# Implementation notes

Authority order followed: business rules (03) → security (04) → acceptance criteria (08) → domain/workflow/
architecture/database (02, 05, 06, 07) → product requirements (01, 09). No specification file was modified.

**UI standards (2.0.0, #214):** every screen follows [ui-standards.md](ui-standards.md) — form rows that line up on
their labels, one control height, buttons and inline checkboxes centred on the input line, solid sticky action bars.
New screens use the shared `Field` component and CSS described there; the E2E test "#214" measures them.

## 1. Specification ambiguities and how they were resolved

None of the items below blocked implementation, but each required a choice the documents do not make. They are
listed so an evaluator (or the product owner) can confirm or overrule them. The first two involve two
requirements that pull against each other.

| # | Topic | Tension | Resolution chosen |
|---|---|---|---|
| A1 | **Administrator audit-log access vs. financial isolation** | docs/04 matrix and BR-003 grant Administrators the Audit Log, but BR-003/AC-SEC-003 forbid them financial content — and audit snapshots of budgets, transactions, etc. *are* financial content. | Administrators see every audit event's metadata (time, actor, action, object type/id, category) but `before/after` snapshots of financial object types are withheld (`snapshots_withheld: true`). Security/user events are shown in full. Auditors see everything. |
| A2 | **Zero `Other` hidden (BR-019) vs. history/roll-up (BR-026, AC-REG-011)** | If `Other` carried allocations and later becomes 0.00, hiding it would make parent roll-ups not reconcile with visible children. | A zero `Other` is always hidden from transaction selection and hidden from displays **unless it carries actual activity**, in which case it is shown (flagged `hidden_zero_other`) so totals reconcile. |
| A3 | Who resolves Fiscal Year review items | Not in the permission matrix. | Budget Manager (governance/closure owner) and Register User (transaction owner) may confirm; reassignment is a transaction edit (Register User). |
| A4 | Cross-FY allocation "may require review" (BR-059, AC-REG-004/006) | Unclear whether every confirmed cross-FY allocation creates a review item. | Every cross-FY or no-covering-FY allocation creates a `PENDING` review; it blocks closure of the budget FY and of the natural FY until confirmed or reassigned. Reviews on VOID transactions/removed allocations do not block. |
| A5 | Budget 0 | Must belong to a Fiscal Year (budget FK) and be usable by both Deposits and Withdrawals. | One protected Budget 0 per Fiscal Year (code `0`, stored type EXPENSE, exempt from the type rule). Automatic for zero-dollar VOID records; manual selection is offered in selectors but requires explicit `BUDGET_ZERO` confirmation. |
| A6 | Budgets added to an already Approved FY | Approval locks *existing* budgets; new ones are not addressed. | Created as `APPROVED` + unlocked (an amendment); the unlocked-budget closure blocker forces an explicit lock. |
| A7 | Lock/unlock granularity | `Other` is derived from parent and children; locking them independently would allow changing a locked `Other`. | Lock/unlock applies to a whole parent family (parent, explicit children, `Other`). |
| A8 | "Inactive" vs "Rejected" budgets | Both are listed statuses; only Rejected is defined (amount 0). | Inactivation behaves like rejection for amounts (allowed amount 0, requested amount retained, history preserved, no new allocations) but shows `–`/“Inactive” instead of `X`/“Rejected”. |
| A9 | Applicable uncleared transactions for closure | "applicable" undefined. | ACTIVE transactions with any live allocation to a budget of that Fiscal Year. |
| A10 | Quarterly activity for cross-FY allocations | A transaction dated outside the budget FY has no Q1–Q4 bucket. | Yearly actual includes it; an extra "Outside FY dates" column appears when non-zero (no silent re-bucketing). |
| A11 | Allocations removed while editing a split | BR-001/BR-026 forbid losing history. | Removed allocations are soft-removed (`removed_at`) and excluded from totals; pending reviews on them become `REASSIGNED`. |
| A12 | Closed-FY transactions | BR-057 freezes *financial* fields. | Append-only supporting notes and new attachments remain allowed (non-financial, audited); edits, voids and attachment removal are refused. |
| A13 | Opening balance changes | BR-093 forbids manually overriding a register balance to zero. | Opening balance/date and the Register-Enabled flag become immutable once any register transaction exists. |
| A14 | Auditor theme/password | Auditors "may not modify application data", but BR-SEC-SELF-001 and BR-UI-THEME-002 apply to *every* user. | Own password and own theme preference are treated as personal account settings, permitted for all domains. |
| A15 | Entity Number of the hidden `Multiple` entity | "Every Entity" receives a number. | `Multiple` is `ENT-000000`; user entities start at `ENT-000001`. |
| A16 | `Other` child code | Not specified. | Reserved child code `00`, so `Other` displays as `1000-00 Other`; users cannot create child `00` or parent `0`. |

## 1a. Change requests after the benchmark baseline

**CR-001 (requested by the product owner, v1.1.1): correct the Transaction Date of a VOID transaction.**
This deliberately relaxes BR-066/BR-069 and the docs/05 statement that voiding "prevents future financial edits"
for one field only. Rationale: a zero-dollar VOID accountability record created with the default (today's) date
could not otherwise be corrected. Scope and safeguards:

- Dedicated action `POST /api/transactions/{id}/void-date` (Register User, CSRF-protected); the request model accepts
  only `transaction_date`, optional `fiscal_year_id` (zero-dollar records, ambiguous overlap) and an optional `reason`.
- Applies to VOID transactions only; general PATCH editing of VOID transactions is still refused (AC-REG-017 unchanged).
  The record remains VOID; amounts, void reason, check number, allocations' figures and attachments are unchanged.
- Zero-dollar VOID records: Budget 0 allocation follows the Fiscal Year covering the new date (same rule as creation).
- Closed Fiscal Years remain immutable: a record in a Closed FY cannot be corrected and cannot be moved into one.
- Audited as `TRANSACTION_VOID_DATE_CORRECTED` with before/after snapshots and the reason.
- Tests: `backend/tests/test_cr001_void_date.py` (5 tests) and E2E "CR-001".

**2.1.0 — Budget Review (#283, Kyle 2026-10-20; built 2026-10-21 with layout A, the issue's recommendation).**
- Renamed from Budget Prep. `budget_review()`, `budget_review_csv()` and `budget_review_pdf()` are the new names;
  `budget_prep*` stay as aliases. The routes are `/api/reports/budget-review` and `/budget-review/projection-choices`,
  and the `/budget-prep` paths still answer, hidden from the schema. The audit name is `report: BUDGET_REVIEW` (older
  events keep `BUDGET_PREP`). Files are `budget-review-*.pdf/.csv`. The table `budget_projection_choice` is unchanged.
- The figures are unchanged from #257. Each row adds `average`: the mean budgeted and actual of the prior years shown
  that have a linked budget, with `compare()` for the difference (actual − budgeted, Kyle 2026-10-20) and `years`.
  The CSV adds Avg budgeted / actual / difference / years.
- **PDF, layout A:** a title band. For each budget, a heading row (spanning, shaded) and Budgeted / Actual /
  Difference rows. The columns are the prior years, Avg, the current year (YTD), and optionally Projected (Budgeted =
  the current budget, Actual = the projection) and Next year (its budget, and the change in the Difference row).
  Each block is `NOSPLIT`, and the columns split into bands when there are many years. The screen
  (`BudgetReview.tsx`, was `BudgetPrep.tsx`) shows the same layout.
- **Planning Sheet:** `include_review=true` makes `append_review()` build the review of the same year (3 years,
  projected with the person's choices, the Draft year's budgets when there is one) and append it with pypdf. Each
  part keeps its own page numbers. Recorded in the sheet's `REPORT_GENERATED` (`include_review`, `review_pages`,
  `review_years`).
- Tests: `backend/tests/test_v210_budget_review.py` (alias, averages, CSV, PDF layout, Planning Sheet with the review,
  access); `test_v210_budget_prep.py` (figures) is updated only for the name and layout; the E2E Budget Review steps.

**2.1.0 — voucher layouts (#246, decided by Kyle 2026-10-15/21; built 2026-10-21).**
- The 2.0.0 config model already allowed any `check_tops[0]` and one or two stubs anywhere that don't overlap
  (`StyleConfig._check_stubs`), and the renderer draws stubs at their own tops. What was missing was the presets and
  the UI.
- `presets.VOUCHER_LAYOUTS` holds the six layouts (check top, stubs as top, height and copy, and a stock note).
  `voucher_config()` builds the five new presets from `VOUCHER_TOP`, which itself is unchanged.
  `presets.voucher_layouts()` is served in `/api/checks/setup` for the setup screen's Check position and Stubs. With
  two stubs, VENDOR (invoice) is the stub next to the check.
- `render._draw_stub(outline=True)` dashes a stub's top edge when it isn't the sheet's top, and its bottom edge when the
  check starts there (a stub above the check). The real check never draws outlines, so 2.0.0 voucher prints are
  unchanged. `stub_drawing()` returns `top`, and the preview's viewBox extends upward for stubs above the check.
- UI labels: *Invoice stub* / *Office stub* (Kyle 2026-10-21). The printed copy label stays *OFFICE COPY*.
- Positions are the issue's starting presets, to be checked against real sheets (Kyle 2026-10-21). The 7-inch stub
  is 3.5–10.5 in with a 0.5 in strip.
- Tests: `backend/tests/test_v210_voucher_layouts.py` (presets, capacity, validation with the check anywhere, printing
  each new layout with positions on the check and record copy, calibration perforations, setup and access) and the
  E2E voucher steps.

**2.1.0 — fold marks on cover letters (#247, decided by Kyle 2026-10-15; built 2026-10-21).**
- `LetterConfig` gains `fold_marks` (NONE / FRONT / BACK, default NONE, so 2.0.0 templates are unchanged),
  `fold_length` and `fold_edge` (0.1–0.5 in; defaults 0.15 and 0.25), `fold_weight` (HAIRLINE 0.25 pt / THIN 0.5 /
  MEDIUM 0.9) and `fold_shade` (LIGHT / MEDIUM / DARK gray). These live in the template's JSON config, so no migration
  is needed. The WINDOW preset starts with FRONT, and the editor sets FRONT when a *new* draft chooses a window layout.
- `documents.fold_ticks()` draws four ticks at `FOLD_LINES`. `letter_pdf(fold=...)` draws them in `onFirstPage` for
  FRONT. For BACK, `_with_back_pages()` uses pypdf to put a ticks page after page 1 and a blank page after each other
  page. The output is deterministic (reportlab `invariant`), so a reprint's record copy is still de-duplicated by
  SHA-256. The test print and preview pass through `sample_letter_pdf`, so they show the ticks as well as the
  labeled window marks.
- **Levels:**
  - letter: `LetterIn.fold_marks`;
  - user: `check_printer_setting.fold_marks` on a row with `feed_key "letter"` and no style or template (migration
    `0044`; empty = TEMPLATE; GET/PUT `/api/checks/my-printer/letter`, audited `CHECK_PRINTER_SETTINGS`);
  - template.

  `letter_fold_default()` resolves user, then template. The print-screen documents list returns `fold_default` per
  letter and `my_letter_fold`. `CHECK_LETTER_PRINTED` records the `fold_marks` used.
- Tests: `backend/tests/test_v210_fold_marks.py` (8 tests: tick positions from the content stream, address page,
  back pages, tuning and limits, test print, user and letter levels, audit, access) and the E2E letter steps.

**2.1.0 — organization profile (#314, Kyle 2026-10-22; part (a) of #318).**
- `entity.is_organization` and `entity.ein` (migration `0046`). One Organization entity per workspace, created by
  `bootstrap.initialize` and, for existing workspaces, by the migration (named like the workspace, numbered from
  `next_entity_number`). The migration moves the EIN and address lines saved in Donations Setup (#312) onto it
  (a last line "City, ST 12345[-6789]" is split) and removes them from `donation_settings.config_json`;
  `ReceiptConfig` drops the two old keys if a backup still has them.
- `services/organization.py`: `get`, `ensure`, `values()` (`ORG.*` plus the older `ORG`, `ORG_NAME`, `ORG_ADDRESS`,
  `ORG_EIN`), `SAMPLE` (test prints), `profile_out`, `update` (fields left out keep their value; EIN `^\d{2}-\d{7}$`;
  phone through `entities.clean_phone`). `GET /api/system/organization` (`system.view`), `PUT` (`system.manage`; the
  2.0.0 `{name}` body still works). `rename_organization` keeps the entity's name in step. Audit
  `ORGANIZATION_UPDATED` on the workspace (so the Administrator sees it; it is not transaction content, BR-003).
- Entities: `PATCH`/inactivate/restore of the organization entity → 409 `ORGANIZATION_ENTITY`; `is_organization`
  is not writable (BR-098). Reinitialize keeps it.
- Patterns: dotted names (`_NAME` allows one `.`), `ORG.*` in every context, `ORG.ADDRESS` only where line breaks are
  allowed. Check printing adds the real `ORG.*` values in `variable_values`; the `SAMPLE_VALUES` carry the sample
  organization. Donations read the EIN and address from the profile (`missing_setup(db, ws_id)`) and refuse a line
  whose donor is the organization entity.
- UI: `OrganizationPanel` (System/About → General), the Entities badge, Donations Setup shows the profile read-only
  with a link; the variable picker completes dotted names.
- Tests: `backend/tests/test_v210_organization.py` (6, including the data migration) and the E2E #126 and #312 steps.

**2.4.0 build 5 — Product catalog (#252, decided 2026-10-16).**
- Tables (migration `0073`): `invoice_unit_type`, `invoice_product_category`, `invoice_product` (name, code, description,
  unit price, unit type, category, taxable, `budget_id`, `is_system`, active), `invoice_tax_rate` (name,
  `rate_milli_pct` = thousandths of a percent, `budget_id`, active). All four are in Reinitialize `WIPE` (before
  `Budget`) and selective-restore `DATA_TABLES`; after a Reinitialize with the module on the seed comes back.
- Seed when the module is turned on (once): unit types Each, Hour, Day, Week, Month, Year and the built-in
  **Discount** product (`is_system`, no price or budget, can't be edited or inactivated).
- Permissions: `invoice.catalog_manage` (IM), `invoice.catalog_view` (IM, BM, BU, Auditor) - per the issue's matrix
  the Register User has no catalog access; Administrator none (BR-003). Module off -> 404 `MODULE_DISABLED`.
- Budget picker `GET /api/invoices/catalog/budget-options`: per open Fiscal Year, the Register's selectable deposit
  leaves on Invoiced Income families, `{id, label}` only (no amounts/actuals). Saving checks the budget server-side
  (Income, Invoiced Income, not Budget 0, not rejected/inactive/deleted, open year, a selectable leaf).
- Retire, never delete: `POST .../{id}/inactivate|restore`; no DELETE routes. Every change audited
  (`INVOICE_PRODUCT_*`, `INVOICE_TAX_RATE_*`, `INVOICE_UNIT_TYPE_*`, `INVOICE_CATEGORY_*`) with before/after. Names
  are unique per kind (case-insensitive, inactive included); product codes unique when given.
- Continuation (#89): `budget_for_year(budget, fy)` follows `continues_budget_id` (a simple budget is chosen by its
  Other leaf, so its parent's chain is followed and that year's simple leaf used); `needs_budget` = no Invoiced Income
  continuation in the **current** Fiscal Year (the open year covering today, else the latest open one). The issue
  marks the payment-time behaviour (Register User picks a budget with a warning) as proposed; it lands with Payments.
- UI: *Product catalog* card on the Invoices page (tabs Products / Tax rates / Unit types / Categories, Show inactive,
  New/Edit/Inactivate/Restore for IM).
- New rules (spec docs unchanged): **BR-INV-CAT-001** catalog maintained by IM, viewed by BM/BU/Auditor, never the
  Administrator; **-002** retired, never deleted, audited; **-003** product and tax-rate budgets are Invoiced Income
  only, picked without amounts; **-004** a product's budget follows the continuation link, else *needs budget*. ACs
  **AC-INV-CAT-001..006** (seed; maintain + audit; picker/validation/mass assignment; roles; continuation; object
  scope).
- Tests: `backend/tests/test_v240_invoice_catalog.py` (6).

**2.4.0 build 4 — Invoices module switch and the Invoice Manager role (#251, decided 2026-10-16).**
- `workspace.invoices_enabled` and the role `INVOICE_MANAGER` (Financial; migration `0072`; seeded for new installs
  from `ROLE_DEFS`; a new local install's first user gets it too). `services/invoices.py`: switch (audited
  `MODULE_ENABLED`/`MODULE_DISABLED`, SECURITY), `require_module` (404 `MODULE_DISABLED`), overview and setup
  placeholders; `routers/invoices.py`: `GET /api/invoices/overview` (`invoice.view`), `GET /api/invoices/setup`
  (`invoice.setup`, Administrator; no real invoices or products, BR-003). Module status lists it.
- Permissions: `invoice.manage` (IM), `invoice.view` (IM, RU, BM, BU, Auditor), `invoice.setup` (Administrator);
  `entity.manage` adds IM (not `entity.create_financial_institution` / `_manage_financial_institution`);
  `system.about` adds IM.
- **`register.view`** (new) = the financial viewers + IM: used by the Register list, a transaction, the bank-account
  list/detail (selector), the entity list/detail, the Fiscal Year list and `natural` (the Register's year filter) and
  the budget filter options. Everything else stays `financial.view` (Fiscal Year detail, budgets, balance history,
  reports, dashboard - the dashboard now refuses a Financial user without `financial.view`). Attachments: list/get/
  content use `register.view`, but a register-only role sees transaction and line documents only (403 otherwise).
- UI: Users role checkbox; Invoices nav after Donations/Payments/Register; Invoices Setup in the Administrator's menu
  when the module is on; an IM-only user's menu is Register, Entities, Invoices (+ System/About) and `/` opens
  Invoices. Security overview item *Whole invoice cycle in one account* (info, never attention).
- New rules (spec docs unchanged; docs/04 changes are listed in the issue): **BR-INV-MOD-001** optional module,
  hidden and refused when off; **-002** Invoice Manager is a Financial role combinable only with Financial roles;
  **-003** separation of duties (BM budgets / IM billing / RU receiving / Auditor review), the whole cycle in one
  account is shown, not blocked; **-004** IM sees the Register read-only and maintains normal entities only. ACs
  **AC-INV-MOD-001..006** (switch + refusal; role combinations; IM access matrix incl. negative API tests;
  attachment scope; security overview; setup page).
- Tests: `backend/tests/test_v240_invoices_module.py` (5).

**2.4.0 build 3 — Invoiced Income budgets (#250, decided 2026-10-16).**
- `budget.invoiced_income` (migration `0071`, off). Set on an Income **parent** with
  `PUT /api/budgets/{id}/invoiced-income` (`budget.manage`); stored on the whole family like `locked` (sub-budgets and
  Other), and a sub-budget or Other created later takes the parent's value (BR-016). Expense budgets, sub-budgets,
  Other, Budget 0, rejected/inactive/deleted budgets and a closed Fiscal Year are refused. Not writable through budget
  create/edit (`extra="forbid"`).
- Locked (Approved) budget: refused with `BUDGET_LOCKED` until the existing audited unlock with a reason
  (BR-023/024) - that is how "set or cleared only through unlock with a reason" is met.
- Audit: `BUDGET_INVOICED_INCOME_SET` / `_CLEARED` with before/after and the family's budget ids.
- Shown: budget lists (Budgets page and Fiscal Year detail, 🧾 + text, BR-079), budget API rows/snapshot, and the
  Audit / Close report budget table ("(Invoiced income)"). Copy forward (BR-027) carries it.
- Not built yet (they need invoices): every rule that applies "when the Invoices module is on" (invoice-only deposits,
  refund exception, product/tax pickers) - with the Payments/Invoices builds. The issue's *proposed* items (refuse
  setting while non-invoice deposits exist / clearing while invoice-linked allocations exist; continuation offers the
  flag) are left for Kyle to confirm; they can only be enforced once invoices exist.
- New rules (spec docs unchanged): **BR-INV-INC-001** Invoiced Income is a flag on an Income parent budget, carried
  by its family, Budget Manager only; **-002** changes on an Approved budget need an unlock with a reason and are
  audited; **-003** copy carries it; without the Invoices module it has no effect (BR-050 unchanged). ACs
  **AC-INV-INC-001..005** (set/clear + inheritance + audit; refused for expense/child/Other/roles/mass assignment;
  unlock first; copy; no register effect).
- Tests: `backend/tests/test_v240_invoiced_income.py` (5).

**2.4.0 build 2 — Events & Fundraisers (#429, decided with Kyle 2026-10-30).**
- UI-only rename: nav **Events**; *Events & Fundraisers* on the module setting (with examples), the list page heading
  and back links; "Series" for the series link. Internal names unchanged: tables `fundraiser*`, `/api/fundraisers*`,
  audit object type `fundraiser`, code identifiers.
- `fundraiser.event_type` (`FUNDRAISER` | `EVENT`, migration `0070`, server default Fundraiser for every existing row).
  Writable only through `FundraiserIn` (create/edit, `fundraiser.manage`); omitted on edit = unchanged; other bodies
  refuse it (`extra="forbid"`).
- Required budgets (`REQUIRED_KINDS`): Fundraiser = Income + Expense, Event = Expense, per Fiscal Year used; a shell
  (no budgets) is always allowed. **Checked when the record is created and whenever its budgets or type change**
  (422 `REQUIRED_BUDGETS` with the gaps) — Claude's reading of "existing records are kept as-is with a warning": an
  upgraded record missing one can still be renamed/edited otherwise, shows `REQUIRED_BUDGET_MISSING`, and *Mark
  results final* is refused (409) until fixed or retyped.
- Type change: audited in `FUNDRAISER_UPDATED` (before/after `event_type`); goal and bucket `is_donation` kept. An
  Event's detail returns no goal (`totals.goal = null`), the Quarterly/Annual report shows no goal for it, its donation
  buckets don't suggest receipts (`donation_bucket_allocations`, `fundraiser_unreceipted`), and the UI hides the goal
  field, the bucket donation flag and the *Donations without a receipt* panel.
- A series holds one type (`series_type()` = its events' type): *Continues from* (`set_link`, options filtered by
  `event_type`), *Add to a series* and *Merge* refuse a mismatch (409 `SERIES_TYPE`); changing the type of an event in
  a series with other events is refused until it is unlinked. *Create next year's* copies the type.
- Combined budgets: `detail.combined_budgets` gives one budgeted Income and Expense figure (sum over Fiscal Years) and
  the labels; actual figures were already combined.
- Reports: stakeholder report/deck say "event" for an Event (no goal there before either); FY fundraising report/deck:
  `fy_report()` keeps the fundraising figures, history, shares and series history for Fundraisers only and returns
  `events` (+ `events_net`), shown as *Events (not fundraisers)* in the PDF and an *events* slide.
- Demo/test data: *Fall Mattress Sale* (demo) and *Summer Car Wash* (test data) gained an Expense budget.
- Tests: `backend/tests/test_v240_events.py` (9). Earlier fundraiser test modules that use one-budget setups to test
  other rules run with the rule relaxed (conftest `_BEFORE_REQUIRED_BUDGETS`); every other module runs with it on.
  E2E: Harvest Dinner is created as an Event (type, no goal field, *Create event*); the goal is tested on the Spring
  Fair shell.
- New rules (spec docs unchanged): **BR-EVT-001** each event is a Fundraiser or an Event (default Fundraiser);
  **-002** required budgets by type per Fiscal Year once budgets are chosen, shells allowed, final blocked while
  missing; **-003** a type change is audited and keeps goal/receipt data; **-004** a series holds one type; **-005**
  Events are reported apart from fundraising totals. ACs **AC-EVT-001..010** as in the issue's checklist (rename and
  internal names; series type; type change audit; Event hides goal/receipts; shells; Event/Fundraiser required budgets;
  final blocked; upgraded record warning; combined figures; FY report separate section; mass assignment and roles).

**2.4.0 build 1 — Attachment deduplication (#425, decided with Kyle 2026-10-30).**
- Kyle: identical content is stored once and linked; existing duplicates are merged at the upgrade (after the
  pre-upgrade backup, each file's hash verified first); the rule covers every attachment, PennyWarden's generated PDFs
  included; the *Attachment added* audit event notes the link; the same file twice on one record warns with
  **Cancel / Attach anyway**, a match on another record links silently.
- Storage (Claude's call, one of the two shapes in the issue): `attachment.storage_key` is no longer unique (migration
  `0069`, plus an index on `workspace_id, sha256`); every attachment record keeps its own row and owner, and records
  with identical content point at one stored file. Chosen over a separate `attachment_file` table because backup,
  selective restore, Reinitialize, reports and downloads already work per stored file / per row and need no change;
  shared files are countable with `GROUP BY storage_key` (Diagnostics does). No new table, so nothing to add to
  Reinitialize `WIPE` / selective-restore `DATA_TABLES`.
- `services/attachments.new_record()` is the one place an attachment is created (uploads, Close report, check record
  copies, receipt/statement/envelope copies): after the caller's validation it looks for a stored file of the
  workspace with the same SHA-256 and size, compares the bytes, and links it; otherwise it writes a new file. It
  returns the path only of a newly written file, so a failed save removes only that file - a linked file is never
  removed. Removed attachments' files count as matches (they are kept for history).
- Same-record check (server-side, after validation): an **active** attachment of the same owner with the same SHA-256
  -> 409 `DUPLICATE_ON_RECORD`; `POST /api/attachments?...&attach_anyway=true` adds it. The client
  (`useAttachmentUpload` in components.tsx: attachment lists and the transaction form's files) shows *Same file
  already attached* with Cancel / Attach anyway. A removed copy does not count.
- Upload responses are unchanged: the other record is never shown (BR-099); the link is only in the audit event
  (`shares_file_with_attachment_id`).
- Merge of existing duplicates: `merge_duplicate_files()` runs at start-up after the migrations and after a web
  restore (a backup from an earlier version). With nothing to merge it is one query. Per group (workspace + SHA-256)
  the oldest verified file is kept; a file that is missing, fails its recorded hash or differs byte-wise is left as it
  is, logged and counted; the extra copies are deleted only after the commit. One `ATTACHMENT_FILES_MERGED` audit
  event per workspace (counts only).
- Reports: unchanged - each attachment row verifies its file, so a damaged shared file is reported on every record
  linked to it. Diagnostics/health check: `attachment_records`, `attachment_shared_files`, `attachment_bytes_saved`
  (counts only), shown under *Shared files* on System/About when any file is shared.
- New rules (spec docs unchanged): **BR-ATT-DEDUP-001** identical attachment content is stored once per workspace and
  linked; **-002** the same file twice on one record needs the user's confirmation (server-side); **-003** a stored
  file is never deleted or overwritten while any attachment record (active, removed or on a VOID transaction)
  references it; **-004** the upgrade merges existing duplicates after verifying each file's hash. ACs:
  **AC-ATT-DEDUP-001** cross-record link (no warning, other record not revealed); **-002/-003** same-record warning,
  Cancel and Attach anyway, UI and direct API; **-004** removing one link leaves the others; **-005** upgrade/start-up
  merge (damaged file left and reported, idempotent); **-006** generated copies follow the rule; **-007** audit link
  note and atomic rollback that keeps a shared file; **-008** diagnostics counts. Unchanged and re-tested: BR-073/074,
  BR-100/101, AC-ATT-001..004, AC-SEC-014..017, AC-AUD-001/003.
- Tests: `backend/tests/test_v240_attachment_dedup.py` (15) and the E2E step "#425" (in the #259 reorder step). The
  test helper `env.fy_doc` now uploads a PDF with content of its own.

**2.3.0 build 15 — Budget History: years included in another budget (#414, decided with Kyle 2026-10-30).**
- Kyle: any budget of the same type at any level; years before **and** in PennyWarden; shown only on the marked
  budget; not counted in Avg; #415's automatic *history on parent* stays where nothing is marked.
- Storage (Claude's call): table `budget_inclusion` (migration `0068`) on the earliest budget of the marked budget's
  line (as the #381 link holder) and looked up across `budget_history.line_budgets`, so no budget from before
  PennyWarden is created for an event that never had an old-spreadsheet line. A PennyWarden year stores
  `fiscal_year_id` + `included_budget_id` (a budget of that year); a year before PennyWarden stores the label/year +
  `included_former_budget_id`. Service `services/budget_inclusions.py`.
- Validation (BR-078/097/098): same type; not Budget 0 or deleted; the year is before the marked budget's Fiscal
  Year; a PennyWarden year has no budget of the line and the included budget is of that year and not of the line; a
  year before PennyWarden goes through the same label rules as entered years and has no entered figure on the line;
  the included budget from before PennyWarden is not the line's own; one active mark per line and year (409);
  explicit fields only; note ≤ 500.
- Figures always win: a mark for a year that later gets figures is not shown (the History says so).
- Budget Review: the cell stays empty (so Avg already leaves it out) and `history_notes[i]` carries
  "included in …", ahead of #415's "history on parent"; also on the not-in-year rows of PennyWarden lines (#382).
  The PDF prints "…, now 1000-00 Other" for the arrow (the PDF font has no → glyph); screen and CSV keep the arrow.
- Never deleted (BR-001): retired with a reason. Audit `BUDGET_HISTORY_INCLUSION_MARKED` / `_RETIRED` on the line's
  holder budget (AC-AUD-001–005). Budget Managers mark (`budget.manage`); every financial role and Auditors see the
  marks in the History (`financial.view`), BR-003. Reporting only (BR-048).
- Reinitialize (#125) wipes the marks before budgets, budgets from before PennyWarden and Fiscal Years; selective
  restore (#319) restores them with the data (`partial_restore.DATA_TABLES`).
- Tests: `backend/tests/test_v230_history_included.py` (5) and the E2E step "#414".

**2.3.0 build 14 — Push builds skip the repeated test suite (#420, Kyle 2026-10-30).**
- `build.yml`: the `tests` job runs only on `workflow_dispatch`; `package`, `windows-exe`, `macos-app`, `assemble`,
  `publish` and `site` use `!failure() && !cancelled()` (a skipped job otherwise skips everything that depends on it,
  directly or not). A failed hand-run test job still stops packaging. The packaging smoke tests are unchanged.
- Safe because the ruleset (develop, test, main) requires a pull request with the `tests / test` and
  `promotion-rules` checks **and** branches up to date before merging (strict, set by Kyle in the repository
  settings). The develop build's `notices: regenerate` only ever affected its own test run, never the package, so
  nothing is lost there.
- No spec impact (CI only).

**2.3.0 build 13 — Users: filters and sortable columns (#409, Kyle 2026-10-29).**
- Client-side on the already-loaded list (`pages/Users.tsx`): Roles (multi-select, OR), Security domain, Status
  (`ACTIVE` / `DISABLED` / `LOCKED` = active with `locked_until` in the future), combined with the search (AND).
  Sortable headings as in the register (`aria-sort`, a button per heading); default Last name ascending; empty values
  last either way; ties by last name, first name, username. Not remembered between visits. No API or data change.
- Test: E2E "#134" extended (roles OR, domain, status, clear, sort and reverse).

**2.3.0 build 12 — Report settings: configurable report grouping (#376).**
- New business rule (recorded here; spec docs aren't changed in the repo): **report grouping is workspace
  configuration; every report belongs to exactly one category of the active scheme; grouping is display-only and
  never grants access.** Administrators only (`system.manage`), audited `REPORT_GROUPING_UPDATED` / `_RESET`.
- Table `report_grouping` (`0067`): the active scheme and, per customized scheme, its categories (`id`, `name`,
  optional `short`, `reports` in order) as JSON; no row / no customization = `services/report_grouping.DEFAULTS`
  (Purpose = the #375 groups). A report added in a later release that a saved grouping doesn't know goes to an
  "Other" category (never lost). Empty categories are allowed (System has no report yet) and hidden in the catalog.
- Validation: 1–20 categories, names 1–60 characters and unique (case-insensitive), ids generated from the name when
  new, every report exactly once. Removing a category with reports asks where they go (another category or a new
  "Other") in the screen; the server only accepts a complete grouping.
- `GET /api/reports/grouping` (any signed-in user) feeds the catalog and side list; `GET/PUT
  /api/system/report-settings`, `POST …/reset` for the Administrator. In backups; part of the *General* partial-restore
  section; kept through a reinitialize (organization setting).
- Tests: `backend/tests/test_v230_report_grouping.py` (defaults, scheme switch, customize, validation, reset, audit,
  Administrators only, display-only); E2E "#376".

**2.3.0 build 11 — Reports screen redesign (#375; layout chosen by Kyle 2026-10-29 from the mockups).**
- Layout: the catalog of mockup (a) as the home (`/reports`), and each report on its own page (`/reports/<id>`) with
  the compact grouped side list of (c) plus the search box of (b). The candidates stay on the design canvas.
- One registry (`frontend/src/pages/reports/registry.ts`: id, name, short name, purpose, audience, group, outputs,
  visibility) drives the catalog, the side list, search, deep links and Recently run; the components are mapped in
  `Reports.tsx` (`BODIES`). Groups are by purpose (#376 will make grouping configurable). The registry ids are also
  the server's (`services/report_prefs.REPORT_IDS`).
- Navigation enforcement (04-security §3 per the issue): a report the user can't run (permission or module) is not
  listed, and `/reports/<id>` for it shows *not authorized*; the report endpoints keep their own permission checks.
- Every report page has the same header (name, purpose, audience, group, output badges) and one action row
  (`ReportActions`: Open · Download PDF · Download PPTX · Download CSV). Reports with a run/review step (Entity
  activity, Financial Flow, Budget Review) keep it; their result's own links are unchanged.
- Moved into Reports: the Fiscal Year fundraising report (FY + the fundraisers to include), the Planning Sheet and the
  cash count sheet (FY + fundraiser). The old buttons are shortcuts: they navigate to the report with the options in
  the address (`?fiscal_year_id=…&ids=…`, `?fundraiser_id=…`), which come before remembered options.
- Remembered per user, server-side (`app_user.report_prefs`, `0066`; `GET /api/me/report-preferences`,
  `POST /api/me/report-runs`): the last 5 runs (report, options, a short label, time; a repeated run moves up) and
  each report's last options. Options only - never output; free text (commentary, notes) and per-run choices that
  would surprise later (Budget Review's optional columns, Financial Flow's balance options, as-of dates) are not
  remembered. A run is recorded when a report is opened/downloaded or run on screen. *Recently run* opens the report
  page with its options filled in (one click there; the file itself then needs **Open**, since a browser won't open
  a new tab without a click on the page).
- Restore re-entry reports stay at the bottom of the catalog, shown only when there are any.
- Tests: `backend/tests/test_v230_report_prefs.py`; E2E "#375" (catalog per role, search, deep link and Back, side
  list, remembered options, Recently run, a refused address); report E2E steps now open reports through the catalog.

**2.3.0 build 10 — Dual branding: light and dark themes per output type (#386, decided with Kyle 2026-10-28/29).**
- `branding_settings` (`0065`): `dark_preset` (a ready-made id, `custom`, or empty = the dark version of the light
  preset; PennyWarden's when the light palette is custom and no dark colors were saved), `dark_colors_json`,
  `theme_reports` / `theme_presentations` (LIGHT | DARK), `dark_logos` and `logo_dark_full_*` / `logo_dark_mark_*`.
  The light source colors are shared by both themes.
- **Upgrade vs new setup** (Kyle 2026-10-29: existing branding stays light): the migration adds a row with both
  outputs LIGHT for every existing workspace, so an upgraded installation that never touched branding stays light
  too. A new installation has no row until branding is saved, and no row (or a row created after 2.3.0, model
  default) means presentations DARK, reports LIGHT. Flagged for Kyle: this treats "existing branding" as "existing
  installation".
- `DARK_PRESETS`: the dark version of each ready-made palette, generated with material-color-utilities 0.4.0 (dark
  scheme from the preset's two source colors; series tones 80/70/80/60/90/60/70/45 so bars show on a dark surface);
  `palette.ts generate(..., dark)` makes the same for custom colors. Dark contrast pairs = the light pairs without the
  white-paper ones, plus primary on surface.
- **Direct editing (decision 4)** is a UI change: every role and series is editable on both theme tabs and an edit
  switches that palette to *Custom* (the server already accepted custom colors). The API keeps the old body shape;
  the dark fields, `themes` and `dark_logos` are optional (omitted = unchanged).
- **Applying a theme:** `branding.load/use(db, output=...)` with `output` "reports" (default, every `@themed` PDF
  builder), "presentations" (the three decks) or "word" (the stakeholder Word report: always light — Word is printed
  on white paper). `Theme.dark` / `Theme.page`. Decks: `paint_background` (called from `brand_footers`, which every
  deck calls last) fills each slide with the surface; table bodies use the page color; chart and data-label text the
  theme's text color on dark (donut labels sit on light slices: dark text). PDFs: `_Styles` gives every non-themed
  style the on-surface text color on dark; `_stamp_and_write` merges a surface-colored page under each page; the few
  fixed light-design lines/shades go through `branding.pick(light_hex, dark_role)` so light reports are unchanged.
  Semantic colors (red warnings, green *above budget*) keep their meaning on both.
- Dark logos: on a dark theme with *Use a separate logo on dark backgrounds* on, each slot uses its dark version
  when uploaded, else the light one. Uploads follow BR-100/BR-101 (`normalize_logo`).
- Backups / partial restore (`settings.branding`) / reinitialize: the new columns live on `branding_settings`, so
  they follow the existing handling unchanged.
- Tests: `backend/tests/test_v230_dual_branding.py` (5, including the migration); `test_v220_branding` updated for
  the new logo slots and to request light presentations where it checks the light palette; E2E "#386".

**2.3.0 build 9 — Quarterly / Annual Fiscal Year financial report and presentation (#373, issue decisions of
2026-10-28/29).** Spec docs are not changed in the repo, so the issue's new rules are recorded here:
- **BR-110 Period Report Cutoff:** cutoff = the end of the period, or the run date while the period is under way
  (*Preliminary — as of <date>* in the title band, the PDF footer and on the deck's first slide); an Annual report
  for a Fiscal Year that isn't Closed is Preliminary too (as of its end date once it has ended). A period that hasn't
  started → 422. "Today" is `routers.reports._today()`, called per request (tests patch it).
- **BR-111 Quarterly Isolation:** a quarterly report has one *Quarter* column plus year-to-date figures; earlier
  quarters are never shown on their own. Annual: Q1–Q4 + the year.
- **BR-112 Fundraiser Period Attribution:** by event end date (one quarter); only lines dated ≤ cutoff count
  (`fundraisers._lines` filtered, `_money_totals` → gross = counted income, net = income − expenses, seed cash
  (classified cash float) netted out and shown separately); *activity after <date> not included*; *Revised* = a
  fundraiser that ended in an earlier quarter of the same year with counted lines dated in the selected quarter
  (its quarter change and updated cumulative figures). Fundraisers ending after the cutoff are not listed yet.
- Choices where the issue left room: **cash flow** = money in (deposits) and money out (withdrawals) of register
  accounts by Transaction Date, Budget 0 (transfers) left out. **Account balances** by Transaction Date
  (`available_cents`; BR-043/BR-047), non-register accounts from their balance history, $0 before *Account opened*,
  "—" before any data; closed accounts listed while they were open in the period. **Budgets:** the FY's budgets with
  their sub-budgets (the parent rolls up every sub-budget, a hidden Other included, AC-REG-011); Draft budgets show
  while the year isn't approved, Rejected/Inactive only with activity, Budget 0 as a note. Over / under = budgeted −
  actual (negative = over, BR-022), with the #371 gross note under each table. **Prior year** = the Fiscal Year
  starting before this one; budgets matched by type + Budget ID (display code); columns left out without one.
  *Budgets over budget* on the highlights counts parent budgets with negative over/under year to date.
- Acceptance mapping (issue AC-RPT-001…010) → `backend/tests/test_v230_period_report.py`:
  001/002/003/005/006 `test_periods_cutoff_preliminary_and_future_blocked`; 004 the same test's account figures;
  007 `test_fundraiser_attribution_revised_and_cutoff`; 008 `test_prior_year_comparison`; 009/010
  `test_pdf_pptx_audit_and_permissions` (commentary on page 1 and in the notes; the deck's monthly bars with the net
  line). E2E "#373" covers the selection screen and both downloads.
- Code: `services/period_report.py` (the data), `services/period_report_output.py` (PDF with the shared report
  toolkit; deck with the `fundraiser_deck` helpers — python-pptx has no combo chart, so the net line is added as a
  `c:lineChart` sharing the bar chart's axes), routes `GET /api/reports/period/options` and `GET /api/reports/period`
  (`format=pdf|pptx|json`; audited `REPORT_GENERATED` with report `FY_PERIOD_REPORT`/`FY_PERIOD_PRESENTATION`).
  Out of scope per the issue: signature block, CSV.

**2.3.0 build 8 — One setup layout with a locked preview (#394, decided with Kyle 2026-10-29).**
- `SetupLayout` (checkShared.tsx) with one CSS rule set (`.setup-layout`) replaces the Donations-only `.setup-grid`;
  `usePin`/`PinToggle` replace the per-page *Keep at the top* code. Used by Donations Setup, the check style editor and
  `EditorFrame` (cover letter and envelope editors, so the Envelopes page and Donations Setup's envelope editor too).
- Settings come first in the DOM; on narrow screens the preview column is `display: contents` with `order: -1`, so the
  preview shows at the top and the existing `.collapsible.pinned` sticky works against the whole layout. The pinned
  rules now apply below 1200px only.
- Wide (≥ 1200px, the breakpoint Donations Setup already used): the preview column is `position: sticky; top: 0`.
  Of the issue's two options, the simpler one was taken: the column is capped at the scrolling pane's height
  (`--pane-h`, measured with a ResizeObserver on `.content`, less padding and the sticky Save bar) and letter
  pictures are scaled to fit it, so the preview never scrolls away; anything taller scrolls inside the column. A true
  two-way sticky can follow if the cap feels cramped.
- The preview's own controls stay with it (check: Sample / Long text sample; Donations Setup: Receipt / Year-end
  statement). Test print stays in each page's Save bar.
- Test: E2E "#394" (wide: beside and in view after scrolling; narrow: at the top, Keep at the top keeps it in view).

**2.3.0 build 7 — Shared signers (#395, decided with Kyle 2026-10-29).**
- The table `check_signer` is kept (not renamed: checks, print snapshots and audit events refer to it) and gets
  `areas` (comma list of CHECKS, COVER_LETTERS, DONATIONS), like the envelope library's `features`. New service
  `services/signers.py` and router `/api/signers` (Administrators: `checks.setup` or `donation.setup`, at least one of
  the modules on). The old `/api/checks/signers` routes stay for compatibility; Payments Setup now links to the
  Signers page. Choosing a signer validates the area tag (`require_tagged`); `usage()` lists where a signer is in use,
  which blocks retiring it or dropping that tag (409 `SIGNER_IN_USE`). Tag changes are audited `SIGNER_AREAS_CHANGED`.
- Signature modes `NONE | PRINTED | IMAGE | SPACE` (`signers.block_for`/`flowables`). The image needs the key, so
  `km` (the app key) is passed explicitly to every letter/receipt/statement render. The record copy (attachment kept
  with the payment or donation) is always rendered with `with_image=False`, so IMAGE becomes PRINTED there; the
  printed/downloaded copy carries the image. IMAGE without an uploaded image falls back to SPACE
  (`SIGNER_NO_IMAGE` warning on Donations Setup).
- `ReceiptConfig`: `signer_name`/`signer_title` removed (old saved keys are dropped on read); `signer_id`,
  `signature_mode`, `statement_signer_id` and `statement_signature_mode` (None = the receipt's). `LetterConfig`:
  `signer_source` (`SAME_AS_CHECK` default | `FIXED`), `signer_id`, `signature_mode` (default `PRINTED`, which is
  the 2.2 behaviour).
- Migration `0064` converts the typed names so nothing prints differently (see upgrade.md).
- Tests: `backend/tests/test_v230_shared_signers.py` (7, including the data migration); E2E steps in the #158/#159,
  #165-#166 and #312 tests now add signers on the Signers page.

**2.3.0 build 6 — Include EIN on receipts (#393, decided with Kyle 2026-10-29).**
- No donation BR series in 03-business-rules; recorded here and in the user guide. `ReceiptConfig.include_ein`
  (default true; old saved configs read as true). `missing_setup` asks for the EIN only while it is on.
  Off: `values_for`/`statement_values` blank `{ORG.EIN}`/`{ORG_EIN}` (`hide_ein`), the acknowledgment block has no
  EIN row, and a blank EIN is not reported as an empty variable at print. `setup_out.warnings`: `EIN_MISSING` (on,
  none entered) and `EIN_PLACEHOLDER_OFF` (off, the letter or statement text still uses it).
- One-off EIN through `{DETAILS}` (off): saving details that use it (register receipt dialog, Donations page create
  and update) needs `confirm_ein_override` + a non-blank `ein_override_reason` (409 `EIN_OVERRIDE_REQUIRED`
  otherwise; 409 `EIN_NOT_ENTERED` without an EIN); the reason is kept on `donation.ein_override_reason` (`0063`) and
  in `DONATION_DETAILS_UPDATED`. Printing adds the `EIN_OVERRIDE` warning, so the backend refuses without that
  confirmation (BR-078); the EIN then prints only inside the details (`ReceiptData.ein_override`), and
  `DONATION_RECEIPT_PRINTED` records `ein_override` and the reason. Details saved before the option was turned off
  (no reason) are refused at print (`EIN_OVERRIDE_REASON_MISSING`) until saved again with one. Statements have no
  details, so no override.
- UI: Donations Setup checkbox + warnings; `useEinOverride` (Donations.tsx) asks for the confirmation and reason when
  the save is refused with `EIN_OVERRIDE_REQUIRED` and saves again.
- Tests: `backend/tests/test_v230_include_ein.py` (7).

**2.3.0 build 5 — Estimated entered years: fundraisers and budgets (#390, decided with Kyle 2026-10-29).**
- `estimated` (bool, default off) on `fundraiser_series_result` and `budget_history_entry` (`0062`). Server rule
  (BR-094): estimated ⇒ a non-blank note (`fundraiser_series.estimate_note_check`, `budget_history._estimate_check`,
  also after a Correct that clears the note). Request models take `estimated` explicitly (BR-097/098).
- Fundraiser series: `POST /api/fundraiser-series/{sid}/results/{rid}/correct` (amounts, note, Estimated; reason
  required; `FUNDRAISER_RESULT_CORRECTED` before/after incl. the flag; the year itself isn't changed — retire and
  enter again). `series_history` rows carry `estimated`/`estimate_notes`; `fy_report` carries `estimated` on history
  rows, trend years and per-series yoy values, and adds "* Estimated: <year> <series> — <note>" lines to its
  footnotes (`fundraiser_fy_report.est_lines` puts them under the trend, yoy and history tables and in the slides).
- Outputs: the year gets `*` (tables, chart categories, speaker notes); the PPTX charts colour an estimated point
  lighter (`fundraiser_deck._lighter`), the Budget Review PDF chart too (`ch.bars[(s, i)]`). Not hatched: python-pptx
  and reportlab bar charts have no pattern fill per point; lighter was the decision's alternative.
- Budgets: `figures` carries `estimated` (a parent's sum of sub-budgets is estimated when any part is, with their
  notes); review cells get `estimated`/`estimate_note`; `estimate_footnotes(rep)` under the PDF tables (and the
  one-budget chart); CSV status column "Entered; estimated: <note>"; the History, Before PennyWarden and the review
  screen show `*`. CSV import: optional `estimated` column (yes/y/true/1/x, no/n/false/0/empty; anything else or yes
  without a note → refused row); the template has the column.
- Tests: `backend/tests/test_v230_estimated_years.py` (5); `test_v220_budget_history` template header updated; E2E
  "#292" extended (Correct as estimated).

**2.3.0 build 4 — Budget Review: budgets not in the chosen Fiscal Year (#382, decided with Kyle 2026-10-29).**
- `budget_planning._add_not_in_year` (full review only; a `budget_id`/`parent_budget_id` filter skips it). Covered =
  the chosen year's rows and every budget in their history cells; covered former budgets = each row's `former_of`
  (+ a parent's `_sub_formers`). Candidates: budgets of the PennyWarden years shown (not deleted, not Budget 0, not
  Other) not covered — a sub-budget only when its parent is covered (a discontinued parent's figures already include
  its subs, no rows for them). Each is taken to the latest budget of its line before the chosen year
  (`_continued_by` chain) — one row per line, under that budget's code and name. Former budgets not covered: one
  continued by a PennyWarden budget joins that budget's line; one nothing continues gets its own row (its own years,
  most recent code and name, `entered_as` for years called differently).
- Rows: `id` "b<budget id>" / "f<former id>", `level` parent, `current`/`projection`/`next`/`state`/`status` None,
  `not_in_year` {fiscal_year, last_year}, `average` over the years with figures. Inserted by natural code order before
  the first parent row with a higher code (existing order untouched; equal codes go after).
- Entered-year columns: `budget_history.year_labels(all_formers=True)` for the full review, so a former budget
  nothing continues adds its years (2.2.0 left them out). Three 2.2.0 tests that asserted the old columns were updated.
- PDF charts are drawn only for a one-budget review, which can't choose a line that isn't in the chosen year — so the
  decision "include them in the charts, marked" has nothing to apply to yet (reported to Kyle).
- Tests: `backend/tests/test_v230_review_not_in_year.py` (6); E2E "#382".

**2.3.0 build 3 — Balance history: Correct and Retire, backfill, closed years (#391, decided with Kyle 2026-10-29).**
- Clarifies the 1.7.3 append-only rule: entries are never deleted; they are corrected or retired with a reason.
  `bank_account_balance` gains `corrected_at/by`, `correct_reason`, `previous_balance_cents/as_of_date` (the values
  the last correction replaced; earlier corrections are in the audit log) and `retired_at/by`, `retire_reason`
  (`0061`). Every reader of the history skips retired entries (`manual_as_of`, `balance_on`'s first entry,
  `_recompute` for the current balance). `GET …/balance-history` keeps its list shape: counted entries newest first
  (change computed over counted entries only), then retired ones (`retired` set); `entered` = dated before the first
  Fiscal Year; `corrected` = the last correction.
- Date rules (`_check_date`, used by add, Correct — on the old and the new date — and Retire): never in the future;
  before the first Fiscal Year allowed even before the opening balance date (that rule stays inside PennyWarden
  years); a Closed Fiscal Year refuses Budget Managers (`FISCAL_YEAR_CLOSED`) and lets a Budget Admin
  (`bank_account.closed_year`) through with a reason and the `CLOSED_FISCAL_YEAR` confirmation naming the year.
  Such a change writes `fiscal_year_balance_change` (per closed year touched; ADD/CORRECT/RETIRE, before/after) and
  the audit event `BANK_ACCOUNT_BALANCE_CHANGED_AFTER_CLOSE` (Security, `closed_fiscal_years`) instead of the usual
  event. `GET /api/fiscal-years/{id}` returns `balance_changes_after_close`; the audit/close report lists them under
  the Fiscal Year Review's closure readiness (*Balance changed after close*).
- Retiring the account's only counted entry is refused (`LAST_BALANCE_ENTRY`): the current balance would have nothing
  to come from (correct it instead). Corrections/retirements need an active account, as balance updates do.
- Tests: `backend/tests/test_v230_balance_correct_retire.py` (5); E2E "#88" extended (Correct, Retire).

**2.3.0 build 2 — Update channel in the Settings editor (#379, decided with Kyle 2026-10-28).**
- `admin_settings`: `update_channel` joins `EDITABLE` (choices `auto`/`stable`/`test`/`off`, plain-language
  `choice_labels`); `LOCAL_EDITABLE = ("update_channel",)` — on a local install it is the only editable key (any
  other key → 409 `SERVER_ONLY`; the view's `editor` is true when something is editable). `LIVE = ("update_channel",)`:
  never `restart_required`; after the save the router calls `apply_live`, which replaces `app.state.settings` with a
  `dataclasses.replace` copy (Settings is frozen). `updates.check` reads `app.state.settings` each tick (every 30 s) and
  fetches again whenever the channel differs from the last check's, so the new channel is used within about a minute.
- Confirmation `PRE_RELEASE_CHANNEL` when the build is a production build (`build_info.branch == "main"`) and the new
  value is `test` (BR-107: the default stays `auto`). Locked by `FM_UPDATE_CHANNEL`/command line as every setting.
- Same-version rule: `updates.current` now gives the test-build number for every build made from `test`, whatever
  the channel (still none for `main`), and `is_newer` on the stable channel reports the production release of the
  running version to a test build. On the test channel nothing changes (a test build follows newer test builds).
  The 1.10.0 unit assertion "a test build on stable doesn't see its own version" was turned around on purpose.
- Tests: `backend/tests/test_v230_update_channel.py` (13); `test_v200_admin_settings` local-mode test updated (the
  #126 criterion's one exception); E2E: the System/About settings step checks the channel row (locked by the E2E
  server's `FM_UPDATE_CHANNEL`).

**2.3.0 build 1 — Gross budgets (#371) and an optional fundraiser goal (#372), Kyle 2026-10-28/29.**
- #371 (proposed BR-109, *Budgets Are Gross*; spec docs unchanged per this file's rule): budgets stay gross — an
  offset recorded in a budget of the opposite type is never netted (netting isn't tractable in general; fundraiser
  seed-cash netting is unchanged). One sentence, `GROSS_BUDGET_NOTE` in `services/common.py` and
  `frontend/src/components.tsx`, kept identical by a test. UI: `GrossBudgetNote` under the budget tables (Budgets,
  Fiscal Year detail, Budget Review), *Gross amount* label/header (`BudgetTable`, budget forms), `InfoTip` (ⓘ popup)
  on the Dashboard budget tiles and the expense-vs-budget chart. PDFs: `reports.gross_note()` directly beneath each
  budget table of the audit/close report, each Budget Review table and its per-budget chart, and each Planning Sheet
  table. The fundraiser stakeholder report, deck and Fiscal Year fundraising report list no budget amounts, so they
  carry no note. The income/expense pies show actuals, not budget amounts, so they have no ⓘ.
- #372: `fundraiser.goal_amount_cents` (`0060`, nullable, ≥ 0). `FundraiserIn.goal_amount` (optional; an edit that
  doesn't send it keeps the goal; null clears it). The goal is compared with the **net** (Kyle, 2026-10-29):
  `totals.goal` = goal, net, difference (net − goal), `pct_of_goal` (one decimal; none for a goal of 0), `met`.
  Snapshot (and so the audit before/after) includes `goal_amount`. Editing stays Budget Manager only. The
  Quarterly/Annual report (#373) will reuse `fundraisers.goal_vs_actual`.
- Tests: `backend/tests/test_v230_gross_budgets_goal.py` (5); E2E "#371" plus steps in "CR-020" (chart ⓘ) and
  "CR-033" (goal).

**2.2.0 — Budgets from before PennyWarden (#381, decided with Kyle 2026-10-28; reshapes #284).**
- Problem: #284 attached entered years to a PennyWarden budget's line and its CSV matched rows on the chosen Fiscal
  Year's codes, so a budget with no PennyWarden year had nowhere to go, and a reused code put old figures on the wrong
  budget without a warning.
- Model: `former_budget` (code, name, type, note, retired) owns the entries (`budget_history_entry.former_budget_id`,
  with `code`/`name` of that year when they differ; `budget_id` only on pre-#381 entries, kept, not read). A budget
  reaches them only through `budget.continues_former_budget_id`, on the earliest budget of its line (`link_holder`);
  Other's line is the Other of each budget of its parent's line, so it carries its own link only when its parent
  starts the line. Migration `0059` converts each #284 line into one former budget linked from the line's oldest
  budget (a deleted one: unlinked).
- Rules (`services/budget_history.set_link`): one predecessor per budget (choosing a former budget clears
  `continues_budget_id` and the other way round, `budgets._set_links`); any level, same type; Other may continue a
  former budget, Budget 0 never; a former budget is continued by at most one non-deleted budget; deleting a budget
  frees its former budget; allowed in any Fiscal Year state and on locked budgets (reporting only — the link is not
  a budget edit). Former budgets are retired, never deleted; retiring unlinks. A type change only while unlinked.
- Reports: `figures()` reads the line's former budget, and for a parent the former budgets of its sub-budget lines
  and its Other's line; `year_labels()` counts only former budgets a budget continues, so an unlinked one adds no
  empty column. Review cells carry `entered_as` (that year's code and name when they differ from the row). Rows for
  budgets not in the chosen year are #382.
- CSV: columns `budget code, type, former code, former name, year, budgeted, actual, note, line` (required: year,
  budgeted, actual, and budget code or former code). Rows group by `line`, else budget code, else former code + type.
  A group goes to its target line's former budget, else an existing former budget with the same code and name
  (current or default; several = refused), else a new one; refusals per group (budget codes or types mixed, type
  mismatch, former budget continued elsewhere, link holder continuing another, two groups creating or linking the
  same). Template rows with only code/name/type are skipped; template cells are formula-neutralised.
- Choices Kyle may want to check: the importer doesn't rename an existing former budget (the years carry their own
  names and the most recent is shown); a new former budget created by *Add an earlier year* takes the earliest
  budget's code and name; the CSV needs a type column for budgets nothing continues (not in the decision list, but
  required to create one).
- API: `GET/POST /api/budgets/former`, `GET/PATCH /api/budgets/former/{id}`, `POST .../retire`, `POST .../entries`,
  `GET .../budget-options?fiscal_year_id=`, `GET /api/budgets/former/link-options?budget_id=`,
  `PUT /api/budgets/{id}/former-link`. Reads `financial.view`, changes `budget.manage`. Audit:
  `FORMER_BUDGET_CREATED/UPDATED/RETIRED`, `BUDGET_FORMER_LINKED/UNLINKED`, `BUDGET_HISTORY_*` now on
  `former_budget`.
- UI: `pages/FormerBudgets.tsx` (list, detail, link form, year form, History link line); Budgets *Before
  PennyWarden…*; the Continues select has a *Before PennyWarden* group; History on Other rows for Budget Managers.
- Tests: `backend/tests/test_v220_former_budgets.py` (17, including the migration) and the updated
  `test_v220_budget_history.py`; E2E "#381".

**2.2.0 — System/About read-only for financial users and Auditors (#349, decided 2026-10-24).**
- Permission `system.about` (Administrator, Auditor, Budget Manager, Budget User, Register User; Budget/Register
  Admins hold it through their base role). `GET /api/system/organization` moved from `system.view` to it. New
  `GET /api/system/modules/status`: every module (`MODULES` in `routers/fundraisers.py`) with `enabled`, `used_by`
  (role names from `PERMISSIONS`, plus "Administrators (setup)") and `you` (the viewer holds a use or setup
  permission). `GET /api/system/about` returns `backup_notice: null` without `system.view`.
- UI: the menu adds System/About for financial users (and COMBINED users with `system.about`). `About.tsx`: General is
  open to `system.about`; non-Administrators get `OrganizationView` (AdminSettings) and `ModulesStatus` instead of
  the editors; `UpdateSettings readOnly` shows On/Off, last check, result and *What's new* (also added for
  Administrators), no switch or Check now. The Data protection note is shown only when the server sends it.
- Choice: the issue named Budget Manager and Register User (Invoice Manager does not exist yet); Budget Users are a
  financial role too, so they get it as well. Auditors also see the update-check status read-only.
- Tests: `backend/tests/test_v220_about_readonly.py` (3); E2E "#216" (Auditor tabs) and "2.2.0 (#349)".

**2.2.0 — Fundraiser series: Add to an existing series, years newest first and sortable (#302, #351, Kyle 2026-10-24).**
- Migration `0058`: `app_user.fundraiser_series_sort` ("asc"; None = newest first, the default stored as no
  preference, like `register_sort`). `PUT /api/me/preferences {fundraiser_series_sort: "asc"|"desc"}`; `/auth/me`
  returns it ("desc" when unset).
- `fundraiser_series.series_list(db, ctx, direction=None)` adds `rows` per series: recorded fundraisers
  (`kind: "recorded"`) and entered results (`kind: "entered"`) in one list, by year in `direction` (default: the
  user's choice). Within a year the order is fixed either way: recorded by start date newest first, then active
  entered results, then retired ones. `fundraisers`/`results` stay as before (oldest first) for existing callers.
  `GET /api/fundraiser-series?direction=asc|desc` overrides; every mutation returns the list in the user's order.
- `add_to_series(db, ctx, f, series_id)` (`PUT /api/fundraisers/{id}/series {series_id}`, `fundraiser.manage`): only a
  fundraiser in no series (else 409 `ALREADY_IN_SERIES` - merge instead); refused with 409 `YEAR_ENTERED` when the
  series has an active entered result for the fundraiser's year. `continues_from_id` stays empty. Audited
  `FUNDRAISER_SERIES_LINK_UPDATED`. `GET /api/fundraisers/{id}/series-add-options` lists every series with
  `allowed`/`reason`.
- UI: *Start a series…* offers *Start a new series* / *Add to an existing series*; the fundraiser page has
  *Add to a series…* while it is in none (`AddChoice` is shared). The series page has a hint for events held more
  than once a year; the Year heading flips every table (aria-sort) and shows *Sorted by year, oldest first* with
  *Reset to default*.
- Not changed: year over year in the stakeholder report, presentation and Fiscal Year report stays oldest first.
- Choice: a fundraiser added by mistake is moved with *Change…* (Continues from) or by merging series; there is no
  separate "remove from series" (same as a started series, #292).
- Tests: `backend/tests/test_v220_fundraiser_series.py` (5) and the E2E "2.2.0 (#302, #351)" step.

**2.2.0 — Entities: names, display name, mailing address, EIN, entity variables (#315, #316, #317; #318).**
- Migration `0057`: `entity.display_name_custom`, `entity.mailing_*` (empty = "same as", resolved at read time),
  `first_name`/`last_name` (from `primary_contact`, trimmed and split at the first space; `name_review` set for every
  split name), `primary_contact` dropped; `app_user.name_order` (None = FIRST_LAST). Downgrade recombines the names.
- Model: `Entity.legal_name` (Individual "First Last", Organization its name) - printed on checks (PAYEE), letters,
  envelopes, receipts, statements; `display_name` = custom or legal name - everywhere else; `primary_contact` is a
  read-only property ("First Last"); `mailing(field)` / `mailing_same`. `checkprint.address_lines(e, mailing=True)`
  is the mailing address; `{ORG.ADDRESS}` therefore follows the organization's mailing address.
- API: `EntityFields` first/last name, `display_name_custom`, `mailing_*`, `ein` (organizations only, validated like
  the profile's); the legacy `primary_contact` input is split. Duplicates (BR-030) match the name or any existing
  display name; search covers first, last, full and display names. `GET /api/entities/names-to-review`,
  `POST /api/entities/{id}/confirm-name` (`entity.review_names`: Budget Manager); a PATCH that sends the names clears
  `name_review`. `PreferencesIn.name_order`; `/api/auth/me` `name_order`. The organization profile takes `mailing_*`.
- Variables (`services/entity_vars`): `{PAYEE.*}` (CHECK, LETTER, ENVELOPE, STUB; ADDRESS/MAILING_ADDRESS only where
  line breaks are allowed) and `{DONOR.*}` (RECEIPT, STATEMENT); donation envelopes give the donor as PAYEE.*.
  Addressee blocks: `LetterConfig.addressee` and `ReceiptConfig.addressee` (≤ 6 lines; default name + mailing
  address, so existing templates print as before), resolved by `entity_vars.addressee`.
- Frontend: `names.ts` (`entityName`, `entitySortKey`, set from `/api/auth/me`) - the Entities list and
  `EntityPicker` follow the name order; the register keeps the display name. The variable picker groups dotted
  names by role.
- Tests: `test_v220_entities.py` (incl. the migration split); E2E "#315 / #316".

**2.2.0 — Year-end giving statements, donor report, fundraiser donation buckets (#256, Kyle 2026-10-24).**
- Migration `0056`: `donation_statement` (donor, calendar year, seq/number S-YYYY-NNNN, kind ORIGINAL | DUPLICATE |
  CORRECTED with `replaces_id`, totals, `line_ids`, `content_sha`, `attachment_id`), `attachment.donation_statement_id`
  (the kept copy and its envelope), `fundraiser_bucket.is_donation`. In `reinitialize.WIPE` and the partial-restore
  data tables.
- `services/donation_statements`: `received_lines(ws, start, end, donor)` — lines of ACTIVE donations that are
  received (`donations.line_received`) with `line_date` in the years; `summary`, `detail`, `preview`, `print_one`,
  `print_all` (one combined PDF via pypdf; one `PRINT_ALL` confirmation plus aggregated NO_DONOR_ADDRESS /
  CORRECTED_STATEMENT / EMPTY_VARIABLES), `document`, `print_envelope`, `report` (≤ 5 years), `report_csv` (BOM;
  formula-leading text quoted), `report_pdf` (landscape, `branding.use` + the reports module's grid and branded
  footer). The statement letter shares the receipt's layout through `donations.donor_letter_pdf` (refactored out of
  `receipt_pdf`), `ack_table`, `items_note_text`.
- Patterns: context `STATEMENT` (the receipt's donor/organization/signer variables plus `YEAR`, `TOTAL`,
  `STATEMENT_NO`, `DONATION_TABLE`); `ReceiptConfig.statement_title|salutation|body|closing`. `{DONATION_TABLE}`
  resolves to a marker; its paragraph becomes the table (appended after the text when absent).
- Routes (`/api/donations`): `GET statements`, `GET statements/{year}/donors/{id}`, `POST .../preview`, `POST ...`
  (print), `POST statements/{year}/print-all`, `GET statements/printed/{id}/document`,
  `POST statements/printed/{id}/envelope|envelope-test`, `GET report?format=json|pdf|csv&detail=`,
  `POST setup/statement-preview|statement-preview-image|statement-test-print`,
  `GET fundraisers/{id}/unreceipted`. View: `donation.view`; print: `donation.print`; setup: `donation.setup`.
- Fundraiser link: `donations.donation_bucket_allocations` → `transaction_out` lines carry `suggested` and
  `fundraiser`; the dialog pre-ticks them (saved only on Save). `fundraiser_unreceipted` lists ACTIVE deposits in
  donation buckets whose line is unmarked or whose donation has no receipt. `FundraiserBucketIn.is_donation`
  (None = unchanged; allowed in a closed year: it only drives a suggestion).
- Tests: `test_v220_year_end.py`; E2E "#256".

**2.2.0 — Donations part 2: before the deposit, items, the Donations page (#325, Kyle 2026-10-23).**
- Model (migration `0054`): `donation` (donor, origin PAGE | DEPOSIT with the deposit for DEPOSIT, status ACTIVE |
  CANCELLED with reason, `details` — was `donation_detail`); `donation_line.donation_id`, `kind` MONEY | ITEM,
  `amount_cents` (unlinked money; an item's estimate), `description`, `item_received`, `item_no_value` + reason;
  `allocation_id` nullable (empty = awaiting deposit). `donation_receipt.donation_id`, `transaction_id` and
  `date_received` nullable; `attachment.donation_id` (receipts of a donation not linked to a deposit). The migration
  groups part 1 lines by (deposit, donor) into DEPOSIT donations, moves details and receipts onto them.
- `services/donations`: `line_received` (money linked to a live allocation of an ACTIVE deposit; items ticked),
  `line_amount` (linked money follows the allocation), `line_date`, `line_locked` (received in a Closed Fiscal Year),
  `_content`/`_content_sha` per donation (items added to the hash only when present, so part 1 receipts keep their
  fingerprint), `_compose` (confirmation `NOT_RECEIVED` when the date prints blank), `print_donation` (a copy on every
  linked deposit, else with the donation). The part 1 API (`/transactions/{id}/...`) now works on DEPOSIT donations;
  lines linked to a PAGE donation show read-only (409 LINKED_TO_DONATION on unmarking).
- Page API: `GET/POST /api/donations`, `GET/PUT /api/donations/{id}`, `POST .../cancel`, `.../receipts/preview`,
  `.../receipts`, `GET /api/donations/awaiting-lines`, `POST /api/donations/create-transaction` (the register's
  `create` with `links[i]` = the donation line of allocation i; a line on several allocations is split into one line
  per allocation adding up to its amount; the donor is the allocation entity; receipts copied onto the deposit).
- Register hooks: `void`, `delete` and allocations removed on edit call `donations.unlink_for_deposit` — PAGE lines are
  unlinked (amount kept), DEPOSIT donations keep their lines and their receipts show void.
- Audit and Close reports: `non_cash_received()` → "Non-cash donations received" after the budgets (whole-year
  reports only).
- Shared envelope library (migration `0055`): `check_document.features` and `default_for` (comma-separated PAYMENTS,
  DONATIONS); every existing template is tagged PAYMENTS and `default_for` follows `is_default`. For envelopes,
  `is_default` is kept equal to "the Payments default" (`services/envelopes._set`) so Payments' code reads it as before.
  `services/envelopes`: `set_tag` (409 `DEFAULT_NEEDED` with `candidates` when removing a feature from its default
  while other tagged active templates remain), `set_default`, `duplicate_for` (the copy takes the tag and default),
  `tag_new` (created on a feature's page: that feature, its default if it had none; global page: none),
  `require_feature` (the feature's setup permission and module). Cover letters stay Payments' (tagged PAYMENTS).
- Routes: `/api/checks/documents*` (template CRUD, drafts, previews, test prints) use `doc_ctx` — `checks.setup` with
  Payments on, or `donation.setup` with Donations on; letters still need Payments (`_kind_ok`). Creating takes
  `feature` (PAYMENTS default, DONATIONS, or null = Not used); flags take `feature` for *Make default*.
  `GET /api/envelopes`, `POST /api/envelopes/{id}/tags|default|duplicate-for`. Payments' print list and print routes
  use only PAYMENTS-tagged envelopes (404 otherwise).
- Receipt envelopes: `GET /api/donations/envelopes` (DONATIONS-tagged, default first, `receipt_window`),
  `POST /api/donations/{id}/envelope|envelope-test`, `PUT /api/donations/my-printer/envelope` (the same per-template
  `check_printer_setting` row as Payments). The donor's name and address; envelope variables `{ORG*}`, `{PAYEE}` (the
  donor), `{PAYEE_ADDRESS}`, `{TODAY}`. The copy (`document_type` DONATION_ENVELOPE, drawn without feed offsets) is
  kept with the donation and on every active linked deposit; Create transaction copies receipts and envelopes.
- Receipt window options: `ReceiptConfig.window` (NONE | LETTER | ADDRESS_PAGE), `window_return`, `fold_marks`
  (NONE | FRONT | BACK; the template's setting — no per-print or per-user override, unlike cover letters), drawn with
  the cover letter's `window_blocks`, `fold_ticks` and `_with_back_pages`. The setup preview draws the window outlines.
- Tests: `test_v220_donations_part2.py`, `test_v220_envelopes.py`.

**2.1.0 — Donations module, part 1: receipt letters (#312, Kyle 2026-10-22; part of #256).**
- Module switch `workspace.donations_enabled` (migration `0045`, off), the same pattern as Fundraisers and Payments:
  `services/donations.module_enabled/require_module/set_module` (audit `MODULE_ENABLED`/`MODULE_DISABLED`,
  entity "donations"), `ModulesIn.donations`, `/api/auth/me` `modules.donations`, diagnostics.
- Permissions: `donation.setup` (Administrator), `donation.print` (Register User), `donation.view` (Budget Manager,
  Budget User, Register User, Auditor). Every `/api/donations` route also needs the module (404 MODULE_DISABLED).
- Setup: `donation_settings.config_json` validated by `ReceiptConfig` (the EIN and address
  moved to the organization profile in #314; font, size, date format, title/salutation/body/closing as `RECEIPT` patterns, signer name and title). Audit
  `DONATION_SETUP_UPDATED` with before/after. Preview, preview-image (PNG via `raster`) and test print use sample data
  only (`DONATION_RECEIPT_TEST` audited); printing is refused until the EIN and address are set (409
  SETUP_INCOMPLETE).
- Marking: `donation_line` per allocation (unique), purpose, goods value and description (value ≤ the line's amount,
  description required with a value). Only on an active deposit outside a Closed Fiscal Year; transfers are not
  deposits here (409 NOT_A_DEPOSIT). Audit `DONATION_MARKED` per change (unmarking deletes the row; before/after in
  the event).
- Receipts: one per donor (the allocation's entity, else the transaction's). The content hash covers donor, name,
  address, amount, date received, goods and purposes. Same hash as the donor's last numbered receipt → DUPLICATE
  (same number, `replaces_id` = that receipt); different → CORRECTED (new number, confirmation
  `CORRECTED_RECEIPT`); none → ORIGINAL. Numbers `R-<year of the deposit date>-<seq>` per workspace. Confirmations
  `EMPTY_VARIABLES`, `NO_DONOR_ADDRESS`. Void/deleted deposit → 409 NOT_PRINTABLE and the receipts show `void`.
  The PDF (ReportLab, `invariant`) is attached as a system-generated `DONATION_RECEIPT` via `_store_doc_copy`
  (de-duplicated by SHA-256); audit `DONATION_RECEIPT_PRINTED`. The acknowledgment box and goods statement are
  drawn by `receipt_pdf()`, not the template.
- UI: `pages/Donations.tsx` — `DonationSetup` (`/donation-setup`, Administrator menu) and `DonationReceiptDialog`
  (Register → deposit → *Donation receipt…*), About → Optional modules.
- Polish (Kyle, 2026-10-22, migration `0047`): `donation_line.date_received` (empty = the deposit's date; not after it).
  A donor's dates are listed on the receipt (`dates_text`), the receipt number's year is the first date's, and the
  content hash includes them. `donation_detail` holds the `{DETAILS}` text per deposit and donor (`DonorIn` in the
  lines PUT; validated as `RECEIPT` text without `{DETAILS}`; audit `DONATION_DETAILS_UPDATED`); `values_for`
  resolves its variables. An empty `{DETAILS}` is not an empty-variable warning, its own paragraph is dropped and
  inside a sentence it leaves no double space. `details_enabled` tells the dialog whether the template uses it.
- Preview (Kyle, 2026-10-23): `POST /api/donations/transactions/{id}/receipts/preview` with the donor and, optionally,
  the unsaved lines and details. They are applied with `set_lines`/`set_details` and rolled back after `_compose()`
  (shared with printing), so the preview validates like a save. The receipt is watermarked *PREVIEW - NOT A RECEIPT*;
  a new receipt's number shows as *(assigned when printed)*. Nothing is attached and no number is taken. Audited
  `DONATION_RECEIPT_PREVIEW` (after the rollback). Headers `X-Receipt-Kind` / `X-Receipt-Replaces`.
- Dialog: the donor blocks are computed on screen from the ticked lines; Save / Preview / Print sit at the bottom for
  one donor, and in each block with several. Print saves first.
- Tests: `backend/tests/test_v210_donations.py` (14) and the E2E "#312" test.

**2.1.0 — scheduled backups: Kept as (#233, Kyle 2026-10-14; built 2026-10-21).**
- `scheduled_backup.keep_levels(runs, daily, weekly, monthly)` returns each kept run's reasons ("Daily", "Weekly",
  "Monthly", or "Latest" when only being the newest keeps it). `keep_set()` is now `set(keep_levels(...))`, so
  retention and the column share one calculation. `_retained_runs()` and `_keep_args()` are shared by
  `apply_retention()` and `kept_as()`.
- `out()` adds `kept_as` to each history row: the levels; *Removed* (deleted by retention); *Removed at the next
  backup* (managed but no longer kept after the settings changed); *Not managed (another folder)*; empty for failed
  or running ones. Nothing new is stored.
- Tests: `backend/tests/test_v210_backup_kept_as.py` (levels, Latest, 40 daily runs and a settings change before and
  after the next run) and the E2E scheduled-backup test.

**2.1.0 — contributor override for lines in no bucket (#303, Kyle 2026-10-21).**
- New table `fundraiser_line_contributor` (migration `0043`): one row per fundraiser and line, holding the
  contributor shown for the part of the line in no bucket. Bucket parts keep `fundraiser_bucket_line.contributor_override`
  (`0042`).
- `set_line` takes a line-level `contributor_override`. It is saved with the rest of the line and appears in the
  `FUNDRAISER_LINE_UPDATED` before/after, and it is deleted when the line is excluded. `_lines()` puts it on each row
  (none for an excluded line).
- `fundraiser_summary`: `line()` uses the bucket's override for a bucket part, and the line's own for the *Other* part.
  The plain line list uses the line's own. With names off, `who()` numbers it as its own *Contributor N*, as before.
- The table is also covered by `has_management_data` (a fundraiser with one is archived, not deleted), by
  `_drop_orphan_adjustments` and by reinitialize's wipe.
- Tests: `backend/tests/test_v210_line_contributor.py` (5 tests) and the E2E fundraiser line test.

**2.1.0 — private test data set (#272, Kyle 2026-10-20/21).**
- `scripts/test_data.py` is called as `scripts/demo_data.py --profile test`; the demo profile is unchanged.
  - It reuses the demo's API client and makes everything through the web API of a new installation, so every rule
    and the audit trail apply. It refuses an initialized installation.
  - `PW_TESTDATA_PASSWORD` is the sign-in password and the security answers; `PW_TESTDATA_PASSPHRASE` is the backup
    passphrase. Both come from the environment only. GitHub masks them in Actions (they come from `secrets.*`). They are
    redacted from API error text and never printed: the script doesn't print them even to mask them (CodeQL).
  - Fiscal Years are relative to today, July–June by default (`--fy-start-month`): two closed, the current approved,
    the next a Draft with `continues_budget_id` links.
- Kyle's decisions (2026-10-21):
  - The test users enroll two-step verification again after each restore. There are no fixed seeds: the API makes up
    the secret, and writing one into the database would bypass it.
  - The sign-ins are admin, budgetmgr, bookkeeper, auditor and treasurer. treasurer also has Register Admin, so the
    data set can include a deleted transaction.
  - The workflow can build from any branch, `test` by default.
  - The data covers several years.
- The two-a-year Pancake Breakfasts can't continue from each other: "Continues from" needs an earlier Fiscal Year. In
  the first year, each starts a series (#292) and the two are merged. Later years continue from the previous year's.
- `--backup` uses the backup API (`POST /api/system/backups`, `recoverable: false`, since the runner's server key is
  thrown away) and downloads the `.fmbak`. `--summary` writes JSON without secrets for the run summary.
- `.github/workflows/test-data.yml`:
  - runs on `workflow_dispatch` with the inputs `ref` (default `test`) and `fy_start_month`; `contents: read`;
  - starts `python -m fmpoc` on loopback with a temporary data folder (no frontend build is needed);
  - writes the schema from `alembic_version` into the run summary;
  - uploads the artifact with a 7-day retention.

  GitHub only lists a manual workflow once the file is on the default branch.
- Tests: `backend/tests/test_v210_test_data.py`. It runs the generator against a live server and checks:
  - refusals without the password variable and on an initialized installation;
  - the data;
  - that no secret appears in output, logs or the backup;
  - `pennywarden restore` into a new folder, then server mode: every test user signs in and gets `mfa_pending: ENROLL`.

**2.1.0 fix — Fiscal Year report PDF with 6+ years of history (#295, Kyle 2026-10-21).**
- The *Year over year by series* table used fixed 0.95" year columns and a 1.6" change column. From 6 years that is
  wider than the 7.13" frame, so the Series column had a negative width and ReportLab raised `ValueError`, which
  surfaced as INTERNAL_ERROR.
- `fundraiser_fy_report.yoy_layout(W, period, cells)` sizes a year column to the widest amount in the table (report
  font, 7.5 pt) plus padding, at most 0.95". The change column is 1.15" and the Series column at least 1.1". Of the
  latest 6 years, only as many as fit are shown, so amounts never wrap: $122,545.67 fits 6, $1,234,567.89 fits 5.
- Tests: `backend/tests/test_v210_fy_report_many_years.py` covers the layout across year counts and amount sizes, and
  the PDF and deck at 5, 7, 10 and All available with 8 years of history.

**2.1.0 fix — starting a series on one fundraiser (#292, Kyle 2026-10-21; completes #277's prior years).**
- `fundraiser_series.start_series()`: returns the fundraiser's series, or creates one named `series_name_for(name)`.
  It is audited as `FUNDRAISER_SERIES_CREATED` plus `FUNDRAISER_SERIES_LINK_UPDATED`, and is idempotent.
  `start_options()` lists the fundraisers in no series, newest first. Routes: `POST /api/fundraisers/{id}/series` and
  `GET /api/fundraiser-series/start-options`, Budget Managers only, any Fiscal Year (reporting only).
- `set_link(None)` on a fundraiser with no `continues_from_id` no longer clears its series. The edit form always sends
  `continues_from_id: null`, so a started series, and the history entered on it, would otherwise be dropped by the
  link dialog. Removing the link from a fundraiser that continues from another still takes it out, as before.
- UI: **Enter prior years…** on the fundraiser (opens `/fundraiser-series?enter=<id>`) and **Start a series…** on the
  series page. Both open the prior-year entry for the series.
- Tests: `backend/tests/test_v210_start_fundraiser_series.py` (5 tests) and E2E "2.1.0 (#292)".

**2.1.0 fix — deleted transactions release their check number (#289, Kyle 2026-10-20; amends the #53 decision).**
- `checks.holders()` (CR-011 uniqueness) and `checks.review()` (CR-012 missing checks) leave out `status ==
  "DELETED"`. The deleted record keeps `check_number` for the Auditors, and the duplicate message no longer mentions
  deleted transactions.
- `register.delete()` refuses with `CHECK_PRINTED` while `checkprint.is_reprint()` is true for a leg, i.e. the
  current number was printed and not spoiled.
- No migration: earlier deletions are released by the same query.
- The 1.7.3 test asserting the number stays used was changed on purpose. Tests: `test_v210_deleted_check_number.py`.

**2.1.0 — build 4–6 feedback (Kyle, 2026-10-20), on the build 7 branch.**
- *Contributor override:* migration `0042` adds `fundraiser_bucket_line.contributor_override` (120 characters).
  - `set_line()` takes `contributor_override` per bucket item and keeps it in the audit snapshot (`bucket_line_out`).
  - `summary()` uses it instead of the Entity for income lines (with names on). With names off, "Contributor n" is
    numbered per override text. For expenses it replaces the Entity before the description.
  - Top contributors in the deck aggregate by the shown name, so all "Cash" lines add up.
- *Headings:* `fundraiser_summary.heading()` puts a `CondPageBreak(1.3 in)` before every PDF section and itemized
  sub-heading, in the stakeholder and the Fiscal Year report. The two-column itemized list is now one 7-column table
  (left | gap | right) that splits by rows. Before, the nested tables could not split, so a long list jumped to the
  next page and left its heading behind. Word: the sub-heading paragraphs keep with next.
- *Deck axes:* `_style_chart()` gives every non-doughnut value axis a `"$"#,##0` format and a round major unit
  (`_nice_step`, about 4 steps). The bounds are rounded to that step. Data labels keep the cents.

**2.1.0 test build 7 — fundraisers across years, Fiscal Year report and deck (#277).** Migration `0041`:
- tables `fundraiser_series` (`name`, `group_as_other`, `merged_into_id`), `fundraiser_series_result` (label, `year`,
  net / income / expense cents, note, retired fields) and `fundraiser_fy_report_note` (one per Fiscal Year);
- columns `fundraiser.series_id` and `continues_from_id`.

The service is `services/fundraiser_series.py`; rendering is `services/fundraiser_fy_report.py` (PDF, and pptx
through the #276 deck helpers).
- **Years:** a Fiscal Year's number is the four-digit year in its name, else its end year. A fundraiser's year is
  that of the Fiscal Year covering its start date (else its first budget year, else the start year). An entered
  result's year is the first four-digit year in its label; a label without one is refused.
- **Linking:**
  - `set_link()` puts the fundraiser in the previous one's series, creating it as `series_name_for()` (the
    fundraiser's name without four-digit years) and audited `FUNDRAISER_SERIES_CREATED`. `None` unlinks.
  - The previous one must belong to an earlier year.
  - Audited `FUNDRAISER_SERIES_LINK_UPDATED`. It goes through `PUT …/series-link`, which works in any year, or through
    create / update (`continues_from_id`).
  - `continue_options()` lists the latest fundraiser per series plus unlinked ones of earlier years, newest first.
- **Next year:** `GET …/next-year` gives the pre-fill:
  - `next_name()` moves every four-digit year on one;
  - dates are moved a year;
  - budgets come from `_continued_by()`.

  Create with `copy_buckets_from_id` copies categories and buckets (`copy_buckets()`, audited).
- **Series list** (`/api/fundraiser-series`, `fundraiser.manage`): rename and *group as Other* (audited
  `FUNDRAISER_SERIES_UPDATED`), entered results (`FUNDRAISER_RESULT_ENTERED`), retire (`FUNDRAISER_RESULT_RETIRED`)
  and merge (`FUNDRAISER_SERIES_MERGED`).
  - A result is refused (409) for a year with a fundraiser of the series in PennyWarden, or a second active entry for
    that year.
  - Merge is refused when both series have an active entry for the same year. It moves the fundraisers and entries
    and sets `merged_into_id`; reports follow merges.
- **`fy_report()`:**
  - Each selected fundraiser comes from `fundraiser_summary.summary()`, so it equals its stakeholder report. The
    year total is their sum.
  - History is keyed by series (or by the fundraiser itself when unlinked). Recorded amounts are every fundraiser
    counted in an earlier year plus the selected ones this year; entered results are added for earlier years. Two
    fundraisers of a series in one year add up.
  - Period: `years` back from this year (-1 = all).
  - Targeted: for each series without a held fundraiser this year (none, or only PLANNED ones), the average of its
    last `avg_years` active years less its YTD, as a separate estimate.
  - Share: series marked *Group as Other* or under 5% of the period total become *Other*, with members listed.
  - Averages: the total over the period ÷ the series' active years (years with a recorded or entered amount, $0
    included).
  - Footnotes: two-year fundraisers, Entered vs Recorded, the estimate rule, the Other members.
  - The default selection (`…/fy-report/selection`) is every non-archived, non-cancelled fundraiser whose start year
    is this year.
- **Endpoints:**
  - `GET /api/fundraisers/fy-report?fiscal_year_id&ids&years&targeted&avg_years&format=pdf|pptx|json`
    (`fundraiser.view`; audit `REPORT_GENERATED {report: FUNDRAISER_FY_SUMMARY | FUNDRAISER_FY_PRESENTATION}` with the
    ids and options; json is not audited);
  - notes: `PUT /api/fundraisers/fy-report/notes` (`fundraiser.manage`, audited `FUNDRAISER_FY_REPORT_NOTES_UPDATED`).
- Frontend:
  - `Fundraisers.tsx`: list checkboxes and `FyReportDialog`; `FundraiserForm` gains *Continues from* and the
    pre-fill; the detail page gets *Series* with *Change…* (`SeriesLinkDialog`) and *Create next year's…*.
  - New page `pages/FundraiserSeries.tsx` at `/fundraiser-series`.
- **Year over year** (Kyle's feedback on the build 7 screenshots, 2026-10-20):
  - `series_history(f)` gives every year of the fundraiser's series up to its own year. A year is the sum of the
    series' fundraisers counted in it (`summary(…, history=False)`, so there is no recursion) or its entered result.
    Revenue, expenses and margin are `None` when an entered result has only the net.
  - `summary()` returns `year_over_year` (when there is more than one year) and adds a "Net proceeds were up/down …
    on <year>" takeaway.
  - The stakeholder PDF / Word get a *Year over year* table; the deck gets a column chart and table slide.
  - `fy_report()` returns `year_over_year` per series: values per period year, and the change on the most recent
    earlier year. The FY PDF shows a table (the last 6 years); the deck shows a multi-line chart and a change table.
- Tests: `test_v210_fundraiser_series.py` (15 tests) and the E2E "2.1.0 (#277)".

**2.1.0 test build 6 — fundraiser presentation (#276).** No migration. New dependencies `python-pptx` 1.0.2 (MIT) and
`XlsxWriter` 3.2.9 (BSD, the embedded chart workbooks). They are pinned, in THIRD-PARTY-NOTICES, pip-audit clean, and
in the PyInstaller specs (`collect_data_files("pptx")` for the default template). The router imports
`services/fundraiser_deck.py` at start-up.
- `fundraiser_deck.build(summary)` works from `fundraiser_summary.summary()`, so the figures equal the report. The
  summary gained `cumulative` (income and net by transaction date).
- The deck is 16:9 (12192000 × 6858000 EMU), on the blank layout, Arial everywhere.
  - Charts: column (revenue → proceeds), doughnut (revenue share; the legend labels carry the amount and percent),
    clustered bar (net by category; expenses), and line with markers (cumulative).
  - Every chart has data labels and no chart title.
  - Tables are capped at 12 rows per slide; top contributors at 10, with "and N more".
  - Every slide has speaker notes.
  - `_strip_template_extras()` drops the default template's printer settings (a `.bin` part) and thumbnail picture,
    so the package holds only XML, the chart workbooks and no media.
- Slides left out:
  - without buckets: revenue by category, category detail, net, top contributors and expenses;
  - without names or itemized revenue: top contributors;
  - revenue over time when there is only one date.
- The gold coin is drawn with two ovals, not an image. Organization branding is #280.
- `GET /api/fundraisers/{id}/presentation?itemized&names` (`fundraiser.view`; always `attachment`; audit
  `REPORT_GENERATED {report: FUNDRAISER_PRESENTATION, format: PPTX, options}`).
- Tests: `test_v210_fundraiser_deck.py`:
  - slide titles, chart types and data labels, chart data equal to the figures, notes on every slide, 16:9;
  - no media, binaries, embedded fonts, external relationships, transitions or animations;
  - no Entity name anywhere with names off;
  - markup kept as plain text.

  The CR-035 E2E downloads the deck. Manual checks in PowerPoint (Windows and Mac), Google Slides and Keynote are
  Kyle's, per build.

**2.1.0 test build 5 — fundraiser stakeholder report (#275).** Migration `0040`: `fundraiser.summary_notes`,
`results_final_at`, `results_final_by_user_id`. New dependency `python-docx` 1.2.0 (+ `lxml`), pinned through
`requirements.in`, in THIRD-PARTY-NOTICES, pip-audit clean, and in the three PyInstaller specs
(`collect_data_files("docx")` for its default template, `collect_submodules("docx"/"lxml")`).
`routers/fundraisers.py` imports `services/fundraiser_summary.py`, which imports `docx`, at start-up, so a package
built without it fails its smoke test.
- `fundraiser_summary.summary()` computes everything once from `fundraisers._lines()`, without excluded lines:
  - totals: gross deposits, float returned/out, net revenue (counted income), expenses, net, margin
    (net ÷ revenue), ROI (as on the page) and credits (sum of Less on expenses);
  - groups: categories in order, then uncategorized buckets, each with its buckets' income and expense lines (bucket
    nets; Charge / Less as detail);
  - `other` = the unassigned part of each line;
  - per-Fiscal-Year rows, takeaways and the plain line list.

  #276 and #277 are to use the same function.
- Contributor: the Entity (not system ones), else the line description. With names off, income lines become
  "Contributor n" (numbered in date order, one number per Entity), and expenses show the line description only.
- `report_status()`:
  - CANCELLED wins;
  - then FINAL (marked, or every Fiscal Year of the fundraiser Closed);
  - then INTERIM (planned / in progress) or POST_EVENT.

  The fundraiser detail returns it as `report_status`.
- Endpoints:
  - `GET /api/fundraisers/{id}/summary-report?format=pdf|docx&itemized&names&plain_lines` (`fundraiser.view`; audit
    `REPORT_GENERATED {report: FUNDRAISER_SUMMARY, format, options}`);
  - `PUT …/summary-notes` and `PUT …/results-final` (`fundraiser.manage`; audited
    `FUNDRAISER_SUMMARY_NOTES_UPDATED` and `FUNDRAISER_RESULTS_FINAL_MARKED/UNMARKED`). Both are allowed in a closed
    year, since they are reporting only;
  - the former `GET …/report` (audit section) is unchanged and is linked from Reports → *Fundraiser detail (audit)*.
- PDF: portrait, `_AuditDoc`. The footer is "Prepared for committee & stakeholders · Generated … · status ·
  Transaction-level evidence is in the Audit report". Itemized lists of more than 12 lines use two side-by-side
  tables.
- DOCX: Letter, Arial, a shaded title band, tiles and tables. The footer has PAGE/NUMPAGES fields. User text goes in
  as plain runs (BR-096). No pictures, macros or external links. The tests read it back with python-docx.
- Tests: `test_v210_fundraiser_summary.py` and the CR-035 E2E (dialog, Word, notes, final, Fundraiser detail).

**2.1.0 test build 4 — fundraiser buckets (#278; all questions resolved 2026-10-20).** Migration `0039`: table
`fundraiser_bucket_category` (`name`, `description`, `display_order`); `fundraiser_bucket.category_id` (no DB-level
FK, like `continues_budget_id`) and `display_order` (existing buckets numbered by `(name, id)` — the old listing
order); `fundraiser_bucket_line.charge_cents` (= `amount_cents`), `less_cents` (0), `less_description`.
- `amount_cents` stays the **net** (charge − less), so `_lines()`, totals, ROI, bucket nets and every report are
  unchanged; `charge_cents`/`less_cents` are detail only (`bucket_line_out()`; a `None` charge = the amount).
- `set_line()` bucket items take `amount` (as before: charge = amount, less = 0) or `charge` + `less` +
  `less_description` (`_bucket_amounts()`): charge > 0, 0 ≤ less ≤ charge, description required when less > 0; the
  nets must not exceed the counted amount. The audit snapshot carries charge, less and description per bucket.
- Categories: `create/update/delete_category()`, audited `FUNDRAISER_CATEGORY_CREATED/UPDATED/DELETED` (delete
  lists the bucket ids that became uncategorized). `reorder(what, ids)` needs every id exactly once and audits
  `FUNDRAISER_CATEGORIES_REORDERED` / `FUNDRAISER_BUCKETS_REORDERED` (no-op when unchanged). Categories, a bucket's
  category and the order are presentation only: allowed in a closed year (`update_bucket` applies `_require_open`
  only when the name or description changes). Permission `fundraiser.lines`; categories count as management data (a
  fundraiser with categories can't be deleted, only archived) and are wiped by Reinitialize.
- `_bucket_summary()` returns `items` in display order (with `category_id`, `credits_income/expense` = sum of Less),
  `categories` (in order, with `bucket_ids` and subtotals) and `uncategorized_ids`. Uncategorized buckets are listed
  after the categories. The Audit/Close fundraiser section prints the same grouping and "(charge less amount
  description)" on bucket assignments.
- Frontend: `BucketTable`, `CategoryDialog`, `OrderDialog` and the *Charge less a credit* toggle in `LineDialog`
  (`Fundraisers.tsx`).
- Tests: `test_v210_bucket_categories.py` (incl. the migration keeping figures) and the E2E "2.1.0 (#278)".

**2.1.0 test build 3 — budget planning (#257, #261; Budget Managers only, proposed items approved 2026-10-20).**
Migration `0038` adds the table `budget_projection_choice` (`user_id`, `budget_id`, `project`; unique per user and
budget, so per Fiscal Year). Reinitialize wipes it with the budgets.
- `services/budget_planning.py` holds both. Projection: `months_between(start, stop)` counts whole months from the
  Fiscal Year's start day (`add_months`, clamped) plus the partial month as days / days in that month.
  - `basis()` counts the report date as elapsed (`as_of + 1 day`); under one month the state is `TOO_EARLY`, and on
    or after the last day `YEAR_ENDED` (projected = actual).
  - `project()` = YTD × months / elapsed, rounded half away from zero to the cent.
- YTD = ACTIVE allocations dated on or before `as_of`, with no lower bound, so with today's date it equals the Budgets
  page actual (which includes allocations dated outside the year).
- Choices are made on rows that carry activity: a parent without sub-budgets, or each sub-budget, Other included. A
  parent with sub-budgets projects as the sum of its sub-budgets (projected or YTD) plus any unlisted remainder.
  - The default is *project*, except when every fundraiser linked to the budget (or to its parent) is ENDED,
    CANCELLED or ARCHIVED (`fundraisers.status_of`).
  - `PUT /api/reports/budget-prep/projection-choices` saves `{budget_id, project}` items; `reset` forgets them. It is
    not audited, like the register sort preference. The REPORT_GENERATED summary lists the unprojected ids.
- History: `_predecessors()` walks `continues_budget_id` back (deleted budgets skipped).
  - A sub-budget without its own link has no line (`history on parent`).
  - Other has no link of its own (BR-017), so it takes the Other of each earlier parent on its parent's line.
  - Next year: `_continued_by()` in the next Fiscal Year (by start date). For Other, only when that parent has
    explicit sub-budgets; otherwise the amount is on the parent's row, and the Planning Sheet doesn't mark that Other
    *not in draft*.
- Structure comes from `budgets.tree()` (Budget 0 excluded; zero Other hidden unless it has activity, BR-019).
  - The report keeps rejected and inactive budgets, labelled.
  - The Planning Sheet leaves them off, and their children with them.
  - A draft budget that continues nothing is listed after the current rows: under its parent's row when its draft
    parent continues a current parent, otherwise at the end of the section.
- Endpoints, all `require("budget.manage")`:
  - `GET /api/reports/budget-prep` (`format=json|pdf|csv`, `years` with -1 = all, `projected`, `include_next`,
    `budget_id` or `parent_budget_id`, `as_of`);
  - `GET`/`PUT /api/reports/budget-prep/projection-choices`;
  - `GET /api/reports/planning-sheet`.

  Each report is audited `REPORT_GENERATED` on the Fiscal Year.
- PDF output:
  - `_AuditDoc` takes a `pagesize`, so the Budget Review (then Budget Prep) report is landscape Letter; year columns split into bands when
    they don't fit.
  - The footer title carries the organization and print date.
  - The single-budget chart is a reportlab `VerticalBarChart`, with the legend in words.
- Frontend: `pages/BudgetPrep.tsx` holds the report tab (shown only with `budget.manage`), the shared
  `ProjectionChoices` checklist and `PlanningSheetDialog`.
- Build 3 feedback (Kyle, 2026-10-20):
  - The sheet is printed from the **Fiscal Years page**. `planning_context()` picks one planning at a time:
    - the latest Draft year that has an earlier year → plan it from the year before;
    - else the non-draft year covering today;
    - else the latest non-draft year, else the latest year.
  - `GET /api/reports/planning-sheet/context` tells the dialog which; `fiscal_year_id` is optional on
    `/planning-sheet`.
  - `_successor()` falls back to a next-year budget with the **same code, type and level that continues nothing**,
    when the current budget isn't continued by anything. Hand-entered drafts therefore line up instead of appearing
    twice (*not in draft* + *new in draft*). The Budget Review next-year column uses the same rule.
  - The Expense table starts on a new page when less than 35% of the page is left (`CondPageBreak(0.35 * BODY_H)`).
- Tests: `test_v210_budget_prep.py`, `test_v210_planning_sheet.py` (negative role tests for Budget User, Register
  User, Auditor and Administrator) and the E2E "2.1.0 (#257, #261)".

**2.1.0 test build 2 — register (#262, #258, #260, #259; proposed items approved 2026-10-19).** Migrations
`0035`–`0037`, additions only.
- *#262 sort:* `app_user.register_sort` (`"<column>:<asc|desc>"`, `None` = `transaction_date:asc`), set through
  `PUT /api/me/preferences` (`register_sort` / `reset_register_sort`) and returned by `/api/auth/me`. The Clear-date
  key is `(uncleared, clear_date, transaction_date, entry_timestamp, id)` and descending reverses the whole list, so
  ties read in entry order both ways. Sorted by Cleared the row's `running_balance` is the cleared balance (opening +
  ACTIVE cleared items in clear order; `None` on uncleared rows) and the response says `running_balance_kind`. The
  frontend keeps the choice in the Me context (`patchMe`) so navigating back keeps it without a reload.
- *#258 filter:* `documentation.categories()` runs the review's `classify()` for the register's rows (ACTIVE only);
  `missing` (and the 1.6.7 value `no`) keeps rows with a category, `marked` rows with a transaction- or
  allocation-level mark. Every row carries `documentation` for the badge. The 1.6.7 backend test was changed on
  purpose: a mark with a reason is documented, so it is no longer under "no".
- *#260 electronic payment:* `register_transaction.electronic_payment`, `payment_method`, `payment_method_other`,
  `payment_reference`. `register.electronic_values()` validates create and edit (withdrawals only; method required;
  OTHER needs a description; check number **or** reference). References are unique per account case-insensitively,
  in their own namespace (`DUPLICATE_PAYMENT_REFERENCE`), and never reach `checks.py` (CR-011/CR-012 read
  `check_number` only). The fields count as financial edits (cleared confirmation, closed-year lock) and are in the
  audit snapshot. Interlock: turning electronic on is refused (`CHECK_PRINTED`) while the current check number is the
  last printed one (`checkprint.is_reprint`); a spoil moves the number on, after which it is allowed.
  `get_printable(..., for_check=True)` refuses electronic payments for prepare/print/spoil/hand-written; options,
  documents, letter, envelope and envelope-test use `for_check=False`, and `PrintCheckDialog` then shows only
  `EnclosuresPanel`. `register.payment_text()` is what the Audit/Close and Entity Activity reports print.
- *#259 order:* `attachment.sort_order`; `attachments.DISPLAY_ORDER = (COALESCE(sort_order, id), id)` is used by the
  lists (active first, then removed), the Audit/Close report, the fundraiser report and the fundraiser lines.
  `reorder()` takes every active attachment of the owner (a Fiscal Year: its Unspecified ones) and numbers them after
  the owner's current maximum, so they never tie with attachments still in upload order; `_next_position()` puts new
  uploads, check copies, letters, envelopes and the Close report after them once an owner has been reordered.
  Rights = `check_manage` (the add-attachment permission per owner type); Closed Fiscal Year / deleted transaction /
  closed fundraiser refused; VOID allowed (BR-070); no `CLEARED_EDIT` (documentation). Audit `ATTACHMENTS_REORDERED`
  on the owner's object type, before/after `attachment_order` (id + filename); an unchanged order is a no-op.

**2.1.0 test build 1 — pipeline and installer (#240, #236, #237, #226; decided in chat 2026-10-19).** No migration.
- *#240 release dates:* `check_promotion.sh` no longer refuses `## <version> — unreleased` into main (the 1.7.3 rule);
  it still needs the section and refuses a tagged version, and pull requests into test/main fail while an *earlier*
  tagged version still says `unreleased`. `scripts/release_notes.sh` never printed the heading, so the published
  notes (GitHub release, `releases.json`, *What's new*) already carry only the publish date — nothing to rewrite in the
  build. `scripts/date_changelog.sh <version>` reads `published_at` of release `v<version>` from the GitHub API
  (`PENNYWARDEN_GITHUB_API`/`PENNYWARDEN_REPO` for tests, `--date` offline) and rewrites only that heading; it is the
  first commit of the next version. README links to the latest release instead of naming it. Tests:
  `test_v210_release_dates.py` (the real scripts in a throw-away repo with a bare `origin` carrying tags).
- *#237 `pennywarden apply-config`:* `cli_apply_config.py`. Order: parse and check `config.toml` (backup folders
  absolute, outside `/home`, `/root`, `/run/user`; mode, host, port, `trusted_proxies`, `secure_cookies`; every other
  value coerced like `load_settings`) → refuse to replace a `backup-folders.conf` without a PennyWarden header → write
  or remove the drop-in (2.0.0 format, new header) → unless `--no-restart`: `daemon-reload`, `restart`, wait up to
  60 s for `/api/health` on the configured address; on failure the previous drop-in is written back and the service
  restarted. `override.conf` is only read (a note when it lists `ReadWritePaths`). Audited as `CONFIG_APPLIED`
  (Security, object `server_config`) when a database exists, then `match_ownership` hands database/logs back to the
  data folder's owner. The data folder defaults to the installed unit's `--data-dir`. Without a systemd unit it only
  checks. Read-only `--show-url` / `--show-endpoints` serve the installer. `install-server.sh` runs `--dry-run`
  right after unpacking (before anything is stopped or migrated), `--no-restart --installer` where its inline
  Python/shell writer was, then `--show-url` for the health and status calls and `--show-endpoints` for the last
  lines. Verified end-to-end in a container with a fake `systemctl` (fresh install, upgrade with `0.0.0.0` and two
  folders, a specific address, the standalone command through the `/usr/local/bin` wrapper, a broken `config.toml`).
- *#236 Bind Address:* `connect_host` maps `0.0.0.0` → `127.0.0.1`, `::` → `[::1]`, IPv6 in brackets, anything else
  as is; `endpoints` lists `hostname -I` addresses (no loopback/link-local) for all-interfaces bindings.

**1.7.1 Display name required and shown in the top bar (issues #47, #46, #50).** `services/users.clean_display_name`
(trimmed, at least 3 characters, messages as agreed in #47) on create and on every update that sends the field;
`bootstrap` gives the first Administrator the username. Migration `0017` copies the username where the name is
missing or too short and adds two triggers on `app_user`. Triggers, not `NOT NULL` + `CHECK`: SQLite can add those
only by rebuilding the table, and `app_user` is referenced by almost every other table — a later migration that
rebuilds it must recreate the triggers (`tests/test_v171_display_name.py` checks they exist at head). The model
column therefore stays nullable in the schema. Top bar: `me.display_name` without roles; My account lists username,
email and roles; the Users list gained a Display name column (not asked for in the issues, added so an
Administrator can see which users still show a username).

**2.0.0 Check Printing, test build 1 (issues #156–#162; parent #60; decided in chat 2026-10-10).** Migration `0025`:
`workspace.checks_enabled` (off), `check_style` (name, preset, active, `config_json`), `check_signer` (name, title,
active, AES-GCM-encrypted PNG with its own AAD `fmpoc:check_signature:v1`), `check_account` (per bank account: the
style a Register User chose and the sheet counter), `check_printer_setting` (per user, style and feed mode: page
option, guide, personal adjustment in thousandths of an inch). Package `services/checkprint/`:
- `config.py` — the check style document (pydantic, `extra="forbid"`): stock (Letter only for now, check size, check
  tops, `TEAR_TOP`/`POSITIONS`, one signature line, a preview-only outline), defaults (font, size, capitals), fields
  (inches from the check's top-left; text fields with font/size/bold/capitals/align/shrink/min size; signature box),
  amount-in-words and number styles, date format, default memo, signature limit, default signer, 1–6 feed modes
  (`SHEET` position, or `SINGLE` lead `DATE_END`/`PAYTO_END`, page `LETTER`/`CHECK`, guide, offset ±0.5"). Rules:
  every field inside the check and **above the bottom 5/8"** (MICR clear band); the minimum size ≤ the size; one sheet
  feed mode at least.
- `presets.py` — `STANDARD_3UP`, measured from the product owner's stock and Word templates (field boxes = the text
  area; text baseline = box bottom + font descent, so the positions reproduce the Word text boxes plus their internal
  margins; verified against pdftotext and a 225-dpi scan of the stock).
- `fonts.py` — Liberation Sans/Serif/Mono 2.1.5 and Carlito (OFL 1.1, `fmpoc/fonts/`, regular + bold), registered
  with ReportLab and embedded; served to the setup preview from `/api/checks/fonts/{key}/{weight}`.
- `amounts.py` — words from whole cents up to 999,999,999.99: bank convention (AND only before cents, hyphens,
  `NN/100`), options AND in hundreds, no hyphens, case, `NO/100`, trailing word; number with commas / `$` / lead fill.
- `patterns.py` — literal text + `{NAME}` (case-insensitive, fixed table lookup), `{{`/`}}`, unknown name = error with
  a difflib suggestion, `{CHECK_NUMBER}` refused on the check face, control characters refused, 200 characters; split
  transactions give the first value + " and others".
- `render.py` — check space = points from the check's bottom-left, after the page transform (sheet: translate to
  the position; single: rotate 90° CCW for date end first, 90° CW for pay-to end first, on a check-sized page or a
  Letter page at the guide position), then the feed offset + personal adjustment in check coordinates (dx right,
  dy down). `layout()` fits each field (shrink in 0.5 pt steps to the minimum; payee and memo get a shortened
  suggestion; date and amounts block). The fill is drawn at baseline + cap height / 2 between "AND" and the cents.
  PDFs: check (signature image), test print, alignment test, calibration page, scale check, record copy (signature
  replaced by text, no image). `PrintScaling /None` is set as a viewer preference.
- `service.py` — module switch (shares `/api/system/modules`), styles, signers (PNG validated with Pillow and
  re-encoded; only a 220-px SAMPLE preview is ever returned), per-account style and sheet counter, printer settings,
  `prepare` (variables, memo, fit, signature choice and limit, warnings `EMPTY_VARIABLES` and `CLEARED`),
  `print_check`, `spoil`.
Printing rules: only ACTIVE withdrawals over zero outside a Closed Fiscal Year; a payee is required; the client
never supplies amounts; the typed number must equal the transaction's check number (set at print time if missing,
CR-011 uniqueness); a **reprint** is a print whose number equals the last printed number (from the
`CHECK_PRINTED`/`CHECK_REPRINTED` audit events) and needs a reason and does not move the sheet counter; any other print
uses a check; the record copy (document type `CHECK_COPY`, system generated, not removable) is attached when its
content (deterministic PDF, sha256) differs from the last one; **spoil** moves the transaction to a new unused number
and creates a zero-dollar VOID record on Budget 0 of the transaction's Fiscal Year with the old number (BR-072).
Permissions `checks.setup` (Administrator) and `checks.print` (Register User); Budget Managers have no access.
Because Administrators cannot see bank accounts or entities (BR-003), the style per bank account is chosen by a
Register User and signers are typed names. Audit: `CHECK_STYLE_*`, `CHECK_SIGNER_*`, `CHECK_SIGNATURE_*` (SECURITY),
`CHECK_TEST_PRINT`, `CHECK_ACCOUNT_SETTINGS`, `CHECK_PRINTED`, `CHECK_REPRINTED`, `CHECK_SPOILED`,
`CHECK_ALIGNMENT_TEST`, `CHECK_PRINTER_SETTINGS(_RESET)`. API `routers/checks.py`. Frontend: `pages/CheckSetup.tsx`,
`pages/CheckPrint.tsx` (print dialog, spoil dialog, sheet counter, printer setup assistant), `pages/checkShared.tsx`
(SVG preview with the built-in fonts, `PatternInput` autocomplete, browser instructions). Tests:
`tests/test_v200_checks.py` (positions read back with pypdf), E2E "#156-#162". Guide: `docs/check-printing.md`.

**2.0.0 Payments, test build 2 (issue #164; decided in chat 2026-10-10).** Migration `0026`:
`app_user.last_payment_account_id` (plain `add_column`; `app_user` has the 0017 triggers). The payment form is the
register's `TxnForm` with `payment` set (withdrawal only, no clear date, "Invoice(s)" wording, `AmountPreview`, submit
"Save and print check", `onSaved(saved)` receives the created transaction), so payments go through
`POST /api/transactions` with all register rules, confirmations, the request key and the attachment uploads. Endpoints
(`checks.print`): `GET /api/checks/payments/options`, `PUT /api/checks/payments/last-account`,
`POST /api/checks/payments/amount-preview` (words and number as the account's style prints them; preset defaults
before a style is chosen; nothing stored), `GET /api/checks/payments/recent` (from the `CHECK_COPY` record copies; the
module keeps no payment list). Frontend `pages/Payments.tsx` (`/payments`, nav for `checks.print` with the module on;
`/payments?txn=<id>` shows the transaction locked in a disabled fieldset). Register: *Create payment…* (detail);
the register's *New payment* button was removed in build 13 (Payments in the menu is the one place to start one). The memo autocomplete sets the cursor in a layout effect (was an animation frame - typing
could land in front of the inserted variable). Tests: `tests/test_v200_payments.py`, E2E "#164".

**2.0.0 Cover letters and envelopes, test build 3 (issues #165, #166, #174; decided in chat 2026-10-10).** Migration
`0027`: `transaction_allocation.invoice_date` (plain `add_column`; optional, withdrawals only, part of the allocation
snapshot and change comparison), table `check_document` (kind `LETTER`/`ENVELOPE`, `config_json` validated by
`LetterConfig`/`EnvelopeConfig` in `services/checkprint/documents.py`, one default per kind), and
`check_printer_setting.document_id` with `check_style_id` optional (batch mode: the table has no triggers) for each
user's envelope settings (`feed_key` "envelope"). Letters: platypus with the embedded fonts; the letterhead is typed
lines (a logo is a later enhancement); signer by name from the check's signer or the template's fallback name/role;
warnings `EMPTY_VARIABLES` and `NO_PAYEE_ADDRESS` (409 confirmation). Envelopes: #10 only (double-window envelopes are a
later phase); rotation as the single-check feed (`STAMP_END` = 90° CCW); the attached copy is drawn without the user's
offsets so it is deduplicated by SHA-256 like the letter (`CHECK_LETTER`, `CHECK_ENVELOPE` attachments). Handwritten
checks: `POST /api/checks/transactions/{id}/handwritten` (number typed twice; refused for a number already printed
unless it is the same), audit `CHECK_HANDWRITTEN`. Endpoints: `/api/checks/documents` (+ `/{id}`, `/{id}/flags`,
`/{id}/test-print`, `checks.setup`), `/api/checks/transactions/{id}/documents|letter|envelope|envelope-test|handwritten`
and `PUT /api/checks/my-printer/envelope` (`checks.print`). Frontend: `pages/CheckDocuments.tsx` (setup),
`pages/CheckEnclosures.tsx` (print screen panel, handwritten mode), `PatternInput` gains `multiline`. #174 polish:
default memo resolved with sample values, collapsible sections, `PdfViewer`, modal stack for Escape. Tests:
`tests/test_v200_letters.py`, `tests/test_v200_polish.py`, E2E "#165-#166".

**2.0.0 Voucher checks and two signature lines, test build 4 (issue #167; decided in chat 2026-10-10).** No
migration: everything lives in the check style's settings document. `config.py`: `Stock.signature_lines` 1|2,
`Fields.signature2` (required with two lines, dropped with one; must not overlap the first or reach the clear zone),
`second_line_limit_cents` (< `signature_limit_cents`), `default_signer2_id` (≠ the first), `stubs` (≤ 2 `Stub`:
`top`/`height` in page inches, `copy_kind` VENDOR|OFFICE, `title` pattern in the STUB context, `show_check_number`,
`show_memo`, font/size/margin) and `stub_columns` (like the letter's). Stubs require one check per sheet and SHEET feed
modes only, and may not overlap the check or each other. Preset `VOUCHER_TOP` (check 0–3.5", stubs 3.5–7" vendor,
7–11" office; the face reuses the 3-up field positions). Stub items flow in a fixed order (title + CHECK # / OFFICE
COPY, payee / date / amount, the line table, total, memo) rather than each being positioned - standard voucher stubs
are blank, and the margins, font and size are adjustable. `render.py`: `StubData`, `stub_columns` (vendor drops
BUDGET, office inserts it before AMOUNT), `stub_capacity`/`stub_rows` (overflow keeps capacity−1 rows plus the
"…and N more" line), stubs drawn in page space after the check (feed offset applied); every signature function takes
a box. `service.py`: `_second_choice` (SAME_SIGNER 409; over the second-line limit → "SECOND SIGNATURE BY HAND (OVER
LIMIT)"; none chosen → "SECOND SIGNATURE BY HAND"), `stub_rows`, `stub_data(job)` built at print time after the number
is confirmed, warning `STUB_OVERFLOW`, `sample_stub` for admin pages; audit adds `signer2_id`, `signature2`,
`stub_lines`. API: `signer2_id` on prepare/print/alignment; options add `signature_lines`, `default_signer2_id`,
`second_line_limit`; setup adds `signature2_default`, `stub_variables`. Frontend: `CheckSetup.tsx` (`StubsSection`,
`setLines`, `MoneyIn`), `CheckPrint.tsx` (second signature select), `CheckPreview` draws the second line. Tests:
`tests/test_v200_voucher.py`, E2E "#167".

**2.0.0 rename (Kyle, 2026-10-10):** the optional module is shown as the **Payments module**; the Administrator's
setup screen and menu item are **Payments Setup** (the Register Users' item stays **Payments**, so a combined local
user sees two distinct entries). Only labels changed: the API (`/api/checks`), permissions (`checks.setup`,
`checks.print`), `workspace.checks_enabled`, the `modules.checks` key, the route `/check-setup` and the guide's file
name `docs/check-printing.md` stay as they are.

**2.0.0 test build 5 (#183, #185, #186).** #183: `render.test_pdf` and `render.alignment_pdf` draw no
`_check_outline` and their stubs have no perforation line (`outline=False`); only `calibration_pdf` (and the record
copy, which is never fed through the printer) keep page markings. `test_pdf` draws one diagonal watermark under the
fields and, with a test signature, `_signature_watermarks` (a small centred note per `_sig_boxes` box) instead of a
second diagonal. `_border_note` sits `NOTE_INSET` (1/4") inside the check's top-right corner; the test print has
none (the diagonal says it). Tests: `tests/test_v200_build5.py` (scans the content streams for a check-sized `re`).
#185: `config.build_info()` adds `built_at_local` from `config.local_time_text()` (`datetime.astimezone()` with no
argument, so the OS time zone of the machine running PennyWarden; no tzdata needed in the PyInstaller builds; Windows'
full zone names are shortened to their initials). `BuildDetails` shows it with the UTC value as the tooltip and falls
back to UTC.
#186: `Section`, `viewState` (in-memory only, AC-SEC-006) and `LivePdfPreview` moved to / added in `checkShared.tsx`;
the letter and envelope editors use them (scopes `pw-letter`, `pw-envelope`). `POST /api/checks/documents/{id}/preview`
returns the sample-data PDF for unsaved settings (not audited: nothing is printed or stored; the test print stays
audited); the envelope preview is drawn upright on an envelope-sized page with its edge (`envelope_pdf(preview=True)`)
and follows the return-address setting. The preview iframe reloads 600 ms after the last change. `POST
/api/checks/sample-stubs` returns `render.stub_drawing()`: `_draw_stub` run against `_StubRecorder`, which records text
runs and lines in page inches, so `CheckPreview` draws the stubs exactly as `_draw_stub` prints them (offset from the
check by the sheet's first check top and the centring).

**2.0.0 test build 6 — letters (#176, #177).** Migration `0028`: `check_document.logo_png` (re-encoded PNG bytes; not
encrypted - a logo isn't secret), `logo_sha256`, `logo_width`, `logo_height`. `service.normalize_logo` accepts PNG or
JPEG by magic bytes and Pillow (`verify()`, then decode; 16-6000 px; decompression bombs refused), converts to RGBA and
scales down to 1500 x 600 px; `set_logo` audits `CHECK_DOCUMENT_LOGO_SET` / `_REMOVED` with the fingerprint and size
only. Routes: `POST /documents/{id}/logo` (multipart, 1 MB read limit), `POST /documents/{id}/logo/remove`,
`GET /documents/{id}/logo` (setup only, `no-store`). `LetterConfig` adds `logo_position` (LEFT|CENTER),
`preprinted` + `preprinted_margin` (1-4 in), `window` (NONE|LETTER|ADDRESS_PAGE), `window_return` and
`return_dx/dy`, `payee_dx/dy` (±0.75 in) over `documents.WINDOW_PRESET` (text start and window box per window, page
inches) with `FOLD_LINES` at 11/3 and 22/3 in. `letter_pdf(cfg, data, logo=, test=)`: the window addresses (return
address = the letterhead lines, first in bold, up to 4; payee up to 5 lines) are drawn on the first page by an
`onFirstPage` callback; in LETTER mode the flow starts with a spacer to just below the first fold, has no "To:" block
and the logo moves to the top right; ADDRESS_PAGE starts with an empty first page (`Spacer` + `PageBreak`). Dashed
window boxes and fold marks only with `test=True` (test print and live preview).

**2.0.0 test build 6 — administration (#126).** Permissions `system.view` (Administrator, Auditor) and
`system.manage` (Administrator). `config.setting_sources()` returns raw values and their source with the same
precedence as `load_settings`, which now remembers its command-line overrides in `config.CLI_OVERRIDES`.
`services/admin_settings.py`: `effective()` (the running value, the source, editable/locked, and `restart_required`
when what the service would start with now differs from the running value), `save()` (allow-list `EDITABLE`, `RANGES`,
`CHOICES`, combination checks, `SETTING_LOCKED`, password callback for `trusted_proxies`, one `SECURITY_WEAKENING`
confirmation, `write_config()` then `SERVER_SETTINGS_CHANGED`), `rewrite_toml()` (line-based: replaces `key = …` lines
inside `[server]`, adds missing keys at the end of the table, creates it if needed; an inline comment on a replaced line
is dropped), `rename_organization()`, `backup_age()` (from the latest `BACKUP_CREATED` / `SCHEDULED_BACKUP_CREATED`,
else `SYSTEM_RESTORED`, else the initialization) and `set_backup_warning_days()`. Migration `0029`:
`workspace.backup_warning_days` (default 7). Routes in `routers/admin.py`: `GET/PUT /api/system/settings`,
`PUT /api/system/organization`, `GET/PUT /api/system/backup-age`; `GET /api/system/backup-schedule/alert` adds `stale`
and `stale_message` for the banner. Frontend `pages/AdminSettings.tsx`; Auditors get System/About in the menu.
#127: migration `0030` adds `auth_session.client_ip`, set by `create_session(..., ip)` and refreshed by `deps._load`
with `last_seen_at`. `services/sessions.py`: active = not revoked, not expired, idle timeout not passed, user of the
workspace; `end_one` (not your own current session: `OWN_SESSION`), `end_user`, `end_everyone` (keeps the caller's).
Routes `GET /api/system/sessions`, `POST /api/system/sessions/{ref}/end`, `/sessions/end-user`, `/sessions/end-all`.
#128: `services/diagnostics.py` - `build()` returns the JSON file (`POST /api/system/diagnostics`, Administrators);
`storage()` (database incl. WAL/SHM, attachments folder size and count, `shutil.disk_usage` of the data folder, Alembic
current vs head) is shared with the health check; `recent_log_lines()` reads the rotated `fmpoc.log.N` files oldest
first into a 1,000-line deque and `scrub()`s each line.
#129: `diagnostics.health()` = `storage()` + `low_disk` (free < 1 GB or < 10 %); `integrity_check()` runs
`PRAGMA integrity_check(20)` (one read transaction; WAL mode keeps writers going), logs the details and returns OK or a
plain message. Routes `GET /api/system/health-check`, `POST /api/system/health-check/integrity`; the Administrators'
banner endpoint (`/api/system/backup-schedule/alert`) adds `low_disk`.

**2.0.0 test build 7 — maintenance mode (#130).** Migration `0031`: `workspace.maintenance_message`, `_starts_at`
(UTC), `_set_by`, `_set_at`; on = a message is set, active once `starts_at` (if any) has passed.
`services/maintenance.py` (`state`, `turn_on`, `turn_off`, `enforce`); global dependency `deps.enforce_maintenance`
after `enforce_csrf`; `GET/PUT /api/system/maintenance`; `/api/system/status` adds `maintenance_mode` (sign-in page
and the `MaintenanceBanner` for every signed-in user). The restore's existing `app.state.maintenance` is unchanged and
covers restore (and reinitialize, #125).
#124: `services/server_recovery.py` (server key, `write_recovery`, `passphrase_for` by file SHA-256, `list_backups`,
`remove_recovery`), `services/restore_report.py` (`build`: the current database through the ORM against the backup's
database by raw SQL on long-standing columns - `register_transaction.id/status/updated_at` and the allocations'
`updated_at` - so older backups compare too; NEW / EDITED / VOIDED / DELETED; a backup whose `workspace.key_check`
differs is compared by time only; the CSV plus a JSON summary in `restore-reports/`), `fmpoc/cli_restore.py`
(`pennywarden restore`; `__main__` dispatches it). `BackupCreateIn.recoverable` (default true). The web restore
writes the report before `swap_in` and adds `report` to `SYSTEM_RESTORED` and `report_summary` to the job result.
Routes: `GET /api/system/server-backups`, `POST /api/system/server-backups/{id}/remove-recovery` (Administrator),
`GET /api/system/restore-reports` (summary for Administrators, `can_download` for `financial.view`),
`GET /api/system/restore-reports/{name}` (`financial.view`).
#125: `services/reinitialize.py` (`WIPE` list children first, scoped deletes through the parents' ids; system entity
kept; organization reminders deleted, personal ones kept with their links cleared; `app_user.last_payment_account_id`
cleared; migration `0032` adds `workspace.reinitialized_at/_by`, `reinitialize_backup`, `reinitialize_ack_at/_by`).
Web: `GET/POST /api/system/reinitialize` (job `reinitialize`, polled at `/api/system/reinitialize/jobs/{id}`, open during
the pause), `GET /api/system/reinitialized` (banner), `POST /api/system/reinitialized/acknowledge`. CLI:
`pennywarden reinitialize` in `cli_restore.py`. `test_ac_sec_023` allows `subprocess` only in `cli_restore.py` (fixed
argument lists to `systemctl` / `sc.exe`, BR-102).

**2.0.0 test build 8 — real names (#134).** Migration `0033`: `app_user.first_name`, `last_name`,
`audit_event.actor_name` (plain `ADD COLUMN`: both tables carry the 0017 triggers). `services/users.py`:
`clean_person_name`, `full_name`, `label` ("First Last - username"), `names_needed`, `complete_names` (all rows
validated before any is saved); `update()` requires names when the account has none. `audit.actor_name(user)` is
stored by `audit.record`. `InitializeIn.admin_first_name/admin_last_name`; `/api/auth/me` adds `first_name`,
`last_name` and `names_needed` (Administrators only); `GET /api/users/names-needed`, `PUT /api/users/names`. Frontend:
`pages/NamesGate.tsx` (shown by `App` before the shell while `names_needed > 0`), Users list columns, search and sort,
"First Last - username" in the edit dialog title and the audit log. The backup list, the reinitialize banner and the
restore report's "entered by" use the same label.
#133: `services/audit_readable.py` - `action_label` (explicit `ACTION_LABELS`, else the code in words, so a new action
never breaks the screen; a test scans the code for action codes), `object_label`, `field_label` (`FIELD_LABELS`, else
words; `_cents` stripped), `fmt` (cents and `MONEY_KEYS` decimal strings as currency, Yes/No, codes in words, ISO
times), `labels_for` (written by `audit.record` into `audit_event.labels`, migration `0034`, "kind:id" -> name for
`ID_KINDS`), `readable()` (summary "who: what — target", kind create/update/remove/event/withheld, `changes()` with
only changed fields for updates and sub-tables for lists of rows). `GET /api/audit-events` adds `readable` to every
item; `GET /api/audit-events/meta` lists the codes present with readable names for the filters.
#131: `services/security_overview.py` - `overview()` builds the items (`key`, `title`, `value`, `status`
attention|ok|info, `note`) from the users, `UserMfa.enabled_at`, `recovery.is_locked`, `admin_settings.backup_age`,
the running settings and the request's scheme; `GET /api/system/security-overview` (`system.view`). Frontend
`SecurityOverviewPanel` in `pages/AdminSettings.tsx`.

**2.0.0 test build 10 — Windows server installer (#187).** `packaging/windows/install-windows-server.ps1` (Windows
PowerShell 5.1+, also pwsh): resolves the release like `install.sh` (`-Channel auto|production|test`, `-Version`;
only releases that have the script), downloads `PennyWarden-windows-x64.zip`, `nssm.exe` and `SHA256SUMS.txt` and
checks them, Caddy `$CaddyVersion` against `$CaddySha256`; stops the service; on an upgrade copies the data folder to
`<DataDir>-upgrade-backups\<stamp>` (ACL: SYSTEM and Administrators only, set before the copy); moves the package
into `<InstallDir>\<version>` and re-points the `current` junction; writes `config.toml` only if absent; creates or
updates the NSSM service (python.exe `-I app\launch.py --mode server --no-browser --data-dir`, auto start, restart,
stdout/stderr to `logs\service.log`, rotated), sets `obj= "NT SERVICE\PennyWarden"` with `sc.exe`, and re-sets the data
folder ACL (`icacls /inheritance:r`, SYSTEM and Administrators full, the service modify); with `-Domain` installs Caddy
into `<InstallDir>\caddy` (Caddyfile with `reverse_proxy 127.0.0.1:<port>`, `XDG_DATA_HOME` there so the certificates
stay with it) as the NSSM service `Caddy` under LocalSystem and opens 80/443; waits for `/api/health` and on failure
puts the previous junction target back; keeps one previous version. `build.yml`: the release includes the script; the
Windows job downloads `nssm-2.24.zip` (SHA-1 check), attaches `nssm.exe` and runs
`packaging/windows/test_server_installer.ps1` (install, upgrade, uninstall under Windows PowerShell 5.1).

**2.0.0 test build 11 — Payments Setup templates (#217).** No migration. `service.create_document(kind, name, preset)`:
without a name the template gets `free_document_name(kind, base)` — the first of `base`, `base 2`, … unused by any
template of the kind, deactivated ones included (they are never deleted, BR-001); a typed name must still be unique
(409 `DUPLICATE_NAME`). Preset `WINDOW` (letters only) = default letter config with `window = LETTER`, name *Window
envelope letter*. `duplicate_document` (`POST /api/checks/documents/{id}/duplicate`, `checks.setup`) copies the config
and logo into a new active template named `<name> copy[ N]` (the original name cut to 71 characters so the suffix
fits 80), default only if its kind has no active default, within `MAX_DOCUMENTS`; audited as
`CHECK_DOCUMENT_CREATED` with `duplicated_from` and `logo_sha256`. Previews: `services/checkprint/raster.py` renders
the sample PDF with PDFium (`pypdfium2`, imported lazily under a lock; up to 3 pages stacked, longer side 1600 px) and
`POST /api/checks/documents/{id}/preview-image` returns the PNG (`no-store`, `X-Page-Count`), or 501
`PREVIEW_UNAVAILABLE` when PDFium can't load (the macOS wheel needs macOS 13+); the PDF endpoint `/preview` stays as
the fallback. Frontend `LivePreview` (`checkShared.tsx`) shows the PNG in an `<img>` (Safari renders blob PDFs in an
inline frame blank), and on `PREVIEW_UNAVAILABLE` the PDF frame plus an *Open preview* link. `CheckDocuments.tsx`:
*Duplicate*, *New window-envelope letter*, the window-envelope pointer in the Envelopes section and the envelope
editor (`onOpen(letter, "window")` opens the letter at its Window envelope section), name field focused and selected
for new/duplicated templates. Packaging: the PyInstaller specs collect `pypdfium2_raw`'s library and data;
`scripts/third_party_notices.py` now includes every file in a PEP 639 `licenses/` folder (PDFium's dependency
licenses). Tests: `tests/test_v200_build11.py`, E2E "#217".

**2.0.0 test build 11 — UI standards (#214).** No backend change. `styles.css`: `--control-h` (34 px),
`--control-h-sm` (26 px) and `--label-h` (20 px = `.field-label` line-height 17 px + the 3 px `.field` gap) on
`:root`; inputs (not checkbox/radio/file/range/colour) and single selects get `height: --control-h`, buttons (not
`.small`/`.link`/`.linklike`/icon/nav buttons) `min-height: --control-h`, small controls `--control-h-sm`. Rows of
fields (`.row`, `.filters`, `.page-head`, `.report-options` that have a `.field` child, also through a `GuardedForm`'s
`fieldset.form-guard` with `display: contents`) use `align-items: flex-start`; their direct button / `.check` children
get `margin-top: --label-h` (small ones `+ (--control-h - --control-h-sm) / 2`), checkboxes `min-height: --control-h`
(replaces the old `.form-row` 19 px offsets). Rows with no fields centre their items. `.content` exposes its padding
as `--pad-x` / `--pad-y`; `.sticky-actions` sticks at `bottom: -pad-y` with negative margins and matching padding so
it covers the content area's padding (content used to show in the 16 px under and the 20 px beside the bar),
`z-index: 7` (above a pinned preview), opaque `--bg`. The pattern input's `<label>` uses the field-label style. E2E
"#214" (`layoutViolations`) measures every visible form row on 20 screens and forms and checks that the area under
the editors' action bar is the bar; screenshots in `e2e-screenshots/forms/`. Reference: `docs/ui-standards.md`.

**2.0.0 test build 11 — row actions menu (#215; icon ⋯ decided by Kyle 2026-10-13).** `RowMenu` (`components.tsx`):
a `<button class="small row-menu-btn">` (⋯, `aria-label`/`title` "Actions for <name>", `aria-haspopup="menu"`,
`aria-expanded`, `aria-controls` while open) and a `role="menu"` list portalled to `<body>` with `position: fixed` at the
button (above it near the bottom of the window) so a scrolling `.table-wrap` can't clip it; items are
`role="menuitem"` buttons with `tabIndex=-1` and roving focus. Escape stops propagation so a surrounding dialog stays
open. Falsy actions are dropped and `danger` ones sorted last behind a divider. Applied to Users, Budgets
(`BudgetTable`), Bank Accounts, Entities, Payments Setup (check styles, signers — the image upload is a hidden file input
clicked from the menu — letters, envelopes), fundraiser buckets, reminders (`ReminderItem`: Edit visible; Resolve…,
Reopen, Delete in the menu) and System/About sessions. E2E: `rowAction()` helper; test "#215" (keyboard, focus return,
outside click, every Users row).

**2.0.0 test build 11 — System/About tabs (#216).** `pages/About.tsx`: `ABOUT_TABS` (`about`, `general`,
`settings`, `backups`, `security`, `health`, `advanced`), the open tab from the path (`/about` or `/about/<tab>`, App
routes both to `About`); visibility — About everyone; General and System health `system.manage`; Settings and Security
`system.view` (Administrator, Auditor; the panels stay read-only for Auditors as before); Backups and Advanced the
Administrator (`restore_max_mb` present) / `system.manage`. A hidden or unknown tab is replaced by `/about`. `PageTabs`
(WAI-ARIA tabs, automatic activation, ←/→/Home/End); panels unchanged, only regrouped. The backup-failed and
backup-age banners link to `/about/backups`, low disk to `/about/health`; the About API's backup notice points to
System/About → Backups. The server's SPA fallback already serves `/about/<tab>` on reload. Docs updated to the new
locations. E2E: `aboutTab()` helper; test "#216" (addresses, reload, Back, keyboard, unknown tab, banner links via a
mocked alert, Auditor tabs); the #214 audit covers every tab.

**2.0.0 test build 12 — audit log export (#188; moved into 2.0.0 by Kyle 2026-10-14).** `routers/audit_log.py`: the
list's filters became a `Filters` model and `_query` / `_ordered`, shared by `GET /api/audit-events` and the new
`POST /api/audit-events/export` (`ExportIn`: filters + `format` csv|pdf + `time_zone`, `extra=forbid`). Every
matching entry goes through `_out` (so `readable` and the Administrator withholding are identical to the screen);
over `audit_export.MAX_EXPORT` (10,000) → 422 `EXPORT_TOO_LARGE`, nothing recorded. The export is audited before the
file is built (`AUDIT_LOG_EXPORTED`, object `audit_log`, category SECURITY, `{format, entries, filters, time_zone}`).
`services/audit_export.py`: `to_csv` (UTF-8 BOM; columns Event #, Local time (<zone>), UTC time, Actor, Category,
Action, Object, Object #, Summary, What changed — an update as `Field: before → after (changed)`, a new record as
`Field: value`, removed as `Field: value (before)`, empty fields left out, line tables as `Line n: Column: value; …`;
every cell through `reports._csv_safe`) and `to_pdf` (reportlab, Letter landscape, Vera fonts: header with exported
by/when/zone/filters/count, then per entry the action, summary, time · actor · category · event #, and the same
Field/Before/After/changed table as the screen; footer with organization and page). Frontend `AuditLog.tsx`: *Export
CSV* (downloads) and *Printable PDF* (`PdfViewer` with Print/Open/Download) send the current filters and the browser's
time zone; the list reloads to show the export entry. Tests: `tests/test_v200_build12.py`, E2E "#188".
The PDF never wraps an entry's change table in another table (a one-cell table can't split, so a long entry broke the
layout): the table is indented with `hAlign`, repeats its header across pages, and a single cell is cut at 2,500
characters with a pointer to the CSV, which holds everything.

**2.0.0 test build 12 — dependencies (Dependabot #223, #224, folded in by Kyle's request 2026-10-14).** `requirements.txt`:
fastapi 0.143.0, pydantic 2.14.0 + **pydantic_core 2.50.0** (Dependabot bumped pydantic but not its pinned core, so
#224's install failed), SQLAlchemy 2.1.4, pypdf 6.20.0, pycparser 3.11 — resolved in a clean Python 3.12 environment
(no new transitive packages; wheels for Windows x64, Linux x64/arm64 and macOS arm64 checked). Frontend dev tools:
@playwright/test 1.64.0, vite 6.4.4 (lockfile identical to #223). Notices regenerated with Python 3.12.

**2.0.0 test build 13 — release-candidate polish from testing (#230; only polish from build 11 on, Kyle
2026-10-14).** No migration.
- *Reinitialize:* System/About → Advanced's section is called *Reinitialize* (no second heading).
- *Maintenance mode:* `services/maintenance.READ_ONLY_POSTS` lets POSTs that change nothing through for everyone
  (Financial Flow Report review/PDF, audit log export, account number reveal, fundraiser filter preview). In the
  frontend `App.tsx` `can()` keeps only `READ_PERMISSIONS` (`*.view*`, `bank_account.reveal`) while paused for a
  non-Administrator, so screens drop their change actions (New payment on Payments, Print check…, reminder actions …); a 503
  `MAINTENANCE` answer dispatches `pw:maintenance-changed` so the shell reloads the state at once. E2E checks pages
  for change buttons while paused (`pausedActions`).
- *Host commands:* `install-server.sh` writes `/usr/local/bin/pennywarden`, a wrapper that execs
  `/opt/pennywarden/current/pennywarden` (not a symlink, so it always runs the current release; a file not written by
  the installer is left alone). The portable launcher resolves a symlink to itself (`readlink -f`).
  `cli_restore.host_command(settings)` / `restore_command()` give the command for the install type (Linux server
  `sudo pennywarden`, Windows server `PennyWarden.cmd` as Administrator, local without sudo, container), used by the
  undo text on Reinitialize and the restore hints. Run as root, `restore`/`reinitialize` already handed files back with
  `match_ownership()`; `reset-password` and `reset-mfa` now do too (`__main__._own_again`, database and logs), so a
  `sudo` run can't leave a root-owned SQLite journal the service can't write.
- *Letters and envelopes as drafts:* *New letter / envelope / window-envelope letter* and *Duplicate* open the editor
  on `GET /api/checks/documents/draft?kind=&preset=&duplicate_of=` (the config only, nothing stored); its previews and
  test print go to `POST /api/checks/documents/draft/preview|preview-image|test-print` with `{kind, config,
  logo_from}`; the first *Save* is `POST /api/checks/documents` with `{kind, name, config, duplicate_of}` (a duplicate's
  logo is copied then). Leaving an unsaved draft asks first; nothing is created or audited until Save. The logo can be
  added once the letter is saved.
- *Over-scroll:* `.content { position: relative }` — absolutely positioned descendants (the hidden file inputs of the
  editors) were measured against the page and stretched it below the last row.
- *Scheduled-backup folders on the Linux server:* new installs write `backup_folders = []` to `config.toml`; the
  installer reads the list (TOML list; a string is split on `:`) and writes the drop-in
  `/etc/systemd/system/pennywarden.service.d/backup-folders.conf` with one quoted `ReadWritePaths="-<folder>"` per
  folder (the service runs with `ProtectSystem=strict`; `-` = a missing folder doesn't stop it), skipping folders under
  `/home`, `/root` or `/run/user` (`ProtectHome`) with a comment; the drop-in is removed when the list is empty. Run the
  installer again after changing the list.
- *Safari print previews:* Safari draws a PDF in an inline frame blank, so the print screens (check, alignment test,
  cover letter, envelope, test prints) and the audit log PDF showed nothing. Every such response now keeps the PDF in
  `services/pdf_preview.py` (memory, per user, 15 minutes, at most 40 / 40 MB) and names it in `X-Preview-Token`;
  `GET /api/pdf-preview/{token}` (`routers/pdf_preview.py`) returns a PNG of it via `raster.pdf_to_png` (4 pages,
  1400 px). Nothing is generated twice, so printing is still recorded once. Frontend: `api.requestBlob` /
  `withPreviewToken` put the token on the Blob, `usePdf` keeps it, and `PdfViewer` in Safari (`detectBrowser()`)
  shows the picture instead of the frame and makes **Print…** open the PDF in a new tab, where Safari shows and prints
  it (printing a blank frame could waste a check); without a picture it falls back to the frame and the new-tab hint.
  Other browsers are unchanged. E2E "#230" runs the print screen with Safari's user agent.
- *Register (product owner, 2026-10-14):* no *New payment* button in the toolbar - a new payment starts on **Payments**.
  A withdrawal's details had both *Print check…* (dialog over the register) and *Create payment…* (the
  `/payments?txn=<id>` page with the details locked, then the same dialog); now there is one button, *Create payment…*,
  or *Reprint check or letter…* once `check_printed`, opening `PrintCheckDialog` over the register. The `?txn=` page and
  `LockedTxn` are gone (an old link shows the Payments page). For a printed check (`is_reprint`) with letter or
  envelope templates (`has_documents`) `PrintCheckDialog` shows two closed `<details>` sections (*Reprint the check* →
  `PrintForm`; *Reprint the letter or envelope* → `EnclosuresPanel`, no check printed or recorded), each mounted only
  while open. `EnclosuresPanel` (first print and reprint): the letter list carries `window`; with a window-envelope
  letter included the envelope part is replaced by a note (*Print an envelope anyway* shows it), a standard letter
  shows it again.
- *Wizard:* the first-name field's error said *Last name is required.* (`clean_person_name` now checks the field name's
  ending).
- *Docs and site:* the CHANGELOG's 13 test-build sections became one 2.0.0 entry by area; every document in `docs/`
  checked against 2.0.0; `scripts/demo_data.py` updated for the security questions (1.8.0) and real names (2.0.0) and
  sets up the Payments module (a voucher style with a made-up signature); `readme_screenshots.mjs` adds `payment.png`
  and `check-print.png`, which the README and pennywarden.org (new *Payments* section) show.
Tests: `tests/test_v200_build13.py`, `test_v200_maintenance.py`, `test_v200_real_names.py`; E2E "#130" (pages
without change actions while paused) and "#217" (drafts kept only on Save).

**1.10.0 Update notification (issue #58; channel decided 2026-10-09).** Migration `0024`: `update_check` (one row).
`services/updates.py`: `channel(settings)` - setting `update_channel` (`auto` → from `build_info.json`: `main` →
stable, `test` → test, anything else / no build info → none); `check(app, force)` - due after 24 h (6 h after an error),
the channel is part of the cache key; `fetch` (urllib, 10 s, 2 MB, schema 1, `_clean` per release); `is_newer` (numeric
version; the same version is newer only for a test build with a higher build number); `status` for
`GET /api/updates` (every signed-in user); `PUT /api/updates/settings`, `POST /api/updates/check` (`users.manage`).
The check runs in the scheduler thread of #62 (`Scheduler._loop` calls `updates.tick`), so it only runs under the real
web server: first ~60 s after the start (local mode "at start-up"), then whenever due. Download link: the product
page's `#download` for production, the GitHub release page for test builds. Frontend `pages/Updates.tsx`: indicator
(SVG circle in the coin's gold `#f2b632` with the arrow cut out by a mask), `WhatsNew` dialog, `ReleaseNotes`
(paragraphs, bullets with wrapped lines, headings, `**bold**`, `` `code` ``, links to github.com / pennywarden.org
only - React elements, no HTML parsing), `UpdateBanner` (shell for Administrators in server mode; My account in local
mode), `UpdateSettings` (System/About). E2E: the fresh server reads `http://127.0.0.1:8796`, served by the "#58" test.
Tests: `tests/test_v1_10_updates.py`, E2E "#58".

**1.10.0 Dialog focus (issue #139).** `Modal` focused the dialog in an effect keyed on `onClose`; a parent that holds
the dialog's input state passes a new `onClose` on every keystroke, so the focus jumped out of the field. The effect now
runs once; the latest `onClose` is kept in a ref for Escape. E2E "#106" types the reason key by key.

**1.10.0 pennywarden.org (issue #83; settled 2026-10-09: in this repository, a hand-written page, one domain).**
`site/` (static HTML/CSS/JS, CSP `default-src 'self'`, no third-party resources; `site.js` fills the download
buttons from `releases.json` with `textContent`/attributes only and accepts only `https://github.com/` URLs),
`scripts/release_data.py` (GitHub releases → `releases.json` / `releases-test.json`: tags `vX.Y.Z` non-prerelease =
stable, `vX.Y.Z-test.N` prerelease = test; numeric version order; notes cut at the install footer the build adds (2.0.0 #207: test builds put that block first, before a rule - `HEADER` strips it);
downloads classified by file name with SHA-256 from each release's `SHA256SUMS.txt`), `scripts/build_site.sh`,
`.github/workflows/pages.yml` (always checks out `main`; `upload-pages-artifact` + `deploy-pages`). `build.yml` gains
a `site` job after `publish` that runs `gh workflow run pages.yml --ref main` (a release created with the workflow
token does not trigger other workflows; `workflow_dispatch` is the documented exception, and running on `main`
satisfies the `github-pages` environment's branch rule). Tests: `tests/test_v1_10_release_data.py`.

**1.9.0 Scheduled Automatic Backups (issue #62).** Migration `0023`: `backup_schedule` (one row per workspace) and
`backup_run`. `services/backup.py` gains the key-pair format (`kdf: "keypair"` in the existing `FMBAK1` header:
`public_key`, `private_key` = scrypt/AES-GCM-locked X25519 key, `epk`, `wrapped_dek`; `decrypt_file` handles both
kinds, so Restore is unchanged) - `new_keypair`, `create_backup(..., keypair=)`. `services/scheduled_backup.py`:
settings (`save`, `check_destination`, `test_folder`, `out`, `alert`), `run_backup` (work folder → copy to
`<folder>/.<name>.partial` → rename; one run at a time), `apply_retention`/`keep_set`, `due`/`tick` and the
`Scheduler` thread (started by the app's lifespan, so only under the real web server; first tick after 60 s, then
every 30 s; skipped during a restore or a manual backup). Schedule times are server local time, stored as UTC
(`next_run`). A scheduled run sets the next time and clears any retry first; a failure sets `retry_at` = 60 min, a
failed retry doubles up to 1440; a run more than 15 minutes late counts as MISSED. Endpoints (`users.manage`):
`GET/PUT /api/system/backup-schedule` (PUT with `passphrase` needs `password`), `POST …/test`, `POST …/run` (202,
background thread), `GET …/alert` (banner). Setting `backup_folders` (TOML list or path-separator list). Frontend:
`pages/ScheduledBackups.tsx` (tab *Scheduled* in Backup / Restore, banner in the shell). Tests:
`tests/test_v190_scheduled_backups.py` (drive `tick`/`run_backup` with explicit times), E2E "#62".

**1.9.0 Single User Local Install (issue #54).** No migration: `app_user.security_domain` gains the value
`COMBINED` (`permissions.domain_of`). `permissions.validate_role_set(domain, roles, mode)` accepts roles of several
domains only when `mode == "local"`, and the domain must equal `domain_of(roles)`. `bootstrap.initialize` gives the
first user `LOCAL_FIRST_USER_ROLES` in local mode (`SYSTEM_INITIALIZED` records `admin_roles` and `mode`).
`services/users.create/update` receive the mode from the router; an update with unchanged roles is not re-validated
(a COMBINED user stays editable on a server). Dashboard: a COMBINED user with the Auditor role gets the Auditor
dashboard (financial + review summary), otherwise the financial one. Frontend: `navFor` builds a COMBINED user's
menu from the permissions; the user form on a local install lists every role grouped by domain and derives the
domain (`domainOf`). Test fixtures keep the test Administrator to the Administrator role (`initialize(app,
single_domain=True)`); the E2E suite does the same through the user form after checking the combined first user.
Tests: `tests/test_v190_single_user.py`, E2E "AC-INIT-001..007".

**1.8.0 Dependabot and the third-party notices (issue #98, option 2 decided 2026-10-08).** `tests.yml` takes an
input `notices` (`check` by default). `ci.yml` passes `regenerate` for pull requests from `dependabot/*` branches,
`build.yml` for develop builds; pull requests into test and main and the test/main builds stay `check`.
`scripts/third_party_notices.py --regenerate` rewrites the file for the run only (it is uploaded with the run's
artifacts, never committed - no write token is involved) and reports the difference as a GitHub warning and in the
job summary; `--check` now also fails when a shipped Python package is not pinned in `backend/requirements.txt`
(`unpinned()`), which `--regenerate` reports as a warning. The file is regenerated and reviewed on develop before a
promotion to test (docs/branching.md). Tests: `tests/test_v180_dependabot_notices.py`.

**1.8.0 Forgotten password (issue #113; decisions recorded in the issue: one random question, fixed list).**
`services/recovery.py`; migration `0022` (`app_user.failed_attempts`, `locked_until`, `must_change_password`,
`reset_question_slot`/`_at`, `notice_failed_attempts_at`, `notice_password_reset_at`/`_method`; tables
`user_security_question` (slot 1-3, question code, Argon2id hash of the normalized answer) and `security_notice`).
**Sign-in steps** reuse the MFA-pending session (`AuthSession.mfa_pending`): after the password and two-step
verification, `recovery.gate_for` returns `PASSWORD` (temporary password from the host `reset-password`) or
`QUESTIONS` (fewer than 3 questions); `auth.login`, `auth.complete_mfa` and the initialization wizard create the
session in that state (15 minutes, no roles). `POST /api/auth/setup/password` and `/api/auth/setup/security-questions`
complete a step through `routers/auth._finish` (session rotation, next step or full session; `LOGIN` audited once the
session is full). `GET /api/auth/security-questions` is the list; `GET/PUT /api/me/security-questions` (PUT needs
`current_password`). **Forgot password:** `POST /api/auth/forgot/start {username}` and `/complete {username, answer,
code?, new_password, new_password_confirmation}` (anonymous, pre-auth CSRF). The offered slot is stored on the user
for 15 minutes and cleared by a failed attempt; unknown / disabled / not-set-up usernames get a decoy question from an
in-memory map with the same lifetime and always fail (`400 RESET_FAILED`, same message). Password rules are checked
before anything is counted. A code is needed when `mfa.required(settings)` or the user has MFA on (`mfa.verify`:
TOTP with replay protection, or a recovery code that is spent). Success: new password, sessions and trusted browsers
revoked, `PASSWORD_RESET_SELF_SERVICE {method}`, user notice, Administrator notice. **Lock-out:**
`recovery.register_failure` (sign-in and reset failures of an existing active account) - locks at
`lockout_{1,2,3}_failures` for `lockout_{1,2,3}_minutes`, disabled at `lockout_disable_failures` (sessions revoked);
`auth.login` refuses a locked account before checking the password (`429 RATE_LIMITED`, the same answer as the
in-memory brake, which stays for client addresses and unknown usernames). A successful sign-in or reset clears the
count; so does re-enabling (`services/users.update`) and the host commands (`__main__._reenable`). **Notices:** the
user's (`sign_in_notices` in `/api/auth/me`, cleared by `POST /api/me/sign-in-notices/dismiss`): password reset,
failed attempts (set at the first lock). Administrators': `GET /api/security-notices`,
`POST /api/security-notices/{id}/dismiss` (`users.manage`) - second lock and later, disabled, self-service reset.
`GET /api/users` adds `security_questions_set`, `failed_attempts`, `locked_until`; `POST /api/users/{id}/reset-security-questions {reason}`.
Frontend: `pages/Recovery.tsx` (question picker, sign-in steps in `MfaGate`, Forgot password on the sign-in page,
My account section, notice banners in the shell). Tests: `tests/test_v180_forgot_password.py`; test helpers set up
the questions on a first sign-in (`conftest.Api.login(setup=True)`, E2E `passGates`); E2E "#113".

**1.8.0 Financial Flow Report (issue #106; decisions recorded in the issue).** `services/flow_report.py`, two
endpoints under `financial.view` (Administrators refused): `POST /api/reports/financial-flow/review` returns the lines
for the review form (not audited; nothing is produced) and `POST /api/reports/financial-flow` the PDF (POST because
the reviewed exclusions and line notes travel in the body). Lines: ACTIVE, `transfer_group IS NULL`, Transaction Date
in the period, cleared or not; a withdrawal is one line `t<transaction id>` with its full amount (description:
payee - the allocation descriptions, de-duplicated), a deposit one line per live allocation `a<allocation id>`
(its entity, or the parent's, - its description). The transaction's and allocations' Notes are never read. Sections
follow `bank_accounts.listing_order()` (#74); several accounts add the overall summary. Validation: register
accounts of the workspace only (404 / 422 `bank_account_ids`), From ≤ Through, Compare Date only with Include Bank
Balances and earlier than the Through Date (422 `compare_date`); no Through Date = server's today, printed
"Current". Exclusions need a non-blank reason and an existing line key (422 `exclusions`); unknown note keys 422
`line_notes`. Balances: every account open on the Through Date (not closed by then; register accounts from their
opening date, non-register accounts from their first history entry) in Checking / Savings / Investments (all other
types), `current_cents(as_of)` (#56 / #88), 0 before an account existed; subtotals, Total Checking & Savings, Total
Investments, Total Assets, and with a Compare Date the balance then and the change. PDF: reportlab like the other
reports, user text escaped (`P()`), Notes column on every table only when a line has a note, Difference and changes
green / red with `+` / `−` (U+2212). The audit entry (REPORT_GENERATED, report `FINANCIAL_FLOW`) records the
parameters, the line notes and each excluded line (transaction, allocation, date, amount, description, reason).
Frontend: Reports → *Financial Flow* tab (`pages/FlowReport.tsx`); totals in the form are recalculated client-side
in cents; unchecking opens a required-reason dialog, checking again discards the reason; the PDF is fetched with
`api.postBlob` and offered as Open / Download links. Tests: `tests/test_v180_flow_report.py`, E2E "#106" (last in
the file so its transactions do not become fundraiser lines in CR-034).

**1.8.0 Historic Budget Traceability (issue #89; decisions recorded in the issue).** Migration `0021` adds the
nullable, indexed `budget.continues_budget_id` (no foreign key, like other soft references; existing budgets are not
linked). One link per budget, 1:1: a budget continues at most one earlier budget and is continued by at most one
(non-deleted) budget. `services/budgets._set_continues` checks: same workspace, a Fiscal Year that starts earlier,
same type, same level (budget/sub-budget), neither is Budget 0 or Other, the target is not Deleted and not continued
by another non-deleted budget (409 `ALREADY_CONTINUED`). Set on create (`continues_budget_id` in `BudgetCreateIn`) or
changed/removed by `PATCH` (applied when the field is sent; `null` removes it) - the normal edit rules apply (not in
a Closed Fiscal Year, a locked budget is unlocked first) and the link is part of the BUDGET_CREATED / BUDGET_UPDATED
snapshots. Deleting a budget clears its link so the earlier budget can be continued again.
`fiscal_years.copy_budgets` links each copy (parents and sub-budgets) to its source when the source year starts
earlier and the source is not continued yet. `GET /api/budgets/continue-options?fiscal_year_id=&budget_type=&level=
[&budget_id=]` lists the choices grouped by Fiscal Year (newest first), Budget ID descending, label `<FY> - <ID> -
<Name>`; a budget already continued is offered only to the budget that continues it, so a later year sees the most
recent budget of each lineage. `GET /api/budgets/{id}/history` walks the chain both ways (cycle-safe) and returns it
oldest first with amount and actual (a parent's actual includes its sub-budgets, as on the Budgets page). The budget
tree marks `has_history`; the Budgets page shows **History** next to such budgets (all Financial viewers) and the
create/edit dialogs a **Continues** selector (hidden when no earlier year has a candidate). Tests:
`tests/test_v180_budget_traceability.py`, E2E "#89".

**1.7.3 Balance history for non-register accounts (issue #88; open questions answered with recommendations on
2026-10-08 while the product owner was away, recorded in the issue for review).** Table `bank_account_balance`
(migration `0020`): account, `as_of_date`, `balance_cents`, reason, `source` (OPENING / UPDATE / UPGRADE), entered
at / by. Append-only; `manual_current_balance_cents` stays as the cached current balance = the entry with the latest
date (ties: the later entry). `update_manual_balance(..., as_of)`: today or earlier, not before the opening balance
date, not inside a Closed Fiscal Year. Creation of a non-register account and a switch from register to
non-register add an entry. `bank_accounts.manual_as_of(date)` (None before the first entry) feeds `current_cents` /
`available_cents` with a date, so "as of" balances (Financial Flow Report #106, charts) carry forward. The balances
chart now includes non-register accounts. `GET /api/bank-accounts/{id}/balance-history` (financial.view; 422 for
register accounts). Back-fill in the migration: `BANK_ACCOUNT_CREATED` (non-register), every
`BANK_ACCOUNT_BALANCE_UPDATED`, and `BANK_ACCOUNT_UPDATED` events that changed the manual balance or switched to
non-register, dated by the event; then an `UPGRADE` entry when the last one differs from the current balance (dated
the account's creation day when there was no history, otherwise the upgrade day). Tests:
`tests/test_v173_balance_history.py`, E2E "#88".

**1.7.3 Budget Admin / Register Admin and the Deleted status (issues #52, #53; decided 2026-10-08).** BR-001 holds:
"delete" sets status `DELETED` (budgets: reason in `status_reason`; transactions: `deleted_at`, `deleted_by_user_id`,
`delete_reason`, migration `0019`, which also inserts the two roles for existing installations; `seed_roles` covers
new ones). Roles `BUDGET_ADMIN` / `REGISTER_ADMIN` are Financial; `validate_role_set` refuses them without
`BUDGET_MANAGER` / `REGISTER_USER` (`permissions.REQUIRES`). Permissions `budget.delete`, `transaction.delete`.
Budgets (`POST /api/budgets/{id}/delete`): Draft Fiscal Year only; refused for system budgets, with sub-budgets that
are not deleted, with live allocations of non-deleted transactions, or when a fundraiser uses it; a parent takes its
Other along; a deleted child gives its amount back to the parent's Other. Excluded everywhere budgets are listed or
copied (`children_of`, `tree` unless `include_deleted` for Auditors, selectable, filter options, copy, approval,
charts, fundraiser budget choices); the code is free again. Transactions (`POST /api/transactions/{id}/delete`):
ACTIVE and uncleared only, not in a Closed Fiscal Year, both transfer legs. Every balance and total already counted
ACTIVE only; listings were checked: the Register hides them except for Auditors with `status=deleted`;
`GET /api/transactions/{id}` is 404 for non-Auditors; the audit/close report selects ACTIVE (+VOID); Fiscal Year
allocation checks skip them; check numbers keep counting them (still used, no missing-check gap). Tests:
`tests/test_v173_admin_delete.py`, E2E "#52 / #53". Spec items changed: BR-001's list of states (+ deleted),
BR-065 (an uncleared transaction may be marked Deleted by a Register Admin), 04 permission matrix (two roles).

**1.7.3 Register Budget filter and Budgets links (issues #104, #105).** `GET /api/register?budget_id=` keeps the
transactions with a live allocation to the budget or its sub-budgets (`budgets.with_sub_budgets`) and adds
`budget_share` to each row (the sum of those allocations) and `budget` to the payload; running balances and
balance tiles are computed as before. `GET /api/budgets/filter-options[?fiscal_year_id=]` lists the choices: Fiscal
Year newest first, Income before Expense, by code; label `<FY> - <display code> - <name>`; Budget 0 left out; a
parent without explicit sub-budgets once (its hidden Other is covered); Other next to explicit sub-budgets only when
the Budgets page shows it (amount > 0 or used, BR-019). Frontend: `budget_id` is one of the Register filters
(kept on account change, reset by Clear); the chosen budget stays in the list when the Fiscal Year filter changes.
Budgets page rows link to `/register?budget=<id>&fiscal_year=<id>`; Register opens on the default account. The
initial-load code also fixes the fundraiser deep link (`?account=&search=`), which since 1.6.7 fell through to the
default account. Tests: `tests/test_v173_budget_filter.py`, E2E "#104 / #105".

**1.7.2 Current and Available balances (issues #56, #57; product owner decisions 2026-10-08, recorded in the
issues).** `services/bank_accounts.current_cents(as_of)` = opening balance + ACTIVE allocations of transactions with a
Clear/Post Date (on or before `as_of`); `available_cents(as_of)` = the former `balance_cents` (Transaction Date on or
before `as_of`, cleared or not); `outstanding(as_of)` = ACTIVE transactions dated on or before `as_of` with no clear
date or a later one. Non-register accounts: both are the manual balance. `out()` (Bank Accounts page, Dashboard and
its totals) and the balance chart use Current; account closure uses Current (equal to Available once nothing is
uncleared). Register view: `starting_balance`/`ending_balance` and the running balance stay on the Available basis
(BR-043: the Fiscal Year starting balance is the Available balance at the end of the previous day - derived, not
stored, and fixed by the previous year's Closed status, BR-012); new `current_balance` (cleared), `available_balance`
and `opening_reconciliation` / `ending_reconciliation` (`bank_balance` + `outstanding` = `balance`). The page shows
Opening + Current + Available for an open year or no year, Opening + Ending for a Closed year, Ending also for an
explicit *To* date. `register.check_clear_date`: Clear/Post Date >= Transaction Date on create, edit (any edit of a
record, as decided in #56), VOID date correction and transfers; existing data is not migrated. "Today's" Current
balance counts every cleared transaction (a future clear date is a data-entry error, not filtered). Spec items changed
(the spec in `spec/` is kept as delivered; these notes and the issues are the record): AC-BANK-006, BR-043 (made
precise + reconciliation), BR-053 (date rule), 07-database-design §11, 05-ui (Register header), CR-021 and CR-020
(Current). Updated tests that asserted the old meaning of `current_balance`: test_entities_bank (AC-BANK-006),
test_register (AC-REG-010/013), test_smoke, test_v13_duplicates, test_v141_charts. New: `tests/test_v172_balances.py`,
E2E "#56 / #57".

**1.7.2 Server Administrators cannot change their own roles (issue #55).** `services/users.update(..., mode=)`
refuses (403 `OWN_ROLES_LOCKED`) when, in server mode, the caller's own security domain or role set would change; the
router passes `settings.mode`. A request that sends the same domain and roles (the edit form always sends them) is
not a change and passes, so the own email address and display name stay editable. Checked before anything is
written, so nothing is audited for a refused attempt. Local mode is unrestricted (#54 relies on that). UI: the
Users page reads `mode` from `/api/system/status` and disables both fieldsets for the signed-in Administrator's own
account, with a hint. Follow-up found in the 1.7.2 test build (product owner): `active: false` on the caller's own
account is refused in every mode (403 `OWN_ACCOUNT_DISABLE`) and the Active box is disabled for one's own account;
the existing last-Administrator rule (409) stays as a second guard (now reachable only through role changes).
`test_init_auth.test_last_administrator_cannot_be_disabled` expects the earlier 403. Tests:
`tests/test_v172_own_roles.py`.

**1.7.1 Bank account order set by Budget Managers (issue #74, option 2).** Migration `0018` adds
`bank_account.sort_order` (integer, default 0) and numbers each group of each workspace 1..n — Primary first, then
by name, then id — with the group rule written out in the migration. `services/bank_accounts.listing_order()`
(group: Checking & Savings first, then `sort_order`, then `id`) is used by `GET /api/bank-accounts` (Bank Accounts
page, Register selector), the Dashboard, the balances chart and the Register's fallback when no account is Primary.
`POST /api/bank-accounts/{id}/move` `{"direction": "up"|"down"}` (`bank_account.manage`, i.e. Budget Managers)
swaps the account with its neighbour in the group — closed accounts included, since the page lists them — and
renumbers the group 1..n; past either end it is refused (409 `CANNOT_MOVE`). Audited as
`BANK_ACCOUNT_ORDER_CHANGED` with group, position and the group's id order before and after. Create and a type
change into the other group put the account at the end of its group. Reports (and the missing-check review) keep
their own order, as #74 leaves them out of scope. UI: ▲ ▼ buttons with `aria-label="Move <name> up/down"`, disabled
at the ends; after a move the focus returns to the moved account's button (the other one when it has become
disabled) and a polite live region announces the position. Tests: `tests/test_v171_bank_account_order.py`, E2E "#74".

**1.7.0 Rename to PennyWarden (product owner, 2026-10-07; issue #70).** Full record: `CHANGELOG.md` 1.7.0 and
`docs/upgrade.md` ("1.7.0: the rename to PennyWarden").

| Topic | Decision / implementation |
|---|---|
| Why | Another product in the financial field uses the name Fundwarden and has a website under it. |
| Name | **PennyWarden** (one word, capital P and W) wherever it is displayed; `pennywarden` for the command, service, system user, folders, packages and Docker image — the full name, not `penny` (a common first name for a system account, and an existing package and command name). The gold coin with a keyhole stays. |
| Release | 1.7.0 contains the rename and nothing else; other work starts with 1.7.1. |
| What was renamed | The same things as in 1.6.6 (below), plus the Mac app, its bundle identifier and data folder. Internal names stay: package `fmpoc`, `fmpoc.sqlite3`, `FM_*`, `.fmbak`. |
| Earlier names | `PREVIOUS_APP_NAMES` in `config.py` and `PREVIOUS` in `install-server.sh` list them newest first (Fundwarden, then the name before 1.6.6). Local default data folder: the newest earlier name that has a folder is renamed in place. Server: the installation in service is migrated, else the newest name with data; the 1.6.6 copy / compare / switch / automatic switch-back is unchanged. |
| Backups | File name and manifest take the name from `config.APP_NAME`; the name is not checked on restore, so Fundwarden backups restore. |
| Documentation | Current documents use the new name. The changelog entries of earlier versions, the migration instructions and this table keep the names that were true at the time. |
| Tests | `backend/tests/test_v170_rename.py`, including a check that no user-facing file still carries the old name; upgrade simulation with the real 1.6.8 and 1.7.0 packages (recorded in `docs/upgrade.md`). |
| Repository | Renamed to `kretherford0983/PennyWarden` on 2026-10-07; domain `pennywarden.org` registered the same day (product page: issue #83). |

**1.6.6 Rename to Fundwarden, first production release (product owner, 2026-10-02).** Plan: project doc
`claude/freedger-plan-1.6.6.md`.

| Topic | Implementation |
|---|---|
| Name | Product owner chose **Fundwarden** (dropped: Kitty — collides with the `kitty` terminal; Coffer — other finance apps of that name). Short name for service, user, folders and command: `fundwarden`. One name everywhere, also on reports (PDF `/Producer`). |
| What was renamed | Everything an operator or user sees: display name, package and launcher names, systemd service/user, `/opt`, `/var/lib`, `/var/backups` paths, default local data folder, backup and recovery-code file names, TOTP issuer (new enrolments only), Docker image/volume, repository URL (`legal.SOURCE_URL`), `FUNDWARDEN_*` test/override variables of `install.sh`. |
| What was not | Python package `fmpoc`, `database/fmpoc.sqlite3`, `logs/fmpoc.log`, `FM_*` settings, AAD strings of the encryption (`fmpoc:…` — changing them would make existing ciphertexts unreadable), the `.fmbak` magic/format, spec file names under `packaging/pyinstaller/`. |
| Server migration | `install-server.sh`: an `fmpoc` installation without Fundwarden data is migrated by **copy** (`cp -a` to `<data>.migrating`, `diff -rq`, `chown`, atomic `mv`), free-space check first; old service stopped + disabled, nothing of it removed (product owner: "installer migrates"; cleanup is a documented manual checklist). Failure before the switch restarts the old service; an unhealthy start after it switches back automatically and parks the copy as `<data>.failed-migration-<stamp>`. Refuses to run when Fundwarden data exists and the old service is running. |
| Local data folder | `config.adopt_legacy_data_dir`: only when the data directory is the default one, the new folder is missing and the old one exists — renamed in place (`Path.rename`), else used where it is. Never for `--data-dir` / `FM_DATA_DIR`. |
| install.sh | Default repository `kretherford0983/Fundwarden`; reads the port from `/var/lib/fundwarden/config.toml`, else the old location; a release whose `SHA256SUMS.txt` lists only the old package name is installed with that name (rollback / deliberate old install). |
| Icon | `frontend/public/favicon.svg` (gold coin with a keyhole, no text; a shield was dropped as too close to another product's mark), PNG 32 px and 180 px, `packaging/windows/fundwarden.ico` (16–256 px) for the `.exe`. Served from the static root; CSP unchanged (`img-src 'self'`). |
| Tests | `backend/tests/test_v166_rename.py` (6), E2E "1.6.6", upgrade simulation recorded in docs/upgrade.md. |

**v1.6.0 CR-033 Fundraiser module, core (product owner, 2026-10-01).** Plan with every decision: project doc
`claude/freedger-plan-1.6.md` (1.6.0 = CR-033; 1.6.1 CR-034 manage, 1.6.2 CR-035 report, 1.6.3 CR-036 reminders;
passkeys deferred).

| Topic | Implementation |
|---|---|
| Switch | `workspace.fundraisers_enabled` (migration `0010`, default off). `GET/PUT /api/system/modules` (`modules.manage` = Administrator, audited `MODULE_ENABLED/DISABLED`). `/api/auth/me` returns `modules`. Every fundraiser endpoint answers `404 MODULE_DISABLED` while off; data is kept. |
| Access | `fundraiser.view` = Budget Manager, Budget User, Register User, Auditor; `fundraiser.manage` = Budget Manager (create, edit, archive/restore, delete, budget options, preview). Administrators: no access (no financial data). |
| Model | `fundraiser` (name, description, event `start_date`/`end_date` — display only, `filter_text`, `filter_regex`, `archived_at`) and `fundraiser_budget` (fundraiser, fiscal year, budget, kind INCOME/EXPENSE; unique per fundraiser + FY + kind). |
| FY rule | `services/fundraisers.in_window`: a FY's budgets are selectable when the FY exists, is not Closed and the event lies inside it or within 3 months of its start/end (`add_months`). ≤ 2 Fiscal Years, adjacent in the workspace's FY order. Shell = no budgets. Creating/moving the event is refused when the FY covering the start date is Closed (`FISCAL_YEAR_CLOSED`). Budgets of a Closed FY cannot be removed/changed/added; moving the event must keep them in the window. Notices: `NO_BUDGETS`, `FY_WITHOUT_BUDGET` (an open FY in the window not used yet), `FUTURE_FY` (the window reaches past the last FY set up). |
| Inclusion | ACTIVE transactions, live allocations whose budget is a chosen budget (a parent = itself + all children, so the system "Other" leaf of a simple budget is covered), any transaction date, then the filter on the allocation description. Filter: RE2 (`google-re2`, linear time, case-insensitive; `literal` mode for plain text, so a plain filter is never a pattern); invalid/unsupported patterns → 422; ≤ 200 chars. |
| Warnings | `OTHER_BUDGET` (an "Other" child next to explicit sub-budgets), `PARENT_BUDGET` (a parent with explicit sub-budgets), `FILTER`, `SHARED_BUDGET` (overlapping leaf budgets with another non-archived fundraiser). `POST /api/fundraisers/preview` gives matched/total lines and non-matching samples for the form. |
| Figures | Income/expense/net per fundraiser and per FY, ROI = net ÷ expense (none without expenses), cumulative series by transaction date, included lines with bank account, entity, budget and the transaction + allocation attachments. Status derived from today vs event dates (Planned/In progress/Ended) or Archived. Classified/excluded amounts are 0 until CR-034. |
| Listing | Under every FY its event dates or budgets touch; "Upcoming" = touches no existing FY. Archived hidden unless requested. |
| UI | Menu item *Fundraisers* (when on); list with FY selector + Upcoming; detail page with notices, budgets, tiles, per-FY table, charts (lazy `FundraiserCharts`, shares the dashboard palette/helpers), transactions (link `/register?account=&search=`), attachments; create/edit dialog with budget options per eligible FY, warnings, filter warning and live preview. Admin: *Optional modules* on System/About. |
| Delete | Allowed unless a Closed FY is involved (archive instead); CR-034 adds the "nothing classified/excluded/bucketed/attached" condition. |

**v1.6.4 CR-037 / CR-038 (product owner, 2026-10-01).**
CR-037: `fundraiser.cancelled_at/_by_user_id/cancel_reason` (migration `0013`). `POST /api/fundraisers/{id}/cancel
{reason}` (required) and `/reinstate` - Budget Manager (`fundraiser.manage`), refused when all its Fiscal Years are
closed, audited `FUNDRAISER_CANCELLED/REINSTATED`. Status `CANCELLED` replaces Planned/In progress/Ended (Archived
still wins); nothing else changes - lines are counted as before. The page shows a banner with the reason; the
fundraiser report section (and so the Audit/Close reports) starts with "CANCELLED - this fundraiser did not take place
as planned" and the reason.
CR-038: `GET /api/fundraisers/{id}/count-sheet?signer_id=&signer_title=` (`fundraiser.view`; audited
`REPORT_GENERATED {report: CASH_COUNT_SHEET}`), `reports.build_count_sheet`: one Letter page - organization,
fundraiser, event date; date/time of count (no location - product owner); bills $100-$1 and coins $1-1¢ (count,
amount); 16 check lines; Cash total / Check total / Total counted (usable alone); notes; agreement statement;
signature + date lines. Signers reuse `signatures.resolve_signers` (0-5 distinct active individual Entities, title
≤ 60); none → three blank blocks; **1.6.6 (product owner):** one row per person; a blank row is Signature | Printed | Date, filled in by hand. **1.6.7:** a chosen signer gets one long signature line spanning both columns up to the date, with the name (and title) under it and no Signature / Printed labels (1.6.6 printed the name on the "Printed" line); with nothing asked for, two blank rows (dialog starts with two and offers the add button at once). **1.6.7 Entity position:** `entity.position` (String(60), migration `0014`, individuals only — dropped for organizations), edited with `entity.manage` (Budget Manager, Register User), audited with the Entity; `positionTitle()` in `SignatureOptions.tsx` fills it in as the signer's title in both dialogs when a signer is picked unless a title was typed by hand; the API prints the title it is given (no server-side default), so clearing the title prints none. `blank_lines` (0–3) adds blank rows after the chosen signers: at most 3 when no signer is chosen, at most 2 next to chosen signers, at most five rows in total (else 422; the dialog sends one per empty row, starts with three and enforces the same limits). Always two notes lines. Page 1 has 13 check lines (= the 13 bill/coin lines; CR-038 had 16) and the signature rows take the tallest height (0.78 in down to 0.4 in) with which page 1 still fits — the sheet is rendered again with the next lower height until it does; `extra_checks` (default true, checkbox in the dialog) adds page 2 for the back: check lines 14–43 and "Total of the checks on this page". Tests: page 1 never overflows, also with a 120-character fundraiser name.
Nothing is stored: the signed sheet comes back as a fundraiser document.

**v1.6.3 CR-036 Reminders and notifications.** Table `reminder` (migration `0012`): scope PERSONAL/ORGANIZATION,
owner, title, details, `due_date`, `notify_days_before` (0–365), optional link (FISCAL_YEAR/BUDGET/BANK_ACCOUNT + id),
resolution (at, by, note). Show date = due date − days before, compared with the **server's local date**. States:
UPCOMING → DUE (stays until resolved) → RESOLVED (can be reopened). Permissions: `reminder.view` (Budget Manager,
Budget User, Register User, Auditor), `reminder.personal` (Budget Manager, Register User), `reminder.org_manage`
(Budget Manager: create/edit/delete), `reminder.org_resolve` (Budget Manager, Register User). Visibility
(`services/reminders.can_see`): personal = owner only (others get 404); organization = Budget Managers always,
Register Users once due (incl. resolved), Budget Users/Auditors only while due and unresolved. Edit/delete only
before the show date (`REMINDER_DUE` afterwards); resolve only when due. API `/api/reminders` (`view=due|upcoming|
resolved`), `/count`, `POST`, `PUT /{id}`, `DELETE /{id}`, `POST /{id}/resolve {note}`, `POST /{id}/reopen`. Audited
`REMINDER_CREATED/UPDATED/DELETED/RESOLVED/REOPENED` (personal ones too - product owner). UI: bell with count in the
top bar (refreshed on navigation, every 5 minutes and after changes), `/notifications` page, dashboard section
`notifications` (new first entry of the default layout; saved layouts get it appended; renders nothing when no
reminder is due). No e-mail, no repeats (deferred).

**v1.6.2 CR-035 Fundraiser report (decisions 2026-10-01).** `services/reports._fundraiser_section` builds one
fundraiser from `fundraisers.detail` (so the PDF always matches the page): metadata, warnings, summary (income,
expenses, net, ROI; cash float and excluded amounts), per-FY table, buckets + Unassigned, counted lines (date, FY,
transaction #, type, entity/description + classification, budget, amount, counted, buckets), excluded lines with
reasons, then the fundraiser documents and each line's transaction/allocation attachments rendered with the audit
report's engine (images drawn, PDF pages merged, SHA-256 verified). No charts (product owner).
`GET /api/fundraisers/{id}/report` (`fundraiser.view`, module on; audited `REPORT_GENERATED {report: FUNDRAISER}`).
`build_audit_report(..., fundraisers=True)` inserts every non-archived fundraiser with a budget in the Fiscal Year
(`fundraisers.for_fiscal_year_report`; nothing when the module is off) after the transaction pages and before the
signature page; a two-FY fundraiser is complete in both reports, the report's year marked "(this report)".
`/api/reports/audit?include_fundraisers=true` (default false), `/api/reports/fy-close?include_fundraisers=` (default
true); the Close report stored at closing always passes true. The summary in the `REPORT_GENERATED` event counts the
fundraisers. UI: *Report (PDF)* on the fundraiser page; *Include fundraisers* (default on) for both reports.

**v1.6.1 CR-034 Fundraiser management.**

| Topic | Implementation |
|---|---|
| Access | `fundraiser.lines` = Budget Manager, Register User (buckets, line state, fundraiser documents). Viewing unchanged. |
| Line state | One call sets the whole state of a line: `PUT /api/fundraisers/{id}/lines/{allocation_id}` `{excluded, exclusion_reason}` **or** `{classification: {kind, amount, note}, buckets: [{bucket_id, amount}]}`. Tables `fundraiser_exclusion`, `fundraiser_classification` (one per fundraiser + line), `fundraiser_bucket_line` (one per bucket + line). Audited `FUNDRAISER_LINE_UPDATED` (before/after). |
| Figures | counted = 0 for an excluded line, else line amount − classified amount; fundraiser income/expense/net/ROI, the per-FY breakdown, the cumulative chart and the list use counted amounts. Totals also report cash float out/returned and excluded income/expense. Buckets: sum of assigned amounts per kind; unassigned = counted − assigned (per line, never negative). |
| Validation | Classification kind must match the line's side (`CASH_FLOAT_OUT` = expense, `CASH_FLOAT_RETURNED` = income; only these two types — product owner), amount > 0 and ≤ the line; bucket amounts > 0, each bucket once, sum ≤ counted; an excluded line has neither; the line must currently be part of the fundraiser; buckets must belong to the fundraiser. If a line's amount is reduced later in the Register, the classification is clamped and the line is flagged "More than counted" when its bucket amounts exceed it. |
| Closed FY | Lines whose budget is in a Closed FY cannot change; a bucket holding such lines cannot be deleted; when all the fundraiser's FYs are closed, buckets and documents are frozen too. |
| Budget change | Removing/changing a budget drops the adjustments of lines no longer in the fundraiser's budgets (count recorded in the `FUNDRAISER_UPDATED` audit event). Lines hidden only by the description filter keep their (dormant) adjustments. |
| Buckets | `POST/PUT/DELETE /api/fundraisers/{id}/buckets[/{bucket}]`; unique name per fundraiser (case-insensitive), ≤ 30; deleting a bucket unassigns its lines. |
| Documents | `attachment.fundraiser_id` (migration `0011`); owner type `fundraiser` in the attachments API (same type/size checks, soft removal). Upload/remove need `fundraiser.lines`; reading needs `fundraiser.view` and the module switched on. |
| Delete | Refused (`FUNDRAISER_IN_USE`) while buckets, classifications, exclusions or active documents exist — archive instead. |

**v1.5.0 polish CR-026 … CR-032, HF-001 (product owner, 2026-09-30).** 1.5.0 improves existing functionality only
(plan: project doc `claude/freedger-plan-1.5.md`).

| CR | Implementation |
|---|---|
| HF-001 | `boot()` loads the signed-in user before leaving the loading state, so the Login page never mounts after initialization; `api.ts` counts CSRF generations and a pre-auth token that arrives after a newer session token is discarded. |
| Sign-in bookmark | Sign-in and MFA always run on `/` (`navigate("/", {replace})`); `401 MFA_REQUIRED` reloads `/api/auth/me` to show the MFA screen. API responses carry `X-Frontend-Build`; a page from another build reloads once (`_b` marker); `index.html` is served `no-store`. |
| CR-028 | `services/bank_accounts.group_of`: CHECKING/SAVINGS → `CHECKING_SAVINGS`, every other type → `INVESTMENTS_OTHER`; accounts carry `group`, the dashboard returns `bank_account_groups` (key, label, account ids, active total) beside the unchanged grand total. Bank Accounts page: one table per group with a total row (active accounts); dashboard: one `tbody` per non-empty group with a subtotal. |
| CR-029 | `GET /api/reports/audit/signature-page` takes the same signature parameters as the audit report and returns only that page (same `_signature_page` renderer, same validation), audited `REPORT_GENERATED` `{report: SIGNATURE_PAGE}`. The Reports page shows *Preview signature page* when the options are valid (preview only, Q). |
| CR-030 | Two-column masonry: each chart goes into the currently shorter column (height estimated per chart type and data), one column below 900 px. No dependency. |
| CR-031 | `app_user.dashboard_layout` (migration `0009`, nullable; NULL = default order fiscal_year, budget, review, bank, attention, charts = the 1.4.1 layout). Stored as a comma list in display order, hidden sections prefixed `-`; `services/dashboard_layout.layout_for` drops unknown keys and appends missing ones (visible), so a section added later appears for users with a saved layout. `PUT /api/me/preferences {dashboard_layout: [{key, visible}]}` or `{reset_dashboard_layout: true}`; `/api/auth/me` returns `dashboard_layout` and `dashboard_layout_customized`. UI: *Customize dashboard* panel (checkbox + ↑/↓ per section, *Reset to default*), saves queued like CR-020. The Review summary is listed for Auditors only; ↑/↓ skip sections the user cannot have. Administrator dashboard unchanged (Q7). |
| CR-026 | `packaging/pyinstaller/fmpoc-onefile.spec` (PyInstaller 6.22.3 `--onefile`, console window, `LICENSE` + notices under `legal/`, `build_info.json`). CI `build.yml`: job `windows-exe` on `windows-latest` builds `Freedger-<version>-windows-x64.exe`, then `packaging/windows/smoke_test.ps1` starts the .exe and the portable zip's `.cmd` with an empty `--data-dir` and checks `/api/health`, version, local mode, the web page and the bundled license, stopping the process tree with `taskkill /T`. Job `assemble` merges the Linux job's files with the .exe and writes `SHA256SUMS.txt`; `publish` needs it, so nothing is released unless both Windows smoke tests pass. The same onefile spec also builds and passes the full E2E suite on Linux (`FM_BUNDLE=dist/Freedger`). Not code-signed (accepted, Q3). |
| CR-027 | `packaging/linux/install.sh`, published on every release. Wrapped in `main()` so a truncated download never runs partially. Release lookup with the public GitHub API, no token, no jq: `releases/latest` (never a pre-release or draft) for production; the newest non-draft pre-release tagged `v*-test.N` from `releases?per_page=30` for test (parsed from the API's pretty-printed JSON with awk; verified against the live API). `auto` = production if ≥ 1.5.0 else test + notice (Q4). `--version` is validated (`vX.Y.Z[-test.N]`) and skips the API. Downloads refuse empty files and HTML pages; the package and `install-server.sh` must be listed in and match `SHA256SUMS.txt`; then the release's own `install-server.sh` runs unchanged. Port: `--port`, else the one in `/var/lib/fmpoc/config.toml` (install-server.sh uses it for its health check), else 8765. Tests: `test_v150_install_sh.py` (fake API/download server; install-server.sh replaced by a stub; `FREEDGER_TEST_NONROOT` is a test-only switch). |
| License | **AGPL-3.0-only** (product owner, 2026-10-01). `LICENSE` (FSF text), `THIRD-PARTY-NOTICES.txt` generated by `scripts/third_party_notices.py` from the installed closure of `backend/requirements.txt` (+ colorama, Windows only), the npm production tree and the CPython license; `--check` in CI compares the inventory (name, version, license). Transitive Python dependencies are pinned in `requirements.txt` so the packages match the notices. All bundled licenses (MIT, BSD, ISC, Apache-2.0, PSF, MIT-CMU) are compatible with AGPL-3.0. Section 13: `fmpoc/legal.py` — `/api/system/status` and `/api/system/version` return `license`, `license_name`, `source_url` (repository tree at the build commit from `build_info.json`); `GET /api/system/legal/license|notices` (public, text/plain) serves the bundled files; links on the sign-in page, My Account and System/About. Packages: both files at the package root (portable, Docker `/opt/fmpoc`), `legal/` inside the .exe. |
| CR-032 | `.row.fields` aligns fields to the top so a hint under one field no longer shifts its neighbour's input. |

**v1.4.0 / v1.4.1 change requests CR-016 … CR-025 (product owner, 2026-09-29).** Decisions were agreed item by item
before implementation (plan: project doc `claude/freedger-plan-1.4.md`). 1.4.0 = CR-017/019/021/022; 1.4.1 = CR-016,
CR-018 (TOTP), CR-020, CR-023 … CR-025. Passkeys (part of CR-018) are deferred to 1.6.

| CR | Decision / implementation |
|---|---|
| CR-016 (1.4.1) | `services/signatures.py`: built-in default wording (plan text), `normalize` (trim, ≤ 3000 chars, only `{FY}` `{ORG}` `{FYE}` — anything else in braces is a 422 listing the unknown names), `render`, saved wordings in `signature_template` (migration `0006`; organization-wide, max 4, identical text returns the existing row, the default cannot be saved as a copy; audited `SIGNATURE_TEMPLATE_SAVED/DELETED`). `GET/POST /api/reports/signature-templates`, `DELETE …/{id}` — any role with `financial.view` (Budget Manager, Budget User, Register User, Auditor), since the wording is report configuration, not financial data. `GET /api/reports/audit` gains `signature_page`, `signature_template_id` (`default` or id), `signature_text` (custom, validated), repeated `signer_id`/`signer_title`: 0–5 distinct active INDIVIDUAL entities, title ≤ 60. The page is the report's last page (`KeepTogether`): "Date" line, wording paragraphs (blank line = new paragraph; text is escaped, never markup), then one 3.4-inch line per signer captioned "Name, Title"; with no signer, three blank "Name and title" lines. The `REPORT_GENERATED` audit event records the wording source and signer count. Close report unchanged (Q12). |
| CR-020 (1.4.1) | `GET /api/dashboard/charts?fiscal_year_id=` (`financial.view`), `services/charts.py`. Data = ACTIVE transactions, live allocations to the year's budgets, **Budget 0 excluded** (so transfers never appear), children rolled up into their parent budget (same actuals as the Budgets page). Months = calendar months clipped to the FY dates; allocations dated outside the FY count in the pies/budget-vs-actual but not in the monthly series; months that have not started (and have no activity) are `null` so lines stop at the current month. Pies: ≤ 7 slices + "Other" (slices < 3 % fold into Other). Budget vs actual: expense parent budgets except Rejected/Inactive. Balances: register-enabled active accounts, `balance_cents(as_of=month end)`, primary first, plus a total. Frontend: Recharts 3.10.1 (exact pin), loaded lazily as its own chunk so the rest of the app does not grow (~124 KB gzip on the dashboard only). Colors: the dataviz reference categorical palette, validated (CVD/normal-vision/contrast) against this app's light `#ffffff` and dark `#1b2128` surfaces; income = blue, expenses = orange everywhere, "Other" grey; three light-mode slots are < 3:1 contrast, so every chart has a legend with values and a *Show data table* view. Chart choice per user: `app_user.dashboard_charts` (migration `0007`, comma list, NULL = default three), `PUT /api/me/preferences {dashboard_charts: [...]}`, returned by `/api/auth/me`. Placed below the Attention section. |
| CR-018 (1.4.1) | `services/mfa.py` + `routers/auth.py`. Policy `mfa.required(settings)` = server mode (product owner Q4). `AuthSession.mfa_pending` (`VERIFY`/`ENROLL`, migration `0008`) marks a password-accepted session: `deps._load` gives it no roles/permissions, `auth_ctx` answers `401 MFA_REQUIRED`, the new `pre_mfa_ctx` admits it for `/api/auth/me`, logout and `/api/auth/mfa/*`; pending sessions live 10 min. `POST /api/auth/mfa/verify {code, trust_browser}` (TOTP or recovery code) and `…/enroll/confirm` in ENROLL state replace the pending session with a new full session (`auth.complete_mfa`, audited `LOGIN` with `mfa: totp/recovery_code/enrolled/trusted_browser`; the password step is audited `LOGIN_PASSWORD_ACCEPTED`). Enrollment: `…/enroll/start {current_code?}` stores an encrypted pending secret (15 min) and returns the key (grouped), `otpauth://` URI (issuer "Freedger (<organization>)") and a server-rendered QR SVG data URI; `…/enroll/confirm {code}` activates it and returns 10 recovery codes (old codes deleted; on a change, trusted browsers revoked). Replacing an authenticator needs a current code or recovery code (Q-plan). Replay: `user_mfa.last_step`. Trusted browsers (Q6): `trusted_device` + cookie `fm_trusted` (30 days); revoked by password change/admin password reset/MFA change/reset/disable. `GET /api/me/mfa`, `POST /api/me/mfa/trusted-browsers/{id}/revoke`, `…/revoke-all`, `POST /api/me/mfa/disable` (local mode only, needs a code). Admin `POST /api/users/{id}/reset-mfa {reason}` (Q5) deletes the MFA rows, revokes trusted browsers and all sessions; `GET /api/users` adds `mfa_enabled`. Host CLI `FinancialManagementPOC reset-mfa --user NAME [--reason] [--data-dir]` (audited with no actor, `via: host_cli`). Initialization in server mode leaves the first Administrator's session in ENROLL. Existing sessions at upgrade stay valid (`mfa_pending` NULL); MFA applies from the next sign-in ("required on next login"). UI: `MfaGate` (full-screen verify/setup), `SecuritySection` in My Account, *Two-step* column + *Reset two-step* on Users. Passkeys: 1.6. |
| CR-023/024/025 (1.4.1) | **Supersedes BR-092** ("POC backup/restore is deferred") and the About-page notice (product owner). `services/backup.py` + `routers/backup.py`; format and steps in docs/backup-restore.md. Decisions: passphrase-encrypted always (Q2; AES-256-GCM records, scrypt, header/order/end authenticated); config.toml excluded (Q13); in-app reload instead of a process restart (Q3: `engine.dispose()`, directory swap with `os.replace`, `upgrade_database`, new engine/session factory/key/limiter on `app.state`; request handlers read `app.state.session_factory` per request); maintenance flag makes other `/api` calls answer `503 MAINTENANCE` during the swap; safety copy `pre-restore/` (latest only) with automatic rollback (Q14); all sessions and trusted browsers revoked; `SYSTEM_RESTORED` audited in the restored DB (actor by name only - the restoring user belongs to the replaced data). Backup and restore run as background jobs with polled status (`/api/system/backups/{job}`, `/api/system/restore/jobs/{job}` - the random job id is the capability, needed because sessions end mid-restore); finished backup files kept 1 h in `backup-work/`. Upload: `POST /api/system/restore/uploads {size}` → `PUT …/{id}?offset=` parts ≤ 20 MB (body-limit exception for that route only; retried parts accepted, gaps 409) → `POST …/{id}/start {passphrase, password, confirm:"RESTORE"}`. Before initialization the restore endpoints are open with the pre-auth double-submit CSRF token (like the wizard); afterwards Administrator + password re-entry + typed RESTORE (password failures count in the sign-in rate limiter, audited `BACKUP_DENIED`/`RESTORE_DENIED`). Extraction allowlists `manifest.json`, `database/fmpoc.sqlite3`, `secrets/portable-encryption-key.json`, `attachments/**` (regular files, safe names; anything else refuses the backup); every file's SHA-256 must match the manifest; the key must match the DB's `key_check`; an unknown (newer) Alembic revision is refused. Backups are accepted from 1.4.1 on. `restore_max_mb` setting (default 20480). |
| CR-017 | `services/documentation.classify` gains the reason test: a no-attachment mark with a non-blank reason (parent or allocation) counts as documented and is not listed; a mark without a reason is still `NO_ATTACHMENT_MARKED`. One function feeds the FY review list, the closure warnings, the dashboard count and the audit/close PDF review page, so all four change together (product owner Q9). The PDFs still print the mark and reason on each transaction. **Supersedes** the v1.2.1 CR-005 wording "a parent mark is listed as 'no attachment'" and the CR-003 note that transfers appear as marked items: transfers carry the system reason "Internal transfer between accounts" and are therefore no longer listed. |
| CR-019 | Budget read model adds `above_budget` (income rows and the income summary, also the budget selector options) = actual − amount when an income budget received more than budgeted; `over_budget` is false for income. UI and PDFs show "+$X above budget" in green instead of a negative Remaining. Closure warning `OVER_BUDGET` now considers expense budgets only — a deliberate change to baseline BR-014 at the product owner's request. |
| CR-021 | `GET /api/dashboard` adds `bank_accounts_total` (sum of the active accounts listed); shown as a Total row. |
| CR-022 | `GET /api/system/version` (any signed-in user): version, build info, mode — no network details. `GET /api/system/about` now returns `bind_host`/`port` only to Administrators. Build info comes from `fmpoc/build_info.json`, written by the CI build job (version, branch, short commit, run number, build time) and bundled in the portable and PyInstaller packages; without it the UI shows "Development build". My Account has an About section; System/About shows the same details plus the bind address. |

**v1.3.0 change requests CR-007 … CR-015 (product owner, 2026-09-29).** Decisions were agreed item by item before
implementation (plan: project doc `claude/freedger-plan-1.3.md`).

| CR | Decision / implementation |
|---|---|
| CR-007 | `attachment.document_type` ∈ APPROVAL, AUDIT_SIGNOFF, UNSPECIFIED (+ CLOSE_REPORT, system generated). Approve → `APPROVAL_DOCUMENT_REQUIRED` unless an Approval document or `fiscal_year.approval_no_attachment`; with only the mark the approval confirmation shows `APPROVAL_NO_ATTACHMENT`. Close blockers: `NO_AUDIT_SIGNOFF` (replaces the v1.1 "any attachment" rule), `APPROVAL_DOCUMENT_MISSING` (no document and no mark); warning `APPROVAL_NO_ATTACHMENT` (mark set). Budget Managers re-type documents while the year is open (`POST /api/attachments/{id}/document-type`, audited `ATTACHMENT_TYPE_CHANGED`); an Approval upload/re-type clears the mark (`FY_APPROVAL_NO_ATTACHMENT_CLEARED`). Mark endpoint `POST /api/fiscal-years/{id}/approval-no-attachment`. Existing FY attachments are migrated to UNSPECIFIED. Note: this deliberately changes baseline BR-013 ("at least one supporting attachment") at the product owner's request. |
| CR-008 | `build_audit_report(layout="close")`: title → Fiscal Year Review → FY documents (Approval, Audit Signoff, other; system-generated documents excluded) → budgets → transactions. `GET /api/reports/fy-close`. Closing generates it inside the closing transaction and stores it with `store_system_fy_document` (not removable/re-typable); on failure the closure is rolled back and the file removed. Audit report: FY documents section removed (product owner Q5). For a closed year the review page states when/by whom it was closed instead of listing blockers. |
| CR-009 | `allocationLabel` (UI) / `allocation_label` (PDF): allocation entity, else the transaction's non-system entity, then the budget label as shown in the UI. |
| CR-010 | `PendingFiles` in the transaction form (transaction + each split allocation); client-side type/size pre-check; uploads after the save response, allocation ids matched (existing by id, new in order); failures listed in a result dialog. No backend change was needed (parent and child uploads were never mutually exclusive); regression tests cover both orders. |
| CR-011 | (a) `GuardedForm` wraps every form: a ref blocks re-entry synchronously, a `fieldset disabled` locks the controls, the submit button reads "Saving…"; the confirmation dialog's continue button is single-shot. (b) `request_key` (16–64 chars, generated with `crypto.getRandomValues` so it also works over plain-HTTP LAN addresses) on transaction/zero-VOID/transfer creation; `services/idempotency.claim` inserts the key first (taking SQLite's write lock) and a repeat returns the stored result; the key row commits atomically with the records, so a failed/confirmation-required attempt does not consume it. Tested with 4 concurrent submits. (c) `POSSIBLE_DUPLICATE` confirmation on create: ACTIVE, same account, date, type, total and parent entity. (d) `DUPLICATE_CHECK_NUMBER` hard block (409) against any record in the account, VOID included; numeric numbers compare without leading zeros. (e) `POST /api/transactions/{id}/void-check-number` (Register User; VOID only; clear or change; reason required; duplicate check applies; stamped note on the record; audit `TRANSACTION_VOID_CHECK_NUMBER_CORRECTED`; closed FY immutable). Pre-1.3 duplicates are left unchanged and listed by the check review. |
| CR-012 | `services/checks.review`: per register account, numeric check numbers of all records; gaps between lowest and highest; minus `check_number_acknowledgement` ranges; gaps > 25 numbers as one range item; computed on the fly. `GET /api/check-review`, `POST /api/check-review/acknowledge` (Register User, note required, only currently-missing numbers, audited). FY closing warning `MISSING_CHECKS` for gaps whose neighbouring checks fall in the year. UI: section in the Register's Fiscal Year reviews panel for the selected account with Enter transaction / Record as VOID check (pre-filled) / Confirm not missing. |
| CR-013/014 | Fixed-height shell (`100dvh`), content area scrolls, nav scrolls independently. Collapsible nav with inline SVG icons (no dependency), names kept as `aria-label`/tooltip, active page highlighted in both states. The collapsed state is stored per user server-side (`app_user.nav_collapsed`, `PUT /api/me/preferences`) like the theme — the SPA keeps its rule of never using browser storage (AC-SEC-006 test). Screens < 800 px always show the icon rail. |
| CR-015 | `.register-sticky` block (sticky inside the scrolling content) + sticky table headings positioned from the measured header height; the reviews panel opens below the pinned block; compact spacing (~⅓ of a 1280×800 screen). Not pinned below 800 px wide or 650 px tall. |

**v1.2.1 corrections (product owner review of 1.2.0).** These supersede the corresponding 1.2.0 rows below.

| CR | Correction | Implementation |
|---|---|---|
| CR-002 | Audit report layout | Page 1 title page; page 2 Fiscal Year Review introduction (activity summary per account, closure readiness, documentation review with transaction numbers); pages 3–n budgets; then ≥ 1 page per transaction: the seven headline fields (Transaction date, Entity, Transaction type, Amount, Description, Clear Date, Notes) at the top, secondary detail (status, check #, entry, void/transfer/documentation info, allocations) in small print, then every attachment **rendered** beneath within the Letter page width. Implementation: one reportlab build; images drawn with `drawImage`; each PDF attachment page reserves a box of its aspect ratio (`_Block`) and is merged afterwards with `pypdf.merge_transformed_page` (vector, scaled, rotation normalised) so it can sit directly under the transaction details. A box is shrunk to fit the rest of the current page when ≥ 60 % of full size fits, otherwise it starts the next page at full width. Description = the allocation description (numbered list with amounts for splits). The transaction index was removed; the FY supporting documents remain as a final section. Only the audit report changed (the entity report/CSV are as in 1.2.0, per the product owner). |
| CR-003 | Transfer entity | `POST /api/transfers` accepts optional `entity_id` (active, non-hidden entity). It is stored as the parent entity and allocation entity of both legs and names the organization in the descriptions `Transfer to|from <mask> for <Entity>`; without it the workspace (organization) name is used as in 1.2.0. Legs stay locked together (clarified by the product owner: no change). |
| CR-005 | Split documentation rule | Product-owner rule, implemented verbatim in `services/documentation.py: classify`: if the parent has an attachment or the parent no-attachment mark, the transaction is not reviewed for missing documentation (a parent mark is listed as "no attachment"); otherwise every child needs an attachment or its **own** no-attachment mark (migration `0004` adds `no_attachment`, `_reason`, `_set_at`, `_set_by_user_id` to `transaction_allocation`). Any child with neither → "Missing attachment"; all children documented but some only by a mark → "no attachment" item. An unsplit transaction is the same rule with one child. Changing allocation marks is not a financial edit (no cleared-edit confirmation). Uploading to an allocation clears that allocation's mark (`ALLOCATION_NO_ATTACHMENT_CLEARED`); uploading to the transaction clears the parent mark. |

**CR-002 … CR-006 (requested by the product owner, v1.2.0)**

| CR | Feature | Key decisions |
|---|---|---|
| CR-002 | Reports: End of Year Audit PDF; Entity activity | PDF built server-side (reportlab + pypdf) so image **and** PDF attachments are physically placed right after their transaction when printed. Transaction set = dated within the FY **or** allocated to its budgets (cross-FY), grouped by account then date; VOID included by default (option). Each transaction starts a new page; each PDF attachment gets a caption page with SHA-256 then its own pages; a PDF that cannot be parsed is replaced by a placeholder identifying the stored file. All user text is XML-escaped before reportlab markup (prevents `<img src=…>` file inclusion). Entity report credits split-deposit allocations to their own entities, groups transfers separately and excludes them from totals; CSV cells are protected against formula injection. Report generation writes a `REPORT_GENERATED` audit event. |
| CR-003 | Transfers | Two linked ACTIVE transactions (`transfer_group`): withdrawal in source, deposit in destination, same date/clear date/amount. Allocated to protected **Budget 0** of the FY covering the date (non-budget activity, no budget impact; closed FY refused; ambiguous overlap requires an explicit FY). Descriptions generated as `Transfer to|from <10-char masked number of the other account> for <workspace name>`. No entity. Void either leg → both voided. Only Clear Date, Notes and the no-attachment flag are editable per leg (banks may clear on different days); otherwise void and re-enter. Transfers are marked "no attachment will be provided" (reason "Internal transfer between accounts") so they appear once in the documentation review as marked items. |
| CR-004 | "No attachment will be provided" | Transaction-level flag + optional reason + who/when (migration 0003). UI shows a warning dialog before the box can be ticked. Setting/clearing it is not treated as a financial edit (no cleared-edit confirmation). Uploading an attachment to the transaction or one of its allocations clears the flag automatically (audited `TRANSACTION_NO_ATTACHMENT_CLEARED`). |
| CR-005 | Documentation review warnings | Applies to ACTIVE transactions with an allocation in the FY. Single allocation: warning when neither the transaction nor its allocation has an attachment. **Split: warning when (parent has 0 attachments and not every child has one) or (no child has one)** — i.e. every child documented is always sufficient; a parent document is sufficient only together with at least one child document. This follows the request text literally; the rule lives in one function (`services/documentation.py: split_is_documented`) if a looser reading (parent document alone suffices) is preferred. Marked transactions are listed as "no attachment" instead of "missing". Warnings appear in closure readiness, on the FY page, the dashboard and the audit report — never as blockers. VOID transactions are not listed. |
| CR-006 | Searchable entity picker | Accessible combobox (type to filter by name or Entity Number, arrow keys/Enter, "— none —"), used for the payee/payer and split-deposit allocation entities. |

## 2. Other implementation choices

- **Money** is stored as integer cents (SQLite has no exact decimal); API uses decimal strings with ≤2 places.
- **Confirmation protocol**: warning conditions (FY gap/overlap, duplicate entity, cross-FY, no covering FY, cleared
  edit, type change, Budget 0) return `409 CONFIRMATION_REQUIRED` with structured warnings; the client resubmits
  with `confirmations: [codes]`. The UI shows a blocking dialog with an explicit checkbox. Approve/close/void use
  explicit `confirm_*` booleans; the void dialog additionally requires typing `VOID`.
- **Ambiguous overlap (BR-008)**: when two open FYs cover the date the API rejects allocations lacking an explicit
  `fiscal_year_id` (`AMBIGUOUS_FISCAL_YEAR`), so the backend itself never chooses.
- **Split deposits**: parent entity becomes `Multiple` when allocation entities differ; a single-entity deposit keeps
  that entity. Withdrawal allocations inherit the payee; a different allocation entity is rejected.
- **Invoice numbers** are accepted on Withdrawal allocations only (docs/01 §10); check numbers on Withdrawals only.
- Fiscal Years are editable (identifier/dates, with continuity checks) only while Draft; budget codes are immutable
  after creation (name/amount/notes editable).
- A guard prevents disabling/demoting the last active Administrator.
- Theme preference changes are not audited (preference, not business data). All other mutations are audited.
- The login rate limiter per client address is in-process (the per-account count of failed attempts is in the database, 1.8.0); run one application process per data directory.
- Frontend routing uses a small built-in History-API router (removes the vulnerable `react-router` dependency chain).

## 3. Known limitations / not verified in this environment

| Item | Status |
|---|---|
| AC-DEP-001 Windows build | Windows artifacts are produced (`build_windows_portable.sh` built `FinancialManagementPOC-windows-x64.zip`; `build_windows.ps1` + CI job for PyInstaller) but could not be executed on Windows here → *Manual Verification Required* (procedure in manual-verification.md; CI smoke test provided). |
| AC-DEP-003 browser opening | Loopback binding verified; automatic browser opening requires a desktop session → manual. |
| AC-DEP-006 cross-OS move | Verified by relocating a data set to a new installation directory (same OS) and decrypting; the key/DB format is OS-neutral. Windows↔Linux transfer → manual. |
| Standard Dockerfile | Not built here (Docker Hub blocked by network policy); the bundle-based image was built and run in server mode. |
| Accessibility | Text + icon status, labelled controls, keyboard-closable dialogs; no formal WCAG audit. |
| Scale | SQLite single node; PostgreSQL is a documented Day-2 option (SQLAlchemy keeps the path open). |
