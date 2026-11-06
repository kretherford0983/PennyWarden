"""2.4.0 (#522): the payment stub - off by default; at the bottom of the invoice's last page (a page of its own when
there isn't room); the invoice number large, dates, customer and customer number, amount due and Amount enclosed;
the pay-to lines from the organization profile (editable); optionally placed for a #9 return envelope window;
customer statements have their own setting. Decisions: Kyle, 2026-11-04. BR-INV-STUB-001..003 / AC-INV-STUB-001..004."""
from __future__ import annotations

import io

from pypdf import PdfReader

from test_v240_invoice_payments import ib  # noqa: F401  (fixture)

def _tpl(env, **kw):
    cfg = env.admin.get("/api/invoices/setup/template").json()["config"]
    r = env.admin.put("/api/invoices/setup/template", {**cfg, **kw})
    assert r.status_code == 200, r.text
    return r.json()["config"]


def _text(pdf: bytes) -> tuple[int, str]:
    pages = PdfReader(io.BytesIO(pdf)).pages
    return len(pages), " ".join(" ".join((p.extract_text() or "").split()) for p in pages)


def test_ac_inv_stub_001_off_by_default_then_on_the_last_page(env, ib):
    cfg = env.admin.get("/api/invoices/setup/template").json()["config"]
    assert cfg["stub"] is False and cfg["statement_stub"] is False and cfg["stub_window"] is False
    off = env.admin.post("/api/invoices/setup/template/preview", cfg).content
    assert "detach and return" not in _text(off)[1]
    on = env.admin.post("/api/invoices/setup/template/preview", {**cfg, "stub": True}).content
    n, t = _text(on)
    assert n == 1 and "Please detach and return this portion with your payment." in t
    for s in ("PAYMENT STUB", "Make checks payable to", "Customer number", "Amount due", "Amount enclosed", "Mail to"):
        assert s in t, s


def test_ac_inv_stub_002_real_invoice_window_and_pay_to(env, ib):
    _tpl(env, stub=True, stub_window=True, stub_payable="Example Club Treasurer", stub_address=["PO Box 12", "Springfield, ST 00000"])
    pdf = ib["im"].get(f"/api/invoices/{ib['inv']}/pdf").content
    n, t = _text(pdf)
    num = ib["im"].get(f"/api/invoices/{ib['inv']}").json()["number"]
    assert num in t and "Example Club Treasurer" in t and "PO Box 12" in t and "$220.00" in t
    assert "Mail to" not in t                                    # in the window: the envelope's address, no label


def test_ac_inv_stub_003_a_new_page_when_there_is_no_room(env, ib):
    cfg = _tpl(env, stub=True)
    long = env.admin.post("/api/invoices/setup/template/preview", {**cfg, "footer": "\n".join(["A long footer line."] * 40)})
    n, t = _text(long.content)
    assert n == 2 and "detach and return" in t


def test_ac_inv_stub_004_customer_statement_has_its_own_stub(env, ib):
    params = {"customer_entity_id": ib["cust"], "date_from": "2026-09-01", "date_to": "2026-09-30", "format": "pdf"}
    plain = env.ru.get("/api/invoices/reports/inv-statement", params=params).content
    _tpl(env, stub=True)                                         # the invoice's stub doesn't add one to statements
    assert _text(env.ru.get("/api/invoices/reports/inv-statement", params=params).content)[0] == _text(plain)[0]
    _tpl(env, statement_stub=True)
    pdf = env.ru.get("/api/invoices/reports/inv-statement", params=params).content
    n, t = _text(pdf)
    assert n == _text(plain)[0] + 1 and "Payment stub" in t and "Amount due" in t and "$220.00" in t


def test_stub_settings_are_checked(env, ib):
    cfg = env.admin.get("/api/invoices/setup/template").json()["config"]
    assert env.admin.put("/api/invoices/setup/template", {**cfg, "stub_dx": 3}).status_code == 422
    assert env.admin.put("/api/invoices/setup/template", {**cfg, "stub_address": ["{NOT_A_VARIABLE}"]}).status_code == 422
