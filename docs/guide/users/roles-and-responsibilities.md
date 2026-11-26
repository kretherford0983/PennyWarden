PennyWarden splits the work on an organization's money between roles, so that **no single person controls the whole
life of the money**: one person sets the budgets, another records what came in and went out, and someone else can
review all of it. Mistakes get caught because more than one person sees the work. A small organization can still give
one person several roles.

## Security domains

Every role belongs to one of three **security domains**:

| Domain | Roles | In short |
|---|---|---|
| **Administration** | Administrator | Runs the installation: users, settings, backups. Never sees the money. |
| **Financial** | Budget Manager, Budget Admin, Budget User, Register User, Register Admin, Invoice Manager | Does the financial work. |
| **Audit** | Auditor | Reviews everything and changes nothing. |

### On a server

On a **server** install (several people signing in through a browser), each account belongs to **exactly one
domain**:

- An **Administrator can't also hold a Financial or Auditor role**. The person who controls user accounts and backups
  never sees or changes financial records, so they can't, for example, add themselves a role, enter a payment and
  remove the trace.
- A **Financial user can't also be an Auditor**. The person reviewing the books must not be one of the people keeping
  them.
- **Financial roles can be combined freely**, for example Budget Manager and Register User for a treasurer who does
  both.

The **New user** form on a server asks for the security domain first and only offers that domain's roles. If roles
from different domains are sent anyway, PennyWarden refuses them: *"Roles from different security domains
(Administrator, Financial, Auditor) cannot be combined."*

Other server-only rules:

- **Two-step verification is required** for every account.
- An Administrator **can't change their own roles** (another Administrator has to), so keep at least two
  Administrators. At least one active Administrator must always remain, on any install.

### On a local install

On a **local install** (PennyWarden on one person's own Windows, Mac or Linux computer), one account **may hold roles
from every domain**. Its security domain shows as **Combined**. The first user of a local install gets every role
except Budget User, which a Budget Manager doesn't need.

This is for the one-person organization, or the treasurer who keeps the books alone: the separation between the
domains is then the organization's own choice, not something PennyWarden enforces. If several people share the work,
a server install keeps their duties apart. In the user list on a server, an account that still has combined roles
(for example one brought over from a local install) is marked **Local-only roles** until an Administrator chooses roles
of a single domain.

### Add-on roles

- **Budget Admin** can only be given together with **Budget Manager**.
- **Register Admin** can only be given together with **Register User**.

They add a few riskier actions, such as deleting instead of voiding, on top of the base role.

## What each role can do

### Administrator

Manages user accounts and roles; reads the Audit Log (without the financial values in its entries); changes the
settings, backups and sessions under System/About; turns the optional modules on and off; and sets up checks,
donation receipts, invoices and the outgoing email. Test prints use sample data only. **Never sees budgets,
transactions, bank accounts or any other financial record.**

### Budget Manager

Plans and governs the money: creates Fiscal Years, approves and closes them; creates and changes budgets; manages bank
accounts (and can see full account numbers) and Financial Institutions; reviews entity names; creates and manages
events; creates organization reminders; resolves Fiscal Year review items; approves or rejects invoice write-offs.
Sees the Register, invoices and the product catalog **but doesn't enter transactions or print checks**, so the person
who sets the budgets isn't also the one spending against them.

### Budget Admin (with Budget Manager)

Deletes a budget of a Fiscal Year that isn't approved yet, and adds, corrects or retires a non-register account
balance inside a Closed Fiscal Year (confirmed, with a reason).

### Budget User

Looks at the financial information (budgets, Fiscal Years, the Register, reports, events, donations, invoices, the
product catalog and reminders) and **changes nothing**. Good for board members who should see the numbers.

### Register User

Keeps the register: enters, edits and voids transactions; adds and edits entities (including new Financial
Institutions); resolves review items and organization reminders; assigns event lines to buckets; prints checks and
makes payments (Payments module); marks donations and prints receipts (Donations module); records invoice payments
and refunds, and links or unlinks them (Invoices module).

### Register Admin (with Register User)

Deletes a transaction that hasn't cleared yet, instead of voiding it.

### Invoice Manager

Bills customers (Invoices module): creates, revises and sends invoices and statements, keeps the product catalog,
adds and edits customers, links a deposit that's already on an Invoiced Income budget to an invoice, and asks for
write-offs (a Budget Manager approves them). Sees the Register read-only. Has no budget or Fiscal Year screens. The
person who bills isn't the one who records the money received or approves writing it off.

### Auditor

Sees everything — users, the Audit Log including the financial values in its entries, the effective settings and
sessions, and every financial record, including inactive, rejected, deleted and voided ones — and **changes nothing**.

## Who can do what

✓ = the role can do it. Budget Admin and Register Admin are always held together with Budget Manager and Register
User, so they also have those columns' ticks.

| Task | Administrator | Budget Manager | Budget Admin | Budget User | Register User | Register Admin | Invoice Manager | Auditor |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Manage users and roles | ✓ |   |   |   |   |   |   |   |
| See the list of users | ✓ |   |   |   |   |   |   | ✓ |
| Read the Audit Log | ✓ |   |   |   |   |   |   | ✓ |
| See the financial values in Audit Log entries |   |   |   |   |   |   |   | ✓ |
| Change System/About settings, backups and sessions | ✓ |   |   |   |   |   |   |   |
| Turn optional modules on or off | ✓ |   |   |   |   |   |   |   |
| Set up checks, donation receipts, invoices and email (test prints only) | ✓ |   |   |   |   |   |   |   |
| See budgets, Fiscal Years and the reports |   | ✓ |   | ✓ | ✓ |   |   | ✓ |
| See the Register |   | ✓ |   | ✓ | ✓ |   | ✓ | ✓ |
| Create, approve and close Fiscal Years |   | ✓ |   |   |   |   |   |   |
| Create and change budgets |   | ✓ |   |   |   |   |   |   |
| Delete a budget of a Fiscal Year not yet approved |   |   | ✓ |   |   |   |   |   |
| Change a non-register balance in a Closed year |   |   | ✓ |   |   |   |   |   |
| Manage bank accounts and see full account numbers |   | ✓ |   |   |   |   |   |   |
| Enter, edit and void transactions |   |   |   |   | ✓ |   |   |   |
| Delete a transaction that hasn't cleared |   |   |   |   |   | ✓ |   |   |
| Add and edit entities |   | ✓ |   |   | ✓ |   | ✓ |   |
| Resolve Fiscal Year review items |   | ✓ |   |   | ✓ |   |   |   |
| Create and manage events |   | ✓ |   |   |   |   |   |   |
| Assign event lines to buckets |   | ✓ |   |   | ✓ |   |   |   |
| Create organization reminders |   | ✓ |   |   |   |   |   |   |
| Print checks and make payments |   |   |   |   | ✓ |   |   |   |
| Print donation receipts |   |   |   |   | ✓ |   |   |   |
| Create and send invoices |   |   |   |   |   |   | ✓ |   |
| Keep the product catalog |   |   |   |   |   |   | ✓ |   |
| Record invoice payments and refunds |   |   |   |   | ✓ |   |   |   |
| Link an existing deposit to an invoice |   |   |   |   | ✓ |   | ✓ |   |
| Approve or reject invoice write-offs |   | ✓ |   |   |   |   |   |   |

Menus and buttons only show what your roles allow. PennyWarden also checks every action on the server, so a hidden
button is never the only protection.

## Optional modules

An Administrator turns each module on under System/About. Its screens appear only then, for the roles below:

| Module | Who works in it |
|---|---|
| **Events & Fundraisers** | Budget Managers create the events; Register Users assign their lines to buckets; the other financial roles and Auditors look. |
| **Payments** (checks) | Register Users only; the Administrator sets up check styles and signers. |
| **Donations** | Register Users mark donations and print receipts; the other financial roles and Auditors look; the Administrator sets up the receipt. |
| **Invoices** | Invoice Managers bill; Register Users record the money; Budget Managers approve write-offs; the Administrator sets up numbering and the invoice layout. |

See also [Managing users](manage-users.md) and [Who does what](../getting-started/who-does-what.md).
