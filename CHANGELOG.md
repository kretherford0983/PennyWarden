# Changelog

Versions are `Breaking.Major.Minor` from 1.6.0 (docs/branching.md).

## 2.1.0 — unreleased
PennyWarden 2.1.0 (in progress).

### Register
- **Sort by Date or Cleared.** Click the *Date* or *Cleared* heading to sort by it; click again for newest first. Each
  user's choice is remembered (in any browser). Sorted by *Cleared*, uncleared transactions come last (first when
  newest first) and the balance column shows the **bank (cleared) balance** after each cleared item — the figure on
  your bank statement. *Reset to default* goes back to Date, oldest first. (#262)
- **Attachments filter: All / Yes / Missing / Marked.** *Missing* lists exactly what the Fiscal Year documentation
  review warns about — no attachment, or "no attachment will be provided" without a reason — so a transaction such as
  bank interest marked with a reason no longer shows up. *Marked* lists everything marked "no attachment will be
  provided". Old links with *No* open *Missing*. (#258)
- **Electronic payments.** Tick *Electronic payment* on a withdrawal paid by ACH / bill pay, debit card, wire or an
  online portal, so it is clear why there is no check. An optional number is either a check number from your own
  sequence (counted in the missing-check review) or the bank's or vendor's reference (never in the check sequence).
  The register shows an *Electronic* badge and a *Payment* filter; the Audit and Close reports show *Electronic
  (method)* where the check number would be. In the Payments module an electronic payment is recorded without
  printing a check (a cover letter and envelope stay optional). (#260)
- **Reorder attachments.** *Reorder…* on a transaction's, an allocation's, a fundraiser's or a Fiscal Year's other
  documents sets the order they are shown and printed in the Audit, Close and fundraiser reports — for example
  invoice, receipt, approval email. New files go to the end; a closed Fiscal Year can't be reordered. (#259)

### Budget planning (Budget Managers)
- **Budget Prep report** (Reports → Budget Prep). Every budget of a Fiscal Year with its history over earlier years —
  budgeted, actual and the difference in dollars and percent, marked *over* or *under* — following the budget
  continuation links, so a renumbered budget stays on one line. Choose how many earlier years to show (or all). The
  current year shows the actual **year-to-date**, dated. Optional columns:
  - **Projected** — the average monthly activity so far carried to the Fiscal Year end. Untick a budget known to be
    complete (a finished fundraiser, say); it then shows *Complete: no projection*. Budgets of fundraisers that have
    ended start unticked, and your choices are remembered for the year.
  - **Next year** — the next Fiscal Year's budget that continues each one, with the change.

  It can be limited to one parent budget or one budget (with a chart of budgeted and actual per year). On screen, as a
  landscape PDF, or CSV. (#257)
- **Fiscal Year Planning Sheet** (Fiscal Year screen → *Planning sheet…*). A portrait form for the budget meeting:
  - this year's Income and Expense budgets with the previous budgeted amount, the actual year-to-date and the
    projection, and a blank *Proposed Budget* column;
  - blank rows, and a second page of blank tables, for new budgets;
  - lines for the new Fiscal Year, the attendees and the meeting date.

  When a Draft next Fiscal Year exists, its name and dates are filled in. The draft amounts appear as *Proposed*,
  with a blank *Proposed Revision* column; new draft budgets are listed, and budgets not carried into the draft are
  marked *not in draft*. The scanned sheet can be attached to the new Fiscal Year; it is not a required document.
  (#261)

### Fundraisers
- **Stakeholder report.** *Report…* on a fundraiser's page now produces a clean **Financial & Proceeds Statement** for
  the committee and stakeholders, as a **PDF or an editable Word document**:
  - three headline figures (net revenue, expenses, net proceeds with the net margin) and a financial summary from
    gross deposits to net proceeds;
  - revenue and expense breakdowns by category and bucket, with *Other (not in a bucket)* so they add up, itemized
    revenue, charge-less-credit detail and a net-by-category table;
  - key takeaways worked out from the figures and optional summary notes.

  Options: summary only (no itemized revenue), hide contributor names ("Contributor 1, 2…") for reports that go
  outside the organization, and a plain line list for a fundraiser without buckets. It has no transaction numbers,
  accounts, budgets or attachments. Budget Managers can write the **summary notes** and **Mark results final**; the
  report reads *Interim*, *Post-event*, *Final* or *Cancelled*. The previous detailed report (lines, excluded lines,
  documents and attachments) is now **Reports → Fundraiser detail (audit)**. (#275)
- **Bucket categories.** Group a fundraiser's buckets under optional categories (for example *Sponsorships*,
  *Registrations*, *Day-of event*), one category per bucket or none. The Buckets table shows each category with its
  buckets beneath and a subtotal of income, expenses and net, and so does the fundraiser section of the Audit and
  Close reports. Deleting a category leaves its buckets uncategorized; no figure changes. A bucket can still hold both
  income and expenses (*Food Sales* with its sales and its supplies). (#278)
- **Reorder categories and buckets** with *Reorder…*. The order is used on the page and in the reports. Existing
  buckets keep their alphabetical order until reordered; new ones go to the end. Categories and order are presentation
  only, so they can be changed in a closed Fiscal Year too. (#278)
- **Charge less a credit.** When assigning part of a line to a bucket, tick *Charge less a credit* to record the full
  charge, the amount taken off and why — a $1,500 venue invoice less a $500 pre-paid team credit, or a $200 sponsorship
  less a $6 card fee. The net (charge − less) is what counts, so every total still matches the register; the charge
  and the credit show as detail on the line and in the reports. A fully credited item (net $0) is allowed. (#278)

### For whoever runs the server

- **`sudo pennywarden apply-config`** applies `config.toml` on a Linux server without running the whole installer:
  after changing `backup_folders` (or another setting), it checks the file first and changes nothing if there is a
  problem, lets the service write to the listed backup folders, restarts the service and waits until it answers —
  putting the previous settings back if it doesn't. `--dry-run` shows what it would do. Recorded in the audit log. The
  installer uses the same command, and now checks `config.toml` before it stops anything. (#237)
- **The Linux installer follows the Bind Address.** With `host = "0.0.0.0"` (tunnel or proxy on another machine) its
  last lines list the server's network addresses to point the tunnel at; with one specific address the install no
  longer fails its health check. (#236)
### Behind the scenes
- **Release dates are set by the pipeline.** The release is dated when it is published (GitHub, pennywarden.org,
  *What's new*); `CHANGELOG.md` gets the date with the next version's first change. No extra round before each
  release. README links to the latest release instead of naming a version. (#240)
- **New dependency:** `python-docx` (MIT, with `lxml`, BSD) writes the Word version of the fundraiser report; it is in THIRD-PARTY-NOTICES and every package. (#275)
- **Python dependencies are compiled with pip-tools** (`backend/requirements.in` → `requirements.txt`, same versions as
  2.0.0), so automatic dependency updates move related packages together. (#226)

## 2.0.0 — 2026-10-15
PennyWarden 2.0.0 adds the optional **Payments module** — print checks, cover letters and envelopes from the
register — and a large set of tools for whoever runs the server: a tidier System/About in tabs, maintenance mode,
server-side restore and reinitialize, a security overview, a readable and exportable audit log, and an installer for
Windows servers.

**Upgrading from 1.10.0.** The database is updated automatically (migrations `0025` to `0034`: columns and tables
added, no existing data changed). Going back to 1.10.0 needs the data snapshot the installer takes before upgrading
(docs/upgrade.md). After the upgrade, the first Administrator to sign in is asked for the first and last name of every
account. On a Linux server, run the installer as usual: it now also adds the `pennywarden` command and lets the service
write to your scheduled-backup folders.

### Payments module (optional)
- **Turn it on** in System/About → General → Optional modules. Administrators set it up in **Payments Setup**;
  Register Users get **Payments** in the menu and **Create payment…** on withdrawals in the register. Budget Managers have no access
  (docs/check-printing.md). (#60)
- **Prints on blank check stock that already carries the bank numbers:** the date, payee, the amount in numbers and
  in words (bank style, with a protective fill), the memo and the signature — never the check number or the bank
  numbers. Built-in fonts only, embedded in every PDF; text that doesn't fit is shrunk or must be shortened by you,
  never cut off silently. (#157)
- **Check styles** are made from a preset and fine-tuned with a live preview drawn to scale: **3 per page – standard
  laser** (print the top check, tear it off, feed the last one like an envelope) and **Voucher – check on top, two
  stubs** (a vendor stub and an office stub with the payment's lines and the check number). Every field's position can
  be moved; nothing can be placed in the bank-number zone. Each bank account remembers its style. (#156, #167)
- **Signers and signatures.** Signature images are stored encrypted, can't be downloaded, print only on real checks
  (and the Administrator's test prints), and every use is audited. A style can have **two signature lines**, and
  amounts above which one or both signatures are left off for a hand signature. (#159, #167)
- **Memo patterns** with `{VARIABLES}` from the transaction, with autocomplete after `{`; an Administrator sets the
  default and users can change it for one print. (#160)
- **Payments.** **New payment** enters a bill once — pay from, check date, payee (or a new vendor), one line per
  invoice with its budget, invoice number and date, description, amount and documents — shows the check amount in
  words as it will print, and records it in the register. **Create payment…** on an existing withdrawal does the same
  from the register. The Payments page lists the checks printed from each account. (#164)
- **Printing a check.** You type the number printed on the loaded check before every print. **Reprint** needs a
  reason; **Mark spoiled** records the number as a $0.00 VOID record and moves the payment to the next check. A record
  copy (marked COPY – NOT NEGOTIABLE, never with the signature image) is attached to the transaction. For a check
  written by hand, **I'm writing the check by hand** records its number (typed twice) without printing. In the
  register a withdrawal shows **Create payment…**, and once its check is printed **Reprint check or letter…**, where
  the check, or only a damaged letter or envelope, can be printed again. (#161, #165, #230)
- **Works without printer setup:** Letter pages by default, instructions for your browser, a plain-paper test of the
  actual check, and a printer setup assistant that saves each user's own small adjustment without changing the
  Administrator's layout. Test prints say TEST – NOT A CHECK and carry a 5-inch line to check the print scale. (#158,
  #162, #183)
- **Safari:** it can't show a PDF inside the page, so the print screens show a picture of the check, letter or
  envelope instead, and **Print…** opens the PDF in a new tab to print it there. (#230)
- **Cover letters** list the invoices paid and print with the check (or on their own): letterhead lines or a **logo**,
  or **pre-printed letterhead paper**; subject, greeting, an invoice table with the columns you choose and a total,
  closing; signed by name by the check's signer. Keep **as many letters as you need** (for invoices, a refund, a
  donation …); the letter is chosen for each payment. A letter can carry the addresses for a **#10 double-window
  envelope**, on the letter itself or on an address page, with a test print that shows the windows and folds.
  (#165, #176, #177, #217)
- **#10 envelopes** with the payee's address from the entity, an optional return address, and the manual feed set up
  for your printer. Printed letters and envelopes are attached to the transaction. (#166)
- **Payments Setup.** Every editor shows a live preview of what prints, with sample data, as you type — a picture of
  the printed page, so it works in every browser. New letters, envelopes and copies (**Duplicate**) are drafts until
  you save them; going back without saving keeps nothing. Sections can be collapsed and the preview kept at the top.
  (#174, #186, #217)
- **Invoice date.** Each line of a withdrawal can have an invoice date; it can be used in memos, letters and voucher
  stubs.

### System/About and running the server
- **System/About is in tabs** — About, General, Settings, Backups, Security, System health and Advanced — each with its
  own address you can bookmark. Auditors see About, Settings and Security. (#216)
- **Settings.** Every setting in effect and where it comes from. On a server an Administrator can change the proxy,
  cookie, HSTS, session, sign-in lock and log settings there (saved to `config.toml`, the old file kept; in effect
  after a restart; every change audited). (#126)
- **Rename the organization** (General). New reports, letters and backups use the new name. (#126)
- **Signed-in sessions** (Security): who is signed in, since when and from where; an Administrator can end one
  session, all of a user's, or everyone else's. (#127)
- **Security overview** (Security): HTTPS, two-step verification by role, the last backup, locked accounts and the
  security settings at a glance, with what needs attention and what to do about it. It only reports. (#131)
- **System health:** database and attachment sizes, free disk space, a database integrity check, and **Download
  diagnostics** for support (passwords, keys, amounts, account numbers and email addresses left out). Administrators
  see a warning on every page when disk space runs low. (#128, #129)
- **Maintenance mode** (Advanced): with a message, now or at a set time. Everyone can sign in and look things up —
  including reports and exports — but only Administrators can change anything; the others see the screens without
  any change actions. The message shows on the sign-in page and at the top of every page. (#130)
- **Reinitialize** (Advanced): start again with no financial data but the same users, roles and settings — after a
  checked safety backup that the server's owner can always restore. Confirmed with the word reinitialize, your
  password and two-step code; everyone sees a notice until an Administrator acknowledges it. (#125)

### Backup and restore
- **Backups the server can recover.** **Let this server recover the passphrase** (on by default) lets the server's
  owner restore that exact backup even if its passphrase is forgotten — only from the server's command line; restoring
  from the web always asks for the passphrase. (#124)
- **Restore from the command line:** `sudo pennywarden restore FILE` (passphrase prompt, passphrase file or
  `--use-server-key`); it stops and restarts the service when you say so and works on a new, empty installation.
  `sudo pennywarden restore --list` lists the backups the server can recover, with their full paths. (#124)
- **Re-entry report.** Every restore lists what was entered or changed after the backup, so it can be entered again;
  financial roles download it under Reports. (#124)
- **Backup reminder:** Administrators are warned when no backup has been made for 7 days (adjustable; 0 turns it
  off). (#126)

### Users and the audit log
- **First and last names** for every account, shown in the Users list (which gains search and sort by last name) and
  in the audit log as First Last - username. (#134)
- **Readable audit log.** Each entry reads as a sentence — who did what to which record — with the time in your time
  zone; **Details** shows what changed in plain words (amounts as currency, readable field names, transaction lines as
  a table). Administrators still see no financial content. (#133)
- **Export the audit log** for an audit review: **Export CSV** and **Printable PDF** hold every entry matching the
  filters, in the same plain words as the screen. Each export is itself recorded. (#188)

### Easier to use
- **Forms line up:** labels and inputs align on every form, text boxes, dropdowns, date fields and buttons are the
  same height, and small buttons and checkboxes sit centred on the input line. (#214)
- **Row actions in a menu:** tables show **Edit** and a **⋯** menu with the row's other actions, which works with
  the keyboard and screen readers; destructive actions come last and still ask to confirm. (#215)
- **Build time in your time zone** on My account and System/About. (#185)

### Installing on a server
- **Windows server installer:** `install-windows-server.ps1`, attached to every release, installs or upgrades
  PennyWarden as a Windows service under its own account, with HTTPS through Caddy (`-Domain`) or behind a Cloudflare
  Tunnel; every download is checked; an upgrade copies the data first and rolls back if the new version doesn't
  start. The Windows server guide (docs/install-windows-server.md) covers everything step by step. (#187, #136)
- **Linux server:** the installer adds the `pennywarden` command (`sudo pennywarden restore …`, `reinitialize`,
  `reset-password`, `reset-mfa`). New installs' `config.toml` has an empty `backup_folders = []` list with an example.
- **Test builds' release notes** start with the install command and downloads. (#207)

### Fixes
- **Scheduled backups to a folder on a Linux server** failed the folder test with a permission error even when the
  folder's permissions were right: the service is sandboxed and could write only to its data folder. The installer
  now lets it write to the folders in `backup_folders` (run the installer again after changing that list; folders
  under `/home` can't be used).
- In server mode, a scheduled backup's folder is always one of the server's configured `backup_folders`. (#168)
- Long pages no longer keep scrolling past their end.

### Under the hood
- New dependency **pypdfium2** (BSD-3-Clause / Apache-2.0), which draws the Payments Setup previews. Updated:
  FastAPI 0.143.0, Pydantic 2.14.0, SQLAlchemy 2.1.4, pypdf 6.20.0 and others (THIRD-PARTY-NOTICES.txt).
- Dependabot no longer proposes pydantic updates on their own (it can't update the matching pydantic-core with it);
  both are updated together by hand.
- UI standards for every new screen are written down in docs/ui-standards.md.

## 1.10.0 — 2026-10-09
Database migration `0024` (one table added; no existing data changes). Rolling back to 1.9.0 needs the data snapshot
the installer takes before the upgrade (docs/upgrade.md).
- **Server on Windows, documented.** A step-by-step guide for running PennyWarden for several people on a Windows
  machine — the portable zip in server mode, a fixed data folder, HTTPS through Cloudflare Tunnel or Caddy, and Task
  Scheduler to start it with Windows (docs/install-windows-server.md, #144); linked from the README and pennywarden.org.
- **Update notification (#58).** When a newer version is out, a gold circle with an up arrow appears next to your
  name in the top bar. It opens **What's new**: the release notes of every newer release, newest first, and a button
  to the download page. On a server, Administrators also see a banner above every page; on a local install the banner
  is on My account. PennyWarden itself (not your browser) asks pennywarden.org about once a day; nothing about your
  organization is sent, and an Administrator can turn the check off in System/About. Production installs are told
  about releases only; test builds also about newer test builds.
- **pennywarden.org (#83).** A product page on GitHub Pages at <https://pennywarden.org>: what PennyWarden is, for
  whom, screenshots, and direct download buttons for Windows, Mac and Linux (the visitor's own system highlighted)
  with the current version, its date and the checksums, plus help with the "unverified app" warnings. It is rebuilt
  after every release from the GitHub releases, together with the release data files the update notification reads
  (docs/product-site.md).
- **Fix: typing in the "Exclude this line" dialog of the Financial Flow Report (#139).** The reason box lost the focus
  after every letter, so a reason could hardly be entered. Dialogs now take the focus once, when they open.

## 1.9.0 — 2026-10-09
Database migration `0023` (two tables added; no existing data changes). Rolling back to 1.8.0 needs the data
snapshot the installer takes before the upgrade (docs/upgrade.md).
- **Scheduled automatic backups (#62).** System/About → Backup / Restore → **Scheduled**: an Administrator chooses
  Daily or Weekly and a time, one folder (on a server, one of the folders the server owner lists as
  `backup_folders` in `config.toml`; locally, any folder), a backup passphrase, and how many daily, weekly and monthly
  backups to keep. Backups are written without anyone signed in, encrypted with a key pair so the application can
  lock them but only the passphrase opens them; they restore through the normal Restore tab. A failed backup is
  retried after 1, 2, 4 … hours (at most 24) and Administrators see a banner until one succeeds; a backup missed
  while PennyWarden was off runs at the next start. **Test**, **Run now** and a history of recent runs; everything is
  in the audit log. Old backups are deleted by the keep rules — only files PennyWarden wrote. The download backup is
  unchanged (docs/backup-restore.md).
- **One person can run a local install (#54).** On a local install (Windows, Mac, or Linux local mode) the first
  user now holds every role: Administrator, Budget Manager, Budget Admin, Register User, Register Admin and Auditor
  (security domain *COMBINED*), so one account can manage users, keep the books and read the audit log. On a local
  install the Users page offers the roles of all three domains together for any user, and an Administrator can
  change their own roles — on an existing local install, edit your own user to add the roles you need. Servers are
  unchanged: one security domain per user, and Administrators cannot change their own roles. A user with combined
  roles whose data is later run as a server keeps them and can still be edited, but changing the roles there needs
  one domain; the Users page marks such users.

## 1.8.0 — 2026-10-09
Database migrations `0021` and `0022` (columns and tables added; no existing data changes). Rolling back to 1.7.3
needs the data snapshot the installer takes before the upgrade (docs/upgrade.md). **Every user chooses three
security questions at the next sign-in.**
- **Forgot password (#113).** Each user chooses three security questions from a list (at the first sign-in; existing
  users at their next one) and can change them in **My account**. **Forgot password?** on the sign-in page asks one
  of them at random; on a server — and on a local install with two-step verification — an authenticator or recovery
  code is needed as well. Then the user sets a new password and is signed out everywhere. The page never reveals
  whether a username exists. The user is told about the reset at the next sign-in and Administrators see a notice.
  Administrators can *Reset security questions* on the Users page.
- **Failed attempts lock the account (#113).** Wrong passwords and wrong *Forgot password* answers now add up per
  account and are kept across restarts: 5 in a row lock the account for 15 minutes, 10 for an hour (Administrators
  get a notice), 15 for 24 hours, and at 20 the account is disabled until an Administrator enables it again. The
  numbers can be changed in `config.toml` (docs/configuration.md). The user is told at the next sign-in.
- **Dependabot's Python updates run the tests (#98).** On Dependabot pull requests and develop builds, an
  out-of-date `THIRD-PARTY-NOTICES.txt` is regenerated for the run and reported (warning and run summary) instead of
  stopping the tests; a new package that is not pinned in `backend/requirements.txt` is named. Pull requests into
  test and main and their builds stay strict, and now also fail when a shipped package is not pinned
  (docs/branching.md).
- **Host command `reset-password` (#113)** for the only Administrator who forgot both the password and the answers:
  it prints a temporary password that must be changed at the next sign-in. `reset-password` and `reset-mfa` also
  enable a disabled account again.
- **Financial Flow Report (#106).** A new report on the Reports page for the treasurer's periodic update: the money
  that came in and went out of the chosen accounts between a From Date and a Through Date (empty: "Current"), one
  section per account with its income, expenses, totals and the **Difference** (green with + or red with −), and an
  overall summary when several accounts are chosen. Expenses are one line per withdrawal, income one line per part of
  a deposit; transfers between accounts and VOID transactions are not listed, uncleared ones are. Before the PDF is
  made you **review the lines**: uncheck a line to leave it out (a reason is required; it goes to the audit log, never
  onto the report) and type a note on a line to print it with the line. Optionally the report lists the Current
  balance of every account on the Through Date in Checking, Savings and Investments with Total Assets, and with a
  Compare Date the balance then and the change. Producing the report is recorded in the audit log.
- **Budgets linked across Fiscal Years (#89).** A budget can record which budget of an earlier Fiscal Year it
  continues, even when its ID or name changed, in a new **Continues** list in the budget's create and edit dialogs
  (grouped by Fiscal Year, e.g. `FY2027 - 1000 - Operations`). The link is one to one, between budgets of the same
  type (Income or Expense) and level (budget or sub-budget); Budget 0 and Other are never linked. Budgets copied into
  a new Fiscal Year are linked to their source automatically; budgets created before 1.8.0 are not linked until you
  choose. Budgets with a link have a **History** link on the Budgets page that shows every year of the budget with its
  ID, name, amount and actual. Changing the link follows the usual budget rules (unlock a locked budget first; not
  in a Closed Fiscal Year) and is recorded in the audit log.
- **Configuration documentation for the Mac (#112).** docs/configuration.md now covers the Mac like Windows and
  Linux: the data folder (`~/Library/Application Support/PennyWarden`) and how to open it in Finder, the log file,
  `config.toml` (environment variables do not reach an app opened from Finder), and starting the app with options
  from Terminal. The paragraph on earlier folder names now covers both renames (1.6.6 and 1.7.0) on all three
  systems. install-macos.md and deployment.md link to it.

## 1.7.3 — 2026-10-08
Database migrations `0019` (two roles and three columns added) and `0020` (balance history, rebuilt from the audit
log); no existing balance changes. Rolling back to 1.7.2 needs the data snapshot the installer takes before the
upgrade (docs/upgrade.md).
- **Register: filter by budget (#104).** A new **Budget** filter in the Register shows only the transactions with
  an allocation to that budget; a parent budget includes its sub-budgets. A split transaction is shown with the
  budget's share, e.g. "$40.00 of $100.00", so the amounts listed add up to the budget's activity. The choices follow
  the Fiscal Year filter (with "All dates": every year's budgets, labelled `FY2026 - 1000 - Operations`). Changing the
  bank account keeps the filter; **Clear** removes it. The Balance column and the balance tiles are not affected.
- **Budgets page: each budget opens its transactions (#105).** A budget's code and name are a link to the Register,
  on the default account (Primary, or the first in the set order), with the Budget filter set to it and the Fiscal
  Year filter set to the budget's year — also for a prior year chosen on the Budgets page. Budget 0 has no link.
- **Budget Admin: delete a budget before the Fiscal Year is approved (#52).** A new Financial role, *Budget Admin*,
  given only together with *Budget Manager*. In a Fiscal Year that is not approved yet, the budget's edit dialog has
  a red **Delete budget…** button; a reason is required. The budget gets the status *Deleted*: it disappears from
  the Budgets page, every budget list, the totals and the next year's copy, and its code can be used again. Nothing
  is removed from the database — Auditors still see it, marked *Deleted* with the reason, and the audit log records
  it. Not possible while Register transactions are allocated to it, while it has sub-budgets (delete those first),
  for Budget 0 and the system Other budgets, or when a fundraiser uses it.
- **Register Admin: delete an uncleared transaction (#53).** A new Financial role, *Register Admin*, given only
  together with *Register User*. The transaction's edit dialog has a red **Delete transaction…** button; a reason is
  required. Only an active, **uncleared** transaction can be deleted: one with a Clear/Post Date has posted at the
  bank and is final (remove the clear date first if it was put on the wrong line). VOID records and transactions of a
  Closed Fiscal Year cannot be deleted; a transfer is deleted with both legs. The transaction gets the status
  *Deleted*: it disappears from the Register, every balance, budget, chart and report. Its check number stays used.
  Auditors still see it (Register → Status → *Deleted*), with the reason and its attachments; the audit log records
  it.
- **Balance history for accounts without a register (#88).** Every **Update balance** on an investment, CD or other
  non-register account is now kept as a dated entry; nothing is overwritten. The dialog has an **As of** date (today
  or earlier — e.g. a statement date; not in a Closed Fiscal Year). The account's current balance is the entry with
  the latest date; for the same date, the one entered last counts — a mistake is corrected by entering the right
  balance again. **History** under the balance on the Bank Accounts page lists the entries with their change, who
  entered them and why. The **Bank balances** chart now includes these accounts (the balance carries forward between
  entries). On upgrade, each account's history is rebuilt from the audit log: its balance when it was created and
  every update since.
- **Fixed: a link from a fundraiser line to the Register** (1.6.0) opened the Primary account and the current Fiscal
  Year instead of the line's account with all dates; it now opens the right account again.

## 1.7.2 — 2026-10-08
No database migration.
- **Administrators cannot change their own roles on a server (#55).** In server mode, the *Security domain* and
  *Roles* of your own account are greyed out on the Users page, with the note "You cannot change your own security
  domain or roles. Another Administrator can change them for you."; a direct request is refused as well
  (`OWN_ROLES_LOCKED`). Your email address and display name can still be changed, and any Administrator can still
  change the roles of *other* users, other Administrators included. A local install (Windows, Mac, single user) is
  not restricted. Keep a second Administrator on a server so roles can always be changed.
- **Nobody can disable their own account (#55 follow-up, all installs).** On your own account the *Active* box is
  greyed out ("You cannot disable your own account."), and a direct request is refused (`OWN_ACCOUNT_DISABLE`).
  Disabling yourself signed you out at once, and an Administrator who meant to disable someone else could lock
  themselves out. Another Administrator can still disable you. (Disabling the *last* Administrator was already
  refused.)
- **Current and Available balances (#56, #57).** Two balances, defined the way the bank does:
  - **Current balance** is the real bank balance: only transactions that have cleared (have a Clear/Post Date).
    For a past date it counts what had cleared by that date. It is now the balance shown everywhere outside the
    Register: the Bank Accounts page and its totals, the Dashboard and its totals, the account dialogs and the *Bank
    balances* chart. **Numbers on these pages change after the upgrade when transactions are not cleared yet** —
    until now they included uncleared transactions.
  - **Available balance** includes everything written or deposited, cleared or not — what is truly available once
    everything has cleared. It is shown in the Register only, next to the Current balance. The running balance on
    each Register line is unchanged (Available basis).
  - **Opening balance of a Fiscal Year** (Register, Fiscal Year selected): the Available balance at the end of the
    day before the year starts, as before, so opening + the year's deposits − its withdrawals = the year's ending
    balance. Under it, **Bank $…** opens a bank reconciliation: the bank balance on that date, the outstanding items
    (written or deposited by then, not cleared by then) and the opening balance they add up to. Clearing last year's
    items later does not change it; it is fixed once last year is Closed.
  - The Register shows **Opening, Current and Available** for an open Fiscal Year (or no Fiscal Year), and
    **Opening and Ending**, each with its reconciliation, for a **Closed** one. A *To* date adds the Ending balance.
  - **New rule:** a Clear/Post Date cannot be earlier than the Transaction Date ("The Clear/Post Date cannot be
    earlier than the Transaction Date."), on new and edited transactions and transfers. Existing records are not
    changed; a record that breaks the rule has to be corrected the next time it is edited.
  - Account closure is unchanged (no uncleared transactions and a 0.00 balance — then both balances are equal).
    Accounts without a register keep their one manually maintained balance.
- **Dependency updates (Dependabot #94, #95).** TypeScript 5.6.3 → 5.9.3 (build only). FastAPI 0.141.1 → 0.142.2,
  SQLAlchemy 2.1.1 → 2.1.3, cryptography 50.0.1 → 50.0.2, charset-normalizer 3.5.1 → 3.5.2, MarkupSafe 3.0.3 →
  3.0.4. FastAPI 0.142 brings one new package, **opentelemetry-api 1.45.1** (Apache-2.0), now pinned and listed in
  THIRD-PARTY-NOTICES.txt. Dependabot's own pull request for the Python updates could not pass, because it cannot
  regenerate the notices file; it was replaced by a branch that does.
- **CHANGELOG:** 1.7.1 is dated 2026-10-08, the day it was released (it said 2026-10-07).

## 1.7.1 — 2026-10-08
Database migrations `0017` (no column added or removed; fills in missing display names and adds the rule to the
database) and `0018` (adds the bank account order). Rolling back to 1.7.0 needs the data snapshot the installer
takes before the upgrade (docs/upgrade.md).
- **Your name in the top bar (#46).** The top bar shows the signed-in user's **display name** instead of the
  username.
- **Roles moved out of the top bar (#50).** The list of roles next to the name is gone; the top bar is the name,
  the theme switch, reminders, *My account* and *Sign out*. **My account** now shows your username, email address
  and roles.
- **Every user has a display name (#47).** *Display name* is required when an Administrator creates a user and
  cannot be removed when editing one. It is stored without leading or trailing spaces and must be at least 3
  characters (at most 120, as before): "Display name is required." / "Display name must be at least 3
  characters." Existing users without a display name — or with one shorter than 3 characters — get their
  **username** as display name during the upgrade; all others are unchanged. The first Administrator created by
  the Initialization Wizard starts with the username too. The database enforces the rule as well. The Users list
  has a *Display name* column.
- **Audit and Fiscal Year Close reports — start and end pages for the fundraisers (#59).** When a report includes
  fundraisers, they now sit between a **"Start of fundraisers"** page and an **"End of fundraisers"** page, like
  each bank account's transactions since 1.6.7. Both pages name the Fiscal Year, the number of fundraisers, the
  first and the last one, and state the page range ("pages 36 to 42 of 42 (7 pages…)"), each pointing at the other;
  the start page lists the fundraisers in order. Every page in between shows **"Fundraisers - section page k of
  n"** at the bottom right. One fundraiser gets the two pages as well; a report without fundraisers is unchanged.
  The page range is recorded with the report in the audit log.
- **Bank accounts in the order you choose (#74).** On the Bank Accounts page a Budget Manager moves accounts up
  and down with the new **▲ ▼** buttons (mouse or keyboard; each button names its account for screen readers and
  the new position is announced, e.g. "Savings moved to position 1 of 3 in Checking & Savings."). The order is kept
  separately for *Checking & Savings* and *Investments and Other*, and is used on the Bank Accounts page, the
  Dashboard (also the balances chart) and in the Register's account list. The Primary account is not pinned — it
  goes wherever it is placed — and the Register still opens on the Primary account. After the upgrade each group
  lists the Primary account first and the others by name, as before; a new account is added at the end of its
  group (also an account whose type moves it to the other group). Only Budget Managers can change the order (also
  refused through the API); each change is recorded in the audit log (`BANK_ACCOUNT_ORDER_CHANGED`, with the
  order before and after). Totals are unchanged. Reports keep their own order.
- **Entity form — Email and Phone line up (#51).** The two labels and the two boxes are level; the hint stays under
  the Phone box and is shorter ("Any format, e.g. 555-123-4567. Shown as (555) 123-4567.").
- **Fixed: new bank account form lost what was typed after "+ New institution".** After a new institution was saved
  the form selected it a moment later — and put the other fields back to what they were when it was saved, so an
  account name typed in between disappeared. Found by an E2E run that failed once at this point.
- **Dependabot no longer proposes major versions (#80).** When 1.6.8 switched Dependabot on, it opened a pull
  request for every major upgrade it could find (React 19, TypeScript 7, Vite 8, …) and one for `pydantic_core`
  alone; none of them could pass the tests. Major upgrades are now left to be planned as issues, and
  `pydantic_core` is only updated together with `pydantic`. The weekly grouped minor and patch updates are
  unchanged, and security updates are not held back by the new rules — also when the fix is a major version.
  No change to the application.
- **Documentation after the rename.** New quick guide *What's new in 1.7* (the new name, and what to do on a
  server, a Windows PC and a Mac). The 1.4, 1.5 and 1.6 guides use the name PennyWarden; the README's *Origin*
  paragraph, docs/deployment.md and docs/implementation-notes.md record both renames.
- **Mac installation guide with pictures (#61).** New page *docs/install-macos.md*: download, copy to
  Applications, and the one-time *Open Anyway* step in System Settings, each with an illustration marking where to
  click; the shorter right-click → *Open* way for macOS 14 and earlier; upgrading; and what to do when something
  looks different. The README and docs/deployment.md link to it. The illustrations are drawings (marked
  "Illustration"), made by `scripts/macos_install_mockups.mjs`.

## 1.7.0 — 2026-10-07
**The application is renamed to PennyWarden** (#70). Another product in the financial field already uses the name
Fundwarden. This release contains the rename and nothing else: no database migration, no change to data, settings
or the way anything works. The gold coin with the keyhole stays.
- **What you see.** *PennyWarden* in the browser tab, on the sign-in page, in the top bar, in reports, in the Mac
  window and in the documentation. New backups are named `pennywarden-backup-…`; backups made as Fundwarden restore
  as before. Two-step verification keeps working — the entry in your authenticator app keeps its old label; new
  set-ups are labelled *PennyWarden*.
- **Downloads.** `PennyWarden-linux-x64-portable.tar.gz` (command `pennywarden`), `PennyWarden-windows-x64.zip`
  (`PennyWarden.cmd`), `PennyWarden-<version>-windows-x64.exe`, `PennyWarden-<version>-macos-arm64.dmg`
  (`PennyWarden.app`). The repository is `github.com/kretherford0983/PennyWarden` — **rename it on GitHub before
  installing a 1.7.0 build**; the old address is forwarded.
- **Server installs migrate themselves.** Run the normal upgrade command. The installer finds the Fundwarden
  installation, stops it, **copies** `/var/lib/fundwarden` to `/var/lib/pennywarden` (compared file by file),
  installs the service `pennywarden` under `/opt/pennywarden` on the same port and disables `fundwarden`. The old
  installation is not changed: going back is `systemctl disable --now pennywarden && systemctl enable --now
  fundwarden`, and the installer does that by itself when PennyWarden does not start. Remove the old installation
  with the checklist in docs/upgrade.md (*Cleanup after the rename to PennyWarden*) when you are sure. A server that
  still holds the stopped installation from before 1.6.6 (`fmpoc`) is handled too: the one in service is migrated.
- **Windows, Mac and Linux PCs.** At its first start 1.7.0 renames the default data folder in place
  (`…\Fundwarden` → `…\PennyWarden`); a folder you chose yourself is never touched. On a Mac the *Open Anyway* step
  is needed once more, because macOS sees a new app.
- **Docker.** Image `pennywarden`, volume `pennywarden-data`; docs/upgrade.md has the three commands that copy the
  old volume.
- **For scripts.** The rarely used `install.sh` overrides are now `PENNYWARDEN_REPO`, `PENNYWARDEN_API`,
  `PENNYWARDEN_DOWNLOAD` and `PENNYWARDEN_CONFIG`. `install.sh --version v1.6.8` (or older) still installs that
  release under the name it had.
- Not renamed (internal): the database file `fmpoc.sqlite3`, the log file, the `FM_*` settings, the `.fmbak` format.

## 1.6.8 — 2026-10-07
Maintenance of the build pipeline, repository security automation, one sign-in fix and two small hardening changes
from the first CodeQL results. No database migration and no change to data or settings.
- **Fixed: sign-in refused with "Missing or invalid CSRF token." (#68).** The sign-in page asks the server for its
  form token when it opens and again when **Sign in** is pressed. When Sign in was pressed before the first answer
  had arrived — a password manager that fills in and submits at once, or a slow connection — the two requests each
  got their own token, the browser kept one and the page sent the other, and a correct username and password were
  refused once (a second attempt worked). The page now never sends two of these requests at the same time. Found by
  an E2E run that failed at exactly this point; a test now plays the overlap deliberately.
- **GitHub Actions on Node.js 24 (#48).** The workflow actions ran on the deprecated Node.js 20 runtime and were
  being forced onto Node.js 24 with a warning on every run. They now use the versions built for Node.js 24:
  `actions/checkout@v7`, `actions/setup-node@v7`, `actions/setup-python@v7`, `actions/upload-artifact@v7` and
  `actions/download-artifact@v8`. The Node.js version that builds the application (22) is unchanged.
- **Linux jobs pinned to Ubuntu 26.04 (#49).** GitHub moves `ubuntu-latest` to Ubuntu 26.04 from 2026-10-19. The
  five Linux jobs (tests, promotion rules, packages, assemble, publish) now name `ubuntu-26.04`, so the move happens
  on our schedule and is proven by the pull request's own run. The E2E tests use **Playwright 1.63.0** (was 1.56.1,
  which cannot install its browser on Ubuntu 26.04). Returning to `ubuntu-latest` is a later one-line change.
- **Weekly security check (#64).** New workflow `security`: every Monday (and on demand from the Actions tab) GitHub
  runs the dependency vulnerability checks and the security tests on `main`. A new advisory fails the run and GitHub
  emails the repository owner, so it is noticed between releases — not, as with 1.6.7, at the release pull request.
- **Dependabot (#65).** `.github/dependabot.yml`: weekly update pull requests into `develop` for the Python,
  JavaScript and GitHub Actions dependencies — minor and patch updates grouped into one pull request per group,
  major versions separately, at most 5 open per group. The promotion rules now accept `dependabot/*` branches into
  `develop` (and only there). docs/branching.md describes how such a pull request is handled.
- **Demo data script (#66).** `scripts/demo_data.py` no longer prints the demo password when it finishes (reported
  by CodeQL as clear-text logging); it points to the `PASSWORD` constant in the script instead. The password was
  always a made-up value in a public file — nothing was exposed.
- **First CodeQL results reviewed (#66).** Four alerts, none exploitable. Two led to small changes: the pattern that
  reads a phone extension (`x204`, `ext 204`) no longer does needless repeated work on a long run of spaces (the
  field is limited to 40 characters, so this was never noticeable; the same numbers are accepted), and the
  pre-sign-in form token cookie is now written only when the server generates a new token — a browser that already
  has one gets it back without the cookie being set again, and a cookie that is not one of our tokens is replaced.
  The other two ("clear-text storage of sensitive information") point at the session cookie and the trusted-browser
  cookie; sending those tokens to the browser as HttpOnly, SameSite=Strict cookies is how sign-in sessions work (the
  server stores only a hash), so they are dismissed as false positives.
- **Issue templates.** New issue → *Enhancement*, *Feature* or *Bug* opens with the headings used for planning
  (problem, proposed behavior, acceptance criteria, out of scope, open questions) and applies the label.

## 1.6.7 — 2026-10-06
Recurring organization reminders, a Mac app, account start and end pages in the audit report, register filters,
phone number formatting, cash count sheet refinements and a position for people. Database migrations `0014`,
`0015` (new optional columns only) and `0016` (tidies stored phone numbers). Rolling back to 1.6.6 needs the data
snapshot the installer takes before the upgrade (docs/upgrade.md).
- **Recurring organization reminders.** An organization reminder can **repeat every N days, weeks, months or
  years**, optionally **until** an end date (New reminder → *Repeat*). Each occurrence is its own reminder with its
  own resolution note. **Resolving one creates the next**, due one interval after the *scheduled* due date — not the
  day it was resolved — so a monthly reminder stays on its day of the month (the 31st falls on the last day of
  shorter months). In the Resolve dialog, *Stop repeating after this one* ends the series; so does deleting the
  upcoming occurrence. Reopening a resolved occurrence takes back the next one it created (refused once that next
  one has itself been resolved). Personal reminders stay one-time. Existing reminders are unchanged.
- **Audit and Fiscal Year Close reports — account start and end pages.** When the report covers more than one bank
  account, each account's transactions now sit between a **"Start of transactions"** page and an **"End of
  transactions"** page. Both name the account, its number of transactions, deposits, withdrawals, first and last
  transaction, and state the account's page range ("pages 4 to 9 of 12 (6 pages…)"), each pointing at the other.
  Every page in between shows the account and **"section page k of n"** at the bottom right, so a reviewer can see
  which account a page belongs to and that no page is missing. A report for a single account is unchanged. The
  page range of each account is also recorded with the report in the audit log.
- **Mac app (Apple Silicon).** New download `Fundwarden-<version>-macos-arm64.dmg` for Macs with an M1 or later
  chip (macOS 11+): open the disk image, drag **Fundwarden** to Applications and open it. A small Fundwarden window
  shows the address, opens the browser and has **Quit**; closing the window stops Fundwarden. Data is kept in
  `~/Library/Application Support/Fundwarden`, so replacing the app with a newer one keeps everything. Like the
  Windows .exe, the app is **not signed with a paid developer certificate**: the first time, macOS says it could
  not verify the app — open *System Settings → Privacy & Security* and click **Open Anyway** (once). The steps are
  in *Read me first* inside the disk image and in docs/deployment.md. Built and smoke-tested by CI on a macOS
  arm64 machine with every build.
- **Documentation.** The README on the project page now presents what Fundwarden does: the core features, each
  with a screenshot (dashboard, budgets, register, audit report, closing the year, fundraisers, reminders), and a
  table of all capabilities. The screenshots come from a made-up organization: `scripts/demo_data.py` fills a new,
  empty installation through the normal API and `scripts/readme_screenshots.mjs` retakes them.
- **Fiscal Year documentation review — links to the Register.** The transaction number of every item in the
  documentation review is now a link: it opens the Register on that bank account (all dates), scrolls to the
  transaction, highlights it and opens its details — where a document can be attached right away.
- **Register — Attachments filter.** A new **Attachments** filter next to Status: *All* (default), *Yes* (only
  transactions that have an attachment, on the transaction or on one of its lines) or *No* (only those without).
  It counts exactly what the paperclip in the row counts, so a transaction marked "no attachment will be
  provided" is listed under *No*. It combines with the other filters; the balances stay those of the whole register.
- **Register — Clear filters.** A **Clear** button next to the register's filters puts Fiscal Year, Type, Status,
  Attachments, From, To and Search back to how the register opens (the current Fiscal Year, everything else
  empty). The chosen bank account stays. The button is greyed out when no filter is set.
- **Entity phone numbers.** Type a phone number any way you like — `5551234567`, `555-123-4567`, `555.123.4567`,
  `(555) 123-4567`, with or without a leading 1. It is stored as plain digits and always shown as
  **(555) 123-4567**; the field tidies itself when you leave it. An extension (`x204`, `ext 204`, `#204`) is kept
  and shown as `x204`; a number from another country is entered with a leading `+` and kept as typed digits.
  Anything else is refused with a hint. Database migration `0016` rewrites the numbers already stored that are
  clearly 10-digit numbers; any other existing value is left untouched and can still be edited.
- **Position of a person.** An individual Entity can have a **Position in the organization** (for example
  "Treasurer"; optional, set by a Budget Manager or Register User on the Entity). When that person is chosen as a
  signer on the **audit review signature page** or the **cash count sheet**, the position is filled in as the title.
  It can still be changed or cleared for that one print. Not used anywhere else.
- **Cash count sheet — chosen signers.** A chosen signer now gets one long signature line running across to the
  date, with the name (and title) printed under it — no "Signature" / "Printed" labels and no empty gap. Rows left
  empty are unchanged (Signature, Printed, Date to fill in by hand).
- **Cash count sheet — dialog.** Starts with two empty rows and offers *+ Add signature line* right away (still at
  most three empty rows, or two next to chosen signers, and five rows in total).
- **Installer fix.** `curl …/releases/latest/download/install.sh | sudo bash` (without `--version`) stopped with
  "no release found": GitHub answers the release lookup on one line and the installer only understood the
  multi-line form. It now understands both. (Installing with `--version <tag>` was not affected.)
- Build: a build tool's helper library (`source-map-js`, used only while building the web interface and not part
  of what is installed) is updated to 1.2.2 after a security advisory published on the day of the release
  (GHSA-68fv-2mgg-jv7q) stopped the release check.
- Build: the Mac app's smoke test no longer fails at random ("LICENSE is not bundled" on one build of develop):
  it searched the page while still downloading it.
- Build: the browser tests wait longer for the page after signing in (a slow build machine failed one run of 1.6.6).

## 1.6.6 — 2026-10-02
**First production release, under a new name: Fundwarden.** The application leaves its proof-of-concept names
(*Financial Management POC*, *Freedger*, `fmpoc`) behind. No database change; nothing about how you work changes.
Everything from 1.1 to 1.6.5 (sections below, kept as written) was published on the test channel only.
- **New name everywhere you see it:** browser tab, sign-in page, top bar, PDF properties, authenticator entry for
  new two-step set-ups (existing entries keep working and keep their old label), backup file names
  (`fundwarden-backup-….fmbak`; older backups restore as before) and the recovery-codes file.
- **App icon:** a gold coin with a keyhole — browser tab (favicon), phone home-screen icon and the Windows `.exe`.
- **Downloads renamed:** `Fundwarden-<version>-windows-x64.exe`, `Fundwarden-windows-x64.zip` (start
  `Fundwarden.cmd`), `Fundwarden-linux-x64-portable.tar.gz` (program `fundwarden`).
- **Linux servers:** service, system user and folders are now `fundwarden` (`/opt/fundwarden`,
  `/var/lib/fundwarden`, `/var/backups/fundwarden`). The normal upgrade command migrates an existing `fmpoc`
  installation: the data is *copied* (and compared) to the new place, the old service is stopped and disabled and
  **left in place**, so going back is one command; if Fundwarden does not start, the installer switches back by
  itself. Removing the old installation afterwards is a short manual checklist: docs/upgrade.md,
  *Cleanup after the rename*.
- **Windows:** the data folder `%LOCALAPPDATA%\FinancialManagementPOC` is renamed to `%LOCALAPPDATA%\Fundwarden`
  at the first start (in place; nothing is copied).
- **Installer:** `install-server.sh` reads the health-check port from the existing `config.toml` and takes its data
  snapshot before every upgrade even when the service was stopped; `install.sh` can still install a release from
  before the rename (`--version <tag>`).
- **Cash count sheet — signature rows.** The sheet is meant to be printed before it is known who will count. Each
  person now gets one row across the page: **Signature**, **Printed** name and **Date**, with room to write. A row
  left empty in *Cash count sheet…* is filled in by hand; a chosen signer's name is printed on the *Printed* line.
  The dialog starts with three empty rows. Up to five rows; at most three may be empty, or two next to chosen
  signers. Always two lines for notes. (Before: a single line captioned "Name and title".)
- **Cash count sheet — checks.** Page 1 now lists 13 checks, level with the 13 bill and coin lines, which leaves the
  room for notes and signatures. An optional **page 2** (on by default) has 30 more check lines and their own total:
  print it on the back with two-sided printing, as a second sheet, or leave it out when it is not needed.
- The source code moved to `github.com/kretherford0983/Fundwarden` (the old address redirects).
- Unchanged on purpose (internal): Python package `fmpoc`, `database/fmpoc.sqlite3`, `logs/fmpoc.log`, `FM_*`
  settings, the `.fmbak` format.

## 1.6.5 — 2026-10-02
Polish and documentation. Beta: test channel only. No database change.
- **Documentation** prepared for the first production release (planned: 1.6.6): README, deployment, upgrade, backup
  and branching guides. Until that release exists, the `releases/latest` install command does not work yet — use a
  pre-release's own address (shown in its release notes).
- **Dashboard bank account balances** (GitHub issue #15): *Checking & Savings* and *Investments and Other* are now
  separate tables with their own heading and subtotal and space between them, and the total of all accounts stands
  on its own below — matching the Bank Accounts page.

## 1.6.4 — 2026-10-02
Two fundraiser additions. Beta: test channel only.
- **CR-037 Cancelled fundraisers.** A Budget Manager can **mark a fundraiser as cancelled** (a reason is required)
  when it did not take place as planned, and **reinstate** it later. The fundraiser shows the status *Cancelled* and
  the reason on its page, in the lists, in its report and therefore in the End of Year Audit and Fiscal Year Close
  reports. Expenses and deposits already made stay listed and counted; buckets, documents and everything else keep
  working. Recorded in the audit log. Database migration `0013` (three new columns).
- **CR-038 Cash count sheet.** *Cash count sheet…* on a fundraiser's page opens a one-page PDF to print and fill in
  by hand: date and time of the count, a grid for bills and coins, a list for checks, **Cash total / Check total /
  Total counted** (the totals can be used on their own), notes, and signature lines with dates — for up to five
  chosen individuals (with optional titles) or three blank lines — under a statement that the signers agree with the
  amounts. Scan the signed sheet and add it under *Fundraiser documents*.

## 1.6.3 — 2026-10-02
Reminders and notifications. Beta: test channel only.
- **CR-036 Reminders.** A bell in the top bar shows how many reminders are due; **Notifications** lists them (Due,
  Upcoming, Resolved), and the dashboard shows due reminders in a new *Notifications* section (at the top by default;
  it can be hidden or moved with *Customize dashboard*).
  - **Personal reminders** — Budget Managers and Register Users set them for themselves; nobody else sees them.
  - **Organization reminders** — set by Budget Managers; shown to every financial user and to Auditors once due.
    Budget Managers and Register Users resolve them; Budget Users and Auditors see them read-only until they are
    cleared.
  - A reminder has a due date, optionally *show N days before*, details and a link to a Fiscal Year, budget or bank
    account. Once shown it stays until it is **resolved** (optional note); a resolved reminder can be reopened.
    It can be edited or deleted only before it is shown. One-time reminders only; no e-mail.
  - Everything is recorded in the audit log. Database migration `0012` (additive).

## 1.6.2 — 2026-10-01
Fundraiser module, part 3: the fundraiser report. Beta: test channel only. No database change.
- **CR-035 Fundraiser report.** **Report (PDF)** on a fundraiser's page (everyone who can see the fundraiser):
  event, budgets and filter; income, expenses, net and return; cash float and excluded amounts; breakdown per Fiscal
  Year; buckets; every counted transaction line; excluded lines with their reasons; then the fundraiser documents and
  the transactions' attachments reproduced.
- The same section can be added to the **End of Year Audit** and **Fiscal Year Close** reports (*Include
  fundraisers*, ticked by default when the module is on): all non-archived fundraisers with a budget in that Fiscal
  Year, after the transactions and before the signature page. A fundraiser spanning two Fiscal Years is shown complete
  in both years' reports, with that report's year marked. The Close report stored automatically when a Fiscal Year is
  closed includes them too.

## 1.6.1 — 2026-10-01
Fundraiser module, part 2: managing a fundraiser's transactions. Beta: test channel only.
- **CR-034 Managing a fundraiser** (Budget Managers and Register Users; everything is recorded in the audit log):
  - **Buckets** — sub-categories such as *Food sales* or *Raffle*. Assign a transaction line to a bucket, or split it
    across buckets by amount (*Manage* on the line). Each bucket shows income, expenses and net; whatever is not
    assigned is shown as *Unassigned*. New chart: income, expenses and net per bucket.
  - **Cash float** — mark the cash taken out for the cash box (*Cash float out*, on a withdrawal) and the float coming
    back inside a deposit (*Cash float returned*), each with an amount. Those amounts are left out of the fundraiser's
    income and expenses and shown separately.
  - **Exclude a line** that does not belong to the fundraiser (a reason is required); it can be included again.
  - **Fundraiser documents** — flyers, permits, tally sheets (PDF/JPG/PNG, 5 MB) on the fundraiser page; the
    transactions' own attachments are still listed below them.
  - Lines of a closed Fiscal Year are frozen. Removing a budget from a fundraiser drops the buckets, classifications
    and exclusions of its lines. A fundraiser with buckets, classifications, exclusions or documents can be archived
    but not deleted.
  - Database migration `0011` (additive).

## 1.6.0 — 2026-10-01
First feature release of the 1.6 line: the optional Fundraiser module (core). Beta: test channel only.
- **CR-033 Fundraiser module.** An Administrator turns it on under System/About → *Optional modules*; it then appears
  in the menu of Budget Managers, Budget Users, Register Users and Auditors (turning it off hides it and keeps the data).
  - **Budget Managers** create a fundraiser as soon as it is agreed — name, description and the event date(s); budgets
    can be added later. Up to one income and one expense budget per Fiscal Year, from at most two adjacent Fiscal
    Years: a Fiscal Year's budgets can be chosen once it is set up and open, when the event is inside it or within
    3 months of its start or end (e.g. preparation in November for a January event). A fundraiser for an event in a
    closed Fiscal Year cannot be set up; budgets of a closed Fiscal Year are frozen. Fundraisers can be archived, and
    deleted while nothing depends on them.
  - **What counts:** every active line allocated to the chosen budgets (a parent budget includes its sub-budgets),
    whatever its date; optionally only lines whose description contains a filter text (or matches a regular
    expression). Warnings for an "Other" budget, a parent budget, a filter and a budget shared with another fundraiser;
    the form previews how many lines will be included.
  - **Everyone with access** sees the fundraisers of a Fiscal Year (or *Upcoming — no Fiscal Year yet*) and each
    fundraiser's details: income, expenses, net and return, a per-Fiscal-Year breakdown, charts (cumulative income and
    expenses with the event marked; income vs expenses), every included transaction with a link to the Register, and
    the transactions' attachments.
  - Everything is recorded in the audit log. Database migration `0010` (additive).
- Register: a link can open a bank account's register with a search filled in (used by fundraiser lines).
- New dependency google-re2 (BSD) for regular-expression filters that can never hang the server.

## 1.5.0 — 2026-10-01
Polish of existing features and easier installation; nothing new in the data model except one per-user setting. Beta: test channel only.
- **Sign-in from a bookmarked page** (found testing 1.4.1): signing in — including two-step verification — now always
  happens on the dashboard address, so a bookmark such as `/about` or `/users` leads to sign-in, then two-step
  verification (or its setup), then the dashboard. A "two-step verification required" answer from the server shows the
  two-step screen instead of the login page.
- A page left open while the server is upgraded now reloads itself once to pick up the new version (API responses name
  the page build they belong to); the page itself is never cached.
- **HF-001** Right after setting up a new installation (or on a slow computer), the sign-in page could briefly appear
  and replace the security token of the new session, so the next action failed ("Missing or invalid CSRF token"). The
  page no longer flashes and a late sign-in token can no longer overwrite the session's token.
- **CR-028 Bank Accounts in two tables.** The Bank Accounts page shows *Checking & Savings* (CHECKING and SAVINGS
  accounts) and *Investments and Other* (every other type) as separate tables, each with a total of its active
  accounts. The dashboard's bank balances table uses the same two groups with a subtotal for each, then the total of
  all accounts.
- **CR-029 Preview the audit signature page.** With *Include audit review signature page* ticked, *Preview signature
  page* opens just that page as a PDF (with the chosen wording and signers) before the full report is generated.
- **CR-030 Charts fill the space.** Charts are placed in two columns that each fill from the top, so a short chart
  no longer leaves a gap next to a tall one (one column on narrow screens).
- **CR-032** The backup passphrase and its confirmation fields line up even when only one has a hint.
- **CR-031 Customize the dashboard.** Financial users and Auditors can choose which dashboard sections are shown and
  in what order: **Customize dashboard** → a checkbox and ↑/↓ buttons per section (Current Fiscal Year, Budget, Bank
  account balances, Attention, Charts and, for Auditors, Review summary). Saved for your account; **Reset to
  default** restores the standard layout. Database migration `0009` (one new column; existing users keep the
  standard layout).
- **CR-026 Windows: one file.** Every release has `Freedger-<version>-windows-x64.exe` — download and double-click
  (local mode, opens the browser; data stays in `%LOCALAPPDATA%\FinancialManagementPOC`). It is not code-signed, so
  SmartScreen may ask: *More info → Run anyway*. The portable .zip is still published. Before a release is published,
  the .exe and the .zip are started on a Windows machine and checked (health, version, web page, license).
- **CR-027 Linux: one command.** `curl -fsSL https://github.com/kretherford0983/Freeger/releases/latest/download/install.sh | sudo bash`
  installs or upgrades a server: it picks the newest production release (while in beta: the newest test
  pre-release, with a notice), verifies the checksums and runs that release's `install-server.sh` (same snapshot,
  rollback copy and untouched `config.toml` as before). `--channel`, `--version` and `--port` options; the port of an
  existing installation is read from its `config.toml`. See docs/deployment.md.
- **License: AGPL-3.0.** Freedger is now free software under the GNU Affero General Public License v3.0 (`LICENSE`).
  `THIRD-PARTY-NOTICES.txt` lists every bundled component with its license; both files are in every package. The
  sign-in page, My Account and System/About show the license and a *Source code* link to the exact commit of the
  build. Runtime dependencies, including indirect ones, are now pinned so packages contain exactly what the notices
  list (CI checks the notices are current).

## 1.4.1 — 2026-09-30
The rest of the 1.4 plan (decisions in docs/implementation-notes.md §1a). Beta: test channel only.
- **CR-016 Audit review signature page.** Reports → End of Year Audit → *Include audit review signature page* adds a
  last page with a blank date line, the wording and a signature line for up to five signers (individual Entities,
  each with an optional title, printed as "Jane Doe, Trustee"). Choose the built-in default wording, one of up to four
  saved wordings (shared by the organization, each with a Delete button) or new wording, which can be saved for future
  use. The variables {FY} (Fiscal Year dates), {ORG} (organization) and {FYE} (Fiscal Year end date) are filled in;
  unknown variables are refused. Saving and deleting wordings is recorded in the audit log.
- **CR-020 Dashboard charts.** The dashboard (financial roles and Auditors) has a *Charts* section for a chosen Fiscal
  Year: income by budget (donut), monthly expenses (bars) with income (line), expense budgets budgeted vs spent, bank
  balances at each month end (per account and total), expenses by budget (donut) and cumulative net. **Choose charts**
  shows or hides each chart; the choice is saved per user (default: the first three). Every chart has a tooltip on
  hover and a *Show data table* view. VOID transactions and transfers are left out; months follow the Fiscal Year.
- **CR-018 Two-step verification (MFA).** Sign-in asks for a 6-digit code from an authenticator app after the
  password. Setup shows a QR code and a key to type in by hand, then 10 one-time **recovery codes** (shown once; new
  ones only by setting it up again). **On a server install it is required for every user** — everyone is asked to set
  it up at their next sign-in; on a local (desktop) install it is optional. "Trust this browser for 30 days" skips the
  code on a private computer. My account → *Two-step verification*: change authenticator, remove trusted browsers.
  Users (Administrator): *Reset two-step* (reason required). A locked-out sole Administrator can be reset on the
  server with `FinancialManagementPOC reset-mfa --user NAME`. Passkeys follow in 1.6.
- **CR-023 Backup.** System/About → *Backup / Restore* (Administrators): one encrypted `.fmbak` file with the
  database, all attachments and the encryption key (not `config.toml`), protected by a passphrase you choose.
- **CR-025 Restore.** Upload a backup, enter its passphrase, your password and `RESTORE`: the current data is replaced,
  kept as a safety copy in `pre-restore/`, the application reloads itself and everyone signs in again with the
  accounts from the backup. Progress is shown step by step; any failure leaves (or puts back) the current data.
- **CR-024 Restore when setting up.** The initialization wizard offers *Restore from a backup instead*, to move an
  installation to a new server. See docs/backup-restore.md.

Upgrade notes: database migrations `0006` (table `signature_template`), `0007` (column `app_user.dashboard_charts`)
and `0008` (tables `user_mfa`, `mfa_recovery_code`, `trusted_device`; column `auth_session.mfa_pending`) are
additive. Users already signed in stay signed in; on a server install each user sets up two-step verification at their
next sign-in (have your phone ready when you first sign in after the upgrade). New folders in the data directory:
`backup-work/` (temporary) and `pre-restore/` (safety copy after a restore).

## 1.4.0 — 2026-09-30
Change requests CR-017, CR-019, CR-021 and CR-022 (decisions recorded in docs/implementation-notes.md §1a). The rest of
the 1.4 plan — audit signature page (CR-016), MFA (CR-018), dashboard charts (CR-020) and backup/restore
(CR-023 … CR-025) — follows in **1.4.1**. Beta: pre-release on the test channel only (no production release is
planned before 1.6).
- **CR-017 Documentation review.** A transaction (or split allocation) marked "no attachment will be provided" **with a
  reason** now counts as documented: it no longer appears in the Fiscal Year documentation review, the closing
  warnings or the dashboard count. A mark without a reason is still listed. Transfers (which carry the reason
  "Internal transfer between accounts") are no longer listed.
- **CR-019 Income budgets.** An income budget that received more than budgeted shows **+$X above budget** in green
  (Budgets page, dashboard, budget selector and the PDF reports) instead of a negative remaining amount, and is no
  longer an "over budget" closing warning. Expense budgets are unchanged.
- **CR-021** The dashboard's bank account balances show a **Total** of all listed accounts.
- **CR-022** **My account → About** shows the application version and build (e.g. *test build #12*) to every user.
  System/About (Administrators) shows the same plus the bind address; other users no longer receive the bind address
  and port from the About API.

## 1.3.0 — 2026-09-29
Change requests CR-007 … CR-015 (decisions recorded in docs/implementation-notes.md §1a):
- **CR-007 Fiscal Year document types.** Fiscal Year documents are *Approval document*, *Audit Signoff* or *Other*.
  Approving a Fiscal Year needs an Approval document — or the "No approval document" mark (strong warning, optional
  reason), which is then a Fiscal Year review warning. Closing needs an Audit Signoff (an "other" document no longer
  counts) and an Approval document unless the mark is set. Budget Managers can change a document's type while the
  year is open (audited); uploading an Approval document clears the mark automatically.
- **CR-008 Fiscal Year Close report.** New PDF on the Reports page: the audit report with the Fiscal Year documents
  placed after the Fiscal Year review and before the budgets and transactions. A copy is generated automatically when
  the year is closed and kept as a permanent, system-generated Fiscal Year document (if it cannot be produced the
  closing is not performed). The End of Year Audit report no longer includes the Fiscal Year documents.
- **CR-009** Split-allocation attachment lists and PDF captions are labelled "<Entity> - <Budget>"
  (e.g. "Bob Smith - 4000 Donations"; the transaction's entity is used when the allocation has none).
- **CR-010** Files can be attached while entering or editing a transaction — for the transaction and for each split
  allocation. They upload right after saving; any file that fails is named and can be added again from the register.
- **CR-011 Duplicate protection.** Every form is locked with "Saving…" while it saves; each create form sends a
  one-time request key so a repeated submit returns the record already created; a *possible duplicate* confirmation
  appears for a transaction with the same account, date, type, amount and entity. A check number can be used only once
  per account — voided checks keep their number. A wrongly entered number on a VOID record is fixed with
  **Correct check number…** (clear or change, reason required, audited, noted on the record).
- **CR-012 Missing check review.** Register → Fiscal Year reviews lists gaps in each account's check sequence (from
  the lowest to the highest recorded number; VOID records count as recorded). Resolve by entering the transaction,
  recording a zero-dollar VOID for the number, or "Confirm not missing" with a note. Gaps are a closing warning only.
  Check numbers repeated before 1.3 are listed for clean-up.
- **CR-013** The top bar and left navigation stay in place; only the page content scrolls.
- **CR-014** The left navigation collapses to icons («/»); the choice is remembered per user.
- **CR-015** The register header (title, account, buttons, filters, balances) and the column headings stay on screen
  while scrolling (normal scrolling on very small windows).

Upgrade notes: database migration `0005` is additive (new tables `request_key`, `check_number_acknowledgement`; new
columns on `attachment`, `fiscal_year`, `app_user`). Existing Fiscal Year documents become "Other": before closing an
open Fiscal Year, mark its signoff document as **Audit Signoff** (and its approval document as **Approval**).
`config.toml`, the key and attachments are not touched. See docs/upgrade.md.

## 1.2.1 — 2026-09-29
Corrections requested by the product owner after reviewing 1.2.0:
- **CR-002 — End of Year Audit PDF layout.** Page 1 is a title page; page 2 is the *Fiscal Year Review*
  introduction (activity summary per account, closure readiness, documentation review); pages 3–n list the budgets;
  then **every transaction gets at least one page** with its headline fields at the top — *Transaction date, Entity,
  Transaction type, Amount, Description, Clear Date, Notes* — and **each attachment reproduced underneath, scaled to
  the 8.5×11 page width** (images drawn; PDF attachments embedded page by page as vector content, landscape/legal
  pages scaled to fit). Every page of the report is US Letter. The transaction index page was removed. The Entity
  activity report and its CSV are unchanged.
- **CR-003 — Transfers.** The transfer form has an **Entity** field; the generated descriptions read
  `Transfer to|from <masked account> for <selected Entity>` (the organization/workspace name when no Entity is chosen),
  and the Entity is recorded on both legs. Legs remain locked together (voiding one voids both) as before.
- **CR-005 — Split documentation rule** is now exactly: if the transaction (parent) has **no** attachment **and** is
  not marked "no attachment", every allocation (child) needs an attachment **or its own "no attachment" mark**;
  if the parent has an attachment or the mark, the allocations need neither and are not reviewed.
  Split allocations therefore get their own **"No attachment will be provided for this allocation"** checkbox
  (with the same warning and optional reason); uploading a file to that allocation clears it automatically.

Upgrade notes: database migration `0004` **adds** four columns to `transaction_allocation` (per-allocation
no-attachment flag, reason, who/when); existing rows are not changed. `config.toml`, the key and attachments are
untouched. See docs/upgrade.md.

## 1.2.0 — 2026-09-29
New features (change requests CR-002 … CR-006):
- **Reports** (new menu item for all financial roles and Auditors):
  - *End of Year Audit report* — one printable PDF: Fiscal Year budget (Q1–Q4, actuals, remaining), closure/review
    summary, transaction index, then **every transaction of the year on its own page followed immediately by its
    attachments** (images rendered, PDF attachments merged page-for-page, SHA-256 verified), then the Fiscal Year
    supporting documents. Options: one account or all, include/exclude VOID. Generation is audited.
  - *Entity activity report* — deposits and withdrawals per entity for an account (or all accounts) and date range,
    with per-transaction detail, print view and CSV export. Transfers are shown separately.
- **Transfers** — "Transfer…" button in the Register records a withdrawal in the source account and a deposit in the
  destination account (linked; descriptions generated as `Transfer to|from <masked account> for <organization>`;
  Budget 0, so budgets are unaffected). Voiding either side voids both; per-side clear date and notes stay editable.
- **Searchable entity picker** in the transaction form (type to filter by name or Entity Number; keyboard friendly).
- **"No attachment will be provided" checkbox** on transactions, with a warning when ticked and an optional reason.
  Adding an attachment later clears the mark automatically (audited).
- **Documentation review** on the Fiscal Year page, in closure-readiness warnings, on the dashboard and in the audit
  report: transactions without supporting attachments and transactions marked "no attachment". Warnings only —
  never a blocker for approval or closure.
- Budget 0 is now shown as inflows/outflows (transfers post both directions).

Upgrade notes: database migration `0003` adds columns only (existing rows untouched). New runtime libraries:
reportlab, pypdf (bundled in the packages). See docs/upgrade.md.

## 1.1.1 — 2026-09-28
- **CR-001 (change request): correct the Transaction Date of a VOID transaction.** Register Users can use
  **Register → expand a VOID row → Correct date…** (API `POST /api/transactions/{id}/void-date`). Only the date changes;
  the record stays VOID with zero balance/budget effect and the change is audited (`TRANSACTION_VOID_DATE_CORRECTED`).
  For a zero-dollar VOID accountability record, its protected Budget 0 allocation follows the new date's Fiscal Year.
  Closed Fiscal Years stay immutable (a record in a closed year cannot be changed, and a record cannot be moved into one).
- Zero-dollar VOID records dated inside a Closed Fiscal Year are now refused instead of attaching to the nearest open year.
- New portable Linux build (`packaging/build_linux_portable.sh`, glibc ≥ 2.27) and server installer
  (`packaging/linux/install-server.sh`).
- No database schema change (no new migration); existing data, `config.toml` and the encryption key are untouched by the upgrade.

## 1.1.0 — 2026-09-28
- Initial implementation of the benchmark v1.1 POC.
