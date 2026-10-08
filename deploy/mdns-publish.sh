#!/usr/bin/env bash
#
# Announces the router's .local names over mDNS (chaos-router.local and
# the names of installed apps), for devices that look up .local names
# only that way (Apple devices, Linux with nss-mdns). The router's DNS
# answers the same names for everyone else.
#
# Run by chaos-router-mdns.service. Reads a file Chaos Router OS writes,
# one "name address" per line, and keeps an avahi-publish running for
# each. Chaos Router OS restarts the service when the file changes.

set -u

NAMES_FILE=${1:?usage: mdns-publish.sh <names file>}

pids=()

# Stop every avahi-publish together with this script.
trap 'kill "${pids[@]}" 2>/dev/null' EXIT

if [[ -s $NAMES_FILE ]]; then

    while read -r name address; do

        [[ -n ${name:-} && -n ${address:-} && $name != \#* ]] || continue

        # --no-reverse: the address already has its own name (the
        # router's hostname); a second reverse entry would collide.
        avahi-publish --address --no-reverse "$name" "$address" &
        pids+=("$!")

    done < "$NAMES_FILE"

fi

if (( ${#pids[@]} == 0 )); then
    # Nothing to announce yet: wait for the next restart.
    exec sleep infinity
fi

# One stopped (e.g. avahi-daemon restarted, or a name collision on the
# network): exit, and systemd starts all of them again.
wait -n
exit 1
