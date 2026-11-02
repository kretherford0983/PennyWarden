"""2.1.0 (#257): the Budget Prep report - every budget of a Fiscal Year with its linked history (#89), the year-to-date
actuals, an optional projection with per-user, per-budget choices, and the next year's continuing budget. Budget
Managers only (decided 2026-10-20); PDF (landscape), CSV and JSON."""
from __future__ import annotations

import csv
import datetime as dt
import io
from fractions import Fraction

import pytest
from pypdf import PdfReader

from fmpoc.services import budget_planning as bp

AS_OF = "2026-09-30"     # three whole months into FY2027 (Jul-Jun)


def _link(env, b, target):
    r = env.bm.patch(f"/api/budgets/{b['id']}", {"continues_budget_id": target})
    assert r.status_code == 200, r.text


@pytest.fixture
def hist(env, base):
    """FY2026 (renumbered 0900 Operations, with actuals), FY2027 = base (Operations with Travel + Other), FY2028 draft."""
    f26 = env.fy("2026", "2025-07-01", "2026-06-30")
    ops26 = env.budget(f26["id"], "0900", "Operations", "EXPENSE", "900.00")
    don26 = env.budget(f26["id"], "4000", "Donations", "INCOME", "4000.00")
    _link(env, base["exp"], ops26["id"])
    _link(env, base["inc"], don26["id"])
    sel26 = {o["label"]: o["id"] for o in env.selectable(f26["id"], "WITHDRAWAL")}
    a = base["acct"]["id"]
    env.txn(a, "WITHDRAWAL", [{"budget_id": sel26["0900 Operations"], "amount": "450.00"}], date="2026-01-15")
    trav = env.budget(base["fy"]["id"], "01", "Travel", amount="40000.00", parent=base["exp"]["id"])
    sel = {o["label"]: o["id"] for o in env.selectable(base["fy"]["id"], "WITHDRAWAL")}
    env.txn(a, "WITHDRAWAL", [{"budget_id": trav["id"], "amount": "300.00"}], date="2026-08-01")
    env.txn(a, "WITHDRAWAL", [{"budget_id": sel["1000-00 Other"], "amount": "60.00"}], date="2026-08-02")
    env.txn(a, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "1500.00"}], date="2026-08-03")
    env.txn(a, "WITHDRAWAL", [{"budget_id": trav["id"], "amount": "25.00"}], date="2026-10-05")   # after the report date
    f28 = env.fy("2028", "2027-07-01", "2028-06-30")
    ops28 = env.budget(f28["id"], "1100", "Operations", "EXPENSE", "110000.00")
    _link(env, ops28, base["exp"]["id"])
    return {"f26": f26, "ops26": ops26, "trav": trav, "f28": f28, "ops28": ops28, "other": sel["1000-00 Other"]}


def rep(env, base, client=None, **q):
    q = {"fiscal_year_id": base["fy"]["id"], "as_of": AS_OF, **q}
    r = (client or env.bm).get("/api/reports/budget-prep", params={k: str(v).lower() if isinstance(v, bool) else v
                                                                   for k, v in q.items()})
    assert r.status_code == 200, r.text
    return r.json() if q.get("format", "json") == "json" else r


def row(report, rid):
    return next(r for s in ("income", "expense") for r in report[s] if r["id"] == rid)


# ------------------------------------------------------------------ projection rule
def test_months_and_projection_rule():
    fy = type("F", (), {"start_date": dt.date(2026, 7, 1), "end_date": dt.date(2027, 6, 30)})()
    assert bp.months_between(fy.start_date, dt.date(2027, 7, 1)) == 12
    b = bp.basis(fy, dt.date(2026, 9, 30))
    assert b["state"] == "PROJECT" and b["elapsed"] == 3
    assert bp.project(30000, b) == 120000
    # partial month: 15 of 31 days of October elapsed
    b = bp.basis(fy, dt.date(2026, 10, 15))
    assert b["elapsed"] == 3 + Fraction(15, 31)
    assert bp.project(10000, b) == round(10000 * 12 / (3 + 15 / 31))
    # less than a month: too early; on or after the last day: the actual is final
    assert bp.basis(fy, dt.date(2026, 7, 20))["state"] == "TOO_EARLY"
    assert bp.project(500, bp.basis(fy, dt.date(2026, 7, 20))) is None
    assert bp.project(777, bp.basis(fy, dt.date(2027, 6, 30))) == 777
    # an end-of-month start: months are counted to the same day (clamped) of the next month
    fe = type("F", (), {"start_date": dt.date(2026, 1, 31), "end_date": dt.date(2027, 1, 30)})()
    assert bp.months_between(fe.start_date, dt.date(2026, 2, 28)) == 1
    assert bp.pct(-100, 1000) == "-10.0" and bp.pct(5, 0) is None and bp.pct(1, 3) == "33.3"


# ------------------------------------------------------------------ the report
def test_history_ytd_and_difference(env, base, hist):
    r = rep(env, base)
    assert [y["display_name"] for y in r["years"]] == ["FY2026"] and r["available_years"] == 1
    ops = row(r, base["exp"]["id"])
    # renumbered 0900 -> 1000 is one line; FY2026 actual 450 of 900 budgeted
    h = ops["history"][0]
    assert h["code"] == "0900" and h["renumbered"] and h["budgeted"] == "900.00" and h["actual"] == "450.00"
    assert h["difference"] == "-450.00" and h["difference_pct"] == "-50.0" and h["direction"] == "under"
    # YTD to the report date only (the October withdrawal is later); parent = Travel + Other
    assert ops["current"] == {"budgeted": "100000.00", "actual": "360.00", "difference": "-99640.00",
                              "difference_pct": "-99.6", "direction": "under"}
    trav = row(r, hist["trav"]["id"])
    assert trav["level"] == "sub" and trav["current"]["actual"] == "300.00"
    assert trav["history"] == [None] and trav["history_note"] == "history on parent"
    # Other follows its parent's line: FY2026 Operations had no sub-budgets, so its Other carried the whole amount
    other = row(r, hist["other"])
    assert other["history_note"] is None and other["history"][0]["budgeted"] == "900.00"
    don = row(r, base["inc"]["id"])
    assert don["history"][0]["actual"] == "0.00" and don["history"][0]["direction"] == "under"
    assert don["current"]["actual"] == "1500.00"


def test_matches_the_budget_actuals_to_the_cent(env, base, hist):
    r = rep(env, base, as_of="2027-06-30")
    tree = env.bu.get(f"/api/fiscal-years/{base['fy']['id']}").json()["budgets"]
    by = {x["id"]: x["actual"] for sec in ("income", "expense") for p in tree[sec] for x in [p, *p["children"]]}
    for sec in ("income", "expense"):
        for x in r[sec]:
            if x["id"] in by:
                assert x["current"]["actual"] == by[x["id"]], x["code"]
    # parent roll-up = sum of its sub-budgets (budgeted and actual)
    kids = [x for x in r["expense"] if x["parent_id"] == base["exp"]["id"]]
    ops = row(r, base["exp"]["id"])
    assert sum(Fraction(k["current"]["actual"]) for k in kids) == Fraction(ops["current"]["actual"])
    assert sum(Fraction(k["current"]["budgeted"]) for k in kids) == Fraction(ops["current"]["budgeted"])


def test_years_parameter_and_gaps(env, base, hist):
    f25 = env.fy("2025", "2024-07-01", "2025-06-30")
    assert rep(env, base, years=1)["years"][0]["display_name"] == "FY2026"
    full = rep(env, base, years=9)
    assert [y["display_name"] for y in full["years"]] == ["FY2025", "FY2026"]
    ops = row(full, base["exp"]["id"])
    assert ops["history"][0] is None                         # no linked budget in FY2025: printed —
    assert rep(env, base, years=0)["years"] == []
    assert f25["id"]


def test_projection_choices_defaults_and_rollup(env, base, hist):
    assert env.admin.put("/api/system/modules", {"fundraisers": True}).status_code == 200
    gala = env.bm.post("/api/fundraisers", {"name": "Gala", "start_date": "2026-08-01", "end_date": "2026-08-02",
                                           "budget_ids": [base["inc"]["id"]]})
    assert gala.status_code == 201, gala.text
    ch = env.bm.get(f"/api/reports/budget-prep/projection-choices?fiscal_year_id={base['fy']['id']}").json()
    inc = {x["budget_id"]: x for x in ch["income"]}
    exp = {x["budget_id"]: x for x in ch["expense"]}
    # a budget of a finished fundraiser defaults to not projected; a parent with sub-budgets has no choice of its own
    assert inc[base["inc"]["id"]]["project"] is False and inc[base["inc"]["id"]]["complete_fundraisers"] == ["Gala"]
    assert exp[base["exp"]["id"]]["choosable"] is False and exp[hist["trav"]["id"]]["project"] is True
    r = rep(env, base, projected=True)
    assert row(r, base["inc"]["id"])["projection"]["state"] == "NOT_PROJECTED"
    assert row(r, base["inc"]["id"])["projection"]["projected"] == "1500.00"
    trav = row(r, hist["trav"]["id"])["projection"]
    assert trav["state"] == "PROJECTED" and trav["projected"] == "1200.00"     # 300 / 3 months x 12
    assert trav["difference"] == "-38800.00"
    ops = row(r, base["exp"]["id"])["projection"]
    assert ops["state"] == "ROLLUP" and ops["projected"] == "1440.00"          # (300 + 60) x 4
    # leave Other unprojected: the roll-up uses its YTD
    put = env.bm.put("/api/reports/budget-prep/projection-choices", {
        "fiscal_year_id": base["fy"]["id"], "choices": [{"budget_id": hist["other"], "project": False}]})
    assert put.status_code == 200, put.text
    r = rep(env, base, projected=True)
    assert row(r, base["exp"]["id"])["projection"]["projected"] == "1260.00"   # 1200 + 60
    # remembered per user: another Budget Manager still has the default
    bm2 = env.user("bm2", "FINANCIAL", ["BUDGET_MANAGER"])
    assert row(rep(env, base, client=bm2, projected=True), hist["other"])["projection"]["state"] == "PROJECTED"
    # reset brings the defaults back
    env.bm.put("/api/reports/budget-prep/projection-choices", {"fiscal_year_id": base["fy"]["id"], "reset": True})
    assert row(rep(env, base, projected=True), hist["other"])["projection"]["state"] == "PROJECTED"


def test_projection_choice_validation(env, base, hist):
    url = "/api/reports/budget-prep/projection-choices"
    bad = env.bm.put(url, {"fiscal_year_id": base["fy"]["id"], "choices": [{"budget_id": base["exp"]["id"], "project": False}]})
    assert bad.status_code == 422                                   # a parent with sub-budgets
    bad = env.bm.put(url, {"fiscal_year_id": base["fy"]["id"], "choices": [{"budget_id": hist["ops26"]["id"], "project": False}]})
    assert bad.status_code == 422                                   # another year's budget


def test_too_early(env, base, hist):
    r = rep(env, base, projected=True, as_of="2026-07-20")
    assert row(r, hist["trav"]["id"])["projection"]["state"] == "TOO_EARLY"
    assert row(r, base["exp"]["id"])["projection"]["state"] == "TOO_EARLY"


def test_next_year_column(env, base, hist):
    r = rep(env, base, include_next=True)
    n = row(r, base["exp"]["id"])["next"]
    assert n["code"] == "1100" and n["amount"] == "110000.00" and n["status"] == "DRAFT"
    assert n["change"] == "10000.00" and n["change_pct"] == "10.0" and n["direction"] == "over"
    assert row(r, base["inc"]["id"])["next"] is None
    assert r["next_fiscal_year"]["display_name"] == "FY2028"


def test_filters(env, base, hist):
    r = rep(env, base, parent_budget_id=base["exp"]["id"])
    assert r["income"] == [] and [x["id"] for x in r["expense"]][0] == base["exp"]["id"] and len(r["expense"]) == 3
    one = rep(env, base, budget_id=hist["trav"]["id"])
    assert [x["id"] for x in one["expense"]] == [hist["trav"]["id"]]
    assert env.bm.get(f"/api/reports/budget-prep?fiscal_year_id={base['fy']['id']}&budget_id={hist['ops26']['id']}").status_code == 422


def test_rejected_history_is_labelled(env, base, hist):
    f25 = env.fy("2025", "2024-07-01", "2025-06-30")
    old = env.budget(f25["id"], "0800", "Operations", "EXPENSE", "800.00")
    _link(env, hist["ops26"], old["id"])
    assert env.bm.post(f"/api/budgets/{old['id']}/reject", {"reason": "Not needed"}).status_code == 200
    r = rep(env, base, years=9)
    h = row(r, base["exp"]["id"])["history"]
    assert h[0]["status"] == "REJECTED" and h[0]["code"] == "0800"


def test_pdf_csv_and_audit(env, base, hist):
    pdf = rep(env, base, format="pdf", projected=True, include_next=True)
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["cache-control"] == "private, no-store"
    reader = PdfReader(io.BytesIO(pdf.content))
    w, h = float(reader.pages[0].mediabox.width), float(reader.pages[0].mediabox.height)
    assert w > h                                                     # landscape
    text = " ".join(" ".join(p.extract_text().split()) for p in reader.pages)   # cells wrap
    # 2.1.0 (#283): named Budget Review, laid out as Budgeted / Actual / Difference rows per budget
    for needle in ("Budget Review", "FY2026", "0900", "history on parent", "Budgeted", "$900.00", "$450.00 under (50.0%)",
                   "YTD 9/30/2026", "projected", "sum of sub-budgets", "1100", "Avg", "Page 1 of"):
        assert needle in text, needle
    c = rep(env, base, format="csv", projected=True)
    rows = list(csv.reader(io.StringIO(c.text)))
    assert rows[0][:5] == ["Section", "Level", "Code", "Budget", "Status"]
    ops = next(x for x in rows if x[2] == "1000")
    assert "450.00" in ops and "360.00" in ops
    ev = env.auditor.get("/api/audit-events?action=REPORT_GENERATED").json()["items"]
    kinds = [e["after"].get("format") for e in ev if (e.get("after") or {}).get("report") == "BUDGET_REVIEW"]
    assert sorted(kinds) == ["csv", "pdf"]


def test_single_budget_chart(env, base, hist):
    pdf = rep(env, base, format="pdf", budget_id=base["exp"]["id"])
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Budgeted and actual per year" in text and "Budgeted (left bar)" in text


def test_csv_formula_safety(env, base):
    env.budget(base["fy"]["id"], "5000", "=HYPERLINK(1)", "EXPENSE", "10.00")
    c = rep(env, base, format="csv")
    assert "'=HYPERLINK(1)" in c.text


@pytest.mark.parametrize("who", ["bu", "ru", "auditor", "admin"])
def test_budget_managers_only(env, base, who):
    c = getattr(env, who)
    fy = base["fy"]["id"]
    assert c.get(f"/api/reports/budget-prep?fiscal_year_id={fy}").status_code == 403
    assert c.get(f"/api/reports/budget-prep?fiscal_year_id={fy}&format=pdf").status_code == 403
    assert c.get(f"/api/reports/budget-prep/projection-choices?fiscal_year_id={fy}").status_code == 403
    assert c.put("/api/reports/budget-prep/projection-choices", {"fiscal_year_id": fy, "choices": []}).status_code == 403


def test_other_workspace_fiscal_year_is_not_found(env, base):
    assert env.bm.get("/api/reports/budget-prep?fiscal_year_id=999999").status_code == 404
