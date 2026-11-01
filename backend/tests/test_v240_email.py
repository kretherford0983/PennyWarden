"""2.4.0 (#249): email invoices and statements - the Administrator's mail server (password encrypted, replace only,
never shown or logged), one click per email by an Invoice Manager, every send logged and audited.

BR-INV-EML-001..005 / AC-INV-EML-001..006 (recorded in docs/implementation-notes.md); regression for BR-103/104,
BR-003, BR-099.
"""
from __future__ import annotations

import io
import logging
import smtplib

import pytest
from pypdf import PdfReader

from fmpoc.services import email as email_svc

SECRET = "Sm7p-Pa55word!x"


class Outbox(list):
    fake = None


@pytest.fixture
def outbox(monkeypatch):
    sent = Outbox()

    def fake(s, km, msg):
        if getattr(fake, "fail", None):
            raise fake.fail
        sent.append((s, email_svc.crypto.decrypt(km, s.password_enc, email_svc.AAD) if s.password_enc else None, msg))
    monkeypatch.setattr(email_svc, "_smtp_send", fake)
    sent.fake = fake
    return sent


def _setup(env, **kw):
    body = {"enabled": True, "host": "smtp.example.org", "port": 587, "security": "STARTTLS", "username": "billing",
            "password": SECRET, "from_address": "billing@example.org", "from_name": "Example Club",
            "reply_to": "treasurer@example.org", **kw}
    return env.admin.put("/api/system/email", body)


@pytest.fixture
def eb(env, base, outbox):
    assert env.admin.put("/api/system/modules", {"invoices": True}).status_code == 200
    im = env.user("invmgr", "FINANCIAL", ["INVOICE_MANAGER"])
    env.bm.put(f"/api/budgets/{base['inc']['id']}/invoiced-income", {"invoiced_income": True})
    units = {u["name"]: u["id"] for u in im.get("/api/invoices/catalog/unit-types").json()}
    dues = im.post("/api/invoices/catalog/products", {"name": "Dues", "unit_price": "80.00", "unit_type_id": units["Year"],
                                                     "budget_id": base["inc_leaf"]}).json()["id"]
    r = im.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "Mail Customer", "email": "ap@customer.example"})
    assert r.status_code == 201, r.text
    cust = r.json()["id"]
    i = im.post("/api/invoices", {"customer_entity_id": cust, "invoice_date": "2026-09-15",
                                  "lines": [{"product_id": dues, "quantity": "1"}]}).json()
    return {"im": im, "cust": cust, "inv": i["id"], "dues": dues}


def test_settings_password_encrypted_replace_only_never_shown(env, eb, caplog):
    """AC-INV-EML-001: Administrator only; the password is encrypted, never returned, audited or logged; an empty
    password keeps the saved one."""
    caplog.set_level(logging.DEBUG)
    for c in (eb["im"], env.bm, env.auditor):
        assert c.get("/api/system/email").status_code == 403
        assert c.put("/api/system/email", {"enabled": False}).status_code == 403
    r = _setup(env)
    assert r.status_code == 200, r.text
    assert r.json()["password_saved"] is True and SECRET not in r.text and r.json()["ready"] is True
    g = env.admin.get("/api/system/email")
    assert SECRET not in g.text and "password_enc" not in g.text
    with env.app.state.session_factory() as db:
        from fmpoc.models import EmailSettings
        row = db.query(EmailSettings).one()
        assert row.password_enc.startswith("v1:") and SECRET not in row.password_enc
    # keep: an update without a password keeps it
    assert _setup(env, password=None, from_name="Club Billing").json()["password_saved"] is True
    ev = env.admin.get("/api/audit-events?action=EMAIL_SETTINGS_UPDATED").json()["items"]
    assert ev and SECRET not in str(ev)
    assert SECRET not in caplog.text
    assert _setup(env, from_address="not-an-address").status_code == 422
    assert _setup(env, host="bad host!").status_code == 422
    assert _setup(env, clear_password=True, password=None).json()["password_saved"] is False


def test_test_email(env, eb, outbox):
    """AC-INV-EML-002: the Administrator sends a test to an address they type; logged and audited."""
    r = env.admin.post("/api/system/email/test", {"to": "admin@example.org"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "EMAIL_NOT_SET_UP"
    _setup(env)
    r = env.admin.post("/api/system/email/test", {"to": "admin@example.org"})
    assert r.status_code == 200 and r.json()["status"] == "SENT"
    s, pw, msg = outbox[-1]
    assert pw == SECRET and msg["To"] == "admin@example.org" and "test" in msg["Subject"].lower()
    assert env.admin.get("/api/audit-events?action=EMAIL_TEST_SENT").json()["items"]


def test_email_invoice_one_click_logged(env, eb, outbox):
    """AC-INV-EML-003: an Invoice Manager emails the sent version's kept PDF; the form starts with the customer's
    address; a draft is refused; logged on the invoice and audited."""
    _setup(env)
    im = eb["im"]
    f = im.get(f"/api/invoices/{eb['inv']}/email").json()
    assert f["defaults"]["to"] == ["ap@customer.example"] and "Invoice" in f["defaults"]["subject"] and f["log"] == []
    body = {"to": ["ap@customer.example"], "cc": ["boss@customer.example"], "subject": "Your invoice", "message": "Attached."}
    assert im.post(f"/api/invoices/{eb['inv']}/email", body).status_code == 409             # still a draft
    i = im.post(f"/api/invoices/{eb['inv']}/send").json()
    r = im.post(f"/api/invoices/{eb['inv']}/email", body)
    assert r.status_code == 200, r.text
    _s, _pw, msg = outbox[-1]
    assert msg["Cc"] == "boss@customer.example" and msg["Reply-To"] == "treasurer@example.org"
    assert "billing@example.org" in msg["From"]
    att = [p for p in msg.iter_attachments()]
    assert len(att) == 1 and att[0].get_filename() == f"invoice-{i['number']}.pdf"
    pdf = att[0].get_content()
    assert "Mail Customer" in "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    log = im.get(f"/api/invoices/{eb['inv']}/email").json()["log"]
    assert log[0]["status"] == "SENT" and log[0]["to"] == "ap@customer.example" and log[0]["sent_by"] == "invmgr"
    assert env.bu.get(f"/api/invoices/{eb['inv']}/email").json().get("defaults") is None    # viewers see the log only
    assert env.auditor.get(f"/api/audit-events?action=INVOICE_EMAILED&object_id={eb['inv']}").json()["items"]
    # header injection and bad addresses
    assert im.post(f"/api/invoices/{eb['inv']}/email", {**body, "to": ["a@b.example\r\nBcc: x@y.example"]}).status_code == 422
    assert im.post(f"/api/invoices/{eb['inv']}/email", {**body, "to": []}).status_code == 422
    sub = im.post(f"/api/invoices/{eb['inv']}/email", {**body, "subject": "Hi\r\nBcc: evil@x.example"})
    assert sub.status_code == 200 and "\n" not in outbox[-1][2]["Subject"] and outbox[-1][2]["Bcc"] is None


def test_failure_is_logged_without_secrets(env, eb, outbox):
    """AC-INV-EML-004: a refused login is reported in plain words, logged as FAILED and audited; no password."""
    _setup(env)
    eb["im"].post(f"/api/invoices/{eb['inv']}/send")
    outbox.fake.fail = smtplib.SMTPAuthenticationError(535, b"5.7.8 bad credentials")
    r = eb["im"].post(f"/api/invoices/{eb['inv']}/email", {"to": ["ap@customer.example"], "subject": "Invoice"})
    assert r.status_code == 502 and "user name or password" in r.json()["error"]["message"] and SECRET not in r.text
    log = eb["im"].get(f"/api/invoices/{eb['inv']}/email").json()["log"]
    assert log[0]["status"] == "FAILED"
    ev = env.auditor.get("/api/audit-events?action=EMAIL_SEND_FAILED").json()["items"]
    assert ev and SECRET not in str(ev)


def test_email_statement(env, eb, outbox):
    """AC-INV-EML-005: a customer statement PDF to the customer, same rules."""
    _setup(env)
    eb["im"].post(f"/api/invoices/{eb['inv']}/send")
    d = eb["im"].get("/api/invoice-statements/email", params={"customer_entity_id": eb["cust"]}).json()
    assert d["to"] == ["ap@customer.example"] and d["customer"] == "Mail Customer"
    r = eb["im"].post("/api/invoice-statements/email", {"customer_entity_id": eb["cust"], "date_from": "2026-07-01",
                                                         "date_to": "2026-09-30", "to": d["to"], "subject": d["subject"],
                                                         "message": d["message"]})
    assert r.status_code == 200, r.text
    att = list(outbox[-1][2].iter_attachments())[0]
    assert att.get_filename() == "statement-2026-09-30.pdf"
    assert "Statement" in "".join(p.extract_text() for p in PdfReader(io.BytesIO(att.get_content())).pages)
    assert env.auditor.get("/api/audit-events?action=STATEMENT_EMAILED").json()["items"]


def test_who_can_send(env, eb, outbox):
    """AC-INV-EML-006: only Invoice Managers send; nothing is sent without a person's click (no scheduled sends)."""
    _setup(env)
    eb["im"].post(f"/api/invoices/{eb['inv']}/send")
    body = {"to": ["ap@customer.example"], "subject": "Invoice"}
    for c in (env.ru, env.bm, env.bu, env.auditor, env.admin):
        assert c.post(f"/api/invoices/{eb['inv']}/email", body).status_code == 403
        assert c.post("/api/invoice-statements/email", {**body, "customer_entity_id": eb["cust"], "date_from": "2026-07-01",
                                                        "date_to": "2026-09-30"}).status_code == 403
    assert outbox == []
