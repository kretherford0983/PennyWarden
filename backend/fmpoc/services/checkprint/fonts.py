"""2.0.0 (#157): the built-in fonts. Check PDFs never use system fonts: every font is shipped with the app
(fmpoc/fonts, SIL OFL 1.1) and embedded in the PDF, so a check prints identically from any installation. The setup
screen's preview loads the same files, so what the Administrator sees is what prints."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = Path(__file__).resolve().parent.parent.parent / "fonts"

# key -> (label, regular file, bold file)
FONTS: dict[str, tuple[str, str, str]] = {
    "SANS": ("Liberation Sans (Arial-compatible)", "LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
    "SERIF": ("Liberation Serif (Times New Roman-compatible)", "LiberationSerif-Regular.ttf",
              "LiberationSerif-Bold.ttf"),
    "MONO": ("Liberation Mono (Courier New-compatible)", "LiberationMono-Regular.ttf", "LiberationMono-Bold.ttf"),
    "CARLITO": ("Carlito (Calibri-compatible)", "Carlito-Regular.ttf", "Carlito-Bold.ttf"),
}
MIN_SIZE, MAX_SIZE = 6.0, 16.0


def options() -> list[dict]:
    """Font choices plus the metrics the setup preview needs to place text exactly like the PDF (per 1 pt)."""
    return [{"key": k, "label": v[0], "descent": descent(k, 1.0), "descent_bold": descent(k, 1.0, True),
             "cap_height": cap_height(k, 1.0)} for k, v in FONTS.items()]


def file_for(key: str, bold: bool) -> Path:
    label, regular, bold_file = FONTS[key]
    return FONT_DIR / (bold_file if bold else regular)


@lru_cache(maxsize=None)
def ps_name(key: str, bold: bool = False) -> str:
    """Registers the font with ReportLab once and returns its name."""
    name = f"PW-{key}{'-B' if bold else ''}"
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(file_for(key, bold))))
    return name


def width(text: str, key: str, size: float, bold: bool = False) -> float:
    """Width in points."""
    return pdfmetrics.stringWidth(text, ps_name(key, bold), size)


def _face(key: str, bold: bool):
    return pdfmetrics.getFont(ps_name(key, bold)).face


def cap_height(key: str, size: float, bold: bool = False) -> float:
    """Capital-letter height in points (the protective fill sits at half of it)."""
    return _face(key, bold).capHeight / 1000.0 * size


def descent(key: str, size: float, bold: bool = False) -> float:
    """Distance below the baseline in points (positive)."""
    return -_face(key, bold).descent / 1000.0 * size


def ascent(key: str, size: float, bold: bool = False) -> float:
    return _face(key, bold).ascent / 1000.0 * size
