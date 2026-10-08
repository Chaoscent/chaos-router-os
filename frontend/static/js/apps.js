window.Page = window.Page || {};

/*
 * Apps page: the Apps Addon's catalog. Installing, removing, ... runs
 * as a job on the router; its output is shown while it runs.
 */
window.Page.apps = {

    timer: null,
    data: null,
    active: false,

    // Finished job the user closed (not shown again).
    closedJob: null,

    STATES: {
        running: { text: "Running", css: "online" },
        stopped: { text: "Stopped", css: "" },
        partial: { text: "Partly running", css: "" },
        error: { text: "Error", css: "offline" },
        unknown: { text: "Unknown", css: "" }
    },


    escape(value) {

        return ChaosSelect.escape(value);

    },


    async request(url, options = {}) {

        const res = await fetch(url, options);

        if (res.status === 401) {
            location.href = "/login";
            return null;
        }

        try {
            return { ok: res.ok, data: await res.json() };
        } catch {
            return { ok: false, data: { message: "Unexpected server response." } };
        }

    },


    post(url, body) {

        return this.request(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body ?? {})
        });

    },


    // ------------------------------------------------------------
    // Load / render
    // ------------------------------------------------------------

    async refresh() {

        const res = await this.request("/api/apps");

        // Left the page while loading.
        if (!res || !this.active) return;

        if (!res.ok) {
            appsNotice.textContent = "The apps could not be loaded.";
            appsNotice.classList.remove("hidden");
            return;
        }

        this.data = res.data;

        this.renderStatus();
        this.renderJob();
        this.renderAddon();
        this.renderCatalog();

        this.schedule();

    },


    // Fast while a job runs, slow otherwise.
    schedule() {

        clearTimeout(this.timer);

        const busy = this.jobRunning();

        this.timer = setTimeout(() => this.refresh(), busy ? 1500 : 10000);

    },


    jobRunning() {

        return Boolean(this.data?.job && !this.data.job.done);

    },


    renderStatus() {

        const { addon, apps } = this.data;

        appsAddonState.textContent = addon.installed
            ? `Installed${addon.version ? ` (${addon.version})` : ""}`
            : "Not installed";

        appsDockerState.textContent = !addon.installed
            ? "--"
            : addon.docker_running ? "Running" : "Stopped";

        appsInstalledCount.textContent = addon.installed
            ? apps.filter(a => a.installed).length
            : "--";

        appsRunningCount.textContent = addon.installed
            ? apps.filter(a => a.state === "running").length
            : "--";

    },


    renderJob() {

        const job = this.data.job;

        if (!job || (job.done && job.id === this.closedJob)) {
            appsJob.classList.add("hidden");
            return;
        }

        const label = this.jobLabel(job.action);

        appsJobTitle.textContent = job.name ? `${label} ${job.name}` : label;

        // Keep the view at the bottom unless the user scrolled up.
        const atBottom = appsJobLog.scrollHeight - appsJobLog.scrollTop - appsJobLog.clientHeight < 24;

        appsJobLog.textContent = job.lines.join("\n") || "Starting...";

        if (atBottom) appsJobLog.scrollTop = appsJobLog.scrollHeight;

        appsJobStatus.textContent = !job.done
            ? "Working... this page updates by itself."
            : job.success ? "✓ Done." : "Failed (see above).";

        appsJobClose.classList.toggle("hidden", !job.done);
        appsJob.classList.remove("hidden");

    },


    jobLabel(action) {

        return {
            install: "Installing", start: "Starting", stop: "Stopping",
            restart: "Restarting", update: "Updating", remove: "Removing",
            addon: "Installing the Apps Addon"
        }[action] || action;

    },


    renderAddon() {

        const { addon } = this.data;

        appsAddon.classList.toggle("hidden", addon.installed);

        appsAddonInstall.disabled = this.jobRunning() || !addon.can_install;

        if (!addon.installed && !addon.can_install) {
            appsAddonStatus.textContent = "The addon installer (deploy/install-apps.sh) is missing.";
        }

        const problem = !addon.installed ? ""
            : addon.error ? `The App Manager reports: ${addon.error}`
            : !addon.docker_running ? "Docker is not running, so apps are stopped. Start it on the router: sudo systemctl start docker"
            : "";

        appsNotice.textContent = problem;
        appsNotice.classList.toggle("hidden", !problem);

    },


    renderCatalog() {

        const { addon, apps, base_domain } = this.data;

        appsCatalog.classList.toggle("hidden", !addon.installed);

        if (!addon.installed) return;

        appsGrid.innerHTML = "";

        if (!apps.length) {
            appsGrid.innerHTML = `<p class="setting-hint">The catalog is empty.</p>`;
        }

        apps.forEach(app => appsGrid.appendChild(this.renderApp(app)));

        appsNamesHint.textContent =
            `Apps are reached by name, e.g. https://<app>.${base_domain}/, from every device in your network. ` +
            `Install the router's certificate (System page) and browsers trust them without warnings.`;

    },


    renderApp(app) {

        const card = document.createElement("div");
        card.className = "card app-card";

        const busy = this.jobRunning();
        const disabled = busy ? "disabled" : "";

        // The app the running job works on: its state is in between.
        const working = busy && this.data.job.app === app.id;

        const state = working
            ? { text: `${this.jobLabel(this.data.job.action)}...`, css: "" }
            : this.STATES[app.state];

        // Apps are HTTPS only (the router redirects plain HTTP).
        const url = app.urls.https;

        let actions;

        if (working) {

            actions = "";

        } else if (!app.installed) {

            actions = `<button class="save-btn" data-action="install" ${disabled}>Install</button>`;

        } else {

            const running = app.state === "running";

            actions = [
                running ? `<a class="save-btn app-open" href="${this.escape(url)}" target="_blank" rel="noopener">Open</a>` : "",
                running || app.state === "partial"
                    ? `<button class="table-btn" data-action="stop" ${disabled}>Stop</button>`
                    : `<button class="table-btn" data-action="start" ${disabled}>Start</button>`,
                running ? `<button class="table-btn" data-action="restart" ${disabled}>Restart</button>` : "",
                `<button class="table-btn" data-action="update" ${disabled}>Update</button>`,
                `<button class="table-btn" data-action="logs">Logs</button>`,
                `<button class="table-btn danger" data-action="remove" ${disabled}>Remove</button>`
            ].join("");

        }

        const size = app.download_mb
            ? `Download: about ${app.download_mb >= 1000 ? `${(app.download_mb / 1000).toFixed(1)} GB` : `${app.download_mb} MB`}.`
            : "";

        card.innerHTML = `
            <div class="app-card-head">
                <div class="app-icon" aria-hidden="true">${this.escape(app.name.charAt(0))}</div>
                <div class="app-title">
                    <strong>${this.escape(app.name)}</strong>
                    <small>${this.escape(app.category)}</small>
                </div>
                ${state ? `<span class="status ${state.css}">${state.text}</span>` : ""}
            </div>

            <p class="app-description">${this.escape(app.description)}</p>

            ${app.installed && !working ? `
                <p class="app-address">
                    <a href="${this.escape(url)}" target="_blank" rel="noopener">${this.escape(url)}</a>
                </p>
                ${app.first_steps ? `<p class="setting-hint">${this.escape(app.first_steps)}</p>` : ""}
            ` : `
                <p class="setting-hint">${this.escape(size)}</p>
            `}

            <div class="app-actions">${actions}</div>
        `;

        card.querySelectorAll("button[data-action]").forEach(button => {
            button.onclick = () => this.act(app, button.dataset.action);
        });

        return card;

    },


    // ------------------------------------------------------------
    // Actions
    // ------------------------------------------------------------

    async act(app, action) {

        if (action === "logs") {
            await this.showLogs(app);
            return;
        }

        let body = {};

        if (action === "remove") {

            const box = document.createElement("label");
            box.className = "check-item";
            box.innerHTML = `
                <input type="checkbox" id="appsDeleteData">
                <span>Also delete its data (files, accounts, settings)</span>
            `;

            const confirmed = await ChaosModal.confirm({
                title: `Remove ${app.name}`,
                subtitle: "The app stops and is removed. Without the box below, its data stays on the router for a later install.",
                body: box,
                confirmText: "Remove"
            });

            if (!confirmed) return;

            body = { delete_data: box.querySelector("input").checked };

        }

        if (action === "update") {

            const confirmed = await ChaosModal.confirm({
                title: `Update ${app.name}`,
                subtitle: "Downloads the newest version and restarts the app. It is unavailable for a moment.",
                confirmText: "Update"
            });

            if (!confirmed) return;

        }

        const res = await this.post(`/api/apps/${encodeURIComponent(app.id)}/${action}`, body);

        if (!res) return;

        if (!res.data.success) {
            appsNotice.textContent = res.data.message || "Something went wrong.";
            appsNotice.classList.remove("hidden");
            return;
        }

        this.closedJob = null;

        await this.refresh();

    },


    async installAddon() {

        const confirmed = await ChaosModal.confirm({
            title: "Install Apps Addon",
            subtitle: "Installs Docker Engine, Docker Compose and the App Manager. This takes a few minutes and needs internet.",
            confirmText: "Install"
        });

        if (!confirmed) return;

        appsAddonStatus.textContent = "Starting...";

        const res = await this.post("/api/apps/addon/install");

        if (!res) return;

        appsAddonStatus.textContent = res.data.success ? "" : res.data.message;

        this.closedJob = null;

        await this.refresh();

    },


    async showLogs(app) {

        const res = await this.request(`/api/apps/${encodeURIComponent(app.id)}/logs`);

        if (!res) return;

        const pre = document.createElement("pre");
        pre.className = "config-preview apps-log";
        pre.textContent = res.data.success
            ? res.data.logs || "No output yet."
            : res.data.message;

        const shown = ChaosModal.confirm({
            title: `${app.name}: Logs`,
            subtitle: "The last 200 lines.",
            body: pre,
            confirmText: "Close"
        });

        pre.scrollTop = pre.scrollHeight;

        await shown;

    },


    // ------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------

    init() {

        this.active = true;

        appsAddonInstall.onclick = () => this.installAddon();

        appsJobClose.onclick = () => {
            this.closedJob = this.data?.job?.id ?? null;
            appsJob.classList.add("hidden");
        };

        this.refresh();

    },


    destroy() {

        this.active = false;

        clearTimeout(this.timer);
        this.timer = null;

        ChaosModal.close();

    }

};
