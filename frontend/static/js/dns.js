window.Page = window.Page || {};

window.Page.dns = {

    timer: null,
    data: null,

    selects: [
        "dnsEnabledInput",
        "dnsUpstreamInput",
        "dnsCacheInput",
        "dnsKeepLocalInput",
        "dnsDnssecInput",
        "dnsLogInput",
        "dnsLookupTypeInput"
    ],


    escape(value) {

        return ChaosSelect.escape(value);

    },


    async request(url, body, method = "POST") {

        const res = await fetch(url, {

            method: method,

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify(body ?? {})

        });

        if (res.status === 401) {
            location.href = "/login";
            return null;
        }

        try {
            return await res.json();
        } catch {
            return { success: false, message: "Unexpected server response." };
        }

    },


    // ------------------------------------------------------------
    // Load / render
    // ------------------------------------------------------------

    async load() {

        const res = await fetch("/api/dns");

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        if (!res.ok) {
            dnsStatus.textContent = "Failed to load DNS settings.";
            return;
        }

        this.data = await res.json();

        this.renderStatus();
        this.renderSettings();
        this.renderRecords();

        dnsBlockedInput.value = this.data.settings.blocked_domains.join("\n");

    },


    // Status only: refreshed periodically without touching the form.
    async refreshStatus() {

        const res = await fetch("/api/dns");

        if (!res.ok) return;

        const data = await res.json();

        this.data.status = data.status;

        this.renderStatus();

    },


    renderStatus() {

        const { status, settings } = this.data;

        dnsState.textContent =
            !status.running ? "Stopped" :
            settings.enabled ? "Running" : "Off";

        dnsUpstreamState.textContent = status.upstream;

        dnsCacheState.textContent = status.cache && status.cache.hit_rate !== null
            ? `${status.cache.hit_rate}%`
            : "--";

        dnsRecordCount.textContent = settings.records.length;

    },


    renderSettings() {

        const { settings, options } = this.data;

        // Upstream: presets, custom servers, or the modem's DNS.
        dnsUpstreamInput.innerHTML = "";

        options.presets.forEach(preset => {

            const option = document.createElement("option");
            option.value = `preset:${preset.id}`;
            option.textContent = preset.label;
            dnsUpstreamInput.appendChild(option);

        });

        [["custom", "Custom servers"], ["isp", "Modem / ISP"]].forEach(([value, label]) => {

            const option = document.createElement("option");
            option.value = value;
            option.textContent = label;
            dnsUpstreamInput.appendChild(option);

        });

        dnsUpstreamInput.value = settings.upstream_mode === "preset"
            ? `preset:${settings.upstream_preset}`
            : settings.upstream_mode;

        dnsServer1Input.value = settings.upstream_servers[0] || "";
        dnsServer2Input.value = settings.upstream_servers[1] || "";

        dnsEnabledInput.value = String(settings.enabled);
        dnsKeepLocalInput.value = String(settings.keep_local);
        dnsDnssecInput.value = String(settings.dnssec);
        dnsLogInput.value = String(settings.log_queries);

        // Keep an unusual saved size selectable.
        const size = String(settings.cache_size);

        if (![...dnsCacheInput.options].some(o => o.value === size)) {

            const option = document.createElement("option");
            option.value = size;
            option.textContent = size;
            dnsCacheInput.appendChild(option);

        }

        dnsCacheInput.value = size;

        dnsDnssecInput.disabled = !options.dnssec_available && !settings.dnssec;

        dnsDomainHint.textContent = options.local_domain
            ? `Names in .${options.local_domain} are answered by the router.`
            : "";

        this.renderInterfaces();
        this.updateUpstreamFields();

        this.selects.forEach(id => {
            ChaosSelect.refresh(document.getElementById(id));
        });

    },


    renderInterfaces() {

        const { settings, options } = this.data;

        dnsInterfaces.innerHTML = "";

        options.interfaces.forEach(choice => {

            const label = document.createElement("label");
            label.className = "check-item";

            // Interfaces with DHCP always answer DNS too.
            const checked = choice.forced || settings.interfaces.includes(choice.name);

            label.innerHTML = `
                <input type="checkbox" value="${this.escape(choice.name)}"
                    ${checked ? "checked" : ""} ${choice.forced ? "disabled" : ""}>
                <span>${this.escape(choice.label)}</span>
                ${choice.forced ? '<small>also serves DHCP</small>' : ""}
            `;

            dnsInterfaces.appendChild(label);

        });

    },


    updateUpstreamFields() {

        dnsCustomServers.classList.toggle(
            "hidden",
            dnsUpstreamInput.value !== "custom"
        );

    },


    renderRecords() {

        const records = this.data.settings.records;

        dnsRecordTable.innerHTML = "";

        if (!records.length) {

            dnsRecordTable.innerHTML = `
                <tr class="empty-row">
                    <td colspan="3">No local records.</td>
                </tr>
            `;

            return;
        }

        records.forEach(record => {

            const row = document.createElement("tr");

            row.innerHTML = `
                <td><strong>${this.escape(record.name)}</strong></td>
                <td>${this.escape(record.ip)}</td>
                <td class="table-action">
                    <button class="table-btn danger">Remove</button>
                </td>
            `;

            row.querySelector("button").onclick = () => this.removeRecord(record);

            dnsRecordTable.appendChild(row);

        });

    },


    // ------------------------------------------------------------
    // Settings
    // ------------------------------------------------------------

    collectSettings() {

        const upstream = dnsUpstreamInput.value;

        return {

            enabled: dnsEnabledInput.value === "true",

            upstream_mode: upstream.startsWith("preset:") ? "preset" : upstream,

            upstream_preset: upstream.startsWith("preset:")
                ? upstream.slice("preset:".length)
                : this.data.settings.upstream_preset,

            upstream_servers: [
                dnsServer1Input.value.trim(),
                dnsServer2Input.value.trim()
            ].filter(Boolean),

            cache_size: Number(dnsCacheInput.value),

            keep_local: dnsKeepLocalInput.value === "true",

            dnssec: dnsDnssecInput.value === "true",

            log_queries: dnsLogInput.value === "true",

            // DHCP interfaces are saved too, so DNS stays on there
            // if DHCP is turned off later.
            interfaces: [...dnsInterfaces.querySelectorAll("input:checked")]
                .map(input => input.value)

        };

    },


    // Applies the outcome of a save; returns true when it succeeded.
    handleResult(data, statusEl, successText) {

        if (!data) return false;

        if (data.settings) {

            this.data.settings = data.settings;

            this.renderStatus();
            this.renderRecords();

        }

        statusEl.textContent = data.success
            ? `✓ ${successText}`
            : data.message || "Failed to save.";

        return data.success === true;

    },


    async save() {

        dnsSave.disabled = true;
        dnsStatus.textContent = "Applying...";

        const data = await this.request("/api/dns/settings", this.collectSettings());

        dnsSave.disabled = false;

        this.handleResult(data, dnsStatus, data?.message || "DNS settings applied");

        if (!dnsConfigPreview.classList.contains("hidden")) {
            this.preview();
        }

        this.refreshStatus();

    },


    async preview() {

        const data = await this.request("/api/dns/preview", this.collectSettings());

        if (!data) return;

        if (!data.success) {
            dnsStatus.textContent = data.message;
            dnsConfigPreview.classList.add("hidden");
            return;
        }

        dnsConfigPreview.textContent = data.config;
        dnsConfigPreview.classList.remove("hidden");

    },


    // ------------------------------------------------------------
    // Records, blocklist, lookup
    // ------------------------------------------------------------

    async addRecord() {

        dnsRecordStatus.textContent = "Saving...";

        const data = await this.request("/api/dns/records", {
            name: dnsRecordNameInput.value.trim(),
            ip: dnsRecordIpInput.value.trim()
        });

        if (this.handleResult(data, dnsRecordStatus, "Record added")) {
            dnsRecordNameInput.value = "";
            dnsRecordIpInput.value = "";
        }

    },


    async removeRecord(record) {

        dnsRecordStatus.textContent = "Removing...";

        const data = await this.request("/api/dns/records", record, "DELETE");

        this.handleResult(data, dnsRecordStatus, "Record removed");

    },


    async saveBlocked() {

        dnsBlockedStatus.textContent = "Saving...";

        const data = await this.request("/api/dns/blocklist", {
            domains: dnsBlockedInput.value.split("\n")
        });

        const count = data?.settings?.blocked_domains.length ?? 0;

        if (this.handleResult(
            data,
            dnsBlockedStatus,
            `Blocklist saved (${count} domain${count === 1 ? "" : "s"})`
        )) {
            // Show the cleaned-up list (duplicates and comments removed).
            dnsBlockedInput.value = data.settings.blocked_domains.join("\n");
        }

    },


    async lookup() {

        dnsLookup.disabled = true;

        const data = await this.request("/api/dns/lookup", {
            name: dnsLookupNameInput.value.trim(),
            type: dnsLookupTypeInput.value
        });

        dnsLookup.disabled = false;

        if (!data) return;

        let text;

        if (data.error && !data.rcode) {

            text = data.error;

        } else {

            const answers = data.answers.length
                ? data.answers.map(a => `${a.type.padEnd(6)} ${a.value}  (TTL ${a.ttl}s)`).join("\n")
                : "No records.";

            text = `${data.name} ${data.type}: ${data.rcode} in ${data.time_ms} ms\n\n${answers}`;

        }

        dnsLookupResult.textContent = text;
        dnsLookupResult.classList.remove("hidden");

    },


    init() {

        this.selects.forEach(id => {
            ChaosSelect.enhance(document.getElementById(id));
        });

        dnsUpstreamInput.onchange = () => this.updateUpstreamFields();

        dnsSave.onclick = () => this.save();
        dnsPreview.onclick = () => this.preview();
        dnsAddRecord.onclick = () => this.addRecord();
        dnsSaveBlocked.onclick = () => this.saveBlocked();
        dnsLookup.onclick = () => this.lookup();

        dnsLookupNameInput.addEventListener("keydown", e => {
            if (e.key === "Enter") this.lookup();
        });

        this.load();

        this.timer = setInterval(() => this.refreshStatus(), 10000);

    },


    destroy() {

        clearInterval(this.timer);
        this.timer = null;

    }

};
