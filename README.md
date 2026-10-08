# Chaos Router Apps

The Apps Addon for [Chaos Router OS](https://github.com/chaoscent/chaos-router-os): run apps like Nextcloud, Jellyfin or Vaultwarden on the router in Docker containers, installed from the dashboard's **Apps** page.

Chaos Router OS never depends on this addon. Without it, the Apps page offers to install it.

## What it installs

- **Docker Engine and Docker Compose** from Docker's own apt repository (Debian, Raspberry Pi OS, Ubuntu).
- **Docker settings for a router** (`/etc/docker/daemon.json`):
  - `ip-forward-no-drop` (Docker 28+): Docker doesn't set the FORWARD policy to DROP, so LAN devices keep their internet even with the router's firewall off.
  - An address pool of its own (172.31.0.0/16), so Docker's networks don't clash with common LANs.
  - An existing `daemon.json` is left alone.
- **The App Manager** (`/usr/local/bin/chaos-apps` → `/opt/chaos-router-apps`, owned by root).
- **A sudoers rule** that lets Chaos Router OS run the App Manager, and nothing else.

## Install

From the dashboard: **Apps → Install Apps Addon**. By hand on the router:

```bash
git clone --branch dev/apps https://github.com/chaoscent/chaos-router-os chaos-router-apps
sudo chaos-router-apps/install.sh
```

The addon lives in the Chaos Router OS repository, on the branches `dev/apps` and `release/apps` (from the v1 release).

Running it again updates the addon; installed apps keep running. Remove it with `sudo /opt/chaos-router-apps/install.sh --remove` (add `--delete-data` to delete the apps' data too). Docker stays installed; `--purge` removes it as well (and the apps' data), if this installer installed it. Chaos Router OS's `uninstall.sh` runs `--remove --purge`.

## How apps fit into the router

Every app is reached by its own name: `<app>.chaos-router.local`, e.g. `http://nextcloud.chaos-router.local/` (the router itself is `chaos-router.local`). Chaos Router OS sets this up when an app is installed:

- **DNS:** dnsmasq answers the name with the router's address.
- **Caddy:** routes the name to the app over HTTP and HTTPS.
- **HTTPS:** a certificate from the router's local certificate authority, like the dashboard.

Apps publish their port on **127.0.0.1 only**. Docker's published ports bypass the firewall (ufw), so nothing is ever exposed directly; Caddy is the only way in.

## App Manager

```
chaos-apps version                      versions, Docker state (JSON)
chaos-apps catalog                      apps that can be installed (JSON)
chaos-apps status                       installed apps and their state (JSON)
chaos-apps install <app> --host <name>  download and start an app
chaos-apps start|stop|restart <app>
chaos-apps update <app>                 newer images, recreate
chaos-apps set-host <app> <name>        the name the app is reached at
chaos-apps remove <app> [--delete-data]
chaos-apps logs <app> [--lines N]
```

- Only apps from `catalog/` can be installed, so the dashboard can never make it run anything else.
- Each app is a Compose project named `chaos-<app>`.
- Its settings, with passwords generated per router, are in `/var/lib/chaos-router-apps/apps/<app>/app.env` (mode 600), and its data in `.../<app>/data/`.
- Removing an app keeps its data unless you pass `--delete-data`.
- Only one change runs at a time.

## Catalog

| App | Port (127.0.0.1) | Notes |
|---|---|---|
| Uptime Kuma | 9101 | |
| Vaultwarden | 9102 | Open it over HTTPS (the web vault needs it). Sign-ups are open until you turn them off. |
| Jellyfin | 9103 | Media goes into `/var/lib/chaos-router-apps/apps/jellyfin/data/media` (needs sudo for now). |
| Nextcloud | 9104 | With MariaDB. The trusted domain is set on first install; a later rename of the router needs `occ config:system:set trusted_domains`. |

Pi-hole and AdGuard are not in the catalog: they need port 53, which the router's own DNS (dnsmasq) uses.

### Adding an app

Add `catalog/<app>/app.json` and `catalog/<app>/compose.yaml`:

- **`app.json`:**
  - `id` (the folder name), `name`, `description`, `category`, `website`.
  - `port`: a free port, 9100 and up.
  - `download_mb`.
  - Optional: `https` (true if it only works over HTTPS), `first_steps`, `secrets` (names of passwords to generate) and `dirs` (folders to create in its data folder).
- **`compose.yaml`:**
  - Publish the web port as `"127.0.0.1:${CHAOS_PORT}:<port inside>"`.
  - Keep data under `${CHAOS_DATA}`.
  - Variables available: `CHAOS_HOST` (its name), `TZ` and the secrets.

Check it with `docker compose --env-file <an app.env> -f catalog/<app>/compose.yaml config`.

## Layout

```
install.sh          Installer (also updates and removes)
bin/chaos-apps      The App Manager (Python 3, standard library only)
catalog/<app>/      app.json + compose.yaml per app
```

## License

Free for noncommercial use under [PolyForm Noncommercial 1.0.0](LICENSE.md), with the copyright notice ("Chaoscent - Chaos Router OS Apps Addon") kept in every copy. Companies and any commercial use need permission first: contact@chaos-software.dev. Documentation: CC BY-NC 4.0.

The apps themselves (Nextcloud, Jellyfin, ...) are separate software under their own licenses. Contributions come under the agreement in Chaos Router OS's [CONTRIBUTING.md](https://github.com/chaoscent/chaos-router-os/blob/dev/core/CONTRIBUTING.md).
