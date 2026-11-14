# What's new in 1.6 — quick guide

> **Since 1.7.0 the application is called PennyWarden** (from 1.6.6 to 1.6.8 it was *Fundwarden*). Everything this
> guide describes works the same way — see [What's new in 1.7](user-guide-v1.7.md).

*1.6.7: a person's position is filled in as the signer's title; count sheet refinements. 1.6.6: the application is renamed (first to Fundwarden; it is PennyWarden since 1.7.0); cash count sheet with blank signature rows and a page for more checks. 1.6.0: the optional Fundraiser module (core). 1.6.1: buckets, cash float, exclusions and fundraiser documents.
1.6.2: the fundraiser report. 1.6.3: reminders and notifications. 1.6.4: cancelled fundraisers and the cash count sheet.*

## 1.6.6: a new name and an icon
With 1.6.6 the application got a new name — *Fundwarden* then, **PennyWarden** since 1.7.0 — and an icon (a gold
coin with a keyhole) in the browser tab. Nothing about your work changes: same address, same sign-in, same data. If you set up two-step verification
earlier, the entry in your authenticator app keeps its old label and keeps working. New backups are named
`pennywarden-backup-…` (1.6.6 to 1.6.8: `fundwarden-backup-…`); older backup files still restore.

## Turning the module on (Administrator)
System/About → **Optional modules** → tick **Fundraiser module**. Budget Managers, Budget Users, Register Users and
Auditors then see **Fundraisers** in the menu (after their next sign-in or page reload). Turning it off hides the
module; nothing is deleted.

## Setting up a fundraiser (Budget Manager)
Set it up as soon as it is agreed — even a year ahead.
1. Fundraisers → **New fundraiser**: name, description and the **event date(s)** (the day or days the event takes
   place; leave the end date empty for a one-day event).
2. **Budgets:** pick the income and/or expense budget. You can choose from a Fiscal Year that is set up and open
   when the event is inside it or within **3 months** of its start or end — so a January event can use this year's
   budget for the preparation and next year's for the event. At most two Fiscal Years, one income and one expense
   budget each. If next year is not set up yet, save now and come back to add its budget once it exists (Draft is
   enough). Choosing a parent budget includes all its sub-budgets; choosing an "Other" budget may mix in unrelated
   items — the form warns about both.
3. **Description filter (optional):** only lines whose description contains this text count (any case). Tick
   *Advanced* to use a regular expression. The form shows how many lines will be included.

Everything allocated to the chosen budgets counts — purchases before the event and deposits after it included.
Transactions are always entered in the Register as usual.

## Viewing a fundraiser (everyone with access)
Choose the Fiscal Year (or *Upcoming — no Fiscal Year yet*) and open a fundraiser: income, expenses, net and the
return on expenses, a breakdown per Fiscal Year, charts, every included transaction (the account links to the
Register) and the transactions' attachments. Notices remind you, for example, to select next year's budget.

## Managing a fundraiser (1.6.1 — Budget Managers and Register Users)
- **Buckets:** in the *Buckets* section click **New bucket** (e.g. *Food sales*, *Raffle*). In the transaction list
  click **Manage** on a line and enter the amount for each bucket (**All remaining** fills in what is left). One
  deposit can be split across several buckets. Each bucket shows its income, expenses and net.
- **Cash float:** on the withdrawal that took cash out for the cash box, click **Manage** → tick **Cash float out**
  and enter the amount. On the deposit that brought it back, tick **Cash float returned** and enter the float amount
  (e.g. 200 of a 1,450 deposit). Those amounts no longer count as fundraiser expenses or income.
- **Exclude a line:** **Manage** → *Exclude this line from the fundraiser* and give a reason. The transaction itself
  is unchanged in the Register.
- **Fundraiser documents:** add flyers, permits or tally sheets under *Fundraiser documents*.
- Lines in a closed Fiscal Year can no longer be changed.

## Fundraiser report (1.6.2)
- **Report (PDF)** on a fundraiser's page prints the whole fundraiser: figures, buckets, every transaction line,
  excluded lines, and the documents and attachments themselves.
- Reports → **End of Year Audit** and **Fiscal Year Close**: *Include fundraisers* (ticked by default) adds the same
  section for every fundraiser of that Fiscal Year (not archived), after the transactions and before the signature
  page. A fundraiser that spans two Fiscal Years appears complete in both years' reports.

## Reminders and notifications (1.6.3)
- The **bell** at the top right shows how many reminders are due; click it for the **Notifications** page (Due,
  Upcoming, Resolved). Due reminders are also shown at the top of the dashboard.
- **New reminder** (Budget Managers and Register Users): what to remember, the due date, optionally *show days
  before*, details and a link to a Fiscal Year, budget or bank account. Budget Managers choose whether it is for
  themselves or for the **whole organization**.
- A reminder stays in the notifications until someone clicks **Resolve** (a note is optional). Organization reminders
  can be resolved by Budget Managers and Register Users; Budget Users and Auditors just see them. A resolved reminder
  can be **reopened**.
- A reminder can be edited or deleted only before it is shown.
- **Repeating organization reminders (1.6.7).** In *New reminder* for the whole organization, set **Repeat** to
  *Repeats every…* and choose the number and the period (days, weeks, months, years), optionally an **Until** date.
  The reminder shows "Repeats every 3 months". When it is resolved, the next one is created automatically, due one
  interval after the due date of the one just resolved (resolving late does not shift the schedule). Budget Managers
  see the next one under *Upcoming* and can still edit or delete it there. To end the series, tick **Stop repeating
  after this one** when resolving, or delete the upcoming one. Reopening a resolved reminder removes the next one it
  created; it is created again when you resolve.

## Cancelled fundraisers and the cash count sheet (1.6.4)
- **Mark as cancelled…** (Budget Manager) when a fundraiser did not take place as planned; give the reason. The
  fundraiser shows *Cancelled* everywhere, including its report and the Audit / Close reports. Money already spent or
  received stays listed and counted. **Reinstate** undoes it.
- **Cash count sheet…** opens a PDF to print for the count: bills and coins, 13 checks, the totals (you can fill
  in just the totals), two lines for notes and one signature row per person. The dialog starts with two empty
  rows — for when you do not yet know who will count; each prints **Signature**, **Printed** name and **Date**
  lines. Choose a signer in a row to get one long signature line with the name and title printed under it. Up to
  five rows; at most three may be empty (two next to chosen signers). **Page 2** (optional, on by default) has 30
  more check lines — print it on the back or as a second sheet. Scan the signed sheet and add it under
  *Fundraiser documents*.
- **Position (1.6.7).** Under *Entities*, an individual can be given a **Position in the organization** (for
  example "Treasurer"). It is filled in as the title when that person is chosen as a signer here or on the audit
  review signature page; you can still change it for that one print.

## Archive or delete
**Archive** hides a finished fundraiser from the list (tick *Show archived* to see it). **Delete** removes a
fundraiser's settings (never transactions); it is not possible once one of its Fiscal Years is closed or while it
has buckets, cash-float marks, exclusions or documents.

## Account start and end pages in the Audit and Close reports (1.6.7)
When the End of Year Audit Report or the Fiscal Year Close Report contains transactions of more than one bank
account, the transactions are grouped by account and each group is framed:
- a **Start of transactions** page before the account's first transaction and an **End of transactions** page after
  its last one. Both show the account, how many transactions it has (active / VOID), deposits and withdrawals, the
  first and last transaction, and the pages the account occupies — for example "pages 4 to 9 of 12 (6 pages)";
- every page of the group shows the account and **section page k of n** at the bottom right, above "Page x of y".

To check that a printed report is complete: for each account, find the start page, read its page range, and confirm
that the section page numbers run from 1 to n up to the end page. A report limited to one account has no such pages.

## Phone numbers of Entities (1.6.7)
Type the number however is convenient: `5551234567`, `555-123-4567`, `555.123.4567`, `(555) 123-4567`, with or
without a leading 1. PennyWarden stores the plain digits and shows **(555) 123-4567** everywhere. For an extension add
`x204` (or `ext 204`); for a number in another country start with `+` and the country code. A number that is neither
is refused, so a typing mistake (a missing digit) is caught when you save.
