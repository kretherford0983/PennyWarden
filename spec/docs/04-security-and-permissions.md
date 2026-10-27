# 04 --- Security and Permissions

## 1. Security Domains

The application has three mutually exclusive high-level security
domains:

1.  Administrator
2.  Financial
3.  Auditor

A user account may not cross high-level domains. Financial users may
hold multiple Financial roles.

### Administrator

Administrators manage users and roles and may view audit logs. They may
not view or modify financial data, financial attachments, budgets, bank
accounts, entities, fiscal years, or registers.

### Financial Roles

Financial users may hold one or more of: - Budget Manager - Budget
User - Register User

### Auditor

Auditors are full-application read-only users. They may view users,
roles, audit logs, all financial data, attachments, inactive records,
rejected budgets, and voided transactions, but may not modify
application data.

## 2. Permission Matrix

  ---------------------------------------------------------------------------------------------------
  Capability                        Administrator       Budget  Budget User     Register      Auditor
                                                       Manager                      User 
  ------------------------------- --------------- ------------ ------------ ------------ ------------
  View users and roles                        Yes           No           No           No          Yes

  Create/update/inactivate users              Yes           No           No           No           No

  Assign roles                                Yes           No           No           No           No

  View audit logs                             Yes           No           No           No          Yes

  View fiscal years                            No          Yes          Yes          Yes          Yes

  Create/edit fiscal years                     No          Yes           No           No           No

  Approve fiscal years                         No          Yes           No           No           No

  Close fiscal years                           No          Yes           No           No           No

  Add fiscal-year attachments                  No          Yes           No           No           No

  View fiscal-year attachments                 No          Yes          Yes          Yes          Yes

  View budgets                                 No          Yes          Yes          Yes          Yes

  Create/edit/reject/inactivate                No          Yes           No           No           No
  budgets                                                                                

  Lock/unlock budgets                          No          Yes           No           No           No

  View bank accounts                           No          Yes          Yes          Yes          Yes

  Create/edit/inactivate bank                  No          Yes           No           No           No
  accounts                                                                               

  Reveal full bank account number              No          Yes           No           No           No

  View register transactions                   No          Yes          Yes          Yes          Yes

  Create/edit/void transactions                No           No           No          Yes           No

  Add transaction attachments                  No           No           No          Yes           No

  Create normal entities                       No          Yes           No          Yes           No

  Edit/inactivate normal entities              No          Yes           No          Yes           No

  Create Financial Institution                 No          Yes           No          Yes           No
  entities                                                                               

  Edit/inactivate Financial                    No          Yes           No           No           No
  Institution entities                                                                   

  View inactive/rejected/voided                No          Yes          Yes          Yes          Yes
  history                                                                                
  ---------------------------------------------------------------------------------------------------

## 3. Navigation Enforcement

Unauthorized modules must be both hidden from navigation and
inaccessible through direct API or URL access. Hiding UI elements is not
an authorization control; FastAPI must enforce authorization on every
protected operation.

## 4. Authentication

Use backend-managed server-side sessions.

-   Passwords are stored only as secure password hashes, preferably
    Argon2id.
-   Session identifiers are random and rotated after successful
    authentication.
-   Authentication cookies are HttpOnly.
-   SameSite is Strict or Lax as appropriate.
-   Secure is enabled when HTTPS is used.
-   Logout invalidates the server-side session.
-   Disabled users lose authorization.
-   Roles and permissions are revalidated server-side.
-   Authentication tokens are not stored in browser localStorage.
-   State-changing requests use CSRF protection.
-   Failed logins receive basic rate limiting.
-   Login, logout, password-reset/change, account-disable, role-change,
    and security-sensitive actions are audited.

Self-service email password recovery is outside the POC.
Administrator-controlled password reset is permitted and audited.

## 5. Sensitive Account Numbers

The complete bank account number may be stored, but: - it is encrypted
at rest using standard authenticated encryption; - the encryption key is
portable and stored separately from the SQLite database; - the key must
not be OS-bound; - read-only roles see only a masked representation; -
Register Users see only the masked representation; - only Budget
Managers may explicitly reveal the full number; - reveal actions are
audited without logging the account number; - audit snapshots mask the
account number rather than storing plaintext.

The normal masked display is 10 characters. It exposes no more than the
final four characters and masks at least 50 percent of the actual
identifier, rounded up.

## 6. Audit Integrity

Audit events are append-only through the application. Financial
mutations and their audit events must commit atomically. If the audit
event cannot be stored, the associated financial mutation must roll
back.

Before/after snapshots are used for auditable mutations, with sensitive
values sanitized before entering the audit record.

**Testing mode (2.2.0, #231).** A server-install-only switch in `config.toml` (`testing_mode = true`, or
`FM_TESTING_MODE`); the web UI and API can't turn it on or off. While it is on, every page shows a testing banner and
Administrators (`system.manage`) can move timers and schedules on System/About → Testing; the endpoints answer 404
otherwise. It never moves the real clock and changes no financial records. Testing actions are not bound by the audit
rules (decision 2026-10-14) but are still recorded as `TESTING_*` events in the Security category. A backup made in
testing mode is marked; the application refuses to restore it onto a server that is not in testing mode, and the
command line requires `--accept-testing-backup` (the server owner); `SYSTEM_RESTORED` records `testing_backup`.


## 7. Secure Coding and Request Handling

The application follows a defense-in-depth model. All client data is untrusted and is validated server-side. SQLAlchemy/parameterized database access is mandatory; user input is never concatenated into SQL. Request schemas expose only fields writable by the caller and prevent mass assignment of protected state. Object-level authorization is checked for requested records, not merely endpoint access.

React renders user content as escaped text by default. User-controlled raw HTML/script execution is prohibited unless a future documented feature introduces an explicit sanitizer.

Uploaded files use application-generated storage names, remain outside executable application directories, are validated by content/type in addition to extension, and may not influence filesystem paths.

The backend must not construct shell commands from user-controlled strings. Safe library APIs are preferred.

## 8. Secrets, Errors, and Logging

Passwords, password hashes, session/CSRF tokens, encryption keys, full plaintext bank account numbers, and equivalent sensitive material must not be written to ordinary logs or returned in errors. Production error responses are generic enough to avoid disclosing stack traces, SQL, filesystem paths, or secret configuration. Protected server logs may contain diagnostic detail only after sensitive values are excluded/sanitized.

## 9. Browser Security Headers

Packaged/server responses should include appropriate headers for a same-origin web application, including MIME-sniffing protection, framing/clickjacking restrictions, Referrer-Policy, and a restrictive Content-Security-Policy compatible with the React application. HSTS is appropriate when HTTPS termination is controlled and correctly configured.

## 10. Dependency Security

Python and JavaScript dependencies are pinned/tracked sufficiently for reproducible builds and are checked for known vulnerabilities through documented development/CI commands. Material findings must be addressed or explicitly documented before a build is considered release-ready.

## Benchmark v1.1 Authentication and Bootstrap Clarifications

Every authenticated active user may change their own password. Current password is required; successful change invalidates other active sessions and creates a password-safe audit event.

The Initialization Wizard-created Administrator is a normal Administrator for authorization purposes. It must appear in the User List and access Administrator navigation, dashboard, user management, and audit functions while remaining unable to access financial modules.
