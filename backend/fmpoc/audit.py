"""Append-only audit trail (BR-075/076/077). Events are added to the caller's DB session so the
business mutation and its audit event commit (or roll back) atomically."""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from .models import AuditEvent

# Never allowed in snapshots (BR-103). Account numbers are represented only by the masked value.
SENSITIVE_KEYS = {
    "password", "password_hash", "new_password", "current_password", "token_hash", "csrf_token",
    "account_number", "account_number_ciphertext", "account_number_fingerprint", "enc_key", "fp_key",
}


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items() if k not in SENSITIVE_KEYS}
    if isinstance(value, (list, tuple, set)):
        return [sanitize(v) for v in value]
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def actor_name(user) -> str | None:
    """2.0.0 (#134): "First Last" of the acting user, or None (no user, or no names yet)."""
    first, last = getattr(user, "first_name", None), getattr(user, "last_name", None)
    return f"{first} {last}"[:130] if first and last else None


def _labels(db, before, after):
    """2.0.0 (#133): the names of related records as they are now, kept with the event (never breaks writing it)."""
    try:
        from .services.audit_readable import labels_for
        return labels_for(db, before, after)
    except Exception:  # noqa: BLE001
        return None


def record(
    db: Session,
    ctx,
    action: str,
    object_type: str,
    object_id,
    before: dict | None = None,
    after: dict | None = None,
    category: str = "BUSINESS",
) -> AuditEvent:
    ev = AuditEvent(
        workspace_id=getattr(ctx, "workspace_id", None),
        actor_user_id=getattr(getattr(ctx, "user", None), "id", None),
        actor_username=getattr(getattr(ctx, "user", None), "username", None),
        actor_name=actor_name(getattr(ctx, "user", None)),
        labels=_labels(db, before, after),
        action=action,
        object_type=object_type,
        object_id=None if object_id is None else str(object_id),
        category=category,
        before_snapshot=sanitize(before) if before is not None else None,
        after_snapshot=sanitize(after) if after is not None else None,
        correlation_id=getattr(ctx, "correlation_id", None),
        source_ip=getattr(ctx, "ip", None),
    )
    db.add(ev)
    db.flush()  # surfaces audit persistence failures inside the business transaction
    return ev
