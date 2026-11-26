"""2.6.0 (#609): the optional modules' sections of the End of Year Audit and Fiscal Year Close reports.

Rule (BR-RPT-MOD-001): a module's section is in the report exactly when the Fiscal Year has that module's data -
whatever the module's switch says now, and with no report option to leave it out. A module that was used in the year
and later turned off keeps its section, with a note; a module never used gets none.

Each section sits between a start page and an end page that state its page range (like the account sections, 1.6.7,
and the events, 1.7.1 #59), and points at the transaction pages of the same report (the #589 page references), so the
trail runs both ways: section -> transaction page, and transaction page -> invoice / donation (`allocation_links`).

The figures here are for tracing only. Income is counted when it is deposited (BR-048); nothing in these sections is
a second income total, and nothing blocks or warns at close (BR-013/014 unchanged).
"""
from __future__ import annotations

import datetime as dt
from xml.sax.saxutils import escape

from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Spacer
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (Budget, Donation, DonationLine, DonationReceipt, Entity, FiscalYear, Invoice, InvoicePayment,
                      RegisterTransaction, TransactionAllocation)
from . import donations as don
from . import fundraisers as fsvc
from . import invoice_docs as idocs
from . import invoices as inv
from . import reports as R
from .common import budget_label
from .invoice_reports import _local_day, _open_rows

KIND_LABEL = {"PAYMENT": "Payment", "OVERPAYMENT": "Overpayment", "REFUND": "Refund of overpayment"}
NOTE_FOR_TRACING = ("Income is counted when it is deposited. This section is for tracing the money to the register: "
                    "its amounts are not a second income total and are not added to the figures above.")
PAGE_NOTE = ("Page = the page of this report where the transaction's details and attachments are printed. "
             "\"Not in this report\" = the transaction is in another Fiscal Year's report or an account this report "
             "leaves out.")


def module_switches(db: Session, ws_id: int) -> dict[str, bool]:
    return {"events": fsvc.module_enabled(db, ws_id), "invoices": inv.module_enabled(db, ws_id),
            "donations": don.module_enabled(db, ws_id)}


def _in_year(d: dt.date | None, fy: FiscalYear) -> bool:
    return d is not None and fy.start_date <= d <= fy.end_date


def _day(ts: dt.datetime | None) -> dt.date | None:
    return _local_day(ts) if ts else None


def _names(db: Session, ids) -> dict[int, str]:
    ids = [i for i in set(ids) if i]
    return {e.id: e.display_name for e in db.scalars(select(Entity).where(Entity.id.in_(ids)))} if ids else {}


def _where(doc, t_id: int, in_report: set[int]):
    return R._PageRef(doc, t_id) if t_id in in_report else R.P("Not in this report", "cell")


def _bounds_page(doc, section: dict, kind: str, title: str, rows: list[tuple[str, object]], listing: list[str],
                 off_note: str | None) -> list:
    """The start or end page of a module section (the same shape as the events' start / end pages)."""
    start = kind == "start"
    head = f"{'Start' if start else 'End'} of {section['thing']}"
    out = [R._Mark(doc, head), Spacer(1, 1.2 * inch), R.PM(head, "cover_sub"), Spacer(1, 6),
           R.PM(escape(title), "cover_title"), Spacer(1, 0.5 * inch), R._kv(rows, w1=1.8 * inch), Spacer(1, 14),
           R._SectionNote(doc, section, kind), Spacer(1, 8)]
    if off_note:
        out += [R.P(off_note, "small"), Spacer(1, 4)]
    if start:
        out += [R.P(x, "small") for x in listing]
        out += [Spacer(1, 8),
                R.P(f"Every page between this start page and the end page shows \"{section['label']} - section page k "
                    "of n\" at the bottom right. The pages belong to this section only, and none is missing when the "
                    "section page numbers run from 1 to n without a gap.", "small")]
    else:
        out += [R.P(f"No {section['one']} follows this page.", "small")]
    return out + [PageBreak()]


# =========================================================================== invoices
def _invoice_links(db: Session, invoice_ids: list[int]) -> dict[int, list[tuple]]:
    """Live links on ACTIVE register lines per invoice: (link, allocation, transaction), date order."""
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


def _open_at(i: Invoice, total: int, paid_by_end: int, fy: FiscalYear) -> int:
    """The balance open on the Fiscal Year's last day (0 for a draft, or one voided / written off by then)."""
    if i.status == "DRAFT" or i.invoice_date > fy.end_date:
        return 0
    if i.status == "VOID" and (_day(i.voided_at) or fy.end_date) <= fy.end_date:
        return 0
    if i.status == "WRITTEN_OFF" and (_day(i.write_off_decided_at) or fy.end_date) <= fy.end_date:
        return 0
    return max(total - paid_by_end, 0)


def invoice_data(db: Session, ws_id: int, fy: FiscalYear, account_id: int | None) -> dict:
    """The Fiscal Year's invoices (BR-RPT-MOD-002): dated in the year, or with a payment, overpayment, refund, credit
    use, write-off or void in it. Each payment counts in the year of its register transaction's date. With an
    account, only the invoices with a register line of that account in the year."""
    invs = list(db.scalars(select(Invoice).where(Invoice.workspace_id == ws_id).order_by(Invoice.seq)))
    links = _invoice_links(db, [i.id for i in invs])
    names = _names(db, [i.customer_entity_id for i in invs])
    by_id = {i.id: i for i in invs}
    rows = []
    for i in invs:
        ls = links[i.id]
        in_year = [(link, a, t) for link, a, t in ls if _in_year(t.transaction_date, fy)]
        wo_day = _day(i.write_off_decided_at) if i.write_off_status == "APPROVED" else None
        wo_req = _day(i.write_off_requested_at)
        void_day = _day(i.voided_at) if i.status == "VOID" else None
        dated = _in_year(i.invoice_date, fy)
        if not (dated or in_year or _in_year(wo_day, fy) or _in_year(void_day, fy) or _in_year(wo_req, fy)):
            continue
        if account_id is not None and not any(t.bank_account_id == account_id for _l, _a, t in in_year):
            continue
        total = idocs.totals_of(i)["total"]
        paid_by_end = sum(a.amount_cents for link, a, t in ls if link.kind == "PAYMENT" and t.transaction_date <= fy.end_date)
        groups: dict[tuple, dict] = {}
        for link, a, t in in_year:
            k = (t.id, link.kind, link.credit_from_invoice_id)
            g = groups.setdefault(k, {"date": t.transaction_date, "kind": link.kind, "txn": t.id, "amount": 0,
                                      "account_id": t.bank_account_id,
                                      "credit_from": by_id[link.credit_from_invoice_id].number
                                      if link.credit_from_invoice_id in by_id else None})
            g["amount"] += a.amount_cents
        activity = sorted(groups.values(), key=lambda g: (g["date"], g["txn"]))
        paid_in_year = sum(g["amount"] for g in activity if g["kind"] == "PAYMENT")
        rows.append({"invoice": i, "number": idocs.display_number(i), "customer": names.get(i.customer_entity_id, ""),
                     "total": total, "paid_in_year": paid_in_year, "open_at_end": _open_at(i, total, paid_by_end, fy),
                     "status": idocs.STATUS_LABEL.get(i.status, i.status), "dated_in_year": dated,
                     "activity": activity, "write_off_day": wo_day, "write_off_requested_day": wo_req,
                     "void_day": void_day,
                     "written_off": max(total - sum(a.amount_cents for link, a, t in ls if link.kind == "PAYMENT"
                                                    and (wo_day is None or t.transaction_date <= wo_day)), 0)})
    return {"rows": rows, "all": invs}


def invoice_numbers(invs: list[Invoice], fy: FiscalYear) -> dict:
    """BR-RPT-MOD-003: every invoice number in the year's range accounted for. A number is taken when the draft is
    created and never reused, so a number in the range is either an invoice dated in this year, one dated in
    another year, or (should never happen) missing."""
    mine = [i for i in invs if _in_year(i.invoice_date, fy)]
    if not mine:
        return {}
    lo, hi = min(i.seq for i in mine), max(i.seq for i in mine)
    have = {i.seq for i in mine}
    by_seq = {i.seq: i for i in invs}
    elsewhere, missing = [], []
    for s in range(lo, hi + 1):
        if s in have:
            continue
        if s in by_seq:
            elsewhere.append(by_seq[s])
        else:
            missing.append(s)
    return {"first": min(mine, key=lambda i: i.seq), "last": max(mine, key=lambda i: i.seq), "count": len(mine),
            "voided": [i for i in mine if i.status == "VOID"], "drafts": [i for i in mine if i.status == "DRAFT"],
            "elsewhere": elsewhere, "missing": missing}


def invoice_tie_out(db: Session, ws_id: int, fy: FiscalYear) -> dict | None:
    """BR-RPT-MOD-004: the Invoiced Income budgets' actual for the year against the invoice links on them; every line
    on those budgets with no invoice link is listed, and the linked lines on other budgets (e.g. sales tax) shown."""
    budgets = {b.id: b for b in db.scalars(select(Budget).where(Budget.fiscal_year_id == fy.id))}
    if not budgets:
        return None
    rows = db.execute(select(TransactionAllocation, RegisterTransaction)
                      .join(RegisterTransaction, RegisterTransaction.id == TransactionAllocation.transaction_id)
                      .where(TransactionAllocation.budget_id.in_(list(budgets)), TransactionAllocation.removed_at.is_(None),
                             RegisterTransaction.status == "ACTIVE", RegisterTransaction.workspace_id == ws_id)).all()
    linked = set(db.scalars(select(InvoicePayment.allocation_id).where(
        InvoicePayment.allocation_id.in_([a.id for a, _t in rows] or [0]), InvoicePayment.removed_at.is_(None))))
    sign = lambda t: 1 if t.transaction_type == "DEPOSIT" else -1  # noqa: E731
    actual = linked_sum = 0
    unlinked: list[tuple] = []
    other: dict[int, int] = {}
    for a, t in rows:
        b = budgets[a.budget_id]
        amt = sign(t) * a.amount_cents
        if b.invoiced_income:
            actual += amt
            if a.id in linked:
                linked_sum += amt
            else:
                unlinked.append((a, t, amt))
        elif a.id in linked:
            other[b.id] = other.get(b.id, 0) + amt
    if not actual and not unlinked and not other and not any(b.invoiced_income for b in budgets.values()):
        return None
    parents = {b.id: b for b in budgets.values()}

    def label(bid: int) -> str:
        b = budgets[bid]
        return budget_label(b, parents.get(b.parent_budget_id) or (db.get(Budget, b.parent_budget_id) if b.parent_budget_id else None))
    return {"actual": actual, "linked": linked_sum, "unlinked": sorted(unlinked, key=lambda x: (x[1].transaction_date, x[1].id)),
            "other": sorted(((label(bid), v) for bid, v in other.items()), key=lambda x: x[0])}


def invoices_present(data: dict, open_rows: list, numbers: dict) -> bool:
    return bool(data["rows"] or open_rows or numbers)


def invoice_flowables(db: Session, doc, fy: FiscalYear, account_id: int | None, in_report: set[int],
                      users: dict[int, str], switch_on: bool) -> tuple[list, dict | None, int]:
    """The Invoices section, or ([], None, 0) when the year has no invoice data."""
    ws_id = fy.workspace_id
    data = invoice_data(db, ws_id, fy, account_id)
    whole = account_id is None
    open_rows = sorted(_open_rows(db, ws_id, fy.end_date, None), key=lambda r: (r["due_date"], r["number"])) if whole else []
    numbers = invoice_numbers(data["all"], fy) if whole else {}
    if not invoices_present(data, open_rows, numbers):
        return [], None, 0
    rows = data["rows"]
    section = {"kind": "invoices", "label": "Invoices", "thing": "invoices", "one": "invoice"}
    doc.sections.append(section)
    off = ("The Invoices module is currently turned off. This section still shows the year's invoice records: turning "
           "a module off doesn't remove a year's records from its report.") if not switch_on else None
    summary_rows = [("Fiscal Year", f"{fy.display_name} ({fy.start_date} to {fy.end_date})"),
                    ("Invoices in this section", str(len(rows))),
                    ("Paid in this year", R.money(sum(r["paid_in_year"] for r in rows)))]
    if whole:
        summary_rows.append(("Open at the year's end", R.money(sum(x["open"] for x in open_rows))))
    else:
        summary_rows.append(("Accounts", "Only the invoices with a register line in this report's account. The "
                                         "all-accounts report lists every invoice, the number check and the tie-out."))
    listing = ["In this section: " + ", ".join(x for x in (
        "the invoices of the year with their payments" if rows else "",
        "the invoice number check" if numbers else "", "the Invoiced Income tie-out" if whole else "",
        "the invoices open at the year's end" if open_rows else "") if x) + "."]
    title = f"Invoices — {fy.display_name}"
    f = _bounds_page(doc, section, "start", title, summary_rows, listing, off)

    f += [R._Mark(doc, "Invoices"), R.PM("Invoices", "h1"), R.P(NOTE_FOR_TRACING, "small"), Spacer(1, 4)]
    if rows:
        f.append(R.P("Each invoice dated in this Fiscal Year, and each older invoice with a payment, refund, credit, "
                     "write-off or void in it. A payment is shown in the Fiscal Year of its deposit's date, so an "
                     "invoice paid in a later year appears in both years' reports.", "small"))
        for r in rows:
            i = r["invoice"]
            head = (f"<b>{escape(r['number'])}</b> — {escape(r['customer'])} · dated {i.invoice_date:%m/%d/%Y}, due "
                    f"{i.due_date:%m/%d/%Y} · total {escape(R.money(r['total']))} · now {escape(r['status'])}")
            if not r["dated_in_year"]:
                head += " · <i>dated in another Fiscal Year</i>"
            block = [Spacer(1, 6), R.PM(head, "body")]
            grid = [[R.PM(f"<b>{h}</b>", "cell") for h in ("Date", "Activity", "Transaction", "Page", "Amount")]]
            for g in r["activity"]:
                what = KIND_LABEL.get(g["kind"], g["kind"])
                if g["credit_from"]:
                    what += f" (from the credit of {g['credit_from']})"
                amt = -g["amount"] if g["kind"] == "REFUND" else g["amount"]
                grid.append([R.P(g["date"].strftime("%m/%d/%Y"), "cell"), R.P(what, "cell"), R.P(f"#{g['txn']}", "cell"),
                             _where(doc, g["txn"], in_report), R.P(R.money(amt), "cellr")])
            if _in_year(r["write_off_day"], fy):
                who = (f"requested by {users.get(i.write_off_requested_by_user_id, '?')}, approved by "
                       f"{users.get(i.write_off_decided_by_user_id, '?')}"
                       + (" (self-approved)" if i.write_off_self_approved else ""))
                grid.append([R.P(r["write_off_day"].strftime("%m/%d/%Y"), "cell"),
                             R.P(f"Written off — {who}. Reason: {i.write_off_reason or '—'}", "cell"), R.P("—", "cell"),
                             R.P("", "cell"), R.P(R.money(r["written_off"]), "cellr")])
            elif i.write_off_status in ("PENDING", "REJECTED") and _in_year(r["write_off_requested_day"], fy):
                st = "pending" if i.write_off_status == "PENDING" else "rejected"
                grid.append([R.P(r["write_off_requested_day"].strftime("%m/%d/%Y"), "cell"),
                             R.P(f"Write-off requested by {users.get(i.write_off_requested_by_user_id, '?')} — {st}. "
                                 f"Reason: {i.write_off_reason or '—'}", "cell"), R.P("—", "cell"), R.P("", "cell"),
                             R.P("", "cell")])
            if _in_year(r["void_day"], fy):
                grid.append([R.P(r["void_day"].strftime("%m/%d/%Y"), "cell"),
                             R.P(f"Voided by {users.get(i.voided_by_user_id, '?')}. Reason: {i.void_reason or '—'}", "cell"),
                             R.P("—", "cell"), R.P("", "cell"), R.P("", "cell")])
            if len(grid) == 1:
                grid.append([R.P("", "cell"), R.P("No payment or other activity in this Fiscal Year.", "cell"),
                             R.P("", "cell"), R.P("", "cell"), R.P("", "cell")])
            grid.append([R.PM("<b>Open at the year's end</b>", "cell"), R.P("", "cell"), R.P("", "cell"), R.P("", "cell"),
                         R.PM(f"<b>{escape(R.money(r['open_at_end']))}</b>", "cellr")])
            n = len(grid)
            block.append(R._grid(grid, [0.8 * inch, R.FRAME_W - 12 - 3.55 * inch, 0.85 * inch, 0.6 * inch, 1.3 * inch],
                                 extra=[("SPAN", (0, n - 1), (3, n - 1))]))
            f += block
        f.append(R.P(PAGE_NOTE, "small"))
    elif not whole:
        f.append(R.P("No invoice has a register line of this account in this Fiscal Year.", "body"))

    if numbers:
        f += [Spacer(1, 8), R.PM("Invoice numbers", "h2"),
              R.P("A number is taken when an invoice is created and is never reused, so every number from the year's "
                  "first to its last should be accounted for below.", "small"),
              R._kv([("Invoices dated in this year", str(numbers["count"])),
                     ("First number", f"{numbers['first'].number} ({numbers['first'].invoice_date:%m/%d/%Y})"),
                     ("Last number", f"{numbers['last'].number} ({numbers['last'].invoice_date:%m/%d/%Y})")],
                    w1=1.9 * inch, style="body")]
        lines = [f"Voided: {i.number} — {i.void_reason or 'no reason'}" for i in numbers["voided"]]
        lines += [f"Draft (never sent): {i.number}" for i in numbers["drafts"]]
        lines += [f"Dated in another Fiscal Year: {i.number} ({i.invoice_date:%m/%d/%Y})" for i in numbers["elsewhere"]]
        lines += [f"No invoice has number #{s} in the sequence — investigate." for s in numbers["missing"]]
        f += [R.P("• " + x, "body") for x in lines] or [R.P("• Every number in the range is an invoice of this year.", "body")]

    if whole:
        tie = invoice_tie_out(db, ws_id, fy)
        f += [Spacer(1, 8), R.PM("Invoiced Income tie-out", "h2")]
        if tie is None:
            f.append(R.P("This Fiscal Year has no Invoiced Income budget.", "body"))
        else:
            f += [R.P("The Invoiced Income budgets' actual for the year should equal the register lines on them that "
                      "are linked to invoices. A line on an Invoiced Income budget with no invoice link is listed "
                      "(for example, one entered while the Invoices module was off).", "small"),
                  R._kv([("Invoiced Income budgets, actual", R.money(tie["actual"])),
                         ("Of which linked to invoices", R.money(tie["linked"])),
                         ("Not linked to an invoice", R.money(tie["actual"] - tie["linked"]))], w1=2.4 * inch, style="body")]
            if tie["unlinked"]:
                grid = [[R.PM(f"<b>{h}</b>", "cell") for h in ("Date", "Transaction", "Page", "Description", "Amount")]]
                for a, t, amt in tie["unlinked"]:
                    grid.append([R.P(t.transaction_date.strftime("%m/%d/%Y"), "cell"), R.P(f"#{t.id}", "cell"),
                                 _where(doc, t.id, in_report), R.P(a.description or "—", "cell"),
                                 R.P(R.money(amt), "cellr")])
                f.append(R._grid(grid, [0.8 * inch, 0.85 * inch, 0.6 * inch, R.FRAME_W - 12 - 3.55 * inch, 1.3 * inch]))
            if tie["other"]:
                f.append(R.P("Invoice payments also put these amounts on other budgets (for example sales tax): "
                             + "; ".join(f"{escape(lbl)} {R.money(v)}" for lbl, v in tie["other"]) + ".", "small"))

    if open_rows:
        grid = [[R.PM(f"<b>{h}</b>", "cell") for h in ("Invoice", "Customer", "Date", "Due", "Total", "Open")]]
        for x in open_rows:
            grid.append([R.P(x["number"], "cell"), R.P(x["customer"], "cell"), R.P(x["invoice_date"].strftime("%m/%d/%Y"), "cell"),
                         R.P(x["due_date"].strftime("%m/%d/%Y"), "cell"), R.P(R.money(x["total"]), "cellr"),
                         R.P(R.money(x["open"]), "cellr")])
        grid.append([R.PM("<b>Total open</b>", "cell"), R.P("", "cell"), R.P("", "cell"), R.P("", "cell"), R.P("", "cell"),
                     R.PM(f"<b>{R.money(sum(x['open'] for x in open_rows))}</b>", "cellr")])
        f += [Spacer(1, 8), R.PM("Open invoices at the year's end", "h2"),
              R.P(f"Invoices with a balance open on {fy.end_date:%m/%d/%Y} (payments dated after it not counted). For "
                  "information: open invoices don't prevent closing the Fiscal Year.", "small"), Spacer(1, 4),
              R._grid(grid, [1.3 * inch, R.FRAME_W - 12 - 5.3 * inch, 0.9 * inch, 0.9 * inch, 1.1 * inch, 1.1 * inch])]
    f.append(PageBreak())
    f += _bounds_page(doc, section, "end", title, summary_rows, [], None)
    return f, section, len(rows)


# =========================================================================== donations
def donation_data(db: Session, ws_id: int, fy: FiscalYear, account_id: int | None) -> dict:
    """The Fiscal Year's donations: a money line deposited in the year, an item received in it, cancelled in it or a
    receipt printed in it. With an account: only donations with a money line deposited to it in the year."""
    ds = list(db.scalars(select(Donation).where(Donation.workspace_id == ws_id).order_by(Donation.id)))
    names = _names(db, [d.donor_entity_id for d in ds])
    receipts = list(db.scalars(select(DonationReceipt).where(DonationReceipt.workspace_id == ws_id)
                               .order_by(DonationReceipt.year, DonationReceipt.seq, DonationReceipt.id)))
    printed_in_year = [r for r in receipts if _in_year(_day(r.printed_at), fy)]
    receipt_donations = {r.donation_id for r in printed_in_year if r.donation_id}
    rows, awaiting = [], []
    for d in ds:
        lines = don.lines_of(db, d)
        out_lines = []
        hit = False
        for x in lines:
            received = don.line_received(db, x)
            date = don.line_date(db, x) if received else None
            t = don.line_deposit(db, x) if x.kind == don.MONEY else None
            if received and _in_year(date, fy):
                if account_id is None or (t is not None and t.bank_account_id == account_id):
                    hit = True
            out_lines.append({"line": x, "received": received, "date": date, "txn": t,
                              "amount": don.line_amount(db, x), "in_year": received and _in_year(date, fy)})
            if (account_id is None and d.status != don.CANCELLED and x.kind == don.MONEY and not received
                    and _day(x.created_at) is not None and _day(x.created_at) <= fy.end_date):
                awaiting.append((d, x))
        cancelled = d.status == don.CANCELLED and _in_year(_day(d.cancelled_at), fy)
        if account_id is None and (cancelled or d.id in receipt_donations):
            hit = True
        if hit:
            rows.append({"donation": d, "donor": names.get(d.donor_entity_id, ""), "lines": out_lines,
                         "status": don.STATUS_TEXT.get(don._status_of(db, d, lines), ""), "cancelled_in_year": cancelled})
    return {"rows": rows, "awaiting": awaiting, "printed": printed_in_year if account_id is None else [],
            "receipts": receipts, "names": names}


def receipt_numbers(printed: list[DonationReceipt], receipts: list[DonationReceipt]) -> list[str]:
    """BR-RPT-MOD-003 for receipts: per receipt year, every number from the first to the last printed in this Fiscal
    Year is accounted for (duplicates reuse the original's number)."""
    out = []
    for year in sorted({r.year for r in printed}):
        mine = {r.seq for r in printed if r.year == year and r.kind != don.DUPLICATE}
        if not mine:
            continue
        everywhere = {r.seq: r for r in receipts if r.year == year and r.kind != don.DUPLICATE}
        for s in range(min(mine), max(mine) + 1):
            if s in mine:
                continue
            r = everywhere.get(s)
            out.append(f"{r.number}: printed {r.printed_at:%m/%d/%Y}, in another Fiscal Year" if r
                       else f"{year} receipt #{s}: no receipt has this number — investigate.")
    return out


def donation_flowables(db: Session, doc, fy: FiscalYear, account_id: int | None, in_report: set[int],
                       users: dict[int, str], switch_on: bool) -> tuple[list, dict | None, int]:
    ws_id = fy.workspace_id
    data = donation_data(db, ws_id, fy, account_id)
    rows, awaiting, printed = data["rows"], data["awaiting"], data["printed"]
    if not rows and not awaiting and not printed:
        return [], None, 0
    whole = account_id is None
    by_id = {r.id: r for r in data["receipts"]}
    section = {"kind": "donations", "label": "Donations", "thing": "donations", "one": "donation"}
    doc.sections.append(section)
    off = ("The Donations module is currently turned off. This section still shows the year's donation records: "
           "turning a module off doesn't remove a year's records from its report.") if not switch_on else None
    money_in = sum(x["amount"] for r in rows for x in r["lines"] if x["in_year"] and x["line"].kind == don.MONEY)
    items = sum(1 for r in rows for x in r["lines"] if x["in_year"] and x["line"].kind == don.ITEM)
    summary_rows = [("Fiscal Year", f"{fy.display_name} ({fy.start_date} to {fy.end_date})"),
                    ("Donations in this section", str(len(rows))),
                    ("Money received in this year", R.money(money_in)), ("Items received in this year", str(items))]
    if whole:
        summary_rows.append(("Receipts printed in this year", str(len(printed))))
    else:
        summary_rows.append(("Accounts", "Only the donations deposited to this report's account. The all-accounts "
                                         "report lists every donation, receipt and cancellation."))
    title = f"Donations — {fy.display_name}"
    f = _bounds_page(doc, section, "start", title, summary_rows, [
        "In this section: each donation of the year with its lines and deposits"
        + (", the receipts printed, cancelled donations and money still awaiting a deposit." if whole else ".")], off)

    f += [R._Mark(doc, "Donations"), R.PM("Donations", "h1"), R.P(NOTE_FOR_TRACING, "small"), Spacer(1, 4)]
    for r in rows:
        d = r["donation"]
        rec = [x for x in data["receipts"] if x.donation_id == d.id]
        cur = don._current(rec)
        head = f"<b>{escape(r['donor'])}</b> — donation #{d.id} · {escape(r['status'])}"
        if cur:
            head += f" · receipt {escape(cur.number)}"
        grid = [[R.PM(f"<b>{h}</b>", "cell") for h in ("Received", "Line", "Transaction", "Page", "Amount / value")]]
        for x in r["lines"]:
            ln = x["line"]
            if not x["in_year"] and x["received"]:
                continue
            desc = ("Money" if ln.kind == don.MONEY else "Item") + (f" — {ln.description}" if ln.description else "")
            if ln.purpose:
                desc += f" · purpose: {ln.purpose}"
            if ln.goods_cents:
                desc += f" · goods or services given in exchange: {R.money(ln.goods_cents)}" + (
                    f" ({ln.goods_description})" if ln.goods_description else "")
            if ln.kind == don.ITEM:
                val = (R.money(x["amount"]) if x["amount"] else
                       (f"none ({ln.item_no_value_reason})" if ln.item_no_value else "Value not entered"))
            else:
                val = R.money(x["amount"])
            t = x["txn"]
            grid.append([R.P(x["date"].strftime("%m/%d/%Y") if x["date"] else "Not received", "cell"), R.P(desc, "cell"),
                         R.P(f"#{t.id}" if t is not None else "—", "cell"),
                         _where(doc, t.id, in_report) if t is not None else R.P("", "cell"), R.P(val, "cellr")])
        if r["cancelled_in_year"]:
            grid.append([R.P(f"{_day(d.cancelled_at):%m/%d/%Y}", "cell"),
                         R.P(f"Cancelled by {users.get(d.cancelled_by_user_id, '?')}. Reason: {d.cancel_reason or '—'}", "cell"),
                         R.P("—", "cell"), R.P("", "cell"), R.P("", "cell")])
        f += [Spacer(1, 6), R.PM(head, "body"),
              R._grid(grid, [0.85 * inch, R.FRAME_W - 12 - 3.6 * inch, 0.85 * inch, 0.6 * inch, 1.3 * inch])]
    if rows:
        f.append(R.P(PAGE_NOTE + " Items are not in the register; their value is the organization's own estimate, "
                     "for its records.", "small"))

    if whole and printed:
        grid = [[R.PM(f"<b>{h}</b>", "cell") for h in ("Receipt", "Printed", "Kind", "Donor", "Amount", "Goods given",
                                                      "Transaction", "Page")]]
        for x in printed:
            kind = {"ORIGINAL": "Original", "DUPLICATE": "Duplicate", "CORRECTED": "Corrected"}.get(x.kind, x.kind)
            if x.kind == don.CORRECTED and x.replaces_id in by_id:
                kind += f" (replaces {by_id[x.replaces_id].number})"
            grid.append([R.P(x.number, "cell"), R.P(f"{x.printed_at:%m/%d/%Y}", "cell"), R.P(kind, "cell"),
                         R.P(x.donor_name, "cell"), R.P(R.money(x.amount_cents), "cellr"),
                         R.P(R.money(x.goods_cents) if x.goods_cents else "—", "cellr"),
                         R.P(f"#{x.transaction_id}" if x.transaction_id else "—", "cell"),
                         _where(doc, x.transaction_id, in_report) if x.transaction_id else R.P("", "cell")])
        f += [Spacer(1, 8), R.PM("Receipts printed", "h2"),
              R.P("Every donation receipt printed in this Fiscal Year. A duplicate repeats the original's number; a "
                  "corrected receipt takes a new number and replaces the earlier one.", "small"),
              R._grid(grid, [0.95 * inch, 0.75 * inch, 1.25 * inch, R.FRAME_W - 12 - 5.95 * inch, 0.85 * inch, 0.75 * inch,
                             0.8 * inch, 0.6 * inch])]
        gaps = receipt_numbers(printed, data["receipts"])
        f += [R.P("• " + x, "body") for x in gaps] or [
            R.P("• Every receipt number from the first to the last printed in this year is listed above.", "body")]

    if whole and awaiting:
        grid = [[R.PM(f"<b>{h}</b>", "cell") for h in ("Donor", "Donation", "Line", "Amount")]]
        for d, x in awaiting:
            grid.append([R.P(data["names"].get(d.donor_entity_id, ""), "cell"), R.P(f"#{d.id}", "cell"),
                         R.P(x.description or "Money", "cell"), R.P(R.money(x.amount_cents or 0), "cellr")])
        f += [Spacer(1, 8), R.PM("Money awaiting a deposit at the year's end", "h2"),
              R.P("Money donations recorded by the year's end and not yet linked to a deposit (still not received "
                  "today). They are not in the register.", "small"),
              R._grid(grid, [2.4 * inch, 0.9 * inch, R.FRAME_W - 12 - 4.6 * inch, 1.3 * inch])]
    f.append(PageBreak())
    f += _bounds_page(doc, section, "end", title, summary_rows, [], None)
    return f, section, len(rows)


# =========================================================================== transaction pages
def allocation_links(db: Session, alloc_ids: list[int]) -> dict[int, list[str]]:
    """Allocation id -> what it is linked to, for the transaction pages: "Invoice INV-0012 (payment)",
    "Donation #7 — Jane Doe, receipt R-2026-0004"."""
    out: dict[int, list[str]] = {}
    if not alloc_ids:
        return out
    for link, i in db.execute(select(InvoicePayment, Invoice).join(Invoice, Invoice.id == InvoicePayment.invoice_id)
                              .where(InvoicePayment.allocation_id.in_(alloc_ids), InvoicePayment.removed_at.is_(None))
                              .order_by(InvoicePayment.id)).all():
        txt = f"Invoice {idocs.display_number(i)} ({KIND_LABEL.get(link.kind, link.kind).lower()})"
        if txt not in out.get(link.allocation_id, []):
            out.setdefault(link.allocation_id, []).append(txt)
    lines = list(db.scalars(select(DonationLine).where(DonationLine.allocation_id.in_(alloc_ids))))
    if lines:
        ds = {d.id: d for d in db.scalars(select(Donation).where(Donation.id.in_({x.donation_id for x in lines if x.donation_id} or {0})))}
        names = _names(db, [d.donor_entity_id for d in ds.values()])
        for x in lines:
            d = ds.get(x.donation_id)
            if d is None:
                continue
            cur = don._current(don._receipts_of(db, d))
            out.setdefault(x.allocation_id, []).append(
                f"Donation #{d.id} — {names.get(d.donor_entity_id, '')}" + (f", receipt {cur.number}" if cur else ""))
    return out
