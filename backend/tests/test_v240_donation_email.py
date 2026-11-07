"""2.4.0 (#539): donation receipts and year-end statements by email, with the mail server set up for Invoices; the
message from Donations Setup; emailing issues the receipt; Invoices and Donations Setup can each have their own
Reply-To and From name. Decisions: Kyle, 2026-11-06. BR-DON-EM-001..003 / AC-DON-EM-001..004."""
from __future__ import annotations

from test_v210_donations import dep, mark_all  # noqa: F401  (fixture)
from test_v220_year_end import ALL_OK, year  # noqa: F401  (fixture)
from test_v240_email import _setup as email_setup
from test_v240_email import outbox  # noqa: F401  (fixture)
from test_v240_invoice_payments import ib  # noqa: F401  (fixture)


def _body(**kw):
    return {"to": ["donor@example.org"], "cc": [], "subject": "Thanks", "message": "Thank you", "confirmations":
            ["EMPTY_VARIABLES", "NOT_RECEIVED", "NO_DONOR_ADDRESS"], **kw}


def test_ac_don_em_001_ready_flag_and_refused_without_email(env, dep):
    mark_all(env, dep)
    assert env.ru.get("/api/auth/me").json()["email_ready"] is False
    r = env.ru.post(dep["url"] + "/receipts/email", _body(donor_entity_id=dep["a"]["id"]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "EMAIL_NOT_SET_UP"
    assert email_setup(env).status_code == 200
    assert env.ru.get("/api/auth/me").json()["email_ready"] is True


def test_ac_don_em_002_email_issues_the_receipt_with_setup_message(env, dep, outbox):
    mark_all(env, dep)
    email_setup(env)
    d = env.ru.get("/api/donations/email/defaults", params={"kind": "RECEIPT", "transaction_id": dep["t"]["id"],
                                                            "donor_entity_id": dep["a"]["id"]}).json()
    assert d["ready"] and "Your donation receipt from" in d["subject"] and "$150.00" in d["message"]
    r = env.ru.post(dep["url"] + "/receipts/email", _body(donor_entity_id=dep["a"]["id"], subject=d["subject"],
                                                          message=d["message"]))
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "ORIGINAL" and r.json()["emailed"]
    _s, _pw, msg = outbox[-1]
    att = [p for p in msg.iter_attachments()]
    assert att and att[0].get_filename() == f"receipt-{r.json()['number']}.pdf"
    # issued: printing now gives a duplicate, not a second original
    p = env.ru.post(dep["url"] + "/receipts", {"donor_entity_id": dep["a"]["id"], "confirmations": ["NOT_RECEIVED"]})
    assert p.headers.get("X-Receipt-Kind") == "DUPLICATE"


def test_ac_don_em_003_a_refused_send_issues_nothing(env, dep, outbox):
    mark_all(env, dep)
    email_setup(env)
    outbox.fake.fail = OSError("connection refused")
    r = env.ru.post(dep["url"] + "/receipts/email", _body(donor_entity_id=dep["a"]["id"]))
    assert r.status_code == 502 and r.json()["error"]["code"] == "EMAIL_NOT_SENT"
    outbox.fake.fail = None
    p = env.ru.post(dep["url"] + "/receipts", {"donor_entity_id": dep["a"]["id"], "confirmations": ["NOT_RECEIVED"]})
    assert p.headers.get("X-Receipt-Kind") == "ORIGINAL"                     # nothing was issued by the failed email
    ev = env.auditor.get("/api/audit-events?action=EMAIL_SEND_FAILED").json()["items"]
    assert ev and ev[0]["after"]["kind"] == "RECEIPT"


def test_ac_don_em_004_statement_and_sender_overrides(env, year, outbox):
    email_setup(env, reply_to="treasurer@example.org", from_name="Example Club")
    cfg = env.admin.get("/api/donations/setup").json()["config"]
    assert env.admin.put("/api/donations/setup", {"config": {**cfg, "email_reply_to": "donations@example.org",
                                                             "email_from_name": "Example Giving"}}).status_code == 200
    bad = env.admin.put("/api/donations/setup", {"config": {**cfg, "email_reply_to": "not an address"}})
    assert bad.status_code == 422
    d = env.ru.get("/api/donations/email/defaults", params={"kind": "STATEMENT", "year": 2026,
                                                            "donor_entity_id": year["a"]["id"]}).json()
    assert "2026 giving statement" in d["subject"]
    r = env.ru.post(f"/api/donations/statements/2026/donors/{year['a']['id']}/email",
                    _body(confirmations=ALL_OK, subject=d["subject"], message=d["message"]))
    assert r.status_code == 200, r.text
    _s, _pw, msg = outbox[-1]
    assert msg["Reply-To"] == "donations@example.org" and "Example Giving" in msg["From"]


def test_invoice_sender_override(env, ib, outbox):
    email_setup(env, reply_to="treasurer@example.org", from_name="Example Club")
    send = lambda: ib["im"].post(f"/api/invoices/{ib['inv']}/email", {"to": ["c@example.org"], "cc": [],  # noqa: E731
                                                                      "subject": "Invoice", "message": "Hi"})
    assert send().status_code in (200, 201)
    assert outbox[-1][2]["Reply-To"] == "treasurer@example.org"            # the Email setup's
    st = env.admin.get("/api/invoices/setup").json()
    body = {k: st[k] for k in ("number_pattern", "terms_days", "terms_text", "default_notes")}
    r = env.admin.put("/api/invoices/setup", {**body, "email_reply_to": "invoicing@example.org", "email_from_name": "Example Billing"})
    assert r.status_code == 200, r.text
    assert send().status_code in (200, 201)
    msg = outbox[-1][2]
    assert msg["Reply-To"] == "invoicing@example.org" and "Example Billing" in msg["From"]
    assert "billing@example.org" in msg["From"]                              # the From address stays the server's
