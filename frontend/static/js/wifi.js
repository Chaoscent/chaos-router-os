window.Page = window.Page || {};

window.Page.wifi = {

    timer: null,
    data: null,
    securityBefore6: null,

    // The radio whose network the form shows, e.g. "wlan0".
    selected: null,

    selects: [
        "wifiEnabledInput",
        "wifiInterfaceInput",
        "wifiHiddenInput",
        "wifiSecurityInput",
        "wifiBandInput",
        "wifiChannelInput",
        "wifiIsolateInput"
    ],


    escape(value) {

        return ChaosSelect.escape(value);

    },


    async request(url, options = {}) {

        const res = await fetch(url, options);

        if (res.status === 401) {
            location.href = "/login";
            return null;
        }

        try {
            return { ok: res.ok, data: await res.json() };
        } catch {
            return { ok: false, data: { message: "Unexpected server response." } };
        }

    },


    post(url, body) {

        return this.request(url, {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify(body ?? {})

        });

    },


    // ------------------------------------------------------------
    // Load / render
    // ------------------------------------------------------------

    async load() {

        const res = await this.request("/api/wifi");

        if (!res) return;

        if (!res.ok) {
            wifiStatus.textContent = "Failed to load WiFi settings.";
            return;
        }

        this.data = res.data;

        const names = Object.keys(this.data.networks);

        // Keep the radio being edited; otherwise the first one that is on.
        if (!names.includes(this.selected)) {
            this.selected =
                names.find(name => this.data.networks[name].enabled) || names[0] || null;
        }

        this.renderSettings();
        this.renderStatus();

        await this.loadClients();

    },


    /** The selected radio's network, or null without radios. */
    network() {

        return this.data?.networks?.[this.selected] ?? null;

    },


    renderStatus() {

        const network = this.network();

        if (!network) {
            wifiState.textContent = "No radio";
            wifiServiceState.textContent = "--";
            wifiChannelState.textContent = "--";
            return;
        }

        const running = this.data.status.running?.[this.selected] === true;

        wifiState.textContent = !network.enabled
            ? "Off"
            : running ? "Broadcasting" : "Not running";

        wifiServiceState.textContent =
            running ? "Running" : "Stopped";

        wifiChannelState.textContent =
            `${network.band} GHz / ${network.channel}`;

    },


    renderSettings() {

        const { networks, interfaces } = this.data;
        const settings = this.network();

        // Every radio with its network: "wlan0 · Chaos Router (on)".
        wifiInterfaceInput.innerHTML = "";

        Object.values(networks).forEach(network => {

            const option = document.createElement("option");
            option.value = network.interface;
            option.textContent =
                `${network.interface} · ` +
                (network.enabled ? `${network.ssid} (on)` : "off") +
                (interfaces.includes(network.interface) ? "" : " (not plugged in)");
            wifiInterfaceInput.appendChild(option);

        });

        if (!settings) {
            wifiStatus.textContent = "No Wi-Fi radio found.";
            wifiSave.disabled = true;
            return;
        }

        wifiSave.disabled = false;

        wifiEnabledInput.value = String(settings.enabled);
        wifiInterfaceInput.value = this.selected;
        wifiHiddenInput.value = String(settings.hidden);
        wifiSsidInput.value = settings.ssid;
        wifiSecurityInput.value = settings.security;
        wifiPasswordInput.value = settings.password || "";
        wifiBandInput.value = settings.band;
        wifiCountryInput.value = this.data.country || "";
        wifiIsolateInput.value = String(settings.isolate_clients);
        wifiAddressInput.value = settings.address || "";
        wifiPrefixInput.value = settings.prefix ?? "";

        this.updateAddressState();

        this.renderBands();
        this.renderChannels(settings.channel);
        this.updateSecurityState();
        this.updatePasswordState();

        this.selects.forEach(id => {
            ChaosSelect.refresh(document.getElementById(id));
        });

    },


    // Channels per band the selected radio supports,
    // or null when the backend could not detect them.
    getSupport() {

        return this.data.options.support?.[wifiInterfaceInput.value] ?? null;

    },


    // Grey out bands the radio lacks (e.g. 6 GHz on the Pi's own Wi-Fi).
    renderBands() {

        const support = this.getSupport();

        [...wifiBandInput.options].forEach(option => {

            const unsupported = support !== null && !support[option.value]?.length;

            option.disabled = unsupported;
            option.textContent = `${option.value} GHz` +
                (unsupported ? " (not supported)" : "");

        });

        ChaosSelect.refresh(wifiBandInput);

    },


    // Channel list depends on the selected band and radio.
    renderChannels(selected) {

        const band = this.data.options.bands[wifiBandInput.value];
        const psc = this.data.options.psc_channels || [];
        const support = this.getSupport()?.[wifiBandInput.value];

        // Fall back to every channel when the radio can't be queried.
        const channels = support?.length ? support : band.channels;

        const fallback = channels.includes(band.default)
            ? band.default
            : channels[0];

        wifiChannelInput.innerHTML = "";

        channels.forEach(channel => {

            const option = document.createElement("option");
            option.value = String(channel);

            if (channel === band.default) {
                option.textContent = `${channel} (recommended)`;
            } else if (wifiBandInput.value === "6" && psc.includes(channel)) {
                option.textContent = `${channel} (PSC)`;
            } else {
                option.textContent = String(channel);
            }

            wifiChannelInput.appendChild(option);

        });

        wifiChannelInput.value = channels.includes(Number(selected))
            ? String(selected)
            : String(fallback);

        ChaosSelect.refresh(wifiChannelInput);

    },


    // 6 GHz only allows WPA3. Restore the previous choice when leaving it.
    updateSecurityState() {

        const sixGhz = wifiBandInput.value === "6";

        if (sixGhz && wifiSecurityInput.value !== "wpa3") {
            this.securityBefore6 = wifiSecurityInput.value;
            wifiSecurityInput.value = "wpa3";
        }

        if (!sixGhz && this.securityBefore6) {
            wifiSecurityInput.value = this.securityBefore6;
            this.securityBefore6 = null;
        }

        wifiSecurityInput.disabled = sixGhz;

        ChaosSelect.refresh(wifiSecurityInput);

        this.updatePasswordState();

    },


    updatePasswordState() {

        const open = wifiSecurityInput.value === "open";

        wifiPasswordInput.disabled = open;
        wifiPasswordToggle.disabled = open;

        wifiPasswordInput.placeholder = open
            ? "Not used for open networks"
            : "8-63 characters";

    },


    togglePassword() {

        const show = wifiPasswordInput.type === "password";

        wifiPasswordInput.type = show ? "text" : "password";
        wifiPasswordToggle.textContent = show ? "Hide" : "Show";

    },


    async loadClients() {

        const res = await this.request("/api/wifi/clients");

        if (!res || !res.ok) return;

        const clients = res.data;

        wifiClientCount.textContent = clients.length;

        // One column more than before: the radio.
        const columns = 6;

        wifiClientTable.innerHTML = "";

        if (!clients.length) {

            wifiClientTable.innerHTML = `
                <tr class="empty-row">
                    <td colspan="${columns}">No wireless clients connected.</td>
                </tr>
            `;

            return;
        }

        clients.forEach(client => {

            const row = document.createElement("tr");

            row.innerHTML = `
                <td>
                    <strong>${this.escape(client.hostname) || "Unknown"}</strong><br>
                    <small>${this.escape(client.mac)}</small>
                </td>
                <td>${this.escape(client.interface || "")}</td>
                <td>${this.escape(client.ip) || "—"}</td>
                <td>${client.signal === null ? "—" : `${client.signal} dBm`}</td>
                <td>${this.formatDuration(client.connected)}</td>
                <td>
                    <small>↓ ${this.formatBytes(client.tx_bytes)}
                    · ↑ ${this.formatBytes(client.rx_bytes)}</small>
                </td>
            `;

            wifiClientTable.appendChild(row);

        });

    },


    formatDuration(seconds) {

        if (seconds === null || seconds === undefined) return "—";

        const d = Math.floor(seconds / 86400);
        const h = Math.floor(seconds % 86400 / 3600);
        const m = Math.floor(seconds % 3600 / 60);

        if (d) return `${d}d ${h}h`;
        if (h) return `${h}h ${m}m`;
        return `${m}m`;

    },


    formatBytes(bytes) {

        const units = ["B", "KB", "MB", "GB", "TB"];

        let value = bytes || 0;
        let i = 0;

        while (value >= 1024 && i < units.length - 1) {
            value /= 1024;
            i++;
        }

        return `${value.toFixed(i ? 1 : 0)} ${units[i]}`;

    },


    // ------------------------------------------------------------
    // Save
    // ------------------------------------------------------------

    /** "10.42.0.1" + 24 -> "10.42.0.0/24", or null when invalid. */
    clientNetwork(address, prefix) {

        const parts = String(address).split(".").map(Number);

        if (parts.length !== 4 || parts.some(p => !Number.isInteger(p) || p < 0 || p > 255))
            return null;

        if (!Number.isInteger(prefix) || prefix < 8 || prefix > 30)
            return null;

        const ip = parts.reduce((a, p) => a * 256 + p, 0);
        const size = 2 ** (32 - prefix);
        const base = Math.floor(ip / size) * size;

        const network = [24, 16, 8, 0].map(s => Math.floor(base / 2 ** s) % 256).join(".");

        return `${network}/${prefix}`;

    },

    /** Interface name in the label, live network, bridged state. */
    updateAddressState() {

        const bridged = this.data?.bridged?.[this.selected] === true;
        const iface = this.selected || "the access point";

        wifiAddressInterface.textContent = iface;

        wifiAddressInput.disabled = bridged;
        wifiPrefixInput.disabled = bridged;

        const network = this.clientNetwork(wifiAddressInput.value.trim(), Number(wifiPrefixInput.value));

        wifiNetworkInfo.textContent = bridged ? "LAN bridge (br0)" : (network || "--");

        wifiAddressHint.textContent = bridged
            ? `${iface} is a port of the LAN bridge: the access point joins br0 and uses the LAN address from the Network page.`
            : network
                ? `Wi-Fi clients reach the router at ${wifiAddressInput.value.trim()}. When the access point is on, DHCP serves ${iface} in ${network} by itself (DHCP page).`
                : "Enter the router's address and prefix, e.g. 10.42.0.1 and 24.";

    },


    collectSettings() {

        return {

            enabled: wifiEnabledInput.value === "true",

            interface: this.selected,

            hidden: wifiHiddenInput.value === "true",

            ssid: wifiSsidInput.value,

            security: wifiSecurityInput.value,

            password: wifiPasswordInput.value,

            band: wifiBandInput.value,

            channel: Number(wifiChannelInput.value),

            country: wifiCountryInput.value.trim().toUpperCase(),

            isolate_clients: wifiIsolateInput.value === "true",

            address: wifiAddressInput.value.trim(),

            prefix: Number(wifiPrefixInput.value)

        };

    },


    async save() {

        const settings = this.collectSettings();

        // Wireless clients drop briefly while hostapd restarts.
        const confirmed = await ChaosModal.confirm({

            title: `Apply WiFi Settings (${settings.interface})`,

            subtitle: settings.enabled
                ? `Devices on ${settings.interface} will disconnect briefly while the access points restart.`
                : `The access point on ${settings.interface} will be turned off and its devices will disconnect.`,

            confirmText: "Apply"

        });

        if (!confirmed) return;

        wifiSave.disabled = true;
        wifiStatus.textContent = "Applying...";

        const res = await this.post("/api/wifi/settings", settings);

        wifiSave.disabled = false;

        if (!res) return;

        const data = res.data;

        if (data.networks) {

            // Status may have changed after restarting hostapd.
            await this.load();

        }

        wifiStatus.textContent = data.success
            ? `✓ ${data.message}`
            : data.message || "Failed to save.";

        if (!wifiConfigPreview.classList.contains("hidden")) {
            this.preview();
        }

    },


    async preview() {

        const res = await this.post(
            "/api/wifi/preview",
            this.collectSettings()
        );

        if (!res) return;

        if (!res.ok) {
            wifiStatus.textContent = res.data.message;
            wifiConfigPreview.classList.add("hidden");
            return;
        }

        wifiConfigPreview.textContent = res.data.config;
        wifiConfigPreview.classList.remove("hidden");

    },


    init() {

        this.selects.forEach(id => {
            ChaosSelect.enhance(document.getElementById(id));
        });

        wifiBandInput.onchange = () => {
            this.renderChannels(wifiChannelInput.value);
            this.updateSecurityState();
        };

        // Another radio: show its network.
        wifiInterfaceInput.onchange = () => {
            this.selected = wifiInterfaceInput.value;
            this.securityBefore6 = null;
            this.renderSettings();
            this.renderStatus();
            wifiStatus.textContent = "";
            wifiConfigPreview.classList.add("hidden");
        };

        wifiAddressInput.oninput = () => this.updateAddressState();
        wifiPrefixInput.oninput = () => this.updateAddressState();

        wifiSecurityInput.onchange = () => this.updatePasswordState();

        wifiPasswordToggle.onclick = () => this.togglePassword();

        wifiCountryInput.oninput = () => {
            wifiCountryInput.value = wifiCountryInput.value.toUpperCase();
        };

        wifiSave.onclick = () => this.save();

        wifiPreview.onclick = () => this.preview();

        this.load();

        this.timer = setInterval(() => this.loadClients(), 10000);

    },


    destroy() {

        clearInterval(this.timer);
        this.timer = null;

        ChaosModal.close();

    }

};
