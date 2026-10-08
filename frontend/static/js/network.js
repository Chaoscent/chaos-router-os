window.Page = window.Page || {};

window.Page.network = {

    timer: null,
    interfaces: {},
    original: {},
    pendingInterface: null,
    pendingRole: null,
    pendingLan: null,
    eth0Role: "lan",

    // LAN bridge status from /api/network/lan, and the edited values.
    lan: null,
    lanBridgeDraft: false,
    outsideClickHandler: null,

    // Editable network fields: card key, error message, validator.
    FIELDS: [
        { key: "ip",      error: "Invalid IP.",      validate: v => Page.network.isIPv4(v) },
        { key: "subnet",  error: "Invalid subnet.",  validate: v => Page.network.isSubnetMask(v) },
        { key: "gateway", error: "Invalid gateway.", validate: v => Page.network.isIPv4(v) },
        { key: "dns",     error: "Invalid DNS.",     validate: v => Page.network.isIPv4(v) }
    ],

    // Top status element id -> API response key.
    STATUS_MAP: {
        wanStatus: "wan",
        wanInterface: "interface",
        wanType: "connection",
        wanGateway: "gateway"
    },

    // ------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------

    $(id) {
        return document.getElementById(id);
    },

    isWWAN(name) {
        return name === "wwan0";
    },

    /** GET helper. Redirects to /login on 401 and returns null. */
    async get(url) {

        const res = await fetch(url);

        if (res.status === 401) {
            location.href = "/login";
            return null;
        }

        return res;

    },

    /** POST helper. Throws an Error carrying the server message on failure. */
    async post(url, payload, fallbackMessage) {

        const options = { method: "POST" };

        if (payload !== undefined) {
            options.headers = { "Content-Type": "application/json" };
            options.body = JSON.stringify(payload);
        }

        const res = await fetch(url, options);

        let data = {};

        try {
            data = await res.json();
        } catch (_) {}

        if (!res.ok)
            throw new Error(data.message || fallbackMessage);

        return data;

    },

    // ------------------------------------------------------------
    // Validation
    // ------------------------------------------------------------

    isIPv4(value) {

        const parts = String(value || "").trim().split(".");

        if (parts.length !== 4)
            return false;

        return parts.every(part => {

            if (!/^\d+$/.test(part))
                return false;

            const n = Number(part);

            return n >= 0 && n <= 255;

        });

    },

    isSubnetMask(value) {

        if (!this.isIPv4(value))
            return false;

        const bits = value
            .split(".")
            .map(n => Number(n).toString(2).padStart(8, "0"))
            .join("");

        return /^1*0*$/.test(bits);

    },

    setFieldState(input, valid, message = "") {

        if (!input)
            return;

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

        if (!card)
            return false;

        // WWAN is read-only and DHCP needs no editable values.
        if (this.isWWAN(name) || card.mode.value === "DHCP Client") {

            this.FIELDS.forEach(({ key }) => this.setFieldState(card[key], true));

            return true;

        }

        let allValid = true;

        for (const { key, error, validate } of this.FIELDS) {

            const ok = validate(card[key].value);

            this.setFieldState(card[key], ok, error);

            allValid = allValid && ok;

        }

        return allValid;

    },

    // ------------------------------------------------------------
    // Custom Dropdown
    // ------------------------------------------------------------

    closeSelect(wrapper) {

        wrapper.classList.remove("open");

        const trigger = wrapper.querySelector(".chaos-select-trigger");

        if (trigger)
            trigger.setAttribute("aria-expanded", "false");

    },

    setupCustomSelect(node) {

        const wrapper = node.querySelector(".chaos-select");
        const trigger = node.querySelector(".chaos-select-trigger");
        const value = node.querySelector(".chaos-select-value");
        const menu = node.querySelector(".chaos-select-menu");
        const nativeSelect = node.querySelector(".interface-mode-select");
        const options = node.querySelectorAll(".chaos-select-option");

        if (!wrapper || !trigger || !value || !menu || !nativeSelect)
            return;

        const updateVisual = () => {

            value.textContent = nativeSelect.value;

            options.forEach(option => {

                const selected = option.dataset.value === nativeSelect.value;

                option.classList.toggle("selected", selected);
                option.setAttribute("aria-selected", selected ? "true" : "false");

            });

        };

        trigger.addEventListener("click", event => {

            event.preventDefault();
            event.stopPropagation();

            if (trigger.disabled)
                return;

            const wasOpen = wrapper.classList.contains("open");

            document
                .querySelectorAll(".chaos-select.open")
                .forEach(other => {
                    if (other !== wrapper)
                        this.closeSelect(other);
                });

            if (wasOpen) {
                this.closeSelect(wrapper);
            } else {
                wrapper.classList.add("open");
                trigger.setAttribute("aria-expanded", "true");
            }

        });

        options.forEach(option => {

            option.addEventListener("click", event => {

                event.preventDefault();
                event.stopPropagation();

                if (trigger.disabled)
                    return;

                nativeSelect.value = option.dataset.value;

                updateVisual();

                nativeSelect.dispatchEvent(new Event("change", { bubbles: true }));

                this.closeSelect(wrapper);

            });

        });

        nativeSelect.addEventListener("change", updateVisual);

        updateVisual();

    },

    // ------------------------------------------------------------
    // Top Status
    // ------------------------------------------------------------

    async updateStatus() {

        try {

            const res = await this.get("/api/network");

            if (!res || !res.ok)
                return;

            const data = await res.json();

            for (const [id, key] of Object.entries(this.STATUS_MAP)) {

                const element = this.$(id);

                if (element)
                    element.textContent = data[key] ?? "--";

            }

            if (data.eth0_role && data.eth0_role !== this.eth0Role) {
                this.eth0Role = data.eth0_role;
                this.renderRoleToggle();
                this.updateEth0BridgeState();
            }

        } catch (err) {

            console.error("Network status update failed:", err);

        }

    },

    // ------------------------------------------------------------
    // Interface Cards
    // ------------------------------------------------------------

    createInterfaceCard(template, iface) {

        const name = iface.name;
        const node = template.content.firstElementChild.cloneNode(true);
        const q = selector => node.querySelector(selector);

        const card = {
            node,
            mode: q(".interface-mode-select"),
            ip: q(".interface-ip"),
            subnet: q(".interface-subnet"),
            gateway: q(".interface-gateway"),
            dns: q(".interface-dns"),
            save: q(".interface-save"),
            modeLabel: q(".interface-mode")
        };

        // Initial values
        q(".interface-name").textContent = name;
        q(".interface-type").textContent = iface.type ?? "";
        card.modeLabel.textContent = iface.mode ?? "";
        card.mode.value = iface.mode === "Static" ? "Static" : "DHCP Client";

        this.FIELDS.forEach(({ key }) => {
            card[key].value = iface[key] ?? "";
        });

        this.interfaces[name] = card;

        if (name === "eth0")
            this.addRoleToggle(q(".interface-header"));

        this.setupCustomSelect(node);

        // State updater
        const updateState = () => {

            const isWWAN = this.isWWAN(name);
            const editable = !isWWAN && card.mode.value === "Static";

            card.modeLabel.textContent = card.mode.value;

            // wwan0 is completely read-only.
            card.mode.disabled = isWWAN;

            this.FIELDS.forEach(({ key }) => {
                card[key].disabled = !editable;
            });

            // Keep the visible custom dropdown in sync with the native select.
            const trigger = q(".chaos-select-trigger");

            if (trigger)
                trigger.disabled = isWWAN;

            // Validate first so error states are always refreshed.
            const valid = this.validateCard(name);

            // Apply only works when there is something valid to apply.
            card.save.disabled = isWWAN || !this.hasChanges(name) || !valid;

        };

        card.mode.addEventListener("change", updateState);

        this.FIELDS.forEach(({ key }) => {
            card[key].addEventListener("input", updateState);
        });

        card.save.addEventListener("click", event => {

            event.preventDefault();
            event.stopPropagation();

            if (card.save.disabled)
                return;

            this.pendingInterface = name;
            this.openConfirmModal(name);

        });

        updateState();

        return node;

    },

    async loadInterfaces() {

        const container = this.$("interfaceContainer");
        const template = this.$("interfaceTemplate");

        if (!container || !template)
            return;

        try {

            const res = await this.get("/api/network/interfaces");

            if (!res)
                return;

            if (!res.ok)
                throw new Error("Failed to load interfaces.");

            const interfaces = await res.json();

            container.innerHTML = "";

            this.interfaces = {};
            this.original = {};

            for (const iface of interfaces) {

                this.original[iface.name] = structuredClone(iface);

                container.appendChild(this.createInterfaceCard(template, iface));

            }

            // Cards are rebuilt: lock eth0 again while it is a bridge port.
            this.updateEth0BridgeState();

        } catch (err) {

            console.error("Failed to load network interfaces:", err);

        }

    },

    // ------------------------------------------------------------
    // Changes
    // ------------------------------------------------------------

    /** Returns [label, oldValue, newValue] for every tracked property. */
    getChangeRows(name) {

        const original = this.original[name];
        const current = this.interfaces[name];

        if (!original || !current)
            return null;

        return [
            ["Mode", original.mode, current.mode.value],
            ["IP", original.ip, current.ip.value],
            ["Subnet", original.subnet, current.subnet.value],
            ["Gateway", original.gateway, current.gateway.value],
            ["DNS", original.dns, current.dns.value]
        ];

    },

    hasChanges(name) {

        const rows = this.getChangeRows(name);

        return !!rows && rows.some(([, oldValue, newValue]) => oldValue !== newValue);

    },

    // ------------------------------------------------------------
    // Confirmation Modal
    // ------------------------------------------------------------

    openConfirmModal(name) {

        const modal = this.$("confirmModal");
        const body = this.$("modalBody");

        if (!modal || !body) {
            console.error("Confirmation modal elements not found.");
            return;
        }

        const rows = this.getChangeRows(name);

        if (!rows) {
            console.error("Interface data not found:", name);
            return;
        }

        this.pendingRole = null;
        this.pendingLan = null;

        this.$("networkModalTitle").textContent = "Apply Network Changes";
        this.$("networkModalIntro").textContent =
            "You're about to change the selected interface configuration.";

        body.innerHTML = "";

        const changes = rows.filter(([, oldValue, newValue]) => oldValue !== newValue);

        if (changes.length === 0) {

            const message = document.createElement("p");
            message.textContent = "No changes to apply.";
            body.appendChild(message);

        }

        for (const [label, oldValue, newValue] of changes) {

            const row = document.createElement("div");
            row.className = "modal-change";

            const labelElement = document.createElement("label");
            labelElement.textContent = label;

            const valueElement = document.createElement("strong");
            valueElement.textContent = `${oldValue} → ${newValue}`;

            row.append(labelElement, valueElement);
            body.appendChild(row);

        }

        modal.classList.remove("hidden");

    },

    closeConfirmModal() {

        const modal = this.$("confirmModal");

        if (modal)
            modal.classList.add("hidden");

    },

    // ------------------------------------------------------------
    // Apply Changes
    // ------------------------------------------------------------

    async applyChanges() {

        if (this.pendingRole)
            return this.applyRole();

        if (this.pendingLan)
            return this.applyLan();

        const name = this.pendingInterface;
        const card = name && this.interfaces[name];
        const modalConfirm = this.$("modalConfirm");

        if (!card || !modalConfirm)
            return;

        modalConfirm.disabled = true;
        modalConfirm.textContent = "Applying...";

        try {

            await this.post(
                "/api/network/stage",
                {
                    interface: name,
                    mode: card.mode.value,
                    ip: card.ip.value.trim(),
                    subnet: card.subnet.value.trim(),
                    gateway: card.gateway.value.trim(),
                    dns: card.dns.value.trim()
                },
                "Failed to stage network changes."
            );

            await this.post(
                "/api/network/apply",
                undefined,
                "Failed to apply network changes."
            );

            this.closeConfirmModal();

            await this.loadInterfaces();
            await this.updateStatus();

        } catch (err) {

            console.error("Network apply failed:", err);

            alert("Apply failed:\n\n" + err.message);

        } finally {

            modalConfirm.disabled = false;
            modalConfirm.textContent = "Apply";

        }

    },

    // ------------------------------------------------------------
    // eth0 LAN / WAN mode
    // ------------------------------------------------------------

    ROLE_INFO: {
        lan: "LAN port: devices plug in here. The modem is the internet uplink.",
        wan: "WAN port: the internet comes in here instead of through the modem."
    },

    addRoleToggle(header) {

        const wrapper = document.createElement("div");
        wrapper.className = "role-switch";

        wrapper.innerHTML = `
            <div class="role-toggle" role="group" aria-label="eth0 mode">
                <button type="button" class="role-option" data-role="lan">LAN</button>
                <button type="button" class="role-option" data-role="wan">WAN</button>
            </div>
            <p class="role-info"></p>
        `;

        wrapper.querySelectorAll(".role-option").forEach(button => {

            button.addEventListener("click", event => {

                event.preventDefault();
                event.stopPropagation();

                if (button.dataset.role !== this.eth0Role)
                    this.openRoleModal(button.dataset.role);

            });

        });

        header.appendChild(wrapper);

        // The card is not in the page yet.
        this.renderRoleToggle(wrapper);

    },

    renderRoleToggle(root = document) {

        root.querySelectorAll(".role-option[data-role]").forEach(button => {

            const active = button.dataset.role === this.eth0Role;

            button.classList.toggle("active", active);
            button.setAttribute("aria-pressed", String(active));

        });

        root.querySelectorAll(".role-info").forEach(info => {
            info.textContent = this.ROLE_INFO[this.eth0Role];
        });

    },

    openRoleModal(role) {

        const modal = this.$("confirmModal");
        const body = this.$("modalBody");

        this.pendingRole = role;
        this.pendingLan = null;
        this.pendingInterface = null;

        this.$("networkModalTitle").textContent =
            role === "wan" ? "Switch eth0 to WAN" : "Switch eth0 to LAN";

        this.$("networkModalIntro").textContent = role === "wan"
            ? "eth0 becomes the internet uplink. It gets its address from the network it is plugged into, and internet traffic leaves through it instead of the modem."
            : "eth0 becomes a LAN port again with its previous LAN address. Internet traffic goes back to the modem.";

        const rows = role === "wan"
            ? [
                ["Internet uplink", "wwan0 (modem) → eth0"],
                ["eth0 address", "→ DHCP client"],
                ["DHCP server on eth0", "paused"]
            ]
            : [
                ["Internet uplink", "eth0 → wwan0 (modem)"],
                ["eth0 address", "→ previous LAN settings"],
                ["DHCP server on eth0", "resumed"]
            ];

        body.innerHTML = "";

        for (const [label, value] of rows) {

            const row = document.createElement("div");
            row.className = "modal-change";

            const labelElement = document.createElement("label");
            labelElement.textContent = label;

            const valueElement = document.createElement("strong");
            valueElement.textContent = value;

            row.append(labelElement, valueElement);
            body.appendChild(row);

        }

        modal.classList.remove("hidden");

    },

    async applyRole() {

        const role = this.pendingRole;
        const modalConfirm = this.$("modalConfirm");

        modalConfirm.disabled = true;
        modalConfirm.textContent = "Applying...";

        try {

            await this.post(
                "/api/network/eth0-role",
                { role },
                "Failed to switch eth0."
            );

            this.eth0Role = role;
            this.pendingRole = null;

            this.closeConfirmModal();

            await this.loadInterfaces();
            await this.updateStatus();

        } catch (err) {

            console.error("eth0 mode switch failed:", err);

            alert("Switch failed:\n\n" + err.message);

        } finally {

            modalConfirm.disabled = false;
            modalConfirm.textContent = "Apply";

        }

    },

    // ------------------------------------------------------------
    // LAN bridge (br0)
    // ------------------------------------------------------------

    async loadLan() {

        const res = await this.get("/api/network/lan");

        if (!res || !res.ok)
            return;

        this.lan = await res.json();
        this.lanBridgeDraft = this.lan.settings.bridge;

        // null in the settings: every port.
        this.lanPortsDraft = this.lan.settings.ports
            ?? this.lan.candidates.map(c => c.name);

        this.renderLanPorts();

        this.$("lanIpInput").value = this.lan.settings.ip;
        this.$("lanSubnetInput").value = this.lan.settings.subnet;

        this.renderLan();
        this.updateEth0BridgeState();

    },

    lanChanged() {

        const s = this.lan?.settings;

        return !!s && (
            this.lanBridgeDraft !== s.bridge
            || this.$("lanIpInput").value.trim() !== s.ip
            || this.$("lanSubnetInput").value.trim() !== s.subnet
            || this.portsChanged()
        );

    },

    portsChanged() {

        const saved = this.lan.settings.ports ?? this.lan.candidates.map(c => c.name);

        return [...saved].sort().join() !== [...this.lanPortsDraft].sort().join();

    },

    /** One checkbox per Ethernet and Wi-Fi interface. */
    renderLanPorts() {

        const list = this.$("lanBridgePorts");

        list.innerHTML = "";

        this.lan.candidates.forEach(candidate => {

            const label = document.createElement("label");
            label.className = "check-item";

            const input = document.createElement("input");
            input.type = "checkbox";
            input.value = candidate.name;
            input.checked = this.lanPortsDraft.includes(candidate.name);

            input.addEventListener("change", () => {
                this.lanPortsDraft = [...list.querySelectorAll("input:checked")].map(i => i.value);
                this.renderLan();
            });

            const name = document.createElement("span");
            name.textContent = candidate.name;

            const kind = document.createElement("small");
            kind.textContent = candidate.name === "eth0" && this.eth0Role === "wan"
                ? "WAN, never bridged"
                : candidate.wireless ? "Wi-Fi" : "Ethernet";

            label.append(input, name, kind);
            list.appendChild(label);

        });

    },

    renderLan() {

        if (!this.lan)
            return;

        document.querySelectorAll(".lan-bridge-card .role-option").forEach(button => {
            const active = button.dataset.bridge === String(this.lanBridgeDraft);
            button.classList.toggle("active", active);
            button.setAttribute("aria-pressed", String(active));
        });

        this.$("lanBridgeInfo").textContent = this.lanBridgeDraft
            ? "The chosen ports share one network and one DHCP range."
            : "Each port works on its own; Wi-Fi gets no LAN address.";

        const ip = this.$("lanIpInput");
        const subnet = this.$("lanSubnetInput");

        ip.disabled = subnet.disabled = !this.lanBridgeDraft;

        this.$("lanBridgePorts").querySelectorAll("input").forEach(input => {
            input.disabled = !this.lanBridgeDraft;
        });

        const ipOk = this.isIPv4(ip.value.trim());
        const subnetOk = this.isSubnetMask(subnet.value.trim());

        this.setFieldState(ip, !this.lanBridgeDraft || ipOk, "Invalid IP.");
        this.setFieldState(subnet, !this.lanBridgeDraft || subnetOk, "Invalid subnet.");

        const { active, ports, address } = this.lan;

        this.$("lanBridgeStatus").textContent = active
            ? `br0 is up${address && address !== "Unknown" ? ` at ${address}` : ""}. Ports: ${ports.length ? ports.join(", ") : "none yet"}.`
            : this.lan.settings.bridge ? "br0 is not up yet." : "";

        this.$("lanBridgeApply").disabled =
            !this.lanChanged()
            || (this.lanBridgeDraft && !(ipOk && subnetOk && this.lanPortsDraft.length));

    },

    /** eth0 has no address of its own while it is a bridge port. */
    updateEth0BridgeState() {

        const card = this.interfaces.eth0;

        if (!card || !this.lan)
            return;

        const bridged = this.lan.settings.bridge && this.eth0Role === "lan"
            && (this.lan.settings.ports ?? ["eth0"]).includes("eth0");

        let note = card.node.querySelector(".bridge-note");

        if (bridged && !note) {
            note = document.createElement("p");
            note.className = "bridge-note";
            note.textContent = "Port of the LAN bridge (br0). Its address is set in the LAN card below.";
            card.node.querySelector(".interface-header > div").appendChild(note);
        }

        if (!bridged && note)
            note.remove();

        card.node.classList.toggle("bridged", bridged);

        card.mode.disabled = bridged;
        this.FIELDS.forEach(({ key }) => { card[key].disabled = bridged || card[key].disabled; });

        const trigger = card.node.querySelector(".chaos-select-trigger");

        if (trigger)
            trigger.disabled = bridged;

        if (bridged)
            card.save.disabled = true;

    },

    openLanModal() {

        const modal = this.$("confirmModal");
        const body = this.$("modalBody");

        const lan = {
            bridge: this.lanBridgeDraft,
            ip: this.$("lanIpInput").value.trim(),
            subnet: this.$("lanSubnetInput").value.trim(),
            ports: this.lanPortsDraft
        };

        this.pendingLan = lan;
        this.pendingRole = null;
        this.pendingInterface = null;

        const wasOn = this.lan.settings.bridge;
        const eth0Joins = this.eth0Role === "lan" && lan.ports.includes("eth0");
        const others = this.lan.candidates.map(c => c.name).filter(name => name !== "eth0");
        const eth0Address = this.lan.eth0_address;

        this.$("networkModalTitle").textContent =
            !lan.bridge ? "Turn off the LAN bridge" :
            wasOn ? "Change the LAN address" : "Turn on the LAN bridge";

        this.$("networkModalIntro").textContent = lan.bridge
            ? `The router's LAN address becomes ${lan.ip}. Devices get addresses in this network from DHCP.`
            : "Ethernet and Wi-Fi go back to working on their own.";

        const rows = lan.bridge
            ? [
                ["LAN (br0)", `${lan.ip} / ${lan.subnet}`],
                ["eth0", eth0Joins
                    ? `joins br0${eth0Address && eth0Address !== "Unknown" && !wasOn ? ` (drops ${eth0Address})` : ""}`
                    : this.eth0Role === "wan" ? "stays the WAN" : "keeps its own connection"],
                ...others.map(name => [name, lan.ports.includes(name) ? "joins br0" : "keeps its own network"]),
                ["DHCP / DNS", "served on br0"]
            ]
            : [
                ["eth0", "gets its own connection back"],
                ["Wi-Fi access points", "leave br0"],
                ["br0", "removed"]
            ];

        body.innerHTML = "";

        for (const [label, value] of rows) {

            const row = document.createElement("div");
            row.className = "modal-change";

            const labelElement = document.createElement("label");
            labelElement.textContent = label;

            const valueElement = document.createElement("strong");
            valueElement.textContent = value;

            row.append(labelElement, valueElement);
            body.appendChild(row);

        }

        if (lan.bridge && eth0Joins && !wasOn) {

            const warning = document.createElement("p");
            warning.className = "modal-note";
            warning.textContent = "If eth0 is plugged into another router (your home network), switch eth0 to WAN first, or this connection will drop.";
            body.appendChild(warning);

        }

        modal.classList.remove("hidden");

    },

    async applyLan() {

        const lan = this.pendingLan;
        const modalConfirm = this.$("modalConfirm");

        modalConfirm.disabled = true;
        modalConfirm.textContent = "Applying...";

        try {

            await this.post("/api/network/lan", lan, "Failed to apply the LAN settings.");

            this.pendingLan = null;

            this.closeConfirmModal();

            await this.loadInterfaces();
            await this.loadLan();
            await this.updateStatus();

        } catch (err) {

            console.error("LAN bridge apply failed:", err);

            alert("Apply failed:\n\n" + err.message);

        } finally {

            modalConfirm.disabled = false;
            modalConfirm.textContent = "Apply";

        }

    },

    initLan() {

        document.querySelectorAll(".lan-bridge-card .role-option").forEach(button => {
            button.addEventListener("click", event => {
                event.preventDefault();
                this.lanBridgeDraft = button.dataset.bridge === "true";
                this.renderLan();
            });
        });

        ["lanIpInput", "lanSubnetInput"].forEach(id => {
            this.$(id).addEventListener("input", () => this.renderLan());
        });

        this.$("lanBridgeApply").addEventListener("click", event => {
            event.preventDefault();
            if (!this.$("lanBridgeApply").disabled) this.openLanModal();
        });

        this.loadLan();

    },

    // ------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------

    init() {

        this.updateStatus();
        this.loadInterfaces().then(() => this.initLan());

        this.timer = setInterval(() => this.updateStatus(), 3000);

        const modal = this.$("confirmModal");
        const modalClose = this.$("modalClose");
        const modalCancel = this.$("modalCancel");
        const modalConfirm = this.$("modalConfirm");

        if (modalClose)
            modalClose.onclick = () => this.closeConfirmModal();

        if (modalCancel)
            modalCancel.onclick = () => this.closeConfirmModal();

        // Click on the backdrop closes the modal.
        if (modal) {
            modal.onclick = event => {
                if (event.target === modal)
                    this.closeConfirmModal();
            };
        }

        if (modalConfirm) {
            modalConfirm.onclick = event => {
                event.preventDefault();
                this.applyChanges();
            };
        }

        // Close custom dropdowns when clicking elsewhere.
        this.outsideClickHandler = event => {

            document
                .querySelectorAll(".chaos-select.open")
                .forEach(wrapper => {
                    if (!wrapper.contains(event.target))
                        this.closeSelect(wrapper);
                });

        };

        document.addEventListener("click", this.outsideClickHandler);

    },

    destroy() {

        if (this.timer) {
            clearInterval(this.timer);
            this.timer = null;
        }

        if (this.outsideClickHandler) {
            document.removeEventListener("click", this.outsideClickHandler);
            this.outsideClickHandler = null;
        }

    }

};