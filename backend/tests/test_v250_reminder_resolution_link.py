"""2.5.0 (#594): a resolved reminder points to the transaction or event that resolved it."""
import datetime as dt


def _due(env, title="Pay the insurance"):
    r = env.bm.post("/api/reminders", {"scope": "ORGANIZATION", "title": title, "due_date": dt.date.today().isoformat()})
    assert r.status_code == 201, r.text
    return r.json()


def test_resolve_with_a_transaction_and_change_it_later(env, base):
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "450.00", "description": "Insurance"}])
    r = _due(env)
    opts = env.ru.get("/api/reminders/resolution-link-options?kind=TRANSACTION&q=insurance").json()
    assert [o["id"] for o in opts] == [t["id"]]
    res = env.ru.post(f"/api/reminders/{r['id']}/resolve", {"note": "Paid", "resolution_link_type": "TRANSACTION",
                                                            "resolution_link_id": t["id"]})
    assert res.status_code == 200, res.text
    link = res.json()["resolution_link"]
    assert link["label"].startswith(f"Transaction #{t['id']} — ") and "$450.00" in link["label"]
    assert link["url"] == f"/register?account={base['acct']['id']}&txn={t['id']}"
    assert res.json()["can_edit_resolution_link"]
    # change it later: to an event (module on), then remove it - each audited
    assert env.admin.put("/api/system/modules", {"fundraisers": True}).status_code == 200
    ev = env.bm.post("/api/fundraisers", {"name": "Summer Cookout", "event_type": "EVENT", "start_date": "2026-08-01",
                                          "budget_ids": []}).json()
    out = env.ru.put(f"/api/reminders/{r['id']}/resolution-link", {"resolution_link_type": "EVENT", "resolution_link_id": ev["id"]}).json()
    assert out["resolution_link"] == {"type": "EVENT", "id": ev["id"], "label": "Event: Summer Cookout", "url": f"/fundraisers/{ev['id']}"}
    out = env.ru.put(f"/api/reminders/{r['id']}/resolution-link", {"resolution_link_type": None, "resolution_link_id": None}).json()
    assert out["resolution_link"] is None
    ev_log = env.auditor.get(f"/api/audit-events?action=REMINDER_RESOLUTION_LINK_CHANGED").json()["items"]
    assert len(ev_log) == 2


def test_label_only_without_access_and_validation(env, base):
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "10.00"}])
    r = _due(env)
    url = f"/api/reminders/{r['id']}/resolve"
    assert env.ru.post(url, {"resolution_link_type": "TRANSACTION"}).status_code == 422          # both or neither
    assert env.ru.post(url, {"resolution_link_type": "TRANSACTION", "resolution_link_id": 999999}).status_code == 422
    assert env.ru.post(url, {"resolution_link_type": "INVOICE", "resolution_link_id": t["id"]}).status_code == 422
    assert env.ru.post(url, {"resolution_link_type": "TRANSACTION", "resolution_link_id": t["id"]}).status_code == 200
    # an event link while the module is off reads as a label only
    assert env.admin.put("/api/system/modules", {"fundraisers": True}).status_code == 200
    ev = env.bm.post("/api/fundraisers", {"name": "Gala", "start_date": "2026-08-01", "budget_ids": []}).json()
    env.ru.put(f"/api/reminders/{r['id']}/resolution-link", {"resolution_link_type": "EVENT", "resolution_link_id": ev["id"]})
    env.admin.put("/api/system/modules", {"fundraisers": False})
    got = next(x for x in env.ru.get("/api/reminders?view=resolved").json() if x["id"] == r["id"])
    assert got["resolution_link"]["label"] == "Fundraiser: Gala" and got["resolution_link"]["url"] is None
    assert env.ru.get("/api/reminders/resolution-link-options?kind=EVENT").json() == []


def test_only_after_resolving_and_not_copied_to_the_next_occurrence(env, base):
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "10.00"}])
    r = env.bm.post("/api/reminders", {"scope": "ORGANIZATION", "title": "Monthly rent", "due_date": dt.date.today().isoformat(),
                                       "repeat_every": 1, "repeat_unit": "MONTH"}).json()
    assert env.ru.put(f"/api/reminders/{r['id']}/resolution-link", {"resolution_link_type": "TRANSACTION",
                                                                     "resolution_link_id": t["id"]}).status_code == 409
    env.ru.post(f"/api/reminders/{r['id']}/resolve", {"resolution_link_type": "TRANSACTION", "resolution_link_id": t["id"]})
    nxt = [x for x in env.bm.get("/api/reminders?view=upcoming").json() if x["title"] == "Monthly rent"]
    assert nxt and nxt[0]["resolution_link"] is None
    # Budget Users can't resolve (nor see a resolved organization reminder), so they can't link either
    assert env.bu.put(f"/api/reminders/{r['id']}/resolution-link", {"resolution_link_type": None, "resolution_link_id": None}).status_code in (403, 404)
