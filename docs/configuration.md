# Configuration

Precedence (docs/06 §11): **built-in defaults → `APP_DATA_DIR/config.toml` → `FM_*` environment variables →
command-line options**.

## Application data directory (`APP_DATA_DIR`)

Separate from the replaceable binaries (BR-086). Set with `--data-dir` or `FM_DATA_DIR`.

| OS | Default |
|---|---|
| Windows | `%LOCALAPPDATA%\PennyWarden` |
| Mac | `~/Library/Application Support/PennyWarden` |
| Linux | `$XDG_DATA_HOME/pennywarden` or `~/.local/share/pennywarden` (a server install uses `/var/lib/pennywarden`) |

**Earlier names.** The application was called *Fundwarden* in 1.6.6 – 1.6.8 and *Financial Management POC* before
that. At its first start under the current name, if the PennyWarden folder does not exist yet, PennyWarden takes over
the folder of the most recent earlier name it finds — renaming it, or using it in place if it cannot be renamed:

| OS | Fundwarden (1.6.6 – 1.6.8) | before 1.6.6 |
|---|---|---|
| Windows | `%LOCALAPPDATA%\Fundwarden` | `%LOCALAPPDATA%\FinancialManagementPOC` |
| Mac | `~/Library/Application Support/Fundwarden` | — (the Mac app arrived in 1.6.7) |
| Linux | `~/.local/share/fundwarden` | `~/.local/share/financial-management-poc` |

A folder chosen with `--data-dir` or `FM_DATA_DIR` is never renamed. (A Linux *server* install is moved by the
installer instead; see docs/upgrade.md.)

```
APP_DATA_DIR/
  config.toml                      optional, human readable, no secrets
  database/fmpoc.sqlite3           SQLite (application owned; never opened over a network share)
  attachments/<xx>/<32-hex>.bin    generated storage names only
  secrets/portable-encryption-key.json   portable AES-256-GCM + HMAC keys (mode 0600; dir 0700)
  logs/fmpoc.log                   rotating, redacted
```

**The database, attachments and `secrets/` must be kept together.** Without the key file encrypted account
numbers cannot be decrypted; the application refuses to start if the key is missing or does not match the
database (key check value stored in the workspace row).

## Settings

| Setting (`config.toml [server]`) | Env var | Default | Meaning |
|---|---|---|---|
| `mode` | `FM_MODE` | `local` | `local` (loopback, opens browser) or `server` |
| `host` | `FM_HOST` | `127.0.0.1` | Bind address. Local mode always defaults to loopback |
| `port` | `FM_PORT` | `8765` | TCP port (UI and API share it) |
| `open_browser` | `FM_OPEN_BROWSER` | `true` | Local mode: open default browser after `/api/health` answers |
| `secure_cookies` | `FM_SECURE_COOKIES` | `auto` | `auto` = Secure flag when request is HTTPS; `true` behind a TLS proxy |
| `hsts` | `FM_HSTS` | `false` | Send HSTS on HTTPS responses |
| `trusted_proxies` | `FM_TRUSTED_PROXIES` | *(empty)* | Comma list of proxy IPs whose `X-Forwarded-*` headers are trusted (`*` only on a private network) |
| `session_idle_minutes` | `FM_SESSION_IDLE_MINUTES` | `30` | Idle session timeout |
| `session_absolute_hours` | `FM_SESSION_ABSOLUTE_HOURS` | `12` | Absolute session lifetime |
| `login_max_failures` | `FM_LOGIN_MAX_FAILURES` | `5` | Failed sign-ins per client address (and per unknown username) before a pause - a brake on top of the per-account count below |
| `login_lockout_seconds` | `FM_LOGIN_LOCKOUT_SECONDS` | `900` | Window / pause for `login_max_failures` |
| `lockout_1_failures` / `lockout_1_minutes` | `FM_LOCKOUT_1_FAILURES` / `FM_LOCKOUT_1_MINUTES` | `5` / `15` | 1.8.0: failed attempts in a row on one account (wrong passwords and wrong *Forgot password* answers or codes together, kept in the database) that lock it, and for how long |
| `lockout_2_failures` / `lockout_2_minutes` | `FM_LOCKOUT_2_FAILURES` / `FM_LOCKOUT_2_MINUTES` | `10` / `60` | Second lock; from this one on, Administrators see a notice |
| `lockout_3_failures` / `lockout_3_minutes` | `FM_LOCKOUT_3_FAILURES` / `FM_LOCKOUT_3_MINUTES` | `15` / `1440` | Third lock (24 hours) |
| `lockout_disable_failures` | `FM_LOCKOUT_DISABLE_FAILURES` | `20` | The account is disabled; an Administrator (or the host `reset-password` / `reset-mfa`) enables it again |
| `backup_folders` | `FM_BACKUP_FOLDERS` | *(empty)* | 1.9.0, server mode: the folders an Administrator may choose for scheduled backups — in `config.toml` a list (`backup_folders = ["/mnt/nas/pennywarden", "/srv/backups"]`), in the environment separated by `:` (Windows `;`). Local installs accept any folder |
| `update_channel` | `FM_UPDATE_CHANNEL` | `auto` | 1.10.0, the update notification: `auto` follows the build (production builds look for releases, test builds for newer test builds and releases, other builds do not check); `stable`, `test` or `off` force it. Administrators turn the check on or off in System/About |
| `update_base_url` | `FM_UPDATE_BASE_URL` | `https://pennywarden.org` | Where the release data files (`releases.json`, `releases-test.json`) are read |
| `log_level` | `FM_LOG_LEVEL` | `INFO` | Log level |

Example `config.toml`:

```toml
[server]
mode = "server"
host = "127.0.0.1"          # behind a reverse proxy on the same host
port = 8765
secure_cookies = "true"
hsts = true
trusted_proxies = "127.0.0.1"
```

Command line: `pennywarden --mode server --host 0.0.0.0 --port 8765 --data-dir /srv/pennywarden --no-browser`
(`python -m fmpoc` from source, `pennywarden` / `PennyWarden.exe` or `PennyWarden.cmd` when packaged).

## Changing settings in the application (2.0.0, #126)

**System/About → Settings** lists every setting in effect with its source (default, `config.toml`, environment or
command line). Administrators and Auditors can see it; it never contains secrets (the encryption key, passwords and
backup keys are not settings).

On a **server** install an Administrator can change these settings there: `trusted_proxies`, `secure_cookies`, `hsts`,
`session_idle_minutes` (5–480), `session_absolute_hours` (1–72), `login_max_failures` (3–50),
`login_lockout_seconds` (60–86400), `lockout_1/2/3_failures` and `lockout_disable_failures` (each larger than the one
before), `lockout_1/2/3_minutes` (1–10080) and `log_level` (DEBUG, INFO, WARNING, ERROR).

- `mode`, `host`, `port` and the data folder are **never** changed from the application (a wrong value would lock
  everyone out); neither is anything else not on the list above.
- A setting that an `FM_*` environment variable or a command-line option sets is shown **locked** with its source:
  change it where it is set.
- Saving rewrites `config.toml` in the data folder: the changed keys are set in `[server]`, every other line —
  comments, other keys, other tables — stays as it is. The new file is checked before it replaces the old one, which
  is kept as `config.toml.bak`. If the file can't be read safely, nothing is changed.
- Changes take effect when the service is **restarted**; until then the page shows *Restart required*. There is no
  restart button.
- Changing `trusted_proxies` needs the Administrator's password. A change that makes the server less strict (secure
  cookies off, HSTS off, longer sessions, more sign-in attempts, shorter locks, debug logging, trusting a proxy) needs
  an explicit confirmation. Every change is in the audit log with the values before and after
  (`SERVER_SETTINGS_CHANGED`).

On a **local** install the page shows the settings; change them in `config.toml`.

**Organization name.** An Administrator can rename the organization on System/About (1–120 characters; audited as
`ORGANIZATION_RENAMED`). New reports, letters and backup file names use the new name; documents already made keep the
old one.

**Backup reminder.** Administrators see a warning at the top of every page when no backup (made in System/About or
scheduled) has been made for 7 days; System/About → *Backup reminder* changes the number of days (0 turns it off). On a
new or restored installation the days count from the installation or the restore.

Debug mode, interactive API docs (`/docs`, `/openapi.json`) and verbose exception pages are never enabled.

## On a Mac

PennyWarden.app (Apple Silicon, since 1.6.7; installation: [install-macos.md](install-macos.md)) uses the same
settings as Windows and Linux. What is different:

- **Data folder:** `~/Library/Application Support/PennyWarden` — the database, attachments, `secrets/`, `logs/` and
  `config.toml` (see *Application data directory* above). Replacing the app with a newer one never touches it.
- **Opening the folder:** the `Library` folder is hidden in Finder. Use **Finder → Go → Go to Folder…** (⇧⌘G) and
  type `~/Library/Application Support/PennyWarden`. In Terminal: `open ~/Library/Application\ Support/PennyWarden`.
- **Log file:** `~/Library/Application Support/PennyWarden/logs/fmpoc.log`.
- **Settings for the app opened from Finder:** put them in `config.toml` in the data folder (create it with any text
  editor). An app opened from Finder or the Dock does **not** see `FM_*` environment variables set in a Terminal
  profile, so `config.toml` is the way to change settings permanently.
- **Starting with options:** run the app's program from Terminal, with the same options as on the other systems:
  ```
  /Applications/PennyWarden.app/Contents/MacOS/PennyWarden --port 8800
  /Applications/PennyWarden.app/Contents/MacOS/PennyWarden --data-dir ~/Documents/PennyWarden-data
  /Applications/PennyWarden.app/Contents/MacOS/PennyWarden --mode server     # server mode, no status window
  ```
  Started this way, `FM_*` environment variables of that Terminal do apply. In local mode the small PennyWarden
  window opens as usual (set `FM_NO_WINDOW=1` to run in the Terminal instead); closing it stops PennyWarden.
- **Host commands** work the same way, e.g. after a lost authenticator:
  `/Applications/PennyWarden.app/Contents/MacOS/PennyWarden reset-mfa --user NAME`, or when the only Administrator
  forgot the password and the answers to the security questions:
  `/Applications/PennyWarden.app/Contents/MacOS/PennyWarden reset-password --user NAME` (prints a temporary password
  that must be changed at the next sign-in). Both also enable a disabled account again.
- More about the Mac app (upgrading, the first start): [deployment.md](deployment.md) and
  [install-macos.md](install-macos.md).
