window.Page = window.Page || {};

window.Page.dhcp = {

    timer: null,
    data: null,


    // Lease hostnames come from client devices; never trust them as HTML.
    escape(value) {

        const div = document.createElement("div");
        div.textContent = value ?? "";
        return div.innerHTML;

    },


    // ------------------------------------------------------------
    // Custom Dropdowns (see select.js)
    // ------------------------------------------------------------

    selects: ["dhcpEnabledInput", "dhcpInterfaceInput", "dhcpLeaseTimeInput"],

    refreshSelects() {

        this.selects.forEach(id => {
            ChaosSelect.refresh(document.getElementById(id));
        });

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


    post(url, body, method = "POST") {

        return this.request(url, {

            method: method,

            headers: {
                "Content-Type": "application/json"
            },

            body: body ? JSON.stringify(body) : undefined

        });

    },


    async load() {

        const res = await this.request("/api/dhcp");

        if (!res) return;

        if (!res.ok) {
            dhcpStatus.textContent = "Failed to load DHCP settings.";
            return;
        }

        this.data = res.data;

        this.renderStatus();
        this.renderSettings();
        this.renderReservations();

        await this.loadLeases();

    },


    renderStatus() {

        const { settings, status } = this.data;

        dhcpServerState.textContent =
            status.paused ? "Paused" :
            settings.enabled ? "Enabled" : "Disabled";

        dhcpServiceState.textContent =
            status.running ? "Running" : "Stopped";

        // eth0 in WAN mode: never hand out addresses to the uplink.
        if (status.paused && !dhcpStatus.textContent) {
            dhcpStatus.textContent = status.paused;
        }

        this.updateRouterIP();

    },


    renderSettings() {

        const { settings, interfaces } = this.data;

        dhcpInterfaceInput.innerHTML = "";

        const names = interfaces.map(i => i.name);

        // Keep the saved interface selectable even if it is currently down.
        if (!names.includes(settings.interface)) {
            names.unshift(settings.interface);
        }

        names.forEach(name => {

            const option = document.createElement("option");
            option.value = name;
            option.textContent = name;
            dhcpInterfaceInput.appendChild(option);

        });

        dhcpEnabledInput.value = settings.enabled ? "true" : "false";
        dhcpInterfaceInput.value = settings.interface;
        dhcpLeaseTimeInput.value = settings.lease_time;
        dhcpRangeStartInput.value = settings.range_start || "";
        dhcpRangeEndInput.value = settings.range_end || "";
        dhcpGatewayInput.value = settings.gateway || "";
        dhcpDns1Input.value = settings.dns[0] || "";
        dhcpDns2Input.value = settings.dns[1] || "";
        dhcpDomainInput.value = settings.domain || "";

        this.refreshSelects();

        this.updateRouterIP();

    },


    updateRouterIP() {

        const iface = this.data.interfaces.find(
            i => i.name === dhcpInterfaceInput.value
        );

        dhcpRouterIP.textContent = iface?.ip || "No IPv4";

    },


    renderReservations() {

        const reservations = this.data.settings.reservations;

        dhcpReservationTable.innerHTML = "";

        if (!reservations.length) {

            dhcpReservationTable.innerHTML = `
                <tr class="empty-row">
                    <td colspan="4">No static leases.</td>
                </tr>
            `;

            return;
        }

        reservations.forEach(r => {

            const row = document.createElement("tr");

            row.innerHTML = `
                <td>${this.escape(r.mac)}</td>
                <td>${this.escape(r.ip)}</td>
                <td>${this.escape(r.hostname) || "<small>—</small>"}</td>
                <td class="table-action">
                    <button class="table-btn danger">Remove</button>
                </td>
            `;

            row.querySelector("button").onclick =
                () => this.removeReservation(r.mac);

            dhcpReservationTable.appendChild(row);

        });

    },


    async loadLeases() {

        const res = await this.request("/api/dhcp/leases");

        if (!res || !res.ok) return;

        const leases = res.data;

        dhcpLeaseCount.textContent = leases.length;

        dhcpLeaseTable.innerHTML = "";

        if (!leases.length) {

            dhcpLeaseTable.innerHTML = `
                <tr class="empty-row">
                    <td colspan="4">No active leases.</td>
                </tr>
            `;

            return;
        }

        leases.forEach(lease => {

            const row = document.createElement("tr");

            row.innerHTML = `
                <td>
                    <strong>${this.escape(lease.hostname) || "Unknown"}</strong><br>
                    <small>${this.escape(lease.mac)}</small>
                </td>
                <td>${this.escape(lease.ip)}</td>
                <td>${this.formatExpiry(lease.expires_in)}</td>
                <td class="table-action">
                    ${lease.reserved
                        ? '<span class="status online">Static</span>'
                        : '<button class="table-btn">Reserve</button>'}
                </td>
            `;

            const button = row.querySelector("button");

            if (button) {
                button.onclick = () => this.reserveLease(lease);
            }

            dhcpLeaseTable.appendChild(row);

        });

    },


    formatExpiry(seconds) {

        if (seconds === null) return "Never";
        if (seconds <= 0) return "Expired";

        const d = Math.floor(seconds / 86400);
        const h = Math.floor(seconds % 86400 / 3600);
        const m = Math.floor(seconds % 3600 / 60);

        if (d) return `${d}d ${h}h`;
        if (h) return `${h}h ${m}m`;
        return `${m}m`;

    },


    collectSettings() {

        return {

            enabled: dhcpEnabledInput.value === "true",

            interface: dhcpInterfaceInput.value,

            lease_time: dhcpLeaseTimeInput.value,

            range_start: dhcpRangeStartInput.value.trim(),

            range_end: dhcpRangeEndInput.value.trim(),

            gateway: dhcpGatewayInput.value.trim(),

            dns: [
                dhcpDns1Input.value.trim(),
                dhcpDns2Input.value.trim()
            ].filter(Boolean),

            domain: dhcpDomainInput.value.trim()

        };

    },


    // Shared handling for every endpoint that saves and applies.
    handleSave(res, statusEl, successText) {

        if (!res) return false;

        const data = res.data;

        if (data.settings) {

            this.data.settings = data.settings;

            this.renderStatus();
            this.renderReservations();
            this.loadLeases();

        }

        if (data.success) {
            statusEl.textContent = `✓ ${successText}`;
            return true;
        }

        statusEl.textContent = data.message || "Failed to save.";

        // Saved but not applied (e.g. dnsmasq missing) still keeps the form.
        return data.saved === true;

    },


    async save() {

        dhcpSave.disabled = true;
        dhcpStatus.textContent = "Applying...";

        const res = await this.post(
            "/api/dhcp/settings",
            this.collectSettings()
        );

        dhcpSave.disabled = false;

        this.handleSave(res, dhcpStatus, "DHCP settings applied");

        if (!dhcpConfigPreview.classList.contains("hidden")) {
            this.preview();
        }

    },


    async preview() {

        const res = await this.post(
            "/api/dhcp/preview",
            { ...this.collectSettings(), enabled: true }
        );

        if (!res) return;

        if (!res.ok) {
            dhcpStatus.textContent = res.data.message;
            dhcpConfigPreview.classList.add("hidden");
            return;
        }

        dhcpConfigPreview.textContent = res.data.config;
        dhcpConfigPreview.classList.remove("hidden");

    },


    async addReservation(reservation) {

        reservationStatus.textContent = "Saving...";

        const res = await this.post(
            "/api/dhcp/reservations",
            reservation
        );

        const saved = this.handleSave(
            res,
            reservationStatus,
            "Static lease saved"
        );

        if (saved) {
            reserveMacInput.value = "";
            reserveIpInput.value = "";
            reserveHostnameInput.value = "";
        }

    },


    reserveLease(lease) {

        this.addReservation({
            mac: lease.mac,
            ip: lease.ip,
            hostname: lease.hostname
        });

    },


    async removeReservation(mac) {

        reservationStatus.textContent = "Removing...";

        const res = await this.post(
            `/api/dhcp/reservations/${encodeURIComponent(mac)}`,
            null,
            "DELETE"
        );

        this.handleSave(res, reservationStatus, "Static lease removed");

    },


    init() {

        this.selects.forEach(id => {
            ChaosSelect.enhance(document.getElementById(id));
        });

        this.load();

        dhcpSave.onclick = () => this.save();

        dhcpPreview.onclick = () => this.preview();

        dhcpInterfaceInput.onchange = () => this.updateRouterIP();

        dhcpAddReservation.onclick = () => {

            this.addReservation({
                mac: reserveMacInput.value.trim(),
                ip: reserveIpInput.value.trim(),
                hostname: reserveHostnameInput.value.trim()
            });

        };

        this.timer = setInterval(() => this.loadLeases(), 10000);

    },


    destroy() {

        clearInterval(this.timer);
        this.timer = null;

    }

};
