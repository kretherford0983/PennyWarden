# 05 --- UI and Workflow Specification

## 1. Role-Aware Navigation

### Administrator

-   Users
-   Audit Log
-   System/About (2.2.0, #280: with a **Branding** tab — see §Organization branding below)

### Financial User

Depending on assigned Financial roles: - Dashboard - Fiscal Years -
Budgets - Bank Accounts - Register - Entities

### Auditor

-   Dashboard
-   Fiscal Years
-   Budgets
-   Bank Accounts
-   Register
-   Entities
-   Users
-   Audit Log

Unauthorized modules are not shown.

## 2. Dashboard

The POC dashboard is intentionally modest.

Financial dashboard: - current fiscal year and status; - aggregate
income and expense budget information; - authorized bank-account
balances; - fiscal-year review items requiring attention.

Auditor dashboard: - fiscal-year status; - transaction count; - voided
transaction count; - cross-fiscal-year allocation count; -
rejected-budget activity; - other review-oriented summaries.

Administrator dashboard may be minimal and focused on user/security
administration.

## 3. Fiscal Years

### List

Display fiscal-year name, dates, and status.

### Detail

Selecting a fiscal year shows holistic data: - Income budgets and
Expense budgets in separate sections; - Q1, Q2, Q3, Q4 and yearly actual
activity; - budget amount, actual activity and remaining amount; -
status icon and visual treatment; - lifecycle/audit dates; - supporting
attachments.

Quarters are four consecutive three-month periods relative to the Fiscal
Year start date.

### Budget Status Presentation

-   Draft/unapproved: `?` icon and light-yellow background.
-   Approved and locked: closed-padlock icon and light-green background.
-   Approved and unlocked: open-padlock icon and light-green background.
-   Rejected: `X` icon and light-red background.

Status must also be conveyed textually or through an accessible
label/tooltip.

### Create Fiscal Year

Budget Manager supplies: - identifier; application prefixes `FY`; -
start date; - end date; - optional prior fiscal year from which budgets
are copied.

Copied budgets retain identifiers, names, type, hierarchy, sub-budget
structure, and prior-year amounts as starting Draft values. The wizard
lists copied budgets and permits removal before creation.

Validate date continuity against adjacent fiscal years: - normal:
previous end date + one day equals new start date; - overlap: strong
warning and explicit Budget Manager confirmation; - gap: strong warning
and explicit Budget Manager confirmation.

Overlap warnings should present relevant prior-year closure/readiness
information. If overlapping active fiscal years cover a transaction
date, transaction entry must not silently choose one.

### Approve

Only Budget Manager. Approval validates budget structures, changes
Fiscal Year to Approved, and locks active budgets.

### Close

Only Budget Manager. Closure is irreversible in the POC.

Block closure when: - Fiscal Year is not Approved; - any budget is
unlocked; - any applicable transaction is uncleared; - unresolved
fiscal-year review items exist; - invalid/incomplete allocation state
exists; - fewer than one supporting Fiscal Year attachment exists.

Warnings may identify rejected-budget activity, over-budget conditions,
reviewed cross-FY allocations, or voided transactions. Budget 0 activity
is not inherently a closure warning.

The Budget Manager must confirm that the Fiscal Year has been reviewed
and approved for closure.

## 4. Budgets

### Standard Display Identifier

Where budgets are referenced outside budget maintenance, display:
`<Parent ID>-<Child ID> <Budget Name>`

Example: `1000-01 Travel`.

When `Other` is the only child, display the parent as the usable budget.
When explicit sub-budgets exist, the parent is a roll-up and is not
selectable.

### Other

Every parent conceptually has a system-managed Other child. - Other =
Parent Amount - sum(explicit children). - Other cannot be manually
edited. - If Other is the only child, it is hidden and the parent is
presented to users. - If Other amount is 0.00, Other is hidden. - If
Other becomes positive later, it becomes visible/selectable again.

### Budget Screen

Similar presentation to Fiscal Year detail, but Budget Managers receive
edit controls such as a pencil icon.

Budget Manager may: - create/edit budgets; - add/edit sub-budgets; -
reject/inactivate budgets; - lock/unlock budgets.

Unlocking an approved budget requires a reason and is audited.

Transactions may exceed a budget. Remaining may become negative.

## 5. Bank Accounts

### List

Show: - account name; - masked account identifier; - financial
institution; - type/subtype; - register-enabled flag; - Primary flag; -
current balance; - status.

Register selectors display `Account Name - masked account number`.

### Create/Edit

Budget Manager manages: - account name; - Financial Institution
entity; - type/subtype; - full account number; - register-enabled
flag; - Primary flag; - optional interest rate; - opening balance and
date; - notes.

Checking and Savings default to register-enabled. Investment defaults to
not register-enabled, but may be overridden.

The account number must be unique within the workspace.

Only one register-enabled account may be Primary. Selecting a new
Primary clears the prior Primary.

A bank account cannot be inactivated/closed while it contains uncleared
transactions. Bank accounts are never deleted.

## 6. Entities

### Required Fields

Individual: - Primary Contact required. - Register display uses Primary
Contact.

Organization: - Organization Name required. - Register display uses
Organization Name.

Other contact fields are optional.

### Financial Institutions

Register User or Budget Manager may create a Financial Institution
entity. Once flagged as a Financial Institution: - Register User cannot
edit, inactivate, or remove that designation; - Budget Manager may edit
or inactivate it.

### Duplicates

Possible duplicates produce a non-blocking warning. Users may create a
duplicate after reviewing the warning.

Every Entity receives an immutable, system-generated Entity Number such
as `ENT-000001`. When duplicate names need disambiguation, selectors may
show the Entity Number.

Inactive entities are hidden from normal selectors but remain available
through filters and historical records.

## 7. Register

### Landing Page

Defaults: - Bank Account: Primary register-enabled account. - Fiscal
Year filter: Fiscal Year containing current date.

Register is continuous across account lifetime; Fiscal Year is a
date-based view/filter.

Filters include: - deposit/withdrawal; - cleared/uncleared/void; - date
range; - search by entity, description, invoice number, check number, or
amount.

Rows show an attachment indicator and may expand to display full
metadata and allocations.

### Dates

-   Transaction Date: user editable; defaults to current date.
-   Entry timestamp: system generated and immutable.
-   Clear/Post Date: nullable; null means uncleared.

### Normal Transaction

Every transaction has a parent Register Transaction and at least one
Transaction Allocation. A normal transaction has one allocation; the UI
presents it as a single entry.

Fiscal Year defaults to the year covering Transaction Date. Budget list
is then filtered by that Fiscal Year and transaction type: - Deposit -\>
Income budgets. - Withdrawal -\> Expense budgets.

Draft and Approved fiscal years may receive transactions. Closed fiscal
years may not.

Cross-FY assignment requires warning and confirmation.

If no Fiscal Year covers the transaction date, warn the user, present
the closest configured year without silently treating it as correct, and
flag the allocation for later Fiscal Year review.

### Split Transaction

Parent amount is always the sum of child allocations. Only the parent
affects bank balance.

Withdrawal split: - one parent payee/entity; - child entity inherited
and not editable; - children may vary invoice, budget, description,
amount, notes and attachments.

Deposit split: - parent uses hidden system Multiple entity; - children
may use different entities, budgets, descriptions, amounts, notes and
attachments.

### Editing

Uncleared active transactions are editable by Register User.

Cleared transactions remain editable unless protected by a Closed Fiscal
Year, but saving a change requires a blocking confirmation and full
audit logging.

Bank Account can never be changed after transaction creation.
Wrong-account entries must be voided and recreated.

Transaction Type may be changed through a deliberately protected flow
that requires confirmation and revalidation/reselection of incompatible
allocations.

### Void

No transaction is hard deleted.

Voiding: - requires a reason; - requires irreversible confirmation; -
leaves transaction permanently visible as VOID; - removes bank-balance
and budget-actual impact; - preserves allocations and existing
attachments; - prevents future financial edits; - permits later
supporting attachments and notes; - cannot be reversed.

A transaction referencing a Closed Fiscal Year cannot be voided.

A transaction may be created as a zero-dollar VOID record for physical
check accountability. It uses Budget 0 automatically and requires a void
reason.

## 8. Attachments

POC types: - PDF - JPG/JPEG - PNG

Maximum 5 MB per file. Multiple attachments are permitted and the viewer
supports navigation between them.

Fiscal Years support attachments. At least one Fiscal Year attachment is
required before closure.

## Benchmark v1.1 Workflow Clarifications

### Initialization Wizard
On first run of an uninitialized application, automatically present the wizard before normal login. Require Organization/Workspace Name, Administrator Username, Administrator Email Address, Password, and Password Confirmation. After completion, the initial Administrator can log in, appears in User List, and can access Administrator screens without authorization errors.

### Password Change
Every authenticated active user receives a self-service password-change action requiring current password, new password, and new-password confirmation.

2.2.0 (#343): the password requirements are listed beside the new-password fields before the first try (fields on the left half, requirements on the right half; stacked on a narrow screen) and are ticked off while typing: at least 12 characters (at most 128), a letter and a digit, not the same as the username, different from the current password, and new password = confirmation. An unmet item is red, a met one green with a check mark (theme tokens, readable in both modes); each item also says "met" / "not met" to screen readers, announced politely. The requirements and their numbers come from the server (`GET /api/auth/password-policy`); the server's password check stays the authority. A refused change keeps every field as typed. The same list is shown wherever a new password is chosen (the step after a temporary password — where "different from the temporary password" is checked on save —, Forgot password, the Initialization Wizard, and an Administrator creating a user or resetting a password). After a failed sign-in the password field is cleared and focused and the username kept; the other password-confirmation fields are unchanged.

### Appearance
Provide a Light/Dark mode control with persistent per-user preference. Core screens, dialogs, tables, forms, validation messages, and status indicators must remain usable in both modes.

### Draft Fiscal Years
Draft Fiscal Years appear in Fiscal Year list/detail, Budget Fiscal Year filters, Create Budget selection, eligible Register allocation Fiscal Year selection, and applicable dashboard/context displays. A newly created Draft Fiscal Year must immediately have a working detail route.

Selectors display identity plus optional status, e.g. `FY2027 — Draft`; `(DRAFT)` alone is invalid.


## Organization branding (2.2.0, #280)

System/About → **Branding**, Administrators only (read-only for financial users once #349 is in). Applies to generated reports and presentations only: every PDF report, the fundraiser stakeholder report (PDF, Word) and presentation, the Fiscal Year fundraising report and presentation. Not to checks (MICR stock, bank layout rules), cover letters, receipts or envelopes, which keep their own letter-editor logo and letterhead. The audit-log export keeps its plain layout.

- **Palette** following Material 3 color roles (primary, on-primary, primary container, secondary, surface, surface variant, outline and their "on" colors) plus eight chart series colors. Five ready-made palettes (PennyWarden — the default and the colors used before 2.2.0 —, Forest, Ocean, Plum, Ember) or **Custom**: the Administrator enters a primary and a secondary color, the browser generates the recommended palette (material-color-utilities: the source colors' tonal palettes, light scheme), and any role or series color can be changed. The server stores the resolved colors.
- **Guardrails** (server-side, mirrored live in the browser): every text role must reach WCAG AA 4.5:1 on the colors it is drawn on (on-primary/primary, on-primary-container/primary-container, on-secondary/secondary, on-secondary-container/secondary-container, on-surface/surface and surface variant, on-surface-variant/surface, primary and on-surface on white) — otherwise the save is refused naming the pair; series colors closer than ΔE 12 need the confirmation `SIMILAR_SERIES_COLORS`; charts never rely on color alone (BR-079). Live preview; **Reset to the PennyWarden palette** (logos and footer kept).
- **Logos**: a full logo (top right of a report's first page, in the margin; the title and closing slides, instead of the PennyWarden coin) and an optional small mark (left of every report page footer and every slide after the title; none without it). PNG or JPEG by content, at most 2 MB, 16–6000 px, re-encoded as PNG without metadata (BR-100/BR-101).
- **Footer text**: optional, one line, at most 120 characters, no variables; printed above the page footer and on every slide after the title.
- Where the colors go: headings and title bands (primary, text on-primary), tiles (primary container), table headers (surface variant), alternate rows (surface), lines (outline / outline variant), charts (series).
- Organization settings (BR-003): in backups, its own partial-restore section `settings.branding`, kept through a reinitialize. Audited: `BRANDING_UPDATED` (before/after colors and footer), `BRANDING_LOGO_SET` / `BRANDING_LOGO_REMOVED` (slot, fingerprint and size; never the image).
