"""2.1.0 (#261): the Fiscal Year Planning Sheet - a portrait form for the budget planning meeting: Income and Expense
tables with Previous Budgeted, Actual YTD (dated), Projected and a blank Proposed column, blank rows for new budgets and
a page of blank tables last. With a Draft next Fiscal Year: header pre-filled, draft amounts as Proposed, a Proposed
Revision column, new draft budgets listed and current budgets not in the draft marked. Budget Managers only."""
from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

from fmpoc.services import budget_planning as bp
from test_fiscal_years import _ready_to_close


def _link(env, b, target):
    r = env.bm.patch(f"/api/budgets/{b['id']}", {"continues_budget_id": target})
    assert r.status_code == 200, r.text


def sheet(env, base, client=None, **q):
    q = {"fiscal_year_id": base["fy"]["id"], "as_of": "2026-09-30", **q}
    return (client or env.bm).get("/api/reports/planning-sheet", params=q)


def pages(r):
    rd = PdfReader(io.BytesIO(r.content))
    return rd, [" ".join((p.extract_text() or "").split()) for p in rd.pages]


@pytest.fixture
def cur(env, base):
    trav = env.budget(base["fy"]["id"], "01", "Travel", amount="400.00", parent=base["exp"]["id"])
    env.budget(base["fy"]["id"], "2000", "Uniforms", "EXPENSE", "250.00")
    rej = env.budget(base["fy"]["id"], "3000", "Dropped idea", "EXPENSE", "10.00")
    assert env.bm.post(f"/api/budgets/{rej['id']}/reject", {"reason": "No"}).status_code == 200
    env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": trav["id"], "amount": "90.00"}], date="2026-08-01")
    return {"trav": trav}


def test_blank_sheet_without_a_draft(env, base, cur):
    r = sheet(env, base)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    rd, t = pages(r)
    w, h = float(rd.pages[0].mediabox.width), float(rd.pages[0].mediabox.height)
    assert h > w                                                      # portrait
    assert len(t) == 2
    p1 = t[0]
    for needle in ("Fiscal Year Planning Sheet", "Meeting date:", "Current Fiscal Year: FY2027", "New Fiscal Year: ____",
                   "Attendees:", "Income", "Expense", "Previous Budgeted", "Actual YTD as of 9/30/2026", "Projected",
                   "Proposed Budget", "4000", "Donations", "1000", "Operations", "1000-01", "Travel", "$400.00",
                   "$90.00", "$360.00", "2000", "Uniforms", "not a required document"):
        assert needle in p1, needle
    assert "Proposed Revision" not in p1 and "Dropped idea" not in p1    # rejected budgets are left off
    assert "Total" not in p1                                              # no totals
    assert "Additional new budgets" in t[1] and "Fiscal Year Planning Sheet" in t[1]
    assert "Page 2 of 2" in t[1] and "printed" in t[1]


def test_with_a_draft_next_year(env, base, cur):
    f28 = env.fy("2028", "2027-07-01", "2028-06-30")
    ops = env.budget(f28["id"], "1100", "Operations", "EXPENSE", "120000.00")       # renumbered
    _link(env, ops, base["exp"]["id"])
    trav = env.budget(f28["id"], "01", "Travel", amount="500.00", parent=ops["id"])
    _link(env, trav, cur["trav"]["id"])
    env.budget(f28["id"], "02", "Meals", amount="80.00", parent=ops["id"])          # new under a continued parent
    env.budget(f28["id"], "5000", "Scholarships", "EXPENSE", "700.00")              # new parent
    r = sheet(env, base)
    assert r.status_code == 200, r.text
    _rd, t = pages(r)
    p1 = t[0]
    for needle in ("New Fiscal Year: FY2028 (7/1/2027 to 6/30/2028)", "Proposed Revision", "1100", "was 1000",
                   "$120,000.00", "$500.00", "Meals", "new in draft", "Scholarships", "$700.00",
                   "Uniforms (Draft · not in draft)", "Donations (Draft · not in draft)"):
        assert needle in p1, needle
    assert "Proposed Revision" in t[-1]                                  # page 2 blank tables get the column too


def test_planning_rows_structure(env, base, cur):
    f28 = env.fy("2028", "2027-07-01", "2028-06-30")
    ops = env.budget(f28["id"], "1000", "Operations", "EXPENSE", "1000.00")
    _link(env, ops, base["exp"]["id"])
    env.budget(f28["id"], "5000", "Scholarships", "EXPENSE", "700.00")
    import datetime as dt
    from sqlalchemy.orm import Session
    from fmpoc.models import FiscalYear, User
    with Session(env.app.state.engine) as db:
        class Ctx:
            workspace_id = db.get(FiscalYear, base["fy"]["id"]).workspace_id
            user = db.query(User).filter_by(username="budgetmgr").one()
        data = bp.planning_rows(db, Ctx, db.get(FiscalYear, base["fy"]["id"]), dt.date(2026, 9, 30))
    exp = data["expense"]
    codes = [(x["code"], x["level"], x["new"], x["not_in_draft"]) for x in exp]
    assert codes[0] == ("1000", "parent", False, False)
    assert ("1000-01", "sub", False, True) in codes                   # Travel not continued
    assert ("2000", "parent", False, True) in codes
    assert codes[-1] == ("5000", "parent", True, False)               # new draft budgets after the current ones
    ops_row = exp[0]
    assert ops_row["proposed"] == 100000 and ops_row["budgeted"] == 10000000
    trav = next(x for x in exp if x["code"] == "1000-01")
    assert trav["ytd"] == 9000 and trav["projection"] == ("VALUE", 36000)   # 90 x 4
    assert all("Dropped idea" != x["name"] for x in exp)


def test_unprojected_budget_shows_complete(env, base, cur):
    put = env.bm.put("/api/reports/budget-prep/projection-choices", {
        "fiscal_year_id": base["fy"]["id"], "choices": [{"budget_id": cur["trav"]["id"], "project": False}]})
    assert put.status_code == 200, put.text
    _rd, t = pages(sheet(env, base))
    assert "Complete" in t[0]


def test_too_early(env, base, cur):
    _rd, t = pages(sheet(env, base, as_of="2026-07-10"))
    assert "too early" in t[0]


def test_many_budgets_continue_and_blank_tables_stay_last(env, base):
    for i in range(45):
        env.budget(base["fy"]["id"], f"{6000 + i}", f"Program line {i}", "EXPENSE", "10.00")
    _rd, t = pages(sheet(env, base))
    assert len(t) >= 3
    assert "Program line 44" in " ".join(t[:-1]) and "Additional new budgets" in t[-1]
    assert all("Additional new budgets" not in x for x in t[:-1])


def test_audited(env, base, cur):
    assert sheet(env, base).status_code == 200
    ev = env.auditor.get("/api/audit-events?action=REPORT_GENERATED").json()["items"]
    assert any((e.get("after") or {}).get("report") == "PLANNING_SHEET" for e in ev)


def test_scanned_sheet_is_not_required_for_closure(env, base):
    """BR-013/BR-015 unchanged: the scanned sheet is an Other (Unspecified) document of the Fiscal Year."""
    _ready_to_close(env, base)
    env.fy_doc(base["fy"]["id"], "UNSPECIFIED", "planning-sheet-scan.pdf")
    c = env.bm.get(f"/api/fiscal-years/{base['fy']['id']}").json()["closure"]
    assert c["can_close"] is True


@pytest.mark.parametrize("who", ["bu", "ru", "auditor", "admin"])
def test_budget_managers_only(env, base, who):
    assert sheet(env, base, client=getattr(env, who)).status_code == 403
