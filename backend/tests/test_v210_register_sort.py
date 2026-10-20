"""2.1.0 (#262): sort the register by Date or Cleared, ascending or descending, remembered per user.

- Ties keep the order they were entered; an uncleared transaction counts as "not yet cleared" (after the cleared ones
  ascending, first descending).
- Sorted by Cleared, the running balance is the bank (cleared) balance after each cleared item, blank on uncleared rows.
- The choice is saved per user with the other preferences (server-side) and returned by /api/auth/me.
"""
from __future__ import annotations

D = "WITHDRAWAL"


def _reg(env, base, client=None, **q):
    params = "".join(f"&{k}={v}" for k, v in q.items())
    r = (client or env.bu).get(f"/api/register?bank_account_id={base['acct']['id']}{params}")
    assert r.status_code == 200, r.text
    return r.json()


def _setup(env, base):
    a = base["acct"]["id"]
    w = lambda amt, **kw: env.txn(a, D, [{"budget_id": base["exp_leaf"], "amount": amt, "description": "x"}], **kw)
    t1 = w("10.00", date="2026-08-01", clear_date="2026-08-10")
    t2 = w("20.00", date="2026-08-01", clear_date="2026-08-05")        # same Date as t1, entered after it
    t3 = w("30.00", date="2026-08-03")                                # uncleared
    t4 = w("40.00", date="2026-08-02", clear_date="2026-08-05")        # same Cleared date as t2
    t5 = w("50.00", date="2026-08-04")                                # uncleared
    return [t["id"] for t in (t1, t2, t3, t4, t5)]


def test_date_sort_default_and_ties_keep_entry_order(env, base):
    t1, t2, t3, t4, t5 = _setup(env, base)
    rows = _reg(env, base)
    assert [t["id"] for t in rows["transactions"]] == [t1, t2, t4, t3, t5]
    assert rows["sort"] == "transaction_date" and rows["direction"] == "asc"
    assert rows["running_balance_kind"] == "register"
    desc = _reg(env, base, sort="transaction_date", direction="desc")
    assert [t["id"] for t in desc["transactions"]] == [t5, t3, t4, t2, t1]
    # the running balance is the same register balance whatever the direction
    by_id = {t["id"]: t["running_balance"] for t in rows["transactions"]}
    assert all(t["running_balance"] == by_id[t["id"]] for t in desc["transactions"])
    assert by_id[t5] == "850.00"   # 1000.00 opening - 150.00


def test_cleared_sort_places_uncleared_and_shows_the_bank_balance(env, base):
    t1, t2, t3, t4, t5 = _setup(env, base)
    asc = _reg(env, base, sort="clear_date", direction="asc")
    # cleared by Clear date (ties by Date, then entry), uncleared after them by Date
    assert [t["id"] for t in asc["transactions"]] == [t2, t4, t1, t3, t5]
    assert asc["running_balance_kind"] == "cleared"
    bal = {t["id"]: t["running_balance"] for t in asc["transactions"]}
    assert bal[t2] == "980.00" and bal[t4] == "940.00" and bal[t1] == "930.00"
    assert bal[t3] is None and bal[t5] is None
    # the last cleared balance is the account's Current (bank) balance
    assert asc["current_balance"] == "930.00"
    desc = _reg(env, base, sort="clear_date", direction="desc")
    assert [t["id"] for t in desc["transactions"]] == [t5, t3, t1, t4, t2]


def test_void_is_listed_but_not_in_the_cleared_balance(env, base):
    t1, t2, t3, t4, t5 = _setup(env, base)
    assert env.ru.post(f"/api/transactions/{t2}/void", {"reason": "Duplicate", "confirm_irreversible": True}).status_code == 200
    asc = _reg(env, base, sort="clear_date")
    bal = {t["id"]: t["running_balance"] for t in asc["transactions"]}
    assert bal[t4] == "960.00" and bal[t1] == "950.00"
    assert asc["current_balance"] == "950.00"


def test_preference_is_saved_per_user_and_reset(env, base):
    me = env.bu.get("/api/auth/me").json()
    assert me["register_sort"] == "transaction_date:asc"
    r = env.bu.put("/api/me/preferences", {"register_sort": "clear_date:desc"})
    assert r.status_code == 200 and r.json()["register_sort"] == "clear_date:desc"
    assert env.bu.get("/api/auth/me").json()["register_sort"] == "clear_date:desc"
    # another user is not affected
    assert env.ru.get("/api/auth/me").json()["register_sort"] == "transaction_date:asc"
    r = env.bu.put("/api/me/preferences", {"reset_register_sort": True})
    assert r.json()["register_sort"] == "transaction_date:asc"
    assert env.bu.put("/api/me/preferences", {"register_sort": "amount:asc"}).status_code == 422
    assert env.bu.put("/api/me/preferences", {"register_sort": "clear_date:sideways"}).status_code == 422


def test_sort_works_with_filters(env, base):
    t1, t2, t3, t4, t5 = _setup(env, base)
    rows = _reg(env, base, sort="clear_date", direction="asc", status="uncleared")
    assert [t["id"] for t in rows["transactions"]] == [t3, t5]
    assert all(t["running_balance"] is None for t in rows["transactions"])
