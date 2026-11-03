# What's new in 1.4 — quick guide

*1.4.0: documentation review, income above budget, bank total, version information. 1.4.1: audit signature page, dashboard charts, two-step verification, backup and restore.*

## Documentation review (Fiscal Year page)
When you tick **No attachment will be provided** on a transaction or a split allocation, fill in the **reason**
(for example *Bank interest - direct deposit*). A mark **with a reason** counts as documented: the transaction no
longer appears in the Fiscal Year's documentation review, the closing warnings or the dashboard count.
A mark **without** a reason stays in the review (shown as *No attachment – no reason given*) until you add one.
Transfers between accounts carry an automatic reason and are no longer listed.

## Income budgets above budget
When an income budget receives more than was budgeted, *Remaining* shows the extra in green — e.g.
**+$250.00 above budget** — on the Budgets page, the dashboard, the budget picker and the PDF reports. This is no
longer reported as "over budget" when closing the year. Expense budgets work as before (a negative remaining amount
in red, and a closing warning).

## Dashboard
The *Bank account balances* table ends with a **Total (all accounts)** row.

## Version information
**My account → About** shows the application version and build (for example *test build #12 (a1b2c3d)*).
Administrators see the same on **System/About**, together with the bind address.

## Audit review signature page (1.4.1)
Reports → **End of Year Audit** → tick **Include audit review signature page**. The PDF then ends with a page that
has a blank line for the date, the wording, and a signature line for each signer.
- **Wording:** *Default wording*, one of the **saved wordings**, or **New wording…**. New wording can be kept with
  **Save for future use** (up to four saved wordings, shared by everyone; **Delete** removes one).
- **Variables** are filled in for the selected Fiscal Year: `{FY}` → *July 1, 2025 – June 30, 2026*,
  `{ORG}` → your organization's name, `{FYE}` → *June 30, 2026*. Any other `{…}` is refused.
- **Signers:** up to five people (individual Entities — add them on the Entities page first), each with an optional
  title such as *Trustee*; printed as "Jane Doe, Trustee". With no signer chosen, three blank lines are printed.
- After the audit, scan the signed page and add it to the Fiscal Year as its **Audit Signoff** document; it then
  appears in the Fiscal Year Close report.

## Dashboard charts (1.4.1)
At the bottom of the dashboard, **Charts** shows the selected Fiscal Year (change it with the *Fiscal Year* list):
income by budget, monthly expenses and income, expense budgets (budgeted vs spent), bank balances at each month end,
expenses by budget and the cumulative net. Use **Choose charts** to show or hide charts — the choice is saved for
your account (new users see the first three). Hover a chart for exact amounts, or open **Show data table** under it.
VOID transactions and transfers between accounts are not included.

## Two-step verification (1.4.1)
After your password, PennyWarden asks for a **6-digit code** from an authenticator app on your phone (Microsoft
Authenticator, Google Authenticator, 1Password, Authy, …).
- **Setting it up:** on a server install you are asked the first time you sign in after the upgrade; on a desktop
  install use **My account → Two-step verification → Set up**. Scan the QR code (or type the key shown under it),
  enter the code the app shows, then **save the 10 recovery codes** (copy, download or print). They are shown only
  once.
- **Signing in:** enter the current code. Tick **Trust this browser for 30 days** only on a computer you alone use.
- **Lost your phone?** Choose *Lost your phone? Use a recovery code* and enter one of your saved codes (each works
  once). Then go to My account → **Change authenticator** to set up the new phone; this also gives you new
  recovery codes.
- **No phone and no recovery codes?** Ask an Administrator: Users → **Reset two-step**. You will set it up again at
  the next sign-in.
- My account also lists your **trusted browsers**; remove any you no longer use.

## Backup and restore (1.4.1, Administrators)
**System/About → Backup / Restore.**
- **Backup:** choose a passphrase (at least 12 characters, entered twice), enter your password, **Create backup**.
  The file downloads automatically. Keep it away from the server and keep the passphrase safe — without it the backup
  cannot be restored.
- **Restore:** choose the backup file, enter its passphrase and your password, type `RESTORE`. All current data is
  replaced (a safety copy is kept on the server), everyone is signed out, and you sign in again with an account from
  the backup.
- **New server:** in the initialization wizard choose *Restore from a backup instead*.
Details: docs/backup-restore.md.
