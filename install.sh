#!/usr/bin/env bash
#
# Chaos Router OS installer for Raspberry Pi OS Lite (64-bit).
#
#   curl -fsSL https://raw.githubusercontent.com/chaoscent/chaos-router-os/dev/core/install.sh | sudo bash
#
# or, from a clone:
#
#   sudo ./install.sh
#
# Installs the packages, the app with its Python environment, the
# default settings and the systemd service. On a router that is not set
# up yet, it finishes by showing the setup Wi-Fi's name, password and QR
# code. Safe to run again: an existing install is updated, settings stay.
#
# Options (also as environment variables):
#   --country XX   Wi-Fi country code, e.g. DE      (CHAOS_COUNTRY)
#   --dir PATH     where to clone the app            (CHAOS_DIR, default /opt/chaos-router-os)
#   --yes          no questions, use the defaults

set -euo pipefail

REPO=${CHAOS_REPO:-https://github.com/chaoscent/chaos-router-os}
BRANCH=${CHAOS_BRANCH:-dev/core}
INSTALL_DIR=${CHAOS_DIR:-/opt/chaos-router-os}
COUNTRY=${CHAOS_COUNTRY:-}
ASSUME_YES=0

STATE_DIR=/var/lib/chaos-router-os
SUDOERS_FILE=/etc/sudoers.d/chaos-router-os

# Packages this installer installed (not the ones that were already
# there): uninstall.sh removes exactly these.
PACKAGES_RECORD=/etc/chaos-router-os/installed-packages

PACKAGES=(
    git python3-venv python3-pip
    network-manager
    dnsmasq hostapd iw rfkill
    ufw iptables
    wireguard-tools openvpn easy-rsa openresolv
    qrencode
    caddy
    avahi-daemon avahi-utils
)

# Commands the app runs with `sudo -n` (see README, System Requirements).
SUDO_COMMANDS=(
    systemctl journalctl nmcli hostnamectl sysctl ip
    ufw iptables ip6tables iw rfkill wg openvpn easyrsa
    install mkdir cp rm cat test find
)


# -------------------------------------------------------------------
# Output
# -------------------------------------------------------------------

step() { printf '\n\033[1;34m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m  x %s\033[0m\n' "$*" >&2; exit 1; }

# Questions work even with `curl | sudo bash` (stdin is the script).
ask() {

    local prompt=$1 default=$2 answer=""

    if [[ $ASSUME_YES -eq 1 || ! -r /dev/tty ]]; then
        echo "$default"
        return
    fi

    read -r -p "    $prompt [$default]: " answer < /dev/tty || true

    echo "${answer:-$default}"
}


# -------------------------------------------------------------------
# Steps
# -------------------------------------------------------------------

parse_args() {

    while [[ $# -gt 0 ]]; do
        case $1 in
            --country) COUNTRY=${2:-}; shift 2 ;;
            --dir)     INSTALL_DIR=${2:-}; shift 2 ;;
            --yes|-y)  ASSUME_YES=1; shift ;;
            *)         die "Unknown option: $1" ;;
        esac
    done
}


check_system() {

    step "Checking the system"

    [[ $EUID -eq 0 ]] || die "Run with sudo."

    APP_USER=${SUDO_USER:-}

    if [[ -z $APP_USER || $APP_USER == "root" ]]; then
        die "Run with sudo from the user account the router should run as (not as root)."
    fi

    APP_GROUP=$(id -gn "$APP_USER")

    info "App user: $APP_USER"

    # shellcheck disable=SC1091
    . /etc/os-release

    if [[ ${ID:-} != "debian" && ${ID:-} != "raspbian" && ${ID_LIKE:-} != *debian* ]]; then
        warn "This is ${PRETTY_NAME:-an unknown system}. Chaos Router OS is made for Raspberry Pi OS Lite (64-bit)."
    else
        info "System: ${PRETTY_NAME:-Debian}"
    fi

    if [[ $(uname -m) != "aarch64" ]]; then
        warn "Not a 64-bit ARM system ($(uname -m)). Raspberry Pi OS Lite (64-bit) is recommended."
    fi

    if grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null; then
        info "Board: $(tr -d '\0' < /proc/device-tree/model)"
    else
        warn "This does not look like a Raspberry Pi. Only the Pi 5 is tested."
    fi
}


install_packages() {

    step "Installing packages (this can take a few minutes)"

    export DEBIAN_FRONTEND=noninteractive

    local pkg new=()

    for pkg in "${PACKAGES[@]}"; do
        dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed" || new+=("$pkg")
    done

    apt-get update -q
    apt-get install -y -q "${PACKAGES[@]}"

    # Add to the record (an update may install packages added later).
    mkdir -p "$(dirname "$PACKAGES_RECORD")"
    touch "$PACKAGES_RECORD"

    if (( ${#new[@]} )); then
        printf '%s\n' "${new[@]}" >> "$PACKAGES_RECORD"
        sort -u -o "$PACKAGES_RECORD" "$PACKAGES_RECORD"
        info "Newly installed: ${new[*]}"
    fi
}


get_code() {

    step "Getting Chaos Router OS"

    local here=""

    # Started as a file from a clone (not piped from curl): install that one.
    if [[ -n ${BASH_SOURCE[0]:-} && -f ${BASH_SOURCE[0]} ]]; then
        here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    fi

    if [[ -n $here && -f $here/backend/app.py ]]; then
        INSTALL_DIR=$here
        info "Using this copy: $INSTALL_DIR"
        return
    fi

    if [[ -d $INSTALL_DIR/.git ]]; then
        info "Updating $INSTALL_DIR"
        sudo -H -u "$APP_USER" git -C "$INSTALL_DIR" pull --ff-only
        return
    fi

    [[ -e $INSTALL_DIR ]] && die "$INSTALL_DIR exists but is not a Chaos Router OS clone."

    mkdir -p "$INSTALL_DIR"
    chown "$APP_USER:$APP_GROUP" "$INSTALL_DIR"

    sudo -H -u "$APP_USER" git clone --branch "$BRANCH" "$REPO" "$INSTALL_DIR"
}


setup_python() {

    step "Setting up the Python environment"

    info "Python $(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"

    if [[ ! -x $INSTALL_DIR/.venv/bin/python ]]; then
        sudo -H -u "$APP_USER" python3 -m venv "$INSTALL_DIR/.venv"
    fi

    sudo -H -u "$APP_USER" "$INSTALL_DIR/.venv/bin/pip" install -q --upgrade pip
    sudo -H -u "$APP_USER" "$INSTALL_DIR/.venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"
}


setup_defaults() {

    step "Writing the default settings (/etc/chaos-router-os)"

    mkdir -p "$STATE_DIR"
    chown "$APP_USER:$APP_GROUP" "$STATE_DIR"

    # Existing defaults are kept (local edits survive updates).
    "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/backend/install_defaults.py"

    # Everything below belongs to the app user. Repairs installs where an
    # older installer left root-owned files there (e.g. system/).
    chown -R "$APP_USER:$APP_GROUP" "$STATE_DIR"

    if [[ -d /tmp/chaos-router-os ]]; then
        chown -R "$APP_USER:$APP_GROUP" /tmp/chaos-router-os
    fi

    # No longer read since the setup page exists (no default login).
    rm -f /etc/chaos-router-os/users.json
}


setup_country() {

    step "Wi-Fi country"

    if [[ -z $COUNTRY ]]; then

        local current=""

        if command -v raspi-config >/dev/null; then
            current=$(raspi-config nonint get_wifi_country 2>/dev/null || true)
        fi

        info "Wi-Fi stays off until a country is set (it decides the allowed channels)."
        COUNTRY=$(ask "Two-letter country code" "${current:-DE}")
    fi

    COUNTRY=${COUNTRY^^}

    [[ $COUNTRY =~ ^[A-Z]{2}$ ]] || die "Invalid country code: $COUNTRY"

    # Sets the regulatory domain and unblocks Wi-Fi on Raspberry Pi OS.
    if command -v raspi-config >/dev/null; then
        raspi-config nonint do_wifi_country "$COUNTRY" || warn "raspi-config could not set the country."
    else
        iw reg set "$COUNTRY" || true
        rfkill unblock wlan || true
    fi

    # The default for the setup Wi-Fi and the WiFi page.
    "$INSTALL_DIR/.venv/bin/python" - "$COUNTRY" <<'PY'
import json, sys
path = "/etc/chaos-router-os/wifi.json"
with open(path) as f:
    data = json.load(f)
data["country"] = sys.argv[1]
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PY

    info "Country: $COUNTRY"
}


setup_sudo() {

    step "Checking permissions"

    if sudo -u "$APP_USER" sudo -n true 2>/dev/null; then
        info "$APP_USER has passwordless sudo."
        return
    fi

    # Only the commands the app needs.
    local paths=() cmd path

    for cmd in "${SUDO_COMMANDS[@]}"; do

        # type -P: the program's full path, never a shell built-in
        # (`command -v test` says "test", which sudoers rejects).
        path=$(PATH=$PATH:/usr/sbin:/sbin type -P "$cmd" || true)

        if [[ -n $path ]]; then
            paths+=("$path")
        fi

    done

    # The Apps page's one-click Apps Addon install, without arguments.
    paths+=("$INSTALL_DIR/deploy/install-apps.sh \"\"")

    local tmp joined
    tmp=$(mktemp)

    joined=$(printf '%s, ' "${paths[@]}")
    joined=${joined%, }

    {
        echo "# Chaos Router OS: system commands the app runs (sudo -n)."
        echo "$APP_USER ALL=(root) NOPASSWD: $joined"
    } > "$tmp"

    if visudo -cf "$tmp" >/dev/null; then
        install -m 440 "$tmp" "$SUDOERS_FILE"
        info "Added $SUDOERS_FILE for $APP_USER."
    else
        warn "Could not create a valid sudoers file; the app cannot change system settings."
    fi

    rm -f "$tmp"
}


check_ports() {

    step "Checking ports"

    # dnsmasq serves DNS (53) and DHCP (67); anything else there clashes.
    local other
    other=$(ss -H -lunp 2>/dev/null | grep -E ':(53|67) ' | grep -v dnsmasq || true)

    if [[ -n $other ]]; then
        warn "Another program uses port 53 or 67 (dnsmasq will clash with it):"
        echo "$other" | sed 's/^/      /' >&2
    fi

    # Caddy serves the dashboard on 80 and 443 (e.g. not Apache or nginx).
    local web
    web=$(ss -H -ltnp 2>/dev/null | grep -E ':(80|443) ' | grep -v caddy || true)

    if [[ -n $web ]]; then
        warn "Another program uses port 80 or 443 (Caddy needs them for the dashboard):"
        echo "$web" | sed 's/^/      /' >&2
    fi

    if [[ -z $other && -z $web ]]; then
        info "OK"
    fi
}


is_set_up() {

    [[ -s $STATE_DIR/users.json ]]
}


# Whether an SSH session reaches this Pi over its Wi-Fi. (sudo drops
# $SSH_CLIENT, so look at the open connections instead.)
ssh_over_wifi() {

    local address interface

    for address in $(
        ss -Htn state established '( sport = :22 )' 2>/dev/null \
            | awk '{print $3}' \
            | sed -E 's/:[0-9]+$//; s/^\[//; s/\]$//; s/^::ffff://'
    ); do

        interface=$(ip -o addr show | awk -v a="$address" '$4 ~ "^"a"/" {print $2; exit}')

        if [[ $interface == wl* ]]; then
            return 0
        fi

    done

    return 1
}


show_setup_wifi() {

    sudo -H -u "$APP_USER" \
        "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/backend/setup_wifi.py" || true
}


# Creates the setup Wi-Fi's name and password now, so they can be shown
# before the service starts (it uses the same ones).
prepare_setup_wifi() {

    (
        cd "$INSTALL_DIR/backend"
        sudo -H -u "$APP_USER" "$INSTALL_DIR/.venv/bin/python" -c \
            'from services.setup_network import get_credentials; get_credentials()' >/dev/null
    )
}


start_service() {

    step "Starting the service"

    SUDO_USER=$APP_USER "$INSTALL_DIR/deploy/install-service.sh"
}


has_wifi() {

    local dev

    for dev in /sys/class/net/*; do
        [[ -d $dev/wireless ]] && return 0
    done

    return 1
}


wait_for_setup_wifi() {

    local _

    for _ in $(seq 1 30); do
        systemctl is-active --quiet hostapd && return 0
        sleep 1
    done

    return 1
}


finish() {

    local address
    address=$(hostname -I | awk '{print $1}')

    if is_set_up; then

        step "Done"
        info "Chaos Router OS is updated and running."
        info "Dashboard: http://$address/"
        return
    fi

    # No Wi-Fi card (e.g. a VM): set up from a computer on the LAN.
    if ! has_wifi; then

        start_service

        step "Set up your router"
        info "This router has no Wi-Fi, so there is no setup Wi-Fi."
        info "Open the setup page from a computer on the LAN:"
        info "  http://chaos-router.local/setup  or  http://$address/setup"
        return
    fi

    prepare_setup_wifi

    if ssh_over_wifi; then

        # Starting the service turns wlan0 into the setup Wi-Fi, which
        # ends this SSH session: show everything first.
        step "Set up your router"
        warn "You are connected over Wi-Fi. This session ends when the setup Wi-Fi starts."
        show_setup_wifi
        info "Scan the QR code with your phone. Starting in 15 seconds..."
        sleep 15

        start_service
        return
    fi

    start_service

    step "Set up your router"

    # The QR code only when the setup Wi-Fi really runs.
    if ! wait_for_setup_wifi; then
        warn "The setup Wi-Fi did not start (journalctl -u chaos-router-os shows why)."
        info "Set up the router from a computer on the LAN instead:"
        info "  http://chaos-router.local/setup  or  http://$address/setup"
        return
    fi

    info "The setup Wi-Fi is on. Scan the QR code with your phone;"
    info "the setup page opens by itself."

    show_setup_wifi

    info "Show this again any time before setup with:"
    info "  $INSTALL_DIR/.venv/bin/python $INSTALL_DIR/backend/setup_wifi.py"
}


main() {

    parse_args "$@"

    check_system
    install_packages
    get_code
    setup_python
    setup_defaults
    setup_country
    setup_sudo
    check_ports
    finish
}


# Everything above only defines functions: a partly downloaded script
# (curl | sudo bash) never runs anything.
main "$@"
