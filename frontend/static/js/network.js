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

        if (!card) return false;

        /*
         * WWAN is completely read-only.
         */
        if (name === "wwan0") {

            [
                card.ip,
                card.subnet,
                card.gateway,
                card.dns
            ].forEach(field => this.setFieldState(field, true));

            return false;

        }

        /*
         * DHCP Client:
         * IP, subnet, gateway and DNS are supplied automatically.
         */
        if (card.mode.value === "DHCP Client") {

            [
                card.ip,
                card.subnet,
                card.gateway,
                card.dns
            ].forEach(field => this.setFieldState(field, true));

            return true;

        }

        const ipOK = this.isIPv4(card.ip.value.trim());
        const subnetOK = this.isSubnetMask(card.subnet.value.trim());
        const gatewayOK = this.isIPv4(card.gateway.value.trim());
        const dnsOK = this.isIPv4(card.dns.value.trim());

        this.setFieldState(
            card.ip,
            ipOK,
            "Invalid IP."
        );

        this.setFieldState(
            card.subnet,
            subnetOK,
            "Invalid subnet."
        );

        this.setFieldState(
            card.gateway,
            gatewayOK,
            "Invalid gateway."
        );

        this.setFieldState(
            card.dns,
            dnsOK,
            "Invalid DNS."
        );

        return ipOK &&
               subnetOK &&
               gatewayOK &&
               dnsOK;

    },

    // ------------------------------------------------------------
    // Top Status
    // ------------------------------------------------------------

    async updateStatus() {

        try {

            const res = await fetch("/api/network");

            if (res.status === 401) {

                location.href = "/login";
                return;

            }

            if (!res.ok)
                return;

            const data = await res.json();

            wanStatus.textContent = data.wan;
            wanInterface.textContent = data.interface;
            wanType.textContent = data.connection;
            wanGateway.textContent = data.gateway;

        } catch (err) {

            console.error("Network status update failed:", err);

        }

    },

    // ------------------------------------------------------------
    // Custom Dropdown
    // ------------------------------------------------------------

    setupCustomSelect(cardData) {

        const {
            name,
            mode,
            chaosSelect,
            trigger,
            valueLabel,
            options
        } = cardData;

        if (!chaosSelect || !trigger)
            return;

        const isWWAN = name === "wwan0";

        const closeMenu = () => {

            chaosSelect.classList.remove("open");
            trigger.setAttribute("aria-expanded", "false");

        };

        const updateVisualState = () => {

            valueLabel.textContent = mode.value;

            options.forEach(option => {

                const selected =
                    option.dataset.value === mode.value;

                option.classList.toggle(
                    "selected",
                    selected
                );

            });

        };

        /*
         * WWAN:
         * Disable both the real select and the visible custom
         * dropdown trigger.
         */
        trigger.disabled = isWWAN;
        mode.disabled = isWWAN;

        if (isWWAN)
            closeMenu();

        updateVisualState();

        /*
         * Do not attach click behaviour to a disabled selector.
         */
        trigger.onclick = e => {

            e.preventDefault();

            if (trigger.disabled)
                return;

            const open =
                chaosSelect.classList.contains("open");

            /*
             * Close any other custom selectors.
             */
            document
                .querySelectorAll(".chaos-select.open")
                .forEach(select => {

                    if (select !== chaosSelect)
                        select.classList.remove("open");

                });

            chaosSelect.classList.toggle(
                "open",
                !open
            );

            trigger.setAttribute(
                "aria-expanded",
                String(!open)
            );

        };

        options.forEach(option => {

            option.onclick = e => {

                e.preventDefault();

                if (trigger.disabled)
                    return;

                const value = option.dataset.value;

                mode.value = value;

                mode.dispatchEvent(
                    new Event("change", {
                        bubbles: true
                    })
                );

                updateVisualState();

                closeMenu();

            };

        });

        return {
            updateVisualState,
            closeMenu
        };

    },

    // ------------------------------------------------------------
    // Interface Cards
    // ------------------------------------------------------------

    async loadInterfaces() {

        try {

            const res = await fetch(
                "/api/network/interfaces"
            );

            if (!res.ok)
                throw new Error(
                    `HTTP ${res.status}`
                );

            const interfaces = await res.json();

            interfaceContainer.innerHTML = "";

            this.interfaces = {};
            this.original = {};

            for (const iface of interfaces) {

                this.original[iface.name] =
                    structuredClone(iface);

                const node =
                    interfaceTemplate
                        .content
                        .firstElementChild
                        .cloneNode(true);

                const modeLabel =
                    node.querySelector(
                        ".interface-mode"
                    );

                const chaosSelect =
                    node.querySelector(
                        ".chaos-select"
                    );

                const trigger =
                    node.querySelector(
                        ".chaos-select-trigger"
                    );

                const valueLabel =
                    node.querySelector(
                        ".chaos-select-value"
                    );

                const options =
                    node.querySelectorAll(
                        ".chaos-select-option"
                    );

                node.querySelector(
                    ".interface-name"
                ).textContent = iface.name;

                node.querySelector(
                    ".interface-type"
                ).textContent = iface.type;

                modeLabel.textContent =
                    iface.mode;

                const mode =
                    node.querySelector(
                        ".interface-mode-select"
                    );

                const ip =
                    node.querySelector(
                        ".interface-ip"
                    );

                const subnet =
                    node.querySelector(
                        ".interface-subnet"
                    );

                const gateway =
                    node.querySelector(
                        ".interface-gateway"
                    );

                const dns =
                    node.querySelector(
                        ".interface-dns"
                    );

                const save =
                    node.querySelector(
                        ".interface-save"
                    );

                mode.value = iface.mode;
                ip.value = iface.ip || "";
                subnet.value = iface.subnet || "";
                gateway.value = iface.gateway || "";
                dns.value = iface.dns || "";

                this.interfaces[iface.name] = {

                    node,
                    mode,
                    ip,
                    subnet,
                    gateway,
                    dns,
                    save,
                    modeLabel,
                    chaosSelect,
                    trigger,
                    valueLabel,
                    options

                };

                const updateState = () => {

                    const isWWAN =
                        iface.name === "wwan0";

                    const isStatic =
                        mode.value === "Static";

                    modeLabel.textContent =
                        mode.value;

                    /*
                     * Only eth0 can be changed.
                     */
                    mode.disabled = isWWAN;
                    trigger.disabled = isWWAN;

                    /*
                     * DHCP Client:
                     * everything is read-only.
                     *
                     * Static:
                     * all network values become editable.
                     */
                    const editable =
                        !isWWAN && isStatic;

                    ip.disabled = !editable;
                    subnet.disabled = !editable;
                    gateway.disabled = !editable;
                    dns.disabled = !editable;

                    /*
                     * Make sure a WWAN dropdown can never
                     * remain visually open.
                     */
                    if (isWWAN) {

                        chaosSelect.classList.remove(
                            "open"
                        );

                        trigger.setAttribute(
                            "aria-expanded",
                            "false"
                        );

                    }

                    const changed =
                        this.hasChanges(
                            iface.name
                        );

                    const valid =
                        this.validateCard(
                            iface.name
                        );

                    /*
                     * WWAN never gets an Apply button
                     * because it is not configurable.
                     */
                    save.disabled =
                        isWWAN ||
                        !(changed && valid);

                };

                /*
                 * Custom dropdown.
                 */
                this.setupCustomSelect({

                    name: iface.name,
                    mode,
                    chaosSelect,
                    trigger,
                    valueLabel,
                    options

                });

                /*
                 * Inputs.
                 */
                [
                    ip,
                    subnet,
                    gateway,
                    dns
                ].forEach(el => {

                    el.addEventListener(
                        "input",
                        updateState
                    );

                });

                mode.addEventListener(
                    "change",
                    updateState
                );

                /*
                 * Apply button.
                 */
                save.onclick = () => {

                    if (save.disabled)
                        return;

                    this.pendingInterface =
                        iface.name;

                    this.openConfirmModal(
                        iface.name
                    );

                };

                updateState();

                interfaceContainer.appendChild(
                    node
                );

            }

        } catch (err) {

            console.error(
                "Failed to load network interfaces:",
                err
            );

        }

    },

    // ------------------------------------------------------------
    // Changes
    // ------------------------------------------------------------

    hasChanges(name) {

        const original =
            this.original[name];

        const current =
            this.interfaces[name];

        if (!original || !current)
            return false;

        return (
            original.mode !==
                current.mode.value ||

            original.ip !==
                current.ip.value ||

            original.subnet !==
                current.subnet.value ||

            original.gateway !==
                current.gateway.value ||

            original.dns !==
                current.dns.value
        );

    },

    // ------------------------------------------------------------
    // Confirmation Modal
    // ------------------------------------------------------------

    openConfirmModal(name) {

        const original =
            this.original[name];

        const current =
            this.interfaces[name];

        if (!original || !current)
            return;

        modalBody.innerHTML = "";

        const changes = [

            [
                "Mode",
                original.mode,
                current.mode.value
            ],

            [
                "IP",
                original.ip,
                current.ip.value
            ],

            [
                "Subnet",
                original.subnet,
                current.subnet.value
            ],

            [
                "Gateway",
                original.gateway,
                current.gateway.value
            ],

            [
                "DNS",
                original.dns,
                current.dns.value
            ]

        ];

        for (
            const [label, oldValue, newValue]
            of changes
        ) {

            if (oldValue === newValue)
                continue;

            const row =
                document.createElement(
                    "div"
                );

            row.className =
                "modal-change";

            row.innerHTML = `
                <label>${label}</label>
                <strong></strong>
            `;

            row.querySelector(
                "strong"
            ).textContent =
                `${oldValue} → ${newValue}`;

            modalBody.appendChild(row);

        }

        confirmModal.classList.remove(
            "hidden"
        );

    },

    closeConfirmModal() {

        confirmModal.classList.add(
            "hidden"
        );

        this.pendingInterface = null;

    },

    // ------------------------------------------------------------
    // Apply
    // ------------------------------------------------------------

    async applyChanges() {

        const name =
            this.pendingInterface;

        if (!name)
            return;

        const card =
            this.interfaces[name];

        if (!card)
            return;

        const payload = {

            interface: name,

            mode:
                card.mode.value,

            ip:
                card.ip.value.trim(),

            subnet:
                card.subnet.value.trim(),

            gateway:
                card.gateway.value.trim(),

            dns:
                card.dns.value.trim()

        };

        const button =
            modalConfirm;

        button.disabled = true;
        button.textContent =
            "Applying...";

        try {

            const stageRes =
                await fetch(
                    "/api/network/stage",
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body:
                            JSON.stringify(
                                payload
                            )
                    }
                );

            if (!stageRes.ok) {

                let error;

                try {
                    error =
                        await stageRes.json();
                } catch {
                    error = {};
                }

                throw new Error(
                    error.message ||
                    "Failed to stage network changes."
                );

            }

            const applyRes =
                await fetch(
                    "/api/network/apply",
                    {
                        method: "POST"
                    }
                );

            let data = {};

            try {
                data =
                    await applyRes.json();
            } catch {
                // Ignore empty response bodies.
            }

            if (!applyRes.ok) {

                throw new Error(
                    data.message ||
                    "Apply failed."
                );

            }

            this.closeConfirmModal();

            /*
             * Reload the actual values from the backend.
             */
            await this.loadInterfaces();
            await this.updateStatus();

        } catch (err) {

            console.error(
                "Network apply failed:",
                err
            );

            alert(
                "Apply failed:\n\n" +
                err.message
            );

        } finally {

            button.disabled = false;
            button.textContent = "Apply";

        }

    },

    // ------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------

    init() {

        this.updateStatus();

        this.loadInterfaces();

        this.timer =
            setInterval(
                () => this.updateStatus(),
                3000
            );

        modalClose.onclick =
            () => this.closeConfirmModal();

        modalCancel.onclick =
            () => this.closeConfirmModal();

        confirmModal.onclick = e => {

            if (e.target === confirmModal)
                this.closeConfirmModal();

        };

        modalConfirm.onclick =
            () => this.applyChanges();

        /*
         * Close custom dropdowns when clicking elsewhere.
         */
        document.addEventListener(
            "click",
            e => {

                if (
                    e.target.closest(
                        ".chaos-select"
                    )
                )
                    return;

                document
                    .querySelectorAll(
                        ".chaos-select.open"
                    )
                    .forEach(select => {

                        select.classList.remove(
                            "open"
                        );

                        const trigger =
                            select.querySelector(
                                ".chaos-select-trigger"
                            );

                        if (trigger) {

                            trigger.setAttribute(
                                "aria-expanded",
                                "false"
                            );

                        }

                    });

            }
        );

    },

    destroy() {

        clearInterval(this.timer);

    }

};