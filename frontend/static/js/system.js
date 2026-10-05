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

        pingDestinationInput.value =
            data.destination || "1.1.1.1";

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

        const destination =
            pingDestinationInput.value.trim();

        if (![5, 10, 30, 60].includes(interval)) {

            pingStatus.textContent =
                "Invalid ping interval.";

            return;
        }

        if (!destination) {

            pingStatus.textContent =
                "Ping destination cannot be empty.";

            return;
        }

        const res = await fetch("/api/system/ping", {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({
                enabled: enabled,
                interval: interval,
                destination: destination
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


    // ------------------------------------------------------------
    // Backup & Restore
    // ------------------------------------------------------------

    backupText: null,
    backupSummary: null,


    escape(value) {

        return ChaosSelect.escape(value);

    },


    async downloadBackup() {

        backupStatus.textContent = "Preparing backup...";

        const res = await fetch("/api/backup/export");

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        if (!res.ok) {
            backupStatus.textContent = "The backup could not be created.";
            return;
        }

        const disposition = res.headers.get("Content-Disposition") || "";
        const name = disposition.match(/filename="([^"]+)"/)?.[1]
            || "chaos-router-backup.json";

        const link = document.createElement("a");

        link.href = URL.createObjectURL(await res.blob());
        link.download = name;
        link.click();

        URL.revokeObjectURL(link.href);

        backupStatus.textContent = `✓ Downloaded ${name}`;

    },


    async postBackup(url, body) {

        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        });

        if (res.status === 401) {
            location.href = "/login";
            return null;
        }

        if (res.status === 413) {
            return { success: false, message: "The file is too large to be a backup." };
        }

        try {
            return await res.json();
        } catch {
            return { success: false, message: "Unexpected server response." };
        }

    },


    readBackupFile(file) {

        if (!file) return;

        backupFileInput.value = "";
        backupResults.classList.add("hidden");
        backupSummary.classList.add("hidden");
        backupStatus.textContent = `Reading ${file.name}...`;

        const reader = new FileReader();

        reader.onload = () => this.inspectBackup(reader.result, file.name);
        reader.onerror = () => {
            backupStatus.textContent = "The file could not be read.";
        };

        reader.readAsText(file);

    },


    async inspectBackup(text, fileName) {

        const data = await this.postBackup("/api/backup/inspect", { backup: text });

        if (!data) return;

        if (!data.success) {
            backupStatus.textContent = data.message;
            return;
        }

        this.backupText = text;
        this.backupSummary = data;

        const created = data.created
            ? new Date(data.created * 1000).toLocaleString()
            : "an unknown date";

        backupInfo.textContent =
            `${fileName}: backup of ${data.hostname || "a router"} from ${created}.`;

        backupAreas.innerHTML = "";

        data.areas.forEach(area => {

            const label = document.createElement("label");
            label.className = `check-item backup-area ${area.status}`;

            const note = {
                ok: "",
                unchanged: "same as now",
                invalid: area.message
            }[area.status];

            label.innerHTML = `
                <input type="checkbox" value="${this.escape(area.name)}"
                    ${area.status === "ok" ? "checked" : ""}
                    ${area.status === "invalid" ? "disabled" : ""}>
                <span>${this.escape(area.label)}</span>
                ${note ? `<small>${this.escape(note)}</small>` : ""}
            `;

            backupAreas.appendChild(label);

        });

        backupCerts.textContent =
            data.certificates === "ok"
                ? "Includes the OpenVPN certificate authority; restoring OpenVPN replaces this router's certificates."
                : data.certificates
                    ? `OpenVPN certificates cannot be used: ${data.certificates}`
                    : "";

        backupSummary.classList.remove("hidden");
        backupStatus.textContent = "Choose what to restore.";

    },


    async restoreBackup() {

        const areas = [...backupAreas.querySelectorAll("input:checked")]
            .map(input => input.value);

        if (!areas.length) {
            backupStatus.textContent = "Select at least one area to restore.";
            return;
        }

        const labels = this.backupSummary.areas
            .filter(a => areas.includes(a.name))
            .map(a => a.label);

        const body = document.createElement("div");

        const warnings = [];

        if (areas.includes("users")) {
            warnings.push("The login password changes to the one in the backup.");
        }

        if (areas.includes("openvpn") && this.backupSummary.certificates === "ok") {
            warnings.push("OpenVPN devices set up on this router stop working; use the profiles from the backup.");
        }

        warnings.push("Network, firewall, WiFi and similar settings wait for you to keep them, or revert automatically.");

        body.innerHTML = `
            <p class="modal-note">${labels.map(l => this.escape(l)).join(", ")}</p>
            <ul class="modal-list">
                ${warnings.map(w => `<li>${this.escape(w)}</li>`).join("")}
            </ul>
        `;

        const confirmed = await ChaosModal.confirm({
            title: "Restore Backup",
            subtitle: "These settings are replaced with the ones from the backup:",
            body: body,
            confirmText: "Restore"
        });

        if (!confirmed) return;

        backupRestore.disabled = true;
        backupStatus.textContent = "Restoring...";

        const data = await this.postBackup("/api/backup/restore", {
            backup: this.backupText,
            areas: areas
        });

        backupRestore.disabled = false;

        if (!data) return;

        backupStatus.textContent = data.message;

        backupResults.innerHTML = "";

        (data.areas || []).forEach(area => {

            const item = document.createElement("li");
            item.className = area.success ? "ok" : "failed";
            item.textContent = `${area.success ? "✓" : "✕"} ${area.label}: ${area.message}`;
            backupResults.appendChild(item);

        });

        backupResults.classList.toggle("hidden", !(data.areas || []).length);
        backupSummary.classList.add("hidden");

        this.backupText = null;

        // Restored hostname, timeouts and ping settings show up here.
        this.load();

    },


    // ------------------------------------------------------------
    // Reboot
    // ------------------------------------------------------------

    async reboot() {

        // A reboot reverts changes that wait for confirmation.
        const pending = window.ChaosApply?.pending;

        const confirmed = await ChaosModal.confirm({
            title: "Reboot the router?",
            subtitle: pending
                ? "Unconfirmed changes (" + pending.areas.map(a => a.label).join(", ") + ") will be reverted. Devices lose their connection for about a minute."
                : "Devices lose their connection for about a minute.",
            confirmText: "Reboot"
        });

        if (!confirmed) return;

        rebootButton.disabled = true;
        rebootStatus.textContent = "Rebooting...";

        let data = {};

        try {

            const res = await fetch("/api/system/reboot", { method: "POST" });

            data = await res.json();

            if (!res.ok || !data.success) {
                rebootButton.disabled = false;
                rebootStatus.textContent = data.message || "The router could not be rebooted.";
                return;
            }

        } catch {
            // The router may already be going down.
        }

        this.waitForRouter();

    },

    /** Waits until the router is gone and back, then reloads. */
    async waitForRouter() {

        const started = Date.now();
        let wentDown = false;

        const sleep = ms => new Promise(r => setTimeout(r, ms));

        while (Date.now() - started < 5 * 60 * 1000) {

            await sleep(3000);

            const seconds = Math.round((Date.now() - started) / 1000);

            let up = false;

            try {
                const res = await fetch("/login", { cache: "no-store" });
                up = res.ok || res.redirected;
            } catch {
                up = false;
            }

            if (!up) wentDown = true;

            // Back after going down (or still up after 40 s: reloaded fast).
            if (up && (wentDown || seconds > 40)) {
                rebootStatus.textContent = "The router is back. Reloading...";
                await sleep(1000);
                location.href = "/";
                return;
            }

            rebootStatus.textContent = wentDown
                ? `Rebooting... waiting for the router (${seconds} s)`
                : `Rebooting... (${seconds} s)`;

        }

        rebootStatus.textContent =
            "The router has not come back after 5 minutes. Check its power and network, then reload this page.";

    },


    cancelRestore() {

        this.backupText = null;
        this.backupSummary = null;

        backupSummary.classList.add("hidden");
        backupStatus.textContent = "";

    },


    init() {

        this.load();

        backupDownload.onclick = () => this.downloadBackup();
        backupChoose.onclick = () => backupFileInput.click();
        backupFileInput.onchange = () => this.readBackupFile(backupFileInput.files[0]);
        backupRestore.onclick = () => this.restoreBackup();
        backupCancel.onclick = () => this.cancelRestore();


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

        rebootButton.onclick = () => this.reboot();

    },


    destroy() {}

};