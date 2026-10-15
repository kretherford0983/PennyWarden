# Running PennyWarden as a server on Windows

For an organization where several people use PennyWarden from their own computers, and the server is a Windows
machine that stays on (Windows 11 or Windows Server 2022). On a single PC for one person, use the normal Windows
download instead ([deployment.md](deployment.md#local-installation-single-user-loopback)). On Linux, the one-command
install does all of this for you ([deployment.md](deployment.md#linux-one-command-since-150)).

In server mode PennyWarden requires **two-step verification** for every user, and it must be reached over
**HTTPS**. The steps below set up both: PennyWarden itself listens only on the server (`127.0.0.1`), runs as a
Windows service under its own account, and an HTTPS front end (Caddy) passes the browsers' requests to it.

## The installer script (recommended)

`install-windows-server.ps1`, attached to every release since 2.0.0, does everything in the rest of this guide for
you. In **PowerShell started as Administrator**:

```powershell
Invoke-WebRequest https://github.com/kretherford0983/PennyWarden/releases/latest/download/install-windows-server.ps1 -OutFile install-windows-server.ps1
powershell -ExecutionPolicy Bypass -File .\install-windows-server.ps1 -Domain books.example.org
```

- **`-Domain books.example.org`** — the web address people will use; it must already point at this server, and ports
  80 and 443 must reach it. The script installs **Caddy** as a second service in front of PennyWarden; Caddy gets and
  renews the HTTPS certificate from Let's Encrypt (add `-Email you@example.org` for its expiry notices).
- **Without `-Domain`** — for a Cloudflare Tunnel or another HTTPS front end you manage: PennyWarden listens on
  `http://127.0.0.1:8765` only, and you point the tunnel at that address.

What it does: downloads the Windows package and NSSM from the release and checks both against the release's
`SHA256SUMS.txt` (Caddy against the SHA-256 written in the script); installs the program into
`C:\PennyWarden\<version>` with `C:\PennyWarden\current` pointing at it; creates `C:\ProgramData\PennyWarden`
readable only by SYSTEM, Administrators and the service, with a `config.toml` for server mode; and runs PennyWarden as
the service **PennyWarden** under the virtual account `NT SERVICE\PennyWarden` (no password to manage), started at
boot and restarted if it stops. Then it checks that PennyWarden answers and tells you where to go next.

- **Upgrade:** run the same command again (the newest release; `-Version v2.1.0` for a particular one). The service
  is stopped, the data folder is copied to `C:\ProgramData\PennyWarden-upgrade-backups\<date-time>`, the new
  version is installed next to the old one and started. If it doesn't answer, the previous version is put back. An
  existing `config.toml` is never changed.
- **Test builds:** `-Version v2.0.0-test.130` (the release notes of each test build show the exact command).
- **Offline servers:** `-ZipPath`, `-NssmPath` and `-CaddyPath` use files you copied to the server
  (`-ZipPath` needs `-Version`).
- **Other folders or port:** `-InstallDir`, `-DataDir`, `-Port`.
- **Scheduled backups:** list the folders in `C:\ProgramData\PennyWarden\config.toml`
  (`backup_folders = ['D:\PennyWarden-backups']` — a list, single quotes), give the service write access to each
  (`icacls D:\PennyWarden-backups /grant "NT SERVICE\PennyWarden:(OI)(CI)M"`) and restart it
  (`Restart-Service PennyWarden`). On a network share the virtual account connects as the server's computer account
  (`DOMAIN\SERVERNAME$`), so grant that account on the share and its folder.
- **Uninstall:** `-Uninstall` removes the services and the program folder and keeps the data folder and the upgrade
  backups.
- `Get-Help .\install-windows-server.ps1 -Detailed` lists every option.

NSSM (public domain) is downloaded from nssm.cc by the release build, checked against the published SHA-1 and attached
to the release. The script is tested on every build on GitHub's Windows Server runner (install, upgrade keeping the
data, uninstall keeping the data); the Caddy certificate step needs a real domain and is not part of that test.

The rest of this guide is the same set-up **by hand**, for those who want to see or change each step.

## Setting it up by hand

> **Status (2.0.0):** these steps were written against the 2.0.0 code (paths, commands and settings checked against
> the application) but have **not yet been run end to end on a Windows machine**. Please report anything that
> doesn't match. The installer script above uses a virtual service account instead of the `pennywarden` user below.

What you need: an Administrator account on the server, a domain name that points at it (for HTTPS), and about half
an hour. Commands below are for **PowerShell started as Administrator** unless they say otherwise.

## 1. Choose the download

From the [latest release](https://github.com/kretherford0983/PennyWarden/releases/latest) download
**`PennyWarden-windows-x64.zip`** — the portable folder. It is the right one for a server: the one-file
`PennyWarden-<version>-windows-x64.exe` unpacks itself to a temporary folder at every start, which is slow and
awkward for a service. Check it against `SHA256SUMS.txt` from the same release:

```powershell
Get-FileHash .\PennyWarden-windows-x64.zip
```

## 2. The program folder and the data folder

1. **Program:** unzip to a folder per version, and point a fixed name at the version in use (upgrades then only
   move the pointer):

   ```powershell
   New-Item -ItemType Directory C:\PennyWarden -Force
   Expand-Archive .\PennyWarden-windows-x64.zip C:\PennyWarden\2.0.0
   # the zip contains one folder, PennyWarden-windows-x64: use it as the version folder
   Move-Item C:\PennyWarden\2.0.0\PennyWarden-windows-x64\* C:\PennyWarden\2.0.0\ ; Remove-Item C:\PennyWarden\2.0.0\PennyWarden-windows-x64
   cmd /c mklink /J C:\PennyWarden\current C:\PennyWarden\2.0.0
   ```

   `C:\PennyWarden\current` now holds `python\`, `app\`, `PennyWarden.cmd` (local mode and the host commands) and
   `PennyWarden-Server.cmd` (server mode). Nothing needs to be installed: Python is included.

2. **Service account:** a local user that only runs PennyWarden (Computer Management → Local Users and Groups, or):

   ```powershell
   $pw = Read-Host -AsSecureString "Password for the pennywarden account"
   New-LocalUser -Name pennywarden -Password $pw -PasswordNeverExpires -UserMayNotChangePassword -Description "PennyWarden service"
   ```

3. **Data:** the per-user default (`%LOCALAPPDATA%\PennyWarden`) belongs to whoever runs the program, so a service
   gets a fixed folder outside any profile. Only Administrators, SYSTEM and the service account may open it — it
   holds the database, the attachments and the encryption key (`secrets\`):

   ```powershell
   New-Item -ItemType Directory C:\ProgramData\PennyWarden\logs -Force
   icacls C:\ProgramData\PennyWarden /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" "pennywarden:(OI)(CI)M"
   ```

   Keep the data folder on a local disk of the server. **Don't put it on a network share** that other computers open:
   only PennyWarden may open the database (BR-084). Backups can go to a share (step 7).

## 3. config.toml

Create `C:\ProgramData\PennyWarden\config.toml` (Notepad is fine; *Save as type: All files*, not `.txt`):

```toml
[server]
mode = "server"
host = "127.0.0.1"          # only Caddy on this machine talks to PennyWarden
port = 8765
secure_cookies = "true"     # browsers reach it over HTTPS
hsts = true                 # browsers keep using HTTPS for this site
trusted_proxies = "127.0.0.1"   # believe the client address Caddy passes on
# where scheduled backups may be written (System/About -> Backups -> Backup / Restore -> Scheduled):
backup_folders = ['D:\PennyWarden-backups', '\\nas\backups\pennywarden']
```

Single quotes keep Windows backslashes as they are. Never put passwords or keys in this file — PennyWarden doesn't
need any there. Every setting: [configuration.md](configuration.md). Once it runs, an Administrator can see every
setting and where it comes from on System/About → Settings, and change the security and session settings there (they are
saved to this file and take effect after a restart of the service).

Settings can also come from `FM_*` environment variables. For a service they must be set **on the service** (step
5, `AppEnvironmentExtra`), not in your own terminal; they override `config.toml`.

Try it once by hand (Command Prompt or PowerShell, as Administrator):

```
C:\PennyWarden\current\PennyWarden-Server.cmd --data-dir C:\ProgramData\PennyWarden --no-browser
```

It prints `PennyWarden <version> - server mode - http://127.0.0.1:8765`. Stop it with Ctrl+C. (Don't initialize it
yet: the first Administrator is created over HTTPS in step 6.)

## 4. HTTPS with Caddy

[Caddy](https://caddyserver.com) is a single program that gets and renews the HTTPS certificate by itself.

1. Download `caddy.exe` (Windows amd64) from <https://caddyserver.com/download> into `C:\Caddy`.
2. Create `C:\Caddy\Caddyfile` (your domain instead of `books.example.org`, which must point at this server):

   ```
   books.example.org {
       reverse_proxy 127.0.0.1:8765
   }
   ```

3. Open ports 80 and 443 (Caddy needs both for the certificate). Port 8765 stays **closed**: only Caddy uses it.

   ```powershell
   New-NetFirewallRule -DisplayName "Caddy HTTPS" -Direction Inbound -Protocol TCP -LocalPort 80,443 -Action Allow
   ```

   On a home or office router, forward ports 80 and 443 to this server.
4. Caddy also runs as a service (step 5): program `C:\Caddy\caddy.exe`, arguments
   `run --config C:\Caddy\Caddyfile`.

What the settings in `config.toml` mean with Caddy in front:

| Setting | Value | Why |
|---|---|---|
| `host` | `127.0.0.1` | PennyWarden is never reached directly from the network |
| `secure_cookies` | `"true"` | the sign-in cookie is only ever sent over HTTPS |
| `hsts` | `true` | browsers remember to use HTTPS for this site |
| `trusted_proxies` | `"127.0.0.1"` | PennyWarden believes the `X-Forwarded-*` headers only from Caddy, so the audit log and sign-in limits see the real client address |

If PennyWarden is reachable on the network over plain HTTP (for example `host = "0.0.0.0"` without HTTPS), it shows
a security warning on every page, and it is right to: passwords and data would cross the network unencrypted.

*Alternatives:* a Cloudflare Tunnel (`cloudflared` as a Windows service, public hostname → `http://127.0.0.1:8765`;
no open ports) or IIS with URL Rewrite and ARR work too; the settings above stay the same.

## 5. Run it as a service with NSSM

[NSSM](https://nssm.cc) (the Non-Sucking Service Manager) turns PennyWarden into a real Windows service: it starts at
boot before anyone signs in, restarts it if it stops, and is stopped and started like any other service.

1. Download NSSM 2.24 from <https://nssm.cc/download>, unzip it and copy `win64\nssm.exe` to `C:\PennyWarden\nssm.exe`.
2. Create the service (PowerShell as Administrator; the service name must be **PennyWarden** — the host commands
   `pennywarden restore` and `pennywarden reinitialize` stop and start the service by that name):

   ```powershell
   $n = "C:\PennyWarden\nssm.exe"
   & $n install PennyWarden C:\PennyWarden\current\python\python.exe
   & $n set PennyWarden AppParameters "-I C:\PennyWarden\current\app\launch.py --mode server --no-browser --data-dir C:\ProgramData\PennyWarden"
   & $n set PennyWarden AppDirectory C:\PennyWarden\current
   & $n set PennyWarden AppEnvironmentExtra PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
   & $n set PennyWarden DisplayName "PennyWarden"
   & $n set PennyWarden Start SERVICE_AUTO_START
   & $n set PennyWarden ObjectName .\pennywarden "<the pennywarden account's password>"
   & $n set PennyWarden AppExit Default Restart
   & $n set PennyWarden AppRestartDelay 3000
   & $n set PennyWarden AppStdout C:\ProgramData\PennyWarden\logs\service.log
   & $n set PennyWarden AppStderr C:\ProgramData\PennyWarden\logs\service.log
   ```

   (It runs `python.exe` directly — the same as `PennyWarden-Server.cmd` — so stopping the service stops PennyWarden
   cleanly.) If the service won't start with a log-on error, give the account the right in *Local Security Policy →
   Local Policies → User Rights Assignment → Log on as a service*.
3. The same for Caddy (it runs as *Local System*, NSSM's default, so it can use ports 80 and 443 and keep its
   certificates):

   ```powershell
   & $n install Caddy C:\Caddy\caddy.exe
   & $n set Caddy AppParameters "run --config C:\Caddy\Caddyfile"
   & $n set Caddy AppDirectory C:\Caddy
   & $n set Caddy Start SERVICE_AUTO_START
   ```

4. Start, stop, restart (or use the Services app, `services.msc`):

   ```powershell
   Start-Service PennyWarden ; Start-Service Caddy
   Stop-Service PennyWarden
   Restart-Service PennyWarden
   Get-Service PennyWarden
   ```

**Logs:** PennyWarden's own log is `C:\ProgramData\PennyWarden\logs\fmpoc.log` (rotated at 5 MB, five kept); what
the program prints at start (and any start-up error) is in `logs\service.log`. Administrators can also download a
scrubbed diagnostics file from System/About.

## 6. First sign-in

Open `https://books.example.org` in a browser. The **Initialization Wizard** asks for the organization's name and
the first Administrator, who then sets up two-step verification (an authenticator app) and three security questions.
Then create the other users under **Users**.

## 7. Backups

- **From the application:** System/About → Backups → Backup / Restore. *Backup* creates an encrypted file you download (keep
  its passphrase in a password manager). *Scheduled* writes backups automatically to one of the `backup_folders` from
  `config.toml` — give the `pennywarden` account write access to that folder (for a share, the share and its
  folder permissions). Administrators get a warning when no backup has been made for 7 days.
- **Off the machine:** keep copies of the backups somewhere else (another drive, a NAS, cloud storage).
- **The data folder by hand:** stop the service first (`Stop-Service PennyWarden`), then copy
  `C:\ProgramData\PennyWarden` (`database\`, `attachments\`, `secrets\` and `config.toml`).
- **Restore** from System/About, or on the server:

  ```
  C:\PennyWarden\current\PennyWarden.cmd restore D:\PennyWarden-backups\FILE.fmbak --data-dir C:\ProgramData\PennyWarden
  ```

  in a PowerShell or Command Prompt **started as Administrator**. It asks before stopping the PennyWarden service and
  offers to start it again. `--use-server-key` restores a backup made on this server without its passphrase;
  `restore --list` shows which. Details: [backup-restore.md](backup-restore.md).

## 8. Upgrading

1. Make a backup (System/About → Backups → Backup / Restore), or stop the service and copy `C:\ProgramData\PennyWarden`.
2. Unzip the new version into its own folder next to the old one, e.g. `C:\PennyWarden\2.1.0` (as in step 2).
3. Switch over:

   ```powershell
   Stop-Service PennyWarden
   cmd /c rmdir C:\PennyWarden\current
   cmd /c mklink /J C:\PennyWarden\current C:\PennyWarden\2.1.0
   Start-Service PennyWarden
   ```

   (`rmdir` on the junction removes only the pointer, never the version folder.) The database is updated at the
   start. Sign in and check System/About shows the new version.
4. **Roll back:** stop the service, point `current` at the old folder again, and — if the new version changed the
   database ([upgrade.md](upgrade.md) lists the changes per version) — restore the backup from step 1; start.

When an update is available, Administrators see it in PennyWarden itself (the gold arrow next to their name). Keep
the old version folder until you are happy with the new one.

## 9. Host commands

Run them on the server in a PowerShell or Command Prompt **started as Administrator** (Administrators have full
control of the data folder), with `--data-dir`:

```
C:\PennyWarden\current\PennyWarden.cmd reset-mfa --user NAME --data-dir C:\ProgramData\PennyWarden
C:\PennyWarden\current\PennyWarden.cmd reset-password --user NAME --data-dir C:\ProgramData\PennyWarden
C:\PennyWarden\current\PennyWarden.cmd restore FILE.fmbak --data-dir C:\ProgramData\PennyWarden
C:\PennyWarden\current\PennyWarden.cmd reinitialize --data-dir C:\ProgramData\PennyWarden
```

`reset-mfa` makes a user set up two-step verification again; `reset-password` prints a temporary password that must
be changed at the next sign-in (both also enable an account disabled after too many failed attempts). `restore` and
`reinitialize` stop the service first (they ask) — see [backup-restore.md](backup-restore.md). Files these commands
create keep the folder's permissions from step 2, so the service account can still read them.

## 10. Troubleshooting

| What you see | What to do |
|---|---|
| The service starts and stops at once | Look at `C:\ProgramData\PennyWarden\logs\service.log`. Often `config.toml` was saved as `config.toml.txt` (turn on *File name extensions* in Explorer), or a setting is misspelled. |
| *Port 8765 is in use* (in `service.log`) | Another program uses it: `Get-NetTCPConnection -LocalPort 8765`. Choose another `port` in `config.toml` and the same in the Caddyfile. |
| The service won't start: log-on failure | The `pennywarden` password changed, or the account lacks *Log on as a service* (step 5). `nssm set PennyWarden ObjectName .\pennywarden "<password>"` sets it again. |
| *Windows protected your PC* (SmartScreen) | The zip isn't code-signed. Check it with `Get-FileHash` against `SHA256SUMS.txt`, then *More info → Run anyway*, or right-click the zip → Properties → *Unblock* before unzipping. |
| Browser: *Not secure* or the security warning banner | Use the `https://` address through Caddy. `host` must be `127.0.0.1` and `secure_cookies = "true"`. Check Caddy's service is running and ports 80/443 reach the server (the certificate needs them). |
| Signed out right after signing in | `secure_cookies = "true"` but the page was opened over `http://` — use the HTTPS address. |
| Every sign-in in the audit log comes from 127.0.0.1 | `trusted_proxies = "127.0.0.1"` is missing, so the address Caddy passes on is not believed. |
| Scheduled backup fails: folder can't be reached | The `pennywarden` account needs write access to the folder (and to the share for a network path); the folder must be listed in `backup_folders`. |
