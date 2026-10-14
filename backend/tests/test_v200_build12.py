"""2.0.0 build 12 (#188): the readable audit log exported as CSV and a printable PDF."""
from __future__ import annotations

import csv
import io

from pypdf import PdfReader

from fmpoc.services import audit_export as ax

EXPORT = "/api/audit-events/export"


def rows(r) -> list[dict]:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    text = r.content.decode("utf-8")
    assert text.startswith("﻿")
    return list(csv.DictReader(io.StringIO(text[1:])))


def pdf_text(r) -> str:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)


def screen(client, **q) -> list[dict]:
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return client.get(f"/api/audit-events?limit=500&{qs}").json()["items"]


def test_csv_holds_the_same_entries_and_summaries_as_the_screen(env, base):
    acct = base["acct"]["id"]
    assert env.bm.patch(f"/api/bank-accounts/{acct}", {"account_name": "Main Checking"}).status_code == 200
    t = env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "12.50", "invoice_number": "A1"},
                                     {"budget_id": base["exp_leaf"], "amount": "7.25", "invoice_number": "A2"}])
    on_screen = screen(env.auditor, category="BUSINESS")
    r = env.auditor.post(EXPORT, {"format": "csv", "category": "BUSINESS", "time_zone": "America/Chicago"})
    got = rows(r)
    assert r.headers["x-entry-count"] == str(len(on_screen)) and len(got) == len(on_screen)
    assert [int(x["Event #"]) for x in got] == [e["id"] for e in on_screen]          # same entries, same order
    assert list(got[0]) == ["Event #", "Local time (America/Chicago)", "UTC time", "Actor", "Category", "Action",
                            "Object", "Object #", "Summary", "What changed"]
    by_id = {int(x["Event #"]): x for x in got}
    for e in on_screen:
        x = by_id[e["id"]]
        assert x["Action"] == e["readable"]["action_label"]
        assert e["readable"]["summary"].endswith(x["Summary"])
    upd = next(e for e in on_screen if e["action"] == "BANK_ACCOUNT_UPDATED")
    assert "Account name: " in by_id[upd["id"]]["What changed"] and "→ Main Checking (changed)" in by_id[upd["id"]]["What changed"]
    # the transaction's lines are flattened into the cell, with currency
    tx = next(e for e in on_screen if e["action"] == "TRANSACTION_CREATED" and e["object_id"] == str(t["id"]))
    cell = by_id[tx["id"]]["What changed"]
    assert "Line 1: " in cell and "Invoice number: A1" in cell and "$12.50" in cell and "Invoice number: A2" in cell
    assert "Total: $19.75" in cell and "→" not in cell and "Void reason" not in cell     # a new record: values only
    # the local time is in the chosen zone (CST/CDT), UTC alongside
    assert by_id[tx["id"]]["Local time (America/Chicago)"].endswith(("CDT", "CST"))
    assert by_id[tx["id"]]["UTC time"][:4] == by_id[tx["id"]]["Local time (America/Chicago)"][:4]


def test_filters_and_order_follow_the_screen(env, base):
    acct = base["acct"]["id"]
    for name in ("One", "Two"):
        env.bm.patch(f"/api/bank-accounts/{acct}", {"account_name": name})
    flt = {"action": "BANK_ACCOUNT_UPDATED", "direction": "asc"}
    got = rows(env.auditor.post(EXPORT, {"format": "csv", **flt}))
    assert [int(x["Event #"]) for x in got] == [e["id"] for e in screen(env.auditor, **flt)]
    assert all(x["Action"] == "Bank account updated" for x in got) and len(got) == 2
    assert got[0]["What changed"].count("→ One") == 1
    # unknown fields are refused (the same allowlists as the list)
    assert env.auditor.post(EXPORT, {"format": "csv", "sort": "password"}).status_code == 422
    assert env.auditor.post(EXPORT, {"format": "csv", "action": "x; drop"}).status_code == 422
    assert env.auditor.post(EXPORT, {"format": "xml"}).status_code == 422
    assert env.auditor.post(EXPORT, {"format": "csv", "evil": 1}).status_code == 422


def test_administrator_export_contains_no_financial_content(env, base):
    acct = base["acct"]["id"]
    env.bm.patch(f"/api/bank-accounts/{acct}", {"account_name": "Secret Savings Name"})
    env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "4321.99", "invoice_number": "INV-SECRET"}])
    got = rows(env.admin.post(EXPORT, {"format": "csv"}))
    blob = "\n".join(",".join(x.values()) for x in got)
    for secret in ("Secret Savings Name", "4,321.99", "4321.99", "INV-SECRET"):
        assert secret not in blob, secret
    withheld = [x for x in got if x["Object"] in ("Bank account", "Transaction")]
    assert withheld and all(x["What changed"] == "Financial content withheld for Administrators" for x in withheld)
    text = pdf_text(env.admin.post(EXPORT, {"format": "pdf"}))
    for secret in ("Secret Savings Name", "4,321.99", "INV-SECRET"):
        assert secret not in text, secret
    assert "withheld for Administrators" in text
    # the Auditor sees it
    assert "Secret Savings Name" in "\n".join(",".join(x.values()) for x in rows(env.auditor.post(EXPORT, {"format": "csv"})))


def test_export_is_audited_and_only_audit_viewers_may_export(env, base):
    r = env.auditor.post(EXPORT, {"format": "pdf", "category": "SECURITY", "date_from": "2020-01-01"})
    text = pdf_text(r)
    assert "Audit log export" in text and "Category: Security" in text and "From: 2020-01-01" in text
    assert r.headers["content-disposition"].startswith('attachment; filename="audit-log-')
    assert r.headers["content-disposition"].endswith('.pdf"') and r.headers["cache-control"] == "private, no-store"
    ev = screen(env.auditor, action="AUDIT_LOG_EXPORTED")
    assert ev and ev[0]["after"]["format"] == "PDF" and ev[0]["after"]["filters"]["category"] == "SECURITY"
    assert ev[0]["category"] == "SECURITY" and ev[0]["readable"]["action_label"] == "Audit log exported"
    assert ev[0]["after"]["entries"] >= 1
    for c in (env.bm, env.ru, env.bu):
        assert c.post(EXPORT, {"format": "csv"}).status_code == 403
    # a GET or a missing CSRF token is refused (it writes an audit record)
    assert env.auditor.get(EXPORT).status_code in (404, 405)
    assert env.auditor.c.post(EXPORT, json={"format": "csv"}).status_code == 403


def test_csv_cells_cannot_start_a_formula(env, base):
    r = env.bm.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "=HYPERLINK(\"http://x\")",
                                      "confirmations": ["DUPLICATE_ENTITY"]})
    assert r.status_code == 201, r.text
    got = rows(env.auditor.post(EXPORT, {"format": "csv", "action": "ENTITY_CREATED"}))
    x = next(x for x in got if "HYPERLINK" in x["Summary"] + x["What changed"])
    for v in x.values():
        assert not v or v[0] not in "=+-@", v


def test_too_many_entries_ask_to_narrow(env, base, monkeypatch):
    monkeypatch.setattr(ax, "MAX_EXPORT", 2)
    r = env.auditor.post(EXPORT, {"format": "csv"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "EXPORT_TOO_LARGE"
    assert "Narrow the filters" in r.json()["error"]["message"]
    assert not screen(env.auditor, action="AUDIT_LOG_EXPORTED")      # nothing exported, nothing recorded


def test_unknown_time_zone_falls_back_to_utc(env, base):
    got = rows(env.auditor.post(EXPORT, {"format": "csv", "time_zone": "Mars/Olympus"}))
    assert got[0]["Local time (UTC)"].endswith("UTC") and got[0]["UTC time"]
    assert ax.zone("Mars/Olympus")[1] == "UTC" and ax.zone(None)[1] == "UTC"
    assert env.auditor.post(EXPORT, {"format": "csv", "time_zone": "../../etc/passwd"}).status_code == 422


def test_pdf_lists_entries_with_what_changed(env, base):
    acct = base["acct"]["id"]
    env.bm.patch(f"/api/bank-accounts/{acct}", {"account_name": "Renamed Account"})
    text = pdf_text(env.auditor.post(EXPORT, {"format": "pdf", "action": "BANK_ACCOUNT_UPDATED"}))
    assert "Bank account updated" in text and "Renamed Account" in text and "changed" in text
    assert "Entries 1" in text.replace("\n", " ") and "Page 1" in text
    empty = pdf_text(env.auditor.post(EXPORT, {"format": "pdf", "action": "NOTHING_LIKE_THIS"}))
    assert "No entries match the filters." in empty


def test_pdf_with_entries_longer_than_a_page():
    """A transaction with many lines (and a huge one) must not break the PDF: tables split, long cells are cut."""
    import datetime as _dt
    lines = [{"budget_id": 1, "amount_cents": 100 + i, "invoice_number": f"INV-{i}", "description": "x" * 200}
             for i in range(60)]
    r = {"action_label": "Transaction created", "summary": "a: Transaction created — transaction #1", "kind": "create",
         "changes": [{"field": "allocations", "label": "Lines", "changed": False, "before_table": None,
                      "after_table": {"columns": ["Invoice number", "Description"],
                                      "rows": [[x["invoice_number"], x["description"]] for x in lines]}}]
         + [{"field": f"f{i}", "label": f"Field {i}", "changed": True, "before": "a" * 300, "after": "b" * 300}
            for i in range(40)]}
    e = {"id": 1, "action": "X", "object_type": "register_transaction", "object_id": "1", "category": "BUSINESS",
         "actor_username": "a", "actor_name": None, "snapshots_withheld": False, "readable": r,
         "_ts": _dt.datetime(2026, 1, 1)}
    pdf = ax.to_pdf([e, e], *ax.zone("UTC"), org="Org", exported_by="a", filters=[], total=2)
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) > 3
    assert "more characters in the CSV export" in "".join(p.extract_text() for p in reader.pages)
