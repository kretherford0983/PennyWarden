"""2.3.0 polish (Kyle, 2026-10-31): the Budget Review PDF keeps every column on one page. Avg and the current year
always print; prior years + Projected + Next year's budget may add up to 6 columns on landscape letter and 9 on
landscape legal. A PDF with more is refused (nothing is generated or audited); prior years are 0-9 (no "all")."""
from __future__ import annotations

import io

from pypdf import PdfReader

AS_OF = "2026-09-30"


def _prior_years(env, n):
    """n Fiscal Years before the base one (FY2027, Jul-Jun), newest first so each is adjacent."""
    for k in range(n):
        y = 2026 - k
        env.fy(str(y), f"{y - 1}-07-01", f"{y}-06-30")


def _get(env, fy_id, **q):
    return env.bm.get("/api/reports/budget-review", params={"fiscal_year_id": fy_id, "as_of": AS_OF, **q})


def test_limits_reported_and_years_capped(env, base):
    fy = base["fy"]["id"]
    r = _get(env, fy, years=3, projected="true")
    assert r.status_code == 200
    assert r.json()["pdf_max_added"] == {"LETTER": 6, "LEGAL": 9} and r.json()["added_columns"] == 1   # no prior years yet
    assert _get(env, fy, years=-1).status_code == 422                     # "all linked years" is gone
    assert _get(env, fy, years=10).status_code == 422
    assert _get(env, fy, years=9).status_code == 200


def test_letter_fits_six_legal_nine(env, base):
    fy = base["fy"]["id"]
    _prior_years(env, 8)
    ok = _get(env, fy, years=5, projected="true", format="pdf")           # 5 + 1 = 6: one page wide
    assert ok.status_code == 200
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(ok.content)).pages)
    assert "Columns 1 of" not in text
    before = len(env.auditor.get("/api/audit-events?action=REPORT_GENERATED").json()["items"])
    r = _get(env, fy, years=6, projected="true", format="pdf")            # 7 on letter: refused
    assert r.status_code == 422 and "fits 6 added columns on letter" in r.text and "legal" in r.text
    assert len(env.auditor.get("/api/audit-events?action=REPORT_GENERATED").json()["items"]) == before
    assert _get(env, fy, years=6, projected="true").status_code == 200    # the screen shows them
    assert _get(env, fy, years=6, projected="true", format="csv").status_code == 200
    legal = _get(env, fy, years=8, projected="true", format="pdf", paper="LEGAL")     # 9 on legal
    assert legal.status_code == 200
    page = PdfReader(io.BytesIO(legal.content)).pages[0]
    assert round(float(page.mediabox.width)) == 1008 and round(float(page.mediabox.height)) == 612   # 14 x 8.5 in
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(legal.content)).pages)
    assert "Columns 1 of" not in text
    ev = env.auditor.get("/api/audit-events?action=REPORT_GENERATED").json()["items"][0]["after"]
    assert ev["paper"] == "LEGAL"
    assert _get(env, fy, years=8, projected="true", include_next="true", format="pdf",
                paper="LEGAL").status_code == 422                         # 10 on legal
    assert _get(env, fy, years=3, format="pdf", paper="A4").status_code == 422
