#!/usr/bin/env bash
#
# Switches a Quectel modem's USB data mode between QMI and MBIM.
#
#   sudo deploy/modem-usb-mode.sh status   prints qmi, mbim, other or none
#   sudo deploy/modem-usb-mode.sh qmi      switches to QMI (Linux: qmi_wwan)
#   sudo deploy/modem-usb-mode.sh mbim     switches to MBIM (cdc_mbim)
#   sudo deploy/modem-usb-mode.sh auto     QMI, but only from MBIM
#
# Why: with some Quectel 5G modules (e.g. RM520N-GL) in MBIM mode, the
# cdc_mbim driver drops every received packet as an RX error: the
# connection "works" but no data comes back. QMI is the mode Quectel
# recommends for Linux; ModemManager and NetworkManager support both.
#
# The setting is stored in the modem. Switching restarts the modem
# (about a minute, mobile data drops meanwhile). Only Quectel modems
# (USB vendor 2c7c) are touched: AT+QCFG="usbnet" is Quectel's command.

set -uo pipefail

MODE=${1:-}

QUECTEL=2c7c

die() { echo "$*" >&2; exit 1; }


# The wwan interface's driver: cdc_mbim, qmi_wwan, ... or nothing.
wwan_driver() {

    local dev
    for dev in /sys/class/net/wwan*; do
        [[ -e $dev/device/driver ]] || continue
        basename "$(readlink -f "$dev/device/driver")"
        return
    done
}


current_mode() {

    case $(wwan_driver) in
        qmi_wwan) echo qmi ;;
        cdc_mbim) echo mbim ;;
        "")       echo none ;;
        *)        echo other ;;
    esac
}


has_quectel() {

    grep -qxi "$QUECTEL" /sys/bus/usb/devices/*/idVendor 2>/dev/null
}


# A port that answers AT commands: from ModemManager, else the usual
# one of Quectel modules (the third serial port).
at_port() {

    local port
    port=$(mmcli -m any 2>/dev/null | grep -o 'ttyUSB[0-9]* (at)' | head -1 | cut -d' ' -f1)

    if [[ -n $port && -e /dev/$port ]]; then
        echo "/dev/$port"
    elif [[ -e /dev/ttyUSB2 ]]; then
        echo /dev/ttyUSB2
    fi
}


# Sends one AT command, prints the answer, succeeds on OK.
at() {

    local port=$1 command=$2 line answer=""

    exec 3<>"$port" || return 1

    printf '%s\r' "$command" >&3

    while IFS= read -r -t 3 line <&3; do
        line=${line%$'\r'}
        [[ -n $line ]] && answer+="$line"$'\n'
        [[ $line == OK || $line == ERROR || $line == *"CME ERROR"* ]] && break
    done

    exec 3>&-

    printf '%s' "$answer"
    [[ $answer == *$'OK\n'* ]]
}


switch_to() {

    local target=$1 value port

    case $target in
        qmi)  value=0 ;;
        mbim) value=2 ;;
    esac

    has_quectel || die "No Quectel modem found; only Quectel modems can be switched."

    if [[ $(current_mode) == "$target" ]]; then
        echo "The modem already uses $target."
        return 0
    fi

    port=$(at_port)
    [[ -n $port ]] || die "No AT port found (ttyUSB)."

    echo "Switching the modem to $target (it restarts; about a minute)..."

    # ModemManager holds the AT ports.
    systemctl stop ModemManager 2>/dev/null || true
    sleep 2

    stty -F "$port" 115200 raw -echo 2>/dev/null || true

    if ! at "$port" "AT+QCFG=\"usbnet\",$value" >/dev/null; then
        systemctl start ModemManager 2>/dev/null || true
        die "The modem did not accept the new mode."
    fi

    # Restarts the modem; it comes back with the new USB interfaces.
    at "$port" "AT+CFUN=1,1" >/dev/null || true

    local _
    for _ in $(seq 1 60); do
        sleep 2
        [[ $(current_mode) == "$target" ]] && break
    done

    systemctl start ModemManager 2>/dev/null || true

    for _ in $(seq 1 30); do
        mmcli -L 2>/dev/null | grep -q "/Modem/" && break
        sleep 2
    done

    if [[ $(current_mode) == "$target" ]]; then
        echo "The modem uses $target now."
    else
        die "The modem did not come back in $target mode (now: $(current_mode))."
    fi
}


[[ $EUID -eq 0 ]] || die "Run with sudo."

case $MODE in
    status)   current_mode ;;
    qmi|mbim) switch_to "$MODE" ;;
    auto)
        if has_quectel && [[ $(current_mode) == mbim ]]; then
            switch_to qmi
        else
            echo "Nothing to switch (mode: $(current_mode))."
        fi
        ;;
    *) die "Usage: $0 status|qmi|mbim|auto" ;;
esac
