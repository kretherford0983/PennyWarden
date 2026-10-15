"""2.0.0 (#165, #166): payment cover letters and #10 envelopes.

Letter: Letter page, 1" margins; typed letterhead lines (first line bold), today's date, the payee's name and address,
subject, salutation, opening paragraph, the invoice table (chosen columns, renamable headings; headings repeat on a
second page), the total line, closing paragraph(s), sign-off and the signer block (the check's signer, else the
template's fallback name and role). Never the signature image or the bank account number.

Envelope: #10 (9.5 x 4.125 in) by default; optional return address (top left), the payee's name and address (the
standard delivery-address position); fed like a single check (stamp end first, Letter page at the guides or an
envelope-sized page), with an offset per template and each user's own adjustment.

Text sections are patterns (patterns.LETTER / ENVELOPE context: `{VARIABLES}`, line breaks allowed).
"""
from __future__ import annotations

import io
from typing import Literal
from xml.sax.saxutils import escape

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import fonts, patterns
from .config import FEED_OFFSET_MAX

PT = 72.0
COLUMN_KEYS = {"INVOICE": "Invoice #", "INVOICE_DATE": "Invoice Date", "DESCRIPTION": "Description",
               "BUDGET": "Budget", "NOTES": "Notes", "AMOUNT": "Amount"}
DOC_FONTS = ("SANS", "SERIF", "CARLITO")


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_pattern(v: str, context: str) -> str:
    patterns.parse(v, context)          # raises PatternError (a ValueError) with the message the user sees
    return v


class Column(_M):
    key: Literal["INVOICE", "INVOICE_DATE", "DESCRIPTION", "BUDGET", "NOTES", "AMOUNT"]
    heading: str = Field(min_length=1, max_length=40)


# #177: a standard #10 double-window envelope with a Letter page folded in three (address panel on top). Positions are
# where the text starts, in inches from the page's top-left corner; the windows are drawn on the test print only.
WINDOW_PRESET = {
    "return": {"x": 0.55, "y": 0.55, "window": (0.45, 0.45, 3.25, 0.875)},     # upper window (left, top, w, h)
    "payee": {"x": 0.85, "y": 2.1, "window": (0.75, 1.95, 4.0, 1.125)},        # lower window
}
FOLD_LINES = (11 / 3, 22 / 3)
WINDOW_OFFSET_MAX = 0.75
LOGO_MAX_W, LOGO_MAX_H = 2.5, 1.0        # inches (#176)


class LetterConfig(_M):
    font: Literal["SANS", "SERIF", "CARLITO"] = "CARLITO"
    size: float = Field(default=11, ge=8, le=14)
    letterhead: list[str] = Field(default_factory=lambda: ["{ORG}"], max_length=6)
    show_date: bool = True
    subject: str = Field(default="Payment for Invoices", max_length=200)
    salutation: str = Field(default="To whom it may concern,", max_length=200)
    opening: str = Field(default="Enclosed please find payment for the following invoices:", max_length=2000)
    columns: list[Column] = Field(default_factory=lambda: [Column(key="INVOICE", heading="Invoice #"),
                                                           Column(key="INVOICE_DATE", heading="Invoice Date"),
                                                           Column(key="AMOUNT", heading="Amount Due")],
                                  min_length=1, max_length=6)
    total_label: str = Field(default="Total Payment Enclosed:", max_length=60)
    closing: str = Field(default="Please apply this payment to the invoices listed above. If there are any "
                                 "discrepancies or questions, please contact us.\n\n"
                                 "Thank you for your continued service and partnership.", max_length=2000)
    signoff: str = Field(default="Sincerely,", max_length=60)
    fallback_name: str = Field(default="", max_length=120)
    fallback_role: str = Field(default="", max_length=120)
    include_by_default: bool = True
    # #176: logo position (the logo itself is stored with the template) and pre-printed letterhead paper
    logo_position: Literal["LEFT", "CENTER"] = "LEFT"
    preprinted: bool = False
    preprinted_margin: float = Field(default=2.0, ge=1.0, le=4.0)      # inches kept blank at the top
    # #177: #10 double-window envelope - the address on the letter itself, or on a separate address page
    window: Literal["NONE", "LETTER", "ADDRESS_PAGE"] = "NONE"
    window_return: bool = True                                          # return address in the upper window
    return_dx: float = Field(default=0, ge=-WINDOW_OFFSET_MAX, le=WINDOW_OFFSET_MAX)
    return_dy: float = Field(default=0, ge=-WINDOW_OFFSET_MAX, le=WINDOW_OFFSET_MAX)
    payee_dx: float = Field(default=0, ge=-WINDOW_OFFSET_MAX, le=WINDOW_OFFSET_MAX)
    payee_dy: float = Field(default=0, ge=-WINDOW_OFFSET_MAX, le=WINDOW_OFFSET_MAX)

    @field_validator("letterhead")
    @classmethod
    def _lh(cls, v):
        for line in v:
            if len(line) > 200:
                raise ValueError("A letterhead line may have at most 200 characters.")
            _check_pattern(line, patterns.LETTER)
            if "\n" in line:
                raise ValueError("Each letterhead line is one line.")
        return v

    @model_validator(mode="after")
    def _check(self):
        for name in ("subject", "salutation", "opening", "closing", "signoff", "fallback_name", "fallback_role"):
            try:
                _check_pattern(getattr(self, name), patterns.LETTER)
            except patterns.PatternError as e:
                raise ValueError(f"{name.replace('_', ' ').capitalize()}: {e}") from None
        keys = [c.key for c in self.columns]
        if len(set(keys)) != len(keys):
            raise ValueError("Each table column can be used once.")
        return self


class EnvelopeConfig(_M):
    width: float = Field(default=9.5, ge=6, le=11)
    height: float = Field(default=4.125, ge=3, le=6)
    font: Literal["SANS", "SERIF", "CARLITO"] = "SANS"
    size: float = Field(default=11, ge=8, le=14)
    upper: bool = False
    return_address: bool = False
    return_lines: list[str] = Field(default_factory=lambda: ["{ORG}"], max_length=5)
    return_x: float = Field(default=0.35, ge=0, le=6)
    return_y: float = Field(default=0.35, ge=0, le=3)
    address_x: float = Field(default=4.0, ge=0, le=8)
    address_y: float = Field(default=1.9, ge=0, le=4)
    lead: Literal["STAMP_END", "OTHER_END"] = "STAMP_END"
    page: Literal["LETTER", "ENVELOPE"] = "LETTER"
    guide: Literal["CENTER", "LEFT", "RIGHT"] = "CENTER"
    dx: float = Field(default=0, ge=-FEED_OFFSET_MAX, le=FEED_OFFSET_MAX)
    dy: float = Field(default=0, ge=-FEED_OFFSET_MAX, le=FEED_OFFSET_MAX)
    note: str | None = Field(default="Feed the envelope through the manual feed, stamp end first.", max_length=200)

    @field_validator("return_lines")
    @classmethod
    def _rl(cls, v):
        for line in v:
            if len(line) > 200 or "\n" in line:
                raise ValueError("Each return address line is one line of at most 200 characters.")
            _check_pattern(line, patterns.ENVELOPE)
        return v

    @model_validator(mode="after")
    def _check(self):
        if self.address_x >= self.width - 1 or self.address_y >= self.height - 0.5:
            raise ValueError("The address would print off the envelope.")
        return self


def parse(kind: str, data: dict):
    return (LetterConfig if kind == "LETTER" else EnvelopeConfig).model_validate(data)


def default_config(kind: str, letterhead: list[str] | None = None) -> dict:
    if kind == "LETTER":
        return LetterConfig().model_dump()
    cfg = EnvelopeConfig()
    if letterhead:
        cfg.return_lines = letterhead[:5]
    return cfg.model_dump()


# ------------------------------------------------------------------ content
class LetterData(BaseModel):
    values: dict[str, str]
    rows: list[dict[str, str]]          # per invoice line: INVOICE, INVOICE_DATE, DESCRIPTION, BUDGET, NOTES, AMOUNT
    total: str                          # "$3,199.30"
    payee_lines: list[str]              # name + address lines
    signer_name: str = ""
    signer_title: str = ""


def _resolve(text: str, values: dict, context: str, empty: list[str]) -> str:
    r = patterns.resolve(text, values, context)
    for v in r.empty:
        if v not in empty:
            empty.append(v)
    return r.text


def letter_texts(cfg: LetterConfig, data: LetterData) -> tuple[dict, list[str]]:
    """The letter's resolved text sections and the variables that had no data."""
    empty: list[str] = []
    vals = {**data.values, "SIGNER": data.signer_name, "SIGNER_TITLE": data.signer_title}
    out = {
        "letterhead": [_resolve(x, vals, patterns.LETTER, empty) for x in cfg.letterhead],
        "subject": _resolve(cfg.subject, vals, patterns.LETTER, empty),
        "salutation": _resolve(cfg.salutation, vals, patterns.LETTER, empty),
        "opening": _resolve(cfg.opening, vals, patterns.LETTER, empty),
        "closing": _resolve(cfg.closing, vals, patterns.LETTER, empty),
        "signoff": _resolve(cfg.signoff, vals, patterns.LETTER, empty),
    }
    if data.signer_name:
        name, role = data.signer_name, ", ".join(x for x in (data.signer_title, vals.get("ORG", "")) if x)
    else:
        name = _resolve(cfg.fallback_name, vals, patterns.LETTER, empty)
        role = _resolve(cfg.fallback_role, vals, patterns.LETTER, empty)
    out["signer_name"], out["signer_role"] = name, role
    return out, empty


def _para_text(text: str) -> str:
    return "<br/>".join(escape(line) for line in text.split("\n"))


def window_blocks(cfg: LetterConfig, texts: dict, payee_lines: list[str]) -> list[tuple[str, float, float, list[str]]]:
    """#177: (which, x, y, lines) of the address blocks shown through the windows: the return address (the letterhead
    lines) in the upper window when chosen, the payee's name and address in the lower one."""
    out = []
    if cfg.window_return:
        lines = [x for x in texts["letterhead"] if x.strip()]
        if lines:
            p = WINDOW_PRESET["return"]
            out.append(("return", p["x"] + cfg.return_dx, p["y"] + cfg.return_dy, lines[:4]))
    if payee_lines:
        p = WINDOW_PRESET["payee"]
        out.append(("payee", p["x"] + cfg.payee_dx, p["y"] + cfg.payee_dy, list(payee_lines)[:5]))
    return out


def _logo_size(png: bytes) -> tuple[float, float]:
    iw, ih = ImageReader(io.BytesIO(png)).getSize()
    scale = min(LOGO_MAX_W * PT / iw, LOGO_MAX_H * PT / ih)
    return iw * scale, ih * scale


def letter_pdf(cfg: LetterConfig, data: LetterData, title: str = "Cover letter", logo: bytes | None = None,
               test: bool = False) -> bytes:
    """`logo` (#176): the template's PNG logo; `test` (#177): the window outlines and fold marks are drawn (test print
    and preview only, never on a real letter)."""
    texts, _empty = letter_texts(cfg, data)
    reg, bold = fonts.ps_name(cfg.font), fonts.ps_name(cfg.font, True)
    size = cfg.size
    base = ParagraphStyle("base", fontName=reg, fontSize=size, leading=size * 1.25)
    strong = ParagraphStyle("strong", parent=base, fontName=bold)
    centred = cfg.logo_position == "CENTER" and logo is not None
    head = ParagraphStyle("head", parent=base, alignment=1 if centred else 0)
    head_b = ParagraphStyle("head_b", parent=strong, alignment=1 if centred else 0)
    windowed = cfg.window != "NONE"
    blocks = window_blocks(cfg, texts, data.payee_lines) if windowed else []

    def first_page(c, _doc):
        if not windowed and not test:
            return
        c.saveState()
        if blocks:
            for which, x, y, lines in blocks:
                yy = (11 - y) * PT - size
                for i, line in enumerate(lines):
                    c.setFont(bold if (which == "return" and i == 0) else reg, size)
                    c.drawString(x * PT, yy, line)
                    yy -= size * 1.2
        if windowed and logo is not None and cfg.window == "LETTER" and not cfg.preprinted:
            w, h = _logo_size(logo)                              # top right, clear of the windows
            c.drawImage(ImageReader(io.BytesIO(logo)), (8.5 - 0.5) * PT - w, (11 - 0.5) * PT - h, w, h, mask="auto")
        if test and windowed:
            c.setStrokeGray(0.45)
            c.setLineWidth(0.6)
            c.setDash(3, 2)
            for key in ("return", "payee"):
                if key == "return" and not cfg.window_return:
                    continue
                left, top, w, h = WINDOW_PRESET[key]["window"]
                c.rect(left * PT, (11 - top - h) * PT, w * PT, h * PT, stroke=1, fill=0)
            c.setDash()
            c.setFont(fonts.ps_name("SANS"), 6.5)
            for f in FOLD_LINES:
                y = (11 - f) * PT
                c.line(0.25 * PT, y, 0.6 * PT, y)
                c.line(7.9 * PT, y, 8.25 * PT, y)
                c.drawString(0.65 * PT, y - 2, "fold")
            c.drawRightString(8.0 * PT, (11 - 3.55) * PT, "WINDOW ALIGNMENT - dashed boxes: #10 double-window envelope")
        c.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=(8.5 * inch, 11 * inch), leftMargin=inch, rightMargin=inch,
                            topMargin=inch, bottomMargin=inch, title=title, creator="PennyWarden",
                            author="", subject="", invariant=1)
    story = []
    if cfg.window == "ADDRESS_PAGE":
        story += [Spacer(1, 1), PageBreak()]           # page 1: only the addresses, for the windows
    if cfg.window == "LETTER":
        story.append(Spacer(1, (FOLD_LINES[0] + 0.15 - 1) * inch))   # the body starts below the address panel
    elif cfg.preprinted:
        story.append(Spacer(1, (cfg.preprinted_margin - 1) * inch))  # the paper's own letterhead is above
    else:
        if logo is not None:
            w, h = _logo_size(logo)
            story.append(Image(io.BytesIO(logo), width=w, height=h, hAlign="CENTER" if centred else "LEFT"))
            story.append(Spacer(1, size * 0.6))
        for i, line in enumerate(texts["letterhead"]):
            if line.strip():
                story.append(Paragraph(escape(line), head_b if i == 0 else head))
    if cfg.show_date:
        story.append(Paragraph(escape(data.values.get("TODAY", "")), base))
    story.append(Spacer(1, size * 1.4))
    if data.payee_lines and cfg.window != "LETTER":
        story.append(Paragraph(f"<font name='{bold}'>To:</font><br/>{'<br/>'.join(escape(x) for x in data.payee_lines)}",
                               base))
        story.append(Spacer(1, size))
    if texts["subject"].strip():
        story.append(Paragraph(f"<font name='{bold}'>Subject:</font> {escape(texts['subject'])}", base))
        story.append(Spacer(1, size))
    for key in ("salutation", "opening"):
        if texts[key].strip():
            for para in texts[key].split("\n\n"):
                story.append(Paragraph(_para_text(para), base))
                story.append(Spacer(1, size * 0.7))
    # invoice table
    right = ParagraphStyle("right", parent=base, alignment=2)
    right_b = ParagraphStyle("right_b", parent=strong, alignment=2)
    header = [Paragraph(escape(c.heading), right_b if c.key == "AMOUNT" else strong) for c in cfg.columns]
    body = [[Paragraph(escape(r.get(c.key, "")), right if c.key == "AMOUNT" else base) for c in cfg.columns]
            for r in data.rows]
    tbl = Table([header] + body, repeatRows=1, hAlign="LEFT",
                colWidths=[6.5 * inch / len(cfg.columns)] * len(cfg.columns))
    style = [("LINEBELOW", (0, 0), (-1, 0), 0.8, "#444444"), ("LINEBELOW", (0, -1), (-1, -1), 0.5, "#888888"),
             ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("TOPPADDING", (0, 0), (-1, -1), 3)]
    tbl.setStyle(TableStyle(style))
    story.append(tbl)
    story.append(Spacer(1, size * 0.8))
    story.append(Paragraph(f"<font name='{bold}'>{escape(cfg.total_label)}</font> {escape(data.total)}", base))
    story.append(Spacer(1, size * 1.2))
    if texts["closing"].strip():
        for para in texts["closing"].split("\n\n"):
            story.append(Paragraph(_para_text(para), base))
            story.append(Spacer(1, size * 0.7))
    story.append(Spacer(1, size * 0.5))
    lines = [escape(texts["signoff"])] if texts["signoff"].strip() else []
    if texts["signer_name"].strip():
        lines.append(f"<font name='{bold}'>{escape(texts['signer_name'])}</font>")
    if texts["signer_role"].strip():
        lines.append(escape(texts["signer_role"]))
    if lines:
        story.append(Paragraph("<br/>".join(lines), base))
    doc.build(story, onFirstPage=first_page)
    return buf.getvalue()


# ------------------------------------------------------------------ envelope
def envelope_lines(cfg: EnvelopeConfig, values: dict, payee_lines: list[str], return_address: bool
                   ) -> tuple[list[str], list[str], list[str]]:
    """(return address lines, delivery address lines, empty variables)."""
    empty: list[str] = []
    ret = [_resolve(x, values, patterns.ENVELOPE, empty) for x in cfg.return_lines] if return_address else []
    ret = [x for x in ret if x.strip()]
    to = list(payee_lines)
    if cfg.upper:
        ret, to = [x.upper() for x in ret], [x.upper() for x in to]
    return ret, to, empty


def _envelope_page(c, cfg: EnvelopeConfig, page: str, guide: str, dx: float, dy: float) -> None:
    """Like a single check: the envelope turned so the chosen end feeds first (stamp end = right end)."""
    w, h = cfg.width, cfg.height
    if page == "ENVELOPE":
        c.setPageSize((h * PT, w * PT))
        gx, strip_top = 0.0, w
    else:
        c.setPageSize((8.5 * PT, 11 * PT))
        gx = {"LEFT": 0.0, "RIGHT": 8.5 - h}.get(guide, (8.5 - h) / 2)
        strip_top = 11.0
    if cfg.lead == "STAMP_END":
        c.translate((gx + h) * PT, (strip_top - w) * PT)
        c.rotate(90)
    else:
        c.translate(gx * PT, strip_top * PT)
        c.rotate(-90)
    c.translate(dx * PT, -dy * PT)


def envelope_pdf(cfg: EnvelopeConfig, ret: list[str], to: list[str], *, page: str | None = None,
                 guide: str | None = None, dx: float = 0.0, dy: float = 0.0, test: bool = False,
                 preview: bool = False) -> bytes:
    """`preview` (#186): the envelope itself, upright on an envelope-sized page with its edge drawn - for the setup
    screen's live preview, never printed."""
    from reportlab.pdfgen import canvas as rl_canvas
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pageCompression=1, invariant=1)
    c.setTitle("Envelope test" if test else "Envelope")
    c.setCreator("PennyWarden")
    try:
        c.setViewerPreference("PrintScaling", "None")
    except Exception:  # pragma: no cover
        pass
    h = cfg.height
    if preview:
        c.setPageSize((cfg.width * PT, h * PT))
        c.saveState()
        c.setLineWidth(0.8)
        c.setStrokeGray(0.55)
        c.rect(0, 0, cfg.width * PT, h * PT, stroke=1, fill=0)
        c.restoreState()
    else:
        _envelope_page(c, cfg, page or cfg.page, guide or cfg.guide, cfg.dx + dx, cfg.dy + dy)
    if test:
        c.saveState()
        c.setLineWidth(0.6)
        c.setStrokeGray(0.3)
        c.rect(0, 0, cfg.width * PT, h * PT, stroke=1, fill=0)
        c.setFont(fonts.ps_name("SANS", True), 8)
        c.drawRightString(cfg.width * PT - 8, h * PT - 14, "ENVELOPE TEST - PLAIN PAPER")
        c.setLineWidth(0.8)
        x0 = 0.5 * PT
        c.line(x0, 0.4 * PT, x0 + 5 * PT, 0.4 * PT)
        c.line(x0, 0.32 * PT, x0, 0.48 * PT)
        c.line(x0 + 5 * PT, 0.32 * PT, x0 + 5 * PT, 0.48 * PT)
        c.setFont(fonts.ps_name("SANS"), 6.5)
        c.drawCentredString(x0 + 2.5 * PT, 0.44 * PT, "5.000 in - if this is not exactly 5 inches, set the scale "
                                                       "to 100% / Actual size")
        c.restoreState()
    name = fonts.ps_name(cfg.font)
    lead = cfg.size * 1.2
    c.setFont(name, cfg.size - 1)
    y = (h - cfg.return_y) * PT - cfg.size
    for line in ret:
        c.drawString(cfg.return_x * PT, y, line)
        y -= lead * 0.95
    c.setFont(name, cfg.size)
    y = (h - cfg.address_y) * PT - cfg.size
    for line in to:
        c.drawString(cfg.address_x * PT, y, line)
        y -= lead
    c.showPage()
    c.save()
    return buf.getvalue()


# ------------------------------------------------------------------ sample data (setup test prints, no real data)
SAMPLE_ROWS = [{"INVOICE": "158092", "INVOICE_DATE": "08/29/2026", "DESCRIPTION": "Supplies",
                "BUDGET": "51 Operations", "NOTES": "", "AMOUNT": "$153.44"},
               {"INVOICE": "158117", "INVOICE_DATE": "09/05/2026", "DESCRIPTION": "Delivery",
                "BUDGET": "51 Operations", "NOTES": "", "AMOUNT": "$46.56"}]
SAMPLE_PAYEE = ["SAMPLE VENDOR COMPANY", "123 Main Street", "P.O. Box 123", "Sample Town, US 55555"]
