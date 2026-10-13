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


# ------------------------------------------------------------------ #185 build time in local time
@pytest.fixture
def local_zone(monkeypatch):
    import os
    import time

    def use(tz: str):
        monkeypatch.setenv("TZ", tz)
        time.tzset()
    yield use
    monkeypatch.undo()
    time.tzset()


def test_built_at_local_in_the_machines_zone(local_zone):
    from fmpoc import config as app_config
    local_zone("America/Chicago")
    assert app_config.local_time_text("2026-10-10T21:15:03Z") == "2026-10-10 4:15 PM CDT"
    assert app_config.local_time_text("2026-12-01T06:05:00Z") == "2026-12-01 12:05 AM CST"
    local_zone("UTC")
    assert app_config.local_time_text("2026-10-10T21:15:03Z") == "2026-10-10 9:15 PM UTC"
    assert app_config.local_time_text("not a time") is None and app_config.local_time_text(None) is None


def test_version_api_serves_built_at_local(env, monkeypatch, tmp_path, local_zone):
    import json
    from fmpoc import config as app_config
    local_zone("America/Chicago")
    f = tmp_path / "build_info.json"
    monkeypatch.setattr(app_config, "BUILD_INFO_FILE", f)
    f.write_text(json.dumps({"version": "2.0.0", "branch": "test", "run": 7, "built_at": "2026-10-10T21:15:03Z"}))
    b = env.bu.get("/api/system/version").json()["build"]
    assert b["built_at"] == "2026-10-10T21:15:03Z" and b["built_at_local"] == "2026-10-10 4:15 PM CDT"
