"""2.5.0 (#590): the Budget proposal as a PDF and a presentation (.pptx), from `budget_proposal.build()`.

The same pieces are appended to the Annual report (period_report_output) when a Budget Manager asks for it:
`pdf_flowables()` after the report's sections, `add_slides()` before its closing slide - so one PDF / one deck reads
"<year> financial review" then "<next year> budget", like the hand-made decks treasurers used before.
"""
from __future__ import annotations

import io
import os
import tempfile
from xml.sax.saxutils import escape

from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle

from . import branding
from . import fundraiser_deck as deck
from .budget_proposal import column_heads, notes_lines, title
from .fundraiser_summary import _band, _table, heading
from .reports import FRAME_W, P, S, _AuditDoc, _Mark, _stamp_and_write
from .reports import money as cm

DASH = "—"


def _m(c: int | None) -> str:
    return DASH if c is None else cm(c)


def _chg(c: int | None, p: str | None) -> str:
    if c is None:
        return DASH
    s = ("+" if c > 0 else "") + cm(c)
    return s + (f" ({'+' if not p.startswith('-') and c > 0 else ''}{p}%)" if p else "")


def file_stem(org: str, rep: dict) -> str:
    from .fundraiser_summary import safe_name
    return safe_name(f"{org}-{rep['fiscal_year']['display_name']}-budget-{rep['state'].lower()}")


def _row_values(rep: dict, x: dict, label: str, *, dropped: bool = False) -> list[str]:
    if not rep["previous_fiscal_year"]:
        return [label, _m(x["proposed"])]
    return [label, _m(x["previous_budget"]), _m(x["previous_actual"]),
            (f"Not in {rep['fiscal_year']['display_name']}" if dropped else _m(x["proposed"])),
            _chg(x["change"], x.get("change_pct"))]


def table_rows(rep: dict, key: str) -> tuple[list[list[str]], list[int]]:
    """The rows of one type (income / expense) with the indices of the bold rows (Total)."""
    sec = rep[key]
    rows: list[list[str]] = []
    for r in sec["rows"]:
        rows.append(_row_values(rep, r, r["label"]))
        for c in r["children"]:
            rows.append(_row_values(rep, c, "    " + c["label"]))
    for r in sec["not_in_year"]:
        rows.append(_row_values(rep, r, ("    " if r["level"] == "sub" else "") + r["label"], dropped=True))
    t = sec["total"]
    rows.append(_row_values(rep, {**t}, "Total"))
    return rows, [len(rows) - 1]


def summary_items(rep: dict) -> list[tuple[str, str, str]]:
    """Tiles: proposed income, expense and net, each against last year's budget."""
    py = rep["previous_fiscal_year"]
    out = []
    for label, x in (("Income", rep["income"]["total"]), ("Expense", rep["expense"]["total"])):
        sub = f"{py['display_name']} budget {cm(x['previous_budget'])}" if py else ""
        out.append((f"{rep['state']} {label.lower()}", cm(x["proposed"]), sub))
    n = rep["net"]
    out.append((f"{rep['state']} net", cm(n["proposed"]),
                f"{py['display_name']} budget {cm(n['previous_budget'])}" if py else "Income minus expense"))
    return out


# ------------------------------------------------------------------ PDF
def pdf_flowables(org: str, rep: dict, doc: _AuditDoc, *, appended: bool = False) -> list:
    W = FRAME_W - 12
    f: list = ([PageBreak()] if appended else []) + [_Mark(doc, title(rep))]
    band = Table([[[P(org, "fs_w"), Paragraph(escape(title(rep)), S["fs_wt"]),
                    P(f"{rep['fiscal_year']['start_date']} – {rep['fiscal_year']['end_date']}", "fs_w")]]], colWidths=[W])
    band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _band()), ("LEFTPADDING", (0, 0), (-1, -1), 12),
                              ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
    f += [band, Spacer(1, 8), *heading("Summary")]
    data = [[P("", "cellb"), P("Income", "fs_rb"), P("Expense", "fs_rb"), P("Net", "fs_rb")]]
    py = rep["previous_fiscal_year"]
    inc, exp, net = rep["income"]["total"], rep["expense"]["total"], rep["net"]
    data.append([P(f"{rep['fiscal_year']['display_name']} {rep['state'].lower()}", "cell"),
                 P(cm(inc["proposed"]), "cellr"), P(cm(exp["proposed"]), "cellr"), P(cm(net["proposed"]), "cellr")])
    if py:
        data.append([P(f"{py['display_name']} budget", "cell"), P(_m(inc["previous_budget"]), "cellr"),
                     P(_m(exp["previous_budget"]), "cellr"), P(_m(net["previous_budget"]), "cellr")])
        data.append([P(f"{py['display_name']} {rep['actual_word']}", "cell"), P(_m(inc["previous_actual"]), "cellr"),
                     P(_m(exp["previous_actual"]), "cellr"), P(_m(net["previous_actual"]), "cellr")])
    f.append(_table(data, [W - 3 * 1.3 * inch] + [1.3 * inch] * 3))
    if rep["commentary"]:
        f += [Spacer(1, 6), *heading("Commentary")]
        f += [P(par, "body") for par in rep["commentary"].split("\n") if par.strip()]
    heads = column_heads(rep)
    n = len(heads) - 1
    col = 1.2 * inch
    cols = [col] * n if n == 1 else [col] * (n - 1) + [1.6 * inch]     # Change: amount and percent on one line
    for key, label in (("income", "Income"), ("expense", "Expense")):
        rows, bold = table_rows(rep, key)
        data = [[P(heads[0], "cellb"), *[P(h, "fs_rb") for h in heads[1:]]]]
        for i, r in enumerate(rows):
            st = "cellb" if i in bold else "cell"
            data.append([P(r[0], st), *[P(v, "cellr") for v in r[1:]]])
        if len(rows) == 1:
            data.insert(1, [P(f"No {label.lower()} budgets.", "cell")] + [P("", "cell")] * n)
        f += [Spacer(1, 8), *heading(f"{label} budgets"),
              _table(data, [W - sum(cols)] + cols, bold_rows=[b + 1 + (1 if len(rows) == 1 else 0) for b in bold])]
    f += [Spacer(1, 8)] + [P(x, "small") for x in notes_lines(rep)]
    return f


def pdf_file(org: str, rep: dict) -> tuple[str, str, int]:
    buf = io.BytesIO()
    doc = _AuditDoc(buf, title=title(rep), author=org)
    doc.build(pdf_flowables(org, rep, doc))
    fd, path = tempfile.mkstemp(prefix="fmpoc-proposal-", suffix=".pdf")
    os.close(fd)
    try:
        pages = _stamp_and_write(buf.getvalue(), doc, path, org)
    except Exception:
        os.unlink(path)
        raise
    return path, file_stem(org, rep) + ".pdf", pages


# ------------------------------------------------------------------ presentation
def add_slides(prs, org: str, rep: dict, *, divider: bool) -> None:
    """The proposal slides: an optional section divider (when appended to the Annual deck), the summary, then the
    Income and Expense tables ("(continued)" slides for long lists)."""
    blank = prs.slide_layouts[6]
    fy = rep["fiscal_year"]["display_name"]
    if divider:
        sl = prs.slides.add_slide(blank)
        deck._text(sl, Inches(0.6), Inches(2.7), Inches(12.1), Inches(1.2), f"{fy} Budget", size=48, bold=True,
                   color=deck.C.BLUE, align=PP_ALIGN.CENTER)
        deck._text(sl, Inches(0.6), Inches(3.9), Inches(12.1), Inches(0.6), rep["state"], size=24,
                   color=deck.C.GREY, align=PP_ALIGN.CENTER)
        deck._notes(sl, [f"The {fy} budget, {rep['state'].lower()}, beside the previous year."])
    # summary tiles
    sl = prs.slides.add_slide(blank)
    deck._title(sl, f"{fy} Budget — Summary", rep["state"])
    items = summary_items(rep)
    w = 12.1 / len(items)
    for i, (k, v, c) in enumerate(items):
        x = Inches(0.6 + i * w)
        card = sl.shapes.add_shape(1, x, Inches(2.0), Inches(w - 0.25), Inches(2.6))
        card.fill.solid()
        card.fill.fore_color.rgb = deck.C.LIGHT
        card.line.color.rgb = deck.C.LINE
        deck._text(sl, x + Inches(0.2), Inches(2.15), Inches(w - 0.6), Inches(0.5), k, size=16, bold=True, color=deck.C.GREY)
        deck._text(sl, x + Inches(0.2), Inches(2.75), Inches(w - 0.6), Inches(0.9), v, size=30, bold=True)
        deck._text(sl, x + Inches(0.2), Inches(3.8), Inches(w - 0.6), Inches(0.6), c, size=14, color=deck.C.GREY)
    deck._notes(sl, ([f"Commentary: {rep['commentary']}"] if rep["commentary"] else []) + notes_lines(rep))
    heads = column_heads(rep)
    n = len(heads) - 1
    cols = [1.85] * n if n == 1 else [1.85] * (n - 1) + [2.45]    # Change: amount and percent on one line
    widths = [12.1 - sum(cols)] + cols
    for key, label in (("income", "Income"), ("expense", "Expense")):
        rows, _bold = table_rows(rep, key)
        if len(rows) == 1:
            rows.insert(0, [f"No {label.lower()} budgets."] + [""] * n)
        for k, part in enumerate(deck._chunks(rows, deck.TABLE_ROWS)):
            sl = prs.slides.add_slide(blank)
            deck._title(sl, f"{fy} Budget — {label}" + (" (continued)" if k else ""), rep["state"])
            deck._table(sl, Inches(0.6), Inches(1.6), Inches(sum(widths)), [heads] + part, widths, set(range(1, n + 1)),
                        bold_rows=[i + 1 for i, r in enumerate(part) if r[0] == "Total"], size=13)
            deck._notes(sl, notes_lines(rep))


def build_pptx(org: str, rep: dict) -> bytes:
    prs = Presentation()
    deck._strip_template_extras(prs)
    prs.slide_width, prs.slide_height = deck.W, deck.H
    blank = prs.slide_layouts[6]
    sl = prs.slides.add_slide(blank)
    deck._mark(sl, Inches(0.6), Inches(0.9), Inches(1.0), Inches(1.3))
    deck._text(sl, Inches(2.0), Inches(0.8), Inches(10.5), Inches(0.6), org, size=24, bold=True)
    deck._text(sl, Inches(2.0), Inches(1.35), Inches(10.5), Inches(0.9), title(rep), size=34, bold=True, color=deck.C.BLUE)
    deck._text(sl, Inches(2.0), Inches(2.25), Inches(10.5), Inches(0.5),
               f"{rep['fiscal_year']['start_date']} – {rep['fiscal_year']['end_date']}", size=18, color=deck.C.GREY)
    deck._notes(sl, ([f"Commentary: {rep['commentary']}"] if rep["commentary"] else []) + notes_lines(rep))
    add_slides(prs, org, rep, divider=False)
    sl = prs.slides.add_slide(blank)
    deck._text(sl, Inches(0.6), Inches(3.0), Inches(12.1), Inches(1.2), "Questions?", size=48, bold=True, align=PP_ALIGN.CENTER)
    deck._text(sl, Inches(0.6), Inches(4.3), Inches(12.1), Inches(0.6), f"{org} · {title(rep)}", size=18,
               color=deck.C.GREY, align=PP_ALIGN.CENTER)
    prs.core_properties.title = title(rep)
    prs.core_properties.author = org
    deck.brand_footers(prs)
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
