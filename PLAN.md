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
- [ ] **Start at boot.** A systemd unit for the app. Without it, Safe Apply's boot recovery (`sync_boot` + `apply_all`) never runs unless the app is started by hand.
- [ ] **Production server.** Run under gunicorn or waitress (one or two workers), bound to localhost, with Caddy in front. The Flask dev server must not face the LAN.
- [ ] **Hardware testing.** Everything marked 🧪 has only been tested with fakes in WSL. Most likely to need fixes: Wi-Fi, 6 GHz, the OpenVPN PKI, the firewall.

---

## 2. Security before v1

- [ ] **CSRF protection and login rate limiting.** Check what exists; a router UI is a classic CSRF target.
- [ ] **No default credentials.** Remove the `backend/data/users.json` fallback. With no admin account, the router is in setup mode (see Setup Wizard).
- [ ] **Root helper instead of a broad sudoers list.** Passwordless `cp`, `rm`, `cat`, `install` and `find` together equal full root. Replace them with one small root helper script that only accepts specific operations; sudoers allows only that script (plus the service commands that are needed).
- [ ] **Backup encryption.** Backups contain passwords and VPN keys in plain text. Add optional password encryption.

---

## 3. Smaller gaps

- [ ] **Wi-Fi country.** Pi OS keeps Wi-Fi rfkill-blocked until a country is set. The installer sets a first value; the Setup Wizard and WiFi page set the real one.
- [ ] **IPv6.** Nothing handles it yet (router advertisements, DHCPv6, forwarding). IPv6 forwarding is deliberately left off: turning it on makes the kernel ignore router advertisements, which can cut off the modem's IPv6.
- [ ] **DNS local domain.** Changing the local domain only takes effect after the DNS settings are saved again.
- [ ] **Apps page.** Still a placeholder.
- [ ] **OpenVPN on slower CPUs.** Consider putting `CHACHA20-POLY1305` first in `CIPHERS`; it's faster than AES on a Pi 4, which lacks AES instructions.

---

## 4. Installer

One command (`curl -fsSL chaos-software.dev/router-os/core | sudo bash`). It must be **idempotent**: running it twice repairs rather than breaks.

- [ ] Check for Raspberry Pi OS Lite 64-bit; warn on anything else.
- [ ] Install the apt packages:
  `dnsmasq hostapd ufw iptables wireguard-tools openvpn easy-rsa openresolv iw rfkill qrencode`
- [ ] Create a dedicated service user.
- [ ] Install the app, Python venv and dependencies (check pins against the OS Python: 3.11 on Bookworm, 3.13 on Trixie).
- [ ] Install the root helper and the sudoers file.
- [ ] Run `backend/install_defaults.py` to write `/etc/chaos-router-os`.
- [ ] Unmask hostapd and set a Wi-Fi country (ask, or default to the worldwide setting).
- [ ] Make sure nothing else holds port 53 (DNS) or 67 (DHCP).
- [ ] Install and enable the systemd units (app, later Caddy).
- [ ] **If installed over the Pi's Wi-Fi:** detect it, warn that the SSH session will drop, and switch wlan0 to AP mode only as the very last step.
- [ ] Start the setup network and print its name, password and QR code (see Setup Wizard).

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

### Captive portal

- [ ] dnsmasq answers every DNS name with the Pi's IP during setup.
- [ ] Port 80 redirects to `/setup`.
- [ ] Redirect the OS check URLs so the portal opens by itself:
  - Apple: `/hotspot-detect.html`
  - Android: `/generate_204`
  - Windows: `/connecttest.txt`, `/ncsi.txt`
- [ ] HTTPS can't be intercepted, which is fine: the OS checks use HTTP.
- [ ] Keep `/setup` one simple page without relying on cookies; Apple's portal window doesn't keep them reliably.

### Steps

1. Admin username and password (stored as a hash).
2. Wi-Fi country.
3. Real Wi-Fi name and password.
4. Optional: WAN or modem check.
5. Finish.

### Finishing

- [ ] The setup network is replaced by the real one via `transaction.change("wifi")`. If the new network fails to start, Safe Apply reverts to the setup network instead of locking the user out.
- [ ] The page tells the user to reconnect to the new Wi-Fi and gives the dashboard address.
- [ ] `/setup` and `/api/setup/*` return 404 permanently.

### Fit with the existing code

- **Setup mode = no admin account in `/var/lib`.** Not a separate flag file. A reboot mid-setup simply starts setup again, the same recovery idea as Safe Apply.
- **API locked during setup.** Every route except `/setup` and `/api/setup/*` refuses requests until setup is complete.

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
