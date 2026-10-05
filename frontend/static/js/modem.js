window.Page=window.Page||{};

window.Page.modem={

timer:null,

async update(){

    const res=await fetch("/api/modem");

    if(res.status===401){
        location.href="/login";
        return;
    }

    const d=await res.json();

    // Unknown values are null: show "--", never invented numbers.
    const show=(value,unit="")=>value===null||value===undefined?"--":`${value}${unit}`;

    modemNotice.classList.toggle("hidden",d.state==="ready");

    modemNotice.textContent=
        d.state==="absent"
            ?"No modem found. Plug in the modem; this page updates by itself."
            :`${d.model||"The modem"} was found but does not answer yet. It can take a minute after startup.`;

    carrier.textContent=show(d.carrier);
    network.textContent=d.state==="absent"?"No modem":show(d.network);
    signal.textContent=show(d.signal,"%");

    rsrp.textContent=show(d.rsrp," dBm");
    rsrq.textContent=show(d.rsrq," dB");
    sinr.textContent=show(d.sinr," dB");

    band.textContent=show(d.band);
    sim.textContent=show(d.sim);
    imei.textContent=show(d.imei);

},

init(){

    this.update();
    this.timer=setInterval(()=>this.update(),3000);

},

destroy(){

    clearInterval(this.timer);

}

};