const DEFAULT_ROUTE = "dashboard";


// ------------------------------------------------------------
// Mobile menu: the sidebar slides in on narrow screens.
// ------------------------------------------------------------

function setNavOpen(open){

    document.body.classList.toggle("nav-open", open);

    document.getElementById("navToggle")
        ?.setAttribute("aria-expanded", String(open));

}

document.addEventListener("DOMContentLoaded", ()=>{

    document.getElementById("navToggle")?.addEventListener("click", ()=>{
        setNavOpen(!document.body.classList.contains("nav-open"));
    });

    document.getElementById("navBackdrop")?.addEventListener("click", ()=>{
        setNavOpen(false);
    });

    // Phones: the shell needs a keyboard, so its entry is greyed out
    // (CSS) and cannot be opened (also not from the keyboard).
    const mobile = window.matchMedia("(max-width: 900px), (hover: none) and (pointer: coarse)");

    const markMobileOnly = () => {
        document.querySelectorAll(".sidebar a.nav-desktop-only").forEach(link=>{
            link.setAttribute("aria-disabled", String(mobile.matches));
            link.tabIndex = mobile.matches ? -1 : 0;
            link.title = mobile.matches ? link.dataset.mobileTitle || "" : "";
        });
    };

    markMobileOnly();
    mobile.addEventListener("change", markMobileOnly);

    document.querySelectorAll(".sidebar a.nav-desktop-only").forEach(link=>{
        link.addEventListener("click", event=>{
            if(mobile.matches) event.preventDefault();
        });
    });

    // Picking a page closes the menu.
    document.querySelectorAll(".sidebar nav a").forEach(link=>{
        link.addEventListener("click", ()=>setNavOpen(false));
    });

    document.addEventListener("keydown", event=>{
        if(event.key === "Escape") setNavOpen(false);
    });

});

let currentPage = null;

// Counts navigations: a page that finishes loading after a newer one
// was requested is dropped, so its script never runs on the wrong page.
let navigation = 0;

async function loadPage(route){

    const id = ++navigation;

    if(window.Page?.[currentPage]?.destroy){
        window.Page[currentPage].destroy();
    }

    currentPage = null;

    try{

        const response = await fetch(`/fragment/${route}`);

        // Session expired
        if(response.status === 401){
            window.location.href = "/login";
            return;
        }

        if(!response.ok){
            throw new Error();
        }

        const html = await response.text();

        if(id !== navigation) return;

        document.getElementById("content").innerHTML = html;

        document.querySelectorAll(".sidebar a").forEach(link=>{
            link.classList.toggle(
                "active",
                link.dataset.route===route
            );
        });

        await loadController(route);

        if(id !== navigation) return;

        currentPage = route;

        window.Page?.[route]?.init?.();

    }catch{

        if(id === navigation && route !== DEFAULT_ROUTE){
            location.hash = `#/${DEFAULT_ROUTE}`;
        }

    }

}

async function loadController(route){

    const existing = document.getElementById("page-controller");

    if(existing){
        existing.remove();
    }

    return new Promise(resolve=>{

        const script = document.createElement("script");

        script.id = "page-controller";
        script.src = `/static/js/${route}.js?v=${window.ASSET_VERSION || ""}`;

        script.onload = resolve;
        script.onerror = resolve;

        document.body.appendChild(script);

    });

}

function getRoute(){

    return location.hash.replace("#/","") || DEFAULT_ROUTE;

}

window.addEventListener("hashchange",()=>{

    loadPage(getRoute());

});

window.addEventListener("DOMContentLoaded",()=>{

    if(!location.hash){
        location.hash = `#/${DEFAULT_ROUTE}`;
    }else{
        loadPage(getRoute());
    }

});