"""Reporting (v1.2 CR-002; v1.3 CR-008).

* End of Year Audit report - a single printable PDF: title, Fiscal Year review, budgets, then every transaction of
  the year with its attachments reproduced beneath it.
* Fiscal Year Close report - the same, with the Fiscal Year documents (approval, audit signoff, other) placed after
  the review and before the budgets; generated on demand and automatically when the Fiscal Year is closed.
* Entity activity report - how much each entity deposited and withdrew for an account in a date range.

All user-controlled text is XML-escaped before it reaches reportlab's paragraph markup (prevents markup/<img>
injection); attachment bytes are read only through the application's generated storage paths and verified
against their recorded SHA-256.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import os
import tempfile
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (Flowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..errors import validation
from ..models import (Attachment, BankAccount, Budget, Entity, FiscalYear, FiscalYearReview, Fundraiser,
                      RegisterTransaction, TransactionAllocation, User, Workspace, utcnow)
from ..money import fmt
from . import bank_accounts as bank
from . import budgets as bsvc
from . import fundraisers as fsvc
from . import register as reg
from . import branding
from .attachments import DISPLAY_ORDER, path_for
from .common import budget_label
from .documentation import review as documentation_review
from .fiscal_years import closure_check

# --------------------------------------------------------------------------- fonts / styles
_FONT, _FONT_BOLD = "Helvetica", "Helvetica-Bold"
try:  # Bitstream Vera ships with reportlab and covers far more characters than the base-14 fonts
    import reportlab
    _fd = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    pdfmetrics.registerFont(TTFont("FMVera", os.path.join(_fd, "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("FMVeraBd", os.path.join(_fd, "VeraBd.ttf")))
    _FONT, _FONT_BOLD = "FMVera", "FMVeraBd"
except Exception:  # pragma: no cover - fall back to built-in fonts
    pass

_ss = getSampleStyleSheet()


class _Styles(dict):
    """2.2.0 (#280): the paragraph styles, with the headings (and the white text on title bands) in the organization's
    branding colors while a document is built (branding.themed). Other styles are as defined."""
    THEMED = {"title": "primary", "h1": "primary", "h2": "primary", "cover_title": "primary",
              "fs_w": "on_primary", "fs_wb": "on_primary", "fs_wt": "on_primary", "br_head": "on_primary"}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._cache: dict[tuple[str, str], ParagraphStyle] = {}

    def __getitem__(self, k):
        base = dict.__getitem__(self, k)
        role = self.THEMED.get(k)
        if role is None:
            return base
        hx = branding.hex_of(role)
        st = self._cache.get((k, hx))
        if st is None:
            st = ParagraphStyle(f"{base.name}_{hx[1:]}", parent=base, textColor=colors.HexColor(hx))
            self._cache[(k, hx)] = st
        return st


S = _Styles({
    "title": ParagraphStyle("t", parent=_ss["Title"], fontName=_FONT_BOLD, fontSize=20, leading=24),
    "h1": ParagraphStyle("h1", parent=_ss["Heading1"], fontName=_FONT_BOLD, fontSize=15, leading=18, spaceAfter=6),
    "h2": ParagraphStyle("h2", parent=_ss["Heading2"], fontName=_FONT_BOLD, fontSize=12, leading=15, spaceAfter=4),
    "body": ParagraphStyle("b", parent=_ss["BodyText"], fontName=_FONT, fontSize=9, leading=11.5),
    "small": ParagraphStyle("s", parent=_ss["BodyText"], fontName=_FONT, fontSize=7.5, leading=9.5),
    "cell": ParagraphStyle("c", parent=_ss["BodyText"], fontName=_FONT, fontSize=7.5, leading=9),
    "cellr": ParagraphStyle("cr", parent=_ss["BodyText"], fontName=_FONT, fontSize=7.5, leading=9, alignment=TA_RIGHT),
    "h3": ParagraphStyle("h3", parent=_ss["BodyText"], fontName=_FONT, fontSize=9, leading=11.5),
    "metak": ParagraphStyle("mk", parent=_ss["BodyText"], fontName=_FONT_BOLD, fontSize=10, leading=13),
    "metav": ParagraphStyle("mv", parent=_ss["BodyText"], fontName=_FONT, fontSize=10, leading=13),
    "cover_org": ParagraphStyle("co", parent=_ss["Title"], fontName=_FONT, fontSize=16, leading=20),
    "cover_title": ParagraphStyle("ct", parent=_ss["Title"], fontName=_FONT_BOLD, fontSize=28, leading=34),
    "cover_sub": ParagraphStyle("cs", parent=_ss["Title"], fontName=_FONT, fontSize=14, leading=19, spaceAfter=0),
    "sig_body": ParagraphStyle("sb", parent=_ss["BodyText"], fontName=_FONT, fontSize=11.5, leading=16),
    "cellb": ParagraphStyle("cb", parent=_ss["BodyText"], fontName=_FONT_BOLD, fontSize=7.5, leading=9),
})
PAGE_W, PAGE_H = letter
MARGIN = 0.6 * inch
FRAME_W = PAGE_W - 2 * MARGIN


def P(text, style="body") -> Paragraph:
    """Paragraph from *untrusted* text: always escaped, newlines preserved."""
    t = escape("" if text is None else str(text)).replace("\n", "<br/>")
    return Paragraph(t, S[style])


def PM(markup: str, style="body") -> Paragraph:
    """Paragraph from trusted markup built by this module (callers escape any user values)."""
    return Paragraph(markup, S[style])


def money(c: int | str | None) -> str:
    if c is None:
        return ""
    v = c if isinstance(c, str) else fmt(c)
    neg = v.startswith("-")
    i, d = v.lstrip("-").split(".")
    return f"{'-' if neg else ''}${int(i):,}.{d}"


def _grid(data, widths, header_rows=1, zebra=True, extra=None) -> Table:
    t = Table(data, colWidths=widths, repeatRows=header_rows)
    style = [("GRID", (0, 0), (-1, -1), 0.25, branding.color("outline")),
             ("BACKGROUND", (0, 0), (-1, header_rows - 1), branding.color("surface_variant")),
             ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
             ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
    if zebra:
        for r in range(header_rows, len(data)):
            if (r - header_rows) % 2:
                style.append(("BACKGROUND", (0, r), (-1, r), branding.color("surface")))
    t.setStyle(TableStyle(style + (extra or [])))
    return t


def _kv(rows: list[tuple[str, object]], w1=1.45 * inch, style="cell") -> Table:
    data = [[PM(f"<b>{escape(k)}</b>", style), P(v, style)] for k, v in rows]
    t = Table(data, colWidths=[w1, FRAME_W - 12 - w1])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    return t


# --------------------------------------------------------------------------- PDF assembly
class _Mark(Flowable):
    """Zero-size flowable that sets the footer label for the page it lands on (and later pages)."""

    def __init__(self, doc: "_AuditDoc", label: str):
        super().__init__()
        self._d, self._label = doc, label

    def wrap(self, aw, ah):
        return 0, 0

    def draw(self):
        self._d.current_label = self._label
        self._d.page_labels[self.canv.getPageNumber()] = self._label


class _SectionNote(Flowable):
    """1.6.7: reserves two lines on an account's start / end page and remembers where they are. The page range of
    the account's section is only known once the whole report is laid out, so the text is stamped afterwards."""

    HEIGHT = 34

    def __init__(self, doc: "_AuditDoc", section: dict, kind: str):
        super().__init__()
        self._d, self._s, self._kind = doc, section, kind

    def wrap(self, aw, ah):
        return aw, self.HEIGHT

    def draw(self):
        x, y = self.canv.absolutePosition(0, 0)
        self._s[self._kind] = (self.canv.getPageNumber(), x, y)


BODY_H = PAGE_H - MARGIN - (MARGIN + 0.25 * inch) - 12 - 4  # usable frame height (frame padding + safety)


class _Block(Flowable):
    """Caption flowables followed by attachment content scaled to the page frame width.

    The content keeps its aspect ratio and is as wide as the frame (height-limited for tall content). If the space
    left on the current page holds it at >= ``min_ratio`` of that size it is shrunk to fit there, so an attachment
    can sit directly under the transaction details; otherwise the whole block moves to the next page.
    """

    def __init__(self, head: list, iw: float, ih: float, draw_fn, min_ratio: float = 0.6):
        super().__init__()
        self.head, self.iw, self.ih, self._draw_fn, self.min_ratio = head, max(iw, 1.0), max(ih, 1.0), draw_fn, min_ratio

    def wrap(self, aw, ah):
        self.hs = []
        hh = 0.0
        for f in self.head:
            _, h = f.wrap(aw, ah)
            sb, sa = f.getSpaceBefore(), f.getSpaceAfter()
            self.hs.append((f, h, sb, sa))
            hh += h + sb + sa
        s = min(aw / self.iw, (BODY_H - hh) / self.ih)
        fw, fh = self.iw * s, self.ih * s
        if hh + fh > ah and ah - hh >= fh * self.min_ratio:
            r = (ah - hh) / fh
            fw, fh = fw * r, fh * r
        self.aw, self.fw, self.fh, self.hh = aw, fw, fh, hh
        self.width, self.height = aw, hh + fh
        return self.width, self.height

    def drawOn(self, canvas, x, y, _sW=0):
        cur = y + self.height
        for f, h, sb, sa in self.hs:
            cur -= sb + h
            f.drawOn(canvas, x, cur)
            cur -= sa
        self._draw_fn(canvas, x + (self.aw - self.fw) / 2, y, self.fw, self.fh)


class _SignLine(Flowable):
    """v1.4.1 CR-016: a line to write on, with a caption (plain text, not markup) underneath."""

    def __init__(self, width: float, caption: str):
        super().__init__()
        self.lw, self.caption = width, caption
        self.width, self.height = width, 0.42 * inch

    def draw(self):
        c = self.canv
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.8)
        c.line(0, 0.2 * inch, self.lw, 0.2 * inch)
        c.setFillColor(colors.black)
        c.setFont(_FONT, 10.5)
        c.drawString(0, 0.02 * inch, self.caption[:90])


def _signature_page(doc: "_AuditDoc", sp) -> list:
    """Date line at the top, the wording, then up to five signature lines stacked vertically (~1 inch each)."""
    f: list = [_Mark(doc, "Audit review signatures"), Spacer(1, 0.25 * inch), _SignLine(2.3 * inch, "Date"),
               Spacer(1, 0.45 * inch)]
    for para in [x.strip() for x in sp.text.split("\n\n") if x.strip()]:
        f += [P(para, "sig_body"), Spacer(1, 10)]
    f.append(Spacer(1, 0.2 * inch))
    lines = [f"{name}, {title}" if title else name for name, title in sp.signers] or ["Name and title"] * 3
    for cap in lines:
        f += [Spacer(1, 0.55 * inch), _SignLine(3.4 * inch, cap)]
    return [KeepTogether(f)]


class _AuditDoc(SimpleDocTemplate):
    def __init__(self, buf, pagesize=letter, **kw):   # 2.1.0 (#257): landscape for the Budget Prep report
        super().__init__(buf, pagesize=pagesize, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
                         bottomMargin=MARGIN + 0.25 * inch, **kw)
        self.current_label = ""
        self.page_labels: dict[int, str] = {}
        self.slots: list[tuple[int, float, float, float, float, object]] = []  # page, x, y, w, h, pypdf page
        self.sections: list[dict] = []  # 1.6.7: one per bank account when the report covers several

    def afterPage(self):
        self.page_labels.setdefault(self.page, self.current_label)


_MARK_H = 14          # the small mark in the footer (points)
_LOGO_H, _LOGO_W = 0.42 * inch, 2.2 * inch     # the full logo in the first page's top margin


def _aspect(size: tuple[int, int] | None) -> float:
    return (size[0] / size[1]) if size and size[1] else 1.0


def _brand_page(c, theme, w: float, h: float, first: bool) -> None:
    """2.2.0 (#280): the small mark at the left of every footer and the full logo at the top right of the first page,
    in the margin (nothing is drawn without a logo)."""
    if theme.logo_mark:
        mw = _MARK_H * _aspect(theme.logo_mark_size)
        c.drawImage(ImageReader(io.BytesIO(theme.logo_mark)), 18, 6, mw, _MARK_H, mask="auto",
                    preserveAspectRatio=True)
    if first and theme.logo_full:
        a = _aspect(theme.logo_full_size)
        lh = _LOGO_H
        lw = lh * a
        if lw > _LOGO_W:
            lw, lh = _LOGO_W, _LOGO_W / a
        c.drawImage(ImageReader(io.BytesIO(theme.logo_full)), w - MARGIN - lw, h - MARGIN + (MARGIN - lh) / 2 - 2,
                    lw, lh, mask="auto", preserveAspectRatio=True)


def _stamp_and_write(reader_bytes: bytes, doc: _AuditDoc, path: str, title: str) -> int:
    """Merges the reserved PDF-attachment slots (vector, scaled) and stamps footers."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(reader_bytes)))
    for page_no, x, y, w, h, src in doc.slots:
        box = src.cropbox
        sw, sh = float(box.width), float(box.height)
        s = min(w / sw, h / sh)
        op = (Transformation().translate(-float(box.left), -float(box.bottom)).scale(s, s)
              .translate(x + (w - sw * s) / 2, y + (h - sh * s) / 2))
        writer.pages[page_no - 1].merge_transformed_page(src, op, over=True)
    total = len(writer.pages)
    # 1.6.7: account sections - every page of a section carries "<account> - section page k of n" in the footer,
    # and the start / end pages state the section's page range, so a reviewer can tell that no page is missing.
    in_section: dict[int, str] = {}
    notes: dict[int, list[tuple[float, float, list[str]]]] = {}
    for sec in doc.sections:
        if "start" not in sec or "end" not in sec:
            continue
        first, last = sec["start"][0], sec["end"][0]
        n = last - first + 1
        for pg in range(first, last + 1):
            in_section[pg] = f"{sec['label']} - section page {pg - first + 1} of {n}"
        span = f"pages {first} to {last} of {total} ({n} pages, counting this start page and the end page)"
        # 1.7.1 (#59): the fundraisers have a section of their own, worded for what it holds
        fr = sec.get("kind") == "fundraisers"
        what = "The fundraisers section" if fr else "This account's section"
        thing, whose = ("fundraisers", "") if fr else ("transactions", " for this account")
        notes.setdefault(first, []).append((sec["start"][1], sec["start"][2], [
            f"{what}: {span}.",
            f"Its last page is page {last}, headed \"End of {thing}\"{whose}."]))
        notes.setdefault(last, []).append((sec["end"][1], sec["end"][2], [
            f"{what}: pages {first} to {last} of {total} ({n} pages, counting the start page and this end page).",
            f"Its first page is page {first}, headed \"Start of {thing}\"{whose}."]))
    theme = branding.current()
    for i, page in enumerate(writer.pages):
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        buf = io.BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=(w, h))
        _brand_page(c, theme, w, h, first=i == 0)
        left = 18 + (_MARK_H * 1.1 * _aspect(theme.logo_mark_size) + 6 if theme.logo_mark else 0)
        c.setFont(_FONT, 7)
        c.setFillColor(colors.HexColor("#444444"))
        c.drawString(left, 10, f"{title}  ·  {doc.page_labels.get(i + 1, '')}"[:160])
        c.drawRightString(w - 18, 10, f"Page {i + 1} of {total}")
        if theme.footer_text:
            c.drawString(left, 19, theme.footer_text[:branding.FOOTER_MAX])
        if i + 1 in in_section:
            c.drawRightString(w - 18, 20, in_section[i + 1][:120])
        for x, y, lines in notes.get(i + 1, []):
            c.setFont(_FONT, 10)
            c.setFillColor(colors.black)
            for k, line in enumerate(lines):
                c.drawString(x, y + _SectionNote.HEIGHT - 12 - 14 * k, line)
        c.save()
        buf.seek(0)
        page.merge_page(PdfReader(buf).pages[0])
    writer.add_metadata({"/Title": title, "/Producer": "PennyWarden"})
    with open(path, "wb") as fh:
        writer.write(fh)
    return total


def _attachment_bytes(settings, a: Attachment) -> tuple[bytes | None, str]:
    try:
        with open(path_for(settings, a), "rb") as fh:
            data = fh.read()
    except OSError:
        return None, "stored file missing"
    if hashlib.sha256(data).hexdigest() != a.sha256:
        return data, "SHA-256 MISMATCH - stored file differs from the uploaded file"
    return data, "SHA-256 verified"


def _frame_box(canvas, x, y, w, h):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#c3c9d0"))
    canvas.setLineWidth(0.5)
    canvas.rect(x - 1, y - 1, w + 2, h + 2)
    canvas.restoreState()


def _attachment_flowables(doc: _AuditDoc, settings, a: Attachment, heading: str, users: dict[int, str]) -> list:
    """Caption line followed by the attachment's content rendered within the page width."""
    data, integrity = _attachment_bytes(settings, a)
    cap = PM(f"<b>{escape(heading)}</b> — {escape(a.original_filename)}", "h3")
    meta = P(f"{a.mime_type} · {a.size_bytes:,} bytes · uploaded {a.uploaded_at:%Y-%m-%d %H:%M} UTC by "
             f"{users.get(a.uploaded_by_user_id, '?')} · SHA-256 {a.sha256} ({integrity})", "small")
    head = [Spacer(1, 6), cap, meta, Spacer(1, 3)]
    if data is None:
        return head + [P(f"Attachment content unavailable: {integrity}.", "body")]
    if a.mime_type.startswith("image/"):
        try:
            with PILImage.open(io.BytesIO(data)) as im:
                iw, ih = im.size

            def draw_img(canvas, x, y, w, h, _d=data):
                canvas.drawImage(ImageReader(io.BytesIO(_d)), x, y, w, h, preserveAspectRatio=True, mask="auto")
                _frame_box(canvas, x, y, w, h)
            return [_Block(head, iw, ih, draw_img)]
        except Exception:
            return head + [P("Image could not be rendered.", "body")]
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("encrypted")
        pages = list(reader.pages)
        if not pages:
            raise ValueError("no pages")
        for p in pages:
            p.transfer_rotation_to_content()
            _ = p.cropbox.width  # validate the page box
    except Exception:
        return head + [P("This PDF could not be embedded (malformed or protected). The stored file is retained and "
                         "identified by its SHA-256 above.", "body")]
    out: list = []
    for n, p in enumerate(pages):
        def draw_pdf(canvas, x, y, w, h, _p=p):
            doc.slots.append((canvas.getPageNumber(), x, y, w, h, _p))
            _frame_box(canvas, x, y, w, h)
        pw, ph = float(p.cropbox.width), float(p.cropbox.height)
        if n == 0:
            out.append(_Block(head + ([P(f"Page 1 of {len(pages)}", "small")] if len(pages) > 1 else []), pw, ph, draw_pdf))
        else:
            out.append(_Block([Spacer(1, 6), P(f"{heading} — page {n + 1} of {len(pages)}", "small")], pw, ph, draw_pdf))
    return out


# --------------------------------------------------------------------------- data selection
def audit_transactions(db: Session, ws_id: int, fy: FiscalYear, account_id: int | None,
                       include_void: bool) -> list[RegisterTransaction]:
    """Transactions dated in the Fiscal Year plus any (cross-FY) transaction allocated to its budgets."""
    alloc_ids = select(TransactionAllocation.transaction_id).join(Budget, Budget.id == TransactionAllocation.budget_id) \
        .where(Budget.fiscal_year_id == fy.id, TransactionAllocation.removed_at.is_(None))
    q = select(RegisterTransaction).where(
        RegisterTransaction.workspace_id == ws_id,
        or_(RegisterTransaction.transaction_date.between(fy.start_date, fy.end_date),
            RegisterTransaction.id.in_(alloc_ids)))
    if account_id:
        q = q.where(RegisterTransaction.bank_account_id == account_id)
    q = q.where(RegisterTransaction.status.in_(("ACTIVE",) if not include_void else ("ACTIVE", "VOID")))
    txns = list(db.scalars(q))
    accts = {a.id: a for a in db.scalars(select(BankAccount).where(BankAccount.workspace_id == ws_id))}
    txns.sort(key=lambda t: (accts[t.bank_account_id].account_name.lower(), t.bank_account_id, t.transaction_date,
                             t.entry_timestamp, t.id))
    return txns


def _attachments_for(db: Session, t: RegisterTransaction) -> tuple[list[Attachment], dict[int, list[Attachment]], list[Attachment]]:
    alloc_ids = [a.id for a in t.allocations]
    rows = list(db.scalars(select(Attachment).where(or_(Attachment.transaction_id == t.id,
                                                        Attachment.allocation_id.in_(alloc_ids or [-1])))
                           .order_by(*DISPLAY_ORDER)))
    parent = [a for a in rows if a.transaction_id == t.id and a.active]
    by_alloc: dict[int, list[Attachment]] = {}
    for a in rows:
        if a.allocation_id and a.active:
            by_alloc.setdefault(a.allocation_id, []).append(a)
    removed = [a for a in rows if not a.active]
    return parent, by_alloc, removed


# --------------------------------------------------------------------------- End of Year Audit report
def _txn_description(t: RegisterTransaction) -> str:
    live = t.live_allocations
    descs = [a.description for a in live if a.description]
    if len(live) <= 1:
        return descs[0] if descs else "—"
    return "\n".join(f"{i + 1}. {a.description or '(no description)'} — {money(a.amount_cents)}" for i, a in enumerate(live))


def _meta_table(rows: list[tuple[str, object]]) -> Table:
    """The seven headline transaction fields, printed large at the top of each transaction page."""
    w1 = 1.55 * inch
    data = [[PM(f"<b>{escape(k)}</b>", "metak"), P(v, "metav")] for k, v in rows]
    t = Table(data, colWidths=[w1, FRAME_W - 12 - w1])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#6b7682")),
                           ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#c3c9d0")),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef1f5")),
                           ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _remaining_cell(x: dict, bold: bool = False):
    """v1.4 CR-019: income received above budget prints as a green '+$X above budget'."""
    if x.get("above_budget"):
        return PM(f'<font color="#1d6b2c"><b>+{escape(money(x["above_budget"]))}</b> above budget</font>', "cellr")
    return PM(f"<b>{escape(money(x['remaining']))}</b>", "cellr") if bold else P(money(x["remaining"]), "cellr")


def gross_note():
    """2.3.0 (#371, BR-109): the small italic gross-budget footnote placed directly beneath a budget table or chart."""
    from .common import GROSS_BUDGET_NOTE
    return PM(f"<i>{escape(GROSS_BUDGET_NOTE)}</i>", "small")


def _budget_section(tree: dict) -> list:
    f: list = [PM("Fiscal Year Budgets", "h1")]
    qn = [q["name"] for q in tree["quarters"]]
    for label, rows, summ in (("Income", tree["income"], tree["income_summary"]),
                              ("Expense", tree["expense"], tree["expense_summary"])):
        f.append(PM(f"{label} budgets", "h2"))
        data = [[PM("<b>Budget</b>", "cell"), PM("<b>Status</b>", "cell"), PM("<b>Gross amount</b>", "cellr"),
                 *[PM(f"<b>{q}</b>", "cellr") for q in qn], PM("<b>Actual</b>", "cellr"), PM("<b>Remaining</b>", "cellr")]]
        for r in rows:
            for x, indent in [(r, ""), *[(c, "    ") for c in r["children"]]]:
                data.append([P(indent + x["label"], "cell"), P(x["state"]["label"], "cell"), P(money(x["amount"]), "cellr"),
                             *[P(money(q), "cellr") for q in x["quarters"]], P(money(x["actual"]), "cellr"),
                             _remaining_cell(x)])
        data.append([PM("<b>Total</b>", "cell"), P("", "cell"), PM(f"<b>{money(summ['amount'])}</b>", "cellr"),
                     *[P(money(q), "cellr") for q in summ["quarters"]], PM(f"<b>{money(summ['actual'])}</b>", "cellr"),
                     _remaining_cell(summ, bold=True)])
        if len(data) == 2:
            data.insert(1, [P(f"No {label.lower()} budgets.", "cell")] + [""] * (len(qn) + 4))
        f.append(_grid(data, [1.95 * inch, 1.0 * inch, 0.75 * inch] + [0.52 * inch] * len(qn) + [0.7 * inch, 0.72 * inch]))
        f.append(gross_note())   # 2.3.0 (#371): directly beneath each budget table, so it travels with the page
        f.append(Spacer(1, 8))
    if tree["budget_zero"]:
        b0 = tree["budget_zero"]
        f.append(P(f"Protected Budget 0 (non-budget activity such as transfers between accounts): inflows "
                   f"{money(b0.get('inflow'))}, outflows {money(b0.get('outflow'))}.", "small"))
    return f


def _long_date(d: dt.date) -> str:
    return f"{d:%B} {d.day}, {d.year}"  # portable (no %-d on Windows)


def allocation_label(db: Session, t: RegisterTransaction, al: TransactionAllocation) -> str:
    """v1.3 CR-009: "<Entity> - <Budget>" (entity falls back to the transaction's; budget label as in the UI)."""
    from .register import _budget_info
    ent = al.entity if al.entity is not None else t.parent_entity
    budget = _budget_info(db, al.budget)["label"]
    return f"{ent.display_name} - {budget}" if ent is not None and not ent.is_system else budget


def _id_list(ids: list[int], limit: int = 60) -> str:
    s = ", ".join(f"#{i}" for i in ids[:limit])
    return s + (f" and {len(ids) - limit} more" if len(ids) > limit else "")


FY_DOC_LABELS = {"APPROVAL": "Approval document", "AUDIT_SIGNOFF": "Audit Signoff", "UNSPECIFIED": "Other document"}


@branding.themed
def build_audit_report(db: Session, ctx, settings, fy: FiscalYear, account_id: int | None = None,
                       include_void: bool = True, layout: str = "audit", signature=None,
                       fundraisers: bool = False) -> tuple[str, str, dict]:
    """Returns (temp file path, download filename, summary). Caller deletes the file.

    Layout "audit" (v1.2.1 CR-002; v1.3 Q5): page 1 title page; page 2 Fiscal Year Review introduction; pages 3-n
    budgets; then at least one page per transaction - the headline fields at the top and every attachment rendered
    underneath within the 8.5x11 page width.
    Layout "close" (v1.3 CR-008, Fiscal Year Close report): identical, with the Fiscal Year documents (Approval,
    Audit Signoff, other) inserted after the Fiscal Year Review and before the budgets and transactions.
    signature (v1.4.1 CR-016, audit layout): a resolved signatures.SignaturePage appended as the last page.
    fundraisers (v1.6.2 CR-035): the Fiscal Year's fundraisers (module on, not archived, a budget in this year) after
    the transactions and before the signature page - each complete, even when it spans a second Fiscal Year.
    """
    close_layout = layout == "close"
    report_name = "Fiscal Year Close Report" if close_layout else "End of Year Audit Report"
    ws = db.get(Workspace, ctx.workspace_id)
    users = {u.id: u.username for u in db.scalars(select(User).where(User.workspace_id == ctx.workspace_id))}
    accts = {a.id: a for a in db.scalars(select(BankAccount).where(BankAccount.workspace_id == ctx.workspace_id))}
    if account_id is not None and account_id not in accts:
        raise validation("Bank Account not found.", "bank_account_id")
    title = f"{report_name} — {fy.display_name} — {ws.name}"
    buf = io.BytesIO()
    doc = _AuditDoc(buf, title=report_name, author=ws.name)
    tree = bsvc.tree(db, fy)
    check = closure_check(db, fy)
    txns = audit_transactions(db, ctx.workspace_id, fy, account_id, include_void)
    doc_review = documentation_review(db, fy)
    doc_items = {i["transaction_id"]: i for i in doc_review}
    fy_atts = list(db.scalars(select(Attachment).where(Attachment.fiscal_year_id == fy.id, Attachment.active.is_(True),
                                                       Attachment.system_generated.is_(False))
                              .order_by(*DISPLAY_ORDER)))
    order = {"APPROVAL": 0, "AUDIT_SIGNOFF": 1}
    fy_atts.sort(key=lambda a: (order.get(a.document_type or "UNSPECIFIED", 2), a.id))
    att_cache = {t.id: _attachments_for(db, t) for t in txns}
    now = utcnow()
    scope = (accts[account_id].account_name + " - " + bank.masked(accts[account_id]) if account_id
             else "All register-enabled accounts")

    # ---- page 1: title page
    f: list = [_Mark(doc, "Title"), Spacer(1, 1.6 * inch), PM(escape(ws.name), "cover_org"), Spacer(1, 10),
               PM(report_name, "cover_title"), Spacer(1, 6),
               PM(f"Fiscal Year {escape(fy.display_name)}", "cover_sub"),
               PM(f"{_long_date(fy.start_date)} – {_long_date(fy.end_date)}", "cover_sub"), Spacer(1, 1.2 * inch),
               _kv([("Fiscal Year status", fy.status.title()),
                    ("Approved", f"{fy.approved_at:%Y-%m-%d %H:%M} UTC by {users.get(fy.approved_by_user_id, '?')}"
                     if fy.approved_at else "—"),
                    ("Closed", f"{fy.closed_at:%Y-%m-%d %H:%M} UTC by {users.get(fy.closed_by_user_id, '?')}"
                     if fy.closed_at else "—"),
                    ("Accounts", scope),
                    ("Transactions", f"{len(txns)} ({'including' if include_void else 'excluding'} VOID)"),
                    ("Generated", f"{now:%Y-%m-%d %H:%M} UTC by {ctx.user.username}")], w1=1.6 * inch),
               PageBreak()]

    # ---- page 2: Fiscal Year Review introduction
    active = [t for t in txns if t.status == "ACTIVE"]
    dep = sum(t.total_cents for t in active if t.transaction_type == "DEPOSIT")
    wd = sum(t.total_cents for t in active if t.transaction_type == "WITHDRAWAL")
    n_att = sum(len(v[0]) + sum(len(x) for x in v[1].values()) for v in att_cache.values())
    missing = [i["transaction_id"] for i in doc_review if i["category"] == "MISSING_ATTACHMENTS"]
    marked = [i["transaction_id"] for i in doc_review if i["category"] == "NO_ATTACHMENT_MARKED"]
    in_report = {t.id for t in txns}
    per_acct: dict[int, list[int]] = {}
    for t in active:
        per_acct.setdefault(t.bank_account_id, [0, 0, 0])
        row = per_acct[t.bank_account_id]
        row[0] += 1
        row[1 if t.transaction_type == "DEPOSIT" else 2] += t.total_cents
    frs = fsvc.for_fiscal_year_report(db, ctx.workspace_id, fy) if fundraisers else []
    f += [_Mark(doc, "Fiscal Year Review"), PM("Fiscal Year Review", "h1"),
          P(f"This report documents Fiscal Year {fy.display_name} ({fy.start_date} to {fy.end_date}) for {ws.name}. "
            "It is organised as follows: this review summary; "
            + ("the Fiscal Year documents (approval, audit signoff and other supporting documents); the Fiscal Year "
               "budgets; " if close_layout else "the Fiscal Year budgets (page 3 onward); ")
            + "then every transaction of the year on its own page(s), with the transaction details at the top and each "
              "supporting attachment reproduced beneath them."
            + (" The transactions are grouped by bank account: each account begins with a \"Start of transactions\" "
               "page and finishes with an \"End of transactions\" page, both stating the account's page range."
               if len({t.bank_account_id for t in txns}) > 1 else "")
            + (" The fundraisers follow the transactions, between a \"Start of fundraisers\" page and an \"End of "
               "fundraisers\" page that state their page range." if frs else ""), "body"),
          Spacer(1, 8), PM("Activity summary", "h2"),
          _kv([("Transactions", f"{len(txns)} in this report — {len(active)} active, {len(txns) - len(active)} VOID"),
               ("Deposits (active)", money(dep)), ("Withdrawals (active)", money(wd)), ("Net", money(dep - wd)),
               ("Attachments", f"{n_att} transaction/allocation attachment(s); {len(fy_atts)} Fiscal Year document(s)")])]
    if per_acct:
        data = [[PM(f"<b>{h}</b>", "cell") for h in ("Account", "Transactions", "Deposits", "Withdrawals")]]
        for aid, (n, d, w) in sorted(per_acct.items(), key=lambda kv: accts[kv[0]].account_name.lower()):
            a = accts[aid]
            data.append([P(f"{a.account_name} - {bank.masked(a)}", "cell"), P(n, "cellr"), P(money(d), "cellr"),
                         P(money(w), "cellr")])
        f += [Spacer(1, 4), _grid(data, [3.4 * inch, 1.0 * inch, 1.3 * inch, 1.3 * inch])]
    f += [Spacer(1, 8), PM("Closure readiness", "h2")]
    if fy.status == "CLOSED":
        items = [f"The Fiscal Year is closed ({fy.closed_at:%Y-%m-%d %H:%M} UTC by {users.get(fy.closed_by_user_id, '?')})."
                 if fy.closed_at else "The Fiscal Year is closed."]
    else:
        items = ([f"Blocker: {b['message']}" for b in check["blockers"]]
                 + [f"Warning: {w['message']}" for w in check["warnings"]])
    f += [P("• " + x, "body") for x in (items or ["No blockers or warnings."])]
    changed = bank.changes_after_close(db, fy)          # 2.3.0 (#391)
    if changed:
        f += [Spacer(1, 6), PM("Balance changed after close", "h2"),
              P("These non-register account balances were changed by a Budget Admin after the Fiscal Year was closed "
                "(it was closed with the earlier balance).", "small")]
        word = {"ADD": "Added", "CORRECT": "Corrected", "RETIRE": "Retired"}
        for c in changed:
            b, a = c["before"] or {}, c["after"] or {}
            what = (f"{money(a.get('balance'))} as of {a.get('as_of_date')}" if c["action"] == "ADD" else
                    f"{money(b.get('balance'))} as of {b.get('as_of_date')}" + (
                        f" → {money(a.get('balance'))} as of {a.get('as_of_date')}" if c["action"] == "CORRECT" else ""))
            f.append(P(f"• {c['changed_at'][:16].replace('T', ' ')} UTC by {c['changed_by'] or '?'} — {c['account']}: "
                       f"{word.get(c['action'], c['action'])} {what}. Reason: {c['reason']}", "body"))
    f += [Spacer(1, 8), PM("Documentation review", "h2"),
          P("A transaction is documented when it has an attachment or is marked 'no attachment will be provided' with a "
            "reason. When the transaction itself has neither, every allocation (child) must have an attachment or its "
            "own marker with a reason. A marker without a reason is still listed. These items are review warnings; "
            "they do not block closure.", "small"), Spacer(1, 2)]
    if not missing and not marked:
        f.append(P("• All applicable transactions are documented by attachments or a stated reason.", "body"))
    if missing:
        f.append(P(f"• Missing supporting attachments ({len(missing)}): {_id_list(missing)}", "body"))
    if marked:
        f.append(P(f"• Marked 'no attachment will be provided' without a reason ({len(marked)}): {_id_list(marked)}", "body"))
    outside = [i for i in missing + marked if i not in in_report]
    if outside:
        f.append(P(f"({len(outside)} of these are outside this report's account/VOID filter.)", "small"))
    f.append(PageBreak())

    # ---- Close report only: Fiscal Year documents before the budgets and transactions (v1.3 CR-008)
    if close_layout:
        f += [_Mark(doc, "Fiscal Year documents"), PM("Fiscal Year documents", "h1")]
        if fy.approval_no_attachment and not any(a.document_type == "APPROVAL" for a in fy_atts):
            f.append(P("Approval document: none — the Fiscal Year is marked as having no approval document"
                       + (f" ({fy.approval_no_attachment_reason})." if fy.approval_no_attachment_reason else "."), "body"))
        if not fy_atts:
            f.append(P("No Fiscal Year documents are attached.", "body"))
        counts: dict[str, int] = {}
        for x in fy_atts:
            counts[x.document_type or "UNSPECIFIED"] = counts.get(x.document_type or "UNSPECIFIED", 0) + 1
        seen: dict[str, int] = {}
        for x in fy_atts:
            kind = x.document_type or "UNSPECIFIED"
            seen[kind] = seen.get(kind, 0) + 1
            f += _attachment_flowables(doc, settings, x, f"{FY_DOC_LABELS[kind]} {seen[kind]} of {counts[kind]}", users)
        f.append(PageBreak())

    # ---- budgets
    f += [_Mark(doc, "Budgets")] + _budget_section(tree) + [PageBreak()]

    # ---- 2.2.0 (#325): items (non-cash donations) received in the year - never in the register
    if account_id is None:
        from . import donations as don_svc
        items = don_svc.non_cash_received(db, ctx.workspace_id, fy.start_date, fy.end_date)
        if items:
            rows = [[PM("<b>Received</b>", "cell"), PM("<b>Donor</b>", "cell"), PM("<b>Item</b>", "cell"),
                     PM("<b>Our estimate</b>", "cellr"), PM("<b>Receipt</b>", "cell")]]
            for x in items:
                est = money(x["value_cents"]) if x["value_cents"] else (
                    f"none ({x['no_value_reason']})" if x["no_value_reason"] else "Value not entered")
                rows.append([P(x["date"].strftime("%m/%d/%Y"), "cell"), P(x["donor"], "cell"), P(x["description"], "cell"),
                             P(est, "cellr"), P(x["receipt"] or "", "cell")])
            f += [_Mark(doc, "Non-cash donations received"), PM("Non-cash donations received", "h1"),
                  P("Items donated to the organization and received in this Fiscal Year. They are not in the register "
                    "(nothing was deposited); receipts list them by description only. The estimate is the "
                    "organization's own, for its records.", "small"), Spacer(1, 4),
                  _grid(rows, [0.8 * inch, 1.7 * inch, FRAME_W - 12 - 4.7 * inch, 1.2 * inch, 1.0 * inch]),
                  PageBreak()]

    # ---- one or more pages per transaction
    if not txns:
        f += [_Mark(doc, "Transactions"), PM("Transactions", "h1"), P("No transactions for this Fiscal Year.", "body")]
    # 1.6.7: with several accounts in the report, each account's transactions sit between a start page and an end page
    acct_order = list(dict.fromkeys(t.bank_account_id for t in txns))
    sectioned = len(acct_order) > 1
    by_acct = {aid: [t for t in txns if t.bank_account_id == aid] for aid in acct_order}

    def section_page(sec: dict, kind: str) -> list:
        aid = sec["account_id"]
        a, mine = accts[aid], by_acct[aid]
        act = [t for t in mine if t.status == "ACTIVE"]
        n = acct_order.index(aid) + 1
        first, last = mine[0], mine[-1]
        nxt = acct_order[n] if n < len(acct_order) else None
        start = kind == "start"
        rows = [("Account", f"{a.account_name} - {bank.masked(a)}"),
                ("Account in this report", f"{n} of {len(acct_order)}"),
                ("Transactions", f"{len(mine)} — {len(act)} active, {len(mine) - len(act)} VOID"),
                ("Deposits (active)", money(sum(t.total_cents for t in act if t.transaction_type == "DEPOSIT"))),
                ("Withdrawals (active)", money(sum(t.total_cents for t in act if t.transaction_type == "WITHDRAWAL"))),
                ("First transaction", f"#{first.id} — {first.transaction_date}"),
                ("Last transaction", f"#{last.id} — {last.transaction_date}")]
        if not start:
            rows.append(("Next", f"{accts[nxt].account_name} - {bank.masked(accts[nxt])}" if nxt
                         else "This was the last account in the report."))
        head = "Start of transactions" if start else "End of transactions"
        return [_Mark(doc, f"{head} — {a.account_name}"), Spacer(1, 1.2 * inch),
                PM(head, "cover_sub"), Spacer(1, 6),
                PM(escape(f"{a.account_name} - {bank.masked(a)}"), "cover_title"), Spacer(1, 0.5 * inch),
                _kv(rows, w1=1.8 * inch), Spacer(1, 14), _SectionNote(doc, sec, kind), Spacer(1, 8),
                P("Every page between this account's start page and end page shows the account and \"section page "
                  "k of n\" at the bottom right. The pages belong to this account only, and none is missing when the "
                  "section page numbers run from 1 to n without a gap." if start else
                  "No transaction of this account follows this page.", "small"),
                PageBreak()]

    section = None
    for i_t, t in enumerate(txns):
        a = accts[t.bank_account_id]
        if sectioned and (section is None or section["account_id"] != t.bank_account_id):
            section = {"account_id": a.id, "label": f"{a.account_name} {bank.masked(a)}"}
            doc.sections.append(section)
            f += section_page(section, "start")
        parent_atts, by_alloc, removed = att_cache[t.id]
        live = t.live_allocations
        void = t.status == "VOID"
        f += [_Mark(doc, f"Transaction #{t.id}"),
              PM(f"Transaction #{t.id}" + (" — <font color='#b3261e'>VOID</font>" if void else ""), "h1"),
              P(f"{a.account_name} - {bank.masked(a)}", "small"), Spacer(1, 4)]
        ent = t.parent_entity
        f.append(_meta_table([
            ("Transaction date", t.transaction_date),
            ("Entity", f"{ent.display_name} ({ent.entity_number})" if ent else "—"),
            ("Transaction type", t.transaction_type.title()),
            ("Amount", money(t.total_cents)),
            ("Description", _txn_description(t)),
            ("Clear Date", t.clear_date or "Uncleared"),
            ("Notes", t.notes or "—")]))
        # 2.1.0 (#260): an electronic payment shows "Electronic (method)" where the check number would be
        extra = [("Status", t.status),
                 ("Payment", reg.payment_text(t)) if t.electronic_payment else ("Check number", t.check_number or "—"),
                 ("Entered", f"{t.entry_timestamp:%Y-%m-%d %H:%M} UTC by {users.get(t.created_by_user_id, '?')}")]
        if void:
            extra.append(("Void", f"{t.void_reason} — {t.voided_at:%Y-%m-%d %H:%M} UTC by "
                                  f"{users.get(t.voided_by_user_id, '?')}" if t.voided_at else t.void_reason))
        if t.transfer_group:
            other = db.scalar(select(RegisterTransaction).where(RegisterTransaction.transfer_group == t.transfer_group,
                                                                RegisterTransaction.id != t.id))
            if other is not None:
                oa = accts[other.bank_account_id]
                extra.append(("Transfer", f"{'to' if t.transaction_type == 'WITHDRAWAL' else 'from'} {oa.account_name} "
                                          f"{bank.masked(oa)} (transaction #{other.id})"))
        if t.no_attachment:
            extra.append(("Documentation", f"Marked 'no attachment will be provided': {t.no_attachment_reason or '(no reason)'}"))
        di = doc_items.get(t.id)
        if di and di["category"] == "MISSING_ATTACHMENTS":
            extra.append(("Documentation review", "WARNING: supporting attachments missing"))
        f += [Spacer(1, 4), _kv(extra, w1=1.2 * inch, style="small")]
        # allocations (budget detail) - compact
        rows = [[PM(f"<b>{h}</b>", "cell") for h in ("Budget", "Entity", "Invoice #", "Description / notes", "Docs",
                                                     "Amount")]]
        for al in live:
            b = al.budget
            parent = db.get(Budget, b.parent_budget_id) if b.parent_budget_id else None
            lbl = budget_label(parent, None) if b.is_other and parent and not bsvc.children_of(db, parent)[0] else budget_label(b, parent)
            fyb = db.get(FiscalYear, b.fiscal_year_id)
            revs = db.scalars(select(FiscalYearReview).where(FiscalYearReview.transaction_allocation_id == al.id)).all()
            desc = " — ".join(x for x in (al.description, al.notes) if x)
            if revs:
                desc += ("\n" if desc else "") + "Review: " + "; ".join(
                    f"{r.category} {r.status}" + (f" ({r.review_note})" if r.review_note else "") for r in revs)
            docs = (f"{len(by_alloc.get(al.id, []))} att." if by_alloc.get(al.id) else
                    ("No attachment" + (f": {al.no_attachment_reason}" if al.no_attachment_reason else "")
                     if al.no_attachment else "—"))
            rows.append([P(f"{fyb.display_name} / {lbl}", "cell"), P(al.entity.display_name if al.entity else "", "cell"),
                         P(al.invoice_number or "", "cell"), P(desc, "cell"), P(docs, "cell"),
                         P(money(al.amount_cents), "cellr")])
        f += [Spacer(1, 4), _grid(rows, [1.7 * inch, 1.1 * inch, 0.65 * inch, 2.05 * inch, 0.75 * inch, 0.8 * inch])]
        ordered: list[tuple[str, Attachment]] = [("transaction", x) for x in parent_atts]
        for al in live:
            ordered += [(allocation_label(db, t, al), x) for x in by_alloc.get(al.id, [])]
        if not ordered:
            f += [Spacer(1, 6), P("No attachments." + (" Marked 'no attachment will be provided'." if t.no_attachment
                                                       else ""), "small")]
        for i, (k, x) in enumerate(ordered):
            f += _attachment_flowables(doc, settings, x, f"Attachment {i + 1} of {len(ordered)} ({k})", users)
        if removed:
            f += [Spacer(1, 4), P("Removed attachments (retained in history, not reproduced): " + ", ".join(
                f"{x.original_filename} (removed {x.removed_at:%Y-%m-%d})" for x in removed), "small")]
        f.append(PageBreak())
        if sectioned and (i_t + 1 == len(txns) or txns[i_t + 1].bank_account_id != t.bank_account_id):
            f += section_page(section, "end")

    # 1.7.1 (#59): like each account's transactions (1.6.7), the fundraisers sit between a start page and an end page
    # that state their page range, so a reviewer can tell where they begin and end and that no page is missing.
    fr_section = {"kind": "fundraisers", "label": "Fundraisers"} if frs else None

    def fundraisers_page(kind: str) -> list:
        start = kind == "start"
        cancelled = sum(1 for x in frs if x.cancelled_at is not None)
        when = lambda x: (f"{x.start_date}" if x.start_date == x.end_date else f"{x.start_date} to {x.end_date}")  # noqa: E731
        rows = [("Fiscal Year", f"{fy.display_name} ({fy.start_date} to {fy.end_date})"),
                ("Fundraisers", f"{len(frs)}" + (f" — {cancelled} cancelled" if cancelled else "")),
                ("First fundraiser", f"{frs[0].name} — {when(frs[0])}"),
                ("Last fundraiser", f"{frs[-1].name} — {when(frs[-1])}")]
        head = "Start of fundraisers" if start else "End of fundraisers"
        out = [_Mark(doc, head), Spacer(1, 1.2 * inch), PM(head, "cover_sub"), Spacer(1, 6),
               PM(escape(f"Fundraisers — {fy.display_name}"), "cover_title"), Spacer(1, 0.5 * inch),
               _kv(rows, w1=1.8 * inch), Spacer(1, 14), _SectionNote(doc, fr_section, kind), Spacer(1, 8)]
        if start:
            out += [P("In this section, in order of event date:", "small")]
            out += [P(f"{i}. {x.name} — {when(x)}" + (" — cancelled" if x.cancelled_at is not None else ""), "small")
                    for i, x in enumerate(frs, start=1)]
            out += [Spacer(1, 8),
                    P("Every page between this start page and the end page shows \"Fundraisers - section page k of n\" "
                      "at the bottom right. The pages belong to the fundraisers only, and none is missing when the "
                      "section page numbers run from 1 to n without a gap.", "small")]
        else:
            out += [P("No fundraiser follows this page.", "small")]
        return out + [PageBreak()]

    if frs:
        if f and not isinstance(f[-1], PageBreak):
            f.append(PageBreak())
        doc.sections.append(fr_section)
        f += fundraisers_page("start")
    for fr in frs:  # v1.6.2 CR-035
        if f and not isinstance(f[-1], PageBreak):
            f.append(PageBreak())
        f += _fundraiser_section(db, ctx, settings, doc, fr, users, this_fy=fy)
        f.append(PageBreak())
    if frs:
        f += fundraisers_page("end")

    if signature is not None:
        if f and not isinstance(f[-1], PageBreak):
            f.append(PageBreak())
        f += _signature_page(doc, signature)
    if f and isinstance(f[-1], PageBreak):
        f.pop()  # no blank page at the end
    doc.build(f)
    fd, path = tempfile.mkstemp(prefix="fmpoc-audit-", suffix=".pdf")
    os.close(fd)
    try:
        pages = _stamp_and_write(buf.getvalue(), doc, path, title)
    except Exception:
        os.unlink(path)
        raise
    fname = f"{fy.display_name}-{'fiscal-year-close' if close_layout else 'end-of-year-audit'}-report.pdf"
    summary = {"transactions": len(txns), "pages": pages, **({"fundraisers": len(frs)} if fundraisers else {})}
    acct_sections = [x for x in doc.sections if "account_id" in x]
    if acct_sections:
        summary["account_sections"] = [{"bank_account_id": x["account_id"], "first_page": x["start"][0],
                                        "last_page": x["end"][0]} for x in acct_sections]
    if fr_section is not None:  # 1.7.1 (#59)
        summary["fundraiser_section"] = {"first_page": fr_section["start"][0], "last_page": fr_section["end"][0]}
    return path, fname, summary


# --------------------------------------------------------------------------- v1.6.2 CR-035 fundraiser report
_FR_STATUS = {"CANCELLED": "Cancelled", "PLANNED": "Planned", "IN_PROGRESS": "In progress", "ENDED": "Ended", "ARCHIVED": "Archived"}


def _fundraiser_section(db: Session, ctx, settings, doc: _AuditDoc, fr: Fundraiser, users: dict[int, str],
                        this_fy: FiscalYear | None = None) -> list:
    """One fundraiser: summary, buckets, transaction list, excluded lines, then the fundraiser documents and the
    transactions' attachments rendered. The same section is used standalone and inside the Audit / Close reports
    (this_fy = the report's Fiscal Year, marked in the per-year breakdown)."""
    d = fsvc.detail(db, ctx, fr)
    t = d["totals"]
    fy_name = {y["id"]: y["display_name"] for y in d["fiscal_years"]}
    event = d["start_date"] if d["start_date"] == d["end_date"] else f"{d['start_date']} to {d['end_date']}"
    f: list = [_Mark(doc, f"Fundraiser: {fr.name}"), PM(f"Fundraiser — {escape(fr.name)}", "h1")]
    if d["cancelled"]:  # v1.6.4 CR-037
        f += [PM("<font color='#b3261e'><b>CANCELLED</b></font> — this fundraiser did not take place as planned.", "body"),
              P(f"Reason: {d['cancel_reason']} (marked {d['cancelled_at'][:10]})", "body"), Spacer(1, 4)]
    meta = [("Event", event + (" (cancelled)" if d["cancelled"] else "")), ("Status", _FR_STATUS.get(d["status"], d["status"])),
            ("Fiscal Years", " – ".join(fy_name.values()) or "—")]
    if d["description"]:
        meta.append(("Description", d["description"]))
    for b in d["budgets"]:
        meta.append((f"{'Income' if b['kind'] == 'INCOME' else 'Expense'} budget", f"{b['fiscal_year']['display_name']} / {b['label']}"))
    if d["filter_text"]:
        meta.append(("Description filter", f"{d['filter_text']} ({'regular expression' if d['filter_regex'] else 'contains, any case'})"
                                            + (f" — {d['filtered_out_lines']} line(s) in these budgets did not match" if d["filtered_out_lines"] else "")))
    f.append(_kv(meta, w1=1.5 * inch, style="body"))
    warn = [n["message"] for n in d["notices"] if n["code"] in ("OTHER_BUDGET", "PARENT_BUDGET", "FILTER", "SHARED_BUDGET")]
    for w in warn:
        f.append(P("Note: " + w, "small"))
    if this_fy is not None and len(d["fiscal_years"]) > 1:
        f.append(P(f"This fundraiser spans two Fiscal Years and is shown complete; this report covers {this_fy.display_name}.", "small"))

    # ---- summary
    roi = "—" if t["roi"] is None else f"{float(t['roi']) * 100:.1f}%"
    rows = [[PM("<b>Income</b>", "cell"), PM("<b>Expenses</b>", "cell"), PM("<b>Net</b>", "cell"),
             PM("<b>Return on expenses (net ÷ expenses)</b>", "cell")],
            [P(money(t["income"]), "cell"), P(money(t["expense"]), "cell"), P(money(t["net"]), "cell"), P(roi, "cell")]]
    f += [Spacer(1, 8), PM("Summary", "h2"), _grid(rows, [1.6 * inch, 1.6 * inch, 1.6 * inch, FRAME_W - 12 - 4.8 * inch], zebra=False)]
    notes = []
    if t["cash_float_out"] != "0.00":
        notes.append(f"cash float taken out {money(t['cash_float_out'])}")
    if t["cash_float_returned"] != "0.00":
        notes.append(f"cash float returned {money(t['cash_float_returned'])}")
    if t["excluded_lines"]:
        notes.append(f"{t['excluded_lines']} excluded line(s): income {money(t['excluded_income'])}, expenses {money(t['excluded_expense'])}")
    if notes:
        f.append(P("Not counted in the figures above: " + "; ".join(notes) + ".", "small"))
    if len(d["per_fiscal_year"]) > 1:
        rows = [[PM(f"<b>{h}</b>", "cell") for h in ("Fiscal Year", "Income", "Expenses", "Net")]]
        for p in d["per_fiscal_year"]:
            name = p["fiscal_year"]["display_name"] + (" (this report)" if this_fy is not None and p["fiscal_year"]["id"] == this_fy.id else "")
            rows.append([P(name, "cell"), P(money(p["income"]), "cellr"), P(money(p["expense"]), "cellr"), P(money(p["net"]), "cellr")])
        rows.append([PM("<b>Total</b>", "cell"), P(money(t["income"]), "cellr"), P(money(t["expense"]), "cellr"), P(money(t["net"]), "cellr")])
        f += [Spacer(1, 6), PM("By Fiscal Year", "h2"), _grid(rows, [2.4 * inch, 1.4 * inch, 1.4 * inch, 1.4 * inch])]

    # ---- buckets
    names = {b["id"]: b["name"] for b in d["buckets"]["items"]}
    if d["buckets"]["items"]:
        rows = [[PM(f"<b>{h}</b>", "cell") for h in ("Bucket", "Income", "Expenses", "Net")]]
        by_id = {b["id"]: b for b in d["buckets"]["items"]}

        def bucket_row(b, indent=False):
            label = b["name"] + (f" — {b['description']}" if b["description"] else "")
            rows.append([PM(("&nbsp;" * 4 if indent else "") + escape(label), "cell"),
                         P(money(b["income"]), "cellr"), P(money(b["expense"]), "cellr"), P(money(b["net"]), "cellr")])
        # 2.1.0 (#278): categories (in order) with their buckets beneath and a subtotal; then uncategorized buckets
        for c in d["buckets"].get("categories", []):
            rows.append([PM(f"<b>{escape(c['name'])}</b>", "cell"), "", "", ""])
            for bid in c["bucket_ids"]:
                bucket_row(by_id[bid], indent=True)
            rows.append([PM(f"<i>{escape(c['name'])} subtotal</i>", "cell"), P(money(c["income"]), "cellr"),
                         P(money(c["expense"]), "cellr"), P(money(c["net"]), "cellr")])
        for bid in d["buckets"].get("uncategorized_ids", [b["id"] for b in d["buckets"]["items"]]):
            bucket_row(by_id[bid])
        u = d["buckets"]["unassigned"]
        rows.append([PM("<b>Unassigned</b>", "cell"), P(money(u["income"]), "cellr"), P(money(u["expense"]), "cellr"), P(money(u["net"]), "cellr")])
        f += [Spacer(1, 6), PM("Buckets", "h2"), _grid(rows, [2.4 * inch, 1.4 * inch, 1.4 * inch, 1.4 * inch])]

    # ---- transactions
    included = [x for x in d["lines"] if not x["excluded"]]
    excluded = [x for x in d["lines"] if x["excluded"]]
    f += [Spacer(1, 6), PM("Transactions", "h2")]
    if included:
        rows = [[PM(f"<b>{h}</b>", "cell") for h in ("Date", "FY", "#", "Type", "Entity / description", "Budget", "Amount",
                                                     "Counted", "Buckets")]]
        for x in included:
            desc = " — ".join(v for v in (x["entity"], x["description"]) if v) or "—"
            if x["classification"]:
                c = x["classification"]
                desc += f"\n{c['label']} {money(c['amount'])}" + (f" ({c['note']})" if c["note"] else "")
            bk = "; ".join(f"{names.get(b['bucket_id'], '?')} {money(b['amount'])}"
                           + (f" ({money(b['charge'])} less {money(b['less'])} {b['less_description'] or ''})".replace(" )", ")")
                              if b.get("less") not in (None, "0.00") else "") for b in x["buckets"])
            rows.append([P(x["transaction_date"], "cell"), P(fy_name.get(x["fiscal_year_id"], ""), "cell"),
                         P(str(x["transaction_id"]), "cell"), P("Income" if x["kind"] == "INCOME" else "Expense", "cell"),
                         P(desc, "cell"), P(x["budget"], "cell"), P(money(x["amount"]), "cellr"),
                         P(money(x["counted"]), "cellr"), P(bk, "cell")])
        rows.append([PM("<b>Income (counted)</b>", "cell"), "", "", "", "", "", "", P(money(t["income"]), "cellr"), ""])
        rows.append([PM("<b>Expenses (counted)</b>", "cell"), "", "", "", "", "", "", P(money(t["expense"]), "cellr"), ""])
        n = len(rows)
        f.append(_grid(rows, [0.72 * inch, 0.5 * inch, 0.32 * inch, 0.6 * inch, 1.7 * inch, 1.1 * inch, 0.72 * inch,
                              0.72 * inch, FRAME_W - 12 - 6.38 * inch],
                       extra=[("SPAN", (0, n - 2), (6, n - 2)), ("SPAN", (0, n - 1), (6, n - 1))]))
    else:
        f.append(P("No transactions.", "body"))
    if excluded:
        rows = [[PM(f"<b>{h}</b>", "cell") for h in ("Date", "#", "Type", "Entity / description", "Amount", "Reason for excluding")]]
        for x in excluded:
            rows.append([P(x["transaction_date"], "cell"), P(str(x["transaction_id"]), "cell"),
                         P("Income" if x["kind"] == "INCOME" else "Expense", "cell"),
                         P(" — ".join(v for v in (x["entity"], x["description"]) if v) or "—", "cell"),
                         P(money(x["amount"]), "cellr"), P(x["exclusion_reason"], "cell")])
        grid = _grid(rows, [0.72 * inch, 0.32 * inch, 0.6 * inch, 2.3 * inch, 0.8 * inch, FRAME_W - 12 - 4.74 * inch])
        f += [Spacer(1, 6), KeepTogether([PM("Excluded lines", "h2"), grid]) if len(rows) <= 12 else PM("Excluded lines", "h2")]
        if len(rows) > 12:
            f.append(grid)

    # ---- attachments: fundraiser documents, then the transactions' attachments
    docs = list(db.scalars(select(Attachment).where(Attachment.fundraiser_id == fr.id, Attachment.active.is_(True))
                           .order_by(*DISPLAY_ORDER)))
    for i, a in enumerate(docs):
        f += _attachment_flowables(doc, settings, a, f"Fundraiser document {i + 1} of {len(docs)}", users)
    seen: set[int] = set()
    for x in included:
        for a in x["attachments"]:
            if a["id"] in seen:
                continue
            seen.add(a["id"])
            att = db.get(Attachment, a["id"])
            f += _attachment_flowables(doc, settings, att, f"Transaction #{x['transaction_id']} ({x['transaction_date']}) attachment", users)
    if not docs and not seen:
        f += [Spacer(1, 6), P("No fundraiser documents or transaction attachments.", "small")]
    return f


@branding.themed
def build_fundraiser_report(db: Session, ctx, settings, fr: Fundraiser) -> tuple[str, str, dict]:
    """Standalone fundraiser report (the same section the Audit / Close reports include)."""
    ws = db.get(Workspace, ctx.workspace_id)
    users = {u.id: u.username for u in db.scalars(select(User).where(User.workspace_id == ctx.workspace_id))}
    title = f"Fundraiser Report — {fr.name} — {ws.name}"
    buf = io.BytesIO()
    doc = _AuditDoc(buf, title="Fundraiser Report", author=ws.name)
    f = _fundraiser_section(db, ctx, settings, doc, fr, users)
    f += [Spacer(1, 10), P(f"Generated {utcnow():%Y-%m-%d %H:%M} UTC by {ctx.user.username} — {ws.name}", "small")]
    doc.build(f)
    fd, path = tempfile.mkstemp(prefix="fmpoc-fundraiser-", suffix=".pdf")
    os.close(fd)
    try:
        pages = _stamp_and_write(buf.getvalue(), doc, path, title)
    except Exception:
        os.unlink(path)
        raise
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in fr.name).strip("-")[:60] or "fundraiser"
    return path, f"fundraiser-{safe}-report.pdf", {"pages": pages}


@branding.themed
def build_signature_page(db: Session, ctx, fy: FiscalYear, signature) -> tuple[str, str]:
    """v1.5.0 CR-029: the audit review signature page on its own (preview / separate printing)."""
    ws = db.get(Workspace, ctx.workspace_id)
    title = f"Audit review signature page — {fy.display_name} — {ws.name}"
    buf = io.BytesIO()
    doc = _AuditDoc(buf, title="Audit review signature page", author=ws.name)
    doc.build(_signature_page(doc, signature))
    fd, path = tempfile.mkstemp(prefix="fmpoc-signature-", suffix=".pdf")
    os.close(fd)
    try:
        _stamp_and_write(buf.getvalue(), doc, path, title)
    except Exception:
        os.unlink(path)
        raise
    return path, f"{fy.display_name}-audit-signature-page.pdf"


# --------------------------------------------------------------------------- Entity activity report
def entity_activity(db: Session, ctx, *, account_id: int | None, date_from: dt.date, date_to: dt.date,
                    entity_id: int | None, include_details: bool) -> dict:
    if date_to < date_from:
        raise validation("date_to must be on or after date_from.", "date_to")
    accts = {a.id: a for a in db.scalars(select(BankAccount).where(BankAccount.workspace_id == ctx.workspace_id))}
    if account_id is not None and account_id not in accts:
        raise validation("Bank Account not found.", "bank_account_id")
    q = (select(TransactionAllocation, RegisterTransaction)
         .join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
         .where(RegisterTransaction.workspace_id == ctx.workspace_id, RegisterTransaction.status == "ACTIVE",
                TransactionAllocation.removed_at.is_(None),
                RegisterTransaction.transaction_date.between(date_from, date_to))
         .order_by(RegisterTransaction.transaction_date, RegisterTransaction.id, TransactionAllocation.id))
    if account_id is not None:
        q = q.where(RegisterTransaction.bank_account_id == account_id)
    groups: dict[str, dict] = {}
    for al, t in db.execute(q).all():
        if t.transfer_group:
            key, ent = "transfers", None
        else:
            ent = al.entity or t.parent_entity
            if ent is not None and ent.is_system:
                ent = None
            key = f"e{ent.id}" if ent else "none"
        if entity_id is not None and (ent is None or ent.id != entity_id):
            continue
        g = groups.setdefault(key, {
            "key": key, "entity": None if ent is None else {"id": ent.id, "entity_number": ent.entity_number,
                                                            "display_name": ent.display_name, "active": ent.active},
            "label": ent.display_name if ent else ("(Transfers between accounts)" if key == "transfers" else "(No entity)"),
            "deposits": 0, "withdrawals": 0, "deposit_txns": set(), "withdrawal_txns": set(), "lines": []})
        if t.transaction_type == "DEPOSIT":
            g["deposits"] += al.amount_cents
            g["deposit_txns"].add(t.id)
        else:
            g["withdrawals"] += al.amount_cents
            g["withdrawal_txns"].add(t.id)
        if include_details:
            a = accts[t.bank_account_id]
            g["lines"].append({"transaction_id": t.id, "transaction_date": t.transaction_date.isoformat(),
                               "account": f"{a.account_name} - {bank.masked(a)}", "type": t.transaction_type,
                               "description": al.description, "invoice_number": al.invoice_number,
                               "check_number": reg.payment_text(t), "amount": fmt(al.amount_cents),
                               "cleared": t.clear_date is not None})
    rows = []
    for g in groups.values():
        rows.append({"key": g["key"], "entity": g["entity"], "label": g["label"], "deposits": fmt(g["deposits"]),
                     "withdrawals": fmt(g["withdrawals"]), "net": fmt(g["deposits"] - g["withdrawals"]),
                     "deposit_count": len(g["deposit_txns"]), "withdrawal_count": len(g["withdrawal_txns"]),
                     "lines": g["lines"] if include_details else None})
    order = {"none": 1, "transfers": 2}
    rows.sort(key=lambda r: (order.get(r["key"], 0), r["label"].lower()))
    entity_rows = [r for r in rows if r["key"] != "transfers"]
    tot_d = sum(int(round(float(r["deposits"]) * 100)) for r in entity_rows)
    tot_w = sum(int(round(float(r["withdrawals"]) * 100)) for r in entity_rows)
    acct = accts.get(account_id) if account_id else None
    return {"account": {"id": acct.id, "label": f"{acct.account_name} - {bank.masked(acct)}"} if acct else None,
            "date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "rows": rows,
            "totals": {"deposits": fmt(tot_d), "withdrawals": fmt(tot_w), "net": fmt(tot_d - tot_w),
                       "note": "Totals exclude transfers between accounts."},
            "generated_at": utcnow().isoformat() + "Z"}


def _csv_safe(v) -> str:
    """Neutralise spreadsheet formula injection in exported text (=, +, -, @ prefixes)."""
    s = "" if v is None else str(v)
    if s and s[0] in "=+-@\t\r" and not _is_number(s):
        return "'" + s
    return s


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def entity_activity_csv(report: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Entity", "Entity Number", "Deposits", "Deposit transactions", "Withdrawals", "Withdrawal transactions",
                "Net", "Account", "From", "To"])
    acct = report["account"]["label"] if report["account"] else "All accounts"
    for r in report["rows"]:
        w.writerow([_csv_safe(r["label"]), r["entity"]["entity_number"] if r["entity"] else "", r["deposits"],
                    r["deposit_count"], r["withdrawals"], r["withdrawal_count"], r["net"], _csv_safe(acct),
                    report["date_from"], report["date_to"]])
    if any(r["lines"] for r in report["rows"]):
        w.writerow([])
        w.writerow(["Entity", "Transaction #", "Date", "Account", "Type", "Description", "Invoice #", "Check # / payment", "Amount"])
        for r in report["rows"]:
            for ln in r["lines"] or []:
                w.writerow([_csv_safe(r["label"]), ln["transaction_id"], ln["transaction_date"], _csv_safe(ln["account"]),
                            ln["type"], _csv_safe(ln["description"]), _csv_safe(ln["invoice_number"]),
                            _csv_safe(ln["check_number"]), ln["amount"]])
    return out.getvalue()


__all__ = ["build_audit_report", "entity_activity", "entity_activity_csv", "KeepTogether", "Entity"]


# --------------------------------------------------------------------------- v1.6.4 CR-038 cash count sheet
_BILLS = ["$100", "$50", "$20", "$10", "$5", "$2", "$1"]
_COINS = ["$1 coin", "50¢", "25¢", "10¢", "5¢", "1¢"]
_CHECK_LINES = 13          # 1.6.7: as many check lines as bill/coin lines; more checks go on page 2 (the back)
_EXTRA_CHECK_LINES = 30    # page 2


COUNT_SHEET_MAX_SIGNATURES = 5        # rows on the sheet in total
COUNT_SHEET_MAX_BLANK = 3             # blank rows when no signer is chosen
COUNT_SHEET_DEFAULT_BLANK = 2         # blank rows when nothing is asked for (the dialog starts with two)
COUNT_SHEET_MAX_BLANK_WITH_NAMED = 2  # blank rows next to chosen signers


@branding.themed
def build_count_sheet(db: Session, ctx, fr: Fundraiser, signers: list[tuple[str, str | None]],
                      blank_lines: int = 0, extra_checks: bool = True) -> tuple[str, str]:
    """One printable page, filled in by hand: bills and coins grid, checks list, totals (usable on their own when the
    individual counts are not written down), two notes lines and one signature row per person (1.6.7): the
    chosen signers (signature line with the name under it, date) followed by `blank_lines` blank rows (Signature |
    Printed | Date).
    With neither, two blank rows. `extra_checks` adds page 2 (to print on the back): more check lines and their
    total."""
    ws = db.get(Workspace, ctx.workspace_id)
    title = f"Cash count sheet — {fr.name} — {ws.name}"
    def render(h_row: float):
        buf = io.BytesIO()
        doc = _AuditDoc(buf, title="Cash count sheet", author=ws.name)
        event = fr.start_date.isoformat() if fr.start_date == fr.end_date else f"{fr.start_date} to {fr.end_date}"
        blank = ""
        f: list = [_Mark(doc, "Cash count sheet"), PM("Cash count sheet", "h1"),
                   _kv([("Organization", ws.name), ("Fundraiser", fr.name), ("Event date", event)], w1=1.2 * inch, style="body"),
                   Spacer(1, 6),
                   PM("Date of count: ______________________ &nbsp;&nbsp;&nbsp; Time: ______________", "body"), Spacer(1, 8)]
        cash = [[PM("<b>Bills and coins</b>", "cell"), PM("<b>Count</b>", "cell"), PM("<b>Amount</b>", "cell")]]
        cash += [[P(x, "body"), blank, blank] for x in _BILLS + _COINS]
        cash += [[blank, blank, blank]] * max(0, _CHECK_LINES - len(_BILLS) - len(_COINS))
        checks = [[PM("<b>#</b>", "cell"), PM("<b>Check no.</b>", "cell"), PM("<b>From</b>", "cell"), PM("<b>Amount</b>", "cell")]]
        checks += [[P(str(i + 1), "cell"), blank, blank, blank] for i in range(_CHECK_LINES)]
        caps: list[str | None] = [f"{name}, {t}" if t else name for name, t in signers]
        caps += [None] * (blank_lines if (caps or blank_lines) else COUNT_SHEET_DEFAULT_BLANK)   # None = blank row
        caps = caps[:COUNT_SHEET_MAX_SIGNATURES]
        row_h = [0.2 * inch] + [0.235 * inch] * _CHECK_LINES
        left_w = [1.05 * inch, 0.7 * inch, 1.0 * inch]
        right_w = [0.3 * inch, 0.8 * inch, 1.75 * inch, 1.0 * inch]

        def grid(data, widths, heights=None):
            t = Table(data, colWidths=widths, rowHeights=heights or row_h)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#6b7480")),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8ecf1")),
                                   ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 4),
                                   ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
            return t

        pair = Table([[grid(cash, left_w), grid(checks, right_w)]], colWidths=[sum(left_w) + 0.3 * inch, sum(right_w)])
        pair.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
        totals = Table([[PM("<b>Cash total</b>", "body"), "$", PM("<b>Check total</b>", "body"), "$",
                         PM("<b>Total counted</b>", "body"), "$"]],
                       colWidths=[0.95 * inch, 1.3 * inch, 1.0 * inch, 1.3 * inch, 1.15 * inch, FRAME_W - 12 - 5.7 * inch],
                       rowHeights=[0.34 * inch])
        totals.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                    ("LINEAFTER", (1, 0), (1, 0), 0.5, colors.HexColor("#6b7480")),
                                    ("LINEAFTER", (3, 0), (3, 0), 0.5, colors.HexColor("#6b7480")),
                                    ("FONTNAME", (0, 0), (-1, -1), _FONT), ("FONTSIZE", (0, 0), (-1, -1), 10)]))
        if extra_checks:
            more = Table([["", P("More checks: continue on page 2 (the back of this sheet).", "small")]],
                         colWidths=[sum(left_w) + 0.3 * inch, sum(right_w)])
            more.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 1),
                                      ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
            f.append(pair)
            pair = more
        f += [pair, Spacer(1, 8), totals,
              P("The totals may be entered on their own when the individual bills, coins and checks are not listed above.", "small"),
              Spacer(1, 8), PM("Notes: ______________________________________________________________________________________", "body"),
              Spacer(1, 9), PM("_" * 92, "body"),   # always two notes lines
              Spacer(1, 10),
              P(f"We, the undersigned, counted the cash and checks received for {fr.name} and agree with the amounts "
                "recorded on this sheet.", "body"), Spacer(1, 4)]
        # 1.6.7: one row per person. A chosen signer: the signature line with the name (and title) under it, and
        # the date. A blank row: Signature | Printed | Date, all filled in by hand.
        w_sig, w_name, w_date, gap = 2.55 * inch, 2.45 * inch, 1.1 * inch, 0.22 * inch
        # (a chosen signer's line runs across both columns, up to the date - no empty gap)
        lines = [[_SignLine(w_sig + gap + w_name, c), "", _SignLine(w_date, "Date")] if c else
                 [_SignLine(w_sig, "Signature"), _SignLine(w_name, "Printed"), _SignLine(w_date, "Date")]
                 for c in caps]
        sig_t = Table(lines, hAlign="LEFT", colWidths=[w_sig + gap, w_name + gap, w_date], rowHeights=[h_row] * len(lines))
        sig_t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]
                                  + [("SPAN", (0, i), (1, i)) for i, c in enumerate(caps) if c]))
        f.append(sig_t)
        if extra_checks:   # page 2: print it on the back (duplex) or as a second sheet, only when it is needed
            wide = [0.4 * inch, 1.2 * inch, FRAME_W - 12 - 3.1 * inch, 1.5 * inch]
            more_rows = [[PM("<b>#</b>", "cell"), PM("<b>Check no.</b>", "cell"), PM("<b>From</b>", "cell"), PM("<b>Amount</b>", "cell")]]
            more_rows += [[P(str(_CHECK_LINES + 1 + i), "cell"), blank, blank, blank] for i in range(_EXTRA_CHECK_LINES)]
            sub = Table([[PM("<b>Total of the checks on this page</b>", "body"), "$"]],
                        colWidths=[FRAME_W - 12 - 1.5 * inch, 1.5 * inch], rowHeights=[0.34 * inch])
            sub.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                     ("LINEBEFORE", (1, 0), (1, 0), 0.5, colors.HexColor("#6b7480")),
                                     ("FONTNAME", (0, 0), (-1, -1), _FONT), ("FONTSIZE", (0, 0), (-1, -1), 10)]))
            f += [PageBreak(), _Mark(doc, "Additional checks"), PM("Cash count sheet — additional checks", "h1"),
                  _kv([("Organization", ws.name), ("Fundraiser", fr.name), ("Event date", event)], w1=1.2 * inch, style="body"),
                  Spacer(1, 8), grid(more_rows, wide, [0.2 * inch] + [0.235 * inch] * _EXTRA_CHECK_LINES), Spacer(1, 8), sub,
                  P("Include this total in the Check total on page 1.", "small")]
        doc.build(f)
        return buf, doc

    # the signature rows get as much height as page 1 allows (long names in the header take room): tallest that fits
    want = 2 if extra_checks else 1
    for h in (0.78, 0.7, 0.62, 0.55, 0.5, 0.46, 0.43, 0.4):
        buf, doc = render(h * inch)
        if doc.page <= want:
            break
    fd, path = tempfile.mkstemp(prefix="fmpoc-count-", suffix=".pdf")
    os.close(fd)
    try:
        _stamp_and_write(buf.getvalue(), doc, path, title)
    except Exception:
        os.unlink(path)
        raise
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in fr.name).strip("-")[:60] or "fundraiser"
    return path, f"fundraiser-{safe}-cash-count-sheet.pdf"
