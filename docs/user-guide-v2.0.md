# What's new in 2.0 — quick guide

*2.0.0: the Payments module (check printing, payments, cover letters and envelopes). 2.0.0 is tested in several test builds; this guide grows with each one. The full
guide is [check-printing.md](check-printing.md).*

## Check printing (test build 1)
PennyWarden can now print your checks on printable check stock that already carries the bank numbers.

**Administrators** turn it on in **System/About → General → Optional modules → Payments module**, then open **Payments Setup** to:
- create a **check style** from a preset (the first preset is a Letter sheet with three 3.5-inch checks) and adjust
  where each field prints, with a preview drawn to scale;
- choose fonts, how the amounts look, and a **default memo** such as `{BUDGET_CODE}, INVOICE {INVOICE}`;
- add **signers** with a signature image, and optionally an amount above which no signature prints;
- print a **test print** and a **calibration page** on plain paper.

**Register Users** open a withdrawal in the **Register** and click **Print check…**:
- check the preview, the feed mode (the last check on a sheet goes through the manual feed on its own) and the memo;
- type the number printed on the check in the printer, then print at **actual size**;
- afterwards choose **Yes – done**, **Reprint** (the check was not damaged) or **Mark spoiled** (its number becomes a
  $0.00 VOID record and you print on the next check).

A record copy of every printed check is attached to the transaction. If the printing is shifted on your printer, the
**Printer setup assistant** on the print screen adjusts it for you without changing anyone else's settings.

## Payments (test build 2)
**Payments** in the menu (Register Users) enters a bill and prints its check in one go: pay from (your last account is
remembered), date, payee (or a new one), one line per invoice with its documents — the check amount is shown in words
as you type. **Save and print check** records it in the register and opens the print screen. **Create payment…** on a
withdrawal already in the register shows its details locked and prints its check.

## Cover letters and envelopes (test build 3)
Administrators keep **cover letter** and **#10 envelope** templates in Payments Setup (letterhead, text with
`{VARIABLES}`, the invoice table; envelope return address and feeding). After a check prints, the print screen offers
the letter and the envelope; they are attached to the transaction. For a check written by hand, choose **I'm writing
the check by hand**, record its number (typed twice), and print the letter and envelope. Withdrawal lines can carry an
optional **invoice date**. Details: [Check printing](check-printing.md#cover-letters-and-envelopes).

## Voucher checks and two signatures (test build 4)
Administrators can create a **voucher check** style (one check per sheet with a vendor-copy and an office-copy stub
listing the invoices paid, the total and the check number) and give any style **two signature lines**. Register Users
then choose two different signers when printing; above an optional amount only the first signature prints. Details:
[Check printing](check-printing.md#10-voucher-checks-check-with-stubs).

## Polish from testing (test build 5)
- **Test prints** have no outline or page markings any more — only the **calibration page** draws the check's edges —
  and one TEST – NOT A CHECK watermark (plus a small one across each signature line with a test signature).
- The **cover letter** and **envelope** editors show a live **preview** with sample data as you type, and their
  sections can be collapsed. The **check style** preview draws a voucher check's **stubs** under the check.
- **My account** and **System/About** show when your version was built in **local time** (hover for UTC).

## Letter logo, window envelopes and administration (test build 6)
- A **cover letter** can carry your **logo** (top left or centered), be printed on **pre-printed letterhead paper**
  (the top of the page stays blank), and carry the addresses for a **#10 double-window envelope** — at the top of the
  letter or on a separate address page. Details: [Check printing](check-printing.md#cover-letters-and-envelopes).
- **System/About** has new sections for Administrators: rename the **organization**, a **backup reminder** (a warning
  after a set number of days without a backup), and **Settings** — every setting in effect and where it comes from;
  on a server, the security and session settings can be changed there (they take effect after a restart). Auditors
  can see the settings too. Details: [Configuration](configuration.md#changing-settings-in-the-application-200-126).
- **Signed-in sessions** on System/About: who is signed in, since when and from which address. An Administrator can
  end a session (for example a forgotten sign-in on a shared computer) or end all other sessions.
- **Download diagnostics** on System/About gives an Administrator a file to share when asking for help. It holds no
  financial data, passwords or keys.
- **Health** on System/About: database and attachment sizes, free disk space and an integrity check; a warning
  appears for Administrators when the disk is nearly full.

## Maintenance mode (test build 7)
- An Administrator can switch on **maintenance mode** on System/About with a message for everyone, now or at a set
  time (for example during the year-end close or before an upgrade). Everyone can still sign in and look things up;
  only Administrators can change anything until it is turned off.
- **Backups the server can recover:** a backup made with *Let this server recover the passphrase* (the default) can
  be restored by the server's owner even if its passphrase is forgotten — from the server's command line, on that
  server only. **`pennywarden restore`** restores a backup from the command line ([Backup and
  restore](backup-restore.md)).
- After a restore, **Reports → Restore re-entry reports** lists what was entered or changed after the backup, so it
  can be entered again.
- **Reinitialize** (System/About → Advanced → Reinitialize): start again with no financial data but the same users, after a safety
  backup the server can always restore ([Backup and restore](backup-restore.md#reinitialize-keeping-the-users-since-200)).
- **Windows server:** the [Windows server guide](install-windows-server.md) now covers everything from the download
  to HTTPS, a Windows service, backups, upgrades and troubleshooting.

## Real names, readable audit log, security overview (test build 8)
- Every user has a **first and last name** (Administrators set them under Users). The Users list can be searched and
  sorted by last name, and the audit log shows people as *First Last - username*. After the upgrade, the first
  Administrator to sign in is asked for the names of the existing accounts.
- The **Audit Log** reads in plain words: each entry says who did what to which record, *Details* shows what changed
  (with readable names and amounts), and the raw data is still there under *Show technical details*.
- **Security overview** on System/About (Administrators and Auditors): HTTPS, two-step verification, the last backup,
  locked accounts and the security settings at a glance, with what needs attention marked and what to do about it.

## Windows server installer (test build 10)
On a Windows server, `install-windows-server.ps1` from the release installs or upgrades PennyWarden as a service in
one step, with HTTPS through Caddy (`-Domain`) or behind your Cloudflare Tunnel. Details:
[Windows server guide](install-windows-server.md#the-installer-script-recommended).

## Payments Setup polish (test build 11)
- Keep **several cover letters and envelopes**: a new one is numbered (*Invoice payment letter 2*) and opens with its
  name ready to type over, and **Duplicate** copies one with all its settings.
- **Window envelopes** are set up on a cover letter (**New window-envelope letter**); the Envelopes section points
  there.
- The letter and envelope **previews** are pictures of the printed page and show in every browser, Safari included.
  Details: [Check printing](check-printing.md#cover-letters-and-envelopes).
- **Tidier screens:** form fields, dropdowns and buttons line up; tables show **Edit** and a **⋯** menu with the other
  actions of the row; **System/About** is split into tabs (About, General, Settings, Backups, Security, System health,
  Advanced), each with its own address you can bookmark.

## Audit log export (test build 12)
On the **Audit Log**, set the filters (for example the Fiscal Year's dates), then **Export CSV** for a spreadsheet or
**Printable PDF** to print or keep. Both hold every matching entry — not only the page on screen — with the same
summaries and *What changed* details, times in your time zone. Administrators' exports leave out financial content,
as the screen does. Each export is itself recorded in the audit log.
