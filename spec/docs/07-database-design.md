# 07 --- Relational Database Design

This document defines the proposed logical schema. Exact SQL types and
names may be refined during implementation, but changes must preserve
the documented domain and business rules.

## 1. Core Tables

### workspace

-   id PK
-   name
-   created_at

POC may initialize one workspace, but financial/business records should
be scoped by workspace where practical.

### user

-   id PK
-   workspace_id FK
-   username/email identifier
-   password_hash
-   active
-   created_at
-   updated_at

### role

-   id PK
-   code
-   name
-   security_domain

Seed roles: - ADMINISTRATOR - BUDGET_MANAGER - BUDGET_USER -
REGISTER_USER - AUDITOR

### user_role

-   user_id FK
-   role_id FK
-   composite uniqueness

Application validation prevents cross-domain role combinations.

## 2. Fiscal Years

### fiscal_year

-   id PK
-   workspace_id FK
-   identifier
-   display_name
-   start_date
-   end_date
-   status: DRAFT / APPROVED / CLOSED
-   approved_at
-   approved_by_user_id FK nullable
-   closed_at
-   closed_by_user_id FK nullable
-   created_at
-   created_by_user_id FK
-   updated_at
-   updated_by_user_id FK

Unique workspace + identifier/display name as appropriate.

Date-overlap/gap detection is a business-service validation because
intentional exceptions may be confirmed.

## 3. Budgets

### budget

-   id PK
-   workspace_id FK
-   fiscal_year_id FK
-   parent_budget_id FK nullable
-   parent_code / code components as implementation requires
-   child_code nullable/system value
-   name
-   type: INCOME / EXPENSE
-   amount decimal
-   status: DRAFT / APPROVED / REJECTED / INACTIVE as finalized by
    implementation
-   locked boolean
-   system_managed boolean
-   is_other boolean
-   is_budget_zero boolean
-   created_at/by
-   updated_at/by

Rules: - exact Budget PK is referenced by transaction allocation; -
parent roll-up is not selectable when explicit children exist; -
system-managed Other always exists conceptually; - Other is calculated,
never manually authored; - Budget 0 is protected; - rejected budget
amount is 0; - no hard deletion of historically material budgets.

Budget display identifiers are derived, not duplicated unnecessarily.

### branding_settings (2.2.0, #280; migration 0053)

-   id PK
-   workspace_id FK unique (one row per organization; no row = the PennyWarden palette, no logos)
-   preset (pennywarden, forest, ocean, plum, ember, custom)
-   source_primary, source_secondary nullable (custom: the colors the palette was generated from)
-   colors_json nullable (custom: the resolved role colors and eight series colors)
-   footer_text nullable (one line, at most 120)
-   logo_full_png / _sha256 / _width / _height nullable; logo_mark_png / _sha256 / _width / _height nullable (re-encoded PNG)
-   updated_at, updated_by_user_id nullable

### budget_history_entry (2.2.0, #284)

-   id PK
-   workspace_id FK
-   budget_id FK (the oldest budget of the line)
-   fiscal_year_label, year (the year found in the label)
-   budgeted_cents, actual_cents
-   note nullable
-   retired_at / retired_by_user_id / retire_reason nullable
-   created_at/by, updated_at/by

Rules: only years before the first Fiscal Year in PennyWarden; at most one active entry per line and year; never
deleted (retired with a reason); reporting only (not an allocation, never in actuals). Removed by Reinitialize with
the rest of the financial data.

## 4. Entities

### entity

-   id PK
-   workspace_id FK
-   entity_number unique within workspace
-   entity_type: INDIVIDUAL / ORGANIZATION
-   organization_name nullable
-   primary_contact nullable
-   address fields nullable
-   phone nullable
-   email nullable
-   notes nullable
-   is_financial_institution boolean
-   is_system boolean
-   active boolean
-   created_at/by
-   updated_at/by

Conditional validation: - Individual requires primary_contact. -
Organization requires organization_name.

Seed hidden system Multiple entity.

## 5. Bank Accounts

### bank_account

-   id PK
-   workspace_id FK
-   financial_institution_entity_id FK
-   account_name
-   account_type
-   account_subtype nullable
-   account_number_ciphertext
-   account_number_fingerprint
-   account_number_last4/display support
-   register_enabled boolean
-   primary_register boolean
-   interest_rate nullable
-   opening_balance decimal nullable
-   opening_balance_date nullable
-   account_opened_date nullable (2.2.0, #348; migration 0052)
-   manual_current_balance decimal nullable
-   active boolean
-   closed_date nullable
-   close_reason nullable
-   notes nullable
-   created_at/by
-   updated_at/by

Constraints/business validation: - account-number fingerprint unique
within workspace; - Financial Institution FK must reference entity
flagged as Financial Institution; - at most one Primary register-enabled
account per workspace; - account cannot be inactivated with uncleared
transactions; - account association on an existing transaction is
immutable.

## 6. Register Transactions

### register_transaction

-   id PK
-   workspace_id FK
-   bank_account_id FK
-   transaction_type: DEPOSIT / WITHDRAWAL
-   transaction_date
-   entry_timestamp
-   clear_date nullable
-   parent_entity_id FK nullable according to transaction rules
-   check_number nullable
-   status: ACTIVE / VOID
-   notes nullable
-   void_reason nullable
-   created_at/by
-   updated_at/by
-   voided_at/by nullable

Do not store an independently authoritative transaction amount if it can
be derived from allocations. If an implementation caches the total, it
must be treated as derived and transactionally synchronized.

Only ACTIVE transactions affect bank balance.

## 7. Transaction Allocations

### transaction_allocation

-   id PK
-   transaction_id FK
-   budget_id FK NOT NULL
-   entity_id FK nullable/required according to deposit/withdrawal rules
-   invoice_number nullable
-   description nullable
-   amount decimal
-   notes nullable
-   created_at/by
-   updated_at/by

Rules: - every transaction has at least one allocation; - normal
transaction has one allocation; - split transaction has multiple
allocations; - parent total = sum(allocation amounts); - allocation
Budget FK determines Budget Fiscal Year; - Deposit budgets must be
Income; - Withdrawal budgets must be Expense; - Withdrawal split child
entity is inherited from parent; - Deposit split children may use
separate entities; - Closed-FY allocations are immutable; - zero-dollar
created-as-VOID transaction may use protected Budget 0.

## 8. Attachments

Prefer a generalized attachment table plus ownership/association design
that preserves referential integrity.

### attachment

-   id PK
-   workspace_id FK
-   original_filename
-   storage_filename/path key
-   mime_type
-   size_bytes
-   uploaded_at
-   uploaded_by_user_id FK
-   active/retention fields only if required by immutable-history rules

### attachment_link

-   id PK
-   attachment_id FK
-   owner_type
-   owner_id

Allowed POC owner types include: - Fiscal Year - Register Transaction -
Transaction Allocation

If polymorphic owner links make referential integrity too weak, use
explicit join tables instead. Integrity is preferred over schema
cleverness.

## 9. Fiscal-Year Review

### fiscal_year_review

-   id PK
-   transaction_allocation_id FK
-   reason/category
-   status: PENDING / REVIEWED
-   review_note nullable
-   reviewed_at nullable
-   reviewed_by_user_id FK nullable
-   created_at

Use for allocations whose natural transaction-date Fiscal Year differs
from their selected Budget Fiscal Year or when no matching Fiscal Year
existed at entry time.

Intentional reviewed cross-FY allocations remain valid.

## 10. Audit Events

### audit_event

-   id PK
-   workspace_id FK
-   actor_user_id FK
-   action
-   object_type
-   object_id
-   timestamp
-   before_snapshot JSON nullable
-   after_snapshot JSON nullable
-   optional request/session correlation identifier
-   optional source metadata

Audit rows are append-only through application behavior.

Sensitive fields are sanitized/masked before snapshots are written.

Security events such as account-number reveal are recorded without
storing the revealed value.

## 11. Derived Balances

Register-enabled account current balance:

`opening_balance + active deposits - active withdrawals`

Fiscal-Year starting balance:

`account balance at end of day immediately before Fiscal Year start`

This is a derived display value, not a yearly opening transaction.

Non-register account current balance may be manually maintained and
every update is audited.

## 12. Derived Budget Values

Expense remaining:
`budget amount - applicable active withdrawal allocations`

Income remaining:
`budget amount - applicable active deposit allocations`

Negative remaining is permitted.

Parent roll-up actuals are derived from child allocations.

## 13. Transactional Integrity

The backend must use database transactions for compound operations
including: - transaction + allocations + audit event; - budget hierarchy
changes + Other recalculation + audit event; - Primary account
reassignment; - fiscal-year approval/locking; - fiscal-year closure; -
voiding; - role changes where multiple records are affected.

A failed audit write must roll back the corresponding auditable
mutation.

## 14. Indexing Guidance

At minimum consider indexes for: - workspace scoping; - fiscal_year
dates/status; - budget fiscal_year/type/status; - entity
number/name/status/financial-institution flag; - bank account
active/primary; - transaction bank_account/date/status/clear_date; -
allocation transaction/budget; - audit object/timestamp/actor; -
fiscal-year-review status.

Exact indexes should be verified against implemented queries.

## Benchmark v1.1 Data Model Clarifications

The user/preference model must support bootstrap Administrator email, persistent Light/Dark preference, and self-service password changes with session invalidation.

Bootstrap state must be reliably detectable; an empty SQLite file is not sufficient evidence of initialization.

General Fiscal Year queries and Draft-eligible selectors must not globally filter to `APPROVED`. Draft is operational; Closed is historical/read-only and excluded only where explicitly documented.
