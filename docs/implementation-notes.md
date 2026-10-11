# Implementation notes

Authority order followed: business rules (03) → security (04) → acceptance criteria (08) → domain/workflow/
architecture/database (02, 05, 06, 07) → product requirements (01, 09). No specification file was modified.

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
`/payments?txn=<id>` shows the transaction locked in a disabled fieldset). Register: *New payment* (toolbar) and
*Create payment…* (detail). The memo autocomplete sets the cursor in a layout effect (was an animation frame - typing
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
stable, `vX.Y.Z-test.N` prerelease = test; numeric version order; notes cut at the install footer the build adds;
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
