"""2.4.0 (#429): Events & Fundraisers - each record is a Fundraiser or an Event.

BR-EVT-001..005 / AC-EVT-001..010 (recorded in docs/implementation-notes.md); regression for BR-075/076 (type change
audited before/after), BR-098 (mass assignment), BR-099/BR-078 (roles), BR-001 (no hard delete of data kept).
"""
from __future__ import annotations

from fmpoc.models import Fundraiser, FundraiserBudget


def enable(env):
    assert env.admin.put("/api/system/modules", {"fundraisers": True}).status_code == 200


def _create(env, name, start, budget_ids, event_type=None, **kw):
    body = {"name": name, "start_date": start, "budget_ids": budget_ids, **kw}
    if event_type:
        body["event_type"] = event_type
    return env.bm.post("/api/fundraisers", body)


def test_default_type_is_fundraiser_and_shells_save_for_both(env, base):
    """AC-EVT-001 (upgrade/default) and AC-EVT-004 (shells): no type = Fundraiser; a shell needs no budgets."""
    enable(env)
    f = _create(env, "Gala", "2026-09-12", [])
    assert f.status_code == 201 and f.json()["event_type"] == "FUNDRAISER"
    e = _create(env, "Cookout", "2026-09-13", [], "EVENT")
    assert e.status_code == 201 and e.json()["event_type"] == "EVENT"
    assert {n["code"] for n in e.json()["notices"]} >= {"NO_BUDGETS"}
    rows = {r["name"]: r["event_type"] for r in env.bu.get(f"/api/fundraisers?fiscal_year_id={base['fy']['id']}&upcoming=false").json()}
    assert rows.get("Gala", "FUNDRAISER") == "FUNDRAISER"


def test_required_budgets_by_type_are_enforced_server_side(env, base):
    """AC-EVT-005/006: an Event needs Expense (Income optional); a Fundraiser needs both, per Fiscal Year used."""
    enable(env)
    inc, exp = base["inc"]["id"], base["exp"]["id"]
    r = _create(env, "Cookout", "2026-09-12", [inc], "EVENT")
    assert r.status_code == 422 and r.json()["error"]["code"] == "REQUIRED_BUDGETS"
    assert "Expense" in r.json()["error"]["message"]
    assert _create(env, "Cookout", "2026-09-12", [exp], "EVENT").status_code == 201
    assert _create(env, "Cookout 2", "2026-09-12", [inc, exp], "EVENT").status_code == 201
    for ids in ([inc], [exp]):
        r = _create(env, "Gala", "2026-09-12", ids, "FUNDRAISER")
        assert r.status_code == 422 and r.json()["error"]["code"] == "REQUIRED_BUDGETS", ids
    assert _create(env, "Gala", "2026-09-12", [inc, exp]).status_code == 201
    # each Fiscal Year used needs its own: a second year with only Income fails for an Event too
    fy28 = env.fy("2028", "2027-07-01", "2028-06-30")
    inc28 = env.budget(fy28["id"], "4000", "Donations", "INCOME", "100.00")
    r = _create(env, "Bridge", "2027-06-30", [exp, inc28["id"]], "EVENT", end_date="2027-07-01")
    assert r.status_code == 422 and "FY2028" in r.json()["error"]["message"]


def test_two_year_event_shows_one_combined_figure_per_kind(env, base):
    """AC-EVT-009: budgets don't span Fiscal Years, but the event shows one Income and one Expense figure."""
    enable(env)
    fy28 = env.fy("2028", "2027-07-01", "2028-06-30")
    exp28 = env.budget(fy28["id"], "1000", "Operations", "EXPENSE", "500.00")
    inc28 = env.budget(fy28["id"], "4000", "Donations", "INCOME", "250.00")
    f = _create(env, "Bridge Gala", "2027-06-30", [base["inc"]["id"], base["exp"]["id"], inc28["id"], exp28["id"]],
                end_date="2027-07-01")
    assert f.status_code == 201, f.text
    cb = f.json()["combined_budgets"]
    assert cb["income"]["budgeted"] == "5250.00" and cb["income"]["fiscal_years"] == 2
    assert cb["expense"]["budgeted"] == "100500.00" and len(cb["expense"]["labels"]) == 2


def test_type_change_is_audited_keeps_goal_and_reapplies_the_rule(env, base):
    """AC-EVT-003: before/after audit, goal kept (hidden for an Event); Event -> Fundraiser needs Income too."""
    enable(env)
    exp = base["exp"]["id"]
    f = _create(env, "Dinner", "2026-09-12", [base["inc"]["id"], exp], goal_amount="500").json()
    body = {"name": "Dinner", "start_date": "2026-09-12", "budget_ids": [base["inc"]["id"], exp]}
    e = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "event_type": "EVENT"})
    assert e.status_code == 200, e.text
    assert e.json()["event_type"] == "EVENT" and e.json()["totals"]["goal"] is None
    assert e.json()["goal_amount"] == "500.00"                          # kept
    ev = env.auditor.get(f"/api/audit-events?action=FUNDRAISER_UPDATED&object_id={f['id']}").json()["items"][0]
    assert ev["before"]["event_type"] == "FUNDRAISER" and ev["after"]["event_type"] == "EVENT"
    # Event with Expense only, then back to Fundraiser without an Income budget: refused
    e = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "budget_ids": [exp]}).json()
    r = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "budget_ids": [exp], "event_type": "FUNDRAISER"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "REQUIRED_BUDGETS"
    back = env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "event_type": "FUNDRAISER"}).json()
    assert back["totals"]["goal"]["goal"] == "500.00"                   # shown again


def test_type_is_writable_only_by_authorized_create_edit(env, base):
    """AC-EVT-010 / BR-098, BR-099: viewers can't change it; other operations ignore an event_type field."""
    enable(env)
    f = _create(env, "Gala", "2026-09-12", []).json()
    body = {"name": "Gala", "start_date": "2026-09-12", "budget_ids": [], "event_type": "EVENT"}
    for c in (env.bu, env.ru, env.auditor):
        assert c.put(f"/api/fundraisers/{f['id']}", body).status_code == 403
    assert env.admin.put(f"/api/fundraisers/{f['id']}", body).status_code == 403
    r = env.bm.put(f"/api/fundraisers/{f['id']}/results-final", {"final": False, "event_type": "EVENT"})
    assert r.status_code == 422          # unknown fields are refused (extra=forbid), nothing changes
    assert env.bm.get(f"/api/fundraisers/{f['id']}").json()["event_type"] == "FUNDRAISER"
    assert env.bm.put(f"/api/fundraisers/{f['id']}", {**body, "event_type": "PARTY"}).status_code == 422


def test_results_final_needs_required_budgets_and_upgraded_record_warns(env, base, app):
    """AC-EVT-007/008: an upgraded record missing a required budget keeps its data, shows a warning, can't be marked
    final until fixed or retyped; other edits still save."""
    enable(env)
    f = _create(env, "Old Fair", "2026-09-12", [base["inc"]["id"], base["exp"]["id"]]).json()
    with app.state.session_factory() as db:           # as if it came from 2.3 with Income only
        x = db.get(Fundraiser, f["id"])
        for fb in list(x.budgets):
            if fb.kind == "EXPENSE":
                db.delete(fb)
        db.commit()
    d = env.bm.get(f"/api/fundraisers/{f['id']}").json()
    assert any(n["code"] == "REQUIRED_BUDGET_MISSING" for n in d["notices"]) and d["required_budget_gaps"]
    r = env.bm.put(f"/api/fundraisers/{f['id']}/results-final", {"final": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "REQUIRED_BUDGETS"
    # a rename that leaves budgets and type alone still saves
    ok = env.bm.put(f"/api/fundraisers/{f['id']}", {"name": "Old Fair (2026)", "start_date": "2026-09-12",
                                                     "budget_ids": [base["inc"]["id"]]})
    assert ok.status_code == 200, ok.text
    # fixed by adding the Expense budget -> final allowed
    fixed = env.bm.put(f"/api/fundraisers/{f['id']}", {"name": "Old Fair (2026)", "start_date": "2026-09-12",
                                                        "budget_ids": [base["inc"]["id"], base["exp"]["id"]]})
    assert fixed.status_code == 200
    assert env.bm.put(f"/api/fundraisers/{f['id']}/results-final", {"final": True}).status_code == 200


def test_series_holds_one_type(env, base):
    """AC-EVT-002: Continues from links the same type only; a linked event's type change needs the link broken."""
    enable(env)
    fy28 = env.fy("2028", "2027-07-01", "2028-06-30")
    exp28 = env.budget(fy28["id"], "1000", "Operations", "EXPENSE", "500.00")
    picnic = _create(env, "Picnic 2026", "2026-09-12", [base["exp"]["id"]], "EVENT").json()
    gala = _create(env, "Gala 2026", "2026-10-12", [base["inc"]["id"], base["exp"]["id"]]).json()
    opts = env.bm.get("/api/fundraisers/continue-options?start_date=2027-09-12&event_type=EVENT").json()
    assert [o["name"] for o in opts] == ["Picnic 2026"]
    r = _create(env, "Picnic 2027", "2027-09-12", [exp28["id"]], "EVENT", continues_from_id=gala["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "SERIES_TYPE"
    p27 = _create(env, "Picnic 2027", "2027-09-12", [exp28["id"]], "EVENT", continues_from_id=picnic["id"]).json()
    assert p27["series_link"]["series"] is not None
    body = {"name": "Picnic 2027", "start_date": "2027-09-12", "budget_ids": [exp28["id"]], "event_type": "FUNDRAISER"}
    r = env.bm.put(f"/api/fundraisers/{p27['id']}", body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "SERIES_TYPE"
    # a Fundraiser can't be added to an Event series either
    sid = p27["series_link"]["series"]["id"]
    r = env.bm.put(f"/api/fundraisers/{gala['id']}/series", {"series_id": sid})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SERIES_TYPE"
    opts = {o["id"]: o for o in env.bm.get(f"/api/fundraisers/{gala['id']}/series-add-options").json()}
    assert opts[sid]["allowed"] is False and "Event" in opts[sid]["reason"]
    assert env.bm.get(f"/api/fundraisers/{gala['id']}").json()["series_link"]["series"] is None


def test_event_hides_goal_and_receipts_and_fy_report_lists_events_apart(env, base):
    """AC-EVT-003/004 (goal and receipts hidden for an Event) and AC-EVT-006 (FY report: Events in their own section,
    not in the fundraising totals)."""
    enable(env)
    gala = _create(env, "Gala", "2026-09-12", [base["inc"]["id"], base["exp"]["id"]]).json()
    picnic = _create(env, "Picnic", "2026-09-20", [base["exp"]["id"]], "EVENT", goal_amount="900").json()
    assert picnic["totals"]["goal"] is None and picnic["goal_amount"] == "900.00"
    env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "40.00"}])
    rep = env.bu.get(f"/api/fundraisers/fy-report?fiscal_year_id={base['fy']['id']}&ids={gala['id']}&ids={picnic['id']}"
                     "&format=json").json()
    assert [r["name"] for r in rep["this_year"]] == ["Gala"]
    assert [e["name"] for e in rep["events"]] == ["Picnic"] and rep["events"][0]["expenses"] == "40.00"
    assert sorted(rep["selected_ids"]) == sorted([gala["id"], picnic["id"]])
    only = env.bu.get(f"/api/fundraisers/fy-report?fiscal_year_id={base['fy']['id']}&ids={picnic['id']}&format=json")
    assert only.status_code == 200 and only.json()["this_year"] == []
    for fmt in ("pdf", "pptx"):
        r = env.bu.get(f"/api/fundraisers/fy-report?fiscal_year_id={base['fy']['id']}&ids={gala['id']}&ids={picnic['id']}"
                       f"&format={fmt}")
        assert r.status_code == 200 and len(r.content) > 1000, fmt
    # stakeholder report and deck render for an Event (no goal sections)
    for url in (f"/api/fundraisers/{picnic['id']}/summary-report", f"/api/fundraisers/{picnic['id']}/presentation"):
        r = env.bu.get(url)
        assert r.status_code == 200 and len(r.content) > 1000, (url, r.text[:200])


def test_no_internal_names_change(env, base, app):
    """AC-EVT-001: the API path, table and audit object type stay 'fundraiser'."""
    enable(env)
    f = _create(env, "Cookout", "2026-09-12", [], "EVENT").json()
    ev = env.auditor.get(f"/api/audit-events?action=FUNDRAISER_CREATED&object_id={f['id']}").json()["items"][0]
    assert ev["object_type"] == "fundraiser" and ev["after"]["event_type"] == "EVENT"
    assert Fundraiser.__tablename__ == "fundraiser" and FundraiserBudget.__tablename__ == "fundraiser_budget"
