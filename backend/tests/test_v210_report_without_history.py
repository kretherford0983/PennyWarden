"""2.1.0 (#300): the report (PDF, Word) and presentation of one fundraiser can leave out year over year
(history=false), so they cover only this year's fundraiser. On by default; the Fiscal Year report is unchanged."""
from __future__ import annotations

import io

import docx
import pytest
from pptx import Presentation

from test_v210_fundraiser_series import pdf_text, years  # noqa: F401  (fixture)


def docx_text(content: bytes) -> str:
    d = docx.Document(io.BytesIO(content))
    return " ".join([p.text for p in d.paragraphs] + [c.text for t in d.tables for r in t.rows for c in r.cells])


def deck_text(content: bytes) -> str:
    out = []
    for sl in Presentation(io.BytesIO(content)).slides:
        out += [sh.text_frame.text for sh in sl.shapes if sh.has_text_frame]
        out.append(sl.notes_slide.notes_text_frame.text)
    return " ".join(out)


@pytest.fixture
def golf(env, years):
    sid = env.bm.get("/api/fundraiser-series").json()[0]["id"]
    assert env.bm.post(f"/api/fundraiser-series/{sid}/results", {"fiscal_year_label": "FY2025", "net": "600.00"}).status_code == 201
    return years["g27"]["id"]


def get(env, fid, kind, **q):
    params = {k: str(v).lower() for k, v in q.items()}
    path = "presentation" if kind == "pptx" else "summary-report"
    if kind != "pptx":
        params["format"] = kind
    r = env.bu.get(f"/api/fundraisers/{fid}/{path}", params=params)
    assert r.status_code == 200, r.text
    return {"pdf": pdf_text, "docx": docx_text, "pptx": deck_text}[kind](r.content)


@pytest.mark.parametrize("kind", ["pdf", "docx", "pptx"])
def test_history_off_leaves_out_year_over_year_only(env, golf, kind):
    on = get(env, golf, kind)
    off = get(env, golf, kind, history=False)
    assert "Year over year" in on and "FY2025" in on
    assert "Year over year" not in off and "FY2025" not in off and "2025 Golf Outing" not in off
    assert "Net proceeds were up" not in off                     # the year-over-year takeaway
    assert "$1,000.00" in off                                    # this year's figures are unchanged


def test_default_is_on_and_the_choice_is_audited(env, golf):
    assert "Year over year" in get(env, golf, "pdf", history=True)
    get(env, golf, "pdf", history=False)
    get(env, golf, "pptx", history=False)
    ev = env.auditor.get("/api/audit-events?action=REPORT_GENERATED").json()["items"]
    opts = [(e["after"]["report"], e["after"]["options"].get("history")) for e in ev
            if (e.get("after") or {}).get("report") in ("FUNDRAISER_SUMMARY", "FUNDRAISER_PRESENTATION")]
    assert ("FUNDRAISER_SUMMARY", False) in opts and ("FUNDRAISER_PRESENTATION", False) in opts
    assert ("FUNDRAISER_SUMMARY", True) in opts


def test_fiscal_year_report_unchanged(env, golf, years):
    r = env.bu.get("/api/fundraisers/fy-report", params={"fiscal_year_id": years["base"]["fy"]["id"],
                                                          "ids": [golf, years["raffle"]["id"]], "format": "pdf"})
    assert r.status_code == 200 and "Year over year by series" in pdf_text(r.content)
