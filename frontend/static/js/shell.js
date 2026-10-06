window.Page = window.Page || {};

/*
 * Web shell: xterm.js connected to a shell on the router over a
 * WebSocket. The password is asked for every session; the server
 * answers with a one-time key for the WebSocket.
 */
window.Page.shell = {

    term: null,
    fit: null,
    ws: null,
    resizeObserver: null,

    // Phones and tablets without a keyboard: greyed out in the sidebar.
    MOBILE_QUERY: "(max-width: 900px), (hover: none) and (pointer: coarse)",

    VENDOR: "/static/vendor/xterm",


    // ------------------------------------------------------------
    // xterm.js, loaded only on this page
    // ------------------------------------------------------------

    loadScript(src) {

        return new Promise((resolve, reject) => {

            if ([...document.scripts].some(s => s.src.endsWith(src))) return resolve();

            const script = document.createElement("script");
            script.src = src;
            script.onload = resolve;
            script.onerror = () => reject(new Error(`Could not load ${src}`));
            document.head.appendChild(script);

        });

    },

    async loadTerminal() {

        if (!document.getElementById("xtermCss")) {
            const link = document.createElement("link");
            link.id = "xtermCss";
            link.rel = "stylesheet";
            link.href = `${this.VENDOR}/xterm.css`;
            document.head.appendChild(link);
        }

        await this.loadScript(`${this.VENDOR}/xterm.js`);
        await this.loadScript(`${this.VENDOR}/addon-fit.js`);

    },


    // ------------------------------------------------------------
    // States
    // ------------------------------------------------------------

    notice(title, text, link = false) {

        shellNoticeTitle.textContent = title;
        shellNoticeText.textContent = text;
        shellNoticeLink.classList.toggle("hidden", !link);
        shellNotice.classList.remove("hidden");
        shellUnlock.classList.add("hidden");

    },

    async load() {

        if (window.matchMedia(this.MOBILE_QUERY).matches) {
            this.notice("Not available on this device",
                "The shell needs a computer with a keyboard. Open the dashboard on a computer to use it.");
            return;
        }

        const res = await fetch("/api/shell/status");

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        const status = await res.json();

        if (!status.enabled) {
            this.notice("The shell is turned off",
                "Turn it on in the System page (Maintenance > Web Shell). It is off by default because it gives full control over the router.",
                true);
            return;
        }

        if (!status.allowed) {
            this.notice("Not available from here", status.reason);
            return;
        }

        shellNotice.classList.add("hidden");
        shellUnlock.classList.remove("hidden");
        shellPasswordInput.focus();

    },


    // ------------------------------------------------------------
    // Session
    // ------------------------------------------------------------

    async open() {

        const password = shellPasswordInput.value;

        if (!password) {
            shellUnlockStatus.textContent = "Enter your password.";
            return;
        }

        shellOpen.disabled = true;
        shellUnlockStatus.textContent = "Checking...";

        let data = {};

        try {

            const res = await fetch("/api/shell/unlock", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ password })
            });

            data = await res.json();

        } catch {
            data = { message: "The router did not answer." };
        }

        shellOpen.disabled = false;
        shellPasswordInput.value = "";

        if (!data.success) {
            shellUnlockStatus.textContent = data.message || "The shell could not be opened.";
            return;
        }

        shellUnlockStatus.textContent = "";

        try {
            await this.loadTerminal();
        } catch (err) {
            shellUnlockStatus.textContent = err.message;
            return;
        }

        this.connect(data.token);

    },

    connect(token) {

        shellUnlock.classList.add("hidden");
        shellTerminalCard.classList.remove("hidden");
        shellState.textContent = "Connecting...";

        this.term = new Terminal({
            cursorBlink: true,
            fontFamily: "ui-monospace, SFMono-Regular, Consolas, 'DejaVu Sans Mono', monospace",
            fontSize: 14,
            scrollback: 5000,
            theme: {
                background: "#0f1117",
                foreground: "#e8eef7",
                cursor: "#4ea1ff",
                selectionBackground: "rgba(78,161,255,.35)"
            }
        });

        this.fit = new FitAddon.FitAddon();
        this.term.loadAddon(this.fit);
        this.term.open(shellTerminal);
        this.fit.fit();
        this.term.focus();

        const scheme = location.protocol === "https:" ? "wss" : "ws";

        this.ws = new WebSocket(`${scheme}://${location.host}/api/shell/ws?token=${encodeURIComponent(token)}`);

        const send = message => {
            if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(message));
        };

        const sendSize = () => send({ type: "resize", rows: this.term.rows, cols: this.term.cols });

        this.ws.onopen = () => {
            shellState.textContent = "Connected";
            shellState.classList.add("connected");
            sendSize();
        };

        this.ws.onmessage = event => this.term.write(event.data);

        this.ws.onclose = () => this.closed();

        this.term.onData(data => send({ type: "input", data }));
        this.term.onResize(sendSize);

        // Follow the window and sidebar size.
        this.resizeObserver = new ResizeObserver(() => {
            try { this.fit.fit(); } catch {}
        });

        this.resizeObserver.observe(shellTerminal);

    },

    closed() {

        shellState.textContent = "Disconnected";
        shellState.classList.remove("connected");

        this.term?.write("\r\n\x1b[90m[Disconnected. Enter your password to open a new shell.]\x1b[0m\r\n");

        this.ws = null;

        shellUnlock.classList.remove("hidden");

    },

    disconnect() {

        this.ws?.close();

    },

    teardown() {

        if (this.ws) {
            this.ws.onclose = null;
            this.ws.close();
            this.ws = null;
        }

        this.resizeObserver?.disconnect();
        this.resizeObserver = null;

        this.term?.dispose();
        this.term = null;

    },


    // ------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------

    init() {

        shellOpen.onclick = () => {
            this.teardown();
            shellTerminalCard.classList.add("hidden");
            this.open();
        };

        shellPasswordInput.addEventListener("keydown", event => {
            if (event.key === "Enter") shellOpen.click();
        });

        shellClose.onclick = () => this.disconnect();

        this.load();

    },

    destroy() {

        // Leaving the page closes the shell.
        this.teardown();

    }

};
