# Chaos Router OS

> **Development in Progress**

> **Disclaimer:** This project relies heavily on AI-assisted development (Vibecoding). Every feature is tested on real hardware before it's considered done.

A networking-first operating system for Raspberry Pi 5.

Built specifically for the Raspberry Pi 5, the Waveshare PCIe TO 4G/5G M.2 USB3.2 HAT+, and the Quectel RM520N-GL.

Chaos Router OS combines a UniFi-inspired interface with MikroTik-style navigation while keeping networking as the primary focus.

---

## Why?

Chaos Router OS exists because of **Chaos Router**.

My TP-Link M850 got hot enough to warp my SIM card. Instead of accepting that I'd have to replace the SIM every few months,
or buying another 5G router with Wi-Fi 6E, hoping it wouldn't melt my SIM too,
I decided to build my own router.

The software became its own project along the way.

---

## Supported Hardware

Officially tested hardware for **Core v1**:

* Raspberry Pi 5
* Waveshare PCIe TO 4G/5G M.2 USB3.2 HAT+
* Quectel RM520N-GL

Only hardware that can be tested is officially supported.

**Recommended OS:** Raspberry Pi OS Lite (64-bit). This is what the test system runs. The desktop version isn't needed: everything is managed from the web dashboard.

**Wi-Fi 6E (6 GHz)** needs an extra adapter whose driver can run a 6 GHz access point. The Raspberry Pi 5's built-in Wi-Fi has no 6 GHz radio; the WiFi page detects this and only offers the bands the radio supports.

---

## Editions

### Core

Networking-first installation.

**Included**

* Dashboard
* Modem
* Network
* WiFi (hostapd, 2.4 / 5 / 6 GHz)
* DHCP (dnsmasq)
* DNS (dnsmasq)
* Clients
* Firewall (ufw)
* VPN (WireGuard and OpenVPN, servers and clients)
* Logs
* System
* Safe Apply (bad settings never brick the router)
* Setup Wizard *(planned)*
* Caddy *(planned)*
* MikroTik-style SPA navigation

Planned Install Command (coming with V1):
```bash
curl -fsSL chaos-software.dev/router-os/core | sudo bash
```

---

### Hardware Edition

**Core + Chaos Router hardware features.**

Compatible only with the Chaos Router hardware.

Adds:

* OLED integration
* Hardware switch integration
* RGB control
* GPS features
* Hardware-specific dashboard widgets
* GPIO services

Planned Install Command (not recommended if you´re not using Chaos Router Hardware):

```bash
curl -fsSL chaos-software.dev/router-os/hardware-edition | sudo bash
```

---

## Apps Addon

Neither **Core** nor **Hardware Edition** ships with the Apps Addon.

The sidebar always contains an **Apps** page.

Before installation, it offers a one-click installer for the Container Runtime.

After installation, it becomes the App Store.

The Apps Addon installs:

* Docker Engine
* Docker Compose
* App Manager
* Caddy integration
* Local DNS integration

Core networking functionality never depends on Docker or installed applications.

Planned apps include:

* Nextcloud
* Pi-hole
* Uptime Kuma
* AdGuard
* Jellyfin
* Immich

---

## Networking Philosophy

The router owns ports **80** and **443**.

Applications never need to expose user-facing ports directly.

Example:

```text
nextcloud.chaos-router.local
        │
      Caddy
        │
localhost:9000
        │
Nextcloud container (80)
```

The user never has to remember `:9000`.

---

## Safe Apply

A bad setting must never brick the router.

Every change made in the dashboard goes through the same steps:

1. The new settings become the **running config**.
2. They are applied and **verified**: the service has to start, stay up, and (for DNS) actually answer.
3. Only verified settings are saved as the **persistent config**, which is what the router boots with.

If applying or verifying fails, the previous settings are restored immediately.

Changes that can cut you off (Network, Firewall, WiFi, DHCP, DNS, VPN servers, blocking a device) wait for confirmation. A banner on every page shows a countdown with **Keep changes** and **Revert**. If you can't reach the page any more, nobody confirms and the router reverts by itself after 120 seconds.

A reboot always comes back to the last verified config, because the running config is rebuilt from the persistent config at boot.

### Configuration Layout

Everything Chaos Router OS writes to these folders is JSON.

```text
/etc/chaos-router-os/        Defaults. Shipped with the OS, never written by the app.
                             Includes a firewall that is on: nothing comes in
                             from the internet, the LAN keeps working.
/var/lib/chaos-router-os/    Persistent config: only applied and verified settings.
  └── system/                Records of what is actually on the system
                             (firewall rules, OpenVPN certificate backup, event log).
/tmp/chaos-router-os/        Running config. Rebuilt from /var/lib at every boot.
```

Deleting a file in `/var/lib/chaos-router-os/` restores that area's defaults.

Services still read their own config files (`/etc/hostapd/`, `/etc/dnsmasq.d/`, `/etc/wireguard/`, `/etc/openvpn/`). Those are generated from the JSON settings and re-applied at boot.

---

## Development

```bash
git clone https://github.com/chaoscent/chaos-router-os
cd chaos-router-os

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python backend/app.py
```

The dashboard runs on port `5000`.

Write the default settings to `/etc/chaos-router-os` (the installer will do this later):

```bash
sudo .venv/bin/python backend/install_defaults.py
```

For development and tests, the three config folders can be moved with `CHAOS_DEFAULTS_DIR`, `CHAOS_STATE_DIR` and `CHAOS_RUNTIME_DIR`.

### System Requirements

The installer will set all of these up. For development, install them by hand:

```bash
sudo apt install dnsmasq hostapd ufw iptables wireguard-tools openvpn easy-rsa openresolv iw rfkill
```

The app runs as a normal user and uses `sudo -n` for system changes, so that user needs passwordless sudo for:
`systemctl`, `journalctl`, `nmcli`, `hostnamectl`, `sysctl`, `ufw`, `iptables`, `ip6tables`, `iw`, `rfkill`, `wg`, `openvpn`, `easyrsa`, `install`, `mkdir`, `cp`, `rm`, `cat`, `test`, `find`.

A ready-made sudoers file will ship with the installer.

---

## Roadmap

✅ done (tested on real hardware) · 🧪 implemented, waiting for hardware testing · ⬜ planned

### Core v1

| | Feature |
|---|---|
| ✅ | Flask foundation |
| ✅ | Dashboard UI |
| ✅ | Live System API |
| ✅ | SPA routing (`#/dashboard`) |
| ✅ | Network page |
| ✅ | Modem page (`mmcli`) |
| ✅ | System |
| 🧪 | Safe Apply (verify, confirm or auto-revert, recover at boot) |
| 🧪 | Config layout (`/etc` defaults, `/var/lib` persistent, `/tmp` running) |
| 🧪 | WiFi page (hostapd, WPA2/WPA3, 2.4/5/6 GHz, connected clients) |
| 🧪 | DHCP page (dnsmasq, static leases, active leases) |
| 🧪 | DNS page (dnsmasq, upstream providers, local records, blocklist, lookup) |
| 🧪 | Clients page (reserve DHCP IP, block device, ping, Wake-on-LAN) |
| 🧪 | Firewall page (ufw, default policies, rules) |
| 🧪 | Routing & NAT (IP forwarding, masquerading to the WAN) |
| 🧪 | eth0 LAN/WAN switch (Ethernet uplink instead of the modem) |
| 🧪 | VPN page: WireGuard server |
| 🧪 | VPN page: OpenVPN server with its own certificate authority |
| 🧪 | VPN page: WireGuard and OpenVPN client profiles |
| 🧪 | Logs (router events and service logs) |
| ⬜ | Start the app at boot (systemd service) |
| ⬜ | Installer with sudoers file |
| ⬜ | Setup Wizard |
| ⬜ | Caddy |
| ⬜ | Apps installer page |

### Apps Addon (released with v2)

* [ ] Container Runtime installer
* [ ] App Manager
* [ ] Caddy automation
* [ ] First installable app

### Hardware Edition

* [ ] OLED integration
* [ ] Hardware buttons
* [ ] RGB control
* [ ] GPS
* [ ] Hardware widgets

---

## Design Principles

These are considered non-negotiable for Chaos Router OS.

* UniFi-inspired visual language (not a clone)
* MikroTik-style SPA navigation (`/#page`) with no full-page reloads
* Vanilla JavaScript frontend
* Flask backend
* Caddy as the reverse proxy
* No Docker dependency in Core
* Hardware Edition builds on Core, but hardware-exclusive features are never installable from Core
* A bad setting never bricks the router: changes are verified before they are saved

---

## License

License to be decided before v1 release.

---

## Status

**Early development.**

If something is broken, open an issue.

If something looks vibecoded, it probably is.

**Judge the router by the packets it routes, not by the prompts that helped build it.**
