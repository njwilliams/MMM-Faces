/* Magic Mirror Module: MMM-Faces
 *
 * This is a simple stub that translates pi-faced updates
 * into notifications for MMM-ProfileSwitcher.
 *
 * By Nick Williams
 * MIT Licensed.
 */

Module.register('MMM-Faces',{
    defaults: {
        // what profile should we revert to during a logout?
        defaultClass: "default"
    },

    start: function() {
        Log.info('Starting module: ' + this.name);
        this.sendSocketNotification('CONFIG', this.config);
    },

    // Override socket notification handler.
    socketNotificationReceived: function(notification, payload) {
        if (payload.action == "login"){
            this.sendNotification("CURRENT_PROFILE", payload.user);
        } else if (payload.action == "logout") {
            this.sendNotification("CURRENT_PROFILE", this.config.defaultClass);
        }
    }
});
