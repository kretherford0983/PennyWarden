"""2.4.0 (#255): invoice reports (Reports catalog, Invoices group) and the overdue figures.

Seven reports, each a list of sections (columns + rows + totals) rendered by one PDF and one CSV writer:
open invoices, aging, customer statement, sales tax collected, invoice register, sales by product / category, and
payments, write-offs, discounts and refunds. Viewers are the invoice viewers (`invoice.view`: Invoice Managers,
Register Users, Budget Managers, Budget Users, Auditors - never the Administrator); the module must be on.

Money is in cents throughout and every figure comes from the invoices and their linked register lines
(`invoice_payments`), so the reports reconcile with the invoices to the cent. Only ACTIVE (not voided) register lines
count; a payment counts on its register transaction date.
"""
from __future__ import annotations

import csv
import datetime as dt
import io

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import not_found, validation
from ..models import (Budget, Entity, Invoice, InvoicePayment, InvoiceProduct, InvoiceProductCategory, InvoiceRevision,
                      RegisterTransaction, TransactionAllocation, Workspace)
from ..money import fmt
from . import invoice_docs as docs
from . import invoice_payments as pay
from . import invoices as inv
from .common import budget_label

REPORTS = {
    "inv-open": "Open invoices",
    "inv-aging": "Aging",
    "inv-statement": "Customer statement",
    "inv-sales-tax": "Sales tax collected",
    "inv-register": "Invoice register",
    "inv-sales": "Sales by product / category",
    "inv-activity": "Payments, write-offs, discounts and refunds",
}
BUCKETS = [("current", "Current"), ("d1_30", "1–30 days"), ("d31_60", "31–60 days"), ("d61_90", "61–90 days"),
           ("d90", "Over 90 days")]
LIVE = ("SENT", "PARTLY_PAID", "PAID", "WRITTEN_OFF")        # issued (not draft, not void)


def today() -> dt.date:
    return dt.date.today()


# ------------------------------------------------------------------ data helpers
def _invoices(db: Session, ws_id: int, statuses=None, date_from=None, date_to=None, customer_id=None) -> list[Invoice]:
    q = select(Invoice).where(Invoice.workspace_id == ws_id)
    if statuses:
        q = q.where(Invoice.status.in_(statuses))
    if date_from:
        q = q.where(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.where(Invoice.invoice_date <= date_to)
    if customer_id:
        q = q.where(Invoice.customer_entity_id == customer_id)
    return list(db.scalars(q.order_by(Invoice.invoice_date, Invoice.seq)))


def _links(db: Session, invoice_ids: list[int]) -> dict[int, list[tuple[InvoicePayment, TransactionAllocation, RegisterTransaction]]]:
    """Live links on ACTIVE register lines, per invoice, in date order."""
    out: dict[int, list] = {i: [] for i in invoice_ids}
    if not invoice_ids:
        return out
    rows = db.execute(select(InvoicePayment, TransactionAllocation, RegisterTransaction)
                      .join(TransactionAllocation, TransactionAllocation.id == InvoicePayment.allocation_id)
                      .join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
                      .where(InvoicePayment.invoice_id.in_(invoice_ids), InvoicePayment.removed_at.is_(None),
                             TransactionAllocation.removed_at.is_(None), RegisterTransaction.status == "ACTIVE")
                      .order_by(RegisterTransaction.transaction_date, InvoicePayment.id)).all()
    for link, a, t in rows:
        out[link.invoice_id].append((link, a, t))
    return out


def _by_txn(links) -> list[tuple[str, RegisterTransaction, int, int]]:
    """Links grouped per register transaction and kind (a payment is one line per invoice line and tax):
    [(kind, transaction, amount, first link id)] in date order."""
    out: dict[tuple, list] = {}
    for link, a, t in links:
        k = (t.id, link.kind)
        if k not in out:
            out[k] = [link.kind, t, 0, link.id]
        out[k][2] += a.amount_cents
    return sorted((tuple(v) for v in out.values()), key=lambda v: (v[1].transaction_date, v[3]))


def _paid(links, as_of: dt.date | None = None) -> int:
    return sum(a.amount_cents for link, a, t in links if link.kind == "PAYMENT" and (as_of is None or t.transaction_date <= as_of))


def _names(db: Session, ids) -> dict[int, str]:
    ids = [i for i in set(ids) if i]
    return {e.id: e.display_name for e in db.scalars(select(Entity).where(Entity.id.in_(ids)))} if ids else {}


def _budget_names(db: Session, ids) -> dict[int, str]:
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    bs = {b.id: b for b in db.scalars(select(Budget).where(Budget.id.in_(ids)))}
    parents = {b.id: b for b in db.scalars(select(Budget).where(Budget.id.in_([b.parent_budget_id for b in bs.values() if b.parent_budget_id])))}
    return {bid: budget_label(b, parents.get(b.parent_budget_id)) for bid, b in bs.items()}


def _days_over(i: Invoice, as_of: dt.date) -> int:
    return max((as_of - i.due_date).days, 0)


def _bucket(days: int) -> str:
    if days <= 0:
        return "current"
    return "d1_30" if days <= 30 else "d31_60" if days <= 60 else "d61_90" if days <= 90 else "d90"


def _open_rows(db: Session, ws_id: int, as_of: dt.date, customer_id: int | None) -> list[dict]:
    """Invoices issued by `as_of` with an open balance as of that day (payments dated after it don't count).
    Void, written-off and draft invoices are not open."""
    invs = [i for i in _invoices(db, ws_id, ("SENT", "PARTLY_PAID", "PAID"), date_to=as_of, customer_id=customer_id)]
    links = _links(db, [i.id for i in invs])
    names = _names(db, [i.customer_entity_id for i in invs])
    rows = []
    for i in invs:
        total = docs.totals_of(i)["total"]
        paid = min(_paid(links[i.id], as_of), total)
        if total - paid <= 0:
            continue
        days = _days_over(i, as_of)
        rows.append({"invoice": i, "number": docs.display_number(i), "customer": names.get(i.customer_entity_id, ""),
                     "customer_id": i.customer_entity_id, "invoice_date": i.invoice_date, "due_date": i.due_date,
                     "days": days, "total": total, "paid": paid, "open": total - paid, "bucket": _bucket(days),
                     "write_off_pending": i.write_off_status == "PENDING"})
    return rows


# ------------------------------------------------------------------ the reports
def _period(date_from, date_to) -> tuple[dt.date, dt.date]:
    if date_from is None or date_to is None:
        raise validation("Choose the period (from and to).", "date_from")
    if date_from > date_to:
        raise validation("The period's start is after its end.", "date_from")
    return date_from, date_to


def open_invoices(db: Session, ctx, as_of: dt.date | None = None, customer_id: int | None = None) -> dict:
    as_of = as_of or today()
    rows = _open_rows(db, ctx.workspace_id, as_of, customer_id)
    rows.sort(key=lambda r: (r["due_date"], r["number"]))
    cols = [("number", "Invoice", "text"), ("customer", "Customer", "text"), ("invoice_date", "Date", "date"),
            ("due_date", "Due", "date"), ("days", "Days overdue", "int"), ("total", "Total", "money"),
            ("paid", "Paid", "money"), ("open", "Open balance", "money"), ("note", "Note", "text")]
    for r in rows:
        r["note"] = "Write-off pending" if r["write_off_pending"] else ""
    return {"id": "inv-open", "title": "Open invoices", "subtitle": f"As of {as_of.isoformat()}",
            "params": {"as_of": as_of.isoformat()},
            "sections": [{"heading": None, "columns": cols, "rows": rows,
                          "totals": {"number": f"{len(rows)} invoices", **_sum(rows, "total", "paid", "open")}}]}


def aging(db: Session, ctx, as_of: dt.date | None = None) -> dict:
    as_of = as_of or today()
    per: dict[int, dict] = {}
    for r in _open_rows(db, ctx.workspace_id, as_of, None):
        c = per.setdefault(r["customer_id"], {"customer": r["customer"], "count": 0, "total": 0,
                                              **{k: 0 for k, _l in BUCKETS}})
        c[r["bucket"]] += r["open"]
        c["total"] += r["open"]
        c["count"] += 1
    rows = sorted(per.values(), key=lambda c: c["customer"].lower())
    cols = [("customer", "Customer", "text"), ("count", "Invoices", "int")] + [(k, l, "money") for k, l in BUCKETS] + \
        [("total", "Total open", "money")]
    return {"id": "inv-aging", "title": "Aging", "subtitle": f"As of {as_of.isoformat()} (days past the due date)",
            "params": {"as_of": as_of.isoformat()},
            "sections": [{"heading": None, "columns": cols, "rows": rows,
                          "totals": {"customer": "Total", **_sum(rows, "count", "total", *[k for k, _l in BUCKETS])}}]}


def statement(db: Session, ctx, customer_id: int | None, date_from: dt.date | None, date_to: dt.date | None) -> dict:
    e = db.get(Entity, customer_id) if isinstance(customer_id, int) else None
    if e is None or e.workspace_id != ctx.workspace_id:
        raise not_found("Customer")
    date_from, date_to = _period(date_from, date_to)
    ws = ctx.workspace_id
    invs = _invoices(db, ws, LIVE, date_to=date_to, customer_id=e.id)
    links = _links(db, [i.id for i in invs])
    activity = []
    for i in invs:
        total = docs.totals_of(i)["total"]
        num = docs.display_number(i)
        if date_from <= i.invoice_date <= date_to:
            activity.append({"date": i.invoice_date, "what": f"Invoice {num}", "charge": total, "credit": None, "_k": (i.invoice_date, 0, i.id)})
        for kind, t, amount, lid in _by_txn(links[i.id]):
            if not date_from <= t.transaction_date <= date_to:
                continue
            if kind == "REFUND":
                activity.append({"date": t.transaction_date, "what": f"Refund — {num}", "charge": amount, "credit": None,
                                 "_k": (t.transaction_date, 2, lid)})
            else:
                activity.append({"date": t.transaction_date, "what": f"Payment — {num}" + (" (overpayment)" if kind == "OVERPAYMENT" else ""),
                                 "charge": None, "credit": amount, "_k": (t.transaction_date, 1, lid)})
        if i.status == "WRITTEN_OFF" and i.write_off_decided_at and date_from <= i.write_off_decided_at.date() <= date_to:
            activity.append({"date": i.write_off_decided_at.date(), "what": f"Written off — {num}", "charge": None,
                             "credit": max(total - _paid(links[i.id]), 0), "_k": (i.write_off_decided_at.date(), 3, i.id)})
    activity.sort(key=lambda r: r["_k"])
    open_rows = _open_rows(db, ws, date_to, e.id)
    acols = [("date", "Date", "date"), ("what", "Activity", "text"), ("charge", "Charges", "money"), ("credit", "Payments and credits", "money")]
    ocols = [("number", "Invoice", "text"), ("invoice_date", "Date", "date"), ("due_date", "Due", "date"),
             ("days", "Days overdue", "int"), ("total", "Total", "money"), ("paid", "Paid", "money"), ("open", "Open balance", "money")]
    return {"id": "inv-statement", "title": f"Statement — {e.display_name}",
            "subtitle": f"{date_from.isoformat()} to {date_to.isoformat()}", "customer": e.display_name,
            "params": {"customer_entity_id": e.id, "date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
            "sections": [
                {"heading": "Activity in the period", "columns": acols, "rows": activity,
                 "totals": {"what": "Total", **_sum(activity, "charge", "credit")}},
                {"heading": f"Open invoices as of {date_to.isoformat()}", "columns": ocols, "rows": open_rows,
                 "totals": {"number": "Amount due", **_sum(open_rows, "open")}},
            ]}


def sales_tax(db: Session, ctx, date_from: dt.date | None, date_to: dt.date | None) -> dict:
    """Per tax rate: taxable sales and tax charged on invoices dated in the period, and the tax collected - the tax
    part of each payment dated in the period, apportioned exactly as Record payment splits it."""
    date_from, date_to = _period(date_from, date_to)
    invs = [i for i in _invoices(db, ctx.workspace_id, LIVE) if i.tax_rate_milli_pct]
    links = _links(db, [i.id for i in invs])
    per: dict[tuple, dict] = {}
    for i in invs:
        t = docs.totals_of(i)
        key = (i.tax_name or "Sales tax", i.tax_rate_milli_pct)
        r = per.setdefault(key, {"rate": f"{i.tax_name or 'Sales tax'} ({docs.cat.rate_text(i.tax_rate_milli_pct)} %)",
                                 "invoices": 0, "taxable": 0, "charged": 0, "collected": 0})
        if date_from <= i.invoice_date <= date_to:
            r["invoices"] += 1
            r["taxable"] += t["taxable_base"]
            r["charged"] += t["tax"]
        cum = 0
        for link, a, tx in links[i.id]:
            if link.kind != "PAYMENT":
                continue
            _p0, tax0 = pay.apportion(i, cum)
            cum += a.amount_cents
            _p1, tax1 = pay.apportion(i, cum)
            if date_from <= tx.transaction_date <= date_to:
                r["collected"] += tax1 - tax0
    rows = [r for _k, r in sorted(per.items()) if r["invoices"] or r["collected"]]
    cols = [("rate", "Tax rate", "text"), ("invoices", "Invoices", "int"), ("taxable", "Taxable sales", "money"),
            ("charged", "Tax charged", "money"), ("collected", "Tax collected", "money")]
    return {"id": "inv-sales-tax", "title": "Sales tax collected", "subtitle": f"{date_from.isoformat()} to {date_to.isoformat()}",
            "params": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
            "note": "Charged: invoices dated in the period. Collected: the tax part of payments received in the period.",
            "sections": [{"heading": None, "columns": cols, "rows": rows,
                          "totals": {"rate": "Total", **_sum(rows, "invoices", "taxable", "charged", "collected")}}]}


def register(db: Session, ctx, date_from: dt.date | None, date_to: dt.date | None, status: str | None = None) -> dict:
    date_from, date_to = _period(date_from, date_to)
    if status and status not in docs.STATUS_LABEL:
        raise validation("Unknown status.", "status")
    invs = _invoices(db, ctx.workspace_id, (status,) if status else None, date_from, date_to)
    links = _links(db, [i.id for i in invs])
    names = _names(db, [i.customer_entity_id for i in invs])
    revs: dict[int, int] = {}
    for r in db.scalars(select(InvoiceRevision).where(InvoiceRevision.invoice_id.in_([i.id for i in invs] or [0]))):
        revs[r.invoice_id] = revs.get(r.invoice_id, 0) + 1
    rows = []
    for i in invs:
        total = docs.totals_of(i)["total"]
        paid = min(_paid(links[i.id]), total)
        st = docs.STATUS_LABEL[i.status]
        if i.status == "WRITTEN_OFF" and i.write_off_self_approved:
            st += " (self-approved)"
        elif i.write_off_status == "PENDING":
            st += ", write-off pending"
        live = i.status not in ("DRAFT", "VOID")
        rows.append({"number": docs.display_number(i), "invoice_date": i.invoice_date, "due_date": i.due_date,
                     "customer": names.get(i.customer_entity_id, ""), "status": st, "total": total,
                     "paid": paid if live else 0, "open": total - paid if i.status in docs.OPEN else 0,
                     "revisions": i.revision, "sent_versions": revs.get(i.id, 0)})
    cols = [("number", "Invoice", "text"), ("invoice_date", "Date", "date"), ("due_date", "Due", "date"),
            ("customer", "Customer", "text"), ("status", "Status", "text"), ("total", "Total", "money"),
            ("paid", "Paid", "money"), ("open", "Open balance", "money"), ("revisions", "Revisions", "int")]
    return {"id": "inv-register", "title": "Invoice register", "subtitle": f"{date_from.isoformat()} to {date_to.isoformat()}"
            + (f" · {docs.STATUS_LABEL[status]}" if status else ""),
            "params": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "status": status or ""},
            "sections": [{"heading": None, "columns": cols, "rows": rows,
                          "totals": {"number": f"{len(rows)} invoices", **_sum(rows, "total", "paid", "open")}}]}


def sales(db: Session, ctx, date_from: dt.date | None, date_to: dt.date | None, by: str = "product") -> dict:
    """Invoice lines of issued invoices (not drafts or voids) dated in the period, by product, category or budget.
    Amount = after line and invoice discounts, before tax - the lines add up to the invoices' net totals."""
    date_from, date_to = _period(date_from, date_to)
    if by not in ("product", "category", "budget"):
        raise validation("Group by product, category or budget.", "by")
    invs = _invoices(db, ctx.workspace_id, LIVE, date_from, date_to)
    prods = {p.id: p for p in db.scalars(select(InvoiceProduct).where(InvoiceProduct.workspace_id == ctx.workspace_id))}
    cats = {c.id: c.name for c in db.scalars(select(InvoiceProductCategory).where(InvoiceProductCategory.workspace_id == ctx.workspace_id))}
    budgets = _budget_names(db, [ln.budget_id for i in invs for ln in i.lines])
    per: dict = {}
    for i in invs:
        for r in docs.totals_of(i)["rows"]:
            ln = r["line"]
            p = prods.get(ln.product_id)
            if by == "product":
                key = ln.product_id
                label = (f"{p.code} " if p and p.code else "") + (p.name if p else ln.description[:80])
            elif by == "category":
                key = p.category_id if p else None
                label = cats.get(key, "(no category)")
            else:
                key = ln.budget_id
                label = budgets.get(ln.budget_id, "(no budget)")
            x = per.setdefault(key, {"label": label, "quantity": 0, "gross": 0, "discounts": 0, "amount": 0})
            x["quantity"] += ln.quantity_milli
            x["gross"] += r["gross"]
            x["discounts"] += r["line_discount"] + r["share"]
            x["amount"] += r["final"]
    rows = sorted(per.values(), key=lambda x: x["label"].lower())
    for x in rows:
        x["qty"] = docs.qty_text(x["quantity"])
    head = {"product": "Product", "category": "Category", "budget": "Income budget"}[by]
    cols = [("label", head, "text")] + ([("qty", "Quantity", "num")] if by == "product" else []) + \
        [("gross", "Gross", "money"), ("discounts", "Discounts", "money"), ("amount", "Amount (before tax)", "money")]
    return {"id": "inv-sales", "title": f"Sales by {head.lower()}", "subtitle": f"{date_from.isoformat()} to {date_to.isoformat()}",
            "params": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "by": by},
            "sections": [{"heading": None, "columns": cols, "rows": rows,
                          "totals": {"label": "Total", **_sum(rows, "gross", "discounts", "amount")}}]}


def activity(db: Session, ctx, date_from: dt.date | None, date_to: dt.date | None) -> dict:
    """Payments and refunds by register date, write-offs by decision date, discounts on invoices dated in the period."""
    date_from, date_to = _period(date_from, date_to)
    invs = _invoices(db, ctx.workspace_id, LIVE)
    links = _links(db, [i.id for i in invs])
    names = _names(db, [i.customer_entity_id for i in invs])
    rows = []
    kind_label = {"PAYMENT": "Payment", "OVERPAYMENT": "Overpayment", "REFUND": "Refund"}
    for i in invs:
        num = docs.display_number(i)
        cust = names.get(i.customer_entity_id, "")
        for kind, t, amount, _lid in _by_txn(links[i.id]):
            if date_from <= t.transaction_date <= date_to:
                rows.append({"type": kind_label[kind], "date": t.transaction_date, "number": num, "customer": cust,
                             "amount": -amount if kind == "REFUND" else amount, "detail": f"Register transaction #{t.id}"})
        if i.status == "WRITTEN_OFF" and i.write_off_decided_at and date_from <= i.write_off_decided_at.date() <= date_to:
            amount = max(docs.totals_of(i)["total"] - _paid(links[i.id]), 0)
            rows.append({"type": "Write-off" + (" (self-approved)" if i.write_off_self_approved else ""),
                         "date": i.write_off_decided_at.date(), "number": num, "customer": cust, "amount": amount,
                         "detail": i.write_off_reason or ""})
        if date_from <= i.invoice_date <= date_to:
            t = docs.totals_of(i)
            for r in t["rows"]:
                if r["line_discount"]:
                    rows.append({"type": "Discount (line)", "date": i.invoice_date, "number": num, "customer": cust,
                                 "amount": r["line_discount"], "detail": f"{r['line'].description[:60]}: {r['line'].discount_reason or ''}"})
            if t["invoice_discount"]:
                rows.append({"type": "Discount (invoice)", "date": i.invoice_date, "number": num, "customer": cust,
                             "amount": t["invoice_discount"], "detail": i.discount_reason or ""})
    rows.sort(key=lambda r: (r["date"], r["number"], r["type"]))
    summary = {}
    for r in rows:
        k = r["type"].split(" (")[0] if r["type"].startswith("Discount") else r["type"].replace(" (self-approved)", "")
        summary[k] = summary.get(k, 0) + r["amount"]
    cols = [("date", "Date", "date"), ("type", "Type", "text"), ("number", "Invoice", "text"), ("customer", "Customer", "text"),
            ("amount", "Amount", "money"), ("detail", "Detail", "text")]
    srows = [{"type": k, "amount": v} for k, v in summary.items()]
    return {"id": "inv-activity", "title": "Payments, write-offs, discounts and refunds",
            "subtitle": f"{date_from.isoformat()} to {date_to.isoformat()}",
            "params": {"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
            "sections": [{"heading": "Summary", "columns": [("type", "Type", "text"), ("amount", "Amount", "money")],
                          "rows": srows, "totals": None, "csv": False},
                         {"heading": "Detail", "columns": cols, "rows": rows, "totals": None}]}


def _sum(rows: list[dict], *keys) -> dict:
    return {k: sum(r.get(k) or 0 for r in rows) for k in keys}


def run(db: Session, ctx, report_id: str, p: dict) -> dict:
    inv.require_module(db, ctx)
    ctx.require("invoice.view")
    if report_id == "inv-open":
        return open_invoices(db, ctx, p.get("as_of"), p.get("customer_entity_id"))
    if report_id == "inv-aging":
        return aging(db, ctx, p.get("as_of"))
    if report_id == "inv-statement":
        return statement(db, ctx, p.get("customer_entity_id"), p.get("date_from"), p.get("date_to"))
    if report_id == "inv-sales-tax":
        return sales_tax(db, ctx, p.get("date_from"), p.get("date_to"))
    if report_id == "inv-register":
        return register(db, ctx, p.get("date_from"), p.get("date_to"), p.get("status"))
    if report_id == "inv-sales":
        return sales(db, ctx, p.get("date_from"), p.get("date_to"), p.get("by") or "product")
    if report_id == "inv-activity":
        return activity(db, ctx, p.get("date_from"), p.get("date_to"))
    raise not_found("Report")


# ------------------------------------------------------------------ output
def _cell(v, kind: str) -> str:
    if v is None or v == "":
        return ""
    if kind == "money":
        return fmt(v)
    if kind == "date":
        return v.isoformat() if hasattr(v, "isoformat") else str(v)
    return str(v)


def as_json(rep: dict) -> dict:
    return {**{k: v for k, v in rep.items() if k != "sections"},
            "sections": [{"heading": s["heading"],
                          "columns": [{"key": k, "label": label, "kind": kind} for k, label, kind in s["columns"]],
                          "rows": [{k: _cell(r.get(k), kind) for k, _l, kind in s["columns"]} for r in s["rows"]],
                          "totals": ({k: _cell(s["totals"].get(k), kind) for k, _l, kind in s["columns"] if k in s["totals"]}
                                     if s.get("totals") else None)} for s in rep["sections"]]}


def as_csv(rep: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    secs = [s for s in rep["sections"] if s.get("csv", True)]
    for n, s in enumerate(secs):
        if len(secs) > 1:
            if n:
                w.writerow([])
            w.writerow([s["heading"] or ""])
        w.writerow([label for _k, label, _t in s["columns"]])
        for r in s["rows"]:
            w.writerow([_csv_safe(_cell(r.get(k), kind)) for k, _l, kind in s["columns"]])
        if s.get("totals"):
            w.writerow([_csv_safe(_cell(s["totals"].get(k), kind)) for k, _l, kind in s["columns"]])
    return out.getvalue()


def _csv_safe(v: str) -> str:
    """No formula injection in a spreadsheet (BR-108 / SR): text starting with = + - @ is quoted with an apostrophe,
    except plain negative amounts."""
    if v and v[0] in "=+-@\t\r" and not _is_number(v):
        return "'" + v
    return v


def _is_number(v: str) -> bool:
    try:
        float(v.replace(",", ""))
        return True
    except ValueError:
        return False


def as_pdf(db: Session, ctx, rep: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    from . import organization as org_svc
    ws = db.get(Workspace, ctx.workspace_id)
    org = org_svc.get(db, ctx.workspace_id)
    org_name = (org.organization_name if org else None) or (ws.name if ws else "")
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["Normal"], fontSize=8.5, leading=10.5)
    head = ParagraphStyle("h", parent=body, fontName="Helvetica-Bold")
    num = ParagraphStyle("n", parent=body, alignment=2)
    numb = ParagraphStyle("nb", parent=num, fontName="Helvetica-Bold")
    buf = io.BytesIO()
    printed = today().isoformat()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(0.5 * inch, 0.35 * inch, f"{org_name} · {rep['title']} · printed {printed}")
        canvas.drawRightString(landscape(letter)[0] - 0.5 * inch, 0.35 * inch, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=landscape(letter), leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.6 * inch, title=rep["title"], author=org_name)
    width = landscape(letter)[0] - inch
    story = [Paragraph(escape(org_name), ss["Heading3"]), Paragraph(escape(rep["title"]), ss["Title"]),
             Paragraph(escape(rep["subtitle"]), ss["Normal"])]
    if rep.get("note"):
        story.append(Paragraph(escape(rep["note"]), body))
    story.append(Spacer(1, 10))
    for s in rep["sections"]:
        if s.get("heading"):
            story += [Paragraph(escape(s["heading"]), ss["Heading4"])]
        cols = s["columns"]
        right = {k for k, _l, kind in cols if kind in ("money", "int", "num")}
        data = [[Paragraph(escape(label), numb if k in right else head) for k, label, _t in cols]]
        for r in s["rows"]:
            data.append([Paragraph(escape(_cell(r.get(k), kind)), num if k in right else body) for k, _l, kind in cols])
        if not s["rows"]:
            data.append([Paragraph("Nothing in this period.", body)] + [""] * (len(cols) - 1))
        if s.get("totals"):
            data.append([Paragraph(escape(_cell(s["totals"].get(k), kind)), numb if k in right else head) for k, _l, kind in cols])
        text_cols = [k for k, _l, kind in cols if kind == "text"]
        fixed = {"money": 0.95, "int": 0.7, "num": 0.7, "date": 0.8}
        fixed_w = sum(fixed.get(kind, 0) * inch for _k, _l, kind in cols if kind != "text")
        tw = max((width - fixed_w) / max(len(text_cols), 1), 0.8 * inch)
        widths = [tw if kind == "text" else fixed[kind] * inch for _k, _l, kind in cols]
        t = Table(data, colWidths=widths, repeatRows=1)
        style = [("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")])]
        if s.get("totals"):
            style.append(("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black))
        if not s["rows"]:
            style.append(("SPAN", (0, 1), (-1, 1)))
        t.setStyle(TableStyle(style))
        story += [t, Spacer(1, 12)]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def filename(rep: dict, ext: str) -> str:
    stamp = rep["params"].get("as_of") or rep["params"].get("date_to") or today().isoformat()
    return f"{rep['id']}-{stamp}.{ext}"


# ------------------------------------------------------------------ overdue (dashboard card, Invoice Manager reminder)
def overdue(db: Session, ctx) -> dict:
    inv.require_module(db, ctx)
    ctx.require("invoice.view")
    d = today()
    s = docs.settings_of(db, ctx.workspace_id)
    n = s.overdue_reminder_days or 0
    open_rows = _open_rows(db, ctx.workspace_id, d, None)
    rows = [r for r in open_rows if r["days"] > 0]
    rows.sort(key=lambda r: (-r["days"], r["number"]))
    # the Invoice Manager's reminder: from the due date + N days on, until it is paid, written off or voided
    remind = sorted([r for r in open_rows if (d - r["due_date"]).days >= n], key=lambda r: (r["due_date"], r["number"])) \
        if ctx.has("invoice.manage") else []
    item = lambda r: {"id": r["invoice"].id, "number": r["number"], "customer": r["customer"],  # noqa: E731
                      "due_date": r["due_date"].isoformat(), "days": r["days"], "open": fmt(r["open"])}
    return {"count": len(rows), "open": fmt(sum(r["open"] for r in rows)), "items": [item(r) for r in rows[:10]],
            "reminder_days": n, "reminders": [item(r) for r in remind]}
