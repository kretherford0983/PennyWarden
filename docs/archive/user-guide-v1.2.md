# What's new in 1.2 — quick guide (1.2.1)

## Reports (menu: Reports)
**End of Year Audit** — choose the Fiscal Year, optionally one account, and whether VOID transactions are included.
*Open printable PDF* opens it in a new tab (print from there); *Download PDF* saves it. The PDF (US Letter) contains:
page 1 title page; page 2 Fiscal Year Review summary; pages 3 onward the budgets; then each transaction on its own
page(s) — Transaction date, Entity, Transaction type, Amount, Description, Clear Date and Notes at the top, and every
attachment shown underneath at page width (images and PDF pages are reproduced, not just listed); finally the Fiscal
Year supporting documents. Page footers show the section and "Page X of Y".

**Entity activity** — choose an account (or all), a date range (or pick a Fiscal Year to fill the dates) and
optionally one entity; *Run report*. Expand a row for the individual transactions. *Print* or *Download CSV*.
Transfers between your own accounts are listed separately and are not included in the totals.

## Transfers (Register → Transfer…)
Pick the *To account*, amount, transaction date, (optionally) clear date and the *Entity* the transfer is for.
Two linked entries are created: a withdrawal here ("Transfer to ******1234 for <Entity>") and a deposit in the other
account ("Transfer from ******6789 for <Entity>"). Without an Entity your organization's name is used. Budgets are not affected. To fix a mistake, void either side —
both sides are voided — and enter the transfer again. Each side's clear date and notes can be edited separately.

## Finding entities faster
In *New transaction* start typing in the Payee/Entity box; the list filters as you type (name or ENT number).
Use ↑/↓ and Enter, or click.

## "No attachment will be provided"
Tick the box at the bottom of the transaction form when no document exists (e.g. interest paid directly by the bank).
A warning explains that transactions should normally have documentation; confirm to continue and optionally give a reason.
If you attach a document later, the mark is removed automatically.
For a split transaction each allocation also has its own "No attachment will be provided for this allocation" box.

## Documentation review
The Fiscal Year page lists transactions that are missing attachments or are marked "no attachment", and the same
counts appear in closure readiness (as warnings), on the dashboard and in the audit report. They never block
approval or closure. The rule: if the transaction itself has an attachment or is marked "no attachment", it is
documented and its allocations need nothing. Otherwise every allocation needs its own attachment or its own
"no attachment" mark; any allocation with neither makes the transaction "Missing attachment".
