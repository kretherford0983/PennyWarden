"""v1.6.2 CR-035: fundraiser report - standalone and inside the Audit / Fiscal Year Close reports."""
import io

from conftest import PDF_BYTES, png_bytes
from pypdf import PdfReader


def _text(pdf: bytes) -> tuple[int, str]:
    r = PdfReader(io.BytesIO(pdf))
    return len(r.pages), " ".join(" ".join((p.extract_text() or "") for p in r.pages).split())


def _setup(env, base):
    assert env.admin.put("/api/system/modules", {"fundraisers": True}).status_code == 200
    acct = base["acct"]["id"]
    env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "200.00", "description": "Cash float"}], date="2026-09-10")
    t = env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "300.00", "description": "Food supplies"}], date="2026-09-11")
    env.txn(acct, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "1450.00", "description": "Gala takings"},
                              {"budget_id": base["inc_leaf"], "amount": "75.00", "description": "Unrelated donation"}], date="2026-09-14")
    f = env.bm.post("/api/fundraisers", {"name": "Harvest Gala", "description": "Annual dinner", "start_date": "2026-09-12",
                                         "budget_ids": [base["inc"]["id"], base["exp"]["id"]]}).json()
    fid = f["id"]
    line = {x["description"]: x["allocation_id"] for x in f["lines"]}
    b = env.ru.post(f"/api/fundraisers/{fid}/buckets", {"name": "Food sales"}).json()["buckets"]["items"][0]["id"]
    put = lambda d, body: env.ru.put(f"/api/fundraisers/{fid}/lines/{line[d]}", body)  # noqa: E731
    assert put("Cash float", {"classification": {"kind": "CASH_FLOAT_OUT", "amount": "200.00"}}).status_code == 200
    assert put("Gala takings", {"classification": {"kind": "CASH_FLOAT_RETURNED", "amount": "200.00", "note": "till"},
                                "buckets": [{"bucket_id": b, "amount": "1000.00"}]}).status_code == 200
    assert put("Unrelated donation", {"excluded": True, "exclusion_reason": "Not the gala"}).status_code == 200
    up = lambda url, name, data, mime: env.ru.c.post(url, files={"file": (name, data, mime)}, headers={"X-CSRF-Token": env.ru.csrf})  # noqa: E731
    assert up(f"/api/attachments?owner_type=fundraiser&owner_id={fid}", "flyer.png", png_bytes(), "image/png").status_code == 201
    assert up(f"/api/attachments?owner_type=transaction&owner_id={t['id']}", "receipt.pdf", PDF_BYTES, "application/pdf").status_code == 201
    return fid


def test_standalone_fundraiser_report(env, base):
    fid = _setup(env, base)
    assert env.admin.get(f"/api/fundraisers/{fid}/report").status_code == 403
    r = env.auditor.get(f"/api/fundraisers/{fid}/report")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert "fundraiser-Harvest-Gala-report.pdf" in r.headers["content-disposition"]
    pages, text = _text(r.content)
    for want in ("Fundraiser — Harvest Gala", "Annual dinner", "2026-09-12", "4000 Donations", "1000 Operations",
                 "$1,250.00", "$300.00", "$950.00", "316.7%", "cash float taken out $200.00", "cash float returned $200.00",
                 "Food sales", "Unassigned", "Gala takings", "Cash float returned $200.00 (till)", "Excluded lines",
                 "Not the gala", "Fundraiser document 1 of 1", "flyer.png", "receipt.pdf", "SHA-256"):
        assert want in text, want
    ev = env.auditor.get("/api/audit-events?action=REPORT_GENERATED&object_type=fundraiser").json()["items"]
    assert ev and ev[0]["after"]["report"] == "FUNDRAISER"
    # module off -> not reachable
    env.admin.put("/api/system/modules", {"fundraisers": False})
    assert env.auditor.get(f"/api/fundraisers/{fid}/report").status_code == 404


def test_audit_and_close_reports_include_fundraisers(env, base):
    fid = _setup(env, base)
    fy = base["fy"]["id"]
    # 2.6.0 (#609): the year's events are always in the report (no option); the old parameter is ignored
    plain = _text(env.auditor.get(f"/api/reports/audit?fiscal_year_id={fy}&include_fundraisers=false").content)
    assert "Fundraiser — Harvest Gala" in plain[1]
    r = env.auditor.get(f"/api/reports/audit?fiscal_year_id={fy}&signature_page=true")
    assert r.status_code == 200
    pages, text = _text(r.content)
    assert pages > plain[0] and "Fundraiser — Harvest Gala" in text
    # after the transaction pages, before the signature page
    assert text.index("Transaction #1") < text.index("Fundraiser — Harvest Gala") < text.rindex("undersigned")
    # Close report: always included; archived fundraisers are left out. 2.6.0 (#609): a switched-off module keeps
    # the year's events in the report (the data decides, not the switch)
    assert "Fundraiser — Harvest Gala" in _text(env.bm.get(f"/api/reports/fy-close?fiscal_year_id={fy}").content)[1]
    assert "Fundraiser — Harvest Gala" in _text(env.bm.get(f"/api/reports/fy-close?fiscal_year_id={fy}&include_fundraisers=false").content)[1]
    env.bm.post(f"/api/fundraisers/{fid}/archive")
    assert "Fundraiser — Harvest Gala" not in _text(env.bm.get(f"/api/reports/fy-close?fiscal_year_id={fy}").content)[1]
    env.bm.post(f"/api/fundraisers/{fid}/restore")
    env.admin.put("/api/system/modules", {"fundraisers": False})
    off = _text(env.bm.get(f"/api/reports/fy-close?fiscal_year_id={fy}").content)[1]
    assert "Fundraiser — Harvest Gala" in off and "Events & Fundraisers (module currently off)" in off


def test_two_year_fundraiser_is_shown_complete_in_each_year(env, base):
    assert env.admin.put("/api/system/modules", {"fundraisers": True}).status_code == 200
    fy28 = env.fy("2028", "2027-07-01", "2028-06-30")
    inc28 = env.budget(fy28["id"], "4000", "Donations", "INCOME", "1000.00")
    leaf28 = {o["label"]: o["id"] for o in env.selectable(fy28["id"], "DEPOSIT")}["4000 Donations"]
    env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "120.00", "description": "Fair prep"}], date="2027-06-20")
    env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": leaf28, "amount": "900.00", "description": "Fair takings"}], date="2027-07-12")
    env.bm.post("/api/fundraisers", {"name": "Summer Fair", "start_date": "2027-07-10",
                                     "budget_ids": [base["exp"]["id"], inc28["id"]]})
    for fy_id, name in ((base["fy"]["id"], "FY2027"), (fy28["id"], "FY2028")):
        text = _text(env.auditor.get(f"/api/reports/audit?fiscal_year_id={fy_id}&include_fundraisers=true").content)[1]
        assert "Fundraiser — Summer Fair" in text and "Fair prep" in text and "Fair takings" in text
        assert f"{name} (this report)" in text and "spans more than one Fiscal Year" in text
        assert "$900.00" in text and "$120.00" in text and "$780.00" in text
