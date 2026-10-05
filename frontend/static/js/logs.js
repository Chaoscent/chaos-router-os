window.Page = window.Page || {};

window.Page.logs = {

    timer: null,
    searchTimer: null,
    live: false,
    entries: [],
    loading: false,

    selects: [
        "logSourceInput",
        "logLevelInput",
        "logLimitInput"
    ],

    PREFS_KEY: "chaos-log-filters",

    LEVEL_BADGES: {
        error: "blocked",
        warning: "warning",
        info: "",
        debug: "muted"
    },


    escape(value) {

        return ChaosSelect.escape(value);

    },


    // Remember filters per viewer (convenience only).
    loadPrefs() {

        try {
            return JSON.parse(localStorage.getItem(this.PREFS_KEY)) || {};
        } catch {
            return {};
        }

    },


    savePrefs() {

        try {
            localStorage.setItem(this.PREFS_KEY, JSON.stringify({
                source: logSourceInput.value,
                level: logLevelInput.value,
                limit: logLimitInput.value
            }));
        } catch {}

    },


    async loadSources() {

        const res = await fetch("/api/logs/sources");

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        const sources = await res.json();

        logSourceInput.innerHTML = "";

        sources.forEach(source => {

            const option = document.createElement("option");
            option.value = source.id;
            option.textContent = source.label;
            logSourceInput.appendChild(option);

        });

    },


    async load() {

        // Skip a poll while the previous request is still running.
        if (this.loading) return;

        this.loading = true;

        const params = new URLSearchParams({
            source: logSourceInput.value,
            level: logLevelInput.value,
            limit: logLimitInput.value,
            search: logSearchInput.value.trim()
        });

        try {

            const res = await fetch(`/api/logs?${params}`);

            if (res.status === 401) {
                location.href = "/login";
                return;
            }

            const data = await res.json();

            this.entries = data.entries;

            this.render();

            logStatus.textContent = data.error
                ? data.error
                : `${data.entries.length} entries` +
                  (this.live ? " · updating live" : "");

        } catch {

            logStatus.textContent = "Could not load logs.";

        } finally {

            this.loading = false;

        }

    },


    formatTime(seconds) {

        const date = new Date(seconds * 1000);

        const sameDay = date.toDateString() === new Date().toDateString();

        return sameDay
            ? date.toLocaleTimeString()
            : date.toLocaleString();

    },


    render() {

        logTable.innerHTML = "";

        if (!this.entries.length) {

            logTable.innerHTML = `
                <tr class="empty-row">
                    <td colspan="4">No log entries.</td>
                </tr>
            `;

            return;
        }

        const fragment = document.createDocumentFragment();

        this.entries.forEach(entry => {

            const row = document.createElement("tr");

            row.className = `log-${entry.level}`;

            row.innerHTML = `
                <td class="log-time">${this.escape(this.formatTime(entry.time))}</td>
                <td>
                    <span class="status ${this.LEVEL_BADGES[entry.level] || ""}">
                        ${this.escape(entry.level)}
                    </span>
                </td>
                <td class="log-source">${this.escape(entry.source)}</td>
                <td class="log-message">${this.escape(entry.message)}</td>
            `;

            fragment.appendChild(row);

        });

        logTable.appendChild(fragment);

    },


    updateClearButton() {

        // Only the router's own event log can be cleared.
        logClear.classList.toggle("hidden", logSourceInput.value !== "app");

    },


    toggleLive() {

        this.live = !this.live;

        logLive.textContent = this.live ? "Live: On" : "Live: Off";
        logLive.setAttribute("aria-pressed", String(this.live));
        logLive.classList.toggle("active", this.live);

        clearInterval(this.timer);
        this.timer = null;

        if (this.live) {
            this.timer = setInterval(() => this.load(), 3000);
        }

        this.load();

    },


    download() {

        const source = logSourceInput.value;
        const stamp = new Date().toISOString().replace(/[:.]/g, "-");

        const blob = new Blob(
            [JSON.stringify(this.entries, null, 2)],
            { type: "application/json" }
        );

        const link = document.createElement("a");

        link.href = URL.createObjectURL(blob);
        link.download = `chaos-router-${source}-logs-${stamp}.json`;
        link.click();

        URL.revokeObjectURL(link.href);

    },


    async clear() {

        const confirmed = await ChaosModal.confirm({
            title: "Clear Router Events",
            subtitle: "All router events are deleted. System logs are not affected.",
            confirmText: "Clear"
        });

        if (!confirmed) return;

        await fetch("/api/logs/clear", { method: "POST" });

        this.load();

    },


    onFilterChange() {

        this.savePrefs();
        this.updateClearButton();
        this.load();

    },


    async init() {

        await this.loadSources();

        const prefs = this.loadPrefs();

        [
            [logSourceInput, prefs.source],
            [logLevelInput, prefs.level],
            [logLimitInput, prefs.limit]
        ].forEach(([select, value]) => {

            if (value && [...select.options].some(o => o.value === value)) {
                select.value = value;
            }

        });

        if (!prefs.limit) logLimitInput.value = "200";

        this.selects.forEach(id => {
            ChaosSelect.enhance(document.getElementById(id));
        });

        logSourceInput.onchange = () => this.onFilterChange();
        logLevelInput.onchange = () => this.onFilterChange();
        logLimitInput.onchange = () => this.onFilterChange();

        logSearchInput.oninput = () => {
            clearTimeout(this.searchTimer);
            this.searchTimer = setTimeout(() => this.load(), 300);
        };

        logRefresh.onclick = () => this.load();
        logLive.onclick = () => this.toggleLive();
        logDownload.onclick = () => this.download();
        logClear.onclick = () => this.clear();

        this.updateClearButton();

        this.load();

    },


    destroy() {

        clearInterval(this.timer);
        clearTimeout(this.searchTimer);

        this.timer = null;
        this.live = false;

        ChaosModal.close();

    }

};
