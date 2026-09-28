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
            .map(Number)
            .map(n => n.toString(2).padStart(8, "0"))
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

        // WWAN is completely read-only.
        if (name === "wwan0") {

            [
                card.ip,
                card.subnet,
                card.gateway,
                card.dns
            ].forEach(field => {

                this.setFieldState(field, true);

            });

            return true;

        }

        // DHCP does not require editable network values.
        if (card.mode.value === "DHCP Client") {

            [
                card.ip,
                card.subnet,
                card.gateway,
                card.dns
            ].forEach(field => {

                this.setFieldState(field, true);

            });

            return true;

        }

        const ipOK = this.isIPv4(card.ip.value);
        const subnetOK = this.isSubnetMask(card.subnet.value);
        const gatewayOK = this.isIPv4(card.gateway.value);
        const dnsOK = this.isIPv4(card.dns.value);

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

        return (
            ipOK &&
            subnetOK &&
            gatewayOK &&
            dnsOK
        );

    },

    // ------------------------------------------------------------
    // Custom Dropdown
    // ------------------------------------------------------------

    setupCustomSelect(node, interfaceName) {

        const wrapper = node.querySelector(".chaos-select");
        const trigger = node.querySelector(".chaos-select-trigger");
        const value = node.querySelector(".chaos-select-value");
        const menu = node.querySelector(".chaos-select-menu");
        const nativeSelect = node.querySelector(".interface-mode-select");
        const options = node.querySelectorAll(".chaos-select-option");

        if (
            !wrapper ||
            !trigger ||
            !value ||
            !menu ||
            !nativeSelect
        ) {
            return;
        }

        const close = () => {

            wrapper.classList.remove("open");

            trigger.setAttribute(
                "aria-expanded",
                "false"
            );

        };

        const updateVisual = () => {

            value.textContent = nativeSelect.value;

            options.forEach(option => {

                const selected =
                    option.dataset.value === nativeSelect.value;

                option.classList.toggle(
                    "selected",
                    selected
                );

                option.setAttribute(
                    "aria-selected",
                    selected ? "true" : "false"
                );

            });

        };

        trigger.addEventListener("click", event => {

            event.preventDefault();
            event.stopPropagation();

            if (trigger.disabled)
                return;

            const isOpen =
                wrapper.classList.contains("open");

            document
                .querySelectorAll(".chaos-select.open")
                .forEach(other => {

                    if (other !== wrapper)
                        other.classList.remove("open");

                });

            if (isOpen) {

                close();

            } else {

                wrapper.classList.add("open");

                trigger.setAttribute(
                    "aria-expanded",
                    "true"
                );

            }

        });

        options.forEach(option => {

            option.addEventListener("click", event => {

                event.preventDefault();
                event.stopPropagation();

                if (trigger.disabled)
                    return;

                const newValue =
                    option.dataset.value;

                nativeSelect.value = newValue;

                updateVisual();

                nativeSelect.dispatchEvent(
                    new Event("change", {
                        bubbles: true
                    })
                );

                close();

            });

        });

        nativeSelect.addEventListener("change", () => {

            updateVisual();

        });

        updateVisual();

    },

    // ------------------------------------------------------------
    // Top Status
    // ------------------------------------------------------------

    async updateStatus() {

        try {

            const res =
                await fetch("/api/network");

            if (res.status === 401) {

                location.href = "/login";
                return;

            }

            if (!res.ok)
                return;

            const data =
                await res.json();

            const wanStatus =
                document.getElementById("wanStatus");

            const wanInterface =
                document.getElementById("wanInterface");

            const wanType =
                document.getElementById("wanType");

            const wanGateway =
                document.getElementById("wanGateway");

            if (wanStatus)
                wanStatus.textContent = data.wan ?? "--";

            if (wanInterface)
                wanInterface.textContent =
                    data.interface ?? "--";

            if (wanType)
                wanType.textContent =
                    data.connection ?? "--";

            if (wanGateway)
                wanGateway.textContent =
                    data.gateway ?? "--";

        } catch (err) {

            console.error(
                "Network status update failed:",
                err
            );

        }

    },

    // ------------------------------------------------------------
    // Interface Cards
    // ------------------------------------------------------------

    async loadInterfaces() {

        const container =
            document.getElementById(
                "interfaceContainer"
            );

        const template =
            document.getElementById(
                "interfaceTemplate"
            );

        if (!container || !template)
            return;

        try {

            const res =
                await fetch(
                    "/api/network/interfaces"
                );

            if (res.status === 401) {

                location.href = "/login";
                return;

            }

            if (!res.ok)
                throw new Error(
                    "Failed to load interfaces."
                );

            const interfaces =
                await res.json();

            container.innerHTML = "";

            this.interfaces = {};
            this.original = {};

            for (const iface of interfaces) {

                this.original[iface.name] =
                    structuredClone(iface);

                const node =
                    template.content
                        .firstElementChild
                        .cloneNode(true);

                const name =
                    iface.name;

                const modeLabel =
                    node.querySelector(
                        ".interface-mode"
                    );

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

                node.querySelector(
                    ".interface-name"
                ).textContent = name;

                node.querySelector(
                    ".interface-type"
                ).textContent =
                    iface.type ?? "";

                modeLabel.textContent =
                    iface.mode ?? "";

                mode.value =
                    iface.mode === "Static"
                        ? "Static"
                        : "DHCP Client";

                ip.value =
                    iface.ip ?? "";

                subnet.value =
                    iface.subnet ?? "";

                gateway.value =
                    iface.gateway ?? "";

                dns.value =
                    iface.dns ?? "";

                this.interfaces[name] = {

                    node,
                    mode,
                    ip,
                    subnet,
                    gateway,
                    dns,
                    save,
                    modeLabel

                };

                // ------------------------------------------------
                // Custom dropdown
                // ------------------------------------------------

                this.setupCustomSelect(
                    node,
                    name
                );

                // ------------------------------------------------
                // State updater
                // ------------------------------------------------

                const updateState = () => {

                    const isWWAN =
                        name === "wwan0";

                    const isStatic =
                        mode.value === "Static";

                    modeLabel.textContent =
                        mode.value;

                    // wwan0 is completely read-only.
                    mode.disabled =
                        isWWAN;

                    const editable =
                        !isWWAN &&
                        isStatic;

                    ip.disabled =
                        !editable;

                    subnet.disabled =
                        !editable;

                    gateway.disabled =
                        !editable;

                    dns.disabled =
                        !editable;

                    // Keep visible custom dropdown disabled
                    // together with the native select.
                    const trigger =
                        node.querySelector(
                            ".chaos-select-trigger"
                        );

                    if (trigger) {

                        trigger.disabled =
                            isWWAN;

                    }

                    const changed =
                        this.hasChanges(name);

                    const valid =
                        this.validateCard(name);

                    // Apply only works when there is
                    // actually something to apply.
                    save.disabled =
                        isWWAN ||
                        !changed ||
                        !valid;

                };

                // ------------------------------------------------
                // Field listeners
                // ------------------------------------------------

                mode.addEventListener(
                    "change",
                    updateState
                );

                ip.addEventListener(
                    "input",
                    updateState
                );

                subnet.addEventListener(
                    "input",
                    updateState
                );

                gateway.addEventListener(
                    "input",
                    updateState
                );

                dns.addEventListener(
                    "input",
                    updateState
                );

                // ------------------------------------------------
                // APPLY BUTTON
                // ------------------------------------------------

                save.addEventListener(
                    "click",
                    event => {

                        event.preventDefault();
                        event.stopPropagation();

                        if (save.disabled)
                            return;

                        console.log(
                            "Apply clicked:",
                            name
                        );

                        this.pendingInterface =
                            name;

                        this.openConfirmModal(
                            name
                        );

                    }
                );

                updateState();

                container.appendChild(node);

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

        const modal =
            document.getElementById(
                "confirmModal"
            );

        const body =
            document.getElementById(
                "modalBody"
            );

        if (!modal || !body) {

            console.error(
                "Confirmation modal elements not found."
            );

            return;

        }

        const original =
            this.original[name];

        const current =
            this.interfaces[name];

        if (!original || !current) {

            console.error(
                "Interface data not found:",
                name
            );

            return;

        }

        body.innerHTML = "";

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

        let changeCount = 0;

        for (const [
            label,
            oldValue,
            newValue
        ] of changes) {

            if (oldValue === newValue)
                continue;

            changeCount++;

            const row =
                document.createElement("div");

            row.className =
                "modal-change";

            const labelElement =
                document.createElement("label");

            labelElement.textContent =
                label;

            const valueElement =
                document.createElement("strong");

            valueElement.textContent =
                `${oldValue} → ${newValue}`;

            row.appendChild(
                labelElement
            );

            row.appendChild(
                valueElement
            );

            body.appendChild(row);

        }

        if (changeCount === 0) {

            const message =
                document.createElement("p");

            message.textContent =
                "No changes to apply.";

            body.appendChild(message);

        }

        modal.classList.remove("hidden");

    },

    closeConfirmModal() {

        const modal =
            document.getElementById(
                "confirmModal"
            );

        if (modal)
            modal.classList.add("hidden");

    },

    // ------------------------------------------------------------
    // Apply Changes
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

        const modalConfirm =
            document.getElementById(
                "modalConfirm"
            );

        if (!modalConfirm)
            return;

        modalConfirm.disabled = true;
        modalConfirm.textContent =
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

                        body: JSON.stringify({

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

                        })

                    }
                );

            let stageData = {};

            try {

                stageData =
                    await stageRes.json();

            } catch (_) {}

            if (!stageRes.ok) {

                throw new Error(
                    stageData.message ||
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

            let applyData = {};

            try {

                applyData =
                    await applyRes.json();

            } catch (_) {}

            if (!applyRes.ok) {

                throw new Error(
                    applyData.message ||
                    "Failed to apply network changes."
                );

            }

            this.closeConfirmModal();

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

            modalConfirm.disabled = false;

            modalConfirm.textContent =
                "Apply";

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

        const modal =
            document.getElementById(
                "confirmModal"
            );

        const modalClose =
            document.getElementById(
                "modalClose"
            );

        const modalCancel =
            document.getElementById(
                "modalCancel"
            );

        const modalConfirm =
            document.getElementById(
                "modalConfirm"
            );

        if (modalClose) {

            modalClose.onclick = () =>
                this.closeConfirmModal();

        }

        if (modalCancel) {

            modalCancel.onclick = () =>
                this.closeConfirmModal();

        }

        if (modal) {

            modal.onclick = event => {

                if (
                    event.target === modal
                ) {

                    this.closeConfirmModal();

                }

            };

        }

        if (modalConfirm) {

            modalConfirm.onclick = event => {

                event.preventDefault();

                this.applyChanges();

            };

        }

        // Close custom dropdowns when clicking elsewhere.
        document.addEventListener(
            "click",
            event => {

                document
                    .querySelectorAll(
                        ".chaos-select.open"
                    )
                    .forEach(wrapper => {

                        if (
                            !wrapper.contains(
                                event.target
                            )
                        ) {

                            wrapper.classList.remove(
                                "open"
                            );

                            const trigger =
                                wrapper.querySelector(
                                    ".chaos-select-trigger"
                                );

                            if (trigger) {

                                trigger.setAttribute(
                                    "aria-expanded",
                                    "false"
                                );

                            }

                        }

                    });

            }
        );

    },

    destroy() {

        if (this.timer) {

            clearInterval(
                this.timer
            );

            this.timer = null;

        }

    }

};