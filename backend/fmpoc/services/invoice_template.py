"""2.4.0 (#253 part 3): the invoice PDF template, built on the cover-letter editor's pieces (fonts, logo handling,
{VARIABLES}, live preview).

The Administrator (Invoices Setup) chooses the font and size, an accent color, the logo and its place, the
letterhead lines, the title, the Bill to lines, the line-table columns (picked and ordered, each with its heading),
whether invoice fields, terms and notes print, and a footer. Texts take {VARIABLES} - the organization ({ORG.*}),
the customer ({CUSTOMER.*}) and the invoice ({INVOICE.*}); an unknown name is refused when saving, with the closest
match suggested. Substitution is a fixed table lookup (BR-102). Previews and test prints use sample data only (BR-003).
One template for the organization; every invoice PDF made afterwards uses it (PDFs already kept for sent versions
don't change).
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from xml.sax.saxutils import escape

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, validation
from ..models import InvoiceSettings
from .checkprint import fonts, patterns

CTX = patterns.INVOICE_DOC
COLUMN_KEYS = ("DESCRIPTION", "CODE", "UNIT", "QUANTITY", "UNIT_PRICE", "AMOUNT", "DISCOUNT", "NET")
COLUMN_LABELS = {"DESCRIPTION": "Description", "CODE": "Product code", "UNIT": "Unit", "QUANTITY": "Quantity",
                 "UNIT_PRICE": "Unit price", "AMOUNT": "Amount (before discount)", "DISCOUNT": "Line discount",
                 "NET": "Net (after line discount)"}
MONEYISH = ("UNIT_PRICE", "AMOUNT", "DISCOUNT", "NET", "QUANTITY")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Column(_M):
    key: str
    heading: str = Field(min_length=1, max_length=30)

    @field_validator("key")
    @classmethod
    def _k(cls, v):
        if v not in COLUMN_KEYS:
            raise ValueError("Unknown column.")
        return v


def _check(v: str, what: str) -> str:
    try:
        patterns.parse(v, CTX)
    except patterns.PatternError as e:
        raise ValueError(f"{what}: {e}") from None
    return v


class TemplateConfig(_M):
    font: str = "CARLITO"
    size: float = Field(default=10, ge=8, le=12)
    accent: str = "#1F3A5F"
    logo_position: str = "LEFT"                          # NONE | LEFT | RIGHT
    letterhead: list[str] = Field(default_factory=lambda: ["{ORG}", "{ORG.ADDRESS}", "{ORG.PHONE}"], max_length=6)
    title: str = Field(default="INVOICE", max_length=40)
    bill_to_heading: str = Field(default="Bill to", max_length=40)
    bill_to: list[str] = Field(default_factory=lambda: ["{CUSTOMER.NAME}", "{CUSTOMER.MAILING_ADDRESS}"], max_length=6)
    columns: list[Column] = Field(default_factory=lambda: [
        Column(key="DESCRIPTION", heading="Description"), Column(key="QUANTITY", heading="Qty"),
        Column(key="UNIT_PRICE", heading="Unit price"), Column(key="AMOUNT", heading="Amount")], min_length=1, max_length=8)
    show_fields: bool = True
    show_terms: bool = True
    show_notes: bool = True
    footer: str = Field(default="", max_length=2000)

    @field_validator("font")
    @classmethod
    def _f(cls, v):
        if v not in fonts.FONTS:
            raise ValueError("Unknown font.")
        return v

    @field_validator("accent")
    @classmethod
    def _a(cls, v):
        if not HEX.match(v):
            raise ValueError("The accent color is #RRGGBB.")
        return v.upper()

    @field_validator("logo_position")
    @classmethod
    def _lp(cls, v):
        if v not in ("NONE", "LEFT", "RIGHT"):
            raise ValueError("The logo goes left, right or nowhere.")
        return v

    @field_validator("letterhead", "bill_to")
    @classmethod
    def _lines(cls, v):
        for line in v:
            if len(line) > 200 or "\n" in line:
                raise ValueError("Each line is one line of at most 200 characters.")
            _check(line, "A line")
        return v

    @model_validator(mode="after")
    def _all(self):
        for name in ("title", "bill_to_heading", "footer"):
            _check(getattr(self, name), name.replace("_", " ").capitalize())
        keys = [c.key for c in self.columns]
        if len(set(keys)) != len(keys):
            raise ValueError("Each column can be used once.")
        if "DESCRIPTION" not in keys:
            raise ValueError("The Description column is required.")
        if not ({"AMOUNT", "NET"} & set(keys)):
            raise ValueError("Choose the Amount or the Net column.")
        return self


def parse(data: dict | None) -> TemplateConfig:
    try:
        return TemplateConfig(**(data or {}))
    except ValidationError as e:
        msg = "; ".join(str(x.get("msg", "")).removeprefix("Value error, ") for x in e.errors()[:3])
        raise validation(msg or "The template is not valid.", "template") from None


def stored(s: InvoiceSettings) -> TemplateConfig:
    try:
        return TemplateConfig(**json.loads(s.template_json)) if s.template_json else TemplateConfig()
    except (ValueError, ValidationError):
        return TemplateConfig()


def out(s: InvoiceSettings) -> dict:
    return {"config": stored(s).model_dump(), "has_logo": bool(s.logo_png), "logo_sha256": s.logo_sha256,
            "columns": [{"key": k, "label": COLUMN_LABELS[k]} for k in COLUMN_KEYS],
            "fonts": [{"key": k, "label": v[0]} for k, v in fonts.FONTS.items()],
            "variables": patterns.variable_options(CTX)}


def save(db: Session, ctx, s: InvoiceSettings, data: dict) -> dict:
    cfg = parse(data)
    before = stored(s).model_dump()
    s.template_json = json.dumps(cfg.model_dump(), sort_keys=True)
    s.updated_by_user_id = ctx.user.id
    db.flush()
    if cfg.model_dump() != before:
        audit.record(db, ctx, "INVOICE_TEMPLATE_UPDATED", "invoice_settings", s.id, before, cfg.model_dump())
    return out(s)


def set_logo(db: Session, ctx, s: InvoiceSettings, data: bytes | None) -> dict:
    from .checkprint.service import normalize_logo
    before = {"logo_sha256": s.logo_sha256}
    if data is None:
        s.logo_png = s.logo_sha256 = None
        action = "INVOICE_LOGO_REMOVED"
    else:
        png, _w, _h = normalize_logo(data)
        s.logo_png, s.logo_sha256 = png, hashlib.sha256(png).hexdigest()
        action = "INVOICE_LOGO_SET"
    db.flush()
    audit.record(db, ctx, action, "invoice_settings", s.id, before, {"logo_sha256": s.logo_sha256})
    return out(s)


# ------------------------------------------------------------------ rendering
def render(cfg: TemplateConfig, data: dict, values: dict[str, str], logo: bytes | None, watermark: str | None,
           author: str) -> bytes:
    """data: number/date/due, lines (description, code, unit, qty, price, amount, discount, net, discount_reason),
    totals, terms, notes, fields; values: the {VARIABLES}."""
    from reportlab.lib import colors
    from reportlab.lib.fonts import addMapping
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    reg, bold = fonts.ps_name(cfg.font), fonts.ps_name(cfg.font, True)
    addMapping(reg, 0, 0, reg)
    addMapping(reg, 1, 0, bold)
    addMapping(reg, 0, 1, reg)
    addMapping(reg, 1, 1, bold)
    accent = colors.HexColor(cfg.accent)
    sz = cfg.size
    body = ParagraphStyle("b", fontName=reg, fontSize=sz, leading=sz * 1.25)
    bodyb = ParagraphStyle("bb", parent=body, fontName=bold)
    small = ParagraphStyle("s", parent=body, fontSize=sz - 1.5, leading=(sz - 1.5) * 1.25, textColor=colors.HexColor("#555555"))
    right = ParagraphStyle("r", parent=body, alignment=2)
    rightb = ParagraphStyle("rb", parent=right, fontName=bold)
    head_r = ParagraphStyle("hr", parent=rightb, textColor=colors.white)
    head_l = ParagraphStyle("hl", parent=bodyb, textColor=colors.white)
    title = ParagraphStyle("t", fontName=bold, fontSize=sz * 2, leading=sz * 2.3, alignment=2, textColor=accent)

    def lines(patterns_: list[str]) -> list[str]:
        out: list[str] = []
        for p in patterns_:
            out += [x.strip() for x in patterns.resolve(p, values, CTX).text.split("\n") if x.strip()]
        return out

    def text(p: str) -> str:
        return patterns.resolve(p, values, CTX).text

    buf = io.BytesIO()

    def mark(canvas, _doc):
        if watermark:
            canvas.saveState()
            canvas.setFont("Helvetica-Bold", 48)
            canvas.setFillColor(colors.Color(0.85, 0.85, 0.85, alpha=0.5))
            canvas.translate(letter[0] / 2, letter[1] / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, watermark)
            canvas.restoreState()

    width = letter[0] - 1.5 * inch
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch, topMargin=0.6 * inch,
                            bottomMargin=0.7 * inch, title=f"Invoice {data['number']}", author=author)
    lh = lines(cfg.letterhead)
    left: list = []
    if logo and cfg.logo_position == "LEFT":
        left.append(_logo(logo, Image))
    left += [Paragraph(escape(x), bodyb if k == 0 else body) for k, x in enumerate(lh)]
    rcol: list = []
    if logo and cfg.logo_position == "RIGHT":
        rcol.append(_logo(logo, Image, align="RIGHT"))
    rcol += [Paragraph(escape(text(cfg.title) or "INVOICE"), title), Paragraph(f"<b>{escape(data['number'])}</b>", right),
             Paragraph(f"Date: {escape(data['date'])}", right), Paragraph(f"Due: {escape(data['due'])}", right)]
    head = Table([[left or "", rcol]], colWidths=[width * 0.55, width * 0.45])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    f: list = [head, Spacer(1, 14)]
    bill = lines(cfg.bill_to)
    if bill:
        f.append(Paragraph(f"<b>{escape(text(cfg.bill_to_heading))}</b>", ParagraphStyle("bh", parent=body, textColor=accent)))
        f += [Paragraph(escape(x), body) for x in bill]
    if cfg.show_fields:
        for name, value in data.get("fields") or []:
            f.append(Paragraph(f"<b>{escape(name)}:</b> {escape(value)}", body))
    f.append(Spacer(1, 12))
    cols = cfg.columns
    keys = [c.key for c in cols]
    show_disc_rows = "DISCOUNT" not in keys and "NET" not in keys
    hdr = [Paragraph(escape(c.heading), head_r if c.key in MONEYISH else head_l) for c in cols]
    rows = [hdr]
    for ln in data["lines"]:
        cells = []
        for c in cols:
            v = {"DESCRIPTION": ln["description"], "CODE": ln.get("code") or "", "UNIT": ln.get("unit") or "",
                 "QUANTITY": ln["qty"], "UNIT_PRICE": ln["price"], "AMOUNT": ln["amount"],
                 "DISCOUNT": (f"-{ln['discount']}" if ln.get("discount") else ""), "NET": ln.get("net") or ln["amount"]}[c.key]
            if c.key == "DESCRIPTION" and "UNIT" not in keys and ln.get("unit"):
                cells.append(Paragraph(escape(v) + f" <font size={sz - 2}>({escape(ln['unit'])})</font>", body))
            elif c.key == "DESCRIPTION" and ln.get("discount") and not show_disc_rows:
                cells.append(Paragraph(escape(v) + f"<br/><font size={sz - 2}>Discount: {escape(ln.get('discount_reason') or '')}</font>", body))
            else:
                cells.append(Paragraph(escape(v), right if c.key in MONEYISH else body))
        rows.append(cells)
        if show_disc_rows and ln.get("discount"):
            last = keys.index("AMOUNT") if "AMOUNT" in keys else len(keys) - 1
            r = [""] * len(keys)
            r[keys.index("DESCRIPTION")] = Paragraph(f"&nbsp;&nbsp;Discount — {escape(ln.get('discount_reason') or '')}", small)
            r[last] = Paragraph(f"-{escape(ln['discount'])}", right)
            rows.append(r)
    widths_fixed = {"CODE": 0.9, "UNIT": 0.6, "QUANTITY": 0.6, "UNIT_PRICE": 0.95, "AMOUNT": 0.95, "DISCOUNT": 0.9, "NET": 0.95}
    fixed = sum(widths_fixed[k] * inch for k in keys if k != "DESCRIPTION")
    cw = [max(width - fixed, 1.8 * inch) if k == "DESCRIPTION" else widths_fixed[k] * inch for k in keys]
    if sum(cw) > width:                                   # many columns: shrink the description
        cw[keys.index("DESCRIPTION")] = max(width - fixed, 1.2 * inch)
    t = Table(rows, colWidths=cw, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), accent), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3)]))
    f += [t, Spacer(1, 8)]
    tot = [["Subtotal", data["subtotal"]]]
    if data.get("invoice_discount"):
        tot.append([f"Discount — {data['invoice_discount_reason']}", f"-{data['invoice_discount']}"])
    if data.get("tax"):
        tot.append([data["tax_label"], data["tax"]])
    tot.append(["Total due", data["total"]])
    if data.get("paid"):
        tot.append(["Paid", f"-{data['paid']}"])
        tot.append(["Balance due", data["balance"]])
    tt = Table([[Paragraph(escape(a), rightb if a in ("Total due", "Balance due") else right),
                 Paragraph(escape(b), rightb if a in ("Total due", "Balance due") else right)] for a, b in tot],
               colWidths=[width - 1.2 * inch, 1.2 * inch])
    total_row = [k for k, (a, _b) in enumerate(tot) if a == "Total due"][0]
    tt.setStyle(TableStyle([("LINEABOVE", (0, total_row), (-1, total_row), 0.8, accent),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    f.append(tt)
    if cfg.show_terms and data.get("terms"):
        f += [Spacer(1, 12), Paragraph(f"<b>Terms:</b> {escape(data['terms'])}", body)]
    if cfg.show_notes and data.get("notes"):
        f += [Spacer(1, 6), Paragraph(escape(data["notes"]).replace("\n", "<br/>"), body)]
    foot = text(cfg.footer).strip() if cfg.footer else ""
    if foot:
        f += [Spacer(1, 16), Paragraph(escape(foot).replace("\n", "<br/>"), small)]
    doc.build(f, onFirstPage=mark, onLaterPages=mark)
    return buf.getvalue()


def _logo(png: bytes, Image, align: str = "LEFT"):
    from PIL import Image as PImage
    from reportlab.lib.units import inch
    im = PImage.open(io.BytesIO(png))
    w, h = im.size
    scale = min(2.2 * inch / w, 0.9 * inch / h)
    img = Image(io.BytesIO(png), width=w * scale, height=h * scale)
    img.hAlign = align
    return img


def logo_error() -> AppError:
    return AppError(413, "FILE_TOO_LARGE", "A logo may not exceed 1 MB.")
