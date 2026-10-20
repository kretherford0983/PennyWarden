"""2.1.0 (#259): reorder the attachments of a transaction, an allocation, a fundraiser and a Fiscal Year (Unspecified
documents); the order is used by the lists, the Audit report and the fundraiser report."""
from __future__ import annotations

from test_fiscal_years import _ready_to_close
from test_v12_reports import first_page, make_pdf, page_texts, up


def names(env, owner_type, owner_id, client=None, removed=False):
    c = client or env.bu
    q = "&include_removed=true" if removed else ""
    return [a["original_filename"] for a in c.get(f"/api/attachments?owner_type={owner_type}&owner_id={owner_id}{q}").json()]


def reorder(env, owner_type, owner_id, ids, client=None):
    return (client or env.ru).put("/api/attachments/order", {"owner_type": owner_type, "owner_id": owner_id,
                                                              "attachment_ids": ids})


def _three(env, base, **kw):
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "12.00"}], **kw)
    ids = [up(env, "transaction", t["id"], f"{n}.pdf", make_pdf(n.upper(), pages=1))["id"]
           for n in ("approval", "invoice", "receipt")]
    return t, ids


def test_reorder_transaction_and_new_uploads_go_last(env, base):
    t, (a, b, c) = _three(env, base)
    assert names(env, "transaction", t["id"]) == ["approval.pdf", "invoice.pdf", "receipt.pdf"]
    r = reorder(env, "transaction", t["id"], [b, c, a])
    assert r.status_code == 200, r.text
    assert [x["original_filename"] for x in r.json()] == ["invoice.pdf", "receipt.pdf", "approval.pdf"]
    assert names(env, "transaction", t["id"]) == ["invoice.pdf", "receipt.pdf", "approval.pdf"]
    up(env, "transaction", t["id"], "late.pdf", make_pdf("LATE", pages=1))
    assert names(env, "transaction", t["id"])[-1] == "late.pdf"
    # removing one keeps the others in order; removed ones are listed after the active ones
    assert env.ru.post(f"/api/attachments/{c}/remove").status_code == 200
    assert names(env, "transaction", t["id"]) == ["invoice.pdf", "approval.pdf", "late.pdf"]
    assert names(env, "transaction", t["id"], removed=True) == ["invoice.pdf", "approval.pdf", "late.pdf", "receipt.pdf"]


def test_audited_with_before_and_after(env, base):
    t, (a, b, c) = _three(env, base)
    assert reorder(env, "transaction", t["id"], [c, a, b]).status_code == 200
    ev = env.auditor.get(f"/api/audit-events?action=ATTACHMENTS_REORDERED").json()["items"]
    assert len(ev) == 1 and ev[0]["object_type"] == "register_transaction" and ev[0]["object_id"] == str(t["id"])
    assert [x["name"] for x in ev[0]["before"]["attachment_order"]] == ["approval.pdf", "invoice.pdf", "receipt.pdf"]
    assert [x["name"] for x in ev[0]["after"]["attachment_order"]] == ["receipt.pdf", "approval.pdf", "invoice.pdf"]
    # the same order again is not a change (no audit event)
    assert reorder(env, "transaction", t["id"], [c, a, b]).status_code == 200
    assert len(env.auditor.get(f"/api/audit-events?action=ATTACHMENTS_REORDERED").json()["items"]) == 1


def test_validation_and_permissions(env, base):
    t, (a, b, c) = _three(env, base)
    assert reorder(env, "transaction", t["id"], [a, b]).status_code == 422          # not all of them
    assert reorder(env, "transaction", t["id"], [a, a, b]).status_code == 422       # duplicated
    assert reorder(env, "transaction", t["id"], [a, b, 999999]).status_code == 422  # someone else's
    for client in (env.bu, env.auditor, env.bm):
        assert reorder(env, "transaction", t["id"], [c, b, a], client=client).status_code == 403
    assert reorder(env, "transaction", t["id"], [c, b, a], client=env.admin).status_code == 403


def test_cleared_needs_no_confirmation_and_void_still_reorders(env, base):
    t, (a, b, c) = _three(env, base, clear_date="2026-08-03")
    assert reorder(env, "transaction", t["id"], [b, a, c]).status_code == 200
    assert env.ru.post(f"/api/transactions/{t['id']}/void",
                       {"reason": "dup", "confirm_irreversible": True}).status_code == 200
    assert reorder(env, "transaction", t["id"], [c, b, a]).status_code == 200


def test_allocation_order(env, base):
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "3.00"},
                                                   {"budget_id": base["exp_leaf"], "amount": "2.00"}])
    al = t["allocations"][0]["id"]
    x = up(env, "allocation", al, "x.pdf", make_pdf("X", pages=1))["id"]
    y = up(env, "allocation", al, "y.pdf", make_pdf("Y", pages=1))["id"]
    assert reorder(env, "allocation", al, [y, x]).status_code == 200
    assert names(env, "allocation", al) == ["y.pdf", "x.pdf"]


def test_fiscal_year_unspecified_only_and_closed_year_locked(env, base):
    fy = base["fy"]["id"]
    p = up(env, "fiscal_year", fy, "minutes.pdf", make_pdf("MIN", pages=1), client=env.bm)["id"]
    q = up(env, "fiscal_year", fy, "bank-letter.pdf", make_pdf("BANK", pages=1), client=env.bm)["id"]
    assert reorder(env, "fiscal_year", fy, [q, p], client=env.ru).status_code == 403   # Budget Managers only
    assert reorder(env, "fiscal_year", fy, [q, p], client=env.bm).status_code == 200
    # Approval documents are not part of the Unspecified order
    _ready_to_close(env, base)
    listed = names(env, "fiscal_year", fy, client=env.bm)
    assert listed.index("bank-letter.pdf") < listed.index("minutes.pdf")
    assert env.bm.post(f"/api/fiscal-years/{fy}/close", {"confirm_reviewed": True}).status_code == 200
    r = reorder(env, "fiscal_year", fy, [p, q], client=env.bm)
    assert r.status_code == 409 and r.json()["error"]["code"] == "FISCAL_YEAR_CLOSED"


def test_audit_report_follows_the_order(env, base):
    t, (a, b, c) = _three(env, base)
    assert reorder(env, "transaction", t["id"], [c, a, b]).status_code == 200
    texts = page_texts(env.auditor.get(f"/api/reports/audit?fiscal_year_id={base['fy']['id']}").content)
    pages = [first_page(texts, m) for m in ("RECEIPT page 1", "APPROVAL page 1", "INVOICE page 1")]
    assert pages == sorted(pages) and len(set(pages)) == 3


def test_fundraiser_documents(env, base):
    assert env.admin.put("/api/system/modules", {"fundraisers": True}).status_code == 200
    f = env.bm.post("/api/fundraisers", {"name": "Gala", "start_date": "2026-09-12",
                                         "budget_ids": [base["inc"]["id"]]}).json()
    d1 = up(env, "fundraiser", f["id"], "flyer.pdf", make_pdf("FLYER", pages=1), client=env.bm)["id"]
    d2 = up(env, "fundraiser", f["id"], "permit.pdf", make_pdf("PERMIT", pages=1), client=env.bm)["id"]
    assert reorder(env, "fundraiser", f["id"], [d2, d1], client=env.bm).status_code == 200
    assert names(env, "fundraiser", f["id"], client=env.bm) == ["permit.pdf", "flyer.pdf"]
    assert reorder(env, "fundraiser", f["id"], [d1, d2], client=env.auditor).status_code == 403
