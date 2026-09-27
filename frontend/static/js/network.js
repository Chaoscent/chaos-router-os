window.Page = window.Page || {};

window.Page.network = {

    timer: null,

    original: {},

    async update() {

        const res = await fetch("/api/network");

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        const data = await res.json();

        // Live cards
        currentIp.textContent = data.ip;
        wan.textContent = data.wan;
        connection.textContent = data.connection;
        interface.textContent = data.interface;

        // Only populate inputs the first time
        if (!this.original.ip) {

            this.original = {
                ip: data.ip,
                subnet: "255.255.255.0",
                gateway: data.gateway,
                dns: data.dns
            };

            lanIpInput.value = data.ip;
            subnetInput.value = this.original.subnet;
            gatewayInput.value = data.gateway;
            dnsInput.value = data.dns;

        }

    },

    checkChanges() {

        let changes = 0;

        if (lanIpInput.value !== this.original.ip) changes++;
        if (subnetInput.value !== this.original.subnet) changes++;
        if (gatewayInput.value !== this.original.gateway) changes++;
        if (dnsInput.value !== this.original.dns) changes++;

        pendingCount.textContent = changes;

        pendingBar.classList.toggle("hidden", changes === 0);

        applyChanges.disabled = changes === 0;
        discardChanges.disabled = changes === 0;

    },

    discard() {

        lanIpInput.value = this.original.ip;
        subnetInput.value = this.original.subnet;
        gatewayInput.value = this.original.gateway;
        dnsInput.value = this.original.dns;

        this.checkChanges();

    },

    init() {

        this.update();

        this.timer = setInterval(() => this.update(), 3000);

        [
            lanIpInput,
            subnetInput,
            gatewayInput,
            dnsInput
        ].forEach(input => {

            input.addEventListener("input", () => this.checkChanges());

        });

        discardChanges.onclick = () => this.discard();

        applyChanges.onclick = () => {

            alert(
                "Apply Changes is coming next.\n\n" +
                "We'll validate, apply, verify, and roll back if needed."
            );

        };

    },

    destroy() {

        clearInterval(this.timer);

    }

};