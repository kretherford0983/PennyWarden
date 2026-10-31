"""2.3.0 (#395): one shared list of signers for checks and letters.

A signer (table check_signer, kept from #159) has a name, a title, an optional signature image (encrypted; never
downloadable) and *Used for* area tags, like the envelope library: CHECKS, COVER_LETTERS, DONATIONS (receipts and
year-end statements; INVOICES later, #218). Each area's settings offer only the signers tagged for it, and the backend
refuses a signer that isn't (BR-078/BR-099).

Each letter's settings choose a signer and how the signature is shown (MODES): NONE (the letter ends at the
closing), PRINTED (name and title), IMAGE (the image above the name and title) or SPACE (room to sign by hand above
the name). The image goes only into the printed/downloaded copy; the copy kept with the record shows the printed
name instead (`with_image=False`), the way a check's record copy does. A signer whose image is missing falls back
from IMAGE to SPACE (Setup warns).
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass

from reportlab.lib.units import inch
from reportlab.platypus import Image as RLImage, Paragraph, Spacer
from sqlalchemy import select
from sqlalchemy.orm import Session
from xml.sax.saxutils import escape

from .. import audit
from ..errors import conflict, validation
from ..models import CheckDocument, CheckSigner, CheckStyle, DonationSettings
from .common import get_scoped

CHECKS, COVER_LETTERS, DONATIONS = "CHECKS", "COVER_LETTERS", "DONATIONS"
AREAS = (CHECKS, COVER_LETTERS, DONATIONS)
LABELS = {CHECKS: "Checks", COVER_LETTERS: "Payment cover letters", DONATIONS: "Donation receipts and statements"}
AREA_MODULE = {CHECKS: "PAYMENTS", COVER_LETTERS: "PAYMENTS", DONATIONS: "DONATIONS"}
MODES = ("NONE", "PRINTED", "IMAGE", "SPACE")
MODE_LABELS = {"NONE": "None (the letter ends at the closing)", "PRINTED": "Printed name and title",
               "IMAGE": "Signature image and printed name", "SPACE": "Printed name with space to sign by hand"}
SAME_AS_CHECK = "SAME_AS_CHECK"
IMAGE_BOX = (2.2 * inch, 0.6 * inch)       # the signature image on a letter: scaled into this box


def areas_of(s: CheckSigner) -> list[str]:
    return [a for a in (s.areas or "").split(",") if a in AREAS]


def _set_areas(s: CheckSigner, areas: list[str]) -> None:
    s.areas = ",".join(a for a in AREAS if a in areas) or None


def get(db: Session, ctx, signer_id: int) -> CheckSigner:
    return get_scoped(db, CheckSigner, signer_id, ctx, "Signer")


def tagged(db: Session, ctx, area: str, active_only: bool = True) -> list[CheckSigner]:
    q = select(CheckSigner).where(CheckSigner.workspace_id == ctx.workspace_id)
    if active_only:
        q = q.where(CheckSigner.active.is_(True))
    return [s for s in db.scalars(q.order_by(CheckSigner.name, CheckSigner.id)) if area in areas_of(s)]


def require_tagged(db: Session, ctx, signer_id: int | None, area: str, field: str) -> CheckSigner | None:
    """A signer chosen in an area's settings: in this workspace, active, and tagged for the area."""
    if signer_id is None:
        return None
    s = db.get(CheckSigner, signer_id) if isinstance(signer_id, int) else None
    if s is None or s.workspace_id != ctx.workspace_id:
        raise validation("That signer does not exist.", field)
    if not s.active:
        raise validation(f"{s.name} is retired; choose another signer.", field)
    if area not in areas_of(s):
        raise validation(f"{s.name} is not tagged for {LABELS[area].lower()} (Signers page).", field)
    return s


def usage(db: Session, ctx, s: CheckSigner) -> list[str]:
    """Where a signer is in use (it can't be retired, or lose that area's tag, until those settings change)."""
    out: list[str] = []
    for st in db.scalars(select(CheckStyle).where(CheckStyle.workspace_id == ctx.workspace_id,
                                                  CheckStyle.active.is_(True))):
        try:
            cfg = json.loads(st.config_json or "{}")
        except ValueError:
            continue
        if s.id in (cfg.get("default_signer_id"), cfg.get("default_signer2_id")):
            out.append(f"{CHECKS}:Check style {st.name}")
    row = db.scalar(select(DonationSettings).where(DonationSettings.workspace_id == ctx.workspace_id))
    if row is not None:
        try:
            cfg = json.loads(row.config_json or "{}")
        except ValueError:
            cfg = {}
        if cfg.get("signer_id") == s.id and cfg.get("signature_mode", "NONE") != "NONE":
            out.append(f"{DONATIONS}:Donation receipt")
        if cfg.get("statement_signer_id") == s.id:
            out.append(f"{DONATIONS}:Year-end statement")
    for d in db.scalars(select(CheckDocument).where(CheckDocument.workspace_id == ctx.workspace_id,
                                                    CheckDocument.kind == "LETTER", CheckDocument.active.is_(True))):
        try:
            cfg = json.loads(d.config_json or "{}")
        except ValueError:
            continue
        if cfg.get("signer_id") == s.id:
            out.append(f"{COVER_LETTERS}:Cover letter {d.name}")
    return out


def out(db: Session, ctx, s: CheckSigner) -> dict:
    used = usage(db, ctx, s)
    return {"id": s.id, "name": s.name, "title": s.title, "active": s.active, "has_image": bool(s.image_ciphertext),
            "image_uploaded_at": s.image_uploaded_at.isoformat() if s.image_uploaded_at else None,
            "areas": areas_of(s), "in_use": [u.split(":", 1)[1] for u in used],
            "in_use_areas": sorted({u.split(":", 1)[0] for u in used})}


def set_areas(db: Session, ctx, s: CheckSigner, areas: list[str]) -> CheckSigner:
    bad = [a for a in areas if a not in AREAS]
    if bad:
        raise validation("Unknown area.", "areas")
    used = {u.split(":", 1)[0] for u in usage(db, ctx, s)}
    dropped = [a for a in used if a not in areas]
    if dropped:
        raise conflict("SIGNER_IN_USE", f"{s.name} is in use for " + ", ".join(LABELS[a].lower() for a in dropped)
                       + "; change those settings first.")
    before = areas_of(s)
    _set_areas(s, areas)
    db.flush()
    if areas_of(s) != before:
        audit.record(db, ctx, "SIGNER_AREAS_CHANGED", "check_signer", s.id, {"areas": before}, {"areas": areas_of(s)},
                     category="SECURITY")
    return s


def check_can_retire(db: Session, ctx, s: CheckSigner) -> None:
    used = usage(db, ctx, s)
    if used:
        raise conflict("SIGNER_IN_USE", f"{s.name} is in use ({', '.join(u.split(':', 1)[1] for u in used)}); choose "
                                        "another signer there first.")


# ------------------------------------------------------------------ 2.3.0 polish: the signer chosen when printing
# (Kyle, 2026-10-31) A letter's settings can leave the signer to be chosen when printing (AT_PRINT), with the
# setting's signer as the default. The Register User is asked only when more than one active signer is tagged for
# the area; with one, that one signs. Applies to donation receipts, year-end statements and payment cover letters.
FIXED, AT_PRINT = "FIXED", "AT_PRINT"


def signing_out(db: Session, ctx, area: str, choice: str, default_id: int | None, mode: str,
                last_id: int | None = None) -> dict:
    """What a print screen needs: whether to ask, the signers to offer and the one to start from (`last_id`, the
    signer of the copy being reprinted, when still usable; else the setting's default; else the first)."""
    if choice != AT_PRINT or mode == "NONE":
        return {"choice": choice if mode != "NONE" else FIXED, "ask": False, "signers": [], "default_id": None}
    opts = tagged(db, ctx, area)
    ids = [s.id for s in opts]
    pick = next((x for x in (last_id, default_id) if x in ids), ids[0] if ids else None)
    return {"choice": AT_PRINT, "ask": len(opts) > 1, "default_id": pick,
            "signers": [{"id": s.id, "name": s.name, "title": s.title or ""} for s in opts]}


def chosen(db: Session, ctx, area: str, choice: str, default_id: int | None, signer_id: int | None,
           field: str = "signer_id") -> int | None:
    """The signer for this print. FIXED: the setting's signer (a different one is refused - BR-098/BR-099).
    AT_PRINT: the chosen signer (tagged for the area, active), else the default, else the only tagged signer."""
    if choice != AT_PRINT:
        if signer_id is not None and signer_id != default_id:
            raise validation("The signer for this letter is set in its settings and can't be changed when printing.",
                             field)
        return default_id
    if signer_id is not None:
        return require_tagged(db, ctx, signer_id, area, field).id
    ids = [s.id for s in tagged(db, ctx, area)]
    if default_id in ids:
        return default_id
    if len(ids) == 1:
        return ids[0]
    if not ids:
        return None
    raise validation("Choose who signs this letter.", field)


# ------------------------------------------------------------------ the signature on a letter
@dataclass
class SignatureBlock:
    mode: str = "NONE"                   # NONE | PRINTED | IMAGE | SPACE (IMAGE without an image -> SPACE)
    name: str = ""
    title: str = ""
    image: bytes | None = None           # PNG, only for the printed copy (never the record copy)


def block_for(km, s: CheckSigner | None, mode: str, with_image: bool) -> SignatureBlock:
    if s is None or mode == "NONE":
        return SignatureBlock()
    if mode == "IMAGE":
        if not s.image_ciphertext:
            mode = "SPACE"
        elif not with_image or km is None:
            # the record copy: the printed name in place of the image (as a check's record copy)
            return SignatureBlock(mode="PRINTED", name=s.name, title=s.title or "")
        else:
            from .checkprint.service import signature_png
            return SignatureBlock(mode="IMAGE", name=s.name, title=s.title or "", image=signature_png(km, s))
    return SignatureBlock(mode=mode, name=s.name, title=s.title or "")


def flowables(b: SignatureBlock, style, bold_font: str, size: float, extra_title: str = "") -> list:
    """The signature under a letter's closing: image (IMAGE), room to sign (SPACE), then the name and title."""
    if b.mode == "NONE" or not b.name:
        return []
    out: list = []
    if b.mode == "IMAGE" and b.image:
        from PIL import Image as PILImage
        with PILImage.open(io.BytesIO(b.image)) as im:
            w, h = im.size
        bw, bh = IMAGE_BOX
        scale = min(bw / w, bh / h)
        img = RLImage(io.BytesIO(b.image), width=w * scale, height=h * scale)
        img.hAlign = "LEFT"
        out += [Spacer(1, size * 0.4), img]
    elif b.mode == "SPACE":
        out.append(Spacer(1, size * 2.6))
    else:
        out.append(Spacer(1, size * 0.6))
    lines = [f"<font name='{bold_font}'>{escape(b.name)}</font>"]
    title = ", ".join(x for x in (b.title, extra_title) if x)
    if title:
        lines.append(escape(title))
    out.append(Paragraph("<br/>".join(lines), style))
    return out
