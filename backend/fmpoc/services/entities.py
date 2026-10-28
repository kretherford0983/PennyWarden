"""Entities: required names, duplicates, Entity Numbers, Financial Institution controls (BR-028..034)."""
from __future__ import annotations

import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import audit, phone as phone_fmt
from ..errors import AppError, Warning_, forbidden, not_found, require_confirmations, validation
from ..models import Entity, Workspace

FIELDS = ["entity_type", "organization_name", "first_name", "last_name", "position", "address_line1", "address_line2",
          "city", "state_region", "postal_code", "country", "phone", "email", "notes", "is_financial_institution",
          # 2.2.0 (#315): "same as" falls back at read time - empty means same
          "display_name_custom", "mailing_address_line1", "mailing_address_line2", "mailing_city",
          "mailing_state_region", "mailing_postal_code", "mailing_country", "ein"]
MAILING = ["mailing_address_line1", "mailing_address_line2", "mailing_city", "mailing_state_region",
           "mailing_postal_code", "mailing_country"]


def name_key(s: str | None) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(inc|llc|ltd|co|corp|corporation|company|the)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()[:200]


def snapshot(e: Entity) -> dict:
    return {"id": e.id, "entity_number": e.entity_number, "display_name": e.display_name, "name": e.legal_name,
            **{f: getattr(e, f) for f in FIELDS}, "active": e.active, "is_system": e.is_system,
            "is_organization": bool(e.is_organization), "name_review": bool(e.name_review)}


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
    return {**snapshot(e), "phone_display": phone_fmt.display(e.phone),
            "primary_contact": e.primary_contact or None,                 # 2.2.0 (#316): "First Last", read only
            "display_name_same": not (e.display_name_custom or "").strip(), "mailing_same": e.mailing_same,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "updated_at": e.updated_at.isoformat() if e.updated_at else None}


def get_visible(db: Session, ctx, entity_id: int) -> Entity:
    e = db.get(Entity, entity_id) if isinstance(entity_id, int) else None
    if e is None or e.workspace_id != ctx.workspace_id or e.is_system:  # Multiple is never exposed (BR-034)
        raise not_found("Entity")
    return e


def _validate_names(e_type: str, org: str | None, first: str | None) -> None:
    if e_type == "INDIVIDUAL" and not (first or "").strip():
        raise validation("First name is required for an Individual.", "first_name")
    if e_type == "ORGANIZATION" and not (org or "").strip():
        raise validation("Organization Name is required for an Organization.", "organization_name")


def split_name(full: str | None) -> tuple[str | None, str | None]:
    """2.2.0 (#316): "First Last..." split at the first space (one word = the first name), as the migration does."""
    name = " ".join((full or "").split())
    if not name:
        return None, None
    first, _, last = name.partition(" ")
    return first[:100], (last[:100] or None)


def _incoming(data, fields: set[str]) -> dict:
    """The writable values given: the legacy `primary_contact` is split into first and last name (#316); an EIN is
    tidied and checked (#315: organizations only)."""
    from .organization import EIN_RE, normalize_ein
    v = {f: getattr(data, f) for f in FIELDS if f in fields}
    if "primary_contact" in fields and not ({"first_name", "last_name"} & fields):
        v["first_name"], v["last_name"] = split_name(data.primary_contact)
    if "ein" in v:
        ein = normalize_ein(v["ein"])
        if ein and not EIN_RE.match(ein):
            raise validation("The EIN is 9 digits written as 12-3456789.", "ein")
        v["ein"] = ein
    for f in ("first_name", "last_name", "display_name_custom", *MAILING):
        if f in v:
            v[f] = (v[f] or "").strip() or None
    return v


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
    out = list(db.scalars(q.limit(20)))
    if key:                       # 2.2.0 (#315): an existing display name is a possible duplicate too
        for e in db.scalars(select(Entity).where(Entity.workspace_id == ws_id, Entity.is_system.is_(False),
                                                 Entity.display_name_custom.is_not(None))):
            if e.id != exclude_id and e not in out and name_key(e.display_name_custom) == key:
                out.append(e)
    return out[:20]


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


def _display_for(new: dict) -> str:
    if new["entity_type"] == "INDIVIDUAL":
        return " ".join(x for x in (new.get("first_name"), new.get("last_name")) if x)
    return new.get("organization_name") or ""


def _dup_matches(db: Session, ws_id: int, new: dict, exclude_id: int | None = None) -> list[Entity]:
    """BR-030 (#315): compares the name and, when one is set, the display name."""
    seen, out = set(), []
    for name in (_display_for(new), new.get("display_name_custom")):
        for m in duplicates(db, ws_id, name or "", new.get("email"), exclude_id) if name else []:
            if m.id not in seen:
                seen.add(m.id)
                out.append(m)
    if not out and new.get("email"):
        out = duplicates(db, ws_id, "", new.get("email"), exclude_id)
    return out


def create(db: Session, ctx, data) -> Entity:
    fields = set(data.model_fields_set) | {"entity_type"}
    new = {f: None for f in FIELDS}
    new.update(_incoming(data, fields))
    _validate_names(new["entity_type"], new["organization_name"], new["first_name"])
    if new["ein"] and new["entity_type"] != "ORGANIZATION":
        raise validation("An EIN is for organizations.", "ein")
    if data.is_financial_institution:
        ctx.require("entity.create_financial_institution")
    matches = _dup_matches(db, ctx.workspace_id, new)
    if matches:
        require_confirmations([_dup_warning(matches)], data.confirmations)
    e = Entity(workspace_id=ctx.workspace_id, entity_number=_next_number(db, ctx.workspace_id),
               created_by_user_id=ctx.user.id, updated_by_user_id=ctx.user.id, active=True, is_system=False)
    for f in FIELDS:
        setattr(e, f, new[f])
    e.phone = clean_phone(data.phone)
    if e.entity_type != "INDIVIDUAL":
        e.position = None  # 1.6.7: a position belongs to a person
    e.is_financial_institution = bool(data.is_financial_institution)
    e.name_key = name_key(e.legal_name)
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
    new = {f: getattr(e, f) for f in FIELDS}
    new.update(_incoming(data, fields))
    if new["is_financial_institution"] is None:
        new["is_financial_institution"] = e.is_financial_institution
    _validate_names(new["entity_type"], new["organization_name"], new["first_name"])
    if new["entity_type"] != "INDIVIDUAL":
        new["position"] = None
    if new["ein"] and new["entity_type"] != "ORGANIZATION":
        raise validation("An EIN is for organizations.", "ein")
    if "phone" in fields:
        new["phone"] = clean_phone(data.phone, e.phone)
    key = name_key(_display_for(new))
    changed_names = (key != e.name_key or (new["display_name_custom"] or None) != (e.display_name_custom or None))
    if changed_names or (new["email"] and new["email"] != e.email):
        matches = _dup_matches(db, ctx.workspace_id, new, exclude_id=e.id)
        if matches:
            require_confirmations([_dup_warning(matches)], data.confirmations)
    # #316: saving the names (the entity form always sends them) counts as reviewed
    name_edited = bool({"first_name", "last_name", "primary_contact"} & fields)
    for f in FIELDS:
        setattr(e, f, new[f])
    if name_edited:
        e.name_review = False                  # #316: an edited name is reviewed
    e.name_key = key
    e.updated_by_user_id = ctx.user.id
    db.flush()
    audit.record(db, ctx, "ENTITY_UPDATED", "entity", e.id, before, snapshot(e))
    return e


def names_to_review(db: Session, ctx) -> list[Entity]:
    """2.2.0 (#316): the names split by the upgrade, until each is edited or confirmed."""
    return list(db.scalars(select(Entity).where(Entity.workspace_id == ctx.workspace_id, Entity.is_system.is_(False),
                                                Entity.name_review.is_(True))
                           .order_by(Entity.last_name, Entity.first_name, Entity.id)))


def confirm_name(db: Session, ctx, e: Entity) -> Entity:
    if not e.name_review:
        return e
    e.name_review = False
    e.updated_by_user_id = ctx.user.id
    db.flush()
    audit.record(db, ctx, "ENTITY_NAME_CONFIRMED", "entity", e.id, {"name_review": True},
                 {"name_review": False, "first_name": e.first_name, "last_name": e.last_name})
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
