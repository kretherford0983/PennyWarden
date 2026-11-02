"""2.2.0 (#381): budgets from before PennyWarden ("former budgets").

Decisions (Kyle, 2026-10-28): every entered year belongs to a former budget that a PennyWarden budget reaches only by an
explicit link (never by code); links may cross levels; Other may continue a former budget; the CSV import creates former
budgets, years and links in one pass (rows form a line by budget code, else former code, the *line* column overrides);
each year keeps the code and name it had, and a former budget shows its most recent. Reporting only (BR-048), never
deleted (BR-001), audited (BR-075..077), Budget Managers change it, financial roles and Auditors read it, the
Administrator is refused (BR-003); object-level checks (BR-099) and explicit writable fields (BR-098).
"""
from __future__ import annotations

import sqlite3

from conftest import Api

AS_OF = "2026-09-30"


def _former(env, code, name, btype="EXPENSE", note=None, expect=201):
    r = env.bm.post("/api/budgets/former", {"code": code, "name": name, "budget_type": btype, "note": note})
    assert r.status_code == expect, r.text
    return r.json()


def _year(env, fid, label, budgeted, actual, code=None, name=None, expect=201):
    r = env.bm.post(f"/api/budgets/former/{fid}/entries",
                    {"fiscal_year_label": label, "budgeted": budgeted, "actual": actual, "code": code, "name": name})
    assert r.status_code == expect, r.text
    return r.json()


def _link(env, budget_id, fid, client=None):
    return (client or env.bm).put(f"/api/budgets/{budget_id}/former-link", {"former_budget_id": fid})


def _view(env, budget_id):
    r = env.bm.get(f"/api/budgets/{budget_id}/history/entered")
    assert r.status_code == 200, r.text
    return r.json()


def _review(env, fy_id, **q):
    r = env.bm.get("/api/reports/budget-review", params={"fiscal_year_id": fy_id, "as_of": AS_OF, "years": 5, **q})
    assert r.status_code == 200, r.text
    return r.json() if q.get("format", "json") == "json" else r


def _row(rep, rid):
    return next(r for s in ("income", "expense") for r in rep[s] if r["id"] == rid)


def _audit(env, action):
    return env.auditor.get(f"/api/audit-events?action={action}").json()["items"]


def _csv(env, fy_id, text, what="preview"):
    r = env.bm.post(f"/api/budgets/history-entries/{what}", {"fiscal_year_id": fy_id, "csv": text})
    assert r.status_code == 200, r.text
    return r.json()


def test_bowling_resurrected_from_a_former_budget(env, base):
    """Kyle's example: Bowling ran in 2023 and 2024, not later; brought back, it continues the former budget."""
    bowl = _former(env, "450", "Bowling Tournament", note="old spreadsheets")
    _year(env, bowl["id"], "FY2023", "800.00", "760.00")
    _year(env, bowl["id"], "FY2024", "900.00", "910.00")
    lst = env.bm.get("/api/budgets/former").json()
    assert [(f["label"], f["years"], f["continued_by"]) for f in lst] == [("450 Bowling Tournament", 2, None)]
    # nothing continues it yet: 2.3.0 (#382) the review lists it anyway, as a budget not in this Fiscal Year
    rep = _review(env, base["fy"]["id"])
    assert [y["display_name"] for y in rep["years"]] == ["FY2023", "FY2024"]
    nic = _row(rep, f"f{bowl['id']}")
    assert nic["not_in_year"] == {"fiscal_year": "FY2027", "last_year": "FY2024"} and nic["current"] is None
    # create the resurrected budget and choose it under Continues
    b = env.bm.post("/api/budgets", {"fiscal_year_id": base["fy"]["id"], "code": "3000", "name": "Bowling",
                                     "budget_type": "EXPENSE", "amount": "1000.00",
                                     "continues_former_budget_id": bowl["id"]})
    assert b.status_code == 201, b.text
    b = b.json()
    assert b["continues_former_budget_id"] == bowl["id"] and b["continues_budget_id"] is None
    rep = _review(env, base["fy"]["id"])
    assert [(y["display_name"], y["entered"]) for y in rep["years"]] == [("FY2023", True), ("FY2024", True)]
    row = _row(rep, b["id"])
    assert [c["actual"] for c in row["history"]] == ["760.00", "910.00"]
    assert row["history"][0]["entered_as"] == "450 Bowling Tournament"         # called differently then
    assert row["average"]["years"] == 2 and row["average"]["actual"] == "835.00"
    assert _row(rep, base["exp"]["id"])["history"] == [None, None]
    tree = env.bm.get(f"/api/budgets?fiscal_year_id={base['fy']['id']}").json()
    assert next(r for r in tree["expense"] if r["id"] == b["id"])["has_history"] is True
    v = _view(env, b["id"])
    assert v["former"]["id"] == bowl["id"] and v["is_holder"] and len(v["entries"]) == 2


def test_reused_code_is_fixed_by_unlinking(env, base):
    """Code 100 was Bowling before PennyWarden and Golf Outing since: figures attached to Golf by mistake are moved off
    its line by unlinking; nothing is retired or entered again."""
    golf26 = env.budget(env.fy("2026", "2025-07-01", "2026-06-30")["id"], "100", "Golf Outing", "INCOME", "100.00")
    golf27 = env.budget(base["fy"]["id"], "100", "Golf Outing", "INCOME", "100.00")
    assert env.bm.patch(f"/api/budgets/{golf27['id']}", {"continues_budget_id": golf26["id"]}).status_code == 200
    p = _csv(env, base["fy"]["id"], "budget code,year,budgeted,actual\n100,FY2024,500,450\n100,FY2025,500,470\n",
             "import")
    assert p["saved"] == 2 and p["lines"][0]["link"]["id"] == golf26["id"]      # linked from the earliest budget
    v = _view(env, golf27["id"])
    fid = v["former"]["id"]
    assert v["former"]["continued_by"]["id"] == golf26["id"] and not v["is_holder"]
    assert len(_review(env, base["fy"]["id"])["years"]) == 3
    # unlink from Golf, rename the former budget to what it really was
    assert _link(env, golf26["id"], None).status_code == 200
    r = env.bm.patch(f"/api/budgets/former/{fid}", {"name": "Bowling", "reason": "code 100 was reused"})
    assert r.status_code == 200 and r.json()["label"] == "100 Bowling" and r.json()["years"] == 2
    assert _view(env, golf27["id"])["former"] is None and _view(env, golf27["id"])["entries"] == []
    # 2.3.0 (#382): the unlinked years stay in the review, as "100 Bowling", not in FY2027
    rep = _review(env, base["fy"]["id"])
    assert [y["entered"] for y in rep["years"]] == [True, True, False]
    assert _row(rep, golf27["id"])["history"][:2] == [None, None]
    assert _row(rep, f"f{fid}")["not_in_year"]["last_year"] == "FY2025"
    ev = _audit(env, "BUDGET_FORMER_UNLINKED")[0]
    assert str(ev["object_id"]) == str(golf26["id"]) and ev["before"]["former"]["id"] == fid and ev["after"]["former"] is None
    assert _audit(env, "FORMER_BUDGET_UPDATED")[0]["after"]["reason"] == "code 100 was reused"
    # FY2027 Golf -> FY2026 Golf is the ordinary #89 link, untouched
    assert env.bm.get(f"/api/budgets/{golf27['id']}").json()["continues_budget_id"] == golf26["id"]


def test_link_rules(env, base):
    exp_f = _former(env, "101", "Pumpkin Patch")
    inc_f = _former(env, "4500", "Raffle", "INCOME")
    sub = env.budget(base["fy"]["id"], "01", "Pumpkin Patch", amount="10.00", parent=base["exp"]["id"])
    # decision 2: any level - a former top-level budget continued by a sub-budget
    assert _link(env, sub["id"], exp_f["id"]).status_code == 200
    # same type only
    r = _link(env, base["exp"]["id"], inc_f["id"])
    assert r.status_code == 422
    # continued by at most one budget
    r = _link(env, base["exp"]["id"], exp_f["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "ALREADY_CONTINUED"
    assert "already continued by FY2027 1000-01 Pumpkin Patch" in r.json()["error"]["message"]
    # only the earliest budget of a line carries the link
    f28 = env.fy("2028", "2027-07-01", "2028-06-30")
    ops28 = env.budget(f28["id"], "1000", "Operations", "EXPENSE", "1.00")
    assert env.bm.patch(f"/api/budgets/{ops28['id']}", {"continues_budget_id": base["exp"]["id"]}).status_code == 200
    other_f = _former(env, "1000", "Operations")
    r = _link(env, ops28["id"], other_f["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_FIRST_OF_LINE" and "FY2027 1000" in r.json()["error"]["message"]
    # Budget 0 never; a retired former budget never
    tree = env.bm.get(f"/api/budgets?fiscal_year_id={base['fy']['id']}").json()
    assert _link(env, tree["budget_zero"]["id"], other_f["id"]).status_code == 422
    assert env.bm.post(f"/api/budgets/former/{other_f['id']}/retire", {"reason": "made by mistake"}).status_code == 200
    r = _link(env, base["exp"]["id"], other_f["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "FORMER_RETIRED"
    # choosing an earlier PennyWarden budget replaces the former link (one predecessor) and frees the former budget
    f26 = env.fy("2026", "2025-07-01", "2026-06-30")
    fund26 = env.budget(f26["id"], "500", "Fundraisers", "EXPENSE", "10.00")
    pump26 = env.budget(f26["id"], "01", "Pumpkin Patch", amount="1.00", parent=fund26["id"])
    r = env.bm.patch(f"/api/budgets/{sub['id']}", {"continues_budget_id": pump26["id"]})
    assert r.status_code == 200 and r.json()["continues_former_budget_id"] is None
    assert _link(env, pump26["id"], exp_f["id"]).status_code == 200
    assert _view(env, sub["id"])["former"]["id"] == exp_f["id"]       # reached through the earlier budget
    # link options: same type, not taken by another budget, not retired
    opts = env.bm.get(f"/api/budgets/former/link-options?budget_id={base['inc']['id']}").json()
    assert [o["label"] for o in opts] == ["4500 Raffle"]
    opts = env.bm.get(f"/api/budgets/former/link-options?budget_id={base['exp']['id']}").json()
    assert opts == []
    # budget options of a Fiscal Year for a former budget: the earliest of each line only
    got = env.bm.get(f"/api/budgets/former/{exp_f['id']}/budget-options?fiscal_year_id={base['fy']['id']}").json()
    assert [o["code"] for o in got] == ["1000", "1000-00"]           # 1000-01 continues FY2026 500-01 now


def test_linking_is_allowed_in_any_fiscal_year_state(env, base):
    """Reporting only: an approved, locked year's budgets can still be linked (they can't be edited)."""
    env.approve(base["fy"]["id"])
    f = _former(env, "1000", "Operations")
    assert _link(env, base["exp"]["id"], f["id"]).status_code == 200
    _year(env, f["id"], "FY2025", "10", "9")
    assert _review(env, base["fy"]["id"])["years"][0]["entered"] is True


def test_other_continues_the_old_parent_row(env, base):
    """Decision 3: old 100 held the uncategorized amounts = PennyWarden's -00 Other; the parent adds up as in
    PennyWarden years (sub-budgets + Other)."""
    trav = env.budget(base["fy"]["id"], "01", "Travel", amount="10.00", parent=base["exp"]["id"])
    tree = env.bm.get(f"/api/budgets?fiscal_year_id={base['fy']['id']}").json()
    other = next(c for r in tree["expense"] for c in r["children"] if c["is_other"])
    old100 = _former(env, "100", "Fundraisers")
    old101 = _former(env, "101", "Travel")
    _year(env, old100["id"], "FY2025", "300", "280")
    _year(env, old101["id"], "FY2025", "200", "150")
    assert _link(env, other["id"], old100["id"]).status_code == 200
    assert _link(env, trav["id"], old101["id"]).status_code == 200
    rep = _review(env, base["fy"]["id"])
    p = _row(rep, base["exp"]["id"])["history"][0]
    assert (p["budgeted"], p["actual"], p["from_sub_budgets"]) == ("500.00", "430.00", True)
    o = _row(rep, other["id"])["history"][0]
    assert (o["actual"], o["entered_as"]) == ("280.00", "100 Fundraisers")
    # an Other of a later year follows its parent's line, so it can't carry its own link
    f28 = env.fy("2028", "2027-07-01", "2028-06-30")
    p28 = env.budget(f28["id"], "1000", "Operations", "EXPENSE", "100.00")
    env.budget(f28["id"], "01", "Travel", amount="1.00", parent=p28["id"])
    assert env.bm.patch(f"/api/budgets/{p28['id']}", {"continues_budget_id": base["exp"]["id"]}).status_code == 200
    t28 = env.bm.get(f"/api/budgets?fiscal_year_id={f28['id']}").json()
    o28 = next(c for r in t28["expense"] for c in r["children"] if c["is_other"])
    r = _link(env, o28["id"], _former(env, "999", "Spare")["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_FIRST_OF_LINE"
    assert _view(env, o28["id"])["former"]["id"] == old100["id"]


def test_years_keep_their_own_code_and_name(env, base):
    """Decision 6: 2024 '104 Raffle Fundraiser', 2025 '104 Raffle' -> one line, shown as '104 Raffle'."""
    f = _former(env, "104", "Raffle Fundraiser", "INCOME")
    e24 = _year(env, f["id"], "FY2024", "100", "90")
    e25 = _year(env, f["id"], "FY2025", "120", "130", name="Raffle")
    assert e24["name"] is None and e25["name"] == "Raffle" and e25["name_shown"] == "Raffle"
    d = env.bm.get(f"/api/budgets/former/{f['id']}").json()
    assert d["label"] == "104 Raffle" and d["default_name"] == "Raffle Fundraiser"
    assert [x["name_shown"] for x in d["entries"]] == ["Raffle Fundraiser", "Raffle"]
    # correcting a year's name (reason required) keeps the line
    r = env.bm.patch(f"/api/budgets/history-entries/{e24['id']}", {"name": "Raffle Fundraiser 2024", "reason": "typo"})
    assert r.status_code == 200 and r.json()["name"] == "Raffle Fundraiser 2024"
    raffle = env.budget(base["fy"]["id"], "04", "Raffle", amount="1.00", parent=base["inc"]["id"])
    assert _link(env, raffle["id"], f["id"]).status_code == 200
    h = _row(_review(env, base["fy"]["id"]), raffle["id"])["history"]
    assert [c["entered_as"] for c in h] == ["104 Raffle Fundraiser 2024", "104 Raffle"]
    assert "Entered; as 104 Raffle Fundraiser 2024" in _review(env, base["fy"]["id"], format="csv").text


def test_retire_never_deletes_and_unlinks(env, base):
    f = _former(env, "1000", "Operations")
    _year(env, f["id"], "FY2025", "10", "9")
    assert _link(env, base["exp"]["id"], f["id"]).status_code == 200
    assert env.bm.post(f"/api/budgets/former/{f['id']}/retire", {"reason": ""}).status_code == 422
    r = env.bm.post(f"/api/budgets/former/{f['id']}/retire", {"reason": "duplicate of another line"})
    assert r.status_code == 200 and r.json()["retired"] and r.json()["continued_by"] is None
    assert r.json()["entries"][0]["counted"] is False
    assert env.bm.get(f"/api/budgets/{base['exp']['id']}").json()["continues_former_budget_id"] is None
    assert _review(env, base["fy"]["id"])["years"] == []
    assert env.bm.post(f"/api/budgets/former/{f['id']}/retire", {"reason": "again"}).status_code == 409
    assert env.bm.patch(f"/api/budgets/former/{f['id']}", {"name": "x"}).status_code == 409
    _year(env, f["id"], "FY2024", "1", "1", expect=409)
    assert len(_audit(env, "BUDGET_FORMER_UNLINKED")) == 1 and len(_audit(env, "FORMER_BUDGET_RETIRED")) == 1
    con = sqlite3.connect(env.settings.database_path)
    assert con.execute("SELECT count(*) FROM former_budget").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM budget_history_entry").fetchone()[0] == 1
    con.close()
    # listed last, as retired
    assert env.bm.get("/api/budgets/former").json()[0]["retired"] is True


def test_deleting_a_budget_frees_its_former_budget(env, base):
    f = _former(env, "2000", "Supplies")
    b = env.budget(base["fy"]["id"], "2000", "Supplies", "EXPENSE", "10.00")
    assert _link(env, b["id"], f["id"]).status_code == 200
    ba = env.user("budgetadmin", "FINANCIAL", ["BUDGET_MANAGER", "BUDGET_ADMIN"])
    assert ba.post(f"/api/budgets/{b['id']}/delete", {"reason": "not needed"}).status_code == 200
    assert env.bm.get(f"/api/budgets/former/{f['id']}").json()["continued_by"] is None
    b2 = env.budget(base["fy"]["id"], "2001", "Supplies", "EXPENSE", "10.00")
    assert _link(env, b2["id"], f["id"]).status_code == 200


def test_type_change_only_while_unlinked(env, base):
    f = _former(env, "1000", "Operations")
    assert _link(env, base["exp"]["id"], f["id"]).status_code == 200
    r = env.bm.patch(f"/api/budgets/former/{f['id']}", {"budget_type": "INCOME"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "TYPE_LINKED"
    assert _link(env, base["exp"]["id"], None).status_code == 200
    assert env.bm.patch(f"/api/budgets/former/{f['id']}", {"budget_type": "INCOME"}).json()["budget_type"] == "INCOME"


def test_permissions_and_object_scope(env, base):
    """BR-003 / BR-004 / BR-078 / BR-099 (AC-SEC-003, AC-SEC-004, AC-SEC-014)."""
    f = _former(env, "1000", "Operations")
    e = _year(env, f["id"], "FY2025", "1", "1")
    for c in (env.bu, env.ru, env.auditor):          # financial roles and Auditors read
        assert c.get("/api/budgets/former").status_code == 200
        assert c.get(f"/api/budgets/former/{f['id']}").status_code == 200
    for c in (env.admin,):                            # the Administrator sees no financial data
        assert c.get("/api/budgets/former").status_code == 403
        assert c.get(f"/api/budgets/former/{f['id']}").status_code == 403
    body = {"code": "1", "name": "x", "budget_type": "EXPENSE"}
    for c in (env.admin, env.bu, env.ru, env.auditor):
        assert c.post("/api/budgets/former", body).status_code == 403
        assert c.patch(f"/api/budgets/former/{f['id']}", {"name": "y"}).status_code == 403
        assert c.post(f"/api/budgets/former/{f['id']}/retire", {"reason": "x"}).status_code == 403
        assert c.post(f"/api/budgets/former/{f['id']}/entries", {"fiscal_year_label": "FY2024", "budgeted": "1", "actual": "1"}).status_code == 403
        assert _link(env, base["exp"]["id"], f["id"], client=c).status_code == 403
    assert Api(env.app).get("/api/budgets/former").status_code == 401
    # unknown ids: not found, never another workspace's record
    assert env.bm.get("/api/budgets/former/999999").status_code == 404
    assert _link(env, base["exp"]["id"], 999999).status_code == 404
    assert _link(env, 999999, f["id"]).status_code == 404
    # explicit writable fields: protected properties are refused, not assigned (AC-SEC-013)
    r = env.bm.post("/api/budgets/former", {**body, "retired_at": "2020-01-01T00:00:00", "workspace_id": 2})
    assert r.status_code == 422
    r = env.bm.patch(f"/api/budgets/former/{f['id']}", {"retire_reason": "x"})
    assert r.status_code == 422
    r = env.bm.post(f"/api/budgets/former/{f['id']}/entries", {"fiscal_year_label": "FY2023", "budgeted": "1",
                                                                "actual": "1", "former_budget_id": 5})
    assert r.status_code == 422
    assert e["former_budget_id"] == f["id"]


def test_script_text_is_kept_as_text(env, base):
    """AC-SEC-011: names are stored and returned as text (React renders them escaped)."""
    f = _former(env, "<b>1</b>", "<script>alert(1)</script>")
    assert env.bm.get(f"/api/budgets/former/{f['id']}").json()["name"] == "<script>alert(1)</script>"


def test_reporting_only(env, base):
    """BR-048: never actuals, registers or the Budgets page totals."""
    before = env.bm.get(f"/api/budgets?fiscal_year_id={base['fy']['id']}").json()
    f = _former(env, "1000", "Operations")
    _year(env, f["id"], "FY2025", "1000000.00", "999999.00")
    assert _link(env, base["exp"]["id"], f["id"]).status_code == 200
    after = env.bm.get(f"/api/budgets?fiscal_year_id={base['fy']['id']}").json()
    assert after["expense_summary"] == before["expense_summary"]
    assert _row(_review(env, base["fy"]["id"]), base["exp"]["id"])["current"]["actual"] == "0.00"


# ------------------------------------------------------------------ CSV (decisions 4 and 5)
def test_csv_lines_by_budget_code_former_code_and_line_column(env, base):
    trav = env.budget(base["fy"]["id"], "01", "Travel", amount="10.00", parent=base["exp"]["id"])
    text = ("budget code,type,former code,former name,year,budgeted,actual,note,line\n"
            "1000-00,,100,Fundraisers,FY2024,2000,1850,,\n"        # old 100 -> PennyWarden's 1000-00 Other
            "1000-01,,101,Pumpkin Patch,FY2024,5000,6200,,\n"
            "1000-01,,101,Pumpkin Patch,FY2025,5000,5900,,\n"
            ",Expense,450,Bowling,FY2023,800,760,,\n"              # not continued: grouped by former code
            ",Expense,450,Bowling Tournament,FY2024,900,910,,\n"   # renamed the next year: same line
            ",Expense,98,Car Wash,FY2022,50,40,,cw\n"              # renumbered: the line column keeps it one line
            ",Expense,99,Car Wash,FY2023,60,55,,cw\n")
    p = _csv(env, base["fy"]["id"], text)
    assert p["counts"] == {"MATCHED": 7, "REFUSED": 0, "DUPLICATE": 0}
    lines = {g["key"]: g for g in p["lines"]}
    assert set(lines) == {"budget 1000-00", "budget 1000-01", "former 450", "line cw"}
    assert lines["budget 1000-00"]["link"]["code"] == "1000-00" and lines["budget 1000-00"]["former_name"] == "Fundraisers"
    assert (lines["former 450"]["former_name"], lines["former 450"]["link"]) == ("Bowling Tournament", None)
    assert lines["line cw"]["former_code"] == "99" and lines["line cw"]["years"] == 2
    r = _csv(env, base["fy"]["id"], text, "import")
    assert r["saved"] == 7 and r["former_budgets_created"] == 4 and r["links_made"] == 2
    formers = {f["label"]: f for f in env.bm.get("/api/budgets/former").json()}
    assert set(formers) == {"100 Fundraisers", "101 Pumpkin Patch", "450 Bowling Tournament", "99 Car Wash"}
    assert formers["450 Bowling Tournament"]["years"] == 2 and formers["450 Bowling Tournament"]["continued_by"] is None
    d = env.bm.get(f"/api/budgets/former/{formers['99 Car Wash']['id']}").json()
    assert [(x["code_shown"], x["fiscal_year_label"]) for x in d["entries"]] == [("98", "FY2022"), ("99", "FY2023")]
    assert _view(env, trav["id"])["former"]["label"] == "101 Pumpkin Patch"
    p = _row(_review(env, base["fy"]["id"]), base["exp"]["id"])["history"]
    # 2024: 1850 + 6200; 2025: 5900 (FY2022/FY2023 come from the lines nothing continues, 2.3.0 #382)
    assert [c and c["actual"] for c in p] == [None, None, "8050.00", "5900.00"]


def test_csv_matches_existing_former_budgets_and_refuses_conflicts(env, base):
    bowl = _former(env, "450", "Bowling Tournament")
    _year(env, bowl["id"], "FY2023", "1", "1")
    linked = _former(env, "1000", "Operations")
    assert _link(env, base["exp"]["id"], linked["id"]).status_code == 200
    other_f = _former(env, "1000", "Old Operations")
    text = ("budget code,type,former code,former name,year,budgeted,actual\n"
            ",Expense,450,Bowling Tournament,FY2024,2,2\n"                 # adds a year to the existing one
            ",Expense,450,Bowling Tournament,FY2023,3,3\n"                 # that year is already entered
            ",Income,450,Bowling Tournament,FY2022,3,3\n"                  # a different type: its own line, refused
            "4000,,1000,Old Operations,FY2024,1,1\n"                       # Income budget, Expense former budget
            ",Expense,777,Golf,FY2024,1,1\n"
            ",Expense,778,Golf,FY2024,1,1\n")                               # two new lines with the same name: fine
    p = _csv(env, base["fy"]["id"], text)
    st = {r["line"]: (r["status"], r["reason"]) for r in p["rows"]}
    assert st[2][0] == "MATCHED" and st[3] == ("DUPLICATE", "Already entered for that year on this line.")
    assert st[4][0] == "REFUSED" and "is Expense, not Income" in st[4][1]
    assert st[5][0] == "REFUSED" and "is Expense, not Income" in st[5][1]
    assert st[6][0] == st[7][0] == "MATCHED"
    g450 = next(g for g in p["lines"] if g["key"] == "former 450" and g["budget_type"] == "EXPENSE")
    assert g450["former_id"] == bowl["id"] and g450["action"] == "EXISTING"
    # two budgets of the file naming the same new former budget: the second is refused
    text = ("budget code,type,former code,former name,year,budgeted,actual,line\n"
            ",Expense,555,Carnival,FY2024,1,1,a\n"
            ",Expense,555,Carnival,FY2023,1,1,b\n")
    p = _csv(env, base["fy"]["id"], text)
    assert [r["status"] for r in p["rows"]] == ["MATCHED", "REFUSED"] and "Another line of this file" in p["rows"][1]["reason"]
    # a budget whose line already continues a former budget keeps it: the rows go there, whatever former code they name
    text = "budget code,former code,former name,year,budgeted,actual\n1000,1000,Something Else,FY2024,4,4\n"
    p = _csv(env, base["fy"]["id"], text)
    assert p["lines"][0]["former_id"] == linked["id"] and p["lines"][0]["link_action"] == "EXISTING"
    assert other_f


def test_csv_refuses_a_former_budget_continued_elsewhere(env, base):
    f = _former(env, "450", "Bowling")
    b = env.budget(base["fy"]["id"], "3000", "Bowling", "EXPENSE", "1.00")
    assert _link(env, b["id"], f["id"]).status_code == 200
    text = "budget code,former code,former name,year,budgeted,actual\n1000,450,Bowling,FY2024,4,4\n"
    p = _csv(env, base["fy"]["id"], text)
    assert p["rows"][0]["status"] == "REFUSED" and "already continued by FY2027 3000 Bowling" in p["rows"][0]["reason"]


def test_csv_template_lists_the_linked_former_budget(env, base):
    f = _former(env, "100", "Ops before")
    _year(env, f["id"], "FY2025", "1", "1", code="100", name="Ops then")
    assert _link(env, base["exp"]["id"], f["id"]).status_code == 200
    env.bm.patch(f"/api/budgets/{base['inc']['id']}", {"name": "=HYPERLINK(1)"})
    r = env.bm.get(f"/api/budgets/history-entries/template?fiscal_year_id={base['fy']['id']}")
    import csv
    import io
    rows = list(csv.reader(io.StringIO(r.text)))
    exp = next(x for x in rows if x[0] == "1000")
    assert exp[3:5] == ["100", "Ops then"]
    inc = next(x for x in rows if x[0] == "4000")
    assert inc[1] == "'=HYPERLINK(1)"                                    # formula cells neutralised


# ------------------------------------------------------------------ migration
def test_migration_converts_entries_into_linked_former_budgets(tmp_path):
    """0059: each line's 2.2.0 entries become one former budget, continued by the line's earliest budget; entries on
    a deleted budget's line become a former budget nothing continues."""
    from alembic import command

    from fmpoc.db import alembic_config
    url = f"sqlite:///{tmp_path / 'm.sqlite3'}"
    command.upgrade(alembic_config(url), "0058_fundraiser_series_sort")
    c = sqlite3.connect(tmp_path / "m.sqlite3")
    c.execute("pragma foreign_keys=off")
    bcols = [r[1] for r in c.execute("pragma table_info(budget)")]
    budgets = {  # id: (fy, parent, parent_code, child_code, name, type, status, continues)
        1: (1, None, "100", None, "Golf", "INCOME", "APPROVED", None),
        2: (2, None, "100", None, "Golf", "INCOME", "DRAFT", 1),
        3: (2, 2, "100", "01", "Travel", "INCOME", "DRAFT", None),
        4: (2, None, "200", None, "Gone", "EXPENSE", "DELETED", None),
    }
    for i, (fy, parent, pc, cc, name, t, st, cont) in budgets.items():
        row = {k: None for k in bcols}
        row.update(id=i, workspace_id=1, fiscal_year_id=fy, parent_budget_id=parent, parent_code=pc, child_code=cc,
                   name=name, budget_type=t, amount_cents=0, status=st, locked=0, system_managed=0, is_other=0,
                   is_budget_zero=0, continues_budget_id=cont, created_at="2026-01-01 00:00:00",
                   updated_at="2026-01-01 00:00:00")
        c.execute(f"insert into budget ({','.join(row)}) values ({','.join('?' * len(row))})", list(row.values()))
    for i, (bid, year) in enumerate([(1, 2024), (1, 2025), (3, 2024), (4, 2023)], start=1):
        c.execute("insert into budget_history_entry (id, workspace_id, budget_id, fiscal_year_label, year, "
                  "budgeted_cents, actual_cents, created_at) values (?, 1, ?, ?, ?, 100, 90, '2026-10-01 00:00:00')",
                  (i, bid, f"FY{year}", year))
    c.commit()
    c.close()
    command.upgrade(alembic_config(url), "head")
    c = sqlite3.connect(tmp_path / "m.sqlite3")
    formers = {r[0]: r[1:] for r in c.execute("select id, code, name, budget_type from former_budget order by id")}
    assert list(formers.values()) == [("100", "Golf", "INCOME"), ("100-01", "Travel", "INCOME"), ("200", "Gone", "EXPENSE")]
    links = dict(c.execute("select id, continues_former_budget_id from budget").fetchall())
    assert links == {1: 1, 2: None, 3: 2, 4: None}
    assert dict(c.execute("select id, former_budget_id from budget_history_entry").fetchall()) == {1: 1, 2: 1, 3: 2, 4: 3}
    c.close()
