window.Page = window.Page || {};

window.Page.network = {

    timer: null,

    interfaces: {},
    original: {},
    pendingInterface: null,

    // ------------------------------------------------------------
    // Validation
    // ------------------------------------------------------------

    isIPv4(value) {

        const parts = value.split(".");
        if (parts.length !== 4) return false;

        return parts.every(part => {
            if (!/^\d+$/.test(part)) return false;
            const n = Number(part);
            return n >= 0 && n <= 255;
        });

    },

    isSubnetMask(value) {

        if (!this.isIPv4(value)) return false;

        const bits = value
            .split(".")
            .map(Number)
            .map(n => n.toString(2).padStart(8, "0"))
            .join("");

        return /^1*0*$/.test(bits);

    },

    setFieldState(input, valid, message = "") {

        input.classList.toggle("invalid", !valid);

        let error = input.parentElement.querySelector(".field-error");

        if (!error) {
            error = document.createElement("div");
            error.className = "field-error";
            input.parentElement.appendChild(error);
        }

        error.textContent = valid ? "" : message;

    },

    validateCard(name) {

        const card = this.interfaces[name];

        if (name === "wwan0") return true;

        if (card.mode.value === "DHCP Client") {

            [card.ip, card.subnet, card.gateway, card.dns].forEach(field =>
                this.setFieldState(field, true)
            );

            return true;

        }

        const ipOK = this.isIPv4(card.ip.value.trim());
        const subnetOK = this.isSubnetMask(card.subnet.value.trim());
        const gatewayOK = this.isIPv4(card.gateway.value.trim());
        const dnsOK = this.isIPv4(card.dns.value.trim());

        this.setFieldState(card.ip, ipOK, "Invalid IP.");
        this.setFieldState(card.subnet, subnetOK, "Invalid subnet.");
        this.setFieldState(card.gateway, gatewayOK, "Invalid gateway.");
        this.setFieldState(card.dns, dnsOK, "Invalid DNS.");

        return ipOK && subnetOK && gatewayOK && dnsOK;

    },

    // ------------------------------------------------------------
    // Top Status
    // ------------------------------------------------------------

    async updateStatus() {

        const res = await fetch("/api/network");

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        const data = await res.json();

        wanStatus.textContent = data.wan;
        wanInterface.textContent = data.interface;
        wanType.textContent = data.connection;
        wanGateway.textContent = data.gateway;

    },

    // ------------------------------------------------------------
    // Interface Cards
    // ------------------------------------------------------------

    async loadInterfaces() {

        const res = await fetch("/api/network/interfaces");
        const interfaces = await res.json();

        interfaceContainer.innerHTML = "";

        this.interfaces = {};
        this.original = {};

        for (const iface of interfaces) {

            this.original[iface.name] = structuredClone(iface);

            const node = interfaceTemplate.content.firstElementChild.cloneNode(true);

            const modeLabel = node.querySelector(".interface-mode");

            node.querySelector(".interface-name").textContent = iface.name;
            node.querySelector(".interface-type").textContent = iface.type;
            modeLabel.textContent = iface.mode;

            const mode = node.querySelector(".interface-mode-select");
            const ip = node.querySelector(".interface-ip");
            const subnet = node.querySelector(".interface-subnet");
            const gateway = node.querySelector(".interface-gateway");
            const dns = node.querySelector(".interface-dns");
            const save = node.querySelector(".interface-save");

            mode.value = iface.mode;
            ip.value = iface.ip;
            subnet.value = iface.subnet;
            gateway.value = iface.gateway;
            dns.value = iface.dns;

            this.interfaces[iface.name] = {
                node,
                mode,
                ip,
                subnet,
                gateway,
                dns,
                save,
                modeLabel
            };

            const updateState = () => {

                modeLabel.textContent = mode.value;

                const editable = iface.name === "eth0" && mode.value === "Static";

                mode.disabled = iface.name === "wwan0";

                ip.disabled = !editable;
                subnet.disabled = !editable;
                gateway.disabled = !editable;
                dns.disabled = !editable;

                if (iface.name === "wwan0") {
                    save.style.display = "none";
                }

                const changed = this.hasChanges(iface.name);
                const valid = this.validateCard(iface.name);

                save.disabled = !(changed && valid);

            };

            [mode, ip, subnet, gateway, dns].forEach(el => {
                el.addEventListener("input", updateState);
                if (el.tagName === "SELECT")
                    el.addEventListener("change", updateState);
            });

            save.onclick = () => {
                this.pendingInterface = iface.name;
                this.openConfirmModal(iface.name);
            };

            updateState();

            interfaceContainer.appendChild(node);

        }

    },

    hasChanges(name) {

        const o = this.original[name];
        const c = this.interfaces[name];

        return (
            o.mode !== c.mode.value ||
            o.ip !== c.ip.value ||
            o.subnet !== c.subnet.value ||
            o.gateway !== c.gateway.value ||
            o.dns !== c.dns.value
        );

    },

    // ------------------------------------------------------------
    // Confirmation Modal
    // ------------------------------------------------------------

    openConfirmModal(name) {

        modalBody.innerHTML = "";

        const o = this.original[name];
        const c = this.interfaces[name];

        const changes = [
            ["Mode", o.mode, c.mode.value],
            ["IP", o.ip, c.ip.value],
            ["Subnet", o.subnet, c.subnet.value],
            ["Gateway", o.gateway, c.gateway.value],
            ["DNS", o.dns, c.dns.value]
        ];

        for (const [label, oldValue, newValue] of changes) {

            if (oldValue === newValue) continue;

            modalBody.insertAdjacentHTML("beforeend", `
                <div class="modal-change">
                    <label>${label}</label>
                    <strong>${oldValue} → ${newValue}</strong>
                </div>
            `);

        }

        confirmModal.classList.remove("hidden");

    },

    closeConfirmModal() {
        confirmModal.classList.add("hidden");
    },

    // ------------------------------------------------------------
    // Apply
    // ------------------------------------------------------------

    async applyChanges() {

        const name = this.pendingInterface;
        const card = this.interfaces[name];

        const button = card.save;

        button.disabled = true;
        button.textContent = "Applying...";

        modalConfirm.disabled = true;
        modalConfirm.textContent = "Applying...";

        try {

            await fetch("/api/network/stage", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    interface: name,
                    mode: card.mode.value,
                    ip: card.ip.value.trim(),
                    subnet: card.subnet.value.trim(),
                    gateway: card.gateway.value.trim(),
                    dns: card.dns.value.trim()
                })
            });

            const res = await fetch("/api/network/apply", {
                method: "POST"
            });

            const data = await res.json();

            if (!res.ok)
                throw new Error(data.message || "Apply failed.");

            this.closeConfirmModal();

            await this.loadInterfaces();
            await this.updateStatus();

        } catch (err) {

            alert("Apply failed:\n\n" + err.message);

            button.disabled = false;
            button.textContent = "Apply";

        } finally {

            modalConfirm.disabled = false;
            modalConfirm.textContent = "Apply";

        }

    },

    // ------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------

    init() {

        this.updateStatus();
        this.loadInterfaces();

        this.timer = setInterval(() => this.updateStatus(), 3000);

        modalClose.onclick = () => this.closeConfirmModal();
        modalCancel.onclick = () => this.closeConfirmModal();

        confirmModal.onclick = e => {
            if (e.target === confirmModal)
                this.closeConfirmModal();
        };

        modalConfirm.onclick = () => this.applyChanges();

    },

    destroy() {
        clearInterval(this.timer);
    }

};