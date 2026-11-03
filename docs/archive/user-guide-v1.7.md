# What's new in 1.7 — quick guide

*1.7.0: the application is renamed PennyWarden. 1.7.1: your name in the top bar, a display name for every user,
bank accounts in the order you choose, start and end pages for the fundraisers in the Audit and Close reports.
1.7.2: Current and Available balances; on a server, Administrators cannot change their own roles.
1.7.3: the Register filtered by budget, links from the Budgets page, and deleting a mistaken budget or
transaction.*

## 1.7.3: balance history for investment and other accounts
Accounts without a register (investments, CDs, cash, …) now keep every balance you enter:
- **Update balance** asks for the balance and its **As of** date — today, or an earlier date such as a statement
  date. Each update is a new entry; nothing is overwritten.
- The account shows the balance with the **latest** date. Entered a wrong figure? Enter the right one for the same
  date — the one entered last counts — and both stay in the history.
- **History** (under the balance on the Bank Accounts page) lists every entry: date, balance, change from the one
  before, who entered it, when, and the reason.
- The Dashboard's **Bank balances** chart now shows these accounts too.
- Your existing accounts already have a history: PennyWarden rebuilt it from the audit log when it was upgraded.

## 1.7.3: deleting a mistake
Two new roles an Administrator can give under **Users**, each only together with its usual role:

| Role | Needs | Can delete |
|---|---|---|
| **Budget Admin** | Budget Manager | a budget of a Fiscal Year that is **not approved yet** — e.g. one copied into the new year by mistake |
| **Register Admin** | Register User | a transaction that has **not cleared** — e.g. one entered twice |

- The red **Delete…** button is in the budget's or the transaction's **Edit** dialog, away from Save. You must give
  a reason.
- Deleted means gone for everyone except **Auditors**: they still see the budget or transaction, marked *Deleted*,
  with your reason (in the Register: Status → *Deleted*). Nothing is erased, and the audit log records who deleted
  what and why.
- A **cleared** transaction has posted at the bank and cannot be deleted. If you put the clear date on the wrong
  line, remove it first, then delete. VOID records stay as they are.
- A budget that has transactions allocated to it, or sub-budgets, cannot be deleted until they are moved or deleted.
- Deleting one side of a transfer deletes both sides. A deleted check's number stays used.

## 1.7.3: see a budget's transactions
- **Register → Budget:** choose a budget to see only its transactions. A parent budget shows its sub-budgets'
  transactions too. A transaction split across several budgets shows this budget's part, e.g. *$40.00 of $100.00*.
  The list of budgets follows the Fiscal Year filter; with *All dates* every year's budgets are listed, each with its
  year. The filter stays when you switch bank accounts; **Clear** removes it.
- **Budgets page:** click a budget's code or name to open the Register with that budget already chosen, on your
  default account and in that budget's Fiscal Year (also when you are looking at a previous year).


## 1.7.2: Current and Available balances
PennyWarden now keeps two balances for every register account, the way your bank thinks about them:

| | What it counts | Where you see it |
|---|---|---|
| **Current balance** | Only what has **cleared** — the bank's own balance | Everywhere: Bank Accounts, Dashboard, charts, Register |
| **Available balance** | Everything you have written or deposited, cleared or not | The Register |

Example: the bank shows $10,000.00. You wrote check #101 for $500.00 that has not been cashed, and made a $200.00
deposit the bank has not posted yet. Current balance: **$10,000.00** (what the bank has). Available balance:
**$9,700.00** (what you really have once everything clears).

**After the upgrade** the Dashboard and the Bank Accounts page show the Current balance. If some transactions are not
marked cleared yet, those numbers are lower or higher than before — mark them cleared as the bank posts them (Clear/
Post Date) and the two balances meet.

**In the Register** you see:
- **Opening balance** — for a Fiscal Year: what you had at the end of the day before the year started, counting
  everything written or deposited by then. Under it, **Bank $…** shows what the bank had that day and the
  outstanding items (written or deposited, not cleared by then) that make up the difference — a bank reconciliation.
  Clearing those items in the new year does not change last year's numbers.
- **Current** and **Available** balance — for an open Fiscal Year.
- **Ending balance** with its reconciliation — for a **Closed** Fiscal Year (instead of Current and Available), or
  when you choose a *To* date.
- The **Balance** column on each line works as before (everything written or deposited).

**New check:** the Clear/Post Date cannot be before the transaction date — the bank cannot cash a check before you
write it. If an older transaction breaks this rule, PennyWarden asks you to correct it the next time you edit it.

## 1.7.2: on a server, your own roles are changed by another Administrator
On a server, when you edit **your own** account under **Users**, the *Security domain* and *Roles* are greyed out:
another Administrator has to change them. This keeps one person from giving themselves different rights without
anyone else being involved. You can still change your own email address and display name, and you can change the
roles of every other user, other Administrators included. Keep at least two Administrators on a server.
Also, on every install, the **Active** box of your own account is greyed out: you cannot disable yourself.
On a Windows PC or a Mac (local install) nothing changes.

## 1.7.1: your name in the top bar
The top bar now shows your **display name** — for example *Jordan Lee* — instead of your username, and no longer
lists your roles next to it. Your username, email address and roles are on **My account**.

**Administrators:** every user now has a display name of at least 3 characters.
- **New user:** *Display name* must be filled in. Leaving it empty gives "Display name is required."; fewer than 3
  characters gives "Display name must be at least 3 characters." Spaces before and after the name are removed.
- **Editing a user:** the display name can be changed but not removed.
- **Existing users** who had no display name were given their username as display name by the upgrade — nothing
  looks different for them until you enter their real name under **Users → Edit**. The Users list has a
  *Display name* column so you can see who still shows a username.
- The first Administrator created by the Initialization Wizard also starts with the username as display name.

## 1.7.1: bank accounts in the order you choose
**Budget Managers** decide the order in which bank accounts are listed. On **Bank Accounts**, each account has
**▲** (move up) and **▼** (move down) buttons in the *Order* column. Each group — *Checking & Savings* and
*Investments and Other* — has its own order; moving an account never changes the other group.
- The same order is used on the **Dashboard** and in the **Register**'s bank account list.
- The **Primary** account is not kept at the top: put it wherever you like. The Register still opens on the
  Primary account, wherever it is in the list.
- After the upgrade nothing looks different: each group lists the Primary account first and the others by name.
  A new account is added at the end of its group.
- **Keyboard:** Tab to a button and press Enter or Space. The focus stays on the account you moved, so you can
  keep pressing to move it further; a screen reader announces the new position ("Savings moved to position 1 of
  3 in Checking & Savings.").
- Other users see the order but cannot change it. Every change is in the audit log.

## 1.7.1: fundraisers in the Audit and Close reports
When an Audit or Fiscal Year Close report includes fundraisers, they now begin with a **Start of fundraisers** page
and finish with an **End of fundraisers** page. Both state which pages the fundraisers take up — for example
"pages 36 to 42 of 42" — and every page in between is marked "Fundraisers - section page 3 of 7" at the bottom
right. A reviewer holding the printed report can see where the fundraisers begin and end and that no page is
missing, the same way as for each bank account's transactions.

## 1.7.1: smaller changes
- **Entities:** on the Entity form the Email and Phone boxes are level, with a shorter hint under Phone.
- **Bank Accounts:** creating an institution from the New bank account form no longer clears what you typed
  while it was being added.
- **Installing on a Mac:** a new page, [Installing PennyWarden on a Mac](../install-macos.md), shows each step with
  a picture — including the one-time *Open Anyway* in System Settings.

## 1.7.0: a new name — PennyWarden
The application is now called **PennyWarden**. Another product in the financial field already uses the name it had
from 1.6.6 to 1.6.8 (*Fundwarden*). The icon — the gold coin with a keyhole — stays.

**Nothing about your work changes:** same address, same sign-in, same data, same screens.

What you may notice:
- The name in the browser tab, on the sign-in page, in the top bar and on reports.
- **Two-step verification** keeps working. The entry in your authenticator app keeps its old label; you do not need
  to set anything up again. A new set-up is labelled *PennyWarden*.
- **Backups** are now named `pennywarden-backup-…`. Backup files made earlier restore exactly as before.
- **Bookmarks** keep working — the address of your installation has not changed.

## If you look after the installation
- **Server (Linux):** run the usual upgrade command. The installer moves the installation to the new name by
  itself and leaves the old one in place until you remove it. Steps, going back and the cleanup checklist:
  [upgrade.md](../upgrade.md), *1.7.0: the rename to PennyWarden*.
- **Windows PC:** download the new `PennyWarden-<version>-windows-x64.exe` (or the zip) and start it. Your data
  folder is renamed by itself at the first start; delete the old program when you no longer want it.
- **Mac:** download the new `.dmg` and drag **PennyWarden** to Applications. macOS sees a new app, so the *Open
  Anyway* step in *Read me first* is needed once more. Your data is found by itself; delete the old app afterwards.
- **Downloads** are now at `github.com/kretherford0983/PennyWarden`. Old links are forwarded.
