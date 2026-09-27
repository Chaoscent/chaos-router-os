from flask import Flask, render_template, abort

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

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
