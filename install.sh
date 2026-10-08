#!/usr/bin/env bash
#
# Chaos Router Apps: installs the Apps Addon for Chaos Router OS.
#
#   sudo ./install.sh [--user NAME] [--yes]     install or update
#   sudo ./install.sh --remove [--delete-data]  remove the addon
#
# Installs Docker Engine and Docker Compose (Docker's own apt
# repository), the App Manager (/usr/local/bin/chaos-apps) and a
# sudoers rule that lets Chaos Router OS run exactly that command.
# Running it again updates the addon; installed apps keep running.
#
# --user is the account Chaos Router OS runs as (default: the owner of
# /var/lib/chaos-router-os, else the user who called sudo).

set -euo pipefail

ADDON_DIR=/opt/chaos-router-apps
STATE_DIR=/var/lib/chaos-router-apps
CLI_LINK=/usr/local/bin/chaos-apps
SUDOERS_FILE=/etc/sudoers.d/chaos-router-apps
DAEMON_JSON=/etc/docker/daemon.json
# Copy of the daemon.json we wrote: tells ours from someone else's
# (dockerd refuses unknown keys, so no marker inside the file).
DAEMON_COPY=/var/lib/chaos-router-apps/daemon.json
ROUTER_STATE=/var/lib/chaos-router-os

SOURCE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

APP_USER=""
REMOVE=0
DELETE_DATA=0


# -------------------------------------------------------------------
# Output
# -------------------------------------------------------------------

step() { printf '\n\033[1;34m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m  x %s\033[0m\n' "$*" >&2; exit 1; }


parse_args() {

    while [[ $# -gt 0 ]]; do
        case $1 in
            --user)        APP_USER=${2:-}; shift 2 ;;
            --remove)      REMOVE=1; shift ;;
            --delete-data) DELETE_DATA=1; shift ;;
            --yes|-y)      shift ;;
            *)             die "Unknown option: $1" ;;
        esac
    done
}


check_system() {

    step "Checking the system"

    [[ $EUID -eq 0 ]] || die "Run with sudo: sudo $0"

    # shellcheck disable=SC1091
    . /etc/os-release

    case ${ID:-} in
        debian|raspbian|ubuntu) info "System: ${PRETTY_NAME:-$ID}" ;;
        *) die "Docker's packages are only set up for Debian, Raspberry Pi OS and Ubuntu." ;;
    esac

    if [[ -z $APP_USER ]]; then
        if [[ -d $ROUTER_STATE ]]; then
            APP_USER=$(stat -c %U "$ROUTER_STATE")
        else
            APP_USER=${SUDO_USER:-}
        fi
    fi

    if [[ -z $APP_USER || $APP_USER == root ]] || ! id "$APP_USER" >/dev/null 2>&1; then
        die "Could not tell which user Chaos Router OS runs as. Use --user NAME."
    fi

    info "Chaos Router OS user: $APP_USER"
}


# -------------------------------------------------------------------
# Docker
# -------------------------------------------------------------------

install_docker() {

    step "Installing Docker"

    if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
        info "Already installed: $(docker --version)"
        return
    fi

    # shellcheck disable=SC1091
    . /etc/os-release

    # Docker's repository: raspbian for 32-bit Raspberry Pi OS, debian
    # for 64-bit (which says ID=debian), ubuntu for Ubuntu.
    local distro=$ID

    apt-get update -q
    apt-get install -y -q ca-certificates curl

    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/$distro/gpg" -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc

    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$distro ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list

    apt-get update -q
    apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin

    info "$(docker --version)"
}


configure_docker() {

    step "Configuring Docker for the router"

    if [[ -f $DAEMON_JSON ]] && ! cmp -s "$DAEMON_JSON" "$DAEMON_COPY"; then
        warn "$DAEMON_JSON exists and was not written by this installer; leaving it alone."
        warn "Recommended there: \"ip-forward-no-drop\": true and an address pool outside your LAN."
        return
    fi

    # ip-forward-no-drop (Docker 28+): Docker leaves the FORWARD policy
    # alone, so LAN devices keep their internet even with the firewall
    # off. Address pool: Docker's own networks, away from common LANs.
    local major extra=""
    major=$(dockerd --version 2>/dev/null | sed -E 's/^Docker version ([0-9]+).*/\1/')

    if [[ $major =~ ^[0-9]+$ ]] && (( major >= 28 )); then
        extra='  "ip-forward-no-drop": true,'
    else
        warn "Docker ${major:-?} is older than 28: it may set the FORWARD policy to DROP (keep the firewall's essential rules on)."
    fi

    mkdir -p "$(dirname "$DAEMON_JSON")" "$STATE_DIR"
    chmod 700 "$STATE_DIR"

    cat > "$DAEMON_JSON" <<EOF
{
$extra
  "default-address-pools": [ { "base": "172.31.0.0/16", "size": 24 } ],
  "log-driver": "local"
}
EOF

    # Drop the empty line left when $extra is empty.
    sed -i '/^$/d' "$DAEMON_JSON"
    cp "$DAEMON_JSON" "$DAEMON_COPY"

    systemctl enable docker >/dev/null 2>&1
    systemctl restart docker

    info "OK"
}


# -------------------------------------------------------------------
# Addon
# -------------------------------------------------------------------

install_addon() {

    step "Installing the App Manager"

    if [[ $SOURCE_DIR != "$ADDON_DIR" ]]; then
        # Owned by root: the router's user may run it with sudo, so it
        # must not be able to change it.
        rm -rf "$ADDON_DIR.new"
        mkdir -p "$ADDON_DIR.new"
        cp -r "$SOURCE_DIR/bin" "$SOURCE_DIR/catalog" "$SOURCE_DIR/install.sh" "$ADDON_DIR.new/"
        [[ -f $SOURCE_DIR/README.md ]] && cp "$SOURCE_DIR/README.md" "$ADDON_DIR.new/"
        chown -R root:root "$ADDON_DIR.new"
        chmod -R go-w "$ADDON_DIR.new"
        rm -rf "$ADDON_DIR"
        mv "$ADDON_DIR.new" "$ADDON_DIR"
    fi

    chmod 755 "$ADDON_DIR/bin/chaos-apps"
    ln -sfn "$ADDON_DIR/bin/chaos-apps" "$CLI_LINK"

    mkdir -p "$STATE_DIR"
    chmod 700 "$STATE_DIR"

    info "$("$CLI_LINK" version | tr -d '\n ' )"
}


setup_sudo() {

    step "Allowing Chaos Router OS to manage apps"

    local tmp
    tmp=$(mktemp)

    {
        echo "# Chaos Router Apps: Chaos Router OS runs the App Manager (sudo -n)."
        echo "$APP_USER ALL=(root) NOPASSWD: $CLI_LINK"
    } > "$tmp"

    if visudo -cf "$tmp" >/dev/null; then
        install -m 440 "$tmp" "$SUDOERS_FILE"
        info "Added $SUDOERS_FILE for $APP_USER."
    else
        rm -f "$tmp"
        die "Could not create a valid sudoers file."
    fi

    rm -f "$tmp"
}


finish() {

    step "Done"
    info "The Apps page of Chaos Router OS now shows the app catalog."
}


# -------------------------------------------------------------------
# Remove
# -------------------------------------------------------------------

remove_addon() {

    step "Removing the Apps Addon"

    [[ $EUID -eq 0 ]] || die "Run with sudo: sudo $0 --remove"

    local app

    if [[ -x $CLI_LINK ]] && docker info >/dev/null 2>&1; then

        for app in "$STATE_DIR"/apps/*/; do

            [[ -f $app/app.env ]] || continue

            app=$(basename "$app")
            info "Removing $app"

            if (( DELETE_DATA )); then
                "$CLI_LINK" remove "$app" --delete-data || warn "Could not remove $app."
            else
                "$CLI_LINK" remove "$app" || warn "Could not remove $app."
            fi

        done
    fi

    rm -f "$CLI_LINK" "$SUDOERS_FILE"
    rm -rf "$ADDON_DIR"

    # Docker's settings stay (removing them would change running containers).

    if (( DELETE_DATA )); then
        rm -rf "$STATE_DIR"
        info "App data deleted."
    else
        info "App data kept in $STATE_DIR."
    fi

    info "Docker stays installed (remove it with apt if you no longer need it)."
}


main() {

    parse_args "$@"

    if (( REMOVE )); then
        remove_addon
        return
    fi

    check_system
    install_docker
    configure_docker
    install_addon
    setup_sudo
    finish
}


# A partly downloaded script never runs anything.
main "$@"
