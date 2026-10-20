"""2.1.0 (#276): the fundraiser presentation - the stakeholder report (#275) as a 16:9 PowerPoint deck (.pptx) with
native, editable charts and speaker notes. .pptx is the one format PowerPoint, Google Slides and Keynote all open.

Compatibility rules (so the deck looks the same everywhere): Arial only, no embedded fonts, no pictures, SmartArt,
macros, animations, transitions, media or external links - plain shapes, text boxes, tables and native charts.
Every chart has data labels, and the legend / category names carry the amounts, so values never depend on colour.
User text (fundraiser, categories, buckets, contributors, notes) goes in as plain text runs.

The figures come from `fundraiser_summary.summary()`, so they match the report to the cent.
"""
from __future__ import annotations

import datetime as dt
import io
import math

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_AXIS_CROSSES, XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

from .fundraiser_summary import _p, _us, event_dates, money, safe_name

FONT = "Arial"
NAVY = RGBColor(0x1F, 0x3A, 0x5F)
BLUE = RGBColor(0x1F, 0x5F, 0xBF)
GOLD = RGBColor(0xD4, 0xA0, 0x17)
GOLD_DARK = RGBColor(0xA6, 0x7C, 0x0E)
GREY = RGBColor(0x5B, 0x65, 0x73)
LIGHT = RGBColor(0xEE, 0xF3, 0xF9)
RED = RGBColor(0xB3, 0x26, 0x1E)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
SERIES = [RGBColor(0x1F, 0x5F, 0xBF), RGBColor(0xD4, 0xA0, 0x17), RGBColor(0x2E, 0x8B, 0x57), RGBColor(0x8E, 0x44, 0xAD),
          RGBColor(0xC0, 0x39, 0x2B), RGBColor(0x16, 0xA0, 0x85), RGBColor(0x7F, 0x8C, 0x8D), RGBColor(0xE6, 0x7E, 0x22)]
W, H = Emu(12192000), Emu(6858000)   # 13.333 x 7.5 in (16:9)
TOP_N = 10
BULLETS_PER_SLIDE = 5
TABLE_ROWS = 12


def _f(x: str) -> float:
    return float(x)


def _text(slide, x, y, w, h, text, size=18, bold=False, color=NAVY, align=None, wrap=True):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = wrap
    lines = text if isinstance(text, list) else [text]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        if align:
            p.alignment = align
        r = p.add_run()
        r.text = line
        r.font.name, r.font.size, r.font.bold = FONT, Pt(size), bold
        r.font.color.rgb = color
    return box


def _title(slide, text, sub=None):
    _text(slide, Inches(0.6), Inches(0.35), Inches(12.1), Inches(0.8), text, size=30, bold=True)
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(1.12), Inches(1.2), Inches(0.06))
    bar.fill.solid()
    bar.fill.fore_color.rgb = GOLD
    bar.line.fill.background()
    if sub:
        _text(slide, Inches(0.6), Inches(1.25), Inches(12.1), Inches(0.5), sub, size=14, color=GREY)


def _notes(slide, lines: list[str]):
    slide.notes_slide.notes_text_frame.text = "\n".join(lines)


def _coin(slide, x, y, d):
    """The PennyWarden gold coin, drawn with plain shapes (no picture)."""
    outer = slide.shapes.add_shape(MSO_SHAPE.OVAL, x, y, d, d)
    outer.fill.solid()
    outer.fill.fore_color.rgb = GOLD
    outer.line.color.rgb = GOLD_DARK
    inner = slide.shapes.add_shape(MSO_SHAPE.OVAL, x + int(d * 0.16), y + int(d * 0.16), int(d * 0.68), int(d * 0.68))
    inner.fill.background()
    inner.line.color.rgb = GOLD_DARK
    inner.line.width = Pt(2)


def _nice_step(top: float) -> float:
    """A round axis step giving about 4-5 gridlines (Kyle, 2026-10-20: long axis amounts ran into each other)."""
    if top <= 0:
        return 1
    raw = top / 4
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _style_chart(chart, legend=True, legend_pos=XL_LEGEND_POSITION.BOTTOM):
    chart.font.name = FONT
    chart.font.size = Pt(12)
    chart.has_title = False          # the slide title says what it is
    if chart.chart_type != XL_CHART_TYPE.DOUGHNUT:
        # whole dollars on the value axis, with a round step, so the labels never overlap (the data labels keep cents)
        va = chart.value_axis
        va.tick_labels.number_format = '"$"#,##0'
        va.tick_labels.number_format_is_linked = False
        va.tick_labels.font.size = Pt(11)
        vals = [v for p in chart.plots for s_ in p.series for v in s_.values if v is not None]
        if vals:
            top = max(max(vals), 0)
            low = min(min(vals), 0)
            step = _nice_step(max(top - low, 1))
            va.major_unit = step
            va.maximum_scale = math.ceil(top * 1.1 / step) * step if top > 0 else 0
            va.minimum_scale = math.floor(low / step) * step if low < 0 else 0
    if chart.chart_type in (XL_CHART_TYPE.BAR_CLUSTERED,):
        chart.category_axis.reverse_order = True   # first category at the top, as in the tables
        chart.category_axis.crosses = XL_AXIS_CROSSES.MAXIMUM   # ... and the value axis stays at the bottom
    chart.has_legend = legend
    if legend:
        chart.legend.position = legend_pos
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(12)


def _labels(plot, fmt='"$"#,##0.00', pos=None, size=11):
    plot.has_data_labels = True
    dl = plot.data_labels
    dl.number_format = fmt
    dl.number_format_is_linked = False
    dl.font.size = Pt(size)
    dl.font.name = FONT
    if pos is not None:
        dl.position = pos


def _table(slide, x, y, w, rows: list[list[str]], widths: list[float], right: set[int], bold_rows=(), size=12):
    shape = slide.shapes.add_table(len(rows), len(rows[0]), x, y, w, Inches(0.36) * len(rows))
    t = shape.table
    for i, wd in enumerate(widths):
        t.columns[i].width = Inches(wd)
    for r, vals in enumerate(rows):
        for c, v in enumerate(vals):
            cell = t.cell(r, c)
            cell.text = ""
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.RIGHT if c in right else PP_ALIGN.LEFT
            run = p.add_run()
            run.text = v
            run.font.name, run.font.size = FONT, Pt(size)
            run.font.bold = r == 0 or r in bold_rows
            run.font.color.rgb = WHITE if r == 0 else RGBColor(0x1B, 0x1F, 0x24)
            cell.fill.solid()
            cell.fill.fore_color.rgb = NAVY if r == 0 else (LIGHT if r in bold_rows else WHITE)
    return t


def build(s: dict) -> bytes:
    prs = Presentation()
    _strip_template_extras(prs)
    prs.slide_width, prs.slide_height = W, H
    blank = prs.slide_layouts[6]
    t, st = s["totals"], s["status"]
    groups, other = s["groups"], s["other"]
    names = s["options"]["names"]
    generated = _us(s["generated_at"])

    # 1. title
    sl = prs.slides.add_slide(blank)
    band = sl.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, W, Inches(0.5))
    band.fill.solid()
    band.fill.fore_color.rgb = NAVY
    band.line.fill.background()
    _coin(sl, Inches(0.8), Inches(1.6), Inches(1.3))
    _text(sl, Inches(2.4), Inches(1.45), Inches(10), Inches(0.7), s["organization"], size=28, bold=True)
    _text(sl, Inches(2.4), Inches(2.2), Inches(10), Inches(1.2), s["fundraiser"], size=44, bold=True, color=BLUE)
    _text(sl, Inches(2.4), Inches(3.5), Inches(10), Inches(0.6), "Financial & Proceeds results", size=22, color=GREY)
    _text(sl, Inches(2.4), Inches(4.1), Inches(10), Inches(0.6), f"{event_dates(s)}  ·  {st['text']}", size=18, color=GREY)
    notes = [f"{s['fundraiser']} — {s['organization']}", f"Event: {event_dates(s)}. Status: {st['text']}.",
             f"Generated {generated} by PennyWarden; the figures match the fundraiser's stakeholder report."]
    if st["code"] == "CANCELLED":
        warn = sl.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(2.4), Inches(5.0), Inches(10), Inches(0.8))
        warn.fill.solid()
        warn.fill.fore_color.rgb = RGBColor(0xFD, 0xE4, 0xE2)
        warn.line.color.rgb = RED
        tf = warn.text_frame
        tf.word_wrap = True
        r = tf.paragraphs[0].add_run()
        r.text = f"Cancelled: {st['cancel_reason'] or 'no reason given'}. The figures are what was received and spent."
        r.font.name, r.font.size, r.font.bold = FONT, Pt(16), True
        r.font.color.rgb = RED
        notes.append(f"This fundraiser was cancelled: {st['cancel_reason'] or 'no reason given'}.")
    _notes(sl, notes)

    # 2. executive highlights
    sl = prs.slides.add_slide(blank)
    _title(sl, "Executive highlights")
    for i, (k, v, cap) in enumerate((("Net revenue", t["net_revenue"], "All income counted for the fundraiser"),
                                     ("Expenses", t["expenses"], "Fundraiser expenses"),
                                     ("Net proceeds", t["net_proceeds"], f"Net margin {_p(t['net_margin'])}"))):
        x = Inches(0.6 + i * 4.1)
        card = sl.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, Inches(2.0), Inches(3.8), Inches(2.6))
        card.fill.solid()
        card.fill.fore_color.rgb = LIGHT
        card.line.color.rgb = RGBColor(0xC3, 0xCA, 0xD3)
        _text(sl, x + Inches(0.3), Inches(2.2), Inches(3.3), Inches(0.5), k, size=18, bold=True, color=GREY)
        _text(sl, x + Inches(0.3), Inches(2.9), Inches(3.3), Inches(0.9), money(v), size=36, bold=True,
              color=BLUE if i == 2 else NAVY)
        _text(sl, x + Inches(0.3), Inches(3.9), Inches(3.3), Inches(0.5), cap, size=14, color=GREY)
    _notes(sl, [f"Net revenue {money(t['net_revenue'])} (gross deposits {money(t['gross_deposits'])} less cash float "
                f"returned {money(t['cash_float_returned'])}).",
                f"Expenses {money(t['expenses'])} (cash float taken out, {money(t['cash_float_out'])}, is not an expense).",
                f"Net proceeds {money(t['net_proceeds'])} = net revenue − expenses.",
                f"Net margin = net proceeds ÷ net revenue = {_p(t['net_margin'])}.",
                f"ROI = net proceeds ÷ expenses = {t['roi'] if t['roi'] is not None else 'n/a (no expenses)'}."])

    # 3. from revenue to proceeds
    sl = prs.slides.add_slide(blank)
    _title(sl, "From revenue to proceeds")
    cd = CategoryChartData(number_format='"$"#,##0.00')
    cd.categories = [f"Net revenue {money(t['net_revenue'])}", f"Expenses {money(t['expenses'])}",
                     f"Net proceeds {money(t['net_proceeds'])}"]
    cd.add_series("Amount", (_f(t["net_revenue"]), _f(t["expenses"]), _f(t["net_proceeds"])))
    ch = sl.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1.2), Inches(1.7), Inches(10.9), Inches(4.9), cd).chart
    _style_chart(ch, legend=False)
    _labels(ch.plots[0], pos=XL_LABEL_POSITION.OUTSIDE_END, size=14)
    for i, pt in enumerate(ch.plots[0].series[0].points):
        pt.format.fill.solid()
        pt.format.fill.fore_color.rgb = (BLUE, GOLD, RGBColor(0x2E, 0x8B, 0x57))[i]
    if t["cash_float_returned"] != "0.00" or t["cash_float_out"] != "0.00":
        _text(sl, Inches(1.2), Inches(6.65), Inches(11), Inches(0.5),
              f"Cash float: {money(t['cash_float_out'])} taken out and {money(t['cash_float_returned'])} returned — "
              "not counted as income or expense.", size=13, color=GREY)
    _notes(sl, [f"Gross deposits {money(t['gross_deposits'])}; less cash float returned {money(t['cash_float_returned'])} "
                f"= net revenue {money(t['net_revenue'])}.", f"Less expenses {money(t['expenses'])} = net proceeds "
                f"{money(t['net_proceeds'])}."] + [f"{y['fiscal_year']}: revenue {money(y['income'])}, expenses "
                                                   f"{money(y['expense'])}, net {money(y['net'])}." for y in s["per_fiscal_year"]])

    # year over year (#277 feedback): only when earlier years of the series are known
    if s.get("year_over_year"):
        from .fundraiser_summary import YOY_HEAD, yoy_rows, yoy_change
        yy = s["year_over_year"]
        sl = prs.slides.add_slide(blank)
        _title(sl, "Year over year", "Each year this fundraiser was held")
        cd = CategoryChartData(number_format='"$"#,##0.00')
        cd.categories = [str(r["year"]) for r in yy]
        cd.add_series("Net revenue", [float(r["net_revenue"]) if r["net_revenue"] is not None else None for r in yy])
        cd.add_series("Expenses", [float(r["expenses"]) if r["expenses"] is not None else None for r in yy])
        cd.add_series("Net proceeds", [float(r["net_proceeds"]) for r in yy])
        ch = sl.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.5), Inches(1.6), Inches(7.2), Inches(5.6), cd).chart
        _style_chart(ch)
        _labels(ch.plots[0], size=9)
        for i, ser in enumerate(ch.plots[0].series):
            ser.format.fill.solid()
            ser.format.fill.fore_color.rgb = (BLUE, GOLD, RGBColor(0x2E, 0x8B, 0x57))[i]
        rows = [["Year", "Net proceeds", "vs year before"]] + [[str(r["year"]) + ("" if r["source"] == "Recorded" else " (Entered)"),
                                                               money(r["net_proceeds"]), yoy_change(r)] for r in yy[-TABLE_ROWS:]]
        _table(sl, Inches(7.9), Inches(1.7), Inches(5.0), rows, [1.4, 1.5, 2.1], {1}, bold_rows=[len(rows) - 1], size=11)
        _notes(sl, ["Year over year for this fundraiser's series (linked with “Continues from”); Entered = a year before "
                    "PennyWarden entered by hand, which may have only the net amount.", " | ".join(YOY_HEAD)]
               + [" | ".join(r) for r in yoy_rows(s)])

    if s["has_buckets"]:
        rev = [(g["name"], g["income"], g["income_pct"]) for g in groups if g["income"] != "0.00"]
        if other["income"] != "0.00":
            rev.append((other["name"], other["income"], other["income_pct"]))
        # 4. revenue by category (doughnut)
        if rev:
            sl = prs.slides.add_slide(blank)
            _title(sl, "Revenue by category")
            cd = CategoryChartData(number_format='"$"#,##0.00')
            cd.categories = [f"{n} — {money(v)} ({_p(p)})" for n, v, p in rev]
            cd.add_series("Revenue", [_f(v) for _n, v, _p_ in rev])
            ch = sl.shapes.add_chart(XL_CHART_TYPE.DOUGHNUT, Inches(0.8), Inches(1.6), Inches(11.7), Inches(5.6), cd).chart
            _style_chart(ch, legend_pos=XL_LEGEND_POSITION.RIGHT)
            _labels(ch.plots[0], fmt="0.0%", size=12)
            ch.plots[0].data_labels.show_percentage = True
            ch.plots[0].data_labels.show_value = False
            for i, pt in enumerate(ch.plots[0].series[0].points):
                pt.format.fill.solid()
                pt.format.fill.fore_color.rgb = SERIES[i % len(SERIES)]
            _notes(sl, [f"Share of net revenue ({money(t['net_revenue'])}) by category or bucket:"]
                   + [f"{n}: {money(v)} = {_p(p)}" for n, v, p in rev])
            # 5. category detail (table)
            rows: list[tuple[list[str], bool]] = []
            for g in groups:
                if g["income"] == "0.00":
                    continue
                rows.append(([g["name"], str(g["income_lines"]), money(g["income"]), _p(g["income_pct"])], True))
                if g["kind"] == "category":
                    rows += [([f"    {b['name']}", str(len(b["income_lines"])), money(b["income"]), _p(b["income_pct"])], False)
                             for b in g["buckets"] if b["income"] != "0.00"]
            if other["income"] != "0.00":
                rows.append(([other["name"], str(len(other["income_lines"])), money(other["income"]), _p(other["income_pct"])], False))
            rows.append((["Total net revenue", "", money(t["net_revenue"]), "100.0%"], True))
            head = ["Category / bucket", "Lines", "Subtotal", "% of revenue"]
            for k, part in enumerate(_chunks(rows, TABLE_ROWS)):
                sl = prs.slides.add_slide(blank)
                _title(sl, "Category detail" + (" (continued)" if k else ""))
                _table(sl, Inches(0.8), Inches(1.7), Inches(11.7), [head] + [r for r, _b in part], [6.2, 1.5, 2.2, 1.8],
                       {1, 2, 3}, bold_rows=[i + 1 for i, (_r, b) in enumerate(part) if b])
                _notes(sl, ["Lines = income lines assigned to each category or bucket (a line split across buckets counts in each).",
                            "% of revenue = subtotal ÷ net revenue."])
        # 6. net by category / bucket (chart + table)
        sl = prs.slides.add_slide(blank)
        _title(sl, "Net by category / bucket")
        items = [(g["name"], g["income"], g["expense"], g["net"]) for g in groups]
        if other["income"] != "0.00" or other["expense"] != "0.00":
            items.append((other["name"], other["income"], other["expense"], other["net"]))
        cd = CategoryChartData(number_format='"$"#,##0.00')
        cd.categories = [n for n, *_ in items]
        cd.add_series("Income", [_f(i) for _n, i, _e, _x in items])
        cd.add_series("Expenses", [_f(e) for _n, _i, e, _x in items])
        cd.add_series("Net", [_f(x) for _n, _i, _e, x in items])
        ch = sl.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.5), Inches(1.6), Inches(7.4), Inches(5.6), cd).chart
        _style_chart(ch)
        _labels(ch.plots[0], size=10)
        for i, ser in enumerate(ch.plots[0].series):
            ser.format.fill.solid()
            ser.format.fill.fore_color.rgb = (BLUE, GOLD, RGBColor(0x2E, 0x8B, 0x57))[i]
        rows = [["Category / bucket", "Income", "Expenses", "Net"]] + [[n, money(i), money(e), money(x)] for n, i, e, x in items[:TABLE_ROWS]]
        rows.append(["Total", money(t["net_revenue"]), money(t["expenses"]), money(t["net_proceeds"])])
        _table(sl, Inches(8.1), Inches(1.7), Inches(4.9), rows, [1.9, 1.0, 1.0, 1.0], {1, 2, 3}, bold_rows=[len(rows) - 1], size=10)
        _notes(sl, ["Net = income − expenses for each category or bucket (a bucket can hold both)."]
               + [f"{n}: income {money(i)}, expenses {money(e)}, net {money(x)}" for n, i, e, x in items])

    # 7. revenue over time (line)
    cum = s["cumulative"]
    if len(cum) >= 2:
        sl = prs.slides.add_slide(blank)
        _title(sl, "Revenue over time", "Cumulative by transaction date")
        cd = CategoryChartData(number_format='"$"#,##0.00')
        cd.categories = [_us(c["date"]) for c in cum]
        cd.add_series("Cumulative income", [_f(c["income"]) for c in cum])
        cd.add_series("Cumulative net", [_f(c["net"]) for c in cum])
        ch = sl.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Inches(0.8), Inches(1.8), Inches(11.7), Inches(5.3), cd).chart
        _style_chart(ch)
        _labels(ch.plots[0], pos=XL_LABEL_POSITION.ABOVE, size=10)
        for i, ser in enumerate(ch.plots[0].series):
            ser.format.line.color.rgb = (BLUE, RGBColor(0x2E, 0x8B, 0x57))[i]
            ser.format.line.width = Pt(2.5)
            ser.smooth = False
        _notes(sl, [f"Cumulative income and net by transaction date, from {_us(cum[0]['date'])} to {_us(cum[-1]['date'])}.",
                    f"Final: income {money(cum[-1]['income'])}, net {money(cum[-1]['net'])} (the headline figures)."])

    # 8. top contributors (itemized and names on, buckets only)
    if s["has_buckets"] and s["options"]["itemized"] and names:
        for g in groups + [{"name": other["name"], "kind": "other", "buckets": [{"income_lines": other["income_lines"]}]}]:
            agg: dict[str, float] = {}
            for b in g["buckets"]:
                for x in b["income_lines"]:
                    agg[x["who"]] = agg.get(x["who"], 0) + _f(x["amount"])
            if not agg:
                continue
            top = sorted(agg.items(), key=lambda kv: (-kv[1], kv[0]))
            sl = prs.slides.add_slide(blank)
            _title(sl, f"Top contributors — {g['name']}")
            rows = [["Contributor", "Amount"]] + [[k, money(f"{v:.2f}")] for k, v in top[:TOP_N]]
            _table(sl, Inches(1.5), Inches(1.7), Inches(10.3), rows, [7.3, 3.0], {1})
            more = len(top) - TOP_N
            if more > 0:
                _text(sl, Inches(1.5), Inches(1.8) + Inches(0.36) * (TOP_N + 1), Inches(10), Inches(0.5),
                      f"and {more} more", size=14, color=GREY)
            _notes(sl, [f"Largest contributors to {g['name']} by total amount ({len(top)} in all)."]
                   + [f"{k}: {money(f'{v:.2f}')}" for k, v in top])

    # 9. expenses (bar chart + table with Charge / Less)
    if s["has_buckets"] and t["expenses"] != "0.00":
        sl = prs.slides.add_slide(blank)
        _title(sl, "Expenses", f"Total {money(t['expenses'])} (net of credits)")
        items = []
        for g in groups:
            for b in g["buckets"]:
                if b["expense"] != "0.00":
                    items.append((b["name"] if g["kind"] == "bucket" else f"{g['name']} — {b['name']}", b["expense"], b["expense_pct"]))
        if other["expense"] != "0.00":
            items.append((other["name"], other["expense"], other["expense_pct"]))
        cd = CategoryChartData(number_format='"$"#,##0.00')
        cd.categories = [f"{n} ({_p(p)})" for n, _v, p in items]
        cd.add_series("Expenses", [_f(v) for _n, v, _p_ in items])
        ch = sl.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(0.5), Inches(1.7), Inches(6.8), Inches(5.5), cd).chart
        _style_chart(ch, legend=False)
        _labels(ch.plots[0], pos=XL_LABEL_POSITION.OUTSIDE_END, size=11)
        ch.plots[0].series[0].format.fill.solid()
        ch.plots[0].series[0].format.fill.fore_color.rgb = GOLD
        rows = [["Line", "Amount"]]
        lines = [x for g in groups for b in g["buckets"] for x in b["expense_lines"]] + other["expense_lines"]
        for x in lines:
            if x.get("less"):
                rows += [[f"{x['who']} — charge", money(x["charge"])], [f"Less: {x['less_description'] or ''}", f"-{money(x['less'])}"],
                         ["Net", money(x["amount"])]]
            else:
                rows.append([x["who"], money(x["amount"])])
        shown = rows[:TABLE_ROWS + 1]
        _table(sl, Inches(7.6), Inches(1.7), Inches(5.3), shown, [3.8, 1.5], {1}, size=10)
        if len(rows) > len(shown):
            _text(sl, Inches(7.6), Inches(1.8) + Inches(0.36) * len(shown), Inches(5.3), Inches(0.4),
                  f"and {len(rows) - len(shown)} more rows — see the report", size=11, color=GREY)
        _notes(sl, [f"Expenses by bucket; amounts are net (charge less any credit). Credits received: {money(t['credits'])}.",
                    "% = share of total expenses."] + [f"{n}: {money(v)} ({_p(p)})" for n, v, p in items])

    # 10. key takeaways
    for k, part in enumerate(_chunks(s["takeaways"], BULLETS_PER_SLIDE)):
        sl = prs.slides.add_slide(blank)
        _title(sl, "Key takeaways" + (" (continued)" if k else ""))
        _text(sl, Inches(0.9), Inches(1.8), Inches(11.5), Inches(5), [f"•  {x}" for x in part], size=22, color=RGBColor(0x1B, 0x1F, 0x24))
        _notes(sl, ["Worked out from the figures:"] + part)
    # 11. summary notes
    if s["summary_notes"]:
        sl = prs.slides.add_slide(blank)
        _title(sl, "Summary notes")
        _text(sl, Inches(0.9), Inches(1.8), Inches(11.5), Inches(5), s["summary_notes"].split("\n"), size=20,
              color=RGBColor(0x1B, 0x1F, 0x24))
        _notes(sl, ["Written by the Budget Managers:", s["summary_notes"]])
    # 12. closing
    sl = prs.slides.add_slide(blank)
    _coin(sl, Inches(6.07), Inches(1.7), Inches(1.2))
    _text(sl, Inches(0.6), Inches(3.2), Inches(12.1), Inches(1.2), "Questions?", size=48, bold=True, align=PP_ALIGN.CENTER)
    _text(sl, Inches(0.6), Inches(4.5), Inches(12.1), Inches(0.6), f"{s['fundraiser']} · {s['organization']}", size=20,
          color=GREY, align=PP_ALIGN.CENTER)
    _text(sl, Inches(0.6), Inches(5.1), Inches(12.1), Inches(0.6), f"Generated {generated}", size=14, color=GREY,
          align=PP_ALIGN.CENTER)
    _notes(sl, [f"Generated {generated}. Transaction-level evidence is in the Audit report."])

    prs.core_properties.title = f"{s['fundraiser']} — results"
    prs.core_properties.author = s["organization"]
    prs.core_properties.comments = ""
    prs.core_properties.last_modified_by = "PennyWarden"
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def _strip_template_extras(prs) -> None:
    """The default template carries printer settings (a binary part) and a thumbnail picture: neither is needed, and
    leaving them out keeps the file to text, shapes, tables and charts."""
    try:
        for rid, rel in list(prs.part.rels.items()):
            if rel.reltype.endswith("/printerSettings"):
                prs.part.drop_rel(rid)
        rels = prs.part.package._rels
        for rid, rel in list(rels.items()):
            if rel.reltype.endswith("/thumbnail"):
                rels.pop(rid)
    except Exception:  # pragma: no cover - python-pptx internals changed; the deck is still valid with them
        pass


def _chunks(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)] if items else []


def file_name(s: dict) -> str:
    return f"fundraiser-{safe_name(s['fundraiser'])}-presentation.pptx"


__all__ = ["build", "file_name", "Emu", "dt"]
