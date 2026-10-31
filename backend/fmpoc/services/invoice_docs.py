"""2.4.0 (#253): invoices - drafts from the catalog, discounts, sales tax, numbering, sending (PDF), revisions, void
and write-off (Budget Manager approval).

Calculation (to the cent; all amounts in cents, quantities in thousandths, rates in thousandths of a percent):
  line gross     = round(quantity x unit price)
  line discount  = fixed amount, or round(gross x %)            (never more than the line)
  line net       = gross - line discount
  invoice disc.  = fixed amount, or round(sum of nets x %)      (never more than the sum of nets)
                   spread over the lines in proportion to their nets, the leftover cent(s) to the largest line, so
                   every line (and later every deposit allocation) stays >= 0 on its own budget
  taxable base   = sum of the final nets of taxable lines (tax applies after discounts)
  tax            = round(taxable base x rate), once per invoice
  total          = sum of final nets + tax
Rounding is half up.

Numbers come from the Administrator's pattern ({YYYY}/{YY} of the invoice date, {SEQ} or {SEQ:n}) and one sequence
that never restarts; a number is taken when the draft is created and never reused, even after a void (BR-001).
A sent invoice is changed by a revision: the same number with -R<n>; every sent version's PDF stays attached.
Void and write-off have no financial or budget effect. Payments (Partly paid / Paid) arrive with #254.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import re
from decimal import ROUND_HALF_UP, Decimal
from xml.sax.saxutils import escape

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, conflict, not_found, validation
from ..models import (Attachment, Entity, FiscalYear, Invoice, InvoiceLine, InvoiceProduct, InvoiceRevision,
                      InvoiceSettings, InvoiceTaxRate, Workspace, utcnow)
from ..money import fmt, parse_amount
from . import invoice_catalog as cat
from . import invoices as inv

OPEN = ("SENT", "PARTLY_PAID")
STATUS_LABEL = {"DRAFT": "Draft", "SENT": "Sent", "PARTLY_PAID": "Partly paid", "PAID": "Paid", "VOID": "Void",
                "WRITTEN_OFF": "Written off"}
PATTERN_TOKENS = re.compile(r"\{(YYYY|YY|SEQ(?::([1-9]))?)\}")
DEFAULT_PATTERN = "INV-{YYYY}-{SEQ:4}"


def _r(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------ parsing
def parse_quantity(raw) -> int:
    s = str(raw if raw is not None else "").strip()
    if not re.fullmatch(r"\d{1,9}(\.\d{1,3})?", s):
        raise validation("Enter the quantity as a number such as 1, 2.5 or 0.25 (up to three decimals).", "quantity")
    q = _r(Decimal(s) * 1000)
    if q <= 0:
        raise validation("The quantity must be more than 0.", "quantity")
    return q


def qty_text(milli: int) -> str:
    return f"{milli // 1000}.{milli % 1000:03d}".rstrip("0").rstrip(".")


def _discount(kind, value, reason, field: str) -> tuple[str | None, int | None, str | None]:
    if not kind:
        return None, None, None
    if kind not in ("AMOUNT", "PERCENT"):
        raise validation("A discount is a fixed amount or a percentage.", field)
    reason = (reason or "").strip()
    if not reason:
        raise validation("A discount needs a reason (it is printed on the discount line).", field)
    if kind == "AMOUNT":
        try:
            v = parse_amount(value, allow_zero=False)
        except ValueError as e:
            raise validation(str(e), field) from None
    else:
        v = cat._rate(value)
    return kind, v, reason[:200]


# ------------------------------------------------------------------ calculation
def compute(lines: list[InvoiceLine], discount_kind, discount_value, tax_milli: int | None) -> dict:
    rows = []
    for ln in lines:
        gross = _r(Decimal(ln.quantity_milli) * Decimal(ln.unit_price_cents) / 1000)
        if ln.discount_kind == "AMOUNT":
            ldisc = ln.discount_value or 0
        elif ln.discount_kind == "PERCENT":
            ldisc = _r(Decimal(gross) * Decimal(ln.discount_value or 0) / 100000)
        else:
            ldisc = 0
        if ldisc > gross:
            raise validation(f"The discount on \"{ln.description[:60]}\" is more than the line.", "lines")
        rows.append({"line": ln, "gross": gross, "line_discount": ldisc, "net": gross - ldisc, "share": 0})
    nets = sum(r["net"] for r in rows)
    if discount_kind == "AMOUNT":
        idisc = discount_value or 0
    elif discount_kind == "PERCENT":
        idisc = _r(Decimal(nets) * Decimal(discount_value or 0) / 100000)
    else:
        idisc = 0
    if idisc > nets:
        raise validation("The invoice discount is more than the invoice.", "discount")
    if idisc and nets:
        spread = 0
        for r in rows:
            r["share"] = int(Decimal(idisc) * Decimal(r["net"]) / Decimal(nets))     # floor; leftover below
            spread += r["share"]
        rest = idisc - spread
        for r in sorted(rows, key=lambda x: (-x["net"], x["line"].position)):
            if rest <= 0:
                break
            take = min(rest, r["net"] - r["share"])
            r["share"] += take
            rest -= take
    for r in rows:
        r["final"] = r["net"] - r["share"]
    base = sum(r["final"] for r in rows if r["line"].taxable)
    tax = _r(Decimal(base) * Decimal(tax_milli) / 100000) if tax_milli else 0
    subtotal = sum(r["gross"] for r in rows)
    return {"rows": rows, "subtotal": subtotal, "line_discounts": sum(r["line_discount"] for r in rows),
            "invoice_discount": idisc, "taxable_base": base, "tax": tax,
            "total": sum(r["final"] for r in rows) + tax}


def totals_of(i: Invoice) -> dict:
    return compute(list(i.lines), i.discount_kind, i.discount_value, i.tax_rate_milli_pct)


# ------------------------------------------------------------------ setup (Administrator)
def settings_of(db: Session, ws_id: int) -> InvoiceSettings:
    s = db.scalar(select(InvoiceSettings).where(InvoiceSettings.workspace_id == ws_id))
    if s is None:
        s = InvoiceSettings(workspace_id=ws_id, number_pattern=DEFAULT_PATTERN, next_seq=1, terms_days=30,
                            terms_text="Net 30")
        db.add(s)
        db.flush()
    return s


def check_pattern(p: str) -> str:
    p = (p or "").strip()
    seqs = [m for m in PATTERN_TOKENS.finditer(p) if m.group(1).startswith("SEQ")]
    if len(seqs) != 1:
        raise validation("The pattern needs exactly one {SEQ} (or {SEQ:4} for 4 digits).", "number_pattern")
    rest = PATTERN_TOKENS.sub("", p)
    if not re.fullmatch(r"[A-Za-z0-9 ._/#-]*", rest) or "{" in rest or "}" in rest:
        raise validation("Use letters, digits, spaces and - _ . / # besides {YYYY}, {YY} and {SEQ}.", "number_pattern")
    if len(p) > 40:
        raise validation("At most 40 characters.", "number_pattern")
    return p


def format_number(pattern: str, d: dt.date, seq: int) -> str:
    def rep(m):
        t = m.group(1)
        if t == "YYYY":
            return f"{d.year:04d}"
        if t == "YY":
            return f"{d.year % 100:02d}"
        width = int(m.group(2) or 0)
        return f"{seq:0{width}d}" if width else str(seq)
    return PATTERN_TOKENS.sub(rep, pattern)


def setup_out(db: Session, ctx) -> dict:
    s = settings_of(db, ctx.workspace_id)
    return {"module": inv.module_enabled(db, ctx.workspace_id), "number_pattern": s.number_pattern,
            "next_number_example": format_number(s.number_pattern, dt.date.today(), _next_seq(db, ctx.workspace_id, s)),
            "terms_days": s.terms_days, "terms_text": s.terms_text, "default_notes": s.default_notes,
            "overdue_reminder_days": s.overdue_reminder_days or 0,
            "fields": [field_out(f) for f in fields_of(db, ctx.workspace_id, include_inactive=True)],
            "pending": ["PDF template"]}


def save_setup(db: Session, ctx, body) -> dict:
    inv.require_module(db, ctx)
    s = settings_of(db, ctx.workspace_id)
    before = {"number_pattern": s.number_pattern, "terms_days": s.terms_days, "terms_text": s.terms_text,
              "default_notes": s.default_notes, "overdue_reminder_days": s.overdue_reminder_days or 0}
    s.number_pattern = check_pattern(body.number_pattern)
    if not 0 <= body.terms_days <= 365:
        raise validation("Terms are 0 to 365 days.", "terms_days")
    s.terms_days = body.terms_days
    s.terms_text = (body.terms_text or "").strip() or None
    s.default_notes = (body.default_notes or "").strip() or None
    if body.overdue_reminder_days is not None:                     # 2.4.0 (#255)
        if not 0 <= body.overdue_reminder_days <= 365:
            raise validation("The reminder is 0 to 365 days after the due date.", "overdue_reminder_days")
        s.overdue_reminder_days = body.overdue_reminder_days
    s.updated_by_user_id = ctx.user.id
    after = {"number_pattern": s.number_pattern, "terms_days": s.terms_days, "terms_text": s.terms_text,
             "default_notes": s.default_notes, "overdue_reminder_days": s.overdue_reminder_days or 0}
    if after != before:
        db.flush()
        audit.record(db, ctx, "INVOICE_SETUP_UPDATED", "invoice_settings", s.id, before, after)
    return setup_out(db, ctx)


def _next_seq(db: Session, ws_id: int, s: InvoiceSettings) -> int:
    """The settings' counter, never below the highest number used (so a restore can never cause a reuse)."""
    used = db.scalar(select(func.max(Invoice.seq)).where(Invoice.workspace_id == ws_id)) or 0
    return max(s.next_seq, used + 1)


# ------------------------------------------------------------------ read models
def display_number(i: Invoice) -> str:
    return i.number if not i.revision else f"{i.number}-R{i.revision}"


def _customer(db: Session, ctx, eid: int | None) -> Entity:
    e = db.get(Entity, eid) if isinstance(eid, int) else None
    if e is None or e.workspace_id != ctx.workspace_id or e.is_system:
        raise validation("Choose the customer.", "customer_entity_id")
    if not e.active:
        raise validation("That customer is inactive.", "customer_entity_id")
    return e


def snapshot(i: Invoice) -> dict:
    t = totals_of(i)
    return {"id": i.id, "number": display_number(i), "status": i.status, "customer_entity_id": i.customer_entity_id,
            "invoice_date": i.invoice_date.isoformat(), "due_date": i.due_date.isoformat(),
            "terms_text": i.terms_text, "notes": i.notes, "tax_rate_id": i.tax_rate_id,
            "discount": None if not i.discount_kind else {"kind": i.discount_kind, "value": i.discount_value,
                                                          "reason": i.discount_reason},
            "lines": [{"product_id": ln.product_id, "description": ln.description, "quantity": qty_text(ln.quantity_milli),
                       "unit_price": fmt(ln.unit_price_cents), "budget_id": ln.budget_id,
                       "discount": None if not ln.discount_kind else {"kind": ln.discount_kind, "value": ln.discount_value,
                                                                      "reason": ln.discount_reason}}
                      for ln in i.lines],
            "total": fmt(t["total"]), "tax": fmt(t["tax"]),
            "custom_values": json.loads(i.custom_values) if i.custom_values else {},
            "line_custom_values": [json.loads(ln.custom_values) if ln.custom_values else {} for ln in i.lines]}


def _disc_out(kind, value) -> str | None:
    if not kind:
        return None
    return fmt(value) if kind == "AMOUNT" else cat.rate_text(value)


def out(db: Session, ctx, i: Invoice, brief: bool = False) -> dict:
    t = totals_of(i)
    e = db.get(Entity, i.customer_entity_id)
    base = {"id": i.id, "number": display_number(i), "base_number": i.number, "revision": i.revision,
            "status": i.status, "status_label": STATUS_LABEL[i.status],
            "customer": {"id": e.id, "name": e.display_name} if e else None,
            "invoice_date": i.invoice_date.isoformat(), "due_date": i.due_date.isoformat(),
            "overdue": i.status in OPEN and i.due_date < dt.date.today(),
            "total": fmt(t["total"]), "write_off_status": i.write_off_status}
    from .invoice_payments import figures                    # 2.4.0 (#254)
    base["open"] = fmt(figures(db, i)["open"]) if i.status in OPEN + ("DRAFT",) else "0.00"
    if brief:
        return base
    revs = list(db.scalars(select(InvoiceRevision).where(InvoiceRevision.invoice_id == i.id)
                           .order_by(InvoiceRevision.revision)))
    return {**base, "terms_text": i.terms_text, "notes": i.notes,
            "tax": None if i.tax_rate_milli_pct is None else {"id": i.tax_rate_id, "name": i.tax_name,
                                                              "rate": cat.rate_text(i.tax_rate_milli_pct)},
            "discount": None if not i.discount_kind else {"kind": i.discount_kind, "value": _disc_out(i.discount_kind, i.discount_value),
                                                          "reason": i.discount_reason},
            "lines": [{"id": r["line"].id, "product_id": r["line"].product_id, "description": r["line"].description,
                       "unit_type": r["line"].unit_type, "quantity": qty_text(r["line"].quantity_milli),
                       "unit_price": fmt(r["line"].unit_price_cents), "taxable": bool(r["line"].taxable),
                       "budget": cat._budget_brief(db, r["line"].budget_id),
                       "gross": fmt(r["gross"]),
                       "discount": None if not r["line"].discount_kind else {
                           "kind": r["line"].discount_kind, "value": _disc_out(r["line"].discount_kind, r["line"].discount_value),
                           "reason": r["line"].discount_reason, "amount": fmt(r["line_discount"])},
                       "invoice_discount_share": fmt(r["share"]), "net": fmt(r["final"]),
                       "custom_values": json.loads(r["line"].custom_values) if r["line"].custom_values else {},
                       "fields": values_out(db, i.workspace_id, "LINE", r["line"].custom_values)} for r in t["rows"]],
            "custom_values": json.loads(i.custom_values) if i.custom_values else {},
            "fields": values_out(db, i.workspace_id, "INVOICE", i.custom_values),
            "totals": {"subtotal": fmt(t["subtotal"]), "line_discounts": fmt(t["line_discounts"]),
                       "invoice_discount": fmt(t["invoice_discount"]), "taxable": fmt(t["taxable_base"]),
                       "tax": fmt(t["tax"]), "total": fmt(t["total"])},
            "sent_at": i.sent_at.isoformat() + "Z" if i.sent_at else None,
            "void_reason": i.void_reason,
            "write_off": None if not i.write_off_status else {
                "status": i.write_off_status, "reason": i.write_off_reason, "note": i.write_off_note,
                "self_approved": bool(i.write_off_self_approved),
                "requested_at": i.write_off_requested_at.isoformat() + "Z" if i.write_off_requested_at else None,
                "decided_at": i.write_off_decided_at.isoformat() + "Z" if i.write_off_decided_at else None},
            "versions": [{"revision": r.revision, "number": r.number, "total": fmt(r.total_cents),
                          "sent_at": r.sent_at.isoformat() + "Z",
                          "pdf_url": f"/api/attachments/{r.attachment_id}/content" if r.attachment_id else None,
                          "reason": r.reason} for r in revs],
            "payments": _payments_out(db, i),
            "can": {"edit": i.status == "DRAFT", "send": i.status == "DRAFT", "revise": i.status in OPEN,
                    "void": i.status in ("DRAFT", "SENT") and not _has_payments(db, i),
                    "write_off": i.status in OPEN and i.write_off_status != "PENDING",
                    "decide_write_off": i.write_off_status == "PENDING"}}


def _payments_out(db: Session, i: Invoice) -> dict:
    from .invoice_payments import payments_out
    return payments_out(db, i)


def _has_payments(db: Session, i: Invoice) -> bool:
    from .invoice_payments import has_payments          # 2.4.0 (#254)
    return has_payments(db, i)


def get(db: Session, ctx, iid: int) -> Invoice:
    inv.require_module(db, ctx)
    ctx.require("invoice.view")
    i = db.get(Invoice, iid) if isinstance(iid, int) else None
    if i is None or i.workspace_id != ctx.workspace_id:
        raise not_found("Invoice")
    return i


def list_out(db: Session, ctx, status: str | None, customer_id: int | None, search: str | None) -> list[dict]:
    inv.require_module(db, ctx)
    ctx.require("invoice.view")
    q = select(Invoice).where(Invoice.workspace_id == ctx.workspace_id).order_by(Invoice.seq.desc())
    if status == "OPEN":
        q = q.where(Invoice.status.in_(OPEN))
    elif status:
        q = q.where(Invoice.status == status)
    if customer_id:
        q = q.where(Invoice.customer_entity_id == customer_id)
    if search:
        like = f"%{search.strip()}%"
        q = q.join(Entity, Entity.id == Invoice.customer_entity_id).where(or_(
            Invoice.number.ilike(like), Entity.organization_name.ilike(like), Entity.first_name.ilike(like),
            Entity.last_name.ilike(like)))
    return [out(db, ctx, i, brief=True) for i in db.scalars(q.limit(1000))]


# ------------------------------------------------------------------ create / edit (Invoice Manager)
def _fy_for(db: Session, ws_id: int, d: dt.date) -> FiscalYear:
    fys = list(db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ws_id, FiscalYear.start_date <= d,
                                                   FiscalYear.end_date >= d, FiscalYear.status != "CLOSED")
                          .order_by(FiscalYear.start_date)))
    if not fys:
        raise validation("No open Fiscal Year covers the invoice date, so its budgets can't be set. Choose another "
                         "date, or ask a Budget Manager to set up that Fiscal Year.", "invoice_date")
    return fys[0]


def _apply(db: Session, ctx, i: Invoice, body, creating: bool) -> None:
    e = _customer(db, ctx, body.customer_entity_id)
    s = settings_of(db, ctx.workspace_id)
    i.customer_entity_id = e.id
    i.invoice_date = body.invoice_date
    terms = s.terms_days
    i.due_date = body.due_date or (body.invoice_date + dt.timedelta(days=terms))
    if i.due_date < i.invoice_date:
        raise validation("The due date can't be before the invoice date.", "due_date")
    i.terms_text = (body.terms_text if body.terms_text is not None else (s.terms_text if creating else i.terms_text))
    i.terms_text = (i.terms_text or "").strip() or None
    i.notes = (body.notes if body.notes is not None else (s.default_notes if creating else i.notes))
    i.notes = (i.notes or "").strip() or None
    fy = _fy_for(db, ctx.workspace_id, i.invoice_date)
    # tax rate (copied, like prices)
    if body.tax_rate_id:
        tr = db.get(InvoiceTaxRate, body.tax_rate_id)
        if tr is None or tr.workspace_id != ctx.workspace_id:
            raise validation("Unknown tax rate.", "tax_rate_id")
        if not tr.active and tr.id != i.tax_rate_id:
            raise validation("That tax rate is inactive.", "tax_rate_id")
        tb = cat.budget_for_year(db, tr.budget_id, fy)
        if tb is None:
            raise AppError(422, "NEEDS_BUDGET", f"The tax rate \"{tr.name}\" has no Invoiced Income budget in "
                           f"{fy.display_name}. An Invoice Manager updates it in the catalog.")
        i.tax_rate_id, i.tax_name, i.tax_rate_milli_pct, i.tax_budget_id = tr.id, tr.name, tr.rate_milli_pct, tb.id
    else:
        i.tax_rate_id = i.tax_name = i.tax_rate_milli_pct = i.tax_budget_id = None
    d = body.discount
    i.discount_kind, i.discount_value, i.discount_reason = _discount(
        d.kind if d else None, d.value if d else None, d.reason if d else None, "discount")
    if not body.lines:
        raise validation("Add at least one line from the catalog.", "lines")
    keep = {ln.id: ln for ln in i.lines}
    new_lines = []
    for pos, lb in enumerate(body.lines, start=1):
        old = keep.get(lb.id) if lb.id else None
        if lb.id and old is None:
            raise validation("Unknown line.", "lines")
        if old is not None and old.product_id == lb.product_id:
            ln = old                                       # keeps its copied description and price
        else:
            p = db.get(InvoiceProduct, lb.product_id)
            if p is None or p.workspace_id != ctx.workspace_id:
                raise validation("Unknown product.", "lines")
            if p.is_system:
                raise validation("Use the discount fields for a discount.", "lines")
            if not p.active:
                raise validation(f"\"{p.name}\" is inactive.", "lines")
            b = cat.budget_for_year(db, p.budget_id, fy)
            if b is None:
                raise AppError(422, "NEEDS_BUDGET", f"\"{p.name}\" has no Invoiced Income budget in {fy.display_name}. "
                               "An Invoice Manager updates the product in the catalog.")
            from ..models import InvoiceUnitType
            u = db.get(InvoiceUnitType, p.unit_type_id) if p.unit_type_id else None
            desc = p.name if not p.description else f"{p.name} - {p.description}"
            ln = InvoiceLine(product_id=p.id, description=desc[:1000], unit_type=u.name if u else None,
                             unit_price_cents=p.unit_price_cents, taxable=bool(p.taxable), budget_id=b.id)
        ln.position = pos
        ln.quantity_milli = parse_quantity(lb.quantity)
        ln.discount_kind, ln.discount_value, ln.discount_reason = _discount(
            lb.discount_kind, lb.discount_value, lb.discount_reason, "lines")
        new_lines.append(ln)
    for ln in list(i.lines):
        if ln not in new_lines:
            i.lines.remove(ln)
    for ln in new_lines:
        if ln not in i.lines:
            i.lines.append(ln)
    i.lines.sort(key=lambda x: x.position)
    compute(list(i.lines), i.discount_kind, i.discount_value, i.tax_rate_milli_pct)   # validates the discounts
    # 2.4.0 (#253 part 2): custom fields
    i.custom_values = custom_values(db, ctx.workspace_id, "INVOICE", getattr(body, "custom_values", None),
                                    i.custom_values)
    for ln, lb in zip(new_lines, body.lines):
        ln.custom_values = custom_values(db, ctx.workspace_id, "LINE", getattr(lb, "custom_values", None),
                                         ln.custom_values)
    i.updated_by_user_id = ctx.user.id


def create(db: Session, ctx, body) -> Invoice:
    inv.require_module(db, ctx)
    ctx.require("invoice.manage")
    s = settings_of(db, ctx.workspace_id)
    seq = _next_seq(db, ctx.workspace_id, s)
    i = Invoice(workspace_id=ctx.workspace_id, seq=seq, revision=0, status="DRAFT", created_by_user_id=ctx.user.id,
                invoice_date=body.invoice_date, due_date=body.invoice_date, customer_entity_id=0, number="")
    _apply(db, ctx, i, body, creating=True)
    i.number = format_number(s.number_pattern, i.invoice_date, seq)
    s.next_seq = seq + 1                       # taken now; never reused, even if the draft is voided
    db.add(i)
    db.flush()
    audit.record(db, ctx, "INVOICE_CREATED", "invoice", i.id, None, snapshot(i))
    return i


def update(db: Session, ctx, i: Invoice, body) -> Invoice:
    ctx.require("invoice.manage")
    if i.status != "DRAFT":
        raise conflict("NOT_DRAFT", "Only a draft can be edited. A sent invoice is changed by a revision.")
    before = snapshot(i)
    _apply(db, ctx, i, body, creating=False)
    db.flush()
    if i.revision:                      # 2.4.0 (#254): a revision can't bring the total below what was paid
        from .invoice_payments import figures
        f = figures(db, i)
        if f["total"] < f["paid"]:
            raise validation(f"The revised total ({fmt(f['total'])}) can't be below the amount already paid "
                             f"({fmt(f['paid'])}).", "lines")
    after = snapshot(i)
    if after != before:
        audit.record(db, ctx, "INVOICE_UPDATED", "invoice", i.id, before, after)
    return i


# ------------------------------------------------------------------ send / revise
def send(db: Session, ctx, settings, i: Invoice) -> Invoice:
    """Mark as sent: the PDF of this version is made and kept with the invoice (every version's stays)."""
    ctx.require("invoice.manage")
    if i.status != "DRAFT":
        raise conflict("NOT_DRAFT", "Only a draft (or a revision being prepared) can be marked as sent.")
    from . import attachments as att_svc
    pdf = invoice_pdf(db, ctx.workspace_id, i)
    before = snapshot(i)
    t = totals_of(i)
    att, path = att_svc.new_record(db, ctx, settings, pdf,
                                   original_filename=att_svc.sanitize_filename(f"invoice-{display_number(i)}.pdf"),
                                   mime_type="application/pdf", invoice_id=i.id, document_type="INVOICE_PDF",
                                   system_generated=True)
    try:
        r = InvoiceRevision(invoice_id=i.id, revision=i.revision, number=display_number(i), total_cents=t["total"],
                            snapshot=json.dumps(snapshot(i), sort_keys=True), attachment_id=att.id,
                            sent_at=utcnow(), sent_by_user_id=ctx.user.id)
        db.add(r)
        i.status = "SENT"
        i.sent_at, i.sent_by_user_id = utcnow(), ctx.user.id
        db.flush()
        from .invoice_payments import refresh_status        # 2.4.0 (#254): a revision may already be (partly) paid
        refresh_status(db, ctx, i)
        audit.record(db, ctx, "INVOICE_SENT", "invoice", i.id, before,
                     {**snapshot(i), "pdf_attachment_id": att.id, "pdf_sha256": hashlib.sha256(pdf).hexdigest()})
        db.commit()
    except Exception:
        db.rollback()
        att_svc.discard_new_file(path)
        raise
    return i


def revise(db: Session, ctx, i: Invoice, reason: str) -> Invoice:
    """A sent invoice is changed by a revision: same number, -R<n>; it is a draft again until marked as sent."""
    ctx.require("invoice.manage")
    if i.status not in OPEN:
        raise conflict("INVALID_STATE", "Only a sent invoice can be revised.")
    if i.write_off_status == "PENDING":
        raise conflict("WRITE_OFF_PENDING", "A write-off is waiting for a decision; it must be decided first.")
    reason = (reason or "").strip()
    if not reason:
        raise validation("Say why the invoice is revised.", "reason")
    before = snapshot(i)
    last = db.scalar(select(InvoiceRevision).where(InvoiceRevision.invoice_id == i.id)
                     .order_by(InvoiceRevision.revision.desc()))
    if last is not None:
        last.reason = reason[:500]
    i.revision += 1
    i.status = "DRAFT"
    i.updated_by_user_id = ctx.user.id
    db.flush()
    audit.record(db, ctx, "INVOICE_REVISION_STARTED", "invoice", i.id, before, {**snapshot(i), "reason": reason})
    return i


# ------------------------------------------------------------------ void / write-off
def void(db: Session, ctx, i: Invoice, reason: str) -> Invoice:
    ctx.require("invoice.manage")
    if i.status not in ("DRAFT", "SENT"):
        raise conflict("INVALID_STATE", "Only a draft or a sent, unpaid invoice can be voided.")
    if _has_payments(db, i):
        raise conflict("HAS_PAYMENTS", "Payments are linked to this invoice; it can't be voided.")
    reason = (reason or "").strip()
    if not reason:
        raise validation("A void needs a reason.", "reason")
    before = snapshot(i)
    i.status, i.void_reason, i.voided_at, i.voided_by_user_id = "VOID", reason[:500], utcnow(), ctx.user.id
    db.flush()
    audit.record(db, ctx, "INVOICE_VOIDED", "invoice", i.id, before, {**snapshot(i), "reason": reason})
    return i


def request_write_off(db: Session, ctx, i: Invoice, reason: str) -> Invoice:
    ctx.require("invoice.manage")
    if i.status not in OPEN:
        raise conflict("INVALID_STATE", "Only a sent invoice with an open balance can be written off.")
    if i.write_off_status == "PENDING":
        raise conflict("WRITE_OFF_PENDING", "A write-off is already waiting for a decision.")
    reason = (reason or "").strip()
    if not reason:
        raise validation("A write-off needs a reason.", "reason")
    i.write_off_status, i.write_off_reason = "PENDING", reason[:500]
    i.write_off_requested_at, i.write_off_requested_by_user_id = utcnow(), ctx.user.id
    i.write_off_decided_at = i.write_off_decided_by_user_id = i.write_off_note = None
    i.write_off_self_approved = False
    db.flush()
    audit.record(db, ctx, "INVOICE_WRITE_OFF_REQUESTED", "invoice", i.id, None,
                 {"number": display_number(i), "reason": reason, "open_balance": fmt(totals_of(i)["total"])})
    return i


def decide_write_off(db: Session, ctx, i: Invoice, approve: bool, note: str | None) -> Invoice:
    """A Budget Manager approves or rejects. A person holding both roles may approve their own request; it is marked
    self-approved. No financial or budget effect."""
    ctx.require("invoice.write_off_decide")
    if i.write_off_status != "PENDING":
        raise conflict("INVALID_STATE", "No write-off is waiting for a decision.")
    note = (note or "").strip() or None
    if not approve and not note:
        raise validation("Say why the write-off is rejected.", "note")
    before = snapshot(i)
    i.write_off_status = "APPROVED" if approve else "REJECTED"
    i.write_off_decided_at, i.write_off_decided_by_user_id, i.write_off_note = utcnow(), ctx.user.id, note
    i.write_off_self_approved = approve and i.write_off_requested_by_user_id == ctx.user.id
    if approve:
        i.status = "WRITTEN_OFF"
    db.flush()
    audit.record(db, ctx, "INVOICE_WRITE_OFF_APPROVED" if approve else "INVOICE_WRITE_OFF_REJECTED", "invoice", i.id,
                 before, {**snapshot(i), "note": note, "self_approved": bool(i.write_off_self_approved)})
    return i


# ------------------------------------------------------------------ PDF
def invoice_pdf(db: Session, ws_id: int, i: Invoice | None, sample: bool = False, watermark: str | None = None) -> bytes:
    """The invoice PDF (a plain layout; the template editor comes with the next build). `sample` renders dummy data
    for the Administrator's test print (BR-003): no real invoice, customer or product is read."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from . import organization as org_svc
    ws = db.get(Workspace, ws_id)
    org = org_svc.get(db, ws_id)
    org_name = (org.organization_name if org else None) or (ws.name if ws else "")
    org_lines = org_svc.address_lines(org)
    if sample:
        data = _sample_data()
    else:
        data = _pdf_data(db, i)
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["Normal"], fontSize=9.5, leading=12)
    small = ParagraphStyle("s", parent=body, fontSize=8, leading=10, textColor=colors.HexColor("#555555"))
    right = ParagraphStyle("r", parent=body, alignment=2)
    title = ParagraphStyle("t", parent=ss["Title"], fontSize=20, alignment=2, spaceAfter=2)
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
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch, title=f"Invoice {data['number']}",
                            author=org_name)
    head = Table([[[Paragraph(f"<b>{escape(org_name)}</b>", body)] + [Paragraph(escape(x), body) for x in org_lines],
                   [Paragraph("INVOICE", title), Paragraph(f"<b>{escape(data['number'])}</b>", right),
                    Paragraph(f"Date {escape(data['date'])}", right), Paragraph(f"Due {escape(data['due'])}", right)]]],
                 colWidths=[3.6 * inch, 3.4 * inch])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    f = [head, Spacer(1, 14), Paragraph("<b>Bill to</b>", body)]
    f += [Paragraph(escape(x), body) for x in data["bill_to"]]
    for name, value in data.get("fields") or []:          # 2.4.0 (#253 part 2): invoice custom fields
        f.append(Paragraph(f"<b>{escape(name)}:</b> {escape(value)}", body))
    f.append(Spacer(1, 12))
    rows = [[Paragraph("<b>Description</b>", body), Paragraph("<b>Qty</b>", right), Paragraph("<b>Unit price</b>", right),
             Paragraph("<b>Amount</b>", right)]]
    for ln in data["lines"]:
        rows.append([Paragraph(escape(ln["description"]) + (f" <font size=8>({escape(ln['unit'])})</font>" if ln["unit"] else ""), body),
                     Paragraph(escape(ln["qty"]), right), Paragraph(escape(ln["price"]), right),
                     Paragraph(escape(ln["amount"]), right)])
        if ln.get("discount"):
            rows.append([Paragraph(f"&nbsp;&nbsp;Discount — {escape(ln['discount_reason'])}", small), "", "",
                         Paragraph(f"-{escape(ln['discount'])}", right)])
    t = Table(rows, colWidths=[4.1 * inch, 0.7 * inch, 1.1 * inch, 1.1 * inch], repeatRows=1)
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#888888")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    f.append(t)
    f.append(Spacer(1, 8))
    tot = [["Subtotal", data["subtotal"]]]
    if data.get("invoice_discount"):
        tot.append([f"Discount — {data['invoice_discount_reason']}", f"-{data['invoice_discount']}"])
    if data.get("tax"):
        tot.append([data["tax_label"], data["tax"]])
    tot.append(["Total due", data["total"]])
    tt = Table([[Paragraph(escape(a), right if k < len(tot) - 1 else ParagraphStyle("tb", parent=right, fontName="Helvetica-Bold")),
                 Paragraph(escape(b), right if k < len(tot) - 1 else ParagraphStyle("tb2", parent=right, fontName="Helvetica-Bold"))]
                for k, (a, b) in enumerate(tot)], colWidths=[5.9 * inch, 1.1 * inch])
    tt.setStyle(TableStyle([("LINEABOVE", (0, len(tot) - 1), (-1, len(tot) - 1), 0.6, colors.HexColor("#888888"))]))
    f.append(tt)
    if data.get("terms"):
        f += [Spacer(1, 14), Paragraph(f"<b>Terms:</b> {escape(data['terms'])}", body)]
    if data.get("notes"):
        f += [Spacer(1, 6), Paragraph(escape(data["notes"]).replace("\n", "<br/>"), body)]
    doc.build(f, onFirstPage=mark, onLaterPages=mark)
    return buf.getvalue()


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _pdf_data(db: Session, i: Invoice) -> dict:
    from .checkprint.service import address_lines
    t = totals_of(i)
    e = db.get(Entity, i.customer_entity_id)
    lines = []
    for r in t["rows"]:
        ln = r["line"]
        extra = "; ".join(f"{x['name']}: {x['value']}" for x in values_out(db, i.workspace_id, "LINE", ln.custom_values,
                                                                           pdf_only=True))
        lines.append({"description": ln.description + (f" ({extra})" if extra else ""), "unit": ln.unit_type or "",
                      "qty": qty_text(ln.quantity_milli),
                      "price": _money(ln.unit_price_cents), "amount": _money(r["gross"]),
                      "discount": _money(r["line_discount"]) if r["line_discount"] else None,
                      "discount_reason": ln.discount_reason or ""})
    return {"number": display_number(i), "date": i.invoice_date.strftime("%m/%d/%Y"),
            "due": i.due_date.strftime("%m/%d/%Y"),
            "bill_to": ([e.legal_name] if e else []) + (address_lines(e) if e else []),
            "lines": lines, "subtotal": _money(t["subtotal"] - t["line_discounts"]),
            "invoice_discount": _money(t["invoice_discount"]) if t["invoice_discount"] else None,
            "invoice_discount_reason": i.discount_reason or "",
            "tax": _money(t["tax"]) if i.tax_rate_milli_pct else None,
            "tax_label": f"{i.tax_name} ({cat.rate_text(i.tax_rate_milli_pct)} %)" if i.tax_rate_milli_pct else "",
            "total": _money(t["total"]), "terms": i.terms_text, "notes": i.notes,
            "fields": [(x["name"], x["value"]) for x in values_out(db, i.workspace_id, "INVOICE", i.custom_values,
                                                                  pdf_only=True)]}


def _sample_data() -> dict:
    return {"number": "INV-0000-SAMPLE", "date": "01/15/2027", "due": "02/14/2027",
            "bill_to": ["Sample Customer", "123 Example Street", "Springfield, ST 00000"],
            "lines": [{"description": "Sample product - annual dues", "unit": "Year", "qty": "1", "price": "$120.00",
                       "amount": "$120.00", "discount": None, "discount_reason": ""},
                      {"description": "Sample service", "unit": "Hour", "qty": "2.5", "price": "$40.00",
                       "amount": "$100.00", "discount": "$10.00", "discount_reason": "Sample discount"}],
            "subtotal": "$210.00", "invoice_discount": None, "invoice_discount_reason": "",
            "tax": "$15.23", "tax_label": "Sample tax (7.25 %)", "total": "$225.23", "terms": "Net 30",
            "notes": "This is a test print with sample data.", "fields": [("Purchase order", "SAMPLE-PO-1")]}


__all__ = ["Attachment"]


# ------------------------------------------------------------------ 2.4.0 (#253 part 2): custom fields
FIELD_TYPES = ("TEXT", "NUMBER", "DATE", "PICKLIST")
FIELD_LEVELS = ("INVOICE", "LINE")
TEXT_MAX = 200


def field_out(f) -> dict:
    return {"id": f.id, "level": f.level, "name": f.name, "field_type": f.field_type,
            "options": json.loads(f.options) if f.options else [], "required": bool(f.required),
            "show_on_pdf": bool(f.show_on_pdf), "position": f.position, "active": bool(f.active)}


def fields_of(db: Session, ws_id: int, include_inactive: bool = False) -> list:
    from ..models import InvoiceCustomField
    q = select(InvoiceCustomField).where(InvoiceCustomField.workspace_id == ws_id).order_by(
        InvoiceCustomField.level, InvoiceCustomField.position, InvoiceCustomField.id)
    if not include_inactive:
        q = q.where(InvoiceCustomField.active.is_(True))
    return list(db.scalars(q))


def save_field(db: Session, ctx, fid: int | None, body) -> dict:
    """Administrator (invoice.setup). The level and type are fixed once created (values already entered keep their
    meaning); name, options, required, show-on-PDF and order can change."""
    from ..models import InvoiceCustomField
    inv.require_module(db, ctx)
    name = (body.name or "").strip()
    if not name:
        raise validation("Enter a name.", "name")
    opts = [o.strip() for o in (body.options or []) if o and o.strip()]
    if len(set(o.lower() for o in opts)) != len(opts):
        raise validation("The choices must be different.", "options")
    if any(len(o) > 80 for o in opts) or len(opts) > 50:
        raise validation("At most 50 choices of 80 characters.", "options")
    if fid is None:
        if body.level not in FIELD_LEVELS or body.field_type not in FIELD_TYPES:
            raise validation("Choose the level and the type.", "field_type")
        f = InvoiceCustomField(workspace_id=ctx.workspace_id, level=body.level, field_type=body.field_type,
                               created_by_user_id=ctx.user.id,
                               position=1 + (db.scalar(select(func.max(InvoiceCustomField.position)).where(
                                   InvoiceCustomField.workspace_id == ctx.workspace_id)) or 0))
        db.add(f)
        before = None
    else:
        f = db.get(InvoiceCustomField, fid)
        if f is None or f.workspace_id != ctx.workspace_id:
            raise not_found("Field")
        if (body.level and body.level != f.level) or (body.field_type and body.field_type != f.field_type):
            raise validation("A field's level and type can't change; retire it and add a new one.", "field_type")
        before = field_out(f)
    if f.field_type == "PICKLIST" and not opts:
        raise validation("A pick-list needs at least one choice.", "options")
    dup = db.scalar(select(InvoiceCustomField.id).where(
        InvoiceCustomField.workspace_id == ctx.workspace_id, InvoiceCustomField.level == f.level,
        func.lower(InvoiceCustomField.name) == name.lower(), InvoiceCustomField.id != (f.id or -1)))
    if dup is not None:
        raise conflict("DUPLICATE_NAME", f"A field named \"{name}\" already exists (it may be retired).")
    f.name, f.options = name[:60], json.dumps(opts) if f.field_type == "PICKLIST" else None
    f.required, f.show_on_pdf, f.updated_by_user_id = bool(body.required), bool(body.show_on_pdf), ctx.user.id
    db.flush()
    after = field_out(f)
    if before is None:
        audit.record(db, ctx, "INVOICE_FIELD_CREATED", "invoice_custom_field", f.id, None, after)
    elif after != before:
        audit.record(db, ctx, "INVOICE_FIELD_UPDATED", "invoice_custom_field", f.id, before, after)
    return after


def set_field_active(db: Session, ctx, fid: int, active: bool) -> dict:
    from ..models import InvoiceCustomField
    inv.require_module(db, ctx)
    f = db.get(InvoiceCustomField, fid) if isinstance(fid, int) else None
    if f is None or f.workspace_id != ctx.workspace_id:
        raise not_found("Field")
    if bool(f.active) != active:
        before = field_out(f)
        f.active, f.updated_by_user_id = active, ctx.user.id
        db.flush()
        audit.record(db, ctx, "INVOICE_FIELD_RESTORED" if active else "INVOICE_FIELD_RETIRED", "invoice_custom_field",
                     f.id, before, field_out(f))
    return field_out(f)


def _check_value(f, raw):
    """A value for an active field, as stored (string); None for empty."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if f.required:
            raise validation(f"\"{f.name}\" is required.", f"field_{f.id}")
        return None
    v = str(raw).strip()
    if f.field_type == "TEXT":
        if len(v) > TEXT_MAX:
            raise validation(f"\"{f.name}\": at most {TEXT_MAX} characters.", f"field_{f.id}")
    elif f.field_type == "NUMBER":
        if not re.fullmatch(r"-?\d{1,12}(\.\d{1,4})?", v):
            raise validation(f"\"{f.name}\" must be a number.", f"field_{f.id}")
    elif f.field_type == "DATE":
        try:
            dt.date.fromisoformat(v)
        except ValueError:
            raise validation(f"\"{f.name}\" must be a date.", f"field_{f.id}") from None
    else:
        if v not in (json.loads(f.options) if f.options else []):
            raise validation(f"\"{f.name}\": choose one of the listed choices.", f"field_{f.id}")
    return v


def custom_values(db: Session, ws_id: int, level: str, given: dict | None, old_json: str | None) -> str | None:
    """Validates the values for the level's active fields; values of retired fields are kept as they were."""
    given = {str(k): v for k, v in (given or {}).items()}
    old = json.loads(old_json) if old_json else {}
    fields = {str(f.id): f for f in fields_of(db, ws_id, include_inactive=True) if f.level == level}
    unknown = set(given) - set(fields)
    if unknown:
        raise validation("Unknown field.", "custom_values")
    out = {}
    for fid, f in fields.items():
        if not f.active:
            if fid in old:
                out[fid] = old[fid]
            continue
        v = _check_value(f, given.get(fid))
        if v is not None:
            out[fid] = v
    return json.dumps(out, sort_keys=True) if out else None


def values_out(db: Session, ws_id: int, level: str, raw: str | None, pdf_only: bool = False) -> list[dict]:
    vals = json.loads(raw) if raw else {}
    rows = []
    for f in fields_of(db, ws_id, include_inactive=True):
        if f.level != level or str(f.id) not in vals or (pdf_only and not f.show_on_pdf):
            continue
        rows.append({"field_id": f.id, "name": f.name, "value": vals[str(f.id)], "retired": not f.active})
    return rows
