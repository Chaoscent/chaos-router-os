window.Page = window.Page || {};

window.Page.system = {

    async load() {

        const res = await fetch("/api/dashboard");

        if (res.status === 401) {
            location.href = "/login";
            return;
        }

        const data = await res.json();

        hostnameInput.value = data.hostname;

    },

    async save() {

        hostnameStatus.textContent = "Saving...";

        const res = await fetch("/api/system/hostname", {

            method: "POST",

            headers: {
                "Content-Type": "application/json"
            },

            body: JSON.stringify({
                hostname: hostnameInput.value.trim()
            })

        });

        const data = await res.json();

        if (data.success) {

            hostnameStatus.textContent = "✓ Hostname updated";

            if (window.Header?.update) {
                Header.update();
            }

        } else {

            hostnameStatus.textContent = data.message;

        }

    },

    init() {

        this.load();

        saveHostname.onclick = () => this.save();

        hostnameInput.addEventListener("keydown", (e) => {

            if (e.key === "Enter") {
                this.save();
            }

        });

    },

    destroy() {}

};
