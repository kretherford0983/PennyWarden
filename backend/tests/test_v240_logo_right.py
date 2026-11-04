"""2.4.0 polish (#520): Top right - above the letterhead (the text moves down) or beside it (the text stays where it
is) - on donation letters and payment cover letters alike. A setting saved as RIGHT before keeps its look: above on
donation letters, beside on cover letters."""
from __future__ import annotations

import pytest

from test_v200_build6 import img, letter, upload  # noqa: F401  (fixture)
from test_v200_checks import _texts
from test_v240_org_logos import org_logo  # noqa: F401  (fixture)
from test_v210_donations import enable as enable_donations
from test_v210_donations import setup as donation_setup


def _pos(pdf: bytes) -> dict[str, tuple[float, float]]:
    """text -> (x, y) in inches from the top-left corner; the first time a text is printed"""
    out: dict[str, tuple[float, float]] = {}
    for t, x, y in _texts(pdf):
        out.setdefault(t, (x, y))
    return out


def _image_box(pdf: bytes) -> tuple[float, float, float, float]:
    """(left, top, width, height) in inches of page 1's first image - drawn on the canvas (w 0 0 h x y cm) or as a
    flowable (1 0 0 1 x y cm, then w 0 0 h 0 0 cm)."""
    import io
    import re

    from pypdf import PdfReader
    data = PdfReader(io.BytesIO(pdf)).pages[0].get_contents().get_data()
    m = re.search(rb"1 0 0 1 ([-\d.]+) ([-\d.]+) cm\s*q\s*([-\d.]+) 0 0 ([-\d.]+) 0 0 cm\s*/\S+ Do", data)
    if m:
        x, y, w, h = (float(v) / 72 for v in m.groups())
    else:
        m = re.search(rb"([-\d.]+) 0 0 ([-\d.]+) ([-\d.]+) ([-\d.]+) cm\s*/\S+ Do", data)
        w, h, x, y = (float(v) / 72 for v in m.groups())
    return x, 11 - y - h, w, h


def test_cover_letter_top_right_above_moves_the_text_down(env, letter):
    did = letter["id"]
    upload(env.admin, did, img(size=(600, 120)))                                 # 2.5 x 0.5 in
    pdf = lambda pos: env.admin.post(f"/api/checks/documents/{did}/preview",   # noqa: E731
                                     {"config": {**letter["config"], "logo_position": pos, "logo_source": "OWN"}}).content
    above, beside = pdf("RIGHT_ABOVE"), pdf("RIGHT_BESIDE")
    a, b = _pos(above), _pos(beside)
    assert a["Sample Organization"][1] > b["Sample Organization"][1] + 0.4     # pushed below the logo
    left, top, w, h = _image_box(above)
    assert left + w == pytest.approx(7.5 - 6 / 72, abs=0.01)                  # the text's right edge (frame padding)
    assert top + h < a["Sample Organization"][1]
    # a letter saved as RIGHT before #520 was beside the letterhead and stays so
    assert _pos(pdf("RIGHT"))["Sample Organization"] == pytest.approx(b["Sample Organization"], abs=0.01)
    cfg = env.admin.put(f"/api/checks/documents/{did}", {"name": letter["name"], "config": {**letter["config"], "logo_position": "RIGHT"}})
    assert cfg.status_code == 200, cfg.text
    assert cfg.json()["config"]["logo_position"] == "RIGHT_BESIDE"


def test_donation_letter_top_right_beside_keeps_the_text_where_it_is(env, base, org_logo):
    enable_donations(env)
    cfg = donation_setup(env, logo_source="ORG", logo_position="RIGHT")["config"]
    assert cfg["logo_position"] == "RIGHT_ABOVE"                # saved before #520: above, as it printed then
    pdf = lambda pos, src="ORG": env.admin.post("/api/donations/setup/preview",  # noqa: E731
                                                {"config": {**cfg, "logo_position": pos, "logo_source": src}}).content
    none, above, beside = _pos(pdf("LEFT", "NONE")), _pos(pdf("RIGHT_ABOVE")), _pos(pdf("RIGHT_BESIDE"))
    assert above["Acme Org"][1] > none["Acme Org"][1] + 0.4                     # above: pushed down
    assert beside["Acme Org"] == pytest.approx(none["Acme Org"], abs=0.01)      # beside: where it is without a logo
    left, top, w, h = _image_box(pdf("RIGHT_BESIDE"))
    assert left + w == pytest.approx(7.5, abs=0.01) and top < beside["Acme Org"][1]
    # a logo taller than the name and address: the donor's address after the date starts below it
    dates = [y for t, (x, y) in beside.items() if y > top + h]
    assert dates and min(dates) > top + h
