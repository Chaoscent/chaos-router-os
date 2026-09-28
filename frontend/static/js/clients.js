window.Page = window.Page || {};

window.Page.clients = {

    timer: null,
    selected: null,
    currentClient: null,

    async update() {

        const res = await fetch("/api/clients");

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        const clients = await res.json();

        clientTable.innerHTML = "";

        clients.forEach(client => {

            const row = document.createElement("tr");

            if (this.selected === client.ip) {
                row.classList.add("selected");
            }

            row.innerHTML = `
                <td>
                    <strong>${client.hostname}</strong><br>
                    <small>${client.mac}</small>
                </td>

                <td>${client.ip}</td>
                <td>${client.interface}</td>

                <td>
                    <span class="status">${client.state}</span>
                </td>
            `;

            row.onclick = () => this.select(client);

            clientTable.appendChild(row);

        });

    },

    select(client) {

        this.selected = client.ip;
        this.currentClient = client;

        inspectorName.textContent = client.hostname;
        inspectorIP.textContent = client.ip;
        inspectorMAC.textContent = client.mac;
        inspectorVendor.textContent = client.vendor;
        inspectorInterface.textContent = client.interface;
        inspectorStatus.textContent = client.state;

        clientInspector.classList.add("open");

        this.update();

    },

    close() {

        this.selected = null;
        this.currentClient = null;

        clientInspector.classList.remove("open");

        this.update();

    },

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

        this.update();

        this.timer = setInterval(() => this.update(), 2000);

    },

    destroy() {

        clearInterval(this.timer);

    }

};