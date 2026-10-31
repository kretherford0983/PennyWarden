"""2.1.0 (#283): the Budget Prep report is now the Budget Review - Budgeted, Actual and Difference in separate cells
per year with an Avg column (layout A: a block per budget), the same figures as #257, and it can be appended to the
Fiscal Year Planning Sheet in one PDF."""
from __future__ import annotations

import csv
import io

from pypdf import PdfReader

from test_v210_budget_prep import AS_OF, hist, rep, row  # noqa: F401  (fixture)


def test_new_path_and_old_alias_give_the_same_figures(env, base, hist):
    q = {"fiscal_year_id": base["fy"]["id"], "as_of": AS_OF}
    new = env.bm.get("/api/reports/budget-review", params=q).json()
    old = env.bm.get("/api/reports/budget-prep", params=q).json()
    strip = lambda r: {k: v for k, v in r.items() if k != "generated_at"}   # noqa: E731
    assert strip(new) == strip(old)
    assert env.bm.get(f"/api/reports/budget-review/projection-choices?fiscal_year_id={base['fy']['id']}").status_code == 200
    ev = env.auditor.get("/api/audit-events?action=REPORT_GENERATED").json()["items"]
    assert [e["after"]["report"] for e in ev if (e.get("after") or {}).get("report", "").startswith("BUDGET_")] == \
        ["BUDGET_REVIEW", "BUDGET_REVIEW"]


def test_average_of_the_prior_years_shown(env, base, hist):
    r = rep(env, base, years=9)
    ops = row(r, base["exp"]["id"])
    av = ops["average"]
    assert (av["budgeted"], av["actual"], av["difference"], av["years"]) == ("900.00", "450.00", "-450.00", 1)
    assert av["direction"] == "under" and av["difference_pct"] == ops["history"][0]["difference_pct"]
    # a budget with no linked earlier year has no average
    assert row(r, hist["trav"]["id"])["average"] is None


def test_csv_has_avg_columns(env, base, hist):
    c = rep(env, base, format="csv")
    rows = list(csv.reader(io.StringIO(c.text)))
    head = rows[0]
    assert "Avg budgeted" in head and "Avg actual" in head and "Avg difference" in head
    ops = next(x for x in rows if x[2] == "1000")
    i = head.index("Avg budgeted")
    assert ops[i:i + 4] == ["900.00", "450.00", "-450.00", "1"]
    assert 'filename="budget-review-' in c.headers["content-disposition"]


def test_pdf_layout_a(env, base, hist):
    r = rep(env, base, format="pdf", projected=True, include_next=True)
    assert 'filename="budget-review-' in r.headers["content-disposition"]
    text = " ".join(" ".join(p.extract_text().split()) for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "Budget Review — FY2027" in text and "Budget Prep" not in text
    for word in ("Budgeted", "Actual", "Difference", "Avg", "Income", "Expense", "next year's budget",
                 "+$10,000.00 (10.0%) vs this year"):
        assert word in text, word


def test_planning_sheet_can_include_the_review(env, base, hist):
    q = {"as_of": AS_OF, "fiscal_year_id": base["fy"]["id"]}
    alone = PdfReader(io.BytesIO(env.bm.get("/api/reports/planning-sheet", params=q).content))
    both = env.bm.get("/api/reports/planning-sheet", params={**q, "include_review": "true"})
    assert both.status_code == 200 and both.headers["content-type"] == "application/pdf"
    pages = PdfReader(io.BytesIO(both.content)).pages
    assert len(pages) > len(alone.pages)
    first = " ".join(p.extract_text() for p in pages[:len(alone.pages)])
    rest = " ".join(p.extract_text() for p in pages[len(alone.pages):])
    assert "Planning" in first and "Budget Review" in rest
    assert float(pages[0].mediabox.width) < float(pages[0].mediabox.height)        # the sheet: portrait
    assert float(pages[-1].mediabox.width) > float(pages[-1].mediabox.height)      # the review: landscape
    ev = env.auditor.get("/api/audit-events?action=REPORT_GENERATED").json()["items"]
    sheet = next(e["after"] for e in ev if (e.get("after") or {}).get("report") == "PLANNING_SHEET"
                 and e["after"].get("include_review"))
    assert sheet["review_pages"] >= 1 and sheet["review_years"] == 1


def test_access(env, base):
    for c in (env.bu, env.ru, env.auditor, env.admin):
        assert c.get(f"/api/reports/budget-review?fiscal_year_id={base['fy']['id']}").status_code == 403
        assert c.get("/api/reports/planning-sheet", params={"include_review": "true"}).status_code == 403
