"""2.4.0 polish (#503): the organization's logos (System/About -> General -> Organization logos).

Four slots like Branding's: `full` (the logo), `mark` (the small mark of report footers) and their dark-background
versions. Every place that prints a logo has a Logo choice (BR-ORG-LOGO-002):

* ``ORG``  - the organization logo, read at print time, so replacing it changes every such place (AC-ORG-LOGO-002);
* ``OWN``  - the logo uploaded in that place (as before 2.4.0);
* ``NONE`` - no logo (the default for places that had none, and for new templates).

Letters, envelopes, the invoice PDF and donation letters use the `full` slot (paper is light); Branding chooses per slot.
Removing an organization logo lists the places that use it and needs a confirmation; they then print no logo
(BR-ORG-LOGO-003). Logos are organization settings (BR-003): Administrators manage them; uploads are validated and
re-encoded by content, without metadata (BR-096); every change is audit-logged with the fingerprint, never the image.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, validation
from ..models import (BrandingSettings, CheckDocument, DonationSettings, InvoiceSettings, OrganizationLogo,
                      utcnow)

SLOTS = ("full", "mark", "dark_full", "dark_mark")
SLOT_LABELS = {"full": "Logo", "mark": "Small mark", "dark_full": "Logo on dark backgrounds",
               "dark_mark": "Small mark on dark backgrounds"}
SOURCES = ("ORG", "OWN", "NONE")
MAX_BYTES = 2 * 1024 * 1024


def _row(db: Session, ws_id: int, slot: str) -> OrganizationLogo | None:
    return db.scalar(select(OrganizationLogo).where(OrganizationLogo.workspace_id == ws_id,
                                                    OrganizationLogo.slot == slot))


def get(db: Session, ws_id: int, slot: str = "full") -> OrganizationLogo | None:
    return _row(db, ws_id, slot) if slot in SLOTS else None


def png(db: Session, ws_id: int, slot: str = "full") -> bytes | None:
    r = get(db, ws_id, slot)
    return r.png if r is not None else None


def resolve(db: Session, ws_id: int, source: str | None, own: bytes | None, slot: str = "full") -> bytes | None:
    """The logo a place prints: the organization's (ORG), its own upload (OWN) or none."""
    if source == "ORG":
        return png(db, ws_id, slot)
    if source == "OWN":
        return own
    return None


def info(r: OrganizationLogo | None) -> dict | None:
    return {"width": r.width, "height": r.height, "version": r.sha256[:12]} if r is not None else None


def usage(db: Session, ws_id: int) -> dict[str, list[str]]:
    """Per slot, the places set to use the organization logo (for the removal warning, AC-ORG-LOGO-005)."""
    from .checkprint.service import doc_config
    used: dict[str, list[str]] = {s: [] for s in SLOTS}
    for d in db.scalars(select(CheckDocument).where(CheckDocument.workspace_id == ws_id, CheckDocument.active)
                        .order_by(CheckDocument.kind.desc(), CheckDocument.name)):
        if getattr(doc_config(d), "logo_source", "NONE") == "ORG":
            used["full"].append(f"{'Cover letter' if d.kind == 'LETTER' else 'Envelope'}: {d.name}")
    inv = db.scalar(select(InvoiceSettings).where(InvoiceSettings.workspace_id == ws_id))
    if inv is not None:
        from .invoice_template import stored
        if stored(inv).logo_source == "ORG":
            used["full"].append("Invoice PDF")
    don = db.scalar(select(DonationSettings).where(DonationSettings.workspace_id == ws_id))
    if don is not None:
        from .donations import ReceiptConfig
        try:
            cfg = ReceiptConfig.model_validate(json.loads(don.config_json))
        except ValueError:
            cfg = None
        if cfg is not None:
            if cfg.logo_source == "ORG":
                used["full"].append("Donation receipt letter")
            if statement_source(cfg) == "ORG":
                used["full"].append("Year-end statement letter")
    b = db.scalar(select(BrandingSettings).where(BrandingSettings.workspace_id == ws_id))
    for slot, src in branding_sources(b).items():
        if src == "ORG":
            used[slot].append(f"Branding: {SLOT_LABELS[slot].lower()}")
    return used


def statement_source(cfg) -> str:
    """The year-end statement's Logo choice: its own, or the receipt letter's (FOLLOW, the default)."""
    return cfg.logo_source if cfg.statement_logo_source == "FOLLOW" else cfg.statement_logo_source


def branding_sources(b: BrandingSettings | None) -> dict[str, str]:
    """Branding's Logo choice per slot; a slot not set yet is OWN (the logo uploaded in Branding, if any)."""
    try:
        raw = json.loads(b.logo_sources) if b is not None and b.logo_sources else {}
    except ValueError:
        raw = {}
    return {s: (raw.get(s) if raw.get(s) in SOURCES else "OWN") for s in SLOTS}


def view(db: Session, ctx) -> dict:
    return {"logos": {s: info(_row(db, ctx.workspace_id, s)) for s in SLOTS},
            "labels": SLOT_LABELS, "usage": usage(db, ctx.workspace_id)}


def set_logo(db: Session, ctx, slot: str, data: bytes | None, confirmations: list[str] | None = None) -> dict:
    """Sets (data) or removes (None) one organization logo. Removing one that places use needs the confirmation
    ORG_LOGO_IN_USE (409 CONFIRMATION_REQUIRED lists them); they then print no logo."""
    if slot not in SLOTS:
        raise validation("Choose the logo, the small mark or one of their dark-background versions.", "slot")
    from .checkprint.service import normalize_logo
    r = _row(db, ctx.workspace_id, slot)
    before = {"slot": slot, "sha256": r.sha256 if r else None}
    if data is None:
        if r is None:
            return view(db, ctx)
        places = usage(db, ctx.workspace_id)[slot]
        if places and "ORG_LOGO_IN_USE" not in (confirmations or []):
            raise AppError(409, "CONFIRMATION_REQUIRED", "This logo is used elsewhere; those places will print no "
                           "logo until a new one is added.",
                           warnings=[{"code": "ORG_LOGO_IN_USE", "message": "Used by: " + "; ".join(places),
                                      "details": {"places": places}}])
        db.delete(r)
        db.flush()
        audit.record(db, ctx, "ORGANIZATION_LOGO_REMOVED", "workspace", ctx.workspace_id, before,
                     {"slot": slot, "sha256": None, "places": places})
        return view(db, ctx)
    out_png, w, h = normalize_logo(data, max_bytes=MAX_BYTES)
    sha = hashlib.sha256(out_png).hexdigest()
    if r is None:
        r = OrganizationLogo(workspace_id=ctx.workspace_id, slot=slot, png=out_png, sha256=sha, width=w, height=h,
                             updated_by_user_id=ctx.user.id)
        db.add(r)
    else:
        r.png, r.sha256, r.width, r.height = out_png, sha, w, h
        r.updated_by_user_id, r.updated_at = ctx.user.id, utcnow()
    db.flush()
    audit.record(db, ctx, "ORGANIZATION_LOGO_SET", "workspace", ctx.workspace_id, before,
                 {"slot": slot, "sha256": sha, "width": w, "height": h})
    return view(db, ctx)
