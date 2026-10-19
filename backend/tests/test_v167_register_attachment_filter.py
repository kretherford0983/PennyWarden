"""1.6.7: register filter "Attachments" - all (default), yes, no (2.1.0, #258: no = missing; plus marked)."""
from test_v12_reports import make_pdf, up


def ids(env, base, q=""):
    r = env.bu.get(f"/api/register?bank_account_id={base['acct']['id']}{q}")
    assert r.status_code == 200, r.text
    return [t["id"] for t in r.json()["transactions"]]


def test_filter_by_attachments(env, base):
    a = base["acct"]["id"]
    line = [{"budget_id": base["exp_leaf"], "amount": "5.00", "description": "x"}]
    own = env.txn(a, "WITHDRAWAL", line, date="2026-08-01")            # attachment on the transaction
    up(env, "transaction", own["id"], "invoice.pdf", make_pdf("INV", pages=1))
    child = env.txn(a, "WITHDRAWAL", line, date="2026-08-02")          # attachment on an allocation only
    up(env, "allocation", child["allocations"][0]["id"], "receipt.pdf", make_pdf("REC", pages=1))
    none = env.txn(a, "WITHDRAWAL", line, date="2026-08-03")
    marked = env.txn(a, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "1.00"}], date="2026-08-04",
                     no_attachment=True, no_attachment_reason="Bank interest")   # "none will be provided" is still none
    gone = env.txn(a, "WITHDRAWAL", line, date="2026-08-05")           # its only attachment was removed
    att = up(env, "transaction", gone["id"], "wrong.pdf", make_pdf("WRONG", pages=1))
    assert env.ru.post(f"/api/attachments/{att["id"]}/remove", {"reason": "Wrong file"}).status_code == 200

    everything = [own["id"], child["id"], none["id"], marked["id"], gone["id"]]
    assert ids(env, base) == everything
    assert ids(env, base, "&attachments=yes") == [own["id"], child["id"]]
    # 2.1.0 (#258): "no" now means "missing" - a mark WITH a reason is documented, so it is not listed
    assert ids(env, base, "&attachments=no") == [none["id"], gone["id"]]
    assert ids(env, base, "&attachments=marked") == [marked["id"]]
    # combines with the other filters; balances are those of the whole register, not of the filtered rows
    assert ids(env, base, "&attachments=marked&transaction_type=DEPOSIT") == [marked["id"]]
    assert ids(env, base, "&attachments=no&transaction_type=DEPOSIT") == []
    assert ids(env, base, "&attachments=yes&date_from=2026-08-02") == [child["id"]]
    full = env.bu.get(f"/api/register?bank_account_id={a}").json()
    part = env.bu.get(f"/api/register?bank_account_id={a}&attachments=yes").json()
    assert part["current_balance"] == full["current_balance"] and part["ending_balance"] == full["ending_balance"]
    by_id = {t["id"]: t["running_balance"] for t in full["transactions"]}
    assert all(t["running_balance"] == by_id[t["id"]] for t in part["transactions"])
    assert env.bu.get(f"/api/register?bank_account_id={a}&attachments=maybe").status_code == 422
