window.Page = window.Page || {};

window.Page.network = {

    timer: null,
    original: {},

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

        const parts = value.split(".").map(Number);

        let bits = "";

        for (const p of parts) {
            bits += p.toString(2).padStart(8, "0");
        }

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

    validate() {

        const ipOK = this.isIPv4(lanIpInput.value.trim());
        const maskOK = this.isSubnetMask(subnetInput.value.trim());
        const gwOK = this.isIPv4(gatewayInput.value.trim());
        const dnsOK = this.isIPv4(dnsInput.value.trim());

        this.setFieldState(
            lanIpInput,
            ipOK,
            "Invalid IPv4 address."
        );

        this.setFieldState(
            subnetInput,
            maskOK,
            "Invalid subnet mask."
        );

        this.setFieldState(
            gatewayInput,
            gwOK,
            "Invalid gateway."
        );

        this.setFieldState(
            dnsInput,
            dnsOK,
            "Invalid DNS server."
        );

        return ipOK && maskOK && gwOK && dnsOK;

    },

    async update() {

        const res = await fetch("/api/network");

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        const data = await res.json();

        currentIp.textContent = data.ip;
        wan.textContent = data.wan;
        connection.textContent = data.connection;
        interface.textContent = data.interface;

    },

    async loadConfig() {

        const res = await fetch("/api/network/config");
        const config = await res.json();

        this.original = { ...config };

        lanIpInput.value = config.ip;
        subnetInput.value = config.subnet;
        gatewayInput.value = config.gateway;
        dnsInput.value = config.dns;

        const pendingRes = await fetch("/api/network/pending");
        const pending = await pendingRes.json();

        if (Object.keys(pending).length) {

            lanIpInput.value = pending.ip;
            subnetInput.value = pending.subnet;
            gatewayInput.value = pending.gateway;
            dnsInput.value = pending.dns;

        }

        this.checkChanges();

    },

    async stage() {

        if (!this.validate()) return;

        const payload = {
            ip: lanIpInput.value.trim(),
            subnet: subnetInput.value.trim(),
            gateway: gatewayInput.value.trim(),
            dns: dnsInput.value.trim()
        };

        await fetch("/api/network/stage", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });

    },

    checkChanges() {

        const valid = this.validate();

        const statusText = document.getElementById("pendingStatus");
        const list = document.getElementById("pendingList");

        const fields = [
            {
                label: "LAN IP",
                old: this.original.ip,
                value: lanIpInput.value
            },
            {
                label: "Subnet",
                old: this.original.subnet,
                value: subnetInput.value
            },
            {
                label: "Gateway",
                old: this.original.gateway,
                value: gatewayInput.value
            },
            {
                label: "Primary DNS",
                old: this.original.dns,
                value: dnsInput.value
            }
        ];

        list.innerHTML = "";

        let changes = 0;

        for (const field of fields) {

            if (field.old === field.value) continue;

            changes++;

            const row = document.createElement("div");
            row.className = "pending-change";

            row.innerHTML = `
                <strong>${field.label}</strong>
                <span class="pending-old">${field.old}</span>
                <span class="pending-arrow">→</span>
                <span class="pending-new">${field.value}</span>
            `;

            list.appendChild(row);

        }

        pendingCount.textContent = changes;
        pendingBar.classList.toggle("hidden", changes === 0);

        applyChanges.disabled = changes === 0 || !valid;
        discardChanges.disabled = changes === 0;

        if (statusText) {

            if (!valid) {
                statusText.textContent = "Fix validation errors before applying.";
                statusText.style.color = "#ffb4b4";
            } else {
                statusText.textContent = "Pending Changes";
                statusText.style.color = "";
            }

        }

    },

    async discard() {

        await fetch("/api/network/discard", {
            method: "POST"
        });

        lanIpInput.value = this.original.ip;
        subnetInput.value = this.original.subnet;
        gatewayInput.value = this.original.gateway;
        dnsInput.value = this.original.dns;

        this.checkChanges();

    },

    init() {

        this.update();
        this.loadConfig();

        this.timer = setInterval(() => this.update(), 3000);

        [
            lanIpInput,
            subnetInput,
            gatewayInput,
            dnsInput
        ].forEach(input => {

            input.addEventListener("input", () => {

                this.checkChanges();
                this.stage();

            });

        });

        discardChanges.onclick = () => this.discard();

        applyChanges.onclick = () => {

            if (!this.validate()) return;

            const statusText = document.getElementById("pendingStatus");

            if (statusText) {
                statusText.textContent = "✓ Validation passed · Ready to apply";
                statusText.style.color = "#8ce5aa";
            }

        };

    },

    destroy() {

        clearInterval(this.timer);

    }

};