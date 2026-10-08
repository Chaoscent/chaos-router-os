#!/usr/bin/env bash
#
# Installs the Apps Addon (Chaos Router Apps): Docker, Docker Compose
# and the App Manager. The Apps page runs this ("Install Apps Addon");
# it also works by hand:
#
#   sudo deploy/install-apps.sh
#
# Downloads the addon from CHAOS_APPS_REPO (git) and runs its
# install.sh for the user Chaos Router OS runs as. The sudoers rule
# from the installer allows this script without arguments only, and
# sudo drops the environment: the dashboard cannot pick another source.

set -euo pipefail

REPO=${CHAOS_APPS_REPO:-https://github.com/chaoscent/chaos-router-apps.git}

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo: sudo $0" >&2
    exit 1
fi

APP_USER=${SUDO_USER:-}

if [[ -z $APP_USER || $APP_USER == root ]]; then
    # By hand as root: the owner of the router's settings.
    APP_USER=$(stat -c %U /var/lib/chaos-router-os 2>/dev/null || true)
fi

if [[ -z $APP_USER || $APP_USER == root ]]; then
    echo "Could not tell which user Chaos Router OS runs as." >&2
    exit 1
fi

if ! command -v git >/dev/null; then
    apt-get install -y -q git
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "==> Downloading the Apps Addon"
git clone --depth 1 --quiet "$REPO" "$tmp/addon"

"$tmp/addon/install.sh" --user "$APP_USER" --yes
