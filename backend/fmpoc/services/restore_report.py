"""2.0.0 (#124): the restore re-entry report.

Before a restore replaces the data, the transactions that exist only in the data being replaced - entered, edited,
voided or deleted after the backup was made (by the immutable entry timestamp and the last change) - are written to a
CSV file in `restore-reports/` in the data folder, outside the database, so they can be entered again. Other records
(Fiscal Years, budgets, entities, bank accounts) created after the backup are summarized by count and name.

The report is financial data: only the roles that can read the register download it (`financial.view`); the
Administrator who ran the restore and the command line see only the summary counts (BR-003). Account numbers are
masked; text cells that could start a spreadsheet formula are escaped. Reports are kept until the server owner
removes them.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
import sqlite3
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (Attachment, BankAccount, Budget, Entity, FiscalYear, Invoice, RegisterTransaction,
                      TransactionAllocation, User, Workspace)
from .reports import _csv_safe

REPORT_DIR = "restore-reports"
NAME_RE = re.compile(r"^restore-report-\d{8}-\d{6}(-\d+)?\.csv$")
COLUMNS = ["Change", "Transaction date", "Entry timestamp (UTC)", "Entered by", "Bank account", "Type", "Payee",
           "Transaction total", "Fiscal Year", "Budget ID", "Budget", "Amount", "Invoice number", "Description",
           "Clear date", "Status", "Void reason", "Attachments"]


def _money(c: int | None) -> str:
    if c is None:
        return ""
    sign = "-" if c < 0 else ""
    c = abs(c)
    return f"{sign}{c // 100}.{c % 100:02d}"


def _parse_ts(s) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "").replace("T", " ").split("+")[0])
    except ValueError:
        return None


def _backup_state(backup_db: Path) -> tuple[dict, str | None]:
    """{transaction id: (status, last change)} and the key check value of the backup's database - minimal SQL on
    columns every version has, so a backup from an older version can be compared too."""
    con = sqlite3.connect(f"file:{backup_db.as_posix()}?mode=ro", uri=True)
    try:
        rows = {r[0]: (r[1], _parse_ts(r[2])) for r in con.execute(
            "SELECT id, status, updated_at FROM register_transaction")}
        for tid, upd in con.execute("SELECT transaction_id, MAX(updated_at) FROM transaction_allocation "
                                    "GROUP BY transaction_id"):
            if tid in rows and upd:
                st, last = rows[tid]
                u = _parse_ts(upd)
                rows[tid] = (st, max(x for x in (last, u) if x is not None) if (last or u) else None)
        key = con.execute("SELECT key_check FROM workspace ORDER BY id LIMIT 1").fetchone()
        return rows, key[0] if key else None
    finally:
        con.close()


def _last_change(t: RegisterTransaction) -> dt.datetime:
    times = [t.updated_at, t.voided_at, t.deleted_at] + [a.updated_at for a in t.allocations]
    return max(x for x in times if x is not None)


def build(db: Session, ws_id: int, backup_db: Path, backup_created_at: str | None, out_dir: Path,
          now: dt.datetime | None = None) -> dict:
    """Compares the current database (db) with the backup's and writes the report. Returns the summary (no
    financial values): {"report": file name or None, "transactions": n, "allocations": n, "by_change": {...},
    "other": {...}, "by_time_only": bool}."""
    created = _parse_ts(backup_created_at) or dt.datetime.min
    ws = db.get(Workspace, ws_id)
    try:
        backup_rows, backup_key = _backup_state(backup_db)
    except sqlite3.Error:
        backup_rows, backup_key = {}, None
    by_time_only = bool(ws and backup_key != ws.key_check)       # a backup from another system: ids mean nothing
    users = {u.id: (f"{u.first_name} {u.last_name} - {u.username}" if getattr(u, "first_name", None) and
                    getattr(u, "last_name", None) else u.username) for u in db.scalars(select(User))}
    changed: list[tuple[str, RegisterTransaction]] = []
    for t in db.scalars(select(RegisterTransaction).where(RegisterTransaction.workspace_id == ws_id)
                        .order_by(RegisterTransaction.transaction_date, RegisterTransaction.id)):
        last = _last_change(t)
        if by_time_only or t.id not in backup_rows:
            if t.entry_timestamp > created:
                changed.append(("NEW", t))
            elif by_time_only and last > created:
                changed.append(("EDITED", t))
            continue
        b_status, b_last = backup_rows[t.id]
        if t.status != b_status and t.status == "VOID":
            changed.append(("VOIDED", t))
        elif t.status != b_status and t.status == "DELETED":
            changed.append(("DELETED", t))
        elif last > created and (b_last is None or last > b_last):
            changed.append(("EDITED", t))
    other = {}
    for label, model, name in (("fiscal_years", FiscalYear, lambda x: x.identifier),
                               ("budgets", Budget, lambda x: f"{x.parent_code}{'-' + x.child_code if x.child_code else ''} {x.name}"),
                               ("entities", Entity, lambda x: x.display_name),
                               ("bank_accounts", BankAccount, lambda x: x.account_name),
                               # 2.4.0 (#255): invoices made after the backup are re-entered too
                               ("invoices", Invoice, lambda x: f"{x.number}{'-R' + str(x.revision) if x.revision else ''}")):
        new = [r for r in db.scalars(select(model).where(model.workspace_id == ws_id, model.created_at > created))]
        if new:
            other[label] = {"count": len(new), "names": [str(name(x))[:120] for x in new[:50]]}
    by_change: dict[str, int] = {}
    for c, _t in changed:
        by_change[c] = by_change.get(c, 0) + 1
    summary = {"report": None, "transactions": len(changed), "allocations": 0, "by_change": by_change,
               "other": other, "by_time_only": by_time_only, "backup_created_at": backup_created_at}
    if not changed and not other:
        return summary
    accounts = {a.id: a for a in db.scalars(select(BankAccount).where(BankAccount.workspace_id == ws_id))}
    fys = {f.id: f.identifier for f in db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ws_id))}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    if by_time_only:
        w.writerow(["Note: the backup came from another system - changes are found by time only "
                    f"(entered or changed after {backup_created_at})."])
    w.writerow([f"Restore re-entry report: data entered or changed after the backup of {backup_created_at}"])
    w.writerow(COLUMNS)
    n_alloc = 0
    for change, t in changed:
        acct = accounts.get(t.bank_account_id)
        acct_text = f"{acct.account_name} (****{acct.account_number_visible_suffix})" if acct else ""
        files = [a.original_filename for a in db.scalars(select(Attachment).where(
            Attachment.transaction_id == t.id, Attachment.active.is_(True)))]
        allocs = [a for a in t.allocations if a.removed_at is None] or [None]
        total = sum(a.amount_cents for a in t.allocations if a.removed_at is None)
        for a in allocs:
            b = a.budget if a is not None else None
            w.writerow([_csv_safe(x) for x in (
                change, t.transaction_date.isoformat(), t.entry_timestamp.replace(microsecond=0).isoformat(),
                users.get(t.created_by_user_id, ""), acct_text, t.transaction_type,
                t.parent_entity.display_name if t.parent_entity else "", _money(total),
                fys.get(b.fiscal_year_id, "") if b else "", b.id if b else "",
                f"{b.parent_code}{'-' + b.child_code if b.child_code else ''} {b.name}" if b else "",
                _money(a.amount_cents) if a else "", (a.invoice_number or "") if a else "",
                (a.description or "") if a else "", t.clear_date.isoformat() if t.clear_date else "", t.status,
                t.void_reason or t.delete_reason or "", "; ".join(files))])
            n_alloc += 1
    if other:
        w.writerow([])
        w.writerow(["Other records created after the backup"])
        for label, v in other.items():
            w.writerow([_csv_safe(label.replace("_", " ").capitalize()), v["count"], _csv_safe("; ".join(v["names"]))])
    out_dir.mkdir(parents=True, exist_ok=True)
    now = now or dt.datetime.utcnow()
    name = f"restore-report-{now:%Y%m%d-%H%M%S}.csv"
    i = 1
    while (out_dir / name).exists():
        i += 1
        name = f"restore-report-{now:%Y%m%d-%H%M%S}-{i}.csv"
    (out_dir / name).write_text("﻿" + buf.getvalue(), encoding="utf-8")
    summary.update(report=name, allocations=n_alloc)
    (out_dir / (name[:-4] + ".json")).write_text(json.dumps({**summary, "created_at": now.isoformat() + "Z"},
                                                            indent=1), encoding="utf-8")
    return summary


def summary_text(s: dict) -> str:
    if not s or (not s.get("transactions") and not s.get("other")):
        return "Nothing was entered or changed after the backup was made."
    parts = []
    if s.get("transactions"):
        parts.append(f"{s['transactions']} transaction(s) entered or changed after the backup")
    for label, v in (s.get("other") or {}).items():
        parts.append(f"{v['count']} {label.replace('_', ' ')}")
    return ("; ".join(parts) + " are in the restore re-entry report " + (s.get("report") or "") +
            ". Budget Managers, Budget Users, Register Users and Auditors can download it (Reports).")


def list_reports(settings) -> list[dict]:
    d = settings.data_dir / REPORT_DIR
    out = []
    if d.is_dir():
        for p in sorted(d.glob("restore-report-*.csv"), reverse=True):
            if not NAME_RE.match(p.name):
                continue
            meta = {}
            j = p.with_suffix(".json")
            if j.is_file():
                try:
                    meta = json.loads(j.read_text(encoding="utf-8"))
                except ValueError:
                    meta = {}
            out.append({"name": p.name, "size": p.stat().st_size, "created_at": meta.get("created_at"),
                        "backup_created_at": meta.get("backup_created_at"), "transactions": meta.get("transactions"),
                        "by_time_only": meta.get("by_time_only", False)})
    return out


def report_path(settings, name: str) -> Path | None:
    if not NAME_RE.match(name or ""):
        return None
    p = settings.data_dir / REPORT_DIR / name
    return p if p.is_file() else None
