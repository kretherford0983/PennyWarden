"""2.5.0 (#590): the Budget proposal - a Draft (Proposed) or Approved year's budgets beside the previous year, as a
PDF / presentation for Budget Managers, and appended to the Annual report on request."""
import datetime as dt
import io
from types import SimpleNamespace

import pytest
from pptx import Presentation
from pypdf import PdfReader

from fmpoc.models import FiscalYear, User
from fmpoc.services import budget_proposal as bp


def _text(pdf: bytes) -> str:
    return " ".join(" ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages).split())


def _slides(data: bytes) -> str:
    prs = Presentation(io.BytesIO(data))
    out = []
    for s in prs.slides:
        for sh in s.shapes:
            if sh.has_text_frame:
                out.append(sh.text_frame.text)
            if getattr(sh, "has_table", False) and sh.has_table:
                out += [c.text for r in sh.table.rows for c in r.cells]
    return " ".join(" ".join(out).split())


@pytest.fixture
def plan(env, base):
    """FY2027 (base, running) and a Draft FY2028: one line carried by code, one renamed through its link, one new,
    one dropped, one rejected."""
    acct = base["acct"]["id"]
    env.txn(acct, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "1200.00", "description": "Gifts"}], date="2026-08-01")
    env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "3000.00", "description": "Rent"}], date="2026-08-02")
    uni = env.budget(base["fy"]["id"], "1200", "Uniforms", "EXPENSE", "2000.00")
    fy28 = env.fy("2028", "2027-07-01", "2028-06-30")
    env.budget(fy28["id"], "4000", "Donations", "INCOME", "6000.00")
    env.budget(fy28["id"], "4100", "Kiwanis", "INCOME", "500.00")
    r = env.bm.post("/api/budgets", {"fiscal_year_id": fy28["id"], "code": "1100", "name": "Ops & Supplies",
                                     "budget_type": "EXPENSE", "amount": "90000.00",
                                     "continues_budget_id": base["exp"]["id"]})
    assert r.status_code == 201, r.text
    rej = env.budget(fy28["id"], "1300", "Raffle", "EXPENSE", "700.00")
    assert env.bm.post(f"/api/budgets/{rej['id']}/reject", {"reason": "Not this year"}).status_code == 200
    return {"fy28": fy28, "uniforms": uni}


def _build(env, fy_id: int, today: dt.date) -> dict:
    with env.app.state.session_factory() as db:
        fy = db.get(FiscalYear, fy_id)
        user = db.query(User).filter(User.username.isnot(None)).first()
        ctx = SimpleNamespace(user=user, workspace_id=fy.workspace_id)
        return bp.build(db, ctx, fy, today)


def _row(sec: dict, label: str) -> dict:
    return next(r for r in sec["rows"] + sec["not_in_year"] if r["label"] == label)


def test_lines_match_by_code_and_link_new_and_dropped(env, base, plan):
    rep = _build(env, plan["fy28"]["id"], dt.date(2027, 7, 15))       # FY2027 has ended: whole-year actuals
    assert rep["state"] == "Proposed" and rep["actual_word"] == "actual"
    inc, exp = rep["income"], rep["expense"]
    d = _row(inc, "4000 Donations")
    assert (d["previous_budget"], d["previous_actual"], d["proposed"], d["change"]) == (500000, 120000, 600000, 100000)
    k = _row(inc, "4100 Kiwanis")
    assert k["previous_budget"] is None and k["change"] is None and k["proposed"] == 50000
    ops = _row(exp, "1100 Ops & Supplies")                             # renamed and renumbered: one line by its link
    assert (ops["previous_budget"], ops["previous_actual"], ops["change"]) == (10000000, 300000, -1000000)
    assert not any(r["label"].startswith("1300") for r in exp["rows"])  # rejected: left out
    gone = exp["not_in_year"]
    assert [r["label"] for r in gone] == ["1200 Uniforms"] and gone[0]["previous_budget"] == 200000
    # totals equal each year's own totals
    assert inc["total"] == {"previous_budget": 500000, "previous_actual": 120000, "proposed": 650000,
                            "change": 150000, "change_pct": "30.0"}
    assert exp["total"]["previous_budget"] == 10200000 and exp["total"]["proposed"] == 9000000
    assert rep["net"]["proposed"] == 650000 - 9000000


def test_running_previous_year_is_projected(env, base, plan):
    rep = _build(env, plan["fy28"]["id"], dt.date(2026, 12, 31))      # about half the year: about double the YTD
    assert rep["actual_word"] == "projected"
    from fmpoc.services.budget_planning import basis, project
    fy27 = SimpleNamespace(start_date=dt.date(2026, 7, 1), end_date=dt.date(2027, 6, 30))
    want = project(120000, basis(fy27, dt.date(2026, 12, 31)))
    assert _row(rep["income"], "4000 Donations")["previous_actual"] == want and 230000 < want < 250000
    assert any("projected to the year end" in x for x in bp.notes_lines(rep))


def test_closed_year_is_not_a_proposal():
    with pytest.raises(Exception):
        bp.check_year(SimpleNamespace(status="CLOSED", display_name="FY2026"))


def test_outputs_and_permissions(env, base, plan):
    fid = plan["fy28"]["id"]
    for who in (env.ru, env.auditor, env.admin):
        assert who.get(f"/api/reports/budget-proposal?fiscal_year_id={fid}").status_code == 403
    j = env.bm.get(f"/api/reports/budget-proposal?fiscal_year_id={fid}&format=json").json()
    assert j["state"] == "Proposed" and j["income"]["total"]["proposed"] == "6500.00"
    pdf = env.bm.get(f"/api/reports/budget-proposal?fiscal_year_id={fid}&commentary=Board%20meeting")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    text = _text(pdf.content)
    for want in ("FY2028 Budget — Proposed", "Income budgets", "Expense budgets", "4100 Kiwanis", "1100 Ops & Supplies",
                 "Not in FY2028", "FY2027 budget", "FY2028 proposed", "Board meeting"):
        assert want in text, want
    deck = env.bm.get(f"/api/reports/budget-proposal?fiscal_year_id={fid}&format=pptx")
    assert deck.status_code == 200
    s = _slides(deck.content)
    assert "FY2028 Budget — Income" in s and "FY2028 Budget — Expense" in s and "Questions?" in s
    ev = env.auditor.get("/api/audit-events?action=REPORT_GENERATED&object_type=fiscal_year").json()["items"]
    assert any(e["after"]["report"] in ("BUDGET_PROPOSAL", "BUDGET_PROPOSAL_PRESENTATION") for e in ev)


def test_approved_year_reads_approved(env, base):
    fy28 = env.fy("2028", "2027-07-01", "2028-06-30")
    env.budget(fy28["id"], "4000", "Donations", "INCOME", "6000.00")
    env.approve(fy28["id"])
    assert env.bm.get(f"/api/reports/budget-proposal?fiscal_year_id={fy28['id']}&format=json").json()["state"] == "Approved"


def test_annual_report_can_append_next_years_proposal(env, base, plan):
    fy = base["fy"]["id"]
    opts = env.bm.get(f"/api/reports/period/options?fiscal_year_id={fy}").json()
    assert opts["next_fiscal_year"]["display_name"] == "FY2028"
    assert env.ru.get(f"/api/reports/period/options?fiscal_year_id={fy}").json()["next_fiscal_year"] is None
    url = f"/api/reports/period?fiscal_year_id={fy}&period=ANNUAL&include_proposal=true"
    assert env.ru.get(url).status_code == 403                          # Budget Managers only
    assert env.bm.get(f"/api/reports/period?fiscal_year_id={fy}&period=Q1&include_proposal=true").status_code == 422
    text = _text(env.bm.get(url).content)
    assert "FY2028 Budget — Proposed" in text and "4100 Kiwanis" in text
    assert "FY2028 Budget" not in _text(env.bm.get(url.replace("&include_proposal=true", "")).content)
    s = _slides(env.bm.get(url + "&format=pptx").content)
    assert s.index("FY2028 Budget — Income") < s.index("Questions?")
