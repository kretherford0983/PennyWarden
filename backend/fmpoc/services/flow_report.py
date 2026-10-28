"""1.8.0 (#106): Financial Flow Report - the money that came in and went out of the selected register accounts in a
period, one section per account (and an overall summary for several), reviewed line by line before the PDF is made;
optionally followed by every account's Current balance on the Through Date and its change since a Compare Date.

Lines: ACTIVE transactions dated in the period (cleared or not), transfers between accounts left out. An expense is
one line per withdrawal (its full amount); income is one line per deposit allocation. Line keys: `t<transaction id>`
for a withdrawal, `a<allocation id>` for a deposit allocation."""
from __future__ import annotations

import datetime as dt
import io
import os
import tempfile
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import validation
from ..models import BankAccount, RegisterTransaction, Workspace, utcnow
from ..money import fmt
from . import bank_accounts as bank
from . import branding
from .common import get_scoped
from .reports import FRAME_W, P, PM, _AuditDoc, _Mark, _grid, _stamp_and_write, money

GREEN, RED = colors.HexColor("#1a7f37"), colors.HexColor("#c62828")
MINUS = "−"
SECTIONS = [("CHECKING", "Checking"), ("SAVINGS", "Savings"), ("INVESTMENTS", "Investments")]


def _us(d: dt.date) -> str:
    return d.strftime("%m/%d/%Y")


def signed(c: int) -> str:
    """+$1.00 / −$1.00 / $0.00 - the sign keeps the meaning on a black-and-white printout."""
    if c > 0:
        return "+" + money(c)
    if c < 0:
        return MINUS + money(-c)
    return money(0)


# --------------------------------------------------------------------------- parameters
def _params(db: Session, ctx, data) -> dict:
    today = dt.date.today()
    current = data.date_to is None
    date_to = data.date_to or today
    if data.date_from > date_to:
        raise validation("The From Date must be on or before the Through Date.", "date_from" if current else "date_to")
    ids: list[int] = []
    for i in data.bank_account_ids:
        if i not in ids:
            ids.append(i)
    accounts = [get_scoped(db, BankAccount, i, ctx, "Bank account") for i in ids]
    for a in accounts:
        if not a.register_enabled:
            raise validation(f"{a.account_name} has no register; choose register accounts.", "bank_account_ids")
    order = {a.id: n for n, a in enumerate(db.scalars(select(BankAccount).where(
        BankAccount.workspace_id == ctx.workspace_id).order_by(*bank.listing_order())))}
    accounts.sort(key=lambda a: order.get(a.id, 0))          # the order set on the Bank Accounts page (#74)
    compare = data.compare_date
    if compare is not None and not data.include_balances:
        raise validation("A Compare Date needs Include Bank Balances.", "compare_date")
    if compare is not None and compare >= date_to:
        raise validation("The Compare Date must be earlier than the Through Date.", "compare_date")
    return {"title": data.title, "date_from": data.date_from, "date_to": date_to, "current": current,
            "accounts": accounts, "include_balances": data.include_balances, "compare_date": compare,
            "notes": data.notes or None, "substitution_notes": bool(data.show_substitution_notes)}


def _period(p: dict) -> str:
    return f"{_us(p['date_from'])} – {'Current' if p['current'] else _us(p['date_to'])}"


# --------------------------------------------------------------------------- lines
def _describe(entity, *descriptions: str | None) -> str:
    parts = []
    for d in descriptions:
        if d and d.strip() and d.strip() not in parts:
            parts.append(d.strip())
    text = "; ".join(parts)
    name = entity.display_name if entity is not None else ""
    if name and text:
        return f"{name} — {text}"
    return name or text or "—"


def account_lines(db: Session, a: BankAccount, date_from: dt.date, date_to: dt.date) -> tuple[list[dict], list[dict]]:
    txns = db.scalars(select(RegisterTransaction).where(
        RegisterTransaction.bank_account_id == a.id, RegisterTransaction.status == "ACTIVE",
        RegisterTransaction.transfer_group.is_(None),
        RegisterTransaction.transaction_date >= date_from, RegisterTransaction.transaction_date <= date_to)
        .order_by(RegisterTransaction.transaction_date, RegisterTransaction.id))
    income, expense = [], []
    for t in txns:
        live = t.live_allocations
        if t.transaction_type == "WITHDRAWAL":
            ent = t.parent_entity or next((x.entity for x in live if x.entity is not None), None)
            expense.append({"key": f"t{t.id}", "transaction_id": t.id, "allocation_id": None,
                            "date": t.transaction_date, "amount": sum(x.amount_cents for x in live),
                            "description": _describe(ent, *[x.description for x in live])})
        else:
            for x in live:
                income.append({"key": f"a{x.id}", "transaction_id": t.id, "allocation_id": x.id,
                               "date": t.transaction_date, "amount": x.amount_cents,
                               "description": _describe(x.entity or t.parent_entity, x.description)})
    return income, expense


def _totals(sec: dict) -> dict:
    inc = sum(x["amount"] for x in sec["income"] if not x.get("excluded"))
    exp = sum(x["amount"] for x in sec["expense"] if not x.get("excluded"))
    return {"income_total": inc, "expense_total": exp, "difference": inc - exp}


# --------------------------------------------------------------------------- balances
def _started(db: Session, a: BankAccount, d: dt.date) -> bool:
    if a.account_opened_date is not None and d < a.account_opened_date:
        return False
    if not a.register_enabled:
        return bank.manual_as_of(db, a, d) is not None
    start = bank.register_start(a)
    return start is None or start <= d


def _open_on(db: Session, a: BankAccount, d: dt.date) -> bool:
    return (a.closed_date is None or a.closed_date > d) and _started(db, a, d)


def _section_of(account_type: str) -> str:
    return account_type if account_type in ("CHECKING", "SAVINGS") else "INVESTMENTS"


def substitution_text(s: dict) -> str:
    """The note for a substituted starting value (Kyle, 2026-10-24): "Savings: starting balance is the first recorded
    balance, 2026-07-01 (no data on 2026-01-01)." """
    return (f"{s['account']}: starting balance is the first recorded balance, {s['date'].isoformat()} "
            f"(no data on {s['requested'].isoformat()}).")


def _hint(db: Session, account_id: int) -> str:
    a = db.get(BankAccount, account_id)
    how = ("set an earlier Opening Balance Date on the account" if a.register_enabled
           else "enter a dated balance with Update balance")
    return f"No data on that date. To use a real balance, {how}; if the account was opened later, set Account opened."


def balances(db: Session, ws_id: int, date_to: dt.date, compare: dt.date | None) -> dict:
    """Every account open on the Through Date, by section, with its Current (bank) balance on that date (#56 / #88)
    and, with a Compare Date, the balance then and the change."""
    subs: list[dict] = []

    def bal(a, d):
        # 2.2.0 (#348): a date before any data uses the earliest available data, not $0 (unless the account was
        # opened after that date: Account opened)
        cents, s = bank.balance_on(db, a, d)
        if s is not None:
            subs.append({"id": a.id, "account": a.account_name, "date": s["date"], "requested": d})
        return cents, s
    secs = {k: {"key": k, "label": lbl, "accounts": [], "total": 0, "compare_total": 0} for k, lbl in SECTIONS}
    for a in db.scalars(select(BankAccount).where(BankAccount.workspace_id == ws_id).order_by(*bank.listing_order())):
        if not _open_on(db, a, date_to):
            continue
        s = secs[_section_of(a.account_type)]
        row = {"id": a.id, "label": f"{a.account_name} - {bank.masked(a)}", "balance": bal(a, date_to)[0],
               "interest_rate": a.interest_rate or None, "register": a.register_enabled}
        if compare is not None:
            row["compare_balance"], s_ = bal(a, compare)
            row["compare_substituted"] = s_["date"] if s_ else None
            row["change"] = row["balance"] - row["compare_balance"]
            s["compare_total"] += row["compare_balance"]
        s["accounts"].append(row)
        s["total"] += row["balance"]
    cs = secs["CHECKING"]["total"] + secs["SAVINGS"]["total"]
    cs_c = secs["CHECKING"]["compare_total"] + secs["SAVINGS"]["compare_total"]
    inv, inv_c = secs["INVESTMENTS"]["total"], secs["INVESTMENTS"]["compare_total"]
    out = {"date": date_to, "compare_date": compare, "substitutions": subs, "sections": [secs[k] for k, _ in SECTIONS],
           "totals": [{"label": "Total Checking & Savings", "total": cs, "compare_total": cs_c},
                      {"label": "Total Investments", "total": inv, "compare_total": inv_c},
                      {"label": "Total Assets", "total": cs + inv, "compare_total": cs_c + inv_c}]}
    for x in [*out["sections"], *out["totals"]]:
        x["change"] = x["total"] - x["compare_total"] if compare is not None else None
    return out


# --------------------------------------------------------------------------- the report data
def compute(db: Session, ctx, data) -> dict:
    p = _params(db, ctx, data)
    sections = []
    for a in p["accounts"]:
        inc, exp = account_lines(db, a, p["date_from"], p["date_to"])
        sections.append({"id": a.id, "label": f"{a.account_name} - {bank.masked(a)}", "income": inc, "expense": exp})
    return {**p, "sections": sections,
            "balances": balances(db, ctx.workspace_id, p["date_to"], p["compare_date"]) if p["include_balances"] else None}


def _fmt_line(x: dict) -> dict:
    return {"key": x["key"], "transaction_id": x["transaction_id"], "allocation_id": x["allocation_id"],
            "date": x["date"].isoformat(), "amount": fmt(x["amount"]), "description": x["description"]}


def preview(db: Session, ctx, data) -> dict:
    """The review form: every line that would be in the report, with the totals."""
    r = compute(db, ctx, data)
    secs = []
    for s in r["sections"]:
        t = _totals(s)
        secs.append({"id": s["id"], "label": s["label"], "income": [_fmt_line(x) for x in s["income"]],
                     "expense": [_fmt_line(x) for x in s["expense"]], **{k: fmt(v) for k, v in t.items()}})
    out = {"title": r["title"], "date_from": r["date_from"].isoformat(), "date_to": r["date_to"].isoformat(),
           "current": r["current"], "period": _period(r), "sections": secs, "summary": None, "balances": None}
    if len(secs) > 1:
        tot = [_totals(s) for s in r["sections"]]
        out["summary"] = {k: fmt(sum(t[k] for t in tot)) for k in ("income_total", "expense_total", "difference")}
    if r["balances"]:
        b = r["balances"]

        def f(x):
            return {**x, **{k: fmt(x[k]) for k in ("balance", "compare_balance", "change", "total", "compare_total")
                            if k in x and x[k] is not None}}
        out["balances"] = {"date": b["date"].isoformat(), "compare_date": b["compare_date"].isoformat() if b["compare_date"] else None,
                           "substitutions": [{"id": s["id"], "text": substitution_text(s), "hint": _hint(db, s["id"])}
                                             for s in b["substitutions"]],
                           "sections": [{**f(s), "accounts": [f(a) for a in s["accounts"]]} for s in b["sections"]],
                           "totals": [f(t) for t in b["totals"]]}
    return out


def _apply_review(r: dict, exclusions, line_notes) -> tuple[list[dict], list[dict]]:
    lines = {x["key"]: x for s in r["sections"] for x in [*s["income"], *s["expense"]]}
    excluded, notes = [], []
    seen = set()
    for e in exclusions:
        x = lines.get(e.key)
        if x is None:
            raise validation(f"Line {e.key} is not in this report; review the transactions again.", "exclusions")
        if e.key in seen:
            continue
        seen.add(e.key)
        reason = (e.reason or "").strip()
        if not reason:
            raise validation(f"A reason is required to exclude the line of {_us(x['date'])} ({money(x['amount'])}).",
                             "exclusions")
        x["excluded"] = True
        excluded.append({"key": x["key"], "transaction_id": x["transaction_id"], "allocation_id": x["allocation_id"],
                         "date": x["date"].isoformat(), "amount": fmt(x["amount"]), "description": x["description"],
                         "reason": reason})
    for n in line_notes:
        x = lines.get(n.key)
        if x is None:
            raise validation(f"Line {n.key} is not in this report; review the transactions again.", "line_notes")
        if n.note and n.note.strip():
            x["note"] = n.note.strip()
            notes.append({"key": x["key"], "transaction_id": x["transaction_id"], "allocation_id": x["allocation_id"],
                          "note": x["note"]})
    return excluded, notes


# --------------------------------------------------------------------------- PDF
def _color_cell(text: str, c: int, style="cellr", bold=True):
    col = "#1a7f37" if c > 0 else "#c62828" if c < 0 else "#000000"
    t = escape(text)
    return PM(f'<font color="{col}">{"<b>" + t + "</b>" if bold else t}</font>', style)


def _lines_table(lines: list[dict], with_notes: bool, total: int, empty: str) -> Table:
    w_date, w_amt = 0.85 * inch, 1.0 * inch
    rest = FRAME_W - 12 - w_date - w_amt
    widths = [w_date, w_amt, rest * 0.6, rest * 0.4] if with_notes else [w_date, w_amt, rest]
    head = [PM("<b>Date</b>", "cell"), PM("<b>Amount</b>", "cellr"), PM("<b>Description</b>", "cell")]
    if with_notes:
        head.append(PM("<b>Notes</b>", "cell"))
    data = [head]
    for x in lines:
        row = [P(_us(x["date"]), "cell"), P(money(x["amount"]), "cellr"), P(x["description"], "cell")]
        if with_notes:
            row.append(P(x.get("note") or "", "cell"))
        data.append(row)
    extra = []
    if not lines:
        data.append([P(empty, "cell"), "", "", *([""] if with_notes else [])])
        extra.append(("SPAN", (0, 1), (-1, 1)))
    data.append([PM("<b>Total</b>", "cell"), PM(f"<b>{escape(money(total))}</b>", "cellr"), "",
                 *([""] if with_notes else [])])
    n = len(data) - 1
    extra += [("LINEABOVE", (0, n), (-1, n), 0.8, colors.black), ("BACKGROUND", (0, n), (-1, n), branding.color("surface_variant"))]
    return _grid(data, widths, extra=extra)


def _diff_table(rows: list[tuple[str, int, bool]]) -> Table:
    """(label, cents, is_difference) rows, right-aligned amounts; the Difference in green / red with its sign."""
    data = []
    for label, c, is_diff in rows:
        data.append([PM(f"<b>{escape(label)}</b>", "body"),
                     _color_cell(signed(c), c, "body") if is_diff else PM(f"<b>{escape(money(c))}</b>", "body")])
    t = Table(data, colWidths=[2.2 * inch, 1.6 * inch], hAlign="LEFT")
    t.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("LEFTPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                           ("LINEABOVE", (0, len(data) - 1), (-1, len(data) - 1), 0.6, colors.black)]))
    return t


def _balances_table(b: dict) -> Table:
    comp = b["compare_date"] is not None
    head = [PM("<b>Account</b>", "cell"), PM(f"<b>Balance {escape(_us(b['date']))}</b>", "cellr"),
            PM("<b>Interest rate</b>", "cellr")]
    if comp:
        head += [PM(f"<b>Balance {escape(_us(b['compare_date']))}</b>", "cellr"), PM("<b>Change</b>", "cellr")]
    data, extra = [head], []

    for s in b["sections"]:
        data.append([PM(f"<b>{escape(s['label'])}</b>", "cell")] + [""] * (len(head) - 1))
        r = len(data) - 1
        extra += [("SPAN", (0, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), branding.color("surface_variant"))]
        if not s["accounts"]:
            data.append([P("No accounts", "cell")] + [""] * (len(head) - 1))
        for a in s["accounts"]:
            rate = f"{a['interest_rate']}%" if a.get("interest_rate") else ""
            row = [P(a["label"], "cell"), P(money(a["balance"]), "cellr"), P(rate, "cellr")]
            if comp:
                row += [P(money(a["compare_balance"]), "cellr"), _color_cell(signed(a["change"]), a["change"], bold=False)]
            data.append(row)
        row = [PM(f"<b>Total {escape(s['label'])}</b>", "cell"), PM(f"<b>{escape(money(s['total']))}</b>", "cellr"), ""]
        if comp:
            row += [PM(f"<b>{escape(money(s['compare_total']))}</b>", "cellr"), _color_cell(signed(s["change"]), s["change"])]
        data.append(row)
        extra.append(("LINEABOVE", (0, len(data) - 1), (-1, len(data) - 1), 0.6, colors.black))
    for t in b["totals"]:
        row = [PM(f"<b>{escape(t['label'])}</b>", "cell"), PM(f"<b>{escape(money(t['total']))}</b>", "cellr"), ""]
        if comp:
            row += [PM(f"<b>{escape(money(t['compare_total']))}</b>", "cellr"), _color_cell(signed(t["change"]), t["change"])]
        data.append(row)
        r = len(data) - 1
        extra += [("BACKGROUND", (0, r), (-1, r), branding.color("surface_variant"))]
    extra.append(("LINEABOVE", (0, len(data) - 3), (-1, len(data) - 3), 1.2, colors.black))
    rest = FRAME_W - 12
    widths = ([rest - 4.4 * inch, 1.2 * inch, 0.8 * inch, 1.2 * inch, 1.2 * inch] if comp
              else [rest - 2.0 * inch, 1.2 * inch, 0.8 * inch])
    return _grid(data, widths, zebra=False, extra=extra)


@branding.themed
def build_pdf(db: Session, ctx, data) -> tuple[str, str, dict]:
    r = compute(db, ctx, data)
    excluded, notes = _apply_review(r, data.exclusions, data.line_notes)
    with_notes = bool(notes)
    ws = db.get(Workspace, ctx.workspace_id)
    period = _period(r)
    buf = io.BytesIO()
    doc = _AuditDoc(buf, title=f"Financial Flow Report — {r['title']}", author=ws.name)
    f: list = [_Mark(doc, "Financial Flow Report"), P(ws.name, "h3"), P(r["title"], "title"),
               PM(f"<b>Financial Flow Report</b> &nbsp;·&nbsp; {escape(period)}", "h2"), Spacer(1, 4)]
    if r["notes"]:
        f += [PM("<b>Notes</b>", "body"), P(r["notes"], "body"), Spacer(1, 8)]
    totals = []
    for s in r["sections"]:
        inc = [x for x in s["income"] if not x.get("excluded")]
        exp = [x for x in s["expense"] if not x.get("excluded")]
        t = _totals(s)
        totals.append(t)
        f += [_Mark(doc, s["label"]), P(s["label"], "h1"),
              KeepTogether([PM("<b>Income</b>", "h2"),
                            _lines_table(inc, with_notes, t["income_total"], "No income in this period")]),
              Spacer(1, 6),
              KeepTogether([PM("<b>Expenses</b>", "h2"),
                            _lines_table(exp, with_notes, t["expense_total"], "No expenses in this period")]),
              Spacer(1, 6),
              _diff_table([("Total income", t["income_total"], False), ("Total expenses", t["expense_total"], False),
                           ("Difference", t["difference"], True)]), Spacer(1, 12)]
    if len(r["sections"]) > 1:
        ti, te = sum(t["income_total"] for t in totals), sum(t["expense_total"] for t in totals)
        f += [KeepTogether([_Mark(doc, "Summary"), P("Summary of all selected accounts", "h1"),
                            _diff_table([("Total income", ti, False), ("Total expenses", te, False),
                                         ("Difference", ti - te, True)])]), Spacer(1, 12)]
    if r["balances"]:
        b = r["balances"]
        f += [_Mark(doc, "Account balances"), P("Account balances", "h1"),
              P(f"Current (bank) balance of every account open on {_us(b['date'])}"
                + (f", compared with {_us(b['compare_date'])}." if b["compare_date"] else "."), "small"),
              Spacer(1, 4), _balances_table(b)]
        if r["substitution_notes"] and b["substitutions"]:      # 2.2.0 (#348): off by default - the PDF stays clean
            f += [Spacer(1, 4)] + [P(substitution_text(s), "small") for s in b["substitutions"]]
        f.append(Spacer(1, 12))
    f.append(P(f"Generated {utcnow():%Y-%m-%d %H:%M} UTC by {ctx.user.username} — {ws.name}", "small"))
    doc.build(f)
    fd, path = tempfile.mkstemp(prefix="fmpoc-flow-", suffix=".pdf")
    os.close(fd)
    try:
        pages = _stamp_and_write(buf.getvalue(), doc, path, f"Financial Flow Report — {r['title']} — {ws.name}")
    except Exception:
        os.unlink(path)
        raise
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in r["title"]).strip("-")[:60] or "report"
    summary = {"report": "FINANCIAL_FLOW", "title": r["title"], "date_from": r["date_from"].isoformat(),
               "date_to": r["date_to"].isoformat(), "through": "Current" if r["current"] else r["date_to"].isoformat(),
               "bank_account_ids": [s["id"] for s in r["sections"]], "include_balances": r["include_balances"],
               "compare_date": r["compare_date"].isoformat() if r["compare_date"] else None, "notes": r["notes"], "show_substitution_notes": r["substitution_notes"],
               "line_notes": notes, "exclusions": excluded, "pages": pages}
    return path, f"financial-flow-{safe}.pdf", summary
