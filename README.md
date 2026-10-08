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

**One network per radio.** Every Wi-Fi radio (the built-in one, USB adapters) runs its own access point with its own name, band and subnet. A radio sends on one band at a time, so 2.4 and 5 GHz at once need two radios.

---

## Editions

### Core

Networking-first installation.

**Included**

* Dashboard
* Modem (ModemManager: mobile data, APN, SIM PIN)
* Network (LAN bridge with selectable ports)
* WiFi (hostapd, 2.4 / 5 / 6 GHz, one network per radio)
* DHCP (dnsmasq, one range per interface)
* DNS (dnsmasq)
* Clients
* Firewall (ufw)
* VPN (WireGuard and OpenVPN, servers and clients)
* Logs
* System
* Shell (web terminal; off by default, password per session, desktop only)
* Safe Apply (bad settings never brick the router)
* Setup Wizard (first-time setup at `/setup`)
* Caddy (dashboard on ports 80 and 443, HTTPS with the router's own certificate authority)
* MikroTik-style SPA navigation

Install on Raspberry Pi OS Lite (64-bit), logged in as your normal user:
```bash
curl -fsSL https://raw.githubusercontent.com/chaoscent/chaos-router-os/dev/core/install.sh | sudo bash
```

The installer sets up the packages, the app, the default settings and the service, asks for your Wi-Fi country, and finishes with a QR code for the setup Wi-Fi. Scan it with your phone and the setup page opens. Running it again updates an existing install; your settings are kept. The country has no default: the installer lists every country with its code and you type yours. A Quectel modem in MBIM mode is switched to QMI mode (in MBIM mode Linux drops all received mobile data); set `CHAOS_MODEM_MODE=keep` to leave it, and switch back with `sudo /opt/chaos-router-os/deploy/modem-usb-mode.sh mbim`. Options: `--country US`, `--dir PATH`, `--yes` (needs `--country` unless the system already has one).

Short form: `curl -fsSL https://chaos-software.dev/router-os/core | sudo bash`.

To remove Chaos Router OS and everything it set up:

```bash
sudo /opt/chaos-router-os/uninstall.sh            # asks for confirmation
sudo /opt/chaos-router-os/uninstall.sh --dry-run  # only shows what it would do
```

It removes the Apps Addon with all apps (and Docker, if the addon installed it), switches off and deletes everything Chaos Router OS set up (Wi-Fi, DHCP, DNS, VPNs, firewall rules, NAT, LAN bridge, Caddy routes, mDNS names), purges the packages the installer installed, and deletes all its files. It keeps eth0's address settings (so SSH over eth0 stays), the hostname, the Wi-Fi country and the system journal. A dropped SSH connection doesn't stop it halfway (log: `/tmp/chaos-router-os-uninstall.log`). Options: `--yes`, `--keep-packages`, `--all-packages` (for installs made before the installer recorded its packages).

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

Before installation, it offers a one-click installer for the addon (`deploy/install-apps.sh`, which downloads the addon from this repository's `dev/apps` branch (`release/apps` from v1) and runs its installer).

After installation, it becomes the App Store: install, open, start/stop, update, view logs and remove apps, with the install output shown live.

The Apps Addon installs:

* Docker Engine
* Docker Compose
* App Manager (`chaos-apps`; only installs apps from its catalog)

Chaos Router OS does the integration when an app is installed:

* **Name:** `<app>.chaos-router.local`, e.g. `nextcloud.chaos-router.local` (the router itself: `chaos-router.local`)
* **Local DNS:** dnsmasq answers the name with the router's address (`/etc/dnsmasq.d/chaos-router-apps.conf`)
* **Caddy:** routes the name to the app over HTTP and HTTPS (`/etc/caddy/chaos-apps/<app>.caddy`)
* **HTTPS:** certificates for the app names from the router's local certificate authority

Apps publish their ports on 127.0.0.1 only: Caddy is the only way in.

Core networking functionality never depends on Docker or installed applications.

Apps in the catalog:

* Nextcloud
* Uptime Kuma
* Jellyfin
* Vaultwarden

Planned: Immich. Pi-hole and AdGuard need port 53, which the router's DNS uses.

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
127.0.0.1:9104
        │
Nextcloud container (80)
```

The router answers these names in two ways, because devices look up `.local` names differently:

* **DNS** (dnsmasq, `/etc/dnsmasq.d/chaos-router-apps.conf`): Windows, Android and everything else that asks the router's DNS.
* **mDNS** (Avahi, `chaos-router-mdns.service` running `deploy/mdns-publish.sh`): Apple devices and Linux with nss-mdns, which ask only over mDNS.

`chaos-router.local` (the dashboard) works without the Apps Addon too.

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

Services still read their own config files (`/etc/hostapd/chaos-<radio>.conf`, `/etc/dnsmasq.d/`, `/etc/wireguard/`, `/etc/openvpn/`). Those are generated from the JSON settings and re-applied at boot. Each Wi-Fi radio's access point is its own service, `chaos-hostapd@wlan0`, `chaos-hostapd@wlan1`, ...; the mobile data connection is the NetworkManager connection `chaos-modem`.

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

The dashboard runs on port `5000` (on the router, Caddy serves it on ports 80 and 443; see below). There is no default login: on first start every page leads to `/setup`, where you create the admin account.

While the router is not set up, the app also starts a setup Wi-Fi (WPA2, 10.42.0.1/24) with a captive portal. Show its name, password and QR code with `python backend/setup_wifi.py`. Set `CHAOS_SETUP_WIFI=0` to keep it off during development.

Write the default settings to `/etc/chaos-router-os` (the installer will do this later):

```bash
sudo .venv/bin/python backend/install_defaults.py
```

For development and tests, the three config folders can be moved with `CHAOS_DEFAULTS_DIR`, `CHAOS_STATE_DIR` and `CHAOS_RUNTIME_DIR`.

### Run as a service (starts at boot)

On the router, install the systemd service instead of starting `python backend/app.py` by hand. It runs the app with gunicorn (no debug mode) as your user, after NetworkManager is up, and restarts it if it crashes:

```bash
sudo deploy/install-service.sh            # install or update, then start
sudo deploy/install-service.sh --remove   # stop and remove (settings are kept)

journalctl -u chaos-router-os -f          # logs
sudo systemctl restart chaos-router-os    # after pulling new code
```

With the service, a reboot (including the one after a factory reset) brings the router back on its saved settings, or into the setup Wi-Fi when it is not set up.

### Caddy (ports 80 and 443)

When Caddy is installed (`sudo apt install caddy`; the installer does this), `install-service.sh` makes `deploy/Caddyfile` the system's `/etc/caddy/Caddyfile` (an existing one is kept as `Caddyfile.before-chaos` and put back by `--remove`). The app then only listens on `127.0.0.1:5000`, and Caddy serves the dashboard:

- `http://<router>/`: redirected to HTTPS once the router is set up. Before that it stays plain HTTP: the setup Wi-Fi's captive portal and the connectivity checks of phones need it. Apps always redirect to HTTPS.
- `https://<router>/`: HTTPS with a certificate from Caddy's own local certificate authority, made on the first visit for the address or name in the browser. Caddy asks the app first (`/caddy/tls-allowed`), which only allows the router's LAN addresses, its hostname, `<hostname>.local` and `<hostname>.<LAN domain>`. Browsers warn once per device, since they don't know this authority.

Install the authority's certificate on a device once (System page, "HTTPS Certificate", or `http://<router>/router-ca.crt`) and browsers trust the dashboard and every app without warnings. Over HTTPS the session cookie is marked Secure. No HSTS: with a router's own authority it would make the warning impossible to click through. The firewall keeps ports 80 and 443 closed on the internet side. The Caddyfile turns Caddy's admin API off, so apply changes with `sudo systemctl restart caddy` (not `reload`).

Without Caddy the service falls back to port 5000 on every address, as in development.

### System Requirements

The installer will set all of these up. For development, install them by hand:

```bash
sudo apt install dnsmasq hostapd modemmanager mobile-broadband-provider-info ufw iptables wireguard-tools openvpn easy-rsa openresolv iw rfkill qrencode caddy avahi-daemon avahi-utils
```

The app runs as a normal user and uses `sudo -n` for system changes, so that user needs passwordless sudo for:
`systemctl`, `journalctl`, `nmcli`, `mmcli`, `hostnamectl`, `sysctl`, `ip`, `ufw`, `iptables`, `ip6tables`, `iw`, `rfkill`, `wg`, `openvpn`, `easyrsa`, `install`, `mkdir`, `cp`, `rm`, `cat`, `test`, `find`.

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
| 🧪 | Mobile data (NetworkManager connection: APN with fallbacks, roaming, SIM PIN unlock, Quectel QMI mode) |
| ✅ | System |
| 🧪 | Safe Apply (verify, confirm or auto-revert, recover at boot) |
| 🧪 | Config layout (`/etc` defaults, `/var/lib` persistent, `/tmp` running) |
| 🧪 | WiFi page (hostapd, WPA2/WPA3, 2.4/5/6 GHz, one network per radio, connected clients) |
| 🧪 | DHCP page (dnsmasq, one range per interface, follows the Wi-Fi, static leases, active leases) |
| 🧪 | DNS page (dnsmasq, upstream providers, local records, blocklist, lookup) |
| 🧪 | Clients page (reserve DHCP IP, block device, ping, Wake-on-LAN) |
| 🧪 | Firewall page (ufw, default policies, rules) |
| 🧪 | Routing & NAT (IP forwarding, masquerading to the WAN) |
| 🧪 | eth0 LAN/WAN switch (Ethernet uplink instead of the modem) |
| 🧪 | LAN bridge (br0: chosen Ethernet and Wi-Fi ports in one network) |
| 🧪 | VPN page: WireGuard server |
| 🧪 | VPN page: OpenVPN server with its own certificate authority |
| 🧪 | VPN page: WireGuard and OpenVPN client profiles |
| 🧪 | Logs (router events and service logs) |
| 🧪 | Web shell (xterm.js; off by default, password per session, LAN only) |
| ⬜ | Start the app at boot (systemd service) |
| ⬜ | Installer with sudoers file |
| 🧪 | Setup Wizard (`/setup`: admin account, Wi-Fi; only until an account exists) |
| 🧪 | Caddy (ports 80 and 443, HTTPS from a local certificate authority) |
| 🧪 | Apps page: one-click Apps Addon install, app catalog (install, open, start/stop, update, logs, remove) |

### Apps Addon (released with v2)

* [x] Container Runtime installer (Apps Addon: Docker Engine + Compose)
* [x] App Manager
* [x] Caddy automation (and local DNS names)
* [x] First installable apps (Nextcloud, Uptime Kuma, Jellyfin, Vaultwarden)
* [ ] Test on the Pi 5 with real Docker

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

Chaos Router OS is free for **noncommercial use**: at home, for learning, in schools, clubs and nonprofits. You may use, change and share it, as long as the copyright notice in [LICENSE.md](LICENSE.md) ("Chaoscent - Chaos Router OS") stays with every copy.

**Companies and any commercial use need permission first.** That includes selling devices with it, offering it as a service, or using it in a business. Ask at contact@chaos-software.dev for a commercial license.

| Part | License |
|---|---|
| Software (this repository, the Apps Addon) | [PolyForm Noncommercial 1.0.0](LICENSE.md) |
| Documentation, website texts, images, videos | [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/): credit Chaoscent, no commercial use |
| xterm.js (`frontend/static/vendor/xterm`) | MIT, its own license files |
| Names "Chaos Router", "Chaos Router OS" and the logos | Not licensed |
| Chaos Router hardware (PCB, case) | Not public |

Contributions come under the agreement in [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Status

**Alpha: version 0.1.0-alpha** (the `VERSION` file; the dashboard shows it at the bottom of the sidebar, with the git commit on installs from a clone). Versions follow [semantic versioning](https://semver.org): `0.x` until the v1 release, then `1.0.0`.

If something is broken, open an issue.

If something looks vibecoded, it probably is.

**Judge the router by the packets it routes, not by the prompts that helped build it.**
