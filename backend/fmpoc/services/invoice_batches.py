"""2.4.0 (#248): batch invoicing - the same invoice for many customers at once (annual dues to every member).

The Invoice Manager picks the customers and the catalog lines and sets the dates; one **draft** per customer is
created in one step (all or none), numbered in customer order. The batch is only a label on its invoices: each stays
an ordinary invoice (edit, void, send, payments). *Mark all as sent* sends the batch's drafts; the combined PDF is
every invoice of the batch that isn't void, one after another (drafts marked DRAFT). Everything is audited.
"""
from __future__ import annotations

import io

from pypdf import PdfReader, PdfWriter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import not_found, validation
from ..models import Entity, Invoice, InvoiceBatch
from ..money import fmt
from . import invoice_docs as docs
from . import invoices as inv

MAX_CUSTOMERS = 500


def _invoices(db: Session, b: InvoiceBatch) -> list[Invoice]:
    return list(db.scalars(select(Invoice).where(Invoice.batch_id == b.id).order_by(Invoice.seq)))


def get(db: Session, ctx, bid: int) -> InvoiceBatch:
    inv.require_module(db, ctx)
    ctx.require("invoice.view")
    b = db.get(InvoiceBatch, bid) if isinstance(bid, int) else None
    if b is None or b.workspace_id != ctx.workspace_id:
        raise not_found("Batch")
    return b


def out(db: Session, ctx, b: InvoiceBatch) -> dict:
    invs = _invoices(db, b)
    items = [docs.out(db, ctx, i, brief=True) for i in invs]
    total = sum(docs.totals_of(i)["total"] for i in invs if i.status != "VOID")
    return {"id": b.id, "name": b.name, "created_at": b.created_at.isoformat() + "Z", "invoices": items,
            "count": len(items), "drafts": sum(1 for x in items if x["status"] == "DRAFT"), "total": fmt(total)}


def listing(db: Session, ctx) -> list[dict]:
    inv.require_module(db, ctx)
    ctx.require("invoice.view")
    counts = dict(db.execute(select(Invoice.batch_id, func.count()).where(Invoice.workspace_id == ctx.workspace_id,
                                                                         Invoice.batch_id.is_not(None))
                             .group_by(Invoice.batch_id)).all())
    drafts = dict(db.execute(select(Invoice.batch_id, func.count()).where(Invoice.workspace_id == ctx.workspace_id,
                                                                         Invoice.batch_id.is_not(None), Invoice.status == "DRAFT")
                             .group_by(Invoice.batch_id)).all())
    return [{"id": b.id, "name": b.name, "created_at": b.created_at.isoformat() + "Z", "count": counts.get(b.id, 0),
             "drafts": drafts.get(b.id, 0)}
            for b in db.scalars(select(InvoiceBatch).where(InvoiceBatch.workspace_id == ctx.workspace_id)
                                .order_by(InvoiceBatch.id.desc()))]


def create(db: Session, ctx, body) -> InvoiceBatch:
    """One draft per customer, same lines, dates, tax, discount, notes and invoice fields; all or none."""
    from ..schemas import InvoiceIn
    inv.require_module(db, ctx)
    ctx.require("invoice.manage")
    ids = list(dict.fromkeys(body.customer_entity_ids))
    if not ids:
        raise validation("Choose at least one customer.", "customer_entity_ids")
    if len(ids) != len(body.customer_entity_ids):
        raise validation("A customer is listed twice.", "customer_entity_ids")
    if len(ids) > MAX_CUSTOMERS:
        raise validation(f"At most {MAX_CUSTOMERS} customers in one batch.", "customer_entity_ids")
    if not body.lines:
        raise validation("Add at least one line.", "lines")
    ents = {e.id: e for e in db.scalars(select(Entity).where(Entity.id.in_(ids), Entity.workspace_id == ctx.workspace_id))}
    missing = [i for i in ids if i not in ents]
    if missing:
        raise not_found("Customer")
    name = (body.name or "").strip() or f"Batch of {body.invoice_date.isoformat()}"
    b = InvoiceBatch(workspace_id=ctx.workspace_id, name=name[:120], created_by_user_id=ctx.user.id)
    db.add(b)
    db.flush()
    made = []
    for e in sorted(ents.values(), key=lambda x: (x.display_name.lower(), x.id)):
        data = InvoiceIn(customer_entity_id=e.id, invoice_date=body.invoice_date, due_date=body.due_date,
                         terms_text=body.terms_text, notes=body.notes, tax_rate_id=body.tax_rate_id,
                         discount=body.discount, lines=[ln.model_copy() for ln in body.lines],
                         custom_values=body.custom_values)
        try:
            i = docs.create(db, ctx, data)
        except Exception as x:                # name the customer that failed (the whole batch is rolled back)
            msg = getattr(x, "message", None)
            if msg:
                x.message = f"{e.display_name}: {msg}"
            raise
        i.batch_id = b.id
        made.append(i)
    db.flush()
    audit.record(db, ctx, "INVOICE_BATCH_CREATED", "invoice_batch", b.id, None,
                 {"name": b.name, "invoices": [i.id for i in made], "numbers": [i.number for i in made],
                  "customers": len(made)})
    return b


def send_all(db: Session, ctx, settings, b: InvoiceBatch) -> dict:
    """Marks every draft of the batch as sent (each keeps its PDF, as when sent one by one). Each invoice is its own
    step: one that can't be sent is reported and the others go ahead."""
    ctx.require("invoice.manage")
    sent, failed = [], []
    for i in [i for i in _invoices(db, b) if i.status == "DRAFT"]:
        try:
            docs.send(db, ctx, settings, i)
            sent.append(docs.display_number(i))
        except Exception as x:                # noqa: BLE001 - reported per invoice
            db.rollback()
            failed.append({"number": docs.display_number(i), "message": getattr(x, "message", str(x))[:300]})
    audit.record(db, ctx, "INVOICE_BATCH_SENT", "invoice_batch", b.id, None, {"sent": sent, "failed": failed})
    db.commit()
    return {"sent": sent, "failed": failed}


def combined_pdf(db: Session, ctx, b: InvoiceBatch) -> bytes:
    """Every invoice of the batch that isn't void, in number order (drafts marked DRAFT)."""
    w = PdfWriter()
    n = 0
    for i in _invoices(db, b):
        if i.status == "VOID":
            continue
        pdf = docs.invoice_pdf(db, ctx.workspace_id, i, watermark="DRAFT" if i.status == "DRAFT" else None)
        for page in PdfReader(io.BytesIO(pdf)).pages:
            w.add_page(page)
        n += 1
    if not n:
        raise validation("The batch has no invoices to print (all are void).", "batch")
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()
