"""2.0.0 build 12 (#188): the readable audit log exported for an audit review - CSV and a printable PDF.

Both are built from the same readable entries as the Audit Log screen (`audit_readable.readable`), so financial content
is withheld for Administrators exactly as on screen (BR-003) and the wording matches. Times are shown in the viewer's
time zone (sent by the browser; UTC when missing or unknown), with UTC alongside in the CSV. CSV cells that could start
a spreadsheet formula are escaped (the reports' helper). The raw JSON snapshots are not exported (they stay under
*Show technical details* on screen). The caller audits every export (AUDIT_LOG_EXPORTED)."""
from __future__ import annotations

import csv
import datetime as dt
import io
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, SimpleDocTemplate, Spacer, Table, TableStyle

from .reports import P, PM, _csv_safe, _FONT, _FONT_BOLD

MAX_EXPORT = 10_000          # entries per export; more asks the user to narrow the filters
CSV_HEADER = ["Event #", "Local time", "UTC time", "Actor", "Category", "Action", "Object", "Object #", "Summary",
              "What changed"]


def zone(name: str | None) -> tuple[dt.tzinfo, str]:
    """The viewer's IANA time zone, or UTC."""
    if name:
        try:
            return ZoneInfo(name), name
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return dt.timezone.utc, "UTC"


def local_time(ts: dt.datetime, tz: dt.tzinfo) -> str:
    return ts.replace(tzinfo=dt.timezone.utc).astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")


def actor(e: dict) -> str:
    if e.get("actor_name") and e.get("actor_username"):
        return f"{e['actor_name']} - {e['actor_username']}"
    return e.get("actor_username") or "system"


def _empty(v) -> bool:
    return v is None or v == "" or v == "—"


def _table_text(t: dict | None, sep: str = " | ") -> str:
    """A line table (allocations) as text: one entry per line ("Line 1: Column: value; ..."), empty values left out."""
    if not t:
        return "—"
    return sep.join(f"Line {i}: " + "; ".join(f"{c}: {v}" for c, v in zip(t["columns"], row) if not _empty(v))
                    for i, row in enumerate(t["rows"], 1))


def _side(c: dict, side: str, sep: str = " | ") -> str:
    if f"{side}_table" in c:
        return _table_text(c[f"{side}_table"], sep)
    v = c.get(side)
    return "—" if _empty(v) else str(v)


def changes_text(r: dict) -> str:
    """The "What changed" rows in one cell, one per line: an update as `Field: before → after (changed)`; a new record
    as `Field: value` and a removed one as `Field: value (before)`, leaving out empty fields."""
    out = []
    kind = r.get("kind")
    for c in r.get("changes") or []:
        before, after = _side(c, "before"), _side(c, "after")
        if kind == "update":
            out.append(f"{c['label']}: {before} → {after}{' (changed)' if c.get('changed') else ''}")
        elif after != "—":
            out.append(f"{c['label']}: {after}")
        elif before != "—":
            out.append(f"{c['label']}: {before} (before)")
    return "\n".join(out)


def what(e: dict) -> str:
    """The summary without the actor (the actor has its own column)."""
    s = (e.get("readable") or {}).get("summary") or ""
    return " — ".join(s.split(" — ")[1:]) or s


def to_csv(entries: list[dict], tz: dt.tzinfo, tz_name: str) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([f"Local time ({tz_name})" if h == "Local time" else h for h in CSV_HEADER])
    for e in entries:
        r = e.get("readable") or {}
        ts = e["_ts"]
        changes = ("Financial content withheld for Administrators" if e["snapshots_withheld"] else changes_text(r))
        w.writerow([_csv_safe(x) for x in (
            e["id"], local_time(ts, tz), ts.strftime("%Y-%m-%d %H:%M:%S"), actor(e),
            "Security" if e["category"] == "SECURITY" else "Business", r.get("action_label") or e["action"],
            r.get("object_label") or e["object_type"], e.get("object_id") or "", what(e), changes)])
    return "﻿" + out.getvalue()          # BOM: Excel opens UTF-8 correctly


# --------------------------------------------------------------------------- PDF
PAGE = landscape(letter)
MARGIN = 0.5 * inch
WIDTH = PAGE[0] - 2 * MARGIN


MAX_CELL = 2500     # characters of one PDF cell (a table row can't break across pages); the CSV holds it all


def _cell(text: str) -> str:
    return text if len(text) <= MAX_CELL else text[:MAX_CELL].rstrip() + f" … ({len(text) - MAX_CELL:,} more characters in the CSV export)"


def _change_table(r: dict) -> Table | None:
    rows = r.get("changes") or []
    if not rows:
        return None
    data = [[P("Field", "cellb"), P("Before", "cellb"), P("After", "cellb"), PM("", "cell")]]
    for c in rows:
        data.append([P(c["label"], "cell"), P(_cell(_side(c, "before", "\n")), "cell"), P(_cell(_side(c, "after", "\n")), "cell"),
                     P("changed" if c.get("changed") else "", "cellb")])
    w = WIDTH - 0.4 * inch
    t = Table(data, colWidths=[w * 0.22, w * 0.355, w * 0.355, w * 0.07], repeatRows=1, hAlign="RIGHT")
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9aa3ad")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8ecf1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]
        + [("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f2f4f7")) for i, c in enumerate(rows, 1) if c.get("changed")]))
    return t


def to_pdf(entries: list[dict], tz: dt.tzinfo, tz_name: str, *, org: str, exported_by: str, filters: list[str],
           total: int) -> bytes:
    buf = io.BytesIO()
    now = dt.datetime.utcnow()
    footer = f"{org} · Audit log export · {local_time(now, tz)}"

    def page(canvas, doc):
        canvas.saveState()
        canvas.setFont(_FONT, 7.5)
        canvas.setFillColor(colors.HexColor("#5b6573"))
        canvas.drawString(MARGIN, 0.3 * inch, footer)
        canvas.drawRightString(PAGE[0] - MARGIN, 0.3 * inch, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=PAGE, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
                            bottomMargin=0.55 * inch, title="Audit log export", author=org, subject="Audit log")
    story: list = [P(org, "h2"), P("Audit log export", "title"), Spacer(1, 4)]
    meta = [("Exported by", exported_by), ("Exported", local_time(now, tz)), ("Times shown in", tz_name),
            ("Filters", "; ".join(filters) or "none (the whole log)"), ("Entries", f"{total:,}")]
    mt = Table([[PM(f"<font name='{_FONT_BOLD}'>{escape(k)}</font>", "body"), P(v, "body")] for k, v in meta],
               colWidths=[1.3 * inch, WIDTH - 1.3 * inch])
    mt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                            ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    story += [mt, Spacer(1, 6)]
    if any(e["snapshots_withheld"] for e in entries):
        story.append(P("Financial content is withheld for Administrators: for those entries only who, the kind of "
                       "action and when are shown.", "small"))
    story.append(Spacer(1, 8))
    if not entries:
        story.append(P("No entries match the filters."))
    for e in entries:
        r = e.get("readable") or {}
        head = PM(f"<font name='{_FONT_BOLD}'>{escape(r.get('action_label') or e['action'])}</font> — {escape(what(e))}",
                  "body")
        sub = P(f"{local_time(e['_ts'], tz)} · {actor(e)} · "
                f"{'Security' if e['category'] == 'SECURITY' else 'Business'} · event #{e['id']}", "small")
        block = [head, sub]
        t = _change_table(r)        # indented, and splits across pages (repeating its header) when long
        if t is not None:
            block += [Spacer(1, 2), t]
        elif not e["snapshots_withheld"]:
            block.append(P("No recorded values.", "small"))
        block.append(Spacer(1, 7))
        story.append(KeepTogether(block))    # together on one page when it fits; split otherwise
    doc.build(story, onFirstPage=page, onLaterPages=page)
    return buf.getvalue()


def filter_lines(f: dict, labels: dict) -> list[str]:
    """The filters in words for the PDF's header (and the audit record)."""
    out = []
    if f.get("object_type"):
        out.append(f"Object type: {labels['object'](f['object_type'])}")
    if f.get("action"):
        out.append(f"Action: {labels['action'](f['action'])}")
    if f.get("actor"):
        out.append(f"Actor: {f['actor']}")
    if f.get("category"):
        out.append(f"Category: {'Security' if f['category'] == 'SECURITY' else 'Business'}")
    if f.get("date_from"):
        out.append(f"From: {f['date_from']}")
    if f.get("date_to"):
        out.append(f"To: {f['date_to']}")
    out.append("Oldest first" if f.get("direction") == "asc" else "Newest first")
    return out

