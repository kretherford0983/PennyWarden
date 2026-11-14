"""2.4.0 (#513): the formal invoice reports as a PDF (tables) and a presentation (.pptx: native charts and tables,
the figures in the speaker notes), drawn from `invoice_formal`. Same toolkit and Branding as the Quarterly / Annual and
Fiscal Year fundraising reports: `services/reports.py` for the PDF, `fundraiser_deck` for the deck. Every name
(customers, products, categories, budgets) is untrusted text - `P()` escapes it in the PDF; python-pptx writes text
runs, never markup."""
from __future__ import annotations

import datetime as dt
import io
import os
import tempfile

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from . import branding
from . import fundraiser_deck as deck
from .fundraiser_summary import _band, _table, _tile, heading, safe_name, tile_values
from .reports import FRAME_W, P, S, _AuditDoc, _Mark, _stamp_and_write
from .reports import money as cm

DASH = "—"


def _d(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%B} {d.day}, {d.year}"


def title(rep: dict) -> str:
    return f"{rep['title']} — {rep['period_label']}"


def as_of(rep: dict) -> str:
    return (f"Preliminary — as of {_d(rep['cutoff'])}" if rep["preliminary"] else f"As of {_d(rep['cutoff'])}")


def file_stem(org: str, rep: dict) -> str:
    return f"{safe_name(org)}-{safe_name(rep['title'])}-{safe_name(rep['period_label'])}"


def _pct(x: float | None) -> str:
    return DASH if x is None else f"{x:.1f}%"


def _chg(x: float | None) -> str:
    return DASH if x is None else f"{'+' if x >= 0 else ''}{x:.1f}%"


def _hdr(cells: list[str]) -> list:
    """The first column's heading left, the figures' headings right - over their numbers."""
    return [P(c, "cellb" if i == 0 else "fs_rb") for i, c in enumerate(cells)]


def _r(v) -> Paragraph:
    return P(v, "cellr")


def _vs(rep: dict, prior: int | None, change: float | None) -> str:
    if prior is None or not rep["prior_label"]:
        return ""
    return f"{rep['prior_label']}: {cm(prior)} ({_chg(change)})"


# ------------------------------------------------------------------ highlights
def highlights(rep: dict) -> list[tuple[str, str, str]]:
    if rep["id"] == "inv-sales-formal":
        t = rep["total"]
        out = [("Sales invoiced", cm(t["amount"]),
                _vs(rep, rep["prior_total"]["amount"] if rep["prior_total"] else None, rep["change"])
                or "After discounts, before tax"),
               ("Collected so far", cm(t["collected"]), f"{_pct(t['collected_pct'])} of the sales")]
        if rep["top_category"]:
            c = rep["top_category"]
            out.append(("Top category", c["label"], f"{cm(c['amount'])} · {_pct(c['share'])} of sales"))
        if rep["top_product"]:
            p = rep["top_product"]
            out.append(("Top product", p["label"], f"{cm(p['amount'])} · {_pct(p['share'])} of sales"))
        return out
    f, c = rep["figures"], rep["compare"]

    def vs(key):
        return _vs(rep, c[key]["prior"], c[key]["change"]) if c else ""
    return [("Invoiced", cm(f["invoiced"]), vs("invoiced") or f"{f['invoices']} invoices, tax included"),
            ("Collected", cm(f["net_collected"]), vs("net_collected") or "Payments received in the period"),
            ("Open at the end", cm(f["open_end"]), f"{f['open_invoices']} invoice{'s' if f['open_invoices'] != 1 else ''} on {_d(rep['cutoff'])}"),
            ("Overdue at the end", cm(f["overdue_end"]), vs("overdue_end") or "Past their due date")]


# ------------------------------------------------------------------ PDF
def build_pdf(org: str, rep: dict):
    buf = io.BytesIO()
    doc = _AuditDoc(buf, title=title(rep), author=org)
    W = FRAME_W - 12
    band = Table([[[P(org, "fs_w"), Paragraph(escape(rep["title"]), S["fs_wt"]), P(as_of(rep), "fs_wb"),
                    P(f"{rep['period_label']} · {_d(rep['start_date'])} – {_d(rep['end_date'])}"
                      + (f" · compared with {rep['prior_label']}" if rep["prior_label"] else ""), "fs_w")]]],
                 colWidths=[W])
    band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _band()), ("LEFTPADDING", (0, 0), (-1, -1), 12),
                              ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
    f: list = [_Mark(doc, rep["period_label"]), band, Spacer(1, 8), *heading("Highlights")]
    hl = highlights(rep)
    vals = tile_values([v for _k, v, _c in hl], W / len(hl) - 12)
    tt = Table([[[P(k, "fs_tk"), vals[i], P(c, "small")] for i, (k, v, c) in enumerate(hl)]], colWidths=[W / len(hl)] * len(hl))
    tt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _tile()),
                            ("BOX", (0, 0), (-1, -1), 0.5, branding.color("outline_variant")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.5, branding.color("outline_variant")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6),
                            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    f += [tt, Spacer(1, 6), *heading("Key points", "h2")]
    f += [P(f"• {x}", "body") for x in rep["key_points"]]
    if rep["commentary"]:
        f += [Spacer(1, 4), *heading("Commentary", "h2")]
        f += [P(par, "body") for par in rep["commentary"].split("\n") if par.strip()]
    f += (_sales_pdf if rep["id"] == "inv-sales-formal" else _overview_pdf)(rep, W)
    f += [Spacer(1, 10)] + [P(x, "small") for x in notes(rep)]
    doc.build(f)
    return buf.getvalue(), doc


def _sales_pdf(rep: dict, W: float) -> list:
    prior = rep["prior_label"] is not None
    f: list = [Spacer(1, 8), *heading("Sales by category")]
    head = ["Category", "Sales", "Collected", "Share"] + (["Last year", "Change"] if prior else [])
    data = [_hdr(head)]
    for c in rep["categories"]:
        data.append([P(c["label"], "cell"), _r(cm(c["amount"])), _r(cm(c["collected"])), _r(_pct(c["share"]))]
                    + ([_r(cm(c["prior"])), _r(_chg(c["change"]))] if prior else []))
    t = rep["total"]
    data.append([P("Total", "cellb"), _r(cm(t["amount"])), _r(cm(t["collected"])), _r("100.0%" if t["amount"] else DASH)]
                + ([_r(cm(rep["prior_total"]["amount"])), _r(_chg(rep["change"]))] if prior else []))
    n = len(head) - 1
    f.append(_table(data, [W - n * 0.95 * inch] + [0.95 * inch] * n, bold_rows=[len(data) - 1]))
    f += [Spacer(1, 8), *heading("Sales by product")]
    head = ["Product", "Quantity", "Gross", "Discounts", "Sales", "Collected"] + (["Last year"] if prior else [])
    data, bold = [_hdr(head)], []
    for g in rep["products"]:
        data.append([P(g["category"], "cellb")] + [P("", "cell")] * (len(head) - 1))
        bold.append(len(data) - 1)
        for p in g["products"]:
            data.append([P(p["label"], "fs_ind"), _r(p["qty"]), _r(cm(p["gross"])), _r(cm(p["discounts"])),
                         _r(cm(p["amount"])), _r(cm(p["collected"]))] + ([_r(cm(p["prior"]))] if prior else []))
    data.append([P("Total", "cellb"), _r(""), _r(cm(t["gross"])), _r(cm(t["discounts"])), _r(cm(t["amount"])),
                 _r(cm(t["collected"]))] + ([_r(cm(rep["prior_total"]["amount"]))] if prior else []))
    bold.append(len(data) - 1)
    n = len(head) - 1
    f.append(_table(data, [W - n * 0.85 * inch] + [0.85 * inch] * n, bold_rows=bold))
    f += [Spacer(1, 8), *heading("Sales by Income budget")]
    head = ["Income budget", "Sales", "Collected", "Share"] + (["Last year", "Change"] if prior else [])
    data = [_hdr(head)]
    for b in rep["budgets"]:
        data.append([P(b["label"], "cell"), _r(cm(b["amount"])), _r(cm(b["collected"])), _r(_pct(b["share"]))]
                    + ([_r(cm(b["prior"])), _r(_chg(b["change"]))] if prior else []))
    data.append([P("Total", "cellb"), _r(cm(t["amount"])), _r(cm(t["collected"])), _r("100.0%" if t["amount"] else DASH)]
                + ([_r(cm(rep["prior_total"]["amount"])), _r(_chg(rep["change"]))] if prior else []))
    n = len(head) - 1
    f.append(_table(data, [W - n * 0.95 * inch] + [0.95 * inch] * n, bold_rows=[len(data) - 1]))
    return f


def _overview_pdf(rep: dict, W: float) -> list:
    fg, c = rep["figures"], rep["compare"]
    prior = c is not None
    f: list = [Spacer(1, 8), *heading("Summary")]
    rows = [("Invoices issued", str(fg["invoices"]), "invoices", True), ("Invoiced (tax included)", cm(fg["invoiced"]), "invoiced", False),
            ("Sales before tax", cm(fg["net_sales"]), "net_sales", False), ("Average invoice", cm(fg["average"]), "average", False),
            ("Collected (after refunds)", cm(fg["net_collected"]), "net_collected", False),
            (f"Open on {_d(rep['cutoff'])}", cm(fg["open_end"]), "open_end", False),
            ("Overdue (part of the open amount)", cm(fg["overdue_end"]), "overdue_end", False),
            ("Discounts given", cm(fg["discounts"]), "discounts", False), ("Written off", cm(fg["write_offs"]), "write_offs", False),
            ("Refunded", cm(fg["refunds"]), "refunds", False)]
    head = ["", "This period"] + ([rep["prior_label"], "Change"] if prior else [])
    data = [_hdr(head)]
    for label, val, key, count in rows:
        r = [P(label, "cell"), _r(val)]
        if prior:
            pv = c[key]["prior"]
            r += [_r(str(pv) if count else cm(pv)), _r(_chg(c[key]["change"]))]
        data.append(r)
    f.append(_table(data, [W - (len(head) - 1) * 1.3 * inch] + [1.3 * inch] * (len(head) - 1)))
    f += [Spacer(1, 8), *heading("By month")]
    data = [_hdr(["Month", "Invoiced", "Collected"])]
    for m in rep["months"]:
        data.append([P(m["label"], "cell"), _r(cm(m["invoiced"])), _r(cm(m["collected"]))])
    data.append([P("Total", "cellb"), _r(cm(fg["invoiced"])), _r(cm(fg["net_collected"]))])
    f.append(_table(data, [W - 2 * 1.3 * inch, 1.3 * inch, 1.3 * inch], bold_rows=[len(data) - 1]))
    f += [Spacer(1, 8), *heading("Invoices by status")]
    data = [_hdr(["Status (today)", "Invoices"])] + [[P(s["label"], "cell"), _r(str(s["count"]))] for s in rep["status"]]
    f.append(_table(data, [W - 1.3 * inch, 1.3 * inch]))
    f += [Spacer(1, 8), *heading(f"Aging on {_d(rep['cutoff'])}")]
    data = [_hdr([a["label"] for a in rep["aging"]] + ["Total open"])]
    data.append([_r(cm(a["amount"])) for a in rep["aging"]] + [_r(cm(fg["open_end"]))])
    f.append(_table(data, [W / (len(rep["aging"]) + 1)] * (len(rep["aging"]) + 1)))
    if rep["tax"]:
        f += [Spacer(1, 8), *heading("Sales tax")]
        data = [_hdr(["Tax rate", "Taxable sales", "Tax charged", "Tax collected"])]
        for t in rep["tax"]:
            data.append([P(t["rate"], "cell"), _r(cm(t["taxable"])), _r(cm(t["charged"])), _r(cm(t["collected"]))])
        f.append(_table(data, [W - 3 * 1.3 * inch] + [1.3 * inch] * 3))
    f += [Spacer(1, 8), *heading("Top customers")]
    if rep["top_customers"]:
        data = [_hdr(["Customer", "Invoices", "Invoiced", "Paid", "Share"])]
        for t in rep["top_customers"]:
            data.append([P(t["name"], "cell"), _r(str(t["invoices"])), _r(cm(t["invoiced"])), _r(cm(t["paid"])), _r(_pct(t["share"]))])
        f.append(_table(data, [W - 4 * 1.05 * inch] + [1.05 * inch] * 4))
        if rep["customers_count"] > len(rep["top_customers"]):
            f.append(P(f"{rep['customers_count']} customers in all.", "small"))
    else:
        f.append(P("No invoices in this period.", "body"))
    if rep["top_products"]:
        f += [Spacer(1, 8), *heading("Top products")]
        data = [_hdr(["Product", "Quantity", "Sales", "Share"])]
        for t in rep["top_products"]:
            data.append([P(t["label"], "cell"), _r(t["qty"]), _r(cm(t["amount"])), _r(_pct(t["share"]))])
        f.append(_table(data, [W - 3 * 1.05 * inch] + [1.05 * inch] * 3))
    return f


def notes(rep: dict) -> list[str]:
    out = []
    if rep["id"] == "inv-sales-formal":
        out.append("Sales: issued invoices dated in the period (not drafts or voided invoices), after line and invoice "
                   "discounts, before tax - the same figures as the Sales by product / category report. Collected: the "
                   f"part of those sales paid by {_d(rep['cutoff'])}, split over the lines as payments are recorded.")
    else:
        out.append("Invoiced: issued invoices dated in the period, tax included. Collected: payments recorded in the "
                   "period on any invoice, less refunds. Open and overdue: as of the end of the period. Statuses are "
                   "today's.")
    if rep["prior_label"]:
        out.append(f"Compared with {rep['prior_label']} ({_d(rep['prior_start'])} – {_d(rep['prior_end'])}).")
    elif rep["kind"] == "CUSTOM":
        out.append("A custom period has no comparison with last year.")
    else:
        out.append("No comparison: PennyWarden has no Fiscal Year before this one.")
    if rep.get("show_names") is False:
        out.append("Customer names are left out; customers are numbered by amount invoiced.")
    if rep["preliminary"]:
        out.append(f"Preliminary: the period is still in progress; figures as of {_d(rep['cutoff'])}.")
    out.append(f"Generated {_d(rep['generated_on'])}.")
    return out


def pdf_file(org: str, rep: dict) -> tuple[str, str, int]:
    pdf, doc = build_pdf(org, rep)
    footer = f"{org}  ·  {title(rep)}  ·  {as_of(rep)}"
    fd, path = tempfile.mkstemp(prefix="fmpoc-invrep-", suffix=".pdf")
    os.close(fd)
    try:
        pages = _stamp_and_write(pdf, doc, path, footer)
    except Exception:
        os.unlink(path)
        raise
    return path, file_stem(org, rep) + ".pdf", pages


# ------------------------------------------------------------------ presentation
def _bar_chart(sl, labels: list[str], series: list[tuple[str, list[int]]], y: float = 1.7, h: float = 5.0,
               horizontal: bool = False) -> None:
    cd = CategoryChartData(number_format='"$"#,##0')
    cd.categories = labels or [DASH]
    for name, vals in series:
        cd.add_series(name, [v / 100 for v in vals] or [0])
    kind = XL_CHART_TYPE.BAR_CLUSTERED if horizontal else XL_CHART_TYPE.COLUMN_CLUSTERED
    ch = sl.shapes.add_chart(kind, Inches(0.7), Inches(y), Inches(11.9), Inches(h), cd).chart
    deck._style_chart(ch, legend=len(series) > 1, legend_pos=XL_LEGEND_POSITION.BOTTOM)
    for i, s in enumerate(ch.plots[0].series):
        s.format.fill.solid()
        s.format.fill.fore_color.rgb = deck.C.SERIES[i % len(deck.C.SERIES)]
    if horizontal:
        from pptx.enum.chart import XL_TICK_LABEL_POSITION
        ch.category_axis.reverse_order = True                 # largest at the top
        ch.category_axis.tick_label_position = XL_TICK_LABEL_POSITION.LOW


def build_pptx(org: str, rep: dict) -> bytes:
    prs = Presentation()
    deck._strip_template_extras(prs)
    prs.slide_width, prs.slide_height = deck.W, deck.H
    blank = prs.slide_layouts[6]
    sl = prs.slides.add_slide(blank)
    deck._mark(sl, Inches(0.6), Inches(0.9), Inches(1.0), Inches(1.3))
    deck._text(sl, Inches(2.0), Inches(0.8), Inches(10.5), Inches(0.6), org, size=24, bold=True)
    deck._text(sl, Inches(2.0), Inches(1.35), Inches(10.5), Inches(0.9), rep["title"], size=34, bold=True, color=deck.C.BLUE)
    deck._text(sl, Inches(2.0), Inches(2.2), Inches(10.5), Inches(0.5), f"{rep['period_label']} · {as_of(rep)}", size=18,
               color=(deck.C.GOLD if deck.C.DARK else deck.RED) if rep["preliminary"] else deck.C.GREY)
    hl = highlights(rep)
    w = 12.1 / len(hl)
    for i, (k, v, c) in enumerate(hl):
        x = Inches(0.6 + i * w)
        card = sl.shapes.add_shape(1, x, Inches(3.4), Inches(w - 0.25), Inches(2.4))
        card.fill.solid()
        card.fill.fore_color.rgb = deck.C.LIGHT
        card.line.color.rgb = deck.C.LINE
        deck._text(sl, x + Inches(0.2), Inches(3.55), Inches(w - 0.6), Inches(0.5), k, size=15, bold=True, color=deck.C.GREY)
        size = 24 if len(v) <= 14 else 20 if len(v) <= 22 else 16       # a long name gets smaller type, never split
        deck._text(sl, x + Inches(0.2), Inches(4.1), Inches(w - 0.6), Inches(0.9), v, size=size, bold=True)
        deck._text(sl, x + Inches(0.2), Inches(5.05), Inches(w - 0.6), Inches(0.6), c, size=12, color=deck.C.GREY)
    deck._notes(sl, ([f"Commentary: {rep['commentary']}"] if rep["commentary"] else []) + notes(rep))
    sl = prs.slides.add_slide(blank)
    deck._title(sl, "Key points", rep["period_label"])
    deck._text(sl, Inches(0.8), Inches(1.8), Inches(11.7), Inches(4.8), [f"• {x}" for x in rep["key_points"]], size=20,
               color=deck.C.TEXT)
    deck._notes(sl, rep["key_points"])
    if rep["commentary"]:
        sl = prs.slides.add_slide(blank)
        deck._title(sl, "Commentary", rep["period_label"])
        deck._text(sl, Inches(0.8), Inches(1.8), Inches(11.7), Inches(4.8),
                   [p for p in rep["commentary"].split("\n") if p.strip()], size=18, color=deck.C.TEXT)
        deck._notes(sl, [rep["commentary"]])
    (_sales_slides if rep["id"] == "inv-sales-formal" else _overview_slides)(prs, blank, rep)
    sl = prs.slides.add_slide(blank)
    deck._text(sl, Inches(0.6), Inches(3.0), Inches(12.1), Inches(1.2), "Questions?", size=48, bold=True, align=PP_ALIGN.CENTER)
    deck._text(sl, Inches(0.6), Inches(4.3), Inches(12.1), Inches(0.6), f"{org} · {title(rep)} · {as_of(rep)}", size=18,
               color=deck.C.GREY, align=PP_ALIGN.CENTER)
    deck._notes(sl, [f"Generated {_d(rep['generated_on'])}."])
    prs.core_properties.title = title(rep)
    prs.core_properties.author = org
    deck.brand_footers(prs)
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def _sales_slides(prs, blank, rep: dict) -> None:
    prior = rep["prior_label"] is not None
    cats = [c for c in rep["categories"] if c["amount"] or c["prior"]]
    if cats:
        sl = prs.slides.add_slide(blank)
        deck._title(sl, "Sales by category", f"{cm(rep['total']['amount'])} invoiced" + (f" · vs {rep['prior_label']}" if prior else ""))
        series = [("This period", [c["amount"] for c in cats[:10]])] + ([("Last year", [c["prior"] or 0 for c in cats[:10]])] if prior else [])
        _bar_chart(sl, [c["label"] for c in cats[:10]], series, horizontal=True)
        deck._notes(sl, [f"{c['label']}: {cm(c['amount'])} ({_pct(c['share'])}); collected {cm(c['collected'])}"
                         + (f"; last year {cm(c['prior'])} ({_chg(c['change'])})" if prior else "") + "." for c in cats])
    head = ["Category", "Sales", "Collected", "Share"] + (["Last year", "Change"] if prior else [])
    rows = [[c["label"], cm(c["amount"]), cm(c["collected"]), _pct(c["share"])] + ([cm(c["prior"]), _chg(c["change"])] if prior else [])
            for c in rep["categories"]]
    t = rep["total"]
    rows.append(["Total", cm(t["amount"]), cm(t["collected"]), "100.0%" if t["amount"] else DASH]
                + ([cm(rep["prior_total"]["amount"]), _chg(rep["change"])] if prior else []))
    _table_slides(prs, blank, "Categories", rep["period_label"], head, rows)
    head = ["Product", "Quantity", "Sales", "Collected"] + (["Last year"] if prior else [])
    rows = []
    for g in rep["products"]:
        rows.append([g["category"], "", "", ""] + ([""] if prior else []))
        rows += [["   " + p["label"], p["qty"], cm(p["amount"]), cm(p["collected"])] + ([cm(p["prior"])] if prior else [])
                 for p in g["products"]]
    _table_slides(prs, blank, "Products", "Grouped by category", head, rows, bold=lambda r: not r[1] and not r[2])
    bud = [b for b in rep["budgets"] if b["amount"] or b["prior"]]
    head = ["Income budget", "Sales", "Collected", "Share"] + (["Last year", "Change"] if prior else [])
    rows = [[b["label"], cm(b["amount"]), cm(b["collected"]), _pct(b["share"])] + ([cm(b["prior"]), _chg(b["change"])] if prior else [])
            for b in bud]
    _table_slides(prs, blank, "Income budgets", "Where the sales were recorded", head, rows)


def _overview_slides(prs, blank, rep: dict) -> None:
    fg = rep["figures"]
    sl = prs.slides.add_slide(blank)
    deck._title(sl, "Invoiced and collected by month", f"{cm(fg['invoiced'])} invoiced · {cm(fg['net_collected'])} collected")
    _bar_chart(sl, [m["label"] for m in rep["months"]], [("Invoiced", [m["invoiced"] for m in rep["months"]]),
                                                        ("Collected", [m["collected"] for m in rep["months"]])])
    deck._notes(sl, [f"{m['label']}: invoiced {cm(m['invoiced'])}, collected {cm(m['collected'])}." for m in rep["months"]])
    c = rep["compare"]
    head = ["", "This period"] + ([rep["prior_label"], "Change"] if c else [])
    keys = [("Invoices issued", "invoices", True), ("Invoiced (tax included)", "invoiced", False),
            ("Sales before tax", "net_sales", False), ("Average invoice", "average", False),
            ("Collected (after refunds)", "net_collected", False), ("Open at the end", "open_end", False),
            ("Overdue at the end", "overdue_end", False), ("Discounts", "discounts", False), ("Written off", "write_offs", False)]
    rows = []
    for label, key, count in keys:
        v = fg[key]
        r = [label, str(v) if count else cm(v)]
        if c:
            pv = c[key]["prior"]
            r += [str(pv) if count else cm(pv), _chg(c[key]["change"])]
        rows.append(r)
    _table_slides(prs, blank, "Summary", rep["period_label"], head, rows)
    sl = prs.slides.add_slide(blank)
    deck._title(sl, "Aging", f"Open on {_d(rep['cutoff'])}: {cm(fg['open_end'])}")
    _bar_chart(sl, [a["label"] for a in rep["aging"]], [("Open", [a["amount"] for a in rep["aging"]])])
    deck._notes(sl, [f"{a['label']}: {cm(a['amount'])}." for a in rep["aging"]] + ["Days past the due date, as of the end of the period."])
    if rep["top_customers"]:
        sl = prs.slides.add_slide(blank)
        deck._title(sl, "Top customers", f"{rep['customers_count']} customer{'s' if rep['customers_count'] != 1 else ''} invoiced")
        _bar_chart(sl, [t["name"] for t in rep["top_customers"]], [("Invoiced", [t["invoiced"] for t in rep["top_customers"]]),
                                                                  ("Paid", [t["paid"] for t in rep["top_customers"]])], horizontal=True)
        deck._notes(sl, [f"{t['name']}: invoiced {cm(t['invoiced'])} on {t['invoices']} invoice(s), paid {cm(t['paid'])} ({_pct(t['share'])})."
                         for t in rep["top_customers"]])
    if rep["top_products"]:
        _table_slides(prs, blank, "Top products", "By sales before tax", ["Product", "Quantity", "Sales", "Share"],
                      [[t["label"], t["qty"], cm(t["amount"]), _pct(t["share"])] for t in rep["top_products"]])
    if rep["tax"]:
        _table_slides(prs, blank, "Sales tax", "Charged on the period's invoices; collected with its payments",
                      ["Tax rate", "Taxable sales", "Tax charged", "Tax collected"],
                      [[t["rate"], cm(t["taxable"]), cm(t["charged"]), cm(t["collected"])] for t in rep["tax"]])


def _table_slides(prs, blank, name: str, sub: str, head: list[str], rows: list[list[str]], bold=None) -> None:
    if not rows:
        return
    n = len(head) - 1
    widths = [12.1 - n * 1.65] + [1.65] * n
    for k, part in enumerate(deck._chunks(rows, deck.TABLE_ROWS)):
        sl = prs.slides.add_slide(blank)
        deck._title(sl, name + (" (continued)" if k else ""), sub)
        deck._table(sl, Inches(0.6), Inches(1.7), Inches(12.1), [head] + part, widths, set(range(1, len(head))),
                    bold_rows=[i + 1 for i, r in enumerate(part) if r[0] == "Total" or (bold and bold(r))], size=12)
        deck._notes(sl, [" · ".join(x for x in r if x) for r in part])
