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

**Budgets from before PennyWarden.** **Budgets → Before PennyWarden…** lists your budgets as they were in the old
spreadsheets — code, name, Income or Expense — with their years. A budget in PennyWarden shows those years once it
**continues** one of them. The link is something you choose; it never goes by code. That covers:
- a budget that **continued into PennyWarden** — the usual case;
- a budget that **stopped** before PennyWarden — it stays in the list, and if it comes back (say a bowling tournament
  that ran in 2022 and 2023 and returns in 2027), create the new budget and choose it under **Continues → Before
  PennyWarden**. The 2027 Budget Review then shows 2022 and 2023, and its average counts only those years;
- a budget that **skipped years** — just enter the years it ran;
- a **different numbering**: in PennyWarden the fundraisers may be *100* with sub-budgets *100-01, 100-02*, where the
  old sheets had *100, 101, 102*. Link old 101 to 100-01, old 102 to 100-02 — any level works — and old 100 to
  **100-00 (Other)** if that row held the amounts not tied to one fundraiser;
- a **code that was reused** for a different budget (100 was Bowling, then Golf Outing): link each old budget to the
  right one. If old figures ended up on the wrong budget, **Unlink** them, rename the old budget, and link it where
  it belongs — nothing has to be entered again.

**Finding one in the list.** Search by code, name or the budget that continues it, filter by **Type** (Income or
Expense) and **Continued** (continued or not), and click a column heading to sort by it (again to reverse; *Years*
sorts by the latest year entered). **Clear** puts the search, filters and sort back to how the list opens (by Code).
Every financial role and Auditors can open the list; only Budget Managers add or change budgets from before
PennyWarden.

Budget Managers add, link, correct and retire them; everyone else with access to Budgets (and Auditors) can look.

**One year at a time.** Open a budget's **History** (every budget has one for Budget Managers, Other too) and choose
**Add an earlier year**: the Fiscal Year (include the year, for example *FY2021*), what was **budgeted**, what was
**actually** spent or received, and an optional note such as *from the 2021 treasurer's spreadsheet*. The first time,
PennyWarden creates the budget from before PennyWarden (with this budget's code and name — rename it if it was called
something else) and links it. If the budget was called differently that year, open **Called differently that
year?** and enter that year's code and name. The History also shows which budget from before PennyWarden it
continues, with **Link…**, **Change…** and **Unlink**.
- Only years **before your first Fiscal Year in PennyWarden** can be entered; later years come from PennyWarden itself.
- **Correct** fixes a typo (a reason is required); **Retire** takes an entry out (a reason is required). A whole budget
  from before PennyWarden can be retired too. Nothing is deleted, and every change is in the audit log.
- Enter the figures at whatever level your spreadsheet has. A budget without its own figure for a year shows the
  **sum of its sub-budgets'** (and its Other's). If you enter both and they don't add up, the History and the Budget
  Review say so.

**Many years at once.** **Budgets → Import earlier years…** takes a CSV file with one row per budget per year and the
columns **budget code, type, former code, former name, year, budgeted, actual, note, line**:
- **budget code** — the budget of the Fiscal Year you're looking at that continues it (*100-00* for a parent's Other).
  Leave it empty for a budget nothing continues; then fill in **type** (Income or Expense).
- **former code** and **former name** — what it was called that year (empty: the same as the budget).
- Rows with the same budget code are one budget, even if the old name changed over the years. Without a budget code,
  rows with the same former code are one budget. If an old budget was renumbered, give its rows the same **line**
  (any word, for example *carwash*).

**Download the template** to get the year's budgets ready to fill in; rows you leave empty are skipped. Choose
**Preview** to see, before anything is saved, each budget from before PennyWarden (*New* or existing), which budget
will continue it (*New link*), and each row — *will be saved*, *duplicate* (already entered, or twice in the file) or
*refused* with the reason. Then **Import**.

**Where they show.** In the budget's History and in the **Budget Review** (on screen, in the PDF and the CSV, and in
the review you can add to the Planning Sheet), after your PennyWarden years, with the column marked *entered* (and
*as 104 Raffle Fundraiser* where the budget was called differently that year). They never change actuals, the
registers or the Fiscal Year closure, and they are not in the dashboard charts. A budget from before PennyWarden that
nothing continues isn't in a year's Budget Review yet.

## Reports: comparisons to a date before any data

When a Financial Flow Report compares balances with a date before an account has any data in PennyWarden, the report
uses the account's **earliest data** instead of $0 — its first dated balance, or for a register account its opening
balance — so the Change column shows real growth, not the whole balance.

- On the review screen each such account is listed with ⓘ. Hover over (or tab to) it to see how to give the account a
  real balance on that date: *Update balance* with that date (accounts without a register), or an earlier Opening
  Balance Date (register accounts).
- The option **Show notes on substituted starting values** (off by default) prints a note for each one under the
  balances, for example: *Savings: starting balance is the first recorded balance, 2026-07-01 (no data on
  2026-01-01).* With the option off the PDF stays clean.

### Account opened (Budget Managers)

*Edit* a bank account to set **Account opened** when the account really was opened after PennyWarden was set up.
Dates before it count as $0 (the account didn't exist), the report doesn't list it for a Through Date before then, and
the dashboard balance charts start there. Leave it blank if the account existed before PennyWarden.

## Donations: before the deposit, and items (Donations module)

**Donations** is now in the navigation when the module is on. Register Users record and print there; the other
financial roles and Auditors see it.

### A receipt before the money arrives
1. **New donation**: choose the donor, then one or more lines — the amount, an optional purpose and any goods or
   services given in exchange. The **Est. received date** is optional.
2. **Save**, then **Print receipt**. As the money hasn't come in yet, the receipt prints *Date received:
   ________________* to fill in by hand when the donation is handed over. The printed copy is kept with the donation.
3. When the money is deposited: **Create transaction**, tick the donation(s), choose the bank account and
   **Continue**. The deposit form opens with one allocation per donation — donor, amount and description filled in.
   Choose the budget(s); **Split this donation** spreads one over several budgets (its allocations must add up to its
   amount). Enter the date received if the donation had none (empty = the deposit's date) and save. The deposit is
   linked to the donations and their printed receipts are attached to it.

Until it is deposited a money line shows **Awaiting deposit** (a filter with a count on the Donations page). Once
linked, the deposit decides: changing its amount in the register changes the donation, and the next receipt prints as
*Corrected*.

### Items (not money)
Tick **Item (not money)** on a line for a physical gift — a TV, auction goods. The receipt lists items **by
description only**, never a value, and prints a note about it (Donations Setup can adjust the wording); its total
covers money only. The amount box becomes *Estimated value for our records (not printed)*; leave it empty and the
donation shows *Value not entered* until you enter an estimate or tick **No value will be provided** with a reason.
Tick **Received** with the date when the item is handed over. Items received in a Fiscal Year are listed in the Audit
and Close reports under **Non-cash donations received**.

### Changing, voiding and cancelling
- A line received in a Closed Fiscal Year can't be changed, like the register.
- Voiding a deposit created from the Donations page *unlinks* its donations: they show *Awaiting deposit* again and
  their receipts stay valid. (Receipts of donations marked on a deposit in the register are void with the deposit, as
  before.)
- A donation that never happens is **Cancelled** with a reason, as long as nothing of it is received. Its receipts are
  void; nothing is deleted.

### Donations Setup (Administrators)
**Note when a receipt lists items**: empty prints the default wording (shown in grey); **Default wording** puts it in
the box to edit. Your own wording needs at least 8 words (a `{VARIABLE}` counts as one).

**Window envelope and fold marks**: as on a cover letter, the receipt can carry the addresses for a #10
double-window envelope (*On the receipt*, or *On a separate address page*), with or without the organization's address
in the upper window, and fold marks on the front or on the back (two-sided printing). A window receipt needs no
envelope, so the print screen hides that step (*Print an envelope anyway* brings it back).

**Envelopes**: the envelopes used for Donations. **New #10 envelope** makes one for Donations; **Add to Donations**
uses one of the other templates (for example Payments' envelope) as well. See *Envelopes: one library* below.

### Printing the donor's envelope (Register Users)
After printing a receipt (on the Donations page or in a deposit's *Donation receipt…* dialog), the **Envelope** step
offers the envelopes used for Donations, the default first. Tick or untick **Print the return address**, use **Test on
plain paper** to check where the address lands (not kept), and **My envelope printer settings** to move the print by
up to 1/4 inch. The printed envelope is kept with the donation and on its deposit. With no envelope set up for
Donations the step says so; an Administrator adds one in Donations Setup.

## Year-end giving statements and the donor report (Donations module)

### Year-end statements
Donations page → **Year-end statements**: choose the **year** (and, if you like, a **minimum total**, e.g. 250). The
list shows each donor with donations **received** in that calendar year — money deposited in the register and items
ticked Received — their money total, gifts and items, and their statement. Donations that were cancelled, deposits
that were voided and money still awaiting a deposit are not on it.

- **Open** a donor to see the year's donations, **Preview** the statement and **Print** it (Register Users). Items
  are listed by description only; the total covers money only.
- **Print all** prints a statement for every donor in the list as one PDF, asking once to confirm.
- Each printed statement is kept and numbered per year, *S-2026-0001*. Printing it again with the same content prints
  a **Duplicate**; if a donation of that year changed, a **Corrected** statement with a new number replaces it.
- After printing, the **Envelope** step prints the donor's envelope, as for receipts.
- Budget Managers, Budget Users and Auditors see the statements and open the printed copies.

### Donor report
Donations page → **Donor report**: each donor's money received per calendar year (up to 5 years side by side) and
the total, the number of gifts, the last gift, and items with their estimated value (for your own records — never
printed on a letter to a donor). Click a donor to see their donations. Filter by years, donor and minimum total, and
download it as **PDF** or **CSV** (tick *With each donation* to include the detail lines).

### Donations Setup: the statement letter (Administrators)
**Year-end statement letter**: the title, salutation, text and closing. Put `{DONATION_TABLE}` in a paragraph of
its own where the table of the year's donations goes (without it, the table prints after the text); `{YEAR}`,
`{TOTAL}` and `{STATEMENT_NO}` are also available. The layout, window envelope, fold marks and signer are the
receipt's. **Show the statement preview** and **Test print the statement** use sample data only.

### Fundraisers: donation buckets
Mark a fundraiser bucket **Donations** (New bucket / Edit bucket). Deposits classified into it then start with the
**Donation** box ticked in their *Donation receipt…* dialog — a suggestion: it is saved only when you Save. The
fundraiser page lists **Donations without a receipt**; **Print receipts** opens each deposit in the register.

## Entities: names, display name and mailing address

- **First name** and **Last name** replace *Primary Contact* (for an Organization they are its contact person). An
  Individual needs a first name; the last name is optional.
- **Display name same as Name**: untick it to give the entity a display name (for example a nickname or a shorter
  name). The register, pickers, lists and reports show the display name; checks, envelopes, letters, receipts and
  year-end statements print the name.
- **Mailing address same as Address**: untick it to add a mailing address (for example a P.O. Box). Letters,
  envelopes, receipts and statements are addressed there. The organization profile (System/About) has a mailing
  address too.
- **EIN** for organizations, written as 12-3456789.
- Searching finds an entity by its name, display name, first or last name.
- **Names to review** (Budget Managers): after the upgrade, each Primary Contact was split into a first and a last name
  at the first space. Names like "Mary Ann Smith" or "John Smith Jr." may need fixing: **Edit** one, or **Confirm** it
  when it is right. Saving an entity's names also takes it off the list.
- **My account → Show people's names as**: *First Last* or *Last, First* — how Individuals show and sort for you in
  the Entities list and the entity pickers.

### Template variables by role and the addressee block (Administrators)
Letters, envelopes, checks and stubs can use `{PAYEE.NAME}`, `{PAYEE.FIRST_NAME}`, `{PAYEE.MAILING_ADDRESS}` and the
other `{PAYEE.*}` fields; receipts and statements the same `{DONOR.*}` fields. Type `{` for the list, grouped by role.
A cover letter's **Addressee** section (Payments Setup) and the receipt's **Addressee** section (Donations Setup)
set the lines of the addressee's block — up to six, for example `Attn: {PAYEE.FIRST_NAME} {PAYEE.LAST_NAME}`. The
default, name and mailing address, prints as before.

## Envelopes: one library (Administrators)
Envelope templates are one library shared by Payments and Donations. Each template is *used for* the features you
choose, and each feature has its own default. **Envelopes** in the navigation (shown when Payments or Donations is on)
lists every template with what it is used for: **Use for …** / **Remove from …**, **Make the … default**, **Edit**,
**Deactivate**. Payments Setup and Donations Setup list their own envelopes and can remove only their own use.

- Removing a feature from its default envelope asks which envelope it uses from now on. Removing it from its last
  envelope leaves that feature with no envelope: printing an envelope is hidden there.
- An envelope no feature uses stays on the Envelopes page as *Not used*. Templates are never deleted, because printed
  copies refer to them.
- Editing an envelope another feature also uses shows *Also used for …: changes apply there too*. **Duplicate for …
  only** makes a copy for the feature you are setting up and moves that feature (and its default) to the copy.
- Your *My envelope printer settings* belong to the template, so they apply wherever it is used.
- After upgrading, every existing envelope is used for Payments and Payments keeps its default.

## Organization branding (Administrators)

**System/About → Branding** gives generated reports and presentations your organization's look: every PDF report,
the fundraiser report and presentation, and the Fiscal Year fundraising report and presentation. Checks, cover
letters, receipts and envelopes keep their own design.

- **Palette.** Choose one of the ready-made palettes (PennyWarden, the default; Forest; Ocean; Plum; Ember), or
  **Custom**: enter your **primary** and **secondary** colors and choose **Generate recommended palette**. PennyWarden
  works out a full Material 3 palette from them — the colors for headings, title bands, tiles, table headers and
  lines, and eight chart colors. Open *Color roles* or *Chart series colors* to change any of them.
- **Checks while you choose.** Every text color must be readable on the color it sits on (WCAG AA, at least 4.5:1);
  a color that fails is named and **Save branding** stays unavailable until it is fixed. Chart colors that are hard to
  tell apart get a warning; you can still save, because charts always keep their labels and legends.
- **Live preview.** The sample page on the right shows the palette, the logo and the footer as you change them.
- **Logos.** A **full logo** (report headers and title slides) and an optional **small mark** (footers of reports and
  slides; without it, none is printed). PNG or JPEG, at most 2 MB; PennyWarden re-saves the picture without its
  hidden details (metadata). Adding or removing a logo takes effect at once.
- **Footer text** (optional): one line, up to 120 characters, printed at the bottom of every report page and slide.
- **Reset to the PennyWarden palette** puts the colors back; the logos and footer text stay.

Branding is included in backups and can be restored on its own (**Settings → Branding** under *What to restore*). A
reinitialize keeps it, like the organization name.

## Backup and restore (Administrators)

### Choose what to restore
**System/About → Backups → Restore** works as before up to the passphrase, your password and *RESTORE*. Once the
backup is checked, **What to restore** opens with everything ticked (**All**). Choose *show the parts* to untick what
should stay as it is now:
- **Data** — all the financial records and attachments, always together;
- **Settings** — General, Backups, Payments Setup, Donations Setup and Branding, each on its own;
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
