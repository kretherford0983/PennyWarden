"""2.3.0 build 1: #371 gross-budget disclaimer (BR-109) and #372 optional fundraiser goal (compared with the net)."""
import io
import pathlib
import re

from pypdf import PdfReader

from fmpoc.services.common import GROSS_BUDGET_NOTE

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _flat(content: bytes) -> str:
    return " ".join(" ".join((p.extract_text() or "").split()) for p in PdfReader(io.BytesIO(content)).pages)


# ------------------------------------------------------------------ #371
def test_note_is_identical_in_backend_and_frontend():
    src = (ROOT / "frontend" / "src" / "components.tsx").read_text(encoding="utf-8")
    m = re.search(r'export const GROSS_BUDGET_NOTE =\s*"([^"]+)"', src)
    assert m and m.group(1) == GROSS_BUDGET_NOTE


def test_fy_audit_report_budget_tables_carry_the_note(env, base):
    r = env.auditor.get(f"/api/reports/audit?fiscal_year_id={base['fy']['id']}")
    assert r.status_code == 200
    text = _flat(r.content)
    assert "Gross amount" in text
    assert text.count(GROSS_BUDGET_NOTE) == 2          # beneath the Income and the Expense table


def test_budget_review_and_planning_sheet_carry_the_note(env, base):
    q = {"fiscal_year_id": base["fy"]["id"], "format": "pdf"}
    r = env.bm.get("/api/reports/budget-review", params=q)
    assert r.status_code == 200, r.text
    assert GROSS_BUDGET_NOTE in _flat(r.content)
    r = env.bm.get("/api/reports/planning-sheet", params={"fiscal_year_id": base["fy"]["id"], "as_of": "2026-09-30"})
    assert r.status_code == 200, r.text
    assert GROSS_BUDGET_NOTE in _flat(r.content)


# ------------------------------------------------------------------ #372
def _enable(env):
    assert env.admin.put("/api/system/modules", {"fundraisers": True}).status_code == 200


def test_goal_optional_and_compared_with_net(env, base):
    _enable(env)
    acct = base["acct"]["id"]
    env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "200.00", "description": "Gala supplies"}],
            date="2026-09-01")
    env.txn(acct, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "1200.00", "description": "Gala tickets"}],
            date="2026-09-14")
    body = {"name": "Gala", "start_date": "2026-09-12", "budget_ids": [base["inc"]["id"], base["exp"]["id"]]}
    f = env.bm.post("/api/fundraisers", body).json()
    assert f["goal_amount"] is None and f["totals"]["goal"] is None            # no goal: nothing shown
    f = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "goal_amount": "1500"}).json()
    assert f["goal_amount"] == "1500.00"
    g = f["totals"]["goal"]
    assert g == {"goal": "1500.00", "net": "1000.00", "difference": "-500.00", "pct_of_goal": 66.7, "met": False}
    # an edit that doesn't send the goal keeps it
    f = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "name": "Spring Gala"}).json()
    assert f["goal_amount"] == "1500.00" and f["totals"]["goal"]["met"] is False
    f = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "goal_amount": "900.00"}).json()
    assert f["totals"]["goal"]["met"] is True and f["totals"]["goal"]["difference"] == "100.00"
    # a goal of 0 has no percentage
    f = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "goal_amount": "0"}).json()
    assert f["totals"]["goal"]["pct_of_goal"] is None
    # null (the form sends null for a blank field) clears it; changes are audited with before/after
    f = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "goal_amount": None}).json()
    assert f["goal_amount"] is None and f["totals"]["goal"] is None
    ev = [e for e in env.auditor.get("/api/audit-events?object_type=fundraiser").json()["items"]
          if e["action"] == "FUNDRAISER_UPDATED"]
    assert any("1500.00" in str(e) and "900.00" in str(e) for e in ev)


def test_goal_validation_and_permissions(env, base):
    _enable(env)
    body = {"name": "Gala", "start_date": "2026-09-12", "budget_ids": []}
    for bad in ("-5", "abc", "12.345"):
        r = env.bm.post("/api/fundraisers", {**body, "goal_amount": bad})
        assert r.status_code == 422, (bad, r.text)
    f = env.bm.post("/api/fundraisers", {**body, "goal_amount": "250.50"}).json()
    assert f["goal_amount"] == "250.50"
    for c in (env.bu, env.ru, env.auditor, env.admin):            # only Budget Managers edit fundraisers
        assert c.put(f"/api/fundraisers/{f['id']}", {**body, "goal_amount": "1"}).status_code == 403
    assert env.auditor.get(f"/api/fundraisers/{f['id']}").json()["goal_amount"] == "250.50"
