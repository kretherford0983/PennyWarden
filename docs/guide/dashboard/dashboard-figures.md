How the Dashboard's budget boxes are worked out. Every figure comes from the transactions in the register; nothing is
estimated except the **projected year end**, and that is labelled as a projection.

## Income budget and Expense budget

- **The big amount** is the total of the Fiscal Year's budgets of that type. Rejected and inactive budgets are left
  out, and Budget 0 (transfers between accounts) is never counted. Budget amounts are
  [gross](../budgets/about-budgets.md): a reimbursement recorded as income doesn't reduce an expense budget.
- **Actual** is everything recorded against those budgets so far: every transaction allocation that isn't voided,
  whatever its date. Activity on a budget that was later rejected or made inactive still counts, so the totals match the
  register. On an Invoiced Income budget, a refund to a customer counts as a negative amount.
- **Remaining** is the budget minus the actual. When income is more than its budget, the box says how much it is
  **above budget** instead; when an expense budget is overspent, Remaining is shown in red as a negative amount.

## FY Progress

**The big amount: the result so far.** The Income box's *Actual* minus the Expense box's *Actual*. More income than
expenses is a **surplus** (green, +); more expenses than income is a **deficit** (red, −).

**Budgeted** is the result the budgets plan for: the Income budget minus the Expense budget (the two big amounts beside
it). A plan that spends more than it expects to bring in shows as a budgeted deficit.

**Projected year end** is an estimate of the result when the Fiscal Year ends. It is worked out separately for income
and for expenses, then the expenses are subtracted from the income:

1. Start with what has come in (or gone out) this year so far.
2. For each of the **previous three Fiscal Years** in PennyWarden, find how much came in (or went out) in the *rest of
   that year*: from the same point in the year (the same number of days after its start) to its end.
3. Take the **middle** of those three amounts (the median) and add it to this year's figure.

Example, for income, on April 30 of a January–December year:

| | By April 30 | Rest of the year |
|---|---|---|
| Three years ago | $1,000 | $2,000 |
| Two years ago | $1,000 | $2,200 |
| Last year | $1,000 | $9,000 (a one-time grant) |
| **This year** | **$1,500** | **projected: $2,200** (the middle of $2,000, $2,200 and $9,000) |

Projected income for the year: $1,500 + $2,200 = **$3,700**. Expenses are projected the same way, and the projected
year end is projected income minus projected expenses.

Why it is done this way:
- **Seasons are respected.** Money that always comes in at the same time of year (a January fundraiser, say) is
  expected again only where it came in before, so an early-year boost isn't stretched over the whole year.
- **Being ahead or behind carries through.** If this year is $1,000 behind where past years were by now, the projection
  stays $1,000 lower; it doesn't assume the gap will be made up.
- **One unusual year doesn't skew it.** Using the middle of three years means a one-time grant or a one-time large
  expense in a single year is ignored.

Fewer previous years:
- **Two previous years:** the average of their rest-of-year amounts.
- **One previous year:** its rest-of-year amount.
- **None** (the first year in PennyWarden): this year's pace — what has come in (or gone out) so far, spread evenly
  over the whole year. For example, $1,500 in the first 4 months becomes $1,500 × 12 ÷ 4 = $4,500 for the year. The box
  then says *this year's pace; no previous year to compare*.

When there is no projection:
- **The first 3 months** of the Fiscal Year: *not enough information yet*.
- **After the Fiscal Year has ended:** the box shows *Year ended*, and the result is final.

The projection is a guide, not a forecast anyone has approved: it assumes the rest of this year will go like the middle
of the past years did.
