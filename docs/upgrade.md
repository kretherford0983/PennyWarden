# Upgrading a Linux server install (current release: 2.0.0)

The upgrade replaces only the application binaries. It does **not** modify:

- `/var/lib/pennywarden/config.toml` (only written when it does not exist)
- `/var/lib/pennywarden/secrets/` (portable encryption key), `database/`, `attachments/`, `logs/`

Before switching versions the installer stops the service and copies the whole data directory to
`/var/backups/pennywarden/<timestamp>/`. The previous release stays in `/opt/pennywarden/releases/` for rollback.

| Upgrade | Database change | Rollback |
|---|---|---|
| 2.3.x → 2.4.0 | migrations `0069` and `0070`. `0070` adds `fundraiser.event_type` — every existing record becomes a **Fundraiser** (nothing else changes; a record whose budgets don't meet the new rule shows a warning, see the 2.4 guide). `0069`: `attachment.storage_key` is no longer unique (attachments with identical content share one stored file) and an index on `attachment(workspace_id, sha256)`. **At the first start**, attachments with identical content are linked to one stored file and the extra copies in `attachments/` are deleted — each file's SHA-256 is verified first; a file that is missing or no longer matches is left as it is and reported (log and the audit event *Identical attachment files merged*). No attachment record, name or owner changes | switch binaries **and** restore the pre-upgrade data backup (2.3.x does not know revisions 0069–0070 and needs the removed copies) |
| 2.2.x → 2.3.0 | migrations from `0060`, additions only: `fundraiser.goal_amount_cents` (empty = no goal; `0060`), correction/retirement columns on `bank_account_balance` (empty) and the table `fiscal_year_balance_change` (empty; `0061`), `estimated` on `fundraiser_series_result` and `budget_history_entry` (off; `0062`), `donation.ein_override_reason` (empty; `0063`), and `check_signer.areas` (`0064`): existing signers are tagged for Checks, the Donations Setup signer name and title become a signer tagged for donation letters (space to sign by hand, as before) and a cover letter's typed fallback name becomes a signer tagged for cover letters — nothing prints differently, and the dark theme on `branding_settings` (`0065`: dark palette, the theme per output type, dark-background logos; every existing organization stays light for every output, with a branding row added where there was none), and `app_user.report_prefs` (empty; `0066`: Recently run and each report's last options), the table `report_grouping` (empty = the Purpose grouping; `0067`), and the table `budget_inclusion` (empty; `0068`: years a budget's money was included in another budget) | switch binaries **and** restore the pre-upgrade data backup (2.2.x does not know revisions 0060 and later) |
| 2.1.x → 2.2.0 | migrations `0048`–`0059`, additions only except `0057`, which splits each entity's Primary Contact into first and last name: `user_mfa.new_key_required` (off: set by a two-step reset marked as a possible compromise) and `user_mfa.pending_own_key` (off) (`0048`), and the table `budget_history_entry` (empty: budget figures of years before PennyWarden; `0049`), and the table `testing_state` (empty; read only in testing mode; `0050`), and `workspace.demo_mode` (off: the demo marker, set only by `scripts/build_demo.py`; `0051`), and `bank_account.account_opened_date` (empty = the account existed before PennyWarden; `0052`), and the table `branding_settings` (empty = the PennyWarden palette, no logos; `0053`), and the table `donation` with new `donation_line`, `donation_receipt` and `attachment` columns — every 2.1 donation (one donor's marked lines on one deposit) becomes a donation that started from that deposit, with its lines, details and receipts; no amount, date or receipt changes (`0054`), `check_document.features`/`default_for` (every envelope is tagged Payments; Payments keeps its default; `0055`), the table `donation_statement` with `attachment.donation_statement_id` and `fundraiser_bucket.is_donation` (off) (`0056`), and entity names (`0057`): **the Primary Contact becomes First name and Last name, split at the first space** (one word = the first name) — every split name is listed under *Names to review* for a Budget Manager to check — plus empty display-name and mailing-address fields (empty = the name and the address, so nothing prints differently) and `app_user.name_order` (empty = First Last), and `app_user.fundraiser_series_sort` (empty = Fundraiser series newest year first; `0058`), and the table `former_budget` with `budget_history_entry.former_budget_id`/`code`/`name` and `budget.continues_former_budget_id` — the years entered before the upgrade become one budget from before PennyWarden per budget line, continued by the earliest budget of that line, so nothing shows differently (`0059`) | switch binaries **and** restore the pre-upgrade data backup (2.1.x does not know revisions 0048 and later) |
| 2.0.0 → 2.1.0 | migrations `0035` to `0047`, all additions — no existing value changes: `app_user.register_sort` (empty = Date, oldest first; `0035`), four columns on `register_transaction` for electronic payments — `electronic_payment` (off for every existing transaction), `payment_method`, `payment_method_other`, `payment_reference` (`0036`) — `attachment.sort_order` (empty = upload order; `0037`) and the table `budget_projection_choice` (each user's projected / not projected choices for the Budget Review and the Planning Sheet; empty = the defaults; `0038`), and the table `fundraiser_bucket_category` with `fundraiser_bucket.category_id` (empty = uncategorized) and `display_order` (existing buckets numbered in the order they were listed: by name), and `fundraiser_bucket_line.charge_cents` (= the existing amount), `less_cents` (0) and `less_description` (`0039`; every figure stays the same), and `fundraiser.summary_notes`, `results_final_at`, `results_final_by_user_id` (empty; `0040`), and the tables `fundraiser_series`, `fundraiser_series_result`, `fundraiser_fy_report_note` with `fundraiser.series_id` / `continues_from_id` (empty; `0041`), and `fundraiser_bucket_line.contributor_override` (empty; `0042`), and the table `fundraiser_line_contributor` (empty; `0043`), and `check_printer_setting.fold_marks` (empty = each user follows the letter template, whose fold marks are off after the upgrade; `0044`), and `workspace.donations_enabled` (off) with the tables `donation_settings`, `donation_line` and `donation_receipt` (empty; `0045`), and `entity.is_organization` (off) and `entity.ein` (empty), with one new Organization entity per organization named like it — the organization profile (`0046`), and `donation_line.date_received` (empty = the deposit's date) with the table `donation_detail` (empty; `0047`) | switch binaries **and** restore the pre-upgrade data backup (2.0.0 does not know revisions 0035–0047) |
| 1.10.0 → 2.0.0 | migrations `0025` to `0034`, all additions — no existing value is changed or removed. Tables: `check_style`, `check_signer`, `check_account`, `check_printer_setting` (`0025`) and `check_document` (`0027`) for the Payments module. Columns: `workspace` — `checks_enabled` (off; `0025`), `backup_warning_days` (7; `0029`), four for maintenance mode (`0031`) and five for reinitialize (`0032`); `app_user` — `last_payment_account_id` (`0026`), `first_name`, `last_name` (`0033`); `transaction_allocation.invoice_date` (`0027`); `check_printer_setting.document_id` (`0027`); four logo columns on `check_document` (`0028`); `auth_session.client_ip` (`0030`); `audit_event` — `actor_name` (`0033`) and `labels` (`0034`; existing audit events are never rewritten). See *2.0.0: after the upgrade* below | switch binaries **and** restore the pre-upgrade data backup (1.10.0 does not know revisions 0025–0034) |
| 1.9.0 → 1.10.0 | migration `0024` — creates the table `update_check` (the update notification: on/off and the last result); no existing data changes | switch binaries **and** restore the pre-upgrade data backup (1.9.0 does not know revision 0024) |
| 1.8.0 → 1.9.0 | migration `0023` — creates the tables `backup_schedule` and `backup_run` (scheduled backups); no existing data changes. On a local install new installations give the first user every role; existing users keep their roles | switch binaries **and** restore the pre-upgrade data backup (1.8.0 does not know revision 0023) |
| 1.7.3 → 1.8.0 | migrations `0021` and `0022` — `0021`: adds the empty column `budget.continues_budget_id` and its index; no existing budget is linked; `0022`: adds eight columns to `app_user` (count of failed attempts, lock, temporary-password flag, the question offered by *Forgot password*, notices) and the tables `user_security_question` and `security_notice` — no existing data changes; every user chooses security questions at the next sign-in | switch binaries **and** restore the pre-upgrade data backup (1.7.3 does not know revisions 0021 and 0022) |
| 1.7.2 → 1.7.3 | migrations `0019` and `0020` — `0019`: adds the *Budget Admin* and *Register Admin* roles and three columns to `register_transaction` (`deleted_at`, `deleted_by_user_id`, `delete_reason`); `0020`: creates `bank_account_balance` and rebuilds the balance history of every non-register account from the audit log (each recorded balance becomes an entry; a last entry with today's balance is added where needed) — no current balance changes | switch binaries **and** restore the pre-upgrade data backup (1.7.2 does not know revisions 0019 and 0020) |
| 1.7.1 → 1.7.2 | none | switch binaries |
| 1.7.0 → 1.7.1 | migrations `0017` and `0018` — `0017`: no column added or removed: users without a display name (or with one shorter than 3 characters) get their **username** as display name, every other display name is left as it is; two database triggers then require a display name of at least 3 characters for every user; `0018`: adds `bank_account.sort_order` and fills it so that each group lists the Primary account first and the others by name (as before) | switch binaries **and** restore the pre-upgrade data backup (1.7.0 does not know revisions 0017 and 0018) |
| 1.6.8 → 1.7.0 | none — the application is renamed to PennyWarden (see *1.7.0: the rename to PennyWarden* below) | switch back to the old `fundwarden` service (left in place) |
| 1.6.7 → 1.6.8 | none | switch binaries only |
| 1.6.6 → 1.6.7 | migrations `0014` — **adds** column `entity.position` (empty for every existing Entity); `0015` — **adds** columns `reminder.repeat_every`, `repeat_unit`, `repeat_until`, `repeat_anchor`, `repeat_index`, `repeat_source_id` (existing reminders stay one-time); `0016` — **rewrites** `entity.phone` values that are clearly 10-digit numbers to plain digits (e.g. `555-123-4567` → `5551234567`); other values are left as they are | switch binaries **and** restore the pre-upgrade data backup |
| 1.6.5 → 1.6.6 | none — the application is renamed to Fundwarden (see *1.6.6: the rename* below) | switch back to the old `fmpoc` service (left in place) |
| 1.6.4 → 1.6.5 | none | switch binaries only |
| 1.6.3 → 1.6.4 | migration `0013` — **adds** columns `fundraiser.cancelled_at`, `cancelled_by_user_id`, `cancel_reason` | switch binaries **and** restore the pre-upgrade data backup |
| 1.6.2 → 1.6.3 | migration `0012` — **adds** table `reminder` | switch binaries **and** restore the pre-upgrade data backup |
| 1.6.1 → 1.6.2 | none | switch binaries only |
| 1.6.0 → 1.6.1 | migration `0011` — **adds** tables `fundraiser_bucket`, `fundraiser_bucket_line`, `fundraiser_classification`, `fundraiser_exclusion` and column `attachment.fundraiser_id` | switch binaries **and** restore the pre-upgrade data backup |
| 1.5.0 → 1.6.0 | migration `0010` — **adds** column `workspace.fundraisers_enabled` (off) and tables `fundraiser`, `fundraiser_budget` | switch binaries **and** restore the pre-upgrade data backup |
| 1.4.1 → 1.5.0 | migration `0009` — **adds** column `app_user.dashboard_layout` (NULL = standard dashboard layout) | switch binaries **and** restore the pre-upgrade data backup |
| 1.3.0 → 1.4.1 | migrations `0006`–`0008` (as below) | switch binaries **and** restore the pre-upgrade data backup |
| 1.4.0 → 1.4.1 | migrations `0006` — **adds** table `signature_template`; `0007` — **adds** column `app_user.dashboard_charts`; `0008` — **adds** tables `user_mfa`, `mfa_recovery_code`, `trusted_device` and column `auth_session.mfa_pending`. **After the upgrade every user of a server install sets up two-step verification at the next sign-in** — see below | switch binaries **and** restore the pre-upgrade data backup |
| 1.3.0 → 1.4.0 | none | switch binaries only |
| 1.2.x → 1.4.0 | migration `0005` (see 1.2.x → 1.3.0) | switch binaries **and** restore the pre-upgrade data backup |
| 1.2.x → 1.3.0 | migration `0005` — **adds** tables `request_key`, `check_number_acknowledgement` and columns on `attachment` (document type, system-generated), `fiscal_year` (approval "no document" mark) and `app_user` (collapsed menu); existing Fiscal Year documents are labelled "Other" | switch binaries **and** restore the pre-upgrade data backup |
| 1.1.x → 1.3.0 | migrations `0003`–`0005` applied in order automatically | restore the pre-upgrade data backup |
| 1.2.0 → 1.2.1 | migration `0004` — **adds** four columns to `transaction_allocation` (per-allocation no-attachment flag, reason, who/when); no existing value is changed or removed | switch binaries **and** restore the pre-upgrade data backup (1.2.0 does not know revision 0004) |
| 1.1.x → 1.2.1 | migrations `0003` + `0004` applied in order automatically | restore the pre-upgrade data backup |
| 1.1.x → 1.2.0 | migration `0003` — **adds** columns to `register_transaction` (transfer link, no-attachment flag); no existing value is changed or removed | switch binaries **and** restore the pre-upgrade data backup (1.1.x cannot open a 0003 database) |
| 1.1.0 → 1.1.1 | none | switch binaries only |

Verified during release testing: upgrading a 1.4.0 server with data to 1.4.1 (installer, simulated systemd) left
`config.toml`, the key and all attachments byte-for-byte identical, kept every row and applied `0006`–`0008`; users
were then asked to set up two-step verification; a backup → restore round trip on the upgraded server worked
(including two-step verification from the backup). Rollback: the 1.4.0 binaries alone refuse the 1.4.1 database
("Can't locate revision"); restoring the installer's data snapshot with the 1.4.0 binaries returned exactly the
pre-upgrade data.
Verified for 1.6.7 (simulated systemd): a 1.6.6 `fundwarden` server with data was upgraded with `install-server.sh`:
snapshot taken, `0014` applied (`entity.position` empty for every Entity), every other row, attachment, the key and a
hand-edited `config.toml` identical. The 1.6.6 binaries alone refuse the 1.6.7 database ("Can't locate revision");
with the snapshot restored they started on exactly the pre-upgrade data.
Repeated for the complete 1.6.7 (migrations `0014`–`0016`, run from source rather than through the installer): a
1.6.6 data directory with budgets, 25 transactions, attachments, fundraisers, reminders and Entities with phone
numbers in several spellings was opened by 1.6.7. Every table kept its rows; the only changed values were the three
phone numbers that are clearly 10-digit numbers (`555-123-4567` → `5551234567`, `(555) 987-6543 x12` →
`5559876543x12`, `1.555.222.3333` → `5552223333`) — a 7-digit number and a `+44` number were left as they were;
the new columns are empty; attachments and the key are byte-for-byte identical; register balance and the audit
report are as before. 1.6.6 refuses the upgraded database and starts normally on the pre-upgrade copy.
Verified for 1.6.1: a 1.6.0 server with fundraisers was upgraded with `install.sh`: files identical, every row kept,
`0011` applied (four new empty tables); rollback started 1.6.0 on the identical data.
Verified for 1.6.0: a 1.5.0 server with data was upgraded with `install.sh` (test channel): `config.toml`, the key and
the attachment byte-for-byte identical, every row kept, `0010` applied (two new empty tables, module off). Rollback
(previous release + snapshot) started 1.5.0 on the identical data.
Verified for 1.5.0: a 1.4.1 server installation with data (users, accounts, transactions, an attachment) was
upgraded with the one-command `install.sh` from a (local) release: it chose the test pre-release, verified the
checksums, read the port from `config.toml`, snapshotted the data and ran `install-server.sh`. `config.toml`, the key
and the attachment were byte-for-byte identical, every row was kept and `0009` was applied. Rollback (previous
release + the snapshot) started 1.4.1 on the identical data.
Earlier: upgrading a 1.2.1 server with data to 1.3.0 left `config.toml`, the key and all
attachments byte-for-byte identical, kept every row, applied `0005`, labelled the existing Fiscal Year document "Other"
and reported the Audit Signoff as the only new closing requirement.
Earlier: upgrading a 1.2.0 server with data to 1.2.1 left `config.toml`, the key and all
attachments byte-for-byte identical, kept every row and existing no-attachment marks, and applied `0004`.
Earlier: upgrading a 1.1.1 server with data left `config.toml`, the encryption key and
every attachment file byte-for-byte identical, kept all rows, and the audit/entity reports, transfers and
documentation review worked on the pre-existing data.

## Steps

**One command on the server** (does steps 1–4 below; the data snapshot and rollback copy are the same):
```bash
curl -fsSL https://github.com/kretherford0983/PennyWarden/releases/latest/download/install.sh | sudo bash
```
This installs the newest production release. A specific release (for example a test pre-release on a test server):
`curl -fsSL https://github.com/kretherford0983/PennyWarden/releases/download/<tag>/install.sh | sudo bash -s -- --version <tag>`
(`<tag>` e.g. `v1.7.0` or `v1.7.0-test.3`). A release from before a rename installs under the name it had then:
1.6.6 to 1.6.8 as service `fundwarden`, before 1.6.6 as service `fmpoc`.

**From a test pre-release to the production release:** a server installed from any `v1.x.y-test.N` build upgrades
to the production release with the same command; the table above applies unchanged (a test build and the release of
the same version have the same database).
The port of the existing installation is read from `config.toml`. Then continue with *Verify*.

**Manual:**

1. Copy the new package and installer to the server (from the PennyWarden folder on your PC):
   ```powershell
   scp dist\PennyWarden-linux-x64-portable.tar.gz packaging\linux\install-server.sh you@yourserver:~/
   ```
2. (Optional) note the current version: `curl -s http://127.0.0.1:8765/api/system/status`
3. Run the installer — the same command as the first install:
   ```bash
   sudo bash install-server.sh PennyWarden-linux-x64-portable.tar.gz
   ```
   The port for the health check is read from your `config.toml` (which is never changed).
4. Expected output ends with `"version":"<new version>"` and `Installed.` and names the backup folder
   (`snapshotting data to /var/backups/pennywarden/<timestamp>`). The Cloudflare tunnel needs no change.
5. Verify: sign in, check the version under System/About (or My Account), open a Fiscal Year page and a register.
6. **Only when upgrading from a version before 1.3.0:** open each Fiscal Year that is not closed yet. Documents uploaded earlier are listed
   under *Other documents*; use the drop-down to mark the signoff as **Audit Signoff** and the budget approval as
   **Approval document** (or tick "No approval document"). Closed years are unaffected.

## Rollback

Rolling back across a database change (see the table above) requires restoring the data snapshot taken by the upgrade, because an older release
cannot open a database migrated by a newer one. **Anything entered after the upgrade is lost**, so export anything you need first.

```bash
sudo systemctl stop pennywarden
ls /opt/pennywarden/releases/ /var/backups/pennywarden/        # previous release + the snapshot taken at upgrade time
sudo ln -sfn /opt/pennywarden/releases/<previous> /opt/pennywarden/current
sudo mv /var/lib/pennywarden /var/lib/pennywarden.failed-upgrade      # keep it until you are sure
sudo cp -a /var/backups/pennywarden/<timestamp> /var/lib/pennywarden
sudo systemctl start pennywarden
```
(Verified during release testing: the previous release starts normally on the restored snapshot. Switching only the
symlink is not enough after a schema change — the older release refuses to start with "Can't locate revision".)
For 1.1.1 → 1.1.0 (no schema change) switching the symlink alone is enough.

## Notes

- The installer rewrites `/etc/systemd/system/pennywarden.service` on every run. Put any service customisations in a
  drop-in (`sudo systemctl edit pennywarden`), which is preserved. (Since 2.0.0 the installer also writes its own
  drop-in, `backup-folders.conf`, from `backup_folders`; don't edit that one — it is rewritten. Since 2.1.0
  `sudo pennywarden apply-config` writes it, from the installer and on its own.)
- Old backups in `/var/backups/pennywarden/` are not pruned automatically; remove ones you no longer need.

## Windows server

**Since 2.0.0:** run `install-windows-server.ps1` from the new release again (PowerShell as Administrator). It copies
the data folder first, installs the new version next to the old one, restarts the service and puts the previous
version back if the new one doesn't start ([install-windows-server.md](install-windows-server.md#the-installer-script-recommended)).

By hand: step by step in [install-windows-server.md](install-windows-server.md#8-upgrading) — back up, unzip the new
version into its own folder, `Stop-Service PennyWarden`, point the `C:\PennyWarden\current` junction at the new
folder, `Start-Service PennyWarden` (the database is updated at the start), check System/About. To roll back, point the
junction back and restore the backup if the database changed (see the table above).

## Windows (local install)

Data lives in `%LOCALAPPDATA%\PennyWarden` and is separate from the program folder.

1. Close the running console window (Ctrl+C) so the app is stopped.
2. Copy `%LOCALAPPDATA%\PennyWarden` somewhere safe (backup).
3. Unzip the new `PennyWarden-windows-x64.zip` into a **new** folder (keep the old one for rollback).
4. Run `PennyWarden.cmd` from the new folder. The database is migrated automatically on start.

To roll back: stop the app, restore the backed-up data folder, and run the old program folder.

## 2.1.0: after the upgrade

- **Linux server: `sudo pennywarden apply-config`** (#237). After changing `config.toml` (for example `backup_folders`),
  run this instead of the whole installer. It first checks the file without stopping anything (it must parse; backup
  folders must be absolute and outside `/home`; host, port, `trusted_proxies` and `secure_cookies` must be valid) and
  changes nothing if there is a problem. Then it writes the drop-in `backup-folders.conf`, restarts the service and
  waits until it answers on the configured Bind Address; if it doesn't, the previous drop-in is put back. `--dry-run`
  shows what it would write; `--no-restart` only writes. It never edits your own `override.conf` (`systemctl edit`),
  but tells you when that file still lists `ReadWritePaths` lines you added by hand before 2.0.0 — those can go now.
  Each run is recorded in the audit log (*Server settings applied*). The installer runs the same command, so the two
  always agree.
- **Linux server: the installer follows the Bind Address** (#236). With `host = "0.0.0.0"` (tunnel on another
  machine) its last lines list this server's network addresses; with one specific address the health check now uses
  that address (before 2.1.0 the install was reported as failed). `config.toml` is still never changed by the
  installer.

## 2.0.0: after the upgrade

- **Real names.** The first Administrator to sign in is asked for the first and last name of every account that has
  none (a stand-in is fine and can be corrected later under Users). Until then the Users list marks them *name
  needed*; nobody else is held up.
- **Linux server: the installer does two new things.** It adds the `pennywarden` command, so host commands are
  `sudo pennywarden …` from any folder. It also lets the sandboxed service write to the folders in `backup_folders`
  (a drop-in, `/etc/systemd/system/pennywarden.service.d/backup-folders.conf`, rewritten on every run). Whenever you change `backup_folders` in `config.toml`, run the installer again — **from 2.1.0:
  `sudo pennywarden apply-config`**. Folders under `/home` can't be used: the
  service can't see `/home`. An existing `config.toml` is not changed; add `backup_folders = ["/srv/…"]` yourself if you
  use scheduled backups.
- **Windows server:** from now on, upgrade an installation made by `install-windows-server.ps1` by running the script
  from the new release. An installation set up by hand keeps upgrading by hand. See *Windows server* below.
- **Nothing to configure for the Payments module.** It stays off until an Administrator turns it on (System/About →
  General → Optional modules).
- **New dependency** `pypdfium2` (draws the Payments Setup previews) is part of every package; nothing to install.
  On a Mac older than macOS 13 the previews fall back to a PDF view.

## 1.7.0: the rename to PennyWarden (server installs)

From 1.6.6 to 1.6.8 the application was called *Fundwarden* and a server install used the service `fundwarden`,
`/opt/fundwarden`, `/var/lib/fundwarden` and `/var/backups/fundwarden`. From 1.7.0 everything is called
`pennywarden`. **First rename the GitHub repository** to `PennyWarden` (Settings → General → Repository name);
GitHub forwards the old address to the new one, not the other way round, and the 1.7.0 installer downloads from
the new name. Then run the normal upgrade command — you do not prepare anything on the server. When the installer
finds a Fundwarden installation and no PennyWarden data yet, it migrates it:

1. checks that there is room for a second copy of the data (otherwise it stops before changing anything);
2. stops the `fundwarden` service and **copies** `/var/lib/fundwarden` to `/var/lib/pennywarden` (compared file by
   file before it is used), owned by the new system user `pennywarden` — `config.toml`, the key, the database and
   attachments arrive unchanged, so the port and your tunnel / reverse proxy stay as they are;
3. installs the program under `/opt/pennywarden`, creates and starts the service `pennywarden`, and disables
   `fundwarden`.

**Nothing of the old installation is changed or removed.** If PennyWarden does not come up healthy, the installer
switches back to `fundwarden` by itself and says so.

| 1.6.6 to 1.6.8 | From 1.7.0 |
|---|---|
| service and system user `fundwarden` | `pennywarden` |
| `/opt/fundwarden/current/fundwarden` | `/opt/pennywarden/current/pennywarden` |
| `/var/lib/fundwarden` (data, `config.toml`) | `/var/lib/pennywarden` |
| `/var/backups/fundwarden/<timestamp>` (snapshots) | `/var/backups/pennywarden/<timestamp>` |
| `Fundwarden-linux-x64-portable.tar.gz`, `Fundwarden-windows-x64.zip`, `Fundwarden-<version>-windows-x64.exe`, `Fundwarden-<version>-macos-arm64.dmg` | `PennyWarden-linux-x64-portable.tar.gz`, `PennyWarden-windows-x64.zip`, `PennyWarden-<version>-windows-x64.exe`, `PennyWarden-<version>-macos-arm64.dmg` |
| `%LOCALAPPDATA%\Fundwarden` (Windows), `~/Library/Application Support/Fundwarden` (Mac), `~/.local/share/fundwarden` (Linux, local) | `…\PennyWarden`, `…/PennyWarden`, `…/pennywarden` |
| backups `fundwarden-backup-….fmbak` | `pennywarden-backup-….fmbak` (older backup files restore as before) |
| `FUNDWARDEN_REPO`, `FUNDWARDEN_API`, `FUNDWARDEN_DOWNLOAD`, `FUNDWARDEN_CONFIG` (overrides for `install.sh`, rarely used) | `PENNYWARDEN_…` |
| Docker image `fundwarden`, volume `fundwarden-data` | `pennywarden`, `pennywarden-data` (see *Docker* below) |

Not renamed (internal, invisible in normal use): the database file `database/fmpoc.sqlite3`, the log file
`logs/fmpoc.log`, the `FM_*` environment variables and the `.fmbak` extension. **Two-step verification** keeps
working: the entry in each user's authenticator app keeps the label *Fundwarden* and its codes stay valid; new
set-ups are labelled *PennyWarden*.

A server that was installed before 1.6.6 and never cleaned up may still hold the stopped `fmpoc` installation as
well. The installer migrates the installation that is **in service** (normally `fundwarden`) and leaves the other
alone; both are listed in its `NOTE:` lines until you remove them.

**Going back to 1.6.8** (no database change between 1.6.8 and 1.7.0): the old installation is still complete.
```bash
sudo systemctl disable --now pennywarden && sudo systemctl enable --now fundwarden
```
It continues with the data as it was at the moment of the migration; anything entered in PennyWarden since then
stays in `/var/lib/pennywarden`. To migrate again later, move `/var/lib/pennywarden` away first and run the
installer.

Verified for 1.7.0 (simulated systemd, real packages): a 1.6.8 `fundwarden` server with a demo organization (28
tables, 267 rows, 15 attachments), a hand-edited `config.toml`, one user with two-step verification set up, and a
stopped leftover `fmpoc` data directory was upgraded with `install-server.sh`: `config.toml`, the key and every
attachment byte-for-byte identical in `/var/lib/pennywarden`, every table identical, 1.7.0 answering on the same
port, `fundwarden` stopped and disabled, the `fmpoc` leftover ignored; the user signed in with a code from the
authenticator set up on 1.6.8. The switch back started 1.6.8 on its data and the switch forward 1.7.0 again. With
PennyWarden data present and `fundwarden` running the installer refused and changed nothing. A package that does
not start made the installer return to `fundwarden` by itself, its files and tables identical before and after. A
second run was a normal upgrade with a snapshot in `/var/backups/pennywarden`; after the cleanup below 1.7.0 kept
running on identical data and the `NOTE:` lines were gone; a fresh install on an empty machine used the new names.

### Cleanup after the rename to PennyWarden

Do this on each migrated server **once you are sure you will not go back** — for example after a few days of
normal use and one fresh backup (System/About → Backups → Backup / Restore) stored off the server. Until then the leftovers
only cost disk space. The installer reminds you with a `NOTE:` line as long as they exist.

```bash
# 0. PennyWarden is the one that is running, and the old service is not
systemctl is-active pennywarden           # must print: active
systemctl is-active fundwarden            # must print: inactive
curl -s http://127.0.0.1:<port>/api/system/status      # "version":"1.7.0" (or later) and your organization's name

# 1. optional: one last archive of the old data, kept somewhere safe (it contains the encryption key)
sudo tar -C /var/lib -czf /root/fundwarden-final-data.tar.gz fundwarden

# 2. remove the old service
sudo systemctl disable --now fundwarden
sudo rm -f /etc/systemd/system/fundwarden.service
sudo rm -rf /etc/systemd/system/fundwarden.service.d   # only exists if you made a drop-in with "systemctl edit fundwarden"
sudo systemctl daemon-reload

# 3. remove the old program, data and snapshots
sudo rm -rf /opt/fundwarden /var/lib/fundwarden /var/backups/fundwarden

# 4. remove the old system user
sudo userdel fundwarden

# 5. check
systemctl is-active pennywarden           # still: active
ls -d /opt/fundwarden /var/lib/fundwarden /var/backups/fundwarden 2>&1    # "No such file or directory" three times
```

Also check, because the installer cannot know about them:
- a **drop-in** you created for the old service (`/etc/systemd/system/fundwarden.service.d/`): recreate what you
  still need with `sudo systemctl edit pennywarden` before deleting it;
- your own **backup jobs, cron entries or monitoring** that mention `fundwarden`, `/var/lib/fundwarden` or
  `/var/backups/fundwarden`: point them at the new names;
- **downloaded installers** in home directories (`install-server.sh`, `Fundwarden-*.tar.gz`) and
  `/var/lib/pennywarden.failed-migration-*` (only present if a migration attempt failed): delete them;
- a bookmark or script with the old `…/kretherford0983/Fundwarden/…` download address keeps working (GitHub
  forwards it), but update it when convenient;
- the Cloudflare tunnel / reverse proxy needs **no** change (same address and port).

### Windows, Mac and Linux PCs (local installs)

Nothing needs cleaning up: at its first start 1.7.0 renames the data folder (`%LOCALAPPDATA%\Fundwarden` →
`%LOCALAPPDATA%\PennyWarden`; on a Mac `~/Library/Application Support/Fundwarden` → `…/PennyWarden`; on Linux
`~/.local/share/fundwarden` → `…/pennywarden`). It is a rename in place — nothing is copied; a data folder you
chose yourself with `--data-dir` or `FM_DATA_DIR` is never touched. Delete the old `Fundwarden-…exe`, the
`Fundwarden-windows-x64` folder or `Fundwarden.app` when you no longer want it. To go back to 1.6.8, close
PennyWarden and rename the folder back first. On a Mac, PennyWarden is a new app to macOS, so the *Open Anyway*
step in *Read me first* is needed once more.

### Docker

A container keeps its data in a named volume, which the installer does not touch. To keep the data under the new
names, copy the volume once while the container is stopped, then start the new image on the copy:
```bash
docker compose down                                   # or: docker stop <container>
docker volume create pennywarden-data
docker run --rm -v fundwarden-data:/from -v pennywarden-data:/to alpine sh -c "cp -a /from/. /to/"
# build / pull the 1.7.0 image as "pennywarden", start it with  -v pennywarden-data:/data
```
The old volume `fundwarden-data` is left as it is — that is the way back (start the 1.6.8 image on it). Remove it
with `docker volume rm fundwarden-data` when you no longer need it. Keeping the old volume name also works: the
name of a volume has no meaning to the application.

## 1.6.6: the rename to Fundwarden (server installs)

Up to 1.6.5 the application was called *Financial Management POC* / *Freedger* and a server install used the service
`fmpoc`, `/opt/fmpoc`, `/var/lib/fmpoc` and `/var/backups/fmpoc`. From 1.6.6 everything is called `fundwarden`.
You do not prepare anything: run the normal upgrade command. When the installer finds an old installation and no
Fundwarden data yet, it migrates it:

1. checks that there is room for a second copy of the data (otherwise it stops before changing anything);
2. stops the `fmpoc` service and **copies** `/var/lib/fmpoc` to `/var/lib/fundwarden` (compared file by file before
   it is used), owned by the new system user `fundwarden` — `config.toml`, the key, the database and attachments
   arrive unchanged, so the port and your tunnel / reverse proxy stay as they are;
3. installs the program under `/opt/fundwarden`, creates and starts the service `fundwarden`, and disables `fmpoc`.

**Nothing of the old installation is changed or removed.** If Fundwarden does not come up healthy, the installer
switches back to `fmpoc` by itself and says so.

| Before 1.6.6 | From 1.6.6 |
|---|---|
| service and system user `fmpoc` | `fundwarden` |
| `/opt/fmpoc/current/FinancialManagementPOC` | `/opt/fundwarden/current/fundwarden` |
| `/var/lib/fmpoc` (data, `config.toml`) | `/var/lib/fundwarden` |
| `/var/backups/fmpoc/<timestamp>` (snapshots) | `/var/backups/fundwarden/<timestamp>` |
| `FinancialManagementPOC-linux-x64-portable.tar.gz`, `FinancialManagementPOC-windows-x64.zip`, `Freedger-<version>-windows-x64.exe` | `Fundwarden-linux-x64-portable.tar.gz`, `Fundwarden-windows-x64.zip`, `Fundwarden-<version>-windows-x64.exe` |
| `%LOCALAPPDATA%\FinancialManagementPOC` (Windows, local) | `%LOCALAPPDATA%\Fundwarden` |
| backups `freedger-backup-….fmbak` | `fundwarden-backup-….fmbak` (older backup files restore as before) |

Not renamed (internal, invisible in normal use): the database file `database/fmpoc.sqlite3`, the log file
`logs/fmpoc.log`, the `FM_*` environment variables and the `.fmbak` extension.

**Going back to 1.6.5** (no database change between 1.6.5 and 1.6.6): the old installation is still complete.
```bash
sudo systemctl disable --now fundwarden && sudo systemctl enable --now fmpoc
```
It continues with the data as it was at the moment of the migration; anything entered in Fundwarden since then
stays in `/var/lib/fundwarden`. To migrate again later, move `/var/lib/fundwarden` away first and run the installer.

Verified for 1.6.6 (simulated systemd): a 1.6.5 `fmpoc` server with data was upgraded with `install.sh`: every table
row, every attachment, the key and a hand-edited `config.toml` identical in `/var/lib/fundwarden`; `/var/lib/fmpoc`
byte-for-byte untouched; 1.6.6 answered on the same port. The switch back started 1.6.5 on its data; a package that
does not start made the installer return to `fmpoc` automatically; after the cleanup below 1.6.6 kept running on
identical data and a further upgrade took its snapshot in `/var/backups/fundwarden`.

### Cleanup after the rename

Do this on each migrated server (dev, test, later any other) **once you are sure you will not go back** — for
example after a few days of normal use and one fresh backup (System/About → Backups → Backup / Restore) stored off the server.
Until then the leftovers only cost disk space. The installer reminds you with a `NOTE:` line as long as they exist.

```bash
# 0. Fundwarden is the one that is running, and the old service is not
systemctl is-active fundwarden            # must print: active
systemctl is-active fmpoc                 # must print: inactive
curl -s http://127.0.0.1:<port>/api/system/status      # "version":"1.6.6" (or later) and your organization's name

# 1. optional: one last archive of the old data, kept somewhere safe (it contains the encryption key)
sudo tar -C /var/lib -czf /root/fmpoc-final-data.tar.gz fmpoc

# 2. remove the old service
sudo systemctl disable --now fmpoc
sudo rm -f /etc/systemd/system/fmpoc.service
sudo rm -rf /etc/systemd/system/fmpoc.service.d      # only exists if you made a drop-in with "systemctl edit fmpoc"
sudo systemctl daemon-reload

# 3. remove the old program, data and snapshots
sudo rm -rf /opt/fmpoc /var/lib/fmpoc /var/backups/fmpoc

# 4. remove the old system user
sudo userdel fmpoc

# 5. check
systemctl is-active fundwarden            # still: active
ls -d /opt/fmpoc /var/lib/fmpoc /var/backups/fmpoc 2>&1    # "No such file or directory" three times
```

Also check, because the installer cannot know about them:
- a **drop-in** you created for the old service (`/etc/systemd/system/fmpoc.service.d/`): recreate what you still
  need with `sudo systemctl edit fundwarden` before deleting it;
- your own **backup jobs, cron entries or monitoring** that mention `fmpoc`, `/var/lib/fmpoc` or
  `/var/backups/fmpoc`: point them at the new names;
- **downloaded installers** in home directories (`install-server.sh`, `FinancialManagementPOC-*.tar.gz`) and
  `/var/lib/fundwarden.failed-migration-*` (only present if a migration attempt failed): delete them;
- the Cloudflare tunnel / reverse proxy needs **no** change (same address and port).

On a **Windows** PC nothing needs cleaning up: at its first start 1.6.6 renames the data folder
`%LOCALAPPDATA%\FinancialManagementPOC` to `%LOCALAPPDATA%\Fundwarden` (a rename in place — nothing is copied; a
data folder you chose yourself with `--data-dir` or `FM_DATA_DIR` is never touched). Delete the old
`Freedger-…exe` / `FinancialManagementPOC-windows-x64` folder when you no longer want it. To go back to 1.6.5 on
Windows, rename the folder back first.

## 1.4.1: two-step verification after the upgrade (server installs)

Sessions that were open before the upgrade keep working until they end. At the **next sign-in every user** is asked to
set up an authenticator app (QR code or typed key) and to save 10 recovery codes. Do it yourself first as the
Administrator, with your phone at hand.

If a user loses both the phone and the recovery codes: Users → the user's **⋯** menu → **Reset two-step** (Administrator,
reason required).
If the only Administrator is locked out, on the server:

```
sudo pennywarden reset-mfa --user <username> --data-dir /var/lib/pennywarden
```

(since 2.0.0; files it writes are handed back to the service account afterwards. On an older installation without the
`pennywarden` command: `sudo -u pennywarden /opt/pennywarden/current/pennywarden reset-mfa --user <username> --data-dir /var/lib/pennywarden`). The reset is
recorded in the audit log; the user sets up two-step verification again at the next sign-in.
