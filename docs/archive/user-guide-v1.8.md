# What's new in 1.8 — quick guide

*1.8.0: budgets linked across Fiscal Years, the Financial Flow Report, a forgotten password reset with security
questions, and configuration notes for the Mac.*

## 1.8.0: forgot your password?
**Security questions.** At your next sign-in PennyWarden asks you to choose **three security questions** and answer
them. Pick questions whose answers you will remember and that other people cannot easily find out. Upper and lower
case, spaces and punctuation do not matter ("Rex", "rex" and "REX!" are the same). You can change them in
**My account → Security questions** (your password is needed).

**Forgot password?** On the sign-in page, click **Forgot password?**, enter your username and answer the question
shown. On a server — or if you turned on two-step verification — also enter the code from your authenticator app or
one of your recovery codes. Then choose a new password. You are signed out on every computer; sign in with the new
password. At your next sign-in you see when the password was reset — if it was not you, tell an Administrator.

**Too many wrong tries.** Wrong passwords and wrong answers add up: after 5 in a row your account is locked for 15
minutes, after 10 for an hour, after 15 for a day, and after 20 it is disabled until an Administrator enables it again.
Signing in successfully starts the count over.

**Administrators** see a notice at the top of the page when someone reset their password this way, or when an
account was locked for an hour or more or disabled. On the **Users** page they see who has set up their questions,
can **Reset security questions** (the user chooses new ones at the next sign-in) and enable a disabled account again.
If you are the only Administrator and forgot both your password and your answers, run on the computer or server
itself `pennywarden reset-password --user NAME` (on a Mac:
`/Applications/PennyWarden.app/Contents/MacOS/PennyWarden reset-password --user NAME`): it prints a temporary
password that you change at the next sign-in.

## 1.8.0: the Financial Flow Report
**Reports → Financial Flow.** Enter a **Title** (e.g. "August 2026"), the **From Date**, and a **Through Date** — or
leave it empty for "Current" (today). Choose the account(s), and optionally **Include Bank Balances** with a
**Compare Date** (e.g. the date of your last report) and **Notes** to print on the report. Then **Review
transactions**.

The review shows every line of the report, one section per account:

- **Income** — every part of each deposit (a deposit from three donors is three lines); **Expenses** — one line per
  withdrawal. Uncleared transactions are included; transfers between your accounts and VOID transactions are not.
- **Uncheck** a line to leave it out of the report and its totals, for example a transfer that was entered as a
  withdrawal and a deposit. You are asked **why**; the reason is kept in the audit log with the report and is not
  printed. Checking the line again discards the reason.
- Type a **note** on a line to print it with that line. The transaction itself is not changed.

**Generate PDF** makes the report from the checked lines; **Open PDF** / **Download PDF** then show or save it. The
review is not saved — to keep a report, upload the PDF as a Fiscal Year document.

With **Include Bank Balances**, the report ends with the bank balance of every account on the Through Date (Checking,
Savings, Investments, Total Assets) and, with a Compare Date, each balance then and how much it grew or shrank.

## 1.8.0: budgets across Fiscal Years
A budget's ID or name sometimes changes from one year to the next. To keep track, open the budget's **Edit** dialog
(or create the budget) and choose in **Continues** the budget of an earlier year it carries on, e.g.
`FY2027 - 1000 - Operations`. The list offers budgets of the same type and level that no other budget continues yet.

- Budgets you **copy** into a new Fiscal Year are linked to their source for you.
- A budget with a link shows **History** next to its name on the Budgets page: every year of that budget with its
  ID, name, amount and actual, oldest first; the one you opened it from is highlighted.
- Choose **— None —** to remove a link. A locked budget is unlocked first, as for any other change.

## 1.8.0: configuration on a Mac
docs/configuration.md now has a section for the Mac: where the data folder and the log are
(`~/Library/Application Support/PennyWarden`, hidden in Finder — use **Go → Go to Folder…**), how to change settings
with `config.toml`, and how to start the app with options from Terminal.
