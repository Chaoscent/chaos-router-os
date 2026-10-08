# Chaos Router OS — Architecture

> [!abstract] Purpose
> The architecture of Chaos Router OS: what it is made of, where things live, and the rules the code follows.
>
> When development moves to another chat or another person, start with this document, then README.md (usage) and PLAN.md (what is done and what is next).
>
> Details evolve; the decisions marked as **invariants** at the end should not change casually. Where something is planned but not built yet, this document says so.

---

# Project Overview

**Project:** Chaos Router OS

**Target:** Raspberry Pi 5 with Raspberry Pi OS Lite (64-bit), a cellular modem (tested: Quectel RM520N-GL) and optional extra Wi-Fi adapters.

Chaos Router OS is not an operating system of its own: it installs **on top of Raspberry Pi OS** and turns the Pi into a router managed from a web dashboard.

- Mobile data through the modem (or Ethernet as the WAN)
- Ethernet LAN, LAN bridge
- Wi-Fi access points, one network per radio
- DHCP and DNS
- Firewall, routing and NAT
- VPN: WireGuard and OpenVPN servers, WireGuard and OpenVPN client profiles
- Web dashboard over HTTPS, with a setup wizard
- Safe Apply: changes are verified and reverted when they cut you off
- Backup, restore, factory reset, uninstaller
- Optional apps in Docker (Apps Addon)

One command turns a fresh Raspberry Pi OS into a router:

```bash
curl -fsSL https://chaos-software.dev/router-os/core | sudo bash
```

---

# Layers

```text
┌─────────────────────────────────────────────┐
│ Browser: dashboard (HTML, CSS, JavaScript)  │
├─────────────────────────────────────────────┤
│ Caddy: HTTPS, app names                     │
├─────────────────────────────────────────────┤
│ Chaos Router OS app (Flask, gunicorn)       │
├─────────────────────────────────────────────┤
│ Settings: defaults, persistent, running     │
├─────────────────────────────────────────────┤
│ System services: NetworkManager, hostapd,   │
│ dnsmasq, ufw, WireGuard, OpenVPN,           │
│ ModemManager, Avahi                         │
├─────────────────────────────────────────────┤
│ Raspberry Pi OS (Debian)                    │
├─────────────────────────────────────────────┤
│ Raspberry Pi 5, modem, Wi-Fi adapters       │
└─────────────────────────────────────────────┘
```

The app never re-implements a network service. It writes the services' own configuration (hostapd, dnsmasq, NetworkManager connections, ufw rules, WireGuard and OpenVPN configs), starts them through systemd and checks that they stay up.

Optional apps are a separate layer that Core never depends on:

```text
Chaos Router OS Core
        │ optional
        ▼
   Apps Addon ── Docker ──┬── App
                          ├── App
                          └── App
```

---

# Filesystem Layout

| Location | Purpose | Written by |
|---|---|---|
| `/opt/chaos-router-os/` | The app: a git clone with its Python environment (`.venv`) | Installer (git) |
| `/etc/chaos-router-os/` | Default settings (JSON) and the record of installed packages | Installer only, never the app |
| `/var/lib/chaos-router-os/` | Persistent settings: the last applied and verified state | App |
| `/tmp/chaos-router-os/` | Running settings, pending changes; gone after a reboot | App |

## App: `/opt/chaos-router-os/`

The installer clones the repository here (or uses the clone it is run from) and keeps it updated with git. It holds code only:

```text
backend/       Flask app, services/ (one module per area), installer helpers
frontend/      templates/ (pages), static/ (CSS, JavaScript, vendor files)
deploy/        systemd units, Caddyfile, service installer
install.sh     Core installer
uninstall.sh   Uninstaller
VERSION        e.g. 0.1.0-alpha
```

Code is **not** in `/etc`: by the Filesystem Hierarchy Standard, `/etc` is configuration only, and code there would mix with settings that must survive updates. `/opt` is where software installed outside the package manager belongs. Packaged as a `.deb` some day, it would move to `/usr/lib/chaos-router-os`. The installer option `--dir PATH` chooses another folder.

The sidebar shows the version and, in a git clone, the commit: `v0.1.0-alpha (8464d20)`.

## Defaults: `/etc/chaos-router-os/`

Written by `backend/install_defaults.py` during install, never by the app. Existing files are kept on updates, so local edits survive. Examples: the firewall (on, nothing comes in from the internet, the LAN keeps working), NAT, the Wi-Fi country chosen during install. `installed-packages` lists the packages the installer added, so the uninstaller removes exactly those.

## Persistent: `/var/lib/chaos-router-os/`

One JSON file per settings area (`wifi.json`, `dhcp.json`, `network.json`, ...), plus `users.json` (the admin account) and `system/` (records of what is actually on the system: firewall rules, the OpenVPN CA backup, the event log, the session key). Secrets are mode 600.

This is the **last known-good** configuration. It survives reboots and updates, and the router boots with it. Deleting an area's file restores that area's defaults.

## Running: `/tmp/chaos-router-os/`

The configuration the system runs right now, one JSON file per area, plus `pending.json` (changes waiting for confirmation) and small records (e.g. which addresses the access points set). Rebuilt from `/var/lib` at every boot.

## Service configs

The system services keep reading their own files; the app generates them from the JSON settings:

| Service | File(s) |
|---|---|
| hostapd (one per radio) | `/etc/hostapd/chaos-<radio>.conf`, unit `chaos-hostapd@<radio>` |
| dnsmasq | `/etc/dnsmasq.d/chaos-router-*.conf` |
| NetworkManager | connections `chaos-lan` (bridge), `chaos-lan-<port>`, `chaos-modem` |
| WireGuard / OpenVPN | `/etc/wireguard/`, `/etc/openvpn/` |
| Caddy | `/etc/caddy/Caddyfile`, `/etc/caddy/chaos-apps/*.caddy` |
| Firewall | ufw rules, recorded in `system/firewall_rules.json` |

---

# Safe Apply: How Settings Change

Every settings area (network, firewall, routing, Wi-Fi, DHCP, DNS, mobile data, VPN servers and profiles, blocked devices) is registered in `backend/services/areas.py` with an apply, a verify and a baseline function, and changes only through `backend/services/transaction.py`.

```text
Page sends a change
        ↓
Backend validation (never trusts the page's own checks)
        ↓
Running config  (/tmp)
        ↓
Apply to the system (write configs, restart services)
        ↓
Verify (services still up after a moment, addresses set)
        ↓
   ┌────┴─────────────────────────────┐
   │ failed                           │ verified
   ▼                                  ▼
Persistent config is restored    Can it cut the user off?
and applied again                (network, firewall, Wi-Fi,
                                  DHCP, DNS, VPN servers,
                                  blocking a device)
                                   │ no            │ yes
                                   ▼               ▼
                              Persistent      Pending: banner on every
                              (/var/lib)      page, "Keep" or "Revert"
                                                   │
                                   ┌───────────────┴──────────────┐
                                   ▼                              ▼
                             Keep: persistent        No answer in 120 s, Revert,
                                                     or a reboot: back to the
                                                     persistent config
```

- **Dependents:** an area that others read (e.g. the network: which interface is the WAN, which ports are bridged) re-applies them after a change.
- **Several areas can be pending at once** and are kept or reverted together. Turning on a Wi-Fi network also makes DHCP serve that radio; both wait for one confirmation.
- **Before the first change** to an area, what the system runs is recorded as its persistent config (the baseline), so there is always something to go back to.
- **Validation happens twice:** the page checks input for immediate feedback; the backend validates everything again and is the only authority.

## Brick Recovery

A bad network change must never permanently lock the user out:

```text
Change cuts off the dashboard
        ↓
Nobody confirms → reverted after 120 seconds
        or
Power cycle
        ↓
Boot: the kernel's boot ID differs from the last start
        ↓
Running config is deleted and rebuilt from /var/lib
        ↓
Every configured area is applied in order
        ↓
Router reachable on the last known-good config
```

An app restart (not a reboot) keeps running changes but reverts unconfirmed ones (`recover_pending`). Temporary configuration never becomes authoritative by existing.

## Settings Format Changes

There are no schema version numbers yet. When a format changes, the module reads the old format and converts it on the fly. For example, `wifi.json` and `dhcp.json` used to describe a single network or scope and are read as the settings of that one interface. The converted form is saved with the next change. Backups are validated with the same functions.

---

# Network

## Interfaces

| Interface | Role |
|---|---|
| `wwan0` | The modem's data interface; WAN by default. Managed by ModemManager and NetworkManager, read-only on the Network page. |
| `eth0` | LAN by default; can be switched to WAN (Ethernet uplink instead of the modem). DHCP client or static. |
| `wlan0`, `wlan1`, ... | Wi-Fi radios: built-in and USB adapters. Each can run an access point. |
| `br0` | Optional LAN bridge. |

## Wi-Fi

- **One access point per radio**, each its own systemd unit `chaos-hostapd@<radio>` with its own name, band, channel and subnet (10.42.0.1/24, 10.43.0.1/24, ...).
- **Saving one radio leaves the others running:** an access point only restarts when its config changed.
- **One band per radio:** a radio sends on one channel at a time, so 2.4 and 5 GHz at once need two radios.
- **Bands and channels:** the page offers only what `iw` reports for the radio (e.g. no 6 GHz on the Pi's built-in Wi-Fi).
- **Country:** one for all radios, set during install (no default) and changeable on the Wi-Fi page.
- **DHCP follows:** turning on an access point makes DHCP serve its radio in its subnet.

## DHCP and DNS (dnsmasq)

- **DHCP:** one scope per interface, each with its own range, gateway, DNS and lease time. The local domain and the static leases are shared. Bridge ports are served through `br0`. A scope on eth0 pauses while eth0 is the WAN.
- **DNS:** answered only on the LAN interfaces, never the WAN.
- **Local names:** `chaos-router.local` and `<app>.chaos-router.local` for every device on the LAN.
- **The router's own name lookups** do not go through dnsmasq: the installer keeps the system's resolver, so switching DNS off on the dashboard never breaks the router's own lookups.

## LAN Bridge

Off by default. When on, the chosen ports (Ethernet and Wi-Fi, all by default) share one network on `br0`; the others keep their own. Wired ports are NetworkManager bridge ports; access points join with hostapd's `bridge=`.

## Modem and Mobile Data

- **ModemManager (`mmcli`)** reads the modem: carrier, network type, signal, SIM state.
- **Mobile data** is the NetworkManager connection `chaos-modem`: APN (automatic from the carrier database `mobile-broadband-provider-info`, falling back to the APN the network gave the modem, or entered by hand), roaming, optional username and password. It reconnects by itself.
- **SIM PIN:** sent once per click, never retried automatically, so it can't run the SIM into the PUK lock. It is saved for unlocking at startup only after it has worked.
- **USB data mode:** Quectel modems (e.g. RM520N-GL) in MBIM mode lose every received packet on Linux (`cdc_mbim` counts them as RX errors): the connection is up, but nothing comes back. The installer switches them to QMI (`deploy/modem-usb-mode.sh`, `AT+QCFG="usbnet",0`). The Modem page shows the data mode and the addresses, and offers the switch when received data is being dropped.
- **APN order when the field is empty:** NetworkManager's carrier database (can be outdated), then the APN the network gave the modem (never `IMS`, which is for calls), then the empty APN (the network's default for the SIM). NetworkManager retries a failing connection a few times, then pauses.
- **IPv6-only plans:** the Modem page shows "Connected (IPv6 only)". IPv4 through such a plan needs 464XLAT (CLAT), which is not built yet.

## Firewall, Routing, NAT

- **ufw** with default policies: incoming and routed traffic denied, outgoing allowed.
- **Essential rules:** SSH, the dashboard, DHCP and DNS are allowed on the LAN interfaces only.
- **Routing:** IP forwarding and masquerading to the WAN.
- **On by default:** shipped in `/etc/chaos-router-os` and applied from the first boot.

---

# Web Access

```text
Browser
   ↓
http(s)://chaos-router.local
   ↓
Caddy (ports 80, 443)
   ↓
Chaos Router OS app (127.0.0.1:5000, gunicorn)
```

- **HTTPS** uses Caddy's own local certificate authority (`tls internal`). A certificate is issued on the first visit, but only for the router's own LAN addresses and names: Caddy asks the app first (`/caddy/tls-allowed`).
- **Certificate warning:** browsers warn once per device because they don't know the local CA. The System page offers the CA certificate (`/router-ca.crt`) to install. A warning-free certificate would need the user's own domain and a public CA. That is not built; it would be an opt-in feature.
- **HTTP → HTTPS:** after setup, the app redirects HTTP to HTTPS. Before setup it stays plain HTTP, because the setup Wi-Fi's captive portal and phones' connectivity checks need it.
- **`.local` names:**
  - LAN devices get them from the router's DNS (dnsmasq).
  - Devices that use another DNS server get them over mDNS: the service `chaos-router-mdns` announces them with Avahi.

---

# Setup and First Start

```text
Fresh Raspberry Pi OS Lite
        ↓
curl installer
        ↓
App starts, no admin account → setup mode
        ↓
Setup Wi-Fi "ChaosRouter-Setup-XXXX" (WPA2, 2.4 GHz, 10.42.0.1/24)
on the first radio that can do 2.4 GHz (preferably the built-in wlan0),
with a captive portal; the installer shows its name, password and QR code
        ↓
Phone joins → setup page opens by itself
        ↓
Admin account, optionally the first Wi-Fi network
        ↓
Setup Wi-Fi replaced by the real one (or turned off)
        ↓
Dashboard: https://chaos-router.local
```

There is no default login: without an account the router is in setup mode, and the setup page only works until an account exists.

---

# Installer

## Commands

```bash
curl -fsSL https://chaos-software.dev/router-os/core | sudo bash
```

The URL is a redirect on chaos-software.dev to the installer in the repository (today: branch `dev/core`).

## Philosophy

The installer is a **bootstrapper**, not the app. It gets the code with git and never lists app files, so new files in the repository arrive without changing the installer.

## Steps

1. **Check the system:**
   - It must run with sudo, from the user account the app should run as.
   - It checks for Raspberry Pi OS, 64-bit and a Raspberry Pi; anything else is warned about, not refused.
2. **Packages:**
   - It installs these and records which ones were new:
     - git, python3-venv, NetworkManager
     - dnsmasq, hostapd, iw, rfkill
     - ModemManager, mobile-broadband-provider-info
     - ufw, iptables
     - wireguard-tools, openvpn, easy-rsa, openresolv
     - qrencode, Caddy, Avahi
   - A modem plugged in before ModemManager came is looked for again, so no reboot is needed.
3. **Name resolution:** dnsmasq must not become the router's own resolver; the installer checks that name lookups still work.
4. **Code:**
   - It clones or updates the repository in `/opt/chaos-router-os`, owned by the app user.
   - It creates the Python environment.
5. **Defaults:** it writes `/etc/chaos-router-os` and leaves existing files alone.
6. **Wi-Fi country:**
   - It lists every country with its code; the user types theirs, with no default.
   - `--country XX` skips the question.
7. **sudoers:**
   - The app runs as a normal user and uses `sudo -n` for a fixed list of commands only (systemctl, nmcli, mmcli, ip, ufw, ...).
   - Paths are resolved with `type -P`.
8. **Ports:** it warns when something else uses 53, 67, 80 or 443.
9. **Modem mode:** a Quectel modem in MBIM mode is switched to QMI (`CHAOS_MODEM_MODE=keep` skips it).
10. **Services:**
   - `deploy/install-service.sh` installs `chaos-router-os` (the app), `chaos-router-mdns` and the `chaos-hostapd@` template.
   - It installs the Caddyfile and keeps the previous one as `Caddyfile.before-chaos`.
11. **Finish:** on a router that is not set up yet, it shows the setup Wi-Fi with its QR code.

## Running It Again

Safe to run any number of times: it updates the code, repairs the infrastructure and restarts the services, and **keeps all settings**. This is also how updates work today.

## Uninstaller

```bash
sudo /opt/chaos-router-os/uninstall.sh
```

**What it removes:**
- The Apps Addon with all apps (and Docker, if the addon installed it).
- Every system change Chaos Router OS made: Wi-Fi, DHCP, DNS, VPNs, mobile data, firewall rules, NAT, the LAN bridge, Caddy routes and the `.local` names.
- The packages the installer installed, and all of its files.

**What it keeps:** eth0's settings (so SSH stays), the hostname, the Wi-Fi country and the system journal.

**How it runs:** it continues as its own process, so a dropped SSH connection doesn't stop it halfway. `--dry-run` shows what it would do.

---

# Services

```text
systemd
   ├── chaos-router-os          The app (gunicorn on 127.0.0.1:5000, as the app user)
   ├── chaos-router-mdns        .local names over mDNS
   ├── chaos-hostapd@<radio>    One access point per radio
   ├── caddy                    HTTPS, ports 80 and 443
   ├── dnsmasq                  DHCP and DNS for the LAN
   ├── NetworkManager           Interfaces, bridge, mobile data
   ├── ModemManager             The modem
   ├── ufw                      Firewall
   ├── wg-quick@, openvpn@      VPN servers and client profiles
   └── docker                   Only with the Apps Addon
```

## Boot

```text
Raspberry Pi boot
        ↓
NetworkManager, ModemManager, dnsmasq, Caddy, ...
        ↓
chaos-router-os starts
        ↓
New boot ID → running config rebuilt from /var/lib
        ↓
Areas applied in order: network, mobile data, firewall, routing,
blocked devices, DHCP, DNS, Wi-Fi, VPN
        ↓
Not set up yet → setup Wi-Fi with captive portal
        ↓
App names (DNS, mDNS, Caddy routes) synced
```

---

# Editions and Branches

Chaos Router OS has two editions:

- **Core:** the main edition for any Raspberry Pi 5 with a cellular modem. Networking first.
- **Hardware Edition:** Core plus support for physical switches and OLED displays, made for the author's own Pi 5 router design, **Chaos Router**. Not installable from Core.

```bash
curl -fsSL https://chaos-software.dev/router-os/core | sudo bash
curl -fsSL https://chaos-software.dev/router-os/hardware-edition | sudo bash
```

The Hardware Edition has its own version and states which Core version it is based on:

```text
Chaos Router OS Core
    └── Core v2

Chaos Router OS Hardware Edition
    └── Hardware Edition v1
        └── based on Core v2
```

**Branches** in the repository `chaoscent/chaos-router-os`:

| Branch | Content |
|---|---|
| `dev/core` | Core development; what the installer installs until v1 |
| `dev/hardware-edition` | Hardware Edition development |
| `dev/apps` | The Apps Addon |
| `release/core`, `release/hardware-edition`, `release/apps` | Empty until the v1 release; from then on, only the newest full release |

At v1, `VERSION` becomes `1.0.0`, the release branches are filled and the installers, the redirect on chaos-software.dev and GitHub's default branch switch to `release/*` (see PLAN.md).

**Current version:** `0.1.0-alpha`.

---

# Apps Addon

## Optional

Neither Core nor the Hardware Edition ships with the Apps Addon. The Apps page in the sidebar offers to install it with one click. Core never depends on it; the Apps Addon depends on Core.

## What It Is

The addon lives on the branch `dev/apps` and installs into `/opt/chaos-router-apps` (owned by root):

- **Docker Engine and Docker Compose** from Docker's own repository.
- **Router-friendly Docker settings:**
  - `ip-forward-no-drop`: Docker doesn't block forwarding.
  - Its own address pool, 172.31.0.0/16.
- **The App Manager** `chaos-apps` (`/usr/local/bin/chaos-apps`). It is the only thing the app may run for apps (one sudoers rule), and only for apps in the catalog.

## Catalog

The catalog is **git-based**: no API, just one folder per app in the addon's repository with a Docker Compose definition and metadata (name, description, version, port, download size). The App Manager reads it, and the dashboard shows it.

Today's official catalog has fixed versions of Uptime Kuma, Vaultwarden, Jellyfin and Nextcloud. The Chaos Router OS project doesn't keep updating these versions.

Planned: community-maintained app definitions and additional catalogs. Chaos Router OS maintains the platform and the integration; app maintainers maintain their apps.

## How an App Fits In

Example: the user installs Nextcloud.

```text
Apps page → Install
        ↓
chaos-apps install nextcloud (Docker Compose project chaos-nextcloud)
        ↓
Port published on 127.0.0.1 only (never on the LAN or WAN)
        ↓
Chaos Router OS adds:
  - dnsmasq:  nextcloud.chaos-router.local → the router
  - Avahi:    the same name over mDNS
  - Caddy:    nextcloud.chaos-router.local → 127.0.0.1:<port>, HTTPS
        ↓
https://nextcloud.chaos-router.local
```

- **No extra ports:** apps open no ports beyond 80 and 443. Docker's published ports would bypass ufw, so they only go to 127.0.0.1, and Caddy is the only way in.
- **HTTPS:** like the dashboard, with Caddy's internal TLS. HTTP redirects to HTTPS.

## Lifecycle and Versions

- **Lifecycle:** install, open, start, stop, restart, update, logs, remove (keeping or deleting the data). Every action runs as a job with a live log on the Apps page.
- **Versions:**
  - The addon has its own version (shown on the Apps page), independent of Core.
  - Each app has its own version from the catalog.
  - Updating an app never requires updating Core.

## Isolation

A crashing app must not affect:
- routing, DHCP, DNS, Wi-Fi, VPN or the modem;
- the dashboard.

Apps run in containers with their own networks, separate from the router's services.

Planned: building and maintaining own app containers.

---

# Factory Reset

A factory reset returns the router to a freshly installed state without reinstalling Raspberry Pi OS. It is different from an update, which keeps the settings.

**Safety:** it asks for the admin password (System page) and says what it removes.

**Steps:**
1. Every area is set back to its defaults and applied:
   - Wi-Fi, DHCP, DNS, mobile data and the VPNs off.
   - Own firewall rules removed, LAN bridge removed.
   - **eth0 keeps its connection**, so the router stays reachable.
2. Generated secrets are deleted: OpenVPN certificates, WireGuard and hostapd configs, VPN client profiles.
3. `/var/lib/chaos-router-os` and `/tmp/chaos-router-os` are emptied. No stale configuration survives.
4. The router reboots into setup mode. The defaults from `/etc` (firewall, NAT) apply, and the setup Wi-Fi starts.

**The app itself stays installed**, and so do the **Apps Addon, Docker and the apps**. Their names and routes are set up again at the next start.

## Reset Levels

| Level | Resets | Keeps | Status |
|---|---|---|---|
| Router reset | All Chaos Router OS settings, secrets, admin account | The app, Apps Addon, apps and their data | Built (the factory reset) |
| Full reset | Additionally the apps and their data | The app | Planned |
| Uninstall | Everything Chaos Router OS set up, including Apps and Docker | eth0's settings, hostname, Wi-Fi country | Built (`uninstall.sh`) |
| Reinstall | Raspberry Pi OS itself | Nothing | Outside Chaos Router OS |

Planned: offering a backup download before a reset. Today, download one on the System page first.

**Recovery:** the installer can always repair or reinstall the app and the infrastructure, with or without the old settings.

---

# Security

- **Access:** HTTPS for the dashboard; admin login with password hashes; the session cookie is secure over HTTPS.
- **Session key and CSRF:** the session key is random per router. A CSRF token is required for every request that changes something.
- **Validation and least privilege:**
  - Every input is validated in the backend.
  - System commands run without a shell, as argument lists, so settings can't inject commands.
  - The app runs as a normal user, with `sudo -n` for a fixed list of commands only.
- **Reach:**
  - The app only listens on 127.0.0.1; Caddy is the only way in.
  - The firewall allows the dashboard, SSH, DHCP and DNS only on LAN interfaces.
  - `X-Forwarded-For` is trusted only from Caddy (localhost).
- **Apps:** the App Manager is root-owned, may only run catalog apps, and apps publish ports on 127.0.0.1 only.
- **Web shell:** off by default, needs its own password per session, LAN only, and not offered on phones.
- **Secrets on disk:** Wi-Fi passwords, VPN keys and the SIM PIN are stored with mode 600. The dashboard never sends the PIN or the mobile data password back.

---

# Development Workflow

Development happens on a PC (WSL), hardware testing on the Raspberry Pi.

```text
Edit (WSL)
 ↓
Test locally (app on port 5000; simulated radios and modem for UI tests)
 ↓
git commit
 ↓
git push (dev/core)
 ↓
On the Pi: run the curl installer again (updates, keeps settings)
 ↓
Hardware test
```

Git is the source of truth for the code. The online demo (demo.chaos-software.dev/router-os) is built from the frontend by the separate `chaos-router-os-demo` project, with a mock of the API. Changes to the API's format need the mock updated before the next demo build.

---

# Hardware Tests

Each of these must pass on a real Pi before a release:

- **Fresh install:** fresh Pi, installer, setup Wi-Fi with QR code and captive portal, setup wizard, dashboard on `https://chaos-router.local`.
- **Wi-Fi:** an access point per radio, clients connect, get DHCP and reach the router; saving one radio keeps the other's clients connected.
- **DHCP and DNS:** addresses on every served interface, local names, app names.
- **Mobile data:** modem found right after install, SIM PIN, APN automatic and by hand, reconnect after a reboot.
- **Caddy:** HTTPS on the router's names and addresses, HTTP redirect after setup, the CA download.
- **Safe Apply:** a change that cuts off the dashboard is reverted after 120 s and after a power cycle.
- **Update:** the installer run again keeps every setting.
- **Factory reset:** settings gone, router reachable over eth0, setup mode, apps still installed.
- **Apps:** addon install, app install, the app's name over HTTPS, a crashing app does not affect the router.
- **Uninstall:** nothing left behind; SSH over eth0 still works.

---

# Architecture Invariants

> [!important] These are architectural rules

- Core is installed through the permanent public bootstrap URL.
- Git is the source of truth for the code; the installer never lists app files.
- The code (`/opt`) is separate from the defaults (`/etc`), the persistent settings (`/var/lib`) and the running settings (`/tmp`).
- The app never writes `/etc/chaos-router-os`.
- Persistent settings are the last known-good state; settings become persistent only after validation, applying and verification.
- Running and pending settings are never authoritative at boot: a reboot always starts from `/var/lib`.
- Every change that can cut the user off waits for confirmation and reverts by itself.
- The backend validates everything; system commands never go through a shell.
- The app runs as a normal user with a fixed sudo command list.
- The installer is safe to run again and keeps all settings; updates never erase configuration.
- dnsmasq serves the LAN, never the router's own name lookups.
- `https://chaos-router.local` is the management address.
- The setup Wi-Fi runs on a 2.4 GHz-capable radio until an admin account exists. There is no default login.
- Core never depends on the Apps Addon; apps publish ports on 127.0.0.1 only, and Caddy is their only way in.
- A factory reset resets configuration, not the app and not the apps.

---

# Overview

```text
                         CHAOS ROUTER OS
                                │
                 ┌──────────────┴──────────────┐
                 │                             │
                CORE                      APPS ADDON (optional)
                 │                             │
     ┌───────────┼─────────────┐               ▼
     │           │             │             Docker
  Network       Web         Settings           │
     │           │             │               ├── App
     │           ├── Caddy     ├── /etc        ├── App
     │           └── App       ├── /var/lib    └── App
     │               (/opt)    └── /tmp
     │
     ├── NetworkManager (eth0, br0, chaos-modem)
     ├── ModemManager (wwan0)
     ├── hostapd (one per radio)
     ├── dnsmasq (DHCP, DNS)
     ├── ufw
     └── WireGuard, OpenVPN
```

> [!success] Core Design Rule
> **Chaos Router OS Core is a stable router platform on top of Raspberry Pi OS. Git supplies the code; settings live apart from it. A change becomes permanent only once it is verified, and a reboot always returns to the last known-good state. Optional apps live outside the router's lifecycle.**
