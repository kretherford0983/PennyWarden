"""Build 11 (#217): a picture (PNG) of a PDF for the on-screen previews in Payments Setup.

Safari shows a PDF in an inline frame blank (letter and envelope previews), so the editors show an image of the very
PDF that prints instead: same layout code, same positions, works in every browser. PDFium (pypdfium2) is imported on
first use; where it can't load (for example an older macOS than the wheel supports) `available()` is False and the
editors fall back to the PDF itself with an "Open preview" link.
"""
from __future__ import annotations

import io
import threading

MAX_PAGES = 3                 # a cover letter is one page, two with a window envelope's address page
MAX_SIDE_PX = 1600            # the longer side of each page (sharp on high-density screens, about 100-250 KB)
GAP_PX = 16                   # space between stacked pages

_lock = threading.Lock()      # PDFium is not thread-safe; previews are small, so one at a time
_pdfium = None
_failed = False


def _load():
    global _pdfium, _failed
    if _pdfium is None and not _failed:
        try:
            import pypdfium2 as pdfium        # noqa: PLC0415 - optional at run time, see the module docstring
            _pdfium = pdfium
        except Exception:                     # pragma: no cover - depends on the platform  # noqa: BLE001
            _failed = True
    return _pdfium


def available() -> bool:
    return _load() is not None


def pdf_to_png(pdf: bytes, max_pages: int = MAX_PAGES, max_side: int = MAX_SIDE_PX) -> tuple[bytes, int]:
    """The first `max_pages` pages of `pdf` drawn as one PNG, stacked top to bottom on a light grey background.
    Returns (png, page count of the PDF). Raises RuntimeError when no renderer is available."""
    pdfium = _load()
    if pdfium is None:
        raise RuntimeError("PDF rendering is not available")
    from PIL import Image                     # noqa: PLC0415

    with _lock:
        doc = pdfium.PdfDocument(pdf)
        try:
            count = len(doc)
            images = []
            for i in range(min(count, max_pages)):
                page = doc[i]
                try:
                    w, h = page.get_size()
                    scale = max_side / max(w, h)
                    images.append(page.render(scale=scale).to_pil().convert("RGB"))
                finally:
                    page.close()
        finally:
            doc.close()
    width = max(im.width for im in images)
    height = sum(im.height for im in images) + GAP_PX * (len(images) - 1)
    sheet = Image.new("RGB", (width, height), (220, 222, 226))
    y = 0
    for im in images:
        sheet.paste(im, ((width - im.width) // 2, y))
        y += im.height + GAP_PX
    out = io.BytesIO()
    sheet.save(out, "PNG", optimize=True)
    return out.getvalue(), count
