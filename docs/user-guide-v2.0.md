# What's new in 2.0 — quick guide

*2.0.0: the optional Payments module (check printing, payments, cover letters and envelopes), and new tools for the
people who run PennyWarden: System/About in tabs, maintenance mode, server-side restore and reinitialize, a security
overview, and a readable audit log you can export. The full Payments guide is [check-printing.md](check-printing.md).*

## Print checks (Payments module)
PennyWarden can print your checks on printable check stock that already carries the bank numbers: the date, payee,
amount in numbers and in words, memo and signature — never the check number or bank numbers.

**Administrators** turn it on in **System/About → General → Optional modules → Payments module**, then open
**Payments Setup** to:
- create a **check style** from a preset — **3 per page** laser checks, or a **voucher check** with a vendor stub and
  an office stub — and adjust where each field prints, with a preview drawn to scale;
- choose fonts, how the amounts look and a **default memo** such as `{BUDGET_CODE}, INVOICE {INVOICE}`;
- add **signers** with a signature image (stored encrypted); a style can have **two signature lines**, and amounts
  above which a signature is left off for signing by hand;
- print a **test print** and a **calibration page** on plain paper.

**Register Users** pay bills and print checks:
- **Payments → New payment** enters a bill once — pay from, date, payee (or a new one), one line per invoice with its
  documents and invoice date — shows the amount in words as you type, records it in the register and opens the print
  screen. A withdrawal already in the register is paid with **Create payment…** in its details.
- **Create payment…** on a withdrawal (**Reprint check…** once printed): check the preview and the feed mode, type the number printed on the check in the
  printer, print at **actual size**. Afterwards choose **Yes – done**, **Reprint** (not damaged) or **Mark spoiled**
  (its number becomes a $0.00 VOID record and you print on the next check).
- For a check you write by hand, choose **I'm writing the check by hand** and record its number (typed twice).
- A record copy of every printed check is attached to the transaction. If printing is shifted on your printer, the
  **Printer setup assistant** on the print screen adjusts it for you only.

Details: [Check printing](check-printing.md).

## Cover letters and envelopes
Administrators keep **cover letter** and **#10 envelope** templates in Payments Setup — as many as you need (for
example invoices, a refund, a donation). A letter lists the invoices paid, can carry your **logo** or be printed on
**pre-printed letterhead paper**, and can carry the addresses for a **#10 double-window envelope** (**New
window-envelope letter**). Each editor shows a live preview of the printed page as you type. A new letter or envelope —
or a copy made with **Duplicate** — is only kept once you click **Save**.

After a check prints, the print screen offers the letter and the envelope; both are attached to the transaction.
Details: [Check printing](check-printing.md#cover-letters-and-envelopes).

## System/About, for Administrators
System/About now has tabs, each with its own address you can bookmark:

- **About** — version, licence, the update check.
- **General** — rename the **organization**; turn the optional modules on or off.
- **Settings** — every setting in effect and where it comes from; on a server, the security and session settings can
  be changed here (they take effect after a restart). Details:
  [Configuration](configuration.md#changing-settings-in-the-application-200-126).
- **Backups** — Backup / Restore, scheduled backups, and the **backup reminder** (a warning after a set number of
  days without a backup).
- **Security** — the **security overview** (HTTPS, two-step verification, the last backup, locked accounts — with
  what needs attention) and the **signed-in sessions**, where you can end a forgotten sign-in or everyone else's.
- **System health** — sizes, free disk space, a database integrity check, and **Download diagnostics** to share when
  asking for help (it holds no financial data, passwords or keys).
- **Advanced** — **maintenance mode** and **Reinitialize** (below).

Auditors see About, Settings and Security.

## Maintenance mode and reinitialize
- **Maintenance mode** (System/About → Advanced): an Administrator sets a message, now or at a set time. Everyone can
  still sign in and look things up — reports and exports included — but only Administrators can change anything; the
  others see the screens without any change buttons. The message shows on the sign-in page and at the top of every
  page.
- **Reinitialize** (System/About → Advanced → Reinitialize): start again with no financial data but the same users,
  after a safety backup that the server's owner can always restore. The page shows the exact command to undo it.
  Details: [Backup and restore](backup-restore.md#reinitialize-keeping-the-users-since-200).

## Backups the server can recover
- A backup made with **Let this server recover the passphrase** (the default) can be restored by the server's owner
  even if its passphrase is forgotten — from the server's command line, on that server only. Restoring from the web
  page always asks for the passphrase.
- **`sudo pennywarden restore`** restores a backup from a Linux server's command line;
  **`sudo pennywarden restore --list`** shows the backups it can recover, with their full paths. On a Windows server:
  `C:\PennyWarden\current\PennyWarden.cmd restore …` as Administrator. Details: [Backup and restore](backup-restore.md).
- After a restore, **Reports → Restore re-entry reports** lists what was entered or changed after the backup, so it
  can be entered again.

## Users and the audit log
- Every user has a **first and last name** (Administrators set them under Users). After the upgrade, the first
  Administrator to sign in is asked for the names of the existing accounts. The Users list can be searched and sorted
  by last name.
- The **Audit Log** reads in plain words: each entry says who did what to which record; **Details** shows what
  changed, with readable names and amounts.
- **Export CSV** and **Printable PDF** on the Audit Log hold every entry matching your filters, for an audit review.
  Administrators' exports leave out financial content, as the screen does.

## Easier to use
- Form fields, dropdowns and buttons line up on every screen.
- Tables show **Edit** and a **⋯** menu with the row's other actions (reset a password, make an account primary,
  deactivate, duplicate …).
- My account and System/About show when your version was built, in your time zone.

## Running a server
- **Windows server:** `install-windows-server.ps1` from the release installs or upgrades PennyWarden as a Windows
  service in one step, with HTTPS through Caddy (`-Domain`) or behind your Cloudflare Tunnel. Details:
  [Windows server guide](install-windows-server.md#the-installer-script-recommended).
- **Linux server:** the installer now adds the `pennywarden` command for the host commands (`sudo pennywarden …`)
  and lets the service write to your scheduled-backup folders — list them in `config.toml`
  (`backup_folders = ["/srv/pennywarden-backups"]`) and run the installer again after changing the list. Details:
  [Upgrading](upgrade.md#200-after-the-upgrade).
