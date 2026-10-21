"""2.1.0 (#295): the Fiscal Year fundraising report PDF with 6 or more years of history. The "Year over year by
series" table had fixed 0.95" year columns, so 6 years left its Series column a negative width and the PDF failed."""
from __future__ import annotations

import pytest
from reportlab.lib.units import inch

from reportlab.pdfbase.pdfmetrics import stringWidth

from fmpoc.services import fundraiser_fy_report as fyrep
from fmpoc.services import reports
from fmpoc.services.reports import FRAME_W
from test_v210_fundraiser_series import _report, pdf_text, years  # noqa: F401  (fixture)


@pytest.mark.parametrize("amount", ["$800.00", "$12,345.67", "$122,245.67", "-$123,456.78", "$1,234,567.89"])
@pytest.mark.parametrize("n", [1, 2, 6, 8, 12])
def test_layout_fits_the_frame_and_amounts_do_not_wrap(n, amount):
    W = FRAME_W - 12
    period = list(range(2027 - n + 1, 2028))
    years, w = fyrep.yoy_layout(W, period, [amount])
    assert years == period[-len(years):] and 1 <= len(years) <= 6       # the latest, at most 6
    assert len(w) == len(years) + 2 and abs(sum(w) - W) < 0.01
    assert w[0] >= 1.1 * inch - 0.01
    assert min(w[1:-1]) >= stringWidth(amount, reports._FONT, 7.5) + 8  # cell padding is 4 + 4
    if amount in ("$800.00", "$12,345.67"):
        assert len(years) == min(n, 6)                                     # five-figure amounts: all 6 years


@pytest.fixture
def six_entered(env, years):
    """6 entered years (FY2020-FY2025) on the Golf Outing series, with large amounts: 8 years of history in all."""
    sid = env.bm.get("/api/fundraiser-series").json()[0]["id"]
    for y in range(2020, 2026):
        r = env.bm.post(f"/api/fundraiser-series/{sid}/results", {"fiscal_year_label": f"FY{y}", "net": f"12{y % 100}45.67"})
        assert r.status_code == 201, r.text
    # and a long-named series of one year, entered for the Raffle
    rid = env.bm.post(f"/api/fundraisers/{years['raffle']['id']}/series").json()["series_id"]
    env.bm.patch(f"/api/fundraiser-series/{rid}", {"name": "Annual Spring Community Raffle and Silent Auction Night"})
    assert env.bm.post(f"/api/fundraiser-series/{rid}/results", {"fiscal_year_label": "FY2024", "net": "-1234.56"}).status_code == 201
    return years


@pytest.mark.parametrize("n", ["5", "7", "10", "-1"])     # the dialog's choices; -1 = All available
def test_pdf_with_many_years(env, six_entered, n):
    r = _report(env, six_entered, fmt="pdf", years=n, targeted=True)
    assert r.status_code == 200, r.text
    t = pdf_text(r.content)
    assert "Year over year by series" in t and "$122,545.67" in t and "$122,545.6 7" not in t
    if n != "5":                                       # 8 years of history: the table shows the last 6
        assert "The last 6 years are shown" in t                  # $122,545.67 still fits 6 columns without wrapping
    assert _report(env, six_entered, fmt="pptx", years=n).status_code == 200
