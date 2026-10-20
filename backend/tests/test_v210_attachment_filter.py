"""2.1.0 (#258): the register's Attachments filter - All / Yes / Missing / Marked - matches the Fiscal Year
documentation review (CR-005, CR-017): Missing is exactly what the review warns about."""
from __future__ import annotations

from test_v12_reports import make_pdf, up


def ids(env, base, q=""):
    r = env.bu.get(f"/api/register?bank_account_id={base['acct']['id']}{q}")
    assert r.status_code == 200, r.text
    return [t["id"] for t in r.json()["transactions"]]


def _setup(env, base):
    a = base["acct"]["id"]
    line = lambda amt="5.00", **kw: {"budget_id": base["exp_leaf"], "amount": amt, "description": "x", **kw}
    w = lambda lines, **kw: env.txn(a, "WITHDRAWAL", lines, **kw)
    t = {}
    t["attached"] = w([line()], date="2026-08-01")
    up(env, "transaction", t["attached"]["id"], "inv.pdf", make_pdf("INV", pages=1))
    t["missing"] = w([line()], date="2026-08-02")
    t["reason"] = w([line()], date="2026-08-03", no_attachment=True, no_attachment_reason="Bank fee")
    t["no_reason"] = w([line()], date="2026-08-04", no_attachment=True)
    # split: one allocation documented, the other has neither attachment nor mark -> Yes AND Missing
    t["split"] = w([line("3.00"), line("2.00")], date="2026-08-05")
    up(env, "allocation", t["split"]["allocations"][0]["id"], "r.pdf", make_pdf("R", pages=1))
    # split: one allocation marked with a reason, the other attached -> documented, Yes and Marked
    t["split_marked"] = w([line("3.00", no_attachment=True, no_attachment_reason="Cash"), line("2.00")],
                          date="2026-08-06")
    up(env, "allocation", t["split_marked"]["allocations"][1]["id"], "r2.pdf", make_pdf("R2", pages=1))
    t["void"] = w([line()], date="2026-08-07")
    assert env.ru.post(f"/api/transactions/{t['void']['id']}/void",
                       {"reason": "error", "confirm_irreversible": True}).status_code == 200
    return {k: v["id"] for k, v in t.items()}


def test_filter_options(env, base):
    t = _setup(env, base)
    assert ids(env, base, "&attachments=yes") == [t["attached"], t["split"], t["split_marked"]]
    assert ids(env, base, "&attachments=missing") == [t["missing"], t["no_reason"], t["split"]]
    assert ids(env, base, "&attachments=marked") == [t["reason"], t["no_reason"], t["split_marked"]]
    # 1.6.7 links: "no" means "missing"
    assert ids(env, base, "&attachments=no") == ids(env, base, "&attachments=missing")
    assert env.bu.get(f"/api/register?bank_account_id={base['acct']['id']}&attachments=maybe").status_code == 422


def test_missing_equals_the_documentation_review(env, base):
    t = _setup(env, base)
    review = env.bu.get(f"/api/fiscal-years/{base['fy']['id']}/documentation-review").json()["items"]
    assert sorted(i["transaction_id"] for i in review) == sorted(ids(env, base, "&attachments=missing"))
    cats = {i["transaction_id"]: i["category"] for i in review}
    rows = env.bu.get(f"/api/register?bank_account_id={base['acct']['id']}&attachments=missing").json()["transactions"]
    assert {r["id"]: r["documentation"] for r in rows} == cats
    assert cats[t["no_reason"]] == "NO_ATTACHMENT_MARKED" and cats[t["missing"]] == "MISSING_ATTACHMENTS"


def test_void_is_never_missing(env, base):
    t = _setup(env, base)
    assert t["void"] not in ids(env, base, "&attachments=missing")
    rows = env.bu.get(f"/api/register?bank_account_id={base['acct']['id']}").json()["transactions"]
    assert next(r for r in rows if r["id"] == t["void"])["documentation"] is None


def test_adding_a_reason_moves_it_out_of_missing(env, base):
    t = _setup(env, base)
    r = env.ru.patch(f"/api/transactions/{t['no_reason']}", {"no_attachment": True,
                                                              "no_attachment_reason": "Bank fee, no receipt"})
    assert r.status_code == 200, r.text
    assert t["no_reason"] not in ids(env, base, "&attachments=missing")
    assert t["no_reason"] in ids(env, base, "&attachments=marked")
