"""2.2.0 (#284): budget history before PennyWarden - a Budget Manager enters the budgeted and actual figures of years
before the first Fiscal Year in PennyWarden (labelled Entered) on a budget's History; the Budget Review shows them
after the PennyWarden years; a CSV import with a preview. Decisions (Kyle, 2026-10-24): any budget level (a parent
without its own figure shows the sum of its sub-budgets', a mismatch note when both differ); CSV in the first version;
History, Budget Review and Planning Sheet only; years in PennyWarden refused. Never deleted (BR-001), audited,
reporting only (BR-048), Budget Managers only (BR-003).
#381: the entries now belong to a budget from before PennyWarden (a former budget) that the earliest budget of the
line continues; the CSV import takes the new columns (more in test_v220_former_budgets.py)."""
from __future__ import annotations

import csv
import io

from pypdf import PdfReader

from conftest import Api

AS_OF = "2026-09-30"


def _add(env, budget_id, label, budgeted, actual, note=None, client=None, expect=201):
    r = (client or env.bm).post(f"/api/budgets/{budget_id}/history/entered",
                                {"fiscal_year_label": label, "budgeted": budgeted, "actual": actual, "note": note})
    assert r.status_code == expect, r.text
    return r.json()


def _view(env, budget_id, client=None):
    r = (client or env.bm).get(f"/api/budgets/{budget_id}/history/entered")
    assert r.status_code == 200, r.text
    return r.json()


def _review(env, base, **q):
    q = {"fiscal_year_id": base["fy"]["id"], "as_of": AS_OF, "years": 5, **q}
    r = env.bm.get("/api/reports/budget-review", params=q)
    assert r.status_code == 200, r.text
    return r.json() if q.get("format", "json") == "json" else r


def _row(rep, rid):
    return next(r for s in ("income", "expense") for r in rep[s] if r["id"] == rid)


def _audit(env, action):
    return env.auditor.get(f"/api/audit-events?action={action}").json()["items"]


def test_enter_view_and_review(env, base):
    e = _add(env, base["exp"]["id"], "FY2025", "90000.00", "87500.25", "from the 2025 treasurer's spreadsheet")
    assert e["year"] == 2025 and e["budgeted"] == "90000.00" and e["actual"] == "87500.25" and e["budget_id"] is None
    assert e["former_budget_id"] and (e["code_shown"], e["name_shown"]) == ("1000", "Operations")
    _add(env, base["exp"]["id"], "FY 2026", "95000", "$96,100.00")
    v = _view(env, base["exp"]["id"])
    assert v["first_year"] == 2027 and v["can_enter"] is True
    # #381: the first entered year created the former budget "1000 Operations", continued by this budget
    assert v["former"]["label"] == "1000 Operations" and v["former"]["continued_by"]["id"] == base["exp"]["id"]
    assert v["is_holder"] is True and v["former"]["years"] == 2
    assert [(x["fiscal_year_label"], x["actual"], x["counted"], x["source"]) for x in v["entries"]] == \
        [("FY2025", "87500.25", True, "ENTERED"), ("FY 2026", "96100.00", True, "ENTERED")]
    # every financial role can read it (History is financial.view)
    assert _view(env, base["exp"]["id"], env.auditor)["entries"][0]["budgeted"] == "90000.00"
    rep = _review(env, base)
    assert [(y["display_name"], y["entered"]) for y in rep["years"]] == [("FY2025", True), ("FY 2026", True)]
    assert rep["available_years"] == 2 and rep["entered_years"] == 2
    ops = _row(rep, base["exp"]["id"])
    assert [c["source"] for c in ops["history"]] == ["ENTERED", "ENTERED"]
    assert ops["history"][1]["budgeted"] == "95000.00" and ops["history"][1]["direction"] == "over"
    assert ops["average"]["years"] == 2
    assert _row(rep, base["inc"]["id"])["history"] == [None, None]
    # the budgets page offers History for it now
    tree = env.bu.get(f"/api/budgets?fiscal_year_id={base['fy']['id']}").json()
    rows = {r["id"]: r for r in tree["expense"] + tree["income"]}
    assert rows[base["exp"]["id"]]["has_history"] is True and rows[base["inc"]["id"]]["has_history"] is False
    ev = _audit(env, "BUDGET_HISTORY_ENTERED")
    assert len(ev) == 2 and ev[-1]["after"]["budgeted"] == "90000.00" and ev[-1]["after"]["via"] == "single"
    assert ev[-1]["object_type"] == "former_budget" and ev[-1]["after"]["entered_on_budget_id"] == base["exp"]["id"]
    assert len(_audit(env, "FORMER_BUDGET_CREATED")) == 1 and len(_audit(env, "BUDGET_FORMER_LINKED")) == 1


def test_pennywarden_years_and_duplicates_refused(env, base):
    r = env.bm.post(f"/api/budgets/{base['exp']['id']}/history/entered",
                    {"fiscal_year_label": "FY2027", "budgeted": "1", "actual": "1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "YEAR_IN_PENNYWARDEN"
    assert env.bm.post(f"/api/budgets/{base['exp']['id']}/history/entered",
                       {"fiscal_year_label": "FY2030", "budgeted": "1", "actual": "1"}).status_code == 409
    r = env.bm.post(f"/api/budgets/{base['exp']['id']}/history/entered",
                    {"fiscal_year_label": "Last year", "budgeted": "1", "actual": "1"})
    assert r.status_code == 422 and r.json()["error"]["errors"][0]["field"] == "fiscal_year_label"
    r = env.bm.post(f"/api/budgets/{base['exp']['id']}/history/entered",
                    {"fiscal_year_label": "FY2024", "budgeted": "-5", "actual": "1"})
    assert r.status_code == 422
    _add(env, base["exp"]["id"], "FY2024", "10", "-2.50")          # a negative actual (refunds) is allowed
    r = env.bm.post(f"/api/budgets/{base['exp']['id']}/history/entered",
                    {"fiscal_year_label": "FY 2024 (revised)", "budgeted": "1", "actual": "1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "YEAR_ENTERED"
    # Budget 0 takes none; #381 decision 3: Other may (its own former budget, the old parent row's uncategorized)
    sub = env.budget(base["fy"]["id"], "01", "Travel", amount="10.00", parent=base["exp"]["id"])
    tree = env.bm.get(f"/api/budgets?fiscal_year_id={base['fy']['id']}").json()
    other = next(c for r in tree["expense"] for c in r["children"] if c["is_other"])
    r = env.bm.post(f"/api/budgets/{tree['budget_zero']['id']}/history/entered", {"fiscal_year_label": "FY2020", "budgeted": "1", "actual": "1"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "SYSTEM_MANAGED"
    _add(env, other["id"], "FY2020", "1", "1")
    assert _view(env, other["id"])["former"]["label"] == "1000-00 Other"
    assert sub


def test_only_budget_managers_change_it(env, base):
    body = {"fiscal_year_label": "FY2025", "budgeted": "1", "actual": "1"}
    for c in (env.admin, env.bu, env.ru, env.auditor):
        assert c.post(f"/api/budgets/{base['exp']['id']}/history/entered", body).status_code == 403
    assert env.admin.get(f"/api/budgets/{base['exp']['id']}/history/entered").status_code == 403   # BR-003
    e = _add(env, base["exp"]["id"], "FY2025", "1", "1")
    for c in (env.admin, env.bu, env.ru, env.auditor):
        assert c.patch(f"/api/budgets/history-entries/{e['id']}", {"budgeted": "2", "reason": "x"}).status_code == 403
        assert c.post(f"/api/budgets/history-entries/{e['id']}/retire", {"reason": "x"}).status_code == 403
    assert Api(env.app).get(f"/api/budgets/{base['exp']['id']}/history/entered").status_code == 401


def test_correct_and_retire_never_delete(env, base):
    e = _add(env, base["exp"]["id"], "FY2025", "100.00", "80.00")
    r = env.bm.patch(f"/api/budgets/history-entries/{e['id']}", {"actual": "85.00"})
    assert r.status_code == 422                                     # a reason is required
    r = env.bm.patch(f"/api/budgets/history-entries/{e['id']}", {"actual": "85.00", "reason": "Typo in the spreadsheet"})
    assert r.status_code == 200 and r.json()["actual"] == "85.00"
    ev = _audit(env, "BUDGET_HISTORY_CORRECTED")[0]
    assert ev["before"]["actual"] == "80.00" and ev["after"]["actual"] == "85.00" and ev["after"]["reason"] == "Typo in the spreadsheet"
    assert env.bm.post(f"/api/budgets/history-entries/{e['id']}/retire", {"reason": ""}).status_code == 422
    r = env.bm.post(f"/api/budgets/history-entries/{e['id']}/retire", {"reason": "Wrong budget"})
    assert r.status_code == 200 and r.json()["retired"] is True and r.json()["retire_reason"] == "Wrong budget"
    assert env.bm.post(f"/api/budgets/history-entries/{e['id']}/retire", {"reason": "again"}).status_code == 409
    assert env.bm.patch(f"/api/budgets/history-entries/{e['id']}", {"actual": "1", "reason": "x"}).status_code == 409
    # still listed (retired), not counted; the year can be entered again
    v = _view(env, base["exp"]["id"])["entries"]
    assert len(v) == 1 and v[0]["retired"] and not v[0]["counted"]
    assert _review(env, base)["years"] == []
    _add(env, base["exp"]["id"], "FY2025", "100.00", "85.00")
    assert len(_audit(env, "BUDGET_HISTORY_RETIRED")) == 1
    import sqlite3
    con = sqlite3.connect(env.settings.database_path)
    assert con.execute("SELECT count(*) FROM budget_history_entry").fetchone()[0] == 2
    con.close()


def test_stored_on_the_oldest_budget_and_follows_the_line(env, base):
    f26 = env.fy("2026", "2025-07-01", "2026-06-30")
    ops26 = env.budget(f26["id"], "0900", "Operations", "EXPENSE", "900.00")
    assert env.bm.patch(f"/api/budgets/{base['exp']['id']}", {"continues_budget_id": ops26["id"]}).status_code == 200
    e = _add(env, base["exp"]["id"], "FY2024", "800.00", "790.00")   # entered on today's budget, linked from the oldest
    v = _view(env, base["exp"]["id"])
    assert v["former"]["continued_by"]["id"] == ops26["id"] and v["holder"]["id"] == ops26["id"] and not v["is_holder"]
    assert v["former"]["label"] == "0900 Operations"                 # named after the earliest budget of the line
    # first Fiscal Year is now FY2026: 2026 is refused
    r = env.bm.post(f"/api/budgets/{base['exp']['id']}/history/entered", {"fiscal_year_label": "FY2026", "budgeted": "1", "actual": "1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "YEAR_IN_PENNYWARDEN"
    assert _view(env, ops26["id"])["entries"][0]["id"] == e["id"]
    rep = _review(env, base)
    assert [(y["display_name"], y["entered"]) for y in rep["years"]] == [("FY2024", True), ("FY2026", False)]
    ops = _row(rep, base["exp"]["id"])
    assert ops["history"][0]["source"] == "ENTERED" and ops["history"][1]["source"] == "RECORDED"
    assert ops["history"][1]["code"] == "0900" and ops["history"][1]["renumbered"]
    # years=1: only the newest prior year (the PennyWarden one)
    assert [y["display_name"] for y in _review(env, base, years=1)["years"]] == ["FY2026"]
    # a Fiscal Year added later that covers an entered year: kept, no longer counted
    env.fy("2024", "2023-07-01", "2024-06-30", confirmations=["FY_GAP"])
    v = _view(env, base["exp"]["id"])
    assert v["first_year"] == 2024 and v["entries"][0]["counted"] is False
    assert all(not y["entered"] for y in _review(env, base)["years"])


def test_parent_sum_of_sub_budgets_and_mismatch(env, base):
    trav = env.budget(base["fy"]["id"], "01", "Travel", amount="100.00", parent=base["exp"]["id"])
    supp = env.budget(base["fy"]["id"], "02", "Supplies", amount="100.00", parent=base["exp"]["id"])
    _add(env, trav["id"], "FY2025", "300.00", "250.00")
    _add(env, supp["id"], "FY2025", "200.00", "220.00")
    rep = _review(env, base)
    p = _row(rep, base["exp"]["id"])["history"][0]
    assert (p["budgeted"], p["actual"], p["from_sub_budgets"], p["mismatch"]) == ("500.00", "470.00", True, None)
    t = _row(rep, trav["id"])
    assert t["history"][0]["budgeted"] == "300.00" and t["history_note"] is None
    v = _view(env, base["exp"]["id"])["entries"]
    assert [(x["from_sub_budgets"], x["budgeted"], x["id"]) for x in v] == [(True, "500.00", None)]
    # the parent's own figure wins; a different sum of sub-budgets is noted, nothing is blocked
    _add(env, base["exp"]["id"], "FY2025", "600.00", "470.00")
    p = _row(_review(env, base), base["exp"]["id"])["history"][0]
    assert (p["budgeted"], p["from_sub_budgets"]) == ("600.00", False)
    assert p["mismatch"] == {"budgeted": "500.00", "actual": "470.00"}
    v = _view(env, base["exp"]["id"])["entries"]
    assert len(v) == 1 and v[0]["mismatch"] == {"budgeted": "500.00", "actual": "470.00"}
    csv_text = _review(env, base, format="csv").text
    assert "Entered; sub-budgets add up to 500.00 budgeted, 470.00 actual" in csv_text


def test_reporting_only(env, base):
    """BR-048: entered figures never change the budget's actual, the registers or the Budgets page totals."""
    before = env.bm.get(f"/api/budgets?fiscal_year_id={base['fy']['id']}").json()
    _add(env, base["exp"]["id"], "FY2025", "1000000.00", "999999.00")
    after = env.bm.get(f"/api/budgets?fiscal_year_id={base['fy']['id']}").json()
    assert after["expense_summary"] == before["expense_summary"]
    rep = _review(env, base)
    assert _row(rep, base["exp"]["id"])["current"]["actual"] == "0.00"


def test_review_pdf_and_csv(env, base):
    _add(env, base["exp"]["id"], "FY2025", "900.00", "450.00")
    r = _review(env, base, format="csv")
    head = next(csv.reader(io.StringIO(r.text)))
    assert "FY2025 (entered) budgeted" in head
    r = _review(env, base, format="pdf")
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "entered" in text and "before the first Fiscal Year in PennyWarden" in text


TEMPLATE_HEAD = ["budget code", "budget name (ignored)", "type", "former code", "former name", "year", "budgeted",
                 "actual", "note", "line"]


def test_csv_template_preview_and_import(env, base):
    """#381 decisions 4 and 5: budget code of the chosen Fiscal Year (or blank), type, former code/name, year, amounts."""
    trav = env.budget(base["fy"]["id"], "01", "Travel", amount="10.00", parent=base["exp"]["id"])
    r = env.bm.get(f"/api/budgets/history-entries/template?fiscal_year_id={base['fy']['id']}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == TEMPLATE_HEAD
    # income first; the -00 Other of a parent with sub-budgets is offered; no Budget 0
    assert [x[0] for x in rows[1:]] == ["4000", "1000", "1000-00", "1000-01"]
    assert rows[1][1:3] == ["Donations", "Income"]
    _add(env, base["inc"]["id"], "FY2024", "1.00", "1.00")
    text = ("Budget code,Type,Former code,Former name,Year,Budgeted,Actual,Note\n"
            "1000,,,,FY2025,\"$1,000.00\",950,old sheet\n"
            "1000-01,,101,Travel,FY2025,200,180,\n"
            "1000,,,,FY2025,5,5,again\n"                 # twice in the file
            "4000,,,,FY2024,1,1,\n"                      # already entered
            "1000,,,,FY2027,1,1,\n"                      # a PennyWarden year
            "9999,,,,FY2025,1,1,\n"                      # unknown code
            "1000-01,,,,FY2024,abc,1,\n"                 # bad amount
            "4000,,,,last year,1,1,\n"                   # no year
            "4000,Expense,,,FY2023,1,1,\n"               # type mismatch
            ",,450,Bowling,FY2023,1,1,\n"               # no type for a former budget nothing continues
            ",,,,,,,\n"
            "1000-01,Expense,,,,,,\n")                   # a template row left as it is: skipped
    body = {"fiscal_year_id": base["fy"]["id"], "csv": text}
    p = env.bm.post("/api/budgets/history-entries/preview", body)
    assert p.status_code == 200, p.text
    p = p.json()
    assert [(r["line"], r["status"]) for r in p["rows"]] == [
        (2, "MATCHED"), (3, "MATCHED"), (4, "DUPLICATE"), (5, "DUPLICATE"), (6, "REFUSED"), (7, "REFUSED"),
        (8, "REFUSED"), (9, "REFUSED"), (10, "REFUSED"), (11, "REFUSED")]
    assert p["counts"] == {"MATCHED": 2, "REFUSED": 6, "DUPLICATE": 2}
    reasons = {r["line"]: r["reason"] for r in p["rows"]}
    assert "line 2" in reasons[4] and "Only years before" in reasons[6] and "No budget 9999" in reasons[7]
    assert reasons[8].startswith("Budgeted:") and "include the year" in reasons[9]
    assert "doesn't match" in reasons[10] and "Type (Income or Expense) is needed" in reasons[11]
    assert p["rows"][0]["budgeted"] == "1000.00" and p["rows"][0]["budget_name"] == "Operations"
    lines = {g["key"]: g for g in p["lines"]}
    assert lines["budget 1000"]["action"] == "NEW" and lines["budget 1000"]["link_action"] == "NEW"
    assert lines["budget 1000-01"]["former_code"] == "101" and lines["budget 1000-01"]["link"]["id"] == trav["id"]
    assert lines["budget 4000"]["action"] == "EXISTING" and lines["budget 4000"]["link_action"] == "EXISTING"
    assert p["new_former_budgets"] == 2 and p["new_links"] == 2
    assert _view(env, base["exp"]["id"])["entries"] == []           # the preview saved nothing
    r = env.bm.post("/api/budgets/history-entries/import", body)
    assert r.status_code == 200 and r.json()["saved"] == 2 and r.json()["former_budgets_created"] == 2
    v = _view(env, trav["id"])
    assert v["entries"][0]["budgeted"] == "200.00" and v["former"]["label"] == "101 Travel"
    ev = _audit(env, "BUDGET_HISTORY_IMPORTED")[0]
    assert ev["after"] == {"saved": 2, "refused": 6, "duplicates": 2, "former_budgets_created": 2, "links_made": 2}
    assert all(x["after"]["via"] == "csv" for x in _audit(env, "BUDGET_HISTORY_ENTERED")[:2])
    # importing the same file again: everything is a duplicate now, nothing saved
    r = env.bm.post("/api/budgets/history-entries/import", body)
    assert r.status_code == 422
    # missing columns
    r = env.bm.post("/api/budgets/history-entries/preview", {"fiscal_year_id": base["fy"]["id"], "csv": "year,code\nFY2020,1000\n"})
    assert r.status_code == 422 and "budget code or former code" in r.json()["error"]["message"]
    for c in (env.admin, env.bu, env.auditor):
        assert c.post("/api/budgets/history-entries/preview", body).status_code == 403
        assert c.get(f"/api/budgets/history-entries/template?fiscal_year_id={base['fy']['id']}").status_code == 403


def test_csv_formula_cells_are_neutralised_in_the_review_csv(env, base):
    _add(env, base["exp"]["id"], "=HYPERLINK(1) FY2025", "1", "1")
    text = _review(env, base, format="csv").text
    assert "\n=" not in text and ",=" not in text


def test_reinitialize_wipes_entered_history():
    from fmpoc.models import Budget, BudgetHistoryEntry, FormerBudget
    from fmpoc.services.reinitialize import WIPE
    assert BudgetHistoryEntry in WIPE and WIPE.index(BudgetHistoryEntry) < WIPE.index(FormerBudget) < WIPE.index(Budget)
