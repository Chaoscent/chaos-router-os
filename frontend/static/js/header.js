window.Header = {

    timer: null,
    pingTimer: null,

    // Throughput bar range, logarithmic: empty below 10 kbps (idle
    // background chatter), full at 1 Gbps.
    BAR_MIN_MBPS: 0.01,
    BAR_MAX_MBPS: 1000,

    pingEnabled: false,
    pingInterval: 5,


    async update() {

        try {

            const res =
                await fetch("/api/header");

            if (res.status === 401) {

                location.href =
                    "/login";

                return;
            }

            const data =
                await res.json();


            headerStatus.textContent =
                data.online ? "Online" : "Offline";

            headerStatus.className =
                `status ${data.online ? "online" : "offline"}`;


            // Only real modem data; never placeholders.
            headerNetwork.textContent =
                data.modem_state === "absent" ? "No modem" :
                data.modem_state === "not_ready" ? "Not ready" :
                data.network || "--";


            headerModule.textContent =
                data.model || (data.modem_state === "absent" ? "No modem" : "--");


            headerCarrier.textContent =
                data.carrier || "--";


            /*
             * Ping is updated separately.
             *
             * The normal header refresh must
             * never perform an ICMP request.
             */


            headerTime.textContent =
                data.time;


            headerUser.textContent =
                data.user;


            pulseDown.textContent =
                `↓ ${this.formatRate(data.rx)}`;


            pulseUp.textContent =
                `↑ ${this.formatRate(data.tx)}`;


            // Empty when idle, never a fake minimum.
            const total = data.rx + data.tx;

            pulseFill.style.width =
                `${this.barPercent(total)}%`;

            pulseFill.parentElement.title = data.interface
                ? `${this.formatRate(total)} total on ${data.interface}`
                : this.formatRate(total);

        } catch {}

    },


    /** Mbps -> "850 kbps", "12.4 Mbps", "1.2 Gbps". */
    formatRate(mbps) {

        const value = Number(mbps) || 0;

        if (value >= 1000)
            return `${(value / 1000).toFixed(2)} Gbps`;

        if (value >= 1)
            return `${value.toFixed(value >= 100 ? 0 : 1)} Mbps`;

        const kbps = value * 1000;

        return `${kbps.toFixed(kbps >= 10 || kbps === 0 ? 0 : 1)} kbps`;

    },


    barPercent(mbps) {

        if (!(mbps > this.BAR_MIN_MBPS)) return 0;

        const min = Math.log10(this.BAR_MIN_MBPS);
        const max = Math.log10(this.BAR_MAX_MBPS);
        const pct = (Math.log10(mbps) - min) / (max - min) * 100;

        return Math.min(100, pct);

    },


    async loadPingConfig() {

        try {

            const res =
                await fetch(
                    "/api/system/ping"
                );


            if (res.status === 401) {

                location.href =
                    "/login";

                return;
            }


            if (!res.ok) {

                return;
            }


            const data =
                await res.json();


            this.pingEnabled =
                data.enabled === true;


            this.pingInterval =
                Number(
                    data.interval
                ) || 5;


            this.startPing();

        } catch {}

    },


    async updatePing() {

        if (!this.pingEnabled) {

            headerPing.parentElement.style.display =
                "none";

            return;
        }


        /*
         * Ping is enabled, so make the
         * complete Ping header item visible.
         */

        headerPing.parentElement.style.display =
            "";


        try {

            const res =
                await fetch(
                    "/api/system/ping/value"
                );


            if (res.status === 401) {

                location.href =
                    "/login";

                return;
            }


            if (!res.ok) {

                headerPing.textContent =
                    "-- ms";

                return;
            }


            const data =
                await res.json();


            headerPing.textContent =
                data.ping ||
                "-- ms";

        } catch {

            headerPing.textContent =
                "-- ms";

        }

    },


    startPing() {

        if (
            this.pingTimer !== null
        ) {

            clearInterval(
                this.pingTimer
            );

            this.pingTimer =
                null;
        }


        if (!this.pingEnabled) {

            /*
             * Hide the complete Ping
             * header item when disabled.
             */

            headerPing.parentElement.style.display =
                "none";

            return;
        }


        /*
         * Ping is enabled.
         */

        headerPing.parentElement.style.display =
            "";


        /*
         * Perform the first ping immediately.
         */

        this.updatePing();


        this.pingTimer =
            setInterval(
                () => this.updatePing(),
                this.pingInterval * 1000
            );

    },


    init() {

        /*
         * Keep Ping hidden until its
         * configuration has loaded.
         */

        headerPing.parentElement.style.display =
            "none";


        this.update();


        this.timer =
            setInterval(
                () => this.update(),
                1000
            );


        this.loadPingConfig();

    }

};


window.addEventListener(
    "DOMContentLoaded",
    () => Header.init()
);