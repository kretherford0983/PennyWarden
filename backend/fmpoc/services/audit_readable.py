"""2.0.0 (#133): the readable audit log - plain-language summaries and "What changed" tables, built on the server in
the same place that withholds financial content from Administrators (BR-003), so the rule is enforced once.

Every action code gets a readable name: an explicit label where the generated one would read badly, otherwise the
code itself in words (`BANK_ACCOUNT_BALANCE_UPDATED` -> "Bank account balance updated"), so a new action can never
break the screen. Field names get labels the same way; values are formatted (cents -> currency, Yes/No, status codes
in words, dates); lists of rows (allocations) become sub-tables. Related records are named from the labels recorded
with the event (`audit_event.labels`, written for new events) or looked up now for older ones - and the entry says so
when a record no longer exists. The stored snapshots are never changed (BR-075)."""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..models import BankAccount, Budget, Entity, FiscalYear, User

ACTION_LABELS = {
    "LOGIN": "Signed in", "LOGOUT": "Signed out", "LOGIN_FAILED": "Sign-in failed",
    "LOGIN_PASSWORD_ACCEPTED": "Password accepted (two-step pending)", "LOGIN_RATE_LIMITED": "Sign-in blocked (too many attempts)",
    "MFA_CHANGED": "Two-step verification changed", "MFA_DISABLED": "Two-step verification turned off",
    "MFA_FAILED": "Two-step code failed", "MFA_RESET": "Two-step verification reset",
    "MFA_RECOVERY_CODE_USED": "Two-step recovery code used",
    "MFA_TRUSTED_BROWSER_ADDED": "Browser trusted for two-step", "MFA_TRUSTED_BROWSER_REVOKED": "Trusted browser removed",
    "FY_APPROVAL_NO_ATTACHMENT_SET": "Fiscal Year approval marked as having no document",
    "FY_APPROVAL_NO_ATTACHMENT_CLEARED": "Fiscal Year approval 'no document' mark cleared",
    "CHECK_NUMBERS_CONFIRMED_NOT_MISSING": "Missing check numbers confirmed",
    "TRANSACTION_CREATED_AS_VOID": "Transaction recorded as void",
    "CHECK_HANDWRITTEN": "Check written by hand recorded", "CHECK_SPOILED": "Check marked spoiled",
    "SYSTEM_INITIALIZED": "Application initialized", "SYSTEM_RESTORED": "Data restored from a backup",
    "REINITIALIZE": "Data reinitialized (users kept)", "ALL_SESSIONS_ENDED_BY_ADMIN": "All other sessions ended",
    "SESSION_ENDED_BY_ADMIN": "Session ended by an Administrator", "ACCOUNT_NUMBER_REVEALED": "Account number shown",
    "UPDATE_CHECK_SETTING_CHANGED": "Update check setting changed", "REPORT_GENERATED": "Report generated",
    "AUDIT_LOG_EXPORTED": "Audit log exported",
    "CONFIG_APPLIED": "Server settings applied (pennywarden apply-config)",
    "ATTACHMENTS_REORDERED": "Attachments reordered",
    # 2.1.0 (#312, #314)
    "ORGANIZATION_UPDATED": "Organization profile changed", "DONATION_SETUP_UPDATED": "Donations setup changed",
    "DONATION_MARKED": "Donation lines changed",
    "DONATION_DETAILS_UPDATED": "Donation details changed", "DONATION_RECEIPT_PRINTED": "Donation receipt printed",
    "DONATION_RECEIPT_TEST": "Donation receipt test print",
}
OBJECT_LABELS = {
    "user": "User", "workspace": "Organization", "server_config": "Server settings", "fiscal_year": "Fiscal Year", "budget": "Budget", "entity": "Entity",
    "bank_account": "Bank account", "register_transaction": "Transaction", "attachment": "Attachment",
    "fiscal_year_review": "Fiscal Year review", "transaction_allocation": "Transaction line", "fundraiser": "Fundraiser",
    "reminder": "Reminder", "check_style": "Check style", "check_signer": "Signer", "check_document": "Letter/envelope template",
    "signature_template": "Signature wording", "security_notice": "Security notice", "audit_log": "Audit log",
    "donation_settings": "Donations setup",
}
FIELD_LABELS = {
    "id": "ID", "username": "Username", "display_name": "Display name", "first_name": "First name",
    "last_name": "Last name", "email": "Email", "active": "Active", "roles": "Roles", "security_domain": "Security domain",
    "account_name": "Account name", "account_type": "Account type", "manual_current_balance": "Current balance",
    "opening_balance": "Opening balance", "opening_balance_date": "Opening balance date", "is_primary": "Primary",
    "transaction_date": "Date", "transaction_type": "Type", "clear_date": "Cleared", "check_number": "Check number",
    "void_reason": "Void reason", "invoice_number": "Invoice number", "invoice_date": "Invoice date",
    "allocations": "Lines", "amount": "Amount", "total": "Total", "parent_code": "Code", "child_code": "Sub-code",
    "budget_type": "Budget type", "identifier": "Fiscal Year", "start_date": "Start", "end_date": "End",
    "organization_name": "Organization name", "primary_contact": "Contact", "entity_type": "Entity type",
    "ein": "EIN", "address_line1": "Address", "address_line2": "Address line 2", "city": "City",
    "state_region": "State", "postal_code": "ZIP", "phone": "Phone",
    "account_number_visible_suffix": "Account number (last 4)", "notes": "Notes", "description": "Description",
}
# ids of related records and how to name them
ID_KINDS = {"budget_id": "budget", "entity_id": "entity", "parent_entity_id": "entity",
            "financial_institution_entity_id": "entity", "bank_account_id": "bank_account",
            "fiscal_year_id": "fiscal_year", "user_id": "user", "created_by_user_id": "user",
            "updated_by_user_id": "user"}
FINANCIAL_KINDS = {"budget", "entity", "bank_account", "fiscal_year"}
MONEY_KEYS = {"amount", "total", "opening_balance", "manual_current_balance", "balance", "amount_due"}
NAME_KEYS = ("name", "account_name", "display_name", "organization_name", "primary_contact", "identifier", "title",
             "username", "filename", "original_filename")
_ISO_DT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def humanize(code: str) -> str:
    words = code.replace("_", " ").strip().lower()
    return (words[:1].upper() + words[1:]) if words else code


def action_label(code: str) -> str:
    return ACTION_LABELS.get(code) or humanize(code)


def object_label(t: str) -> str:
    return OBJECT_LABELS.get(t) or humanize(t)


def field_label(key: str) -> str:
    base = key[:-6] if key.endswith("_cents") else key
    if base in FIELD_LABELS:
        return FIELD_LABELS[base]
    if base.endswith("_id"):
        return humanize(base[:-3])
    return humanize(base)


def fmt(key: str, v):
    """A readable value. Never adds information the snapshot doesn't hold."""
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if key.endswith("_cents") and isinstance(v, int):
        sign = "-" if v < 0 else ""
        v = abs(v)
        return f"{sign}${v // 100:,}.{v % 100:02d}"
    if isinstance(v, str) and key in MONEY_KEYS and re.fullmatch(r"-?\d+(\.\d{1,2})?", v):
        whole, _, frac = v.lstrip("-").partition(".")
        return f"{'-' if v.startswith('-') else ''}${int(whole):,}.{(frac + '00')[:2]}"
    if isinstance(v, str):
        if re.fullmatch(r"[A-Z][A-Z0-9_]{1,40}", v) and key not in ("username", "check_number", "invoice_number"):
            return humanize(v)
        if _ISO_DT.match(v):
            return v[:16].replace("T", " ") + " UTC"
        return v
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return ", ".join(humanize(x) if re.fullmatch(r"[A-Z][A-Z0-9_]+", x) else x for x in v) or "—"
    return v


# ------------------------------------------------------------------ labels of related records
def collect_ids(snap, out: set | None = None) -> set:
    out = out if out is not None else set()
    if isinstance(snap, dict):
        for k, v in snap.items():
            if k in ID_KINDS and isinstance(v, int):
                out.add((ID_KINDS[k], v))
            else:
                collect_ids(v, out)
    elif isinstance(snap, list):
        for x in snap:
            collect_ids(x, out)
    return out


def name_of(db: Session, kind: str, rid: int) -> str | None:
    if kind == "budget":
        b = db.get(Budget, rid)
        if b is None:
            return None
        fy = db.get(FiscalYear, b.fiscal_year_id)
        return f"{b.parent_code}{'-' + b.child_code if b.child_code else ''} {b.name}" + (f" ({fy.identifier})" if fy else "")
    if kind == "entity":
        e = db.get(Entity, rid)
        return e.display_name if e else None
    if kind == "bank_account":
        a = db.get(BankAccount, rid)
        return f"{a.account_name} (****{a.account_number_visible_suffix})" if a else None
    if kind == "fiscal_year":
        f = db.get(FiscalYear, rid)
        return f.identifier if f else None
    if kind == "user":
        u = db.get(User, rid)
        if u is None:
            return None
        return f"{u.first_name} {u.last_name} - {u.username}" if u.first_name and u.last_name else u.username
    return None


def labels_for(db: Session, before, after) -> dict | None:
    """Written with a new event: the names of the related records as they are now ("kind:id" -> name)."""
    ids = collect_ids(before) | collect_ids(after)
    out = {}
    for kind, rid in sorted(ids):
        try:
            n = name_of(db, kind, rid)
        except Exception:  # noqa: BLE001 - naming must never break writing the event
            n = None
        if n:
            out[f"{kind}:{rid}"] = n[:200]
    return out or None


# ------------------------------------------------------------------ the readable view
def _related(db: Session, stored: dict | None, kind: str, rid: int, can_financial: bool) -> str:
    if kind in FINANCIAL_KINDS and not can_financial:
        return f"#{rid}"
    key = f"{kind}:{rid}"
    if stored and key in stored:
        return f"{stored[key]} (#{rid})"
    n = name_of(db, kind, rid)
    return f"{n} (#{rid})" if n else f"#{rid} (no longer exists)"


def _value(db, stored, key, v, can_financial):
    if key in ID_KINDS and isinstance(v, int):
        return _related(db, stored, ID_KINDS[key], v, can_financial)
    return fmt(key, v)


def _rows(db, stored, items: list, can_financial: bool) -> dict:
    keys: list[str] = []
    for it in items:
        for k in it:
            if k not in keys and k not in ("id",):
                keys.append(k)
    return {"columns": [field_label(k) for k in keys],
            "rows": [[_value(db, stored, k, it.get(k), can_financial) for k in keys] for it in items]}


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and v and not any(isinstance(x, (dict, list)) for x in v.values()) and prefix == "":
            for k2, v2 in v.items():
                out[f"{key}.{k2}"] = v2
        else:
            out[key] = v
    return out


def changes(db: Session, stored: dict | None, before: dict | None, after: dict | None, can_financial: bool) -> list:
    b, a = _flatten(before or {}), _flatten(after or {})
    keys = list(dict.fromkeys([*b.keys(), *a.keys()]))
    update = bool(before) and bool(after)
    out = []
    for k in keys:
        bv, av = b.get(k), a.get(k)
        if update and bv == av:
            continue
        last = k.split(".")[-1]
        row = {"field": k, "label": field_label(last) if "." not in k else
               f"{field_label(k.split('.')[0])}: {field_label(last)}", "changed": update and bv != av}
        if isinstance(bv, list) and bv and all(isinstance(x, dict) for x in bv) or \
                isinstance(av, list) and av and all(isinstance(x, dict) for x in av):
            row["before_table"] = _rows(db, stored, bv, can_financial) if isinstance(bv, list) and bv else None
            row["after_table"] = _rows(db, stored, av, can_financial) if isinstance(av, list) and av else None
        else:
            row["before"] = _value(db, stored, last, bv, can_financial) if before else None
            row["after"] = _value(db, stored, last, av, can_financial) if after else None
        out.append(row)
    return out


def _name_in(snap) -> str | None:
    if isinstance(snap, dict):
        for k in NAME_KEYS:
            v = snap.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()[:120]
    return None


def readable(db: Session, e, withheld: bool, can_financial: bool) -> dict:
    """The summary and the change table for one event, as this viewer may see it."""
    who = (f"{e.actor_name} - {e.actor_username}" if getattr(e, "actor_name", None) and e.actor_username
           else e.actor_username or ("command line" if (e.correlation_id or "") == "host-cli" else "system"))
    what = action_label(e.action)
    obj = object_label(e.object_type)
    if withheld:
        return {"summary": f"{who}: {what} — {obj.lower()} #{e.object_id} (details withheld for Administrators)",
                "action_label": what, "object_label": obj, "kind": "withheld", "changes": []}
    name = _name_in(e.after_snapshot) or _name_in(e.before_snapshot)
    target = f'{obj.lower()} "{name}"' if name else (f"{obj.lower()} #{e.object_id}" if e.object_id else obj.lower())
    kind = "update" if e.before_snapshot and e.after_snapshot else "create" if e.after_snapshot else \
        "remove" if e.before_snapshot else "event"
    return {"summary": f"{who}: {what} — {target}", "action_label": what, "object_label": obj, "kind": kind,
            "changes": changes(db, getattr(e, "labels", None), e.before_snapshot, e.after_snapshot, can_financial)}
