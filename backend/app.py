from flask import Flask, render_template, abort, jsonify
from services.system import (
    get_hostname,
    get_ip,
    get_uptime,
    get_cpu_temp,
    get_ram,
    get_time
)

app = Flask(
    __name__,
    template_folder="../frontend/templates",
    static_folder="../frontend/static"
)

# Permanent shell
@app.route("/")
def index():
    return render_template("base.html")

# HTML fragments for the SPA
VALID_PAGES = {
    "dashboard",
    "network",
    "vpn",
    "modem",
    "logs",
    "system",
    "apps"
}

@app.route("/fragment/<page>")
def fragment(page):
    if page not in VALID_PAGES:
        abort(404)
    return render_template(f"{page}.html")

@app.route("/api/dashboard")
def dashboard_api():
    return jsonify({
        "hostname": get_hostname(),
        "ip": get_ip(),
        "uptime": get_uptime(),
        "cpu_temp": get_cpu_temp(),
        "ram": get_ram(),
        "time": get_time()
    })

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
