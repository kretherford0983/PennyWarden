from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..models import Entity
from ..schemas import EntityCreateIn, EntityUpdateIn, OptionalReasonIn
from ..services import entities as svc

router = APIRouter(prefix="/api/entities", tags=["entities"])
SORTS = {"name": Entity.name_key, "entity_number": Entity.entity_number, "created_at": Entity.created_at}


@router.get("")
def list_entities(
    search: str | None = Query(None, max_length=200),
    status: Literal["active", "inactive", "all"] = "active",
    financial_institution: bool | None = None,
    sort: Literal["name", "entity_number", "created_at"] = "name",
    direction: Literal["asc", "desc"] = "asc",
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view")),
):
    q = select(Entity).where(Entity.workspace_id == ctx.workspace_id, Entity.is_system.is_(False))
    if status != "all":
        q = q.where(Entity.active.is_(status == "active"))
    if financial_institution is not None:
        q = q.where(Entity.is_financial_institution.is_(financial_institution))
    if search:
        like = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        # 2.2.0 (#315, #316): the name, the display name and the person's names
        full = func.coalesce(Entity.first_name, "") + " " + func.coalesce(Entity.last_name, "")
        q = q.where(or_(Entity.organization_name.ilike(like, escape="\\"), Entity.first_name.ilike(like, escape="\\"),
                        Entity.last_name.ilike(like, escape="\\"), full.ilike(like, escape="\\"),
                        Entity.display_name_custom.ilike(like, escape="\\"),
                        Entity.entity_number.ilike(like, escape="\\"), Entity.email.ilike(like, escape="\\")))
    col = SORTS[sort]
    q = q.order_by(col.desc() if direction == "desc" else col.asc(), Entity.id).limit(limit)
    return [svc.out(e) for e in db.scalars(q)]


@router.get("/duplicates")
def check_duplicates(name: str = Query(..., max_length=200), email: str | None = Query(None, max_length=254),
                     db: Session = Depends(get_db), ctx: Ctx = Depends(require("entity.manage"))):
    return [svc.out(e) for e in svc.duplicates(db, ctx.workspace_id, name, email)]


@router.get("/names-to-review")
def names_to_review(db: Session = Depends(get_db), ctx: Ctx = Depends(require("entity.review_names"))):
    """2.2.0 (#316): the names the upgrade split into first and last name, for a Budget Manager to check."""
    return [svc.out(e) for e in svc.names_to_review(db, ctx)]


@router.post("/{entity_id}/confirm-name")
def confirm_name(entity_id: int, db: Session = Depends(get_db),
                 ctx: Ctx = Depends(require("entity.review_names"))):
    e = svc.confirm_name(db, ctx, svc.get_visible(db, ctx, entity_id))
    db.commit()
    return svc.out(e)


@router.get("/{entity_id}")
def get_entity(entity_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("financial.view"))):
    return svc.out(svc.get_visible(db, ctx, entity_id))


@router.post("", status_code=201)
def create(body: EntityCreateIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("entity.manage"))):
    e = svc.create(db, ctx, body)
    db.commit()
    return svc.out(e)


@router.patch("/{entity_id}")
def update(entity_id: int, body: EntityUpdateIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("entity.manage"))):
    e = svc.update(db, ctx, svc.get_visible(db, ctx, entity_id), body)
    db.commit()
    return svc.out(e)


@router.post("/{entity_id}/inactivate")
def inactivate(entity_id: int, body: OptionalReasonIn, db: Session = Depends(get_db),
               ctx: Ctx = Depends(require("entity.manage"))):
    e = svc.set_active(db, ctx, svc.get_visible(db, ctx, entity_id), False, body.reason)
    db.commit()
    return svc.out(e)


@router.post("/{entity_id}/restore")
def restore(entity_id: int, body: OptionalReasonIn, db: Session = Depends(get_db),
            ctx: Ctx = Depends(require("entity.manage"))):
    e = svc.set_active(db, ctx, svc.get_visible(db, ctx, entity_id), True, body.reason)
    db.commit()
    return svc.out(e)


__all__ = ["func"]
