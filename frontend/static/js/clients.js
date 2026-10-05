window.Page = window.Page || {};

window.Page.clients = {

    timer: null,
    selected: null,
    currentClient: null,
    dhcpEnabled: false,

    escape(value) {

        return ChaosSelect.escape(value);

    },

    async request(url, body) {

        const res = await fetch(url, {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify(body)

        });

        if (res.status === 401) {
            location.href = "/login";
            return null;
        }

        try {
            return await res.json();
        } catch {
            return { success: false, message: "Unexpected server response." };
        }

    },

    async update() {

        const res = await fetch("/api/clients");

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        const data = await res.json();

        this.dhcpEnabled = data.dhcp_enabled;

        clientTable.innerHTML = "";

        data.clients.forEach(client => {

            const row = document.createElement("tr");

            // Blocked devices may have no IP; select by MAC.
            if (this.selected === client.mac) {
                row.classList.add("selected");
                this.currentClient = client;
            }

            const badge = client.blocked
                ? "blocked"
                : client.state === "Online" ? "online" : "";

            const tags = [
                client.reservation ? "Reserved IP" : "",
                client.is_you ? "This device" : ""
            ].filter(Boolean).join(" · ");

            row.innerHTML = `
                <td>
                    <strong>${this.escape(client.hostname)}</strong><br>
                    <small>${this.escape(client.mac)}${tags ? ` · ${tags}` : ""}</small>
                </td>

                <td>${this.escape(client.ip) || "—"}</td>
                <td>${this.escape(client.interface) || "—"}</td>

                <td>
                    <span class="status ${badge}">${this.escape(client.state)}</span>
                </td>
            `;

            row.onclick = () => this.select(client);

            clientTable.appendChild(row);

        });

        // Keep the open inspector in sync with live data.
        if (this.currentClient) {
            this.renderInspector();
        }

    },

    select(client) {

        this.selected = client.mac;
        this.currentClient = client;

        inspectorResult.classList.add("hidden");

        this.renderInspector();

        clientInspector.classList.add("open");

        this.update();

    },

    renderInspector() {

        const client = this.currentClient;

        inspectorName.textContent = client.hostname;
        inspectorIP.textContent = client.ip || "No address";
        inspectorMAC.textContent = client.mac;
        inspectorVendor.textContent = client.vendor;
        inspectorInterface.textContent = client.interface || "—";
        inspectorStatus.textContent = client.state;

        inspectorAssignment.textContent = this.describeAssignment(client);
        inspectorAccess.textContent = client.blocked ? "Blocked" : "Allowed";

        inspectorYou.classList.toggle("hidden", !client.is_you);

        reserveDevice.textContent = client.reservation
            ? `Edit Reservation (${client.reservation.ip})`
            : "Reserve DHCP IP";

        blockDevice.textContent = client.blocked ? "Unblock Device" : "Block Device";
        blockDevice.classList.toggle("danger", !client.blocked);

        // Actions that need the device online with an address.
        const reachable = Boolean(client.ip) && !client.blocked;

        pingDevice.disabled = !reachable;
        openDevice.disabled = !reachable;
        wakeDevice.disabled = !client.interface || client.blocked;

    },

    describeAssignment(client) {

        if (client.reservation) {
            return `Reserved (${client.reservation.ip})`;
        }

        if (client.lease_expires_in === null || client.lease_expires_in === undefined) {
            return client.dhcp ? "DHCP" : "Static or unknown";
        }

        const hours = Math.floor(client.lease_expires_in / 3600);
        const minutes = Math.floor(client.lease_expires_in % 3600 / 60);

        return `DHCP, lease ${hours ? `${hours}h ` : ""}${minutes}m left`;

    },

    close() {

        this.selected = null;
        this.currentClient = null;

        clientInspector.classList.remove("open");

        this.update();

    },

    showResult(message, ok = true) {

        inspectorResult.textContent = message;
        inspectorResult.classList.toggle("error", !ok);
        inspectorResult.classList.remove("hidden");

    },

    // ------------------------------------------------------------
    // Quick tools
    // ------------------------------------------------------------

    async ping() {

        pingDevice.disabled = true;

        this.showResult(`Pinging ${this.currentClient.ip}...`);

        const data = await this.request("/api/clients/ping", {
            ip: this.currentClient.ip
        });

        pingDevice.disabled = false;

        if (data) this.showResult(data.message, data.success);

    },

    async wake() {

        const data = await this.request("/api/clients/wake", {
            mac: this.currentClient.mac,
            interface: this.currentClient.interface
        });

        if (data) this.showResult(data.message, data.success);

    },

    openWebPage() {

        window.open(`http://${this.currentClient.ip}/`, "_blank", "noopener");

    },

    async copyMac() {

        try {
            await navigator.clipboard.writeText(this.currentClient.mac);
            this.showResult("MAC address copied.");
        } catch {
            this.showResult(this.currentClient.mac);
        }

    },

    // ------------------------------------------------------------
    // Rename
    // ------------------------------------------------------------

    openRenameModal() {

        if (!this.currentClient) return;

        renameInput.value =
            this.currentClient.hostname === "Unknown"
                ? ""
                : this.currentClient.hostname;

        renameModal.classList.remove("hidden");

        setTimeout(() => renameInput.focus(), 50);

    },

    closeRenameModal() {

        renameModal.classList.add("hidden");

    },

    async saveRename() {

        const alias = renameInput.value.trim();

        if (!alias) return;

        saveRenameBtn.disabled = true;
        saveRenameBtn.textContent = "Saving...";

        const res = await fetch("/api/clients/alias", {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({
                mac: this.currentClient.mac,
                alias
            })

        });

        saveRenameBtn.disabled = false;
        saveRenameBtn.textContent = "Save";

        if (!res.ok) {
            alert("Failed to save alias.");
            return;
        }

        this.closeRenameModal();
        this.update();

    },

    // ------------------------------------------------------------
    // DHCP reservation
    // ------------------------------------------------------------

    // DHCP hostnames allow letters, numbers and hyphens only.
    suggestHostname(name) {

        if (!name || name === "Unknown") return "";

        return name
            .replace(/[^A-Za-z0-9-]+/g, "-")
            .replace(/^-+|-+$/g, "")
            .slice(0, 63);

    },

    openReserveModal() {

        const client = this.currentClient;
        const reservation = client.reservation;

        reserveTitle.textContent = reservation ? "Edit Reservation" : "Reserve DHCP IP";

        reserveSubtitle.textContent = this.dhcpEnabled
            ? `${client.hostname} always gets this address.`
            : "The DHCP server is off. The reservation takes effect once it is on.";

        reserveIpField.value = reservation ? reservation.ip : client.ip;
        reserveNameField.value = reservation
            ? reservation.hostname
            : this.suggestHostname(client.hostname);

        reserveStatus.textContent = "";

        removeReserveBtn.classList.toggle("hidden", !reservation);
        saveReserveBtn.textContent = reservation ? "Save" : "Reserve";

        reserveModal.classList.remove("hidden");

        setTimeout(() => reserveIpField.focus(), 50);

    },

    closeReserveModal() {

        reserveModal.classList.add("hidden");

    },

    async saveReservation() {

        saveReserveBtn.disabled = true;
        reserveStatus.textContent = "Saving...";

        // Re-reserving a MAC replaces its previous reservation.
        const data = await this.request("/api/dhcp/reservations", {
            mac: this.currentClient.mac,
            ip: reserveIpField.value.trim(),
            hostname: reserveNameField.value.trim()
        });

        saveReserveBtn.disabled = false;

        if (!data) return;

        if (!data.success) {
            reserveStatus.textContent = data.message;
            return;
        }

        this.closeReserveModal();
        this.showResult(`Reserved ${reserveIpField.value.trim()}.`);
        this.update();

    },

    async removeReservation() {

        const res = await fetch(
            `/api/dhcp/reservations/${encodeURIComponent(this.currentClient.mac)}`,
            { method: "DELETE" }
        );

        const data = await res.json();

        if (!data.success) {
            reserveStatus.textContent = data.message;
            return;
        }

        this.closeReserveModal();
        this.showResult("Reservation removed.");
        this.update();

    },

    // ------------------------------------------------------------
    // Block
    // ------------------------------------------------------------

    async toggleBlock() {

        const client = this.currentClient;

        if (client.blocked) {

            const data = await this.request("/api/clients/unblock", {
                mac: client.mac
            });

            if (data) this.showResult(data.message, data.success);

            this.update();

            return;
        }

        const body = document.createElement("div");

        body.innerHTML = client.is_you
            ? `<p class="modal-warning">
                   This is the device you are using right now. You will lose
                   access to this page. If you do not confirm within the
                   countdown, the block is undone automatically.
               </p>`
            : `<p class="modal-note">
                   It loses access to the internet and to the router until
                   you unblock it, whichever address it uses.
               </p>`;

        const confirmed = await ChaosModal.confirm({
            title: `Block ${client.hostname}?`,
            subtitle: client.mac,
            body: body,
            confirmText: "Block"
        });

        if (!confirmed) return;

        const data = await this.request("/api/clients/block", {
            mac: client.mac,
            name: client.hostname === "Unknown" ? "" : client.hostname
        });

        if (data) this.showResult(data.message, data.success);

        this.update();

    },

    init() {

        closeInspector.onclick = () => this.close();

        renameDevice.onclick = () => this.openRenameModal();

        closeRenameModal.onclick = () => this.closeRenameModal();
        cancelRenameBtn.onclick = () => this.closeRenameModal();
        saveRenameBtn.onclick = () => this.saveRename();

        renameInput.addEventListener("keydown", e => {

            if (e.key === "Enter")
                this.saveRename();

            if (e.key === "Escape")
                this.closeRenameModal();

        });

        renameModal.onclick = e => {

            if (e.target === renameModal)
                this.closeRenameModal();

        };

        reserveDevice.onclick = () => this.openReserveModal();
        closeReserveModal.onclick = () => this.closeReserveModal();
        cancelReserveBtn.onclick = () => this.closeReserveModal();
        saveReserveBtn.onclick = () => this.saveReservation();
        removeReserveBtn.onclick = () => this.removeReservation();

        reserveModal.onclick = e => {

            if (e.target === reserveModal)
                this.closeReserveModal();

        };

        blockDevice.onclick = () => this.toggleBlock();
        pingDevice.onclick = () => this.ping();
        wakeDevice.onclick = () => this.wake();
        openDevice.onclick = () => this.openWebPage();
        copyMac.onclick = () => this.copyMac();

        this.update();

        this.timer = setInterval(() => this.update(), 2000);

    },

    destroy() {

        clearInterval(this.timer);

    }

};
