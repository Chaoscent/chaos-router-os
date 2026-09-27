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

    carrier.textContent=d.carrier;
    network.textContent=d.network;
    signal.textContent=`${d.signal}%`;

    rsrp.textContent=`${d.rsrp} dBm`;
    rsrq.textContent=`${d.rsrq} dB`;
    sinr.textContent=`${d.sinr} dB`;

    band.textContent=d.band;
    sim.textContent=d.sim;
    imei.textContent=d.imei;

},

init(){

    this.update();
    this.timer=setInterval(()=>this.update(),3000);

},

destroy(){

    clearInterval(this.timer);

}

};