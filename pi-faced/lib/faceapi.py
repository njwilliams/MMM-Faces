
import os
import sys
import datetime
import time
import shutil
import uuid
import faceutils
import cv2
import flask
from flask_cors import CORS
import connexion
import logging
from faceutils import get_path, get_config

BIN=sys.argv[0]
# An optimized "get me the absolute path for my binary" algo,
# which tries to not actually do any touching of the filesystem
if BIN[0] != '/':
    if 'PWD' in os.environ:
        binstat = os.stat(BIN)
        BIN = os.path.join(os.environ['PWD'], sys.argv[0])
        newstat = os.stat(BIN)
        if binstat.st_ino != newstat.st_ino:
            BIN = os.path.realpath(sys.argv[0])

BINDIR = os.path.dirname(BIN)
ETCDIR = os.path.join(BINDIR, "..", "etc")
WEBDIR = os.path.join(BINDIR, "..", "web")
swaggerDir = os.path.join(BINDIR, "..", "etc", "swagger")
cacheTime = time.time()
FPS = 0

NotReady = None
# Give a starting image
with open(os.path.join(ETCDIR, "notready.jpg"), "rb") as fd:
    NotReady = fd.read()

def startAPI():
    global server
    global swaggerDir
    app = connexion.FlaskApp(__name__, specification_dir=swaggerDir,
        server_args = {'static_folder':WEBDIR, 'static_url_path':'/faceui'})
    app.add_api('face-api.yaml')
    CORS(app.app)

    # The UI is served from the API flask server as well...
    @app.route('/')
    def home():
        return flask.redirect('/faceui/index.html', 301)

    # Note: if debug is turned on, then the process will fork and end up with two
    # threads trying to use the video camera at the same time, which will break.
    app.run(port=8081, debug=False)


def get_disk_info():
    free = 0
    used = 0
    for path, dirs, files in os.walk(get_path()):
        for f in files:
            fp = os.path.join(path, f)
            used += os.path.getsize(fp)
    used = int(used/1024)

    sv = shutil.disk_usage(get_path())
    free = int(sv.free / 1024)
    cappedStorage = get_config("Storage").getint("maxFaceStorage") - used
    if cappedStorage < free:
        free = cappedStorage
    return free, used

def status():
    status = faceutils.get_status()
    # We now modify our local copy
    try:
        sb = os.stat(get_path("model", "recognizer.pickle"))
        status["modeltime"] = datetime.datetime.fromtimestamp(sb.st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
    except:
        status["modeltime"] = 0

    status["modelLog"] = "\n".join(faceutils.facelog)
    # We manually look at the unknowns, instead of asking to create/recognize all the faces again
    try:
        status["unknowns"] = len(os.listdir(get_path("images", "unknown")))
    except:
        status["unknowns"] = 0
    status["cachetime"] = datetime.datetime.fromtimestamp(cacheTime).strftime("%Y-%m-%dT%H:%M:%S")
    free, used = get_disk_info()
    status["storage"] = used
    status["available"] = free
    status["names"] = dict()
    for n in get_names():
        status["names"][n] = len(get_faces(n)["faces"])
    status["config"] = dict()
    cfg = faceutils.get_config()
    for sec in cfg.sections(): 
        for k in cfg[sec]:
            status["config"][k] = cfg[sec][k]

    global FPS
    status["fps"] = int(FPS)
    return status

def updateFPS(fps):
    global FPS
    FPS = fps

def set_config(key, value):
    # find the relevant section
    cfg = faceutils.get_config()
    found = None
    for s in cfg.sections():
        if key in cfg[s]:
            found = s
            break
    if found is None:
        return ('No such config item', 404)

    # now do the update
    try:
        faceutils.set_config(found, key, value)
    except Exception as e:
        logging.error("failed to set config: %s" % e)
        return ('Failed to set config', 500)
    return 200

def reset():
    Face.Reset_Cache()
    return 200

def rebuild():
    faceutils.rebuild_model()
    return 200

def get_face(face_id):
    try:
        face = Face.Cache[face_id]
    except KeyError:
        return ('Face Not Found', 404)
    
    path = os.path.join(face.dir, face.filename)
    try:
        st = os.stat(path)
    except Exception as e:
        return ('Face Not Found', 404)
    imgfd = open(os.path.join(face.dir, face.filename), "rb")
    bytes = imgfd.read()
    imgfd.close()
    r = flask.make_response(bytes, 200)
    r.mimetype = 'image/jpeg'
    r.last_modified = st.st_mtime
    return r

def get_frame(t=0, annotated=False):
    frame = None
    if annotated:
        frame = faceutils.get_annotated_frame()
    else:
        frame = faceutils.get_latest_frame()
    if frame is None:
        global NotReady
        r = flask.make_response(NotReady, 503)
        r.mimetype = 'image/jpeg'
        return r
    ret, buf = cv2.imencode('.jpg', frame)
    bytes = buf.tobytes()
    r = flask.make_response(bytes, 200)
    r.mimetype = 'image/jpeg'
    return r

def get_faces(name, offset=0, limit=0):
    dir = get_path("images", name)
    if not os.path.isdir(dir):
        return ('Not found', 404)
    entries = os.listdir(dir)
    ret = dict()
    ret["total"] = len(entries)
    ret["faces"] = list()
    for e in entries:
        if offset > 0:
            offset -= 1
            continue
        ret["faces"].append(Face(name, dir, e))
        if limit > 0 and len(ret) >= limit:
            break
        
    return ret

def get_face_json_by_name(name, offset=0, limit=0):
    dir = get_path("images", name)
    if not os.path.isdir(dir):
        return ('Not found', 404)
    faces = get_faces(name, offset, limit)
    ret = {
        'total': faces["total"],
        'faces': list(map(lambda x: x.summary(), faces["faces"]))
    }
    return ret

def get_unknown_faces(offset=0, limit=0):
    return get_face_json_by_name("unknown", offset, limit)

def get_names():
    dir = get_path("images")
    entries = os.listdir(dir)
    result = list()
    for e in entries:
        if e == 'unknown' or e.startswith('.'):
            continue
        result.append(e)
    return result

def add_name(name):
    dir = get_path("images")
    try:
        os.mkdir(os.path.join(dir, name))
    except Exception as e:
        logging.error("failed to create name: %s" % e)
        return ('Failed to create Name', 500)
    return 200

def del_name(name):
    dir = get_path("images", name)
    try:
        os.rmdir(dir)
    except Exception as e:
        logging.error("failed to delete name: %s" % e)
        return ('Failed to delete name', 500)
    return 200

def assign(face_id, name):
    try:
        face = Face.Cache[face_id]
    except KeyError:
        return ('Face Not Found', 404)
    
    dir = get_path("images", name)
    if not os.path.isdir(dir):
        return ('Name Unknown', 404)

    if face.name == name:
        return face

    face.assign(name)
    return face.summary()

def del_face(face_id):
    try:
        face = Face.Cache[face_id]
    except KeyError:
        return ('Face Not Found', 404)
    try:
        os.remove(os.path.join(face.dir, face.filename))
    except Exception as e:
        logging.error("failed to delete face: %s" % e)
        return ("Failed to delete face", 500)
    del Face.Cache[face_id]
    return 200

def add_unknown(frame):
    ret, buf = cv2.imencode('.jpg', frame)
    bytes = buf.tobytes()

    # Check we have space to store this image
    free, used = get_disk_info()
    if len(bytes) > 1024*free:
        return

    today = datetime.datetime.now()
    # We name the images based on the minute of the day,
    # which allows us to easily throttle to a maximum of
    # one image per minute for a particular user
    dir = get_path("images", "unknown")
    file = today.strftime("%Y%m%d_%H%M") + '.jpg'
    path = os.path.join(dir, file)
    if os.path.exists(path):
        return
    if not os.path.isdir(dir):
        try:
            os.mkdir(dir)
        except Exception as e:
            logging.error("failed to create unknown path %s: %s" % (dir, e))
            return
    
    try:
        with open(path, "wb") as fd:
            fd.write(bytes)
    except Exception as e:
        logging.error("failed to add unknown image %s: %s" % (path, e))
    
    return

class Face():
    Cache = {}

    def Reset_Cache():
        global cacheTime
        Cache = {}
        dir = get_path("images")
        imageentries = os.listdir(dir)
        for i in imageentries:
            if i.startswith("."):
                continue
            if i == 'unknown':
                continue
            idir = os.path.join(dir, i)
            images = os.listdir(idir)
            for img in images:
                if i.startswith("."):
                    continue
                f = Face(i, idir, img)
        cacheTime = time.time()

    def __init__(self, name, dir, filename):
        self.dir = dir
        self.filename = filename
        st = os.stat(os.path.join(dir, filename))
        self.when = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
        self.name = name
        self.maybe = None
        self.probability = 0
        if name == 'unknown':
            frame = self.get_cv2img()
            name, probability = faceutils.recognize_face(frame)
            if name != 'unknown':
                self.maybe = name
                self.probability = probability
 

        # we 'expose' an artificial filename, to force us to always base files
        # inside a data directory, reducing the chance of making a security vulnerability
        self.uuid = uuid.uuid3(uuid.NAMESPACE_URL, 'file://' + name + '/' + filename)
        Face.Cache[str(self.uuid)] = self

    def assign(self, name):
        newdir = get_path("images", name)
        os.rename(os.path.join(self.dir, self.filename), os.path.join(newdir, self.filename))
        self.name = name
        del Face.Cache[str(self.uuid)]
        self.uuid = uuid.uuid3(uuid.NAMESPACE_URL, 'file://' + name + '/' + self.filename)
        Face.Cache[str(self.uuid)] = self

    def get_cv2img(self):
        frame = cv2.imread(os.path.join(self.dir, self.filename))
        return frame

    def summary(self):
        ret = {
            'uuid': str(self.uuid),
            'name': self.name,
            'when': self.when,
            'photo': flask.url_for("/faceapi/1_0.faceapi_get_face", face_id=str(self.uuid), _external=True)
        }
        if self.maybe:
            ret['maybe'] = self.maybe
            ret['probability'] = self.probability
        return ret
