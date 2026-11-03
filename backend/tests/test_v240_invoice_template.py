"""2.4.0 (#253 part 3): the invoice PDF template - letterhead, logo, {VARIABLES}, column picker, live preview with
sample data only.

BR-INV-TPL-001..003 / AC-INV-TPL-001..004 (recorded in docs/implementation-notes.md); regression for BR-003, BR-073/074
(logo checked and re-encoded), BR-102 (variables are a table lookup).
"""
from __future__ import annotations

import io

import pytest
from PIL import Image
from pypdf import PdfReader


def _text(pdf: bytes) -> str:
    return "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


def _png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (300, 100), (20, 60, 120)).save(b, "PNG")
    return b.getvalue()


@pytest.fixture
def tb(env, base):
    assert env.admin.put("/api/system/modules", {"invoices": True}).status_code == 200
    im = env.user("invmgr", "FINANCIAL", ["INVOICE_MANAGER"])
    env.bm.put(f"/api/budgets/{base['inc']['id']}/invoiced-income", {"invoiced_income": True})
    units = {u["name"]: u["id"] for u in im.get("/api/invoices/catalog/unit-types").json()}
    p = im.post("/api/invoices/catalog/products", {"name": "Hall rental", "code": "HALL-1", "unit_price": "50.00",
                                                  "unit_type_id": units["Hour"], "budget_id": base["inc_leaf"]}).json()["id"]
    cust = env.entity("Template Customer", client=im)["id"]
    i = im.post("/api/invoices", {"customer_entity_id": cust, "invoice_date": "2026-09-15",
                                  "lines": [{"product_id": p, "quantity": "2", "discount_kind": "AMOUNT", "discount_value": "5.00",
                                             "discount_reason": "Member"}]}).json()
    return {"im": im, "inv": i["id"], "cust": cust}


def test_default_template_and_variables_list(env, tb):
    """AC-INV-TPL-001: the default layout prints the organization, customer and lines; the variables are listed."""
    t = env.admin.get("/api/invoices/setup/template").json()
    assert t["config"]["title"] == "INVOICE" and [c["key"] for c in t["config"]["columns"]] == ["DESCRIPTION", "QUANTITY", "UNIT_PRICE", "AMOUNT"]
    names = {v["name"] for v in t["variables"]}
    assert {"ORG", "ORG.ADDRESS", "CUSTOMER.NAME", "CUSTOMER.MAILING_ADDRESS", "INVOICE.NUMBER", "INVOICE.BALANCE"} <= names
    text = _text(tb["im"].get(f"/api/invoices/{tb['inv']}/pdf").content)
    assert "Template Customer" in text and "Hall rental" in text and "Member" in text


def test_save_validates_and_audits_and_invoices_use_it(env, tb):
    """AC-INV-TPL-002: unknown variables and bad columns are refused with a suggestion; the saved template lays out
    every new PDF; audited; Administrator only."""
    cfg = env.admin.get("/api/invoices/setup/template").json()["config"]
    bad = env.admin.put("/api/invoices/setup/template", {**cfg, "footer": "Pay {INVOICE.TOTL} please"})
    assert bad.status_code == 422 and "INVOICE.TOTAL" in bad.json()["error"]["message"]
    assert env.admin.put("/api/invoices/setup/template", {**cfg, "columns": [{"key": "QUANTITY", "heading": "Qty"}]}).status_code == 422
    assert env.admin.put("/api/invoices/setup/template", {**cfg, "accent": "red"}).status_code == 422
    assert env.admin.put("/api/invoices/setup/template", {**cfg, "unknown": 1}).status_code == 422
    new = {**cfg, "title": "STATEMENT OF CHARGES", "bill_to_heading": "Charged to",
           "columns": [{"key": "CODE", "heading": "Item"}, {"key": "DESCRIPTION", "heading": "What"},
                       {"key": "QUANTITY", "heading": "Hours"}, {"key": "DISCOUNT", "heading": "Less"},
                       {"key": "NET", "heading": "Net"}],
           "footer": "Please pay {INVOICE.BALANCE} for {INVOICE.NUMBER} by {INVOICE.DUE_DATE}. Thank you, {CUSTOMER.NAME}!"}
    r = env.admin.put("/api/invoices/setup/template", new)
    assert r.status_code == 200, r.text
    for c in (tb["im"], env.bm, env.auditor):
        assert c.put("/api/invoices/setup/template", new).status_code == 403
        assert c.post("/api/invoices/setup/template/preview", new).status_code == 403
    assert env.admin.get("/api/audit-events?action=INVOICE_TEMPLATE_UPDATED").json()["items"]
    inv = tb["im"].get(f"/api/invoices/{tb['inv']}").json()
    text = _text(tb["im"].get(f"/api/invoices/{tb['inv']}/pdf").content)
    assert "STATEMENT OF CHARGES" in text and "Charged to" in text and "HALL-1" in text and "Hours" in text
    assert f"Please pay 95.00 for {inv['number']}" in text and "Thank you, Template Customer!" in text


def test_preview_uses_sample_data_only(env, tb):
    """AC-INV-TPL-003 (BR-003): the preview of unsaved settings shows sample data - no real customer or invoice."""
    cfg = env.admin.get("/api/invoices/setup/template").json()["config"]
    r = env.admin.post("/api/invoices/setup/template/preview", {**cfg, "title": "PREVIEW TITLE"})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    text = _text(r.content)
    assert "PREVIEW TITLE" in text and "Sample Customer" in text and "Template Customer" not in text
    assert "Hall rental" not in text
    assert env.admin.get("/api/invoices/setup/template").json()["config"]["title"] == "INVOICE"      # not saved
    img = env.admin.post("/api/invoices/setup/template/preview-image", cfg)
    assert img.status_code in (200, 501)


def test_logo_checked_reencoded_and_printed(env, tb):
    """AC-INV-TPL-004: PNG/JPEG only, at most 1 MB, re-encoded; audited by fingerprint; removable."""
    bad = env.admin.post("/api/invoices/setup/template/logo", files={"file": ("x.png", b"not an image", "image/png")})
    assert bad.status_code in (415, 422)
    r = env.admin.post("/api/invoices/setup/template/logo", files={"file": ("logo.png", _png(), "image/png")})
    assert r.status_code == 200 and r.json()["has_logo"] is True
    assert env.admin.get("/api/invoices/setup/template/logo").content[:8] == b"\x89PNG\r\n\x1a\n"
    pdf = tb["im"].get(f"/api/invoices/{tb['inv']}/pdf").content
    assert any("/Image" in str(p.get("/Resources", {}).get("/XObject", {}).values()) or p.get("/Resources", {}).get("/XObject")
               for p in PdfReader(io.BytesIO(pdf)).pages)
    assert env.admin.get("/api/audit-events?action=INVOICE_LOGO_SET").json()["items"]
    assert env.admin.post("/api/invoices/setup/template/logo/remove").json()["has_logo"] is False
    assert tb["im"].post("/api/invoices/setup/template/logo", files={"file": ("logo.png", _png(), "image/png")}).status_code == 403
