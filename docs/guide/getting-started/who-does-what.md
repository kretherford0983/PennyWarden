PennyWarden separates duties so that no single role controls the whole life of the money: one person plans the budgets,
another records what was received and spent, and someone else can review it all. A small organization can give one
person several roles.

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
