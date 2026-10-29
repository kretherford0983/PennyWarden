# What's new in 2.3 — quick guide

*2.3.0 is in progress. The full list is in the [changelog](../CHANGELOG.md).*

## Budgets

### Budget amounts are gross
A budget's amount and its actual are **gross**. When an expense is reimbursed, the reimbursement is recorded in an
income budget, so the expense budget's actual is not reduced by it — the expense budget can look over budget even
when the net cost was within plan. PennyWarden now says this wherever budget amounts appear:

- under the budget tables on the **Budgets**, **Fiscal Year** and **Budget Review** pages;
- behind the **ⓘ** on the Dashboard's budget tiles and on the *Expense budgets: budgeted vs spent* chart;
- as a small footnote under every budget table in the printed reports (End of Year Audit, Fiscal Year Close, Budget
  Review, Planning Sheet), so it stays with a page that is copied or handed out on its own.

The budget form's **Amount** is now called **Gross amount**. Nothing is calculated differently.

## Fundraisers

### A goal for a fundraiser
*New fundraiser* and *Edit* have a **Goal (optional)** field — what the fundraiser aims to raise. When it is set, the
fundraiser's page shows the goal beside the totals and compares the **net** (income minus expenses) with it: the
percentage of the goal reached and how much is still to go, or how far the goal was beaten. Leave it blank for no
goal. The goal is for information only and never stops anything from being entered. *Create next year's* starts the
new fundraiser without a goal.
