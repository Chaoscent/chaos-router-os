window.Page = window.Page || {};

window.Page.dashboard = {

    timer: null,

    async update() {

        const res = await fetch("/api/dashboard");

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        const data = await res.json();

        hostname.textContent = data.hostname;
        ip.textContent = data.ip;
        cpu.textContent = data.cpu_temp;
        ram.textContent = data.ram;
        uptime.textContent = data.uptime;
        time.textContent = data.time;

        clients.textContent = data.clients;
        active.textContent = data.active;
        download.textContent = `${data.download.toFixed(1)} Mbps`;
        upload.textContent = `${data.upload.toFixed(1)} Mbps`;

        this.drawGraph(data.history);

    },

    drawGraph(history) {

        if (!history.length) return;

        const points = history.slice(-60);

        const w = 600;
        const h = 180;
        const padding = 20;
        const totalSlots = 60;

        const max = Math.max(
            10,
            ...points.flatMap(p => [p.rx, p.tx])
        );

        const startSlot = totalSlots - points.length;

        const makeLine = key =>
            points.map((p, i) => {

                const slot = startSlot + i;
                const x = (slot / (totalSlots - 1)) * w;

                const y =
                    h -
                    padding -
                    (p[key] / max) * (h - padding * 2);

                return `${x},${y}`;

            }).join(" ");

        downloadLine.setAttribute("points", makeLine("rx"));
        uploadLine.setAttribute("points", makeLine("tx"));

    },

    init() {

        this.update();
        this.timer = setInterval(() => this.update(), 1000);

    },

    destroy() {

        clearInterval(this.timer);

    }

};