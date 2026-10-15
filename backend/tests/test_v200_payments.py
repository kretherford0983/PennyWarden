"""2.0.0 build 2 (#164): payments - last bank account per user, live amount preview, recent printed checks."""
from tests.test_v200_checks import PRESET, enable  # noqa: F401  (shared helpers)


def test_last_account_amount_preview_and_recent(env, base):
    enable(env)
    style = env.admin.post("/api/checks/styles", {"preset_key": PRESET}).json()
    acct = base["acct"]["id"]
    # Register Users only
    for c in (env.bm, env.bu, env.auditor, env.admin):
        assert c.get("/api/checks/payments/options").status_code == 403
    assert env.ru.get("/api/checks/payments/options").json() == {"last_bank_account_id": None, "styles_available": True}
    assert env.ru.put("/api/checks/payments/last-account", {"bank_account_id": acct}).json()["last_bank_account_id"] == acct
    assert env.ru.get("/api/checks/payments/options").json()["last_bank_account_id"] == acct
    assert env.ru.put("/api/checks/payments/last-account", {"bank_account_id": 9999}).status_code == 404
    # amount preview: default style before the account has one, then the account's style
    p = env.ru.post("/api/checks/payments/amount-preview", {"bank_account_id": acct, "amount": "1234.56"}).json()
    assert p == {"number": "**1,234.56", "words": "ONE THOUSAND TWO HUNDRED THIRTY-FOUR AND 56/100"}
    cfg = style["config"]
    cfg["amount_words"]["and_mode"] = "HUNDREDS"
    cfg["amount_number"]["lead_fill"] = ""
    env.admin.put(f"/api/checks/styles/{style['id']}", {"name": style["name"], "config": cfg})
    env.ru.put(f"/api/checks/accounts/{acct}", {"check_style_id": style["id"]})
    p = env.ru.post("/api/checks/payments/amount-preview", {"bank_account_id": acct, "amount": "108.50"}).json()
    assert p == {"number": "108.50", "words": "ONE HUNDRED AND EIGHT AND 50/100"}
    for bad in ("", "abc", "0", "1.234", "-5"):
        assert env.ru.post("/api/checks/payments/amount-preview", {"bank_account_id": acct, "amount": bad}).json() == \
            {"number": None, "words": None}
    # recent printed checks: from the record copies, newest first, one row per transaction
    payee = env.entity("Sample Supply Company, Inc")
    t = env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "25.00"}], entity_id=payee["id"],
                check_number="5001")
    assert env.ru.get(f"/api/checks/payments/recent?bank_account_id={acct}").json() == []
    body = {"check_style_id": style["id"], "feed_key": "sheet_top", "confirm_check_number": "5001", "no_signature": True,
            "confirmations": ["EMPTY_VARIABLES"]}
    assert env.ru.post(f"/api/checks/transactions/{t['id']}/print", body).status_code == 200
    rec = env.ru.get(f"/api/checks/payments/recent?bank_account_id={acct}").json()
    assert [(r["transaction_id"], r["check_number"], r["payee"], r["amount"]) for r in rec] == \
        [(t["id"], "5001", "Sample Supply Company, Inc", "25.00")]
    assert env.bm.get(f"/api/checks/payments/recent?bank_account_id={acct}").status_code == 403
