"""2.2.0 (#327): two-step verification set up with the user's own authenticator key.

Decisions (Kyle, 2026-10-23): Base32 of at least 16 characters (a note under 32) or an otpauth://totp link (6 digits,
30 s, SHA-1 only); a current code made with that key is required before anything is saved; after a reset marked as a
possible compromise only a newly generated key is accepted; a new set of recovery codes as usual; the key never
reaches logs, audit records or error responses (BR-103, BR-108)."""
import logging
import sqlite3

import pyotp
import pytest

from conftest import PASSWORD, Api

from test_v141_mfa import _enroll, _init, _next, server_app  # noqa: F401 (fixture)

from fmpoc.services.mfa import parse_own_key

OWN = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"          # 32 characters, the length of PennyWarden's own keys
SHORT = "JBSWY3DPEHPK3PXP"                         # 16 characters (80 bits): accepted, with a note


def _start(a: Api) -> dict:
    r = a.post("/api/auth/mfa/enroll/start", {})
    assert r.status_code == 200, r.text
    return r.json()


def _finish(a: Api, r) -> None:
    """After a confirmed setup at sign-in: the new session, then the security questions of a first sign-in."""
    assert r.status_code == 200, r.text
    a.csrf = r.json()["me"]["csrf_token"]
    if r.json()["me"]["mfa_pending"] == "QUESTIONS":
        a.setup_questions()


def _clerk(server_app, admin):  # noqa: F811
    r = admin.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": "clerk",
                                  "email": "c@example.com", "password": PASSWORD, "display_name": "Clerk Person",
                                  "security_domain": "FINANCIAL", "roles": ["REGISTER_USER"]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.parametrize("value,expected,short", [
    (OWN, OWN, False),
    ("jbsw y3dp ehpk 3pxp jbsw y3dp ehpk 3pxp", OWN, False),
    (SHORT, SHORT, True),
    (SHORT + "====", SHORT, True),
    (f"otpauth://totp/Other%20Site:kyle?secret={OWN}&issuer=Other%20Site", OWN, False),
    (f"otpauth://totp/x?secret={OWN.lower()}&algorithm=SHA1&digits=6&period=30", OWN, False),
])
def test_parse_accepts(value, expected, short):
    assert parse_own_key(value) == (expected, short)


@pytest.mark.parametrize("value,fragment", [
    ("", "Enter your authenticator key"),
    ("JBSWY3DPEHPK3PX", "too short"),                     # 15 characters
    ("JBSWY3DPEHPK3PX0", "letters A-Z and the digits 2-7"),
    ("A" * 101, "too long"),
    ("JBSWY3DPEHPK3PXPA", "not a complete Base32 key"),   # 17 characters: not a whole Base32 length
    (f"otpauth://hotp/x?secret={OWN}&counter=1", "HOTP"),
    ("otpauth://totp/x?issuer=Nope", "no key"),
    (f"otpauth://totp/x?secret={OWN}&digits=8", "6-digit codes"),
    (f"otpauth://totp/x?secret={OWN}&period=60", "30-second codes"),
    (f"otpauth://totp/x?secret={OWN}&algorithm=SHA256", "SHA-1"),
    (f"otpauth-migration://offline?data={OWN}", "not supported"),
])
def test_parse_refuses_without_echoing_the_key(value, fragment):
    from fmpoc.errors import AppError
    with pytest.raises(AppError) as e:
        parse_own_key(value)
    assert e.value.status == 422 and fragment in e.value.message
    assert OWN not in e.value.message and OWN.lower() not in e.value.message


def test_own_key_setup_at_sign_in(server_app, caplog):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    a = _init(server_app)
    s = _start(a)
    assert s["own_key"] is False and s["own_key_allowed"] is True
    r = a.post("/api/auth/mfa/enroll/own-key", {"own_key": f"otpauth://totp/Old:admin?secret={SHORT}&issuer=Old"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {**body, "own_key": True, "short_key": True, "key_length": 16, "own_key_length": 32}
    assert SHORT not in r.text and "secret" not in body
    # a code from the generated key no longer fits; a wrong code saves nothing
    assert a.post("/api/auth/mfa/enroll/confirm", {"code": pyotp.TOTP(s["secret"].replace(" ", "")).now()}
                  ).status_code == 400
    assert a.get("/api/auth/me").json()["mfa_pending"] == "ENROLL"
    totp = pyotp.TOTP(SHORT)
    r = a.post("/api/auth/mfa/enroll/confirm", {"code": totp.now()})
    assert len(r.json()["recovery_codes"]) == 10
    _finish(a, r)
    # the existing authenticator entry keeps working
    b = Api(server_app)
    assert b.login("admin").json()["mfa_pending"] == "VERIFY"
    assert b.post("/api/auth/mfa/verify", {"code": _next(totp)}).status_code == 200
    ev = a.get("/api/audit-events?action=MFA_ENROLLED").json()["items"][0]
    assert ev["after"]["own_key"] is True
    # the key appears nowhere: audit log, logs, the database (encrypted)
    everything = str(a.get("/api/audit-events?page_size=200").json())
    assert SHORT not in everything and SHORT.lower() not in everything
    assert SHORT not in caplog.text
    con = sqlite3.connect(server_app.state.settings.database_path)
    row = con.execute("SELECT secret_enc, pending_own_key, new_key_required FROM user_mfa").fetchone()
    con.close()
    assert row[0].startswith("v1:") and SHORT not in row[0] and row[1:] == (0, 0)


def test_back_to_a_generated_key_and_invalid_keys(server_app):  # noqa: F811
    a = _init(server_app)
    _start(a)
    r = a.post("/api/auth/mfa/enroll/own-key", {"own_key": "not a key at all"})
    assert r.status_code == 422 and r.json()["error"]["errors"][0]["field"] == "own_key"
    assert a.post("/api/auth/mfa/enroll/own-key", {"own_key": OWN}).status_code == 200
    r = a.post("/api/auth/mfa/enroll/own-key", {"own_key": None})   # use a generated key again
    assert r.status_code == 200 and r.json()["own_key"] is False
    new = pyotp.TOTP(r.json()["secret"].replace(" ", ""))
    assert a.post("/api/auth/mfa/enroll/confirm", {"code": pyotp.TOTP(OWN).now()}).status_code == 400
    _finish(a, a.post("/api/auth/mfa/enroll/confirm", {"code": new.now()}))
    ev = a.get("/api/audit-events?action=MFA_ENROLLED").json()["items"][0]
    assert ev["after"]["own_key"] is False


def test_own_key_needs_a_setup_in_progress(server_app):  # noqa: F811
    a = _init(server_app)
    r = a.post("/api/auth/mfa/enroll/own-key", {"own_key": OWN})
    assert r.status_code == 409 and r.json()["error"]["code"] == "MFA_NO_PENDING_SETUP"
    assert Api(server_app).post("/api/auth/mfa/enroll/own-key", {"own_key": OWN}).status_code in (401, 403)


def test_changing_the_authenticator_to_an_own_key_keeps_the_current_code_rule(server_app):  # noqa: F811
    admin = _init(server_app)
    totp, codes = _enroll(admin)
    assert admin.post("/api/auth/mfa/enroll/own-key", {"own_key": OWN}).status_code == 409   # no setup started
    assert admin.post("/api/auth/mfa/enroll/start", {"current_code": codes[0]}).status_code == 200
    assert admin.post("/api/auth/mfa/enroll/own-key", {"own_key": OWN}).status_code == 200
    r = admin.post("/api/auth/mfa/enroll/confirm", {"code": pyotp.TOTP(OWN).now()})
    assert r.status_code == 200 and set(r.json()["recovery_codes"]).isdisjoint(codes)   # a new set
    ev = admin.get("/api/audit-events?action=MFA_CHANGED").json()["items"][0]
    assert ev["after"]["own_key"] is True and OWN not in str(ev)


def test_compromise_reset_requires_a_new_key_until_set_up(server_app):  # noqa: F811
    admin = _init(server_app)
    _enroll(admin)
    uid = _clerk(server_app, admin)
    u = Api(server_app)
    u.login("clerk")
    _enroll(u)
    r = admin.post(f"/api/users/{uid}/reset-mfa", {"reason": "Phone stolen", "compromised": True})
    assert r.status_code == 200 and r.json()["mfa_enabled"] is False
    ev = admin.get("/api/audit-events?action=MFA_RESET").json()["items"][0]
    assert ev["after"]["compromised"] is True and ev["after"]["new_key_required"] is True
    # a later reset without the mark does not lift it
    assert admin.post(f"/api/users/{uid}/reset-mfa", {"reason": "Again"}).status_code == 200
    ev = admin.get("/api/audit-events?action=MFA_RESET").json()["items"][0]
    assert ev["after"]["compromised"] is False and ev["after"]["new_key_required"] is True
    u2 = Api(server_app)
    assert u2.login("clerk").json()["mfa_pending"] == "ENROLL"
    s = _start(u2)
    assert s["own_key_allowed"] is False
    r = u2.post("/api/auth/mfa/enroll/own-key", {"own_key": OWN})
    assert r.status_code == 409 and r.json()["error"]["code"] == "MFA_NEW_KEY_REQUIRED" and OWN not in r.text
    assert u2.post("/api/auth/mfa/enroll/confirm", {"code": pyotp.TOTP(s["secret"].replace(" ", "")).now()}
                   ).status_code == 200
    # set up again: the next ordinary reset offers the own-key box again
    assert admin.post(f"/api/users/{uid}/reset-mfa", {"reason": "New phone"}).status_code == 200
    u3 = Api(server_app)
    u3.login("clerk")
    assert _start(u3)["own_key_allowed"] is True


def test_compromise_flag_only_for_mfa_reset(server_app):  # noqa: F811
    admin = _init(server_app)
    _enroll(admin)
    uid = _clerk(server_app, admin)
    r = admin.post(f"/api/users/{uid}/reset-security-questions", {"reason": "x", "compromised": True})
    assert r.status_code == 422


def test_cli_reset_compromised(server_app, tmp_path, capsys):  # noqa: F811
    admin = _init(server_app)
    _enroll(admin)
    from fmpoc.__main__ import main
    assert main(["reset-mfa", "--user", "admin", "--data-dir", str(tmp_path / "srv"), "--compromised"]) == 0
    assert "possible compromise" in capsys.readouterr().out
    a = Api(server_app)
    assert a.login("admin").json()["mfa_pending"] == "ENROLL"
    assert _start(a)["own_key_allowed"] is False
    assert a.post("/api/auth/mfa/enroll/own-key", {"own_key": OWN}).status_code == 409
