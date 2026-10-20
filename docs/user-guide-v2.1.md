# What's new in 2.1 — quick guide

*2.1.0 (in progress): this guide grows with each test build.*

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

### Budget Prep report
**Reports → Budget Prep.** Choose the Fiscal Year and how many earlier years to show (or *All linked years*), then
**Run report**. For each budget you see, per year: what was budgeted, the actual, and the difference — in dollars and
percent, with *over* or *under* in words (*n/a* when nothing was budgeted).
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
On the Fiscal Year screen, **Planning sheet…** prints the form for the budget planning meeting. It is in portrait, on
as few pages as possible:
- **page 1:** the organization, the current and the new Fiscal Year, attendee lines, and the meeting date (top right).
  Then the **Income** and **Expense** tables: Budget Code, Budget Description, Previous Budgeted, Actual YTD (dated),
  Projected, and a blank **Proposed Budget**, plus four blank rows for new budgets;
- **the last page:** more blank Income and Expense tables.

If the next Fiscal Year already exists as a **Draft**, the sheet fills in its name and dates and shows each draft
amount as *Proposed*, with a blank **Proposed Revision** column to write changes in. A renumbered budget shows the
draft code with the previous code under it. A new draft budget is marked *new in draft*, and a current budget that
isn't in the draft is marked *not in draft*. After the meeting, scan the sheet and attach it to the new Fiscal Year as
an Other document — it is not required for closing a year.

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
