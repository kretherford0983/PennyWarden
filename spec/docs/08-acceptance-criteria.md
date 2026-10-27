# 08 — Acceptance Criteria

These criteria are implementation-neutral and are intended to be executable or objectively verifiable wherever practical. IDs are stable references for the traceability matrix and comparative agent evaluation.

## Authentication and RBAC

### AC-SEC-001 — First-run administrator
Given an uninitialized installation, first run permits creation of a Workspace and initial Administrator without shipping a default password.

### AC-SEC-002 — Security-domain separation
An Administrator account cannot simultaneously hold Financial or Auditor roles. An Auditor cannot hold Financial or Administrator roles. A Financial user may hold multiple Financial roles.

### AC-SEC-003 — Admin financial isolation
An Administrator cannot view or call APIs returning Fiscal Years, Budgets, Entities, Bank Accounts, Registers, financial attachments, or other financial data.

### AC-SEC-004 — Auditor read-only access
An Auditor can view all application data, including users, audit logs, inactive entities, rejected budgets and voided transactions, but cannot modify any application data.

### AC-SEC-005 — Unauthorized direct access
A hidden module remains inaccessible through direct URL/API requests when the current role lacks permission.

### AC-SEC-006 — Session security
Authentication uses server-side sessions, HttpOnly cookies, CSRF protection on state-changing operations, server-side authorization, and no browser-localStorage authentication token.

### AC-SEC-007 — Financial Institution maintenance
A Register User can create an Entity flagged Financial Institution but cannot subsequently edit, inactivate, or remove that designation. A Budget Manager can.

### AC-SEC-008 — Account-number reveal
Only Budget Manager can reveal a full bank account number. Reveal creates an audit event that does not contain the plaintext number.

### AC-SEC-009 — SQL injection resistance
Submitting SQL metacharacters or common injection strings such as `' OR 1=1 --` through text/search/filter inputs does not alter query structure, bypass filters, expose additional records, or produce raw SQL errors. Server-side database access remains parameterized.

### AC-SEC-010 — Dynamic query allowlisting
Supplying an unsupported sort field, sort direction, filter field, or other client-controlled structural query value is rejected or mapped to an explicit safe default rather than incorporated into raw SQL.

### AC-SEC-011 — Stored/reflected script content is inert
Saving and subsequently displaying values such as `<script>alert(1)</script>` or HTML event-handler payloads in Entity names, Notes, descriptions, and other user-controlled text never executes script or markup in another user's browser.

### AC-SEC-012 — Server-side validation cannot be bypassed
A direct API request that bypasses or modifies the React client is still rejected when required fields, enum values, date/decimal formats, limits, or domain constraints are invalid.

### AC-SEC-013 — Mass-assignment protection
Adding protected properties such as `is_system`, `created_by`, `locked`, `closed_at`, privileged role fields, derived balance/amount fields, or immutable Bank Account association values to an otherwise valid request does not alter those protected values unless the specific operation explicitly authorizes them.

### AC-SEC-014 — Object-level authorization
Changing object IDs or workspace-scoped IDs in direct API requests does not allow a user to retrieve or mutate records outside the user's authorized domain/scope.

### AC-SEC-015 — Path traversal resistance
Uploading a permitted file with names containing traversal/absolute-path patterns such as `../receipt.pdf`, `..\receipt.pdf`, or an absolute path cannot cause storage outside the configured attachment directory or overwrite application files. The stored name/path is application generated.

### AC-SEC-016 — Disguised attachment rejection
A non-permitted/executable file renamed with `.pdf`, `.jpg`, `.jpeg`, or `.png`, or sent with a forged MIME type, is rejected when server-side content validation determines that the file is not an allowed type.

### AC-SEC-017 — Attachment limit enforced by API
A file larger than 5 MB is rejected by the backend even when uploaded through a direct API request that bypasses browser validation.

### AC-SEC-018 — Safe error response
A deliberately triggered backend validation or unexpected-error path does not return stack traces, raw SQL, database filenames, local filesystem paths, encryption keys, passwords, session values, or other protected internals to the browser.

### AC-SEC-019 — Sensitive values absent from logs
After login, account-number reveal, failed authentication, transaction processing, and representative error paths, application logs and audit records do not contain plaintext passwords, password hashes, session cookies/IDs, CSRF secrets, encryption keys, or full plaintext bank account numbers.

### AC-SEC-019a — Own authenticator key (2.2.0, #327)
Setting up two-step verification with the user's own key accepts a valid Base32 key of at least 16 characters (a note under 32) or an otpauth://totp link; a short or invalid key, an unsupported link, a wrong code, and an own key after a reset marked as a possible compromise are refused; the key is absent from responses, logs and the audit log, and a new set of recovery codes is issued.

### AC-SEC-020 — CSRF rejection
A state-changing request using cookie authentication but lacking the required valid CSRF control is rejected and produces no persisted mutation.

### AC-SEC-021 — Security headers
Packaged application responses include documented anti-sniffing, anti-framing/clickjacking, Referrer-Policy, and Content-Security-Policy protections compatible with normal application operation. HTTPS deployments support appropriate transport-security configuration.

### AC-SEC-022 — No default credentials or production debug exposure
A fresh installation does not ship usable default credentials, and packaged production builds do not expose framework debug consoles or verbose development exception pages.

### AC-SEC-023 — Unsafe shell input is not executable
User-supplied text used by application features cannot inject additional operating-system commands. Implementation review/tests verify that shell commands are not constructed through raw concatenation of user input.

### AC-SEC-024 — Dependency vulnerability checks are reproducible
Repository documentation/build scripts provide repeatable Python and JavaScript dependency-vulnerability checks. The results can be captured during evaluation.

### AC-SEC-025 — Security negative tests are part of the test suite
Automated tests directly exercise backend controls for authorization, input validation, SQL/injection resistance, mass assignment, CSRF, and upload/path safety where practical; security completion is not inferred solely from hidden UI elements.

## Fiscal Years

### AC-FY-001 — Fiscal Year naming
Entering identifier `2028` creates/displays `FY2028`.

### AC-FY-002 — Relative quarters
For a Fiscal Year starting July 1, Q1 is Jul-Sep, Q2 Oct-Dec, Q3 Jan-Mar and Q4 Apr-Jun.

### AC-FY-003 — Consecutive-year normal case
Creating a Fiscal Year beginning exactly one day after the prior Fiscal Year ends produces no gap/overlap warning.

### AC-FY-004 — Gap warning
Creating a Fiscal Year that leaves uncovered dates relative to an adjacent year produces a strong warning and requires explicit Budget Manager confirmation.

### AC-FY-005 — Overlap warning
Creating a Fiscal Year whose date range overlaps another produces a strong warning, presents relevant prior-year readiness information, and requires explicit Budget Manager confirmation.

### AC-FY-006 — Ambiguous overlapping date
If two non-closed Fiscal Years cover a transaction date, transaction entry does not silently choose one; the Register User must choose.

### AC-FY-007 — Copy prior budgets
Fiscal Year creation can copy selected prior-year budgets, including identifiers, names, types, hierarchy, sub-budget structure and prior amounts as Draft starting values.

### AC-FY-008 — Draft accepts transactions
Transactions may be allocated to valid Draft Fiscal Year budgets.

### AC-FY-009 — Approval
Only Budget Manager can approve a Fiscal Year. Approval is irreversible through POC UI and locks all active budgets.

### AC-FY-010 — Closure blockers
Closure is rejected when the Fiscal Year is not Approved, any budget is unlocked, any applicable transaction is uncleared, unresolved FY-review items exist, invalid allocation state exists, or no Fiscal Year attachment exists.

### AC-FY-011 — Closure documentation
At least one valid attachment is required before Fiscal Year closure.

### AC-FY-012 — Closure warning categories
Rejected-budget activity, over-budget activity, reviewed cross-FY allocations, and voided transactions may be shown as warnings. Budget 0 activity alone does not produce a closure warning.

### AC-FY-013 — Closed immutability
After closure, new allocations cannot be posted to that Fiscal Year and existing financial allocations cannot be edited or voided through normal UI/API operations.

## Budgets

### AC-BUD-001 — Automatic Other
Creating a $100,000 parent with no explicit child creates a system-managed Other allocation representing the full $100,000 while the UI presents the parent as the usable budget.

### AC-BUD-002 — Child allocation and Other recalculation
Adding child `01 Travel` for $25,000 to a $100,000 parent results in Other = $75,000.

### AC-BUD-003 — Child total cannot exceed parent
A change that would make explicit children exceed the parent amount is rejected server-side.

### AC-BUD-004 — Zero Other hidden
When explicit children total the full parent amount, Other remains stored but is hidden from normal display and transaction selection.

### AC-BUD-005 — Other reappears
If child amounts later decrease and Other becomes positive, Other becomes visible/selectable again.

### AC-BUD-006 — Parent roll-up not selectable
When explicit sub-budgets exist, the parent budget cannot receive a transaction allocation directly.

### AC-BUD-007 — Display identifier
A child budget with Parent ID `1000`, Child ID `01`, and name `Travel` is displayed as `1000-01 Travel` where standard budget references are shown.

### AC-BUD-008 — Overage allowed
A transaction that causes remaining budget to become negative is accepted if otherwise valid, and the negative remaining value is displayed.

### AC-BUD-009 — Unlock reason
Unlocking an Approved/Locked budget requires a non-empty reason and produces an audit event.

### AC-BUD-010 — Rejected budget
Rejecting a Draft budget sets its allowed amount to zero, preserves historical allocations, prevents normal new allocations, and displays an `X` plus light-red treatment and accessible status.

### AC-BUD-011 — Status indicators
Draft uses `?`/light yellow; Approved+Locked uses closed padlock/light green; Approved+Unlocked uses open padlock/light green; Rejected uses `X`/light red. Status is not communicated by color alone.

## Entities

### AC-ENT-001 — Individual requirement
An Individual cannot be saved without Primary Contact; other contact fields are optional.

### AC-ENT-002 — Organization requirement
An Organization cannot be saved without Organization Name; other contact fields are optional.

### AC-ENT-003 — Register entity display
Individuals display Primary Contact; Organizations display Organization Name.

### AC-ENT-004 — Duplicate warning
Creating a likely duplicate Entity produces a non-blocking warning and allows creation after confirmation.

### AC-ENT-005 — Entity number
Every Entity receives a unique immutable system-generated Entity Number usable to disambiguate duplicate names.

### AC-ENT-006 — Inactivation preserves history
Inactivating an Entity removes it from normal selectors but preserves all historical transaction references.

## Bank Accounts

### AC-BANK-001 — Financial Institution filtering
Bank Account institution selector includes only Entities flagged Financial Institution.

### AC-BANK-002 — Account-number uniqueness
Attempting to create a second Bank Account with the same full account number in the Workspace is rejected even though encrypted ciphertext is randomized.

### AC-BANK-003 — Account-number encryption
Plaintext full account number is not stored in the SQLite account-number field or audit snapshots.

### AC-BANK-004 — Masked display
Normal account display uses a fixed 10-character masked representation, reveals no more than the final four characters, and masks at least half the actual identifier rounded up.

### AC-BANK-005 — Primary account
At most one active register-enabled Bank Account is Primary. Selecting a new Primary atomically clears the old Primary.

### AC-BANK-006 — Register current balance
For a register-enabled account, current balance equals opening balance plus active deposits minus active withdrawals; VOID transactions have zero effect.

### AC-BANK-007 — Wrong-account correction
An existing Register Transaction cannot be moved to another Bank Account. It must be voided and recreated.

### AC-BANK-008 — Uncleared blocks closure
An account with any active uncleared transaction cannot be inactivated.

### AC-BANK-009 — Non-zero balance blocks closure
An account with current balance other than exactly $0.00 cannot be inactivated.

### AC-BANK-010 — Register account final transaction
A register-enabled account can reach closure eligibility only through register activity that results in exactly $0.00; a Budget Manager cannot manually override the calculated balance to zero.

### AC-BANK-011 — Non-register account zeroing
A non-register account must have its manually maintained balance explicitly updated to $0.00 through an audited change before closure.

## Register Transactions and Allocations

### AC-REG-001 — Parent/allocation model
Every transaction has a parent Register Transaction and at least one Transaction Allocation. An unsplit transaction has exactly one allocation.

### AC-REG-002 — Transaction date default
Transaction Date defaults to current date but is user-editable. Entry timestamp records actual creation time and is not user-editable.

### AC-REG-003 — Budget filtering
Deposit allocation selectors show Income budgets; Withdrawal selectors show Expense budgets, subject to explicit Budget 0 system exceptions.

### AC-REG-004 — Cross-FY warning
Selecting a Budget from a Fiscal Year different from the Fiscal Year naturally covering Transaction Date requires confirmation.

### AC-REG-005 — Missing natural Fiscal Year
When no Fiscal Year covers Transaction Date, the UI warns, presents the closest configured Fiscal Year without silently treating it as correct, and creates a pending Fiscal Year review when saved with such an allocation.

### AC-REG-006 — Reviewed intentional cross-FY
A reviewed intentional cross-FY allocation remains valid and no longer appears as unresolved.

### AC-REG-007 — Split withdrawal
A split withdrawal uses one parent payee; child allocations cannot independently change Entity but may vary budget, invoice, description, amount, notes and attachments.

### AC-REG-008 — Split deposit
A split deposit parent uses hidden Multiple entity and child allocations may use different Entities and Budgets.

### AC-REG-009 — Derived parent amount
For allocations $600 and $400, parent transaction total is $1,000. Changing the second to $500 changes parent total to $1,100.

### AC-REG-010 — Balance counted once
A $1,100 split withdrawal decreases bank balance by exactly $1,100, not by parent plus children.

### AC-REG-011 — Budget allocation totals
Each child allocation affects only its selected budget; parent roll-up values derive from child activity.

### AC-REG-012 — Cleared edit confirmation
Editing a cleared transaction in an open Fiscal Year requires blocking confirmation before save and creates an audit record.
2.1.2 (#344): a save that changes nothing is accepted without the confirmation and creates no audit record.

### AC-REG-013 — Transaction type change
Changing transaction type uses a protected confirmation flow and invalid/incompatible allocations are reselected/revalidated before save.

### AC-REG-014 — No hard delete
No Register Transaction can be hard deleted through the application.

### AC-REG-015 — Void reason
Voiding requires a non-empty reason and irreversible confirmation.

### AC-REG-016 — Void financial effect
After void, transaction remains visible as VOID but contributes zero to bank balance and budget actuals.

### AC-REG-017 — Void irreversibility
A VOID transaction cannot be returned to ACTIVE through normal UI/API.

### AC-REG-018 — Void attachments
Existing attachments remain; additional supporting attachments and notes may be added after void without changing financial fields.

### AC-REG-019 — Zero-dollar void
A zero-dollar transaction may be created only as VOID for accountability, requires a void reason, and uses protected Budget 0 automatically.

## Attachments

### AC-ATT-001 — Allowed formats
PDF, JPG/JPEG and PNG files up to 5 MB each are accepted.

### AC-ATT-002 — Rejected formats/size
Unsupported types and individual files larger than 5 MB are rejected.

### AC-ATT-003 — Multiple attachments
A supported owner may contain multiple attachments and the UI permits navigation among them.

### AC-ATT-004 — Storage names
Uploaded files use generated storage identifiers rather than trusting user filenames as storage paths.

## Audit

### AC-AUD-001 — Create snapshot
Creating an auditable record writes before = null and an after snapshot.

### AC-AUD-002 — Update snapshot
Updating an auditable record stores complete sanitized before/after representations sufficient to identify changed values.

### AC-AUD-003 — Atomicity
If audit persistence fails, the associated auditable business mutation is rolled back.

### AC-AUD-004 — Append-only application behavior
No application role can edit or delete Audit Events.

### AC-AUD-005 — Sensitive sanitization
Audit snapshots never contain plaintext bank account numbers or encryption keys.

## Packaging and Deployment

### AC-DEP-001 — Windows self-contained build
A supported Windows build starts without separately installing Python, Node.js, SQLite, Docker, or another database service.

### AC-DEP-002 — Linux self-contained build
A supported Linux build starts without separately installing Python, Node.js, SQLite, Docker, or another database service.

### AC-DEP-003 — Local loopback
Local mode binds to loopback by default and opens the browser where the environment supports it.

### AC-DEP-004 — Server mode
Server mode can bind to a configured network interface while retaining the same application/domain implementation.

### AC-DEP-005 — Optional container
A Docker-based server deployment may be provided, but native deployments do not require Docker.

### AC-DEP-006 — Portable encrypted data
With the application stopped, moving the persistent data set including database, attachments and portable encryption secret to a compatible installation on another supported OS preserves the ability to decrypt authorized account-number values.

## Benchmark v1.1 Acceptance Criteria

### Initialization
- **AC-INIT-001:** Fresh uninitialized launch automatically presents Initialization Wizard.
- **AC-INIT-002:** Wizard requires Workspace Name, Administrator Username, Administrator Email, Password, and Password Confirmation.
- **AC-INIT-003:** Completion creates Workspace, initial Administrator, Administrator role assignment, roles/permissions, portable encryption key, and required system seed records.
- **AC-INIT-004:** Initial Administrator can log in immediately.
- **AC-INIT-005:** Initial Administrator accesses Admin navigation/screens/dashboard without Unauthorized errors.
- **AC-INIT-006:** Initial Administrator appears in User List with Administrator role.
- **AC-INIT-007:** Initial Administrator remains unable to access financial modules.
- **AC-INIT-008:** Merely creating an empty database does not suppress Initialization Wizard.

### Self-Service Password Change
- **AC-AUTH-SELF-001:** Every authenticated active user can change their own password using the correct current password.
- **AC-AUTH-SELF-002:** Incorrect current password rejects the change.
- **AC-AUTH-SELF-003:** Password-policy violations are rejected.
- **AC-AUTH-SELF-004:** Old password stops authenticating and new password succeeds after change.
- **AC-AUTH-SELF-005:** Other active sessions are invalidated after successful change.
- **AC-AUTH-SELF-006:** Audit records the event without password values.
- **AC-AUTH-SELF-007 (2.2.0, #343):** The password requirements are visible beside the new-password fields before typing, come from the server, and are ticked off (red → green with a check mark, "met"/"not met" for screen readers) as they are met, including new password = confirmation; a refused change leaves every field as typed.
- **AC-AUTH-SELF-008 (2.2.0, #343):** After a failed sign-in the password field is empty and focused and the username is kept.

### Light/Dark Theme
- **AC-UI-THEME-001:** Authenticated user can switch Light/Dark modes.
- **AC-UI-THEME-002:** Preference persists across navigation, logout, and subsequent login.
- **AC-UI-THEME-003:** Core POC UI remains readable and functional in both modes.

### Draft Fiscal Year Visibility and Use
- **AC-FY-VIS-001:** Newly created Draft Fiscal Year immediately appears in Fiscal Year list.
- **AC-FY-VIS-002:** Its detail screen loads and does not return Fiscal Year not found.
- **AC-FY-VIS-003:** It appears in Budget Fiscal Year filters.
- **AC-FY-VIS-004:** It appears in Create Budget Fiscal Year selection.
- **AC-FY-VIS-005:** Budget Manager can create a valid budget against it.
- **AC-FY-VIS-006:** Register User can save a valid allocation against an eligible Draft-year budget.
- **AC-FY-VIS-007:** Selectors display Fiscal Year identity; status alone is never the option label.
- **AC-FY-VIS-008:** Approval preserves identity, route, and authorized visibility.
- **AC-FY-VIS-009:** Closed Fiscal Years remain accessible historically/read-only but unavailable for new allocations.
- **AC-FY-VIS-010:** APIs supplying general and Draft-eligible Fiscal Year selectors do not filter exclusively to APPROVED.
- **AC-FY-VIS-011:** Draft status alone cannot cause an existing Fiscal Year ID to return not-found.
