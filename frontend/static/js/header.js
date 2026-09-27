window.Header={

timer:null,

async update(){

    try{

        const res=await fetch("/api/header");

        if(res.status===401){
            location.href="/login";
            return;
        }

        const data=await res.json();

        headerNetwork.textContent = data.network;
        headerModule.textContent = data.model;
        headerCarrier.textContent = data.carrier;
        headerPing.textContent = data.ping;
        headerTime.textContent = data.time;
        headerUser.textContent = data.user;

        pulseDown.textContent=`↓ ${data.rx.toFixed(1)} Mbps`;
        pulseUp.textContent=`↑ ${data.tx.toFixed(1)} Mbps`;

        const total=Math.min(data.rx+data.tx,200);

        pulseFill.style.width=`${Math.max(8,total/2)}%`;

    }catch{}

},

init(){

    this.update();

    this.timer=setInterval(()=>this.update(),1000);

}

};

window.addEventListener("DOMContentLoaded",()=>Header.init());