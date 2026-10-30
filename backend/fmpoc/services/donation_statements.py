"""2.2.0 (#256): year-end giving statements and the donor giving report (Kyle, 2026-10-24).

Year-end giving statement
- One letter per donor and calendar year (tax statements follow the calendar year) listing the donation lines
  **received** in that year: money linked to an active deposit, items ticked Received, dated in the year. Cancelled
  donations, voided deposits and lines awaiting a deposit are left out.
- Register Users print (`donation.print`); the other financial roles and Auditors view (`donation.view`).
  Administrators never see donors or amounts (BR-003): their setup preview and test print use sample data only.
- One donor, or all donors for a year as one combined PDF, with an optional minimum total.
- A table of each donation (received date, receipt number, description or purpose, amount, goods or services); items
  by description only, no value; a money total; the receipt's required statements (goods or services, items note).
- Its own letter in Donations Setup (`statement_*` in the receipt settings) with {YEAR}, {TOTAL}, {STATEMENT_NO} and
  {DONATION_TABLE}; the layout, window envelope, fold marks and signer are the receipt's.
- Kept (a system-generated attachment of the statement), numbered per year (S-2026-0001), audited. The same content
  again prints a DUPLICATE (same number); changed content prints a CORRECTED statement with a new number.
- Envelopes as for receipts (the Donations envelopes of the shared library).

Donor giving report
- All financial roles and Auditors (`donation.view`); never Administrators.
- One row per donor: a column per year (up to 5) and a total, number of gifts, last gift date, item count and their
  internal estimated value (the organization's own report - never printed on a letter to the donor); the detail
  lines per donor. Filters: year range, donor, minimum total. JSON, PDF and CSV (optionally with the detail lines).
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, Warning_, conflict, not_found, require_confirmations, validation
from ..models import Attachment, Donation, DonationStatement, Entity, Workspace, utcnow
from . import donations as dn
from . import entity_vars
from . import organization as org_svc
from .checkprint import documents, patterns
from .checkprint.service import address_lines, format_date
from .common import get_scoped

STATEMENT_COPY = "DONATION_STATEMENT"       # Attachment.document_type of a statement's kept copy
TABLE_MARK = "\x00DONATION_TABLE\x00"
MAX_YEARS = 5
MIN_YEAR, MAX_YEAR = 1900, 2999


def _year(y: int) -> int:
    if not MIN_YEAR <= y <= MAX_YEAR:
        raise validation("Choose a calendar year.", "year")
    return y


# ------------------------------------------------------------------ what was received
def received_lines(db: Session, ws_id: int, start_year: int, end_year: int, donor_id: int | None = None) -> list[dict]:
    """Every donation line received in the calendar years start..end (inclusive), of active donations."""
    q = select(Donation).where(Donation.workspace_id == ws_id, Donation.status == dn.ACTIVE)
    if donor_id is not None:
        q = q.where(Donation.donor_entity_id == donor_id)
    out = []
    for d in db.scalars(q.order_by(Donation.id)):
        receipts = dn._receipts_of(db, d)
        cur = dn._current(receipts)
        void = dn.receipts_void(db, d)
        for x in dn.lines_of(db, d):
            if not dn.line_received(db, x):
                continue
            when = dn.line_date(db, x)
            if when is None or not start_year <= when.year <= end_year:
                continue
            money_line = x.kind == dn.MONEY
            out.append({"line_id": x.id, "donation_id": d.id, "donor_id": d.donor_entity_id, "date": when,
                        "receipt": cur.number if cur is not None and not void else "",
                        "kind": x.kind, "description": x.purpose or x.description or "",
                        "item_description": x.description or "",
                        "amount_cents": dn.line_amount(db, x) if money_line else 0,
                        "item_value_cents": (x.amount_cents or 0) if not money_line else 0,
                        "goods_cents": x.goods_cents or 0, "goods_description": x.goods_description or ""})
    out.sort(key=lambda r: (r["date"], r["donation_id"], r["line_id"]))
    return out


def _content(db: Session, ws_id: int, donor: Entity, year: int) -> dict:
    rows = received_lines(db, ws_id, year, year, donor.id)
    money_rows = [r for r in rows if r["kind"] == dn.MONEY]
    return {"entity": donor, "year": year, "rows": rows, "total": sum(r["amount_cents"] for r in money_rows),
            "goods": sum(r["goods_cents"] for r in rows), "gifts": len(rows),
            "items": [r["item_description"] for r in rows if r["kind"] == dn.ITEM]}


def _sha(c: dict) -> str:
    e = c["entity"]
    doc = {"donor": e.id, "name": e.legal_name, "address": address_lines(e), "year": c["year"],
           "rows": [[r["line_id"], r["date"].isoformat(), r["receipt"], r["kind"], r["description"],
                     r["item_description"], r["amount_cents"], r["goods_cents"], r["goods_description"]]
                    for r in c["rows"]]}
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def statements_of(db: Session, ws_id: int, donor_id: int, year: int) -> list[DonationStatement]:
    return list(db.scalars(select(DonationStatement).where(
        DonationStatement.workspace_id == ws_id, DonationStatement.donor_entity_id == donor_id,
        DonationStatement.year == year).order_by(DonationStatement.id)))


def _current(statements: list[DonationStatement]) -> DonationStatement | None:
    numbered = [s for s in statements if s.kind != dn.DUPLICATE]
    return numbered[-1] if numbered else None


def _next_kind(cur: DonationStatement | None, sha: str) -> str:
    return dn.ORIGINAL if cur is None else (dn.DUPLICATE if cur.content_sha == sha else dn.CORRECTED)


def _statements_out(db: Session, statements: list[DonationStatement]) -> list[dict]:
    by_id = {s.id: s for s in statements}
    superseded = {s.replaces_id for s in statements if s.kind == dn.CORRECTED and s.replaces_id}
    return [{"id": s.id, "number": s.number, "kind": s.kind, "total": dn.money(s.total_cents),
             "replaces": by_id[s.replaces_id].number if s.replaces_id in by_id else None,
             "printed_at": s.printed_at.isoformat() + "Z", "printed_by": dn._user_name(db, s.printed_by_user_id),
             "attachment_id": s.attachment_id,
             "superseded": s.id in superseded or (s.kind == dn.DUPLICATE and s.replaces_id in superseded)}
            for s in statements]


def _donor(db: Session, ctx, donor_id: int) -> Entity:
    e = get_scoped(db, Entity, donor_id, ctx, "Donor")
    if e.is_system:
        raise not_found("Donor")
    return e


def summary(db: Session, ctx, year: int, min_cents: int = 0, q: str | None = None) -> dict:
    """The donors with donations received in the year, their totals and statements."""
    year = _year(year)
    by_donor: dict[int, list[dict]] = {}
    for r in received_lines(db, ctx.workspace_id, year, year):
        by_donor.setdefault(r["donor_id"], []).append(r)
    rows = []
    for donor_id, lines in by_donor.items():
        e = db.get(Entity, donor_id)
        total = sum(r["amount_cents"] for r in lines)
        if total < min_cents:
            continue
        if q and q.strip().lower() not in e.display_name.lower():
            continue
        c = _content(db, ctx.workspace_id, e, year)
        sts = statements_of(db, ctx.workspace_id, donor_id, year)
        cur = _current(sts)
        rows.append({"donor_id": e.id, "donor": e.display_name, "has_address": bool(address_lines(e)),
                     "total": dn.money(total), "total_cents": total, "gifts": len(lines),
                     "items": sum(1 for r in lines if r["kind"] == dn.ITEM),
                     "current_statement": cur.number if cur else None,
                     "next_kind": _next_kind(cur, _sha(c)), "printed": len(sts)})
    rows.sort(key=lambda r: r["donor"].lower())
    return {"year": year, "items": rows, "min_cents": min_cents,
            "setup_missing": dn.missing_setup(db, ctx.workspace_id)}


def detail(db: Session, ctx, year: int, donor_id: int) -> dict:
    e = _donor(db, ctx, donor_id)
    c = _content(db, ctx.workspace_id, e, _year(year))
    sts = statements_of(db, ctx.workspace_id, e.id, year)
    return {"year": year, "donor": {"id": e.id, "name": e.display_name, "has_address": bool(address_lines(e))},
            "total": dn.money(c["total"]), "rows": [_row_out(r) for r in c["rows"]],
            "next_kind": _next_kind(_current(sts), _sha(c)), "statements": _statements_out(db, sts)}


def _row_out(r: dict) -> dict:
    return {"date": r["date"].isoformat(), "receipt": r["receipt"], "kind": r["kind"], "donation_id": r["donation_id"],
            "description": r["item_description"] if r["kind"] == dn.ITEM else r["description"],
            "amount": dn.money(r["amount_cents"]) if r["kind"] == dn.MONEY else None,
            "goods": dn.money(r["goods_cents"]) if r["goods_cents"] else None,
            "goods_description": r["goods_description"] or None}


# ------------------------------------------------------------------ the letter
def statement_values(cfg, org: dict, donor_name: str, donor_address: list[str], year: int, number: str,
                     total_cents: int, today: dt.date, donor_values: dict | None = None,
                     signature=None) -> dict[str, str]:
    org = org if cfg.include_ein else dn.hide_ein(org)          # 2.3.0 (#393)
    return {"DONOR_NAME": donor_name, "DONOR_ADDRESS": "\n".join(donor_address), **org, **(donor_values or {}),
            "YEAR": str(year),
            "TOTAL": f"{total_cents // 100:,}.{total_cents % 100:02d}", "STATEMENT_NO": number,
            "SIGNER": (signature.name if signature else ""), "SIGNER_TITLE": (signature.title if signature else ""),
            "TODAY": format_date(today, cfg.date_format),
            "DONATION_TABLE": TABLE_MARK}


def statement_texts(cfg, vals: dict) -> tuple[dict, list[str]]:
    out, empty = {}, []
    for name in ("title", "salutation", "body", "closing"):
        r = patterns.resolve(getattr(cfg, f"statement_{name}"), vals, patterns.STATEMENT)
        out[name] = r.text
        empty += [v for v in r.empty if v not in empty and (cfg.include_ein or v not in dn.EIN_VARS)]
    return out, empty


def _donation_table(rows: list[dict], total_cents: int, cfg, st: dict) -> Table:
    head = ["Date received", "Receipt No.", "Description", "Amount", "Goods or services provided"]
    body = []
    for r in rows:
        desc = f"Item: {r['item_description']}" if r["kind"] == dn.ITEM else r["description"]
        goods = (dn.money(r["goods_cents"]) + (f" ({r['goods_description']})" if r["goods_description"] else "")
                 if r["goods_cents"] else "None")
        body.append([format_date(r["date"], cfg.date_format), r["receipt"] or "", desc,
                     dn.money(r["amount_cents"]) if r["kind"] == dn.MONEY else "", goods])
    small = st["small"]
    data = [[Paragraph(escape(h), st["strong"]) for h in head]]
    data += [[Paragraph(escape(v), small) for v in row] for row in body]
    data.append([Paragraph("", small), Paragraph("", small), Paragraph(escape("Total (money)"), st["strong"]),
                 Paragraph(escape(dn.money(total_cents)), st["strong"]), Paragraph("", small)])
    tbl = Table(data, colWidths=[1.0 * inch, 0.95 * inch, 2.05 * inch, 0.9 * inch, 1.6 * inch], repeatRows=1,
                hAlign="LEFT")
    tbl.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.8, "#444444"),
                             ("LINEABOVE", (0, -1), (-1, -1), 0.6, "#666666"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("ALIGN", (3, 0), (3, -1), "RIGHT"), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                             ("TOPPADDING", (0, 0), (-1, -1), 2)]))
    return tbl


def statement_pdf(cfg, *, org: dict, donor_name: str, donor_address: list[str], year: int, number: str, kind: str,
                  kind_note: str, rows: list[dict], total_cents: int, goods: list[tuple[int, str]], items: list[str],
                  today: dt.date | None = None, sample: bool = False, watermark: str | None = None,
                  donor_values: dict | None = None, signature=None) -> bytes:
    today = today or dt.date.today()
    if sample and watermark is None:
        watermark = "SAMPLE - NOT A STATEMENT"
    vals = statement_values(cfg, org, donor_name, donor_address, year, number, total_cents, today, donor_values,
                            signature)
    texts, _empty = statement_texts(cfg, vals)
    st = dn._styles(cfg)
    size, base = st["size"], st["base"]
    table = _donation_table(rows, total_cents, cfg, st)
    middle = []
    if texts["title"].strip():
        middle += [Paragraph(escape(texts["title"].replace(TABLE_MARK, "")), st["title"]), Spacer(1, size * 0.4)]
    middle.append(Paragraph(escape(f"Statement No. {number}"), st["strong"]))
    if kind_note:
        middle.append(Paragraph(escape(kind_note), st["small"]))
    middle.append(Spacer(1, size))
    placed = False
    for key in ("salutation", "body"):
        for para in texts[key].split("\n\n"):
            if TABLE_MARK in para:
                rest = para.replace(TABLE_MARK, "").strip()
                if rest:
                    middle += [Paragraph("<br/>".join(escape(x) for x in rest.split("\n")), base),
                               Spacer(1, size * 0.5)]
                if not placed:
                    middle += [table, Spacer(1, size * 0.7)]
                    placed = True
            elif para.strip():
                middle += [Paragraph("<br/>".join(escape(x) for x in para.split("\n")), base), Spacer(1, size * 0.7)]
    if not placed:                                  # the table is required content: after the text when not placed
        middle += [table, Spacer(1, size * 0.7)]
    rows_ack = ([("Organization", org["ORG.NAME"])] + ([("EIN", org["ORG.EIN"])] if cfg.include_ein else [])   # #393
                + [("Donor", donor_name), ("Calendar year", str(year)), ("Total (money)", dn.money(total_cents))])
    if items:
        rows_ack.append(("Items", "\n".join(f"• {x}" for x in items)))
    rows_ack.append(("Statement No.", number))
    ack = [dn.ack_table(rows_ack, st), Spacer(1, size * 0.6),
           Paragraph(escape(dn.goods_statement(goods)), st["strong"])]
    if items:
        ack += [Spacer(1, size * 0.4), Paragraph(escape(dn.items_note_text(cfg, {k: v for k, v in vals.items()
                                                                                 if k != "DONATION_TABLE"})), base)]
    middle.append(KeepTogether(ack))
    lines = dn.addressee_lines(cfg, {k: v for k, v in vals.items() if k != "DONATION_TABLE"}, donor_name,
                               donor_address)
    return dn.donor_letter_pdf(cfg, org=org, donor_lines=lines, today=today,
                               kind=kind, sample=sample, watermark=watermark,
                               doc_title=f"Year-end giving statement {number}", middle=middle,
                               closing=texts["closing"].replace(TABLE_MARK, ""), signature=signature)


def sample_pdf(db: Session, ctx, data: dict | None, km=None) -> bytes:
    """Setup preview and test print: sample data only (BR-003)."""
    cfg = dn.parse_config(data) if data is not None else dn.get_config(db, ctx.workspace_id)
    year = dt.date.today().year - 1
    rows = [{"date": dt.date(year, 3, 14), "receipt": f"R-{year}-0007", "kind": dn.MONEY, "description": "General support",
             "item_description": "", "amount_cents": 25000, "goods_cents": 0, "goods_description": ""},
            {"date": dt.date(year, 9, 2), "receipt": f"R-{year}-0031", "kind": dn.MONEY, "description": "Gala dinner",
             "item_description": "", "amount_cents": 15000, "goods_cents": 6000, "goods_description": "Dinner"},
            {"date": dt.date(year, 11, 20), "receipt": f"R-{year}-0044", "kind": dn.ITEM, "description": "",
             "item_description": "SAMPLE ITEM - a television for the auction", "amount_cents": 0, "goods_cents": 0,
             "goods_description": ""}]
    return statement_pdf(cfg, org=dn._org_or_placeholders(db, ctx.workspace_id), donor_name=dn.SAMPLE_DONOR[0],
                         donor_address=dn.SAMPLE_DONOR[1:], year=year, number=f"S-{year}-0000", kind=dn.ORIGINAL,
                         kind_note="", rows=rows, total_cents=40000, goods=[(6000, "Dinner")],
                         items=["SAMPLE ITEM - a television for the auction"], sample=True,
                         donor_values=entity_vars.sample("DONOR", dn.SAMPLE_DONOR[0], dn.SAMPLE_DONOR[1:]),
                         signature=dn.signature_for(db, ctx.workspace_id, km, cfg, "statement", with_image=True))


# ------------------------------------------------------------------ printing
PREVIEW_NUMBER = "(assigned when printed)"


def _next_seq(db: Session, ws_id: int, year: int) -> int:
    cur = db.scalar(select(func.max(DonationStatement.seq)).where(DonationStatement.workspace_id == ws_id,
                                                                  DonationStatement.year == year))
    return (cur or 0) + 1


def _compose(db: Session, ctx, e: Entity, year: int, seq: int | None = None) -> dict:
    missing = dn.missing_setup(db, ctx.workspace_id)
    if missing:
        raise conflict("SETUP_INCOMPLETE", "An Administrator must enter " + " and ".join(missing) +
                       " in System/About → Organization before statements can be printed.")
    c = _content(db, ctx.workspace_id, e, year)
    if not c["rows"]:
        raise conflict("NO_DONATIONS", f"{e.display_name} has no donation received in {year}.")
    cfg = dn.get_config(db, ctx.workspace_id)
    sts = statements_of(db, ctx.workspace_id, e.id, year)
    cur = _current(sts)
    sha = _sha(c)
    kind = _next_kind(cur, sha)
    if kind == dn.DUPLICATE:
        number, seq = cur.number, cur.seq
        note = (f"DUPLICATE of statement {cur.number}, first printed "
                f"{format_date(cur.printed_at.date(), cfg.date_format)}.")
    else:
        seq = seq or _next_seq(db, ctx.workspace_id, year)
        number = f"S-{year}-{seq:04d}"
        note = "" if cur is None else (f"CORRECTED statement: replaces statement {cur.number} printed "
                                       f"{format_date(cur.printed_at.date(), cfg.date_format)}.")
    org = org_svc.values_for(db, ctx.workspace_id)
    addr = address_lines(e)
    vals = statement_values(cfg, org, e.legal_name, addr, year, number, c["total"], dt.date.today(),
                            entity_vars.values("DONOR", e), dn.signature_for(db, ctx.workspace_id, None, cfg, "statement"))
    _t, empty = statement_texts(cfg, vals)
    warnings = []
    if empty:
        warnings.append(Warning_("EMPTY_VARIABLES", "These variables have no data for this statement: " +
                                 ", ".join("{" + v + "}" for v in empty) + ". Print the statement as it is?",
                                 variables=empty))
    if not addr:
        warnings.append(Warning_("NO_DONOR_ADDRESS", f"{e.display_name} has no address. Print the statement "
                                 "without it?"))
    if kind == dn.CORRECTED:
        warnings.append(Warning_("CORRECTED_STATEMENT", f"{e.display_name}'s donations in {year} changed since "
                                 f"statement {cur.number}. Print a corrected statement {number} that replaces it?",
                                 replaces=cur.number))
    return {"cfg": cfg, "c": c, "e": e, "org": org, "addr": addr, "kind": kind, "number": number, "seq": seq,
            "cur": cur, "sha": sha, "note": note, "warnings": warnings, "year": year,
            "signature": dn.signature_for(db, ctx.workspace_id, None, cfg, "statement")}   # #395: no image yet


def _pdf(x: dict, watermark: str | None = None) -> bytes:
    c = x["c"]
    return statement_pdf(x["cfg"], org=x["org"], donor_name=x["e"].legal_name, donor_address=x["addr"],
                         year=x["year"], number=x["number"], kind=x["kind"], kind_note=x["note"], rows=c["rows"],
                         total_cents=c["total"], goods=[(r["goods_cents"], r["goods_description"]) for r in c["rows"]
                                                        if r["goods_cents"]],
                         items=c["items"], watermark=watermark, donor_values=entity_vars.values("DONOR", x["e"]),
                         signature=x["signature"])


def preview(db: Session, ctx, year: int, donor_id: int) -> tuple[bytes, dict]:
    x = _compose(db, ctx, _donor(db, ctx, donor_id), _year(year))
    if x["kind"] != dn.DUPLICATE:
        x["number"] = PREVIEW_NUMBER
    pdf = _pdf(x, watermark="PREVIEW - NOT A STATEMENT")
    audit.record(db, ctx, "DONATION_STATEMENT_PREVIEW", "entity", x["e"].id, None, {"year": year, "kind": x["kind"]})
    db.commit()
    return pdf, {"kind": x["kind"], "replaces": x["cur"].number if x["kind"] == dn.CORRECTED else None}


def _keep(db: Session, ctx, settings, x: dict, pdf: bytes) -> tuple[DonationStatement, object]:
    from . import attachments as att_svc
    c, e = x["c"], x["e"]
    s = DonationStatement(workspace_id=ctx.workspace_id, donor_entity_id=e.id, donor_name=e.legal_name[:200],
                          year=x["year"], seq=x["seq"], number=x["number"], kind=x["kind"],
                          replaces_id=x["cur"].id if x["cur"] is not None else None, total_cents=c["total"],
                          goods_cents=c["goods"], gifts=c["gifts"], items=len(c["items"]),
                          line_ids=",".join(str(r["line_id"]) for r in c["rows"]), content_sha=x["sha"],
                          printed_by_user_id=ctx.user.id, printed_at=utcnow())
    db.add(s)
    db.flush()
    key, path = att_svc._write_file(settings, pdf)
    suffix = "-duplicate" if x["kind"] == dn.DUPLICATE else ""
    att = Attachment(workspace_id=ctx.workspace_id,
                     original_filename=att_svc.sanitize_filename(f"statement-{x['number']}{suffix}.pdf"),
                     storage_key=key, mime_type="application/pdf", size_bytes=len(pdf),
                     sha256=hashlib.sha256(pdf).hexdigest(), uploaded_by_user_id=ctx.user.id, active=True,
                     donation_statement_id=s.id, document_type=STATEMENT_COPY, system_generated=True)
    db.add(att)
    db.flush()
    s.attachment_id = att.id
    audit.record(db, ctx, "ATTACHMENT_ADDED", "attachment", att.id, None, att_svc.snapshot(att))
    audit.record(db, ctx, "DONATION_STATEMENT_PRINTED", "donation_statement", s.id, None,
                 {"statement_id": s.id, "number": s.number, "kind": s.kind, "year": s.year, "donor_entity_id": e.id,
                  "total_cents": s.total_cents, "goods_cents": s.goods_cents, "gifts": s.gifts, "items": s.items,
                  "replaces": x["cur"].number if x["cur"] is not None and s.kind != dn.ORIGINAL else None})
    return s, path


def _commit(db: Session, paths: list) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        for p in paths:
            try:
                p.unlink()
            except OSError:
                pass
        raise


def _printed(db: Session, ctx, x: dict, km) -> bytes | None:
    """2.3.0 (#395): the printed copy with the signature image (None: same as the record copy)."""
    if km is None:
        return None
    sig = dn.signature_for(db, ctx.workspace_id, km, x["cfg"], "statement", with_image=True)
    if not sig.image:
        return None
    return _pdf({**x, "signature": sig})


def print_one(db: Session, ctx, settings, year: int, donor_id: int, confirmations: list[str],
              km=None) -> tuple[bytes, DonationStatement]:
    x = _compose(db, ctx, _donor(db, ctx, donor_id), _year(year))
    require_confirmations(x["warnings"], confirmations)
    pdf = _pdf(x)                                   # kept with the record: never the signature image (#395)
    s, path = _keep(db, ctx, settings, x, pdf)
    _commit(db, [path])
    return _printed(db, ctx, x, km) or pdf, s


def print_all(db: Session, ctx, settings, year: int, min_cents: int, confirmations: list[str],
              km=None) -> tuple[bytes, list[DonationStatement]]:
    """All donors with donations received in the year (and at least `min_cents` of money), one statement each,
    as one combined PDF. Each is kept and numbered on its own; asks once for what needs confirming."""
    year = _year(year)
    donors = [r["donor_id"] for r in summary(db, ctx, year, min_cents)["items"]]
    if not donors:
        raise conflict("NO_DONATIONS", f"No donor has donations received in {year}"
                                       + (f" totalling at least {dn.money(min_cents)}." if min_cents else "."))
    seq = _next_seq(db, ctx.workspace_id, year)
    composed = []
    for donor_id in donors:
        x = _compose(db, ctx, db.get(Entity, donor_id), year, seq)
        if x["kind"] != dn.DUPLICATE:
            seq += 1
        composed.append(x)
    no_addr = [x["e"].display_name for x in composed if not x["addr"]]
    corrected = [x["e"].display_name for x in composed if x["kind"] == dn.CORRECTED]
    empty = sorted({v for x in composed for w in x["warnings"] if w.code == "EMPTY_VARIABLES"
                    for v in w.as_dict().get("variables", [])})
    warnings = [Warning_("PRINT_ALL", f"Print {len(composed)} year-end statement{'s' if len(composed) != 1 else ''} "
                         f"for {year} as one PDF? Each is kept and numbered.", count=len(composed))]
    if no_addr:
        warnings.append(Warning_("NO_DONOR_ADDRESS", "These donors have no address: " + ", ".join(no_addr) +
                                 ". Print their statements without it?", donors=no_addr))
    if corrected:
        warnings.append(Warning_("CORRECTED_STATEMENT", "Donations changed since the last statement of: " +
                                 ", ".join(corrected) + ". Print corrected statements that replace them?",
                                 donors=corrected))
    if empty:
        warnings.append(Warning_("EMPTY_VARIABLES", "These variables have no data for some statements: " +
                                 ", ".join("{" + v + "}" for v in empty) + ". Print as they are?", variables=empty))
    require_confirmations(warnings, confirmations)
    out, paths, writer = [], [], PdfWriter()
    for x in composed:
        pdf = _pdf(x)
        s, path = _keep(db, ctx, settings, x, pdf)
        out.append(s)
        paths.append(path)
        for page in PdfReader(io.BytesIO(_printed(db, ctx, x, km) or pdf)).pages:     # #395: image only here
            writer.add_page(page)
    writer.add_metadata({"/Title": f"Year-end giving statements {year}", "/Creator": "PennyWarden"})
    buf = io.BytesIO()
    writer.write(buf)
    audit.record(db, ctx, "DONATION_STATEMENTS_PRINTED_ALL", "donation_statement", None, None,
                 {"year": year, "min_cents": min_cents, "count": len(out), "numbers": [s.number for s in out]})
    _commit(db, paths)
    return buf.getvalue(), out


def get_statement(db: Session, ctx, statement_id: int) -> DonationStatement:
    return get_scoped(db, DonationStatement, statement_id, ctx, "Statement")


def document(db: Session, ctx, settings, s: DonationStatement) -> tuple[bytes, str]:
    from . import attachments as att_svc
    a = db.get(Attachment, s.attachment_id) if s.attachment_id else None
    if a is None or not a.active:
        raise not_found("Document")
    data = att_svc.path_for(settings, a).read_bytes()
    audit.record(db, ctx, "ATTACHMENT_VIEWED", "attachment", a.id, None, {"donation_statement_id": s.id})
    db.commit()
    return data, a.original_filename


# ------------------------------------------------------------------ envelopes (the Donations envelopes)
ENVELOPE_COPY = "STATEMENT_ENVELOPE"


def print_envelope(db: Session, ctx, settings, s: DonationStatement, doc_id: int, *, return_address: bool | None,
                   page: str | None, guide: str | None, test: bool, confirmations: list[str]) -> bytes:
    """The donor's envelope for a statement, like a receipt's: kept with the statement (not the test), audited."""
    from . import attachments as att_svc
    from .checkprint import service as cp
    doc = dn._donation_envelope(db, ctx, doc_id)
    if not doc.active:
        raise conflict("TEMPLATE_INACTIVE", "Choose an active envelope template.")
    cfg = cp.doc_config(doc)
    e = db.get(Entity, s.donor_entity_id)
    use_return = cfg.return_address if return_address is None else return_address
    to_lines = [e.legal_name] + address_lines(e)
    ret, to, empty = documents.envelope_lines(cfg, dn._envelope_values(db, ctx, None, e), to_lines, use_return)
    if not test:
        warnings = []
        if not to_lines[1:]:
            warnings.append(Warning_("NO_DONOR_ADDRESS", "The donor has no address. Add it to the donor's entity, or "
                                     "print the envelope with the name only?"))
        if empty:
            warnings.append(Warning_("EMPTY_VARIABLES", "These variables have no data: " +
                                     ", ".join("{" + v + "}" for v in empty) + ". Print anyway?", variables=empty))
        require_confirmations(warnings, confirmations)
    opt = cp.envelope_options(db, ctx, doc, {"page": page, "guide": guide})
    pdf = documents.envelope_pdf(cfg, ret, to, page=opt["page"], guide=opt["guide"], dx=opt["dx"], dy=opt["dy"],
                                 test=test)
    if test:
        audit.record(db, ctx, "DONATION_ENVELOPE_TEST", "donation_statement", s.id, None,
                     {"statement_id": s.id, "document_id": doc.id, "page": opt["page"], "guide": opt["guide"]})
        db.commit()
        return pdf
    copy_pdf = documents.envelope_pdf(cfg, ret, to, page="ENVELOPE")
    sha = hashlib.sha256(copy_pdf).hexdigest()
    path, added = None, False
    if db.scalar(select(Attachment).where(Attachment.donation_statement_id == s.id,
                                          Attachment.document_type == ENVELOPE_COPY,
                                          Attachment.sha256 == sha)) is None:
        key, path = att_svc._write_file(settings, copy_pdf)
        att = Attachment(workspace_id=ctx.workspace_id,
                         original_filename=att_svc.sanitize_filename(f"envelope-{s.number}.pdf"), storage_key=key,
                         mime_type="application/pdf", size_bytes=len(copy_pdf), sha256=sha,
                         uploaded_by_user_id=ctx.user.id, active=True, donation_statement_id=s.id,
                         document_type=ENVELOPE_COPY, system_generated=True)
        db.add(att)
        db.flush()
        audit.record(db, ctx, "ATTACHMENT_ADDED", "attachment", att.id, None, att_svc.snapshot(att))
        added = True
    audit.record(db, ctx, "DONATION_ENVELOPE_PRINTED", "donation_statement", s.id, None,
                 {"statement_id": s.id, "document_id": doc.id, "donor_entity_id": e.id, "return_address": use_return,
                  "page": opt["page"], "guide": opt["guide"], "attached": added})
    _commit(db, [path] if path is not None else [])
    return pdf


# ------------------------------------------------------------------ the donor giving report
def report(db: Session, ctx, start_year: int, end_year: int, donor_id: int | None = None,
           min_cents: int = 0) -> dict:
    start_year, end_year = _year(start_year), _year(end_year)
    if end_year < start_year:
        start_year, end_year = end_year, start_year
    if end_year - start_year + 1 > MAX_YEARS:
        raise validation(f"Choose at most {MAX_YEARS} years.", "end_year")
    if donor_id is not None:
        _donor(db, ctx, donor_id)
    years = list(range(start_year, end_year + 1))
    by_donor: dict[int, list[dict]] = {}
    for r in received_lines(db, ctx.workspace_id, start_year, end_year, donor_id):
        by_donor.setdefault(r["donor_id"], []).append(r)
    rows = []
    for did, lines in by_donor.items():
        e = db.get(Entity, did)
        per_year = {y: sum(r["amount_cents"] for r in lines if r["date"].year == y) for y in years}
        total = sum(per_year.values())
        if total < min_cents:
            continue
        items = [r for r in lines if r["kind"] == dn.ITEM]
        rows.append({"donor_id": did, "donor": e.display_name,
                     "years": {str(y): per_year[y] for y in years}, "total_cents": total, "gifts": len(lines),
                     "last_gift": max(r["date"] for r in lines).isoformat(), "items": len(items),
                     "item_value_cents": sum(r["item_value_cents"] for r in items),
                     "lines": [{**_row_out(r), "amount_cents": r["amount_cents"] if r["kind"] == dn.MONEY else None,
                                "item_value_cents": r["item_value_cents"] if r["kind"] == dn.ITEM else None}
                               for r in sorted(lines, key=lambda r: r["date"])]})
    rows.sort(key=lambda r: (-r["total_cents"], r["donor"].lower()))
    totals = {"years": {str(y): sum(r["years"][str(y)] for r in rows) for y in years},
              "total_cents": sum(r["total_cents"] for r in rows), "gifts": sum(r["gifts"] for r in rows),
              "items": sum(r["items"] for r in rows), "item_value_cents": sum(r["item_value_cents"] for r in rows)}
    return {"years": years, "rows": rows, "totals": totals, "min_cents": min_cents, "donor_id": donor_id}


def report_csv(rep: dict, detail_lines: bool) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    years = [str(y) for y in rep["years"]]

    def cell(v):                         # spreadsheet formula injection: text starting with = + - @ is quoted
        v = "" if v is None else str(v)
        return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v

    w.writerow(["Donor"] + years + ["Total", "Gifts", "Last gift", "Items", "Items estimated value (internal)"])
    for r in rep["rows"]:
        w.writerow([cell(r["donor"])] + [f"{r['years'][y] / 100:.2f}" for y in years] +
                   [f"{r['total_cents'] / 100:.2f}", r["gifts"], r["last_gift"], r["items"],
                    f"{r['item_value_cents'] / 100:.2f}"])
    t = rep["totals"]
    w.writerow(["Total"] + [f"{t['years'][y] / 100:.2f}" for y in years] +
               [f"{t['total_cents'] / 100:.2f}", t["gifts"], "", t["items"], f"{t['item_value_cents'] / 100:.2f}"])
    if detail_lines:
        w.writerow([])
        w.writerow(["Donor", "Date received", "Receipt No.", "Kind", "Description", "Amount",
                    "Item estimated value (internal)", "Goods or services", "Goods description"])
        for r in rep["rows"]:
            for x in r["lines"]:
                w.writerow([cell(r["donor"]), x["date"], cell(x["receipt"]), "Item" if x["kind"] == dn.ITEM else "Money",
                            cell(x["description"]),
                            f"{x['amount_cents'] / 100:.2f}" if x["amount_cents"] is not None else "",
                            f"{x['item_value_cents'] / 100:.2f}" if x["item_value_cents"] is not None else "",
                            cell(x["goods"] or ""), cell(x["goods_description"] or "")])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def report_pdf(db: Session, ctx, rep: dict, detail_lines: bool) -> bytes:
    """The donor giving report as a PDF in the organization's branding (#280): landscape, a column per year."""
    from . import branding
    from . import reports as rp
    with branding.use(db) as theme:
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.lib import colors
        ws = db.get(Workspace, ctx.workspace_id)
        years = [str(y) for y in rep["years"]]
        head = ["Donor"] + years + ["Total", "Gifts", "Last gift", "Items", "Items est. value"]
        data = [[rp.P(h, "cellb") for h in head]]
        for r in rep["rows"]:
            data.append([rp.P(r["donor"], "cellb")] + [rp.P(dn.money(r["years"][y]), "cellr") for y in years] +
                        [rp.P(dn.money(r["total_cents"]), "cellr"), rp.P(r["gifts"], "cellr"),
                         rp.P(r["last_gift"], "cell"), rp.P(r["items"], "cellr"),
                         rp.P(dn.money(r["item_value_cents"]), "cellr")])
            if detail_lines:
                for x in r["lines"]:
                    desc = ("Item: " if x["kind"] == dn.ITEM else "") + (x["description"] or "")
                    amt = x["amount"] or (dn.money(x["item_value_cents"]) + " est." if x["item_value_cents"] else "")
                    data.append([rp.P(f"   {x['date']}  {x['receipt'] or ''}  {desc}", "cell")]
                                + [rp.P("", "cell")] * len(years) + [rp.P(amt, "cellr")] + [rp.P("", "cell")] * 4)
        t = rep["totals"]
        data.append([rp.P("Total", "cellb")] + [rp.P(dn.money(t["years"][y]), "cellr") for y in years] +
                    [rp.P(dn.money(t["total_cents"]), "cellr"), rp.P(t["gifts"], "cellr"), rp.P("", "cell"),
                     rp.P(t["items"], "cellr"), rp.P(dn.money(t["item_value_cents"]), "cellr")])
        pw, ph = landscape(letter)
        width = pw - 2 * rp.MARGIN
        first = 2.6 * inch
        other = (width - first) / (len(head) - 1)
        tbl = rp._grid(data, [first] + [other] * (len(head) - 1))
        title = f"Donor giving report {years[0]}" + (f"–{years[-1]}" if len(years) > 1 else "")
        story = [rp.P(ws.name if ws else "", "h2"), rp.P(title, "h1"),
                 rp.P("Money received, by calendar year (the received date of each donation line). Items are counted "
                      "with their internal estimated value, for the organization's records only - it is never printed "
                      "on a letter to the donor." + (f" Donors giving at least {dn.money(rep['min_cents'])}."
                                                     if rep["min_cents"] else ""), "small"),
                 Spacer(1, 8), tbl]

        def on_page(c, doc):
            c.saveState()
            rp._brand_page(c, theme, pw, ph, first=doc.page == 1)
            c.setFont(rp._FONT, 7)
            c.setFillColor(colors.HexColor("#444444"))
            c.drawString(rp.MARGIN, 14, title)
            c.drawRightString(pw - rp.MARGIN, 14, f"Page {doc.page}")
            if theme.footer_text:
                c.drawString(rp.MARGIN, 23, theme.footer_text[:branding.FOOTER_MAX])
            c.restoreState()

        buf = io.BytesIO()
        SimpleDocTemplate(buf, pagesize=(pw, ph), leftMargin=rp.MARGIN, rightMargin=rp.MARGIN,
                          topMargin=rp.MARGIN, bottomMargin=rp.MARGIN, title=title, creator="PennyWarden",
                          invariant=1).build(story, onFirstPage=on_page, onLaterPages=on_page)
        return buf.getvalue()
