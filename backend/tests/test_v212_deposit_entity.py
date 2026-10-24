"""2.1.2 (#344): changing a Deposit's Entity saved without error but changed nothing.

The edit form sent each line's stored Entity back (hidden on a non-split deposit), and for deposits the parent Entity
is derived from the allocations (BR-063), so the old line Entity put the parent back. A save that changed nothing
still asked for the cleared-edit confirmation (AC-REG-012) and wrote an empty TRANSACTION_UPDATED audit entry.
"""


def _events(env, tid):
    return env.auditor.get(f"/api/audit-events?action=TRANSACTION_UPDATED&object_id={tid}").json()["items"]


def _deposit(env, base, entity_id, lines=("360.00",)):
    return env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": a} for a in lines],
                   entity_id=entity_id, clear_date="2026-08-02")


def test_single_line_deposit_entity_change_with_stale_line_entity(env, base):
    old, new = env.entity("Fire Bell Club Old"), env.entity("Fire Bell Club, Inc")
    t = _deposit(env, base, old["id"])
    a = t["allocations"][0]
    assert a["entity"]["id"] == old["id"]
    # what the 2.1.1 form sent: the new header Entity plus the line still on the old Entity
    body = {"entity_id": new["id"], "allocations": [{"id": a["id"], "budget_id": base["inc_leaf"],
                                                     "entity_id": old["id"], "amount": "360.00"}]}
    r = env.ru.patch(f"/api/transactions/{t['id']}", body)
    assert r.status_code == 409 and r.json()["error"]["warnings"][0]["code"] == "CLEARED_EDIT"
    r = env.ru.patch(f"/api/transactions/{t['id']}", {**body, "confirmations": ["CLEARED_EDIT"]})
    assert r.status_code == 200, r.text
    assert r.json()["entity"]["id"] == new["id"] and r.json()["allocations"][0]["entity"]["id"] == new["id"]
    ev = _events(env, t["id"])[0]
    assert ev["before"]["parent_entity_id"] == old["id"] and ev["after"]["parent_entity_id"] == new["id"]
    # the old Entity can now be inactivated without stranding the transaction
    assert env.ru.get(f"/api/transactions/{t['id']}").json()["entity"]["id"] == new["id"]


def test_deposit_entity_change_header_only(env, base):
    old, new = env.entity(), env.entity()
    t = _deposit(env, base, old["id"])
    r = env.ru.patch(f"/api/transactions/{t['id']}", {"entity_id": new["id"], "confirmations": ["CLEARED_EDIT"]})
    assert r.status_code == 200, r.text
    assert r.json()["entity"]["id"] == new["id"] and r.json()["allocations"][0]["entity"]["id"] == new["id"]


def test_split_deposit_lines_on_old_entity_follow_but_other_entities_stay(env, base):
    old, new, other = env.entity(), env.entity(), env.entity()
    t = _deposit(env, base, old["id"], lines=("100.00", "50.00"))
    a1, a2 = t["allocations"]
    body = {"entity_id": new["id"], "confirmations": ["CLEARED_EDIT"], "allocations": [
        {"id": a1["id"], "budget_id": base["inc_leaf"], "entity_id": old["id"], "amount": "100.00"},
        {"id": a2["id"], "budget_id": base["inc_leaf"], "entity_id": old["id"], "amount": "50.00"}]}
    r = env.ru.patch(f"/api/transactions/{t['id']}", body)
    assert r.status_code == 200, r.text
    assert r.json()["entity"]["id"] == new["id"]
    assert {x["entity"]["id"] for x in r.json()["allocations"]} == {new["id"]}
    # a line deliberately set to a different Entity keeps it (parent becomes the protected Multiple, BR-063)
    body["allocations"][0]["entity_id"] = new["id"]
    body["allocations"][1]["entity_id"] = other["id"]
    r = env.ru.patch(f"/api/transactions/{t['id']}", body)
    assert r.status_code == 200, r.text
    assert [x["entity"]["id"] for x in r.json()["allocations"]] == [new["id"], other["id"]]
    assert r.json()["entity"]["is_system"]


def test_cleared_save_with_no_changes_needs_no_confirmation_and_no_audit(env, base):
    old = env.entity()
    t = _deposit(env, base, old["id"])
    a = t["allocations"][0]
    n = len(_events(env, t["id"]))
    body = {"entity_id": old["id"], "allocations": [{"id": a["id"], "budget_id": base["inc_leaf"],
                                                     "entity_id": old["id"], "amount": "360.00"}]}
    r = env.ru.patch(f"/api/transactions/{t['id']}", body)
    assert r.status_code == 200, r.text
    assert r.json()["entity"]["id"] == old["id"] and r.json()["total"] == "360.00"
    assert len(_events(env, t["id"])) == n
