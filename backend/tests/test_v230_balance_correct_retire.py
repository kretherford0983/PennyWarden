"""2.3.0 build 3 (#391): bank account balance history - Correct and Retire an entry (reason required, audited, never
deleted), backfill before the first Fiscal Year (even before the opening balance date), and changes inside a Closed
Fiscal Year by Budget Admins only (confirmed, with a reason, its own audit event, shown as "Balance changed after
close" on the Fiscal Year and in its report)."""
import datetime as dt
import io

import pytest
from pypdf import PdfReader

PAST = ("2026", "2025-07-01", "2026-06-30")       # the first Fiscal Year in PennyWarden here


@pytest.fixture
def ba(env):
    return env.user("budgetadmin", "FINANCIAL", ["BUDGET_MANAGER", "BUDGET_ADMIN"])


@pytest.fixture
def setup(env):
    fy = env.fy(*PAST)
    r = env.bm.post("/api/bank-accounts", {"account_name": "Brokerage", "financial_institution_entity_id": env.fi()["id"],
                                           "account_type": "INVESTMENT", "account_number": "5550001234",
                                           "register_enabled": False, "current_balance": "1000.00",
                                           "opening_balance": "1000.00", "opening_balance_date": "2025-09-01"})
    assert r.status_code == 201, r.text
    return {"fy": fy, "acct": r.json()}


def _bal(c, a, value, as_of, reason=None, confirmations=None):
    return c.post(f"/api/bank-accounts/{a['id']}/balance", {"current_balance": value, "as_of_date": as_of, "reason": reason,
                                                             "confirmations": confirmations or []})


def _hist(c, a):
    r = c.get(f"/api/bank-accounts/{a['id']}/balance-history")
    assert r.status_code == 200, r.text
    return r.json()


def _entry(c, a, as_of):
    return next(x for x in _hist(c, a) if x["as_of_date"] == as_of and not x["retired"])


def _current(c, a):
    return c.get(f"/api/bank-accounts/{a['id']}").json()["current_balance"]


def _correct(c, a, e, **body):
    return c.post(f"/api/bank-accounts/{a['id']}/balance-history/{e['id']}/correct", {"confirmations": [], **body})


def _retire(c, a, e, **body):
    return c.post(f"/api/bank-accounts/{a['id']}/balance-history/{e['id']}/retire", {"confirmations": [], **body})


def _close(env, fy_id):
    env.approve(fy_id)
    env.fy_doc(fy_id, "AUDIT_SIGNOFF")
    r = env.bm.post(f"/api/fiscal-years/{fy_id}/close", {"confirm_reviewed": True})
    assert r.status_code == 200, r.text


def _today():
    return dt.date.today().isoformat()     # computed when the check runs (CI can cross midnight UTC)


def test_correct_amount_and_date_reason_required_and_audited(env, setup):
    a = setup["acct"]
    assert _bal(env.bm, a, "1500.00", _today(), "typo").status_code == 200       # fat-fingered (entered last today)
    assert _current(env.bm, a) == "1500.00"
    e = next(x for x in _hist(env.bm, a) if x["balance"] == "1500.00")
    assert _correct(env.bm, a, e, balance="1050.00").status_code == 422             # no reason
    assert _correct(env.bm, a, e, balance="1500.00", reason="same").status_code == 422   # nothing changes
    r = _correct(env.bm, a, e, balance="1050.00", reason="typed 1500 for 1050")
    assert r.status_code == 200, r.text
    assert r.json()["account"]["current_balance"] == "1050.00"                      # recalculated at once
    x = next(x for x in _hist(env.bm, a) if x["id"] == e["id"])
    assert x["balance"] == "1050.00" and x["corrected"]["previous_balance"] == "1500.00"
    assert x["corrected"]["reason"] == "typed 1500 for 1050" and x["corrected"]["by"]
    # a wrong date: moving it back makes the other entry the current balance again
    assert _bal(env.bm, a, "2000.00", _today(), "wrong date").status_code == 200
    assert _current(env.bm, a) == "2000.00"
    w = next(x for x in _hist(env.bm, a) if x["balance"] == "2000.00")
    r = _correct(env.bm, a, w, as_of_date="2026-09-20", reason="statement was September")
    assert r.status_code == 200 and r.json()["account"]["current_balance"] == "1050.00"
    ev = env.auditor.get("/api/audit-events?action=BANK_ACCOUNT_BALANCE_CORRECTED").json()["items"]
    assert ev and ev[0]["before"]["entry"]["as_of_date"] == _today() and ev[0]["after"]["entry"]["as_of_date"] == "2026-09-20"
    assert ev[0]["after"]["reason"] == "statement was September"


def test_retire_takes_an_entry_out_but_keeps_it_listed(env, setup):
    a = setup["acct"]
    _bal(env.bm, a, "9999.00", _today(), "fat finger")
    assert _current(env.bm, a) == "9999.00"
    e = next(x for x in _hist(env.bm, a) if x["balance"] == "9999.00")
    assert _retire(env.bm, a, e).status_code == 422                                  # reason required
    r = _retire(env.bm, a, e, reason="duplicate, wrong amount")
    assert r.status_code == 200 and r.json()["account"]["current_balance"] == "1000.00"
    h = _hist(env.bm, a)
    counted = [x for x in h if not x["retired"]]
    gone = [x for x in h if x["retired"]]
    assert [x["balance"] for x in gone] == ["9999.00"] and gone[0]["retired"]["reason"] == "duplicate, wrong amount"
    assert all(x["balance"] != "9999.00" for x in counted)
    assert _retire(env.bm, a, e, reason="again").status_code == 409                  # already retired
    assert _correct(env.bm, a, e, balance="1.00", reason="x").status_code == 409
    # the only counted entry can't be retired
    only = counted[0]
    r = _retire(env.bm, a, only, reason="no")
    assert r.status_code == 409 and r.json()["error"]["code"] == "LAST_BALANCE_ENTRY"
    assert env.auditor.get("/api/audit-events?action=BANK_ACCOUNT_BALANCE_RETIRED").json()["items"]


def test_backfill_before_the_first_fiscal_year_even_before_the_opening_date(env, setup):
    a = setup["acct"]
    # inside a PennyWarden year, before the opening balance date: refused as before
    r = _bal(env.bm, a, "800.00", "2025-08-01")
    assert r.status_code == 422 and r.json()["error"]["errors"][0]["field"] == "as_of_date"
    # before the first Fiscal Year: allowed, marked entered
    assert _bal(env.bm, a, "700.00", "2024-12-31", "old statement").status_code == 200
    e = _entry(env.bm, a, "2024-12-31")
    assert e["entered"] is True and _entry(env.bm, a, _hist(env.bm, a)[0]["as_of_date"])["entered"] is False
    assert _correct(env.bm, a, e, balance="725.00", as_of_date="2024-06-30", reason="the June statement").status_code == 200
    # correcting a date into a PennyWarden year before the opening date is refused
    e = _entry(env.bm, a, "2024-06-30")
    assert _correct(env.bm, a, e, as_of_date="2025-08-01", reason="x").status_code == 422


def test_closed_year_budget_managers_refused_budget_admins_confirm(env, setup, ba):
    a, fy = setup["acct"], setup["fy"]
    assert _bal(env.bm, a, "1200.00", "2025-12-31", "year end").status_code == 200
    _close(env, fy["id"])
    e = _entry(env.bm, a, "2025-12-31")
    # Budget Managers: refused for add, correct, retire and for moving a date into the closed year
    for r in (_bal(env.bm, a, "1.00", "2026-01-31", "x"), _correct(env.bm, a, e, balance="1250.00", reason="x"),
              _retire(env.bm, a, e, reason="x")):
        assert r.status_code == 409 and r.json()["error"]["code"] == "FISCAL_YEAR_CLOSED"
    latest = _entry(env.bm, a, _hist(env.bm, a)[0]["as_of_date"])
    assert _correct(env.bm, a, latest, as_of_date="2026-01-15", reason="x").json()["error"]["code"] == "FISCAL_YEAR_CLOSED"
    # Budget Admins: a reason and an explicit confirmation naming the closed year
    r = _correct(ba, a, e, balance="1250.00")
    assert r.status_code == 422
    r = _correct(ba, a, e, balance="1250.00", reason="statement said 1,250")
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    w = r.json()["error"]["warnings"][0]
    assert w["code"] == "CLOSED_FISCAL_YEAR" and "FY2026" in w["message"]
    assert _entry(env.bm, a, "2025-12-31")["balance"] == "1200.00"                    # nothing changed
    r = _correct(ba, a, e, balance="1250.00", reason="statement said 1,250", confirmations=["CLOSED_FISCAL_YEAR"])
    assert r.status_code == 200, r.text
    assert _bal(ba, a, "1300.00", "2026-03-31", "missing quarter", ["CLOSED_FISCAL_YEAR"]).status_code == 200
    # its own audit event, flagged with the year
    ev = env.auditor.get("/api/audit-events?action=BANK_ACCOUNT_BALANCE_CHANGED_AFTER_CLOSE").json()["items"]
    assert len(ev) == 2 and all(x["after"]["closed_fiscal_years"] == ["FY2026"] for x in ev)
    assert not env.auditor.get("/api/audit-events?action=BANK_ACCOUNT_BALANCE_CORRECTED").json()["items"]
    # shown on the Fiscal Year and in its report
    d = env.bu.get(f"/api/fiscal-years/{fy['id']}").json()["balance_changes_after_close"]
    assert [x["action"] for x in d] == ["CORRECT", "ADD"]
    assert d[0]["before"]["balance"] == "1200.00" and d[0]["after"]["balance"] == "1250.00"
    assert d[0]["reason"] == "statement said 1,250" and d[0]["changed_by"] and "Brokerage" in d[0]["account"]
    pdf = env.auditor.get(f"/api/reports/audit?fiscal_year_id={fy['id']}")
    text = " ".join(" ".join((p.extract_text() or "").split()) for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Balance changed after close" in text and "statement said 1,250" in text


def test_who_may_and_object_checks(env, setup, base):
    a = setup["acct"]
    _bal(env.bm, a, "1100.00", "2026-10-02", "x")
    e = _entry(env.bm, a, "2026-10-02")
    for c in (env.bu, env.ru, env.auditor, env.admin):                # Administrators refused (BR-003), Auditors read-only
        assert _correct(c, a, e, balance="1.00", reason="x").status_code == 403
        assert _retire(c, a, e, reason="x").status_code == 403
    assert env.auditor.get(f"/api/bank-accounts/{a['id']}/balance-history").status_code == 200
    # an entry of another account, a register account
    other = env.bm.post("/api/bank-accounts", {"account_name": "CD", "financial_institution_entity_id": env.fi()["id"],
                                               "account_type": "CERTIFICATE_OF_DEPOSIT", "account_number": "5550009999",
                                               "register_enabled": False, "current_balance": "5.00"}).json()
    assert _correct(env.bm, other, e, balance="1.00", reason="x").status_code == 404
    assert _retire(env.bm, base["acct"], e, reason="x").status_code in (404, 409)
    # mass assignment: unknown fields are refused
    r = env.bm.post(f"/api/bank-accounts/{a['id']}/balance-history/{e['id']}/correct",
                    {"balance": "1.00", "reason": "x", "retired_at": "2026-01-01"})
    assert r.status_code == 422
