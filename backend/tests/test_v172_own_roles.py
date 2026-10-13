"""1.7.2 (#55): in server mode an Administrator cannot change their own roles or security domain - another
Administrator can. A local install is not restricted."""
import pyotp
import pytest

from conftest import ADMIN, PASSWORD, Api

from fmpoc.app import create_app
from fmpoc.config import load_settings


def _enroll(a: Api) -> None:
    s = a.post("/api/auth/mfa/enroll/start", {}).json()
    r = a.post("/api/auth/mfa/enroll/confirm", {"code": pyotp.TOTP(s["secret"].replace(" ", "")).now()})
    assert r.status_code == 200, r.text
    a.csrf = r.json()["me"]["csrf_token"]
    if r.json()["me"]["mfa_pending"] == "QUESTIONS":   # 1.8.0 (#113)
        a.setup_questions()


@pytest.fixture
def server(tmp_path):
    """Server mode: the first Administrator plus a second one (both enrolled in two-step verification)."""
    app = create_app(load_settings({"data_dir": str(tmp_path / "srv"), "mode": "server", "login_max_failures": 5}))
    a = Api(app)
    a.pre_csrf()
    assert a.post("/api/system/initialize", ADMIN).status_code == 200
    a.csrf = a.get("/api/auth/me").json()["csrf_token"]
    _enroll(a)
    r = a.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": "admin2", "email": "a2@example.com", "display_name": "Second Admin",
                              "password": PASSWORD, "security_domain": "ADMINISTRATOR", "roles": ["ADMINISTRATOR"]})
    assert r.status_code == 201, r.text
    b = Api(app)
    assert b.login("admin2").status_code == 200
    _enroll(b)
    me_a = a.get("/api/auth/me").json()["id"]
    return a, b, me_a, r.json()["id"]


def test_server_admin_cannot_change_own_roles_or_domain(server):
    a, _b, me_a, _ = server
    for body in ({"security_domain": "AUDITOR", "roles": ["AUDITOR"]},
                 {"security_domain": "FINANCIAL", "roles": ["BUDGET_MANAGER"]}):
        r = a.patch(f"/api/users/{me_a}", body)
        assert r.status_code == 403 and r.json()["error"]["code"] == "OWN_ROLES_LOCKED", r.text
        assert "Another Administrator" in r.json()["error"]["message"]
    me = a.get("/api/auth/me").json()
    assert me["security_domain"] == "ADMINISTRATOR" and me["roles"] == ["ADMINISTRATOR"]


def test_server_admin_can_still_edit_own_profile_with_roles_unchanged(server):
    a, _b, me_a, _ = server
    # the edit form sends the roles back unchanged together with the other fields - that is allowed
    r = a.patch(f"/api/users/{me_a}", {"email": "boss@example.com", "display_name": "The Boss",
                                       "security_domain": "ADMINISTRATOR", "roles": ["ADMINISTRATOR"], "active": True})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "boss@example.com" and r.json()["display_name"] == "The Boss"


def test_server_admin_can_change_another_admins_roles(server):
    a, b, me_a, admin2 = server
    r = a.patch(f"/api/users/{admin2}", {"security_domain": "AUDITOR", "roles": ["AUDITOR"]})
    assert r.status_code == 200 and r.json()["roles"] == ["AUDITOR"]
    r = a.patch(f"/api/users/{admin2}", {"security_domain": "ADMINISTRATOR", "roles": ["ADMINISTRATOR"]})
    assert r.status_code == 200
    # and the other way round: the second Administrator may change the first one's roles
    r = b.patch(f"/api/users/{me_a}", {"security_domain": "AUDITOR", "roles": ["AUDITOR"]})
    assert r.status_code == 200 and r.json()["roles"] == ["AUDITOR"]


def test_refused_attempt_is_not_recorded_as_a_change(server):
    a, _b, me_a, _ = server
    before = a.get("/api/audit-events?action=USER_ROLES_CHANGED").json()["total"]
    assert a.patch(f"/api/users/{me_a}", {"security_domain": "AUDITOR", "roles": ["AUDITOR"]}).status_code == 403
    assert a.get("/api/audit-events?action=USER_ROLES_CHANGED").json()["total"] == before


def test_local_mode_admin_may_change_own_roles(env):
    """Local installs are not restricted (#54 builds on this). The last-Administrator rule still applies."""
    me = env.admin.get("/api/auth/me").json()["id"]
    r = env.admin.patch(f"/api/users/{me}", {"security_domain": "AUDITOR", "roles": ["AUDITOR"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "LAST_ADMINISTRATOR"
    r = env.admin.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": "admin2", "email": "a2@example.com", "display_name": "Second Admin",
                                      "password": PASSWORD, "security_domain": "ADMINISTRATOR", "roles": ["ADMINISTRATOR"]})
    assert r.status_code == 201
    r = env.admin.patch(f"/api/users/{me}", {"security_domain": "AUDITOR", "roles": ["AUDITOR"]})
    assert r.status_code == 200, r.text


def test_server_admin_cannot_disable_own_account_but_can_disable_another(server):
    """#55 follow-up: disabling yourself signs you out at once and, by mistake, can remove the Administrator who
    meant to disable someone else."""
    a, b, me_a, admin2 = server
    r = a.patch(f"/api/users/{me_a}", {"active": False})
    assert r.status_code == 403 and r.json()["error"]["code"] == "OWN_ACCOUNT_DISABLE", r.text
    assert a.get("/api/auth/me").status_code == 200                       # still signed in, still active
    # the edit form sends active=true back unchanged: allowed
    assert a.patch(f"/api/users/{me_a}", {"email": "me@example.com", "active": True}).status_code == 200
    # another Administrator can be disabled (and enabled again)
    assert a.patch(f"/api/users/{admin2}", {"active": False}).status_code == 200
    assert a.patch(f"/api/users/{admin2}", {"active": True}).status_code == 200


def test_local_admin_cannot_disable_own_account_either(env):
    me = env.admin.get("/api/auth/me").json()["id"]
    env.admin.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": "admin2", "email": "a2@example.com", "display_name": "Second Admin",
                                  "password": PASSWORD, "security_domain": "ADMINISTRATOR", "roles": ["ADMINISTRATOR"]})
    r = env.admin.patch(f"/api/users/{me}", {"active": False})
    assert r.status_code == 403 and r.json()["error"]["code"] == "OWN_ACCOUNT_DISABLE"
    ev = env.auditor.get("/api/audit-events?action=USER_DISABLED").json()["total"]
    assert ev == 0
