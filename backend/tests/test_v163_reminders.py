"""v1.6.3 CR-036: reminders and notifications."""
import datetime as dt

import pytest

from fmpoc.services import reminders as _reminders

# The reminder service's "today" is pinned to the date the tests were collected, so a run that crosses
# midnight (as a CI build in the evening, US time, crosses midnight UTC) still agrees with D().
TODAY = dt.date.today()
D = lambda n: (TODAY + dt.timedelta(days=n)).isoformat()  # noqa: E731


@pytest.fixture(autouse=True)
def _pinned_today(monkeypatch):
    monkeypatch.setattr(_reminders, "today", lambda: TODAY)


def mk(c, **kw):
    return c.post("/api/reminders", {"title": "Reconcile bank", "due_date": D(0), **kw})


def titles(c, view="due"):
    return [r["title"] for r in c.get(f"/api/reminders?view={view}").json()]


def test_personal_reminders_are_private(env, base):
    assert mk(env.bu).status_code == 403 and mk(env.auditor).status_code == 403 and mk(env.admin).status_code == 403
    r = mk(env.ru, title="Call the bank", details="About fees")
    assert r.status_code == 201 and r.json()["state"] == "DUE" and r.json()["scope"] == "PERSONAL"
    rid = r.json()["id"]
    assert titles(env.ru) == ["Call the bank"] and env.ru.get("/api/reminders/count").json() == {"due": 1}
    for c in (env.bm, env.bu, env.auditor):  # nobody else sees or touches it
        assert titles(c) == [] and c.get("/api/reminders/count").json() == {"due": 0}
        assert c.post(f"/api/reminders/{rid}/resolve", {}).status_code == 404
    assert env.admin.get("/api/reminders").status_code == 403
    # stays until resolved; optional note; reopen
    x = env.ru.post(f"/api/reminders/{rid}/resolve", {"note": "Done by phone"}).json()
    assert x["state"] == "RESOLVED" and x["resolution_note"] == "Done by phone" and x["resolved_by"] == "reguser"
    assert titles(env.ru) == [] and titles(env.ru, "resolved") == ["Call the bank"]
    assert env.ru.post(f"/api/reminders/{rid}/resolve", {}).status_code == 409
    assert env.ru.post(f"/api/reminders/{rid}/reopen").json()["state"] == "DUE"
    acts = [e["action"] for e in env.auditor.get("/api/audit-events?object_type=reminder&sort=id&direction=asc").json()["items"]]
    assert acts == ["REMINDER_CREATED", "REMINDER_RESOLVED", "REMINDER_REOPENED"]


def test_organization_reminders_roles(env, base):
    assert mk(env.ru, scope="ORGANIZATION").status_code == 403  # only Budget Managers create them
    due = mk(env.bm, scope="ORGANIZATION", title="File annual return").json()
    mk(env.bm, scope="ORGANIZATION", title="Renew insurance", due_date=D(30))
    # everyone with financial access (and Auditors) sees the due one; only Budget Managers see upcoming ones
    for c in (env.bm, env.bu, env.ru, env.auditor):
        assert titles(c) == ["File annual return"]
    assert titles(env.bm, "upcoming") == ["Renew insurance"]
    for c in (env.bu, env.ru, env.auditor):
        assert titles(c, "upcoming") == []
    # read-only users cannot clear it; Register Users can, with a note
    for c in (env.bu, env.auditor):
        assert c.post(f"/api/reminders/{due['id']}/resolve", {}).status_code == 403
        assert c.get("/api/reminders").json()[0]["can_resolve"] is False
    assert env.ru.post(f"/api/reminders/{due['id']}/resolve", {"note": "Filed"}).status_code == 200
    assert titles(env.bu) == [] and titles(env.bu, "resolved") == []       # cleared -> gone for read-only users
    assert titles(env.ru, "resolved") == ["File annual return"] == titles(env.bm, "resolved")
    assert env.bm.post(f"/api/reminders/{due['id']}/reopen").status_code == 200
    assert titles(env.auditor) == ["File annual return"]


def test_show_days_before_edit_delete_and_links(env, base):
    fy = base["fy"]["id"]
    r = mk(env.bm, scope="ORGANIZATION", title="Approve budget", due_date=D(10), notify_days_before=3,
           link_type="FISCAL_YEAR", link_id=fy).json()
    assert r["state"] == "UPCOMING" and r["show_date"] == D(7) and r["link"]["url"] == f"/fiscal-years/{fy}"
    assert r["can_edit"] and env.bm.post(f"/api/reminders/{r['id']}/resolve", {}).status_code == 409  # not due yet
    # edit before it is shown: now it shows from today (10 days before the due date)
    body = {"scope": "ORGANIZATION", "title": "Approve the budget", "due_date": D(10), "notify_days_before": 10,
            "link_type": "BANK_ACCOUNT", "link_id": base["acct"]["id"]}
    x = env.bm.put(f"/api/reminders/{r['id']}", body).json()
    assert x["state"] == "DUE" and x["overdue_days"] == 0 and x["link"]["label"].startswith("Bank account")
    assert titles(env.bu) == ["Approve the budget"]
    # once shown it can no longer be edited or deleted - only resolved
    assert env.bm.put(f"/api/reminders/{r['id']}", body).status_code == 409
    assert env.bm.delete(f"/api/reminders/{r['id']}").status_code == 409
    # overdue
    old = mk(env.bm, title="Old", due_date=D(-4)).json()
    assert old["overdue_days"] == 4
    # delete an upcoming personal reminder; validation
    up = mk(env.ru, title="Later", due_date=D(5)).json()
    assert env.bm.delete(f"/api/reminders/{up['id']}").status_code == 404
    assert env.ru.delete(f"/api/reminders/{up['id']}").json() == {"deleted": True}
    assert mk(env.ru, link_type="BUDGET").status_code == 422
    assert mk(env.ru, link_type="BUDGET", link_id=999999).status_code == 422
    assert mk(env.ru, notify_days_before=-1).status_code == 422
    assert mk(env.ru, title="").status_code == 422
    assert mk(env.ru, link_type="BUDGET", link_id=base["exp"]["id"]).json()["link"]["label"].startswith("Budget 1000 Operations")


def test_dashboard_layout_has_notifications_section(env):
    keys = [s["key"] for s in env.bu.get("/api/auth/me").json()["dashboard_layout"]]
    assert keys[0] == "notifications" and len(keys) == 8      # 2.4.0 (#255): + Overdue invoices
    r = env.bu.put("/api/me/preferences", {"dashboard_layout": [{"key": "notifications", "visible": False}]})
    assert r.status_code == 200 and r.json()["dashboard_layout"][0] == {"key": "notifications", "visible": False}
