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

## Bank accounts

### Fix a wrong balance in the history
In **Bank Accounts → History** (accounts without a register), each entry's **⋯** menu has:
- **Correct…** — change the amount and/or the *as of* date, for example a balance typed wrong or given the wrong
  date. The entry is marked **Corrected**; hover over the mark to see what it was before.
- **Retire…** — take a wrong entry out. It stops counting and is listed under **Retired entries** with your reason.

Both ask for a reason and are recorded in the audit log. The account's current balance updates straight away.
Nothing is ever deleted.

### Balances from before PennyWarden
You can add balances dated before your first Fiscal Year in PennyWarden (with *Update balance* and an earlier *As of*
date) to fill in the history, even before the account's opening balance date. They are marked **Entered**.

### Closed Fiscal Years
Balances inside a Closed Fiscal Year can't be changed by Budget Managers. A **Budget Admin** can add, correct or retire
one there: you give a reason and confirm that you are changing a closed year (it was closed with the old balance).
The Fiscal Year page and its reports then show **Balance changed after close** with what changed, who changed it and
why.

## System/About

### Choose which releases the update check looks at
Under **System/About → Settings**, an Administrator can change **Update channel**:

| Choice | What the update notice tells you about |
|---|---|
| **Follow this build** (default) | Production builds: production releases. Test builds: newer test builds and production releases. |
| **Production releases only** | Production releases — a test build is also told when the final release of its own version is out. |
| **Test builds and production releases** | Test builds (pre-release) too, each linked to its GitHub release page. |
| **Off** | Nothing; the check makes no requests. The *Check for updates* switch is still the usual way to turn it off. |

The change is saved to `config.toml` and works straight away — no restart needed. On a **local install** this is
the only setting you can change from the app. On a production installation, choosing test builds asks you to confirm:
test builds are pre-release and not production ready, so only install them on a system you use for testing.
PennyWarden never installs an update by itself.
