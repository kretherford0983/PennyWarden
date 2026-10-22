# What's new in 2.1 — quick guide

*2.1.0: fundraiser reporting (a stakeholder report as PDF or Word, a slide deck, fundraisers across years with
year over year, and a Fiscal Year fundraising report), the Budget Review and the Fiscal Year Planning Sheet, electronic
payments and other register improvements, fold marks on cover letters, more voucher check layouts, and the optional
Donations module for donation receipt letters. The full list is
in the [changelog](../CHANGELOG.md).*

## Register

### Sort by Date or Cleared
Click the **Date** or **Cleared** heading to sort the register by it; click it again to reverse (▲ oldest first,
▼ newest first). PennyWarden remembers your choice, in any browser — other users keep their own.
- **Sorted by Cleared**, transactions that haven't cleared yet come after the cleared ones (first when newest first),
  and the balance column becomes the **Cleared balance**: the bank balance after each cleared item, which is what your
  bank statement shows. It is blank on uncleared rows.
- Transactions with the same date stay in the order they were entered.
- **Reset to default** (shown under the filters when you have changed the sort) goes back to Date, oldest first.

### Attachments filter: Yes, Missing, Marked
- **Yes** — transactions with at least one attachment (as before).
- **Missing** — exactly what the Fiscal Year documentation review (and the closing warnings) will flag: no attachment
  and no mark, or *No attachment will be provided* without a reason. A badge says which. Bank interest or a direct
  deposit marked *No attachment will be provided* **with a reason** is not missing any more.
- **Marked** — everything marked *No attachment will be provided*, with or without a reason (without a reason it is
  under Missing too).

### Electronic payments
For a bill paid by **ACH / bill pay, debit card, wire or a vendor's online portal**, tick **Electronic payment (no
physical check)** on the withdrawal and choose how it was paid. If there is a number, say which kind:
- **Check # from our sequence** — when a bill-pay service uses a number from your checkbook. It counts in the
  missing-check review, so the gap it fills isn't reported as a missing check.
- **Payment reference** — the bank's or vendor's confirmation number. It never counts as a check number, so it can't
  create false "missing check" warnings.

The register shows an **Electronic** badge, and the **Payment** filter lists checks, electronic payments, or
withdrawals with no check number. The Audit and Close reports show *Electronic (method)* where the check number would
be. With the Payments module, an electronic payment is saved without printing a check — see
[check-printing.md](check-printing.md#for-register-users-payments).

### Reorder attachments
On a transaction, each allocation of a split, a fundraiser, or a Fiscal Year's **Other documents**, click
**Reorder…**, drag the files by their handle (or use ▲ ▼) and **Save order**. That order is used on screen and in the
Audit, Close and fundraiser reports — put the invoice first, then the receipt, then the approval, for example. New
files go to the end. The order of a closed Fiscal Year can't be changed. Register Users reorder transaction
attachments, Budget Managers the Fiscal Year documents, and whoever manages a fundraiser its documents.

### Deleting a transaction frees its check number
When a Register Admin deletes a transaction that had a check number, the number becomes free again for another
record. If it isn't reused, the missing-check review shows it until it is entered or confirmed "not missing". If a
check was printed for that transaction with the Payments module, deleting is refused: void it, or mark the check
spoiled first. (A VOID record keeps its number, as before.)

## Budget planning (Budget Managers)

### Budget Review
**Reports → Budget Review** (called *Budget Prep* in the first test builds). Choose the Fiscal Year and how many
earlier years to show (or *All linked years*), then **Run report**. Each budget is a block, laid out like a budget
review spreadsheet: its name, then a **Budgeted**, an **Actual** and a **Difference** row, with the years across. The
difference is in dollars and percent, with *over* or *under* in words (*n/a* when nothing was budgeted). **Avg** is
the average of the earlier years shown, counting only the years the budget existed (the current year isn't
included, since it isn't finished).
- **History follows the budget links** (*Continues* on a budget, set when a budget is copied into the next year or by
  hand). A budget that was renumbered stays on one line; its earlier code is shown in that year. A year with no linked
  budget shows —. A sub-budget without a link of its own says *history on parent*; *Other* follows its parent.
- **The current year** shows the actual **year-to-date** as of the date you choose (today by default).
- **Projected column** (optional): the average monthly activity so far, carried to the end of the Fiscal Year. For
  example, $300 spent in the first three months projects to $1,200. With less than a month gone it says *too early to
  project*.
  - Untick a budget that is **complete** — a fundraiser that is over and will receive nothing more — and it shows
    *Complete: no projection* (its YTD figure).
  - Budgets of fundraisers that have ended, were cancelled or archived start unticked.
  - Your choices are remembered for that Fiscal Year (other Budget Managers have their own) and are also used by the
    Planning Sheet.
- **Next year's budget** (optional): the budget of the next Fiscal Year that continues each one, its status and the
  change.
- **Budgets:** all, one parent budget with its sub-budgets, or a single budget (the PDF then adds a chart of budgeted
  and actual per year).
- **Open PDF** (landscape), **Download PDF** or **Download CSV**.

### Fiscal Year Planning Sheet
On the **Fiscal Years** page, **Planning sheet…** prints the form for the budget planning meeting — usually before
next year's Fiscal Year is even created. PennyWarden works out which year is being planned (one at a time): if a
**Draft** Fiscal Year exists, it plans that year from the year before it; otherwise it plans the year after the
current one, with the new year's name and the Proposed column left blank. The dialog says which. The sheet is in
portrait, on as few pages as possible:
- **page 1:** the organization, the current and the new Fiscal Year, attendee lines, and the meeting date (top right).
  Then the **Income** and **Expense** tables: Budget Code, Budget Description, Previous Budgeted, Actual YTD (dated),
  Projected, and a blank **Proposed Budget**, plus four blank rows for new budgets;
- **the last page:** more blank Income and Expense tables.

If the next Fiscal Year already exists as a **Draft**, the sheet fills in its name and dates and shows each draft
amount as *Proposed* — on the row of the budget it continues, or of the budget with the same code if it was entered
by hand — with a blank **Proposed Revision** column to write changes in. A renumbered budget shows the
draft code with the previous code under it. A new draft budget is marked *new in draft*, and a current budget that
isn't in the draft is marked *not in draft*. If the Income table ends low on a page, the Expense table starts on the
next page. After the meeting, scan the sheet and attach it to the new Fiscal Year as
an Other document — it is not required for closing a year.

Tick **Include the Budget Review** to print the Budget Review of the same year after the sheet, in the same PDF: the
last 3 years of each budget (budgeted, actual and difference), the projection with your projection choices, and the
Draft year's budgets when there is one. (#283)

## Fundraisers

### The stakeholder report (Financial & Proceeds Statement)
**Report…** on a fundraiser's page opens the report options:
- **Itemized revenue** (on): every income line under its category or bucket. Off gives a one-to-two-page summary.
- **Show contributor names** (on): off shows "Contributor 1, 2…" instead of names, for a report that goes outside the
  organization.
- **Plain line list** (only for a fundraiser without buckets): adds a simple list of its income and expense lines.

Then **Report (PDF)** to print or email it, or **Report (Word)** to adjust the wording before sending. The report
starts with the organization, the fundraiser, its dates and its status:
- *Interim, figures may change* before or during the event;
- *Post-event* once it is over;
- *Final* when a Budget Manager uses **Mark results final** (it can be undone) or when every Fiscal Year it uses is
  closed;
- *Cancelled*, with the reason.

It continues with three headline figures — net revenue, expenses and net proceeds with the net margin — and a summary
from gross deposits to net proceeds (the cash float is never counted as income or expense). With buckets there are
breakdowns by category and bucket, and lines that are in no bucket appear as *Other (not in a bucket)*, so the
figures always add up. *Key takeaways* are worked out from the figures. A Budget Manager can add **Summary notes** on
the fundraiser's page; they print under the takeaways.

The report leaves out what is audit detail: transaction numbers, bank accounts, budgets, excluded lines and
attachments. That detail is under **Reports → Fundraiser detail (audit)**.

### The fundraiser presentation
**Presentation** in the same dialog downloads the report as a slide deck (`.pptx`, 16:9) for a meeting. Open it in
**PowerPoint**, import it into **Google Slides**, or open it in **Keynote**. It uses the same figures and the same two
options (itemized revenue, contributor names). Charts are native, so you can restyle them in PowerPoint; Keynote
converts them to its own charts, and Google Slides shows them as pictures. The **speaker notes** of every slide give
the exact figures and how each one is worked out, for example "Net margin = net proceeds ÷ net revenue". Slides with
nothing to show are left out — a fundraiser without buckets gets no category slides. The *Top contributors* slides
appear only with itemized revenue and contributor names both on.

### Fundraisers across years
- **Link a fundraiser with last year's.** On the fundraiser form, **Continues from (previous fundraiser)** lists the
  latest fundraiser of each event (and fundraisers not linked yet) from earlier Fiscal Years. Picking one puts both in
  the same *series* (e.g. "Golf Outing" — the year is taken out of the name). The link only matters for reporting,
  so **Change…** next to *Series* on the fundraiser's page works even when the year is closed.
- **Create next year's…** (Budget Managers) opens a new fundraiser already filled in from this one: the name with
  the year moved on (2026 → 2027), the description, the filter, next year's continuing budgets, the buckets and
  categories without amounts, and the link. Change anything before saving.
- **Fundraiser series** (button on *Fundraisers*): rename a series, **Group as Other** (it is then combined with
  the small ones in the share charts), **Enter a prior year…** for years before PennyWarden (Fiscal Year label with
  the year, amount raised, optionally income, expenses and a note; shown as *Entered*), **Retire…** an entry (it
  stays listed, struck through), and **Merge into…** when the same event was started twice. A year in which the
  series already has a fundraiser in PennyWarden can't be entered.
- **An event whose earlier years are all from before PennyWarden** (nothing to *continue from*): click **Enter prior
  years…** next to *Series* on the fundraiser's page, or **Start a series…** on *Fundraiser series* and choose the
  fundraiser. Either one creates the fundraiser's series, named with the year taken out (it can be renamed), and opens
  **Enter a prior year…**. Next year's fundraiser then continues from this one as usual. The entered years show in the
  **Year over year** section of the fundraiser's report and presentation, and in the Fiscal Year report. Leaving
  *Continues from* empty on that fundraiser keeps its series.

### The Fiscal Year fundraising report
On **Fundraisers**, choose the Fiscal Year: each fundraiser has a checkbox, and every fundraiser of that year is
ticked except cancelled ones (*All* / *None* change that). **Fiscal Year report…** then offers:
- **Years of history** (5 by default, or all) and **Include targeted total**. The targeted total adds, for each
  event that hasn't taken place yet this year, the average of its last 5 active years (you can change the number),
  shown separately as an estimate.
- **Notes** (Budget Managers), printed on the report and the deck, and remembered for that Fiscal Year.
- **Report (PDF)** or **Presentation** (`.pptx`, like the fundraiser presentation).

It shows the year's total raised and each fundraiser's share, growth versus last year, the top fundraiser, the annual
trend, each event's share and its average per active year, and every year's result marked *Recorded* (from
PennyWarden) or *Entered*. Two fundraisers of one series in the same year add together. A fundraiser that spans two
Fiscal Years counts in the year its event starts (a footnote says so). With nothing linked yet, the history sections
say "No earlier years linked yet".

**Year over year.** Once a fundraiser is linked with earlier years (or results of earlier years are entered), its own
report and presentation get a *Year over year* section, and the Fiscal Year report and deck a *Year over year by
series* section. Each year's figures are shown with the change on the year before (up or down, in dollars and
percent), so the committee can see how an event is trending when deciding whether to keep it. A year entered by hand
with only the amount raised shows — for income, expenses and margin.

To report on **this year's fundraiser only**, untick **Include year over year** in the fundraiser's *Report…* dialog.
The PDF, the Word file and the presentation then leave out the *Year over year* section, its slide and the
"Net proceeds were up/down…" takeaway; everything else is the same. The option shows only for a fundraiser in a
series, and the Fiscal Year report always includes its history.

### Bucket categories
On a fundraiser's page, **New category** adds a heading such as *Sponsorships* or *Day-of event*. In a bucket's
**Edit**, choose its **Category** (or *No category*). The Buckets table then shows each category with its buckets
indented beneath it and a **subtotal** (income, expenses, net); buckets without a category come after the categories.
Deleting a category keeps its buckets — they just become uncategorized. A bucket can hold both income and expenses, so
*Food Sales* can show its sales, its supply costs and its profit.

**Reorder…** sets the order of the categories and of the buckets (▲ ▼, then **Save order**). That order is used on
the page and in the reports. Existing buckets stay in alphabetical order until you reorder them; new ones go to the
end. Categories, a bucket's category and the order can be changed even after the Fiscal Year is closed — they only
change how things are grouped, never a figure.

### Different contributor on reports
The fundraiser reports name the line's Entity as the contributor. When that isn't right, tick **Different contributor
on reports** next to the bucket in **Manage** and type what should show instead:
- lump cash the organization itself collected (food, raffle…) → "Cash", so the organization doesn't appear to have
  given to itself;
- a business everyone knows by a shorter name than its legal name → that name;
- someone who handed in money collected from others → the actual contributor.

It applies to that bucket's part of the line, so a deposit split between two buckets can show a different name for
each. With *Show contributor names* off, the report still shows "Contributor 1, 2…".

For the part of a line that is in **no bucket** (shown under *Other (not in a bucket)*), and for every line of a
fundraiser without buckets (the plain line list), use **Different contributor on reports** in the separate
*Contributor for the part in no bucket* box of **Manage**. The lines table shows the name after the buckets
(*not in a bucket: shown as "…"*). (#303)

### Charge less a credit
Sometimes a bill is a full charge less a credit: a $1,500 venue invoice less $500 that teams pre-paid, paid with a
$1,000 check. In **Manage** on the line, tick **Charge less a credit** next to the bucket and enter the **Charge**
($1,500), the **Less** amount ($500) and a **Less description** ("Pre-paid team credit"). The **net** ($1,000) is what
counts for the line, so the fundraiser's totals still match the register. It works the same on income — a $200
sponsorship less a $6 card fee. The Less amount can equal the charge (a fully comped item, net $0) but not exceed it.

## Payments

### Voucher checks: check on top, in the middle or at the bottom
Payments Setup has five more voucher presets: the check **in the middle** or **at the bottom** with two stubs, and the
check on top or at the bottom with **one tall invoice stub** (including a 7-inch one). In an existing voucher style,
**Stubs (voucher check)** has **Check position** and **Stubs** to switch layouts, and **Check top** to fine-tune where
the check is. The stubs are now called **Invoice stub** (mailed with the check, no budgets) and **Office stub**. The
positions are starting points from the published layouts; check them against your stock with the test print. (#246)

### Fold marks on cover letters
A cover letter can print **fold marks**: four small, faint ticks at the left and right edges where the page is folded
in even thirds for a #10 envelope, on the first sheet only.
- **Administrators** set it on the letter template (*Payments Setup → Cover letters → Fold marks*): *No*, *On the
  front of the page*, or *On the back of the page* (needs two-sided printing), with the tick length, distance from the
  edge, line weight and shade. New window-envelope letters start with marks on the front.
- **Your own default:** on the print screen, **My letter printer settings** → *Fold marks on my letters*. For example,
  choose *On the back* when your printer prints two-sided.
- **One letter:** the **Fold marks** choice next to the letter changes it for that letter only.

With marks on the back, the print screen shows a banner: print on both sides of the paper (flip on long edge). (#247)

## Organization profile

**System/About → General → Organization** (Administrators) now holds the organization's **address, phone, email and
EIN** next to its name. Save once and they are available everywhere `{VARIABLES}` are used — cover letters, envelopes,
check memos and stubs, donation receipts:

| Variable | Prints |
|---|---|
| `{ORG.NAME}` (or `{ORG}`) | the organization's name |
| `{ORG.ADDRESS}` | the whole address, several lines (letters, envelopes, receipts) |
| `{ORG.ADDRESS1}`, `{ORG.ADDRESS2}`, `{ORG.CITY}`, `{ORG.STATE}`, `{ORG.ZIP}`, `{ORG.COUNTRY}` | one part of the address |
| `{ORG.PHONE}`, `{ORG.EMAIL}`, `{ORG.EIN}` | phone, email, EIN |

Capitalization doesn't matter (`{Org.Name}` works). For example, a letterhead line `{ORG.ADDRESS1}, {ORG.CITY},
{ORG.STATE} {ORG.ZIP}` no longer has to be retyped when the organization moves. Test prints and previews of check and
letter templates still use a sample organization.

**The organization is an entity too.** It is listed in Entities with a *Your organization* badge and can be chosen
wherever an entity is chosen — for example for cash collected at an event, when no single person gave it. It is
changed only in System/About and can't be inactivated. If you created an entity for your organization by hand before,
you can keep using it or inactivate it. (A line recorded as the organization's can't be marked as a donation.) (#314)

## Donations (optional module)

Donation receipt letters, printed from the deposits in the register. (The year-end giving statement and a donor report
are planned for 2.2.)

### Turning it on and setting it up (Administrator)
1. **System/About → General → Optional modules → Donations module.** It works with the Payments module on or off.
2. **System/About → General → Organization:** the **EIN** (as 12-3456789) and the **address** (see *Organization
   profile* below). Receipts can't be printed until both are entered.
3. **Donations Setup** (in the menu):
   - **Receipt letter**: title, salutation, thank-you text and closing, with `{VARIABLES}` — type `{` for the list
     (`{DONOR_NAME}`, `{AMOUNT}`, `{DATE_RECEIVED}`, `{PURPOSE}`, `{ORG.NAME}`, `{ORG.EIN}`, `{RECEIPT_NO}`…) — and the
     signer's **name and title** (there is room above the name to sign by hand).
   - The preview updates as you type; **Test print** prints it with sample data, marked SAMPLE – NOT A RECEIPT.

Every receipt prints a box with the organization's name and EIN, the donor, the date received, the amount, the
purpose and the receipt number, followed by the **goods or services statement**. These can't be removed from the
template. Confirm the wording with your organization's own tax advisor.

### Marking donations and printing receipts (Register Users)
Open a deposit in the register and choose **Donation receipt…**:
1. Tick **Donation** on each line that is a donation. A line's donor is the line's entity, else the deposit's. Add a
   **purpose** if you like, and, if the donor received something in return (a dinner, raffle tickets), its **value
   and a description**. Then **Save donation lines**. Every change is in the audit log.
2. Each donor gets **one receipt** for all of their donation lines on the deposit: **Print receipt**. Receipts are
   numbered per calendar year of the deposit: R-2026-0001, R-2026-0002…
3. The receipt is attached to the deposit.

Without goods or services the statement reads *"No goods or services were provided in exchange for this
contribution."*; otherwise *"Goods or services valued at $X were provided in exchange for this contribution
(description)."*

**Reprints and changes:**
- **Print duplicate:** nothing changed since the last receipt. It has the same number and is marked DUPLICATE.
- **Print corrected receipt:** the amount, donor, date, purpose or goods changed. After you confirm, it gets a new
  number, is marked CORRECTED, and names the receipt it replaces. The list shows the earlier one as *Replaced*.
- A **voided** deposit: its receipts show as *Void*, and no receipt can be printed. Deposits in a Closed Fiscal Year
  can't be changed or printed; their receipts stay attached.

Budget Managers, Budget Users and Auditors open the same dialog read-only. Administrators never see deposits or donors.
(#312)

## For whoever runs a Linux server

### Changed `config.toml`? Run `sudo pennywarden apply-config`
After changing `config.toml` — for example adding a folder to `backup_folders` so an Administrator can choose it for
scheduled backups — run:

```
sudo pennywarden apply-config
```

It does only what the change needs, in this order:
1. **Checks the file first, without stopping anything.** If `config.toml` doesn't parse, a backup folder isn't an
   absolute path or is under `/home`, or the host, port, `trusted_proxies` or `secure_cookies` value is wrong, it says
   what is wrong and **changes nothing**. A backup folder that doesn't exist yet is only a warning.
2. **Lets the service write to the backup folders** (the service is sandboxed and may otherwise write only to its data
   folder).
3. **Restarts PennyWarden and waits until it answers.** If it doesn't come back, the previous settings are put back and
   the service is restarted again.
4. **Tells you** which folders the service may write to, what changed, and where to point your tunnel or proxy.

`sudo pennywarden apply-config --dry-run` shows what it would do and changes nothing. Each run is listed in the audit
log as *Server settings applied*. The installer runs the same command on every install and upgrade, so the two always
agree. (Before 2.1.0 you had to run the whole installer again.)

### The installer follows your Bind Address
The installer's last lines tell you where to point your Cloudflare Tunnel or reverse proxy, using the **Bind Address**
(`host` in `config.toml`):
- `127.0.0.1` (the default): `http://127.0.0.1:8765`, as before.
- `0.0.0.0` (the tunnel or proxy runs on **another machine**): the server's network addresses, plus `127.0.0.1` in case
  the tunnel is on the same machine, with a reminder to limit the port with the firewall and to list the tunnel
  machine's address in `trusted_proxies`.
- one specific address: that address. (Before 2.1.0 such an install was reported as failed.)

The installer still never changes your `config.toml`. Details: [Upgrading](upgrade.md#210-after-the-upgrade) and
[Configuration](configuration.md).
