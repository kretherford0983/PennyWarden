"""2.2.0 (#325): the shared envelope library (Administrators).

One library of envelope templates, tagged by feature (Payments, Donations), each feature with its own default. The
global Envelopes page lists every template (untagged ones as *Not used*) and can add or remove any tag; each
feature's setup page manages its own tag through the same routes. Templates are created, edited, previewed and
test printed through /api/checks/documents (open to an Administrator while either module is on). Templates are
never deleted (BR-001): printed copies refer to them."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db
from ..services import envelopes as svc
from ..services.checkprint import config as cfgmod
from ..services.checkprint import fonts, patterns
from ..services.checkprint import service as cp
from .checks import doc_ctx

router = APIRouter(prefix="/api/envelopes", tags=["envelopes"])

Feature = Literal["PAYMENTS", "DONATIONS"]


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TagIn(In):
    feature: Feature
    on: bool
    new_default_id: int | None = None     # removing the tag from the feature's default: the next default


class FeatureIn(In):
    feature: Feature


def _out(db: Session, ctx: Ctx) -> dict:
    return {**svc.library(db, ctx), "envelope_variables": patterns.variable_options(patterns.ENVELOPE),
            "fonts": fonts.options(), "font_sizes": {"min": fonts.MIN_SIZE, "max": fonts.MAX_SIZE},
            "limits": {"clear_zone": cfgmod.CLEAR_ZONE, "feed_offset_max": cfgmod.FEED_OFFSET_MAX,
                       "personal_max": cfgmod.PERSONAL_MAX}}


@router.get("")
def library(db: Session = Depends(get_db), ctx: Ctx = Depends(doc_ctx)):
    return _out(db, ctx)


@router.post("/{doc_id}/tags")
def set_tag(doc_id: int, body: TagIn, db: Session = Depends(get_db), ctx: Ctx = Depends(doc_ctx)):
    svc.require_feature(db, ctx, body.feature)
    svc.set_tag(db, ctx, cp.get_document(db, ctx, doc_id, "ENVELOPE"), body.feature, body.on, body.new_default_id)
    db.commit()
    return _out(db, ctx)


@router.post("/{doc_id}/default")
def set_default(doc_id: int, body: FeatureIn, db: Session = Depends(get_db), ctx: Ctx = Depends(doc_ctx)):
    svc.require_feature(db, ctx, body.feature)
    svc.set_default(db, ctx, cp.get_document(db, ctx, doc_id, "ENVELOPE"), body.feature)
    db.commit()
    return _out(db, ctx)


@router.post("/{doc_id}/duplicate-for", status_code=201)
def duplicate_for(doc_id: int, body: FeatureIn, db: Session = Depends(get_db), ctx: Ctx = Depends(doc_ctx)):
    """*Duplicate for <feature> only*: a copy for this feature; the tag (and default) move to the copy."""
    svc.require_feature(db, ctx, body.feature)
    copy = svc.duplicate_for(db, ctx, cp.get_document(db, ctx, doc_id, "ENVELOPE"), body.feature)
    db.commit()
    return {**_out(db, ctx), "created": svc.out(db, ctx, copy)}
