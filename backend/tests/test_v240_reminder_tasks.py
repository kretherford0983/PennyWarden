"""2.4.0 (#551): reminder tasks - a checklist ticked one at a time, contacts (a fixed entity or a position) and app
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


def mk(c, tasks, **kw):
    body = {"scope": "ORGANIZATION", "title": "Christmas letter", "due_date": D(0), "tasks": tasks, **kw}
    r = c.post("/api/reminders", body)
    assert r.status_code == 201, r.text
    return r.json()


def tick(c, r, i, **body):
    return c.post(f"/api/reminders/{r['id']}/tasks/{r['tasks'][i]['id']}/tick", body)


def audit_actions(env):
    return [e["action"] for e in env.auditor.get("/api/audit-events?object_type=reminder&sort=id&direction=asc")
            .json()["items"]]


def test_christmas_letter_ticks_in_any_order_and_the_last_tick_resolves(env):
    """AC-REM-TASK-001"""
    names = ["Prepare the letter", "Receive stakeholder approvals", "Print", "Mail"]
    r = mk(env.bm, [{"title": n} for n in names])
    assert [t["title"] for t in r["tasks"]] == names and r["tasks_done"] == 0 and r["can_tick"]
    # a Register User ticks; any order is allowed
    x = tick(env.ru, r, 1).json()
    assert x["tasks"][1]["done"] and x["tasks"][1]["done_by"] == "reguser" and x["state"] == "DUE"
    assert tick(env.ru, r, 1).status_code == 409                       # already ticked
    for i in (0, 2):
        x = tick(env.ru, r, i).json()
    assert x["tasks_done"] == 3 and x["state"] == "DUE"
    # Budget Users and Auditors only look
    assert tick(env.bu, r, 3).status_code == 403 and tick(env.auditor, r, 3).status_code == 403
    x = tick(env.ru, r, 3, note="Mailed on time").json()
    assert x["state"] == "RESOLVED" and x["resolution_note"] == "Mailed on time" and x["tasks_done"] == 4
    acts = audit_actions(env)
    assert acts.count("REMINDER_TASK_TICKED") == 4 and acts[-1] == "REMINDER_RESOLVED"
    # unticking a task of a resolved reminder reopens it
    x = env.ru.post(f"/api/reminders/{r['id']}/tasks/{r['tasks'][2]['id']}/untick").json()
    assert x["state"] == "DUE" and x["tasks_done"] == 3 and not x["tasks"][2]["done"]
    assert audit_actions(env)[-2:] == ["REMINDER_REOPENED", "REMINDER_TASK_UNTICKED"]


def test_tasks_tick_only_once_the_reminder_is_shown(env):
    r = mk(env.bm, [{"title": "Prepare"}], due_date=D(40), notify_days_before=30)
    assert r["state"] == "UPCOMING" and not r["can_tick"]
    assert tick(env.bm, r, 0).status_code == 409


def test_resolving_with_open_tasks_needs_a_note(env):
    """AC-REM-TASK-002"""
    r = mk(env.bm, [{"title": "Prepare"}, {"title": "Print"}])
    tick(env.ru, r, 0)
    res = env.ru.post(f"/api/reminders/{r['id']}/resolve", {})
    assert res.status_code == 422 and "note" in res.text
    x = env.ru.post(f"/api/reminders/{r['id']}/resolve", {"note": "No printing this year"}).json()
    assert x["state"] == "RESOLVED" and [t["done"] for t in x["tasks"]] == [True, False]
    # without tasks the note stays optional
    plain = env.bm.post("/api/reminders", {"scope": "ORGANIZATION", "title": "Plain", "due_date": D(0)}).json()
    assert env.ru.post(f"/api/reminders/{plain['id']}/resolve", {}).status_code == 200


def test_a_repeating_reminder_copies_its_tasks_unticked(env):
    """AC-REM-TASK-003"""
    r = mk(env.bm, [{"title": "Prepare"}, {"title": "Mail", "function_id": "page:donations"}],
           repeat_every=1, repeat_unit="YEAR")
    tick(env.ru, r, 0)
    x = tick(env.ru, r, 1).json()
    assert x["state"] == "RESOLVED"
    nxt = env.bm.get("/api/reminders?view=upcoming").json()
    assert len(nxt) == 1 and [(t["title"], t["done"], t["function_id"]) for t in nxt[0]["tasks"]] == [
        ("Prepare", False, None), ("Mail", False, "page:donations")]
    assert {t["id"] for t in nxt[0]["tasks"]}.isdisjoint({t["id"] for t in x["tasks"]})


def test_city_clerk_by_position_follows_the_current_holder(env):
    """AC-REM-TASK-004"""
    jane = person(env.ru, "Jane", "Doe", "City Clerk", "jane@example.org")
    r = mk(env.bm, [{"title": "Email the clerk", "contact_kind": "POSITION", "contact_position": "  city  clerk "},
                    {"title": "Copy Jane", "contact_kind": "ENTITY", "contact_entity_id": jane["id"]}])
    c = r["tasks"][0]["contact"]
    assert r["tasks"][0]["contact_position"] == "city clerk"
    assert c["kind"] == "POSITION" and not c["missing"] and [p["email"] for p in c["people"]] == ["jane@example.org"]
    assert c["people"][0]["address"] == ["1 Main St", "Sample Town, US 55555"]
    # a second active City Clerk: both listed, with the warning flag
    john = person(env.ru, "John", "Roe", "City Clerk", "john@example.org")
    c = env.bm.get("/api/reminders?view=due").json()[0]["tasks"][0]["contact"]
    assert c["several"] and [p["name"] for p in c["people"]] == ["Jane Doe", "John Roe"]
    # Jane inactivated: the position shows John; the fixed contact shows Jane, inactive, with no email
    assert env.ru.post(f"/api/entities/{jane['id']}/inactivate", {}).status_code == 200
    t0, t1 = env.bm.get("/api/reminders?view=due").json()[0]["tasks"]
    assert [p["email"] for p in t0["contact"]["people"]] == ["john@example.org"] and not t0["contact"]["several"]
    assert t1["contact"]["inactive"] and t1["contact"]["missing"] and "email" not in t1["contact"]["people"][0]
    # nobody holds the position: the position is still shown, without contact details
    env.ru.post(f"/api/entities/{john['id']}/inactivate", {})
    t0 = env.bm.get("/api/reminders?view=due").json()[0]["tasks"][0]
    assert t0["contact"]["label"] == "city clerk" and t0["contact"]["missing"] and t0["contact"]["people"] == []


def test_contacts_and_functions_are_checked(env):
    """AC-REM-TASK-005 (server side): only known app functions; contacts must exist."""
    for bad in ({"title": "x", "function_id": "report:nope"}, {"title": "x", "contact_kind": "ENTITY"},
                {"title": "x", "contact_kind": "ENTITY", "contact_entity_id": 999999},
                {"title": "x", "contact_kind": "POSITION", "contact_position": "  "}):
        r = env.bm.post("/api/reminders", {"scope": "ORGANIZATION", "title": "T", "due_date": D(0), "tasks": [bad]})
        assert r.status_code == 422, bad
    r = mk(env.bm, [{"title": "Run the audit report", "function_id": "report:audit"}])
    assert r["tasks"][0]["function_id"] == "report:audit"
    too_many = [{"title": f"Task {i}"} for i in range(26)]
    assert env.bm.post("/api/reminders", {"scope": "ORGANIZATION", "title": "T", "due_date": D(0),
                                          "tasks": too_many}).status_code == 422


def test_tasks_stay_editable_while_shown(env):
    """AC-REM-TASK-006 / BR-REM-TASK-005"""
    jane = person(env.ru, "Jane", "Doe", "City Clerk", "jane@example.org")
    r = mk(env.bm, [{"title": "Prepare"}, {"title": "Email"}])
    tick(env.ru, r, 0)
    # the reminder itself is locked once shown...
    full = {"scope": "ORGANIZATION", "title": "Renamed", "due_date": D(0)}
    assert env.bm.put(f"/api/reminders/{r['id']}", full).status_code == 409
    # ...but its tasks aren't: re-point the contact, add a task, reorder
    t0, t1 = r["tasks"]
    body = {"tasks": [{"id": t1["id"], "title": "Email the clerk", "contact_kind": "ENTITY", "contact_entity_id": jane["id"]},
                      {"id": t0["id"], "title": "Prepare"}, {"title": "File a copy"}]}
    assert env.ru.put(f"/api/reminders/{r['id']}/tasks", body).status_code == 403   # Register Users tick, not edit
    x = env.bm.put(f"/api/reminders/{r['id']}/tasks", body).json()
    assert [(t["title"], t["done"]) for t in x["tasks"]] == [("Email the clerk", False), ("Prepare", True),
                                                            ("File a copy", False)]
    assert x["tasks"][0]["contact"]["people"][0]["email"] == "jane@example.org"
    assert audit_actions(env)[-1] == "REMINDER_UPDATED"
    # a ticked task can't be removed
    res = env.bm.put(f"/api/reminders/{r['id']}/tasks", {"tasks": [{"id": x["tasks"][0]["id"], "title": "Email"}]})
    assert res.status_code == 409 and "REMINDER_TASK_DONE" in res.text
    # once resolved, the tasks are locked too
    env.ru.post(f"/api/reminders/{r['id']}/resolve", {"note": "Done another way"})
    assert env.bm.put(f"/api/reminders/{r['id']}/tasks", {"tasks": []}).status_code == 409


def test_personal_reminders_have_tasks_too(env):
    r = env.ru.post("/api/reminders", {"scope": "PERSONAL", "title": "Mine", "due_date": D(0),
                                       "tasks": [{"title": "One"}]}).json()
    assert r["can_edit_tasks"] and r["can_tick"]
    x = tick(env.ru, r, 0).json()
    assert x["state"] == "RESOLVED"
    assert tick(env.bm, r, 0).status_code == 404       # someone else's personal reminder


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
