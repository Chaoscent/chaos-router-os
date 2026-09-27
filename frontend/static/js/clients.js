window.Page = window.Page || {};

window.Page.clients = {

    timer:null,

    selected:null,

    async update(){

        const res = await fetch("/api/clients");

        if(res.status===401){
            location.href="/login";
            return;
        }

        const clients = await res.json();

        clientTable.innerHTML="";

        clients.forEach(client=>{

            const row=document.createElement("tr");

            if(this.selected===client.ip){
                row.classList.add("selected");
            }

            row.innerHTML=`
                <td>
                    <strong>${client.hostname}</strong><br>
                    <small>${client.mac}</small>
                </td>

                <td>${client.ip}</td>

                <td>${client.interface}</td>

                <td>
                    <span class="status">
                        ${client.state}
                    </span>
                </td>
            `;

            row.onclick=()=>this.select(client);

            clientTable.appendChild(row);

        });

    },

    select(client){

        this.selected=client.ip;

        inspectorName.textContent=client.hostname;
        inspectorIP.textContent=client.ip;
        inspectorMAC.textContent=client.mac;
        inspectorVendor.textContent=client.vendor;
        inspectorInterface.textContent=client.interface;
        inspectorStatus.textContent=client.state;

        clientInspector.classList.add("open");

        this.update();

    },

    close(){

        this.selected=null;

        clientInspector.classList.remove("open");

        this.update();

    },

    init(){

        closeInspector.onclick=()=>this.close();

        this.update();

        this.timer=setInterval(()=>this.update(),2000);

    },

    destroy(){

        clearInterval(this.timer);

    }

};