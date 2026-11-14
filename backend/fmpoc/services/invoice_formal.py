"""2.4.0 (#513): the formal invoice reports - *Sales by product & category* and *Sales overview* - for publication
(board, members), each as a branded PDF and presentation (`invoice_formal_output.py`).

Decisions (Kyle, 2026-11-03), recorded in docs/implementation-notes.md as BR-INV-PUB-001..003 / AC-INV-PUB-001..006:

* Period: a Fiscal Year quarter or the whole year (the Quarterly / Annual rules - BR-110: as of the end of the
  period, *Preliminary* while it is in progress) or a custom From / Through range. The same period of the previous
  Fiscal Year is shown beside it when PennyWarden has that year; a custom range has no comparison.
* Money: invoices issued (not drafts or voids) dated in the period. Sales are after discounts and before tax, exactly
  as the basic *Sales by product / category* report (so the totals match it to the cent); "collected" is the part of
  those sales paid by the period's end, split over the lines as Record payment splits a payment
  (`invoice_payments.apportion_rates`). The overview's invoiced and open amounts include tax.
* Customer names can be replaced by *Customer 1, 2...* for a report that goes outside the organization.
* Viewers: `invoice.view` with the module on (never the Administrator, BR-003). Untrusted names are escaped by the
  output writers.

"Today" is passed in by the caller (computed when the request runs, never at import).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import validation
from ..models import FiscalYear, InvoiceProduct, InvoiceProductCategory
from . import invoice_docs as docs
from . import invoice_payments as pay
from . import invoice_reports as ir
from . import invoices as inv
from . import period_report as prep
from .common import fy_brief

REPORTS = {"inv-sales-formal": "Sales by product & category", "inv-overview": "Sales overview"}
MAX_COMMENTARY = 2000
TOP = 5
STATUS_ORDER = ("SENT", "PARTLY_PAID", "PAID", "WRITTEN_OFF")


# ------------------------------------------------------------------ the period (BR-INV-PUB-001)
def _us(d: dt.date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def resolve_period(db: Session, ctx, fiscal_year_id: int | None, period: str | None, date_from: dt.date | None,
                   date_to: dt.date | None, today: dt.date) -> dict:
    """A Fiscal Year quarter / Annual (with the same period of the year before), or a custom range (no comparison)."""
    if fiscal_year_id is not None:
        fy = db.get(FiscalYear, fiscal_year_id)
        if fy is None or fy.workspace_id != ctx.workspace_id:
            raise validation("Choose a Fiscal Year.", "fiscal_year_id")
        p = prep.resolve(fy, period or "", today)
        prior_fy = prep.previous_fy(db, fy)
        prior = prep._prior_dates(prior_fy, p) if prior_fy is not None else None
        label = f"{'Annual' if p['annual'] else p['period']} {fy.display_name}"
        out = {"kind": "FY", "fiscal_year": fy_brief(fy), "period": p["period"], "annual": p["annual"],
               "start": p["start"], "end": p["end"], "cutoff": p["cutoff"], "preliminary": p["preliminary"],
               "label": label}
        if prior is not None:
            pend = prior["end"]
            if p["cutoff"] < p["end"]:          # in progress: compare the same stretch of last year's period
                pend = min(prior["end"], prior["start"] + (p["cutoff"] - p["start"]))
            out["prior"] = {"start": prior["start"], "end": pend,
                            "label": f"{'Annual' if p['annual'] else p['period']} {prior_fy.display_name}"
                            + (f" through {_us(pend)}" if pend < prior["end"] else "")}
        return out
    if date_from is None or date_to is None:
        raise validation("Choose a Fiscal Year and period, or a From and Through date.", "date_from")
    if date_from > date_to:
        raise validation("The period's start is after its end.", "date_from")
    if date_from > today:
        raise validation("The period hasn't started yet.", "date_from")
    cutoff = min(date_to, today)
    return {"kind": "CUSTOM", "fiscal_year": None, "period": "CUSTOM", "annual": False, "start": date_from,
            "end": date_to, "cutoff": cutoff, "preliminary": today < date_to,
            "label": f"{_us(date_from)} – {_us(date_to)}"}


def _commentary(text: str | None) -> str | None:
    text = (text or "").strip() or None
    if text and len(text) > MAX_COMMENTARY:
        raise validation(f"The commentary can be at most {MAX_COMMENTARY} characters.", "commentary")
    return text


def _pct(part: int, whole: int) -> float | None:
    return None if not whole else round(part * 100 / whole, 1)


def _change(cur: int, prev: int | None) -> float | None:
    return None if not prev else round((cur - prev) * 100 / abs(prev), 1)


# ------------------------------------------------------------------ sales lines, with what has been collected
def _sales_lines(db: Session, ws_id: int, start: dt.date, end: dt.date) -> list[dict]:
    """Every line of the issued invoices dated in the period: product, category, budget, quantity, gross, discounts,
    the final amount (after discounts, before tax) and how much of it was paid by `end`."""
    invs = ir._invoices(db, ws_id, ir.LIVE, start, end)
    links = ir._links(db, [i.id for i in invs])
    out = []
    for i in invs:
        paid = min(ir._paid(links[i.id], end), docs.totals_of(i)["total"])
        parts, _tax = pay.apportion_rates(i, paid)
        for r, got in zip(docs.totals_of(i)["rows"], parts):
            ln = r["line"]
            out.append({"invoice_id": i.id, "customer_id": i.customer_entity_id, "product_id": ln.product_id,
                        "budget_id": ln.budget_id, "description": ln.description, "quantity": ln.quantity_milli,
                        "gross": r["gross"], "discounts": r["line_discount"] + r["share"], "amount": r["final"],
                        "collected": got, "date": i.invoice_date})
    return out


def _group(lines: list[dict], key, label) -> dict:
    per: dict = {}
    for x in lines:
        k = key(x)
        g = per.setdefault(k, {"key": k, "label": label(x), "quantity": 0, "gross": 0, "discounts": 0, "amount": 0,
                               "collected": 0, "lines": 0})
        for f in ("quantity", "gross", "discounts", "amount", "collected"):
            g[f] += x[f]
        g["lines"] += 1
    return per


def _catalog(db: Session, ws_id: int) -> tuple[dict, dict]:
    prods = {p.id: p for p in db.scalars(select(InvoiceProduct).where(InvoiceProduct.workspace_id == ws_id))}
    cats = {c.id: c.name for c in db.scalars(select(InvoiceProductCategory).where(InvoiceProductCategory.workspace_id == ws_id))}
    return prods, cats


def _sales_figures(db: Session, ws_id: int, start: dt.date, end: dt.date) -> dict:
    lines = _sales_lines(db, ws_id, start, end)
    prods, cats = _catalog(db, ws_id)
    budgets = ir._budget_names(db, [x["budget_id"] for x in lines])

    def pname(x):
        p = prods.get(x["product_id"])
        return (f"{p.code} " if p and p.code else "") + (p.name if p else x["description"][:80])

    def cat_of(x):
        p = prods.get(x["product_id"])
        return p.category_id if p else None

    by_cat = _group(lines, cat_of, lambda x: cats.get(cat_of(x), "(no category)"))
    by_prod = _group(lines, lambda x: x["product_id"] or f"d:{x['description'][:80]}", pname)
    for x in lines:                                   # each product sits under its category
        by_prod[x["product_id"] or f"d:{x['description'][:80]}"]["category"] = cat_of(x)
    by_budget = _group(lines, lambda x: x["budget_id"], lambda x: budgets.get(x["budget_id"], "(no budget)"))
    total = {f: sum(x[f] for x in lines) for f in ("gross", "discounts", "amount", "collected")}
    total["invoices"] = len({x["invoice_id"] for x in lines})
    return {"by_category": by_cat, "by_product": by_prod, "by_budget": by_budget, "total": total}


def _rows(cur: dict, prev: dict | None, total: int, sort_by="amount") -> list[dict]:
    rows = []
    for k, g in cur.items():
        p = prev.get(k) if prev is not None else None
        rows.append({**g, "share": _pct(g["amount"], total), "collected_pct": _pct(g["collected"], g["amount"]),
                     "qty": docs.qty_text(g["quantity"]),
                     "prior": None if prev is None else (p["amount"] if p else 0),
                     "change": None if prev is None else _change(g["amount"], p["amount"] if p else 0)})
    if prev is not None:                              # sold last year, not this period: listed with 0
        for k, p in prev.items():
            if k not in cur:
                rows.append({"key": k, "label": p["label"], "quantity": 0, "qty": "0", "gross": 0, "discounts": 0,
                             "amount": 0, "collected": 0, "lines": 0, "share": 0.0 if total else None,
                             "collected_pct": None, "prior": p["amount"], "change": -100.0 if p["amount"] else None,
                             **({"category": p.get("category")} if "category" in p else {})})
    rows.sort(key=lambda r: (-r[sort_by], r["label"].lower()))
    return rows


def sales_report(db: Session, ctx, period: dict, today: dt.date, commentary: str | None = None) -> dict:
    """Sales by product & category: one report with every grouping (category; product within its category; Income
    budget), invoiced with collected beside it, and last year's figures."""
    inv.require_module(db, ctx)
    ctx.require("invoice.view")
    ws = ctx.workspace_id
    cur = _sales_figures(db, ws, period["start"], period["cutoff"])
    prior = period.get("prior")
    prev = _sales_figures(db, ws, prior["start"], prior["end"]) if prior else None
    t = cur["total"]
    cats = _rows(cur["by_category"], prev["by_category"] if prev else None, t["amount"])
    prods = _rows(cur["by_product"], prev["by_product"] if prev else None, t["amount"])
    budgets = _rows(cur["by_budget"], prev["by_budget"] if prev else None, t["amount"])
    # products under their category, in the categories' order
    order = {c["key"]: n for n, c in enumerate(cats)}
    for p in prods:
        p.setdefault("category", None)
    grouped = [{"category": c["label"], "key": c["key"], "amount": c["amount"],
                "products": [p for p in prods if p.get("category") == c["key"]]} for c in cats]
    grouped = [g for g in grouped if g["products"]]
    grouped.sort(key=lambda g: order.get(g["key"], 999))
    pt = prev["total"] if prev else None
    live = [r for r in cats if r["amount"]]
    top_cat = live[0] if live else None
    top_prod = next((p for p in prods if p["amount"]), None)
    rep = _envelope("inv-sales-formal", period, today, _commentary(commentary))
    rep.update({
        "total": {**t, "collected_pct": _pct(t["collected"], t["amount"])},
        "prior_total": pt,
        "change": None if pt is None else _change(t["amount"], pt["amount"]),
        "top_category": top_cat and {"label": top_cat["label"], "amount": top_cat["amount"], "share": top_cat["share"]},
        "top_product": top_prod and {"label": top_prod["label"], "amount": top_prod["amount"], "share": top_prod["share"]},
        "categories": cats, "products": grouped, "budgets": budgets,
        "products_count": sum(1 for p in prods if p["amount"]),
    })
    rep["key_points"] = _sales_points(rep)
    return rep


def _envelope(rid: str, period: dict, today: dt.date, commentary: str | None) -> dict:
    prior = period.get("prior")
    return {"id": rid, "title": REPORTS[rid], "period_label": period["label"], "kind": period["kind"],
            "fiscal_year": period["fiscal_year"], "period": period["period"], "annual": period["annual"],
            "start_date": period["start"].isoformat(), "end_date": period["end"].isoformat(),
            "cutoff": period["cutoff"].isoformat(), "preliminary": period["preliminary"],
            "generated_on": today.isoformat(), "commentary": commentary,
            "prior_label": prior["label"] if prior else None,
            "prior_start": prior["start"].isoformat() if prior else None,
            "prior_end": prior["end"].isoformat() if prior else None}


def _m(c: int) -> str:
    return ("-" if c < 0 else "") + f"${abs(c) // 100:,}.{abs(c) % 100:02d}"


def _sales_points(rep: dict) -> list[str]:
    t = rep["total"]
    if not t["amount"]:
        return ["No sales were invoiced in this period."]
    pts = [f"{_m(t['amount'])} invoiced on {t['invoices']} invoice{'s' if t['invoices'] != 1 else ''} (after discounts, "
           f"before tax); {_m(t['collected'])} of it collected so far ({t['collected_pct']:.1f}%)."]
    if rep["change"] is not None:
        pts.append(f"{'Up' if rep['change'] >= 0 else 'Down'} {abs(rep['change']):.1f}% on {rep['prior_label']} "
                   f"({_m(rep['prior_total']['amount'])}).")
    if rep["top_category"] and len([c for c in rep["categories"] if c["amount"]]) > 1:
        c = rep["top_category"]
        pts.append(f"{c['label']} was the largest category: {_m(c['amount'])}, {c['share']:.1f}% of sales.")
    if rep["top_product"]:
        p = rep["top_product"]
        pts.append(f"Top product: {p['label']}, {_m(p['amount'])} ({p['share']:.1f}%).")
    if t["discounts"]:
        pts.append(f"Discounts given: {_m(t['discounts'])} ({_pct(t['discounts'], t['gross']):.1f}% of the gross).")
    grew = [c for c in rep["categories"] if c["change"] is not None and c["prior"] and c["amount"] and c["change"] > 0]
    if grew:
        g = max(grew, key=lambda c: c["change"])
        pts.append(f"Fastest growing category: {g['label']}, up {g['change']:.1f}%.")
    return pts


# ------------------------------------------------------------------ the overview
def _overview_figures(db: Session, ctx, start: dt.date, end: dt.date) -> dict:
    ws = ctx.workspace_id
    invs = ir._invoices(db, ws, ir.LIVE, start, end)
    links_all = ir._links(db, [i.id for i in ir._invoices(db, ws, ir.LIVE)])
    invoiced = sum(docs.totals_of(i)["total"] for i in invs)
    tax = sum(docs.totals_of(i)["tax"] for i in invs)
    status = {s: 0 for s in STATUS_ORDER}
    for i in invs:
        status[i.status] = status.get(i.status, 0) + 1
    # money in the period (any invoice): payments and overpayments in, refunds out, by register date
    collected = refunds = 0
    months: dict[tuple, dict] = {}
    for d in _month_starts(start, end):
        months[(d.year, d.month)] = {"label": f"{d:%b} {d.year}", "invoiced": 0, "collected": 0}
    for i in invs:
        months[(i.invoice_date.year, i.invoice_date.month)]["invoiced"] += docs.totals_of(i)["total"]
    for _iid, ls in links_all.items():
        for kind, t, amount, _lid in ir._by_txn(ls):
            if not start <= t.transaction_date <= end:
                continue
            if kind == "REFUND":
                refunds += amount
                months[(t.transaction_date.year, t.transaction_date.month)]["collected"] -= amount
            else:
                collected += amount
                months[(t.transaction_date.year, t.transaction_date.month)]["collected"] += amount
    open_rows = ir._open_rows(db, ws, end, None)
    aging = {k: 0 for k, _l in ir.BUCKETS}
    for r in open_rows:
        aging[r["bucket"]] += r["open"]
    act = ir.activity(db, ctx, start, end)
    summary = {r["type"]: r["amount"] for r in act["sections"][0]["rows"]}
    discounts = summary.get("Discount", 0)
    write_offs = summary.get("Write-off", 0)
    # customers by amount invoiced (with what they paid of it by the end)
    per_cust: dict[int, dict] = {}
    for i in invs:
        c = per_cust.setdefault(i.customer_entity_id, {"customer_id": i.customer_entity_id, "invoiced": 0, "paid": 0,
                                                       "invoices": 0})
        tot = docs.totals_of(i)["total"]
        c["invoiced"] += tot
        c["paid"] += min(ir._paid(links_all.get(i.id, []), end), tot)
        c["invoices"] += 1
    sales = _sales_figures(db, ws, start, end)
    return {"invoiced": invoiced, "tax": tax, "net_sales": invoiced - tax, "invoices": len(invs), "status": status,
            "average": invoiced // len(invs) if invs else 0, "collected": collected, "refunds": refunds,
            "net_collected": collected - refunds, "open_end": sum(r["open"] for r in open_rows),
            "overdue_end": sum(v for k, v in aging.items() if k != "current"), "open_invoices": len(open_rows),
            "aging": aging, "months": list(months.values()), "discounts": discounts, "write_offs": write_offs,
            "customers": per_cust, "products": sales["by_product"], "sales_total": sales["total"],
            "tax_rows": ir.sales_tax(db, ctx, start, end)["sections"][0]["rows"]}


def _month_starts(start: dt.date, end: dt.date) -> list[dt.date]:
    out, d = [], start.replace(day=1)
    while d <= end:
        out.append(d)
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return out


def overview_report(db: Session, ctx, period: dict, today: dt.date, commentary: str | None = None,
                    show_names: bool = True) -> dict:
    """Sales overview: invoicing for the period in one place - invoiced, collected, open and overdue at the end,
    by month, aging, sales tax, top customers and products, discounts, write-offs and refunds; last year beside it."""
    inv.require_module(db, ctx)
    ctx.require("invoice.view")
    cur = _overview_figures(db, ctx, period["start"], period["cutoff"])
    prior = period.get("prior")
    prev = _overview_figures(db, ctx, prior["start"], prior["end"]) if prior else None
    names = ir._names(db, list(cur["customers"]))
    custs = sorted(cur["customers"].values(), key=lambda c: (-c["invoiced"], names.get(c["customer_id"], "").lower()))
    top_c = []
    for n, c in enumerate(custs[:TOP], 1):
        top_c.append({"name": names.get(c["customer_id"], "") if show_names else f"Customer {n}",
                      "invoiced": c["invoiced"], "paid": c["paid"], "invoices": c["invoices"],
                      "share": _pct(c["invoiced"], cur["invoiced"])})
    prods = sorted((p for p in cur["products"].values() if p["amount"]), key=lambda p: (-p["amount"], p["label"].lower()))
    top_p = [{"label": p["label"], "amount": p["amount"], "qty": docs.qty_text(p["quantity"]),
              "share": _pct(p["amount"], cur["sales_total"]["amount"])} for p in prods[:TOP]]

    def cmp(key):
        return None if prev is None else {"prior": prev[key], "change": _change(cur[key], prev[key])}
    rep = _envelope("inv-overview", period, today, _commentary(commentary))
    rep.update({
        "show_names": show_names,
        "figures": {k: cur[k] for k in ("invoiced", "tax", "net_sales", "invoices", "average", "collected", "refunds",
                                        "net_collected", "open_end", "overdue_end", "open_invoices", "discounts",
                                        "write_offs")},
        "compare": None if prev is None else {k: cmp(k) for k in ("invoiced", "net_sales", "invoices", "average",
                                                                  "net_collected", "open_end", "overdue_end",
                                                                  "discounts", "write_offs", "refunds")},
        "status": [{"status": s, "label": docs.STATUS_LABEL[s], "count": cur["status"].get(s, 0)} for s in STATUS_ORDER],
        "months": cur["months"],
        "aging": [{"key": k, "label": l, "amount": cur["aging"][k]} for k, l in ir.BUCKETS],
        "tax": [{"rate": r["rate"], "taxable": r["taxable"], "charged": r["charged"], "collected": r["collected"]}
                for r in cur["tax_rows"]],
        "top_customers": top_c, "customers_count": len(custs), "top_products": top_p,
    })
    rep["key_points"] = _overview_points(rep)
    return rep


def _overview_points(rep: dict) -> list[str]:
    f, c = rep["figures"], rep["compare"]
    if not f["invoices"] and not f["collected"] and not f["open_end"]:
        return ["No invoicing activity in this period."]
    pts = [f"{f['invoices']} invoice{'s' if f['invoices'] != 1 else ''} issued for {_m(f['invoiced'])} "
           f"(average {_m(f['average'])})."]
    if c and c["invoiced"]["change"] is not None:
        ch = c["invoiced"]["change"]
        pts.append(f"Invoicing {'up' if ch >= 0 else 'down'} {abs(ch):.1f}% on {rep['prior_label']} "
                   f"({_m(c['invoiced']['prior'])}).")
    pts.append(f"{_m(f['net_collected'])} collected in the period" + (f" after {_m(f['refunds'])} refunded" if f["refunds"] else "") + ".")
    if f["open_end"]:
        pts.append(f"{_m(f['open_end'])} still open on {_us(dt.date.fromisoformat(rep['cutoff']))} across "
                   f"{f['open_invoices']} invoice{'s' if f['open_invoices'] != 1 else ''}"
                   + (f"; {_m(f['overdue_end'])} of it overdue." if f["overdue_end"] else "; none overdue."))
    if rep["top_customers"] and rep["customers_count"] > 1:
        t = rep["top_customers"][0]
        pts.append(f"Largest customer: {t['name']}, {_m(t['invoiced'])} ({t['share']:.1f}% of invoicing).")
    if f["write_offs"]:
        pts.append(f"{_m(f['write_offs'])} written off as uncollectable.")
    return pts


def build(db: Session, ctx, report_id: str, q: dict, today: dt.date) -> dict:
    period = resolve_period(db, ctx, q.get("fiscal_year_id"), q.get("period"), q.get("date_from"), q.get("date_to"),
                            today)
    if report_id == "inv-sales-formal":
        return sales_report(db, ctx, period, today, q.get("commentary"))
    if report_id == "inv-overview":
        return overview_report(db, ctx, period, today, q.get("commentary"), q.get("show_names", True))
    raise validation("Unknown report.", "report")
