"""2.2.0 (#348): a comparison to a date before any data uses the earliest available data, not $0 - unless the account
was opened after that date (Account opened). The report notes on substituted starting values are off by default; the
review screen always marks them."""
import datetime as dt
import io

import pytest
from pypdf import PdfReader

TODAY = dt.date.today()


def _d(days):
    return (TODAY - dt.timedelta(days=days)).isoformat()


@pytest.fixture
def brokerage(env, base):
    r = env.bm.post("/api/bank-accounts", {"account_name": "Brokerage", "financial_institution_entity_id": env.fi()["id"],
                                           "account_type": "INVESTMENT", "account_number": "5550001234",
                                           "register_enabled": False, "current_balance": "2000.00"})
    assert r.status_code == 201, r.text
    a = r.json()
    r = env.bm.post(f"/api/bank-accounts/{a['id']}/balance", {"current_balance": "1800.00", "as_of_date": _d(30)})
    assert r.status_code in (200, 201), r.text
    return a


def _body(base, compare, **kw):
    return {"title": "T", "date_from": _d(5), "date_to": None, "bank_account_ids": [base["acct"]["id"]],
            "include_balances": True, "compare_date": compare, **kw}


def _review(env, body):
    r = env.bu.post("/api/reports/financial-flow/review", body)
    assert r.status_code == 200, r.text
    return r.json()["balances"]


def _inv(b):
    return {s["key"]: s for s in b["sections"]}["INVESTMENTS"]["accounts"][0]


def _pdf(env, body):
    r = env.bu.post("/api/reports/financial-flow", body)
    assert r.status_code == 200, r.text
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)


def test_before_the_first_entry_uses_the_earliest_entry(env, base, brokerage):
    b = _review(env, _body(base, _d(60)))
    i = _inv(b)
    assert (i["compare_balance"], i["change"]) == ("1800.00", "200.00")       # not $0 / +$2,000
    assert i["compare_substituted"] == _d(30)
    s = [x for x in b["substitutions"] if x["id"] == brokerage["id"]]
    assert s and s[0]["text"] == f"Brokerage: starting balance is the first recorded balance, {_d(30)} (no data on {_d(60)})."
    assert "Update balance" in s[0]["hint"]
    # a date with data is not substituted
    i = _inv(_review(env, _body(base, _d(20))))
    assert i["compare_balance"] == "1800.00" and i["compare_substituted"] is None


def test_register_before_its_opening_date_uses_the_opening_balance(env, base):
    acct = env.bm.get(f"/api/bank-accounts/{base['acct']['id']}").json()
    opening = dt.date.fromisoformat(acct["opening_balance_date"])
    compare = (opening - dt.timedelta(days=40)).isoformat()
    b = _review(env, _body(base, compare))
    chk = {s["key"]: s for s in b["sections"]}["CHECKING"]["accounts"][0]
    assert chk["compare_balance"] == acct["opening_balance"] and chk["compare_substituted"] == opening.isoformat()
    assert "Opening Balance Date" in b["substitutions"][0]["hint"]


def test_account_opened_later_starts_at_zero(env, base, brokerage):
    r = env.bm.patch(f"/api/bank-accounts/{brokerage['id']}", {"account_opened_date": _d(45)})
    assert r.status_code == 200, r.text
    assert r.json()["account_opened_date"] == _d(45)
    i = _inv(_review(env, _body(base, _d(60))))
    assert (i["compare_balance"], i["change"], i["compare_substituted"]) == ("0.00", "2000.00", None)
    # on or after Account opened, the earliest data again
    i = _inv(_review(env, _body(base, _d(40))))
    assert i["compare_balance"] == "1800.00" and i["compare_substituted"] == _d(30)
    # audited, can't be in the future, can be cleared
    ev = [e for e in env.auditor.get("/api/audit-events").json()["items"] if e["action"] == "BANK_ACCOUNT_UPDATED"]
    assert any("account_opened_date" in str(e.get("after") or e.get("details") or e) for e in ev)
    r = env.bm.patch(f"/api/bank-accounts/{brokerage['id']}", {"account_opened_date": (TODAY + dt.timedelta(days=1)).isoformat()})
    assert r.status_code == 422 and "future" in r.text
    r = env.bm.patch(f"/api/bank-accounts/{brokerage['id']}", {"account_opened_date": None})
    assert r.status_code == 200 and r.json()["account_opened_date"] is None


def test_account_opened_after_the_through_date_is_not_listed(env, base, brokerage):
    env.bm.patch(f"/api/bank-accounts/{brokerage['id']}", {"account_opened_date": _d(1)})
    b = _review(env, {**_body(base, None), "date_to": _d(3), "date_from": _d(10)})
    assert {s["key"]: s for s in b["sections"]}["INVESTMENTS"]["accounts"] == []


def test_pdf_notes_off_by_default(env, base, brokerage):
    note = f"Brokerage: starting balance is the first recorded balance, {_d(30)}"
    t = _pdf(env, _body(base, _d(60)))
    assert "$1,800.00" in t and note not in t
    t = _pdf(env, _body(base, _d(60), show_substitution_notes=True))
    assert note in t.replace("\n", " ")


def test_charts_no_value_before_account_opened(env, base):
    fy = base["fy"]
    start = dt.date.fromisoformat(fy["start_date"])
    if TODAY < start + dt.timedelta(days=62):
        pytest.skip("needs two months of the fiscal year behind us")
    opened = (start + dt.timedelta(days=40)).isoformat()
    a = env.account(opening="10.00", account_name="Later")
    r = env.bm.patch(f"/api/bank-accounts/{a['id']}", {"account_opened_date": opened})
    assert r.status_code == 200, r.text
    d = env.bu.get(f"/api/dashboard/charts?fiscal_year_id={fy['id']}").json()
    row = next(x for x in d["balances"]["accounts"] if x["id"] == a["id"])
    assert row["values"][0] is None and row["values"][1] is not None
