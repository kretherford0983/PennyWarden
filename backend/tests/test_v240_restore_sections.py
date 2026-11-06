"""2.4.0 (#535, Kyle 2026-11-06): Invoices Setup, Email, Organization logos and Signers are sections of their own in
a selective restore; references across sections that point at nothing are cleared and reported; the next invoice
number always follows the highest invoice (BR-001)."""
from __future__ import annotations

from conftest import PASSWORD, Api
from test_v141_backup import _backup, _restore
from test_v210_donations import enable as enable_donations
from test_v210_donations import setup as donation_setup
from test_v220_partial_restore import _second_install
from test_v240_invoice_payments import ib  # noqa: F401  (fixture)

from fmpoc.services import partial_restore as pr


def _parts(client, blob, domains):
    j = _restore(client, blob, password=PASSWORD, confirm="RESTORE", domains=domains)
    assert j["state"] == "done", j
    return j


def _admin(app):
    c = Api(app)
    assert c.login("admin", PASSWORD).status_code == 200
    return c


def _donation_signer(app):
    import json

    from sqlalchemy import text
    with app.state.session_factory() as db:
        return json.loads(db.execute(text("SELECT config_json FROM donation_settings")).scalar())["signer_id"]


def test_the_four_sections(env, base):
    for d in ("settings.invoices", "settings.email", "settings.logos", "settings.signers"):
        assert d in pr.DOMAINS and pr.LABELS[d]
    general = pr.SETTINGS_SECTIONS["settings.general"]["tables"]
    assert not {"invoice_settings", "email_settings", "organization_logo"} & set(general)
    assert "check_signer" not in pr.SETTINGS_SECTIONS["settings.payments"]["tables"]
    assert "Invoices" in pr.LABELS["data"]


def test_email_restored_on_its_own(env, base):
    body = {"enabled": True, "host": "smtp.before.example", "port": 587, "security": "STARTTLS", "username": "u",
            "password": "Secret-1", "from_address": "a@example.org", "from_name": "A"}
    assert env.admin.put("/api/system/email", body).status_code == 200
    blob = _backup(env)
    assert env.admin.put("/api/system/email", {**body, "host": "smtp.after.example"}).status_code == 200
    _parts(env.admin, blob, ["settings.general"])                      # General no longer holds the mail server
    a = _admin(env.app)
    assert a.get("/api/system/email").json()["host"] == "smtp.after.example"
    _parts(a, blob, ["settings.email"])
    a = _admin(env.app)
    assert a.get("/api/system/email").json()["host"] == "smtp.before.example"


def test_a_signer_missing_from_the_restored_list_is_cleared(env, base, tmp_path):
    enable_donations(env)
    donation_setup(env)
    s = {"id": env.admin.get("/api/donations/setup").json()["config"]["signer_id"]}
    assert s["id"]
    blob = _backup(env)
    app2, a2 = _second_install(tmp_path)                                # no signers there
    j = _parts(a2, blob, ["settings.donations"])
    a2 = _admin(app2)
    assert _donation_signer(app2) is None                                # (the module is off there: read it directly)
    ev = a2.get("/api/audit-events?action=SYSTEM_RESTORED").json()["items"][0]
    assert any("signer choice" in line for line in ev["after"]["notes"]), ev["after"]
    # with Signers too, the choice stays
    _parts(a2, blob, ["settings.donations", "settings.signers"])
    assert _donation_signer(app2) == s["id"]
    assert j


def test_invoice_numbers_are_never_used_twice(env, base, ib):
    blob = _backup(env)                                                 # one invoice; the next number is the 2nd
    nxt = ib["im"].post("/api/invoices", {"customer_entity_id": ib["cust"], "invoice_date": "2026-09-16",
                                          "lines": [{"product_id": ib["dues"], "quantity": "1"}]})
    assert nxt.status_code == 201, nxt.text
    _parts(env.admin, blob, ["settings.invoices"])                      # the backup's counter is behind
    a = _admin(env.app)
    ev = a.get("/api/audit-events?action=SYSTEM_RESTORED").json()["items"][0]
    assert any("next invoice number" in line for line in ev["after"]["notes"]), ev["after"]
    # the next draft gets a new number, not the one taken after the backup
    from sqlalchemy import text
    with env.app.state.session_factory() as db:
        top = db.execute(text("SELECT MAX(seq) FROM invoice")).scalar()
        assert db.execute(text("SELECT next_seq FROM invoice_settings")).scalar() == top + 1
