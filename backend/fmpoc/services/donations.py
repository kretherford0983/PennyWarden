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
import re
from dataclasses import dataclass, field
from typing import Literal
from xml.sax.saxutils import escape

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, Warning_, conflict, not_found, require_confirmations, validation
from ..models import (Attachment, CheckSigner, Donation, DonationLine, DonationReceipt, DonationSettings, Entity, FiscalYear,
                      RegisterTransaction, TransactionAllocation, User, Workspace, utcnow)
from . import register as reg
from .checkprint import config as cfgmod
from . import organization as org_svc
from .checkprint import documents, fonts, patterns
from . import entity_vars
from . import signers
from .checkprint.service import _store_doc_copy, address_lines, format_date
from .common import get_scoped

RECEIPT_COPY = "DONATION_RECEIPT"          # Attachment.document_type of a receipt's record copy (system generated)
ORIGINAL, DUPLICATE, CORRECTED = "ORIGINAL", "DUPLICATE", "CORRECTED"
PT = 72.0
NO_GOODS = "No goods or services were provided in exchange for this contribution."
# 2.2.0 (#325): printed whenever a receipt lists items; editable in Donations Setup (empty = this default)
ITEMS_NOTE_DEFAULT = ("Donated items are listed by description only. {ORG.NAME} does not assign a monetary value to "
                      "donated property; determining its value is the donor's responsibility.")
ITEMS_NOTE_MIN_WORDS = 8
BLANK_DATE = "________________"
DEFAULT_ADDRESSEE = ["{DONOR.NAME}", "{DONOR.MAILING_ADDRESS}"]      # 2.2.0 (#317): today's block


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
                              "possible.\n\n{DETAILS}\n\nPlease keep this letter as the written acknowledgment of your "
                              "contribution.", max_length=2000)
    closing: str = Field(default="With gratitude,", max_length=200)
    # 2.3.0 (#395): the signer (shared Signers page, tagged for donation receipts) and how the signature is shown;
    # the year-end statement has its own (None = the receipt's)
    signer_id: int | None = None
    signature_mode: Literal["NONE", "PRINTED", "IMAGE", "SPACE"] = "NONE"
    statement_signer_id: int | None = None
    statement_signature_mode: Literal["NONE", "PRINTED", "IMAGE", "SPACE"] | None = None
    items_note: str = Field(default="", max_length=1000)     # 2.2.0 (#325): empty = ITEMS_NOTE_DEFAULT
    # 2.2.0 (#325): the cover letter's window-envelope options (#177) and fold marks (#247). A receipt printed for a
    # #10 double-window envelope needs no envelope of its own (the print screen hides that step).
    window: Literal["NONE", "LETTER", "ADDRESS_PAGE"] = "NONE"
    window_return: bool = True                                # the organization's address in the upper window
    fold_marks: Literal["NONE", "FRONT", "BACK"] = "NONE"
    # 2.2.0 (#317): the addressee block of receipts and statements - up to 6 lines from {DONOR.*}
    addressee: list[str] = Field(default_factory=lambda: list(DEFAULT_ADDRESSEE), max_length=6)
    # 2.2.0 (#256): the year-end giving statement's letter (the receipt variables plus {YEAR}, {TOTAL},
    # {STATEMENT_NO} and {DONATION_TABLE}); the layout, window and signer are the receipt's
    statement_title: str = Field(default="Year-End Giving Statement {YEAR}", max_length=120)
    statement_salutation: str = Field(default="Dear {DONOR_NAME},", max_length=200)
    statement_body: str = Field(default="Thank you for your generous support of {ORG.NAME} during {YEAR}. These are the "
                                        "contributions we received from you in {YEAR}:\n\n{DONATION_TABLE}\n\nPlease "
                                        "keep this statement with your tax records.", max_length=2000)
    statement_closing: str = Field(default="With gratitude,", max_length=200)
    # 2.3.0 (#393): print the organization's EIN on receipts and statements (default on, also for existing setups)
    include_ein: bool = True

    @model_validator(mode="before")
    @classmethod
    def _moved(cls, v):
        """2.1.0 (#314): the EIN and address moved to the organization profile; older saved settings carry them."""
        if isinstance(v, dict):    # 2.3.0 (#395): the typed signer became a signer (migration 0064)
            v = {k: x for k, x in v.items() if k not in ("ein", "org_address", "signer_name", "signer_title")}
        return v

    @model_validator(mode="after")
    def _patterns(self):
        for name in ("title", "salutation", "body", "closing"):
            _check(getattr(self, name), name.capitalize())
        for line in self.addressee:
            if len(line) > 200 or "\n" in line:
                raise ValueError("Addressee: each line is one line of at most 200 characters.")
            _check(line, "Addressee")
        for name in ("statement_title", "statement_salutation", "statement_body", "statement_closing"):
            try:
                patterns.parse(getattr(self, name), patterns.STATEMENT)
            except patterns.PatternError as e:
                raise ValueError(f"Year-end statement {name.split('_', 1)[1]}: {e}") from None
        if self.items_note.strip():
            _check(self.items_note, "Items note")
            if note_words(self.items_note) < ITEMS_NOTE_MIN_WORDS:
                raise ValueError(f"Items note: write at least {ITEMS_NOTE_MIN_WORDS} words so the note explains "
                                 "itself (a {VARIABLE} counts as one word), or leave it empty for the default wording.")
        return self


def note_words(text: str) -> int:
    """Words in a note; a {VARIABLE} counts as one word however many words it prints (Kyle, 2026-10-23)."""
    return len(re.sub(r"\{[^{}]*\}", " X ", text).split())


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


EIN_VARS = ("ORG.EIN", "ORG_EIN")


def hide_ein(vals: dict) -> dict:
    """2.3.0 (#393): the values with the EIN printed blank (Include EIN on receipts is off)."""
    return {**vals, **{k: "" for k in EIN_VARS if k in vals}}


def uses_ein(text: str, kind=None) -> bool:
    """Does this text use {ORG.EIN} / {ORG_EIN}?"""
    try:
        return any(t.var in EIN_VARS for t in patterns.parse(text or "", kind or patterns.RECEIPT))
    except patterns.PatternError:
        return False


def ein_entered(db: Session, ws_id: int) -> bool:
    e = org_svc.get(db, ws_id)
    return bool(e and e.ein)


def missing_setup(db: Session, ws_id: int) -> list[str]:
    """What a receipt can't be printed without (#314: from the organization profile in System/About). 2.3.0 (#393):
    the EIN only while Include EIN on receipts is on."""
    e = org_svc.get(db, ws_id)
    out = []
    if not (e and e.ein) and get_config(db, ws_id).include_ein:
        out.append("the organization's EIN")
    if not org_svc.address_lines(e):
        out.append("the organization's address")
    return out


def organization_out(db: Session, ws_id: int) -> dict:
    v = org_svc.values_for(db, ws_id)
    return {"name": v["ORG.NAME"], "address": [x for x in v["ORG.ADDRESS"].split("\n") if x], "ein": v["ORG.EIN"]}


def setup_warnings(db: Session, ws_id: int, cfg: ReceiptConfig) -> list[dict]:
    """2.3.0 (#393): Donations Setup warnings about the EIN."""
    out = []
    if cfg.include_ein and not ein_entered(db, ws_id):
        out.append({"code": "EIN_MISSING", "message": "Include EIN on receipts is on, but no EIN has been entered. "
                    "Enter it in System/About → Organization (or turn Include EIN on receipts off); until then "
                    "receipts and statements can't be printed."})
    if not cfg.include_ein:
        used = [n for n in ("title", "salutation", "body", "closing") if uses_ein(getattr(cfg, n))]
        used += [f"statement {n}" for n in ("title", "salutation", "body", "closing")
                 if uses_ein(getattr(cfg, f"statement_{n}"), patterns.STATEMENT)]
        if used:
            out.append({"code": "EIN_PLACEHOLDER_OFF", "message": "Include EIN on receipts is off, but the letter "
                        "text still uses {ORG.EIN} (" + ", ".join(used) + "); it prints blank there."})
    return out


def setup_out(db: Session, ctx) -> dict:
    cfg = get_config(db, ctx.workspace_id)
    row = _settings_row(db, ctx.workspace_id)
    return {"config": cfg.model_dump(), "defaults": ReceiptConfig().model_dump(), "saved": row is not None,
            "warnings": setup_warnings(db, ctx.workspace_id, cfg) + signature_warnings(db, ctx.workspace_id, cfg),
            # 2.3.0 (#395): the signers tagged for donation receipts, and the signature modes
            "signers": [signers.out(db, ctx, s) for s in signers.tagged(db, ctx, signers.DONATIONS)],
            "signature_modes": [{"id": m, "label": signers.MODE_LABELS[m]} for m in signers.MODES],
            "missing": missing_setup(db, ctx.workspace_id), "organization": organization_out(db, ctx.workspace_id),
            "variables": patterns.variable_options(patterns.RECEIPT),
            "statement_variables": patterns.variable_options(patterns.STATEMENT),     # 2.2.0 (#256)
            "date_formats": list(cfgmod.DATE_FORMATS), "no_goods_statement": NO_GOODS,
            "items_note_default": ITEMS_NOTE_DEFAULT, "items_note_min_words": ITEMS_NOTE_MIN_WORDS}


def save_config(db: Session, ctx, data: dict) -> ReceiptConfig:
    cfg = parse_config(data)
    # 2.3.0 (#395): only signers tagged for donation receipts (BR-078/BR-099)
    signers.require_tagged(db, ctx, cfg.signer_id, signers.DONATIONS, "signer_id")
    signers.require_tagged(db, ctx, cfg.statement_signer_id, signers.DONATIONS, "statement_signer_id")
    if cfg.signature_mode != "NONE" and cfg.signer_id is None:
        raise validation("Choose the signer, or set the signature to None.", "signer_id")
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


def signature_for(db: Session, ws_id: int, km, cfg: ReceiptConfig, which: str = "receipt",
                  with_image: bool = False) -> signers.SignatureBlock:
    """2.3.0 (#395): the receipt's (or the statement's: its own signer and mode, else the receipt's) signature. The
    image only with `with_image` (the printed copy, the Administrator's setup preview and test print)."""
    sid, mode = cfg.signer_id, cfg.signature_mode
    if which == "statement":
        sid = cfg.statement_signer_id if cfg.statement_signer_id is not None else cfg.signer_id
        mode = cfg.statement_signature_mode or cfg.signature_mode
    s = db.get(CheckSigner, sid) if sid else None
    if s is not None and (s.workspace_id != ws_id or not s.active):
        s = None
    return signers.block_for(km, s, mode, with_image)


def signature_warnings(db: Session, ws_id: int, cfg: ReceiptConfig) -> list[dict]:
    out = []
    for which, label in (("receipt", "receipt"), ("statement", "year-end statement")):
        sid = cfg.signer_id if which == "receipt" else (cfg.statement_signer_id or cfg.signer_id)
        mode = cfg.signature_mode if which == "receipt" else (cfg.statement_signature_mode or cfg.signature_mode)
        s = db.get(CheckSigner, sid) if sid else None
        if mode == "IMAGE" and s is not None and not s.image_ciphertext:
            out.append({"code": "SIGNER_NO_IMAGE", "message": f"{s.name} has no signature image, so the {label} "
                        "prints the name with space to sign by hand. Upload the image on the Signers page."})
    return out


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
    dates: list[dt.date]                 # when received (each line's date, else the deposit's); [] = not received yet
                                         # (2.2.0, #325: the receipt prints the date blank, to fill in by hand)
    purposes: list[str]
    goods: list[tuple[int, str]] = field(default_factory=list)       # (cents, description) per line with goods
    today: dt.date = field(default_factory=dt.date.today)
    details: str = ""                    # the {DETAILS} text as written (may contain {VARIABLES})
    items: list[str] = field(default_factory=list)                    # 2.2.0 (#325): item descriptions (no values)
    donor_values: dict[str, str] = field(default_factory=dict)        # 2.2.0 (#317): {DONOR.*}
    ein_override: bool = False            # 2.3.0 (#393): EIN off, but these details include it (confirmed, with a reason)
    signature: signers.SignatureBlock = field(default_factory=signers.SignatureBlock)   # 2.3.0 (#395)


def money(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def goods_statement(goods: list[tuple[int, str]]) -> str:
    total = sum(c for c, _d in goods)
    if total <= 0:
        return NO_GOODS
    desc = "; ".join(d for _c, d in goods if d)
    return (f"Goods or services valued at {money(total)} were provided in exchange for this contribution"
            + (f" ({desc})" if desc else "") + ".")


def dates_text(dates: list[dt.date], fmt: str) -> str:
    """One date, or "May 1, 2026 and May 8, 2026", or "May 1, 2026, May 8, 2026 and May 15, 2026"."""
    parts = [format_date(d, fmt) for d in sorted(set(dates))]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1] if parts else ""


def values_for(cfg: ReceiptConfig, data: ReceiptData) -> dict[str, str]:
    vals = {"DONOR_NAME": data.donor_name, "DONOR_ADDRESS": "\n".join(data.donor_address),
            "AMOUNT": f"{data.amount_cents // 100:,}.{data.amount_cents % 100:02d}",
            "DATE_RECEIVED": dates_text(data.dates, cfg.date_format) or BLANK_DATE,
            "PURPOSE": "; ".join(data.purposes), **data.org, "RECEIPT_NO": data.number, "SIGNER": data.signature.name,
            "SIGNER_TITLE": data.signature.title, "TODAY": format_date(data.today, cfg.date_format), **data.donor_values}
    # the details may use the same variables (not {DETAILS} itself); 2.3.0 (#393): with the EIN off it prints blank
    # in the letter, and in the details only when they include it by a confirmed override
    shown = vals if cfg.include_ein else hide_ein(vals)
    dvals = vals if (cfg.include_ein or data.ein_override) else shown
    shown["DETAILS"] = patterns.resolve(data.details, dvals, patterns.RECEIPT).text if data.details.strip() else ""
    return shown


def check_details(text: str) -> None:
    """The details are receipt text: any receipt variable except {DETAILS}; 422 otherwise."""
    try:
        tokens = patterns.parse(text, patterns.RECEIPT)
    except patterns.PatternError as e:
        raise AppError(422, "PATTERN_INVALID", f"Details: {e}", variable=e.variable, suggestion=e.suggestion) from None
    if any(t.var == "DETAILS" for t in tokens):
        raise validation("The details can't contain {DETAILS} itself.", "details")


def uses_details(cfg: ReceiptConfig) -> bool:
    for name in ("title", "salutation", "body", "closing"):
        try:
            if any(t.var == "DETAILS" for t in patterns.parse(getattr(cfg, name), patterns.RECEIPT)):
                return True
        except patterns.PatternError:
            pass
    return False


def receipt_texts(cfg: ReceiptConfig, data: ReceiptData) -> tuple[dict, list[str]]:
    vals = values_for(cfg, data)
    empty: list[str] = []
    out = {}
    for name in ("title", "salutation", "body", "closing"):
        r = patterns.resolve(getattr(cfg, name), vals, patterns.RECEIPT)
        # empty {DETAILS} inside a sentence leaves no double space (a paragraph of its own is dropped by _paras)
        out[name] = "\n".join(re.sub(r"[ \t]{2,}", " ", line).strip() if "DETAILS" in r.empty else line
                              for line in r.text.split("\n"))
        empty += [v for v in r.empty if v not in empty and v != "DETAILS"     # details are optional
                  and (cfg.include_ein or v not in EIN_VARS)]                # #393: blank on purpose
    return out, empty


def _paras(text: str) -> list[str]:
    return ["<br/>".join(escape(x) for x in p.split("\n")) for p in text.split("\n\n") if p.strip()]


def _styles(cfg) -> dict:
    reg_f, bold = fonts.ps_name(cfg.font), fonts.ps_name(cfg.font, True)
    size = cfg.size
    base = ParagraphStyle("base", fontName=reg_f, fontSize=size, leading=size * 1.3)
    strong = ParagraphStyle("strong", parent=base, fontName=bold)
    return {"reg": reg_f, "bold": bold, "size": size, "base": base, "strong": strong,
            "title": ParagraphStyle("title", parent=strong, fontSize=size + 3, leading=(size + 3) * 1.3),
            "small": ParagraphStyle("small", parent=base, fontSize=size - 1.5, leading=(size - 1.5) * 1.3)}


def ack_table(rows: list[tuple[str, str]], st: dict) -> Table:
    """The acknowledgment block: always printed, not part of the template."""
    tbl = Table([[Paragraph(escape(k), st["strong"]), Paragraph(escape(v).replace("\n", "<br/>"), st["base"])]
                 for k, v in rows], colWidths=[1.6 * inch, 4.9 * inch], hAlign="LEFT")
    tbl.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, "#666666"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3),
                             ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
    return tbl


def donor_letter_pdf(cfg: ReceiptConfig, *, org: dict, donor_lines: list[str], today: dt.date,
                     kind: str, sample: bool, watermark: str | None, doc_title: str, middle: list,
                     closing: str, signature: "signers.SignatureBlock | None" = None) -> bytes:
    """A letter to a donor (receipt or year-end statement, 2.2.0 #256): the organization and donor heading - or the
    window-envelope layout and fold marks (#325) - then `middle`, the closing and the signer. A kind other than
    ORIGINAL is printed in the top corner; `watermark` across the page."""
    st = _styles(cfg)
    reg_f, bold, size, base = st["reg"], st["bold"], st["size"], st["base"]
    lcfg = documents.LetterConfig(font=cfg.font, size=cfg.size, window=cfg.window, window_return=cfg.window_return,
                                  fold_marks=cfg.fold_marks)
    org_lines = [org["ORG.NAME"]] + [x for x in org["ORG.ADDRESS"].split("\n") if x]
    windowed = cfg.window != "NONE"
    blocks = documents.window_blocks(lcfg, {"letterhead": org_lines}, donor_lines) if windowed else []

    def first_page(c, doc):
        if cfg.fold_marks == "FRONT":
            documents.fold_ticks(c, lcfg)
        if blocks:
            c.saveState()
            for which, x, y, lines in blocks:
                yy = (11 - y) * PT - size
                for i, line in enumerate(lines):
                    c.setFont(bold if (which == "return" and i == 0) else reg_f, size)
                    c.drawString(x * PT, yy, line)
                    yy -= size * 1.2
            if sample:                                   # the setup preview shows where the windows are
                c.setStrokeGray(0.45)
                c.setLineWidth(0.6)
                c.setDash(3, 2)
                for key in ("return", "payee"):
                    if key == "return" and not cfg.window_return:
                        continue
                    left, top, w, h = documents.WINDOW_PRESET[key]["window"]
                    c.rect(left * PT, (11 - top - h) * PT, w * PT, h * PT, stroke=1, fill=0)
            c.restoreState()
        page(c, doc)

    def page(c, _doc):
        c.saveState()
        if kind != ORIGINAL:
            c.setFont(bold, 9)
            c.setFillGray(0.35)
            c.drawRightString(7.5 * PT, 10.55 * PT, kind)
        if watermark:
            c.setFillGray(0.86)
            c.setFont(bold, 46)
            c.translate(4.25 * PT, 5.5 * PT)
            c.rotate(35)
            c.drawCentredString(0, 0, watermark)
        c.restoreState()

    story = []
    if cfg.window == "ADDRESS_PAGE":
        story += [Spacer(1, 1), PageBreak()]                    # page 1: only the addresses, for the windows
    if cfg.window == "LETTER":                                  # the addresses show through the windows
        story += [Spacer(1, (documents.FOLD_LINES[0] + 0.15 - 1) * inch),
                  Paragraph(escape(format_date(today, cfg.date_format)), base)]
    else:
        story += [Paragraph(escape(org["ORG.NAME"]), st["strong"])]
        story += [Paragraph(escape(x), base) for x in org["ORG.ADDRESS"].split("\n") if x]
        story += [Spacer(1, size * 1.2), Paragraph(escape(format_date(today, cfg.date_format)), base),
                  Spacer(1, size * 1.2)]
        story += [Paragraph(escape(x), base) for x in donor_lines]
    story.append(Spacer(1, size * 1.4))
    story += middle
    story.append(Spacer(1, size * 1.2))
    block = [Paragraph(escape(closing), base)] if closing.strip() else []
    # 2.3.0 (#395): the chosen signer, shown as the letter's mode says (image only in the printed copy)
    block += signers.flowables(signature or signers.SignatureBlock(), base, bold, size, extra_title=org["ORG.NAME"])
    if block:
        story.append(KeepTogether(block))
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=(8.5 * inch, 11 * inch), leftMargin=inch, rightMargin=inch,
                            topMargin=inch, bottomMargin=inch, title=doc_title,
                            creator="PennyWarden", author="", subject="", invariant=1)
    doc.build(story, onFirstPage=first_page, onLaterPages=page)
    if cfg.fold_marks == "BACK":
        return documents._with_back_pages(buf.getvalue(), lcfg, doc_title)
    return buf.getvalue()


def addressee_lines(cfg: ReceiptConfig, values: dict, name: str, address: list[str]) -> list[str]:
    """2.2.0 (#317): the donor's addressee block from the template's lines (default: name and mailing address)."""
    return entity_vars.addressee(cfg.addressee, values, patterns.RECEIPT) or [name] + address


def items_note_text(cfg: ReceiptConfig, values: dict) -> str:
    return patterns.resolve(cfg.items_note.strip() or ITEMS_NOTE_DEFAULT, values, patterns.RECEIPT).text


def receipt_pdf(cfg: ReceiptConfig, data: ReceiptData, sample: bool = False, watermark: str | None = None) -> bytes:
    """The receipt letter. `sample` (setup preview and test print) draws SAMPLE - NOT A RECEIPT across the page;
    `watermark` another text (the Register User's preview: PREVIEW - NOT A RECEIPT)."""
    if sample and watermark is None:
        watermark = "SAMPLE - NOT A RECEIPT"
    texts, _empty = receipt_texts(cfg, data)
    st = _styles(cfg)
    size, base = st["size"], st["base"]
    middle = []
    if texts["title"].strip():
        middle += [Paragraph(escape(texts["title"]), st["title"]), Spacer(1, size * 0.4)]
    middle += [Paragraph(escape(f"Receipt No. {data.number}"), st["strong"])]
    if data.kind_note:
        middle.append(Paragraph(escape(data.kind_note), st["small"]))
    middle.append(Spacer(1, size))
    for key in ("salutation", "body"):
        for p in _paras(texts[key]):
            middle += [Paragraph(p, base), Spacer(1, size * 0.7)]
    rows = ([("Organization", data.org["ORG.NAME"])] + ([("EIN", data.org["ORG.EIN"])] if cfg.include_ein else [])
            + [("Donor", data.donor_name), ("Date received", dates_text(data.dates, cfg.date_format) or BLANK_DATE)])
    if data.amount_cents or not data.items:                    # 2.2.0 (#325): the total covers money only
        rows.append(("Amount", money(data.amount_cents)))
    if data.items:
        rows.append(("Items", "\n".join(f"• {x}" for x in data.items)))
    if data.purposes:
        rows.append(("Purpose", "; ".join(data.purposes)))
    rows.append(("Receipt No.", data.number))
    ack = [ack_table(rows, st), Spacer(1, size * 0.6), Paragraph(escape(goods_statement(data.goods)), st["strong"])]
    if data.items:                                  # 2.2.0 (#325): always with items; the wording is editable
        ack += [Spacer(1, size * 0.4), Paragraph(escape(items_note_text(cfg, values_for(cfg, data))), base)]
    middle.append(KeepTogether(ack))
    return donor_letter_pdf(cfg, org=data.org, donor_lines=addressee_lines(cfg, values_for(cfg, data), data.donor_name,
                                                                           data.donor_address),
                            today=data.today, kind=data.kind, sample=sample, watermark=watermark,
                            doc_title=f"Donation receipt {data.number}", middle=middle, closing=texts["closing"],
                            signature=data.signature)


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
                       amount_cents=25000, dates=[dt.date.today()], purposes=["General support"],
                       items=["SAMPLE ITEM - a television for the auction"],
                       donor_values=entity_vars.sample("DONOR", SAMPLE_DONOR[0], SAMPLE_DONOR[1:]),
                       details="(The details written for this donation in the Donation receipt dialog: for example, "
                               "how the gift of ${AMOUNT} will be used.)")


def sample_pdf(db: Session, ctx, data: dict | None, km=None) -> bytes:
    """Setup preview and test print (Administrators): sample data; 2.3.0 (#395) the real signature for IMAGE."""
    cfg = parse_config(data) if data is not None else get_config(db, ctx.workspace_id)
    sd = sample_data(db, ctx, cfg)
    sd.signature = signature_for(db, ctx.workspace_id, km, cfg, "receipt", with_image=True)
    return receipt_pdf(cfg, sd, sample=True)


# ------------------------------------------------------------------ 2.2.0 (#325): the donation model
# A donation (donor, lines, details) is the receipt's unit. It starts on the Donations page (PAGE) or by marking a
# deposit's lines in the register (DEPOSIT: one donation per donor on that deposit). Each line is money or an item.
# "Received" decides (Kyle, 2026-10-23): a money line when it is linked to a deposit, an item when ticked Received.
PAGE, DEPOSIT = "PAGE", "DEPOSIT"
MONEY, ITEM = "MONEY", "ITEM"
ACTIVE, CANCELLED = "ACTIVE", "CANCELLED"


def get_deposit(db: Session, ctx, txn_id: int) -> RegisterTransaction:
    t = get_scoped(db, RegisterTransaction, txn_id, ctx, "Transaction")
    if t.transaction_type != "DEPOSIT" or t.transfer_group:
        raise conflict("NOT_A_DEPOSIT", "Donation receipts come from deposits only.")
    return t


def get_donation(db: Session, ctx, donation_id: int) -> Donation:
    return get_scoped(db, Donation, donation_id, ctx, "Donation")


def _donor(t: RegisterTransaction, a) -> Entity | None:
    return a.entity or t.parent_entity


def lines_of(db: Session, d: Donation) -> list[DonationLine]:
    return list(db.scalars(select(DonationLine).where(DonationLine.donation_id == d.id).order_by(DonationLine.id)))


def _alloc(db: Session, line: DonationLine) -> TransactionAllocation | None:
    if line.allocation_id is None:
        return None
    a = db.get(TransactionAllocation, line.allocation_id)
    return a if a is not None and a.removed_at is None else None


def line_received(db: Session, line: DonationLine) -> bool:
    if line.kind == ITEM:
        return bool(line.item_received)
    a = _alloc(db, line)
    return a is not None and a.transaction.status == "ACTIVE"


def line_amount(db: Session, line: DonationLine) -> int:
    """A linked money line follows the deposit's allocation (the register wins); otherwise its own amount. For an
    item: its estimated value (for our records only, never printed)."""
    if line.kind == MONEY:
        a = _alloc(db, line)
        if a is not None:
            return a.amount_cents
    return line.amount_cents or 0


def line_date(db: Session, line: DonationLine) -> dt.date | None:
    """The received date of a received line; for one not received yet, the estimate (if any)."""
    if line.kind == MONEY:
        a = _alloc(db, line)
        if a is not None:
            return line.date_received or a.transaction.transaction_date
    return line.date_received


def line_deposit(db: Session, line: DonationLine) -> RegisterTransaction | None:
    a = _alloc(db, line)
    return a.transaction if a is not None else None


def value_missing(line: DonationLine) -> bool:
    return line.kind == ITEM and not line.amount_cents and not line.item_no_value


def _closed_on(db: Session, ws_id: int, d: dt.date | None) -> bool:
    if d is None:
        return False
    return db.scalar(select(func.count(FiscalYear.id)).where(
        FiscalYear.workspace_id == ws_id, FiscalYear.status == "CLOSED", FiscalYear.start_date <= d,
        FiscalYear.end_date >= d)) > 0


def line_locked(db: Session, line: DonationLine) -> bool:
    """A received line in a Closed Fiscal Year can't be edited, like the register (BR-057)."""
    if not line_received(db, line):
        return False
    if line.kind == MONEY:
        t = line_deposit(db, line)
        return t is not None and reg.is_closed_protected(db, t)
    return _closed_on(db, line.workspace_id, line.date_received)


def deposits_of(db: Session, d: Donation) -> list[RegisterTransaction]:
    out: list[RegisterTransaction] = []
    for line in lines_of(db, d):
        t = line_deposit(db, line)
        if t is not None and t not in out:
            out.append(t)
    if d.origin == DEPOSIT and d.transaction_id:
        t = db.get(RegisterTransaction, d.transaction_id)
        if t is not None and t not in out:
            out.insert(0, t)
    return out


def _content(db: Session, d: Donation) -> dict:
    """What the donation's receipt would carry now."""
    e = db.get(Entity, d.donor_entity_id)
    lines = lines_of(db, d)
    money_cents, goods, purposes, items, dates, allocs = 0, [], [], [], [], []
    received = bool(lines) and all(line_received(db, x) for x in lines)
    for x in lines:
        if x.kind == MONEY:
            money_cents += line_amount(db, x)
            if x.allocation_id:
                allocs.append(x.allocation_id)
        else:
            items.append(x.description or "")
        if x.goods_cents:
            goods.append((x.goods_cents, x.goods_description or ""))
        if x.purpose and x.purpose not in purposes:
            purposes.append(x.purpose)
        when = line_date(db, x)
        if received and when and when not in dates:
            dates.append(when)
    dates.sort()
    return {"entity": e, "amount": money_cents, "goods": goods, "purposes": purposes, "items": items,
            "dates": dates, "details": d.details or "", "allocs": allocs, "received": received}


def _content_sha(c: dict) -> str:
    e = c["entity"]
    doc = {"donor": e.id, "name": e.legal_name, "address": address_lines(e), "amount": c["amount"],
           "dates": [x.isoformat() for x in c["dates"]], "goods": c["goods"], "purposes": c["purposes"],
           "details": c["details"]}
    if c["items"]:                       # 2.2.0: part 1 receipts (no items) keep their fingerprint
        doc["items"] = c["items"]
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def _receipts_of(db: Session, d: Donation) -> list[DonationReceipt]:
    return list(db.scalars(select(DonationReceipt).where(DonationReceipt.donation_id == d.id)
                           .order_by(DonationReceipt.id)))


def _current(receipts: list[DonationReceipt]) -> DonationReceipt | None:
    """The receipt in force: the last numbered (ORIGINAL or CORRECTED) one."""
    numbered = [r for r in receipts if r.kind != DUPLICATE]
    return numbered[-1] if numbered else None


def _user_name(db: Session, uid: int | None) -> str:
    u = db.get(User, uid) if uid else None
    return (u.display_name or u.username) if u else ""


def receipts_void(db: Session, d: Donation) -> bool:
    """Cancelled donations, and donations marked on a deposit that was voided or deleted (part 1), have void
    receipts. A Donations page donation whose deposit was voided is unlinked instead: its receipts stay valid."""
    if d.status == CANCELLED:
        return True
    if d.origin == DEPOSIT and d.transaction_id:
        t = db.get(RegisterTransaction, d.transaction_id)
        return t is None or t.status != "ACTIVE"
    return False


def _receipts_out(db: Session, d: Donation) -> list[dict]:
    receipts = _receipts_of(db, d)
    by_id = {r.id: r for r in receipts}
    superseded = {r.replaces_id for r in receipts if r.kind == CORRECTED and r.replaces_id}
    void = receipts_void(db, d)
    return [{"id": r.id, "number": r.number, "kind": r.kind, "donor_entity_id": r.donor_entity_id,
             "donor": r.donor_name, "amount": money(r.amount_cents),
             "date_received": r.date_received.isoformat() if r.date_received else None,
             "replaces": by_id[r.replaces_id].number if r.replaces_id in by_id else None,
             "attachment_id": r.attachment_id, "printed_at": r.printed_at.isoformat() + "Z",
             "printed_by": _user_name(db, r.printed_by_user_id), "void": void,
             "superseded": r.id in superseded or (r.kind == DUPLICATE and r.replaces_id in superseded)}
            for r in receipts]


def _next_seq(db: Session, ws_id: int, year: int) -> int:
    cur = db.scalar(select(func.max(DonationReceipt.seq)).where(DonationReceipt.workspace_id == ws_id,
                                                                DonationReceipt.year == year))
    return (cur or 0) + 1


def _check_printable(db: Session, ctx, d: Donation) -> None:
    if d.status == CANCELLED:
        raise conflict("NOT_PRINTABLE", "This donation was cancelled - its receipts are void and no receipt can be "
                                        "printed.")
    if d.origin == DEPOSIT and d.transaction_id:
        t = db.get(RegisterTransaction, d.transaction_id)
        if t is None or t.status != "ACTIVE":
            raise conflict("NOT_PRINTABLE", "This deposit is void - its receipts are void and no receipt can be "
                                            "printed.")
        if reg.is_closed_protected(db, t):
            raise conflict("FISCAL_YEAR_CLOSED", "The deposit belongs to a Closed Fiscal Year and cannot be printed. "
                                                 "Its receipts are attached to it.")
    if not lines_of(db, d):
        raise conflict("NO_LINES", "This donation has no lines.")
    missing = missing_setup(db, ctx.workspace_id)
    if missing:
        raise conflict("SETUP_INCOMPLETE", "An Administrator must enter " + " and ".join(missing) +
                       " in System/About → Organization before receipts can be printed.")


def _compose(db: Session, ctx, d: Donation) -> dict:
    """Everything a receipt for this donation would be now: kind and number, the data, the warnings."""
    _check_printable(db, ctx, d)
    cfg = get_config(db, ctx.workspace_id)
    c = _content(db, d)
    receipts = _receipts_of(db, d)
    cur = _current(receipts)
    sha = _content_sha(c)
    e = c["entity"]
    if cur is not None and cur.content_sha == sha:
        kind, number, year, seq = DUPLICATE, cur.number, cur.year, cur.seq
        note = f"DUPLICATE of receipt {cur.number}, first printed {format_date(cur.printed_at.date(), cfg.date_format)}."
    else:
        year = c["dates"][0].year if c["dates"] else dt.date.today().year   # the (first) date received
        seq = _next_seq(db, ctx.workspace_id, year)
        number = f"R-{year}-{seq:04d}"
        kind = ORIGINAL if cur is None else CORRECTED
        note = "" if cur is None else (f"CORRECTED receipt: replaces receipt {cur.number} printed "
                                       f"{format_date(cur.printed_at.date(), cfg.date_format)}.")
    data = ReceiptData(number=number, kind=kind, kind_note=note, org=org_svc.values_for(db, ctx.workspace_id),
                       donor_name=e.legal_name, donor_address=address_lines(e),
                       amount_cents=c["amount"], dates=c["dates"], purposes=c["purposes"],
                       goods=c["goods"], details=c["details"], items=c["items"],
                       donor_values=entity_vars.values("DONOR", e),
                       signature=signature_for(db, ctx.workspace_id, None, cfg))   # #395: no image unless printing
    warnings = []
    if not cfg.include_ein and uses_ein(data.details):        # 2.3.0 (#393): a one-off EIN through {DETAILS}
        if not ein_entered(db, ctx.workspace_id):
            raise conflict("EIN_NOT_ENTERED", "These details include the EIN, but no EIN has been entered in "
                                              "System/About → Organization. Remove it from the details, or ask an "
                                              "Administrator to enter it.")
        if not (d.ein_override_reason or "").strip():
            raise conflict("EIN_OVERRIDE_REASON_MISSING", "The EIN is turned off for donations, and these details "
                                                          "include it without a reason. Save the details again and "
                                                          "give the reason.")
        data.ein_override = True
        warnings.append(Warning_("EIN_OVERRIDE", "The EIN has been turned off for donations, and these details "
                                 f"include it (reason: {d.ein_override_reason}). Print the receipt with the EIN?"))
    _texts, empty = receipt_texts(cfg, data)
    if empty:
        warnings.append(Warning_("EMPTY_VARIABLES", "These variables have no data for this receipt: " +
                                 ", ".join("{" + v + "}" for v in empty) + ". Print the receipt as it is?",
                                 variables=empty))
    if not data.donor_address:
        warnings.append(Warning_("NO_DONOR_ADDRESS", "The donor has no address in the register. Print the receipt "
                                 "without it?"))
    if not c["received"]:
        warnings.append(Warning_("NOT_RECEIVED", "This donation is not received yet, so the receipt prints the date "
                                 "received blank, to fill in by hand when it is handed over. Print it?"))
    if kind == CORRECTED:
        warnings.append(Warning_("CORRECTED_RECEIPT", f"The donation changed since receipt {cur.number}. Print a "
                                 f"corrected receipt {number} that replaces it?", replaces=cur.number))
    return {"cfg": cfg, "data": data, "kind": kind, "number": number, "year": year, "seq": seq, "cur": cur,
            "sha": sha, "c": c, "e": e, "warnings": warnings}


PREVIEW_NUMBER = "(assigned when printed)"


def _preview(db: Session, ctx, d: Donation) -> tuple[bytes, dict]:
    c = _compose(db, ctx, d)
    data = c["data"]
    if c["kind"] != DUPLICATE:
        data.number = PREVIEW_NUMBER          # a new number is only taken when the receipt is printed
    pdf = receipt_pdf(c["cfg"], data, watermark="PREVIEW - NOT A RECEIPT")
    return pdf, {"kind": c["kind"], "number": c["number"] if c["kind"] == DUPLICATE else None,
                 "replaces": c["cur"].number if c["cur"] is not None and c["kind"] == CORRECTED else None,
                 "warnings": [w.as_dict() for w in c["warnings"]]}


def _store_donation_copy(db: Session, ctx, settings, d: Donation, kind_type: str, filename: str,
                         pdf: bytes) -> tuple[bool, object]:
    """A printed receipt (or envelope) of a donation not linked to a deposit: kept with the donation."""
    from . import attachments as att_svc
    sha = hashlib.sha256(pdf).hexdigest()
    if db.scalar(select(Attachment).where(Attachment.donation_id == d.id, Attachment.document_type == kind_type,
                                          Attachment.sha256 == sha)) is not None:
        return False, None
    key, path = att_svc._write_file(settings, pdf)
    att = Attachment(workspace_id=ctx.workspace_id, original_filename=att_svc.sanitize_filename(filename),
                     storage_key=key, mime_type="application/pdf", size_bytes=len(pdf), sha256=sha,
                     uploaded_by_user_id=ctx.user.id, active=True, donation_id=d.id, document_type=kind_type,
                     system_generated=True)
    db.add(att)
    db.flush()
    audit.record(db, ctx, "ATTACHMENT_ADDED", "attachment", att.id, None, att_svc.snapshot(att))
    return True, path


def print_donation(db: Session, ctx, settings, d: Donation, confirmations: list[str],
                   km=None) -> tuple[bytes, DonationReceipt]:
    c = _compose(db, ctx, d)
    cfg, data, kind, number, year, seq, cur, sha, content, e = (c[k] for k in ("cfg", "data", "kind", "number",
                                                                                "year", "seq", "cur", "sha", "c", "e"))
    require_confirmations(c["warnings"], confirmations)
    pdf = receipt_pdf(cfg, data)                                   # the copy kept with the record: never the image
    printed = pdf
    if cfg.signature_mode == "IMAGE" and km is not None:          # 2.3.0 (#395): the image only in the printed copy
        data.signature = signature_for(db, ctx.workspace_id, km, cfg, "receipt", with_image=True)
        if data.signature.image:
            printed = receipt_pdf(cfg, data)
    suffix = "-duplicate" if kind == DUPLICATE else ""
    fname = f"receipt-{number}{suffix}.pdf"
    deposits = [t for t in deposits_of(db, d) if t.status == "ACTIVE"]
    paths, added = [], False
    for t in deposits:                     # kept on every deposit it is linked to, else with the donation
        a, path = _store_doc_copy(db, ctx, settings, t, RECEIPT_COPY, fname, pdf)
        added = added or a
        paths.append(path)
    if not deposits:
        added, path = _store_donation_copy(db, ctx, settings, d, RECEIPT_COPY, fname, pdf)
        paths.append(path)
    psha = hashlib.sha256(pdf).hexdigest()
    att = db.scalar(select(Attachment).where(Attachment.document_type == RECEIPT_COPY, Attachment.sha256 == psha,
                                             Attachment.workspace_id == ctx.workspace_id).order_by(Attachment.id))
    r = DonationReceipt(workspace_id=ctx.workspace_id, donation_id=d.id,
                        transaction_id=deposits[0].id if deposits else None, donor_entity_id=e.id,
                        donor_name=e.legal_name[:200], number=number, year=year, seq=seq, kind=kind,
                        replaces_id=cur.id if cur is not None else None, amount_cents=content["amount"],
                        goods_cents=sum(x for x, _d in content["goods"]),
                        date_received=content["dates"][0] if content["dates"] else None,
                        allocation_ids=",".join(str(x) for x in content["allocs"])[:500], content_sha=sha,
                        attachment_id=att.id if att else None, printed_by_user_id=ctx.user.id)
    db.add(r)
    db.flush()
    audit.record(db, ctx, "DONATION_RECEIPT_PRINTED", "donation", d.id, None,
                 {"donation_id": d.id, "transaction_id": r.transaction_id, "receipt_id": r.id, "number": number,
                  "kind": kind, "donor_entity_id": e.id, "amount_cents": content["amount"],
                  "items": len(content["items"]), "goods_cents": r.goods_cents, "received": content["received"],
                  "replaces": cur.number if cur is not None and kind != ORIGINAL else None, "attached": added,
                  "ein_override": data.ein_override,                                        # 2.3.0 (#393)
                  "ein_override_reason": d.ein_override_reason if data.ein_override else None,
                  "signature": data.signature.mode if data.signature.name else "NONE"})          # 2.3.0 (#395)
    try:
        db.commit()
    except Exception:
        db.rollback()
        for p in paths:
            if p is not None:
                try:
                    p.unlink()
                except OSError:
                    pass
        raise
    return printed, r


# ------------------------------------------------------------------ deposits: marking (part 1 flow) and receipts
def _deposit_donations(db: Session, t: RegisterTransaction) -> dict[int, Donation]:
    """The donations marked on this deposit (origin DEPOSIT), by donor."""
    return {d.donor_entity_id: d for d in db.scalars(select(Donation).where(
        Donation.transaction_id == t.id, Donation.origin == DEPOSIT).order_by(Donation.id))}


def _lines_by_alloc(db: Session, t: RegisterTransaction) -> dict[int, DonationLine]:
    ids = [a.id for a in t.live_allocations]
    if not ids:
        return {}
    return {x.allocation_id: x for x in db.scalars(select(DonationLine).where(DonationLine.allocation_id.in_(ids)))}


def transaction_out(db: Session, ctx, t: RegisterTransaction) -> dict:
    lines = _lines_by_alloc(db, t)
    donations = {x.donation_id: db.get(Donation, x.donation_id) for x in lines.values()}
    deposit_donations = _deposit_donations(db, t)
    printable = t.status == "ACTIVE" and not reg.is_closed_protected(db, t)
    cfg = get_config(db, ctx.workspace_id)
    donors, receipts = [], []
    for d in deposit_donations.values():
        c = _content(db, d)
        rs = _receipts_of(db, d)
        receipts += _receipts_out(db, d)
        if not lines_of(db, d):
            continue
        cur = _current(rs)
        sha = _content_sha(c)
        next_kind = ORIGINAL if cur is None else (DUPLICATE if cur.content_sha == sha else CORRECTED)
        e = c["entity"]
        donors.append({"entity_id": e.id, "donation_id": d.id, "name": e.display_name, "amount": money(c["amount"]),
                       "amount_cents": c["amount"], "goods_cents": sum(x for x, _d in c["goods"]),
                       "purposes": c["purposes"], "has_address": bool(address_lines(e)),
                       "dates": [x.isoformat() for x in c["dates"]], "details": c["details"],
                       "current_receipt": cur.number if cur else None, "next_kind": next_kind})
    receipts.sort(key=lambda r: r["id"])
    page_linked = []
    for d in donations.values():
        if d is not None and d.origin == PAGE and all(p["id"] != d.id for p in page_linked):
            page_linked.append({"id": d.id, "donor": db.get(Entity, d.donor_entity_id).display_name})

    suggested = donation_bucket_allocations(db, [a.id for a in t.live_allocations])

    def line_out(a):
        x = lines.get(a.id)
        d = donations.get(x.donation_id) if x is not None else None
        e = _donor(t, a)
        return {"allocation_id": a.id, "donor_entity_id": e.id if e else None, "donor": e.display_name if e else "",
                "description": a.description or "", "donor_is_organization": bool(e and e.is_organization),
                "amount": money(a.amount_cents), "amount_cents": a.amount_cents,
                "donation": x is not None,
                "linked_donation_id": d.id if d is not None and d.origin == PAGE else None,
                "purpose": x.purpose if x else None, "goods_cents": x.goods_cents if x else None,
                "goods_description": x.goods_description if x else None,
                "date_received": x.date_received.isoformat() if x is not None and x.date_received else None,
                # 2.2.0 (#256): in a fundraiser's donation bucket - the Donation box starts ticked as a suggestion
                "suggested": x is None and a.id in suggested, "fundraiser": suggested.get(a.id)}

    return {
        "transaction_id": t.id, "status": t.status, "date": t.transaction_date.isoformat(),
        "total": money(t.total_cents), "printable": printable, "closed": reg.is_closed_protected(db, t),
        "setup_missing": missing_setup(db, ctx.workspace_id), "details_enabled": uses_details(cfg),
        "variables": [v for v in patterns.variable_options(patterns.RECEIPT) if v["name"] != "DETAILS"],
        "lines": [line_out(a) for a in t.live_allocations], "donors": donors, "receipts": receipts,
        "page_donations": page_linked,
    }


class LineIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    allocation_id: int
    donation: bool
    purpose: str | None = Field(default=None, max_length=200)
    goods_cents: int | None = Field(default=None, ge=0)
    goods_description: str | None = Field(default=None, max_length=200)
    date_received: dt.date | None = None          # empty = the deposit's date


class DonorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: int
    details: str = Field(default="", max_length=2000)
    # 2.3.0 (#393): details that include the EIN while it is off - confirmed, with a reason
    confirm_ein_override: bool = False
    ein_override_reason: str | None = Field(default=None, max_length=500)


def ein_override_check(db: Session, ctx, text: str, confirmed: bool, reason: str | None,
                       field_prefix: str = "") -> str | None:
    """2.3.0 (#393): {ORG.EIN} in the details while Include EIN on receipts is off needs an explicit confirmation and
    a reason (server-validated); refused when no EIN is entered. Returns the reason to keep (None: no override)."""
    if not text or not uses_ein(text) or get_config(db, ctx.workspace_id).include_ein:
        return None
    if not ein_entered(db, ctx.workspace_id):
        raise conflict("EIN_NOT_ENTERED", "The details include the EIN, but no EIN has been entered in System/About → "
                                          "Organization, so it would print blank. Remove it, or ask an Administrator "
                                          "to enter the EIN.")
    why = (reason or "").strip()
    if not confirmed or not why:
        raise AppError(409, "EIN_OVERRIDE_REQUIRED", "The EIN has been turned off for donations. These details include "
                       "it: confirm that this receipt should show the EIN, and give the reason.",
                       field=field_prefix + "ein_override_reason")
    return why


def _line_snap(db: Session, x: DonationLine | None) -> dict | None:
    if x is None:
        return None
    return {"line_id": x.id, "donation_id": x.donation_id, "kind": x.kind, "allocation_id": x.allocation_id,
            "amount_cents": line_amount(db, x), "description": x.description, "purpose": x.purpose,
            "goods_cents": x.goods_cents, "goods_description": x.goods_description,
            "date_received": x.date_received.isoformat() if x.date_received else None,
            "item_received": x.item_received if x.kind == ITEM else None,
            "item_no_value": x.item_no_value if x.kind == ITEM else None,
            "item_no_value_reason": x.item_no_value_reason if x.kind == ITEM else None}


def _deposit_donation_for(db: Session, ctx, t: RegisterTransaction, donor: Entity) -> Donation:
    d = _deposit_donations(db, t).get(donor.id)
    if d is None:
        d = Donation(workspace_id=ctx.workspace_id, donor_entity_id=donor.id, origin=DEPOSIT, transaction_id=t.id,
                     status=ACTIVE, created_by_user_id=ctx.user.id, updated_by_user_id=ctx.user.id)
        db.add(d)
        db.flush()
    return d


def set_lines(db: Session, ctx, t: RegisterTransaction, items: list[LineIn]) -> None:
    """Part 1: mark deposit lines as donations - one donation per donor on the deposit (origin DEPOSIT). Lines linked
    to a donation from the Donations page are changed there."""
    if t.status != "ACTIVE":
        raise conflict("TRANSACTION_NOT_ACTIVE", "Donations can only be marked on an active deposit.")
    if reg.is_closed_protected(db, t):
        raise conflict("FISCAL_YEAR_CLOSED", "The deposit belongs to a Closed Fiscal Year.")
    allocs = {a.id: a for a in t.live_allocations}
    current = _lines_by_alloc(db, t)
    seen = set()
    for i, it in enumerate(items):
        a = allocs.get(it.allocation_id)
        if a is None or it.allocation_id in seen:
            raise validation("Unknown deposit line.", f"lines.{i}.allocation_id")
        seen.add(it.allocation_id)
        x = current.get(a.id)
        if x is not None:
            owner = db.get(Donation, x.donation_id)
            if owner is not None and owner.origin == PAGE:      # changed on the Donations page, not here
                if not it.donation:
                    raise conflict("LINKED_TO_DONATION", f"This line is linked to donation #{owner.id} from the "
                                                         "Donations page; change it there.")
                continue
        if not it.donation:
            if x is not None:
                before = _line_snap(db, x)
                db.delete(x)
                db.flush()
                audit.record(db, ctx, "DONATION_MARKED", "register_transaction", t.id, before,
                             {"allocation_id": a.id, "donation": False})
            continue
        donor = _donor(t, a)
        if donor is None:
            raise validation("This line has no entity (donor). Add the donor to the deposit first.",
                             f"lines.{i}.donation")
        if donor.is_organization:          # 2.1.0 (#314): e.g. lump cash recorded as the organization's
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
        when = it.date_received if it.date_received != t.transaction_date else None
        if when is not None and when > t.transaction_date:
            raise validation("A donation can't be received after the deposit it was deposited in.",
                             f"lines.{i}.date_received")
        before = _line_snap(db, x)
        d = _deposit_donation_for(db, ctx, t, donor)
        if x is None:
            x = DonationLine(workspace_id=ctx.workspace_id, allocation_id=a.id, kind=MONEY,
                             created_by_user_id=ctx.user.id)
            db.add(x)
        x.donation_id = d.id                    # a changed donor moves the line to that donor's donation
        x.purpose, x.goods_cents, x.goods_description, x.date_received = purpose, goods, desc, when
        x.updated_by_user_id, x.updated_at = ctx.user.id, utcnow()
        db.flush()
        after = _line_snap(db, x)
        if before != after:
            audit.record(db, ctx, "DONATION_MARKED", "register_transaction", t.id, before,
                         {**after, "donation": True})


def set_details(db: Session, ctx, t: RegisterTransaction, donors: list[DonorIn]) -> None:
    """The {DETAILS} text per donor of this deposit (after the lines are saved: only current donors)."""
    if not donors:
        return
    deposit_donations = {k: d for k, d in _deposit_donations(db, t).items() if lines_of(db, d)}
    for i, it in enumerate(donors):
        d = deposit_donations.get(it.entity_id)
        if d is None:
            raise validation("That entity is not a donor on this deposit.", f"donors.{i}.entity_id")
        text = (it.details or "").replace("\r\n", "\n").strip()
        if text:
            check_details(text)
        before = d.details or ""
        if before == text:
            continue
        why = ein_override_check(db, ctx, text, it.confirm_ein_override, it.ein_override_reason, f"donors.{i}.")
        before_reason = d.ein_override_reason
        d.details, d.updated_by_user_id, d.updated_at = (text or None), ctx.user.id, utcnow()
        d.ein_override_reason = why
        db.flush()
        audit.record(db, ctx, "DONATION_DETAILS_UPDATED", "register_transaction", t.id,
                     {"donor_entity_id": it.entity_id, "details": before, "ein_override_reason": before_reason},
                     {"donor_entity_id": it.entity_id, "details": text, "ein_override_reason": why})


def _deposit_donation(db: Session, t: RegisterTransaction, donor_entity_id: int) -> Donation:
    d = _deposit_donations(db, t).get(donor_entity_id)
    if d is None or not lines_of(db, d):
        raise not_found("Donor")
    return d


def preview_receipt(db: Session, ctx, t: RegisterTransaction, donor_entity_id: int,
                    lines: list | None = None, donors: list | None = None) -> tuple[bytes, dict]:
    """2.1.0 (Kyle, 2026-10-23): the receipt as it would print, from what is on screen (unsaved lines and details
    applied in a transaction that is rolled back). Watermarked PREVIEW - NOT A RECEIPT; nothing is attached, no
    number is used and nothing counts toward Duplicate/Corrected. The preview itself is audited."""
    try:
        if lines:
            set_lines(db, ctx, t, lines)
        if donors:
            set_details(db, ctx, t, donors)
        pdf, info = _preview(db, ctx, _deposit_donation(db, t, donor_entity_id))
        info["unsaved"] = bool(lines or donors)
    finally:
        db.rollback()                             # nothing of the unsaved changes stays
    audit.record(db, ctx, "DONATION_RECEIPT_PREVIEW", "register_transaction", t.id, None,
                 {"transaction_id": t.id, "donor_entity_id": donor_entity_id, "kind": info["kind"],
                  "unsaved_changes": info["unsaved"]})
    db.commit()
    return pdf, info


def print_receipt(db: Session, ctx, settings, t: RegisterTransaction, donor_entity_id: int,
                  confirmations: list[str], km=None) -> tuple[bytes, DonationReceipt]:
    if t.status != "ACTIVE":
        raise conflict("NOT_PRINTABLE", "This deposit is void - its receipts are void and no receipt can be printed.")
    if reg.is_closed_protected(db, t):
        raise conflict("FISCAL_YEAR_CLOSED", "The deposit belongs to a Closed Fiscal Year and cannot be printed. Its "
                                             "receipts are attached to it.")
    return print_donation(db, ctx, settings, _deposit_donation(db, t, donor_entity_id), confirmations, km=km)


# ------------------------------------------------------------------ 2.2.0 (#256): fundraiser donation buckets
def donation_bucket_allocations(db: Session, allocation_ids: list[int]) -> dict[int, str]:
    """The allocations classified into a fundraiser's donation bucket -> the fundraiser's name."""
    from ..models import Fundraiser, FundraiserBucket, FundraiserBucketLine
    if not allocation_ids:
        return {}
    rows = db.execute(select(FundraiserBucketLine.allocation_id, Fundraiser.name)
                      .join(FundraiserBucket, FundraiserBucket.id == FundraiserBucketLine.bucket_id)
                      .join(Fundraiser, Fundraiser.id == FundraiserBucket.fundraiser_id)
                      .where(FundraiserBucketLine.allocation_id.in_(allocation_ids),
                             FundraiserBucket.is_donation.is_(True)))
    return {aid: name for aid, name in rows}


def fundraiser_unreceipted(db: Session, ctx, fundraiser_id: int) -> dict:
    """The deposits classified into this fundraiser's donation buckets that have no receipt yet: lines not marked as
    donations, or marked but never printed. Voided deposits are left out."""
    from ..models import Fundraiser, FundraiserBucket, FundraiserBucketLine
    f = get_scoped(db, Fundraiser, fundraiser_id, ctx, "Fundraiser")
    q = (select(FundraiserBucketLine.allocation_id)
         .join(FundraiserBucket, FundraiserBucket.id == FundraiserBucketLine.bucket_id)
         .where(FundraiserBucket.fundraiser_id == f.id, FundraiserBucket.is_donation.is_(True)))
    by_txn: dict[int, dict] = {}
    for aid in sorted(set(db.scalars(q))):
        a = db.get(TransactionAllocation, aid)
        if a is None or a.removed_at is not None:
            continue
        t = a.transaction
        if t.status != "ACTIVE" or t.transaction_type != "DEPOSIT":
            continue
        x = db.scalar(select(DonationLine).where(DonationLine.allocation_id == a.id))
        if x is None:
            state = "NOT_MARKED"
        else:
            d = db.get(Donation, x.donation_id) if x.donation_id else None
            if d is None or _current(_receipts_of(db, d)) is not None:
                continue
            state = "NOT_PRINTED"
        row = by_txn.setdefault(t.id, {"transaction_id": t.id, "bank_account_id": t.bank_account_id,
                                       "date": t.transaction_date.isoformat(), "donors": [], "amount_cents": 0,
                                       "lines": 0, "states": []})
        e = _donor(t, a)
        if e is not None and e.display_name not in row["donors"]:
            row["donors"].append(e.display_name)
        row["amount_cents"] += a.amount_cents
        row["lines"] += 1
        if state not in row["states"]:
            row["states"].append(state)
    items = sorted(by_txn.values(), key=lambda r: (r["date"], r["transaction_id"]))
    for r in items:
        r["amount"] = money(r["amount_cents"])
    return {"fundraiser_id": f.id, "items": items,
            "has_donation_buckets": db.scalar(select(func.count(FundraiserBucket.id)).where(
                FundraiserBucket.fundraiser_id == f.id, FundraiserBucket.is_donation.is_(True))) > 0}


# ------------------------------------------------------------------ the register's changes reach the donations
def unlink_for_deposit(db: Session, ctx, t: RegisterTransaction, allocation_ids: list[int] | None = None) -> None:
    """A voided or deleted deposit (or allocations removed from it): money lines of Donations page donations are
    unlinked - they await a deposit again and their receipts stay valid (Kyle, 2026-10-23, decision 4). Donations
    marked on the deposit (part 1) keep their lines; their receipts are void with the deposit."""
    ids = allocation_ids if allocation_ids is not None else [a.id for a in t.allocations]
    if not ids:
        return
    for x in db.scalars(select(DonationLine).where(DonationLine.allocation_id.in_(ids))):
        d = db.get(Donation, x.donation_id) if x.donation_id else None
        if d is None or d.origin != PAGE:
            continue
        a = db.get(TransactionAllocation, x.allocation_id)
        before = _line_snap(db, x)
        x.amount_cents = a.amount_cents if a is not None else x.amount_cents
        x.allocation_id = None
        x.updated_by_user_id, x.updated_at = ctx.user.id, utcnow()
        db.flush()
        audit.record(db, ctx, "DONATION_UNLINKED", "donation", d.id, before,
                     {**_line_snap(db, x), "transaction_id": t.id, "reason": t.status})


# ------------------------------------------------------------------ the Donations page
class PageLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: int | None = None
    kind: Literal["MONEY", "ITEM"] = "MONEY"
    amount_cents: int | None = Field(default=None, ge=0, le=10**12)
    description: str | None = Field(default=None, max_length=200)
    purpose: str | None = Field(default=None, max_length=200)
    goods_cents: int | None = Field(default=None, ge=0, le=10**12)
    goods_description: str | None = Field(default=None, max_length=200)
    date_received: dt.date | None = None        # money not linked / items: the estimate until received
    item_received: bool = False
    item_no_value: bool = False
    item_no_value_reason: str | None = Field(default=None, max_length=500)


class DonationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    donor_entity_id: int
    details: str = Field(default="", max_length=2000)
    confirm_ein_override: bool = False                                      # 2.3.0 (#393)
    ein_override_reason: str | None = Field(default=None, max_length=500)
    lines: list[PageLineIn] = Field(min_length=1, max_length=50)


def _donor_entity(db: Session, ctx, entity_id: int) -> Entity:
    e = get_scoped(db, Entity, entity_id, ctx, "Entity")
    if e.is_system:
        raise validation("Choose the donor.", "donor_entity_id")
    if e.is_organization:
        raise validation("The donor can't be your own organization.", "donor_entity_id")
    return e


def _apply_line(db: Session, ctx, x: DonationLine, it: PageLineIn, i: int) -> None:
    linked = x.kind == MONEY and x.allocation_id is not None
    if x.id is not None and it.kind != x.kind:
        if linked or line_received(db, x):
            raise validation("A received line can't change between money and item.", f"lines.{i}.kind")
    kind = it.kind
    desc = (it.description or "").strip() or None
    if kind == ITEM and not desc:
        raise validation("Describe the item: the receipt lists items by description only.", f"lines.{i}.description")
    goods = it.goods_cents or None
    gdesc = (it.goods_description or "").strip() or None
    if goods and not gdesc:
        raise validation("Describe the goods or services provided.", f"lines.{i}.goods_description")
    if not goods:
        gdesc = None
    if kind == MONEY and not linked:
        if not it.amount_cents:
            raise validation("Enter the amount.", f"lines.{i}.amount_cents")
        x.amount_cents = it.amount_cents
        x.date_received = it.date_received
    elif kind == MONEY and linked:
        a = _alloc(db, x)
        amount = a.amount_cents if a is not None else x.amount_cents
        if it.amount_cents is not None and it.amount_cents != amount:
            raise validation("This line is linked to a deposit: its amount follows the register. Change the deposit "
                             "instead.", f"lines.{i}.amount_cents")
        t = a.transaction if a is not None else None
        if t is not None and it.date_received is not None and it.date_received > t.transaction_date:
            raise validation("A donation can't be received after the deposit it was deposited in.",
                             f"lines.{i}.date_received")
        x.date_received = it.date_received if (t is None or it.date_received != t.transaction_date) else None
    else:                                           # an item
        x.amount_cents = it.amount_cents or None
        x.item_received = bool(it.item_received)
        x.date_received = it.date_received
        if x.item_received and it.date_received is None:
            raise validation("Enter the date the item was received.", f"lines.{i}.date_received")
        reason = (it.item_no_value_reason or "").strip() or None
        if it.item_no_value and x.amount_cents:
            raise validation("An item with an estimated value can't also be marked No value will be provided.",
                             f"lines.{i}.item_no_value")
        if it.item_no_value and not reason:
            raise validation("Give the reason no value will be provided.", f"lines.{i}.item_no_value_reason")
        x.item_no_value, x.item_no_value_reason = bool(it.item_no_value), (reason if it.item_no_value else None)
    if kind == MONEY and goods and goods > (line_amount(db, x) or 0):
        raise validation("The goods or services value can't be more than the line's amount.",
                         f"lines.{i}.goods_cents")
    x.kind, x.description, x.purpose = kind, desc, (it.purpose or "").strip() or None
    x.goods_cents, x.goods_description = goods, gdesc
    x.updated_by_user_id, x.updated_at = ctx.user.id, utcnow()


def _donation_snap(db: Session, d: Donation) -> dict:
    return {"donor_entity_id": d.donor_entity_id, "details": d.details, "status": d.status,
            "ein_override_reason": d.ein_override_reason,
            "lines": [_line_snap(db, x) for x in lines_of(db, d)]}


def create(db: Session, ctx, data: DonationIn) -> Donation:
    e = _donor_entity(db, ctx, data.donor_entity_id)
    text = (data.details or "").replace("\r\n", "\n").strip()
    if text:
        check_details(text)
    why = ein_override_check(db, ctx, text, data.confirm_ein_override, data.ein_override_reason)
    d = Donation(workspace_id=ctx.workspace_id, donor_entity_id=e.id, origin=PAGE, status=ACTIVE, details=text or None,
                 ein_override_reason=why, created_by_user_id=ctx.user.id, updated_by_user_id=ctx.user.id)
    db.add(d)
    db.flush()
    for i, it in enumerate(data.lines):
        if it.id is not None:
            raise validation("Unknown line.", f"lines.{i}.id")
        x = DonationLine(workspace_id=ctx.workspace_id, donation_id=d.id, kind=it.kind, created_by_user_id=ctx.user.id)
        _apply_line(db, ctx, x, it, i)
        db.add(x)
    db.flush()
    audit.record(db, ctx, "DONATION_CREATED", "donation", d.id, None, _donation_snap(db, d))
    return d


def update(db: Session, ctx, d: Donation, data: DonationIn) -> Donation:
    if d.status == CANCELLED:
        raise conflict("DONATION_CANCELLED", "This donation was cancelled and can't be changed.")
    if d.origin != PAGE:
        raise conflict("MARKED_ON_DEPOSIT", "This donation was marked on a deposit; change it from the deposit in the "
                                            "register (Donation receipt…).")
    before = _donation_snap(db, d)
    current = {x.id: x for x in lines_of(db, d)}
    if data.donor_entity_id != d.donor_entity_id:
        if any(line_received(db, x) for x in current.values()):
            raise validation("The donor can't change once part of the donation is received.", "donor_entity_id")
        d.donor_entity_id = _donor_entity(db, ctx, data.donor_entity_id).id
    text = (data.details or "").replace("\r\n", "\n").strip()
    if text:
        check_details(text)
    if text != (d.details or ""):
        d.ein_override_reason = ein_override_check(db, ctx, text, data.confirm_ein_override, data.ein_override_reason)
    d.details = text or None
    kept = set()
    for i, it in enumerate(data.lines):
        if it.id is None:
            x = DonationLine(workspace_id=ctx.workspace_id, donation_id=d.id, kind=it.kind,
                             created_by_user_id=ctx.user.id)
            _apply_line(db, ctx, x, it, i)
            db.add(x)
            continue
        x = current.get(it.id)
        if x is None or it.id in kept:
            raise validation("Unknown line.", f"lines.{i}.id")
        kept.add(it.id)
        snap = _line_snap(db, x)
        locked = line_locked(db, x)
        _apply_line(db, ctx, x, it, i)
        if locked and _line_snap(db, x) != snap:
            raise conflict("FISCAL_YEAR_CLOSED", "This line was received in a Closed Fiscal Year and can't be "
                                                 "changed.")
    for lid, x in current.items():
        if lid in kept:
            continue
        if x.kind == MONEY and x.allocation_id is not None:
            raise conflict("LINE_LINKED", "A line linked to a deposit can't be removed. Void the deposit first.")
        if line_locked(db, x):
            raise conflict("FISCAL_YEAR_CLOSED", "This line was received in a Closed Fiscal Year and can't be removed.")
        db.delete(x)
    d.updated_by_user_id, d.updated_at = ctx.user.id, utcnow()
    db.flush()
    if not lines_of(db, d):
        raise validation("A donation needs at least one line.", "lines")
    after = _donation_snap(db, d)
    if after != before:
        audit.record(db, ctx, "DONATION_UPDATED", "donation", d.id, before, after)
    return d


def cancel(db: Session, ctx, d: Donation, reason: str) -> Donation:
    """A donation that never happens: Cancelled with a reason, only while none of its lines is received (decision 5).
    Its receipts are void; nothing is deleted."""
    reason = (reason or "").strip()
    if not reason:
        raise validation("Give the reason the donation is cancelled.", "reason")
    if d.status == CANCELLED:
        raise conflict("DONATION_CANCELLED", "The donation is already cancelled.")
    if d.origin != PAGE:
        raise conflict("MARKED_ON_DEPOSIT", "This donation was marked on a deposit; untick its lines there instead.")
    if any(line_received(db, x) for x in lines_of(db, d)):
        raise conflict("DONATION_RECEIVED", "Part of this donation is received, so it can't be cancelled. Correct it "
                                            "instead: void the deposit, untick Received, or print a corrected receipt.")
    d.status, d.cancel_reason, d.cancelled_at, d.cancelled_by_user_id = CANCELLED, reason[:500], utcnow(), ctx.user.id
    d.updated_by_user_id, d.updated_at = ctx.user.id, utcnow()
    db.flush()
    audit.record(db, ctx, "DONATION_CANCELLED", "donation", d.id, {"status": ACTIVE},
                 {"status": CANCELLED, "reason": d.cancel_reason})
    return d


def _status_of(db: Session, d: Donation, lines: list[DonationLine]) -> str:
    if d.status == CANCELLED:
        return "CANCELLED"
    if any(x.kind == MONEY and x.allocation_id is None for x in lines):
        return "AWAITING_DEPOSIT"
    if lines and all(line_received(db, x) for x in lines):
        return "RECEIVED"
    return "NOT_RECEIVED"


STATUS_TEXT = {"CANCELLED": "Cancelled", "AWAITING_DEPOSIT": "Awaiting deposit", "RECEIVED": "Received",
               "NOT_RECEIVED": "Not received"}


def donation_out(db: Session, ctx, d: Donation, full: bool = True) -> dict:
    e = db.get(Entity, d.donor_entity_id)
    lines = lines_of(db, d)
    c = _content(db, d)
    rs = _receipts_of(db, d)
    cur = _current(rs)
    status = _status_of(db, d, lines)
    out = {"id": d.id, "origin": d.origin, "status": status, "status_text": STATUS_TEXT[status],
           "donor": {"id": e.id, "name": e.display_name, "has_address": bool(address_lines(e))},
           "money": money(c["amount"]), "money_cents": c["amount"], "items": len(c["items"]),
           "awaiting": sum(1 for x in lines if x.kind == MONEY and x.allocation_id is None) if d.status == ACTIVE else 0,
           "value_missing": sum(1 for x in lines if value_missing(x)) if d.status == ACTIVE else 0,
           "current_receipt": cur.number if cur else None,
           "deposits": [{"id": t.id, "date": t.transaction_date.isoformat(), "status": t.status}
                        for t in deposits_of(db, d)],
           "created_at": d.created_at.isoformat() + "Z", "cancel_reason": d.cancel_reason}
    if not full:
        return out
    next_kind = ORIGINAL if cur is None else (DUPLICATE if cur.content_sha == _content_sha(c) else CORRECTED)
    out.update({
        "details": d.details or "", "next_kind": next_kind, "receipts": _receipts_out(db, d),
        "editable": d.status == ACTIVE and d.origin == PAGE,
        "cancellable": d.status == ACTIVE and d.origin == PAGE and not any(line_received(db, x) for x in lines),
        "printable": d.status == ACTIVE and not receipts_void(db, d) and bool(lines),
        "received": c["received"],
        "lines": [{"id": x.id, "kind": x.kind, "amount_cents": line_amount(db, x) if x.kind == MONEY else x.amount_cents,
                   "description": x.description, "purpose": x.purpose, "goods_cents": x.goods_cents,
                   "goods_description": x.goods_description,
                   "date_received": (line_date(db, x).isoformat() if line_date(db, x) else None),
                   "date_is_estimate": not line_received(db, x),
                   "linked": x.allocation_id is not None, "received": line_received(db, x),
                   "deposit_id": line_deposit(db, x).id if line_deposit(db, x) else None,
                   "item_received": x.item_received, "item_no_value": x.item_no_value,
                   "item_no_value_reason": x.item_no_value_reason, "value_missing": value_missing(x),
                   "locked": line_locked(db, x)} for x in lines],
        "documents": [{"id": a.id, "name": a.original_filename, "kind": a.document_type}
                      for a in db.scalars(select(Attachment).where(Attachment.donation_id == d.id,
                                                                   Attachment.active.is_(True))
                                          .order_by(Attachment.id))],
    })
    return out


def list_out(db: Session, ctx, show: str = "all", q: str | None = None) -> dict:
    rows = [donation_out(db, ctx, d, full=False) for d in db.scalars(
        select(Donation).where(Donation.workspace_id == ctx.workspace_id).order_by(Donation.id.desc()))]
    rows = [r for r in rows if r["origin"] == PAGE or r["money_cents"] or r["items"] or r["current_receipt"]]
    counts = {"all": len(rows), "awaiting": sum(1 for r in rows if r["awaiting"]),
              "value_missing": sum(1 for r in rows if r["value_missing"]),
              "cancelled": sum(1 for r in rows if r["status"] == "CANCELLED")}
    if show == "awaiting":
        rows = [r for r in rows if r["awaiting"]]
    elif show == "value_missing":
        rows = [r for r in rows if r["value_missing"]]
    elif show == "cancelled":
        rows = [r for r in rows if r["status"] == "CANCELLED"]
    elif show == "active":
        rows = [r for r in rows if r["status"] != "CANCELLED"]
    if q:
        k = q.strip().lower()
        rows = [r for r in rows if k in r["donor"]["name"].lower() or k == str(r["id"])
                or (r["current_receipt"] or "").lower() == k]
    # 2.2.0: the variables a donation's Details can use (as on the register's receipt form), for the page's editor
    return {"items": rows, "counts": counts, "status_text": STATUS_TEXT,
            "variables": [v for v in patterns.variable_options(patterns.RECEIPT) if v["name"] != "DETAILS"]}


def preview_donation(db: Session, ctx, d: Donation) -> tuple[bytes, dict]:
    pdf, info = _preview(db, ctx, d)
    audit.record(db, ctx, "DONATION_RECEIPT_PREVIEW", "donation", d.id, None,
                 {"donation_id": d.id, "kind": info["kind"]})
    db.commit()
    return pdf, info


# ------------------------------------------------------------------ Create transaction from donations
def awaiting_lines(db: Session, ctx) -> list[dict]:
    """Money lines not yet linked to a deposit, of active donations: what Create transaction can pick."""
    out = []
    for x in db.scalars(select(DonationLine).where(DonationLine.workspace_id == ctx.workspace_id,
                                                   DonationLine.kind == MONEY, DonationLine.allocation_id.is_(None))
                        .order_by(DonationLine.id)):
        d = db.get(Donation, x.donation_id) if x.donation_id else None
        if d is None or d.status != ACTIVE:
            continue
        e = db.get(Entity, d.donor_entity_id)
        out.append({"id": x.id, "donation_id": d.id, "donor_entity_id": e.id, "donor": e.display_name,
                    "amount_cents": x.amount_cents or 0, "amount": money(x.amount_cents or 0),
                    "description": x.description or x.purpose or "", "purpose": x.purpose,
                    "date_received": x.date_received.isoformat() if x.date_received else None})
    return out


def create_transaction(db: Session, ctx, settings, data, links: list[int | None], date_received: dt.date | None):
    """Saves the deposit (an ordinary register deposit: income budgets, the Fiscal Year rules, split as in the
    register) and links each chosen money line to its allocation(s): `links[i]` is the donation line of allocation i.
    A line spread over several allocations (split further) becomes one line per allocation, adding up to its amount.
    Lines with no date received get `date_received` (empty = the deposit's date). The donations' printed receipts (and
    printed envelopes) are attached to the deposit."""
    from . import attachments as att_svc
    if data.transaction_type != "DEPOSIT":
        raise validation("Create transaction makes a deposit.", "transaction_type")
    if len(links) != len(data.allocations):
        raise validation("Each allocation needs its donation line (or none).", "links")
    chosen: dict[int, DonationLine] = {}
    for i, lid in enumerate(links):
        if lid is None or lid in chosen:
            continue
        x = db.get(DonationLine, lid)
        d = db.get(Donation, x.donation_id) if x is not None and x.donation_id else None
        if x is None or d is None or x.workspace_id != ctx.workspace_id:
            raise validation("Unknown donation line.", f"links.{i}")
        if d.status != ACTIVE or x.kind != MONEY or x.allocation_id is not None:
            raise conflict("LINE_NOT_AWAITING", f"Donation #{d.id}'s line is not awaiting a deposit any more.")
        chosen[lid] = x
    if not chosen:
        raise validation("Pick at least one donation.", "links")
    for lid, x in chosen.items():
        d = db.get(Donation, x.donation_id)
        idx = [i for i, v in enumerate(links) if v == lid]
        total = sum(int(round(float(data.allocations[i].amount) * 100)) for i in idx)
        if total != (x.amount_cents or 0):
            raise validation(f"The allocations for donation #{d.id} must add up to its amount "
                             f"{money(x.amount_cents or 0)}.", f"allocations.{idx[0]}.amount")
        for i in idx:
            if data.allocations[i].entity_id not in (None, d.donor_entity_id):
                raise validation(f"The entity of donation #{d.id}'s line is its donor.", f"allocations.{i}.entity_id")
            data.allocations[i].entity_id = d.donor_entity_id
        if x.date_received is None and date_received is not None:
            if data.transaction_date and date_received > data.transaction_date:
                raise validation("A donation can't be received after the deposit it was deposited in.",
                                 "date_received")
    t = reg.create(db, ctx, data)
    allocs = list(t.live_allocations)
    donations: dict[int, Donation] = {}
    for lid, x in chosen.items():
        d = db.get(Donation, x.donation_id)
        donations[d.id] = d
        before = _line_snap(db, x)
        idx = [i for i, v in enumerate(links) if v == lid]
        if x.date_received is None and date_received is not None and date_received != t.transaction_date:
            x.date_received = date_received
        elif x.date_received is not None and x.date_received > t.transaction_date:
            x.date_received = None                     # an estimate after the deposit: the deposit's date
        x.allocation_id = allocs[idx[0]].id
        x.amount_cents = allocs[idx[0]].amount_cents
        made = [x.id]
        for i in idx[1:]:                               # split further: one line per allocation
            y = DonationLine(workspace_id=ctx.workspace_id, donation_id=d.id, kind=MONEY, allocation_id=allocs[i].id,
                             amount_cents=allocs[i].amount_cents, description=x.description, purpose=x.purpose,
                             date_received=x.date_received, created_by_user_id=ctx.user.id,
                             updated_by_user_id=ctx.user.id)
            db.add(y)
            db.flush()
            made.append(y.id)
        x.updated_by_user_id, x.updated_at = ctx.user.id, utcnow()
        db.flush()
        audit.record(db, ctx, "DONATION_LINKED", "donation", d.id, before,
                     {"transaction_id": t.id, "line_ids": made, "allocation_ids": [allocs[i].id for i in idx]})
    for d in donations.values():                       # the printed receipts go with the deposit
        for att in db.scalars(select(Attachment).where(Attachment.donation_id == d.id, Attachment.active.is_(True),
                                                       Attachment.document_type.in_((RECEIPT_COPY, ENVELOPE_COPY)))
                              .order_by(Attachment.id)):
            try:
                pdf = att_svc.path_for(settings, att).read_bytes()
            except OSError:
                continue
            _store_doc_copy(db, ctx, settings, t, att.document_type, att.original_filename, pdf)
    return t


# ------------------------------------------------------------------ receipt envelopes (Kyle, 2026-10-23)
ENVELOPE_COPY = "DONATION_ENVELOPE"         # Attachment.document_type of a printed receipt envelope's record copy


def envelope_choices(db: Session, ctx) -> dict:
    """The envelopes tagged for Donations (the Donations default first) with the user's envelope printer settings.
    `receipt_window`: receipts print for a window envelope, so the print screen hides the envelope step (with *Print
    an envelope anyway*). No envelope tagged for Donations: printing an envelope is hidden, with a hint."""
    from . import envelopes as env_lib
    from .checkprint import service as cp
    envs = env_lib.envelopes(db, ctx, env_lib.DONATIONS, active_only=True)
    envs.sort(key=lambda d: (env_lib.DONATIONS not in env_lib.defaults(d), d.name.lower()))
    cfg = get_config(db, ctx.workspace_id)
    return {"envelopes": [{**cp.doc_out(d, full=False), "is_default": env_lib.DONATIONS in env_lib.defaults(d),
                           "printer": cp.envelope_options(db, ctx, d)} for d in envs],
            "receipt_window": cfg.window != "NONE"}


def _donation_envelope(db: Session, ctx, doc_id: int):
    from . import envelopes as env_lib
    from .checkprint import service as cp
    doc = cp.get_document(db, ctx, doc_id, "ENVELOPE")
    if env_lib.DONATIONS not in env_lib.tags(doc):
        raise not_found("Template")
    return doc


def _check_envelope_printable(db: Session, d: Donation) -> None:
    if d.status == CANCELLED:
        raise conflict("NOT_PRINTABLE", "This donation was cancelled - no envelope can be printed for it.")
    if receipts_void(db, d):
        raise conflict("NOT_PRINTABLE", "This deposit is void - no envelope can be printed for its donations.")


def _envelope_values(db: Session, ctx, d: Donation, e: Entity) -> dict[str, str]:
    """The envelope's variables for a donation: the organization's, the donor as the addressee, today's date. The
    check-only variables have no data here."""
    ws = db.get(Workspace, ctx.workspace_id)
    fmt = get_config(db, ctx.workspace_id).date_format
    return {**entity_vars.values("PAYEE", e),       # 2.2.0 (#317): the donor is the envelope's addressee
            "ORG": ws.name if ws else "", "PAYEE": e.legal_name, "PAYEE_ADDRESS": "\n".join(address_lines(e)),
            "TODAY": format_date(dt.date.today(), fmt),
            **{k: v for k, v in org_svc.values_for(db, ctx.workspace_id).items() if k.startswith("ORG.")}}


def print_envelope(db: Session, ctx, settings, d: Donation, doc_id: int, *, return_address: bool | None,
                   page: str | None, guide: str | None, test: bool, confirmations: list[str]) -> bytes:
    """Prints the donor's envelope with a template tagged for Donations, like a cover letter's envelope. The printed
    envelope is kept with the donation and on every deposit it is linked to; audited. The test on plain paper is
    neither kept nor counted."""
    from .checkprint import service as cp
    _check_envelope_printable(db, d)
    doc = _donation_envelope(db, ctx, doc_id)
    if not doc.active:
        raise conflict("TEMPLATE_INACTIVE", "Choose an active envelope template.")
    cfg = cp.doc_config(doc)
    e = db.get(Entity, d.donor_entity_id)
    use_return = cfg.return_address if return_address is None else return_address
    to_lines = [e.legal_name] + address_lines(e)
    ret, to, empty = documents.envelope_lines(cfg, _envelope_values(db, ctx, d, e), to_lines, use_return)
    if not test:
        warnings = []
        if not to_lines[1:]:
            warnings.append(Warning_("NO_DONOR_ADDRESS", "The donor has no address. Add it to the donor's entity, or "
                                     "print the envelope with the name only?"))
        if empty:
            warnings.append(Warning_("EMPTY_VARIABLES", "These variables have no data: " +
                                     ", ".join("{" + v + "}" for v in empty) + ". Print anyway?", variables=empty))
        require_confirmations(warnings, confirmations)
    opt = cp.envelope_options(db, ctx, doc, {"page": page, "guide": guide})
    pdf = documents.envelope_pdf(cfg, ret, to, page=opt["page"], guide=opt["guide"], dx=opt["dx"], dy=opt["dy"],
                                 test=test)
    if test:
        audit.record(db, ctx, "DONATION_ENVELOPE_TEST", "donation", d.id, None,
                     {"donation_id": d.id, "document_id": doc.id, "page": opt["page"], "guide": opt["guide"]})
        db.commit()
        return pdf
    # the kept copy is drawn without the feed offsets, so the same envelope is kept only once
    copy_pdf = documents.envelope_pdf(cfg, ret, to, page="ENVELOPE")
    fname = f"envelope-donation-{d.id}.pdf"
    deposits = [t for t in deposits_of(db, d) if t.status == "ACTIVE"]
    added, paths = False, []
    for t in deposits:
        a, path = _store_doc_copy(db, ctx, settings, t, ENVELOPE_COPY, fname, copy_pdf)
        added = added or a
        paths.append(path)
    a, path = _store_donation_copy(db, ctx, settings, d, ENVELOPE_COPY, fname, copy_pdf)
    added = added or a
    paths.append(path)
    audit.record(db, ctx, "DONATION_ENVELOPE_PRINTED", "donation", d.id, None,
                 {"donation_id": d.id, "document_id": doc.id, "donor_entity_id": e.id, "return_address": use_return,
                  "page": opt["page"], "guide": opt["guide"], "transaction_ids": [t.id for t in deposits],
                  "attached": added})
    try:
        db.commit()
    except Exception:
        db.rollback()
        for x in paths:
            if x is not None:
                try:
                    x.unlink()
                except OSError:
                    pass
        raise
    return pdf


# ------------------------------------------------------------------ Audit and Close reports
def non_cash_received(db: Session, ws_id: int, start: dt.date, end: dt.date) -> list[dict]:
    """Items received in a period (the Fiscal Year): for the Audit and Close reports' "Non-cash donations
    received" section. Values are the organization's own estimates (never printed on receipts)."""
    out = []
    for x in db.scalars(select(DonationLine).where(DonationLine.workspace_id == ws_id, DonationLine.kind == ITEM,
                                                   DonationLine.item_received.is_(True),
                                                   DonationLine.date_received >= start,
                                                   DonationLine.date_received <= end)
                        .order_by(DonationLine.date_received, DonationLine.id)):
        d = db.get(Donation, x.donation_id) if x.donation_id else None
        if d is None or d.status != ACTIVE:
            continue
        e = db.get(Entity, d.donor_entity_id)
        receipts = _receipts_of(db, d)
        cur = _current(receipts)
        out.append({"date": x.date_received, "donor": e.display_name, "description": x.description or "",
                    "value_cents": x.amount_cents, "no_value_reason": x.item_no_value_reason if x.item_no_value else None,
                    "receipt": cur.number if cur else None, "donation_id": d.id})
    return out
