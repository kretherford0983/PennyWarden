"""1.7.1 (#59): Audit / Fiscal Year Close report - the fundraisers sit between a "Start of fundraisers" page and an
"End of fundraisers" page that state their page range, like each bank account's transactions (1.6.7)."""
import io
import re

from pypdf import PdfReader

from test_v162_fundraiser_report import _setup
from test_v167_report_account_sections import two_accounts


def texts(content: bytes) -> list[str]:
    return [" ".join((p.extract_text() or "").split()) for p in PdfReader(io.BytesIO(content)).pages]


def frame(pages: list[str]) -> tuple[int, int]:
    starts = [i + 1 for i, t in enumerate(pages) if t.startswith("Start of fundraisers")]
    ends = [i + 1 for i, t in enumerate(pages) if t.startswith("End of fundraisers")]
    assert len(starts) == 1 and len(ends) == 1, (starts, ends)
    return starts[0], ends[0]


def test_fundraisers_are_framed_by_a_start_and_an_end_page(env, base):
    _setup(env, base)                                                        # "Harvest Gala", 2026-09-12
    env.bm.post("/api/fundraisers", {"name": "Spring Raffle", "start_date": "2027-03-01", "end_date": "2027-03-03",
                                     "budget_ids": [base["inc"]["id"]]})
    fy = base["fy"]["id"]
    for url in (f"/api/reports/audit?fiscal_year_id={fy}&include_fundraisers=true&signature_page=true",
                f"/api/reports/fy-close?fiscal_year_id={fy}"):
        pages = texts(env.auditor.get(url).content)
        total = len(pages)
        first, last = frame(pages)
        size = last - first + 1
        start, end = pages[first - 1], pages[last - 1]
        # the start page comes straight after the last transaction page, the end page straight after the last fundraiser page
        assert "Transaction #" in pages[first - 2] and "Fundraiser" not in pages[first - 2].split("·")[0]
        gala = [i + 1 for i, t in enumerate(pages) if t.startswith("Fundraiser — Harvest Gala")]
        raffle = [i + 1 for i, t in enumerate(pages) if t.startswith("Fundraiser — Spring Raffle")]
        assert gala and raffle and first < gala[0] < raffle[0] < last and gala[0] == first + 1   # event-date order
        assert pages[last - 2].split("·")[-1].strip().startswith("Fundraiser: Spring Raffle")   # footer label of the page before
        # both pages state the same range, each naming the other one
        span = f"pages {first} to {last} of {total} ({size} pages"
        assert f"The fundraisers section: {span}" in start and f"The fundraisers section: {span}" in end
        assert f'Its last page is page {last}, headed "End of fundraisers".' in start
        assert f'Its first page is page {first}, headed "Start of fundraisers".' in end
        for want in ("Fundraisers 2", "First fundraiser Harvest Gala — 2026-09-12",
                     "Last fundraiser Spring Raffle — 2027-03-01 to 2027-03-03"):
            assert want in start and want in end, want
        assert "1. Harvest Gala — 2026-09-12" in start and "2. Spring Raffle — 2027-03-01 to 2027-03-03" in start
        assert "No fundraiser follows this page." in end
        # every page in between carries a gap-free "Fundraisers - section page k of n"; no other page does
        for k, pg in enumerate(range(first, last + 1), start=1):
            assert f"Fundraisers - section page {k} of {size}" in pages[pg - 1] and f"Page {pg} of {total}" in pages[pg - 1]
        assert all("section page" not in pages[i] for i in range(total) if not first <= i + 1 <= last)
        # every fundraiser page - and no transaction page - is inside the frame
        outside = " ".join(pages[:first - 1] + pages[last:])
        assert "Fundraiser — Harvest Gala" not in outside and "Fundraiser — Spring Raffle" not in outside
        assert not re.search(r"(^| )Transaction #\d+ ", " ".join(t[:20] for t in pages[first - 1:last]))
        assert 'between a "Start of fundraisers" page and an "End of fundraisers" page' in pages[1]
        if "signature_page" in url:
            assert "undersigned" in pages[last] and last == total - 1        # the signature page follows the end page
        else:
            assert last == total
    ev = env.auditor.get("/api/audit-events?object_type=fiscal_year&sort=id&direction=desc").json()["items"]
    done = next(e for e in ev if e["action"] == "REPORT_GENERATED")
    assert done["after"]["fundraiser_section"] == {"first_page": first, "last_page": last}
    assert "account_sections" not in done["after"]                           # one bank account: no account sections


def test_one_fundraiser_also_gets_both_pages_and_a_cancelled_one_is_marked(env, base):
    fid = _setup(env, base)
    assert env.bm.post(f"/api/fundraisers/{fid}/cancel", {"reason": "Rained off"}).status_code == 200
    pages = texts(env.auditor.get(f"/api/reports/audit?fiscal_year_id={base['fy']['id']}&include_fundraisers=true").content)
    first, last = frame(pages)
    assert "Fundraisers 1 — 1 cancelled" in pages[first - 1] and "1. Harvest Gala — 2026-09-12 — cancelled" in pages[first - 1]
    assert "First fundraiser Harvest Gala" in pages[last - 1] and "Last fundraiser Harvest Gala" in pages[last - 1]


def test_no_frame_without_fundraisers_and_no_option_to_leave_them_out(env, base):
    fy = base["fy"]["id"]
    env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "5.00"}], date="2026-09-01")
    assert env.admin.put("/api/system/modules", {"fundraisers": True}).status_code == 200
    none = " ".join(texts(env.auditor.get(f"/api/reports/audit?fiscal_year_id={fy}&include_fundraisers=true").content))
    assert "Start of fundraisers" not in none and "End of fundraisers" not in none and "section page" not in none
    _setup(env, base)
    # 2.6.0 (#609): the year's events are always in both reports; the old option is ignored
    for url in (f"/api/reports/audit?fiscal_year_id={fy}", f"/api/reports/fy-close?fiscal_year_id={fy}&include_fundraisers=false"):
        kept = " ".join(texts(env.auditor.get(url).content))
        assert "Start of fundraisers" in kept and "End of fundraisers" in kept


def test_account_sections_and_the_fundraisers_section_together(env, base):
    a1, other, _ = two_accounts(env, base)
    _setup(env, base)
    pages = texts(env.auditor.get(f"/api/reports/audit?fiscal_year_id={base['fy']['id']}&include_fundraisers=true").content)
    total = len(pages)
    first, last = frame(pages)
    acct_starts = [i + 1 for i, t in enumerate(pages) if t.startswith("Start of transactions")]
    acct_ends = [i + 1 for i, t in enumerate(pages) if t.startswith("End of transactions")]
    assert len(acct_starts) == len(acct_ends) == 2 and acct_ends[-1] + 1 == first and last == total
    # each account page still says "This account's section", the fundraisers pages say theirs; labels never mix
    assert "This account's section:" in pages[acct_starts[0] - 1] and 'headed "End of transactions" for this account.' in pages[acct_starts[0] - 1]
    assert "The fundraisers section:" in pages[first - 1] and "This account's section" not in pages[first - 1]
    for pg in range(acct_starts[0], acct_ends[-1] + 1):
        assert "section page" in pages[pg - 1] and "Fundraisers - section page" not in pages[pg - 1]
    for pg in range(first, last + 1):
        assert "Fundraisers - section page" in pages[pg - 1]
    ev = env.auditor.get("/api/audit-events?object_type=fiscal_year&sort=id&direction=desc").json()["items"]
    done = next(e for e in ev if e["action"] == "REPORT_GENERATED")
    assert [(s["first_page"], s["last_page"]) for s in done["after"]["account_sections"]] == list(zip(acct_starts, acct_ends))
    assert done["after"]["fundraiser_section"] == {"first_page": first, "last_page": last}
