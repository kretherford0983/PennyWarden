"""2.4.0 (#513): the formal invoice reports - Sales by product & category, and the Sales overview - as JSON, PDF and
presentation. BR-INV-PUB-001..003 / AC-INV-PUB-001..006 (docs/implementation-notes.md)."""
from __future__ import annotations

import io

import pytest
from pptx import Presentation
from pypdf import PdfReader

from test_v240_invoice_payments import ib  # noqa: F401  (fixture)

URL = "/api/invoices/formal"


def _q(env, base, rid="inv-sales-formal", client=None, **kw):
    params = {"fiscal_year_id": base["fy"]["id"], "period": "ANNUAL", "format": "json", **kw}
    return (client or env.ru).get(f"{URL}/{rid}", params=params)


def pdf_text(content: bytes) -> str:
    return " ".join(" ".join((p.extract_text() or "").split()) for p in PdfReader(io.BytesIO(content)).pages)


def _pay(env, ib, amount, date="2026-09-20"):
    r = env.ru.post(f"/api/invoices/{ib['inv']}/payments", {"bank_account_id": ib["acct"], "amount": amount,
                                                            "transaction_date": date})
    assert r.status_code == 201, r.json().get("error")


def test_ac_inv_pub_001_sales_match_the_basic_report_and_collected_is_exact(env, base, ib):
    r = _q(env, base)
    assert r.status_code == 200, r.text
    rep = r.json()
    for by in ("product", "category", "budget"):              # the same total as the basic report, every grouping
        basic = env.ru.get("/api/invoices/reports/inv-sales", params={"date_from": rep["start_date"],
                                                                      "date_to": rep["cutoff"], "by": by}).json()
        assert basic["sections"][0]["totals"]["amount"] == "200.00"
    assert rep["total"]["amount"] == 20000                    # 2 x $100 dues, before tax
    assert rep["total"]["collected"] == 0 and rep["total"]["invoices"] == 1
    _pay(env, ib, "110.00")                                   # half of $220 (tax included)
    rep = _q(env, base).json()
    assert rep["total"]["collected"] == 10000                 # the payment's sales part, exactly
    assert sum(c["amount"] for c in rep["categories"]) == rep["total"]["amount"]
    assert sum(p["amount"] for g in rep["products"] for p in g["products"]) == rep["total"]["amount"]
    assert sum(b["amount"] for b in rep["budgets"]) == rep["total"]["amount"]
    assert rep["top_product"]["label"] == "Dues" and rep["key_points"]


def test_ac_inv_pub_002_overview_figures(env, base, ib):
    _pay(env, ib, "50.00", "2026-10-01")
    rep = _q(env, base, "inv-overview").json()
    f = rep["figures"]
    assert f["invoices"] == 1 and f["invoiced"] == 22000 and f["tax"] == 2000 and f["net_sales"] == 20000
    assert f["net_collected"] == 5000 and f["open_end"] in (17000, 22000)    # open as of the cutoff
    assert sum(m["invoiced"] for m in rep["months"]) == f["invoiced"]
    assert sum(m["collected"] for m in rep["months"]) == f["net_collected"]
    assert rep["top_customers"][0]["name"] == "Paying Customer"
    assert rep["tax"] and rep["tax"][0]["charged"] == 2000
    hidden = _q(env, base, "inv-overview", show_names=False).json()
    assert hidden["top_customers"][0]["name"] == "Customer 1"
    assert "Paying Customer" not in str(hidden)


def test_ac_inv_pub_003_periods_custom_range_and_comparison(env, base, ib):
    rep = _q(env, base, period="Q1").json()                  # FY2027 Q1 = Jul-Sep 2026: the invoice is in it
    assert rep["period_label"].startswith("Q1") and rep["total"]["amount"] == 20000
    assert rep["prior_label"] is None                         # no Fiscal Year before FY2027 in this setup
    rep = env.ru.get(f"{URL}/inv-sales-formal", params={"date_from": "2026-09-01", "date_to": "2026-09-30",
                                                        "format": "json"}).json()
    assert rep["kind"] == "CUSTOM" and rep["total"]["amount"] == 20000 and rep["prior_label"] is None
    r = env.ru.get(f"{URL}/inv-sales-formal", params={"date_from": "2026-09-30", "date_to": "2026-09-01", "format": "json"})
    assert r.status_code == 422
    assert env.ru.get(f"{URL}/inv-sales-formal", params={"format": "json"}).status_code == 422


def test_ac_inv_pub_003_same_period_last_year(env, base, ib):
    prev = env.fy("2026", "2025-07-01", "2026-06-30")
    rep = _q(env, base, period="Q1").json()
    assert rep["prior_label"].startswith("Q1 FY2026") and rep["prior_total"]["amount"] == 0
    assert rep["categories"][0]["prior"] == 0
    ov = _q(env, base, "inv-overview", period="Q1").json()
    assert ov["compare"]["invoiced"]["prior"] == 0 and ov["compare"]["invoiced"]["change"] is None
    assert prev


def test_ac_inv_pub_004_pdf_and_presentation_audited(env, base, ib):
    for rid in ("inv-sales-formal", "inv-overview"):
        r = _q(env, base, rid, format="pdf", commentary="A <b>strong</b> year.")
        assert r.status_code == 200 and r.content.startswith(b"%PDF")
        t = pdf_text(r.content)
        assert "A <b>strong</b> year." in t and "Dues" in t and "Key points" in t
        r = _q(env, base, rid, format="pptx")
        assert r.status_code == 200
        prs = Presentation(io.BytesIO(r.content))
        assert len(prs.slides) >= 4
    ev = env.admin.get("/api/audit-events?action=REPORT_GENERATED").json()["items"]
    kinds = {e["after"]["report"] for e in ev if e.get("after")}
    assert {"INV_SALES_FORMAL", "INV_SALES_FORMAL_PRESENTATION", "INV_OVERVIEW", "INV_OVERVIEW_PRESENTATION"} <= kinds


def test_ac_inv_pub_005_who_can_run_them(env, base, ib):
    assert _q(env, base, client=env.bm).status_code == 200
    assert _q(env, base, client=ib["im"]).status_code == 200
    assert _q(env, base, client=env.auditor).status_code == 200
    assert _q(env, base, client=env.admin).status_code == 403             # BR-003
    opts = ib["im"].get(f"{URL}/options").json()
    assert opts["fiscal_year_id"] == base["fy"]["id"] and opts["periods"][-1]["id"] == "ANNUAL"
    assert env.admin.put("/api/system/modules", {"invoices": False}).status_code == 200
    assert _q(env, base).status_code in (403, 404, 409)


def test_ac_inv_pub_006_commentary_limit_and_no_markup(env, base, ib):
    assert _q(env, base, commentary="x" * 2001).status_code == 422
    pdf = _q(env, base, "inv-overview", format="pdf", commentary="<script>alert(1)</script>").content
    assert "<script>alert(1)</script>" in pdf_text(pdf)      # printed as text, not interpreted


def test_ac_inv_pub_004_a_period_with_no_invoices_still_prints(env, base):
    assert env.admin.put("/api/system/modules", {"invoices": True}).status_code == 200
    for rid in ("inv-sales-formal", "inv-overview"):
        for fmt in ("pdf", "pptx", "json"):
            r = _q(env, base, rid, client=env.bm, format=fmt)
            assert r.status_code == 200, (rid, fmt, r.text[:200])
        r = env.bm.get(f"{URL}/{rid}", params={"date_from": "2026-01-01", "date_to": "2026-12-31", "format": "pptx"})
        assert r.status_code == 200
