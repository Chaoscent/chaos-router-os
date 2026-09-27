async function updateDashboard(){

    const res = await fetch("/api/dashboard");
    const data = await res.json();

    document.getElementById("hostname").textContent = data.hostname;
    document.getElementById("ip").textContent = data.ip;
    document.getElementById("cpu_temp").textContent =
        data.cpu_temp ? `${data.cpu_temp}°C` : "--";

    document.getElementById("ram").textContent = `${data.ram}%`;
    document.getElementById("uptime").textContent = data.uptime;
    document.getElementById("time").textContent = data.time;
}

updateDashboard();
setInterval(updateDashboard,2000);
