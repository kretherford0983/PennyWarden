"""2.6.0 (#609): module sections in the End of Year Audit and Fiscal Year Close reports.

Decisions (Kyle, 2026-11-26): a module's section is always included when the Fiscal Year has its data (no option; the
Events option is gone); the data decides, not the module switch (a module turned off keeps its section, with a note);
invoices dated in the year or with activity in it, a payment counted in the year of its deposit; donations with their
receipts, cancellations and goods given; a single-account Audit report shows only that account's.

BR-RPT-MOD-001..004 / AC-RPT-MOD-001..012 (docs/implementation-notes.md). Regression for BR-003 (Administrator
refused), BR-013/014 (nothing blocks the close).
"""
from __future__ import annotations

import datetime as dt
import io
from types import SimpleNamespace as NS

from pypdf import PdfReader

from fmpoc.services import report_modules as rm
from test_v220_donations_part2 import _create, _ok, _print, don  # noqa: F401
from test_v240_invoice_reports import rb  # noqa: F401


def _text(r) -> str:
    assert r.status_code == 200, r.text[:300]
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)


def _pages(r) -> list[str]:
    return [p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages]


def _audit(env, fy, **p):
    return env.bu.get("/api/reports/audit", params={"fiscal_year_id": fy, **p})


def _number(rb, key):
    return rb["im"].get(f"/api/invoices/{rb[key]}").json()["number"]


def _payment_txn(rb, key):
    return rb["im"].get(f"/api/invoices/{rb[key]}").json()["payments"]["links"][0]["transaction_id"]


# ------------------------------------------------------------------ AC-RPT-MOD-001: nothing to show, nothing shown
def test_no_module_data_no_module_sections(env, base):
    env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "5.00"}], date="2026-09-01")
    for url in ("/api/reports/audit", "/api/reports/fy-close"):
        t = _text(env.bm.get(url, params={"fiscal_year_id": base["fy"]["id"]}))
        for kind in ("fundraisers", "invoices", "donations"):
            assert f"Start of {kind}" not in t
        assert "Module sections None: no optional module has records in this Fiscal Year" in t


# ------------------------------------------------------------------ AC-RPT-MOD-002/003/004: invoices, both ways
def test_invoice_section_traces_payments_to_transaction_pages_and_back(env, base, rb):
    fy = base["fy"]["id"]
    ia, ib = _number(rb, "ia"), _number(rb, "ib")
    r = _audit(env, fy)
    pages = _pages(r)
    t = "\n".join(pages)
    start = next(i for i, p in enumerate(pages) if p.startswith("Start of invoices"))
    end = next(i for i, p in enumerate(pages) if p.startswith("End of invoices"))
    assert start < end and "Invoices - section page 1 of" in pages[start]
    # the Fiscal Year Review lists the module sections
    assert "Module sections Invoices" in t
    section = "\n".join(pages[start:end + 1])
    assert ia in section and ib in section and "Acme Club" in section and "Payment" in section
    # each payment row points at the page of its transaction, and that page points back at the invoice
    txn = _payment_txn(rb, "ia")
    tx_page = next(i for i, p in enumerate(pages) if f"Transaction #{txn}\n" in p)
    assert f"Linked to Invoice {ia} (payment)" in pages[tx_page]
    row = next(line for line in section.splitlines() if f"#{txn} " in line and "Payment" in line)
    assert f"#{txn} {tx_page + 1} " in row
    # open at the year's end: A 220 - 110, B 110 - 50
    assert "Open invoices at the year's end" in section and "$170.00" in section
    # the audit event records the section's page range
    ev = env.auditor.get("/api/audit-events?action=REPORT_GENERATED").json()["items"][0]["after"]
    assert ev["invoices"] == 4 and ev["invoice_section"] == {"first_page": start + 1, "last_page": end + 1}
    assert "Invoices" in ev["module_sections"]


def test_invoice_numbers_are_accounted_for_and_the_tie_out_balances(env, base, rb):
    t = _text(env.bm.get("/api/reports/fy-close", params={"fiscal_year_id": base["fy"]["id"]}))
    assert "Invoice numbers" in t and "Invoices dated in this year 4" in t
    assert f"Voided: {_number(rb, 'void')} — Entered twice" in t
    assert f"Draft (never sent): {_number(rb, 'draft')}" in t
    # every payment (and its tax, on the same Invoiced Income budget here) is linked
    assert "Invoiced Income budgets, actual $160.00" in t and "Of which linked to invoices $160.00" in t
    assert "Not linked to an invoice $0.00" in t


def test_tie_out_lists_a_line_on_an_invoiced_income_budget_with_no_invoice(env, base, rb):
    # entered while the module was off: the register doesn't require a link then
    assert env.admin.put("/api/system/modules", {"invoices": False}).status_code == 200
    t = env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "7.00",
                                                 "description": "Cash at the door"}], date="2026-10-01")
    text = _text(env.bm.get("/api/reports/fy-close", params={"fiscal_year_id": base["fy"]["id"]}))
    assert "Not linked to an invoice $7.00" in text
    assert f"#{t['id']}" in text and "Cash at the door" in text


# ------------------------------------------------------------------ AC-RPT-MOD-005: the data decides, not the switch
def test_module_turned_off_keeps_its_section_with_a_note(env, base, rb):
    ia = _number(rb, "ia")
    assert env.admin.put("/api/system/modules", {"invoices": False}).status_code == 200
    t = _text(_audit(env, base["fy"]["id"]))
    assert "Start of invoices" in t and ia in t
    assert "Invoices (module currently off)" in t
    assert "The Invoices module is currently turned off" in t


# ------------------------------------------------------------------ AC-RPT-MOD-006: one account
def test_single_account_report_shows_only_that_accounts_invoices(env, base, rb):
    other = env.account(opening="0.00")
    env.txn(other["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "1.00"}], date="2026-09-01")
    none = _text(_audit(env, base["fy"]["id"], bank_account_id=other["id"]))
    assert "Start of invoices" not in none
    mine = _text(_audit(env, base["fy"]["id"], bank_account_id=rb["acct"]))
    assert "Start of invoices" in mine and _number(rb, "ia") in mine
    assert "Only the invoices with a register line in this report's account" in mine
    # the number check, tie-out and open list belong to the all-accounts report
    assert "Invoice numbers" not in mine and "Invoiced Income budgets, actual" not in mine
    assert "Open invoices at the year's end" not in mine


# ------------------------------------------------------------------ AC-RPT-MOD-007: a payment counts in its deposit's year
def test_invoice_dated_in_one_year_and_paid_in_the_next_is_in_both(app, env, base, rb):
    from fmpoc.models import Invoice
    with app.state.session_factory() as db:
        ws = db.get(Invoice, rb["ia"]).workspace_id
        # a "year" covering September only: A is dated 08-01 and paid 09-05 -> in, as an older invoice
        sept = NS(workspace_id=ws, start_date=dt.date(2026, 9, 1), end_date=dt.date(2026, 9, 30))
        rows = {r["invoice"].id: r for r in rm.invoice_data(db, ws, sept, None)["rows"]}
        assert rows[rb["ia"]]["dated_in_year"] is False and rows[rb["ia"]]["paid_in_year"] == 11000
        # a "year" covering August only: A is dated in it, its September payment is not counted there
        aug = NS(workspace_id=ws, start_date=dt.date(2026, 8, 1), end_date=dt.date(2026, 8, 31))
        rows = {r["invoice"].id: r for r in rm.invoice_data(db, ws, aug, None)["rows"]}
        assert rows[rb["ia"]]["dated_in_year"] is True and rows[rb["ia"]]["paid_in_year"] == 0
        assert rows[rb["ia"]]["open_at_end"] == 22000 and rb["ib"] not in rows


# ------------------------------------------------------------------ AC-RPT-MOD-008: number gaps
def test_invoice_and_receipt_number_gaps_are_listed():
    fy = NS(start_date=dt.date(2026, 7, 1), end_date=dt.date(2027, 6, 30))
    inv = lambda s, d, st="SENT": NS(seq=s, number=f"INV-{s:04d}", invoice_date=d, status=st)  # noqa: E731
    invs = [inv(1, dt.date(2026, 7, 2)), inv(2, dt.date(2026, 6, 30)), inv(4, dt.date(2026, 8, 1), "VOID")]
    n = rm.invoice_numbers(invs, fy)
    assert n["count"] == 2
    # 1 and 4 are this year's: 2 is dated in the previous year, 3 doesn't exist
    assert [i.number for i in n["elsewhere"]] == ["INV-0002"] and n["missing"] == [3]
    assert [i.number for i in n["voided"]] == ["INV-0004"]
    rec = lambda s, k="ORIGINAL", when=dt.datetime(2026, 9, 1): NS(year=2026, seq=s, kind=k, number=f"R-2026-{s:04d}",  # noqa: E731
                                                                   printed_at=when)
    printed = [rec(1), rec(1, "DUPLICATE"), rec(4)]
    everything = printed + [rec(2, when=dt.datetime(2026, 3, 1))]
    gaps = rm.receipt_numbers(printed, everything)
    assert gaps == ["R-2026-0002: printed 03/01/2026, in another Fiscal Year",
                    "2026 receipt #3: no receipt has this number — investigate."]


# ------------------------------------------------------------------ AC-RPT-MOD-009/010/011: donations
def test_donation_section_with_receipts_cancellations_and_links(env, don):
    base = don["base"]
    d = _ok(_create(env, don, [{"kind": "MONEY", "amount_cents": 25000, "purpose": "Roof",
                                "goods_cents": 2000, "goods_description": "Dinner"},
                               {"kind": "ITEM", "description": "Ladder", "amount_cents": 8000,
                                "item_received": True, "date_received": "2026-08-20"}]), 201)
    line = next(x for x in _ok(env.ru.get("/api/donations/awaiting-lines"))["items"] if x["donation_id"] == d["id"])
    t = _ok(env.ru.post("/api/donations/create-transaction", {
        "transaction": {"bank_account_id": base["acct"]["id"], "transaction_type": "DEPOSIT",
                        "transaction_date": "2026-08-21",
                        "allocations": [{"budget_id": base["inc_leaf"], "amount": "250.00", "description": "Gift"}]},
        "links": [line["id"]], "date_received": "2026-08-21"}), 201)
    r = _print(env, d["id"], confirmations=("EMPTY_VARIABLES",))
    assert r.status_code == 200, r.text
    receipt = r.headers["X-Receipt-Number"]
    c = _ok(_create(env, don, [{"kind": "MONEY", "amount_cents": 1000}], who="b"), 201)
    assert env.ru.post(f"/api/donations/{c['id']}/cancel", {"reason": "Pledge withdrawn"}).status_code == 200
    pages = _pages(env.bm.get("/api/reports/fy-close", params={"fiscal_year_id": base["fy"]["id"]}))
    text = "\n".join(pages)
    start = next(i for i, p in enumerate(pages) if p.startswith("Start of donations"))
    section = "\n".join(pages[start:])
    flat = section.replace("\n", " ")
    assert f"donation #{d['id']}" in section and "Roof" in section and "Ladder" in section
    assert "goods or services given in exchange: $20.00 (Dinner)" in flat
    assert "Receipts printed" in section and receipt in section
    assert "Pledge withdrawn" in section and "Cancelled by" in section
    # the deposit's page points at the donation, and the donation row points at that page
    tx_page = next(i for i, p in enumerate(pages) if f"Transaction #{t['id']}\n" in p)
    assert f"Donation #{d['id']} — Sample Donor One, receipt {receipt}" in pages[tx_page]
    assert any(f"#{t['id']} {tx_page + 1} $250.00" in ln for ln in section.splitlines())
    assert "Module sections Donations" in text


# ------------------------------------------------------------------ AC-RPT-MOD-012: permissions unchanged
def test_administrator_still_cannot_run_the_reports(env, base, rb):
    for url in ("/api/reports/audit", "/api/reports/fy-close"):
        assert env.admin.get(url, params={"fiscal_year_id": base["fy"]["id"]}).status_code == 403
