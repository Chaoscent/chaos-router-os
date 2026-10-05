/*
 * Safe apply banner.
 *
 * Changes that can cut the browser off (network, firewall, Wi-Fi, ...)
 * are applied but not saved until confirmed here. If this page cannot
 * reach the router any more, nobody confirms and the router reverts
 * them by itself when the countdown ends.
 */

window.ChaosApply = {

    pending: null,
    deadline: 0,
    pollTimer: null,
    tickTimer: null,
    busy: false,

    SEEN_KEY: "chaos-last-revert-seen",


    async check() {

        let data;

        try {

            const res = await this.rawFetch("/api/config/pending");

            if (!res.ok) return;

            data = await res.json();

        } catch {
            // Router unreachable: keep counting down locally.
            return;
        }

        const wasPending = Boolean(this.pending);

        this.pending = data.pending;

        if (this.pending) {

            this.deadline = Date.now() + this.pending.remaining * 1000;
            this.showPending();

        } else {

            this.hidePending();

            if (wasPending) {
                // Reverted on the router (timeout) while we waited.
                this.reloadPage();
            }

        }

        this.showRevertNotice(data.last_revert);

    },


    showPending() {

        const areas = this.pending.areas.map(a => a.label).join(", ");

        applyBannerTitle.textContent = `${areas}: new settings are active.`;

        const hints = this.pending.areas
            .map(a => a.hint)
            .filter(Boolean);

        applyBannerHint.textContent = hints.join(" ");
        applyBannerHint.classList.toggle("hidden", !hints.length);

        applyBanner.classList.remove("hidden");

        this.tick();

        if (!this.tickTimer) {
            this.tickTimer = setInterval(() => this.tick(), 1000);
        }

        if (!this.pollTimer) {
            this.pollTimer = setInterval(() => this.check(), 3000);
        }

    },


    hidePending() {

        applyBanner.classList.add("hidden");

        clearInterval(this.tickTimer);
        clearInterval(this.pollTimer);

        this.tickTimer = null;
        this.pollTimer = null;

    },


    tick() {

        const seconds = Math.max(0, Math.round((this.deadline - Date.now()) / 1000));

        const m = Math.floor(seconds / 60);
        const s = String(seconds % 60).padStart(2, "0");

        applyBannerCountdown.textContent =
            `Keep them, or they are reverted in ${m}:${s}.`;

    },


    // Tell the user once when the router reverted changes by itself.
    showRevertNotice(revert) {

        if (!revert) return;

        let seen = 0;

        try {
            seen = Number(localStorage.getItem(this.SEEN_KEY)) || 0;
        } catch {}

        if (revert.time <= seen) return;

        const areas = revert.areas.map(a => a.label).join(", ");

        applyNoticeText.textContent =
            `${areas}: changes were reverted. ${revert.reason}`;

        applyNotice.dataset.time = revert.time;
        applyNotice.classList.remove("hidden");

    },


    dismissNotice() {

        try {
            localStorage.setItem(this.SEEN_KEY, applyNotice.dataset.time);
        } catch {}

        applyNotice.classList.add("hidden");

    },


    async resolve(action) {

        if (this.busy) return;

        this.busy = true;

        applyKeep.disabled = true;
        applyRevert.disabled = true;

        applyBannerCountdown.textContent =
            action === "confirm" ? "Saving..." : "Reverting...";

        try {

            const res = await this.rawFetch(`/api/config/${action}`, {
                method: "POST"
            });

            const data = await res.json();

            applyNoticeText.textContent = data.message;

        } catch {

            applyNoticeText.textContent =
                "The router did not answer. Unconfirmed changes revert automatically.";

        }

        this.busy = false;

        applyKeep.disabled = false;
        applyRevert.disabled = false;

        this.pending = null;
        this.hidePending();

        // Show the result briefly in the notice line.
        applyNotice.dataset.time = Math.floor(Date.now() / 1000);
        applyNotice.classList.remove("hidden");

        if (action === "revert") {
            this.reloadPage();
        }

    },


    // Pages show the restored settings after a revert.
    reloadPage() {

        if (typeof loadPage === "function" && typeof getRoute === "function") {
            loadPage(getRoute());
        }

    },


    init() {

        // Never wrap fetch twice.
        if (this.rawFetch) return;

        this.rawFetch = window.fetch.bind(window);

        // After any change request, look for pending changes.
        window.fetch = async (input, options = {}) => {

            const response = await this.rawFetch(input, options);

            const url = typeof input === "string" ? input : input.url;
            const method = (options.method || "GET").toUpperCase();

            if (
                method !== "GET"
                && url.startsWith("/api/")
                && !url.startsWith("/api/config/")
            ) {
                this.check();
            }

            return response;

        };

        applyKeep.onclick = () => this.resolve("confirm");
        applyRevert.onclick = () => this.resolve("revert");
        applyNoticeClose.onclick = () => this.dismissNotice();

        this.check();

    }

};


document.addEventListener("DOMContentLoaded", () => ChaosApply.init());
