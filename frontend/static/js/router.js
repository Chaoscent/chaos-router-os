const DEFAULT_ROUTE = "dashboard";

let currentPage = null;

async function loadPage(route){

    if(window.Page?.[currentPage]?.destroy){
        window.Page[currentPage].destroy();
    }

    try{

        const response = await fetch(`/fragment/${route}`);

        if(!response.ok){
            throw new Error();
        }

        document.getElementById("content").innerHTML =
            await response.text();

        document.querySelectorAll(".sidebar a").forEach(link=>{
            link.classList.toggle(
                "active",
                link.dataset.route===route
            );
        });

        currentPage = route;

        await loadController(route);

        window.Page?.[route]?.init?.();

    }catch{

        if(route!==DEFAULT_ROUTE){
            location.hash=`#/${DEFAULT_ROUTE}`;
        }

    }

}

async function loadController(route){

    const existing=document.getElementById("page-controller");

    if(existing){
        existing.remove();
    }

    return new Promise(resolve=>{

        const script=document.createElement("script");

        script.id="page-controller";
        script.src=`/static/js/${route}.js`;

        script.onload=resolve;
        script.onerror=resolve;

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

        location.hash=`#/${DEFAULT_ROUTE}`;

    }else{

        loadPage(getRoute());

    }

});
