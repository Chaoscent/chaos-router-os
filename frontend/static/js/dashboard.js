window.Page = window.Page || {};

window.Page.dashboard = {

    timer:null,

    async update(){

        const res = await fetch("/api/dashboard");

        if(res.status===401){
            location.href="/login";
            return;
        }

        const data = await res.json();

        hostname.textContent=data.hostname;
        ip.textContent=data.ip;
        cpu.textContent=data.cpu_temp;
        ram.textContent=data.ram;
        uptime.textContent=data.uptime;
        time.textContent=data.time;

        clients.textContent=data.clients;
        active.textContent=data.active;
        download.textContent=`${data.download.toFixed(1)} Mbps`;
        upload.textContent=`${data.upload.toFixed(1)} Mbps`;

        this.drawGraph(data.history);

    },

    drawGraph(history){

        if(!history.length) return;

        const w=600;
        const h=180;

        const max=Math.max(
            10,
            ...history.map(p=>Math.max(p.rx,p.tx))
        );

        const makeLine=(key)=>history.map((p,i)=>{

            const x=i*(w/(history.length-1||1));
            const y=h-20-(p[key]/max)*(h-40);

            return `${x},${y}`;

        }).join(" ");

        downloadLine.setAttribute("points",makeLine("rx"));
        uploadLine.setAttribute("points",makeLine("tx"));

    },

    init(){

        this.update();
        this.timer=setInterval(()=>this.update(),1000);

    },

    destroy(){

        clearInterval(this.timer);

    }

};