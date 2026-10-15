"""2.0.0 build 3 (#165, #166): invoice dates, cover letters, #10 envelopes, handwritten checks."""
import io

from pypdf import PdfReader

from tests.test_v200_checks import PRESET, enable, has_image, make_signer


def text(pdf: bytes) -> str:
    return " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


def vendor(env):
    r = env.ru.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "Sample Vendor Company",
                                      "address_line1": "123 Main Street", "address_line2": "P.O. Box 123",
                                      "city": "Sample Town", "state_region": "US", "postal_code": "55555",
                                      "confirmations": ["DUPLICATE_ENTITY"]})
    assert r.status_code == 201, r.text
    return r.json()


def setup_docs(env):
    letter = env.admin.post("/api/checks/documents", {"kind": "LETTER"}).json()
    cfg = letter["config"]
    cfg["letterhead"] = ["{ORG}", "789 Sample Street", "Sample Town, US 12345", "office@example.org"]
    cfg["fallback_name"], cfg["fallback_role"] = "Pat Example", "Treasurer, {ORG}"
    letter = env.admin.put(f"/api/checks/documents/{letter['id']}", {"name": letter["name"], "config": cfg}).json()
    env_ = env.admin.post("/api/checks/documents", {"kind": "ENVELOPE"}).json()
    return letter, env_


def test_invoice_date_on_withdrawal_lines(env, base):
    acct = base["acct"]["id"]
    t = env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "10.00", "invoice_number": "A1",
                                      "invoice_date": "2026-08-29"}])
    assert t["allocations"][0]["invoice_date"] == "2026-08-29"
    r = env.ru.patch(f"/api/transactions/{t['id']}", {"allocations": [{"id": t["allocations"][0]["id"],
                     "budget_id": base["exp_leaf"], "amount": "10.00", "invoice_date": "2026-09-01"}]})
    assert r.status_code == 200 and r.json()["allocations"][0]["invoice_date"] == "2026-09-01"
    r = env.txn(acct, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "5.00", "invoice_date": "2026-08-29"}],
                expect=422)
    assert "Invoice date" in r["error"]["message"]


def test_templates_setup_and_test_prints(env, base):
    enable(env)
    letter, envelope = setup_docs(env)
    assert letter["is_default"] and envelope["is_default"]
    cols = [(c["key"], c["heading"]) for c in letter["config"]["columns"]]
    assert cols == [("INVOICE", "Invoice #"), ("INVOICE_DATE", "Invoice Date"), ("AMOUNT", "Amount Due")]
    # the envelope's return address starts as the default letter's letterhead; off by default
    assert envelope["config"]["return_lines"][:2] == ["{ORG}", "789 Sample Street"]
    assert envelope["config"]["return_address"] is False
    assert (envelope["config"]["width"], envelope["config"]["height"]) == (9.5, 4.125)
    # validation: unknown variables, duplicate columns, unknown settings
    bad = dict(letter["config"], subject="{dtae}")
    r = env.admin.put(f"/api/checks/documents/{letter['id']}", {"name": "x", "config": bad})
    assert r.status_code == 422 and "Did you mean {DATE}" in r.json()["error"]["message"]
    bad = dict(letter["config"], columns=[{"key": "AMOUNT", "heading": "A"}, {"key": "AMOUNT", "heading": "B"}])
    assert env.admin.put(f"/api/checks/documents/{letter['id']}", {"name": "x", "config": bad}).status_code == 422
    assert env.admin.put(f"/api/checks/documents/{letter['id']}",
                         {"name": "x", "config": dict(letter["config"], evil=1)}).status_code == 422
    # a second letter can become the default; deactivated templates are kept
    l2 = env.admin.post("/api/checks/documents", {"kind": "LETTER", "name": "Refund letter"}).json()
    assert l2["is_default"] is False
    assert env.admin.post(f"/api/checks/documents/{l2['id']}/flags", {"is_default": True}).json()["is_default"]
    docs = {d["id"]: d for d in env.admin.get("/api/checks/setup").json()["documents"]}
    assert docs[letter["id"]]["is_default"] is False
    # test prints use sample data only
    t = text(env.admin.post(f"/api/checks/documents/{letter['id']}/test-print", {}).content)
    assert "SAMPLE VENDOR COMPANY" in t and "Total Payment Enclosed:" in t and "158092" in t
    t = text(env.admin.post(f"/api/checks/documents/{envelope['id']}/test-print", {}).content)
    assert "ENVELOPE TEST" in t and "SAMPLE VENDOR COMPANY" in t
    for c in (env.ru, env.bm, env.auditor):
        assert c.post("/api/checks/documents", {"kind": "LETTER"}).status_code == 403


def test_letter_envelope_and_handwritten_check(env, base):
    enable(env)
    style = env.admin.post("/api/checks/styles", {"preset_key": PRESET}).json()
    letter, envelope = setup_docs(env)
    signer = make_signer(env, "Jordan Sample", "Treasurer")
    v = vendor(env)
    acct = base["acct"]["id"]
    t = env.txn(acct, "WITHDRAWAL", [
        {"budget_id": base["exp_leaf"], "amount": "153.44", "invoice_number": "158092", "invoice_date": "2026-08-29"},
        {"budget_id": base["exp_leaf"], "amount": "46.56", "invoice_number": "158117"}], entity_id=v["id"])
    env.ru.put(f"/api/checks/accounts/{acct}", {"check_style_id": style["id"]})
    tid = t["id"]
    docs = env.ru.get(f"/api/checks/transactions/{tid}/documents").json()
    assert [d["id"] for d in docs["letters"]] == [letter["id"]] and docs["envelopes"][0]["printer"]["page"] == "LETTER"
    assert env.ru.get(f"/api/checks/transactions/{tid}/options").json()["has_documents"] is True
    # handwritten check: the number is recorded (confirmed twice, unique), nothing printed or counted
    r = env.ru.post(f"/api/checks/transactions/{tid}/handwritten", {"check_number": "3001", "confirm_check_number": "3002"})
    assert r.json()["error"]["code"] == "CHECK_NUMBER_MISMATCH"
    assert env.ru.post(f"/api/checks/transactions/{tid}/handwritten",
                       {"check_number": "3001", "confirm_check_number": "3001"}).json()["check_number"] == "3001"
    other = env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "1.00"}], entity_id=v["id"])
    assert env.ru.post(f"/api/checks/transactions/{other['id']}/handwritten",
                       {"check_number": "3001", "confirm_check_number": "3001"}).json()["error"]["code"] == \
        "DUPLICATE_CHECK_NUMBER"
    assert env.ru.get(f"/api/checks/transactions/{tid}/options").json()["sheet_remaining"] == 3
    # letter: letterhead, payee address, table with invoice dates, total, the check's signer; attached once
    body = {"document_id": letter["id"], "signer_id": signer["id"]}
    pdf = env.ru.post(f"/api/checks/transactions/{tid}/letter", body).content
    tx = text(pdf)
    for s in ("Acme Org", "789 Sample Street", "Sample Vendor Company", "123 Main Street", "Sample Town, US 55555",
              "Invoice #", "158092", "08/29/2026", "$153.44", "158117", "$46.56", "Total Payment Enclosed: $200.00",
              "Jordan Sample", "Treasurer, Acme Org", "Sincerely,"):
        assert s in tx, s
    assert not has_image(pdf) and "98765432" not in tx
    assert env.ru.post(f"/api/checks/transactions/{tid}/letter", body).status_code == 200
    atts = env.auditor.get(f"/api/attachments?owner_type=transaction&owner_id={tid}").json()
    assert [a["original_filename"] for a in atts] == ["letter-3001.pdf"]
    # no signer: the template's fallback name and role
    tx = text(env.ru.post(f"/api/checks/transactions/{tid}/letter", {"document_id": letter["id"]}).content)
    assert "Pat Example" in tx and "Treasurer, Acme Org" in tx
    # empty variables need confirming
    cfg = dict(letter["config"], subject="Payment {NOTES}")
    env.admin.put(f"/api/checks/documents/{letter['id']}", {"name": letter["name"], "config": cfg})
    r = env.ru.post(f"/api/checks/transactions/{tid}/letter", body)
    assert r.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert env.ru.post(f"/api/checks/transactions/{tid}/letter", {**body, "confirmations": ["EMPTY_VARIABLES"]}
                       ).status_code == 200
    # envelope: delivery address, optional return address; the test page is not attached
    eb = {"document_id": envelope["id"]}
    tx = text(env.ru.post(f"/api/checks/transactions/{tid}/envelope-test", eb).content)
    assert "ENVELOPE TEST" in tx and "Sample Vendor Company" in tx
    tx = text(env.ru.post(f"/api/checks/transactions/{tid}/envelope", eb).content)
    assert "Sample Vendor Company" in tx and "789 Sample Street" not in tx
    tx = text(env.ru.post(f"/api/checks/transactions/{tid}/envelope", {**eb, "return_address": True}).content)
    assert "789 Sample Street" in tx
    names = [a["original_filename"] for a in env.ru.get(f"/api/attachments?owner_type=transaction&owner_id={tid}").json()]
    assert names.count("envelope-3001.pdf") == 2 and "envelope-test.pdf" not in names
    # a payee without an address needs confirming
    nobody = env.entity("No Address Supplier")
    t2 = env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "5.00"}], entity_id=nobody["id"])
    assert env.ru.post(f"/api/checks/transactions/{t2['id']}/envelope", eb).json()["error"]["warnings"][0]["code"] \
        == "NO_PAYEE_ADDRESS"
    # personal envelope printer settings
    p = env.ru.put("/api/checks/my-printer/envelope", {"document_id": envelope["id"], "page": "ENVELOPE", "dy": 0.125})
    assert p.json()["page"] == "ENVELOPE" and p.json()["dy"] == 0.125
    assert env.ru.put("/api/checks/my-printer/envelope", {"document_id": envelope["id"], "dx": 0.5}).status_code == 422
    # access: Register Users only
    for c in (env.bm, env.bu, env.auditor, env.admin):
        assert c.post(f"/api/checks/transactions/{tid}/letter", body).status_code == 403
        assert c.post(f"/api/checks/transactions/{tid}/handwritten",
                      {"check_number": "1", "confirm_check_number": "1"}).status_code == 403
