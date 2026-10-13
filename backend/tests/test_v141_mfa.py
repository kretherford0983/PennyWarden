"""v1.4.1 CR-018: two-step verification (TOTP + recovery codes + trusted browsers)."""
import time

import pyotp
import pytest

from conftest import ADMIN, PASSWORD, Api

from fmpoc.app import create_app
from fmpoc.config import load_settings


@pytest.fixture
def server_app(tmp_path):
    return create_app(load_settings({"data_dir": str(tmp_path / "srv"), "mode": "server", "login_max_failures": 5}))


def _init(app) -> Api:
    a = Api(app)
    a.pre_csrf()
    r = a.post("/api/system/initialize", ADMIN)
    assert r.status_code == 200, r.text
    a.csrf = a.get("/api/auth/me").json()["csrf_token"]
    return a


def _enroll(a: Api) -> tuple[pyotp.TOTP, list[str]]:
    r = a.post("/api/auth/mfa/enroll/start", {})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["qr_svg"].startswith("data:image/svg+xml") and s["otpauth_uri"].startswith("otpauth://totp/")
    totp = pyotp.TOTP(s["secret"].replace(" ", ""))
    r = a.post("/api/auth/mfa/enroll/confirm", {"code": totp.now()})
    assert r.status_code == 200, r.text
    body = r.json()
    a.csrf = body["me"]["csrf_token"]
    if body["me"]["mfa_pending"] == "QUESTIONS":   # 1.8.0 (#113): the first sign-in continues with the questions
        a.setup_questions()
    return totp, body["recovery_codes"]


def _next(totp: pyotp.TOTP) -> str:
    return totp.at(time.time() + 30)  # the following step (inside the +/-1 window, never a replay)


def test_initialize_in_server_mode_requires_enrollment(server_app):
    a = _init(server_app)
    me = a.get("/api/auth/me").json()
    assert me["mfa_pending"] == "ENROLL" and me["permissions"] == []
    r = a.get("/api/users")
    assert r.status_code == 401 and r.json()["error"]["code"] == "MFA_REQUIRED"
    assert a.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": "x"}).status_code == 401
    # a wrong code does not complete enrollment
    assert a.post("/api/auth/mfa/enroll/start", {}).status_code == 200
    r = a.post("/api/auth/mfa/enroll/confirm", {"code": "000000"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "MFA_INVALID_CODE"
    old_cookie = a.c.cookies.get("fm_session")
    totp, codes = _enroll(a)
    assert len(codes) == 10 and len(set(codes)) == 10 and all(len(c) == 14 for c in codes)
    assert a.c.cookies.get("fm_session") != old_cookie  # session rotated after the second step
    assert a.get("/api/users").status_code == 200
    st = a.get("/api/me/mfa").json()
    assert st["enabled"] and st["required"] and st["recovery_codes_remaining"] == 10
    ev = a.get("/api/audit-events?action=MFA_ENROLLED").json()
    assert ev["total"] == 1 and ev["items"][0]["after"]["recovery_codes_issued"] == 10
    assert not any(c in str(ev["items"][0]) for c in codes)  # codes never reach the audit log


def test_sign_in_totp_replay_recovery_and_rate_limit(server_app):
    admin = _init(server_app)
    totp, codes = _enroll(admin)
    admin.post("/api/auth/logout")
    a = Api(server_app)
    r = a.login("admin")
    assert r.status_code == 200 and r.json()["mfa_pending"] == "VERIFY"
    assert a.get("/api/dashboard").status_code == 401
    code = _next(totp)
    r = a.post("/api/auth/mfa/verify", {"code": code})
    assert r.status_code == 200, r.text
    a.csrf = r.json()["csrf_token"]
    assert r.json()["mfa_pending"] is None and "users.manage" in r.json()["permissions"]
    assert a.get("/api/dashboard").status_code == 200
    # the same code cannot be used again (replay)
    b = Api(server_app)
    b.login("admin")
    assert b.post("/api/auth/mfa/verify", {"code": code}).status_code == 400
    # recovery code: works once, any case / without dashes
    rc = codes[0].replace("-", "").lower()
    r = b.post("/api/auth/mfa/verify", {"code": rc})
    assert r.status_code == 200, r.text
    c = Api(server_app)
    c.login("admin")
    assert c.post("/api/auth/mfa/verify", {"code": codes[0]}).status_code == 400
    assert c.post("/api/auth/mfa/verify", {"code": codes[1]}).status_code == 200
    b.csrf = r.json()["csrf_token"]
    assert b.get("/api/me/mfa").json()["recovery_codes_remaining"] == 8
    assert b.get("/api/audit-events?action=MFA_RECOVERY_CODE_USED").json()["total"] == 2
    # rate limit on wrong codes
    d = Api(server_app)
    d.login("admin")
    for _ in range(5):
        assert d.post("/api/auth/mfa/verify", {"code": "123456"}).status_code in (400, 429)
    assert d.post("/api/auth/mfa/verify", {"code": _next(totp)}).status_code == 429


def test_trusted_browser_and_revocation(server_app):
    admin = _init(server_app)
    totp, _codes = _enroll(admin)
    a = Api(server_app)
    a.login("admin")
    r = a.post("/api/auth/mfa/verify", {"code": _next(totp), "trust_browser": True})
    assert r.status_code == 200 and a.c.cookies.get("fm_trusted")
    a.csrf = r.json()["csrf_token"]
    a.post("/api/auth/logout")
    r = a.login("admin")
    assert r.json()["mfa_pending"] is None  # trusted browser skips the code
    st = a.get("/api/me/mfa").json()
    assert len(st["trusted_browsers"]) == 1
    # another browser (no cookie) still needs the code
    assert Api(server_app).login("admin").json()["mfa_pending"] == "VERIFY"
    # revoking the browser ends the shortcut
    a.post(f"/api/me/mfa/trusted-browsers/{st['trusted_browsers'][0]['id']}/revoke")
    a.post("/api/auth/logout")
    assert a.login("admin").json()["mfa_pending"] == "VERIFY"


def test_password_change_revokes_trusted_browsers(server_app):
    admin = _init(server_app)
    totp, _ = _enroll(admin)
    a = Api(server_app)
    a.login("admin")
    a.csrf = a.post("/api/auth/mfa/verify", {"code": _next(totp), "trust_browser": True}).json()["csrf_token"]
    new = "Another-Good-Pass-77"
    assert a.post("/api/auth/change-password", {"current_password": PASSWORD, "new_password": new,
                                                "new_password_confirmation": new}).status_code == 200
    a.post("/api/auth/logout")
    assert a.login("admin", new).json()["mfa_pending"] == "VERIFY"


def test_admin_reset_and_user_enrollment(server_app):
    admin = _init(server_app)
    atotp, _ = _enroll(admin)
    r = admin.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": "clerk", "email": "c@example.com", "password": PASSWORD,
                                  "display_name": "Clerk Person",
                                  "security_domain": "FINANCIAL", "roles": ["REGISTER_USER"]})
    assert r.status_code == 201
    uid = r.json()["id"]
    u = Api(server_app)
    assert u.login("clerk").json()["mfa_pending"] == "ENROLL"
    utotp, _ = _enroll(u)
    assert u.get("/api/bank-accounts").status_code == 200
    users = {x["username"]: x for x in admin.get("/api/users").json()}
    assert users["clerk"]["mfa_enabled"] is True
    # a financial user cannot reset MFA; reason is required
    assert u.post(f"/api/users/{uid}/reset-mfa", {"reason": "x"}).status_code == 403
    assert admin.post(f"/api/users/{uid}/reset-mfa", {"reason": ""}).status_code == 422
    r = admin.post(f"/api/users/{uid}/reset-mfa", {"reason": "Lost phone"})
    assert r.status_code == 200 and r.json()["mfa_enabled"] is False
    assert u.get("/api/bank-accounts").status_code == 401  # sessions revoked
    u2 = Api(server_app)
    assert u2.login("clerk").json()["mfa_pending"] == "ENROLL"
    ev = admin.get("/api/audit-events?action=MFA_RESET").json()["items"][0]
    assert ev["after"]["reason"] == "Lost phone" and ev["after"]["via"] == "administrator"
    assert atotp and utotp


def test_change_authenticator_needs_current_code(server_app):
    admin = _init(server_app)
    totp, codes = _enroll(admin)
    r = admin.post("/api/auth/mfa/enroll/start", {"current_code": "111111"})
    assert r.status_code == 400
    r = admin.post("/api/auth/mfa/enroll/start", {"current_code": codes[5]})
    assert r.status_code == 200
    new = pyotp.TOTP(r.json()["secret"].replace(" ", ""))
    r = admin.post("/api/auth/mfa/enroll/confirm", {"code": new.now()})
    assert r.status_code == 200
    new_codes = r.json()["recovery_codes"]
    assert set(new_codes).isdisjoint(codes)
    assert admin.get("/api/audit-events?action=MFA_CHANGED").json()["total"] == 1
    b = Api(server_app)
    b.login("admin")
    assert b.post("/api/auth/mfa/verify", {"code": codes[6]}).status_code == 400  # old codes are gone
    assert b.post("/api/auth/mfa/verify", {"code": _next(new)}).status_code == 200


def test_disable_only_in_local_mode(server_app, env):
    admin = _init(server_app)
    totp, _ = _enroll(admin)
    r = admin.post("/api/me/mfa/disable", {"code": _next(totp)})
    assert r.status_code == 409 and r.json()["error"]["code"] == "MFA_REQUIRED_BY_POLICY"
    # local mode (the `env` fixture): optional, can be enabled and disabled
    assert env.bu.get("/api/auth/me").json()["mfa_pending"] is None
    st = env.bu.get("/api/me/mfa").json()
    assert st == {**st, "enabled": False, "required": False}
    ltotp, lcodes = _enroll(env.bu)
    x = Api(env.app)
    assert x.login("budgetuser").json()["mfa_pending"] == "VERIFY"
    x.csrf = x.post("/api/auth/mfa/verify", {"code": _next(ltotp)}).json()["csrf_token"]
    assert x.post("/api/me/mfa/disable", {"code": "000000"}).status_code == 400
    r = x.post("/api/me/mfa/disable", {"code": lcodes[0]})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert Api(env.app).login("budgetuser").json()["mfa_pending"] is None


def test_secret_encrypted_at_rest_and_cli_reset(server_app, tmp_path, capsys):
    admin = _init(server_app)
    r = admin.post("/api/auth/mfa/enroll/start", {})
    secret = r.json()["secret"].replace(" ", "")
    admin.post("/api/auth/mfa/enroll/confirm", {"code": pyotp.TOTP(secret).now()})
    import sqlite3
    db = tmp_path / "srv" / "database" / "fmpoc.sqlite3"
    con = sqlite3.connect(db)
    row = con.execute("SELECT secret_enc FROM user_mfa").fetchone()[0]
    codes = [x[0] for x in con.execute("SELECT code_hash FROM mfa_recovery_code")]
    con.close()
    assert row.startswith("v1:") and secret not in row
    assert all(len(h) == 64 for h in codes)
    from fmpoc.__main__ import main
    assert main(["reset-mfa", "--user", "ADMIN", "--data-dir", str(tmp_path / "srv"), "--reason", "Locked out"]) == 0
    assert "was reset" in capsys.readouterr().out
    assert main(["reset-mfa", "--user", "nobody", "--data-dir", str(tmp_path / "srv")]) == 1
    a = Api(server_app)
    assert a.login("admin").json()["mfa_pending"] == "ENROLL"
    _enroll(a)
    ev = a.get("/api/audit-events?action=MFA_RESET").json()["items"][0]
    assert ev["after"]["via"] == "host_cli" and ev["actor_username"] is None
