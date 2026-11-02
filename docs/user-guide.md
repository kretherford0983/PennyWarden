# PennyWarden user guide

This guide describes PennyWarden as it works today, one area at a time. It is kept up to date with every release; the
notes for earlier releases are in [`docs/archive/`](archive/) and on [pennywarden.org](https://pennywarden.org/guide/).
What changed in each release is in the [changelog](../CHANGELOG.md).

Inside PennyWarden, **Help** in the menu opens this guide, and the **?** button at the top right opens the section for
the page you are on. The guide is part of the app, so it also works without an internet connection.

**Contents**
[Getting started](#getting-started) ·
[My account](#my-account) ·
[Dashboard](#dashboard) ·
[Fiscal Years](#fiscal-years) ·
[Budgets](#budgets) ·
[Bank Accounts](#bank-accounts) ·
[Entities](#entities) ·
[Register](#register) ·
[Attachments](#attachments) ·
[Reports](#reports) ·
[Events & Fundraisers](#events) ·
[Payments and check printing](#payments) ·
[Donations](#donations) ·
[Invoices](#invoices) ·
[Reminders and notifications](#notifications) ·
[Envelopes and signers](#envelopes) ·
[Users](#users) ·
[Audit Log](#audit-log) ·
[System/About](#system-about) ·
[Backup and restore](#backups) ·
[Installing, upgrading and the demo](#installing)

<a id="getting-started"></a>
## Getting started

### Who does what
PennyWarden separates duties so that no single role controls the whole life of the money: one person plans the
budgets, another records what was received and spent, and someone else can review it all. A small organization can
give one person several roles.

| Role | Does |
|---|---|
| **Administrator** | Users and roles, the Audit Log, System/About (settings, backups, optional modules, letter and check setup). Never sees financial data. |
| **Budget Manager** | Fiscal Years, budgets, bank accounts and Financial Institutions; approves and closes Fiscal Years. Sees the Register but does not enter transactions. |
| **Budget Admin** | With Budget Manager: may delete a budget of a Fiscal Year that is not approved yet, and change a balance in a closed year. |
| **Budget User** | Looks at the financial information; changes nothing. |
| **Register User** | Enters, edits and voids transactions; looks after Entities; pays bills and prints checks and receipts. |
| **Register Admin** | With Register User: may delete a transaction that has not cleared. |
| **Invoice Manager** | Creates and sends invoices from the product catalog (Invoices module). Sees the Register read-only. |
| **Auditor** | Sees everything — users, the Audit Log and all financial records, including inactive, rejected, deleted and voided ones — and changes nothing. |

On a **server**, each account belongs to one security domain: Administration, Financial or Audit. Financial roles can
be combined. On a **local install** (PennyWarden on your own Windows, Mac or Linux computer) one person can hold every
role on a single account.

Menus and buttons only show what your roles allow. PennyWarden also checks every action on the server, so a hidden
button is never the only protection.

### The first start
A new installation opens the **Initialization Wizard**: the organization's name, the first Administrator's username,
email address and password (twice). That Administrator then creates the other users under [Users](#users). To move an
existing installation instead, choose **Restore from a backup instead** (see [Backup and restore](#backups)).

### Signing in
Enter your username and password. If the password is refused, the field is emptied so you can type it again.

**Two-step verification.** After the password PennyWarden may ask for a 6-digit code from an authenticator app on
your phone (Microsoft Authenticator, Google Authenticator, 1Password, Authy …). On a server everyone uses it; on a
local install it is optional (**My account → Two-step verification → Set up**).
- To set it up, scan the QR code (or type the key shown under it), enter the code the app shows, then **save the 10
  recovery codes** — they are shown only once.
- Already have a PennyWarden entry in your authenticator from before? Open **Use my own key instead** and enter that
  key, unless it may have been exposed.
- Tick **Trust this browser for 30 days** only on a computer you alone use.
- **Lost your phone?** Choose *Lost your phone? Use a recovery code*, then **My account → Change authenticator**.
  Without a phone and codes, ask an Administrator to reset two-step verification.

**Forgot your password?** Click **Forgot password?**, enter your username, answer one of your three **security
questions** (case, spaces and punctuation don't matter) and, on a server or with two-step verification on, the code.
Then choose a new password; you are signed out everywhere. After 5 wrong passwords or answers in a row the account is
locked for 15 minutes, then longer, and after 20 it is disabled until an Administrator enables it again.

**Password rules:** 12 to 128 characters, at least one letter and one digit, not your username, and different from
your current password. Each rule turns green as you meet it.

### Finding your way
- The **menu** on the left lists the pages you may use. **«** / **»** collapses it to icons; PennyWarden remembers your
  choice.
- The **top bar** shows your name, the **☾ Dark / ☀ Light** switch, the **bell** for reminders, **My account**,
  **Sign out**, and the **?** help button.
- A **gold circle with an up arrow** next to your name means a newer version is out; click it to read what's new.
- Tables show **Edit** and a **⋯** menu with the row's other actions.
- Nothing financial is ever erased. Records are inactivated, rejected, retired, voided or (by the admin roles)
  deleted, and Auditors can still see them.
- Status is always shown in words or icons, never by color alone.

<a id="my-account"></a>
## My account
**My account** (top bar) shows your username, email and roles, and lets you:
- **Change password** — current password, then the new one twice.
- Set up or change **two-step verification**, see your recovery codes situation and remove **trusted browsers**.
- Change your **security questions** (your password is needed).
- Choose **Appearance**: Light or Dark. The choice follows you to any computer you sign in from.
- **Show people's names as** *First Last* or *Last, First* — how Individuals show and sort for you.
- See the version and build (**About**), the license and the source-code links. On a local install, the update notice
  is shown here.

Changing your password signs out your other sessions.

<a id="dashboard"></a>
## Dashboard
The Dashboard opens after you sign in. For financial users it shows:
- the **current Fiscal Year** and its status;
- **income and expense** budget totals (the **ⓘ** explains that budget amounts are [gross](#budget-gross));
- **bank account balances** in two groups — *Checking & Savings* and *Investments and Other* — each with a subtotal,
  then the total of all accounts;
- **attention items**: Fiscal Year reviews, missing documentation, due reminders and overdue invoices;
- **Charts** for the selected Fiscal Year (income by budget, monthly income and expenses, budgeted vs spent, month-end
  bank balances, expenses by budget, cumulative net). **Choose charts** picks which to show; hover a chart for exact
  amounts or open **Show data table**. Voided transactions and transfers are left out.

**Customize dashboard** (top right) hides sections and moves them with **↑** / **↓**; **Reset to default** brings the
standard layout back. Auditors see review-oriented counts (transactions, voids, cross-year allocations, rejected
budgets). Administrators see user and security information only.

<a id="fiscal-years"></a>
## Fiscal Years
A Fiscal Year is the period your budgets cover. Its status is **Draft**, **Approved** or **Closed**. A Draft year is
fully usable: it appears everywhere, takes budgets and takes transactions. Approval locks its budgets; closing it makes
it permanent.

### Creating a Fiscal Year (Budget Managers)
**Fiscal Years → New Fiscal Year**: the identifier (`2027` becomes **FY2027**), the start date and the end date.
- The new year should start the day after the previous one ends. If it leaves a **gap** or **overlaps** another year,
  PennyWarden warns you and asks you to confirm. For an overlap it shows the other year's status and readiness.
  Overlaps are allowed for a change of fiscal calendar; when two open years cover a transaction date, the Register
  asks which year to use.
- **Copy budgets from (optional)** copies chosen budgets of an earlier year: codes, names, types, sub-budgets and
  amounts as Draft starting values, each linked to the budget it came from. You can remove budgets from the list
  before creating the year.

Quarters run three months at a time from the start date: a year starting July 1 has Q1 Jul–Sep, Q2 Oct–Dec, Q3
Jan–Mar and Q4 Apr–Jun.

### The Fiscal Year page
Click a year to see its Income and Expense budgets with each quarter's activity, the year's actual and what remains,
its status, its lifecycle dates, its documents, the documentation review and the closure readiness.

**Documents.** Each document is filed as:
- **Approval document** — the signed approval or the minutes. Needed before **Approve…**. If your organization
  produces none, use **Mark as no approval document** (a warning then stays on the year).
- **Audit Signoff** — needed to close the year (scan the signed audit signature page, see [Reports](#reports)).
- **Other documents** — anything else, such as the scanned Planning Sheet. **Reorder…** sets their order.

**Documentation review** lists transactions with no attachment, or marked *No attachment will be provided* without a
reason (see [Attachments](#attachments)). It warns; it never blocks approval or closure.

### Approving (Budget Managers)
**Approve…** checks the budget structure, sets the year to Approved and locks all its active budgets. It cannot be
undone. A locked budget can be unlocked later with a reason (see [Budgets](#budgets)).

### Closing (Budget Managers)
**Close Fiscal Year…** is refused while:
- the year is not Approved;
- any budget is unlocked;
- any transaction in the year has not cleared;
- a Fiscal Year review item is unresolved;
- an allocation is invalid or incomplete;
- there is no **Audit Signoff** document.

Warnings — rejected-budget activity, expense budgets over budget, reviewed cross-year allocations, voided transactions,
missing checks, missing documentation, open invoices — are listed for you to read but don't stop the close. You confirm
that the year has been reviewed and approved for closure. A closed year can't be reopened; its budgets and allocations
can no longer change, and a copy of the **Fiscal Year Close report** is kept on its page.

### Planning the next year
**Planning sheet…** (also in Reports) prints the form for the budget planning meeting: previous budgeted amounts,
actual year-to-date, projections and a blank *Proposed* column, with blank rows for new budgets. If the next year
already exists as a Draft, its amounts print as *Proposed* with a blank *Proposed Revision* column. Tick **Include the
Budget Review** to add the review to the same PDF.

<a id="budgets"></a>
## Budgets
Every budget belongs to one Fiscal Year and is either **Income** or **Expense**. Choose the year at the top of the
page; Draft, Approved and Closed years are all listed.

### Codes, sub-budgets and Other
- A simple budget is shown by its code and name: **1000 Operations**.
- A budget can have sub-budgets: **1000-01 Travel**. The parent then becomes a roll-up and can't receive transactions
  itself; you allocate to its sub-budgets.
- Every parent has a system-managed **Other** sub-budget: *Other = parent amount − the sub-budgets*. You never edit
  it. When Other is $0.00 it is hidden; when it becomes positive again it reappears.
- Sub-budgets together can't exceed the parent's amount.

<a id="budget-gross"></a>
**Amounts are gross.** A budget's amount and its actual are gross: a reimbursement is recorded in an income budget, so
it doesn't reduce the expense budget's actual. An expense budget can look over budget even when the net cost was
within plan.

**Remaining** can go negative — a budget never stops a transaction. An income budget that receives more than planned
shows the extra in green, e.g. **+$250.00 above budget**.

### Status
| Mark | Status | Background |
|---|---|---|
| **?** | Draft | light yellow |
| closed padlock | Approved and locked | light green |
| open padlock | Approved and unlocked | light green |
| **X** | Rejected | light red |

### Managing budgets (Budget Managers)
- **New budget**, **Edit** (the pencil), sub-budgets — while the budget is Draft or unlocked.
- **Unlock** an approved budget to amend it: a reason is required and recorded. **Lock** it again before closing the
  year.
- **Reject** a budget: its allowed amount becomes zero, its existing transactions stay, and no new ones can be
  allocated to it.
- **Inactivate** a budget you no longer use; it stays in history.
- **Delete budget…** (Budget Admin only) removes a budget of a year that is not approved yet — for example one copied
  by mistake — if it has no transactions or sub-budgets. A reason is required; Auditors still see it as *Deleted*.
- Click a budget's code or name to open the Register filtered to that budget.

### History across years
In **Edit**, **Continues** links a budget to the one it carries on from an earlier year (copied budgets are linked for
you). **History** next to its name lists every linked year: code, name, amount and actual.

**Years before PennyWarden.** In **History → Add an earlier year** enter what was budgeted and actually spent or
received in a year before your first Fiscal Year in PennyWarden (tick **Estimated** with a note if it is an estimate,
or choose **Its money was included in another budget that year**). **Budgets → Before PennyWarden…** lists and links
these older budgets; **Import earlier years…** takes a CSV for many years at once (**Download the template**, then
**Preview** and **Import**). **Correct** and **Retire** fix entries with a reason; nothing is deleted. These years show
in the History and the Budget Review, never in actuals or the registers.

### Invoiced Income budgets
With the [Invoices](#invoices) module, a Budget Manager marks an Income budget **Mark as Invoiced Income** (row menu).
Its sub-budgets carry the mark, it shows **🧾 Invoiced income**, and copying it into a new year keeps the mark. Money
collected on invoices goes there.

<a id="bank-accounts"></a>
## Bank Accounts
Accounts are listed in two groups, **Checking & Savings** and **Investments and Other**, each with the total of its
active accounts.

### Setting up an account (Budget Managers)
**New bank account**: the name, the **Financial Institution** (only Entities marked as a Financial Institution are
offered; **+ New institution** adds one), the type and subtype, the full account number, optional interest rate and
notes.
- **Checking and Savings** use a **register** by default; investments don't. You can change that.
- A register account needs its **opening balance** and **opening balance date** — where its reliable history starts.
- **Account opened** (optional): the date an account was really opened after PennyWarden was set up.
- The account number is stored encrypted and must be unique. Everyone sees it masked, e.g. `******1234`;
  **Reveal** (Budget Managers only) shows it in full and is recorded in the Audit Log.
- **Make primary** chooses the account the Register opens on (one at most).
- **▲ / ▼** in the *Order* column set the order used everywhere.

### Balances
For a register account PennyWarden works the balance out from the opening balance and the register:
- **Current balance** — only what has **cleared**, i.e. what the bank has. Used on the Dashboard and this page.
- **Available balance** — everything written or deposited, cleared or not. Shown in the Register.

For an account without a register (investments, CDs, cash), **Update balance** records a balance and its **As of**
date, e.g. a statement date. Each update is kept; **History** lists them all. In the history's **⋯** menu, **Correct…**
fixes an amount or date and **Retire…** takes a wrong entry out — both with a reason. Balances dated before your first
Fiscal Year are marked *Entered*. In a closed Fiscal Year only a Budget Admin can change a balance, and the year then
shows **Balance changed after close**.

### Closing an account
**Close account** works only when the account has no uncleared transactions and its balance is exactly **$0.00**. For a
register account, bring it to zero with a final transaction; for an account without a register, update its balance to
$0.00 first. Accounts are never deleted.

<a id="entities"></a>
## Entities
Entities are the people and organizations you pay or receive money from. Each gets a permanent number such as
**ENT-000123**, which tells apart entities with the same name.

- **Individual** — a **first name** is required (the last name is optional).
- **Organization** — the **organization name** is required; first and last name are its contact person.
- Optional: address, **mailing address** (untick *same as Address* for a P.O. Box), phone, email, notes, **EIN** for
  organizations, a **display name** (untick *Display name same as Name*) and a **Position in the organization** (used
  as a signer's title).
- Phone numbers can be typed any way and show as **(555) 123-4567**; add `x204` for an extension or start with `+` for
  another country.
- If a new entity looks like an existing one, PennyWarden shows the possible matches. You can still create it.
- The register, lists and pickers use the display name; checks, letters, receipts and envelopes print the name and
  mailing address.
- **Inactivate** hides an entity from the pickers; its history stays and it can be restored.
- **Financial Institution:** a Register User can create one, but only a Budget Manager can edit it, inactivate it or
  remove the mark afterwards.
- **Your organization** is an entity too (badge *Your organization*), for example for cash collected at an event. It is
  changed only in System/About.
- **Names to review** (Budget Managers) lists names that may have been split wrongly at an upgrade: **Edit** or
  **Confirm** them.

Register Users and Budget Managers maintain entities; Budget Users and Auditors look.

<a id="register"></a>
## Register
Each register account has one continuous register for its whole life. The Fiscal Year choice only filters it by
transaction date.

### Reading the register
- Choose the **account** at the top (it opens on the Primary account) and the **Fiscal Year** (the current one by
  default, or *All dates*).
- The balances at the top: **Opening balance** for the year (with **Bank $…** and the outstanding items that make up the
  difference), **Current** and **Available** for an open year, **Ending balance** for a closed year or a *To* date.
- **Filters:** deposit or withdrawal; cleared, uncleared or VOID; date range; **Budget**; **Payment** (checks,
  electronic payments, no check number); **Attachments** (*Yes*, *Missing*, *Marked*); and search by entity,
  description, invoice number, check number or amount.
- Click **Date** or **Cleared** to sort; click again to reverse. Sorted by Cleared, the balance column becomes the
  **Cleared balance** (what the bank statement shows), and uncleared items stay together. **Reset to default** goes back
  to Date, oldest first.
- Click a row to expand it: allocations, notes, attachments, history and actions.

### Entering a transaction (Register Users)
**New transaction**: Deposit or Withdrawal, the **Transaction Date** (today by default), the entity (type to search by
name or ENT number), check number, description, amount and the **Fiscal Year** and **Budget**. Deposits go to Income
budgets, withdrawals to Expense budgets. Leave **Clear/Post Date** empty until the bank posts it; it can't be before the
transaction date.

- **Draft Fiscal Years** take transactions like Approved ones. Closed years don't.
- **A budget from another year:** choosing a Fiscal Year that doesn't cover the transaction date asks you to confirm,
  and the allocation goes on the Fiscal Year review list.
- **No Fiscal Year covers the date:** PennyWarden warns you, names the closest year without choosing it for you, and
  flags the allocation for review once the right year exists.
- **Two years cover the date** (an overlap): you must choose the year.
- **Possible duplicate:** a transaction with the same account, date, type, amount and entity asks *Save anyway?*.
- **Check numbers** can be used only once per account.
- **Electronic payment (no physical check)** for ACH, bill pay, debit card, wire or a vendor portal: choose the method
  and whether the number is a **check # from our sequence** or a **payment reference** (which never counts as a check).
- Attach files under **Transaction attachments** before you save.
- **Budget 0** is a protected system budget for exceptional records such as a zero-dollar VOID check.

### Split transactions
**Split transaction** divides one bank entry over several budgets; the total is always the sum of the lines and only the
total affects the bank balance.
- **Withdrawal:** one payee for the whole check; each line has its own budget, invoice number, description, amount,
  notes and attachments.
- **Deposit:** each line can have its own entity (several payments deposited together); the parent shows *Multiple*.

Any amount typed before splitting is replaced by the sum of the lines.

### Transfers
**Transfer…** moves money between two of your accounts: a withdrawal here and a deposit there, linked, with no effect on
budgets. Voiding either side voids both.

### Changing a transaction
- An uncleared transaction can be edited freely. A **cleared** one can be edited until its Fiscal Year is closed, after
  you confirm; every change is in the Audit Log.
- The **bank account can never change**. Entered in the wrong account? Void it and enter it again in the right one.
- **Change transaction type** (Deposit ↔ Withdrawal) asks you to confirm and to choose budgets of the right type again.
- **Correct check number…** and **Correct date…** fix those on records where normal editing isn't possible.

### Void
**Void…** is how a transaction is taken back: give a reason and confirm. It can't be undone. The transaction stays in the
register as **VOID** with its allocations and attachments, but no longer counts in the bank balance or the budgets. You
can still add notes and attachments; you can't remove the existing ones. A transaction in a closed Fiscal Year can't be
voided.

**Create VOID record** records a check that was never used (spoiled, damaged) as a $0.00 VOID on Budget 0, with a reason,
so the check sequence has no gap.

**Delete transaction…** (Register Admin only) removes a transaction that has **not cleared** — for example one entered
twice — with a reason. Auditors still see it as *Deleted*; its check number becomes free again. A transaction with a
printed check must be voided instead.

### Fiscal Year reviews and missing checks
- **Pending Fiscal Year reviews** lists allocations whose budget year differs from the transaction date's year, or that
  had no year. **Mark reviewed** (with a note) confirms one is intentional; reviewed ones remain valid. Unresolved
  reviews block closing that year.
- **Possible missing checks** lists numbers skipped in the account's sequence: **Enter transaction**, **Record as VOID
  check** or **Confirm not missing…**.

### Printing the register
Use your browser's **Print** (Ctrl+P): you get a portrait printout of the register as it is filtered on screen, with the
account, the filters and the balances at the top and two lines per transaction.

<a id="attachments"></a>
## Attachments
- **PDF, JPG/JPEG and PNG**, up to **5 MB per file**, as many as you need. PennyWarden checks the file itself, not only
  its name.
- Transactions, each line of a split, Fiscal Years and fundraisers take attachments. Use the arrows in the viewer to go
  from one to the next; **Reorder…** sets the order used on screen and in reports.
- If no document exists (bank interest, say), tick **No attachment will be provided** and give a **reason** — then the
  transaction counts as documented. Attaching a file later removes the mark.
- A file you attach twice is stored once. Attaching the same file to the **same** record asks first (**Cancel** or
  **Attach anyway**).

<a id="reports"></a>
## Reports
**Reports** opens a catalog of everything you may run, grouped by purpose. Type in **Find a report**, or pick one from
**Recently run** to run it again with the same choices. Each report has its own page you can bookmark. Most give
**Open PDF**, **Download PDF** and, where it makes sense, **Download CSV** or a presentation (`.pptx`).

| Report | What it is for |
|---|---|
| **End of Year Audit** | The whole year for an auditor: review summary, budgets, every transaction with its attachments, optionally fundraisers and an **audit review signature page** (wording with `{FY}`, `{ORG}`, `{FYE}`; up to five signers; **Preview signature page**). |
| **Fiscal Year Close** | The audit report with the Fiscal Year documents; a copy is kept automatically when the year closes. |
| **Quarterly / Annual** | The board report for a quarter or the year, as a PDF or a presentation. |
| **Financial Flow** | Income and expenses for a period, line by line: untick a line to leave it out (with a reason), add notes, optionally with bank balances and a compare date. |
| **Budget Review** | Each budget's budgeted, actual and difference over the years, with average, projection and next year's budget. |
| **Planning Sheet** | The budget planning meeting form (see [Fiscal Years](#fiscal-years)). |
| **Entity activity** | What each entity paid or received in a period. |
| **Fundraiser detail (audit)** and the **Fiscal Year fundraising report** | See [Events & Fundraisers](#events). |
| **Invoice reports** | See [Invoices](#invoices). |
| **Restore re-entry reports** | After a restore: what was entered after the backup, to enter again. |

In the multi-account Audit and Close reports, each account's transactions — and the fundraisers — are framed by start
and end pages that state their page range, and every page shows *section page k of n*, so a reviewer can confirm that
no page is missing.

An Administrator can regroup the catalog under **System/About → Report settings**; that changes only where a report is
listed, not who may run it. Reports use your organization's [branding](#system-about).

<a id="events"></a>
## Events & Fundraisers
An optional module (**Events** in the menu) that gathers everything spent and received for an event, across the
register. An Administrator turns it on in **System/About → General → Optional modules**.

### Setting one up (Budget Managers)
**New fundraiser**: the name, description, **Type** and the event date(s).
- A **Fundraiser** raises money: it can have a **Goal**, donation buckets and the fundraising report. It needs an
  **Income and an Expense** budget in each Fiscal Year it uses.
- An **Event** (a cookout, a members' dinner) shows income, expenses and net. It needs an **Expense** budget; Income is
  optional.
- Budgets can come from up to two Fiscal Years — so a January event can use this year's budget for preparation and next
  year's for the event. A Draft year is enough. You can save without budgets and add them later.
- **Description filter (optional)**: only lines whose description contains this text count.
- **Continues from** links it with last year's to form a **series**; **Create next year's…** starts next year's from this
  one.

Everything allocated to the chosen budgets counts. Transactions are still entered in the Register.

### Managing it (Budget Managers and Register Users)
- **Buckets** (with optional **categories**) split the money by activity: *Food sales*, *Raffle*. **Manage** on a line
  assigns amounts to buckets; a bucket can hold income and expenses.
- **Cash float out / returned** keeps the cash-box float out of income and expenses.
- **Exclude this line** (with a reason) leaves a line out without changing the transaction.
- **Charge less a credit** and **Different contributor on reports** adjust how a line shows in the reports.
- **Fundraiser documents** hold flyers, permits and the signed **cash count sheet** (print it blank from **Cash count
  sheet…**).
- **Mark as cancelled…** / **Reinstate**, **Archive**, and **Mark results final**.

### Reports
- **Report…** on the page: the stakeholder **Financial & Proceeds Statement** as PDF or Word, or a **Presentation**
  (`.pptx`), with options for itemized revenue, contributor names and year over year.
- **Fiscal Year report…** on the Events page: the year's fundraising totals and trends (Events are listed separately).
- **Fundraiser series** lets you rename series, enter prior years from before PennyWarden (optionally **Estimated**),
  correct, retire and merge them.

<a id="payments"></a>
## Payments and check printing
An optional module for paying bills and printing checks on pre-printed check stock. The full guide is
[Check printing](check-printing.md); in short:

- **Administrators** turn on **Payments module** in System/About → General, then use **Payments Setup** for check styles
  (3 per page or voucher), fonts, default memo, test print and calibration, **cover letters** and settings for printing.
  Signers and envelopes are on their own pages (see [Envelopes and signers](#envelopes)).
- **Register Users** use **Payments → New payment** to enter a bill and print its check, or **Create payment…** on a
  withdrawal already in the register. After printing choose **Yes – done**, **Reprint** or **Mark spoiled** (the number
  becomes a $0.00 VOID record). **I'm writing the check by hand** records a handwritten check; an electronic payment is
  saved without printing.
- The print screen also offers the cover letter and the envelope. Copies of everything printed are attached to the
  transaction.

<a id="donations"></a>
## Donations
An optional module for donation receipts, year-end giving statements and a donor report. An Administrator turns it on
and enters the organization's **EIN** and **address** in System/About → General.

- **Donations Setup** (Administrators): the receipt letter and the year-end statement letter with `{VARIABLES}` (type
  `{` for the list), the signer, **Include EIN on receipts**, window-envelope layout and fold marks.
- **Donation receipt…** on a deposit (Register Users): tick the lines that are donations, add purpose and any goods or
  services received, **Save donation lines**, **Preview**, then **Print receipt**. Receipts are numbered per year
  (R-2026-0001) and attached to the deposit; reprints are **Duplicate** or **Corrected**.
- **Donations → New donation** records a pledge or gift before the money arrives and prints its receipt; **Create
  transaction** later makes the deposit. Tick **Item (not money)** for physical gifts.
- **Year-end statements** prints each donor's statement (or **Print all**); **Donor report** shows giving per year.
- After printing, the **Envelope** step prints the donor's envelope.

Budget Managers, Budget Users and Auditors see the same screens read-only.

<a id="invoices"></a>
## Invoices
An optional module for billing members and customers. An Administrator turns it on in System/About → General and gives
the **Invoice Manager** role; a Budget Manager marks the [Invoiced Income budgets](#budgets).

- **Product catalog** (Invoice Managers): products with price, unit, category, taxable flag and Invoiced Income budget;
  tax rates; unit types and categories. A **Discount** item is built in. Nothing is deleted — inactivate instead.
- **New invoice**: the customer, the date and lines from the catalog; discounts need a reason. **Preview PDF**, then
  **Mark as sent**. **Revise…** a sent invoice (-R1, -R2…), **Void…** a mistake, **Request write-off…** (a Budget
  Manager approves).
- **New batch…** makes one draft per customer for dues and the like; **Mark all drafts as sent** and **Combined PDF**.
- **Record payment…** (Register Users) creates the deposit in the Register; partial payments, overpayments and
  **Refund overpayment…** are handled on the invoice. **Link a deposit…** attaches one already in the Register.
- **Email…** sends a sent invoice when an Administrator has set up email (System/About → Settings → Email).
- **Reports → Invoices**: open invoices, aging, customer statement, sales tax collected, invoice register, sales by
  product/category, and payments/write-offs/discounts/refunds. Overdue invoices show on the Dashboard and as **Invoice
  reminders**.
- **Invoices Setup** (Administrators): number pattern, terms, notes, custom fields, overdue reminder and the **Invoice
  PDF** design.

<a id="notifications"></a>
## Reminders and notifications
The **bell** shows how many reminders are due; click it for **Notifications** (*Due*, *Upcoming*, *Resolved*). Due
reminders also appear on the Dashboard.
- **New reminder** (Budget Managers and Register Users): what, the due date, how many days before to show it, details
  and an optional link to a Fiscal Year, budget or account. Budget Managers can make it for the **whole organization**
  and make it **repeat** (every N days, weeks, months or years, optionally until a date).
- **Resolve** (with an optional note) clears it; a repeating one then creates the next. A resolved reminder can be
  **reopened**.

<a id="envelopes"></a>
## Envelopes and signers
Administrators share these between Payments, Donations and Invoices.
- **Envelopes**: the #10 envelope templates. Each is *used for* the features you choose, with a default per feature.
  Templates are deactivated, never deleted. Your **My envelope printer settings** nudge the print for your printer.
- **Signers**: the people who sign checks, cover letters and donation letters, with an optional signature image
  (stored encrypted) and what each is **Used for**. A signature image prints only on the copy you print.

<a id="users"></a>
## Users
Administrators (and, read-only, Auditors) manage accounts here.
- **New user**: username, first and last name, display name, email, security domain and roles, and an **Initial password**.
- Search and filter by **Roles**, **Security domain** and **Status**; click a heading to sort.
- **⋯** actions: reset password, **Reset two-step verification** (tick **Possible compromise** if the key may be
  exposed), **Reset security questions**, enable a disabled account, deactivate.
- On a server, an Administrator can't change their own roles or deactivate themselves — keep at least two
  Administrators.
- Every sign-in, password change, role change and reset is recorded in the Audit Log.

<a id="audit-log"></a>
## Audit Log
Every change in PennyWarden is recorded: who, when, what and which record, with the values before and after. Entries
read in plain words; **Details** shows what changed. Filter by date, category, user, action or record type, and use **Export CSV** or
**Printable PDF** for an audit review. The log can't be edited or deleted. Account numbers and passwords never appear in
it, and Administrators' views and exports leave out financial content. Administrators and Auditors can open it.

<a id="system-about"></a>
## System/About
Administrators look after the installation here; Auditors and financial users see parts of it read-only. Each tab has
its own address.

- **About** — version and build, license, the update check (**Check now**).
- **General** — the **organization** (name, address, phone, email, EIN), **Optional modules** (Events & Fundraisers,
  Payments, Donations, Invoices).
- **Settings** — every setting in effect and where it comes from. On a server, security and session settings can be
  changed here; **Update channel** chooses which releases the update notice reports; **Email** sets up the mail server.
- **Branding** — a light and a dark palette, logos and footer text for reports and presentations.
- **Report settings** — how the Reports catalog is grouped.
- **Backups** — backup and restore, scheduled backups and the backup reminder (see below).
- **Security** — the security overview (HTTPS, two-step verification, last backup, locked accounts, people holding
  several financial roles) and the **signed-in sessions**.
- **System health** — sizes, free disk space, shared attachments, a database check, and **Download diagnostics**
  (no financial data, passwords or keys).
- **Advanced** — **maintenance mode** (only Administrators can change anything, with a message for everyone) and
  **Reinitialize** (start again with the same users, after a safety backup).
- **Testing** — only on a server set up in testing mode.

<a id="backups"></a>
## Backup and restore
PennyWarden keeps its data in its data folder; a backup holds the database, the attachments and what is needed to
decrypt account numbers. The full guide is [Backup and restore](backup-restore.md).

- **Backup** (System/About → Backups): a passphrase of at least 12 characters, your password, **Create backup**. Keep
  the file away from the computer and the passphrase safe. With **Let this server recover the passphrase**, the server's
  owner can restore it from the command line even if the passphrase is lost.
- **Scheduled**: **Back up automatically** daily or weekly to a folder, with how many to keep. If a backup fails,
  PennyWarden retries (1 hour, 2, 4 …) and shows a banner to Administrators.
- **Restore**: the file, its passphrase, your password and `RESTORE`; **What to restore** lets you restore only Data,
  Settings, Reminders or Users. Everyone is signed out.
- On a local install you are responsible for keeping backups somewhere other than the computer itself.

<a id="installing"></a>
## Installing, upgrading and the demo
- Downloads for Windows, Mac and Linux are on [pennywarden.org](https://pennywarden.org).
- [Installing on a Mac](install-macos.md) · [Windows server](install-windows-server.md) ·
  [Linux and Docker servers](deployment.md) · [Configuration](configuration.md) · [Upgrading](upgrade.md)
- A **local install** listens only on this computer; a **server** install is reached by several people and should sit
  behind HTTPS.
- **Try the demo**: each release has a demo backup of a made-up club; see [the demo](demo.md).
