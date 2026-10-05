/*
 * First-time setup wizard (/setup): admin account, Wi-Fi, finish.
 * Nothing is saved until the last step; the server checks everything
 * again and applies it in one go.
 */

const Setup = {

    step: 1,

    info: null,

    // Common countries first by name; any two-letter code is valid.
    COUNTRIES: [
        ["AT", "Austria"], ["AU", "Australia"], ["BE", "Belgium"], ["BR", "Brazil"],
        ["CA", "Canada"], ["CH", "Switzerland"], ["CN", "China"], ["CZ", "Czechia"],
        ["DE", "Germany"], ["DK", "Denmark"], ["ES", "Spain"], ["FI", "Finland"],
        ["FR", "France"], ["GB", "United Kingdom"], ["GR", "Greece"], ["HR", "Croatia"],
        ["HU", "Hungary"], ["IE", "Ireland"], ["IN", "India"], ["IT", "Italy"],
        ["JP", "Japan"], ["KR", "South Korea"], ["LU", "Luxembourg"], ["MX", "Mexico"],
        ["NL", "Netherlands"], ["NO", "Norway"], ["NZ", "New Zealand"], ["PL", "Poland"],
        ["PT", "Portugal"], ["RO", "Romania"], ["SE", "Sweden"], ["SG", "Singapore"],
        ["SI", "Slovenia"], ["SK", "Slovakia"], ["TR", "Türkiye"], ["UA", "Ukraine"],
        ["US", "United States"], ["ZA", "South Africa"]
    ],

    $(id) {
        return document.getElementById(id);
    },


    // ------------------------------------------------------------
    // Steps
    // ------------------------------------------------------------

    show(step) {

        this.step = step;

        document.querySelectorAll(".setup-step").forEach(el => {
            el.classList.toggle("hidden", el.dataset.step !== String(step));
        });

        document.querySelectorAll(".setup-steps li").forEach(li => {
            const n = Number(li.dataset.step);
            li.classList.toggle("active", n === step);
            li.classList.toggle("done", step === "done" || n < step);
        });

        this.error("");

        const done = step === "done";

        this.$("setupBack").classList.toggle("hidden", step === 1 || done);
        this.$("setupNext").classList.toggle("hidden", done);
        this.$("setupNext").textContent = step === 3 ? "Finish Setup" : "Next";

        if (step === 3) this.renderSummary();

        // Focus the first field for keyboard users.
        document.querySelector(`.setup-step[data-step="${step}"] input:not([type=checkbox])`)?.focus();

    },

    error(message) {

        const box = this.$("setupError");

        box.textContent = message;
        box.classList.toggle("hidden", !message);

    },


    // ------------------------------------------------------------
    // Validation (the server checks the same again)
    // ------------------------------------------------------------

    checkAccount() {

        const username = this.$("setupUsername").value.trim();
        const password = this.$("setupPassword").value;

        if (!/^[A-Za-z0-9_.-]{1,32}$/.test(username))
            return "Username: 1-32 letters, numbers, dots, dashes or underscores.";

        if (password.length < 8)
            return "The password needs at least 8 characters.";

        if (password !== this.$("setupPasswordConfirm").value)
            return "The passwords do not match.";

        return null;

    },

    wifiEnabled() {

        return this.info.wifi.available && this.$("setupWifiEnabled").checked;

    },

    checkWifi() {

        if (!this.wifiEnabled()) return null;

        const ssid = this.$("setupSsid").value;
        const password = this.$("setupWifiPassword").value;

        if (!ssid.trim())
            return "Enter a network name.";

        if (new TextEncoder().encode(ssid).length > 32)
            return "The network name is too long (max 32 bytes).";

        if (!/^[\x20-\x7e]{8,63}$/.test(password))
            return "The Wi-Fi password needs 8-63 characters (letters, numbers, symbols, spaces).";

        return null;

    },


    // ------------------------------------------------------------
    // Review / finish
    // ------------------------------------------------------------

    renderSummary() {

        const rows = [
            ["Admin account", this.$("setupUsername").value.trim()],
            ["Wi-Fi", this.wifiEnabled()
                ? `${this.$("setupSsid").value} (WPA2, ${this.$("setupCountry").value})`
                : "Not now"]
        ];

        const summary = this.$("setupSummary");

        summary.innerHTML = "";

        for (const [label, value] of rows) {

            const row = document.createElement("div");
            row.className = "info-row";

            const l = document.createElement("span");
            l.textContent = label;

            const v = document.createElement("strong");
            v.textContent = value;

            row.append(l, v);
            summary.appendChild(row);

        }

        const reconnect = this.$("setupReconnect");

        const viaSetupWifi = this.info.via_setup_wifi;

        reconnect.textContent =
            this.wifiEnabled()
                ? viaSetupWifi
                    ? `This device will lose the setup Wi-Fi when "${this.$("setupSsid").value}" starts. Join that network, then open ${this.dashboardUrl()}.`
                    : `Devices on the setup Wi-Fi need to join "${this.$("setupSsid").value}" afterwards.`
                : viaSetupWifi
                    ? "This device is on the setup Wi-Fi, which turns off after setup. Connect it with an Ethernet cable to reach the dashboard, or go back and set up Wi-Fi now."
                    : "";

        reconnect.classList.toggle("hidden", !reconnect.textContent);

    },

    async finish() {

        const next = this.$("setupNext");

        next.disabled = true;
        next.textContent = "Setting up…";

        this.error("");

        const wifi = this.wifiEnabled() ? {
            enabled: true,
            interface: this.info.wifi.interface,
            country: this.$("setupCountry").value,
            ssid: this.$("setupSsid").value,
            password: this.$("setupWifiPassword").value
        } : { enabled: false };

        let res = null;
        let data = {};

        try {

            res = await fetch("/api/setup/complete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    admin: {
                        username: this.$("setupUsername").value.trim(),
                        password: this.$("setupPassword").value
                    },
                    wifi
                })
            });

            data = await res.json();

        } catch {

            // Expected when the Wi-Fi this device uses was just replaced.
            if (this.wifiEnabled()) {
                this.showDone(true);
                return;
            }

            data = { message: "The router did not answer. Try again." };

        }

        next.disabled = false;
        next.textContent = "Finish Setup";

        if (res && res.ok && data.success) {
            this.showDone(false);
            return;
        }

        this.error(data.message || "Setup failed. Try again.");

    },

    /** Where the dashboard is after setup, as seen from this device. */
    dashboardUrl() {

        return this.info.via_setup_wifi ? this.info.dashboard_url : `${location.origin}/`;

    },

    showDone(lostConnection) {

        const ssid = this.$("setupSsid").value;
        const url = this.dashboardUrl();

        this.$("setupDoneText").textContent = lostConnection || (this.info.via_setup_wifi && this.wifiEnabled())
            ? `The new Wi-Fi "${ssid}" is starting. Connect to it, then open ${url} and sign in.`
            : this.wifiEnabled()
                ? `Wi-Fi "${ssid}" is on. Devices on the setup Wi-Fi need to join it.`
                : this.info.via_setup_wifi
                    ? `The setup Wi-Fi turns off now. Connect by Ethernet and open the router's address on port ${new URL(url).port}.`
                    : "You are signed in.";

        document.querySelector(".setup-open").href = url;

        this.show("done");

    },


    // ------------------------------------------------------------
    // Init
    // ------------------------------------------------------------

    async next() {

        if (this.step === 1) {

            const problem = this.checkAccount();

            if (problem) return this.error(problem);

            return this.show(2);
        }

        if (this.step === 2) {

            const problem = this.checkWifi();

            if (problem) return this.error(problem);

            return this.show(3);
        }

        if (this.step === 3) return this.finish();

    },

    async init() {

        try {
            this.info = await (await fetch("/api/setup/info")).json();
        } catch {
            this.info = { wifi: { available: false } };
        }

        const wifi = this.info.wifi;

        this.$("setupWifiForm").classList.toggle("hidden", !wifi.available);
        this.$("setupNoWifi").classList.toggle("hidden", wifi.available);

        // Countries, with the configured one selected (added if missing).
        const country = this.$("setupCountry");
        const countries = [...this.COUNTRIES];

        if (wifi.country && !countries.some(([code]) => code === wifi.country)) {
            countries.push([wifi.country, wifi.country]);
        }

        countries.forEach(([code, name]) => {
            const option = document.createElement("option");
            option.value = code;
            option.textContent = `${name} (${code})`;
            country.appendChild(option);
        });

        country.value = wifi.country || "DE";

        ChaosSelect.enhance(country);

        this.$("setupSsid").value = wifi.ssid || "Chaos Router";

        this.$("setupWifiEnabled").onchange = () => {
            this.$("setupWifiFields").classList.toggle("hidden", !this.$("setupWifiEnabled").checked);
        };

        document.querySelectorAll(".setup-show").forEach(button => {
            button.onclick = () => {
                const input = this.$(button.dataset.for);
                const visible = input.type === "text";
                input.type = visible ? "password" : "text";
                button.textContent = visible ? "Show" : "Hide";
            };
        });

        this.$("setupNext").onclick = () => this.next();
        this.$("setupBack").onclick = () => this.show(this.step - 1);

        // An error disappears once the user starts fixing it.
        document.querySelectorAll(".setup-card input").forEach(input => {
            input.addEventListener("input", () => this.error(""));
        });

        // Enter moves on, like a normal form.
        document.addEventListener("keydown", event => {
            if (event.key === "Enter" && event.target.tagName === "INPUT") this.next();
        });

        this.show(1);

    }

};


document.addEventListener("DOMContentLoaded", () => Setup.init());
