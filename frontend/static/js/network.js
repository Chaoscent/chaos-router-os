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

        let error =
            input.parentElement.querySelector(".field-error");

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

        // WWAN is modem managed.
        if (name === "wwan0") {
            return true;
        }

        // DHCP requires no manual address validation.
        if (card.mode.value === "DHCP Client") {
            return true;
        }

        const ipOK =
            this.isIPv4(card.ip.value.trim());

        const subnetOK =
            this.isSubnetMask(card.subnet.value.trim());

        const gatewayOK =
            this.isIPv4(card.gateway.value.trim());

        const dnsOK =
            this.isIPv4(card.dns.value.trim());

        this.setFieldState(
            card.ip,
            ipOK,
            "Invalid IP address."
        );

        this.setFieldState(
            card.subnet,
            subnetOK,
            "Invalid subnet mask."
        );

        this.setFieldState(
            card.gateway,
            gatewayOK,
            "Invalid gateway."
        );

        this.setFieldState(
            card.dns,
            dnsOK,
            "Invalid DNS server."
        );

        return (
            ipOK &&
            subnetOK &&
            gatewayOK &&
            dnsOK
        );

    },

    // ------------------------------------------------------------
    // Status
    // ------------------------------------------------------------

    async updateStatus() {

        try {

            const res =
                await fetch("/api/network");

            if (res.status === 401) {
                location.href = "/login";
                return;
            }

            const data =
                await res.json();

            document.getElementById("wanStatus").textContent =
                data.wan;

            document.getElementById("wanInterface").textContent =
                data.interface;

            document.getElementById("wanType").textContent =
                data.connection;

            document.getElementById("wanGateway").textContent =
                data.gateway;

        } catch (err) {

            console.error(
                "Network status update failed:",
                err
            );

        }

    },

    // ------------------------------------------------------------
    // Custom Dropdown
    // ------------------------------------------------------------

    setupDropdown(card, ifaceName) {

        const wrapper =
            card.node.querySelector(".chaos-select");

        const trigger =
            wrapper.querySelector(".chaos-select-trigger");

        const value =
            wrapper.querySelector(".chaos-select-value");

        const menu =
            wrapper.querySelector(".chaos-select-menu");

        const options =
            wrapper.querySelectorAll(".chaos-select-option");

        const select =
            wrapper.querySelector(".interface-mode-select");

        const setValue = newValue => {

            select.value = newValue;

            value.textContent = newValue;

            options.forEach(option => {

                const selected =
                    option.dataset.value === newValue;

                option.classList.toggle(
                    "selected",
                    selected
                );

            });

            card.modeLabel.textContent =
                newValue;

            this.updateInterfaceState(ifaceName);

        };

        trigger.addEventListener("click", event => {

            event.stopPropagation();

            if (trigger.disabled) return;

            const open =
                wrapper.classList.toggle("open");

            trigger.setAttribute(
                "aria-expanded",
                open ? "true" : "false"
            );

        });

        options.forEach(option => {

            option.addEventListener("click", event => {

                event.stopPropagation();

                setValue(
                    option.dataset.value
                );

                wrapper.classList.remove("open");

                trigger.setAttribute(
                    "aria-expanded",
                    "false"
                );

            });

        });

        card.setMode = setValue;

        setValue(select.value);

    },

    // ------------------------------------------------------------
    // Interface State
    // ------------------------------------------------------------

    updateInterfaceState(name) {

        const card =
            this.interfaces[name];

        if (!card) return;

        const mode =
            card.mode.value;

        // WWAN is completely read-only.
        if (name === "wwan0") {

            card.mode.disabled = true;

            card.ip.disabled = true;
            card.subnet.disabled = true;
            card.gateway.disabled = true;
            card.dns.disabled = true;

            card.save.disabled = true;

            card.modeLabel.textContent =
                "Modem managed";

            return;

        }

        // DHCP Client
        if (mode === "DHCP Client") {

            card.ip.disabled = true;
            card.subnet.disabled = true;
            card.gateway.disabled = true;
            card.dns.disabled = true;

        }

        // Static
        else {

            card.ip.disabled = false;
            card.subnet.disabled = false;
            card.gateway.disabled = false;
            card.dns.disabled = false;

        }

        const changed =
            this.hasChanges(name);

        const valid =
            this.validateCard(name);

        card.save.disabled =
            !(changed && valid);

    },

    // ------------------------------------------------------------
    // Interfaces
    // ------------------------------------------------------------

    async loadInterfaces() {

        try {

            const res =
                await fetch("/api/network/interfaces");

            if (res.status === 401) {
                location.href = "/login";
                return;
            }

            if (!res.ok) {
                throw new Error(
                    "Failed to load interfaces."
                );
            }

            const interfaces =
                await res.json();

            const container =
                document.getElementById(
                    "interfaceContainer"
                );

            const template =
                document.getElementById(
                    "interfaceTemplate"
                );

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
                ).textContent =
                    iface.name;

                node.querySelector(
                    ".interface-type"
                ).textContent =
                    iface.type;

                modeLabel.textContent =
                    iface.mode;

                mode.value =
                    iface.mode;

                ip.value =
                    iface.ip || "";

                subnet.value =
                    iface.subnet || "";

                gateway.value =
                    iface.gateway || "";

                dns.value =
                    iface.dns || "";

                const card = {

                    node,

                    mode,

                    ip,

                    subnet,

                    gateway,

                    dns,

                    save,

                    modeLabel,

                    setMode: null

                };

                this.interfaces[iface.name] =
                    card;

                // Custom dropdown.
                this.setupDropdown(
                    card,
                    iface.name
                );

                // Input changes.
                [
                    ip,
                    subnet,
                    gateway,
                    dns
                ].forEach(input => {

                    input.addEventListener(
                        "input",
                        () => {

                            this.updateInterfaceState(
                                iface.name
                            );

                        }
                    );

                });

                save.addEventListener(
                    "click",
                    event => {

                        event.preventDefault();

                        if (save.disabled)
                            return;

                        if (!this.validateCard(
                            iface.name
                        )) {
                            return;
                        }

                        this.pendingInterface =
                            iface.name;

                        this.openConfirmModal(
                            iface.name
                        );

                    }
                );

                container.appendChild(node);

                this.updateInterfaceState(
                    iface.name
                );

            }

        } catch (err) {

            console.error(
                "Failed to load interfaces:",
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
            current.ip.value.trim() ||

            original.subnet !==
            current.subnet.value.trim() ||

            original.gateway !==
            current.gateway.value.trim() ||

            original.dns !==
            current.dns.value.trim()

        );

    },

    // ------------------------------------------------------------
    // Modal
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

        body.innerHTML = "";

        const original =
            this.original[name];

        const current =
            this.interfaces[name];

        const changes = [

            [
                "Mode",
                original.mode,
                current.mode.value
            ],

            [
                "IP",
                original.ip,
                current.ip.value.trim()
            ],

            [
                "Subnet",
                original.subnet,
                current.subnet.value.trim()
            ],

            [
                "Gateway",
                original.gateway,
                current.gateway.value.trim()
            ],

            [
                "DNS",
                original.dns,
                current.dns.value.trim()
            ]

        ];

        for (
            const [
                label,
                oldValue,
                newValue
            ] of changes
        ) {

            if (oldValue === newValue)
                continue;

            body.insertAdjacentHTML(
                "beforeend",
                `
                <div class="modal-change">
                    <label>${label}</label>
                    <strong>
                        ${oldValue} → ${newValue}
                    </strong>
                </div>
                `
            );

        }

        modal.classList.remove(
            "hidden"
        );

    },

    closeConfirmModal() {

        document
            .getElementById("confirmModal")
            .classList.add("hidden");

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

        const modalConfirm =
            document.getElementById(
                "modalConfirm"
            );

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

                        body:
                            JSON.stringify(payload)
                    }
                );

            const stageData =
                await stageRes.json();

            if (
                !stageRes.ok ||
                !stageData.success
            ) {

                throw new Error(
                    stageData.message ||
                    "Failed to stage configuration."
                );

            }

            const applyRes =
                await fetch(
                    "/api/network/apply",
                    {
                        method: "POST"
                    }
                );

            const applyData =
                await applyRes.json();

            if (
                !applyRes.ok ||
                !applyData.success
            ) {

                throw new Error(
                    applyData.message ||
                    "Failed to apply configuration."
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

            modalConfirm.disabled =
                false;

            modalConfirm.textContent =
                "Apply";

            this.pendingInterface =
                null;

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

        document
            .getElementById("modalClose")
            .onclick = () =>
                this.closeConfirmModal();

        document
            .getElementById("modalCancel")
            .onclick = () =>
                this.closeConfirmModal();

        modal.onclick = event => {

            if (event.target === modal) {
                this.closeConfirmModal();
            }

        };

        document
            .getElementById("modalConfirm")
            .onclick = () =>
                this.applyChanges();

        // Close custom dropdowns when clicking elsewhere.
        document.addEventListener(
            "click",
            () => {

                document
                    .querySelectorAll(
                        ".chaos-select.open"
                    )
                    .forEach(dropdown => {

                        dropdown.classList.remove(
                            "open"
                        );

                        const trigger =
                            dropdown.querySelector(
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

        this.timer = null;

    }

};