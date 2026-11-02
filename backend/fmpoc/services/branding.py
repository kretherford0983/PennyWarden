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
* 2.3.0 (#386) **dual branding**: a light and a dark theme (each a ready-made palette - DARK_PRESETS are the dark
  versions - or custom colors, generated in the browser from the same two source colors with the Material 3 dark
  scheme and adjusted), the theme each type of output uses (OUTPUTS; new setups: presentations dark, reports light;
  upgraded installations keep both light), and optional logos for dark backgrounds (off: the light logos are used on
  dark slides too). Word documents always use the light theme (they print on white paper). Both themes pass the same
  guardrails: WCAG AA text contrast against that theme's background, a confirmation for similar chart colors.
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

# 2.3.0 (#386): the dark version of each ready-made palette - generated with material-color-utilities 0.4.0 from the
# same two source colors (Material 3 dark scheme; chart series tones 80/70/80/60/90/60/70/45 for a dark background).
DARK_PRESETS: dict[str, dict[str, Any]] = {
    "pennywarden": {"colors": {
        "primary": "#aec8f4", "on_primary": "#143155", "primary_container": "#2d476d", "on_primary_container": "#d5e3ff",
        "secondary": "#f6be39", "on_secondary": "#402d00", "secondary_container": "#5c4300", "on_secondary_container": "#ffdfa0",
        "surface": "#111318", "on_surface": "#e1e2e9", "surface_variant": "#43474e", "on_surface_variant": "#c4c6cf",
        "outline": "#8e9199", "outline_variant": "#43474e"},
        "series": ["#aec8f4", "#d7a31b", "#dbbde2", "#7892bc", "#ffdfa0", "#a387aa", "#aaabb1", "#526c93"]},
    "forest": {"colors": {
        "primary": "#88d982", "on_primary": "#003909", "primary_container": "#005312", "on_primary_container": "#a3f69c",
        "secondary": "#ffb86a", "on_secondary": "#492900", "secondary_container": "#683d00", "on_secondary_container": "#ffdcbc",
        "surface": "#10140f", "on_surface": "#e0e4db", "surface_variant": "#424940", "on_surface_variant": "#c2c9bd",
        "outline": "#8c9388", "outline_variant": "#424940"},
        "series": ["#88d982", "#ea9a38", "#a0cfd4", "#53a252", "#ffdcbc", "#6b989d", "#a9aca4", "#2a7a2f"]},
    "ocean": {"colors": {
        "primary": "#88cefe", "on_primary": "#00344c", "primary_container": "#004c6d", "on_primary_container": "#c7e7ff",
        "secondary": "#febb2a", "on_secondary": "#422d00", "secondary_container": "#5e4200", "on_secondary_container": "#ffdea8",
        "surface": "#101417", "on_surface": "#dfe3e7", "surface_variant": "#41484d", "on_surface_variant": "#c1c7ce",
        "outline": "#8b9198", "outline_variant": "#41484d"},
        "series": ["#88cefe", "#dfa000", "#cdc0e9", "#4f98c5", "#ffdea8", "#968bb1", "#a8acb0", "#1e719c"]},
    "plum": {"colors": {
        "primary": "#dcb8ff", "on_primary": "#451374", "primary_container": "#5c2f8c", "on_primary_container": "#efdbff",
        "secondary": "#6fd8c8", "on_secondary": "#003731", "secondary_container": "#005048", "on_secondary_container": "#8cf5e4",
        "surface": "#151218", "on_surface": "#e8e0e8", "surface_variant": "#4a454e", "on_surface_variant": "#ccc4cf",
        "outline": "#968e98", "outline_variant": "#4a454e"},
        "series": ["#dcb8ff", "#51bcad", "#f3b7bf", "#ab7cdd", "#8cf5e4", "#b8838a", "#b0a9b1", "#8255b3"]},
    "ember": {"colors": {
        "primary": "#ffb5a0", "on_primary": "#601500", "primary_container": "#872100", "on_primary_container": "#ffdbd1",
        "secondary": "#a5c9fa", "on_secondary": "#00325a", "secondary_container": "#214872", "on_secondary_container": "#d2e4ff",
        "surface": "#1a110f", "on_surface": "#f1dfda", "surface_variant": "#53433f", "on_surface_variant": "#d8c2bc",
        "outline": "#a08c87", "outline_variant": "#53433f"},
        "series": ["#ffb5a0", "#8aaedd", "#d9c58d", "#eb6943", "#d2e4ff", "#a1905c", "#b8a8a4", "#b94422"]},
}

# 2.3.0 (#386): dark theme - the "page" is the dark surface (no white paper), so the white-paper pairs become surface
DARK_CONTRAST_PAIRS = tuple(p for p in CONTRAST_PAIRS if p[1] != "white") + (("primary", "surface"),)
LIGHT, DARK = "LIGHT", "DARK"
OUTPUTS = {"reports": "PDF reports (printed)", "presentations": "Presentations (.pptx)"}
DEFAULT_OUTPUT_THEMES = {"reports": LIGHT, "presentations": DARK}     # new setups (upgrades keep both light: 0065)


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


def contrast_report(colors: dict[str, str], dark: bool = False) -> list[dict]:
    """Every text/background pair with its contrast ratio and whether it meets WCAG AA (4.5:1)."""
    out = []
    for fg, bg in (DARK_CONTRAST_PAIRS if dark else CONTRAST_PAIRS):
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


def dark_palette_of(b: BrandingSettings | None) -> dict:
    """The dark theme's palette: the chosen ready-made one, custom colors, or (nothing chosen) the dark version of the
    light palette - PennyWarden's when the light one is custom and no dark colors were saved with it."""
    def ready(pid: str) -> dict:
        p, d = PRESETS[pid], DARK_PRESETS[pid]
        return {"preset": pid, "label": p["label"], "source_primary": p["source_primary"],
                "source_secondary": p["source_secondary"], "colors": dict(d["colors"]), "series": list(d["series"])}
    if b is None:
        return ready(DEFAULT)
    if b.dark_preset == CUSTOM and b.dark_colors_json:
        stored = json.loads(b.dark_colors_json)
        base = DARK_PRESETS[DEFAULT]
        colors = {r: stored.get("colors", {}).get(r, base["colors"][r]) for r in ROLES}
        series = (stored.get("series") or [])[:SERIES_COUNT]
        series += base["series"][len(series):]
        return {"preset": CUSTOM, "label": "Custom", "source_primary": b.source_primary,
                "source_secondary": b.source_secondary, "colors": colors, "series": series}
    if b.dark_preset in DARK_PRESETS:
        return ready(b.dark_preset)
    return ready(b.preset if b.preset in DARK_PRESETS else DEFAULT)


def output_themes(b: BrandingSettings | None) -> dict[str, str]:
    if b is None:
        return dict(DEFAULT_OUTPUT_THEMES)
    return {"reports": b.theme_reports or LIGHT, "presentations": b.theme_presentations or LIGHT}


def view(db: Session, ctx) -> dict:
    b = _row(db, ctx.workspace_id)
    pal = palette_of(b)
    dk = dark_palette_of(b)
    return {**pal, "footer_text": b.footer_text if b else None,
            "logos": {slot: _logo_info(b, slot) for slot in SLOTS},
            # 2.3.0 (#386)
            "dark": {**dk, "contrast": contrast_report(dk["colors"], dark=True),
                     "similar_series": [list(p) for p in similar_series(dk["series"])]},
            "dark_presets": [{"id": k, "label": PRESETS[k]["label"], "colors": v["colors"], "series": v["series"]}
                             for k, v in DARK_PRESETS.items()],
            "dark_contrast_pairs": [list(p) for p in DARK_CONTRAST_PAIRS],
            "themes": output_themes(b), "outputs": [{"id": k, "label": v} for k, v in OUTPUTS.items()],
            "dark_logos": bool(b.dark_logos) if b else False,
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
    pal, dk = palette_of(b), dark_palette_of(b)
    return {"preset": pal["preset"], "source_primary": pal["source_primary"], "source_secondary": pal["source_secondary"],
            "colors": pal["colors"], "series": pal["series"], "footer_text": b.footer_text,
            "dark_preset": dk["preset"], "dark_colors": dk["colors"], "dark_series": dk["series"],
            "themes": output_themes(b), "dark_logos": bool(b.dark_logos)}


def _custom_colors(colors_in: dict | None, series_in: list | None, prefix: str) -> tuple[dict, list]:
    colors_in = colors_in or {}
    missing = [r for r in ROLES if r not in colors_in]
    if missing:
        raise validation(f"Every color role is needed ({', '.join(missing)} missing).", f"{prefix}colors")
    unknown = [k for k in colors_in if k not in ROLES]
    if unknown:
        raise validation(f"Unknown color role: {unknown[0]}.", f"{prefix}colors")
    colors = {r: _hex(colors_in[r], f"{prefix}colors.{r}") for r in ROLES}
    series = [_hex(c, f"{prefix}series.{i}") for i, c in enumerate(series_in or [])]
    if len(series) != SERIES_COUNT:
        raise validation(f"A palette has {SERIES_COUNT} chart series colors.", f"{prefix}series")
    return colors, series


def _contrast_gate(colors: dict, dark: bool, prefix: str) -> None:
    bad = [p for p in contrast_report(colors, dark) if not p["ok"]]
    if bad:
        p = bad[0]
        where = ROLE_LABELS.get(p["background"], "white paper")
        raise validation(f"{'Dark theme: ' if dark else ''}{ROLE_LABELS[p['text']]} on {where} has a contrast of "
                         f"{p['ratio']}:1; text needs at least {AA}:1 (WCAG AA).", f"{prefix}colors.{p['text']}")


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
        colors, series = _custom_colors(data.colors, data.series, "")
        stored = {"colors": colors, "series": series}
    else:
        colors, series = PRESETS[preset]["colors"], PRESETS[preset]["series"]
    _contrast_gate(colors, False, "")
    # 2.3.0 (#386): the dark theme (None = unchanged), the theme per output type, dark-background logos
    b = _ensure(db, ctx.workspace_id)
    dark_preset = getattr(data, "dark_preset", None)
    dark_stored = None
    if dark_preset is not None:
        dark_preset = dark_preset.strip().lower()
        if dark_preset != CUSTOM and dark_preset not in DARK_PRESETS:
            raise validation("Choose one of the dark palettes, or Custom.", "dark_preset")
        if dark_preset == CUSTOM:
            dcolors, dseries = _custom_colors(data.dark_colors, data.dark_series, "dark_")
            dark_stored = {"colors": dcolors, "series": dseries}
        else:
            dcolors, dseries = DARK_PRESETS[dark_preset]["colors"], DARK_PRESETS[dark_preset]["series"]
    else:
        dk = dark_palette_of(b)
        dcolors, dseries = dk["colors"], dk["series"]
    _contrast_gate(dcolors, True, "dark_")
    themes = dict(output_themes(b))
    for k in OUTPUTS:
        v = (getattr(data, "themes", None) or {}).get(k)
        if v is not None:
            if v not in (LIGHT, DARK):
                raise validation("Choose Light or Dark.", f"themes.{k}")
            themes[k] = v
    unknown = [k for k in (getattr(data, "themes", None) or {}) if k not in OUTPUTS]
    if unknown:
        raise validation(f"Unknown output type: {unknown[0]}.", "themes")
    close = similar_series(series)
    dclose = similar_series(dseries) if dark_preset is not None else []
    if close or dclose:
        def pairs(x):
            return ", ".join(f"{i + 1} and {j + 1}" for i, j in x[:4])
        names = "; ".join(([("light theme " if dclose else "") + pairs(close)] if close else [])
                          + ([f"dark theme {pairs(dclose)}"] if dclose else []))
        require_confirmations([Warning_("SIMILAR_SERIES_COLORS",
                                        f"Chart series colors {names} are hard to tell apart. Charts keep their labels "
                                        "and legends, so they stay readable; save anyway?", pairs=close, dark_pairs=dclose)],
                              data.confirmations)
    before = _snapshot(b)
    b.preset, b.source_primary, b.source_secondary = preset, sp, ss
    b.colors_json = json.dumps(stored, sort_keys=True) if stored else None
    b.footer_text = footer
    if dark_preset is not None:
        b.dark_preset = dark_preset
        b.dark_colors_json = json.dumps(dark_stored, sort_keys=True) if dark_stored else None
    b.theme_reports, b.theme_presentations = themes["reports"], themes["presentations"]
    if getattr(data, "dark_logos", None) is not None:
        b.dark_logos = bool(data.dark_logos)
    b.updated_at, b.updated_by_user_id = utcnow(), ctx.user.id
    db.flush()
    after = _snapshot(b)
    if after != before:
        audit.record(db, ctx, "BRANDING_UPDATED", "branding_settings", b.id, before, after)
    return view(db, ctx)


def reset_palette(db: Session, ctx) -> dict:
    """*Reset to the PennyWarden palette* (light and dark, #386) - the logos, footer text and the theme of each output
    type stay."""
    b = _row(db, ctx.workspace_id)
    if b is None or (b.preset == DEFAULT and b.dark_preset in (None, DEFAULT)):
        return view(db, ctx)
    before = _snapshot(b)
    b.preset, b.source_primary, b.source_secondary, b.colors_json = DEFAULT, None, None, None
    b.dark_preset, b.dark_colors_json = None, None
    b.updated_at, b.updated_by_user_id = utcnow(), ctx.user.id
    db.flush()
    audit.record(db, ctx, "BRANDING_UPDATED", "branding_settings", b.id, before, {**_snapshot(b), "reset": True})
    return view(db, ctx)


MAX_LOGO_BYTES = 2 * 1024 * 1024
SLOTS = ("full", "mark", "dark_full", "dark_mark")     # 2.3.0 (#386): logos for dark backgrounds


def set_logo(db: Session, ctx, slot: str, data: bytes | None) -> dict:
    """Sets (data) or removes (None) the full logo or the small mark: PNG or JPEG by content, at most 2 MB,
    re-encoded as PNG without metadata (BR-100/BR-101). Audited with the image's fingerprint, never the image."""
    if slot not in SLOTS:
        raise validation("Choose the full logo or the small mark (light or dark).", "slot")
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
                 logo_mark_size: tuple[int, int] | None = None, dark: bool = False):
        self.preset, self.colors, self.series = pal["preset"], pal["colors"], pal["series"]
        self.dark = dark                                       # 2.3.0 (#386): drawn on the dark surface
        self.footer_text, self.logo_full, self.logo_mark = footer_text, logo_full, logo_mark
        self.logo_full_size, self.logo_mark_size = logo_full_size, logo_mark_size

    @property
    def key(self) -> str:
        return json.dumps([self.colors, self.series, self.dark], sort_keys=True)

    @property
    def page(self) -> str:
        """The page / slide background: white paper, or the dark surface."""
        return self.colors["surface"] if self.dark else "#ffffff"


_DEFAULT_THEME = Theme(palette_of(None))
_CURRENT: contextvars.ContextVar[Theme] = contextvars.ContextVar("pennywarden_branding", default=_DEFAULT_THEME)


def theme_for(b: BrandingSettings | None, output: str = "reports") -> str:
    """LIGHT or DARK for an output type ("reports", "presentations"; "word": always light)."""
    if output not in OUTPUTS:
        return LIGHT
    return output_themes(b)[output]


def load(db: Session, ws_id: int | None = None, output: str = "reports") -> Theme:
    if ws_id is None:
        ws_id = db.scalar(select(Workspace.id).order_by(Workspace.id).limit(1))
    b = _row(db, ws_id) if ws_id is not None else None
    dark = theme_for(b, output) == DARK
    if b is None:
        return _DEFAULT_THEME if not dark else Theme(dark_palette_of(None), dark=True)

    def logo(slot: str):
        if dark and b.dark_logos and getattr(b, f"logo_dark_{slot}_png") is not None:
            slot = f"dark_{slot}"        # off, or no dark version of this logo: the light one is used
        png = getattr(b, f"logo_{slot}_png")
        return png, ((getattr(b, f"logo_{slot}_width"), getattr(b, f"logo_{slot}_height")) if png else None)
    (full, full_size), (mark, mark_size) = logo("full"), logo("mark")
    return Theme(dark_palette_of(b) if dark else palette_of(b), b.footer_text, full, mark, full_size, mark_size,
                 dark=dark)


def current() -> Theme:
    return _CURRENT.get()


def themed(fn):
    """Decorator for a (PDF report) builder whose first argument is the database session: the organization's branding
    for reports applies while it runs (and to nothing else)."""
    @functools.wraps(fn)
    def wrapper(db, *a, **kw):
        token = _CURRENT.set(load(db, output="reports"))
        try:
            return fn(db, *a, **kw)
        finally:
            _CURRENT.reset(token)
    return wrapper


@contextlib.contextmanager
def use(db: Session, output: str = "reports"):
    """The organization's branding while a document is built (for builders that don't take the session). output:
    "reports" (PDF), "presentations" (.pptx) or "word" (always light) - #386."""
    token = _CURRENT.set(load(db, output=output))
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


def pick(light_hex: str, dark_role: str):
    """2.3.0 (#386): a fixed color of the light design (lines, shading) or, on a dark theme, a palette role - so the light
    reports keep their exact look and dark ones stay readable."""
    from reportlab.lib import colors as rl
    return rl.HexColor(light_hex) if not current().dark else color(dark_role)
