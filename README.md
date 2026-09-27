# Chaos Router OS

> **Development in Progress**

> **Disclaimer:** This project relies heavily on AI-assisted development (Vibecoding). Every feature is tested on real hardware before it's considered done.

Modern networking OS for the Raspberry Pi 5.

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

Officially supported hardware for **Core v1**:

* Raspberry Pi 5
* Waveshare PCIe TO 4G/5G M.2 USB3.2 HAT+
* Quectel RM520N-GL

Only hardware that can be tested is officially supported.

---

## Editions

### Core

Networking-first installation.

**Included**

* Dashboard
* Network
* VPN
* Modem
* Logs
* System
* Setup Wizard
* Caddy
* WireGuard
* MikroTik-style SPA navigation

Planned Install Command (coming with V1):
```bash
curl -fsSL chaos-software.dev/router-os/core | sudo bash
```

---

### Pro

**Core + Chaos Router hardware features.**

Compatible only with the Chaos Router hardware.

Adds:

* OLED integration
* Hardware switch integration
* RGB control
* GPS features
* Hardware-specific dashboard widgets
* GPIO services

Planned Install Command (coming soon):

```bash
curl -fsSL chaos-software.dev/router-os/pro | sudo bash
```

---

## Apps Addon

Neither **Core** nor **Pro** ships with the Apps Addon.

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

## Roadmap

### Core v1

* [x] Flask foundation
* [x] Dashboard UI
* [ ] Live System API
* [ ] SPA routing (`#/dashboard`)
* [ ] Network page
* [ ] VPN page
* [ ] Modem page (`mmcli`)
* [ ] Logs
* [ ] System
* [ ] Apps installer page

### Apps Addon v1

* [ ] Container Runtime installer
* [ ] App Manager
* [ ] Caddy automation
* [ ] First installable app

### Pro v1

* [ ] OLED integration
* [ ] Hardware buttons
* [ ] RGB control
* [ ] GPS
* [ ] Hardware widgets

---

## Design Principles

These are considered non-negotiable for v1.

* UniFi-inspired visual language (not a clone)
* MikroTik-style SPA navigation (`/#page`) with no full-page reloads
* Vanilla JavaScript frontend
* Flask backend
* Caddy as the reverse proxy
* No Docker dependency in Core
* Pro builds on Core, but hardware-exclusive features are never installable from Core

---

## License

License to be decided before v1 release.

---

## Status

**Early development.**

If something is broken, open an issue.

If something looks vibecoded, it probably is.

**Judge the router by the packets it routes, not by the prompts that helped build it.**
