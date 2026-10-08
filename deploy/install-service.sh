#!/usr/bin/env bash
#
# Installs Chaos Router OS as a systemd service that starts at boot.
#
#   sudo deploy/install-service.sh            install (or update) and start
#   sudo deploy/install-service.sh --remove   stop and remove the service
#
# Run it from the cloned repo after creating the virtualenv
# (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt).
# The app runs as the user who called sudo.
#
# With Caddy installed (apt install caddy), deploy/Caddyfile becomes
# /etc/caddy/Caddyfile: Caddy serves the dashboard on ports 80 and 443
# and the app only listens on 127.0.0.1:5000. Without Caddy the app
# listens on port 5000 of every address.

set -euo pipefail

SERVICE=chaos-router-os
UNIT_FILE=/etc/systemd/system/$SERVICE.service
STATE_DIR=/var/lib/chaos-router-os

APP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEMPLATE=$APP_DIR/deploy/$SERVICE.service

CADDYFILE=/etc/caddy/Caddyfile
CADDY_BACKUP=/etc/caddy/Caddyfile.before-chaos
# First line of deploy/Caddyfile: tells our config from someone else's.
CADDY_MARKER="# Chaos Router OS: Caddy in front of the dashboard."

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo: sudo $0 $*" >&2
    exit 1
fi

# --- Remove ---------------------------------------------------------

if [[ ${1:-} == "--remove" ]]; then

    systemctl disable --now "$SERVICE" 2>/dev/null || true
    rm -f "$UNIT_FILE"
    systemctl daemon-reload

    # Caddy: back to the config it had before, or stopped (ours would
    # only lead to the removed app).
    if grep -qxF "$CADDY_MARKER" "$CADDYFILE" 2>/dev/null; then

        if [[ -f $CADDY_BACKUP ]]; then
            mv "$CADDY_BACKUP" "$CADDYFILE"
            systemctl try-restart caddy 2>/dev/null || true
            echo "Restored the previous $CADDYFILE."
        else
            systemctl disable --now caddy 2>/dev/null || true
            echo "Caddy stopped and disabled (its config was for Chaos Router OS)."
        fi

    fi

    echo "Service removed. Settings in $STATE_DIR were kept."
    exit 0
fi

# --- Install --------------------------------------------------------

APP_USER=${SUDO_USER:-}

if [[ -z $APP_USER || $APP_USER == "root" ]]; then
    echo "Run this with sudo from the user account the app should run as." >&2
    exit 1
fi

APP_GROUP=$(id -gn "$APP_USER")

if [[ ! -x $APP_DIR/.venv/bin/gunicorn ]]; then
    echo "No virtualenv with gunicorn in $APP_DIR/.venv. Create it first:" >&2
    echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

# The app makes system changes with `sudo -n`.
if ! sudo -u "$APP_USER" sudo -n true 2>/dev/null; then
    echo "Warning: $APP_USER has no passwordless sudo. The dashboard will" >&2
    echo "start, but cannot change system settings." >&2
fi

# Persistent settings belong to the app user (everything inside too).
mkdir -p "$STATE_DIR"
chown -R "$APP_USER:$APP_GROUP" "$STATE_DIR"

# --- Caddy ----------------------------------------------------------

install_caddyfile() {

    # Syntax check only: `caddy validate` would also create a CA.
    if ! caddy adapt --adapter caddyfile --config "$APP_DIR/deploy/Caddyfile" >/dev/null 2>&1; then
        echo "Warning: this Caddy version does not accept deploy/Caddyfile." >&2
        return 1
    fi

    mkdir -p "$(dirname "$CADDYFILE")"

    # Keep a config that isn't ours, once.
    if [[ -f $CADDYFILE && ! -f $CADDY_BACKUP ]] && ! grep -qxF "$CADDY_MARKER" "$CADDYFILE"; then
        cp -p "$CADDYFILE" "$CADDY_BACKUP"
        echo "Kept the previous Caddy config as $CADDY_BACKUP."
    fi

    install -m 644 "$APP_DIR/deploy/Caddyfile" "$CADDYFILE"

    # Routes of installed apps (Apps Addon), written by the app.
    mkdir -p "$(dirname "$CADDYFILE")/chaos-apps"
}

if command -v caddy >/dev/null && install_caddyfile; then
    BIND=127.0.0.1
    DASHBOARD="http://$(hostname -I | awk '{print $1}')/"
else
    echo "No Caddy in front: the dashboard stays on port 5000, without HTTPS." >&2
    BIND=0.0.0.0
    DASHBOARD="http://$(hostname -I | awk '{print $1}'):5000/"
fi

# --- Service --------------------------------------------------------

sed \
    -e "s|@USER@|$APP_USER|g" \
    -e "s|@GROUP@|$APP_GROUP|g" \
    -e "s|@APP_DIR@|$APP_DIR|g" \
    -e "s|@BIND@|$BIND|g" \
    "$TEMPLATE" > "$UNIT_FILE"

chmod 644 "$UNIT_FILE"

systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

# Restart, not reload: the Caddyfile turns Caddy's admin API off.
if [[ $BIND == 127.0.0.1 ]]; then
    systemctl enable caddy >/dev/null 2>&1
    systemctl restart caddy || echo "Warning: Caddy did not start: journalctl -u caddy -n 20" >&2
fi

sleep 2

if systemctl is-active --quiet "$SERVICE"; then
    echo "Chaos Router OS is running and starts at boot."
    echo "Dashboard: $DASHBOARD (HTTPS works too; browsers warn once per device)"
    echo "Logs:      journalctl -u $SERVICE -f"
else
    echo "The service did not start. Recent log:" >&2
    journalctl -u "$SERVICE" -n 20 --no-pager >&2
    exit 1
fi
