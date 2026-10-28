# Financial Management Application — Domain Model

**Status:** Draft baseline for review  
**Purpose:** Define core domain objects, relationships, terminology, and ownership boundaries.

## 1. Aggregate Overview

```text
Workspace
├── Users
│   └── Roles
├── Fiscal Years
│   ├── Fiscal Year Attachments
│   └── Budgets
│       └── Parent / Child hierarchy
├── Entities
├── Bank Accounts
│   └── Register Transactions
│       ├── Transaction Allocations
│       │   └── Allocation Attachments
│       └── Transaction Attachments
└── Audit Events
```

## 2. Workspace

Represents the installation/organization boundary for financial data and security.

Key properties:

- `id` — primary key.
- `name`.
- creation metadata.

All financial and security records belong to a Workspace. The POC may initially operate as one Workspace per installation, but schema/business boundaries should not unnecessarily prevent future multi-workspace support.

## 3. User

Represents an authenticated application account.

Key properties:

- `id`.
- username and/or email login identifier.
- password hash.
- active/inactive status.
- high-level security domain.
- created/modified metadata.

A User belongs to exactly one high-level security domain:

- Administrator.
- Financial.
- Auditor.

Financial users may have multiple Financial roles. High-level domains never overlap on one account.

## 4. Role

POC roles:

- Administrator.
- Budget Manager.
- Budget User.
- Register User.
- Auditor.

Role enforcement is authoritative in the backend.

## 5. Fiscal Year

Represents the budget/accounting period against which Budgets are defined.

Key properties:

- `id`.
- user-entered identifier.
- computed/display name with `FY` prefix.
- `start_date`.
- `end_date`.
- status: `DRAFT`, `APPROVED`, `CLOSED`.
- approved by/at.
- closed by/at.
- created/modified metadata.

Relationships:

- has many Budgets.
- has many Fiscal Year Attachments.

Derived concepts:

- Q1 = first 3 months beginning Start Date.
- Q2 = months 4-6.
- Q3 = months 7-9.
- Q4 = months 10-12.

Fiscal Years normally form a consecutive, non-overlapping sequence. Exceptions are explicitly confirmed and audited.

## 6. Budget

Represents an Income or Expense budget for exactly one Fiscal Year.

Key properties:

- `id`.
- `fiscal_year_id` FK.
- `parent_budget_id` nullable/self-referencing FK.
- parent code.
- sub-budget code where applicable.
- name.
- type: `INCOME` or `EXPENSE`.
- amount.
- status.
- locked flag.
- system-managed flag.
- created/modified metadata.

Relationships:

- belongs to one Fiscal Year.
- optionally belongs to one parent Budget.
- may have child Budgets.
- referenced by Transaction Allocations.

### 6.1 Parent and Other

Every user-visible parent Budget has a system-managed `Other` child.

If `Other` is the only child, the UI treats the parent as the simple selectable budget while the backend retains a consistent leaf-allocation representation.

When explicit sub-budgets exist:

- parent is roll-up only.
- children are selectable.
- `Other` is selectable only when its amount is greater than zero.

`Other.amount = parent.amount - SUM(explicit child amounts)`.

### 6.2 Budget History Entry (2.2.0, #284)

A budget line's figures for a year **before the first Fiscal Year in PennyWarden**, entered by a Budget Manager from earlier records: Fiscal Year label (must include the year), budgeted amount, actual amount (may be negative), optional note. It is stored against the oldest budget of the line (the continuation links) and read for every budget of the line. It can be entered on any budget except Budget 0 and the system-managed `Other`; a parent without its own entry for a year shows the sum of its sub-budgets' entries (and, when both exist and differ, its own with a mismatch note). Labelled *Entered*; shown in the budget's History and the Budget Review (and so in the review appended to the Planning Sheet), not in dashboard charts. Reporting only: it never affects actuals, registers or Fiscal Year closure. Corrected or retired with a reason, never deleted; audited with before and after values. A year a Fiscal Year in PennyWarden covers is refused; an entry whose year a later-added Fiscal Year covers is kept but no longer counted.


## 7. Entity

Represents a person or organization participating in financial activity.

Key properties:

- `id`.
- immutable generated Entity Number.
- type: `INDIVIDUAL` or `ORGANIZATION` for user-visible records.
- organization name.
- primary contact/person name.
- address.
- phone.
- email.
- notes.
- Financial Institution flag.
- active/inactive status.
- protected/system flag for internal records.
- created/modified metadata.

Required naming rules:

- Individual: Primary Contact/Person Name required.
- Organization: Organization Name required.

Register display name:

- Individual -> Primary Contact/Person Name.
- Organization -> Organization Name.

### 7.1 Multiple Entity

A hidden protected Entity named `Multiple` is seeded at initialization. It cannot be selected, edited, inactivated, or displayed by normal users and is used only by system-defined split behavior.

## 8. Bank Account

Represents an account held at a Financial Institution.

Key properties:

- `id`.
- `financial_institution_entity_id` FK.
- account name.
- account type.
- account subtype.
- encrypted full account number.
- account-number fingerprint for uniqueness checks.
- account-number last four / masking metadata as needed.
- Register Enabled flag.
- Primary flag.
- optional interest rate.
- opening balance.
- opening balance date.
- optional Account opened date (2.2.0, #348): when the account was really opened; blank means it existed before PennyWarden (BR-044a).
- manually maintained current balance for applicable non-register accounts.
- active/inactive/closed status.
- closed date/reason where applicable.
- notes.
- created/modified metadata.

Relationships:

- Financial Institution must reference an Entity flagged Financial Institution.
- has many Register Transactions.

Full account number is unique within the Workspace using a non-reversible keyed fingerprint rather than ciphertext comparison.

## 9. Register Transaction

Represents one bank/cash event in a Bank Account Register.

Key properties:

- `id`.
- `bank_account_id` FK.
- type: `DEPOSIT` or `WITHDRAWAL`.
- transaction date.
- entry timestamp.
- clear/post date nullable.
- parent Entity/payee where applicable.
- check number for Withdrawals where applicable.
- notes/comments.
- status: `ACTIVE` or `VOID`.
- void reason nullable/required when VOID.
- created/modified metadata.

Relationships:

- belongs to exactly one Bank Account and can never be moved to another after creation.
- has one or more Transaction Allocations.
- may have attachments.

Derived amount:

`transaction_total = SUM(transaction_allocation.amount)`.

Only an ACTIVE parent transaction affects the Bank Account balance.

## 10. Transaction Allocation

Represents the budget/entity classification of part or all of a Register Transaction.

Key properties:

- `id`.
- `transaction_id` FK.
- `budget_id` FK, non-null.
- allocation-level Entity where permitted.
- invoice number where applicable.
- description.
- notes/comments.
- amount.
- Fiscal Year review status/metadata as required.
- created/modified metadata.

Relationships:

- belongs to one Register Transaction.
- belongs to exactly one Budget.
- Budget determines the allocation Fiscal Year.
- may have attachments.

A normal transaction has one Allocation. A split transaction has two or more.

## 11. Attachment

Represents supporting documentation stored outside the database.

Key properties:

- `id`.
- original filename.
- generated storage identifier/path.
- MIME type.
- file size.
- uploaded by/at.
- active/protected state as appropriate.

POC file types:

- PDF.
- JPG/JPEG.
- PNG.

Maximum size: 5 MB per file.

Attachments may be associated with Fiscal Years, Register Transactions, or Transaction Allocations according to workflow rules.

## 12. Audit Event

Append-only record of an auditable action.

Key properties:

- `id`.
- actor User ID.
- timestamp.
- action.
- object type.
- object ID.
- before snapshot JSON nullable.
- after snapshot JSON nullable.
- request/session correlation metadata where appropriate.

Sensitive values are masked/redacted before entering snapshots.

Audit records cannot be edited or deleted through the application.

## 13. Fiscal-Year Review Item

Logical domain concept used when an allocation requires later confirmation/reassignment because its Budget Fiscal Year differs from the natural Fiscal Year implied by Transaction Date, particularly when no covering Fiscal Year existed at entry time.

Implementation may use fields on Transaction Allocation or a dedicated table, but must support:

- Pending review.
- Reviewed/confirmed.
- Reassigned.
- optional note/reviewer metadata.

Unresolved review items block Fiscal Year closure where applicable.

## 14. Protected Budget 0

A protected system budget used only for narrowly defined exceptional non-budget activity, including approved account-initialization/verification scenarios and zero-dollar transactions created directly as VOID for accountability.

Budget 0:

- is system-managed.
- cannot be edited/deleted by users.
- should generate warnings when selected manually where manual selection is permitted.
- is visible to Auditors and relevant Financial users in reporting/review.

## 15. Key Relationship Summary

```text
FiscalYear 1 --- * Budget
Budget 1 --- * TransactionAllocation
BankAccount 1 --- * RegisterTransaction
RegisterTransaction 1 --- * TransactionAllocation
Entity 1 --- * BankAccount (as Financial Institution)
Entity 1 --- * RegisterTransaction / TransactionAllocation (as applicable)
FiscalYear / RegisterTransaction / TransactionAllocation --- * Attachment
User 1 --- * AuditEvent
```

## 16. Derived Values

Values that should be calculated rather than treated as independently authoritative include:

- `Other` budget amount.
- Parent budget roll-up activity.
- Budget actual activity.
- Budget remaining amount.
- Register Transaction total.
- Register-enabled Bank Account current balance.
- Fiscal Year starting balance display for a continuous Register.
- Register running balance.
- Fiscal quarter boundaries.

## Branding Settings (2.2.0, #280)

The organization's look for generated reports and presentations: a palette (a ready-made one or custom Material 3 role colors and eight chart series colors), a full logo and an optional small mark, and an optional one-line footer text. One per organization; an organization setting (BR-003), not financial data. See 05 §Organization branding.
