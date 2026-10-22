"""Entities: required names, duplicates, Entity Numbers, Financial Institution controls (BR-028..034)."""
from __future__ import annotations

import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import audit, phone as phone_fmt
from ..errors import AppError, Warning_, forbidden, not_found, require_confirmations, validation
from ..models import Entity, Workspace

FIELDS = ["entity_type", "organization_name", "primary_contact", "position", "address_line1", "address_line2", "city",
          "state_region", "postal_code", "country", "phone", "email", "notes", "is_financial_institution"]


def name_key(s: str | None) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(inc|llc|ltd|co|corp|corporation|company|the)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()[:200]


def snapshot(e: Entity) -> dict:
    return {"id": e.id, "entity_number": e.entity_number, "display_name": e.display_name,
            **{f: getattr(e, f) for f in FIELDS}, "active": e.active, "is_system": e.is_system,
            "is_organization": bool(e.is_organization), "ein": e.ein}


def clean_phone(typed: str | None, current: str | None = None) -> str | None:
    """1.6.7: the stored form of a typed phone number. A value that is already stored (or is its displayed form) is
    kept as it is, so an Entity whose older number is in another form can still be edited."""
    if current and typed and typed.strip() in (current, phone_fmt.display(current)):
        return current
    try:
        return phone_fmt.normalize(typed)
    except ValueError as exc:
        raise validation(str(exc), "phone") from None


def out(e: Entity) -> dict:
    return {**snapshot(e), "phone_display": phone_fmt.display(e.phone), "created_at": e.created_at.isoformat() if e.created_at else None,
            "updated_at": e.updated_at.isoformat() if e.updated_at else None}


def get_visible(db: Session, ctx, entity_id: int) -> Entity:
    e = db.get(Entity, entity_id) if isinstance(entity_id, int) else None
    if e is None or e.workspace_id != ctx.workspace_id or e.is_system:  # Multiple is never exposed (BR-034)
        raise not_found("Entity")
    return e


def _validate_names(e_type: str, org: str | None, contact: str | None) -> None:
    if e_type == "INDIVIDUAL" and not (contact or "").strip():
        raise validation("Primary Contact / Person Name is required for an Individual.", "primary_contact")
    if e_type == "ORGANIZATION" and not (org or "").strip():
        raise validation("Organization Name is required for an Organization.", "organization_name")


def duplicates(db: Session, ws_id: int, display: str, email: str | None, exclude_id: int | None = None) -> list[Entity]:
    key = name_key(display)
    conds = [Entity.name_key == key] if key else []
    if email:
        conds.append(Entity.email == email)
    if not conds:
        return []
    q = select(Entity).where(Entity.workspace_id == ws_id, Entity.is_system.is_(False), or_(*conds))
    if exclude_id:
        q = q.where(Entity.id != exclude_id)
    return list(db.scalars(q.limit(20)))


def _dup_warning(matches: list[Entity]) -> Warning_:
    return Warning_("DUPLICATE_ENTITY", "Possible duplicate Entity. Review the existing matches before continuing.",
                    matches=[{"id": m.id, "entity_number": m.entity_number, "display_name": m.display_name,
                              "entity_type": m.entity_type, "active": m.active, "email": m.email,
                              "city": m.city} for m in matches])


def _next_number(db: Session, ws_id: int) -> str:
    ws = db.get(Workspace, ws_id)
    n = ws.next_entity_number or 1
    ws.next_entity_number = n + 1
    return f"ENT-{n:06d}"


def create(db: Session, ctx, data) -> Entity:
    _validate_names(data.entity_type, data.organization_name, data.primary_contact)
    if data.is_financial_institution:
        ctx.require("entity.create_financial_institution")
    display = data.primary_contact if data.entity_type == "INDIVIDUAL" else data.organization_name
    matches = duplicates(db, ctx.workspace_id, display, data.email)
    if matches:
        require_confirmations([_dup_warning(matches)], data.confirmations)
    e = Entity(workspace_id=ctx.workspace_id, entity_number=_next_number(db, ctx.workspace_id),
               created_by_user_id=ctx.user.id, updated_by_user_id=ctx.user.id, active=True, is_system=False)
    for f in FIELDS:
        setattr(e, f, getattr(data, f))
    e.phone = clean_phone(data.phone)
    if e.entity_type != "INDIVIDUAL":
        e.position = None  # 1.6.7: a position belongs to a person
    e.is_financial_institution = bool(data.is_financial_institution)
    e.name_key = name_key(display)
    db.add(e)
    db.flush()
    audit.record(db, ctx, "ENTITY_CREATED", "entity", e.id, None, snapshot(e))
    return e


def _check_fi_permission(ctx, e: Entity) -> None:
    if e.is_financial_institution and not ctx.has("entity.manage_financial_institution"):
        raise forbidden("Only a Budget Manager may edit, inactivate or restore a Financial Institution Entity.")


def _check_not_organization(e: Entity) -> None:
    """2.1.0 (#314): the organization's own entity is maintained by Administrators in System/About."""
    if e.is_organization:
        raise AppError(409, "ORGANIZATION_ENTITY", "This is your organization's own entity. An Administrator changes "
                       "its details in System/About → General → Organization; it can't be inactivated.")


def update(db: Session, ctx, e: Entity, data) -> Entity:
    _check_not_organization(e)
    _check_fi_permission(ctx, e)
    before = snapshot(e)
    fields = data.model_fields_set - {"confirmations"}
    new = {f: (getattr(data, f) if f in fields else getattr(e, f)) for f in FIELDS}
    if new["is_financial_institution"] is None:
        new["is_financial_institution"] = e.is_financial_institution
    _validate_names(new["entity_type"], new["organization_name"], new["primary_contact"])
    if new["entity_type"] != "INDIVIDUAL":
        new["position"] = None
    if "phone" in fields:
        new["phone"] = clean_phone(data.phone, e.phone)
    display = new["primary_contact"] if new["entity_type"] == "INDIVIDUAL" else new["organization_name"]
    if name_key(display) != e.name_key or (new["email"] and new["email"] != e.email):
        matches = duplicates(db, ctx.workspace_id, display, new["email"], exclude_id=e.id)
        if matches:
            require_confirmations([_dup_warning(matches)], data.confirmations)
    for f in FIELDS:
        setattr(e, f, new[f])
    e.name_key = name_key(display)
    e.updated_by_user_id = ctx.user.id
    db.flush()
    audit.record(db, ctx, "ENTITY_UPDATED", "entity", e.id, before, snapshot(e))
    return e


def set_active(db: Session, ctx, e: Entity, active: bool, reason: str | None) -> Entity:
    _check_not_organization(e)
    _check_fi_permission(ctx, e)
    if e.active == active:
        raise AppError(409, "INVALID_STATE", "Entity is already " + ("active." if active else "inactive."))
    before = snapshot(e)
    e.active = active
    e.updated_by_user_id = ctx.user.id
    db.flush()
    audit.record(db, ctx, "ENTITY_RESTORED" if active else "ENTITY_INACTIVATED", "entity", e.id, before,
                 {**snapshot(e), "reason": reason})
    return e


def multiple_entity(db: Session, ws_id: int) -> Entity:
    return db.scalar(select(Entity).where(Entity.workspace_id == ws_id, Entity.is_system.is_(True)))
