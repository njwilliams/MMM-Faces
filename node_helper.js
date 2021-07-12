'use strict';
const NodeHelper = require('node_helper');
const { spawn } = require('child_process');
var procStarted = false

module.exports = NodeHelper.create({
  proc_start: function () {
    const self = this;
    process.env.WERKZEUG_RUN_MAIN = 'true';
    const proc = spawn('modules/' + this.name + '/pi-faced/bin/faced');

    proc.stdout.on('data', (data) => {
	const message = JSON.parse(data);
        if (message.hasOwnProperty('status')){
            console.log("[" + self.name + "] " + message.status);
        }
        if (message.hasOwnProperty('login')){
            self.sendSocketNotification('user', 
            {
                action: "login", 
                user: message.login.names[0]
            });
        }
        if (message.hasOwnProperty('logout')){
            self.sendSocketNotification('user', 
            {
                action: "logout", 
                user: message.logout.names[0]
            });
        }
    });

    proc.on('close', (code) => {
        console.log("[" + self.name + "] finished with code " + code);
    });
  },
  
  // Subclass socketNotificationReceived received.
  socketNotificationReceived: function(notification, payload) {
      if(notification === 'CONFIG') {
          this.config = payload
          if (!procStarted) {
              procStarted = true;
              this.proc_start();
          };
      };
  }
  
});
