"""Role -> permission mapping (docs/04 §2 permission matrix). Backend authorization is authoritative."""
from __future__ import annotations

ADMINISTRATOR = "ADMINISTRATOR"
BUDGET_MANAGER = "BUDGET_MANAGER"
BUDGET_USER = "BUDGET_USER"
REGISTER_USER = "REGISTER_USER"
AUDITOR = "AUDITOR"
# 1.7.3 (#52, #53): optional extra Financial roles, each only together with its base role
BUDGET_ADMIN = "BUDGET_ADMIN"
REGISTER_ADMIN = "REGISTER_ADMIN"
REQUIRES = {BUDGET_ADMIN: BUDGET_MANAGER, REGISTER_ADMIN: REGISTER_USER}

ROLE_DEFS = [
    (ADMINISTRATOR, "Administrator", "ADMINISTRATOR"),
    (BUDGET_MANAGER, "Budget Manager", "FINANCIAL"),
    (BUDGET_USER, "Budget User", "FINANCIAL"),
    (REGISTER_USER, "Register User", "FINANCIAL"),
    (BUDGET_ADMIN, "Budget Admin", "FINANCIAL"),
    (REGISTER_ADMIN, "Register Admin", "FINANCIAL"),
    (AUDITOR, "Auditor", "AUDITOR"),
]
ROLE_DOMAIN = {code: domain for code, _n, domain in ROLE_DEFS}
FINANCIAL_ROLES = {BUDGET_MANAGER, BUDGET_USER, REGISTER_USER, BUDGET_ADMIN, REGISTER_ADMIN}
# 1.9.0 (#54): on a local install one person may hold roles of several domains; such a user's security domain is
# COMBINED. The first user of a local install gets these roles (Budget User adds nothing to Budget Manager).
COMBINED = "COMBINED"
LOCAL_FIRST_USER_ROLES = [ADMINISTRATOR, BUDGET_MANAGER, BUDGET_ADMIN, REGISTER_USER, REGISTER_ADMIN, AUDITOR]

PERMISSIONS: dict[str, set[str]] = {
    "users.view": {ADMINISTRATOR, AUDITOR},
    "users.manage": {ADMINISTRATOR},
    "audit.view": {ADMINISTRATOR, AUDITOR},
    "audit.view_financial_snapshots": {AUDITOR},
    "financial.view": {BUDGET_MANAGER, BUDGET_USER, REGISTER_USER, AUDITOR},
    "fiscal_year.manage": {BUDGET_MANAGER},
    "budget.manage": {BUDGET_MANAGER},
    "bank_account.manage": {BUDGET_MANAGER},
    "bank_account.reveal": {BUDGET_MANAGER},
    "transaction.manage": {REGISTER_USER},
    "entity.manage": {BUDGET_MANAGER, REGISTER_USER},
    "entity.create_financial_institution": {BUDGET_MANAGER, REGISTER_USER},
    "entity.manage_financial_institution": {BUDGET_MANAGER},
    "review.resolve": {BUDGET_MANAGER, REGISTER_USER},
    # v1.6.0 CR-033: optional modules (switched on by an Administrator) and the Fundraiser module
    "modules.manage": {ADMINISTRATOR},
    "fundraiser.view": {BUDGET_MANAGER, BUDGET_USER, REGISTER_USER, AUDITOR},
    "fundraiser.manage": {BUDGET_MANAGER},
    # v1.6.1 CR-034: buckets, special classifications, exclusions and fundraiser documents
    "fundraiser.lines": {BUDGET_MANAGER, REGISTER_USER},
    # v1.6.3 CR-036: reminders. Personal reminders are private to their owner; organization reminders are created
    # by Budget Managers, resolved by Budget Managers and Register Users, and seen (once due) by all viewers.
    "reminder.view": {BUDGET_MANAGER, BUDGET_USER, REGISTER_USER, AUDITOR},
    "reminder.personal": {BUDGET_MANAGER, REGISTER_USER},
    "reminder.org_manage": {BUDGET_MANAGER},
    "reminder.org_resolve": {BUDGET_MANAGER, REGISTER_USER},
    # 1.7.3 (#52): delete (status Deleted) a budget of a Fiscal Year that is not approved
    "budget.delete": {BUDGET_ADMIN},
    # 1.7.3 (#53): delete (status Deleted) an uncleared transaction instead of voiding it
    "transaction.delete": {REGISTER_ADMIN},
    # 2.0.0 (#156): Payments module (optional). Administrators set up check styles, signers and limits and test
    # print with dummy data only (BR-003). Only Register Users print checks (and, from build 2, create payments);
    # Budget Managers and Auditors have no access to the module.
    "checks.setup": {ADMINISTRATOR},
    "checks.print": {REGISTER_USER},
}


def permissions_for(role_codes: set[str]) -> set[str]:
    return {p for p, roles in PERMISSIONS.items() if roles & role_codes}


def domain_of(role_codes: set[str]) -> str | None:
    """The security domain a role set belongs to: its one domain, or COMBINED when it spans several (1.9.0, #54)."""
    domains = {ROLE_DOMAIN[r] for r in role_codes if r in ROLE_DOMAIN}
    if not domains:
        return None
    return domains.pop() if len(domains) == 1 else COMBINED


def validate_role_set(domain: str, role_codes: set[str], mode: str = "server") -> str | None:
    """BR-002: returns an error message when the combination crosses security domains. 1.9.0 (#54): on a local
    install (mode "local") roles of different domains may be combined; the domain is then COMBINED."""
    if not role_codes:
        return "At least one role is required."
    unknown = role_codes - set(ROLE_DOMAIN)
    if unknown:
        return "Unknown role."
    domains = {ROLE_DOMAIN[r] for r in role_codes}
    if len(domains) > 1 and mode != "local":
        return "Roles from different security domains (Administrator, Financial, Auditor) cannot be combined."
    if domain_of(role_codes) != domain:
        return "Roles do not match the user's security domain."
    for extra, base in REQUIRES.items():
        if extra in role_codes and base not in role_codes:
            names = {c: n for c, n, _d in ROLE_DEFS}
            return f"{names[extra]} can only be given together with {names[base]}."
    return None
