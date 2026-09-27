window.Page = {

    dashboard:{

        timer:null,

        async update(){

            const res=await fetch("/api/dashboard");
            const data=await res.json();

            document.getElementById("hostname").textContent=data.hostname;
            document.getElementById("ip").textContent=data.ip;

            document.getElementById("cpu_temp").textContent=
                data.cpu_temp ? `${data.cpu_temp}°C` : "--";

            document.getElementById("ram").textContent=`${data.ram}%`;
            document.getElementById("uptime").textContent=data.uptime;
            document.getElementById("time").textContent=data.time;

        },

        init(){

            this.update();

            this.timer=setInterval(()=>this.update(),2000);

        },

        destroy(){

            clearInterval(this.timer);

        }

    }

};
