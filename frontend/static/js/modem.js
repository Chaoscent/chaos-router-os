window.Page=window.Page||{};

window.Page.modem={

timer:null,

// Mobile data settings as saved (the PIN and password stay on the router).
mobile:null,

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
            :d.state==="no_modemmanager"
            ?`${d.model||"The modem"} was found, but ModemManager is not installed (sudo apt install modemmanager), so it cannot be used.`
            :`${d.model||"The modem"} was found but does not answer yet. It can take a minute after startup.`;

    carrier.textContent=show(d.carrier);
    network.textContent=d.state==="absent"?"No modem":show(d.network);
    signal.textContent=show(d.signal,"%");

    rsrp.textContent=show(d.rsrp," dBm");
    rsrq.textContent=show(d.rsrq," dB");
    sinr.textContent=show(d.sinr," dB");

    band.textContent=show(d.band);
    sim.textContent=d.lock==="sim-pin"?"Waiting for PIN":d.lock==="sim-puk"?"Blocked (PUK)":show(d.sim);
    imei.textContent=show(d.imei);

    this.renderSim(d);
    this.renderDataLink(d);

    const onlyV6=d.connection==="activated"&&d.ipv6&&!d.ipv4;

    mobileConnection.textContent=onlyV6?"Connected (IPv6 only)":{
        activated:"Connected",
        activating:"Connecting...",
        deactivating:"Disconnecting...",
        deactivated:"Not connected"
    }[d.connection]||(this.mobile?.enabled?"Not connected":"Off");

},

renderDataLink(d){

    usbMode.textContent=d.usb_mode?d.usb_mode.toUpperCase():"--";

    mobileAddresses.textContent=[d.ipv4,d.ipv6].filter(Boolean).join(" · ")||"--";

    const sw=d.usb_switch||{};
    const show=d.data_dropped||sw.running||(sw.message&&sw.success===false);

    modemDataCard.classList.toggle("hidden",!show);

    if(!show)return;

    modemDataInfo.textContent=d.quectel&&d.usb_mode==="mbim"
        ?`Mobile data is connected, but the modem's received data is discarded: ${d.rx_errors} received packets were dropped as errors. Quectel modems do this in MBIM mode on Linux. QMI mode fixes it; the modem restarts once (about a minute without mobile data).`
        :`Mobile data is connected, but ${d.rx_errors} received packets were dropped as errors.`;

    modemSwitchQmi.classList.toggle("hidden",!(d.quectel&&d.usb_mode==="mbim"));
    modemSwitchQmi.disabled=!!sw.running;

    modemDataStatus.textContent=sw.running
        ?"Switching... the modem restarts, this page updates by itself."
        :sw.message||"";

},

async switchQmi(){

    modemSwitchQmi.disabled=true;
    modemDataStatus.textContent="Starting...";

    const res=await fetch("/api/modem/usb-mode",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({mode:"qmi"})
    });

    const data=await res.json().catch(()=>({message:"Unexpected server response."}));

    modemDataStatus.textContent=data.message;

    await this.update();

},

renderSim(d){

    const locked=d.lock==="sim-pin"||d.lock==="sim-puk";

    simPinCard.classList.toggle("hidden",!locked);

    if(!locked)return;

    const puk=d.lock==="sim-puk";

    simPinInfo.textContent=puk
        ?"The SIM is blocked after too many wrong PINs. Unblock it with its PUK in a phone, then put it back."
        :`The SIM is locked. Enter its PIN to use mobile data${d.pin_retries?` (${d.pin_retries} attempts left)`:""}. It is sent once per click, never retried by itself.`;

    simPinInput.disabled=simPinUnlock.disabled=puk;

},

async unlock(){

    const pin=simPinInput.value.trim();

    if(!/^\d{4,8}$/.test(pin)){
        simPinStatus.textContent="The PIN has 4 to 8 digits.";
        return;
    }

    simPinUnlock.disabled=true;
    simPinStatus.textContent="Unlocking...";

    const res=await fetch("/api/modem/unlock",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({pin,remember:simPinRemember.checked})
    });

    const data=await res.json().catch(()=>({message:"Unexpected server response."}));

    simPinUnlock.disabled=false;
    simPinInput.value="";
    simPinStatus.textContent=data.success?`✓ ${data.message}`:data.message;

    await this.loadMobile();
    await this.update();

},

async loadMobile(){

    const res=await fetch("/api/modem/settings");

    if(!res.ok)return;

    this.mobile=await res.json();

    mobileEnabledInput.value=String(this.mobile.enabled);
    mobileRoamingInput.value=String(this.mobile.roaming);
    mobileApnInput.value=this.mobile.apn||"";
    mobileUsernameInput.value=this.mobile.username||"";
    mobilePasswordInput.value="";
    mobilePasswordInput.placeholder=this.mobile.password_saved?"Saved (leave empty to keep)":"Usually not needed";

    mobilePinNote.textContent=this.mobile.pin_saved
        ?"The SIM PIN is saved: the SIM is unlocked at every start."
        :"";

    mobileForgetPin.classList.toggle("hidden",!this.mobile.pin_saved);

    ["mobileEnabledInput","mobileRoamingInput"].forEach(id=>ChaosSelect.refresh(document.getElementById(id)));

},

async saveMobile(extra={}){

    mobileSave.disabled=true;
    mobileStatus.textContent="Applying...";

    const res=await fetch("/api/modem/settings",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({
            enabled:mobileEnabledInput.value==="true",
            roaming:mobileRoamingInput.value==="true",
            apn:mobileApnInput.value.trim(),
            username:mobileUsernameInput.value,
            password:mobilePasswordInput.value,
            ...extra
        })
    });

    const data=await res.json().catch(()=>({message:"Unexpected server response."}));

    mobileSave.disabled=false;
    mobileStatus.textContent=data.success?`✓ ${data.message}`:data.message||"Failed to save.";

    await this.loadMobile();
    await this.update();

},

init(){

    ["mobileEnabledInput","mobileRoamingInput"].forEach(id=>ChaosSelect.enhance(document.getElementById(id)));

    modemSwitchQmi.onclick=()=>this.switchQmi();

    simPinUnlock.onclick=()=>this.unlock();
    simPinInput.onkeydown=event=>{ if(event.key==="Enter")this.unlock(); };

    mobileSave.onclick=()=>this.saveMobile();
    mobileForgetPin.onclick=()=>this.saveMobile({forget_pin:true});

    this.loadMobile();
    this.update();
    this.timer=setInterval(()=>this.update(),3000);

},

destroy(){

    clearInterval(this.timer);

}

};
