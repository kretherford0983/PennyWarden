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


# ------------------------------------------------------------------ 2.4.0 polish (#478, #479)
def _image_x(pdf: bytes) -> tuple[float, float]:
    """(left, right) in inches of the first image drawn on page 1 (walks the content stream's q/Q/cm to the Do)."""
    from pypdf.generic import ContentStream
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    ctm, stack = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0], []
    for operands, op in ContentStream(page.get_contents(), page.pdf).operations:
        if op == b"q":
            stack.append(ctm)
        elif op == b"Q":
            ctm = stack.pop()
        elif op == b"cm":
            a, b, c, d, e, f = (float(x) for x in operands)
            A, B, C, D, E, F = ctm
            ctm = [a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D, e * A + f * C + E, e * B + f * D + F]
        elif op == b"Do":
            return ctm[4] / 72, (ctm[4] + ctm[0]) / 72
    raise AssertionError("no image")


def _texts(pdf: bytes, page: int = 0) -> dict[str, tuple[float, float]]:
    """text -> (x, y) in inches from the top-left corner."""
    pg = PdfReader(io.BytesIO(pdf)).pages[page]
    h = float(pg.mediabox.height)
    out: dict[str, tuple[float, float]] = {}

    def visit(text, cm, tm, _fd, _fs):
        if text.strip():
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            out.setdefault(text.strip(), (x / 72, (h - y) / 72))
    pg.extract_text(visitor_text=visit)
    return out


def test_logo_right_sits_at_the_margin_and_center_between(env, tb):
    """#478: RIGHT puts the logo at the right margin (over the right-aligned title); CENTER centers it on the page."""
    env.admin.post("/api/invoices/setup/template/logo", files={"file": ("logo.png", _png(), "image/png")})
    cfg = env.admin.get("/api/invoices/setup/template").json()["config"]
    right = env.admin.post("/api/invoices/setup/template/preview", {**cfg, "logo_position": "RIGHT"}).content
    _l, r = _image_x(right)
    assert abs(r - 7.75) < 0.05                                       # 8.5 in page, 0.75 in right margin
    center = env.admin.post("/api/invoices/setup/template/preview", {**cfg, "logo_position": "CENTER"}).content
    l, r = _image_x(center)
    assert abs((l + r) / 2 - 4.25) < 0.05
    assert env.admin.put("/api/invoices/setup/template", {**cfg, "logo_position": "CENTER"}).status_code == 200
    assert env.admin.put("/api/invoices/setup/template", {**cfg, "logo_position": "MIDDLE"}).status_code == 422


def test_fold_marks_and_window_layout(env, tb):
    """#479: fold marks on the back add a back page per page; the window layout prints the letterhead and Bill to in
    the #10 double-window positions and starts the body below the first fold; the sample draws the windows."""
    cfg = env.admin.get("/api/invoices/setup/template").json()["config"]
    plain = env.admin.post("/api/invoices/setup/template/preview", cfg).content
    back = env.admin.post("/api/invoices/setup/template/preview", {**cfg, "fold_marks": "BACK"}).content
    assert len(PdfReader(io.BytesIO(back)).pages) == 2 * len(PdfReader(io.BytesIO(plain)).pages)
    front = env.admin.post("/api/invoices/setup/template/preview", {**cfg, "fold_marks": "FRONT"}).content
    assert len(front) > len(plain)                                    # the ticks are drawn
    win = env.admin.post("/api/invoices/setup/template/preview", {**cfg, "window": "LETTER"}).content
    t = _texts(win)
    cust = t["Sample Customer"]
    assert abs(cust[0] - 0.85) < 0.05 and 2.1 < cust[1] < 2.35        # the lower window
    assert "fold" in t                                                # sample: folds labeled
    desc = [y for k, (x, y) in t.items() if k.startswith("Description")]
    assert desc and min(desc) > 11 / 3                                # the line table starts below the first fold
    moved = env.admin.post("/api/invoices/setup/template/preview", {**cfg, "window": "LETTER", "payee_dx": 0.25}).content
    assert abs(_texts(moved)["Sample Customer"][0] - 1.10) < 0.05
    bad = env.admin.put("/api/invoices/setup/template", {**cfg, "window": "LETTER", "payee_dx": 2})
    assert bad.status_code == 422
    # a real invoice PDF carries no window outlines or fold labels
    env.admin.put("/api/invoices/setup/template", {**cfg, "window": "LETTER", "fold_marks": "FRONT"})
    real = tb["im"].get(f"/api/invoices/{tb['inv']}/pdf").content
    rt = _texts(real)
    assert "fold" not in rt and abs(rt["Template Customer"][0] - 0.85) < 0.05
