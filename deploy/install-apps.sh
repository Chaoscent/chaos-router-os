#!/usr/bin/env bash
#
# Installs the Apps Addon (Chaos Router Apps): Docker, Docker Compose
# and the App Manager. The Apps page runs this ("Install Apps Addon");
# it also works by hand:
#
#   sudo deploy/install-apps.sh
#
# Downloads the addon (branch CHAOS_APPS_BRANCH of CHAOS_APPS_REPO) and
# runs its install.sh for the user Chardsoft Router OS runs as. The sudoers rule
# from the installer allows this script without arguments only, and
# sudo drops the environment: the dashboard cannot pick another source.

set -euo pipefail

REPO=${CHAOS_APPS_REPO:-https://github.com/chaoscent/chaos-router-os.git}

# release/apps from the v1 release on (empty until then).
BRANCH=${CHAOS_APPS_BRANCH:-dev/apps}

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
    echo "Could not tell which user Chardsoft Router OS runs as." >&2
    exit 1
fi

if ! command -v git >/dev/null; then
    apt-get install -y -q git
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "==> Downloading the Apps Addon ($BRANCH)"
git clone --depth 1 --quiet --branch "$BRANCH" "$REPO" "$tmp/addon"

# Only ever run the addon's installer, never something else on that branch.
if [[ ! -x $tmp/addon/bin/chaos-apps || ! -d $tmp/addon/catalog || ! -f $tmp/addon/install.sh ]]; then
    echo "The branch $BRANCH does not contain the Apps Addon." >&2
    exit 1
fi

"$tmp/addon/install.sh" --user "$APP_USER" --yes
