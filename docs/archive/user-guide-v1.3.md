# What's new in 1.3 — quick guide

## Fiscal Year documents (Fiscal Year page)
Documents are now filed as **Approval document**, **Audit Signoff** or **Other documents**, each with its own
"Add …" button.
- **Approval document** — the record that the budget was reviewed and approved (signed approval, meeting minutes…).
  Needed before **Approve…** works. If your organization produces no such document, tick
  *No approval document — this organization does not produce one*; a strong warning explains the consequences and the
  year then shows a warning in the Fiscal Year review. Uploading an approval document later removes the mark.
- **Audit Signoff** — needed to close the year (an "other" document no longer counts).
- **Other documents** — anything else; no effect on approval or closing.
Budget Managers can change a document's type with the drop-down next to it while the year is open.
**After upgrading:** documents uploaded before 1.3 are listed under *Other documents* — change the signoff document to
*Audit Signoff* (and the approval document to *Approval document*) before closing an open year.

## Fiscal Year Close report (Reports → Fiscal Year Close)
The audit report with the Fiscal Year documents placed right after the Fiscal Year review. When you close a Fiscal
Year a copy is created automatically and kept under *Close report* on the Fiscal Year page. The End of Year Audit
report no longer contains the Fiscal Year documents.

## Entering transactions
- **Attach files while you enter the transaction**: *Transaction attachments* at the bottom of the form, and
  *Allocation N attachments* for each split line. They upload when you press Save.
- Split attachment lists are labelled "Entity - Budget", e.g. *Bob Smith - 4000 Donations*.
- **Save** shows "Saving…" and ignores further clicks; a double click creates one transaction.
- If a transaction with the same account, date, type, amount and entity already exists you are asked
  *Possible duplicate … Save anyway?* — confirm only if it really is a second transaction.
- **Check numbers can be used only once per account.** A voided check keeps its number. If a number was entered by
  mistake on a transaction that is already VOID, open it and use **Correct check number…** (clear it or change it;
  a reason is required and the correction is noted on the record).

## Missing checks (Register → Fiscal Year reviews)
*Possible missing checks* lists numbers skipped in the selected account's check sequence (between the lowest and
highest check recorded). For each: **Enter transaction** (check number pre-filled), **Record as VOID check**
(zero-dollar VOID record for a spoiled check) or **Confirm not missing…** with a note (e.g. a new checkbook). Large
gaps appear as one range. Missing checks are a warning when closing a year, not a blocker.

## Screen layout
- The top bar and the menu stay in place; only the page scrolls.
- **« / »** at the top of the menu collapses it to icons (hover an icon for its name). Your choice is remembered.
- In the Register the title, account, buttons, filters, balances and the column headings stay visible while you
  scroll through transactions.
