"""2.1.0 (#312): the Donations module, part 1 - donation receipt letters.

Who does what (docs/04 permission matrix):
- Administrators (donation.setup): switch the module on/off (modules.manage), set the organization's EIN and mailing
  address, the receipt template and the default signer's name and title, and test print with sample data only. Nothing
  here gives them deposits, donors or amounts (BR-003).
- Register Users (donation.print): mark deposit lines as donations (with a purpose and any goods or services given in
  exchange) and print receipts.
- Budget Managers, Budget Users, Register Users and Auditors (donation.view): see a deposit's donation lines and
  receipts. The printed copies are attachments of the deposit.

Receipts come only from recorded deposits: one receipt per donor (the line's entity, else the deposit's), covering
that donor's donation lines. The acknowledgment block (organization and EIN, donor, amount, date received, receipt
number and the goods or services statement) is always printed and is not part of the editable template.

Reprints: the same content again prints a DUPLICATE (the same number, referencing it); changed content prints a
CORRECTED receipt with a new number that replaces the last one. A voided or deleted deposit can't be printed and its
receipts show as void. Receipts are never deleted.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
from dataclasses import dataclass, field
from typing import Literal
from xml.sax.saxutils import escape

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, Warning_, conflict, not_found, require_confirmations, validation
from ..models import (Attachment, DonationLine, DonationReceipt, DonationSettings, Entity, RegisterTransaction, User,
                      Workspace, utcnow)
from . import register as reg
from .checkprint import config as cfgmod
from . import organization as org_svc
from .checkprint import fonts, patterns
from .checkprint.service import _commit_or_unlink, _store_doc_copy, address_lines, format_date
from .common import get_scoped

RECEIPT_COPY = "DONATION_RECEIPT"          # Attachment.document_type of a receipt's record copy (system generated)
ORIGINAL, DUPLICATE, CORRECTED = "ORIGINAL", "DUPLICATE", "CORRECTED"
PT = 72.0
NO_GOODS = "No goods or services were provided in exchange for this contribution."


# ------------------------------------------------------------------ module switch
def module_enabled(db: Session, ws_id: int | None) -> bool:
    ws = db.get(Workspace, ws_id) if ws_id else None
    return bool(ws and ws.donations_enabled)


def require_module(db: Session, ctx) -> None:
    if not module_enabled(db, ctx.workspace_id):
        raise AppError(404, "MODULE_DISABLED", "The Donations module is not turned on.")


def set_module(db: Session, ctx, enabled: bool) -> bool:
    ws = db.get(Workspace, ctx.workspace_id)
    before = bool(ws.donations_enabled)
    if before != enabled:
        ws.donations_enabled = enabled
        audit.record(db, ctx, "MODULE_ENABLED" if enabled else "MODULE_DISABLED", "module", "donations",
                     {"donations_enabled": before}, {"donations_enabled": enabled}, category="SECURITY")
    return enabled


# ------------------------------------------------------------------ setup (Administrator)
def _check(text: str, what: str) -> None:
    try:
        patterns.parse(text, patterns.RECEIPT)
    except patterns.PatternError as e:
        raise ValueError(f"{what}: {e}") from None


class ReceiptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    font: Literal["SANS", "SERIF", "CARLITO"] = "CARLITO"
    size: float = Field(default=11, ge=8, le=14)
    date_format: Literal["MM/DD/YYYY", "MM/DD/YY", "YYYY-MM-DD", "MONTH D, YYYY"] = "MONTH D, YYYY"
    title: str = Field(default="Donation Receipt", max_length=120)
    salutation: str = Field(default="Dear {DONOR_NAME},", max_length=200)
    body: str = Field(default="Thank you for your generous contribution to {ORG.NAME}. Your support makes our work "
                              "possible.\n\nPlease keep this letter as the written acknowledgment of your "
                              "contribution.", max_length=2000)
    closing: str = Field(default="With gratitude,", max_length=200)
    signer_name: str = Field(default="", max_length=120)
    signer_title: str = Field(default="", max_length=120)

    @model_validator(mode="before")
    @classmethod
    def _moved(cls, v):
        """2.1.0 (#314): the EIN and address moved to the organization profile; older saved settings carry them."""
        if isinstance(v, dict):
            v = {k: x for k, x in v.items() if k not in ("ein", "org_address")}
        return v

    @model_validator(mode="after")
    def _patterns(self):
        for name in ("title", "salutation", "body", "closing"):
            _check(getattr(self, name), name.capitalize())
        return self


def _config_error(e: ValidationError) -> AppError:
    errs = [{"field": ".".join(str(p) for p in err.get("loc", ())) or None,
             "message": err.get("msg", "Invalid value.").removeprefix("Value error, ")} for err in e.errors()]
    return AppError(422, "VALIDATION_ERROR", errs[0]["message"] if errs else "The receipt settings are not valid.",
                    errors=errs)


def parse_config(data: dict) -> ReceiptConfig:
    try:
        return ReceiptConfig.model_validate(data)
    except ValidationError as e:
        raise _config_error(e) from None


def _settings_row(db: Session, ws_id: int) -> DonationSettings | None:
    return db.scalar(select(DonationSettings).where(DonationSettings.workspace_id == ws_id))


def get_config(db: Session, ws_id: int) -> ReceiptConfig:
    row = _settings_row(db, ws_id)
    return ReceiptConfig.model_validate(json.loads(row.config_json)) if row else ReceiptConfig()


def missing_setup(db: Session, ws_id: int) -> list[str]:
    """What a receipt can't be printed without (#314: from the organization profile in System/About)."""
    e = org_svc.get(db, ws_id)
    out = []
    if not (e and e.ein):
        out.append("the organization's EIN")
    if not org_svc.address_lines(e):
        out.append("the organization's address")
    return out


def organization_out(db: Session, ws_id: int) -> dict:
    v = org_svc.values_for(db, ws_id)
    return {"name": v["ORG.NAME"], "address": [x for x in v["ORG.ADDRESS"].split("\n") if x], "ein": v["ORG.EIN"]}


def setup_out(db: Session, ctx) -> dict:
    cfg = get_config(db, ctx.workspace_id)
    row = _settings_row(db, ctx.workspace_id)
    return {"config": cfg.model_dump(), "defaults": ReceiptConfig().model_dump(), "saved": row is not None,
            "missing": missing_setup(db, ctx.workspace_id), "organization": organization_out(db, ctx.workspace_id),
            "variables": patterns.variable_options(patterns.RECEIPT),
            "date_formats": list(cfgmod.DATE_FORMATS), "no_goods_statement": NO_GOODS}


def save_config(db: Session, ctx, data: dict) -> ReceiptConfig:
    cfg = parse_config(data)
    row = _settings_row(db, ctx.workspace_id)
    before = json.loads(row.config_json) if row else None
    if row is None:
        row = DonationSettings(workspace_id=ctx.workspace_id, config_json="{}")
        db.add(row)
    after = cfg.model_dump()
    row.config_json = json.dumps(after, sort_keys=True)
    row.updated_at, row.updated_by_user_id = utcnow(), ctx.user.id
    db.flush()
    if before != after:
        audit.record(db, ctx, "DONATION_SETUP_UPDATED", "donation_settings", row.id, before, after)
    return cfg


# ------------------------------------------------------------------ rendering
@dataclass
class ReceiptData:
    number: str
    kind: str
    kind_note: str                       # "" for an ORIGINAL
    org: dict[str, str]                  # #314: the {ORG.*} values of the organization profile
    donor_name: str
    donor_address: list[str]
    amount_cents: int
    date_received: dt.date
    purposes: list[str]
    goods: list[tuple[int, str]] = field(default_factory=list)       # (cents, description) per line with goods
    today: dt.date = field(default_factory=dt.date.today)


def money(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def goods_statement(goods: list[tuple[int, str]]) -> str:
    total = sum(c for c, _d in goods)
    if total <= 0:
        return NO_GOODS
    desc = "; ".join(d for _c, d in goods if d)
    return (f"Goods or services valued at {money(total)} were provided in exchange for this contribution"
            + (f" ({desc})" if desc else "") + ".")


def values_for(cfg: ReceiptConfig, data: ReceiptData) -> dict[str, str]:
    return {"DONOR_NAME": data.donor_name, "DONOR_ADDRESS": "\n".join(data.donor_address),
            "AMOUNT": f"{data.amount_cents // 100:,}.{data.amount_cents % 100:02d}",
            "DATE_RECEIVED": format_date(data.date_received, cfg.date_format),
            "PURPOSE": "; ".join(data.purposes), **data.org, "RECEIPT_NO": data.number, "SIGNER": cfg.signer_name,
            "SIGNER_TITLE": cfg.signer_title, "TODAY": format_date(data.today, cfg.date_format)}


def receipt_texts(cfg: ReceiptConfig, data: ReceiptData) -> tuple[dict, list[str]]:
    vals = values_for(cfg, data)
    empty: list[str] = []
    out = {}
    for name in ("title", "salutation", "body", "closing"):
        r = patterns.resolve(getattr(cfg, name), vals, patterns.RECEIPT)
        out[name] = r.text
        empty += [v for v in r.empty if v not in empty]
    return out, empty


def _paras(text: str) -> list[str]:
    return ["<br/>".join(escape(x) for x in p.split("\n")) for p in text.split("\n\n") if p.strip()]


def receipt_pdf(cfg: ReceiptConfig, data: ReceiptData, sample: bool = False) -> bytes:
    """The receipt letter. `sample` (setup preview and test print) draws SAMPLE - NOT A RECEIPT across the page."""
    texts, _empty = receipt_texts(cfg, data)
    reg_f, bold = fonts.ps_name(cfg.font), fonts.ps_name(cfg.font, True)
    size = cfg.size
    base = ParagraphStyle("base", fontName=reg_f, fontSize=size, leading=size * 1.3)
    strong = ParagraphStyle("strong", parent=base, fontName=bold)
    title = ParagraphStyle("title", parent=strong, fontSize=size + 3, leading=(size + 3) * 1.3)
    small = ParagraphStyle("small", parent=base, fontSize=size - 1.5, leading=(size - 1.5) * 1.3)

    def page(c, _doc):
        c.saveState()
        if data.kind != ORIGINAL:
            c.setFont(bold, 9)
            c.setFillGray(0.35)
            c.drawRightString(7.5 * PT, 10.55 * PT, data.kind)
        if sample:
            c.setFillGray(0.86)
            c.setFont(bold, 46)
            c.translate(4.25 * PT, 5.5 * PT)
            c.rotate(35)
            c.drawCentredString(0, 0, "SAMPLE - NOT A RECEIPT")
        c.restoreState()

    story = [Paragraph(escape(data.org["ORG.NAME"]), strong)]
    story += [Paragraph(escape(x), base) for x in data.org["ORG.ADDRESS"].split("\n") if x]
    story += [Spacer(1, size * 1.2), Paragraph(escape(format_date(data.today, cfg.date_format)), base),
              Spacer(1, size * 1.2)]
    story += [Paragraph(escape(x), base) for x in [data.donor_name] + data.donor_address]
    story.append(Spacer(1, size * 1.4))
    if texts["title"].strip():
        story += [Paragraph(escape(texts["title"]), title), Spacer(1, size * 0.4)]
    head = f"Receipt No. {data.number}"
    story += [Paragraph(escape(head), strong)]
    if data.kind_note:
        story.append(Paragraph(escape(data.kind_note), small))
    story.append(Spacer(1, size))
    for key in ("salutation", "body"):
        for p in _paras(texts[key]):
            story += [Paragraph(p, base), Spacer(1, size * 0.7)]
    # the acknowledgment block: always printed, not part of the template
    rows = [("Organization", data.org["ORG.NAME"]), ("EIN", data.org["ORG.EIN"]), ("Donor", data.donor_name),
            ("Date received", format_date(data.date_received, cfg.date_format)),
            ("Amount", money(data.amount_cents))]
    if data.purposes:
        rows.append(("Purpose", "; ".join(data.purposes)))
    rows.append(("Receipt No.", data.number))
    tbl = Table([[Paragraph(escape(k), strong), Paragraph(escape(v), base)] for k, v in rows],
                colWidths=[1.6 * inch, 4.9 * inch], hAlign="LEFT")
    tbl.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, "#666666"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3),
                             ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
    story.append(KeepTogether([tbl, Spacer(1, size * 0.6), Paragraph(escape(goods_statement(data.goods)), strong)]))
    story.append(Spacer(1, size * 1.2))
    block = [Paragraph(escape(texts["closing"]), base)] if texts["closing"].strip() else []
    sign = []
    if cfg.signer_name:
        sign.append(f"<font name='{bold}'>{escape(cfg.signer_name)}</font>")
    if cfg.signer_title:
        sign.append(escape(", ".join(x for x in (cfg.signer_title, data.org["ORG.NAME"]) if x)))
    if sign:                                            # room to sign by hand above the name (no signature image)
        block += [Spacer(1, size * 2.6), Paragraph("<br/>".join(sign), base)]
    if block:
        story.append(KeepTogether(block))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=(8.5 * inch, 11 * inch), leftMargin=inch, rightMargin=inch,
                            topMargin=inch, bottomMargin=inch, title=f"Donation receipt {data.number}",
                            creator="PennyWarden", author="", subject="", invariant=1)
    doc.build(story, onFirstPage=page, onLaterPages=page)
    return buf.getvalue()


SAMPLE_DONOR = ["SAMPLE DONOR", "123 Main Street", "Sample Town, US 55555"]


def _org_or_placeholders(db: Session, ws_id: int) -> dict[str, str]:
    """The preview shows the real organization profile (not financial data), with placeholders for what's missing."""
    v = dict(org_svc.values_for(db, ws_id))
    if not v["ORG.ADDRESS"]:
        v["ORG.ADDRESS"] = v["ORG_ADDRESS"] = "(organization address - System/About)"
    if not v["ORG.EIN"]:
        v["ORG.EIN"] = v["ORG_EIN"] = "00-0000000"
    return v


def sample_data(db: Session, ctx, cfg: ReceiptConfig) -> ReceiptData:
    return ReceiptData(number=f"R-{dt.date.today().year}-0000", kind=ORIGINAL, kind_note="",
                       org=_org_or_placeholders(db, ctx.workspace_id), donor_name=SAMPLE_DONOR[0], donor_address=SAMPLE_DONOR[1:],
                       amount_cents=25000, date_received=dt.date.today(), purposes=["General support"])


def sample_pdf(db: Session, ctx, data: dict | None) -> bytes:
    cfg = parse_config(data) if data is not None else get_config(db, ctx.workspace_id)
    return receipt_pdf(cfg, sample_data(db, ctx, cfg), sample=True)


# ------------------------------------------------------------------ deposits: marking and receipts
def get_deposit(db: Session, ctx, txn_id: int) -> RegisterTransaction:
    t = get_scoped(db, RegisterTransaction, txn_id, ctx, "Transaction")
    if t.transaction_type != "DEPOSIT" or t.transfer_group:
        raise conflict("NOT_A_DEPOSIT", "Donation receipts come from deposits only.")
    return t


def _lines(db: Session, t: RegisterTransaction) -> dict[int, DonationLine]:
    ids = [a.id for a in t.live_allocations]
    if not ids:
        return {}
    return {d.allocation_id: d for d in db.scalars(select(DonationLine).where(DonationLine.allocation_id.in_(ids)))}


def _donor(t: RegisterTransaction, a) -> Entity | None:
    return a.entity or t.parent_entity


def _donor_groups(db: Session, t: RegisterTransaction) -> dict[int, dict]:
    """Per donor: the donation lines and the receipt content."""
    lines = _lines(db, t)
    out: dict[int, dict] = {}
    for a in t.live_allocations:
        d = lines.get(a.id)
        if d is None:
            continue
        e = _donor(t, a)
        if e is None:
            continue
        g = out.setdefault(e.id, {"entity": e, "allocs": [], "amount": 0, "goods": [], "purposes": []})
        g["allocs"].append(a.id)
        g["amount"] += a.amount_cents
        if d.goods_cents:
            g["goods"].append((d.goods_cents, d.goods_description or ""))
        if d.purpose and d.purpose not in g["purposes"]:
            g["purposes"].append(d.purpose)
    return out


def _content_sha(t: RegisterTransaction, g: dict) -> str:
    e = g["entity"]
    doc = {"donor": e.id, "name": e.display_name, "address": address_lines(e), "amount": g["amount"],
           "date": t.transaction_date.isoformat(), "goods": g["goods"], "purposes": g["purposes"]}
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def _receipts(db: Session, t: RegisterTransaction) -> list[DonationReceipt]:
    return list(db.scalars(select(DonationReceipt).where(DonationReceipt.transaction_id == t.id)
                           .order_by(DonationReceipt.id)))


def _current(receipts: list[DonationReceipt], donor_id: int) -> DonationReceipt | None:
    """The donor's receipt in force: the last numbered (ORIGINAL or CORRECTED) one."""
    numbered = [r for r in receipts if r.donor_entity_id == donor_id and r.kind != DUPLICATE]
    return numbered[-1] if numbered else None


def _user_name(db: Session, uid: int | None) -> str:
    u = db.get(User, uid) if uid else None
    return (u.display_name or u.username) if u else ""


def transaction_out(db: Session, ctx, t: RegisterTransaction) -> dict:
    lines = _lines(db, t)
    receipts = _receipts(db, t)
    groups = _donor_groups(db, t)
    printable = t.status == "ACTIVE" and not reg.is_closed_protected(db, t)
    by_id = {r.id: r for r in receipts}
    cfg = get_config(db, ctx.workspace_id)
    donors = []
    for eid, g in groups.items():
        cur = _current(receipts, eid)
        sha = _content_sha(t, g)
        next_kind = ORIGINAL if cur is None else (DUPLICATE if cur.content_sha == sha else CORRECTED)
        donors.append({"entity_id": eid, "name": g["entity"].display_name, "amount": money(g["amount"]),
                       "amount_cents": g["amount"], "goods_cents": sum(c for c, _d in g["goods"]),
                       "purposes": g["purposes"], "has_address": bool(address_lines(g["entity"])),
                       "current_receipt": cur.number if cur else None, "next_kind": next_kind})
    superseded = {r.replaces_id for r in receipts if r.kind == CORRECTED and r.replaces_id}
    return {
        "transaction_id": t.id, "status": t.status, "date": t.transaction_date.isoformat(),
        "total": money(t.total_cents), "printable": printable,
        "closed": reg.is_closed_protected(db, t),
        "setup_missing": missing_setup(db, ctx.workspace_id),
        "lines": [{"allocation_id": a.id, "donor_entity_id": (_donor(t, a).id if _donor(t, a) else None),
                   "donor": (_donor(t, a).display_name if _donor(t, a) else ""), "description": a.description or "",
                   "donor_is_organization": bool(_donor(t, a) and _donor(t, a).is_organization),
                   "amount": money(a.amount_cents), "amount_cents": a.amount_cents,
                   "donation": a.id in lines,
                   "purpose": lines[a.id].purpose if a.id in lines else None,
                   "goods_cents": lines[a.id].goods_cents if a.id in lines else None,
                   "goods_description": lines[a.id].goods_description if a.id in lines else None}
                  for a in t.live_allocations],
        "donors": donors,
        "receipts": [{"id": r.id, "number": r.number, "kind": r.kind, "donor_entity_id": r.donor_entity_id,
                      "donor": r.donor_name, "amount": money(r.amount_cents),
                      "date_received": r.date_received.isoformat(),
                      "replaces": by_id[r.replaces_id].number if r.replaces_id in by_id else None,
                      "attachment_id": r.attachment_id, "printed_at": r.printed_at.isoformat() + "Z",
                      "printed_by": _user_name(db, r.printed_by_user_id),
                      "void": t.status != "ACTIVE",
                      "superseded": r.id in superseded or (r.kind == DUPLICATE and r.replaces_id in superseded)}
                     for r in receipts],
    }


class LineIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    allocation_id: int
    donation: bool
    purpose: str | None = Field(default=None, max_length=200)
    goods_cents: int | None = Field(default=None, ge=0)
    goods_description: str | None = Field(default=None, max_length=200)


def _line_snap(d: DonationLine | None) -> dict | None:
    if d is None:
        return None
    return {"allocation_id": d.allocation_id, "purpose": d.purpose, "goods_cents": d.goods_cents,
            "goods_description": d.goods_description}


def set_lines(db: Session, ctx, t: RegisterTransaction, items: list[LineIn]) -> None:
    if t.status != "ACTIVE":
        raise conflict("TRANSACTION_NOT_ACTIVE", "Donations can only be marked on an active deposit.")
    if reg.is_closed_protected(db, t):
        raise conflict("FISCAL_YEAR_CLOSED", "The deposit belongs to a Closed Fiscal Year.")
    allocs = {a.id: a for a in t.live_allocations}
    current = _lines(db, t)
    seen = set()
    for i, it in enumerate(items):
        a = allocs.get(it.allocation_id)
        if a is None or it.allocation_id in seen:
            raise validation("Unknown deposit line.", f"lines.{i}.allocation_id")
        seen.add(it.allocation_id)
        d = current.get(a.id)
        if not it.donation:
            if d is not None:
                before = _line_snap(d)
                db.delete(d)
                db.flush()
                audit.record(db, ctx, "DONATION_MARKED", "register_transaction", t.id, before,
                             {"allocation_id": a.id, "donation": False})
            continue
        if _donor(t, a) is None:
            raise validation("This line has no entity (donor). Add the donor to the deposit first.",
                             f"lines.{i}.donation")
        if _donor(t, a).is_organization:          # 2.1.0 (#314): e.g. lump cash recorded as the organization's
            raise validation("This line's entity is your own organization, so it can't be a donation with a receipt. "
                             "Record the donor as the line's entity.", f"lines.{i}.donation")
        goods = it.goods_cents or None
        if goods is not None and goods > a.amount_cents:
            raise validation("The goods or services value can't be more than the line's amount.",
                             f"lines.{i}.goods_cents")
        desc = (it.goods_description or "").strip() or None
        if goods and not desc:
            raise validation("Describe the goods or services provided.", f"lines.{i}.goods_description")
        if not goods:
            desc = None
        purpose = (it.purpose or "").strip() or None
        before = _line_snap(d)
        if d is None:
            d = DonationLine(workspace_id=ctx.workspace_id, allocation_id=a.id, created_by_user_id=ctx.user.id)
            db.add(d)
        d.purpose, d.goods_cents, d.goods_description = purpose, goods, desc
        d.updated_by_user_id, d.updated_at = ctx.user.id, utcnow()
        db.flush()
        after = _line_snap(d)
        if before != after:
            audit.record(db, ctx, "DONATION_MARKED", "register_transaction", t.id, before,
                         {**after, "donation": True})


def _next_seq(db: Session, ws_id: int, year: int) -> int:
    cur = db.scalar(select(func.max(DonationReceipt.seq)).where(DonationReceipt.workspace_id == ws_id,
                                                                DonationReceipt.year == year))
    return (cur or 0) + 1


def print_receipt(db: Session, ctx, settings, t: RegisterTransaction, donor_entity_id: int,
                  confirmations: list[str]) -> tuple[bytes, DonationReceipt]:
    if t.status != "ACTIVE":
        raise conflict("NOT_PRINTABLE", "This deposit is void - its receipts are void and no receipt can be printed.")
    if reg.is_closed_protected(db, t):
        raise conflict("FISCAL_YEAR_CLOSED", "The deposit belongs to a Closed Fiscal Year and cannot be printed. Its "
                                             "receipts are attached to it.")
    cfg = get_config(db, ctx.workspace_id)
    missing = missing_setup(db, ctx.workspace_id)
    if missing:
        raise conflict("SETUP_INCOMPLETE", "An Administrator must enter " + " and ".join(missing) +
                       " in System/About → Organization before receipts can be printed.")
    g = _donor_groups(db, t).get(donor_entity_id)
    if g is None:
        raise not_found("Donor")
    receipts = _receipts(db, t)
    cur = _current(receipts, donor_entity_id)
    sha = _content_sha(t, g)
    e = g["entity"]
    if cur is not None and cur.content_sha == sha:
        kind, number, year, seq = DUPLICATE, cur.number, cur.year, cur.seq
        note = f"DUPLICATE of receipt {cur.number}, first printed {format_date(cur.printed_at.date(), cfg.date_format)}."
    else:
        year = t.transaction_date.year
        seq = _next_seq(db, ctx.workspace_id, year)
        number = f"R-{year}-{seq:04d}"
        kind = ORIGINAL if cur is None else CORRECTED
        note = "" if cur is None else (f"CORRECTED receipt: replaces receipt {cur.number} printed "
                                       f"{format_date(cur.printed_at.date(), cfg.date_format)}.")
    data = ReceiptData(number=number, kind=kind, kind_note=note, org=org_svc.values_for(db, ctx.workspace_id),
                       donor_name=e.display_name, donor_address=address_lines(e),
                       amount_cents=g["amount"], date_received=t.transaction_date, purposes=g["purposes"],
                       goods=g["goods"])
    warnings = []
    _texts, empty = receipt_texts(cfg, data)
    if empty:
        warnings.append(Warning_("EMPTY_VARIABLES", "These variables have no data for this receipt: " +
                                 ", ".join("{" + v + "}" for v in empty) + ". Print the receipt as it is?",
                                 variables=empty))
    if not data.donor_address:
        warnings.append(Warning_("NO_DONOR_ADDRESS", "The donor has no address in the register. Print the receipt "
                                 "without it?"))
    if kind == CORRECTED:
        warnings.append(Warning_("CORRECTED_RECEIPT", f"The donation changed since receipt {cur.number}. Print a "
                                 f"corrected receipt {number} that replaces it?", replaces=cur.number))
    require_confirmations(warnings, confirmations)
    pdf = receipt_pdf(cfg, data)
    suffix = "-duplicate" if kind == DUPLICATE else ""
    added, path = _store_doc_copy(db, ctx, settings, t, RECEIPT_COPY, f"receipt-{number}{suffix}.pdf", pdf)
    att = db.scalar(select(Attachment).where(Attachment.transaction_id == t.id,
                                             Attachment.document_type == RECEIPT_COPY,
                                             Attachment.sha256 == hashlib.sha256(pdf).hexdigest()))
    r = DonationReceipt(workspace_id=ctx.workspace_id, transaction_id=t.id, donor_entity_id=e.id,
                        donor_name=e.display_name[:200], number=number, year=year, seq=seq, kind=kind,
                        replaces_id=cur.id if cur is not None else None, amount_cents=g["amount"],
                        goods_cents=sum(c for c, _d in g["goods"]), date_received=t.transaction_date,
                        allocation_ids=",".join(str(x) for x in g["allocs"])[:500], content_sha=sha,
                        attachment_id=att.id if att else None, printed_by_user_id=ctx.user.id)
    db.add(r)
    db.flush()
    audit.record(db, ctx, "DONATION_RECEIPT_PRINTED", "register_transaction", t.id, None,
                 {"transaction_id": t.id, "receipt_id": r.id, "number": number, "kind": kind,
                  "donor_entity_id": e.id, "amount_cents": g["amount"], "goods_cents": r.goods_cents,
                  "replaces": cur.number if cur is not None and kind != ORIGINAL else None, "attached": added})
    _commit_or_unlink(db, path)
    return pdf, r
