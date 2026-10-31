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
