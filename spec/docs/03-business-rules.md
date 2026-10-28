# Financial Management Application — Business Rules

**Status:** Draft baseline for review  
**Purpose:** Authoritative behavioral rules for the POC. These rules override assumptions based on conventional accounting software behavior.

## BR-001 — No Hard Deletes

Application-managed business/financial records are never physically deleted through normal UI/API operations. User-facing deletion actions must map to the domain-appropriate inactive, rejected, closed, or void state.

## BR-002 — High-Level Security Domains Are Mutually Exclusive

A User account belongs to exactly one of Administrator, Financial, or Auditor domains. Financial users may combine Financial subroles. Administrator and Auditor roles may not be combined with Financial roles or with each other on the same account.

## BR-003 — Administrators Cannot Access Financial Data

Administrators may manage users/roles and view Audit Logs but may not view or modify Budgets, Fiscal Years, Entities, Bank Accounts, Register Transactions, financial Attachments, or other financial content.

## BR-004 — Auditors Are Global Read-Only Users

Auditors may view all application data, including Users, roles, inactive Entities, rejected Budgets, voided Transactions, Attachments, and Audit Logs. They may not modify data in the POC.

## BR-005 — Fiscal Year Naming

The system prepends `FY` to the user-entered Fiscal Year identifier. User entry `2028` displays as `FY2028`.

## BR-006 — Fiscal Years Normally Must Be Consecutive

When creating/editing a Fiscal Year, the system compares it to adjacent Fiscal Years. The normal next Start Date is the prior Fiscal Year's End Date plus one day. A gap requires a strong warning and explicit Budget Manager confirmation.

## BR-007 — Fiscal Years Normally Must Not Overlap

Date overlap with another Fiscal Year requires a strong warning and explicit Budget Manager confirmation. The warning should provide relevant status/closure-readiness information for the overlapping year. Intentional overlap is permitted for organizational fiscal-calendar changes.

## BR-008 — Ambiguous Overlap Cannot Be Silently Resolved

If more than one non-closed Fiscal Year covers a Transaction Date, the application must not silently choose one for budget allocation. The Register User must explicitly choose the intended Fiscal Year.

## BR-009 — Fiscal Quarters Are Relative to Fiscal Year Start

Q1, Q2, Q3, and Q4 are four consecutive three-month periods beginning on the Fiscal Year Start Date.

## BR-010 — Draft Fiscal Years May Receive Transactions

A Draft Fiscal Year and its valid Draft Budgets may receive Transaction Allocations. Approval is a governance state and is not a prerequisite for financial classification.

## BR-011 — Fiscal Year Approval Is Irreversible Through UI

Only a Budget Manager may approve a Fiscal Year. Approval cannot be reversed through the POC UI and automatically locks all active Budgets for that Fiscal Year.

## BR-012 — Fiscal Year Closure Is Irreversible and Immutable

Only a Budget Manager may close a Fiscal Year. Closed Fiscal Years cannot be reopened through the POC UI. Their Budgets and financial allocations are immutable.

## BR-013 — Fiscal Year Closure Blockers

Closure is prohibited when any required condition fails, including:

- Fiscal Year is not Approved.
- Any Budget is unlocked.
- Any applicable Register Transaction remains uncleared.
- Any applicable Fiscal Year review item remains unresolved.
- Invalid/incomplete allocation state exists.
- No Fiscal Year supporting Attachment exists.

## BR-014 — Fiscal Year Closure Warnings

Conditions such as rejected-budget activity, over-budget activity, reviewed cross-FY allocations, and voided transactions may warn without necessarily blocking closure. Budget 0 activity is valid and is not inherently a closure warning.

## BR-015 — Closure Requires Supporting Documentation

At least one valid Attachment is required on a Fiscal Year before it can be Closed.

## BR-016 — Every Parent Budget Has System-Managed Other

Every parent Budget has a system-managed `Other` child record.

## BR-017 — Other Is Calculated

`Other = Parent Amount - SUM(explicit sub-budget amounts)`.

Users cannot manually edit the `Other` amount.

## BR-018 — Child Budgets Cannot Exceed Parent

The sum of explicit sub-budgets may not exceed the parent amount. Attempts must be rejected server-side.

## BR-019 — Zero Other Is Hidden

If calculated `Other` equals `0.00`, it remains stored but is hidden from normal budget displays and Transaction selection.

## BR-020 — Parent Selection Depends on Hierarchy

If `Other` is the only child, the UI may present the parent as the simple selectable Budget while the backend preserves a leaf-allocation representation. Once explicit sub-budgets exist, the parent is roll-up only and cannot receive Transaction Allocations directly.

## BR-021 — Budget Identifiers

Explicit sub-budgets display as `ParentCode-SubBudgetCode`. A simple budget with no explicit sub-budget displays as its Parent Code.

## BR-022 — Budget Overage Is Allowed

A Budget reaching or exceeding its amount never blocks further Transaction Allocation. Remaining may become negative and must be visible for reporting/review.

## BR-023 — Approved Budgets Lock

Approval of a Fiscal Year locks its active Budgets. Locked Budgets cannot be edited.

## BR-024 — Unlock Requires Budget Manager and Reason

Only a Budget Manager may unlock an Approved Budget. Unlocking requires a reason and creates an Audit Event.

## BR-025 — Rejected Budgets Preserve History

A rejected Budget has an allowed amount of zero, remains historically visible, and retains existing Transaction Allocations. Existing allocations are not automatically reassigned. New normal allocations to rejected Budgets are prohibited.

## BR-026 — Budget Historical Use Prevents Disappearance

Once a Budget has any current or historical Transaction Allocation, it must remain in historical storage even if later inactive/rejected and even if allocations are subsequently changed or transactions voided.

## BR-027 — Budget Copy Carries Forward Draft Structure and Amounts

When creating a Fiscal Year by copying selected Budgets from a prior Fiscal Year, copied Budgets carry forward code, name, type, hierarchy/sub-budget structure, and prior amount as the starting Draft amount. The Budget Manager may modify the copied Draft before approval.

## BR-028 — Entity Required Names

Individual Entity requires Primary Contact/Person Name. Organization Entity requires Organization Name. Other contact fields are optional.

## BR-029 — Entity Register Display Name

Register displays Individual Entities by Primary Contact/Person Name and Organization Entities by Organization Name.

## BR-030 — Entity Duplicates Are Non-Blocking

Possible duplicate Entities generate a warning and display likely existing matches. The user may create the new Entity anyway. The system-generated immutable Entity Number distinguishes duplicates.

## BR-031 — Financial Institution Permissions

Register Users may create Entities flagged Financial Institution. Once an Entity is a Financial Institution, only a Budget Manager may edit, remove the Financial Institution designation, or inactivate it. Budget Managers may create/edit/inactivate Financial Institution Entities.

## BR-032 — Ordinary Entity Maintenance

Register Users and Budget Managers may create, edit, and inactivate ordinary non-Financial-Institution Entities, subject to audit rules.

## BR-033 — Inactive Entities Preserve History

Inactive Entities remain associated with historical transactions but are excluded from normal active selectors. Controlled restoration is permitted and audited. Financial Institution restoration/editing remains Budget Manager-only.

## BR-034 — Multiple Entity Is Protected

The hidden `Multiple` Entity is seeded at initialization, cannot be selected manually, and cannot be edited/inactivated by end users.

## BR-035 — Full Bank Account Number Is Unique

A full Bank Account number must be unique within the Workspace. Uniqueness is enforced using a keyed non-reversible fingerprint, not encrypted ciphertext comparison.

## BR-036 — Bank Account Number Is Encrypted

Full Bank Account number is encrypted at rest using application-level authenticated encryption. The portable encryption key is stored separately from SQLite and is not bound to a specific OS/machine.

2.2.0 (#319): every restore, full or partial, installs the backup's portable key; values a partial restore keeps from the current installation (account numbers and their fingerprints, two-step secrets, signature images) are re-encrypted with it in the same transaction when the keys differ.

## BR-037 — Account Number Masking

Normal account-number display is a fixed 10-character masked representation. No more than the final four characters may be revealed in masked form, and at least 50% of the actual identifier (rounded up) must remain masked. Full reveal is available only to Budget Managers.

## BR-038 — Account Reveal Is Audited

Revealing a full Bank Account number creates a security Audit Event. The full number must never be written into the Audit Event or application logs.

## BR-039 — Primary Bank Account

Only a register-enabled active Bank Account may be Primary. There may be zero or one Primary account. Selecting a new Primary atomically clears the prior Primary flag.

## BR-040 — Bank Accounts Cannot Be Deleted

Bank Accounts may be inactivated/closed but never deleted through the application.

## BR-041 — Uncleared Transactions Block Account Closure

A Bank Account with any uncleared active Register Transactions cannot be closed/inactivated.

## BR-042 — Continuous Register

A register-enabled Bank Account has one continuous Register for its lifetime. Fiscal Year Register views are date filters over that continuous history.

## BR-043 — Fiscal-Year Starting Balance Is Derived

The displayed starting balance for a Fiscal Year is the Bank Account balance as of the end of the day immediately preceding the Fiscal Year Start Date. It is not stored as a recurring annual transaction.

## BR-044 — Initial Opening Balance

A newly tracked register-enabled Bank Account has an Opening Balance and Opening Balance Date used to establish the beginning of reliable Register history.

2.2.0 (#348): a point-in-time comparison to a date before the Opening Balance Date uses the opening balance (BR-044a); BR-043's derived Fiscal-Year starting balance already does.

## BR-044a — Comparisons Before Any Data (2.2.0, #348)

Every point-in-time comparison (the Financial Flow Report's Compare Date, and any later comparison of balances or year-over-year figures) uses the **earliest available data** for a date before any data, never $0: a register account before its Opening Balance Date (or, without one, the day it was added) uses its opening balance; a non-register account before its first dated balance uses that first balance; a year-over-year figure with no earlier year shows no comparison.

A Bank Account may have an optional **Account opened** date (not in the future; editable; audited). Blank means the account existed before PennyWarden. A date before Account opened is $0, because the account really did not exist then, and an account opened after a report's Through Date is not listed. Dashboard balance charts show no value for months before Account opened.

Each substituted value is marked on screen with an explanation (always). The PDF lists a note for each one — "Savings: starting balance is the first recorded balance, 2026-07-01 (no data on 2026-01-01)." — only when the report option **Show notes on substituted starting values** is on (off by default).

## BR-045 — Transaction Parent Plus Allocations

Every Register Transaction has one or more Transaction Allocations. A normal transaction has one allocation; a split transaction has multiple. The backend uses the same model for both.

## BR-046 — Transaction Total Is Derived

`Transaction Total = SUM(Transaction Allocation amounts)`.

The parent amount is not independently authoritative.

## BR-047 — Only Parent Affects Bank Balance

Only an ACTIVE parent Register Transaction affects the Bank Account balance. Allocations must never be separately counted toward Bank Account balance.

## BR-048 — Allocations Affect Budget Actuals

ACTIVE Transaction Allocations affect their referenced Budget actuals. VOID transactions have zero Budget impact while preserving historical allocation records.

## BR-049 — Transaction Allocation Budget Is Required

Every Transaction Allocation has a non-null Budget FK. Exceptional non-budget activity uses protected Budget 0 rather than null.

## BR-050 — Deposit/Withdrawal Budget Type

Deposit Allocations may reference only Income Budgets. Withdrawal Allocations may reference only Expense Budgets, except protected system handling such as Budget 0 where explicitly allowed.

## BR-051 — Transaction Date

Transaction Date is user-editable and defaults to the current date. It represents when the financial activity occurred from the user's perspective.

## BR-052 — Entry Timestamp

Entry Timestamp is generated by the system when the record is created and cannot be edited by the user.

## BR-053 — Clear Date

Null Clear/Post Date means uncleared. A present Clear/Post Date means cleared. Cleared status does not itself make the transaction immutable.

## BR-054 — Cleared Transaction Edit Confirmation

A cleared transaction may be edited while no affected Fiscal Year is Closed. Any such financial edit requires blocking confirmation and full auditing.

## BR-055 — Transaction Bank Account Is Immutable

A Register Transaction cannot move to another Bank Account after creation. Incorrect-account entries must be Voided and recreated in the correct account.

## BR-056 — Transaction Type May Change Through Protected Workflow

An ACTIVE transaction may change between Deposit and Withdrawal while affected Fiscal Years remain editable, but the UI must make this intentionally difficult, require confirmation, clear/revalidate incompatible fields/allocations, and enforce the new Budget type rules.

## BR-057 — Closed Fiscal Year Protects Transaction

If any active Allocation references a Closed Fiscal Year, the transaction's financial fields are immutable. No new allocations may be added to a Closed Fiscal Year.

## BR-058 — Natural Fiscal Year vs Budget Fiscal Year

Register chronology is determined by Transaction Date. Budget Fiscal Year is determined by the selected Budget's Fiscal Year. They may legitimately differ.

## BR-059 — Cross-Fiscal-Year Allocation Confirmation

When a user selects a Budget Fiscal Year different from the Fiscal Year naturally covering Transaction Date, the application requires explicit confirmation and records/reviews the mismatch as appropriate.

## BR-060 — Missing Fiscal Year Warning

If no Fiscal Year covers Transaction Date, the application warns the user, identifies the closest configured Fiscal Year, and does not silently treat it as correct. The allocation is flagged for later Fiscal Year review where appropriate.

## BR-061 — Split Withdrawal Entity

A split Withdrawal has one parent Entity/payee. Allocation children cannot use different Entities.

## BR-062 — Split Withdrawal Child Fields

Withdrawal allocations may independently contain Budget, Invoice Number, Description, Amount, Notes, and Attachments. Bank Account, Type, Transaction Date, Clear Date, parent Entity, and Check Number are inherited parent concepts.

## BR-063 — Split Deposit Entities

A split Deposit may contain different Entities on different Allocations because multiple payments may be deposited together. The system uses the protected `Multiple` Entity at the parent level where appropriate.

2.1.2 (#344): the parent Entity of a Deposit is derived from its Allocations. When the parent Entity of a Deposit is changed, Allocations that were on the previous parent Entity follow the new one; Allocations deliberately set to a different Entity keep it.

## BR-064 — Split Conversion Ignores Prior Parent Amount

When a user converts an entry to split mode, any previously entered parent/single amount ceases to be authoritative. Parent total is derived from the resulting Allocations.

## BR-065 — Transaction Cannot Be Deleted

No Register Transaction can be deleted regardless of whether it is cleared or uncleared. Removal from financial effect is always performed through Void.

## BR-066 — Void Is Irreversible

A VOID transaction cannot be unvoided through the POC UI.

## BR-067 — Void Requires Reason and Confirmation

Voiding requires a non-empty Void Reason and blocking irreversible confirmation.

## BR-068 — Void Financial Effect

VOID transactions remain permanently visible but have zero Bank Account balance impact and zero Budget actual impact.

## BR-069 — Void Preserves History

Voiding preserves original transaction fields, allocations, and existing attachments for audit purposes.

## BR-070 — Attachments After Void

Existing attachments on a VOID transaction cannot be removed. Additional supporting attachments and Notes may be added after voiding and are audited.

## BR-071 — Closed-Year Transaction Cannot Be Voided

A transaction with an allocation against a Closed Fiscal Year cannot be voided because that would alter closed financial results.

## BR-072 — Zero-Dollar Transactions

An ACTIVE Deposit/Withdrawal must have a total amount greater than zero. A zero-dollar transaction is permitted only when created as VOID for accountability, such as documenting a damaged unused check. It requires a Void Reason and uses protected Budget 0.

## BR-073 — Attachments

POC supports PDF, JPG/JPEG, and PNG only, maximum 5 MB per file. Multiple attachments are allowed.

## BR-074 — Attachment Validation Is Server-Side

The backend validates size and permitted content/file type; client-side validation is convenience only.

## BR-075 — Audit Log Is Append-Only

Audit Events cannot be edited or deleted through the application.

## BR-076 — Audit Before/After Snapshots

Auditable mutations store complete logical before/after snapshots where appropriate. Create has null `before`. Sensitive fields must be masked/redacted before audit persistence.

## BR-077 — Audit and Financial Mutation Are Atomic

A financial/business mutation and its required Audit Event must commit in the same database transaction. Failure to persist the audit event rolls back the business mutation.

## BR-078 — Backend Authorization Is Authoritative

Hiding unauthorized UI modules/actions is required for usability, but backend API authorization independently enforces every permission.

## BR-079 — Draft/Approved/Rejected Visual State Is Not Color-Only

UI may use light green for Approved, light yellow for Draft, and light red for Rejected, but must also show textual/icon state for accessibility.

## BR-080 — Budget State Icons

Budget views use compact state indicators:

- Closed padlock = Approved + Locked.
- Open padlock = Approved + Unlocked.
- `?` = Draft/Unapproved.
- `X` = Rejected.

## BR-081 — Local Deployment Is Loopback-Only

Local mode binds to loopback (`127.0.0.1` or equivalent) by default and is not intentionally network accessible.

## BR-082 — Server Deployment Uses Same Application

Windows/Linux server mode uses the same application code and data model with configurable network binding. Docker is optional, not required.

## BR-083 — No Runtime Infrastructure Prerequisites for Native Package

Native Windows/Linux distributions must not require the destination user to separately install Python, Node.js, SQLite, Docker, or another database server.

## BR-084 — SQLite Is Application-Owned

Clients never directly open SQLite over a network share. All client access occurs through the FastAPI application/API.

## BR-085 — Portable Encryption Secret

The encryption secret required to decrypt sensitive database values is stored separately from the database, protected by filesystem permissions, and remains portable across Windows/Linux and machine migration. It must not be bound solely to OS-specific credential protection.

## BR-086 — Application Data Is Separate From Application Binaries

Persistent database, attachments, portable secrets, and required recovery configuration live in an application-data location separate from replaceable application binaries.

## BR-087 — Authentication Uses Server-Side Sessions

The POC uses backend-managed sessions with HttpOnly cookies. Authorization is revalidated server-side; role claims from the browser are not authoritative.

## BR-088 — CSRF Protection

State-changing requests using cookie authentication require CSRF protection or an equivalent secure same-origin mechanism appropriate to the selected framework design.

## BR-089 — Passwords Are Hashed

Passwords are stored only as modern slow password hashes; they are never reversibly encrypted or stored in plaintext.

## BR-090 — Network Server Deployments Expect HTTPS

Local loopback HTTP is permitted. Network/server production use should be deployed behind HTTPS/TLS. TLS termination may be provided by operator-managed reverse proxy infrastructure rather than the application itself.

## BR-091 — Unauthorized Modules Are Hidden

Navigation and controls unavailable to a role are hidden, while direct/API access remains independently blocked by backend authorization.

## BR-092 — POC Backup/Restore Is Deferred

The POC does not provide application-managed backup/restore. Local-install users are warned that they are responsible for protecting application data against machine/disk loss. Future backup tooling must include database, attachments, and required portable encryption material.


## BR-093 — Bank Account Closure Requires Zero Balance

A Bank Account cannot be closed/inactivated unless its current balance is exactly `0.00`. For a register-enabled account, the zero balance must result from register activity, including a final transaction where necessary; a user may not manually override the calculated balance to zero. For a non-register account, the manually maintained current balance must be explicitly updated to `0.00` through an audited balance update before closure. BR-041 also applies: no uncleared active transactions may remain.


## Application Security and Secure Coding Rules

## BR-094 — All Client Input Is Untrusted

All data originating from browsers, API clients, uploaded files, configuration interfaces, query parameters, path parameters, headers, cookies, and form submissions is untrusted. Required validation is enforced server-side even when equivalent client-side validation exists. Client-side validation is a usability feature only.

## BR-095 — Parameterized Database Access

User-controlled values must never be concatenated or interpolated into executable SQL. Database access uses SQLAlchemy parameter binding, ORM/query APIs, or equivalently parameterized statements. Dynamic field names, sort keys, directions, filters, and similar structural query choices are mapped through explicit allowlists.

## BR-096 — Context-Appropriate Output Encoding

User-controlled text is rendered as inert text by default. The implementation must preserve React's escaped rendering behavior and must not render user-controlled raw HTML, scripts, event handlers, or executable markup unless a specific documented feature requires it and a suitable sanitization control is applied.

## BR-097 — Domain-Specific Input Validation

Server-side validation enforces expected data type, allowed values, required fields, sensible maximum lengths/ranges, date formats, decimal precision, identifier form, and domain-specific constraints. Validation errors are handled predictably without exposing implementation internals.

## BR-098 — Explicit Writable Fields and Mass-Assignment Protection

API request models explicitly define fields that a caller is permitted to set for that operation. Clients cannot assign or overwrite protected/internal properties such as system-record flags, audit metadata, creator/modifier identity, derived totals, immutable foreign keys, role/security-domain fields, lock/closure state, or other privileged attributes merely by adding them to a request payload.

## BR-099 — Object-Level Authorization

Authorization is enforced not only by endpoint/action but also against the requested object. Altering object identifiers, workspace identifiers, Bank Account IDs, Entity IDs, Budget IDs, Transaction IDs, or other references must not permit a caller to view or mutate data outside the caller's authorized scope.

## BR-100 — Safe Attachment Paths and Filenames

Uploaded filenames are treated as metadata only. Storage paths and filenames are generated by the application. User-provided filenames must not control filesystem paths, path separators, parent traversal, absolute paths, executable locations, or overwrite behavior.

## BR-101 — Attachment Content Validation

Attachment acceptance is based on the documented allowlist and server-side content/type inspection, not solely on filename extension or browser-supplied MIME type. Files that are executable, disguised as an allowed type, malformed in a security-relevant manner, or larger than 5 MB are rejected. Uploaded files are not served from an executable application directory.

## BR-102 — Unsafe Command Construction Is Prohibited

Application features should use Python/library APIs rather than shell commands. If operating-system process execution is unavoidable, user input must not be concatenated into a shell command. Arguments must be structured and allowlisted as appropriate, and shell invocation should be avoided.

## BR-103 — Secrets and Sensitive Values Are Not Logged

Passwords, password hashes, session identifiers/cookies, CSRF secrets, encryption keys, full plaintext bank account numbers, and equivalent secrets must not appear in application logs, audit snapshots, exception responses, client-side logging, or ordinary diagnostic output. Audit records use masked/sanitized representations where required.

2.2.0 (#327): this includes an authenticator key a user supplies when setting up two-step verification ("Use my own key instead"), and any otpauth link it came in. It is validated server-side (Base32, at least 16 and at most 100 characters; links only for 6-digit, 30-second, SHA-1 codes), accepted only during a setup in progress, saved only after a current code made with it, stored encrypted like a generated key, never shown again, and refused after a reset marked as a possible compromise. Error messages describe the problem without repeating the key; the audit records only whether an own key was used (`own_key`) and whether a reset was marked (`compromised`).

## BR-104 — Safe Error Handling

Production-facing error responses must not expose stack traces, raw SQL, database internals, filesystem paths, encryption material, secret configuration, password data, session values, or other sensitive implementation details. Detailed diagnostics may be written to protected server logs only when those logs comply with BR-103.

## BR-105 — Security Response Headers

Web responses use appropriate security headers for the deployed same-origin application, including protections against MIME/content sniffing and clickjacking, a suitable Referrer-Policy, and a reasonably restrictive Content-Security-Policy. HTTPS deployments may use HSTS when TLS termination and deployment topology make it appropriate.

## BR-106 — Dependency and Build Security Hygiene

Application dependencies are version tracked. The project provides a repeatable way to check Python and JavaScript dependencies for known vulnerabilities during development/CI and records/remediates material findings before a release is considered complete.

## BR-107 — Secure Defaults

Security-sensitive defaults favor the safer deployment posture: local mode binds only to loopback, debug mode is disabled in packaged production builds, default credentials are not shipped, privileged features require explicit authorization, and server/network deployment warns when transport security is not configured.

## BR-108 — Security Controls Require Negative Tests

The POC includes automated negative/security tests for the documented security acceptance criteria wherever practical. A feature is not considered secure merely because the normal UI does not expose a prohibited operation. Tests must exercise backend/API controls directly.

## Benchmark v1.1 Additions — Bootstrap, Passwords, Themes, and Draft Fiscal Years

**BR-SEC-SELF-001 — Self-service password change.** Every authenticated active user may change their own password after providing the current password. The new password must satisfy password policy. Password values must never be logged or placed in audit snapshots.

**BR-SEC-SELF-002 — Password-change sessions.** A successful self-service password change invalidates the user's other active sessions and is audited without password values.

**BR-INIT-001 — First-run wizard.** A truly uninitialized installation automatically presents the Initialization Wizard before normal application use.

**BR-INIT-002 — Required bootstrap inputs.** Initialization requires Organization/Workspace Name, initial Administrator Username, initial Administrator Email Address, Password, and Password Confirmation.

**BR-INIT-003 — Atomic bootstrap.** Successful initialization coherently creates the Workspace, initial Administrator, Administrator role assignment, required roles/permissions, portable encryption key, hidden system records, and required seed data. A partial bootstrap is not considered initialized.

**BR-INIT-004 — Initial Administrator.** The bootstrap Administrator immediately has normal Administrator authorization, appears in the User List, can access Administrator screens/dashboard, and remains prohibited from financial modules.

**BR-UI-THEME-001 — Appearance.** The POC provides user-selectable Light and Dark modes.

**BR-UI-THEME-002 — Appearance persistence.** Theme preference persists for the user across navigation and subsequent authenticated sessions. Core POC screens remain readable and functional in both modes.

**BR-FY-VIS-001 — Draft is operational.** A Fiscal Year need not be Approved to exist, be navigable, appear in authorized lists/selectors, receive budgets, or receive transaction allocations.

**BR-FY-VIS-002 — Status does not imply invisibility.** Lifecycle status must not hide a record unless a documented rule explicitly requires it. Closed Fiscal Years remain available in authorized historical/read-only views.

**BR-FY-VIS-003 — Identity is separate from status.** Fiscal Year selectors/headings display the actual Fiscal Year name/identifier. Status may accompany it (for example `FY2027 — Draft`) but status must never substitute for identity.

**BR-FY-VIS-004 — Draft budget use.** Budget Managers may create/maintain budgets in Draft Fiscal Years and Register Users may allocate transactions to eligible Draft-year budgets.

**BR-FY-VIS-005 — Status transition preserves identity.** Approval/closure changes lifecycle behavior without changing Fiscal Year identity, route, primary key, or ordinary authorized visibility.
