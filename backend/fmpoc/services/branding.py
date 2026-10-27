"""2.2.0 (#280): organization branding for generated reports and presentations.

Set by an Administrator (System/About -> Branding): a color palette following Material 3 color roles, a full logo
(report headers, title slides) and an optional small mark (footers), and an optional one-line footer text.

* **Palette.** One of the ready-made palettes (PRESETS; PennyWarden's own is the default), or a custom one: the
  Administrator enters a primary and a secondary color, the browser generates the recommended Material 3 palette from
  them (Google's material-color-utilities), and the Administrator may change any role or chart series color. The
  server stores the resolved colors and validates them: text roles must meet WCAG AA contrast (4.5:1) on the colors
  they are drawn on (the save is refused with the reason); chart series colors that are too similar need a
  confirmation (SIMILAR_SERIES_COLORS). Charts never rely on color alone (BR-079): they keep their labels and legends.
* **Which documents** (Kyle, 2026-10-24): generated reports and presentations - every PDF report, the fundraiser
  report and deck, the Fiscal Year fundraising report and deck. Not checks, cover letters, receipts or envelopes.
* **Where it applies.** Builders are wrapped with `@themed`: the palette for the (only) workspace is loaded into a
  context variable for the build, and `color()`, `rgb()`, `series()` and `logos()` read it. Outside a build the
  PennyWarden palette is used.
* Settings and logos are organization settings (BR-003): in backups, their own partial-restore section
  (`settings.branding`), kept through a reinitialize.
"""
from __future__ import annotations

import contextlib
import contextvars
import functools
import hashlib
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import Warning_, require_confirmations, validation
from ..models import BrandingSettings, Workspace, utcnow

ROLES = ("primary", "on_primary", "primary_container", "on_primary_container",
         "secondary", "on_secondary", "secondary_container", "on_secondary_container",
         "surface", "on_surface", "surface_variant", "on_surface_variant", "outline", "outline_variant")
ROLE_LABELS = {
    "primary": "Primary (headings, title bands)", "on_primary": "Text on Primary",
    "primary_container": "Primary container (tiles, highlighted headers)", "on_primary_container": "Text on Primary container",
    "secondary": "Secondary (accents)", "on_secondary": "Text on Secondary",
    "secondary_container": "Secondary container", "on_secondary_container": "Text on Secondary container",
    "surface": "Surface (alternate table rows)", "on_surface": "Text",
    "surface_variant": "Surface variant (table headers)", "on_surface_variant": "Secondary text",
    "outline": "Outline (table lines)", "outline_variant": "Outline variant (card borders)",
}
SERIES_COUNT = 8
# text role -> the colors it is drawn on (WCAG AA for normal text: 4.5:1)
CONTRAST_PAIRS = (
    ("on_primary", "primary"), ("on_primary_container", "primary_container"),
    ("on_secondary", "secondary"), ("on_secondary_container", "secondary_container"),
    ("on_surface", "surface"), ("on_surface", "surface_variant"), ("on_surface_variant", "surface"),
    ("primary", "white"), ("on_surface", "white"),
)
AA = 4.5
SIMILAR_DELTA_E = 12.0          # CIE76 distance below which two series colors are hard to tell apart
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
FOOTER_MAX = 120
DEFAULT = "pennywarden"

# Ready-made palettes. PennyWarden's is the colors the reports and decks have always used; the others were generated
# with material-color-utilities 0.4.0 from the two source colors shown (Material 3 tonal palettes, light scheme).
PRESETS: dict[str, dict[str, Any]] = {
    "pennywarden": {"label": "PennyWarden", "source_primary": "#1f3a5f", "source_secondary": "#d4a017", "colors": {
        "primary": "#1f3a5f", "on_primary": "#ffffff", "primary_container": "#dfe7f1", "on_primary_container": "#1f3a5f",
        "secondary": "#d4a017", "on_secondary": "#1b1f24", "secondary_container": "#fbefcc",
        "on_secondary_container": "#5c4300", "surface": "#f6f8fa", "on_surface": "#1b1f24", "surface_variant": "#e8ecf1",
        "on_surface_variant": "#4a5560", "outline": "#9aa3ad", "outline_variant": "#c3cad3"},
        "series": ["#1f5fbf", "#d4a017", "#2e8b57", "#8e44ad", "#c0392b", "#16a085", "#7f8c8d", "#e67e22"]},
    "forest": {"label": "Forest", "source_primary": "#2e7d32", "source_secondary": "#c77d1a", "colors": {
        "primary": "#1b6d24", "on_primary": "#ffffff", "primary_container": "#a3f69c", "on_primary_container": "#005312",
        "secondary": "#895200", "on_secondary": "#ffffff", "secondary_container": "#ffdcbc",
        "on_secondary_container": "#683d00", "surface": "#f7fbf1", "on_surface": "#191d17", "surface_variant": "#dee5d8",
        "on_surface_variant": "#424940", "outline": "#72796f", "outline_variant": "#c2c9bd"},
        "series": ["#1b6d24", "#cb801d", "#38656a", "#6dbd6a", "#784700", "#86b3b8", "#747871", "#00460e"]},
    "ocean": {"label": "Ocean", "source_primary": "#00658f", "source_secondary": "#e0a100", "colors": {
        "primary": "#00658f", "on_primary": "#ffffff", "primary_container": "#c7e7ff", "on_primary_container": "#004c6d",
        "secondary": "#7c5800", "on_secondary": "#ffffff", "secondary_container": "#ffdea8",
        "on_secondary_container": "#5e4200", "surface": "#f6fafe", "on_surface": "#181c20", "surface_variant": "#dde3ea",
        "on_surface_variant": "#41484d", "outline": "#71787e", "outline_variant": "#c1c7ce"},
        "series": ["#00658f", "#bd8700", "#63597c", "#6bb3e1", "#6d4d00", "#b1a5cc", "#73777c", "#00405c"]},
    "plum": {"label": "Plum", "source_primary": "#6a3d9a", "source_secondary": "#2a9d8f", "colors": {
        "primary": "#7548a6", "on_primary": "#ffffff", "primary_container": "#efdbff", "on_primary_container": "#5c2f8c",
        "secondary": "#006a60", "on_secondary": "#ffffff", "secondary_container": "#8cf5e4",
        "on_secondary_container": "#005048", "surface": "#fff7ff", "on_surface": "#1e1a20", "surface_variant": "#e9e0eb",
        "on_surface_variant": "#4a454e", "outline": "#7b757e", "outline_variant": "#ccc4cf"},
        "series": ["#7548a6", "#30a193", "#805158", "#c696fa", "#005d54", "#d59ca4", "#7b757c", "#502280"]},
    "ember": {"label": "Ember", "source_primary": "#b3401e", "source_secondary": "#3a5f8a", "colors": {
        "primary": "#a83817", "on_primary": "#ffffff", "primary_container": "#ffdbd1", "on_primary_container": "#872100",
        "secondary": "#3b608b", "on_secondary": "#ffffff", "secondary_container": "#d2e4ff",
        "on_secondary_container": "#214872", "surface": "#fff8f6", "on_surface": "#231917", "surface_variant": "#f5ded8",
        "on_surface_variant": "#53433f", "outline": "#85736e", "outline_variant": "#d8c2bc"},
        "series": ["#a83817", "#6f93c1", "#6c5d2f", "#ff8b6a", "#2e547f", "#bcaa74", "#827470", "#731b00"]},
}
CUSTOM = "custom"


# ------------------------------------------------------------------ color math
def _rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def _lum(h: str) -> float:
    def ch(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _lab(h: str) -> tuple[float, float, float]:
    def lin(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(h))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a: str, b: str) -> float:
    la, lb = _lab(a), _lab(b)
    return sum((p - q) ** 2 for p, q in zip(la, lb)) ** 0.5


def _hex(v: Any, field: str) -> str:
    if not isinstance(v, str) or not HEX.match(v.strip()):
        raise validation("Colors are hex values like #1f3a5f.", field)
    return v.strip().lower()


def contrast_report(colors: dict[str, str]) -> list[dict]:
    """Every text/background pair with its contrast ratio and whether it meets WCAG AA (4.5:1)."""
    out = []
    for fg, bg in CONTRAST_PAIRS:
        b = "#ffffff" if bg == "white" else colors[bg]
        r = contrast(colors[fg], b)
        out.append({"text": fg, "background": bg, "ratio": round(r, 2), "ok": r >= AA})
    return out


def similar_series(series: list[str]) -> list[tuple[int, int]]:
    return [(i, j) for i in range(len(series)) for j in range(i + 1, len(series))
            if delta_e(series[i], series[j]) < SIMILAR_DELTA_E]


# ------------------------------------------------------------------ settings
def _row(db: Session, ws_id: int) -> BrandingSettings | None:
    return db.scalar(select(BrandingSettings).where(BrandingSettings.workspace_id == ws_id))


def palette_of(b: BrandingSettings | None) -> dict:
    """{preset, label, source_primary, source_secondary, colors, series} for a settings row (None = the default)."""
    if b is None or (b.preset != CUSTOM and b.preset not in PRESETS):
        p = PRESETS[DEFAULT]
        return {"preset": DEFAULT, "label": p["label"], "source_primary": p["source_primary"],
                "source_secondary": p["source_secondary"], "colors": dict(p["colors"]), "series": list(p["series"])}
    if b.preset != CUSTOM:
        p = PRESETS[b.preset]
        return {"preset": b.preset, "label": p["label"], "source_primary": p["source_primary"],
                "source_secondary": p["source_secondary"], "colors": dict(p["colors"]), "series": list(p["series"])}
    stored = json.loads(b.colors_json or "{}")
    base = PRESETS[DEFAULT]
    colors = {r: stored.get("colors", {}).get(r, base["colors"][r]) for r in ROLES}
    series = (stored.get("series") or [])[:SERIES_COUNT]
    series += base["series"][len(series):]
    return {"preset": CUSTOM, "label": "Custom", "source_primary": b.source_primary, "source_secondary": b.source_secondary,
            "colors": colors, "series": series}


def view(db: Session, ctx) -> dict:
    b = _row(db, ctx.workspace_id)
    pal = palette_of(b)
    return {**pal, "footer_text": b.footer_text if b else None,
            "logos": {slot: _logo_info(b, slot) for slot in ("full", "mark")},
            "contrast": contrast_report(pal["colors"]),
            "similar_series": [list(p) for p in similar_series(pal["series"])],
            "presets": [{"id": k, "label": v["label"], "source_primary": v["source_primary"],
                         "source_secondary": v["source_secondary"], "colors": v["colors"], "series": v["series"]}
                        for k, v in PRESETS.items()],
            "roles": [{"id": r, "label": ROLE_LABELS[r]} for r in ROLES],
            "contrast_pairs": [list(p) for p in CONTRAST_PAIRS], "minimum_contrast": AA,
            "similar_delta_e": SIMILAR_DELTA_E, "footer_max": FOOTER_MAX,
            "updated_at": b.updated_at.isoformat() if b and b.updated_at else None}


def _logo_info(b: BrandingSettings | None, slot: str) -> dict | None:
    if b is None or getattr(b, f"logo_{slot}_png") is None:
        return None
    return {"sha256": getattr(b, f"logo_{slot}_sha256"), "width": getattr(b, f"logo_{slot}_width"),
            "height": getattr(b, f"logo_{slot}_height")}


def _ensure(db: Session, ws_id: int) -> BrandingSettings:
    b = _row(db, ws_id)
    if b is None:
        b = BrandingSettings(workspace_id=ws_id, preset=DEFAULT)
        db.add(b)
        db.flush()
    return b


def _snapshot(b: BrandingSettings) -> dict:
    pal = palette_of(b)
    return {"preset": pal["preset"], "source_primary": pal["source_primary"], "source_secondary": pal["source_secondary"],
            "colors": pal["colors"], "series": pal["series"], "footer_text": b.footer_text}


def save(db: Session, ctx, data) -> dict:
    """Saves the palette (a preset, or custom colors) and the footer text. Refused when a text color fails WCAG AA;
    similar chart series colors need the SIMILAR_SERIES_COLORS confirmation."""
    preset = (data.preset or "").strip().lower()
    if preset != CUSTOM and preset not in PRESETS:
        raise validation("Choose one of the palettes, or Custom.", "preset")
    footer = (data.footer_text or "").strip() or None
    if footer is not None:
        if len(footer) > FOOTER_MAX:
            raise validation(f"The footer text is at most {FOOTER_MAX} characters.", "footer_text")
        if "\n" in footer or "\r" in footer:
            raise validation("The footer text is one line.", "footer_text")
    stored = None
    sp = ss = None
    if preset == CUSTOM:
        sp, ss = _hex(data.source_primary, "source_primary"), _hex(data.source_secondary, "source_secondary")
        colors_in = data.colors or {}
        missing = [r for r in ROLES if r not in colors_in]
        if missing:
            raise validation(f"Every color role is needed ({', '.join(missing)} missing).", "colors")
        unknown = [k for k in colors_in if k not in ROLES]
        if unknown:
            raise validation(f"Unknown color role: {unknown[0]}.", "colors")
        colors = {r: _hex(colors_in[r], f"colors.{r}") for r in ROLES}
        series = [_hex(c, f"series.{i}") for i, c in enumerate(data.series or [])]
        if len(series) != SERIES_COUNT:
            raise validation(f"A palette has {SERIES_COUNT} chart series colors.", "series")
        stored = {"colors": colors, "series": series}
    else:
        colors, series = PRESETS[preset]["colors"], PRESETS[preset]["series"]
    bad = [p for p in contrast_report(colors) if not p["ok"]]
    if bad:
        p = bad[0]
        raise validation(f"{ROLE_LABELS[p['text']]} on {ROLE_LABELS.get(p['background'], 'white paper')} has a "
                         f"contrast of {p['ratio']}:1; text needs at least {AA}:1 (WCAG AA).", f"colors.{p['text']}")
    close = similar_series(series)
    if close:
        names = ", ".join(f"{i + 1} and {j + 1}" for i, j in close[:4])
        require_confirmations([Warning_("SIMILAR_SERIES_COLORS",
                                        f"Chart series colors {names} are hard to tell apart. Charts keep their labels "
                                        "and legends, so they stay readable; save anyway?", pairs=close)],
                              data.confirmations)
    b = _ensure(db, ctx.workspace_id)
    before = _snapshot(b)
    b.preset, b.source_primary, b.source_secondary = preset, sp, ss
    b.colors_json = json.dumps(stored, sort_keys=True) if stored else None
    b.footer_text = footer
    b.updated_at, b.updated_by_user_id = utcnow(), ctx.user.id
    db.flush()
    after = _snapshot(b)
    if after != before:
        audit.record(db, ctx, "BRANDING_UPDATED", "branding_settings", b.id, before, after)
    return view(db, ctx)


def reset_palette(db: Session, ctx) -> dict:
    """*Reset to the PennyWarden palette* - the logos and footer text stay."""
    b = _row(db, ctx.workspace_id)
    if b is None or b.preset == DEFAULT:
        return view(db, ctx)
    before = _snapshot(b)
    b.preset, b.source_primary, b.source_secondary, b.colors_json = DEFAULT, None, None, None
    b.updated_at, b.updated_by_user_id = utcnow(), ctx.user.id
    db.flush()
    audit.record(db, ctx, "BRANDING_UPDATED", "branding_settings", b.id, before, {**_snapshot(b), "reset": True})
    return view(db, ctx)


MAX_LOGO_BYTES = 2 * 1024 * 1024
SLOTS = ("full", "mark")


def set_logo(db: Session, ctx, slot: str, data: bytes | None) -> dict:
    """Sets (data) or removes (None) the full logo or the small mark: PNG or JPEG by content, at most 2 MB,
    re-encoded as PNG without metadata (BR-100/BR-101). Audited with the image's fingerprint, never the image."""
    if slot not in SLOTS:
        raise validation("Choose the full logo or the small mark.", "slot")
    from .checkprint.service import normalize_logo
    b = _ensure(db, ctx.workspace_id)
    before = {"slot": slot, "sha256": getattr(b, f"logo_{slot}_sha256")}
    if data is None:
        if getattr(b, f"logo_{slot}_png") is None:
            return view(db, ctx)
        for k in ("png", "sha256", "width", "height"):
            setattr(b, f"logo_{slot}_{k}", None)
        action = "BRANDING_LOGO_REMOVED"
    else:
        png, w, h = normalize_logo(data, max_bytes=MAX_LOGO_BYTES)
        setattr(b, f"logo_{slot}_png", png)
        setattr(b, f"logo_{slot}_sha256", hashlib.sha256(png).hexdigest())
        setattr(b, f"logo_{slot}_width", w)
        setattr(b, f"logo_{slot}_height", h)
        action = "BRANDING_LOGO_SET"
    b.updated_at, b.updated_by_user_id = utcnow(), ctx.user.id
    db.flush()
    audit.record(db, ctx, action, "branding_settings", b.id, before,
                 {"slot": slot, "sha256": getattr(b, f"logo_{slot}_sha256"), "width": getattr(b, f"logo_{slot}_width"),
                  "height": getattr(b, f"logo_{slot}_height")})
    return view(db, ctx)


def logo_png(db: Session, ctx, slot: str) -> bytes | None:
    b = _row(db, ctx.workspace_id)
    return getattr(b, f"logo_{slot}_png") if b is not None and slot in SLOTS else None


# ------------------------------------------------------------------ the theme while a document is built
class Theme:
    def __init__(self, pal: dict, footer_text: str | None = None, logo_full: bytes | None = None,
                 logo_mark: bytes | None = None, logo_full_size: tuple[int, int] | None = None,
                 logo_mark_size: tuple[int, int] | None = None):
        self.preset, self.colors, self.series = pal["preset"], pal["colors"], pal["series"]
        self.footer_text, self.logo_full, self.logo_mark = footer_text, logo_full, logo_mark
        self.logo_full_size, self.logo_mark_size = logo_full_size, logo_mark_size

    @property
    def key(self) -> str:
        return json.dumps([self.colors, self.series], sort_keys=True)


_DEFAULT_THEME = Theme(palette_of(None))
_CURRENT: contextvars.ContextVar[Theme] = contextvars.ContextVar("pennywarden_branding", default=_DEFAULT_THEME)


def load(db: Session, ws_id: int | None = None) -> Theme:
    if ws_id is None:
        ws_id = db.scalar(select(Workspace.id).order_by(Workspace.id).limit(1))
    b = _row(db, ws_id) if ws_id is not None else None
    if b is None:
        return _DEFAULT_THEME
    return Theme(palette_of(b), b.footer_text, b.logo_full_png, b.logo_mark_png,
                 (b.logo_full_width, b.logo_full_height) if b.logo_full_png else None,
                 (b.logo_mark_width, b.logo_mark_height) if b.logo_mark_png else None)


def current() -> Theme:
    return _CURRENT.get()


def themed(fn):
    """Decorator for a document builder whose first argument is the database session: the organization's branding
    applies while it runs (and to nothing else)."""
    @functools.wraps(fn)
    def wrapper(db, *a, **kw):
        token = _CURRENT.set(load(db))
        try:
            return fn(db, *a, **kw)
        finally:
            _CURRENT.reset(token)
    return wrapper


@contextlib.contextmanager
def use(db: Session):
    """The organization's branding while a document is built (for builders that don't take the session)."""
    token = _CURRENT.set(load(db))
    try:
        yield _CURRENT.get()
    finally:
        _CURRENT.reset(token)


def color(role: str):
    """A reportlab color for a role, or for "series:<n>"."""
    from reportlab.lib import colors as rl
    return rl.HexColor(hex_of(role))


def hex_of(role: str) -> str:
    t = current()
    if role.startswith("series:"):
        return t.series[int(role.split(":")[1]) % len(t.series)]
    return t.colors[role]


def rgb(role: str):
    """A python-pptx / python-docx RGBColor for a role, or for "series:<n>"."""
    from pptx.dml.color import RGBColor
    return RGBColor.from_string(hex_of(role)[1:].upper())


def series_hex() -> list[str]:
    return list(current().series)
