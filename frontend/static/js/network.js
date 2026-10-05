window.Page = window.Page || {};

window.Page.network = {

    timer: null,
    interfaces: {},
    original: {},
    pendingInterface: null,
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
    // Lifecycle
    // ------------------------------------------------------------

    init() {

        this.updateStatus();
        this.loadInterfaces();

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