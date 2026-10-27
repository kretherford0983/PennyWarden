# What's new in 2.2 — quick guide

*2.2.0 is in progress. The full list is in the [changelog](../CHANGELOG.md).*

## Signing in and passwords

### A wrong password is cleared
When a sign-in is refused (a wrong username or password, or too many attempts), the **Password** field is emptied and
the cursor is put back in it, so you can type the password again straight away. The username stays as you typed it.

### The password requirements, ticked off as you type
Under **My account → Change password** the requirements are listed beside the fields before you start:
- at least 12 characters (at most 128);
- at least one letter and one digit;
- not the same as your username;
- different from your current password;
- *New password* and *Confirm new password* are the same.

Each requirement is **red** until it is met and turns **green with a check mark** once it is. If the change is still
refused (for example, the current password was mistyped), everything you typed stays in the fields.

The same list is shown wherever a new password is chosen: after signing in with a temporary password, under
*Forgot password?*, in the first-run Initialization Wizard, and when an Administrator creates a user or resets a
password. After a temporary password, "different from the temporary password" is checked when you save.

## Two-step verification

### Keep the authenticator you already have
When two-step verification is set up again — for example after an Administrator (or the server command
`reset-mfa`) reset it — you don't have to scan a new QR code. Under the key shown on the setup screen, open **Use my
own key instead** and enter the key from the PennyWarden entry already in your authenticator app, or paste an
`otpauth://totp/…` link exported from the app, then **Use this key** and enter the app's current code as usual.
- The key must be at least 16 characters (letters A–Z and digits 2–7; spaces and lower case don't matter). Keys
  shorter than PennyWarden's own (32 characters) work, with a note.
- Links for codes other than 6 digits every 30 seconds (SHA-1) can't be used.
- Nothing is saved until the code matches, and you get a **new set of recovery codes** as on every setup.
- **Reuse a key only if it was never exposed.** After any security problem use the new key PennyWarden shows.

### Administrators: *Possible compromise*
**Users → ⋯ → Reset two-step** has a **Possible compromise** checkbox. Tick it when the authenticator key may have
been exposed (a stolen phone, a security problem): the user then has to set up with a **newly generated** key, and
*Use my own key instead* explains why it isn't available. On the server command line the same is
`pennywarden reset-mfa --user NAME --compromised` (with `sudo` and `--data-dir` as usual). The audit log records
whether a reset was marked and whether a setup used an own key — never the key itself.

## Budgets (Budget Managers)

### Years before PennyWarden
Your budgets probably have years of history in spreadsheets from before you started using PennyWarden. You can now
enter those years so the History and the Budget Review show the whole picture.

**One year at a time.** On **Budgets**, every budget now has a **History** link for Budget Managers. Open it and
choose **Add an earlier year**: the Fiscal Year (include the year, for example *FY2021*), what was **budgeted**, what
was **actually** spent or received, and an optional note such as *from the 2021 treasurer's spreadsheet*. The year
appears at the top of the History, marked **Entered**.
- Only years **before your first Fiscal Year in PennyWarden** can be entered; later years come from PennyWarden itself.
- **Correct** fixes a typo (a reason is required); **Retire** takes an entry out (a reason is required). Nothing is
  deleted, and every change is in the audit log.
- Enter the figures at whatever level your spreadsheet has: on a budget, on its sub-budgets, or both. A budget
  without its own figure for a year shows the **sum of its sub-budgets'**. If you enter both and they don't add up,
  the History and the Budget Review say so.
- A renumbered budget keeps its entered years: they follow the *Continues* links.

**Many years at once.** **Budgets → Import earlier years…** takes a CSV file with the columns **year, budget code,
budgeted, actual, note** (one row per budget per year). **Download the template** to get every budget code of the
Fiscal Year you're looking at. Choose **Preview** to see what will happen to each row — *will be saved*, *duplicate*
(already entered, or twice in the file) or *refused* with the reason — then **Import**. Only the rows that will be
saved are saved.

**Where they show.** In the budget's History and in the **Budget Review** (on screen, in the PDF and the CSV, and in
the review you can add to the Planning Sheet), after your PennyWarden years, with the column marked *entered*. They
never change actuals, the registers or the Fiscal Year closure, and they are not in the dashboard charts.

## Backup and restore (Administrators)

### Choose what to restore
**System/About → Backups → Restore** works as before up to the passphrase, your password and *RESTORE*. Once the
backup is checked, **What to restore** opens with everything ticked (**All**). Choose *show the parts* to untick what
should stay as it is now:
- **Data** — all the financial records and attachments, always together;
- **Settings** — General, Backups, Payments Setup and Donations Setup, each on its own;
- **Reminders**;
- **Users** — passwords, two-step verification, security questions, preferences.

**Review** lists what will be replaced and what is kept; nothing has changed yet. Then **Restore the chosen parts**.
Everyone is signed out, as with any restore.

Three common cases:
- **Bad entries in the data.** Restore **Data** only: users keep their current passwords and authenticators, settings
  stay as they are, and the audit log still shows what happened.
- **A test server back to its starting point.** Back it up before testing, then restore **Data** only afterwards.
- **Moving to a new server.** Restore **Settings and Users** first so a few people can try it, then **Data and
  Reminders** from a fresh backup at the switch. If someone was added on the old server in between, the restore offers
  to add them.

If you restore Users but not Data, people added after the backup are kept but switched off (inactive); the restore
lists them so you can switch them back on.

## Testing mode (for whoever runs the server)

To try new releases or settings without touching your real data, install PennyWarden a second time as a **test server**
and add `testing_mode = true` to the `[server]` section of its `config.toml` (then restart it; on Linux
`sudo pennywarden apply-config`). Every page then shows a **TESTING MODE** banner, and Administrators get
**System/About → Testing**:
- **Scheduled backups:** set when the next one runs, or *Run as if due now*; *Retry the failed backup now* instead of
  waiting for the retry; move earlier runs back by some days to watch the daily/weekly/monthly retention at work.
- **Backup reminder:** set the time of the last successful backup to make the "no backup for N days" warning appear.
- **Reinitialize:** clear the 24-hour cooldown.
- **Reminders:** move an organization reminder's due date, for example into the past so it shows now.
- **Updates:** check for updates now.

Nothing financial changes and the real clock keeps running. A backup made on the test server can't be restored onto
your main server from the app (it is marked as a test backup); restoring your main server's backup onto the test server
works as usual — that is the easy way to give the test server real-looking data. Local installs ignore the setting for
now.

## Try the demo

Want to show PennyWarden to someone before they set up their own organization? Each release has a demo file with a
made-up band boosters club. Install PennyWarden, choose **Restore from a backup instead** on the first screen, pick the
demo file and enter `pennywarden demo`, then sign in as `demo-admin`, `demo-budget`, `demo-register` or
`demo-auditor` (password `Demo-PennyWarden-2026`). Changes are undone when PennyWarden restarts or with **Reset demo
data**; **Remove the demo and start fresh** clears it away for real use. Details: [docs/demo.md](demo.md).
