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

set -euo pipefail

SERVICE=chaos-router-os
UNIT_FILE=/etc/systemd/system/$SERVICE.service
STATE_DIR=/var/lib/chaos-router-os

APP_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
TEMPLATE=$APP_DIR/deploy/$SERVICE.service

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo: sudo $0 $*" >&2
    exit 1
fi

# --- Remove ---------------------------------------------------------

if [[ ${1:-} == "--remove" ]]; then

    systemctl disable --now "$SERVICE" 2>/dev/null || true
    rm -f "$UNIT_FILE"
    systemctl daemon-reload

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

# Persistent settings belong to the app user.
mkdir -p "$STATE_DIR"
chown "$APP_USER:$APP_GROUP" "$STATE_DIR"

sed \
    -e "s|@USER@|$APP_USER|g" \
    -e "s|@GROUP@|$APP_GROUP|g" \
    -e "s|@APP_DIR@|$APP_DIR|g" \
    "$TEMPLATE" > "$UNIT_FILE"

chmod 644 "$UNIT_FILE"

systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

sleep 2

if systemctl is-active --quiet "$SERVICE"; then
    echo "Chaos Router OS is running and starts at boot."
    echo "Dashboard: http://$(hostname -I | awk '{print $1}'):5000"
    echo "Logs:      journalctl -u $SERVICE -f"
else
    echo "The service did not start. Recent log:" >&2
    journalctl -u "$SERVICE" -n 20 --no-pager >&2
    exit 1
fi
