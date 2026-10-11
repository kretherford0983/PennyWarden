# What's new in 2.0 — quick guide

*2.0.0: the Payments module (check printing, payments, cover letters and envelopes). 2.0.0 is tested in several test builds; this guide grows with each one. The full
guide is [check-printing.md](check-printing.md).*

## Check printing (test build 1)
PennyWarden can now print your checks on printable check stock that already carries the bank numbers.

**Administrators** turn it on in **System/About → Optional modules → Payments module**, then open **Payments Setup** to:
- create a **check style** from a preset (the first preset is a Letter sheet with three 3.5-inch checks) and adjust
  where each field prints, with a preview drawn to scale;
- choose fonts, how the amounts look, and a **default memo** such as `{BUDGET_CODE}, INVOICE {INVOICE}`;
- add **signers** with a signature image, and optionally an amount above which no signature prints;
- print a **test print** and a **calibration page** on plain paper.

**Register Users** open a withdrawal in the **Register** and click **Print check…**:
- check the preview, the feed mode (the last check on a sheet goes through the manual feed on its own) and the memo;
- type the number printed on the check in the printer, then print at **actual size**;
- afterwards choose **Yes – done**, **Reprint** (the check was not damaged) or **Mark spoiled** (its number becomes a
  $0.00 VOID record and you print on the next check).

A record copy of every printed check is attached to the transaction. If the printing is shifted on your printer, the
**Printer setup assistant** on the print screen adjusts it for you without changing anyone else's settings.

## Payments (test build 2)
**Payments** in the menu (Register Users) enters a bill and prints its check in one go: pay from (your last account is
remembered), date, payee (or a new one), one line per invoice with its documents — the check amount is shown in words
as you type. **Save and print check** records it in the register and opens the print screen. **Create payment…** on a
withdrawal already in the register shows its details locked and prints its check.

## Cover letters and envelopes (test build 3)
Administrators keep **cover letter** and **#10 envelope** templates in Payments Setup (letterhead, text with
`{VARIABLES}`, the invoice table; envelope return address and feeding). After a check prints, the print screen offers
the letter and the envelope; they are attached to the transaction. For a check written by hand, choose **I'm writing
the check by hand**, record its number (typed twice), and print the letter and envelope. Withdrawal lines can carry an
optional **invoice date**. Details: [Check printing](check-printing.md#cover-letters-and-envelopes).

## Voucher checks and two signatures (test build 4)
Administrators can create a **voucher check** style (one check per sheet with a vendor-copy and an office-copy stub
listing the invoices paid, the total and the check number) and give any style **two signature lines**. Register Users
then choose two different signers when printing; above an optional amount only the first signature prints. Details:
[Check printing](check-printing.md#10-voucher-checks-check-with-stubs).
