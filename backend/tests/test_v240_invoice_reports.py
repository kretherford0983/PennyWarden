"""2.4.0 (#255): invoice reports (Reports catalog, Invoices group), the overdue card and the Invoice Manager reminder.

BR-INV-RPT-001..004 / AC-INV-RPT-001..009 (recorded in docs/implementation-notes.md); regression for BR-003, BR-004,
BR-013/014 (close not blocked), BR-099, BR-108.
"""
from __future__ import annotations

import csv
import datetime as dt
import io

import pytest
from pypdf import PdfReader

from fmpoc.services import invoice_reports as rep_svc
from fmpoc.services.report_grouping import DEFAULTS
from fmpoc.services.report_prefs import REPORT_IDS

INV_IDS = ["inv-open", "inv-aging", "inv-statement", "inv-sales-tax", "inv-register", "inv-sales", "inv-activity"]


@pytest.fixture
def rb(env, base):
    """Two customers; A: 2 x Dues 100 + 10 % tax = 220 (2026-08-01, due 08-31); B: Hours 3 x 40 = 120, 10.00 off with a
    reason (2026-09-01, due 10-01); a draft and a void. Payments: A 110 on 09-05; B 50 on 09-10."""
    assert env.admin.put("/api/system/modules", {"invoices": True}).status_code == 200
    im = env.user("invmgr", "FINANCIAL", ["INVOICE_MANAGER"])
    env.bm.put(f"/api/budgets/{base['inc']['id']}/invoiced-income", {"invoiced_income": True})
    units = {u["name"]: u["id"] for u in im.get("/api/invoices/catalog/unit-types").json()}
    catg = im.post("/api/invoices/catalog/categories", {"name": "Membership"}).json()["id"]
    dues = im.post("/api/invoices/catalog/products", {"name": "Dues", "code": "D1", "unit_price": "100.00", "unit_type_id": units["Year"],
                                                     "budget_id": base["inc_leaf"], "taxable": True, "category_id": catg}).json()["id"]
    hours = im.post("/api/invoices/catalog/products", {"name": "Hall hours", "unit_price": "40.00", "unit_type_id": units["Hour"],
                                                      "budget_id": base["inc_leaf"]}).json()["id"]
    tax = im.post("/api/invoices/catalog/tax-rates", {"name": "State tax", "rate": "10", "budget_id": base["inc_leaf"]}).json()["id"]
    a = env.entity("Acme Club", client=im)["id"]
    b = env.entity("Bravo Group", client=im)["id"]

    def make(cust, date, lines, **kw):
        i = im.post("/api/invoices", {"customer_entity_id": cust, "invoice_date": date, "lines": lines, **kw})
        assert i.status_code == 201, i.text
        return i.json()["id"]
    ia = make(a, "2026-08-01", [{"product_id": dues, "quantity": "2"}], tax_rate_id=tax)
    ib_ = make(b, "2026-09-01", [{"product_id": hours, "quantity": "3", "discount_kind": "AMOUNT", "discount_value": "10.00",
                                  "discount_reason": "Regulars"}])
    draft = make(a, "2026-09-02", [{"product_id": hours, "quantity": "1"}])
    void = make(b, "2026-09-03", [{"product_id": hours, "quantity": "1"}])
    for i in (ia, ib_, void):
        assert im.post(f"/api/invoices/{i}/send").status_code == 200
    assert im.post(f"/api/invoices/{void}/void", {"reason": "Entered twice"}).status_code == 200
    acct = base["acct"]["id"]
    assert env.ru.post(f"/api/invoices/{ia}/payments", {"bank_account_id": acct, "amount": "110.00", "transaction_date": "2026-09-05"}).status_code == 201
    assert env.ru.post(f"/api/invoices/{ib_}/payments", {"bank_account_id": acct, "amount": "50.00", "transaction_date": "2026-09-10"}).status_code == 201
    return {"im": im, "a": a, "b": b, "ia": ia, "ib": ib_, "draft": draft, "void": void, "acct": acct, "dues": dues,
            "hours": hours, "tax": tax, "fy": base["fy"]}


def _r(client, rid, **p):
    r = client.get(f"/api/invoices/reports/{rid}", params=p)
    assert r.status_code == 200, r.text
    return r.json()


def _rows(rep, n=0):
    return rep["sections"][n]["rows"]


def _csv(client, rid, **p):
    r = client.get(f"/api/invoices/reports/{rid}", params={**p, "format": "csv"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    return list(csv.reader(io.StringIO(r.text)))


def _pdf_text(client, rid, **p):
    r = client.get(f"/api/invoices/reports/{rid}", params={**p, "format": "pdf"})
    assert r.status_code == 200 and r.content[:4] == b"%PDF", r.text[:200]
    return "".join(pg.extract_text() for pg in PdfReader(io.BytesIO(r.content)).pages)


def test_open_and_aging_to_the_cent(env, rb):
    """AC-INV-RPT-001: open balances and aging buckets match the invoices and payments, as screen, PDF and CSV; a
    payment dated after the as-of date doesn't count; drafts and voids are never open."""
    rep = _r(rb["im"], "inv-open", as_of="2026-10-15")
    rows = {r["number"]: r for r in _rows(rep)}
    assert len(rows) == 2
    a = next(r for r in rows.values() if r["customer"] == "Acme Club")
    b = next(r for r in rows.values() if r["customer"] == "Bravo Group")
    assert (a["total"], a["paid"], a["open"], a["days"]) == ("220.00", "110.00", "110.00", "45")
    assert (b["total"], b["paid"], b["open"], b["days"]) == ("110.00", "50.00", "60.00", "14")
    assert rep["sections"][0]["totals"]["open"] == "170.00"
    before = _r(env.bu, "inv-open", as_of="2026-09-06")          # B's payment (09-10) not yet received
    assert {r["customer"]: r["open"] for r in _rows(before)} == {"Acme Club": "110.00", "Bravo Group": "110.00"}
    only_b = _r(env.auditor, "inv-open", as_of="2026-10-15", customer_entity_id=rb["b"])
    assert [r["customer"] for r in _rows(only_b)] == ["Bravo Group"]
    ag = _r(env.ru, "inv-aging", as_of="2026-10-15")
    by = {r["customer"]: r for r in _rows(ag)}
    assert by["Acme Club"]["d31_60"] == "110.00" and by["Bravo Group"]["d1_30"] == "60.00"
    assert ag["sections"][0]["totals"]["total"] == "170.00"
    c = _csv(env.bm, "inv-aging", as_of="2026-10-15")
    assert c[0][:2] == ["Customer", "Invoices"] and c[-1][0] == "Total" and c[-1][-1] == "170.00"
    assert "Bravo Group" in _pdf_text(rb["im"], "inv-open", as_of="2026-10-15")


def test_customer_statement(env, rb):
    """AC-INV-RPT-002: one customer's activity in the period and open invoices; PDF only."""
    st = _r(rb["im"], "inv-statement", customer_entity_id=rb["a"], date_from="2026-08-01", date_to="2026-09-30")
    act = _rows(st, 0)
    assert [(r["what"].split(" ")[0], r["charge"], r["credit"]) for r in act] == [("Invoice", "220.00", ""), ("Payment", "", "110.00")]
    assert st["sections"][1]["totals"]["open"] == "110.00"
    assert all("Bravo" not in r["what"] for r in act)
    assert "Amount due" in _pdf_text(rb["im"], "inv-statement", customer_entity_id=rb["a"], date_from="2026-08-01", date_to="2026-09-30")
    r = rb["im"].get("/api/invoices/reports/inv-statement", params={"customer_entity_id": rb["a"], "date_from": "2026-08-01",
                                                                     "date_to": "2026-09-30", "format": "csv"})
    assert r.status_code == 422
    assert rb["im"].get("/api/invoices/reports/inv-statement", params={"customer_entity_id": 999999, "date_from": "2026-08-01",
                                                                        "date_to": "2026-09-30"}).status_code == 404


def test_sales_tax_charged_and_collected(env, rb):
    """AC-INV-RPT-003: tax charged on invoices dated in the period; tax collected = the tax part of the payments in the
    period, to the cent - equal to the register's tax allocations."""
    st = _r(env.bm, "inv-sales-tax", date_from="2026-07-01", date_to="2027-06-30")
    row = _rows(st)[0]
    assert row["rate"].startswith("State tax (10") and row["taxable"] == "200.00" and row["charged"] == "20.00"
    assert row["collected"] == "10.00"                       # 110 of 220 paid
    # the register's tax allocation for that payment
    inv = env.ru.get(f"/api/invoices/{rb['ia']}").json()
    tax_links = [x for x in inv["payments"]["links"] if "tax" in (x["budget"] or {}).get("label", "").lower() or x["amount"] == "10.00"]
    assert any(x["amount"] == "10.00" for x in tax_links)
    env.ru.post(f"/api/invoices/{rb['ia']}/payments", {"bank_account_id": rb["acct"], "amount": "110.00", "transaction_date": "2026-10-05"})
    st = _r(env.bm, "inv-sales-tax", date_from="2026-07-01", date_to="2027-06-30")
    assert _rows(st)[0]["collected"] == "20.00" == _rows(st)[0]["charged"]
    sept = _r(env.bm, "inv-sales-tax", date_from="2026-09-01", date_to="2026-09-30")
    assert _rows(sept)[0]["charged"] == "" or _rows(sept)[0]["charged"] == "0.00"
    assert _rows(sept)[0]["collected"] == "10.00"


def test_invoice_register_lists_every_invoice(env, rb):
    """AC-INV-RPT-004: every invoice in the range with status, total and revisions; status filter."""
    rb["im"].post(f"/api/invoices/{rb['ib']}/revise", {"reason": "Wrong hours"})
    rep = _r(env.auditor, "inv-register", date_from="2026-08-01", date_to="2026-09-30")
    st = {r["customer"] + r["invoice_date"]: (r["status"], r["total"], r["revisions"]) for r in _rows(rep)}
    assert len(_rows(rep)) == 4
    assert st["Acme Club2026-08-01"] == ("Partly paid", "220.00", "0")
    assert st["Bravo Group2026-09-01"][2] == "1" and st["Acme Club2026-09-02"][0] == "Draft"
    assert st["Bravo Group2026-09-03"][0] == "Void"
    voids = _r(env.auditor, "inv-register", date_from="2026-08-01", date_to="2026-09-30", status="VOID")
    assert len(_rows(voids)) == 1
    assert _csv(env.auditor, "inv-register", date_from="2026-08-01", date_to="2026-09-30")[0][0] == "Invoice"
    assert rb["im"].get("/api/invoices/reports/inv-register", params={"date_from": "2026-09-30", "date_to": "2026-08-01"}).status_code == 422
    assert rb["im"].get("/api/invoices/reports/inv-register").status_code == 422          # the period is required


def test_sales_by_product_category_budget_reconcile(env, rb):
    """AC-INV-RPT-005: totals reconcile to the issued invoices' lines (after discounts, before tax)."""
    p = _r(env.bm, "inv-sales", date_from="2026-08-01", date_to="2026-09-30")
    rows = {r["label"]: r for r in _rows(p)}
    assert rows["D1 Dues"]["qty"] == "2" and rows["D1 Dues"]["amount"] == "200.00"
    assert rows["Hall hours"]["gross"] == "120.00" and rows["Hall hours"]["discounts"] == "10.00" and rows["Hall hours"]["amount"] == "110.00"
    assert p["sections"][0]["totals"]["amount"] == "310.00"          # 220 - 20 tax + 110; no draft, no void
    c = _r(env.bm, "inv-sales", date_from="2026-08-01", date_to="2026-09-30", by="category")
    assert {r["label"]: r["amount"] for r in _rows(c)} == {"Membership": "200.00", "(no category)": "110.00"}
    b = _r(env.bm, "inv-sales", date_from="2026-08-01", date_to="2026-09-30", by="budget")
    assert [r["amount"] for r in _rows(b)] == ["310.00"]


def test_payments_writeoffs_discounts_refunds(env, rb):
    """AC-INV-RPT-006: reconciles to the invoice and payment data; self-approved write-offs are marked."""
    both = env.user("both", "FINANCIAL", ["INVOICE_MANAGER", "BUDGET_MANAGER"])
    both.post(f"/api/invoices/{rb['ib']}/write-off", {"reason": "Group disbanded"})
    assert both.post(f"/api/invoices/{rb['ib']}/write-off/decision", {"approve": True}).json()["status"] == "WRITTEN_OFF"
    env.ru.post(f"/api/invoices/{rb['ia']}/payments", {"bank_account_id": rb["acct"], "amount": "120.00",
                                                       "transaction_date": "2026-09-20", "confirm_overpayment": True})
    r = env.ru.post(f"/api/invoices/{rb['ia']}/refunds", {"bank_account_id": rb["acct"], "amount": "10.00", "transaction_date": "2026-09-25"})
    assert r.status_code == 201, r.text
    today = dt.date.today().isoformat()
    rep = _r(env.auditor, "inv-activity", date_from="2026-08-01", date_to=max(today, "2026-09-30"))
    types = [(x["type"], x["amount"]) for x in _rows(rep, 1)]
    assert ("Payment", "110.00") in types and ("Payment", "50.00") in types
    assert ("Overpayment", "10.00") in types and ("Refund", "-10.00") in types
    assert ("Discount (line)", "10.00") in types
    assert ("Write-off (self-approved)", "60.00") in types
    summary = {x["type"]: x["amount"] for x in _rows(rep, 0)}
    assert summary["Payment"] == "270.00" and summary["Write-off"] == "60.00"
    c = _csv(env.auditor, "inv-activity", date_from="2026-08-01", date_to=max(today, "2026-09-30"))
    assert c[0] == ["Date", "Type", "Invoice", "Customer", "Amount", "Detail"]
    assert any(row[4] == "-10.00" for row in c)             # a negative amount is not quoted as a formula
    # written off: no longer open
    assert all(x["customer"] != "Bravo Group" for x in _rows(_r(env.bm, "inv-open", as_of=today)))


def test_who_can_run_and_the_catalog(env, rb):
    """AC-INV-RPT-007/008: viewers IM, RU, BM, BU, Auditor; the Administrator is refused; module off refuses; every
    report is in the catalog's Invoices group and remembered like the others."""
    for rid in INV_IDS:
        p = {"customer_entity_id": rb["a"], "date_from": "2026-08-01", "date_to": "2026-09-30"}
        for c in (rb["im"], env.ru, env.bm, env.bu, env.auditor):
            assert c.get(f"/api/invoices/reports/{rid}", params=p).status_code == 200, (rid, c)
        assert env.admin.get(f"/api/invoices/reports/{rid}", params=p).status_code == 403
    assert env.admin.get("/api/invoices/overdue").status_code == 403
    assert set(INV_IDS) <= set(REPORT_IDS)
    for scheme, cats in DEFAULTS.items():
        inv = [c for c in cats if c["id"] == "invoices"]
        assert inv and inv[0]["reports"] == INV_IDS, scheme
    g = env.bm.get("/api/reports/grouping").json()
    assert next(c for c in g["categories"] if c["id"] == "invoices")["reports"] == INV_IDS
    r = rb["im"].post("/api/me/report-runs", {"report": "inv-aging", "params": {"as_of": "2026-10-15"}, "label": "as of 2026-10-15"})
    assert r.status_code == 200 and r.json()["recent"][0]["report"] == "inv-aging"
    env.admin.put("/api/system/modules", {"invoices": False})
    assert rb["im"].get("/api/invoices/reports/inv-aging").status_code == 404     # the module is off


def test_saved_grouping_gets_an_invoices_category(env, rb):
    """A scheme customized before 2.4.0 shows the new reports in an Invoices category (never lost)."""
    from fmpoc.services import report_grouping as rg
    cats = [{"id": c["id"], "name": c["name"], "reports": [x for x in c["reports"] if not x.startswith("inv-")]}
            for c in rg.DEFAULTS["PURPOSE"] if c["id"] != "invoices"]
    out = rg._complete(cats)
    assert out[-1]["name"] == "Invoices" and out[-1]["reports"] == INV_IDS


def test_overdue_card_and_invoice_manager_reminder(env, rb, monkeypatch):
    """AC-INV-RPT-009: the card for every invoice viewer; the reminder for Invoice Managers from due date + N (set by
    the Administrator, default 0, audited)."""
    monkeypatch.setattr(rep_svc, "today", lambda: dt.date(2026, 10, 3))
    lay = [{"key": "invoices", "visible": True}, {"key": "bank", "visible": False}]       # the section can be saved
    assert env.bu.put("/api/me/preferences", {"dashboard_layout": lay}).json()["dashboard_layout"][:2] == lay
    o = env.bu.get("/api/invoices/overdue").json()
    assert o["count"] == 2 and o["open"] == "170.00" and o["reminders"] == []      # not an Invoice Manager
    assert [x["days"] for x in o["items"]] == [33, 2]
    im = rb["im"].get("/api/invoices/overdue").json()
    assert im["reminder_days"] == 0 and len(im["reminders"]) == 2
    s = env.admin.get("/api/invoices/setup").json()
    assert s["overdue_reminder_days"] == 0
    r = env.admin.put("/api/invoices/setup", {"number_pattern": s["number_pattern"], "terms_days": s["terms_days"],
                                               "overdue_reminder_days": 5})
    assert r.status_code == 200 and r.json()["overdue_reminder_days"] == 5
    im = rb["im"].get("/api/invoices/overdue").json()
    assert [x["customer"] for x in im["reminders"]] == ["Acme Club"]          # B: due 10-01 + 5 not reached
    assert env.admin.put("/api/invoices/setup", {"number_pattern": s["number_pattern"], "terms_days": 30,
                                                  "overdue_reminder_days": 400}).status_code == 422
    ev = env.admin.get("/api/audit-events?action=INVOICE_SETUP_UPDATED").json()["items"]
    assert any((e.get("after") or e.get("new_values") or {}).get("overdue_reminder_days") == 5 or "overdue_reminder_days" in str(e) for e in ev)


def test_close_report_lists_open_invoices_without_blocking(env, rb, settings):
    """The Close report lists invoices open at the year's end for information (BR-013/014 unchanged)."""
    r = env.bm.get("/api/reports/fy-close", params={"fiscal_year_id": rb["fy"]["id"]})
    assert r.status_code == 200, r.text[:300]
    text = "".join(pg.extract_text() for pg in PdfReader(io.BytesIO(r.content)).pages)
    assert "Open invoices at the year's end" in text and "Bravo Group" in text
    audit = env.bm.get("/api/reports/audit", params={"fiscal_year_id": rb["fy"]["id"]})
    assert "Open invoices at the year" not in "".join(pg.extract_text() for pg in PdfReader(io.BytesIO(audit.content)).pages)
