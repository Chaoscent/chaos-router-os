window.Page = window.Page || {};

window.Page.vpn = {

    timer: null,
    data: null,

    selects: [
        "wgEnabledInput",
        "wgRoutingInput",
        "ovpnEnabledInput",
        "ovpnProtoInput",
        "ovpnRoutingInput",
        "vpnImportTypeInput"
    ],

    TAB_KEY: "chaos-vpn-tab",


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


    send(url, body, method = "POST") {

        return this.request(url, {

            method: method,

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify(body ?? {})

        });

    },


    // Runs an action and shows its message in a status line.
    async run(statusEl, busyText, request) {

        statusEl.textContent = busyText;

        const res = await request();

        if (!res) return false;

        statusEl.textContent = res.data.success
            ? `✓ ${res.data.message}`
            : res.data.message || "Something went wrong.";

        await this.refresh();

        return res.data.success === true || res.data.saved === true;

    },


    // ------------------------------------------------------------
    // Tabs
    // ------------------------------------------------------------

    showTab(tab) {

        document.querySelectorAll(".tab-btn").forEach(btn => {

            const active = btn.dataset.tab === tab;

            btn.classList.toggle("active", active);
            btn.setAttribute("aria-selected", active ? "true" : "false");

        });

        document.querySelectorAll(".tab-panel").forEach(panel => {
            panel.classList.toggle("hidden", panel.dataset.panel !== tab);
        });

        try {
            sessionStorage.setItem(this.TAB_KEY, tab);
        } catch {}

    },


    // ------------------------------------------------------------
    // Load / render
    // ------------------------------------------------------------

    async load() {

        await this.refresh();

        if (!this.data) return;

        this.renderForms();

    },


    // Status and tables only; leaves forms alone while editing.
    async refresh() {

        const res = await this.request("/api/vpn");

        if (!res || !res.ok) return;

        this.data = res.data;

        this.renderStatus();
        this.renderPeers();
        this.renderOpenvpnClients();
        this.renderProfiles();

    },


    serviceState(info) {

        return info.running ? "Running" : "Off";

    },


    renderStatus() {

        const { wireguard, openvpn, profiles } = this.data;

        vpnWgState.textContent = this.serviceState(wireguard);
        vpnOvpnState.textContent = this.serviceState(openvpn);

        vpnRemoteCount.textContent =
            wireguard.peers.filter(p => p.connected).length +
            openvpn.clients.filter(c => c.connected).length;

        const active = profiles.find(p => p.connected);

        vpnClientState.textContent = active ? active.name : "Not connected";

    },


    renderForms() {

        const wg = this.data.wireguard.server;
        const ovpn = this.data.openvpn.server;

        wgEnabledInput.value = String(wg.enabled);
        wgPortInput.value = wg.listen_port;
        wgAddressInput.value = wg.address;
        wgEndpointInput.value = wg.endpoint;
        wgDnsInput.value = wg.dns;
        wgRoutingInput.value = wg.routing;

        wgPublicKeyRow.classList.toggle("hidden", !wg.public_key);
        wgPublicKey.textContent = wg.public_key || "";

        ovpnEnabledInput.value = String(ovpn.enabled);
        ovpnPortInput.value = ovpn.port;
        ovpnProtoInput.value = ovpn.proto;
        ovpnNetworkInput.value = ovpn.network;
        ovpnEndpointInput.value = ovpn.endpoint;
        ovpnDnsInput.value = ovpn.dns;
        ovpnRoutingInput.value = ovpn.routing;

        this.selects.forEach(id => {
            ChaosSelect.refresh(document.getElementById(id));
        });

    },


    emptyRow(table, columns, text) {

        table.innerHTML = `
            <tr class="empty-row">
                <td colspan="${columns}">${text}</td>
            </tr>
        `;

    },


    badge(online, text) {

        return `<span class="status ${online ? "online" : ""}">${this.escape(text)}</span>`;

    },


    renderPeers() {

        const peers = this.data.wireguard.peers;

        wgPeerTable.innerHTML = "";

        if (!peers.length) {
            this.emptyRow(wgPeerTable, 4, "No devices yet.");
            return;
        }

        peers.forEach(peer => {

            const row = document.createElement("tr");

            const seen = peer.last_handshake === null
                ? "Never connected"
                : `Seen ${this.formatDuration(peer.last_handshake)} ago`;

            row.innerHTML = `
                <td>
                    <strong>${this.escape(peer.name)}</strong><br>
                    <small>${this.escape(peer.address)}</small>
                </td>
                <td>
                    ${this.badge(peer.connected, peer.connected ? "Online" : "Offline")}<br>
                    <small>${this.escape(seen)}</small>
                </td>
                <td><small>${this.formatTraffic(peer.rx_bytes, peer.tx_bytes)}</small></td>
                <td class="table-action">
                    ${peer.has_config
                        ? '<button class="table-btn" data-action="download">Download</button>'
                        : ""}
                    <button class="table-btn danger" data-action="remove">Remove</button>
                </td>
            `;

            row.querySelector('[data-action="download"]')?.addEventListener(
                "click",
                () => this.download(
                    `/api/vpn/wireguard/peers/${peer.id}/config`,
                    wgPeerStatus
                )
            );

            row.querySelector('[data-action="remove"]').onclick =
                () => this.removePeer(peer);

            wgPeerTable.appendChild(row);

        });

    },


    renderOpenvpnClients() {

        const clients = this.data.openvpn.clients;

        ovpnClientTable.innerHTML = "";

        if (!clients.length) {
            this.emptyRow(ovpnClientTable, 4, "No devices yet.");
            return;
        }

        clients.forEach(client => {

            const row = document.createElement("tr");

            const detail = client.connected
                ? `${client.virtual_address} from ${client.real_address}`
                : "";

            row.innerHTML = `
                <td><strong>${this.escape(client.name)}</strong></td>
                <td>
                    ${this.badge(client.connected, client.connected ? "Online" : "Offline")}<br>
                    <small>${this.escape(detail)}</small>
                </td>
                <td><small>${client.connected
                    ? this.formatTraffic(client.rx_bytes, client.tx_bytes)
                    : "—"}</small></td>
                <td class="table-action">
                    <button class="table-btn" data-action="download">Download</button>
                    <button class="table-btn danger" data-action="revoke">Revoke</button>
                </td>
            `;

            row.querySelector('[data-action="download"]').onclick =
                () => this.download(
                    `/api/vpn/openvpn/clients/${encodeURIComponent(client.name)}/config`,
                    ovpnClientStatus
                );

            row.querySelector('[data-action="revoke"]').onclick =
                () => this.revokeClient(client);

            ovpnClientTable.appendChild(row);

        });

    },


    renderProfiles() {

        const profiles = this.data.profiles;

        vpnProfileTable.innerHTML = "";

        if (!profiles.length) {
            this.emptyRow(vpnProfileTable, 5, "No profiles. Import one below.");
            return;
        }

        profiles.forEach(profile => {

            const row = document.createElement("tr");

            const type = profile.type === "wireguard" ? "WireGuard" : "OpenVPN";

            row.innerHTML = `
                <td>
                    <strong>${this.escape(profile.name)}</strong><br>
                    <small>${type} · ${this.escape(profile.interface)}</small>
                </td>
                <td>${this.badge(profile.connected, profile.connected ? "Connected" : "Disconnected")}</td>
                <td>
                    <button class="table-btn" data-action="full-tunnel">
                        ${profile.full_tunnel ? "On" : "Off"}
                    </button>
                    ${!profile.full_tunnel && profile.routes_all_by_profile
                        ? "<br><small>Profile routes all</small>" : ""}
                </td>
                <td>
                    <button class="table-btn" data-action="autostart">
                        ${profile.autostart ? "On" : "Off"}
                    </button>
                </td>
                <td class="table-action">
                    <button class="table-btn" data-action="toggle">
                        ${profile.connected ? "Disconnect" : "Connect"}
                    </button>
                    <button class="table-btn danger" data-action="delete">Delete</button>
                </td>
            `;

            row.querySelector('[data-action="autostart"]').onclick =
                () => this.toggleAutostart(profile);

            row.querySelector('[data-action="full-tunnel"]').onclick =
                () => this.toggleFullTunnel(profile);

            row.querySelector('[data-action="toggle"]').onclick =
                () => this.toggleProfile(profile);

            row.querySelector('[data-action="delete"]').onclick =
                () => this.deleteProfile(profile);

            vpnProfileTable.appendChild(row);

        });

    },


    formatDuration(seconds) {

        const d = Math.floor(seconds / 86400);
        const h = Math.floor(seconds % 86400 / 3600);
        const m = Math.floor(seconds % 3600 / 60);

        if (d) return `${d}d ${h}h`;
        if (h) return `${h}h ${m}m`;
        if (m) return `${m}m`;
        return `${seconds}s`;

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


    // rx/tx are from the router's side: rx is the device's upload.
    formatTraffic(rx, tx) {

        return `↓ ${this.formatBytes(tx)} · ↑ ${this.formatBytes(rx)}`;

    },


    // Fetch first so errors show in the page instead of a broken file.
    async download(url, statusEl) {

        const res = await fetch(url);

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        if (!res.ok) {

            try {
                statusEl.textContent = (await res.json()).message;
            } catch {
                statusEl.textContent = "Download failed.";
            }

            return;
        }

        const disposition = res.headers.get("Content-Disposition") || "";
        const name = disposition.match(/filename="([^"]+)"/)?.[1] || "vpn.conf";

        const link = document.createElement("a");

        link.href = URL.createObjectURL(await res.blob());
        link.download = name;
        link.click();

        URL.revokeObjectURL(link.href);

    },


    // ------------------------------------------------------------
    // WireGuard
    // ------------------------------------------------------------

    async saveWireguard() {

        wgSave.disabled = true;

        const saved = await this.run(wgStatus, "Applying...", () =>
            this.send("/api/vpn/wireguard/server", {
                enabled: wgEnabledInput.value === "true",
                listen_port: Number(wgPortInput.value),
                address: wgAddressInput.value.trim(),
                endpoint: wgEndpointInput.value.trim(),
                dns: wgDnsInput.value.trim(),
                routing: wgRoutingInput.value
            })
        );

        wgSave.disabled = false;

        // Keep the user's edits when validation failed.
        if (saved) this.renderForms();

    },


    async addPeer() {

        const added = await this.run(wgPeerStatus, "Adding...", () =>
            this.send("/api/vpn/wireguard/peers", {
                name: wgPeerNameInput.value.trim(),
                public_key: wgPeerKeyInput.value.trim()
            })
        );

        if (added) {
            wgPeerNameInput.value = "";
            wgPeerKeyInput.value = "";
        }

    },


    async removePeer(peer) {

        const confirmed = await ChaosModal.confirm({
            title: "Remove Device",
            subtitle: `${peer.name} will no longer be able to connect.`,
            confirmText: "Remove"
        });

        if (!confirmed) return;

        await this.run(wgPeerStatus, "Removing...", () =>
            this.send(`/api/vpn/wireguard/peers/${peer.id}`, null, "DELETE")
        );

    },


    // ------------------------------------------------------------
    // OpenVPN
    // ------------------------------------------------------------

    async saveOpenvpn() {

        ovpnSave.disabled = true;

        const saved = await this.run(ovpnStatus, "Applying...", () =>
            this.send("/api/vpn/openvpn/server", {
                enabled: ovpnEnabledInput.value === "true",
                port: Number(ovpnPortInput.value),
                proto: ovpnProtoInput.value,
                network: ovpnNetworkInput.value.trim(),
                endpoint: ovpnEndpointInput.value.trim(),
                dns: ovpnDnsInput.value.trim(),
                routing: ovpnRoutingInput.value
            })
        );

        ovpnSave.disabled = false;

        // Keep the user's edits when validation failed.
        if (saved) this.renderForms();

    },


    async addClient() {

        ovpnAddClient.disabled = true;

        const added = await this.run(ovpnClientStatus, "Creating certificate...", () =>
            this.send("/api/vpn/openvpn/clients", {
                name: ovpnClientNameInput.value.trim()
            })
        );

        ovpnAddClient.disabled = false;

        if (added) ovpnClientNameInput.value = "";

    },


    async revokeClient(client) {

        const confirmed = await ChaosModal.confirm({
            title: "Revoke Device",
            subtitle: `${client.name}'s certificate will be revoked. ` +
                "It cannot connect again, even with its saved profile.",
            confirmText: "Revoke"
        });

        if (!confirmed) return;

        await this.run(ovpnClientStatus, "Revoking...", () =>
            this.send(
                `/api/vpn/openvpn/clients/${encodeURIComponent(client.name)}`,
                null,
                "DELETE"
            )
        );

    },


    // ------------------------------------------------------------
    // VPN client profiles
    // ------------------------------------------------------------

    updateImportType() {

        document.querySelector(".vpn-credentials").classList.toggle(
            "hidden",
            vpnImportTypeInput.value !== "openvpn"
        );

    },


    readFile(file) {

        if (!file) return;

        const reader = new FileReader();

        reader.onload = () => {

            vpnImportConfigInput.value = reader.result;

            // Guess type and name from the file name.
            const isOvpn = /\.ovpn$/i.test(file.name) ||
                /^\s*client\s*$/m.test(reader.result);

            vpnImportTypeInput.value = isOvpn ? "openvpn" : "wireguard";
            ChaosSelect.refresh(vpnImportTypeInput);
            this.updateImportType();

            if (!vpnImportNameInput.value) {
                vpnImportNameInput.value = file.name
                    .replace(/\.[^.]+$/, "")
                    .replace(/[^A-Za-z0-9_-]/g, "-")
                    .slice(0, 32);
            }

        };

        reader.readAsText(file);

        vpnImportFileInput.value = "";

    },


    async importProfile() {

        const openvpn = vpnImportTypeInput.value === "openvpn";

        const imported = await this.run(vpnImportStatus, "Importing...", () =>
            this.send("/api/vpn/profiles", {
                name: vpnImportNameInput.value.trim(),
                type: vpnImportTypeInput.value,
                config: vpnImportConfigInput.value,
                username: openvpn ? vpnImportUserInput.value : "",
                password: openvpn ? vpnImportPassInput.value : "",
                full_tunnel: vpnImportFullTunnelInput.checked
            })
        );

        if (imported) {
            vpnImportNameInput.value = "";
            vpnImportConfigInput.value = "";
            vpnImportUserInput.value = "";
            vpnImportPassInput.value = "";
        }

    },


    async toggleProfile(profile) {

        if (!profile.connected) {

            const others = this.data.profiles.some(
                p => p.connected && p.id !== profile.id
            );

            const confirmed = await ChaosModal.confirm({
                title: `Connect to ${profile.name}`,
                subtitle: (others ? "The current VPN connection will be closed. " : "") +
                    "All traffic from the router and your network will go through this VPN.",
                confirmText: "Connect"
            });

            if (!confirmed) return;

        }

        const action = profile.connected ? "disconnect" : "connect";

        await this.run(
            vpnProfileStatus,
            profile.connected ? "Disconnecting..." : "Connecting...",
            () => this.send(`/api/vpn/profiles/${profile.id}/${action}`)
        );

    },


    async toggleFullTunnel(profile) {

        await this.run(
            vpnProfileStatus,
            profile.connected ? "Saving and reconnecting..." : "Saving...",
            () => this.send(`/api/vpn/profiles/${profile.id}/full-tunnel`, {
                enabled: !profile.full_tunnel
            })
        );

    },


    async toggleAutostart(profile) {

        await this.run(vpnProfileStatus, "Saving...", () =>
            this.send(`/api/vpn/profiles/${profile.id}/autostart`, {
                enabled: !profile.autostart
            })
        );

    },


    async deleteProfile(profile) {

        const confirmed = await ChaosModal.confirm({
            title: "Delete Profile",
            subtitle: `${profile.name} will be disconnected and removed.`,
            confirmText: "Delete"
        });

        if (!confirmed) return;

        await this.run(vpnProfileStatus, "Deleting...", () =>
            this.send(`/api/vpn/profiles/${profile.id}`, null, "DELETE")
        );

    },


    init() {

        this.selects.forEach(id => {
            ChaosSelect.enhance(document.getElementById(id));
        });

        document.querySelectorAll(".tab-btn").forEach(btn => {
            btn.onclick = () => this.showTab(btn.dataset.tab);
        });

        let tab = "wireguard";

        try {
            tab = sessionStorage.getItem(this.TAB_KEY) || tab;
        } catch {}

        this.showTab(tab);

        wgSave.onclick = () => this.saveWireguard();
        wgAddPeer.onclick = () => this.addPeer();

        ovpnSave.onclick = () => this.saveOpenvpn();
        ovpnAddClient.onclick = () => this.addClient();

        vpnImportTypeInput.onchange = () => this.updateImportType();
        vpnImportFile.onclick = () => vpnImportFileInput.click();
        vpnImportFileInput.onchange = () => this.readFile(vpnImportFileInput.files[0]);
        vpnImport.onclick = () => this.importProfile();

        this.updateImportType();

        this.load();

        this.timer = setInterval(() => this.refresh(), 10000);

    },


    destroy() {

        clearInterval(this.timer);
        this.timer = null;

        ChaosModal.close();

    }

};
