const DEFAULT_ROUTE = "dashboard";

async function loadPage(route) {
    try {
        const response = await fetch(`/fragment/${route}`);

        if (!response.ok) {
            throw new Error("Page not found");
        }

        const html = await response.text();
        document.getElementById("content").innerHTML = html;
	const routeScript = document.createElement("script");
	routeScript.src = `/static/js/${route}.js`;
	routeScript.onerror = () => {};
	document.body.appendChild(routeScript);

        document.querySelectorAll(".sidebar a").forEach(link => {
            link.classList.toggle(
                "active",
                link.dataset.route === route
            );
        });

    } catch {
        if (route !== DEFAULT_ROUTE) {
            location.hash = "#/" + DEFAULT_ROUTE;
        }
    }
}

function getRoute() {
    const hash = location.hash.replace("#/", "");
    return hash || DEFAULT_ROUTE;
}

window.addEventListener("hashchange", () => {
    loadPage(getRoute());
});

window.addEventListener("DOMContentLoaded", () => {
    if (!location.hash) {
        location.hash = "#/" + DEFAULT_ROUTE;
    } else {
        loadPage(getRoute());
    }
});
