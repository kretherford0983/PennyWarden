"""1.9.0 (#54): Single User Local Install - on a local install the first user holds every role (Administrator,
Budget Manager, Budget Admin, Register User, Register Admin, Auditor; security domain COMBINED), any roles can be
combined for any user, and an Administrator can change their own roles. Servers are unchanged."""
import pytest

from conftest import ADMIN, PASSWORD, Api, initialize

from fmpoc.app import create_app
from fmpoc.config import load_settings

ALL = ["ADMINISTRATOR", "AUDITOR", "BUDGET_ADMIN", "BUDGET_MANAGER", "INVOICE_MANAGER", "REGISTER_ADMIN",   # 2.4.0 (#251)
       "REGISTER_USER"]


@pytest.fixture
def local(tmp_path):
    app = create_app(load_settings({"data_dir": str(tmp_path / "loc"), "login_max_failures": 1000}))
    return app, initialize(app, single_domain=False)


@pytest.fixture
def server(tmp_path):
    app = create_app(load_settings({"data_dir": str(tmp_path / "srv"), "mode": "server", "login_max_failures": 1000}))
    a = Api(app)
    a.pre_csrf()
    assert a.post("/api/system/initialize", ADMIN).status_code == 200
    return app


def test_local_first_user_has_every_role(local):
    app, admin = local
    me = admin.get("/api/auth/me").json()
    assert me["security_domain"] == "COMBINED" and me["roles"] == ALL
    for p in ("users.manage", "financial.view", "budget.manage", "budget.delete", "transaction.manage",
              "transaction.delete", "audit.view", "audit.view_financial_snapshots"):
        assert p in me["permissions"]
    # one person runs the books: Fiscal Years, budgets and the audit log with one account
    r = admin.post("/api/fiscal-years", {"identifier": "2027", "start_date": "2026-07-01", "end_date": "2027-06-30",
                                         "confirmations": []})
    assert r.status_code == 201, r.text
    assert admin.get("/api/audit-events").status_code == 200
    d = admin.get("/api/dashboard").json()
    assert d["kind"] != "administrator" and "review_summary" in d          # financial + Auditor dashboard
    ev = admin.get("/api/audit-events?action=SYSTEM_INITIALIZED").json()["items"][0]
    assert ev["after"]["admin_roles"] == ["ADMINISTRATOR", "BUDGET_MANAGER", "BUDGET_ADMIN", "REGISTER_USER",
                                          "REGISTER_ADMIN", "INVOICE_MANAGER", "AUDITOR"] and ev["after"]["mode"] == "local"


def test_local_any_roles_for_new_users_and_own_roles(local):
    app, admin = local
    r = admin.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": "pat", "email": "pat@example.com", "display_name": "Pat Person",
                                  "password": PASSWORD, "security_domain": "COMBINED",
                                  "roles": ["REGISTER_USER", "AUDITOR"]})
    assert r.status_code == 201, r.text
    assert r.json()["security_domain"] == "COMBINED"
    # the domain must match the roles
    bad = admin.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": "kim", "email": "kim@example.com", "display_name": "Kim Person",
                                    "password": PASSWORD, "security_domain": "FINANCIAL", "roles": ["REGISTER_USER", "AUDITOR"]})
    assert bad.status_code == 422
    # extra roles still need their base role
    bad = admin.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": "kim", "email": "kim@example.com", "display_name": "Kim Person",
                                    "password": PASSWORD, "security_domain": "COMBINED", "roles": ["BUDGET_ADMIN", "AUDITOR"]})
    assert bad.status_code == 422
    # an Administrator edits their own roles on a local install (e.g. an upgraded one)
    uid = admin.get("/api/auth/me").json()["id"]
    r = admin.patch(f"/api/users/{uid}", {"security_domain": "COMBINED", "roles": ["ADMINISTRATOR", "BUDGET_MANAGER"]})
    assert r.status_code == 200, r.text
    assert sorted(admin.get("/api/auth/me").json()["roles"]) == ["ADMINISTRATOR", "BUDGET_MANAGER"]
    r = admin.patch(f"/api/users/{uid}", {"security_domain": "FINANCIAL", "roles": ["BUDGET_MANAGER"]})
    assert r.status_code == 409                                             # the last Administrator stays


def test_server_first_user_is_administrator_only_and_domains_stay_separate(server):
    from fmpoc.models import User
    with server.state.session_factory() as db:
        u = db.query(User).one()
        assert u.security_domain == "ADMINISTRATOR" and u.role_codes == {"ADMINISTRATOR"}
    from fmpoc.permissions import validate_role_set
    assert validate_role_set("COMBINED", {"REGISTER_USER", "AUDITOR"}, "server")
    assert validate_role_set("COMBINED", {"REGISTER_USER", "AUDITOR"}, "local") is None


def test_server_refuses_combined_roles(tmp_path):
    app = create_app(load_settings({"data_dir": str(tmp_path / "s2"), "mode": "server", "login_max_failures": 1000}))
    from fmpoc.services import users as usvc
    from fmpoc.schemas import UserCreateIn
    from types import SimpleNamespace
    a = Api(app)
    a.pre_csrf()
    a.post("/api/system/initialize", ADMIN)
    with app.state.session_factory() as db:
        from fmpoc.models import User
        admin = db.query(User).one()
        ctx = SimpleNamespace(user=admin, workspace_id=admin.workspace_id, correlation_id=None, ip=None, session=None)
        data = UserCreateIn(username="pat", email="pat@example.com", display_name="Pat Person", password=PASSWORD,
                            security_domain="COMBINED", roles=["REGISTER_USER", "AUDITOR"])
        from fmpoc.errors import AppError
        with pytest.raises(AppError):
            usvc.create(db, ctx, data, mode="server")


def test_combined_user_moved_to_a_server_can_still_be_edited(local, tmp_path):
    app, admin = local
    r = admin.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": "pat", "email": "pat@example.com", "display_name": "Pat Person",
                                  "password": PASSWORD, "security_domain": "COMBINED", "roles": ["REGISTER_USER", "AUDITOR"]})
    pat_id = r.json()["id"]
    # the same data run in server mode (the server owner switched the mode)
    srv = create_app(load_settings({"data_dir": str(app.state.settings.data_dir), "mode": "server",
                                    "login_max_failures": 1000}))
    from fmpoc.models import User
    from fmpoc.services import users as usvc
    from fmpoc.schemas import UserUpdateIn
    from fmpoc.errors import AppError
    from types import SimpleNamespace
    with srv.state.session_factory() as db:
        admin_u = db.query(User).filter(User.username_normalized == "admin").one()
        pat = db.get(User, pat_id)
        ctx = SimpleNamespace(user=admin_u, workspace_id=admin_u.workspace_id, correlation_id=None, ip=None, session=None)
        usvc.update(db, ctx, pat, UserUpdateIn(email="pat2@example.com", security_domain="COMBINED",
                                               roles=["REGISTER_USER", "AUDITOR"]), mode="server")   # unchanged roles
        with pytest.raises(AppError):
            usvc.update(db, ctx, pat, UserUpdateIn(security_domain="COMBINED", roles=["REGISTER_USER", "AUDITOR",
                                                                                       "BUDGET_USER"]), mode="server")
        db.rollback()
