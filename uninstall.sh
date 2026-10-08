#!/usr/bin/env bash
#
# Chaos Router OS uninstaller: removes Chaos Router OS and everything it
# set up on this system.
#
#   sudo /opt/chaos-router-os/uninstall.sh [--yes] [--dry-run] [--keep-packages]
#
#   --yes            don't ask for confirmation
#   --dry-run        only show what would be done
#   --keep-packages  keep the packages the installer installed
#   --all-packages   remove every package on the installer's list, even
#                    without a record (installs by an older installer).
#                    Also packages that were there before the install!
#
# In order:
#   1. Apps Addon: apps and their data, the App Manager, and Docker if
#      the addon installed it.
#   2. The services (chaos-router-os, chaos-router-mdns).
#   3. System changes (backend/uninstall.py): Wi-Fi, DHCP, DNS, VPNs,
#      firewall rules, NAT, forwarding, LAN bridge, config files.
#   4. Caddy: the previous Caddyfile comes back.
#   5. The packages the installer installed (it records them).
#   6. Every remaining file: /opt/chaos-router-os, /etc/chaos-router-os,
#      /var/lib/chaos-router-os, /tmp/chaos-router-os, the sudoers file.
#
# Stays on purpose: eth0's address settings (so the router stays
# reachable), the hostname, the Wi-Fi country and the system journal.
#
# After the confirmation it runs on as its own process (log in
# /tmp/chaos-router-os-uninstall.log): a dropped SSH connection doesn't
# stop it halfway.

set -uo pipefail

INSTALL_DIR_DEFAULT=/opt/chaos-router-os
APP_DIR=${CHAOS_UNINSTALL_APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}

SERVICE=chaos-router-os
MDNS_SERVICE=chaos-router-mdns
DEFAULTS_DIR=/etc/chaos-router-os
STATE_DIR=/var/lib/chaos-router-os
RUNTIME_DIR=/tmp/chaos-router-os
SUDOERS_FILE=/etc/sudoers.d/chaos-router-os
PACKAGES_RECORD=$DEFAULTS_DIR/installed-packages

CADDYFILE=/etc/caddy/Caddyfile
CADDY_BACKUP=/etc/caddy/Caddyfile.before-chaos
CADDY_MARKER="# Chaos Router OS: Caddy in front of the dashboard."

APPS_ADDON=/opt/chaos-router-apps/install.sh

# The installer's package list (keep in sync with PACKAGES in install.sh).
ALL_PACKAGES=(
    git python3-venv python3-pip
    network-manager
    dnsmasq hostapd iw rfkill
    ufw iptables
    wireguard-tools openvpn easy-rsa openresolv
    qrencode
    caddy
    avahi-daemon avahi-utils
)

LOG=/tmp/chaos-router-os-uninstall.log

YES=0
DRY_RUN=0
KEEP_PACKAGES=0
ALL_PACKAGES_FLAG=0


# -------------------------------------------------------------------
# Output
# -------------------------------------------------------------------

step() { printf '\n\033[1;34m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m  x %s\033[0m\n' "$*" >&2; exit 1; }


# Runs a command, or shows it in a dry run. Failures are reported, not
# fatal: an uninstall goes as far as it can.
run() {

    if (( DRY_RUN )); then
        info "would run: $*"
        return 0
    fi

    "$@" || { warn "Failed: $*"; return 1; }
}


parse_args() {

    while [[ $# -gt 0 ]]; do
        case $1 in
            --yes|-y)        YES=1 ;;
            --dry-run)       DRY_RUN=1 ;;
            --keep-packages) KEEP_PACKAGES=1 ;;
            --all-packages)  ALL_PACKAGES_FLAG=1 ;;
            *)               die "Unknown option: $1" ;;
        esac
        shift
    done
}


is_installed() {
    dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q "install ok installed"
}


# Packages to remove that are still installed: the recorded ones, or
# with --all-packages the installer's whole list.
recorded_packages() {

    local pkg

    if (( ALL_PACKAGES_FLAG )); then
        for pkg in "${ALL_PACKAGES[@]}"; do
            is_installed "$pkg" && echo "$pkg"
        done
        return 0
    fi

    [[ -f $PACKAGES_RECORD ]] || return 0

    while read -r pkg; do
        [[ -n $pkg ]] && is_installed "$pkg" && echo "$pkg"
    done < "$PACKAGES_RECORD"
}


# -------------------------------------------------------------------
# Before starting
# -------------------------------------------------------------------

confirm() {

    step "Uninstall Chaos Router OS"

    info "This removes Chaos Router OS and everything it set up:"
    info "  - the Apps Addon with all apps and their data (and Docker, if the addon installed it)"
    info "  - Wi-Fi access point, DHCP, DNS, VPN servers and profiles, firewall rules, NAT, LAN bridge"
    info "  - all settings, the admin account, keys and certificates"

    local packages
    packages=$(recorded_packages | tr '\n' ' ')

    if (( KEEP_PACKAGES )); then
        info "  - packages are kept (--keep-packages)"
    elif (( ALL_PACKAGES_FLAG )) && [[ -n $packages ]]; then
        info "  - ALL these packages, even if they were there before: $packages"
    elif [[ -n $packages ]]; then
        info "  - packages it installed: $packages"
    fi

    info ""
    info "Devices on the router's LAN and Wi-Fi lose their connection."
    info "eth0 keeps its address settings, so SSH over eth0 stays."

    if (( YES || DRY_RUN )); then
        return
    fi

    local answer=""

    # Works with curl | sudo bash too (the keyboard is on /dev/tty).
    if [[ -r /dev/tty ]]; then
        read -r -p "    Type \"uninstall\" to continue: " answer < /dev/tty
    fi

    [[ $answer == "uninstall" ]] || die "Cancelled. Nothing was changed."
}


# Runs the rest as its own process, so it survives a dropped SSH
# connection, and shows its output live.
detach() {

    (( DRY_RUN )) && return
    [[ -n ${CHAOS_UNINSTALL_DETACHED:-} ]] && return

    # A copy outside the install folder (which is deleted at the end).
    local copy
    copy=$(mktemp /tmp/chaos-router-os-uninstall.XXXXXX.sh)
    cp "${BASH_SOURCE[0]}" "$copy"
    chmod 700 "$copy"

    : > "$LOG"

    CHAOS_UNINSTALL_DETACHED=1 CHAOS_UNINSTALL_APP_DIR="$APP_DIR" \
        setsid "$copy" --yes "${@}" > "$LOG" 2>&1 < /dev/null &

    local pid=$!

    tail -n +1 --pid="$pid" -f "$LOG"

    rm -f "$copy"
    exit 0
}


# -------------------------------------------------------------------
# Steps
# -------------------------------------------------------------------

remove_apps_addon() {

    step "Apps Addon"

    if [[ ! -x $APPS_ADDON ]]; then
        info "Not installed."
        return
    fi

    run "$APPS_ADDON" --remove --purge
}


stop_services() {

    step "Stopping the services"

    run systemctl disable --now "$SERVICE" "$MDNS_SERVICE" 2>/dev/null
    run rm -f "/etc/systemd/system/$SERVICE.service" "/etc/systemd/system/$MDNS_SERVICE.service"
    run systemctl daemon-reload
}


undo_system_changes() {

    step "Undoing system changes"

    local python=$APP_DIR/.venv/bin/python

    if [[ ! -x $python || ! -f $APP_DIR/backend/uninstall.py ]]; then
        warn "No app in $APP_DIR: system changes cannot be undone automatically."
        return
    fi

    if (( DRY_RUN )); then
        "$python" "$APP_DIR/backend/uninstall.py" --dry-run 2>/dev/null
    else
        (cd "$APP_DIR/backend" && "$python" uninstall.py) 2>&1 | grep -v "RuntimeWarning"
    fi
}


restore_caddy() {

    step "Caddy"

    if ! grep -qxF "$CADDY_MARKER" "$CADDYFILE" 2>/dev/null; then
        info "Not configured by Chaos Router OS."
        return
    fi

    if [[ -f $CADDY_BACKUP ]]; then
        run mv "$CADDY_BACKUP" "$CADDYFILE"
        run systemctl try-restart caddy
        info "The previous Caddyfile is back."
    else
        run systemctl disable --now caddy 2>/dev/null
        run rm -f "$CADDYFILE"
        info "Caddy stopped; its config was only for Chaos Router OS."
    fi
}


remove_packages() {

    step "Packages"

    if (( KEEP_PACKAGES )); then
        info "Kept (--keep-packages)."
        return
    fi

    if [[ ! -f $PACKAGES_RECORD ]] && (( ! ALL_PACKAGES_FLAG )); then
        info "No record of installed packages (installed by an older installer), so none are removed."
        info "Run again with --all-packages to remove the installer's whole package list."
        return
    fi

    local packages=() network_manager=0 pkg

    # apt must never ask questions here.
    export DEBIAN_FRONTEND=noninteractive

    while read -r pkg; do
        if [[ $pkg == network-manager ]]; then
            network_manager=1
        else
            packages+=("$pkg")
        fi
    done < <(recorded_packages)

    if (( ${#packages[@]} )); then
        info "Removing: ${packages[*]}"
        run apt-get purge -y -q "${packages[@]}"
    fi

    # Caddy's own data: its local CA and certificates.
    if [[ " ${packages[*]} " == *" caddy "* ]]; then
        run rm -rf /var/lib/caddy /etc/caddy
    fi

    # Last: the system ran without NetworkManager before the install.
    if (( network_manager )); then
        info "Removing network-manager (the system used its own network setup before)."
        run apt-get purge -y -q network-manager
    fi

    run apt-get autoremove --purge -y -q
}


remove_files() {

    step "Removing files"

    local app_user=""
    [[ -d $STATE_DIR ]] && app_user=$(stat -c %U "$STATE_DIR")

    run rm -f "$SUDOERS_FILE"
    run rm -rf "$DEFAULTS_DIR" "$STATE_DIR" "$RUNTIME_DIR" /etc/chaos-router

    # Settings of very old versions.
    if [[ -n $app_user && $app_user != root ]]; then
        local home
        home=$(getent passwd "$app_user" | cut -d: -f6)
        [[ -n $home ]] && run rm -rf "$home/.config/chaos-router"
    fi

    # The installer's own copy. A copy installed from elsewhere (your
    # own git clone) is left alone: it may hold your work.
    if [[ $APP_DIR == "$INSTALL_DIR_DEFAULT" ]]; then
        run rm -rf "$APP_DIR"
    else
        info "Kept $APP_DIR (not the installer's copy); delete it yourself if you no longer need it."
    fi
}


finish() {

    step "Done"

    if (( DRY_RUN )); then
        info "Dry run: nothing was changed."
        return
    fi

    info "Chaos Router OS is removed."
    info "Kept on purpose: eth0's address settings, the hostname, the Wi-Fi country, the system journal."
    info "Reboot to clear anything still held in memory: sudo reboot"
    info "This log: $LOG (gone after the reboot)"
}


main() {

    parse_args "$@"

    if [[ $EUID -ne 0 ]] && (( ! DRY_RUN )); then
        die "Run with sudo: sudo $0"
    fi

    if [[ -z ${CHAOS_UNINSTALL_DETACHED:-} ]]; then
        confirm
        detach "$@"
    fi

    remove_apps_addon
    stop_services
    undo_system_changes
    restore_caddy
    remove_packages
    remove_files
    finish
}


# A partly downloaded script never runs anything.
main "$@"
