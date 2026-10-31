# What's new in 2.3 — quick guide

*2.3.0 is in progress. The full list is in the [changelog](../CHANGELOG.md).*

## Reports

### Finding a report
**Reports** now opens on a catalog of every report and presentation you can run, grouped by what you need it for. Type
in **Find a report** to filter, or pick one from **Recently run** to open it again with the same choices. Each report
has its own page — bookmark it if you use it often — and the list on the left takes you to another report without
going back. Your last choices are filled in for you, on any computer you sign in from.

An Administrator can change how the catalog is grouped under **System/About → Report settings**: by purpose (the
default), by subject or by audience, and rename, reorder, add or remove the categories and move reports between them.
That only changes where a report is listed — not who can run it.

The Fiscal Year fundraising report, the Planning Sheet and the cash count sheet are in Reports now too; the buttons on
the Fundraisers and Fiscal Years pages still work and take you straight there.

### Quarterly and Annual financial report
**Reports → Quarterly / Annual** makes the report for your board: choose the Fiscal Year and a quarter (Q1–Q4) or
Annual, add a few lines of commentary if you like, then **Open report PDF** or **Download presentation (.pptx)**.
You get the highlights (total cash, how much it changed, how many budgets are over, fundraiser net), each account's
balance at the start and end, money in and out by month, the budgets for the quarter and the year so far, and the
fundraisers — with last year's figures beside them when PennyWarden has the year before.

The report is as of the end of the period: transactions dated later are left out. You can run it before the quarter
ends; it is then marked **Preliminary — as of** today. A fundraiser counts in the quarter its event ends in; if money
for an earlier quarter's fundraiser comes in later, it shows as **Revised**.

## Budgets

### Budget amounts are gross
A budget's amount and its actual are **gross**. When an expense is reimbursed, the reimbursement is recorded in an
income budget, so the expense budget's actual is not reduced by it — the expense budget can look over budget even
when the net cost was within plan. PennyWarden now says this wherever budget amounts appear:

- under the budget tables on the **Budgets**, **Fiscal Year** and **Budget Review** pages;
- behind the **ⓘ** on the Dashboard's budget tiles and on the *Expense budgets: budgeted vs spent* chart;
- as a small footnote under every budget table in the printed reports (End of Year Audit, Fiscal Year Close, Budget
  Review, Planning Sheet), so it stays with a page that is copied or handed out on its own.

The budget form's **Amount** is now called **Gross amount**. Nothing is calculated differently.

### Budget Review: budgets that are not in this year
The **Budget Review** now also lists budgets that had figures in the years you chose to show but are **not in the
chosen Fiscal Year** — for example a fundraiser budget that wasn't run this year, or one from before PennyWarden that
no budget continues yet. They appear among the Income and Expense budgets, under the most recent code and name they
had, with a **Not in FY…, last FY…** tag. Their earlier years and averages are shown as usual; the current year,
*Projected* and next year show —. Budgets are matched by their continuation links, never just by the code.

### Estimated figures from before PennyWarden
When you enter a budget year from before PennyWarden (*Add an earlier year*, *Before PennyWarden*, or a CSV import),
tick **Estimated** if the figure is an estimate — the note then has to say why. The year is marked **\*** in the
History and the Budget Review, with a footnote *\* Estimated: <your note>*. In a CSV file, put *yes* in the
optional **estimated** column.

### A year whose money was in another budget
Sometimes a budget is new on its own, but its money was already there inside another budget. For example, *Kiwanis*
became its own sub-budget this year, but last year its money was recorded in *102 Fundraisers*. Open the budget's
**History**, choose **Add an earlier year**, then **Its money was included in another budget that year**. Pick the
year, the budget it was included in (a budget of the same type: Income or Expense), and add a note if you like. You
don't enter amounts.

The Budget Review then shows *included in 102 Fundraisers* in that year instead of —. That year doesn't count toward
the budget's **Avg**, because it has no figures of its own. The other budget's numbers are not changed. To take a mark
back, choose **Retire** on its row in the History and give a reason; it stays in the list of retired marks.

## Fundraisers

### A goal for a fundraiser
*New fundraiser* and *Edit* have a **Goal (optional)** field — what the fundraiser aims to raise. When it is set, the
fundraiser's page shows the goal beside the totals and compares the **net** (income minus expenses) with it: the
percentage of the goal reached and how much is still to go, or how far the goal was beaten. Leave it blank for no
goal. The goal is for information only and never stops anything from being entered. *Create next year's* starts the
new fundraiser without a goal.

### Estimated results of earlier years
In **Fundraisers → Fundraiser series**, *Enter a prior year* has an **Estimated** box for a result you only know
roughly; a note saying why is then required. An entered result can now be fixed with **Correct…** (the amounts, the
note and the Estimated box, with a reason). Estimated years are marked **\*** in the fundraiser's report and
presentation and in the Fiscal Year fundraising report and presentation, with a footnote giving your note; in the
charts their bars are lighter.

## Donations

### Include EIN on receipts
**Donations Setup → Organization** has **Include EIN on receipts** (on by default). Turn it off if your organization
prefers receipts without its EIN (for example a small church without one): receipts and year-end statements then show
only the organization's name, and `{ORG.EIN}` prints blank in your letter text (Donations Setup warns you if the text
still uses it). When it is on but no EIN has been entered in System/About, receipts can't be printed until it is.

With the EIN turned off, a Register User can still include it on **one** receipt by writing `{ORG.EIN}` in that
donor's *Details for the receipt* — for example for a non-cash gift over $500, where the donor needs the EIN for
Form 8283. Saving asks you to confirm and give a reason, and printing asks once more; both are recorded.

### The receipt preview stays in view
On a wide screen the preview of the receipt now sits beside the settings and stays in view while you scroll, so you
can watch each change. Choose **Receipt** or **Year-end statement** above the preview to see either letter. On a
narrow screen the preview is at the top of the page; tick **Keep at the top** to keep it there while you scroll. The
check style, cover letter and envelope editors work the same way.

### Letters that run onto a second page
Receipts, year-end statements and payment cover letters that only just run over now fit on one page – the spacing
tightens, and if needed the type gets slightly smaller. A letter that needs two pages takes its last paragraph to
page 2 with the signature, so the signature is never on a page by itself. The second page is headed with your
organization, the document and its number, and *Page 2 of 2*.

### Signers for receipts and statements
Signers are now kept on one **Signers** page (Administrators, next to Envelopes), shared by checks, payment cover
letters and donation letters. Add a signer there, upload a signature image if you want one, and tick what the signer
is **Used for**. In **Donations Setup → Receipt letter**, pick the signer and how the signature shows: none, the
printed name and title, the signature image with the printed name, or the printed name with space to sign by hand.
The year-end statement can use a different signer or follow the receipt. A signature image prints only on the copy
you print; the copy kept with the donation shows the printed name.

Cover letters (**Payments Setup → cover letter → Signed by**) can follow the check's signer, as before, or always use
one signer tagged for cover letters, with the same choice of how the signature shows. After the upgrade everything
prints as it did: your existing signers are tagged for checks, and the typed donation signer became a signer.

**Choosing the signer when printing.** Tick **Chosen when printing** under the signer (receipts and cover letters),
or set **Statement signer chosen** to *When printing* for year-end statements. The signer you picked becomes the
default, and whoever prints chooses from the signers tagged for that kind of letter – the choice appears only when
more than one is tagged. A reprint starts from whoever signed the earlier copy; *Print all* statements uses one signer
for all of them; a cover letter starts from the check's signer when that person signs letters too.

## Bank accounts

### Fix a wrong balance in the history
In **Bank Accounts → History** (accounts without a register), each entry's **⋯** menu has:
- **Correct…** — change the amount and/or the *as of* date, for example a balance typed wrong or given the wrong
  date. The entry is marked **Corrected**; hover over the mark to see what it was before.
- **Retire…** — take a wrong entry out. It stops counting and is listed under **Retired entries** with your reason.

Both ask for a reason and are recorded in the audit log. The account's current balance updates straight away.
Nothing is ever deleted.

### Balances from before PennyWarden
You can add balances dated before your first Fiscal Year in PennyWarden (with *Update balance* and an earlier *As of*
date) to fill in the history, even before the account's opening balance date. They are marked **Entered**.

### Closed Fiscal Years
Balances inside a Closed Fiscal Year can't be changed by Budget Managers. A **Budget Admin** can add, correct or retire
one there: you give a reason and confirm that you are changing a closed year (it was closed with the old balance).
The Fiscal Year page and its reports then show **Balance changed after close** with what changed, who changed it and
why.

## Users

### Finding users
On **Users**, narrow the list with **Roles** (tick any number — anyone with one of them is listed), **Security domain**
and **Status** (Active, Disabled, Locked), together with the search. Click **Clear filters** to see everyone again.
Click the Last name, First name, Username, Display name or Email heading to sort by it; click again to reverse.

## System/About

### Light and dark branding
**System/About → Branding** now keeps two looks: a **Light theme** and a **Dark theme**. At the top, choose which one
each kind of output uses — **PDF reports (printed)** and **Presentations (.pptx)**. Printed reports suit the light
theme; a presentation on a screen or projector can use the dark one. Word documents always print in the light theme.

On each theme's tab, pick a ready-made palette, or **Generate** one from your primary and secondary colors, and change
any color you like under *Color roles* and *Chart series colors* — the palette then shows as *Custom*. PennyWarden
won't save a theme whose text would be hard to read on its background, and warns when two chart colors look alike.

If your logo doesn't show well on a dark background, tick **Use a separate logo on dark backgrounds** and add a
version for dark slides. If you upgraded from 2.2, everything stays light until you choose otherwise.

### Choose which releases the update check looks at
Under **System/About → Settings**, an Administrator can change **Update channel**:

| Choice | What the update notice tells you about |
|---|---|
| **Follow this build** (default) | Production builds: production releases. Test builds: newer test builds and production releases. |
| **Production releases only** | Production releases — a test build is also told when the final release of its own version is out. |
| **Test builds and production releases** | Test builds (pre-release) too, each linked to its GitHub release page. |
| **Off** | Nothing; the check makes no requests. The *Check for updates* switch is still the usual way to turn it off. |

The change is saved to `config.toml` and works straight away — no restart needed. On a **local install** this is
the only setting you can change from the app. On a production installation, choosing test builds asks you to confirm:
test builds are pre-release and not production ready, so only install them on a system you use for testing.
PennyWarden never installs an update by itself.
