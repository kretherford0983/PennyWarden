# Deployment

The same application and data model serve both **local** and **server** use on Windows and Linux (BR-082).
Native packages need no separately installed Python, Node.js, SQLite, Docker or database server (BR-083).

## Local installation (single user, loopback)

- **Windows (one file, since 1.5.0)**: download `PennyWarden-<version>-windows-x64.exe` from the GitHub release and
  double-click it. A console window shows the address and log — closing it stops PennyWarden. The .exe unpacks itself
  to a temporary folder at each start, so starting takes a few seconds. It is not code-signed: Windows SmartScreen may
  say "Windows protected your PC" — click **More info → Run anyway** (check the file against `SHA256SUMS.txt` from
  the same release first if you like: `Get-FileHash .\PennyWarden-<version>-windows-x64.exe`). Data is kept in
  `%LOCALAPPDATA%\PennyWarden`, never inside the .exe, so replacing the .exe with a newer one keeps it.
  Server mode from a command prompt: `PennyWarden-<version>-windows-x64.exe --mode server`.
- **Mac with Apple Silicon (since 1.6.7)**: download `PennyWarden-<version>-macos-arm64.dmg` from the GitHub release,
  open it and drag **PennyWarden** onto **Applications**; then open PennyWarden from Applications. A small window
  shows the address and has **Open PennyWarden** and **Quit** — closing it stops PennyWarden. For M1 or later, macOS 11
  or later (not for Intel Macs). The app is signed "ad hoc" only — it is not signed with an Apple Developer ID and
  not notarized — so **the first start needs one confirmation**: macOS says *"PennyWarden" Not Opened — Apple could
  not verify…*; click **Done**, open **System Settings → Privacy & Security**, scroll to *Security* and click
  **Open Anyway** next to the PennyWarden line, then confirm. (macOS 14 and earlier: right-click the app →
  **Open** also works.) Step by step with pictures: [install-macos.md](install-macos.md). To check the download first: `shasum -a 256 PennyWarden-<version>-macos-arm64.dmg` against
  `SHA256SUMS.txt` from the same release. Data is kept in `~/Library/Application Support/PennyWarden`, never inside
  the app, so replacing the app with a newer one keeps it. To upgrade: quit PennyWarden, drag the new app onto
  Applications and choose *Replace*. Data folder, log, `config.toml` and options on a Mac:
  [configuration.md](configuration.md#on-a-mac). Server mode from Terminal:
  `/Applications/PennyWarden.app/Contents/MacOS/PennyWarden --mode server`. (On macOS 11 and 12 the Payments Setup
  previews show as a PDF instead of a picture; everything else is the same.)
- **Windows (portable folder)**: unzip `PennyWarden-windows-x64.zip` anywhere (e.g.
  `%LOCALAPPDATA%\Programs`), double-click `PennyWarden.cmd`.
- **Linux**: `tar xzf PennyWarden-linux-x64.tar.gz && ./pennywarden/pennywarden`

Startup applies pending Alembic migrations, binds to `127.0.0.1:8765`, waits for `/api/health`, and opens the
default browser when a desktop session is available. Plain HTTP is acceptable because traffic stays on loopback.

> **Data protection:** create encrypted backups regularly (System/About → Backups → Backup / Restore, since 1.4.1 — see
> docs/backup-restore.md) and keep them off this machine together with their passphrase.
> From 1.9.0 PennyWarden can also write them on a schedule (Backup / Restore → **Scheduled**) to a folder you
> choose, such as an external drive. On a server the folder must be listed by the server owner with
> `backup_folders` in `config.toml` (a list: `backup_folders = ["/srv/pennywarden-backups"]`; e.g. a mounted NAS
> share; in Docker, a volume mounted into the container), and the service account must be able to write to it. On the
> Linux server install, run `sudo pennywarden apply-config` after changing `backup_folders` (2.1.0): the service is
> sandboxed and may write only to the folders this command (and the installer, which runs it) allows (not under
> `/home`).

## Server installation (multiple users)

On **Windows** (Windows 10/11 or Windows Server): step by step in [install-windows-server.md](install-windows-server.md)
— the portable zip, a fixed data folder with its permissions, HTTPS through Caddy (or a Cloudflare Tunnel), and a
Windows service (NSSM) that starts it with Windows. Since 2.0.0 the script `install-windows-server.ps1` from the release does all of it in
one step (`-Domain books.example.org` for HTTPS through Caddy; without it, for a Cloudflare Tunnel) and upgrades the
same way.

### Linux: one command (since 1.5.0)

```bash
curl -fsSL https://github.com/kretherford0983/PennyWarden/releases/latest/download/install.sh | sudo bash
```

`install.sh` finds the release, downloads the Linux package, `install-server.sh` and `SHA256SUMS.txt` from it,
verifies the checksums and runs that release's `install-server.sh` (systemd service `pennywarden`, `/opt/pennywarden`,
data in `/var/lib/pennywarden`, a data snapshot before every upgrade, health check). The same command installs and
upgrades; `config.toml`, the key, the database and attachments are never replaced. An installation under an
earlier name (service `fundwarden`, 1.6.6 to 1.6.8; service `fmpoc`, before 1.6.6) is migrated to the new names by
the same command — see [upgrade.md](upgrade.md).

- **Which release:** by default the newest production release (1.6.6 was the first). `--channel test` installs the
  newest **test** pre-release instead (for a test server only); `--version <tag>` installs exactly that release:
  `curl -fsSL https://github.com/kretherford0983/PennyWarden/releases/download/<tag>/install.sh | sudo bash -s -- --version <tag>`
- **Port:** a new installation uses 8765 (`--port N` to change); an upgrade reads the port from the existing
  `config.toml`.
- **Also set up (since 2.0.0):** the `pennywarden` command for the host commands (`sudo pennywarden restore … --data-dir /var/lib/pennywarden`), and
  write access for the service to the scheduled-backup folders in `backup_folders`. After changing that list (or any
  other setting in `config.toml`), run `sudo pennywarden apply-config` (2.1.0) instead of the whole installer.
- **Where it listens (2.1.0):** the installer's health check and its last message use the configured **Bind
  Address** (`host` in `config.toml`): with `127.0.0.1` it says to point the tunnel at `http://127.0.0.1:PORT`; with
  `0.0.0.0` (tunnel or proxy on another machine) it lists this server's network addresses and the loopback address,
  and reminds you to restrict the port with the firewall and add the tunnel machine to `trusted_proxies`; with one
  specific address it uses that address.
- **Prefer to read it first?**
  `curl -fsSLO https://github.com/kretherford0983/PennyWarden/releases/download/<tag>/install.sh`, read it, then
  `sudo bash install.sh --version <tag>`.

The manual way (copy the package and `install-server.sh` to the server, then
`sudo bash install-server.sh PennyWarden-linux-x64-portable.tar.gz`) still works.

### Any platform

```bash
pennywarden --mode server --host 127.0.0.1 --port 8765 --no-browser     # behind a local reverse proxy
```

Authenticated network use must be served over HTTPS (BR-090). The application does not obtain certificates;
terminate TLS in a reverse proxy and set `FM_SECURE_COOKIES=true`, `FM_HSTS=true`, and `FM_TRUSTED_PROXIES` to the
proxy address. Binding to a network interface without `secure_cookies=true` prints a prominent
**SECURITY WARNING** at startup and shows a banner in the UI; it is never represented as secure.

### Caddy
```
finance.example.org {
    reverse_proxy 127.0.0.1:8765
}
```
### nginx
```nginx
server {
    listen 443 ssl http2;
    server_name finance.example.org;
    ssl_certificate     /etc/ssl/finance.crt;
    ssl_certificate_key /etc/ssl/finance.key;
    client_max_body_size 6m;
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```
### Apache
```apache
<VirtualHost *:443>
  ServerName finance.example.org
  SSLEngine on
  SSLCertificateFile /etc/ssl/finance.crt
  SSLCertificateKeyFile /etc/ssl/finance.key
  ProxyPreserveHost On
  RequestHeader set X-Forwarded-Proto "https"
  ProxyPass / http://127.0.0.1:8765/
  ProxyPassReverse / http://127.0.0.1:8765/
</VirtualHost>
```

Run as a service: systemd unit (`ExecStart=/opt/pennywarden/current/pennywarden --mode server --no-browser`,
`Environment=FM_DATA_DIR=/var/lib/pennywarden`, dedicated user) or on Windows as the service **PennyWarden** with
NSSM ([install-windows-server.md](install-windows-server.md#5-run-it-as-a-service-with-nssm)). Run a single application process per data directory (SQLite + in-process
login rate limiter; the per-account count of failed attempts is in the database).

Host commands for a locked-out user, run on the server — on the Linux server install with `sudo` (the installer adds
the `pennywarden` command since 2.0.0, and files the commands write are handed back to the service's account); on a
Windows server as Administrator with `C:\PennyWarden\current\PennyWarden.cmd`; see also `restore` and `reinitialize` in
[backup-restore.md](backup-restore.md):
`sudo pennywarden reset-mfa --user NAME --data-dir /var/lib/pennywarden` (two-step verification set up again; add
`--compromised` after a possible compromise so the user must use a newly generated key, 2.2.0) and,
from 1.8.0, `sudo pennywarden reset-password --user NAME --data-dir /var/lib/pennywarden` (prints a temporary password
that must be changed at the next sign-in). On a server always add `--data-dir`
([why](backup-restore.md#the-data-folder---data-dir)).
Both also enable an account that was disabled after too many failed attempts.

## Docker (optional)

```bash
docker build -f packaging/docker/Dockerfile -t pennywarden .
docker run -d -p 127.0.0.1:8765:8765 -v pennywarden-data:/data pennywarden
# or with automatic HTTPS:
docker compose -f packaging/docker/docker-compose.yml up -d     # edit Caddyfile host name first
```
Where a registry is unavailable, `packaging/docker/build_bundle_image.sh` builds an image from the self-contained
Linux bundle (this path was built and run during verification).

## Upgrades

See [upgrade.md](upgrade.md). In short: stop the application, replace the binaries, start it again. Alembic
migrations run automatically; databases are never dropped or recreated.

## Moving data between machines / operating systems (AC-DEP-006)

1. Stop the application.
2. Copy the whole application data directory (`database/`, `attachments/`, `secrets/`, optional `config.toml`).
3. Install a compatible or newer version on the target (Windows or Linux) and point `FM_DATA_DIR`/`--data-dir` at the copy.
4. Start: migrations run; encrypted account numbers decrypt with the portable key (plain JSON key file, no OS keystore).

On Windows, keep the data directory under the user profile (default `%LOCALAPPDATA%`) or, on a server, restrict its
ACL to Administrators, SYSTEM and the service account (`icacls`, [install-windows-server.md](install-windows-server.md#2-the-program-folder-and-the-data-folder)),
because POSIX `chmod 600` is not meaningful there.

## License

PennyWarden is free software under the GNU Affero General Public License v3.0 (`LICENSE`). Every package contains
`LICENSE` and `THIRD-PARTY-NOTICES.txt` (all bundled components and their licenses). The app links to its source code
(sign-in page, My Account, System/About) as AGPL section 13 requires. If you run a **modified** version for other
people, publish your changes and point `SOURCE_URL` in `backend/fmpoc/legal.py` at them.
