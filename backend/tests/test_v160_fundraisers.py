"""v1.6.0 CR-033: Fundraiser module - switch, access, shells, the 3-month Fiscal Year rule, inclusion and figures."""
from fmpoc.models import FiscalYear


def enable(env, on=True):
    r = env.admin.put("/api/system/modules", {"fundraisers": on})
    assert r.status_code == 200, r.text
    return r.json()


def test_module_switch_and_access(env, base):
    # off by default: hidden from /me and the API
    assert env.bm.get("/api/auth/me").json()["modules"] == {"fundraisers": False, "checks": False}
    assert env.bm.get("/api/fundraisers").json()["error"]["code"] == "MODULE_DISABLED"
    # only Administrators switch modules
    assert env.bm.put("/api/system/modules", {"fundraisers": True}).status_code == 403
    assert enable(env) == {"fundraisers": True, "checks": False}
    assert env.bu.get("/api/auth/me").json()["modules"]["fundraisers"] is True
    log = env.admin.get("/api/audit-events?action=MODULE_ENABLED").json()
    assert any(e["action"] == "MODULE_ENABLED" for e in log["items"])
    # view: financial roles + Auditor; not Administrators. Manage: Budget Manager only.
    for c in (env.bm, env.bu, env.ru, env.auditor):
        assert c.get("/api/fundraisers").status_code == 200
    assert env.admin.get("/api/fundraisers").status_code == 403
    body = {"name": "Spring Gala", "start_date": "2026-09-12", "budget_ids": []}
    for c in (env.bu, env.ru, env.auditor, env.admin):
        assert c.post("/api/fundraisers", body).status_code == 403
    assert env.bm.post("/api/fundraisers", body).status_code == 201
    # turning it off keeps the data
    enable(env, False)
    assert env.bm.get("/api/fundraisers").status_code == 404
    enable(env, True)
    assert [f["name"] for f in env.bm.get("/api/fundraisers?include_archived=true").json()] == ["Spring Gala"]


def test_inclusion_by_budget_filter_and_figures(env, base):
    enable(env)
    acct = base["acct"]["id"]
    env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "200.00", "description": "Gala supplies"}],
            date="2026-07-15")  # weeks before the event: included (dates are display only)
    env.txn(acct, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "1250.00", "description": "Gala tickets"},
                              {"budget_id": base["inc_leaf"], "amount": "75.00", "description": "General donation"}],
            date="2026-09-14")
    void = env.txn(acct, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "999.00", "description": "Gala void"}])
    assert env.ru.post(f"/api/transactions/{void['id']}/void", {"reason": "typo", "confirm_irreversible": True}).status_code == 200
    body = {"name": "Spring Gala", "description": "Annual", "start_date": "2026-09-12", "end_date": "2026-09-13",
            "budget_ids": [base["inc"]["id"], base["exp"]["id"]]}
    f = env.bm.post("/api/fundraisers", body).json()
    assert f["status"] in ("ENDED", "IN_PROGRESS", "PLANNED")
    assert f["totals"]["income"] == "1325.00" and f["totals"]["expense"] == "200.00" and f["totals"]["net"] == "1125.00"
    assert f["totals"]["roi"] == "5.6250"
    assert len(f["lines"]) == 3 and f["lines"][0]["transaction_date"] == "2026-07-15"
    assert [c["net"] for c in f["cumulative"]] == ["-200.00", "1125.00"]
    # filter (case-insensitive contains): leaves out the general donation, with a warning notice
    f = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "filter_text": "GALA"}).json()
    assert f["totals"]["income"] == "1250.00" and f["filtered_out_lines"] == 1
    assert any(n["code"] == "FILTER" for n in f["notices"])
    # regex (RE2: linear time; unsupported constructs are refused)
    f = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "filter_text": r"^gala (tickets|supplies)$", "filter_regex": True}).json()
    assert f["totals"]["income"] == "1250.00" and f["totals"]["expense"] == "200.00"
    r = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "filter_text": r"(a)\1", "filter_regex": True})
    assert r.status_code == 422
    # plain text is not a pattern
    f = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "filter_text": "(tickets"}).json()
    assert f["totals"]["income"] == "0.00"
    # preview for the form
    p = env.bm.post("/api/fundraisers/preview", {"budget_ids": [base["inc"]["id"]], "filter_text": "gala"}).json()
    assert p["total_lines"] == 2 and p["matched_lines"] == 1 and p["unmatched_samples"] == ["General donation"]
    # everyone with access can read it; audit trail
    assert env.auditor.get(f"/api/fundraisers/{f['id']}").json()["totals"]["income"] == "0.00"
    acts = [e["action"] for e in env.auditor.get("/api/audit-events?object_type=fundraiser").json()["items"]]
    assert "FUNDRAISER_CREATED" in acts and "FUNDRAISER_UPDATED" in acts


def test_parent_and_other_budget_warnings_and_shared_budget(env, base):
    enable(env)
    fy = base["fy"]["id"]
    parent = env.budget(fy, "2000", "Events", "EXPENSE", "3000.00")
    child = env.budget(fy, "01", "Gala", amount="1000.00", parent=parent["id"])
    opts = env.bm.get("/api/fundraisers/budget-options?start_date=2026-09-12").json()
    assert [o["fiscal_year"]["id"] for o in opts] == [fy]
    exp = {o["label"]: o for o in opts[0]["expense"]}
    assert {w["code"] for w in exp["2000 Events"]["warnings"]} == {"PARENT_BUDGET"}
    assert {w["code"] for w in exp["2000-00 Other"]["warnings"]} == {"OTHER_BUDGET"}
    assert exp["2000-01 Gala"]["warnings"] == []
    assert "1000 Operations" in exp and exp["1000 Operations"]["warnings"] == []
    # a parent includes its sub-budgets
    env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": child["id"], "amount": "40.00"}])
    a = env.bm.post("/api/fundraisers", {"name": "A", "start_date": "2026-09-12", "budget_ids": [parent["id"]]}).json()
    assert a["totals"]["expense"] == "40.00"
    assert any(n["code"] == "PARENT_BUDGET" for n in a["notices"])
    b = env.bm.post("/api/fundraisers", {"name": "B", "start_date": "2026-10-01", "budget_ids": [child["id"]]}).json()
    assert any(n["code"] == "SHARED_BUDGET" and "A" in n["message"] for n in b["notices"])
    # one budget per kind per Fiscal Year; Budget 0 refused
    r = env.bm.post("/api/fundraisers", {"name": "C", "start_date": "2026-09-12", "budget_ids": [parent["id"], base["exp"]["id"]]})
    assert r.status_code == 422


def test_shells_and_three_month_window_across_fiscal_years(env, base, app):
    """Kyle's examples (FYs Jul-Jun here): shell before the FY exists; second FY within 3 months; closed FY frozen."""
    enable(env)
    fy27 = base["fy"]  # 2026-07-01 .. 2027-06-30
    # shell for an event after every existing FY: allowed, listed as upcoming
    shell = env.bm.post("/api/fundraisers", {"name": "Summer Fair", "start_date": "2027-08-20", "budget_ids": []}).json()
    assert shell["budgets"] == [] and {n["code"] for n in shell["notices"]} >= {"NO_BUDGETS", "FUTURE_FY"}
    assert [x["name"] for x in env.bu.get("/api/fundraisers?upcoming=true").json()] == ["Summer Fair"]
    assert env.bu.get(f"/api/fundraisers?fiscal_year_id={fy27['id']}").json() == []
    # FY2027 budgets are allowed (event within 3 months of its end); the event's own FY does not exist yet
    opts = env.bm.get("/api/fundraisers/budget-options?start_date=2027-08-20").json()
    assert [o["fiscal_year"]["id"] for o in opts] == [fy27["id"]]
    body = {"name": "Summer Fair", "start_date": "2027-08-20", "budget_ids": [base["exp"]["id"]]}
    f = env.bm.put(f"/api/fundraisers/{shell['id']}", body).json()
    assert any(n["code"] == "FUTURE_FY" for n in f["notices"])
    assert [x["name"] for x in env.bu.get(f"/api/fundraisers?fiscal_year_id={fy27['id']}").json()] == ["Summer Fair"]
    # next FY set up (Draft): its budget can be added -> two FYs, listed under both
    fy28 = env.fy("2028", "2027-07-01", "2028-06-30")
    inc28 = env.budget(fy28["id"], "4000", "Donations", "INCOME", "1000.00")
    f = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "budget_ids": [base["exp"]["id"], inc28["id"]]}).json()
    assert [y["id"] for y in f["fiscal_years"]] == [fy27["id"], fy28["id"]] and len(f["per_fiscal_year"]) == 2
    assert [x["name"] for x in env.bu.get(f"/api/fundraisers?fiscal_year_id={fy28['id']}").json()] == ["Summer Fair"]
    assert env.bu.get("/api/fundraisers?upcoming=true").json() == []
    # an event far from a FY cannot use its budgets
    r = env.bm.post("/api/fundraisers", {"name": "Winter", "start_date": "2028-01-15", "budget_ids": [base["exp"]["id"]]})
    assert r.status_code == 422 and "3 months" in r.json()["error"]["message"]
    # moving the event so far that a chosen budget no longer qualifies is refused
    r = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "start_date": "2027-12-01", "budget_ids": [base["exp"]["id"], inc28["id"]]})
    assert r.status_code == 422
    # FY2027 closed: its budget is frozen, the FY2028 part stays editable
    with app.state.session_factory() as db:
        db.get(FiscalYear, fy27["id"]).status = "CLOSED"
        db.commit()
    r = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "budget_ids": [inc28["id"]]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "FISCAL_YEAR_CLOSED"
    exp28 = env.budget(fy28["id"], "1000", "Operations", "EXPENSE", "500.00")
    f = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "name": "Summer Fair 2027",
                                                   "budget_ids": [base["exp"]["id"], inc28["id"], exp28["id"]]}).json()
    assert f["name"] == "Summer Fair 2027" and len(f["budgets"]) == 3
    assert [p["read_only"] for p in f["per_fiscal_year"]] == [True, False]
    # an event in a closed Fiscal Year can no longer be set up; past events in an open FY can
    r = env.bm.post("/api/fundraisers", {"name": "Late", "start_date": "2027-01-10", "budget_ids": []})
    assert r.status_code == 409 and r.json()["error"]["code"] == "FISCAL_YEAR_CLOSED"
    assert env.bm.post("/api/fundraisers", {"name": "Late", "start_date": "2027-08-01", "budget_ids": []}).status_code == 201
    # deleting a fundraiser that uses a closed FY is refused (archive instead)
    assert env.bm.delete(f"/api/fundraisers/{f['id']}").status_code == 409
    assert env.bm.post(f"/api/fundraisers/{f['id']}/archive").json()["status"] == "ARCHIVED"
    names = [x["name"] for x in env.bu.get(f"/api/fundraisers?fiscal_year_id={fy28['id']}").json()]
    assert "Summer Fair 2027" not in names
    names = [x["name"] for x in env.bu.get(f"/api/fundraisers?fiscal_year_id={fy28['id']}&include_archived=true").json()]
    assert "Summer Fair 2027" in names


def test_two_fiscal_years_must_be_adjacent_and_at_most_two(env, base):
    enable(env)
    fy28 = env.fy("2028", "2027-07-01", "2028-06-30")
    inc27 = base["inc"]["id"]
    exp28 = env.budget(fy28["id"], "1000", "Ops", "EXPENSE", "1.00")["id"]
    ok = env.bm.post("/api/fundraisers", {"name": "Bridge", "start_date": "2027-06-30", "end_date": "2027-07-01",
                                          "budget_ids": [inc27, exp28]})
    assert ok.status_code == 201
    r = env.bm.post("/api/fundraisers", {"name": "X", "start_date": "2027-07-02", "end_date": "2027-07-01", "budget_ids": []})
    assert r.status_code == 422  # end before start


def test_delete_shell_and_validation(env, base):
    enable(env)
    f = env.bm.post("/api/fundraisers", {"name": "Bake sale", "start_date": "2026-10-03", "budget_ids": []}).json()
    assert f["end_date"] == "2026-10-03"  # one-day event
    assert env.bm.delete(f"/api/fundraisers/{f['id']}").json() == {"deleted": True}
    assert env.bm.get(f"/api/fundraisers/{f['id']}").status_code == 404
    assert env.bm.post("/api/fundraisers", {"name": "", "start_date": "2026-10-03"}).status_code == 422
    assert env.bm.post("/api/fundraisers", {"name": "F", "start_date": "2026-10-03", "filter_text": "x" * 201}).status_code == 422
