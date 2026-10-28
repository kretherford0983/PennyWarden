"""2.2.0 (#256): year-end giving statements, the donor giving report and fundraiser donation buckets.

Decisions (Kyle, 2026-10-24): a statement covers the donation lines received in the calendar year (cancelled
donations, voided deposits and lines awaiting a deposit are left out); Register Users print, the other financial roles
and Auditors view, never Administrators (BR-003); one donor or all donors (optional minimum total) as one PDF; items by
description only, no value; numbered per year, kept and audited, Duplicate/Corrected like receipts. The donor report:
a column per year (up to 5) and a total, gifts, last gift, items and their internal value; PDF and CSV. A fundraiser
donation bucket pre-ticks Donation as a suggestion; the fundraiser lists its donation deposits without a receipt."""
from __future__ import annotations

import pytest

from test_v210_donations import donor, enable, setup, text  # noqa: F401


def _ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


ALL_OK = ["EMPTY_VARIABLES", "NOT_RECEIVED", "CORRECTED_STATEMENT", "NO_DONOR_ADDRESS", "PRINT_ALL"]


@pytest.fixture
def year(env, base):
    """Donor A: $250 deposited 2026-08-10, $50 marked on a deposit 2026-09-01, a TV received 2026-08-12 (estimate
    $400), a TV received 2025-12-30, plus a cancelled donation and a line awaiting a deposit. Donor B: $20."""
    enable(env)
    setup(env)
    a, b = donor(env), donor(env, "Sample Donor Two")

    def page(who, lines):
        return _ok(env.ru.post("/api/donations", {"donor_entity_id": who["id"], "details": "", "lines": lines}), 201)

    def deposit_from(d, amount, date):
        line = next(x for x in _ok(env.ru.get("/api/donations/awaiting-lines"))["items"] if x["donation_id"] == d["id"])
        return _ok(env.ru.post("/api/donations/create-transaction", {"transaction": {
            "bank_account_id": base["acct"]["id"], "transaction_type": "DEPOSIT", "transaction_date": date,
            "allocations": [{"budget_id": base["inc_leaf"], "amount": amount}]}, "links": [line["id"]]}), 201)

    d1 = page(a, [{"kind": "MONEY", "amount_cents": 25000, "purpose": "New flags"},
                  {"kind": "ITEM", "description": "Television, 55 inch", "amount_cents": 40000, "item_received": True,
                   "date_received": "2026-08-12"}])
    deposit_from(d1, "250.00", "2026-08-10")
    page(a, [{"kind": "ITEM", "description": "Old projector", "item_received": True, "item_no_value": True,
              "item_no_value_reason": "Donor values it", "date_received": "2025-12-30"}])
    cancelled = page(a, [{"kind": "MONEY", "amount_cents": 99900}])
    _ok(env.ru.post(f"/api/donations/{cancelled['id']}/cancel", {"reason": "Never given"}))
    page(a, [{"kind": "MONEY", "amount_cents": 77700}])                       # awaiting a deposit
    t = env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "50.00", "entity_id": a["id"],
                                                 "description": "Gift"}], date="2026-09-01")
    _ok(env.ru.put(f"/api/donations/transactions/{t['id']}/lines",
                   {"lines": [{"allocation_id": t["allocations"][0]["id"], "donation": True}]}))
    d2 = page(b, [{"kind": "MONEY", "amount_cents": 2000}])
    deposit_from(d2, "20.00", "2026-08-20")
    return {"a": a, "b": b, "base": base, "d1": d1}


def test_statement_lists_the_years_received_lines_and_numbers_like_receipts(env, year):
    a = year["a"]
    s = _ok(env.bu.get("/api/donations/statements?year=2026"))
    row = next(x for x in s["items"] if x["donor_id"] == a["id"])
    assert row["total"] == "$300.00" and row["gifts"] == 3 and row["items"] == 1 and row["next_kind"] == "ORIGINAL"
    d = _ok(env.bu.get(f"/api/donations/statements/2026/donors/{a['id']}"))
    assert [x["amount"] for x in d["rows"]] == ["$250.00", None, "$50.00"]       # the item has no value
    # Register Users print; the others view; Administrators never see it (BR-003)
    url = f"/api/donations/statements/2026/donors/{a['id']}"
    for c in (env.bu, env.bm, env.auditor):
        assert c.post(url, {"confirmations": ALL_OK}).status_code == 403
    assert env.admin.get("/api/donations/statements?year=2026").status_code == 403
    assert env.admin.get(url).status_code == 403
    r = env.ru.post(url, {"confirmations": ALL_OK})
    assert r.status_code == 200, r.text
    assert r.headers["X-Statement-Number"] == "S-2026-0001" and r.headers["X-Statement-Kind"] == "ORIGINAL"
    t = text(r.content)
    assert "Year-End Giving Statement 2026" in t and "Television, 55 inch" in t and "$300.00" in t
    assert "$400.00" not in t and "$999.00" not in t and "$777.00" not in t and "Old projector" not in t
    assert "does not assign a monetary value to donated property" in t and "12-3456789" in t
    # the same content again: a duplicate with the same number; kept and viewable by the read-only roles
    r = env.ru.post(url, {"confirmations": ALL_OK})
    assert r.headers["X-Statement-Kind"] == "DUPLICATE" and r.headers["X-Statement-Number"] == "S-2026-0001"
    st = _ok(env.bu.get(url))["statements"]
    assert [x["kind"] for x in st] == ["ORIGINAL", "DUPLICATE"]
    doc = env.auditor.get(f"/api/donations/statements/printed/{st[0]['id']}/document")
    assert doc.status_code == 200 and "S-2026-0001" in text(doc.content)
    assert env.admin.get(f"/api/donations/statements/printed/{st[0]['id']}/document").status_code == 403
    # a change in the year: the next print is a corrected statement (asked first) with a new number
    _ok(env.ru.post("/api/donations", {"donor_entity_id": a["id"], "details": "", "lines": [
        {"kind": "ITEM", "description": "Folding tables", "item_received": True, "date_received": "2026-10-01",
         "item_no_value": True, "item_no_value_reason": "Donor values it"}]}), 201)
    r = env.ru.post(url, {"confirmations": ["EMPTY_VARIABLES"]})
    assert r.status_code == 409 and "CORRECTED_STATEMENT" in r.text
    r = env.ru.post(url, {"confirmations": ALL_OK})
    assert r.headers["X-Statement-Kind"] == "CORRECTED" and r.headers["X-Statement-Number"] == "S-2026-0002"
    assert "replaces statement S-2026-0001" in text(r.content)
    ev = _ok(env.auditor.get("/api/audit-events?action=DONATION_STATEMENT_PRINTED"))["items"]
    assert len(ev) == 3 and ev[0]["before"] is None
    # another year is its own statement; a donor with nothing received is refused
    r = env.ru.post(f"/api/donations/statements/2025/donors/{a['id']}", {"confirmations": ALL_OK})
    assert r.headers["X-Statement-Number"] == "S-2025-0001" and "Old projector" in text(r.content)
    assert env.ru.post(f"/api/donations/statements/2024/donors/{a['id']}",
                       {"confirmations": ALL_OK}).status_code == 409


def test_all_donors_with_a_minimum_total_as_one_pdf(env, year):
    url = "/api/donations/statements/2026/print-all"
    r = env.ru.post(url, {"min_cents": 10000})
    assert r.status_code == 409 and "PRINT_ALL" in r.text
    r = env.ru.post(url, {"min_cents": 10000, "confirmations": ALL_OK})
    assert r.status_code == 200, r.text
    assert r.headers["X-Statement-Count"] == "1" and "Sample Donor One" in text(r.content)
    r = env.ru.post(url, {"min_cents": 0, "confirmations": ALL_OK})
    assert r.headers["X-Statement-Count"] == "2"
    t = text(r.content)
    assert "Sample Donor Two" in t and "S-2026-0002" in t and "DUPLICATE" in t      # A again: same content
    assert env.ru.post(url, {"min_cents": 10**9, "confirmations": ALL_OK}).status_code == 409
    assert env.bu.post(url, {"min_cents": 0, "confirmations": ALL_OK}).status_code == 403


def test_statement_template_setup_preview_and_envelope(env, year):
    """The statement letter in Donations Setup (sample data only); the table prints even when the letter has no
    {DONATION_TABLE}; the statement's envelope is kept with it."""
    cfg = _ok(env.admin.get("/api/donations/setup"))["config"]
    bad = env.admin.put("/api/donations/setup", {"config": {**cfg, "statement_body": "Thanks {RECEIPT_NO}"}})
    assert bad.status_code == 422
    _ok(env.admin.put("/api/donations/setup", {"config": {**cfg, "statement_body": "Thank you for {YEAR}: {TOTAL}."}}))
    p = env.admin.post("/api/donations/setup/statement-preview", {})
    assert p.status_code == 200 and "SAMPLE DONOR" in text(p.content) and "Sample Donor One" not in text(p.content)
    r = env.ru.post(f"/api/donations/statements/2026/donors/{year['a']['id']}", {"confirmations": ALL_OK})
    t = text(r.content)
    assert "300.00" in t and "Date received" in t and "New flags" in t
    sid = int(r.headers["X-Statement-Id"])
    e = _ok(env.admin.post("/api/checks/documents", {"kind": "ENVELOPE", "feature": "DONATIONS"}), 201)
    r = env.ru.post(f"/api/donations/statements/printed/{sid}/envelope", {"document_id": e["id"]})
    assert r.status_code == 200, r.text
    assert "Sample Donor One" in text(r.content)


def test_donor_giving_report(env, year):
    a = year["a"]
    rep = _ok(env.bu.get("/api/donations/report?start_year=2025&end_year=2026"))
    row = next(x for x in rep["rows"] if x["donor_id"] == a["id"])
    assert row["years"] == {"2025": 0, "2026": 30000} and row["total_cents"] == 30000 and row["gifts"] == 4
    assert row["items"] == 2 and row["item_value_cents"] == 40000 and row["last_gift"] == "2026-09-01"
    assert rep["totals"]["total_cents"] == 32000
    assert [x["donor_id"] for x in _ok(env.bu.get(
        "/api/donations/report?start_year=2025&end_year=2026&min_cents=10000"))["rows"]] == [a["id"]]
    assert len(_ok(env.bu.get(f"/api/donations/report?start_year=2026&end_year=2026&donor_id={year['b']['id']}"))
               ["rows"]) == 1
    assert env.bu.get("/api/donations/report?start_year=2020&end_year=2026").status_code == 422     # at most 5 years
    assert env.admin.get("/api/donations/report?start_year=2026&end_year=2026").status_code == 403
    csv_r = env.auditor.get("/api/donations/report?start_year=2025&end_year=2026&format=csv&detail=true")
    assert csv_r.status_code == 200 and csv_r.headers["content-type"].startswith("text/csv")
    body = csv_r.content.decode("utf-8-sig")
    assert "Sample Donor One,0.00,300.00,300.00,4,2026-09-01,2,400.00" in body and "Television, 55 inch" in body
    pdf = env.bm.get("/api/donations/report?start_year=2025&end_year=2026&format=pdf&detail=true")
    assert pdf.status_code == 200 and "Donor giving report 2025" in text(pdf.content)
    assert _ok(env.auditor.get("/api/audit-events?action=REPORT_GENERATED"))["items"]


def test_fundraiser_donation_bucket_suggests_and_lists_unreceipted(env, base):
    enable(env)
    setup(env)
    assert env.admin.put("/api/system/modules", {"fundraisers": True}).status_code == 200
    a = donor(env)
    t = env.txn(base["acct"]["id"], "DEPOSIT", [
        {"budget_id": base["inc_leaf"], "amount": "60.00", "entity_id": a["id"], "description": "Gala gift"},
        {"budget_id": base["inc_leaf"], "amount": "40.00", "entity_id": a["id"], "description": "Tickets"}],
        date="2026-09-14")
    f = _ok(env.bm.post("/api/fundraisers", {"name": "Gala", "start_date": "2026-09-12",
                                             "budget_ids": [base["inc"]["id"]]}), 201)
    f = _ok(env.bm.post(f"/api/fundraisers/{f['id']}/buckets", {"name": "Donations", "is_donation": True}), 201)
    bucket = f["buckets"]["items"][0]
    assert bucket["is_donation"] is True
    line = {x["description"]: x["allocation_id"] for x in f["lines"]}
    _ok(env.ru.put(f"/api/fundraisers/{f['id']}/lines/{line['Gala gift']}",
                   {"buckets": [{"bucket_id": bucket["id"], "amount": "60.00"}]}))
    out = _ok(env.ru.get(f"/api/donations/transactions/{t['id']}"))
    sug = {x["description"]: x["suggested"] for x in out["lines"]}
    assert sug == {"Gala gift": True, "Tickets": False}            # a suggestion only: nothing is marked yet
    assert not any(x["donation"] for x in out["lines"])
    un = _ok(env.bu.get(f"/api/donations/fundraisers/{f['id']}/unreceipted"))
    assert un["has_donation_buckets"] and un["items"][0]["transaction_id"] == t["id"]
    assert un["items"][0]["states"] == ["NOT_MARKED"] and un["items"][0]["amount"] == "$60.00"
    _ok(env.ru.put(f"/api/donations/transactions/{t['id']}/lines",
                   {"lines": [{"allocation_id": line["Gala gift"], "donation": True}]}))
    assert _ok(env.bu.get(f"/api/donations/fundraisers/{f['id']}/unreceipted"))["items"][0]["states"] == ["NOT_PRINTED"]
    r = env.ru.post(f"/api/donations/transactions/{t['id']}/receipts",
                    {"donor_entity_id": a["id"], "confirmations": ["EMPTY_VARIABLES"]})
    assert r.status_code == 200, r.text
    assert _ok(env.bu.get(f"/api/donations/fundraisers/{f['id']}/unreceipted"))["items"] == []
    assert env.admin.get(f"/api/donations/fundraisers/{f['id']}/unreceipted").status_code == 403
    # the bucket option can be switched off again (audited with the bucket)
    f2 = _ok(env.bm.put(f"/api/fundraisers/{f['id']}/buckets/{bucket['id']}",
                        {"name": "Donations", "is_donation": False}))
    assert f2["buckets"]["items"][0]["is_donation"] is False
