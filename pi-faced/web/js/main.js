    var gNameList = [];
    var gEndpoint = "http://192.168.1.99:8081/faceapi/1.0";
    var gVideoTimer = null;

    function setValue(label, value) {
        var thing = document.getElementById(label);
        thing.value = value;
    }
    function setState(label, state) {
        var thing = document.getElementById(label);
        thing.value = state.value;
        thing.className = 'form-control ' + state.goodness;
    }
    function setBool(label, value) {
        var thing = document.getElementById(label);
        if (value == 'yes' || value == '1' || value == 'on' || value == 'true') {
            thing.checked = true;
        } else {
            thing.checked = false;
        }
    }

    // return true if the result of this is that the BACK of the card will be shown.
    // return false if the result of this is that the FRONT of the card will be shown.
    function rotateCard(btn) {
        var $card = $(btn).closest('.card-flip');
        var flipped = $card.hasClass('flipped');
        if (flipped) {
            $card.removeClass("flipped");
            return false;
        } else {
            $card.addClass('flipped');
            return true;
        }
    }
    function rotateFaceCard(btn, name){
        c = document.getElementById('storage');
        if (rotateCard(btn)) {
            c.className = 'canvas-disappear';
            loadFace(name, 0);
        } else {
            c.className = 'canvas-appear';
        }
    }
    function rotateVideoCard(btn) {
        if (rotateCard(btn)) {
            refreshFrame();
            gVideoTimer = setInterval(refreshFrame, 1000);
        } else {
            if (gVideoTimer) {
                clearInterval(gVideoTimer);
            }
            gVideoTimer = null;
        }
    }

    function refreshFrame() {
        var timestamp = new Date().getTime();
        var frame = document.getElementById('videoframe');
        var annotate = "";
        var annotateSwitch = document.getElementById('annotateVideo');
        if (annotateSwitch.checked) {
            annotate = "&annotated=true";
        }
        frame.src = gEndpoint + '/server/frame.jpg?t=' + timestamp + annotate;
    }

    // Get server status
    function serverStatus() {
        fetch(gEndpoint + "/server/status")
        .then(function(response) {
            if (response.status != 200) {
                console.log("failed to get server status (" + response.status + ")");
                return;
            }
            return response.json();
        })
        .then(function(myjson) {
            var opts = {
                angle: 0.35, // The span of the gauge arc
                lineWidth: 0.1, // The line thickness
                radiusScale: 1, // Relative radius
                pointer: {
                  length: 0.6, // // Relative to gauge radius
                  strokeWidth: 0.035, // The thickness
                  color: '#000000' // Fill color
                },
                limitMax: false,     // If false, max value increases automatically if value > maxValue
                limitMin: false,     // If true, the min value of the gauge will be fixed
                colorStart: '#6F6EA0',   // Colors
                colorStop: '#8080DB',    // just experiment with them
                strokeColor: '#EEEEEE',  // to see which ones work best for you
                generateGradient: true,
                highDpiSupport: true,     // High resolution support
                
              };
            var target = document.getElementById('storage'); 
            var gauge = new Donut(target).setOptions(opts); // create sexy gauge!
            gauge.maxValue = myjson.storage + myjson.available; // set max gauge value
            gauge.setMinValue(0);  // Prefer setter over gauge.minValue = 0
            gauge.animationSpeed = 32; // set animation speed (32 is default value)
            gauge.set(myjson.storage);

            setState('cv2-status', myjson.cv2);
            setState('recognizer-status', myjson.recognizer);
            setState('embedder-status', myjson.embedder);
            setState('video-status', myjson.video);
            setState('detector-status', myjson.detector);

            var log = document.getElementById('serverlog');
            log.innerText = myjson.modelLog;
            setValue('fps', myjson.fps);
            setValue('modelTime', myjson.modeltime);
            setValue('videoSource', myjson.config.videosource);
            setValue('rotate', myjson.config.rotate);
            setValue('maxFPS', myjson.config.maxfps);
            setValue('maxFaceStorage', myjson.config.maxfacestorage);
            setBool('recognize', myjson.config.recognize);
            setBool('acceleration', myjson.config.acceleration);
            setValue('loginTime', myjson.config.logintime);
            setBool('captureUnknown', myjson.config.captureunknown);
            setValue('confidence', myjson.config.confidence);
            setBool('annotateVideo', myjson.config.annotatevideo);
            var nameItem = document.getElementById("names");
            while (nameItem.firstChild) {
                nameItem.removeChild(nameItem.firstChild);
            }
            names = myjson.names;
            gNameList = [];
            if (myjson.unknowns > 0) {
                names["unknown"] = myjson.unknowns;
            }
            for (faceName in names) {
                if (faceName != "unknown") {
                    gNameList.push(faceName);
                }
                let li = nameItem.querySelector('#face-name-' + faceName);
                let name = faceName;
                if (!li) {
                    li = document.createElement('button');
                    li.className = 'btn btn-info btn-sm';
                    li.id = 'face-name-' + faceName;
                    li.onclick = function() {
                        rotateFaceCard(li, name);
                    };
                    li.appendChild(document.createTextNode(faceName));
                    nameItem.appendChild(li);
                }
            }
        })
        .catch(function (error) {
            console.log("Error in server status: " + error);
        })
    }


    function loadFace(name, offset) {
        fetch(gEndpoint + "/name/" + name + "?offset=" + offset + "&limit=1")
        .then(function(response) {
            if (response.status != 200) {
                console.log("failed to get server status (" + response.status + ")");
                return;
            }
            return response.json();
        })
        .then(function(myjson) {
            var card = document.getElementById("facedata");
            var bdy = card.querySelector('.card-body');
            while (bdy.firstChild) {
                bdy.removeChild(bdy.firstChild);
            }

            if (myjson.faces.length == 0) {
                bdy.appendChild(document.createTextNode("No more faces to display"));
                if (name == 'unknown') {
                    serverStatus();
                    return;
                }
                bdy.appendChild(document.createElement("br"));
                button = document.createElement('button');
                button.className = 'btn btn-sm btn-danger';
                button.appendChild(document.createTextNode("DELETE USER"));
                button.onclick = function() { delName(button, name); }
                bdy.appendChild(button);
                return;
            }

            var face = myjson.faces[0];
            text = "Taken: " + face.when;
            if ("maybe" in face) {
                text += ". I guessed " + face.maybe + " (" + face.probability + "%)";
            }
            var hdr = card.querySelector('.card-header');
            hdr.textContent = name;

            photo = document.createElement('img');
            photo.setAttribute('height', '300');
            photo.setAttribute('width', 'auto');
            photo.src = face.photo;
            bdy.appendChild(photo)
            cardtext = document.createElement('div');
            cardtext.appendChild(document.createTextNode(text));
            bdy.appendChild(cardtext);

            // LEFT button
            button = document.createElement('button');
            button.className = 'btn btn-sm';
            left = document.createElement("i")
            left.setAttribute("style", "color: white");
            left.className = 'fas fa-arrow-circle-left';
            button.appendChild(left);
            if (offset <= 0) {
                button.onclick = function() { loadFace(name, myjson.total-1); }
            } else { 
                button.onclick = function() { loadFace(name, offset-1); }
            }
            bdy.appendChild(button);

            // ASSIGN buttons
            if (name == "unknown") {
                for (let j = 0, len = gNameList.length; j < len; j++) {
                    button = document.createElement('button');
                    button.className = 'btn btn-info btn-sm';
                    button.onclick = function() {
                        var buttons = card.getElementsByTagName('button')
                        for (b = 0; b < buttons.length; b++) {
                            buttons[b].disabled = true;
                        }
                        fetch(gEndpoint + "/face/" + face.uuid + "/assign/" + gNameList[j],
                        { method: 'POST' }).then(function(){
                            loadFace(name, offset);
                        })
                    }
                    button.appendChild(document.createTextNode(gNameList[j]))
                    bdy.appendChild(button);
                }
            } else {
                button = document.createElement('button');
                button.className = 'btn btn-info btn-sm';
                button.onclick = function() {
                    fetch(gEndpoint + "/face/" + face.uuid + "/assign/" + "unknown",
                    { method: 'POST' }).then(function(){
                        serverStatus();
                        loadFace(name, offset);
                    })
                }
                button.appendChild(document.createTextNode("Unknown"));
                bdy.appendChild(button);
            }

            button = document.createElement('button');
            button.className = 'btn btn-danger btn-sm';
            button.appendChild(document.createTextNode('DELETE'));
            button.onclick = function() {
                var buttons = card.getElementsByTagName('button')
                for (b = 0; b < buttons.length; b++) {
                    buttons[b].disabled = true;
                }
                fetch(gEndpoint + "/face/" + face.uuid,
                { method: 'DELETE' }).then(response => {
                    if (!response.ok) {
                        return Promise.reject(response);
                    }
                    if (offset == myjson.total - 1) {
                        offset = 0;
                    }
                    loadFace(name, offset);
                })
                .catch(error => {
                    console.log("Failed to delete");
                    serverStatus();
                });
            };
            bdy.appendChild(button);

            // RIGHT button
            button = document.createElement('button');
            button.className = 'btn btn-sm';
            right = document.createElement("i")
            right.className = 'fas fa-arrow-circle-right';
            right.setAttribute("style", "color: white");
            button.appendChild(right);
            if (offset >= myjson.total-1) {
                button.onclick = function() { loadFace(name, 0); }
            } else {
                button.onclick = function() { loadFace(name, offset+1); }
            }
            bdy.appendChild(button);
        })
        .catch(function(error) {
            console.log("Error in processing face: " + error)
            serverStatus();
        })
    }

    function buildModel(b) {
        //b = document.getElementById("buildModel");
        b.disabled = true;
        while (b.firstChild) {
            b.removeChild(b.firstChild);
        }
        spin = document.createElement("span")
        spin.className = "spinner-border spinner-border-sm";
        spin.setAttribute("role", "status")
        spin.setAttribute("aria-hidden", "true")
        b.appendChild(spin)
        b.appendChild(document.createTextNode(" Building"))
        fetch(gEndpoint + "/server/rebuild", { method: 'POST'})
        .then(function() {
            b.disabled = false;
            while (b.firstChild) {
                b.removeChild(b.firstChild);
            }
            b.appendChild(document.createTextNode("Build Model"))
            serverStatus();
        })
    }

    function addName(btn) {
        btn.disabled = true;
        newname = document.getElementById('new-name');
        fetch(gEndpoint + "/name/" + newname.value, { method: 'PUT'})
        .then(function() {
            newname.value = "";
            btn.disabled = false;
            serverStatus();
        })
    }

    function delName(btn, name) {
        btn.disabled = true;
        fetch(gEndpoint + "/name/" + name, { method: 'DELETE'})
        .then(function() {
            rotateFaceCard(btn, name);
            serverStatus();
        })
    }

    function setConfig(field) {
        fetch(gEndpoint + "/server/config?key=" + field.id + "&value=" + field.value, {method: 'PATCH'})
        .then(function() {
            serverStatus();
        })
    }
    function setConfigBool(field) {
        fetch(gEndpoint + "/server/config?key=" + field.id + "&value=" + (field.checked?"1":"0"), {method: 'PATCH'})
        .then(function() {
            serverStatus();
        })
    }
    serverStatus();


