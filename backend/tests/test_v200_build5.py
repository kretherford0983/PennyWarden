"""2.0.0 build 5: test prints carry no page markings and one watermark (#183)."""
from __future__ import annotations

import io
import re

import pytest
from pypdf import PdfReader

from fmpoc.services.checkprint import config, presets, render

from test_v200_checks import _texts, sig_png
from test_v200_voucher import dual_config

RECT = re.compile(rb"([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) re\b")


def _rects(pdf: bytes) -> list[tuple[float, float, float, float]]:
    out = []
    for page in PdfReader(io.BytesIO(pdf)).pages:
        data = page.get_contents().get_data()
        out += [tuple(float(v) for v in m.groups()) for m in RECT.finditer(data)]
    return out


def _has_check_outline(pdf: bytes, cfg) -> bool:
    w, h = cfg.stock.check_width * 72, cfg.stock.check_height * 72
    return any(abs(x) < 0.5 and abs(y) < 0.5 and abs(rw - w) < 0.5 and abs(rh - h) < 0.5 for x, y, rw, rh in _rects(pdf))


def _lay(cfg):
    return render.layout(cfg, render.Content(319930, "10/05/2026", "Sample Supply Company, Inc", "51, INVOICE 48513"))


@pytest.mark.parametrize("preset", ["STANDARD_3UP", "VOUCHER_TOP"])
@pytest.mark.parametrize("feed", ["sheet_top", "last_check", "voucher"])
def test_test_and_alignment_prints_draw_no_outline(preset, feed):
    cfg = config.parse(presets.config_for(preset))
    if cfg.feed(feed) is None:
        pytest.skip("feed not in this preset")
    pl = render.placement_for(cfg, cfg.feed(feed))
    stubs = render.SAMPLE_STUB if cfg.stubs else None
    lay = _lay(cfg)
    assert not _has_check_outline(render.test_pdf(cfg, pl, lay, None, stubs), cfg)
    assert not _has_check_outline(render.test_pdf(cfg, pl, lay, sig_png(), stubs), cfg)
    assert not _has_check_outline(render.alignment_pdf(cfg, pl, lay, stubs), cfg)
    # the calibration page keeps its markings
    assert _has_check_outline(render.calibration_pdf(cfg, pl, stubs), cfg)


def test_check_outline_detector_sees_the_outline():
    cfg = config.parse(presets.config_for("STANDARD_3UP"))
    pl = render.placement_for(cfg, cfg.feed("sheet_top"))
    assert _has_check_outline(render.calibration_pdf(cfg, pl), cfg)


@pytest.mark.parametrize("dual", [False, True])
def test_one_watermark_and_a_small_one_per_signature(dual):
    base = presets.config_for("STANDARD_3UP")
    cfg = config.parse(dual_config(base) if dual else base)
    pl = render.placement_for(cfg, cfg.feed("sheet_top"))
    lay = _lay(cfg)
    boxes = render._sig_boxes(cfg)
    signed = [(x, y) for t, x, y in _texts(render.test_pdf(cfg, pl, lay, sig_png())) if t == "TEST - NOT A CHECK"]
    # one big diagonal plus one per signature box - never two on the same centre
    assert len(signed) == 1 + len(boxes)
    assert len({(round(x, 1), round(y, 1)) for x, y in signed}) == len(signed)
    unsigned = [t for t, *_ in _texts(render.test_pdf(cfg, pl, lay, None)) if t == "TEST - NOT A CHECK"]
    assert len(unsigned) == 1


def test_page_notes_sit_a_quarter_inch_inside():
    cfg = config.parse(presets.config_for("STANDARD_3UP"))
    pl = render.placement_for(cfg, cfg.feed("sheet_top"))
    from fmpoc.services.checkprint import fonts
    for pdf, note in ((render.alignment_pdf(cfg, pl, _lay(cfg)), "ALIGNMENT TEST - NOT A CHECK"),
                      (render.calibration_pdf(cfg, pl), "CALIBRATION PAGE - NOT A CHECK")):
        x, y = next((x, y) for t, x, y in _texts(pdf) if t == note)
        right = x + fonts.width(note, "SANS", 7, True) / 72
        assert right == pytest.approx(cfg.stock.check_width - render.NOTE_INSET, abs=0.01)
        assert y >= render.NOTE_INSET
