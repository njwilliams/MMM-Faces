import os
import sys
import cv2
from threading import Lock, RLock
import datetime
import collections
import pickle
import json
import configparser
import faceapi
import imutils
import time
import numpy as np
from sklearn.model_selection import GridSearchCV
from sklearn.preprocessing import LabelEncoder
from sklearn.svm import SVC
import logging
import logging.config
import click
from imutils.video import VideoStream


BIN=sys.argv[0]
# An optimized "get me the absolute path for my binary" algo,
# which tries to not actually do any touching of the filesystem
if len(BIN) > 0 and BIN[0] != '/':
    if 'PWD' in os.environ:
        binstat = os.stat(BIN)
        BIN = os.path.join(os.environ['PWD'], sys.argv[0])
        newstat = os.stat(BIN)
        if binstat.st_ino != newstat.st_ino:
            BIN = os.path.realpath(sys.argv[0])
if BIN == '':
    BINDIR='.'
else:
    BINDIR = os.path.dirname(BIN)
ETCDIR = os.path.join(BINDIR, "..", "etc")

detector   = None
embedder   = None
recognizer = None
labeller   = None
facelog    = collections.deque(maxlen=20)
vs         = None
Frame      = None
FramePlus  = None
config     = None
configLock = RLock()
recogLock  = Lock()
videoLock  = Lock()
status     = dict()

def init_status():
    global status
    status["video"] = "not started"
    status["embedder"] = "not started"
    status["recognizer"] = "not started"
    status["detector"] = "not started"

# A filter to (try) remove ANSI color sequences from flask messages (sigh, why is that forced?)
class FaceLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record and record.msg and isinstance(record.msg, str):
            record.msg = click.unstyle(record.msg)
        return True
    pass

# A log handler that just stashes the logs for later output
class FaceLogHandler(logging.StreamHandler):
    def __init__(self):
        logging.StreamHandler.__init__(self)
    
    def emit(self, record):
        global facelog
        msg = self.format(record)
        facelog.append(msg)

def configureLogging():
    #handler = FaceLogHandler()
    #logging.getLogger('').addHandler(handler)

    logging.config.dictConfig({
    'version': 1,
    'formatters': {'default': {
        'format': '[%(asctime)s]: %(message)s'
    }},
    'handlers': {'wsgi': {
        'class': 'faceutils.FaceLogHandler',
        'formatter': 'default'
    }},
    'root': {
        'level': 'INFO',
        'handlers': ['wsgi']
    }
    })
    #logging.getLogger('').addFilter(FaceLogFilter)


def get_config(*args):
    global config, configLock
    with configLock:
        if config is None:
            config = configparser.ConfigParser()
            config.read(os.path.join(ETCDIR, "faces.defaults.ini"))
            # This is recursive, but we have head recursion to bottom us out
            p = get_config("Storage", "directory")
            if not os.path.isdir(p):
                os.mkdir(p)
                os.mkdir(os.path.join(p, "images"))
                os.mkdir(os.path.join(p, "images", "unknown"))
                os.mkdir(os.path.join(p, "model"))
            config.read(get_path("faces.ini"))

    if len(args) >= 2:
        return config[args[0]][args[1]]
    elif len(args) == 1:
        return config[args[0]]
    else:
        return config

def set_config(section, key, value):
    global config
    prev = config[section][key]
    try:
        config[section][key] = value
        write_config()
    except:
        config[section][key] = prev
        raise

    if section == 'Video' and key.lower() not in ('maxfps', 'annotatevideo'):
        # if the video config has changed, then reset our camera
        init_video()
    if section == 'Recognition':
        init_recognition()

def get_path(*extrapaths):
    paths = [ get_config("Storage", "directory") ]
    paths.extend(extrapaths)
    return os.path.join(*paths)

def write_config():
    global config, configLock
    with configLock:
        fd = open(get_path("faces.ini"), "w")
        config.write(fd)

def verbose(msg):
    logging.info(msg)
    #facelog.append("%s: %s" % (datetime.datetime.fromtimestamp(time.time()).strftime("%Y-%m-%dT%H:%M:%S"), msg))

def printjson(type, message):
    print(json.dumps({type: message}))
    sys.stdout.flush()

def init_video():
    global vs, videoLock
    set_status("video", "initializing...")
    with videoLock:
        if vs is not None:
            vs.stop()
            time.sleep(1)
        
        video = get_config("Video", "videoSource")
        logging.info("starting video stream from " + video)
        try:
            if video == "pi":
                vs = VideoStream(usePiCamera=True, rotation=get_config("Video").getint("rotate")).start()
            elif video.isdigit():
                vs = VideoStream(src=get_config("Video").getint("videoSource")).start()
            else:
                vs = VideoStream(src=video).start()
            set_status("video", "ready")
        except Exception as e:
            set_status("video", "failed")
            logging.error("video failed: %s" % e)
            vs = None

def get_new_frame():
    global vs, Frame
    if vs is not None:
        with videoLock:
            Frame = vs.read()
        return Frame
    return None

def set_status(key, value):
    global status
    status[key] = value

def get_status():
    global status
    return status

def update_annotated_frame(frame):
    global FramePlus
    FramePlus = frame

def get_latest_frame():
    global Frame
    return Frame

def get_annotated_frame():
    global FramePlus
    return FramePlus

def init_recognition():
    global ETCDIR
    global detector
    global recognizer
    global embedder
    global labeller
    acceleration = get_config("Recognition").getboolean("acceleration")

    with recogLock:
            protoPath = os.path.join(ETCDIR, "face_detection_model", "deploy.prototxt")
            modelPath = os.path.join(ETCDIR, "face_detection_model", "res10_300x300_ssd_iter_140000.caffemodel")
            set_status("detector", "starting...")
            # the detector runs on every frame, looking for faces, so this is the bit
            # that needs to be the fastest.
            detector = cv2.dnn.readNetFromCaffe(protoPath, modelPath)
            if acceleration:
                try:
                    detector.setPreferableTarget(cv2.dnn.DNN_TARGET_MYRIAD)
                    set_status("detector", "ready, accelerated")
                except Exception as e:
                    logging.info("fallback to CPU, since failed to activate myriad (%s)" % e)
                    detector.setPreferableTarget(cv2.dnn.DNN_BACKEND_OPENCV)
            else:
                detector.setPreferableTarget(cv2.dnn.DNN_BACKEND_OPENCV)
            set_status("detector", "ready")

            set_status("embedder", "starting...")
            modelPath = os.path.join(ETCDIR, "face_embedding_model/openface_nn4.small2.v1.t7")
            try:
                embedder = cv2.dnn.readNetFromTorch(modelPath)
                # don't use myriad for this, better to run on CPU, says pyImageSearch
                embedder.setPreferableTarget(cv2.dnn.DNN_BACKEND_OPENCV)
                set_status("embedder", "initialized")
            except Exception as e:
                set_status("embedder", "failed")
                logging.warning("Disabling recognition because embedder failed: %s" % e)
                embedder = None

            if embedder is not None:
                logging.info("loading encodings...")
                recognizer = pickle_read("recognizer")
                set_status("recognizer", "ready")
                labeller   = pickle_read("labels")
                # Warm the embedder. This takes time (more than it takes to warm the picamera)
                logging.info("warming embedder...")
                set_status("embedder", "warming...")
                randomBytes = bytearray(os.urandom(27648))
                flatArray = np.array(randomBytes)
                dummyface = flatArray.reshape(96, 96, 3)
                faceBlob = cv2.dnn.blobFromImage(dummyface, 1.0 / 255, (96, 96), (0, 0, 0), swapRB=True, crop=False)
                embedder.setInput(faceBlob)
                t1 = time.perf_counter()
                vec = embedder.forward()
                t2 = time.perf_counter()
                set_status("embedder", "ready")
                logging.info("dummy embedder run took %fs" % (t2-t1))
            

def rebuild_model():
    global recognizer
    global labeller

    names = faceapi.get_names()
    faces = list()
    embeddings = []
    namelist = []
    logging.info("extracting embeddings")
    set_status("embedder", "rebuilding...")
    t1 = time.perf_counter()
    with recogLock:
            for n in names:
                faces = faceapi.get_faces(n)
                if faces["total"] < 3:
                    logging.warning("skipping %s as there are insufficient faces recorded - need at least 3" % n)
                    continue
                for f in faces["faces"]:
                    face = f.get_cv2img()
                    faceBlob = cv2.dnn.blobFromImage(face, 1.0 / 255, (96, 96), (0, 0, 0), swapRB=True, crop=False)
                    embedder.setInput(faceBlob)
                    vec = embedder.forward()
                    namelist.append(n)
                    embeddings.append(vec.flatten())
            set_status("embedder", "ready")
            
            labeller = LabelEncoder()
            labels = labeller.fit_transform(namelist)
            logging.info("training model")
            # train the model used to accept the 128-d embeddings of the face and
            # then produce the actual face recognition
            params = {"C": [0.001, 0.01, 0.1, 1.0, 10.0, 100.0, 1000.0],
                    "gamma": [1e-1, 1e-2, 1e-3, 1e-4, 1e-5]}
            model = GridSearchCV(SVC(kernel="rbf", gamma="auto", probability=True), params, cv=3, n_jobs=-1)
            model.fit(embeddings, labels)
            set_status("recognizer", "rebuilding...")
            recognizer = model.best_estimator_
            set_status("recognizer", "ready")

    t2 = time.perf_counter()
    pickle_write("recognizer", recognizer)
    pickle_write("labels", labeller)
    logging.info("completed rebuild of model in %.1fs" % (t2-t1))

def pickle_read(name):
    try:
        return pickle.loads(open(get_path("model", name + ".pickle"), "rb").read())
    except:
        return None

def pickle_write(name, content):
    path = get_path("model", name + ".pickle")
    with open(path, "wb") as fd:
        fd.write(pickle.dumps(content))

# Given an image of a single face, see if we can work out
# who it is. The input must be a CV2 image
def recognize_face(face):
    global embedder, recognizer, labeller
    if not embedder or not recognizer or not get_config("Recognition").getboolean("recognize"):
        return "unknown", 0

    with recogLock:
            # construct a blob for the face ROI, then pass the blob
            # through our face embedding model to obtain the 128-d
            # quantification of the face. Note that the embedder
            # on first run takes a long time (~40s on a pi3B+) as the
            # model is built, but subsequent runs are less than 0.1s.
            faceBlob = cv2.dnn.blobFromImage(cv2.resize(face,
                    (96, 96)), 1.0 / 255, (96, 96), (0, 0, 0),
                    swapRB=True, crop=False)
            embedder.setInput(faceBlob)
            t1 = time.perf_counter()
            vec = embedder.forward()
            t2 = time.perf_counter()
            # perform classification to recognize the face
            preds = recognizer.predict_proba(vec)[0]
            j = np.argmax(preds)
            proba = preds[j]
            name = labeller.classes_[j]

    logging.info("recognizer thought %s with probability %d%%" % (labeller.classes_[j], int(proba*100)))
    return name, int(proba*100)

# Given an image, look for faces and return a list of all faces found
# Returns an annotated version of the input frame, with the faces marked
# and a list of names. A face which is found, but not identified will
# be listed as "unknown" in the list of names.
def look_for_faces(frame):
    cfg = get_config("Recognition")
    confidenceThreshold = cfg.getint("confidence") / 100
    captureUnknown      = cfg.getboolean("captureUnknown")

    # resize the frame to have a width of 600 pixels (while
    # maintaining the aspect ratio), and then grab the image
    # dimensions
    frame = imutils.resize(frame, width=600)
    original = frame # Before we annotate, but at the right size
    (h, w) = frame.shape[:2]

    # construct a blob from the image
    imageBlob = cv2.dnn.blobFromImage(
        cv2.resize(frame, (300, 300)), 1.0, (300, 300),
        (104.0, 177.0, 123.0), swapRB=False, crop=False)

    # apply OpenCV's deep learning-based face detector to localize
    # faces in the input image
    detector.setInput(imageBlob)
    try:
        detections = detector.forward()
    except Exception as e:
        logging.error("detector failed: %s" % e)
        return frame, []

    # loop over the detections
    names = []
    for i in range(0, detections.shape[2]):
        # extract the confidence (i.e., probability) associated with
        # the prediction
        confidence = detections[0, 0, i, 2]

        # filter out weak detections
        if confidence < confidenceThreshold:
            continue

        # compute the (x, y)-coordinates of the bounding box for
        # the face
        box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
        (startX, startY, endX, endY) = box.astype("int")

        # extract the face ROI
        face = frame[startY:endY, startX:endX]
        (fH, fW) = face.shape[:2]

        # ensure the face width and height are sufficiently large
        if fW < 20 or fH < 20:
            continue

        name, probability = recognize_face(face)
        if probability < 50:
            name = 'unknown'
        if name == "unknown" and captureUnknown:
            logging.info("capturing unknown face")
            faceapi.add_unknown(face)
        if probability > 0:
            # Provide markup in the frame (after we've saved it, in case it's unknown)
            text = "{}: {:d}%".format(name, probability)
            y = startY - 10 if startY - 10 > 10 else startY + 10
            cv2.rectangle(frame, (startX, startY), (endX, endY),
                                (0, 0, 255), 2)
            cv2.putText(frame, text, (startX, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 2)
        names.append(name)

    return frame, names
