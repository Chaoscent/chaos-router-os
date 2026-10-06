# Chaos Router OS: Plan to v1

What is still missing before Core v1, and how the remaining pieces should work.
The README covers what exists; this file covers what's next.

Target platform: **Raspberry Pi OS Lite (64-bit)** on a Raspberry Pi 5.

---

## Order of work

1. ~~LAN NAT and IP forwarding~~ (done, needs hardware test)
2. systemd service and production server
3. Installer (with the root helper and sudoers file)
4. Testing on the Pi 5 (everything marked 🧪 in the README)
5. Setup Wizard with captive portal
6. Updater
7. Uninstaller
8. Caddy and HTTPS

The installer comes early because it makes hardware testing realistic.
The config schema version (see Updater) should be added right away, before any real installs exist.

---

## 1. Blockers

Without these it isn't a router yet.

- [x] **LAN NAT and IP forwarding.** Done: `services/routing.py`, the "Routing & NAT" card on the Firewall page. Applied at boot from the installed defaults (on by default), even before the first change. Still to do:
  - [ ] Test on the Pi 5: LAN devices get internet through the modem.
  - [x] The WAN is no longer guessed from the default route: it is eth0 when eth0 is switched to WAN mode on the Network page, otherwise `wwan0`.
  - [x] The firewall's essential rules follow the WAN (eth0 in WAN mode).
  - [ ] Test the eth0 LAN/WAN switch on the Pi 5: default route on eth0, NAT on eth0, DHCP paused on eth0.
  - [x] Essential firewall rules are a setting, rebuilt on every apply (and on every eth0 mode switch), not one-off copies.
  - [x] **Security:** SSH and the dashboard are only allowed on LAN interfaces, never on the WAN.
- [x] **Firewall on by default.** The installer ships `/etc/chaos-router-os/firewall.json`: on, incoming and routed denied, outgoing allowed, essential rules on. Applied at boot before the first change.
  - [ ] Test on the Pi 5 that a fresh install keeps SSH and the dashboard reachable from eth0 and Wi-Fi.
  - [ ] Once Caddy is in front, drop port 5000 from the essential rules (`CHAOS_PORT`).
  - [ ] Dev setups that enabled the firewall before this change still have the old "allow from any" essential copies as user rules; delete them on the Firewall page.
  - [ ] Consider TCP MSS clamping for the modem link (mobile networks often have a smaller MTU).
- [x] **Start at boot.** `deploy/chaos-router-os.service`, installed with `sudo deploy/install-service.sh` (`--remove` to uninstall): starts after NetworkManager, runs as the user who called sudo, restarts on failure, logs to the journal. Boot recovery (`sync_boot` + `apply_all`) and the setup Wi-Fi now run at every boot.
  - [ ] Test on the Pi 5: boot, factory reset reboot into the setup Wi-Fi, app crash restart.
  - [ ] The installer runs `install-service.sh` (or the same steps).
- [x] **Production server.** The service runs gunicorn (1 worker, 8 threads: Safe Apply's timer and the traffic sampler must stay in one process), no debug mode.
  - [ ] Bind to localhost once Caddy is in front (now `0.0.0.0:5000`).
- [ ] **Hardware testing.** Everything marked 🧪 has only been tested with fakes in WSL. Most likely to need fixes: Wi-Fi, 6 GHz, the OpenVPN PKI, the firewall.
- [x] **Mock modem data removed.** `get_modem_data()` reports `state`: `ready`, `not_ready` (modem found, no answer yet) or `absent`. Unknown values are `null` and shown as "--"; the header and Modem page say "No modem" / "Not ready". The header's Online/Offline pill follows the default route instead of always saying "Online".
  - [ ] Check the `mmcli` parsing against the real RM520N-GL on the Pi 5: signal values per section (`rsrp`, `rsrq`, `s/n`, 5G preferred over LTE), access tech ("lte, 5gnr" → "5G NSA"), SIM state. The parsing was written from documented output, not tested on the modem.
  - [ ] Show the active band. ModemManager does not report it; it needs AT commands (`AT+QENG="servingcell"` on Quectel) through `mmcli --command`.

---

## 1b. Website before v1

- [x] **Mobile layout.** Below 900 px the sidebar is a slide-in menu (☰ button in the header; closes on a page pick, a tap outside or Escape). 16 px side gutter on phones; tables scroll inside their card; dashboard numbers two per row. All pages fit a 390 px wide phone without sideways scrolling.
- [x] **Reboot** on the System page: confirmation (warns about unconfirmed changes, which a reboot reverts), `systemctl reboot` via sudo two seconds after answering, then the page waits for the router to go down and come back and reloads. Refused with a clear message when sudo does not allow it. Logged in the event log.
  - [ ] Test on the Pi 5.
- [x] **Factory reset** (`backend/factory_reset.py`, System page, asks for the password): every area is applied with its defaults (Wi-Fi, DHCP, DNS, VPNs off, own firewall rules removed, LAN bridge removed; eth0's connection is kept so the router stays reachable), OpenVPN PKI / WireGuard / hostapd configs and VPN client profiles are deleted, `/var/lib/chaos-router-os` and `/tmp/chaos-router-os` are emptied, then it reboots. At boot the `/etc` defaults (firewall, NAT) apply and the setup Wi-Fi with captive portal starts.
  - [x] Tested on the Pi 5: works.
  - [ ] Until the systemd service exists, the app has to be started by hand after the reset's reboot, otherwise no setup Wi-Fi appears.
  - [ ] eth0 keeps settings made in WAN mode (DHCP client, route metric 50) after a reset.
- [ ] **Version and updates** on the System page: show the installed version, check for a newer release, and start the updater (see Updater). Needs a version source (e.g. a `VERSION` file written by the installer).

---

## 2. Security before v1

- [x] **CSRF protection and login rate limiting** (`backend/security.py`, `frontend/static/js/csrf.js`).
  - The session key is random per router (`/var/lib/chaos-router-os/system/secret_key.json`, mode 600, not in backups). Before, it defaulted to the public string `chaos-router-dev`, so anyone could forge a session cookie.
  - Every POST/PUT/PATCH/DELETE needs the session's CSRF token (`X-CSRF-Token`, added by `csrf.js`) and must not come from another site (`Origin`). Also covers the login form. Session cookie: `HttpOnly`, `SameSite=Lax`.
  - Logout is a POST with the token.
  - Login: 5 failures within 15 minutes lock the client address out for 60 s, doubling up to 15 minutes; forgiven after 15 quiet minutes. Kept in memory (a restart clears it).
  - `X-Forwarded-For` is only trusted from localhost (Caddy), and its last entry is used (earlier ones can be faked by the client).
  - [ ] Once Caddy serves HTTPS: set `SESSION_COOKIE_SECURE`.
- [x] **No default credentials.** `backend/data/users.json` is gone, and `/etc` no longer ships a login. Without an admin account in `/var/lib`, the router is in setup mode.
  - [ ] On routers that ran an older `install_defaults.py`, delete the stale `/etc/chaos-router-os/users.json` (no longer read).
- [ ] **Root helper instead of a broad sudoers list.** Passwordless `cp`, `rm`, `cat`, `install` and `find` together equal full root. Replace them with one small root helper script that only accepts specific operations; sudoers allows only that script (plus the service commands that are needed).
- [ ] **Backup encryption.** Backups contain passwords and VPN keys in plain text. Add optional password encryption.

---

## 3. Smaller gaps

- [ ] **Wi-Fi country.** Pi OS keeps Wi-Fi rfkill-blocked until a country is set. The installer sets a first value; the Setup Wizard and WiFi page set the real one.
- [ ] **IPv6.** Nothing handles it yet (router advertisements, DHCPv6, forwarding). IPv6 forwarding is deliberately left off: turning it on makes the kernel ignore router advertisements, which can cut off the modem's IPv6.
- [ ] **DNS local domain.** Changing the local domain only takes effect after the DNS settings are saved again.
- [x] **LAN bridge (`br0`)** for one LAN across Ethernet and Wi-Fi: "LAN" card on the Network page (off by default, Safe Apply with confirmation). NetworkManager runs `br0` (connection `chaos-lan`) with the router's LAN address; eth0 in LAN mode is a port (`chaos-lan-eth0`) and leaves it in WAN mode; the access point joins via hostapd `bridge=br0`. DHCP/DNS settings that name a port are served on `br0`; bridge ports drop out of the LAN interface list.
  - [ ] Test on the Pi 5: bridge with eth0 + wlan1 (6 GHz), DHCP on br0, Wi-Fi clients get addresses, revert and reboot.
  - [x] Without the bridge, the access point gets its own address, set on the WiFi page (default 10.42.0.1/24 on the AP interface, e.g. wlan1). Applied with hostapd, verified, removed when the AP turns off or moves; subnets that overlap another interface are refused.
  - [ ] Test on the Pi 5: 10.42.0.1/24 on wlan1, DHCP on wlan1 (10.42.0.x range), Wi-Fi clients get internet through NAT.
  - [ ] The bridge pulls eth0 in while eth0 is in LAN mode, which cuts off access when eth0 is plugged into another router (seen on the test Pi; Safe Apply reverted it). Consider a bridge of Wi-Fi only, or refuse while eth0 has a DHCP-client address.
  - [ ] Only one access point at a time (one hostapd config). Running wlan0 (2.4/5 GHz) and wlan1 (6 GHz) together needs one hostapd instance per radio.
- [x] LAN interfaces are detected instead of a fixed list (eth0, wlan0, br0): every Ethernet (`eth*`, `en*`), Wi-Fi (`wlan*`, `wl*`) and bridge (`br*`) interface except the WAN. DHCP, DNS and the firewall's essential rules now include extra adapters like wlan1.
- [x] **VPN client: all traffic through the VPN** ("All traffic" per profile, checkbox on import): WireGuard AllowedIPs become 0.0.0.0/0 (+ ::/0 with an IPv6 tunnel address), OpenVPN gets `redirect-gateway def1`. Applied to the written files only; off = the profile's own routing.
  - [ ] Test on the Pi 5 with a real provider: LAN devices' public IP is the VPN's.
  - [ ] While a full tunnel is up, answers to connections from the internet side (WireGuard/OpenVPN servers on the router, remote dashboard access over the modem) also go into the tunnel and break. Needs policy routing for traffic that came in on the WAN.
  - [ ] Kill switch: block LAN internet access while the full-tunnel VPN is down, so nothing leaks over the WAN.
- [x] **Web shell** (Shell page; `backend/services/shell.py`, xterm.js 6 + fit add-on vendored in `frontend/static/vendor/xterm`, MIT): off by default (System > Web Shell, password to switch), password + 60 s one-time key per session (counts toward the login lockout), WebSocket origin check, never from the WAN interface or the modem, max 2 sessions, 15 min idle and session-lifetime limits, every session logged. Greyed out on phones/touch-only devices.
  - [ ] Test on the Pi 5 under the systemd service (gunicorn threads + WebSocket).
  - [ ] Keystrokes travel unencrypted until Caddy serves HTTPS.
- [ ] **Apps page.** Still a placeholder. Hide it or label it "coming in v2" before v1.
- [ ] **Active Clients is not a real count.** The dashboard shows 1 whenever there is any traffic. Count clients that sent traffic recently instead (per-client counters, e.g. from the neighbour table plus iptables accounting or conntrack).
- [ ] **OpenVPN on slower CPUs.** Consider putting `CHACHA20-POLY1305` first in `CIPHERS`; it's faster than AES on a Pi 4, which lacks AES instructions.

---

## 4. Installer

`install.sh` in the repo root: `curl -fsSL https://raw.githubusercontent.com/chaoscent/chaos-router-os/main/install.sh | sudo bash` (later also `chaos-software.dev/router-os/core`), or `sudo ./install.sh` from a clone. **Idempotent**: running it again updates, settings stay. Options `--country`, `--dir`, `--yes`.

- [x] Check for Raspberry Pi OS (64-bit, Raspberry Pi board); warn on anything else.
- [x] Install the apt packages (incl. git, python3-venv, NetworkManager, qrencode).
- [x] Get the code: the clone it runs from, else clone/update `/opt/chaos-router-os` (owned by the app user).
- [x] Python venv and dependencies.
- [x] `backend/install_defaults.py` writes `/etc/chaos-router-os`; stale `users.json` default login removed.
- [x] Wi-Fi country: asked (default: raspi-config's current value or DE), set via `raspi-config` (regulatory domain + rfkill unblock) and as the Wi-Fi default.
- [x] Passwordless sudo: kept if present, otherwise `/etc/sudoers.d/chaos-router-os` for exactly the app's commands (validated with visudo).
- [x] Warn when something other than dnsmasq holds port 53 or 67.
- [x] Install and start the systemd service (`deploy/install-service.sh`).
- [x] **Installed over the Pi's Wi-Fi** (detected from the open SSH connections): the setup Wi-Fi's name, password and QR code are shown *before* the service starts, then 15 s to scan.
- [x] Finish: setup Wi-Fi name, 12-character password and QR code (`backend/setup_wifi.py`), or the dashboard address when the router is already set up.
- [ ] Test on a fresh Raspberry Pi OS Lite (64-bit) on the Pi 5, both over Ethernet and over Wi-Fi SSH.
- [ ] Check the Python package pins against the OS Python (3.11 on Bookworm, 3.13 on Trixie).
- [ ] Dedicated service user + root helper (instead of running as the installing user with sudo).

---

## 5. Setup Wizard (captive portal)

### Setup network

After the installer finishes, the Pi's built-in Wi-Fi starts a **WPA2 network with a random password**. The installer prints the network name, the password and a **QR code** in the terminal (`qrencode -t ansiutf8 'WIFI:S:<ssid>;T:WPA;P:<password>;;'`). Scanning it joins the phone in one step.

Not an open network, because:
- anyone nearby could connect first and claim the admin account;
- the admin password would travel unencrypted over the air.

Enhanced Open (OWE) would fix the second point, but the Pi's built-in Wi-Fi probably can't do it in AP mode.

If the Pi is connected by Ethernet, the portal must work there too.

Hardware Edition: show the same QR code on the OLED.

- [x] **Setup Wi-Fi** (`backend/services/setup_network.py`), started by the app whenever it is not set up: `ChaosRouter-Setup-XXXX`, random 12-character password (stored in `system/setup_wifi.json`, mode 600, kept across reboots during setup), WPA2 on 2.4 GHz on the built-in radio, router at **10.42.0.1/24**, DHCP 10.42.0.100-200.
- [x] `python backend/setup_wifi.py` prints name, password and QR code (`qrencode`). The app's log only says how to show them, so the password does not end up in the journal.
- [ ] Test on the Pi 5 with real phones (iOS, Android, Windows).

### Captive portal

- [x] dnsmasq answers every DNS name with 10.42.0.1 on the setup Wi-Fi (separate drop-in, removed after setup) and announces the portal URL (DHCP option 114).
- [x] Port 80 on the setup Wi-Fi is redirected to the app's port (iptables `CHAOS-SETUP`, removed after setup).
- [x] OS check URLs (`/hotspot-detect.html`, `/generate_204`, `/connecttest.txt`, ...) and every other address on the setup Wi-Fi redirect to `http://10.42.0.1/setup`.
- [x] HTTPS can't be intercepted, which is fine: the OS checks use HTTP.
- [ ] Apple's portal window and cookies: the setup page needs the session cookie for its CSRF token within one visit; check on an iPhone.

### Steps

- [x] **The `/setup` page** (`backend/setup.py`, `frontend/templates/setup.html`, `frontend/static/js/setup.js`): three steps, built for phones.
  1. Admin username and password (stored as a hash; 8+ characters, obvious ones refused).
  2. Wi-Fi: country, network name, password (WPA2, 2.4 GHz). Optional; skipped automatically without a Wi-Fi radio.
  3. Review, finish, signed in, on to the dashboard.
- [ ] Optional: WAN or modem check step.

### Finishing

- [x] Wi-Fi is applied first through Safe Apply without confirmation (the browser may lose the connection). If it fails to start, it is rolled back, the setup Wi-Fi comes back, no account is created and the user can try again.
- [x] A Wi-Fi set up in the wizard keeps the setup subnet: 10.42.0.1/24 on the radio and DHCP 10.42.0.100-200 there. Without Wi-Fi, the setup Wi-Fi turns off a few seconds after the answer (the page warns when this device is on it).
- [ ] After setup the dashboard is on port 5000 (the port-80 redirect only exists during setup) until Caddy serves port 80.
- [x] The page tells the user to join the new Wi-Fi and gives the dashboard address.
- [x] `/setup` and `/api/setup/*` return 404 once an admin account exists; a factory reset (empty `/var/lib`) brings setup back.
- [ ] Test on the Pi 5 together with the installer's setup network.

### Fit with the existing code

- **Setup mode = no admin account in `/var/lib`.** Not a separate flag file. A reboot mid-setup simply starts setup again, the same recovery idea as Safe Apply.
- **API locked during setup.** Every route except `/setup`, `/api/setup/*` and static files refuses requests (409) or redirects to `/setup` until setup is complete. Captive portal checks (`/generate_204`, `/hotspot-detect.html`, ...) redirect to `/setup` too; DNS still has to point them at the router (installer).

---

## 6. Updater

- [ ] **Versioned releases** (git tags or tarballs), not `git pull`.
- [ ] **Schema version in the JSON config files** plus migrations between versions. Add the version field now.
- [ ] **Backup first:** take an automatic config backup with `create_backup()` before updating.
- [ ] **Update like Safe Apply:** keep the previous release, restart, run a health check, roll back automatically if the app doesn't come up.

---

## 7. Uninstaller

Most of what's needed already exists.

- [ ] Remove our dnsmasq drop-ins (`/etc/dnsmasq.d/chaos-router-*.conf`), WireGuard and OpenVPN files, and the OpenVPN NAT script.
- [ ] Sync our firewall rules to empty via the ledger (`system/firewall_rules.json`) and delete the `CHAOS-BLOCK` chain (iptables and ip6tables).
- [ ] Restore the recorded baselines.
- [ ] Remove the systemd units, root helper, sudoers file and service user.
- [ ] Ask about `/var/lib/chaos-router-os`: keep it, or export a backup before deleting it.
- [ ] Never remove packages or settings the user had before installing.

---

## 8. Caddy and HTTPS

- [ ] Caddy in front of the app on ports 80 and 443.
- [ ] Self-signed or local CA certificate.
- [ ] `get_viewer_ip()` already honours `X-Forwarded-For`; make sure only Caddy (localhost) is trusted for it.

---

## Hardware notes

**Pi 5 with 1 GB RAM:** fine for Core. Estimated use with everything enabled is about 300–400 MB (OS ~100–150 MB, NetworkManager + ModemManager ~20–30 MB, app ~40–80 MB, OpenVPN ~10 MB per instance, Caddy ~20–40 MB). Verify on the Pi with `free -h` and `ps -eo rss,comm --sort=-rss | head`.

- `/tmp` may be RAM-backed: never write anything large there.
- The journal may be volatile: logs are lost on reboot.
- Apps Addon on 1 GB: Docker alone needs ~100 MB. Pi-hole, AdGuard and Uptime Kuma fit; Nextcloud, Jellyfin and Immich don't. The App Store should warn about or hide RAM-heavy apps on small boards.

**Pi 4:** should work, with caveats: the modem runs over USB, OpenVPN with AES is slower (prefer ChaCha20), and NetworkManager (Bookworm or newer) is required.
