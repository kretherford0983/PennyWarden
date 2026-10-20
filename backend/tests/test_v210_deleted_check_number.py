"""2.1.0 (#289): deleting a transaction releases its check number (CR-011 amended); the missing-check review ignores
deleted transactions (CR-012); Delete is refused while a printed check carries the number (Payments module)."""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from fmpoc.models import RegisterTransaction
from test_v200_checks import do_print, make_signer, setup  # noqa: F401  (fixture)


@pytest.fixture
def ra(env):
    return env.user("regadmin", "FINANCIAL", ["REGISTER_USER", "REGISTER_ADMIN"])


def _w(env, base, number, amount):
    return env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": amount}], check_number=number)


def _missing(env, base):
    r = env.bu.get(f"/api/check-review?bank_account_id={base['acct']['id']}").json()["missing"]
    return [(m["first_number"], m["last_number"]) for m in r]


def test_number_is_released_and_reusable(env, base, ra):
    _w(env, base, "104", "10.00")
    t = _w(env, base, "105", "11.00")
    _w(env, base, "106", "12.00")
    assert ra.post(f"/api/transactions/{t['id']}/delete", {"reason": "entered on the wrong account"}).status_code == 200
    assert _missing(env, base) == [(105, 105)]            # possibly missing until reused or acknowledged
    again = _w(env, base, "105", "13.00")
    assert again["check_number"] == "105" and _missing(env, base) == []
    got = env.auditor.get(f"/api/transactions/{t['id']}").json()
    assert got["status"] == "DELETED" and got["check_number"] == "105"


def test_transactions_deleted_before_the_fix_are_released_too(env, base, app):
    t = _w(env, base, "300", "9.00")
    with Session(app.state.engine) as db:      # as left by 2.0.0: status DELETED, number kept
        db.get(RegisterTransaction, t["id"]).status = "DELETED"
        db.commit()
    assert _w(env, base, "300", "8.00")["check_number"] == "300"


def test_void_still_keeps_its_number(env, base):
    t = _w(env, base, "400", "7.00")
    assert env.ru.post(f"/api/transactions/{t['id']}/void", {"reason": "lost", "confirm_irreversible": True}).status_code == 200
    r = env.ru.post("/api/transactions", {"bank_account_id": base["acct"]["id"], "transaction_type": "WITHDRAWAL",
                                          "check_number": "400", "allocations": [{"budget_id": base["exp_leaf"], "amount": "1.00"}]})
    assert r.status_code == 409 and "VOID" in r.json()["error"]["message"]


def test_printed_check_blocks_delete_until_spoiled(env, setup, ra):
    signer = make_signer(env)
    tid = setup["txn"]["id"]
    assert do_print(env, setup, signer_id=signer["id"]).status_code == 200
    r = ra.post(f"/api/transactions/{tid}/delete", {"reason": "duplicate"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CHECK_PRINTED"
    assert env.ru.post(f"/api/checks/transactions/{tid}/spoil", {"reason": "never sent", "new_check_number": "6176"}).status_code == 200
    assert ra.post(f"/api/transactions/{tid}/delete", {"reason": "duplicate"}).status_code == 200


def test_only_register_admins_delete(env, base):
    t = _w(env, base, "500", "6.00")
    for c in (env.ru, env.bm, env.bu, env.auditor, env.admin):
        assert c.post(f"/api/transactions/{t['id']}/delete", {"reason": "x"}).status_code == 403
