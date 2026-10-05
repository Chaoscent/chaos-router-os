/*
 * Adds the session's CSRF token (from <meta name="csrf-token">) to
 * every same-origin request that changes something. The server
 * rejects such requests without it. Loaded before all other scripts.
 */

(() => {

    const token = document.querySelector('meta[name="csrf-token"]')?.content;

    if (!token || window.fetch.chaosCsrf) return;

    const rawFetch = window.fetch.bind(window);

    const isSameOrigin = input => {

        const url = typeof input === "string" ? input : input.url;

        return new URL(url, location.href).origin === location.origin;

    };

    window.fetch = (input, options = {}) => {

        const method = (options.method || input.method || "GET").toUpperCase();

        if (method !== "GET" && method !== "HEAD" && isSameOrigin(input)) {

            const headers = new Headers(options.headers || (typeof input === "string" ? {} : input.headers));

            headers.set("X-CSRF-Token", token);

            options = { ...options, headers };

        }

        return rawFetch(input, options);

    };

    window.fetch.chaosCsrf = true;

})();


/** Logs out with a POST, so other sites cannot trigger it. */
async function chaosLogout() {

    try {
        await fetch("/logout", { method: "POST" });
    } catch {}

    location.href = "/login";

}
