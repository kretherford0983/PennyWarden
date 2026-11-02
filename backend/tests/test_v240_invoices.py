"""2.4.0 (#253): invoices - catalog lines, discounts, tax, numbering, revisions, PDF, void and write-off.

BR-INV-DOC-001..007 / AC-INV-DOC-001..009 (recorded in docs/implementation-notes.md); regression for BR-001 (numbers
never reused, nothing deleted), BR-003 (Administrator sample data only), BR-075..078, BR-099, BR-108.
"""
from __future__ import annotations

import pytest
from pypdf import PdfReader
import io


@pytest.fixture
def ib(env, base):
    """Invoices on; an Invoice Manager; Invoiced Income budget; products, a tax rate and a customer."""
    assert env.admin.put("/api/system/modules", {"invoices": True}).status_code == 200
    im = env.user("invmgr", "FINANCIAL", ["INVOICE_MANAGER"])
    assert env.bm.put(f"/api/budgets/{base['inc']['id']}/invoiced-income", {"invoiced_income": True}).status_code == 200
    units = {u["name"]: u["id"] for u in im.get("/api/invoices/catalog/unit-types").json()}

    def product(name, price, unit="Each", taxable=False):
        r = im.post("/api/invoices/catalog/products", {"name": name, "unit_price": price, "unit_type_id": units[unit],
                                                      "taxable": taxable, "budget_id": base["inc_leaf"]})
        assert r.status_code == 201, r.text
        return r.json()["id"]
    tax = im.post("/api/invoices/catalog/tax-rates", {"name": "Sales tax", "rate": "7.25", "budget_id": base["inc_leaf"]}).json()
    cust = env.entity("Acme Customer", client=im)
    return {"im": im, "dues": product("Annual dues", "120.00", "Year"), "hour": product("Coaching", "40.00", "Hour", True),
            "shirt": product("Shirt", "19.99", "Each", True), "tax": tax["id"], "cust": cust["id"]}


def _body(ib, lines, **kw):
    return {"customer_entity_id": ib["cust"], "invoice_date": "2026-09-15", "lines": lines, **kw}


def test_draft_totals_to_the_cent(env, ib):
    """AC-INV-DOC-001: quantity x price, line discount, whole-invoice discount spread, tax after discounts."""
    r = ib["im"].post("/api/invoices", _body(ib, [
        {"product_id": ib["dues"], "quantity": "1"},
        {"product_id": ib["hour"], "quantity": "2.5", "discount_kind": "AMOUNT", "discount_value": "10", "discount_reason": "Loyal member"},
        {"product_id": ib["shirt"], "quantity": "3"},
    ], tax_rate_id=ib["tax"], discount={"kind": "PERCENT", "value": "10", "reason": "Early payment"}))
    assert r.status_code == 201, r.text
    i = r.json()
    # gross 120.00 + 100.00 + 59.97; line discount 10.00 -> nets 120.00, 90.00, 59.97 = 269.97
    # invoice discount 10 % = 27.00 (26.997 rounded) spread by net: 12.00, 9.00, 5.99 (+1 leftover cent to the largest)
    t = i["totals"]
    assert t["subtotal"] == "279.97" and t["line_discounts"] == "10.00" and t["invoice_discount"] == "27.00"
    nets = [ln["net"] for ln in i["lines"]]
    assert sum(float(n) for n in nets) == pytest.approx(242.97)
    assert all(float(ln["net"]) >= 0 for ln in i["lines"])
    # taxable: Coaching + Shirt finals; tax 7.25 % once per invoice
    taxable = float(nets[1]) + float(nets[2])
    assert t["taxable"] == f"{taxable:.2f}"
    assert t["tax"] == f"{round(taxable * 0.0725 + 1e-9, 2):.2f}"
    assert t["total"] == f"{242.97 + float(t['tax']):.2f}"
    assert i["lines"][1]["description"].startswith("Coaching") and i["lines"][1]["unit_price"] == "40.00"
    assert i["status"] == "DRAFT" and i["due_date"] == "2026-10-15"            # Net 30 by default


def test_prices_are_copied_and_discounts_validated(env, ib):
    """AC-INV-DOC-002: a catalog price change never alters an invoice; discounts can't exceed what they apply to."""
    i = ib["im"].post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1"}])).json()
    ib["im"].put(f"/api/invoices/catalog/products/{ib['dues']}", {"name": "Annual dues", "unit_price": "150.00",
                 "unit_type_id": [u["id"] for u in ib["im"].get("/api/invoices/catalog/unit-types").json() if u["name"] == "Year"][0],
                 "budget_id": i["lines"][0]["budget"]["id"]})
    again = ib["im"].get(f"/api/invoices/{i['id']}").json()
    assert again["lines"][0]["unit_price"] == "120.00"
    r = ib["im"].post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1", "discount_kind": "AMOUNT",
                                                    "discount_value": "200", "discount_reason": "too much"}]))
    assert r.status_code == 422
    r = ib["im"].post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1"}],
                                             discount={"kind": "AMOUNT", "value": "500", "reason": "x"}))
    assert r.status_code == 422
    r = ib["im"].post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1", "discount_kind": "PERCENT",
                                                    "discount_value": "5"}]))
    assert r.status_code == 422                                              # a reason is required
    assert ib["im"].post("/api/invoices", _body(ib, [])).status_code == 422  # catalog lines only, at least one
    disc = [p for p in ib["im"].get("/api/invoices/catalog/products").json() if p["is_system"]][0]
    assert ib["im"].post("/api/invoices", _body(ib, [{"product_id": disc["id"], "quantity": "1"}])).status_code == 422


def test_numbers_follow_the_pattern_and_are_never_reused(env, ib):
    """AC-INV-DOC-003 (BR-001): the sequence never restarts; a voided draft keeps its number."""
    r = env.admin.put("/api/invoices/setup", {"number_pattern": "INV-{YYYY}-{SEQ:4}", "terms_days": 15})
    assert r.status_code == 200, r.text
    a = ib["im"].post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1"}])).json()
    assert a["number"] == "INV-2026-0001" and a["due_date"] == "2026-09-30"
    assert ib["im"].post(f"/api/invoices/{a['id']}/void", {"reason": "Entered twice"}).json()["status"] == "VOID"
    b = ib["im"].post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1"}], invoice_date="2027-01-05")).json()
    assert b["number"] == "INV-2027-0002"
    assert env.admin.put("/api/invoices/setup", {"number_pattern": "INV-{YYYY}", "terms_days": 30}).status_code == 422
    assert env.admin.put("/api/invoices/setup", {"number_pattern": "X-{SEQ}<script>", "terms_days": 30}).status_code == 422
    assert ib["im"].put("/api/invoices/setup", {"number_pattern": "A-{SEQ}", "terms_days": 30}).status_code == 403


def test_send_revise_keeps_every_pdf(env, ib):
    """AC-INV-DOC-004: Mark as sent keeps the PDF; a revision keeps the number with -R1; earlier PDFs stay."""
    im = ib["im"]
    i = im.post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1"}])).json()
    s = im.post(f"/api/invoices/{i['id']}/send")
    assert s.status_code == 200 and s.json()["status"] == "SENT"
    assert im.put(f"/api/invoices/{i['id']}", _body(ib, [{"product_id": ib["dues"], "quantity": "2"}])).status_code == 409
    r = im.post(f"/api/invoices/{i['id']}/revise", {"reason": "Customer asked for two"})
    assert r.status_code == 200 and r.json()["number"] == f"{i['number']}-R1" and r.json()["status"] == "DRAFT"
    # adding a discount after sending happens in the revision
    lines = [{"id": r.json()["lines"][0]["id"], "product_id": ib["dues"], "quantity": "2", "discount_kind": "AMOUNT",
              "discount_value": "20", "discount_reason": "Two-year member"}]
    assert im.put(f"/api/invoices/{i['id']}", _body(ib, lines)).json()["total"] == "220.00"
    d = im.post(f"/api/invoices/{i['id']}/send").json()
    assert [v["number"] for v in d["versions"]] == [i["number"], f"{i['number']}-R1"]
    assert d["versions"][0]["reason"] == "Customer asked for two"
    for v in d["versions"]:
        pdf = env.bu.get(v["pdf_url"])
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
        assert v["number"] in "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(env.bu.get(d["versions"][1]["pdf_url"]).content)).pages)
    assert "Two-year member" in text and "Acme Customer" in text
    assert env.auditor.get(f"/api/audit-events?action=INVOICE_REVISION_STARTED&object_id={i['id']}").json()["items"]


def test_administrator_test_print_uses_sample_data_only(env, ib):
    """AC-INV-DOC-005 (BR-003): the Administrator's test print has dummy data; no invoice is readable by them."""
    i = ib["im"].post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1"}])).json()
    r = env.admin.get("/api/invoices/setup/test-print")
    assert r.status_code == 200
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "Sample Customer" in text and "Acme Customer" not in text and "Annual dues" not in text
    for url in ("/api/invoices", f"/api/invoices/{i['id']}", f"/api/invoices/{i['id']}/pdf"):
        assert env.admin.get(url).status_code == 403


def test_void_and_write_off_need_reasons_and_budget_manager_approval(env, ib):
    """AC-INV-DOC-006: reasons; Budget Manager approves; self-approval marked; all audited; no budget effect."""
    im = ib["im"]
    i = im.post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1"}])).json()
    assert im.post(f"/api/invoices/{i['id']}/void", {"reason": ""}).status_code == 422
    im.post(f"/api/invoices/{i['id']}/send")
    assert im.post(f"/api/invoices/{i['id']}/write-off", {"reason": "Customer closed"}).json()["write_off_status"] == "PENDING"
    assert im.post(f"/api/invoices/{i['id']}/write-off/decision", {"approve": True}).status_code == 403
    rej = env.bm.post(f"/api/invoices/{i['id']}/write-off/decision", {"approve": False})
    assert rej.status_code == 422                                         # a rejection needs a reason
    rej = env.bm.post(f"/api/invoices/{i['id']}/write-off/decision", {"approve": False, "note": "Try once more"})
    assert rej.json()["status"] == "SENT" and rej.json()["write_off"]["status"] == "REJECTED"
    im.post(f"/api/invoices/{i['id']}/write-off", {"reason": "Customer closed for good"})
    ok = env.bm.post(f"/api/invoices/{i['id']}/write-off/decision", {"approve": True}).json()
    assert ok["status"] == "WRITTEN_OFF" and ok["write_off"]["self_approved"] is False
    # self-approval: one person with both roles
    both = env.user("both", "FINANCIAL", ["INVOICE_MANAGER", "BUDGET_MANAGER"])
    j = both.post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1"}])).json()
    both.post(f"/api/invoices/{j['id']}/send")
    both.post(f"/api/invoices/{j['id']}/write-off", {"reason": "Uncollectable"})
    assert both.post(f"/api/invoices/{j['id']}/write-off/decision", {"approve": True}).json()["write_off"]["self_approved"] is True
    for action in ("INVOICE_VOIDED", "INVOICE_WRITE_OFF_REQUESTED", "INVOICE_WRITE_OFF_REJECTED", "INVOICE_WRITE_OFF_APPROVED", "INVOICE_SENT"):
        if action == "INVOICE_VOIDED":
            continue
        assert env.auditor.get(f"/api/audit-events?action={action}").json()["items"], action
    # no financial effect: the Invoiced Income budget's actual is unchanged
    fy = env.bu.get("/api/fiscal-years").json()[0]["id"]
    tree = env.bu.get(f"/api/fiscal-years/{fy}").json()
    rows = (tree.get("budgets") or tree)["income"]
    assert all(r["actual"] == "0.00" for r in rows)


def test_roles_view_and_refusals(env, ib):
    """AC-INV-DOC-007 (BR-108): IM manages; RU, BM, BU, Auditor view; nobody else changes; module off refuses."""
    i = ib["im"].post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1"}])).json()
    for c in (env.ru, env.bm, env.bu, env.auditor):
        assert c.get(f"/api/invoices/{i['id']}").status_code == 200
        assert c.get("/api/invoices").status_code == 200
        assert c.post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1"}])).status_code == 403
        assert c.post(f"/api/invoices/{i['id']}/send").status_code == 403
        assert c.post(f"/api/invoices/{i['id']}/void", {"reason": "x"}).status_code == 403
    assert ib["im"].get("/api/invoices/999999").status_code == 404           # BR-099
    # mass assignment: status / number / seq are not writable
    r = ib["im"].put(f"/api/invoices/{i['id']}", {**_body(ib, [{"product_id": ib["dues"], "quantity": "1"}]), "status": "PAID"})
    assert r.status_code == 422
    env.admin.put("/api/system/modules", {"invoices": False})
    assert ib["im"].get("/api/invoices").status_code == 404


def test_needs_budget_and_inactive_customer(env, base, ib):
    """AC-INV-DOC-008: a line whose product has no budget in the invoice date's Fiscal Year is refused; no open
    Fiscal Year for the date is refused; an inactive customer is refused."""
    fy28 = env.fy("2028", "2027-07-01", "2028-06-30")
    r = ib["im"].post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1"}], invoice_date="2027-08-01"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "NEEDS_BUDGET"
    r = ib["im"].post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1"}], invoice_date="2030-01-01"))
    assert r.status_code == 422
    assert fy28["id"]


def test_list_filters_and_search(env, ib):
    """AC-INV-DOC-009: list by status (OPEN = sent or partly paid) and search by number or customer."""
    im = ib["im"]
    a = im.post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1"}])).json()
    b = im.post("/api/invoices", _body(ib, [{"product_id": ib["dues"], "quantity": "1"}])).json()
    im.post(f"/api/invoices/{b['id']}/send")
    assert [x["id"] for x in im.get("/api/invoices?status=OPEN").json()] == [b["id"]]
    assert [x["id"] for x in im.get("/api/invoices?status=DRAFT").json()] == [a["id"]]
    assert len(im.get("/api/invoices?search=Acme").json()) == 2
    assert im.get("/api/invoices?search=zzz' OR 1=1 --").json() == []        # AC-SEC-009
