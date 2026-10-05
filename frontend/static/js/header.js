window.Header = {

    timer: null,
    pingTimer: null,

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


            headerNetwork.textContent =
                data.network;


            headerModule.textContent =
                data.model;


            headerCarrier.textContent =
                data.carrier;


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
                `↓ ${data.rx.toFixed(1)} Mbps`;


            pulseUp.textContent =
                `↑ ${data.tx.toFixed(1)} Mbps`;


            const total =
                Math.min(
                    data.rx + data.tx,
                    200
                );


            pulseFill.style.width =
                `${Math.max(
                    8,
                    total / 2
                )}%`;

        } catch {}

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