"""2.4.0 (#248): batch invoicing - one draft per customer, reviewed, sent together, printed as one PDF.

BR-INV-BAT-001..004 / AC-INV-BAT-001..005 (recorded in docs/implementation-notes.md); regression for BR-003, BR-099,
BR-108.
"""
from __future__ import annotations

import io

import pytest
from pypdf import PdfReader


@pytest.fixture
def bb(env, base):
    assert env.admin.put("/api/system/modules", {"invoices": True}).status_code == 200
    im = env.user("invmgr", "FINANCIAL", ["INVOICE_MANAGER"])
    env.bm.put(f"/api/budgets/{base['inc']['id']}/invoiced-income", {"invoiced_income": True})
    units = {u["name"]: u["id"] for u in im.get("/api/invoices/catalog/unit-types").json()}
    dues = im.post("/api/invoices/catalog/products", {"name": "Annual dues", "unit_price": "75.00", "unit_type_id": units["Year"],
                                                     "budget_id": base["inc_leaf"]}).json()["id"]
    custs = [env.entity(n, client=im)["id"] for n in ("Zeta Family", "Alpha Family", "Mid Family")]
    return {"im": im, "dues": dues, "custs": custs}


def _body(bb, **kw):
    return {"name": "2027 dues", "customer_entity_ids": bb["custs"], "invoice_date": "2026-09-01", "due_date": "2026-09-30",
            "notes": "Thank you for your membership.", "lines": [{"product_id": bb["dues"], "quantity": "1"}], **kw}


def test_one_draft_per_customer_numbered_in_customer_order(env, bb):
    """AC-INV-BAT-001: drafts with the same lines and dates, numbered in customer-name order; audited."""
    r = bb["im"].post("/api/invoices/batches", _body(bb))
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["count"] == 3 and b["drafts"] == 3 and b["total"] == "225.00"
    names = [x["customer"]["name"] for x in b["invoices"]]
    assert names == ["Alpha Family", "Mid Family", "Zeta Family"]
    nums = [x["number"] for x in b["invoices"]]
    assert nums == sorted(nums)
    one = bb["im"].get(f"/api/invoices/{b['invoices'][0]['id']}").json()
    assert one["due_date"] == "2026-09-30" and one["notes"] == "Thank you for your membership." and one["batch_id"] == b["id"]
    assert [x["name"] for x in bb["im"].get("/api/invoices/batches").json()] == ["2027 dues"]
    ev = env.auditor.get("/api/audit-events?action=INVOICE_BATCH_CREATED").json()["items"]
    assert ev and len(env.auditor.get("/api/audit-events?action=INVOICE_CREATED").json()["items"]) >= 3


def test_all_or_none_and_validation(env, bb):
    """AC-INV-BAT-002: a problem with one customer creates nothing and names the customer; duplicates, empty lists
    and unknown customers are refused."""
    assert bb["im"].post("/api/invoices/batches", _body(bb, customer_entity_ids=[])).status_code == 422
    assert bb["im"].post("/api/invoices/batches", _body(bb, customer_entity_ids=[bb["custs"][0]] * 2)).status_code == 422
    assert bb["im"].post("/api/invoices/batches", _body(bb, lines=[])).status_code == 422
    assert bb["im"].post("/api/invoices/batches", _body(bb, customer_entity_ids=bb["custs"] + [999999])).status_code == 404
    bad = bb["im"].post("/api/invoices/batches", _body(bb, lines=[{"product_id": bb["dues"], "quantity": "0"}]))
    assert bad.status_code == 422 and "Alpha Family" in bad.json()["error"]["message"]
    assert bb["im"].get("/api/invoices").json() == [] or all(x.get("batch_id") is None for x in bb["im"].get("/api/invoices").json())
    assert bb["im"].get("/api/invoices/batches").json() == []


def test_review_send_all_and_combined_pdf(env, bb):
    """AC-INV-BAT-003/004: each draft stays editable or voidable on its own; Mark all as sent sends the drafts (each
    keeps its PDF); the combined PDF has every non-void invoice."""
    b = bb["im"].post("/api/invoices/batches", _body(bb)).json()
    first, second, third = (x["id"] for x in b["invoices"])
    e = bb["im"].get(f"/api/invoices/{second}").json()
    upd = bb["im"].put(f"/api/invoices/{second}", {"customer_entity_id": e["customer"]["id"], "invoice_date": "2026-09-01",
                                                   "due_date": "2026-09-30", "lines": [{"id": e["lines"][0]["id"], "product_id": bb["dues"], "quantity": "2"}]})
    assert upd.status_code == 200 and upd.json()["total"] == "150.00"
    assert bb["im"].post(f"/api/invoices/{third}/void", {"reason": "Moved away"}).status_code == 200
    pdf = bb["im"].get(f"/api/invoices/batches/{b['id']}/pdf")
    assert pdf.status_code == 200
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Alpha Family" in text and "Mid Family" in text and "Zeta Family" not in text and "DRAFT" in text
    s = bb["im"].post(f"/api/invoices/batches/{b['id']}/send")
    assert s.status_code == 200, s.text
    assert len(s.json()["result"]["sent"]) == 2 and s.json()["drafts"] == 0
    assert [x["status"] for x in s.json()["invoices"]] == ["SENT", "SENT", "VOID"]
    assert bb["im"].get(f"/api/invoices/{first}").json()["versions"]           # its PDF is kept
    assert env.auditor.get("/api/audit-events?action=INVOICE_BATCH_SENT").json()["items"]
    again = bb["im"].post(f"/api/invoices/batches/{b['id']}/send").json()
    assert again["result"]["sent"] == []


def test_roles_and_scope(env, bb):
    """AC-INV-BAT-005: Invoice Managers create and send; viewers read; Administrator refused; unknown batch 404."""
    b = bb["im"].post("/api/invoices/batches", _body(bb)).json()
    for c in (env.bm, env.ru, env.bu, env.auditor):
        assert c.post("/api/invoices/batches", _body(bb)).status_code == 403
        assert c.post(f"/api/invoices/batches/{b['id']}/send").status_code == 403
        assert c.get(f"/api/invoices/batches/{b['id']}").status_code == 200
    assert env.admin.get(f"/api/invoices/batches/{b['id']}").status_code == 403
    assert bb["im"].get("/api/invoices/batches/999999").status_code == 404
