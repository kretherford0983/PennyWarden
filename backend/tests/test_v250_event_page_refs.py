"""2.5.0 (#589): in the FY Audit / Close reports an event's transactions point to their detail pages (Page column)
instead of reprinting the attachments; the event's own documents are still printed; the standalone report is
unchanged."""
import io
import re

from pypdf import PdfReader
from test_v162_fundraiser_report import _setup


def _pages(pdf: bytes) -> list[str]:
    return [" ".join((p.extract_text() or "").split()) for p in PdfReader(io.BytesIO(pdf)).pages]


def _tx_page(pages: list[str], tx_id: int) -> int:
    return next(i + 1 for i, t in enumerate(pages) if re.search(rf"Transaction #{tx_id}\b(?! \()", t)
                and "Transaction date" in t)


def test_audit_report_event_lists_pages_instead_of_images(env, base):
    fid = _setup(env, base)
    fy = base["fy"]["id"]
    lines = {x["description"]: x for x in env.ru.get(f"/api/fundraisers/{fid}").json()["lines"]}
    pages = _pages(env.auditor.get(f"/api/reports/audit?fiscal_year_id={fy}&include_fundraisers=true").content)
    text = " ".join(pages)
    start = next(i for i, t in enumerate(pages) if "Fundraiser — Harvest Gala" in t)
    section = " ".join(pages[start:])
    # the receipt is printed once, with its transaction - not again in the event section
    assert text.count("receipt.pdf") == 1 and "receipt.pdf" not in section
    # the event's own document is still printed
    assert "Fundraiser document 1 of 1" in section and "flyer.png" in section
    assert "Page = the page of this report" in section
    for desc in ("Food supplies", "Gala takings"):
        tid = lines[desc]["transaction_id"]
        page = _tx_page(pages, tid)
        assert page < start + 1
        assert re.search(rf"\b{tid} {page} (Income|Expense)\b", section), (desc, tid, page)
    # the event section is now short: one page here
    end = next(i for i, t in enumerate(pages) if "End of fundraisers" in t)
    assert end - start <= 2


def test_close_report_also_uses_page_references(env, base):
    fid = _setup(env, base)
    pages = _pages(env.bm.get(f"/api/reports/fy-close?fiscal_year_id={base['fy']['id']}").content)
    start = next(i for i, t in enumerate(pages) if "Fundraiser — Harvest Gala" in t)
    section = " ".join(pages[start:])
    assert "receipt.pdf" not in section and "flyer.png" in section and "Page = the page" in section
    assert fid


def test_standalone_report_still_prints_attachments(env, base):
    fid = _setup(env, base)
    text = " ".join(_pages(env.auditor.get(f"/api/fundraisers/{fid}/report").content))
    assert "receipt.pdf" in text and "Page = the page" not in text


def test_line_outside_the_report_says_where_it_is(env, base):
    assert env.admin.put("/api/system/modules", {"fundraisers": True}).status_code == 200
    fy28 = env.fy("2028", "2027-07-01", "2028-06-30")
    inc28 = env.budget(fy28["id"], "4000", "Donations", "INCOME", "1000.00")
    exp28 = env.budget(fy28["id"], "1000", "Operations", "EXPENSE", "1000.00")
    leaf28 = {o["label"]: o["id"] for o in env.selectable(fy28["id"], "DEPOSIT")}["4000 Donations"]
    env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "120.00", "description": "Fair prep"}], date="2027-06-20")
    env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": leaf28, "amount": "900.00", "description": "Fair takings"}], date="2027-07-12")
    r = env.bm.post("/api/fundraisers", {"name": "Summer Fair", "start_date": "2027-07-10",
                                         "budget_ids": [base["inc"]["id"], base["exp"]["id"], inc28["id"], exp28["id"]]})
    assert r.status_code == 201, r.text
    pages = _pages(env.auditor.get(f"/api/reports/audit?fiscal_year_id={base['fy']['id']}&include_fundraisers=true").content)
    start = next(i for i, t in enumerate(pages) if "Fundraiser — Summer Fair" in t)
    section = " ".join(pages[start:])
    assert "FY2028 report" in section
