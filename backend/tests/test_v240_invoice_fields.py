"""2.4.0 (#253 part 2): invoice custom fields - defined by the Administrator, filled in by the Invoice Manager.

BR-INV-FLD-001..003 / AC-INV-FLD-001..004 (recorded in docs/implementation-notes.md); regression for BR-001 (retired,
never deleted), BR-003, BR-075/076, BR-108.
"""
from __future__ import annotations

import io

import pytest
from pypdf import PdfReader


@pytest.fixture
def ib(env, base):
    assert env.admin.put("/api/system/modules", {"invoices": True}).status_code == 200
    im = env.user("invmgr", "FINANCIAL", ["INVOICE_MANAGER"])
    env.bm.put(f"/api/budgets/{base['inc']['id']}/invoiced-income", {"invoiced_income": True})
    units = {u["name"]: u["id"] for u in im.get("/api/invoices/catalog/unit-types").json()}
    p = im.post("/api/invoices/catalog/products", {"name": "Dues", "unit_price": "50.00", "unit_type_id": units["Year"],
                                                  "budget_id": base["inc_leaf"]}).json()
    cust = env.entity("Field Customer", client=im)
    return {"im": im, "product": p["id"], "cust": cust["id"]}


def _field(env, **kw):
    body = {"level": "INVOICE", "field_type": "TEXT", "name": "Purchase order", "required": False, "show_on_pdf": True, **kw}
    return env.admin.post("/api/invoices/setup/fields", body)


def test_administrator_defines_fields_audited_retired_not_deleted(env, ib):
    """AC-INV-FLD-001: types, required, show-on-PDF; level/type fixed; retire/restore; only the Administrator."""
    po = _field(env)
    assert po.status_code == 201, po.text
    pick = _field(env, level="LINE", field_type="PICKLIST", name="Season", options=["Spring", "Fall"], required=True)
    assert pick.status_code == 201
    assert _field(env, field_type="PICKLIST", name="Empty pick").status_code == 422
    assert _field(env, name="purchase order").status_code == 409
    r = env.admin.put(f"/api/invoices/setup/fields/{po.json()['id']}", {"name": "PO number", "field_type": "NUMBER"})
    assert r.status_code == 422                                     # type can't change
    r = env.admin.put(f"/api/invoices/setup/fields/{po.json()['id']}", {"name": "PO number", "show_on_pdf": True})
    assert r.status_code == 200 and r.json()["name"] == "PO number"
    assert env.admin.post(f"/api/invoices/setup/fields/{po.json()['id']}/retire").json()["active"] is False
    assert env.admin.delete(f"/api/invoices/setup/fields/{po.json()['id']}").status_code in (404, 405)
    for c in (ib["im"], env.bm, env.auditor):
        assert c.post("/api/invoices/setup/fields", {"level": "INVOICE", "field_type": "TEXT", "name": "X"}).status_code == 403
    for a in ("INVOICE_FIELD_CREATED", "INVOICE_FIELD_UPDATED", "INVOICE_FIELD_RETIRED"):
        assert env.admin.get(f"/api/audit-events?action={a}").json()["items"], a


def test_values_validated_server_side_and_printed(env, ib):
    """AC-INV-FLD-002/003: required, type and pick-list checks; show-on-PDF controls printing."""
    po = _field(env).json()
    due = _field(env, name="Event date", field_type="DATE", show_on_pdf=False).json()
    season = _field(env, level="LINE", field_type="PICKLIST", name="Season", options=["Spring", "Fall"], required=True).json()
    base = {"customer_entity_id": ib["cust"], "invoice_date": "2026-09-15"}
    line = {"product_id": ib["product"], "quantity": "1"}
    r = ib["im"].post("/api/invoices", {**base, "lines": [line]})
    assert r.status_code == 422 and "Season" in r.json()["error"]["message"]          # required line field
    r = ib["im"].post("/api/invoices", {**base, "lines": [{**line, "custom_values": {str(season["id"]): "Winter"}}]})
    assert r.status_code == 422
    r = ib["im"].post("/api/invoices", {**base, "custom_values": {str(due["id"]): "not a date"},
                                        "lines": [{**line, "custom_values": {str(season["id"]): "Fall"}}]})
    assert r.status_code == 422
    r = ib["im"].post("/api/invoices", {**base, "custom_values": {"999999": "x"},
                                        "lines": [{**line, "custom_values": {str(season["id"]): "Fall"}}]})
    assert r.status_code == 422                                                     # unknown field
    ok = ib["im"].post("/api/invoices", {**base, "custom_values": {str(po["id"]): "PO-77<script>", str(due["id"]): "2026-10-01"},
                                         "lines": [{**line, "custom_values": {str(season["id"]): "Fall"}}]})
    assert ok.status_code == 201, ok.text
    i = ok.json()
    assert {f["name"]: f["value"] for f in i["fields"]} == {"Purchase order": "PO-77<script>", "Event date": "2026-10-01"}
    assert i["lines"][0]["fields"][0]["value"] == "Fall"
    pdf = ib["im"].get(f"/api/invoices/{i['id']}/pdf").content
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "PO-77" in text and "Fall" in text and "2026-10-01" not in text           # Event date: not on the PDF


def test_retired_field_keeps_its_values(env, ib):
    """AC-INV-FLD-004: a retired field is no longer asked for or required, and old values stay."""
    po = _field(env, required=True).json()
    base = {"customer_entity_id": ib["cust"], "invoice_date": "2026-09-15", "lines": [{"product_id": ib["product"], "quantity": "1"}]}
    i = ib["im"].post("/api/invoices", {**base, "custom_values": {str(po["id"]): "PO-1"}}).json()
    env.admin.post(f"/api/invoices/setup/fields/{po['id']}/retire")
    assert po["id"] not in [f["id"] for f in ib["im"].get("/api/invoices/fields").json()]
    again = ib["im"].put(f"/api/invoices/{i['id']}", {**base, "lines": [{"id": i["lines"][0]["id"], "product_id": ib["product"], "quantity": "2"}]})
    assert again.status_code == 200, again.text
    assert again.json()["fields"] == [{"field_id": po["id"], "name": "Purchase order", "value": "PO-1", "retired": True}]
    assert ib["im"].post("/api/invoices", base).status_code == 201                 # not required any more
