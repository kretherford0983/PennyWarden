# What's new in 2.4 — quick guide

*2.4.0 is in progress. The full list is in the [changelog](../CHANGELOG.md).*

## Invoices module and the Invoice Manager
An Administrator turns on **Invoices** under System/About → General, and gives the new **Invoice Manager** role
under Users. The invoice pages arrive in the next test builds. Who does what:

- **Budget Manager** — the budgets, and which Income budgets are *Invoiced Income*;
- **Invoice Manager** — what is billed and for how much;
- **Register User** — receives and records the money;
- **Auditor** — reviews everything.

A small organization can give one person several roles; the Security page lists anyone holding Budget Manager,
Invoice Manager and Register User together, just so it is known. An Invoice Manager on their own sees the Register
(read-only), Entities (customers) and Invoices.

### The product catalog
Invoices are built from the catalog, never typed by hand. On **Invoices → Product catalog**, an Invoice Manager adds:

- **Products** — what you bill for (annual dues, a sponsorship level, an event fee): price, unit (each, hour,
  month…), optional category and code, whether it is taxable, and the **Invoiced Income budget** the money goes to.
  A *Miscellaneous* product is handy for one-off charges.
- **Tax rates** — name, rate and the Invoiced Income budget the tax goes to.
- **Unit types** and **Categories** — the lists the products use.

A **Discount** item is built in. Nothing is deleted: inactivate what you no longer use (and restore it if needed).
When a new Fiscal Year starts, copy or continue the Invoiced Income budgets so products follow them; a product shows
**Needs budget** until its budget is continued (or you choose a new one).

### Invoices
**Invoices → New invoice**: choose the customer, the date, and lines from the catalog (enter the quantity; the price
comes from the catalog). Add a discount to a line or to the whole invoice - a fixed amount or a percentage, with a
reason that prints on the invoice - and the sales tax if it applies. The draft gets its number right away.

- **Preview PDF**, then **Mark as sent** when you send or print it; the PDF is kept with the invoice.
- To change a sent invoice, **Revise…** (say why). It becomes a draft again with the same number and -R1 (-R2…), and
  you mark it as sent again. Every version's PDF stays listed under *Sent versions*.
- **Void…** an invoice entered by mistake (with a reason). Its number is never used again.
- **Request write-off…** for an amount you won't collect; a Budget Manager approves or rejects it.

An Administrator sets the number pattern, the payment terms and default notes in **Invoices Setup**, adds
**custom fields** (on the invoice or on each line: text, number, date or a pick-list; required or not; on the PDF or
not), and can make a **Test print** with sample data.

### The invoice PDF
An Administrator designs the invoice in **Invoices Setup → Invoice PDF**. The preview on the right redraws with
sample data as you change things: font and accent color, the logo (PNG or JPEG, up to 1 MB) and where it goes, the
letterhead lines, the title, the *Bill to* block, the columns of the line table (tick the ones you want, reorder them
with the arrows and rename their headings), and a footer such as *Please pay {INVOICE.BALANCE} by
{INVOICE.DUE_DATE}*. Open **Variables** for the full list. **Save template**: invoices printed from then on use it;
PDFs already kept for sent invoices stay as they were sent.

### Payments
A **Register User** records money received from the invoice itself: **Record payment…** asks for the bank account,
the amount and the date, and creates the deposit in the Register - spread over the invoice's budgets and the sales
tax. The invoice shows *Paid*, the *Open balance*, and each payment with a link to its Register transaction.

- A payment smaller than the open balance makes the invoice **Partly paid**; the rest can be paid later.
- More than the open balance is an **overpayment** - you're asked to confirm, and **Refund overpayment…** later
  records the cheque or transfer back to the customer.
- A deposit already in the Register on an Invoiced Income budget can be attached with **Link a deposit…** (Invoice
  Managers can do this too). A deposit on another budget is re-allocated in the Register first.
- While Invoices is turned on, deposits to Invoiced Income budgets are entered from the invoice, not directly in the
  Register. A payment line linked to an invoice can't change its amount or budget in the Register; **Unlink…** it on
  the invoice (choosing the budget it moves to) if it was linked by mistake.
- Voiding a payment in the Register (a bounced cheque, say) puts the invoice back to *Sent* or *Partly paid*.

### Many customers at once (batches)
For invoices that go to many customers - annual dues to every member, say - use **New batch…** on the Invoices page.
Give the batch a name, tick the customers (type to find them; **Choose all shown** ticks every match), then enter the
lines, dates and tax once. **Create drafts** makes one draft invoice per customer.

On the batch's page, check the drafts (open any one to change it, or void it if it shouldn't go out), then **Mark all
drafts as sent** and **Combined PDF** to print or save them all in one file. Afterwards each invoice is paid,
revised or written off on its own like any other.

### Emailing invoices and statements
First an Administrator enters the organization's mail server under **System/About → Settings → Email** (your email
provider gives the server name, port and security; use an app password if your provider offers one), turns email on
and sends a **test email**. The password can't be viewed again - type a new one to replace it.

Then, on a sent invoice, **Email…** opens a short form: *To* is the customer's email from Entities, and the subject
and message are filled in for you. Change anything, then **Send email**. The invoice PDF that was kept when you
marked it as sent is attached. A customer statement is emailed from **Reports → Customer statement** (*Email to the
customer…*). Each invoice lists its emails (sent or failed) under **Emails**. PennyWarden never emails customers on
its own - overdue reminders stay inside the app for Invoice Managers.

### Invoice reports
**Reports → Invoices** has seven reports. Each shows on screen first; **Open** gives the PDF and **Download CSV** a
spreadsheet (the customer statement is a PDF to send to the customer).

| Report | Answers |
|---|---|
| Open invoices | Which invoices still have money owed on a date, and how late they are |
| Aging | How much each customer owes, by how long it's overdue |
| Customer statement | One customer's invoices, payments and balance for a period |
| Sales tax collected | Tax charged and collected per rate, for your sales tax return |
| Invoice register | Every invoice in a period with its status, payments and revisions |
| Sales by product / category | What was invoiced, by product, category or Income budget |
| Payments, write-offs, discounts and refunds | Money in and out on invoices, and amounts given up (self-approved write-offs marked) |

**Overdue invoices** appear on the Dashboard. Invoice Managers also see **Invoice reminders** at the top of the
Invoices page for unpaid invoices from their due date (or a number of days later - the Administrator sets it under
*Overdue reminder* in Invoices Setup). Open invoices don't stop a Fiscal Year from being closed; the Close report
lists them for information.

## Invoiced Income budgets
Money collected on invoices should go to budgets set aside for it. A Budget Manager marks an Income budget with
**Mark as Invoiced Income** in the budget's row menu (Budgets page); its sub-budgets carry the mark too, and it shows
as **🧾 Invoiced income** on the budget. It still counts as income in every total and report. On an approved budget,
unlock it (with a reason) first. Copying budgets into a new Fiscal Year keeps the mark. For now this only labels the
budget; it takes effect with the Invoices module, coming later in 2.4.

## Events & Fundraisers

The Fundraisers module is now **Events & Fundraisers** — **Events** in the menu. Everything you had is where it was.

### Fundraiser or Event
Each record has a **Type**:

- **Fundraiser** — raises money: goal, donation receipts and the fundraising report, as before. Everything from before
  2.4 is a Fundraiser.
- **Event** — something you run that isn't a fundraiser, such as a Summer Cookout or a members' dinner. It shows
  income, expenses and net, without a goal or donation receipts.

You can change the type later with **Edit**. The goal and receipt settings are kept (just hidden while it is an
Event), and the change is in the audit log. Events that continue each other (*Continues from*) must be the same type;
to change the type of one that is linked with others, set *Continues from* to none first.

### Budgets each type needs
You can save a record without budgets (for example before next year's Fiscal Year exists). Once you choose budgets:

- a **Fundraiser** needs an **Income and an Expense** budget,
- an **Event** needs an **Expense** budget (Income is optional),

in each Fiscal Year it uses. If one is missing, the record shows a warning and its results can't be marked final
until you add it (or change the type). An event that runs across two Fiscal Years shows one combined Income and one
combined Expense budget.

### Reports
The stakeholder report and presentation work for both types. The **Fiscal Year fundraising report** lists Events in
a section of their own — they don't count in the fundraising totals.

## Attachments

### Identical files are stored once
If you attach a file that PennyWarden already has — the same receipt on two transactions, say — it is no longer saved
a second time. Nothing looks different: each record shows its own attachment with the name you gave it, and you can
view, download or remove it exactly as before. Removing it from one record never removes it from another. The saved
copies PennyWarden makes itself (the Close report, check record copies, donation receipts, statements and envelopes)
work the same way.

### Picking the same file twice
When you add a file that is **already attached to the same record**, PennyWarden stops and asks:

- **Cancel** — nothing is added. Use this when you meant to pick a different file (an easy slip when attaching several
  files in a row).
- **Attach anyway** — the file is added a second time.

Attaching the same file to a *different* record does not ask.

### After the upgrade
The first time 2.4 starts, attachments that are identical are linked to one stored file and the extra copies are
removed, freeing disk space. Every file is checked first; anything that doesn't check out is left exactly as it is.
An Administrator can see how many files are shared and how much space was saved in the **Health** section of
**System/About**.
