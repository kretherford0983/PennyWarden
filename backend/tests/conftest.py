"""Test fixtures. Tests exercise the backend API directly (BR-108): every client is a real HTTP client with
its own cookie jar and must obtain/send CSRF tokens like the React app does."""
from __future__ import annotations

import datetime as dt
import io
import itertools

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fmpoc.app import create_app
from fmpoc.config import load_settings

# 1.8.0 (#113): every test user hashes three security answers at the first sign-in. Production uses the library's
# recommended Argon2id cost; the tests hash answers with a much cheaper one (verification reads the parameters from
# the hash, so it works the same) to keep the suite's run time.
from argon2 import PasswordHasher as _PH  # noqa: E402

import fmpoc.services.recovery as _recovery  # noqa: E402

_recovery.hash_password = _PH(time_cost=1, memory_cost=1024, parallelism=1).hash

PASSWORD = "Correct-Horse-9-Battery"
# 1.8.0 (#113): the security questions every test user sets up at the first sign-in
QUESTION_ANSWERS = [("FIRST_TEACHER", "Mrs. Lee"), ("FIRST_PET", "Rex"), ("FIRST_CAR", "Blue Civic")]
ADMIN = {"workspace_name": "Acme Org", "admin_username": "admin", "admin_email": "admin@example.com",
         "admin_first_name": "Pat", "admin_last_name": "Example",   # 2.0.0 (#134)
         "password": PASSWORD, "password_confirmation": PASSWORD}


class Api:
    """Thin wrapper that behaves like the SPA: keeps the session cookie and sends X-CSRF-Token."""

    def __init__(self, app):
        self.c = TestClient(app, raise_server_exceptions=False)
        self.csrf: str | None = None

    def pre_csrf(self):
        self.csrf = self.c.get("/api/auth/csrf").json()["csrf_token"]

    def _h(self, extra=None):
        h = {"X-CSRF-Token": self.csrf} if self.csrf else {}
        h.update(extra or {})
        return h

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def patch(self, url, json=None, **kw):
        return self.c.patch(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def put(self, url, json=None, **kw):
        return self.c.put(url, json=json, headers=self._h(kw.pop("headers", None)), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._h(kw.pop("headers", None)), **kw)

    def login(self, username, password=PASSWORD, setup=True):
        """setup (1.8.0, #113): a first sign-in sets up the security questions like the app does; the answer of that
        step (the signed-in user) is returned in place of the login answer."""
        self.pre_csrf()
        r = self.post("/api/auth/login", {"username": username, "password": password})
        if r.status_code == 200:
            self.csrf = r.json()["csrf_token"]
            if setup and r.json().get("mfa_pending") == "QUESTIONS":
                r = self.setup_questions()
        return r

    def setup_questions(self, answers=QUESTION_ANSWERS):
        r = self.post("/api/auth/setup/security-questions",
                      {"questions": [{"question": q, "answer": a} for q, a in answers]})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf_token"]
        return r


@pytest.fixture
def settings(tmp_path):
    return load_settings({"data_dir": str(tmp_path / "appdata"), "login_max_failures": 5})


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def anon(app):
    return Api(app)


def initialize(app, single_domain=True) -> Api:
    a = Api(app)
    a.pre_csrf()
    r = a.post("/api/system/initialize", ADMIN)
    assert r.status_code == 200, r.text
    me = a.get("/api/auth/me").json()
    a.csrf = me["csrf_token"]
    if me.get("mfa_pending") == "QUESTIONS":   # 1.8.0 (#113)
        a.setup_questions()
    if single_domain:
        # 1.9.0 (#54): the first user of a local install holds every role. Most tests exercise the separation of the
        # security domains, so the test Administrator keeps only the Administrator role (as on a server).
        _set_roles_directly(app, ADMIN["admin_username"], "ADMINISTRATOR", ["ADMINISTRATOR"])
    return a


def _set_roles_directly(app, username, domain, codes):
    from fmpoc.models import Role, User, UserRole
    with app.state.session_factory() as db:
        u = db.query(User).filter(User.username_normalized == username).one()
        db.query(UserRole).filter(UserRole.user_id == u.id).delete()
        for r in db.query(Role).filter(Role.code.in_(codes)):
            db.add(UserRole(user_id=u.id, role_id=r.id))
        u.security_domain = domain
        db.commit()


_counter = itertools.count(1)


class Env:
    def __init__(self, app, settings):
        self.app, self.settings = app, settings
        self.admin = initialize(app)
        self.bm = self.user("budgetmgr", "FINANCIAL", ["BUDGET_MANAGER"])
        self.bu = self.user("budgetuser", "FINANCIAL", ["BUDGET_USER"])
        self.ru = self.user("reguser", "FINANCIAL", ["REGISTER_USER"])
        self.auditor = self.user("auditor", "AUDITOR", ["AUDITOR"])

    def user(self, username, domain, roles) -> Api:
        r = self.admin.post("/api/users", {"first_name": username.capitalize(), "last_name": "Person", "username": username,
                                           "email": f"{username}@example.com",
                                           "display_name": f"{username.capitalize()} Person",
                                           "password": PASSWORD, "security_domain": domain, "roles": roles})
        assert r.status_code == 201, r.text
        a = Api(self.app)
        assert a.login(username).status_code == 200
        return a

    # ---------------------------------------------------------------- scenario helpers
    def fy(self, ident="2027", start="2026-07-01", end="2027-06-30", confirmations=None, **kw):
        r = self.bm.post("/api/fiscal-years", {"identifier": ident, "start_date": start, "end_date": end,
                                               "confirmations": confirmations or [], **kw})
        assert r.status_code == 201, r.text
        return r.json()

    def budget(self, fy_id, code, name, btype="EXPENSE", amount="1000.00", parent=None):
        body = {"fiscal_year_id": fy_id, "code": code, "name": name, "amount": amount}
        if parent:
            body["parent_budget_id"] = parent
        else:
            body["budget_type"] = btype
        r = self.bm.post("/api/budgets", body)
        assert r.status_code == 201, r.text
        return r.json()

    def fi(self, name=None):
        name = name or f"Bank {next(_counter)}"
        r = self.bm.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": name,
                                           "is_financial_institution": True, "confirmations": ["DUPLICATE_ENTITY"]})
        assert r.status_code == 201, r.text
        return r.json()

    def entity(self, name=None, etype="ORGANIZATION", client=None):
        name = name or f"Vendor {next(_counter)}"
        body = {"entity_type": etype, "confirmations": ["DUPLICATE_ENTITY"]}
        body["organization_name" if etype == "ORGANIZATION" else "primary_contact"] = name
        r = (client or self.ru).post("/api/entities", body)
        assert r.status_code == 201, r.text
        return r.json()

    def account(self, number=None, opening="0.00", primary=False, atype="CHECKING", **kw):
        number = number or f"{next(_counter):04d}98765432"
        body = {"account_name": f"Acct {number[-4:]}", "financial_institution_entity_id": self.fi()["id"],
                "account_type": atype, "account_number": number, "is_primary": primary,
                "opening_balance": opening, "opening_balance_date": "2026-01-01", **kw}
        r = self.bm.post("/api/bank-accounts", body)
        assert r.status_code == 201, r.text
        return r.json()

    def txn(self, account_id, ttype, allocations, date="2026-08-01", expect=201, **kw):
        body = {"bank_account_id": account_id, "transaction_type": ttype, "transaction_date": date,
                "allocations": allocations, **kw}
        r = self.ru.post("/api/transactions", body)
        assert r.status_code == expect, r.text
        return r.json()

    def fy_doc(self, fy_id, document_type="UNSPECIFIED", name="doc.pdf"):
        """v1.3 CR-007: upload a typed Fiscal Year document as the Budget Manager."""
        # 2.4.0 (#425): each document has its own content (the same file twice on one Fiscal Year asks first)
        r = self.bm.c.post(f"/api/attachments?owner_type=fiscal_year&owner_id={fy_id}&document_type={document_type}",
                           files={"file": (name, unique_pdf(), "application/pdf")}, headers={"X-CSRF-Token": self.bm.csrf})
        assert r.status_code == 201, r.text
        return r.json()

    def approve(self, fy_id):
        """v1.3 CR-007: approval requires an Approval document."""
        self.fy_doc(fy_id, "APPROVAL", "approval.pdf")
        r = self.bm.post(f"/api/fiscal-years/{fy_id}/approve", {"confirm_irreversible": True})
        assert r.status_code == 200, r.text
        return r.json()

    def selectable(self, fy_id, ttype):
        return self.ru.get(f"/api/budgets/selectable?fiscal_year_id={fy_id}&transaction_type={ttype}").json()


@pytest.fixture
def env(app, settings) -> Env:
    return Env(app, settings)


@pytest.fixture
def base(env):
    """FY2027 (Jul-Jun) with an income and an expense budget and a Primary checking account."""
    fy = env.fy()
    inc = env.budget(fy["id"], "4000", "Donations", "INCOME", "5000.00")
    exp = env.budget(fy["id"], "1000", "Operations", "EXPENSE", "100000.00")
    acct = env.account(opening="1000.00", primary=True)
    sel_exp = {o["label"]: o["id"] for o in env.selectable(fy["id"], "WITHDRAWAL")}
    sel_inc = {o["label"]: o["id"] for o in env.selectable(fy["id"], "DEPOSIT")}
    return {"fy": fy, "inc": inc, "exp": exp, "acct": acct, "exp_leaf": sel_exp["1000 Operations"],
            "inc_leaf": sel_inc["4000 Donations"]}


def png_bytes(size=(4, 4)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 10, 10)).save(buf, "PNG")
    return buf.getvalue()


def jpeg_bytes(other: bool = False) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 10, 200) if other else (10, 200, 10)).save(buf, "JPEG")
    return buf.getvalue()


PDF_BYTES = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
             b"trailer<</Root 1 0 R>>\n%%EOF\n")


_pdf_seq = itertools.count(1)


def unique_pdf() -> bytes:
    """A valid minimal PDF with content of its own (2.4.0 #425: identical files are stored once)."""
    return PDF_BYTES.replace(b"%PDF-1.4\n", b"%%PDF-1.4\n%% doc %d\n" % next(_pdf_seq), 1)


def today() -> str:
    return dt.date.today().isoformat()
