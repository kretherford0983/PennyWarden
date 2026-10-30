"""2.3.0 (#376): Report settings - how the Reports catalog is grouped (Administrators; read by every user's catalog)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..deps import Ctx, auth_ctx, get_db, require
from ..services import report_grouping as svc

router = APIRouter(tags=["reports"])


class CategoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, max_length=20)
    name: str = Field(max_length=svc.MAX_NAME + 10)
    short: str | None = Field(default=None, max_length=40)
    reports: list[str] = Field(default_factory=list, max_length=50)


class GroupingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheme: Literal["PURPOSE", "SUBJECT", "AUDIENCE"]
    categories: list[CategoryIn] | None = Field(default=None, max_length=svc.MAX_CATEGORIES + 5)


class ResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scheme: Literal["PURPOSE", "SUBJECT", "AUDIENCE"]


@router.get("/api/reports/grouping")
def grouping(db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)):
    """The categories the Reports catalog shows (display only; each report's own checks decide who can run it)."""
    return svc.active(db, ctx.workspace_id)


@router.get("/api/system/report-settings")
def view(db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    return svc.admin_view(db, ctx)


@router.put("/api/system/report-settings")
def save(body: GroupingIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    cats = None if body.categories is None else [c.model_dump() for c in body.categories]
    out = svc.save(db, ctx, body.scheme, cats)
    db.commit()
    return out


@router.post("/api/system/report-settings/reset")
def reset(body: ResetIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("system.manage"))):
    out = svc.reset(db, ctx, body.scheme)
    db.commit()
    return out
