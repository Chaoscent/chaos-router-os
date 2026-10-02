window.Page = window.Page || {};

window.Page.system = {

    async load() {

        const res = await fetch("/api/dashboard");

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        const data = await res.json();

        hostnameInput.value = data.hostname;

        await this.loadSecurity();
        await this.loadPing();

    },


    async loadSecurity() {

        const res = await fetch("/api/system/security");

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        const data = await res.json();

        /*
         * Only show a value when a custom value is actually configured.
         * Otherwise the input stays empty and the placeholder shows:
         * "Default: 5 minutes" / "Default: 1 hour".
         *
         * The backend still uses the default values when no custom
         * configuration exists.
         */

        if (
            data.idle_timeout !== null &&
            data.idle_timeout !== undefined
        ) {
            idleTimeoutInput.value =
                Math.floor(data.idle_timeout / 60);
        } else {
            idleTimeoutInput.value = "";
        }

        if (
            data.absolute_timeout !== null &&
            data.absolute_timeout !== undefined
        ) {
            absoluteTimeoutInput.value =
                Math.floor(data.absolute_timeout / 60);
        } else {
            absoluteTimeoutInput.value = "";
        }

    },


    async loadPing() {

        const res = await fetch("/api/system/ping");

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        if (!res.ok) {
            pingStatus.textContent =
                "Failed to load ping settings.";
            return;
        }

        const data = await res.json();

        pingEnabledInput.value =
            data.enabled ? "true" : "false";

        pingIntervalInput.value =
            String(data.interval);

        this.updatePingIntervalState();

    },


    updatePingIntervalState() {

        pingIntervalInput.disabled =
            pingEnabledInput.value !== "true";

    },


    async save() {

        hostnameStatus.textContent = "Saving...";

        const res = await fetch("/api/system/hostname", {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({
                hostname: hostnameInput.value.trim()
            })

        });

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        const data = await res.json();

        if (data.success) {

            hostnameStatus.textContent =
                "✓ Hostname updated";

            if (window.Header?.update) {
                Header.update();
            }

        } else {

            hostnameStatus.textContent =
                data.message;

        }

    },


    async saveSecurity() {

        securityStatus.textContent = "Saving...";

        const idleMinutes = parseInt(
            idleTimeoutInput.value,
            10
        );

        const absoluteMinutes = parseInt(
            absoluteTimeoutInput.value,
            10
        );

        if (
            !Number.isInteger(idleMinutes) ||
            idleMinutes < 1
        ) {

            securityStatus.textContent =
                "Idle timeout must be at least 1 minute.";

            return;
        }

        if (
            !Number.isInteger(absoluteMinutes) ||
            absoluteMinutes < 1
        ) {

            securityStatus.textContent =
                "Absolute timeout must be at least 1 minute.";

            return;
        }

        if (absoluteMinutes < idleMinutes) {

            securityStatus.textContent =
                "Absolute timeout must be greater than idle timeout.";

            return;
        }

        const res = await fetch("/api/system/security", {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({
                idle_timeout: idleMinutes * 60,
                absolute_timeout: absoluteMinutes * 60
            })

        });

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        const data = await res.json();

        if (data.success) {

            securityStatus.textContent =
                "✓ Security settings updated";

        } else {

            securityStatus.textContent =
                data.message ||
                "Failed to save settings.";

        }

    },


    async savePing() {

        pingStatus.textContent = "Saving...";

        const enabled =
            pingEnabledInput.value === "true";

        const interval =
            parseInt(
                pingIntervalInput.value,
                10
            );

        if (![5, 10, 30, 60].includes(interval)) {

            pingStatus.textContent =
                "Invalid ping interval.";

            return;
        }

        const res = await fetch("/api/system/ping", {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({
                enabled: enabled,
                interval: interval
            })

        });

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        const data = await res.json();

        if (data.success) {

            pingStatus.textContent =
                "✓ Ping settings updated";

            this.updatePingIntervalState();

            if (window.Header?.loadPingConfig) {
                Header.loadPingConfig();
            }

        } else {

            pingStatus.textContent =
                data.message ||
                "Failed to save ping settings.";

        }

    },


    async changePassword() {

        passwordStatus.textContent =
            "Changing password...";

        const currentPassword =
            currentPasswordInput.value;

        const newPassword =
            newPasswordInput.value;

        const confirmPassword =
            confirmPasswordInput.value;


        if (
            !currentPassword ||
            !newPassword ||
            !confirmPassword
        ) {

            passwordStatus.textContent =
                "Please fill in all password fields.";

            return;
        }


        if (newPassword !== confirmPassword) {

            passwordStatus.textContent =
                "New passwords do not match.";

            return;
        }


        const res = await fetch(
            "/api/system/password",
            {

                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({
                    current_password:
                        currentPassword,

                    new_password:
                        newPassword
                })

            }
        );


        if (res.status === 401) {
            location.href = "/login";
            return;
        }


        const data = await res.json();


        if (data.success) {

            passwordStatus.textContent =
                "✓ Password changed. Please log in again.";

            currentPasswordInput.value = "";
            newPasswordInput.value = "";
            confirmPasswordInput.value = "";

            setTimeout(() => {
                location.href = "/login";
            }, 1500);

        } else {

            passwordStatus.textContent =
                data.message ||
                "Failed to change password.";

        }

    },


    init() {

        this.load();


        saveHostname.onclick = () => {
            this.save();
        };


        hostnameInput.addEventListener(
            "keydown",
            (e) => {

                if (e.key === "Enter") {
                    this.save();
                }

            }
        );


        saveSecurity.onclick = () => {
            this.saveSecurity();
        };


        pingEnabledInput.addEventListener(
            "change",
            () => {
                this.updatePingIntervalState();
            }
        );


        savePing.onclick = () => {
            this.savePing();
        };


        changePassword.onclick = () => {
            this.changePassword();
        };

    },


    destroy() {}

};