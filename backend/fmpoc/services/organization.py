"""2.1.0 (#314): the organization profile - the organization itself as an Organization entity, one per workspace.

Administrators maintain it in System/About (name, address, phone, email, EIN); the name is kept the same as the
workspace name. Everyone with entity access can choose it wherever an entity is chosen (e.g. a lump cash deposit),
but it can't be edited or inactivated in Entities. Its details feed the {ORG.*} template variables."""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from .. import phone as phone_fmt
from ..errors import validation
from ..models import Entity, Workspace
from . import admin_settings as adm
from . import entities as ent_svc

EIN_RE = re.compile(r"^\d{2}-\d{7}$")
PROFILE_FIELDS = ("address_line1", "address_line2", "city", "state_region", "postal_code", "country", "phone", "email",
                  "ein")


def normalize_ein(typed: str | None) -> str | None:
    """9 digits typed with or without the dash (123456789, 12 3456789) -> 12-3456789; anything else as typed."""
    t = (typed or "").strip()
    if not t:
        return None
    d = re.sub(r"[\s-]", "", t)
    return f"{d[:2]}-{d[2:]}" if re.fullmatch(r"\d{9}", d) else t


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(max_length=adm.ORG_NAME_MAX * 2)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state_region: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=254)
    ein: str | None = Field(default=None, max_length=10)


def get(db: Session, ws_id: int | None) -> Entity | None:
    if not ws_id:
        return None
    return db.scalar(select(Entity).where(Entity.workspace_id == ws_id, Entity.is_organization.is_(True))
                     .order_by(Entity.id))


def ensure(db: Session, ws: Workspace) -> Entity:
    """The workspace's organization entity, created (named like the workspace) when there is none."""
    e = get(db, ws.id)
    if e is None:
        e = Entity(workspace_id=ws.id, entity_number=ent_svc._next_number(db, ws.id), entity_type="ORGANIZATION",
                   organization_name=ws.name, is_organization=True, is_system=False, is_financial_institution=False,
                   active=True, name_key=ent_svc.name_key(ws.name))
        db.add(e)
        db.flush()
    return e


def address_lines(e: Entity | None) -> list[str]:
    from .checkprint.service import address_lines as lines
    return lines(e)


def values(e: Entity | None, ws: Workspace | None) -> dict[str, str]:
    """The {ORG.*} template variables (and the older {ORG} / {ORG_*} names)."""
    name = (e.organization_name if e else None) or (ws.name if ws else "") or ""
    g = (lambda f: (getattr(e, f) or "").strip() if e else "")
    from .. import phone as phone_fmt
    out = {"ORG": name, "ORG.NAME": name, "ORG.ADDRESS": "\n".join(address_lines(e)),
           "ORG.ADDRESS1": g("address_line1"), "ORG.ADDRESS2": g("address_line2"), "ORG.CITY": g("city"),
           "ORG.STATE": g("state_region"), "ORG.ZIP": g("postal_code"), "ORG.COUNTRY": g("country"),
           "ORG.PHONE": phone_fmt.display(e.phone) if e and e.phone else "", "ORG.EMAIL": g("email"),
           "ORG.EIN": g("ein")}
    out.update({"ORG_NAME": out["ORG.NAME"], "ORG_ADDRESS": out["ORG.ADDRESS"], "ORG_EIN": out["ORG.EIN"]})
    return out


def values_for(db: Session, ws_id: int) -> dict[str, str]:
    return values(get(db, ws_id), db.get(Workspace, ws_id))


SAMPLE = {"ORG": "Sample Organization", "ORG.NAME": "Sample Organization",
          "ORG.ADDRESS": "100 Sample Avenue\nSample Town, US 55555", "ORG.ADDRESS1": "100 Sample Avenue",
          "ORG.ADDRESS2": "", "ORG.CITY": "Sample Town", "ORG.STATE": "US", "ORG.ZIP": "55555", "ORG.COUNTRY": "",
          "ORG.PHONE": "(555) 555-0100", "ORG.EMAIL": "office@example.org", "ORG.EIN": "00-0000000"}


def snapshot(e: Entity) -> dict:
    return {"name": e.organization_name, **{f: getattr(e, f) for f in PROFILE_FIELDS}}


def profile_out(db: Session, ws_id: int) -> dict:
    ws = db.get(Workspace, ws_id)
    e = ensure(db, ws)
    return {"id": e.id, "entity_number": e.entity_number, "name": ws.name,
            **{f: getattr(e, f) for f in PROFILE_FIELDS}, "address": address_lines(e),
            "phone_display": phone_fmt.display(e.phone)}          # shown like an entity's phone (1.6.7)


def update(db: Session, ctx, data: ProfileIn) -> dict:
    ws = db.get(Workspace, ctx.workspace_id)
    e = ensure(db, ws)
    before = snapshot(e)
    adm.rename_organization(db, ctx, data.name)          # validates; audits ORGANIZATION_RENAMED when it changes
    given = data.model_fields_set                         # fields left out keep their value
    if "ein" in given:
        ein = normalize_ein(data.ein)
        if ein and not EIN_RE.match(ein):
            raise validation("The EIN is 9 digits written as 12-3456789.", "ein")
        e.ein = ein
    for f in PROFILE_FIELDS:
        if f in ("ein", "phone") or f not in given:
            continue
        if any(ord(c) < 32 for c in (getattr(data, f) or "")):
            raise validation("Control characters are not allowed.", f)
        setattr(e, f, (getattr(data, f) or "").strip() or None)
    if "phone" in given:
        e.phone = ent_svc.clean_phone(data.phone, e.phone)
    e.organization_name = ws.name
    e.name_key = ent_svc.name_key(ws.name)
    e.updated_by_user_id = ctx.user.id
    db.flush()
    after = snapshot(e)
    if before != after:
        # on the workspace, like ORGANIZATION_RENAMED: the Administrator who made it sees it (not transaction content)
        audit.record(db, ctx, "ORGANIZATION_UPDATED", "workspace", ws.id, before, {**after, "entity_id": e.id})
    return profile_out(db, ctx.workspace_id)


def sync_name(db: Session, ws: Workspace) -> None:
    """After a rename: the organization entity carries the new name."""
    e = get(db, ws.id)
    if e is not None and e.organization_name != ws.name:
        e.organization_name, e.name_key = ws.name, ent_svc.name_key(ws.name)
