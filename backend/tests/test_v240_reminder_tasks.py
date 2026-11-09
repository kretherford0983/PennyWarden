"""2.4.0 (#551): reminder tasks - every reminder has an objective task (last, named by its title; ticking it completes
the reminder) and optional steps in front of it, ticked one at a time; contacts (a fixed entity or a position) and app
functions (BR-REM-TASK-001..005, AC-REM-TASK-001..006)."""
import datetime as dt

import pytest

from fmpoc.services import reminders as _reminders

TODAY = dt.date.today()
D = lambda n: (TODAY + dt.timedelta(days=n)).isoformat()  # noqa: E731


@pytest.fixture(autouse=True)
def _pinned_today(monkeypatch):
    monkeypatch.setattr(_reminders, "today", lambda: TODAY)


def person(c, first, last, position=None, email=None):
    r = c.post("/api/entities", {"entity_type": "INDIVIDUAL", "first_name": first, "last_name": last,
                                 "position": position, "email": email, "address_line1": "1 Main St",
                                 "city": "Sample Town", "state_region": "US", "postal_code": "55555"})
    assert r.status_code == 201, r.text
    return r.json()


def mk(c, tasks=None, **kw):
    body = {"scope": "ORGANIZATION", "title": "Christmas letter", "due_date": D(0), **kw}
    if tasks is not None:
        body["tasks"] = tasks
    r = c.post("/api/reminders", body)
    assert r.status_code == 201, r.text
    return r.json()


def tick(c, r, i, **body):
    return c.post(f"/api/reminders/{r['id']}/tasks/{r['tasks'][i]['id']}/tick", body)


def due(c):
    return c.get("/api/reminders?view=due").json()


def audit_actions(env):
    return [e["action"] for e in env.auditor.get("/api/audit-events?object_type=reminder&sort=id&direction=asc")
            .json()["items"]]


def test_every_reminder_has_its_objective_last_named_by_the_title(env):
    r = mk(env.bm)
    assert [(t["title"], t["objective"], t["done"]) for t in r["tasks"]] == [("Christmas letter", True, False)]
    assert r["steps"] == 0 and r["can_tick"] and r["can_resolve"]
    # steps go in front of the objective; renaming the reminder renames the objective
    x = env.bm.put(f"/api/reminders/{r['id']}/tasks", {"tasks": [{"title": "Prepare"}, {"title": "Print"}]}).json()
    assert [(t["title"], t["objective"]) for t in x["tasks"]] == [("Prepare", False), ("Print", False),
                                                                ("Christmas letter", True)]
    up = env.bm.post("/api/reminders", {"scope": "ORGANIZATION", "title": "Later", "due_date": D(30)}).json()
    body = {"scope": "ORGANIZATION", "title": "Holiday letter", "due_date": D(30)}
    assert env.bm.put(f"/api/reminders/{up['id']}", body).json()["tasks"][-1]["title"] == "Holiday letter"
    # resolving ticks the objective; reopening unticks it (a reminder without steps works as before)
    x = env.ru.post(f"/api/reminders/{r['id']}/resolve", {"note": "Skipped steps"}).json()
    assert x["state"] == "RESOLVED" and x["tasks"][-1]["done"] and x["tasks"][-1]["done_by"] == "reguser"
    x = env.ru.post(f"/api/reminders/{r['id']}/reopen").json()
    assert x["state"] == "DUE" and not x["tasks"][-1]["done"]


def test_christmas_letter_steps_in_any_order_then_the_objective_completes_it(env):
    """AC-REM-TASK-001"""
    names = ["Prepare the letter", "Receive stakeholder approvals", "Print", "Mail"]
    r = mk(env.bm, [{"title": n} for n in names])
    assert [t["title"] for t in r["tasks"]] == [*names, "Christmas letter"] and r["steps"] == 4 and r["steps_done"] == 0
    # a Register User ticks; any order is allowed
    x = tick(env.ru, r, 1).json()
    assert x["tasks"][1]["done"] and x["tasks"][1]["done_by"] == "reguser" and x["state"] == "DUE"
    assert tick(env.ru, r, 1).status_code == 409                       # already ticked
    for i in (0, 2, 3):
        x = tick(env.ru, r, i).json()
    assert x["steps_done"] == 4 and x["state"] == "DUE"                 # the last step doesn't complete it
    # Budget Users and Auditors only look
    assert tick(env.bu, r, 4).status_code == 403 and tick(env.auditor, r, 4).status_code == 403
    x = tick(env.ru, r, 4, note="Mailed on time").json()                # the objective does
    assert x["state"] == "RESOLVED" and x["resolution_note"] == "Mailed on time" and x["tasks"][4]["done"]
    acts = audit_actions(env)
    assert acts.count("REMINDER_TASK_TICKED") == 4 and acts[-1] == "REMINDER_RESOLVED"
    # unticking a step of a resolved reminder reopens it
    x = env.ru.post(f"/api/reminders/{r['id']}/tasks/{r['tasks'][2]['id']}/untick").json()
    assert x["state"] == "DUE" and x["steps_done"] == 3 and not x["tasks"][2]["done"] and not x["tasks"][4]["done"]
    assert audit_actions(env)[-2:] == ["REMINDER_REOPENED", "REMINDER_TASK_UNTICKED"]
    # unticking the objective of a resolved reminder is a reopen
    tick(env.ru, r, 2)
    tick(env.ru, r, 4)
    x = env.ru.post(f"/api/reminders/{r['id']}/tasks/{r['tasks'][4]['id']}/untick").json()
    assert x["state"] == "DUE" and x["steps_done"] == 4


def test_tasks_tick_only_once_the_reminder_is_shown(env):
    r = mk(env.bm, [{"title": "Prepare"}], due_date=D(40), notify_days_before=30)
    assert r["state"] == "UPCOMING" and not r["can_tick"]
    assert tick(env.bm, r, 0).status_code == 409 and tick(env.bm, r, 1).status_code == 409


def test_completing_with_open_steps_needs_a_note(env):
    """AC-REM-TASK-002"""
    r = mk(env.bm, [{"title": "Prepare"}, {"title": "Print"}])
    tick(env.ru, r, 0)
    for res in (env.ru.post(f"/api/reminders/{r['id']}/resolve", {}), tick(env.ru, r, 2)):
        assert res.status_code == 422 and "note" in res.text
    x = tick(env.ru, r, 2, note="No printing this year").json()
    assert x["state"] == "RESOLVED" and [t["done"] for t in x["tasks"]] == [True, False, True]
    # without steps the note stays optional
    plain = mk(env.bm, title="Plain")
    assert env.ru.post(f"/api/reminders/{plain['id']}/resolve", {}).status_code == 200


def test_a_repeating_reminder_copies_its_tasks_unticked(env):
    """AC-REM-TASK-003"""
    r = mk(env.bm, [{"title": "Prepare"}, {"title": "Mail", "function_id": "page:donations"}],
           repeat_every=1, repeat_unit="YEAR", objective={"function_id": "report:audit"})
    tick(env.ru, r, 0)
    tick(env.ru, r, 1)
    assert tick(env.ru, r, 2).json()["state"] == "RESOLVED"
    nxt = env.bm.get("/api/reminders?view=upcoming").json()
    assert len(nxt) == 1 and [(t["title"], t["done"], t["function_id"], t["objective"]) for t in nxt[0]["tasks"]] == [
        ("Prepare", False, None, False), ("Mail", False, "page:donations", False),
        ("Christmas letter", False, "report:audit", True)]
    assert {t["id"] for t in nxt[0]["tasks"]}.isdisjoint({t["id"] for t in r["tasks"]})


def test_city_clerk_by_position_follows_the_current_holder(env):
    """AC-REM-TASK-004: here on the objective of a reminder without steps, and on a step"""
    jane = person(env.ru, "Jane", "Doe", "City Clerk", "jane@example.org")
    r = mk(env.bm, [{"title": "Copy Jane", "contact_kind": "ENTITY", "contact_entity_id": jane["id"]}],
           title="Email the City Clerk", objective={"contact_kind": "POSITION", "contact_position": "  city  clerk "})
    obj = r["tasks"][1]
    c = obj["contact"]
    assert obj["objective"] and obj["contact_position"] == "city clerk"
    assert c["kind"] == "POSITION" and not c["missing"] and [p["email"] for p in c["people"]] == ["jane@example.org"]
    assert c["people"][0]["address"] == ["1 Main St", "Sample Town, US 55555"]
    # a second active City Clerk: both listed, with the warning flag
    john = person(env.ru, "John", "Roe", "City Clerk", "john@example.org")
    c = due(env.bm)[0]["tasks"][1]["contact"]
    assert c["several"] and [p["name"] for p in c["people"]] == ["Jane Doe", "John Roe"]
    # Jane inactivated: the position shows John; the fixed contact shows Jane, inactive, with no email
    assert env.ru.post(f"/api/entities/{jane['id']}/inactivate", {}).status_code == 200
    step, obj = due(env.bm)[0]["tasks"]
    assert [p["email"] for p in obj["contact"]["people"]] == ["john@example.org"] and not obj["contact"]["several"]
    assert step["contact"]["inactive"] and step["contact"]["missing"] and "email" not in step["contact"]["people"][0]
    # nobody holds the position: the position is still shown, without contact details
    env.ru.post(f"/api/entities/{john['id']}/inactivate", {})
    obj = due(env.bm)[0]["tasks"][1]
    assert obj["contact"]["label"] == "city clerk" and obj["contact"]["missing"] and obj["contact"]["people"] == []


def test_contacts_and_functions_are_checked(env):
    """AC-REM-TASK-005 (server side): only known app functions; contacts must exist; at most 25 tasks."""
    for bad in ({"title": "x", "function_id": "report:nope"}, {"title": "x", "contact_kind": "ENTITY"},
                {"title": "x", "contact_kind": "ENTITY", "contact_entity_id": 999999},
                {"title": "x", "contact_kind": "POSITION", "contact_position": "  "}):
        r = env.bm.post("/api/reminders", {"scope": "ORGANIZATION", "title": "T", "due_date": D(0), "tasks": [bad]})
        assert r.status_code == 422, bad
    bad_obj = env.bm.post("/api/reminders", {"scope": "ORGANIZATION", "title": "T", "due_date": D(0),
                                             "objective": {"function_id": "page:nope"}})
    assert bad_obj.status_code == 422
    r = mk(env.bm, [{"title": "Run the audit report", "function_id": "report:audit"}])
    assert r["tasks"][0]["function_id"] == "report:audit"
    body = {"scope": "ORGANIZATION", "title": "T", "due_date": D(0)}
    assert env.bm.post("/api/reminders", {**body, "tasks": [{"title": f"S{i}"} for i in range(24)]}).status_code == 201
    assert env.bm.post("/api/reminders", {**body, "tasks": [{"title": f"S{i}"} for i in range(25)]}).status_code == 422


def test_tasks_stay_editable_while_shown_and_the_objective_stays_last(env):
    """AC-REM-TASK-006 / BR-REM-TASK-005"""
    jane = person(env.ru, "Jane", "Doe", "City Clerk", "jane@example.org")
    r = mk(env.bm, [{"title": "A"}, {"title": "B"}, {"title": "C"}, {"title": "D"}], title="E")
    tick(env.ru, r, 0)
    # the reminder itself is locked once shown...
    assert env.bm.put(f"/api/reminders/{r['id']}", {"scope": "ORGANIZATION", "title": "Renamed",
                                                    "due_date": D(0)}).status_code == 409
    # ...but its steps aren't: move D before C (ticks kept), re-point a contact, add a step
    a, b, c_, d = r["tasks"][:4]
    body = {"tasks": [{"id": a["id"], "title": "A"}, {"id": b["id"], "title": "B", "contact_kind": "ENTITY",
                                                       "contact_entity_id": jane["id"]},
                      {"id": d["id"], "title": "D"}, {"id": c_["id"], "title": "C"}, {"title": "F"}]}
    assert env.ru.put(f"/api/reminders/{r['id']}/tasks", body).status_code == 403   # Register Users tick, not edit
    x = env.bm.put(f"/api/reminders/{r['id']}/tasks", body).json()
    assert [(t["title"], t["done"]) for t in x["tasks"]] == [("A", True), ("B", False), ("D", False), ("C", False),
                                                            ("F", False), ("E", False)]
    assert x["tasks"][1]["contact"]["people"][0]["email"] == "jane@example.org"
    assert audit_actions(env)[-1] == "REMINDER_UPDATED"
    # the objective can't be sent as a step (it isn't one) nor removed by leaving it out
    obj_id = x["tasks"][-1]["id"]
    assert env.bm.put(f"/api/reminders/{r['id']}/tasks", {"tasks": [{"id": obj_id, "title": "E"}]}).status_code == 422
    y = env.bm.put(f"/api/reminders/{r['id']}/tasks", {"tasks": [{"id": x["tasks"][0]["id"], "title": "A"}]}).json()
    assert [t["title"] for t in y["tasks"]] == ["A", "E"] and y["tasks"][-1]["id"] == obj_id
    assert y["state"] == "DUE"                               # removing steps never completes the reminder
    # a ticked step can't be removed
    res = env.bm.put(f"/api/reminders/{r['id']}/tasks", {"tasks": []})
    assert res.status_code == 409 and "REMINDER_TASK_DONE" in res.text
    # once resolved, the tasks are locked too
    env.ru.post(f"/api/reminders/{r['id']}/resolve", {})
    assert env.bm.put(f"/api/reminders/{r['id']}/tasks", {"tasks": []}).status_code == 409


def test_personal_reminders_have_tasks_too(env):
    r = env.ru.post("/api/reminders", {"scope": "PERSONAL", "title": "Mine", "due_date": D(0),
                                       "tasks": [{"title": "One"}]}).json()
    assert r["can_edit_tasks"] and r["can_tick"]
    tick(env.ru, r, 0)
    assert tick(env.ru, r, 1).json()["state"] == "RESOLVED"
    assert tick(env.bm, r, 0).status_code == 404       # someone else's personal reminder


def test_upgrade_gives_every_existing_reminder_its_objective(tmp_path):
    """Migration 0089: one objective per reminder, ticked (by the resolver) when the reminder is resolved."""
    from alembic import command
    from sqlalchemy import create_engine

    from fmpoc.db import alembic_config, upgrade_database
    u = f"sqlite:///{tmp_path / 'm.sqlite3'}"
    command.upgrade(alembic_config(u), "0088_invoice_email_sender")
    eng = create_engine(u)
    with eng.begin() as c:
        c.exec_driver_sql("INSERT INTO workspace (id, name, created_at, next_entity_number) VALUES (1, 'W', '2026-01-01', 1)")
        c.exec_driver_sql("PRAGMA foreign_keys=OFF")         # no user rows needed for this check
        for rid, title, res in ((1, "Open one", None), (2, "Done one", "2026-02-01 10:00:00")):
            c.exec_driver_sql("INSERT INTO reminder (id, workspace_id, scope, owner_user_id, title, due_date, "
                              "notify_days_before, resolved_at, resolved_by_user_id, created_at, updated_at, repeat_index) "
                              "VALUES (?, 1, 'ORGANIZATION', 7, ?, '2026-01-15', 0, ?, ?, '2026-01-01', '2026-01-01', 0)",
                              (rid, title, res, 7 if res else None))
    upgrade_database(u)
    with eng.connect() as c:
        rows = c.exec_driver_sql("SELECT reminder_id, title, is_objective, done_at IS NOT NULL, done_by_user_id, seq "
                                 "FROM reminder_task ORDER BY reminder_id").fetchall()
    assert [tuple(r) for r in rows] == [(1, "Open one", 1, 0, None, 0), (2, "Done one", 1, 1, 7, 0)]


def test_function_ids_match_the_frontend():
    """The server's list of app functions is the UI's: every report of the registry and every page of functions.ts."""
    import pathlib
    import re
    from fmpoc.services.reminder_tasks import FUNCTION_IDS
    src = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"
    reports = set(re.findall(r'^\s*\{ id: "([a-z0-9-]+)", name:',
                             (src / "pages/reports/registry.ts").read_text().split("export const REPORTS")[1], re.M))
    pages = set(re.findall(r'id: "(page:[a-z-]+)"', (src / "functions.ts").read_text()))
    assert FUNCTION_IDS == {f"report:{r}" for r in reports} | pages


def test_entities_search_finds_people_by_position(env):
    """2.4.0 (#551): the Entities search also looks at the position (and the list shows it)."""
    person(env.ru, "Jane", "Doe", "City Clerk", "jane@example.org")
    person(env.ru, "John", "Roe", "Treasurer")
    found = env.bm.get("/api/entities?search=city%20cl").json()
    assert [(e["first_name"], e["position"]) for e in found] == [("Jane", "City Clerk")]
