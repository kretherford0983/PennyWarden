"""2.4.0 (#562): link a donation awaiting a deposit to a deposit already in the register.

Decisions (Kyle, 2026-11-10): both places (Link a deposit... on the Donations page, a Donation choice per line in the
register's Donation receipt dialog); the amount follows the deposit line, confirmed when it differs; a line already
marked as a donation on the deposit moves to the awaiting donation (confirmed) and a deposit donation left empty is
Cancelled - its receipts void, replaced; candidates are the donor's lines only; the dialog starts on the donor's only
same-amount awaiting donation."""
from __future__ import annotations

from test_v210_donations import dep, donor, enable, mark, print_receipt, setup  # noqa: F401
from test_v220_donations_part2 import _create, _ok, _print, don  # noqa: F401


def _deposit(env, base, entity_id, amount="1000.00", date="2026-08-20"):
    return env.txn(base["acct"]["id"], "DEPOSIT", [
        {"budget_id": base["inc_leaf"], "amount": amount, "entity_id": entity_id, "description": "Gift"}], date=date)


def _awaiting(env, don, cents=100000, who="a"):
    d = _ok(_create(env, don, [{"kind": "MONEY", "amount_cents": cents, "date_received": "2026-08-18"}], who=who), 201)
    return d, d_line(env, d)


def d_line(env, d):
    return _ok(env.ru.get(f"/api/donations/{d['id']}"))["lines"][0]["id"]


def test_link_from_the_donations_page(env, don):
    base = don["base"]
    d, lid = _awaiting(env, don)
    assert _print(env, d["id"]).status_code == 200                       # receipt before the money (date blank)
    t = _deposit(env, base, don["a"]["id"])
    _deposit(env, base, don["b"]["id"])                                  # another donor's: not offered
    c = _ok(env.ru.get(f"/api/donations/{d['id']}/lines/{lid}/link-candidates"))["items"]
    assert [x["transaction_id"] for x in c] == [t["id"]] and c[0]["same_amount"] and not c[0]["marked"]
    # Budget Users see donations but can't link
    assert env.bu.post(f"/api/donations/{d['id']}/lines/{lid}/link",
                       {"allocation_id": c[0]["allocation_id"]}).status_code == 403
    v = _ok(env.ru.post(f"/api/donations/{d['id']}/lines/{lid}/link", {"allocation_id": c[0]["allocation_id"]}))
    assert v["status"] == "RECEIVED" and v["awaiting"] == 0 and v["lines"][0]["deposit_id"] == t["id"]
    assert v["lines"][0]["date_received"] == "2026-08-18"                # the estimate before the deposit is kept
    assert v["next_kind"] == "CORRECTED"                                 # the date now prints
    atts = env.ru.get(f"/api/attachments?owner_type=transaction&owner_id={t['id']}").json()
    names = [a["original_filename"] for a in (atts["items"] if isinstance(atts, dict) else atts)]
    assert any(n.startswith("receipt-") for n in names)                 # the printed receipt went with the deposit
    out = _ok(env.ru.get(f"/api/donations/transactions/{t['id']}"))
    assert out["lines"][0]["linked_donation_id"] == d["id"]
    # linking again is refused: nothing is awaiting any more
    r = env.ru.post(f"/api/donations/{d['id']}/lines/{lid}/link", {"allocation_id": c[0]["allocation_id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "LINE_NOT_AWAITING"
    ev = env.admin.get("/api/audit-events?action=DONATION_LINKED").json()
    assert ev["items"] if isinstance(ev, dict) else ev


def test_amount_follows_the_deposit_after_confirmation(env, don):
    base = don["base"]
    d, lid = _awaiting(env, don)
    t = _deposit(env, base, don["a"]["id"], amount="900.00")
    a = t["allocations"][0]["id"]
    c = _ok(env.ru.get(f"/api/donations/{d['id']}/lines/{lid}/link-candidates"))["items"]
    assert c[0]["same_amount"] is False
    r = env.ru.post(f"/api/donations/{d['id']}/lines/{lid}/link", {"allocation_id": a})
    assert r.status_code == 409 and [w["code"] for w in r.json()["error"]["warnings"]] == ["AMOUNT_DIFFERS"]
    v = _ok(env.ru.post(f"/api/donations/{d['id']}/lines/{lid}/link",
                        {"allocation_id": a, "confirmations": ["AMOUNT_DIFFERS"]}))
    assert v["money"] == "$900.00"


def test_wrong_donor_and_closed_or_void_deposits_refused(env, don):
    base = don["base"]
    d, lid = _awaiting(env, don)
    other = _deposit(env, base, don["b"]["id"])
    r = env.ru.post(f"/api/donations/{d['id']}/lines/{lid}/link", {"allocation_id": other["allocations"][0]["id"]})
    assert r.status_code == 422 and "donor" in r.text
    t = _deposit(env, base, don["a"]["id"])
    assert env.ru.post(f"/api/transactions/{t['id']}/void", {"reason": "x", "confirm_irreversible": True}).status_code == 200
    assert _ok(env.ru.get(f"/api/donations/{d['id']}/lines/{lid}/link-candidates"))["items"] == []
    r = env.ru.post(f"/api/donations/{d['id']}/lines/{lid}/link", {"allocation_id": t["allocations"][0]["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "TRANSACTION_NOT_ACTIVE"


def test_register_dialog_suggests_and_links(env, don):
    base = don["base"]
    d, lid = _awaiting(env, don)
    t = _deposit(env, base, don["a"]["id"])
    url = f"/api/donations/transactions/{t['id']}"
    out = _ok(env.ru.get(url))
    line = out["lines"][0]
    assert [x["id"] for x in line["awaiting"]] == [lid] and line["suggested_link"] == lid
    assert line["awaiting"][0]["donation_id"] == d["id"]
    out = _ok(env.ru.put(url + "/lines", {"lines": [{"allocation_id": line["allocation_id"], "donation": True,
                                                     "link_line_id": lid}]}))
    assert out["lines"][0]["linked_donation_id"] == d["id"] and out["donors"] == []
    assert _ok(env.ru.get(f"/api/donations/{d['id']}"))["status"] == "RECEIVED"
    # saving the dialog again leaves the link as it is
    assert env.ru.put(url + "/lines", {"lines": [{"allocation_id": line["allocation_id"],
                                                  "donation": True}]}).status_code == 200
    # a different amount: no suggestion, but still offered
    d2, lid2 = _awaiting(env, don, cents=5000)
    t2 = _deposit(env, base, don["a"]["id"], amount="60.00")
    l2 = _ok(env.ru.get(f"/api/donations/transactions/{t2['id']}"))["lines"][0]
    assert [x["id"] for x in l2["awaiting"]] == [lid2] and l2["suggested_link"] is None


def test_replacing_a_line_marked_on_the_deposit_voids_its_receipt(env, don):
    """Kyle's case: the deposit line was ticked in the register first and got its own receipt."""
    base = don["base"]
    d, lid = _awaiting(env, don)
    assert _print(env, d["id"]).status_code == 200
    t = _deposit(env, base, don["a"]["id"])
    a = t["allocations"][0]["id"]
    url = f"/api/donations/transactions/{t['id']}"
    assert mark(env, {"url": url}, [{"allocation_id": a, "donation": True, "purpose": "Flags"}]).status_code == 200
    r = env.ru.post(url + "/receipts", {"donor_entity_id": don["a"]["id"], "confirmations": ["EMPTY_VARIABLES"]})
    assert r.status_code == 200, r.text
    dup = r.headers["X-Receipt-Number"]
    out = _ok(env.ru.get(url))
    assert out["lines"][0]["suggested_link"] is None and [x["id"] for x in out["lines"][0]["awaiting"]] == [lid]
    c = _ok(env.ru.get(f"/api/donations/{d['id']}/lines/{lid}/link-candidates"))["items"]
    assert c[0]["marked"] and c[0]["marked_receipt"] == dup
    r = env.ru.post(f"/api/donations/{d['id']}/lines/{lid}/link", {"allocation_id": a})
    assert r.status_code == 409
    w = r.json()["error"]["warnings"]
    assert [x["code"] for x in w] == ["REPLACES_MARKED"] and dup in w[0]["message"]
    v = _ok(env.ru.post(f"/api/donations/{d['id']}/lines/{lid}/link",
                        {"allocation_id": a, "confirmations": ["REPLACES_MARKED"]}))
    assert v["status"] == "RECEIVED" and v["lines"][0]["purpose"] == "Flags"     # carried over (it had none)
    out = _ok(env.ru.get(url))
    assert out["lines"][0]["linked_donation_id"] == d["id"] and out["donors"] == []
    assert [r["void"] for r in out["receipts"] if r["number"] == dup] == [True]
    lst = _ok(env.ru.get("/api/donations?show=cancelled"))["items"]
    assert any(x["current_receipt"] == dup and x["cancel_reason"] == f"Replaced by donation #{d['id']}" for x in lst)
    # ticking that donor again on the deposit starts a new donation rather than the cancelled one
    t2 = env.txn(base["acct"]["id"], "DEPOSIT", [
        {"budget_id": base["inc_leaf"], "amount": "10.00", "entity_id": don["a"]["id"]},
        {"budget_id": base["inc_leaf"], "amount": "20.00", "entity_id": don["a"]["id"]}], date="2026-08-21")
    u2 = f"/api/donations/transactions/{t2['id']}"
    a1, a2 = (x["id"] for x in t2["allocations"])
    assert mark(env, {"url": u2}, [{"allocation_id": a1, "donation": True}]).status_code == 200
    d3, lid3 = _awaiting(env, don, cents=2000)
    r = env.ru.put(u2 + "/lines", {"lines": [{"allocation_id": a1, "donation": True},
                                             {"allocation_id": a2, "donation": True, "link_line_id": lid3}]})
    assert r.status_code == 200, r.text
    # the same awaiting line can't go to two deposit lines
    d4, lid4 = _awaiting(env, don, cents=1000)
    r = env.ru.put(u2 + "/lines", {"lines": [{"allocation_id": a1, "donation": True, "link_line_id": lid4},
                                             {"allocation_id": a2, "donation": True, "link_line_id": lid4}]})
    assert r.status_code == 422
