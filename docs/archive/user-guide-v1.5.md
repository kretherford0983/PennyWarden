# What's new in 1.5 — quick guide

*1.5.0 polishes existing features; nothing new is added.*

## Signing in from a bookmark
Opening any bookmarked PennyWarden page while signed out shows the sign-in page, then two-step verification (or its
setup), then the dashboard.

## Bank Accounts in two groups
The Bank Accounts page has two tables: **Checking & Savings** and **Investments and Other** (investment, cash and
other accounts). Each table ends with the total of its active accounts. The dashboard's bank balances show the same
two groups with a subtotal each, then the total of all accounts.

## Preview the audit signature page
Reports → End of Year Audit → tick *Include audit review signature page*, choose the wording and signers, then click
**Preview signature page**. The page opens as a PDF in a new tab so you can check it before generating the report.

## Customize the dashboard
Click **Customize dashboard** (top right of the dashboard). Untick a section to hide it and use **↑** / **↓** to move
it. Changes are saved for your account straight away. **Reset to default** brings back the standard layout. The
Administrator dashboard cannot be customized.

## Installing
- **Windows:** download `PennyWarden-<version>-windows-x64.exe` from the release page and double-click it. If Windows
  says "Windows protected your PC", click **More info → Run anyway**. Keep the black window open while you use
  PennyWarden; closing it stops the app. Your data is kept separately, so a newer .exe simply replaces the old one.
- **Linux server:** one command installs or upgrades — see docs/deployment.md (*Linux: one command*).

## License and source code
PennyWarden is free software (AGPL-3.0). The sign-in page and **My account** show links to the source code, the license
and the third-party notices.

## Charts
Dashboard charts are arranged in two columns that each fill from the top, so there are no gaps under short charts.
On a narrow screen they are shown in one column.
