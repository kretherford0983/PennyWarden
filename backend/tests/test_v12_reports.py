"""v1.2 CR-002 reports: End of Year Audit PDF and Entity activity report."""
import csv
import io
import re

from conftest import png_bytes
from pypdf import PdfReader
from reportlab.pdfgen import canvas


def make_pdf(marker: str, pages: int = 2) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i in range(pages):
        c.drawString(72, 700, f"{marker} page {i + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


def up(env, owner_type, owner_id, name, data, client=None):
    c = client or env.ru
    r = c.c.post(f"/api/attachments?owner_type={owner_type}&owner_id={owner_id}", files={"file": (name, data)},
                 headers={"X-CSRF-Token": c.csrf})
    assert r.status_code == 201, r.text
    return r.json()


def page_texts(pdf_bytes: bytes) -> list[str]:
    return [p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf_bytes)).pages]


def first_page(texts, needle):
    return next(i for i, t in enumerate(texts) if needle in t)


def heading_page(texts, txn_id):
    """The page whose heading is "Transaction #n" (with " — VOID" on the same line since pypdf 7's text extraction)."""
    return next(i for i, t in enumerate(texts) if has_heading(t, txn_id))


def has_heading(text, txn_id):
    return re.search(rf"Transaction #{txn_id}(?: — VOID)?\n", text) is not None


def test_cr002_audit_report_structure_and_attachment_order(env, base):
    fy = base["fy"]["id"]
    a = base["acct"]["id"]
    vendor = env.entity("<img src='/etc/passwd'/> Vendor & Co")
    t1 = env.txn(a, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "12.34", "description": "Office rent Aug",
                                     "notes": "Paid by check"}], entity_id=vendor["id"], check_number="1001",
                 date="2026-08-01", clear_date="2026-08-03", notes="Parent note <b>not bold</b>")
    up(env, "transaction", t1["id"], "rent-invoice.pdf", make_pdf("RENTINVOICE", pages=2))
    up(env, "transaction", t1["id"], "receipt.png", png_bytes((300, 200)))
    t2 = env.txn(a, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "50.00", "description": "Gift"}],
                 date="2026-09-01")
    up(env, "allocation", t2["allocations"][0]["id"], "gift-letter.pdf", make_pdf("GIFTLETTER", pages=1))
    t3 = env.txn(a, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "0.42", "description": "Interest"}],
                 date="2026-09-30", no_attachment=True, no_attachment_reason="Bank interest")
    v = env.txn(a, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "5.00"}], date="2026-10-01")
    env.ru.post(f"/api/transactions/{v['id']}/void", {"reason": "Duplicate", "confirm_irreversible": True})
    outside = env.txn(a, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "1.00"}], date="2025-12-01",
                      confirmations=["NO_FISCAL_YEAR"])  # cross-FY: dated outside, allocated to this FY
    up(env, "fiscal_year", fy, "board-minutes.pdf", make_pdf("BOARDMINUTES", pages=1), client=env.bm)

    r = env.auditor.get(f"/api/reports/audit?fiscal_year_id={fy}")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert "inline" in r.headers["content-disposition"] and "FY2027-end-of-year-audit-report.pdf" in r.headers["content-disposition"]
    import os
    if os.environ.get("FM_DUMP_PDF"):
        open(os.environ["FM_DUMP_PDF"], "wb").write(r.content)
    texts = page_texts(r.content)
    joined = "\n".join(texts)
    # page 1 title, page 2 Fiscal Year Review introduction, page 3.. budgets
    assert "End of Year Audit Report" in texts[0] and "Fiscal Year FY2027" in texts[0] and "Budgets" not in texts[0]
    assert "Fiscal Year Review" in texts[1] and "Documentation review" in texts[1] and "Closure readiness" in texts[1]
    assert "Fiscal Year Budgets" in texts[2] and "1000 Operations" in texts[2] and "4000 Donations" in texts[2]
    # every transaction (incl. VOID and the cross-FY one) starts its own page, in date order within the account
    order = [heading_page(texts, t["id"]) for t in (outside, t1, t2, t3, v)]
    assert order == sorted(order) and len(set(order)) == 5 and order[0] > 2
    for i in order:
        head = texts[i].split("\n")[0]
        assert head.startswith("Transaction #")
        for field in ("Transaction date", "Entity", "Transaction type", "Amount", "Description", "Clear Date", "Notes"):
            assert field in texts[i], (i, field)
    # t1's attachments are rendered (not just listed) after t1's details and before t2
    p_t1, p_t2 = order[1], order[2]
    p_inv = first_page(texts, "RENTINVOICE page 1")
    assert p_t1 <= p_inv < p_t2 and "RENTINVOICE page 2" in texts[p_inv + 1]
    p_png = first_page(texts, "Attachment 2 of 2 (transaction)")
    assert p_inv < p_png < p_t2
    # allocation attachment is drawn under t2's details
    assert p_t2 <= first_page(texts, "GIFTLETTER page 1") < order[3]
    t1_page = texts[p_t1]
    assert "Office rent Aug" in t1_page and "2026-08-03" in t1_page and "Withdrawal" in t1_page and "$12.34" in t1_page
    for s_ in ["Paid by check", "1001", "rent-invoice.pdf", "SHA-256 verified"]:
        assert s_ in joined
    assert "<img src='/etc/passwd'/> Vendor & Co" in t1_page  # user markup rendered literally, not interpreted
    assert "Parent note <b>not bold</b>" in t1_page
    assert "Bank interest" in texts[order[3]] and "VOID" in texts[order[4]] and "Duplicate" in texts[order[4]]
    # v1.3 (Q5): Fiscal Year documents are no longer part of the audit report (they are in the Close report)
    assert "BOARDMINUTES" not in joined
    # footers
    assert f"Page 1 of {len(texts)}" in texts[0] and f"Page {len(texts)} of {len(texts)}" in texts[-1]
    # audited
    ev = env.auditor.get("/api/audit-events?action=REPORT_GENERATED").json()["items"][0]
    assert ev["after"]["report"] == "END_OF_YEAR_AUDIT" and ev["after"]["transactions"] == 5


def test_cr002_audit_report_account_filter_void_toggle_and_empty(env, base):
    fy = base["fy"]["id"]
    other = env.account(opening="0.00")
    env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "3.00"}])
    t = env.txn(other["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "4.00"}])
    env.ru.post(f"/api/transactions/{t['id']}/void", {"reason": "x", "confirm_irreversible": True})
    j = "\n".join(page_texts(env.bu.get(f"/api/reports/audit?fiscal_year_id={fy}&bank_account_id={other['id']}").content))
    assert has_heading(j, t["id"]) and not has_heading(j, 1)
    j = "\n".join(page_texts(env.bu.get(f"/api/reports/audit?fiscal_year_id={fy}&bank_account_id={other['id']}"
                                        f"&include_void=false").content))
    assert "No transactions for this Fiscal Year." in " ".join(j.split())
    empty = env.fy("2029", "2028-07-01", "2029-06-30", confirmations=["FY_GAP"])
    r = env.bu.get(f"/api/reports/audit?fiscal_year_id={empty['id']}&download=true")
    assert r.status_code == 200 and "attachment;" in r.headers["content-disposition"]


def test_cr002_audit_report_bad_pdf_attachment_is_placeholder(env, base, settings):
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "3.00"}])
    att = up(env, "transaction", t["id"], "odd.pdf", b"%PDF-1.4\nthis is not a real pdf body\n%%EOF\n")
    r = env.bu.get(f"/api/reports/audit?fiscal_year_id={base['fy']['id']}")
    assert r.status_code == 200
    j = "\n".join(page_texts(r.content))
    assert "could not be embedded" in j and att["sha256"] in j.replace("\n", "")


def test_cr002_report_permissions(env, base):
    fy = base["fy"]["id"]
    assert env.admin.get(f"/api/reports/audit?fiscal_year_id={fy}").status_code == 403
    assert env.admin.get(f"/api/reports/entity-activity?fiscal_year_id={fy}").status_code == 403
    from conftest import Api
    assert Api(env.app).get(f"/api/reports/audit?fiscal_year_id={fy}").status_code == 401
    assert env.bu.get("/api/reports/audit?fiscal_year_id=99999").status_code == 404
    for c in (env.bm, env.bu, env.ru, env.auditor):
        assert c.get(f"/api/reports/entity-activity?fiscal_year_id={fy}").status_code == 200


def test_cr002_entity_activity_report(env, base):
    a = base["acct"]["id"]
    other_acct = env.account(opening="0.00")
    acme = env.entity("Acme Supply")
    donor = env.entity("Jane Donor", "INDIVIDUAL")
    evil = env.entity("=HYPERLINK(\"http://x\")")
    env.txn(a, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "100.00"}], entity_id=acme["id"], date="2026-08-01")
    env.txn(a, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "25.50"}], entity_id=acme["id"], date="2026-09-01")
    env.txn(a, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "10.00"}], entity_id=acme["id"], date="2026-09-02")
    # split deposit: per-allocation entities are credited individually
    env.txn(a, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "40.00", "entity_id": donor["id"]},
                           {"budget_id": base["inc_leaf"], "amount": "7.00", "entity_id": acme["id"]}], date="2026-09-03")
    env.txn(a, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "1.00"}], entity_id=evil["id"], date="2026-09-04")
    env.txn(a, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "0.25"}], date="2026-09-05")  # no entity
    v = env.txn(a, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "999.00"}], entity_id=acme["id"], date="2026-09-06")
    env.ru.post(f"/api/transactions/{v['id']}/void", {"reason": "x", "confirm_irreversible": True})
    env.txn(a, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "77.00"}], entity_id=acme["id"], date="2027-08-01",
            confirmations=["NO_FISCAL_YEAR"])  # out of range
    env.txn(other_acct["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "3.00"}], entity_id=acme["id"],
            date="2026-09-07")  # other account
    env.ru.post("/api/transfers", {"from_account_id": a, "to_account_id": other_acct["id"], "amount": "60.00",
                                   "transaction_date": "2026-09-08"})
    q = f"/api/reports/entity-activity?bank_account_id={a}&date_from=2026-07-01&date_to=2027-06-30"
    rep = env.bu.get(q + "&details=true").json()
    rows = {r["label"]: r for r in rep["rows"]}
    assert rows["Acme Supply"]["withdrawals"] == "125.50" and rows["Acme Supply"]["deposits"] == "17.00"
    assert rows["Acme Supply"]["withdrawal_count"] == 2 and rows["Acme Supply"]["deposit_count"] == 2
    assert rows["Acme Supply"]["net"] == "-108.50" and len(rows["Acme Supply"]["lines"]) == 4
    assert rows["Jane Donor"]["deposits"] == "40.00" and rows["Jane Donor"]["withdrawals"] == "0.00"
    assert rows["(No entity)"]["deposits"] == "0.25"
    assert rows["(Transfers between accounts)"]["withdrawals"] == "60.00"
    assert "Multiple" not in rows
    assert rep["totals"]["deposits"] == "58.25" and rep["totals"]["withdrawals"] == "125.50"
    # entity filter and all-accounts
    one = env.bu.get(q + f"&entity_id={acme['id']}").json()
    assert [r["label"] for r in one["rows"]] == ["Acme Supply"]
    allacc = {r["label"]: r for r in env.bu.get("/api/reports/entity-activity?date_from=2026-07-01&date_to=2027-06-30").json()["rows"]}
    assert allacc["Acme Supply"]["withdrawals"] == "128.50"
    # fiscal year shortcut
    fyrep = {r["label"]: r for r in env.bu.get(f"/api/reports/entity-activity?bank_account_id={a}&fiscal_year_id={base['fy']['id']}").json()["rows"]}
    assert fyrep["Acme Supply"]["withdrawals"] == "125.50"
    # CSV export with formula-injection protection
    r = env.bu.get(q + "&format=csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows_csv = list(csv.reader(io.StringIO(r.text)))
    assert rows_csv[0][0] == "Entity"
    labels = [row[0] for row in rows_csv[1:] if row]
    assert "'=HYPERLINK(\"http://x\")" in labels and "=HYPERLINK(\"http://x\")" not in labels
    # validation
    assert env.bu.get(f"/api/reports/entity-activity?bank_account_id={a}").status_code == 422
    assert env.bu.get("/api/reports/entity-activity?date_from=2026-09-01&date_to=2026-01-01").status_code == 422
    assert env.bu.get("/api/reports/entity-activity?date_from=2026-09-01&date_to=2026-10-01&format=xml").status_code == 422
    assert env.bu.get("/api/reports/entity-activity?bank_account_id=99999&date_from=2026-09-01&date_to=2026-10-01").status_code == 422


def test_cr002_attachments_rendered_within_letter_page_width(env, base):
    """v1.2.1: every page is US Letter; wide images and landscape/odd-size PDFs are scaled into the page width."""
    from reportlab.lib.pagesizes import landscape, legal, letter
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "9.00",
                                                    "description": "Wide docs"}])
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(legal))
    c.drawString(72, 300, "LANDSCAPEDOC page 1")
    c.save()
    up(env, "transaction", t["id"], "landscape.pdf", buf.getvalue())
    up(env, "transaction", t["id"], "wide.png", png_bytes((2400, 600)))
    pdf = env.bu.get(f"/api/reports/audit?fiscal_year_id={base['fy']['id']}").content
    reader = PdfReader(io.BytesIO(pdf))
    assert all((round(float(p.mediabox.width)), round(float(p.mediabox.height))) == (round(letter[0]), round(letter[1]))
               for p in reader.pages)
    texts = [p.extract_text() or "" for p in reader.pages]
    p_t = heading_page(texts, t["id"])
    # the landscape PDF is drawn on the transaction's own page, under the details
    assert "LANDSCAPEDOC page 1" in texts[p_t] and "Wide docs" in texts[p_t]
    assert any("Attachment 2 of 2 (transaction)" in x for x in texts[p_t:])
