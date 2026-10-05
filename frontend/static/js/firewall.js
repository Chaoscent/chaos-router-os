window.Page = window.Page || {};

window.Page.firewall = {

    data: null,

    routing: null,

    selects: [
        "fwIncomingInput",
        "fwOutgoingInput",
        "fwRoutedInput",
        "fwLoggingInput",
        "routeForwardingInput",
        "routeNatInput",
        "routeWanInput",
        "fwActionInput",
        "fwDirectionInput",
        "fwInterfaceInput",
        "fwProtoInput"
    ],

    labels: {
        allow: "Allow",
        deny: "Deny",
        reject: "Reject",
        limit: "Limit",
        unknown: "Unknown"
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


    send(url, body, method = "POST") {

        return this.request(url, {

            method: method,

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify(body ?? {})

        });

    },


    // ------------------------------------------------------------
    // Load / render
    // ------------------------------------------------------------

    async load() {

        const res = await this.request("/api/firewall");

        if (!res) return;

        if (!res.ok) {
            fwToggleStatus.textContent = "Failed to load firewall status.";
            return;
        }

        this.data = res.data;

        this.renderStatus();
        this.renderPolicies();
        this.renderInterfaces();
        this.renderRules();

    },


    renderStatus() {

        const data = this.data;
        const policies = data.policies;

        fwState.textContent =
            !data.installed ? "Not installed" :
            data.active ? "Active" : "Inactive";

        fwIncomingState.textContent = this.labels[policies.incoming];
        fwOutgoingState.textContent = this.labels[policies.outgoing];

        // ufw only filters routed traffic while forwarding is on.
        fwRoutedState.textContent = data.forwarding
            ? this.labels[policies.routed]
            : "Not forwarding";

        fwRuleCount.textContent = data.rules.length;

        fwToggle.disabled = !data.installed;
        fwToggle.textContent = data.active ? "Disable Firewall" : "Enable Firewall";
        fwToggle.classList.toggle("danger-btn", data.active);

        if (!data.installed) {
            fwToggleStatus.textContent =
                "ufw is not installed. Install it with: sudo apt install ufw";
        } else if (!fwToggleStatus.dataset.keep) {
            fwToggleStatus.textContent = data.active
                ? "The firewall is filtering traffic."
                : "The firewall is off. All traffic is allowed.";
        }

        delete fwToggleStatus.dataset.keep;

    },


    renderPolicies() {

        const { policies, logging } = this.data;

        [
            [fwIncomingInput, policies.incoming],
            [fwOutgoingInput, policies.outgoing],
            [fwRoutedInput, policies.routed],
            [fwLoggingInput, logging]
        ].forEach(([select, value]) => {

            // Keep the default option when ufw reports something unknown.
            if ([...select.options].some(o => o.value === value)) {
                select.value = value;
            }

            ChaosSelect.refresh(select);

        });

    },


    renderInterfaces() {

        const current = fwInterfaceInput.value;

        fwInterfaceInput.innerHTML = '<option value="">Any</option>';

        this.data.interfaces.forEach(name => {

            const option = document.createElement("option");
            option.value = name;
            option.textContent = name;
            fwInterfaceInput.appendChild(option);

        });

        fwInterfaceInput.value =
            this.data.interfaces.includes(current) ? current : "";

        ChaosSelect.refresh(fwInterfaceInput);

    },


    describeTraffic(rule) {

        if (rule.route) {

            const from = rule.interface || "any";
            const to = rule.out_interface || "any";

            return `Routed ${from} → ${to}`;
        }

        const direction = rule.direction === "out" ? "Outgoing" : "Incoming";

        return rule.interface
            ? `${direction} on ${rule.interface}`
            : direction;

    },


    describePort(rule) {

        if (rule.app) return rule.app;

        if (!rule.port) {
            return rule.proto === "any" ? "Any" : rule.proto.toUpperCase();
        }

        return rule.proto === "any"
            ? rule.port
            : `${rule.port}/${rule.proto}`;

    },


    renderRules() {

        const { rules, rules_error } = this.data;

        fwRuleTable.innerHTML = "";

        fwRuleStatus.textContent = rules_error || "";

        if (!rules.length) {

            fwRuleTable.innerHTML = `
                <tr class="empty-row">
                    <td colspan="7">No rules.</td>
                </tr>
            `;

            return;
        }

        rules.forEach(rule => {

            const row = document.createElement("tr");

            const badge =
                rule.action === "allow" ? "online" :
                rule.action === "limit" ? "" : "blocked";

            const from = rule.from_port
                ? `${rule.from} port ${rule.from_port}`
                : rule.from;

            row.innerHTML = `
                <td>
                    <span class="status ${badge}">
                        ${this.escape(this.labels[rule.action] || rule.action)}
                    </span>
                </td>
                <td>${this.escape(this.describeTraffic(rule))}</td>
                <td>${this.escape(this.describePort(rule))}</td>
                <td>${this.escape(from === "any" ? "Any" : from)}</td>
                <td>${this.escape(rule.to === "any" ? "Any" : rule.to)}</td>
                <td><small>${this.escape(rule.comment) || "—"}</small></td>
                <td class="table-action">
                    <button class="table-btn danger">Delete</button>
                </td>
            `;

            row.querySelector("button").onclick =
                () => this.deleteRule(rule);

            fwRuleTable.appendChild(row);

        });

    },


    // ------------------------------------------------------------
    // Actions
    // ------------------------------------------------------------

    async toggle() {

        const enable = !this.data.active;

        let essentials = null;
        let body = null;

        if (enable) {

            const res = await this.request("/api/firewall/essentials");

            if (!res) return;

            body = document.createElement("div");

            body.innerHTML = `
                <label class="modal-check">
                    <input id="fwEssentialsInput" type="checkbox" checked>
                    <span>Add essential rules first (recommended)</span>
                </label>

                <p class="modal-note">
                    Keeps SSH and this page reachable, and lets LAN devices
                    keep using DHCP, DNS and the internet.
                </p>

                <ul class="modal-list">
                    ${res.data.map(r => `
                        <li>
                            <strong>${this.escape(r.description)}</strong>
                            <code>${this.escape(r.command)}</code>
                        </li>
                    `).join("")}
                </ul>
            `;

            essentials = body.querySelector("#fwEssentialsInput");

        }

        const confirmed = await ChaosModal.confirm({

            title: enable ? "Enable Firewall" : "Disable Firewall",

            subtitle: enable
                ? "Traffic not allowed by a rule will follow the default policies."
                : "All traffic will be allowed until the firewall is enabled again.",

            body: body,

            confirmText: enable ? "Enable" : "Disable"

        });

        if (!confirmed) return;

        fwToggle.disabled = true;
        fwToggleStatus.textContent = enable ? "Enabling..." : "Disabling...";

        const res = await this.send("/api/firewall/enable", {
            enabled: enable,
            essentials: essentials ? essentials.checked : false
        });

        fwToggle.disabled = false;

        if (!res) return;

        fwToggleStatus.textContent = res.data.success
            ? `✓ ${res.data.message}`
            : res.data.message;

        fwToggleStatus.dataset.keep = "1";

        await this.load();

    },


    async savePolicies() {

        fwPolicyStatus.textContent = "Saving...";

        const res = await this.send("/api/firewall/policies", {
            incoming: fwIncomingInput.value,
            outgoing: fwOutgoingInput.value,
            routed: fwRoutedInput.value
        });

        if (!res) return;

        if (!res.data.success) {
            fwPolicyStatus.textContent = res.data.message;
            return;
        }

        if (fwLoggingInput.value !== this.data.logging) {

            const log = await this.send("/api/firewall/logging", {
                level: fwLoggingInput.value
            });

            if (!log) return;

            if (!log.data.success) {
                fwPolicyStatus.textContent = log.data.message;
                return;
            }

        }

        fwPolicyStatus.textContent = "✓ Default policies updated";

        await this.load();

    },


    // ------------------------------------------------------------
    // Routing & NAT
    // ------------------------------------------------------------

    async loadRouting() {

        const res = await this.request("/api/routing");

        if (!res) return;

        if (!res.ok) {
            routeStatus.textContent = "Failed to load routing status.";
            return;
        }

        this.routing = res.data;

        this.renderRouting();

    },


    renderRouting() {

        const { settings, wan, interfaces } = this.routing;

        routeForwardingInput.value = String(settings.forwarding);
        routeNatInput.value = String(settings.nat);

        const names = [...interfaces];

        // Keep a chosen interface that is currently down (e.g. the modem).
        if (settings.wan_interface !== "auto" && !names.includes(settings.wan_interface)) {
            names.push(settings.wan_interface);
        }

        routeWanInput.innerHTML = "";

        const auto = document.createElement("option");
        auto.value = "auto";
        auto.textContent = `Automatic (${wan})`;
        routeWanInput.appendChild(auto);

        names.forEach(name => {

            const option = document.createElement("option");
            option.value = name;
            option.textContent = name;
            routeWanInput.appendChild(option);

        });

        routeWanInput.value = settings.wan_interface;

        [routeForwardingInput, routeNatInput, routeWanInput]
            .forEach(select => ChaosSelect.refresh(select));

        if (!routeStatus.dataset.keep) {
            routeStatus.textContent = this.describeRouting();
        }

        delete routeStatus.dataset.keep;

    },


    describeRouting() {

        const { installed, forwarding, nat, wan } = this.routing;

        if (!installed) {
            return "iptables is not installed. Install it with: sudo apt install iptables";
        }

        if (forwarding && nat) {
            return `LAN devices reach the internet through ${wan}.`;
        }

        if (!forwarding) {
            return "Forwarding is off: LAN devices can reach the router, but not the internet.";
        }

        return "NAT is off: LAN devices can only reach networks that route back to them.";

    },


    async saveRouting() {

        const forwarding = routeForwardingInput.value === "true";
        const nat = routeNatInput.value === "true";

        if (
            (!forwarding && this.routing.settings.forwarding) ||
            (!nat && this.routing.settings.nat)
        ) {

            const ok = await ChaosModal.confirm({
                title: "Turn off internet sharing?",
                subtitle: "LAN devices and VPN clients will lose internet access. The dashboard stays reachable.",
                confirmText: "Turn Off"
            });

            if (!ok) return;

        }

        routeStatus.textContent = "Saving...";

        const res = await this.send("/api/routing/settings", {
            forwarding: forwarding,
            nat: nat,
            wan_interface: routeWanInput.value
        });

        if (!res) return;

        routeStatus.textContent = res.data.success
            ? "✓ Routing updated"
            : res.data.message;

        routeStatus.dataset.keep = "1";

        await this.loadRouting();

        // The Routed status card depends on forwarding.
        await this.load();

    },


    async addRule() {

        fwAddStatus.textContent = "Adding...";

        const res = await this.send("/api/firewall/rules", {
            action: fwActionInput.value,
            direction: fwDirectionInput.value,
            interface: fwInterfaceInput.value,
            proto: fwProtoInput.value,
            port: fwPortInput.value.trim(),
            from: fwFromInput.value.trim() || "any",
            to: fwToInput.value.trim() || "any",
            comment: fwCommentInput.value.trim()
        });

        if (!res) return;

        if (!res.data.success) {
            fwAddStatus.textContent = res.data.message;
            return;
        }

        fwAddStatus.textContent = `✓ ${res.data.message}`;

        fwPortInput.value = "";
        fwFromInput.value = "";
        fwToInput.value = "";
        fwCommentInput.value = "";

        await this.load();

    },


    async deleteRule(rule) {

        const body = document.createElement("div");

        body.innerHTML = `<code class="modal-code">ufw ${this.escape(rule.spec)}</code>`;

        const confirmed = await ChaosModal.confirm({
            title: "Delete Rule",
            subtitle: "This rule will be removed immediately.",
            body: body,
            confirmText: "Delete"
        });

        if (!confirmed) return;

        fwRuleStatus.textContent = "Deleting...";

        const res = await this.send(
            "/api/firewall/rules",
            { id: rule.id },
            "DELETE"
        );

        if (!res) return;

        await this.load();

        // Set after reloading, which resets the rule status line.
        fwRuleStatus.textContent = res.data.success
            ? "✓ Rule deleted"
            : res.data.message;

    },


    // Limit only makes sense for incoming traffic.
    updateDirectionState() {

        const limit = fwActionInput.value === "limit";

        if (limit) fwDirectionInput.value = "in";

        fwDirectionInput.disabled = limit;

        ChaosSelect.refresh(fwDirectionInput);

    },


    init() {

        this.selects.forEach(id => {
            ChaosSelect.enhance(document.getElementById(id));
        });

        fwToggle.onclick = () => this.toggle();

        fwSavePolicies.onclick = () => this.savePolicies();

        routeSave.onclick = () => this.saveRouting();

        fwAddRule.onclick = () => this.addRule();

        fwActionInput.onchange = () => this.updateDirectionState();

        this.load();

        this.loadRouting();

    },


    destroy() {

        ChaosModal.close();

    }

};
