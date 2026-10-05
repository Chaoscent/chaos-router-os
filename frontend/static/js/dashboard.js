window.Page = window.Page || {};

window.Page.dashboard = {

    timer: null,
    resizeObserver: null,

    // Samples from /api/dashboard: [{ t, rx, tx }] with rates in Mbps.
    history: [],

    // Index of the sample under the mouse, or null.
    hoverIndex: null,

    WINDOW_SECONDS: 60,

    // Plot margins inside the SVG, in pixels (room for axis labels).
    MARGIN: { top: 10, right: 12, bottom: 26, left: 84 },

    SVG_NS: "http://www.w3.org/2000/svg",

    COLORS: {
        rx: "#4ea1ff",
        tx: "#6ee7b7",
        grid: "rgba(255,255,255,.07)",
        axis: "#95a3b8"
    },


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
        download.textContent = Header.formatRate(data.download);
        upload.textContent = Header.formatRate(data.upload);

        graphInterface.textContent = data.interface ? ` · ${data.interface}` : "";

        this.history = data.history || [];

        this.drawGraph();

    },


    // ------------------------------------------------------------
    // Graph
    // ------------------------------------------------------------

    /** A round axis maximum (1, 2, 2.5 or 5 x 10^n) above the data. */
    niceMax(value) {

        const target = Math.max(value * 1.15, 0.01);
        const power = 10 ** Math.floor(Math.log10(target));

        for (const step of [1, 2, 2.5, 5, 10]) {
            if (step * power >= target) return step * power;
        }

        return 10 * power;

    },


    /** Axis labels: round values without trailing zeros, e.g. "25 Mbps". */
    formatAxis(mbps) {

        const trim = n => String(Number(n.toFixed(2)));

        if (mbps === 0) return "0";
        if (mbps >= 1000) return `${trim(mbps / 1000)} Gbps`;
        if (mbps >= 1) return `${trim(mbps)} Mbps`;

        return `${trim(mbps * 1000)} kbps`;

    },


    el(name, attrs = {}, text = null) {

        const node = document.createElementNS(this.SVG_NS, name);

        for (const [key, value] of Object.entries(attrs)) {
            node.setAttribute(key, value);
        }

        if (text !== null) node.textContent = text;

        return node;

    },


    /** Pixel geometry shared by drawing and hovering. */
    layout() {

        const svg = trafficGraph;
        const width = svg.clientWidth;
        const height = svg.clientHeight;
        const m = this.MARGIN;

        const points = this.history;
        const end = points.length ? points[points.length - 1].t : Date.now() / 1000;
        const start = end - this.WINDOW_SECONDS;

        const peak = Math.max(0, ...points.flatMap(p => [p.rx, p.tx]));
        const max = this.niceMax(peak);

        const plotW = Math.max(1, width - m.left - m.right);
        const plotH = Math.max(1, height - m.top - m.bottom);

        return {
            width, height, m, plotW, plotH, start, end, max, points,
            x: t => m.left + ((t - start) / this.WINDOW_SECONDS) * plotW,
            y: v => m.top + plotH - (v / max) * plotH
        };

    },


    drawGraph() {

        const svg = trafficGraph;
        const g = this.layout();

        if (g.width < 50 || g.height < 50) return;

        svg.setAttribute("viewBox", `0 0 ${g.width} ${g.height}`);
        svg.innerHTML = "";

        // Horizontal grid lines with rate labels.
        const ticks = 4;

        for (let i = 0; i <= ticks; i++) {

            const value = (g.max / ticks) * i;
            const y = g.y(value);

            svg.appendChild(this.el("line", {
                x1: g.m.left, x2: g.width - g.m.right, y1: y, y2: y,
                stroke: this.COLORS.grid
            }));

            svg.appendChild(this.el("text", {
                x: g.m.left - 10, y: y + 4,
                "text-anchor": "end", class: "graph-label"
            }, this.formatAxis(value)));

        }

        // Time labels: seconds before the latest sample.
        for (const ago of [60, 45, 30, 15, 0]) {

            const x = g.x(g.end - ago);

            svg.appendChild(this.el("line", {
                x1: x, x2: x, y1: g.m.top, y2: g.m.top + g.plotH,
                stroke: this.COLORS.grid
            }));

            svg.appendChild(this.el("text", {
                x: x, y: g.height - 6,
                "text-anchor": ago === 60 ? "start" : ago === 0 ? "end" : "middle",
                class: "graph-label"
            }, ago === 0 ? "now" : `-${ago}s`));

        }

        if (!g.points.length) {

            svg.appendChild(this.el("text", {
                x: g.m.left + g.plotW / 2, y: g.m.top + g.plotH / 2,
                "text-anchor": "middle", class: "graph-label"
            }, "Collecting data…"));

            return;
        }

        // Area + line per direction.
        const base = g.y(0);

        for (const key of ["rx", "tx"]) {

            const coords = g.points.map(p => `${g.x(p.t).toFixed(1)},${g.y(p[key]).toFixed(1)}`);
            const first = g.x(g.points[0].t).toFixed(1);
            const last = g.x(g.points[g.points.length - 1].t).toFixed(1);

            svg.appendChild(this.el("polygon", {
                points: `${first},${base} ${coords.join(" ")} ${last},${base}`,
                fill: this.COLORS[key],
                "fill-opacity": key === "rx" ? .14 : .10
            }));

            svg.appendChild(this.el("polyline", {
                points: coords.join(" "),
                fill: "none",
                stroke: this.COLORS[key],
                "stroke-width": 2,
                "stroke-linejoin": "round",
                "stroke-linecap": "round"
            }));

        }

        this.drawHover(g);

    },


    drawHover(g) {

        const index = this.hoverIndex;
        const sample = index !== null ? g.points[index] : null;

        if (!sample) {
            graphTooltip.classList.add("hidden");
            return;
        }

        const svg = trafficGraph;
        const x = g.x(sample.t);

        svg.appendChild(this.el("line", {
            x1: x, x2: x, y1: g.m.top, y2: g.m.top + g.plotH,
            stroke: "rgba(255,255,255,.35)", "stroke-dasharray": "4 4"
        }));

        for (const key of ["rx", "tx"]) {

            svg.appendChild(this.el("circle", {
                cx: x, cy: g.y(sample[key]), r: 4.5,
                fill: this.COLORS[key], stroke: "#181c25", "stroke-width": 2
            }));

        }

        const ago = Math.round(g.end - sample.t);
        const clock = new Date(sample.t * 1000).toLocaleTimeString();

        graphTooltip.innerHTML = `
            <div class="graph-tooltip-time">${clock} · ${ago === 0 ? "now" : `${ago}s ago`}</div>
            <div><i class="legend-swatch download"></i>Download <strong>${Header.formatRate(sample.rx)}</strong></div>
            <div><i class="legend-swatch upload"></i>Upload <strong>${Header.formatRate(sample.tx)}</strong></div>
        `;

        graphTooltip.classList.remove("hidden");

        // Next to the cursor line, flipped near the right edge.
        const box = graphTooltip.getBoundingClientRect();
        const left = x + 14 + box.width > g.width ? x - 14 - box.width : x + 14;

        graphTooltip.style.left = `${Math.max(0, left)}px`;
        graphTooltip.style.top = `${g.m.top + 8}px`;

    },


    onPointerMove(event) {

        const g = this.layout();

        if (!g.points.length) return;

        const rect = trafficGraph.getBoundingClientRect();
        const mouseX = event.clientX - rect.left;

        if (mouseX < g.m.left - 8 || mouseX > g.width - g.m.right + 8) {
            this.onPointerLeave();
            return;
        }

        // Nearest sample in time.
        let best = 0;

        g.points.forEach((p, i) => {
            if (Math.abs(g.x(p.t) - mouseX) < Math.abs(g.x(g.points[best].t) - mouseX)) best = i;
        });

        if (best !== this.hoverIndex) {
            this.hoverIndex = best;
            this.drawGraph();
        }

    },


    onPointerLeave() {

        if (this.hoverIndex === null) return;

        this.hoverIndex = null;
        this.drawGraph();

    },


    // ------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------

    init() {

        this.history = [];
        this.hoverIndex = null;

        trafficGraph.addEventListener("pointermove", e => this.onPointerMove(e));
        trafficGraph.addEventListener("pointerleave", () => this.onPointerLeave());

        // Redraw at the new pixel size when the window changes.
        this.resizeObserver = new ResizeObserver(() => this.drawGraph());
        this.resizeObserver.observe(trafficGraph);

        this.update();
        this.timer = setInterval(() => this.update(), 1000);

    },

    destroy() {

        clearInterval(this.timer);

        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
            this.resizeObserver = null;
        }

    }

};
