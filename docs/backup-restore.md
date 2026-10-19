# Backup and restore (since 1.4.1)

Administrators create and restore backups on **System/About → Backups → Backup / Restore**. A new installation can also be
set up from a backup in the **initialization wizard** ("Restore from a backup instead").

## What a backup contains

| Included | Not included |
|---|---|
| The database: organization, users and their password hashes, roles, two-step verification (authenticator secrets, recovery codes), every financial record, the audit log | `config.toml` (server settings: bind address, port, proxy, cookies) |
| Every attachment | Logs, the `pre-restore/` safety copy, temporary work files |
| The portable encryption key (`secrets/`) — needed to read bank account numbers and authenticator secrets | |

A backup is a single file `pennywarden-backup-<organization>-<date>-<time>.fmbak` (1.6.6 to 1.6.8:
`fundwarden-backup-…`; before 1.6.6:
`freedger-backup-…` — those files restore exactly as before).

## Encryption

The file is encrypted with a **passphrase you choose** (at least 12 characters): AES-256-GCM in 1 MiB authenticated
records, key derived with scrypt (N = 2^15, r = 8, p = 1). Record order, the end of the file and the header are
authenticated, so a changed, reordered or shortened file is refused. **Without the passphrase the backup cannot be
restored from the web page.** Keep the passphrase in a password manager and the backup file away from the server.

### Let this server recover the passphrase (since 2.0.0)

When **Let this server recover the passphrase** is ticked (the default), the server also keeps a *recovery file*: the
passphrase, encrypted with a random **server key** that never leaves this server. The backup file itself is unchanged.

- Only the server's owner can use it, from the server's command line:
  `sudo pennywarden restore FILE --use-server-key --data-dir /var/lib/pennywarden` on Linux (on Windows
  `C:\PennyWarden\current\PennyWarden.cmd restore FILE --use-server-key --data-dir C:\ProgramData\PennyWarden` in a
  terminal opened as Administrator). Scheduled backups are not covered: see *Which backups `--use-server-key` can
  restore*.
  The web page **always** asks for the passphrase — a stolen Administrator sign-in can't restore without it.
- It works only **on this server** and only **for this exact file** (the recovery file is bound to the file's
  fingerprint). A copy taken to another computer still needs the passphrase.
- The server key (`server-key/server.key`) and the recovery files (`backup-recovery/`) live in the data folder,
  readable only by the service account. They are never inside a backup. If the server itself is lost, so is the
  key: keep the passphrase too.
- Untick the option, or later choose **Remove recovery** in *Backups this server can recover*, and nobody can recover
  a lost passphrase for that backup. Removing it is audited (`BACKUP_RECOVERY_REMOVED`).

## Creating a backup

System/About → Backups → Backup / Restore → **Backup**: passphrase twice + your own password → **Create backup**. The database
is copied with SQLite's online backup API, so users can keep working. The download starts automatically; the file
stays downloadable from that page for one hour and is then deleted from the server's work folder.

## Restoring

System/About → Backups → Backup / Restore → **Restore**: choose the `.fmbak` file, enter its passphrase, your password and type
`RESTORE`. The file is uploaded in 20 MB parts (so large backups pass Cloudflare Tunnel's 100 MB request limit;
an interrupted part is retried). The page then shows each step:

1. Decrypting and checking the backup (passphrase, integrity, every file against the manifest)
2. Checking versions and the encryption key — a backup from a **newer** version is refused (upgrade the
   application first); a backup from an older 1.4.1+ version is migrated forward
3. Pausing the application (other requests get "restore in progress" for a few seconds)
4. Saving a safety copy of the current data — moved to `pre-restore/` in the data directory (only the latest copy
   is kept)
5. Updating the database to this version
6. Restarting the application — the database and key are reopened inside the running service (no process restart,
   works the same on Windows, systemd and Docker)

Everyone is signed out (all sessions and trusted browsers are revoked). Sign in with an account **from the backup**;
two-step verification continues with the authenticator from the backup. The restore is recorded in the restored audit
log as `SYSTEM_RESTORED`.

If any step fails the current data stays in place (or is put back from the safety copy) and the page says which step
failed. The largest accepted file is set by `restore_max_mb` in `config.toml` (default 20480).

### Restore re-entry report (since 2.0.0)

Before the data is replaced, every restore (web or command line) compares it with the backup. Transactions that
exist only in the data being replaced — entered, edited, voided or deleted after the backup was made — are written to
a CSV file in `restore-reports/` in the data folder (one row per line of the transaction: change, dates, who entered
it, bank account with a masked number, payee, budget, amount, invoice number, description, status, attachments).
Fiscal Years, budgets, entities and bank accounts created after the backup are listed by count and name.

Budget Managers, Budget Users, Register Users and Auditors download it under **Reports → Restore re-entry reports**.
The Administrator who restored, and the command line, see only a summary (for example "3 transaction(s) entered or
changed after the backup"): the report holds financial data. A backup from another system is compared by time only
(the report says so). Reports are kept until the server owner removes them.

## Restoring from the server's command line (since 2.0.0)

```
sudo pennywarden restore FILE.fmbak [--use-server-key | --passphrase-file PATH] --data-dir /var/lib/pennywarden [--stop-service] [--yes]
sudo pennywarden restore --list --data-dir /var/lib/pennywarden
```

(Linux server shown. Windows: `C:\PennyWarden\current\PennyWarden.cmd restore … --data-dir C:\ProgramData\PennyWarden` as
Administrator. A local install: the program itself, without `sudo` and without `--data-dir`, with PennyWarden quit.)

### The data folder (`--data-dir`)

**On a server install, always add `--data-dir`** to `restore`, `restore --list`, `reinitialize`, `reset-password` and
`reset-mfa`.

These commands do **not** ask the running service where its data is. They take the folder from, in this order:
1. `--data-dir DIR`;
2. the environment variable `FM_DATA_DIR`;
3. the **default folder of the user who runs the command**. Under `sudo` that is root's own folder
   (`/root/.local/share/pennywarden`), and for an Administrator on Windows it is `%LOCALAPPDATA%\PennyWarden`. Neither
   is where a server keeps its data.

The server installers give the service its folder as a command-line argument (systemd
`ExecStart … --data-dir /var/lib/pennywarden`, NSSM `… --data-dir C:\ProgramData\PennyWarden`). The
`/usr/local/bin/pennywarden` wrapper does not add it. The one exception is `sudo pennywarden apply-config` (2.1.0),
which reads the folder from the installed service.

| Installation | Data folder | Add |
|---|---|---|
| Linux server (`install-server.sh` / `install.sh`) | `/var/lib/pennywarden` | `--data-dir /var/lib/pennywarden` |
| Windows server (`install-windows-server.ps1`) | `C:\ProgramData\PennyWarden` (or the installer's `-DataDir`) | `--data-dir C:\ProgramData\PennyWarden` |
| Docker | `/data` on the data volume; the image sets `FM_DATA_DIR=/data` | nothing |
| Local install, Windows | `%LOCALAPPDATA%\PennyWarden` | nothing (run as the same user, PennyWarden quit) |
| Local install, Mac | `~/Library/Application Support/PennyWarden` | nothing |
| Local install, Linux | `~/.local/share/pennywarden` (or `$XDG_DATA_HOME/pennywarden`) | nothing |

**The symptom of leaving it out:** `--list` says *"No backups made on this server can be recovered with the server
key"*, and `--use-server-key` says *"This server can't unlock that backup"*. Neither message mentions the folder. Check
with `sudo pennywarden restore --list --data-dir /var/lib/pennywarden`: it should list your backups.

### Which backups `--use-server-key` can restore

| Backup | `--use-server-key` | Otherwise |
|---|---|---|
| Manual backup made on this server with *Let this server recover the passphrase* ticked | ✔ | — |
| `pre-reinitialize/` safety backup | ✔ | — |
| Manual backup made without recovery, or recovery removed later | ✘ | its passphrase |
| **Scheduled backup** | ✘ | the **schedule passphrase**: the one in use when that backup was made, if it was changed later |
| Backup from another system | ✘ | its passphrase |

### Restoring a scheduled backup from the command line

A scheduled backup never has a recovery file: it is locked with the schedule's key pair. Restore it with the schedule
passphrase, either at the hidden prompt or from a file:

```
sudo pennywarden restore /srv/pennywarden-backups/pennywarden-backup-<organization>-<date>-<time>.fmbak --data-dir /var/lib/pennywarden
sudo pennywarden restore /srv/pennywarden-backups/<file>.fmbak --passphrase-file /root/schedule-passphrase.txt --data-dir /var/lib/pennywarden
```

The file is in one of the `backup_folders`. A passphrase file holds the passphrase on one line; delete it afterwards.
The web page's **Restore** tab works the same way with the schedule passphrase.

### What `--list` shows

`--list` shows only backups the server key can recover (the first two rows of the table above).
- **A row with a full path under it** is a file kept on this server, such as a `pre-reinitialize/` backup. The command
  printed below the list is ready to paste and already includes `--data-dir`.
- **A row with no path** (usually a MANUAL backup) is a file that was downloaded. Pass that file from wherever you
  keep it: it is matched by its content, not its name or folder.
- *(was …; no longer on this server)* means the server's copy is gone. A downloaded copy still restores with the key.


- **Rights.** On a server install (the systemd service or the Windows service `PennyWarden`, see
  [install-windows-server.md](install-windows-server.md#9-host-commands)) run it with `sudo` / from a terminal
  opened as Administrator; it says so and stops before changing anything if it needs them. A per-user local install
  needs no extra rights. On Linux the restored files get the data folder's owner again and `secrets/` stays
  owner-only.
- **Passphrase.** Typed at a hidden prompt; or `--passphrase-file PATH` (one trailing newline is ignored), also as the
  environment variable `PENNYWARDEN_PASSPHRASE_FILE` for scripts; or `--use-server-key` for a backup made on this
  server with recovery on. The passphrase is never a command-line value and is never printed or logged.
- **The service.** If PennyWarden is running, the command asks *Stop it now? All signed-in users will be signed out*
  (`--stop-service` or `--yes` answer yes). Answer no and nothing changes. Afterwards it offers to start it again. A
  local install that is running must be quit first.
- **Steps.** The same as the web restore: decrypt and check, versions and key, re-entry report, safety copy in
  `pre-restore/`, swap, update the database, end every session — and put the old data back if anything fails. Audited
  as `SYSTEM_RESTORED` via `host_cli` with the operating-system user.
- **A new server.** It also restores onto a new, empty installation (`--data-dir` of the new data folder): the way to
  move to a new server from the command line. Without the old server's key the passphrase is needed.
- **Docker.** Nothing is stopped inside a container. Stop the app container, run the restore in a one-off container
  on the same data volume, then start it again (with the example `packaging/docker/docker-compose.yml`, service
  `app`):

  ```
  docker compose -f packaging/docker/docker-compose.yml stop app
  docker compose -f packaging/docker/docker-compose.yml run --rm -v /path/to/backups:/backups app restore /backups/FILE.fmbak --yes
  docker compose -f packaging/docker/docker-compose.yml start app
  ```

  Add `--use-server-key` for a backup made by this container (the key is on the data volume), or
  `--passphrase-file /backups/passphrase.txt`. Without either, add `-it` to `run` to type the passphrase.
- `--list` shows the backups this server can recover (date, size, who made it) and, for those kept on the server
  (such as the `pre-reinitialize/` safety backups), their **full path** plus a ready-to-paste restore command. Use it instead of
  typing the path: those folders are readable only by the service account and root (they hold backups the server can
  decrypt), so a normal shell can't list them or complete their file names with Tab, even with `sudo` in front.
- **The `pennywarden` command (Linux server, since 2.0.0).** The installer adds `/usr/local/bin/pennywarden`, which
  runs the current release, so `sudo pennywarden …` works from any folder. An installation made before 2.0.0 gets it
  with the next run of the installer; until then use `sudo /opt/pennywarden/current/pennywarden …`.

## Undoing a restore (`pre-restore/`)

> **Don't run another restore before undoing.** Every restore, from the web or the command line, first moves the
> current data to `pre-restore/` and **deletes the safety copy that was there**. Only the latest copy is kept. After a
> restore of the wrong file, "restore the right backup first" replaces `pre-restore/`, and with it the only copy of the
> newest data. Put `pre-restore/` back first.

`pre-restore/` in the data folder holds what was in place just before the latest restore: the previous `database/`,
`attachments/` and `secrets/`, plus a `README.txt` with the time of the restore. It is **folders, not an `.fmbak`
file**, so it can't be restored with `pennywarden restore`. Undoing means swapping the folders back by hand. A failed
restore puts it back by itself; this section is for a restore that succeeded with the wrong file.

### Linux server
```
sudo systemctl stop pennywarden
cd /var/lib/pennywarden
sudo cat pre-restore/README.txt                              # check the time: is this the data you want back?
sudo cp -a pre-restore /var/backups/pennywarden/pre-restore-copy-$(date +%Y%m%d-%H%M%S)   # a spare copy, outside
sudo mkdir wrong-restore-$(date +%Y%m%d-%H%M%S)
sudo mv database attachments secrets wrong-restore-*/        # the data from the mistaken restore, out of the way
sudo mv pre-restore/database pre-restore/attachments pre-restore/secrets .
sudo chown -R pennywarden:pennywarden database attachments secrets
sudo chmod 700 secrets && sudo chmod 600 secrets/*
sudo systemctl start pennywarden
```
Then sign in and check: the newest transactions are back, and System/About shows the expected organization.

### Windows server
In PowerShell as Administrator:
```powershell
Stop-Service PennyWarden
Set-Location C:\ProgramData\PennyWarden
Get-Content pre-restore\README.txt
Copy-Item pre-restore "C:\ProgramData\PennyWarden-pre-restore-copy-$(Get-Date -Format yyyyMMdd-HHmmss)" -Recurse
$aside = "wrong-restore-$(Get-Date -Format yyyyMMdd-HHmmss)"; New-Item -ItemType Directory $aside | Out-Null
Move-Item database, attachments, secrets $aside
Move-Item pre-restore\database, pre-restore\attachments, pre-restore\secrets .
Start-Service PennyWarden
```
The permissions carry over: the folders stay inside `C:\ProgramData\PennyWarden`, whose access rules they inherit.

### Docker
Stop the app (`docker compose -f packaging/docker/docker-compose.yml stop app`). Make the same moves on the data volume
from a one-off shell, for example
`docker run --rm -it -v pennywarden-data:/data --entrypoint sh <image>`, then `cd /data` and the Linux `mv` steps
without `sudo` and without `chown` (the image's user owns the volume). Then start the app again.

### Local install
Quit PennyWarden, then make the same moves in the data folder (see the table above) with Explorer or Finder. Start
PennyWarden again.

### Common mistakes
- `mv pre-restore/database /` moves it to the **root of the disk**, not the data folder. Run the moves from inside the
  data folder with `.` as the target, as shown.
- Moving onto a folder that already exists gives *"Directory not empty"*, or puts it **inside** the existing folder
  (`database/database`). Move the current folders aside first.
- *"cannot stat 'pre-restore/database'"* on a second try means the first move already worked. Check with `ls`.

### Afterwards
- **Sessions and trusted browsers from before the restore work again.** Only the restored database had them revoked.
  Sign out everywhere (System/About → Sessions) if you want everyone to sign in fresh.
- **The undo is not in the audit log.** The `SYSTEM_RESTORED` event was written in the data you moved aside. Record what
  happened yourself if your organization needs it, for example in a Fiscal Year note.
- **The re-entry report** in `restore-reports/` from the mistaken restore compared the wrong data. Remove it.
- **Clean up** once you've checked everything: delete the `wrong-restore-…` folder and the spare copy.

See also *Manual recovery without the application* below.

## Scheduled backups (since 1.9.0)

System/About → Backups → Backup / Restore → **Scheduled** writes backups on its own, without anyone signed in:

- **Schedule:** Daily at a time, or Weekly on a day at a time — the computer's (server's) local time.
- **Folder:** one folder the operating system running PennyWarden can already see: a local folder, an external drive
  or a mounted network share. On a **server** the server owner lists the allowed folders in `config.toml`
  (`backup_folders = ["/mnt/nas/pennywarden", "/srv/pennywarden-backups"]` — a list in square brackets, one quoted
  path each; docs/configuration.md) and the Administrator picks one; the service account (`pennywarden` on Linux) must
  be able to write there. **Linux server:** the service runs sandboxed and may write only to its data folder and the
  folders listed in `backup_folders` — **after changing `backup_folders`, run `sudo pennywarden apply-config`** (2.1.0;
  it checks `config.toml`, lets the service write to the listed folders, restarts it and waits until it answers;
  folders under `/home` can't be used). The installer does the same on every install or upgrade. Without that, *Test* reports that the
  folder can't be written even when its owner, group and permissions are right. On a **local install** any folder can
  be entered.
  **Test** writes and removes a small file to check the folder. Copying backups offsite is done outside PennyWarden.
- **Passphrase and key pair:** the Administrator sets a backup passphrase once (at least 12 characters; their own
  password confirms it). PennyWarden turns it into a key pair and keeps only the public key and the private key
  locked with the passphrase — it can **lock** each backup but cannot open one. Each file is encrypted like a manual
  backup (AES-256-GCM records) with its own random key, which is locked for the public key (X25519 + HKDF-SHA256);
  the locked private key travels in the file header, so the **passphrase alone restores it anywhere**: through the
  normal **Restore** tab, or from the command line with the schedule passphrase (*Restoring a scheduled backup from
  the command line*; `--use-server-key` does not work for scheduled backups). Changing the passphrase makes a new key pair: backups made before still need the earlier
  passphrase. A forgotten passphrase cannot be recovered.
- **Keep:** Daily schedule — how many daily, weekly (the first backup of each week) and monthly (the first backup of
  each month) backups to keep, e.g. 3 / 2 / 2; Weekly schedule — weekly and monthly only. The newest backup is always
  kept. Older ones are deleted after each successful backup — **only files PennyWarden wrote and recorded in its
  history, never anything else in the folder**.
- **Failures:** a failed backup is tried again after 1 hour, then 2, 4, 8 … hours (at most 24) so failing hardware
  is not hammered; the next scheduled backup runs at its normal time regardless and starts the sequence again.
  Administrators see a red banner on every page until the next backup succeeds.
- **Missed:** if PennyWarden was not running at the scheduled time, the backup runs about a minute after the next
  start.
- **Run now** writes a backup immediately; the page lists the recent runs with their result, file and size. Settings
  changes, runs, failures and deletions are in the audit log (`BACKUP_SCHEDULE_UPDATED`, `BACKUP_PASSPHRASE_SET`,
  `SCHEDULED_BACKUP_CREATED/FAILED/DELETED`).

## Moving to another server

On the new server install the same or a newer version, open it in the browser and choose **Restore from a backup
instead** in the initialization wizard (anyone who can reach an uninitialized installation can do this — the same as
running the wizard). The new server keeps its own `config.toml`.

## Manual recovery without the application

The files can also be copied by hand while the service is stopped: `database/`, `attachments/` and `secrets/` from
the data directory (`/var/lib/pennywarden` on a Linux server). The installer's automatic snapshots before each upgrade
(`/var/backups/pennywarden/<timestamp>/`) are such copies, and so is `pre-restore/`. Putting them back works like
*Undoing a restore* above: stop the service, move the current folders aside, move the copies in, then fix the
ownership on Linux.

## Reinitialize (keeping the users, since 2.0.0)

System/About → **Advanced** → **Reinitialize** removes all financial data and keeps the users — for example after
testing. It removes Fiscal Years, budgets, entities (not the system entity *Multiple*), bank accounts, the register,
attachments (records and files), fundraisers, the Payments module's data and organization reminders. It keeps users,
roles, passwords, two-step verification, security questions, the organization name, the encryption key, module
switches, personal preferences and reminders, backup settings and the **audit log** (with a `REINITIALIZE` event).
Entity numbers continue from the last one, so a new entity never reuses a number from an older backup or report.

1. Type `reinitialize`, your password and, if two-step verification is on, a code. Optionally choose your own
   passphrase for the safety backup (then it can also be restored from the web page); otherwise a random one is
   used, which only the server's owner can use.
2. The application pauses, makes the **safety backup** and checks it. If that fails, nothing is removed.
3. The backup goes to `pre-reinitialize/` in the data folder — never downloadable or removable from the web, and every
   one is kept. It is always recoverable by the server: the page shows the file and the exact command to undo it for
   this installation — on a Linux server
   `sudo pennywarden restore "<data folder>/pre-reinitialize/<file>.fmbak" --use-server-key --data-dir "<data folder>"`,
   on Windows the full path of `PennyWarden.cmd` in a terminal opened as Administrator.
4. The removal happens in one database transaction (all or nothing); the attachment files are removed after it.
   Everyone else is signed out. Everyone who signs in sees a notice (who, when) until an Administrator acknowledges it.

From the web it can be done once in 24 hours. On the server, `sudo pennywarden reinitialize --data-dir
/var/lib/pennywarden [--passphrase-file PATH] [--stop-service] [--yes]` does the same with no time limit (a limit would only push people to
delete the data folder, which leaves no backup); it asks for the word `reinitialize` unless `--yes` is given, handles
the service like `pennywarden restore`, and is audited via `host_cli`.
