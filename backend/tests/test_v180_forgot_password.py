"""1.8.0 (#113): forgotten password - security questions (set at the first / next sign-in, hashed, loosely compared),
Forgot password with one random question (plus the authenticator or a recovery code on a server or with two-step
turned on), no username enumeration, the persistent escalating lock-out (sign-in and reset together) ending in a
disabled account, notices, the Administrator tools and the host commands."""
import datetime as dt
import time

import pyotp
import pytest

from conftest import ADMIN, PASSWORD, QUESTION_ANSWERS, Api

from fmpoc.__main__ import main
from fmpoc.app import create_app
from fmpoc.config import load_settings
from fmpoc.models import User, UserSecurityQuestion
from fmpoc.services import recovery

NEW_PW = "Brand-New-Pass-42"
ANSWERS = dict(QUESTION_ANSWERS)


def _new_user(env, username="pat", roles=("BUDGET_USER",), domain="FINANCIAL"):
    r = env.admin.post("/api/users", {"first_name": "Test", "last_name": "Person", "username": username, "email": f"{username}@example.com", "display_name": "Pat Person",
                                      "password": PASSWORD, "security_domain": domain, "roles": list(roles)})
    assert r.status_code == 201, r.text
    return r.json()


def _db(app):
    return app.state.session_factory()


def _user(app, username):
    with _db(app) as db:
        u = db.query(User).filter(User.username_normalized == username).one()
        db.expunge(u)
        return u


def _set(app, username, **values):
    with _db(app) as db:
        u = db.query(User).filter(User.username_normalized == username).one()
        for k, v in values.items():
            setattr(u, k, v)
        db.commit()


def _forgot(app, username, answer=None, code=None, pw=NEW_PW, client=None):
    a = client or Api(app)
    a.pre_csrf()
    s = a.post("/api/auth/forgot/start", {"username": username})
    if s.status_code != 200:
        return s, None
    q = s.json()["question"]["code"]
    body = {"username": username, "answer": ANSWERS.get(q, "wrong") if answer is None else answer,
            "new_password": pw, "new_password_confirmation": pw}
    if code is not None:
        body["code"] = code
    return a.post("/api/auth/forgot/complete", body), s.json()


@pytest.fixture
def lenient(tmp_path):
    """No per-address brake, so the per-account counts can be walked through from one test client."""
    app = create_app(load_settings({"data_dir": str(tmp_path / "len"), "login_max_failures": 10_000}))
    from conftest import Env
    return Env(app, app.state.settings)


# ------------------------------------------------------------------ setting up the questions
def test_first_sign_in_requires_three_different_questions(env):
    _new_user(env)
    a = Api(env.app)
    r = a.login("pat", setup=False)
    assert r.status_code == 200 and r.json()["mfa_pending"] == "QUESTIONS" and r.json()["permissions"] == []
    assert a.get("/api/dashboard").status_code == 401
    cat = Api(env.app).get("/api/auth/security-questions").json()
    assert len(cat) >= 8 and {"code", "text"} <= set(cat[0])

    def setup(qs):
        return a.post("/api/auth/setup/security-questions", {"questions": [{"question": q, "answer": x} for q, x in qs]})
    assert setup(QUESTION_ANSWERS[:2]).status_code == 422
    assert setup([QUESTION_ANSWERS[0]] * 3).status_code == 422
    assert setup([("NOPE", "x1"), *QUESTION_ANSWERS[1:]]).status_code == 422
    assert setup([("FIRST_TEACHER", " ! "), *QUESTION_ANSWERS[1:]]).status_code == 422
    r = setup(QUESTION_ANSWERS)
    assert r.status_code == 200 and r.json()["mfa_pending"] is None and "financial.view" in r.json()["permissions"]
    a.csrf = r.json()["csrf_token"]
    assert a.get("/api/dashboard").status_code == 200
    assert Api(env.app).login("pat", setup=False).json()["mfa_pending"] is None       # not asked again
    ev = env.auditor.get("/api/audit-events?action=SECURITY_QUESTIONS_SET").json()["items"][0]
    assert "Rex" not in str(ev) and ev["after"]["questions"] == [q for q, _ in QUESTION_ANSWERS]


def test_answers_hashed_and_loosely_compared(env, app):
    _new_user(env)
    Api(app).login("pat")
    with _db(app) as db:
        rows = db.query(UserSecurityQuestion).filter(UserSecurityQuestion.user_id == _user(app, "pat").id).all()
    assert len(rows) == 3 and all(r.answer_hash.startswith("$argon2") and "Rex" not in r.answer_hash for r in rows)
    assert recovery.normalize_answer("Rex") == recovery.normalize_answer(" rex ") == recovery.normalize_answer("REX!") == "rex"
    for variant in ("rex", " REX! ", "R-e-x"):
        _set(app, "pat", reset_question_slot=2, reset_question_at=dt.datetime.utcnow())   # FIRST_PET
        a = Api(app)
        a.pre_csrf()
        r = a.post("/api/auth/forgot/complete", {"username": "pat", "answer": variant, "new_password": NEW_PW + variant.strip(" !-"),
                                                 "new_password_confirmation": NEW_PW + variant.strip(" !-")})
        assert r.status_code == 200, (variant, r.text)


def test_my_account_change_needs_the_current_password(env):
    r = env.bu.put("/api/me/security-questions", {"current_password": "wrong", "questions": [
        {"question": "FIRST_BOOK", "answer": "Matilda"}, {"question": "DREAM_JOB", "answer": "pilot"},
        {"question": "FIRST_PET", "answer": "Rex"}]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "INCORRECT_PASSWORD"
    r = env.bu.put("/api/me/security-questions", {"current_password": PASSWORD, "questions": [
        {"question": "FIRST_BOOK", "answer": "Matilda"}, {"question": "DREAM_JOB", "answer": "pilot"},
        {"question": "FIRST_PET", "answer": "Rex"}]})
    assert r.status_code == 200 and [q["code"] for q in r.json()["questions"]] == ["FIRST_BOOK", "DREAM_JOB", "FIRST_PET"]
    assert "answer" not in str(env.bu.get("/api/me/security-questions").json()).lower().replace("answers", "")


def test_existing_users_set_them_up_at_the_next_sign_in(env, app):
    with _db(app) as db:            # an upgraded installation: nobody has questions yet
        db.query(UserSecurityQuestion).delete()
        db.commit()
    assert Api(app).login("budgetuser", setup=False).json()["mfa_pending"] == "QUESTIONS"


# ------------------------------------------------------------------ Forgot password
def test_local_reset_with_the_answer_alone(env, app):
    _new_user(env)
    pat = Api(app)
    pat.login("pat")
    r, start = _forgot(app, "pat")
    assert start["needs_code"] is False and start["question"]["text"].endswith("?")
    assert r.status_code == 200, r.text
    assert pat.get("/api/dashboard").status_code == 401                            # signed out everywhere
    assert Api(app).login("pat").status_code == 401
    me = Api(app).login("pat", NEW_PW).json()
    assert [n["kind"] for n in me["sign_in_notices"]] == ["PASSWORD_RESET"]
    assert "using your security question" in me["sign_in_notices"][0]["message"]
    ev = env.auditor.get("/api/audit-events?action=PASSWORD_RESET_SELF_SERVICE").json()["items"][0]
    assert ev["after"]["method"] == "question_only" and ev["category"] == "SECURITY"
    notes = env.admin.get("/api/security-notices").json()
    assert notes[0]["kind"] == "PASSWORD_RESET" and "Pat Person reset their password" in notes[0]["message"]
    # dismissing
    x = Api(app)
    x.login("pat", NEW_PW)
    assert x.post("/api/me/sign-in-notices/dismiss").status_code == 200
    assert Api(app).login("pat", NEW_PW).json()["sign_in_notices"] == []
    assert env.admin.post(f"/api/security-notices/{notes[0]['id']}/dismiss").json() == []
    assert env.bu.get("/api/security-notices").status_code == 403


def test_wrong_answer_and_password_rules(env, app):
    _new_user(env)
    Api(app).login("pat")
    r, _ = _forgot(app, "pat", pw="short")
    assert r.status_code == 422                                                     # not counted
    assert _user(app, "pat").failed_attempts == 0
    r, _ = _forgot(app, "pat", answer="nope")
    assert r.status_code == 400 and r.json()["error"]["message"] == recovery.WRONG_MESSAGE
    u = _user(app, "pat")
    assert u.failed_attempts == 1 and u.reset_question_slot is None                 # a new question next time


def test_same_question_until_a_failure_or_timeout(env, app):
    _new_user(env)
    Api(app).login("pat")
    a = Api(app)
    a.pre_csrf()
    first = a.post("/api/auth/forgot/start", {"username": "pat"}).json()["question"]["code"]
    assert {a.post("/api/auth/forgot/start", {"username": "pat"}).json()["question"]["code"] for _ in range(5)} == {first}
    _set(app, "pat", reset_question_at=dt.datetime.utcnow() - dt.timedelta(minutes=recovery.QUESTION_MINUTES + 1))
    a.post("/api/auth/forgot/start", {"username": "pat"})
    assert _user(app, "pat").reset_question_at > dt.datetime.utcnow() - dt.timedelta(minutes=1)   # picked again


def test_unknown_or_disabled_username_looks_the_same(lenient):
    env, app = lenient, lenient.app
    _new_user(env)
    Api(app).login("pat")
    a = Api(app)
    a.pre_csrf()
    ghost = a.post("/api/auth/forgot/start", {"username": "nobody-here"})
    real = a.post("/api/auth/forgot/start", {"username": "pat"})
    assert ghost.status_code == real.status_code == 200
    assert set(ghost.json()) == set(real.json()) and set(ghost.json()["question"]) == set(real.json()["question"])
    assert ghost.json()["question"]["code"] in recovery.QUESTIONS
    again = a.post("/api/auth/forgot/start", {"username": "nobody-here"}).json()["question"]["code"]
    assert again == ghost.json()["question"]["code"]                                  # stable like a real one
    for answer in [x for _, x in QUESTION_ANSWERS]:
        r = a.post("/api/auth/forgot/complete", {"username": "nobody-here", "answer": answer, "new_password": NEW_PW,
                                                 "new_password_confirmation": NEW_PW})
        assert r.status_code in (400, 409)
        if r.status_code == 400:
            assert r.json()["error"]["message"] == recovery.WRONG_MESSAGE
        a.post("/api/auth/forgot/start", {"username": "nobody-here"})
    # a disabled user never succeeds, even with the right answer
    uid = _user(app, "pat").id
    env.admin.patch(f"/api/users/{uid}", {"active": False})
    for _ in range(3):
        r, _s = _forgot(app, "pat")
        assert r.status_code == 400


def test_server_needs_a_code_and_spends_a_recovery_code(tmp_path):
    app = create_app(load_settings({"data_dir": str(tmp_path / "srv"), "mode": "server", "login_max_failures": 10_000}))
    a = Api(app)
    a.pre_csrf()
    assert a.post("/api/system/initialize", ADMIN).status_code == 200
    a.csrf = a.get("/api/auth/me").json()["csrf_token"]
    s = a.post("/api/auth/mfa/enroll/start", {}).json()
    totp = pyotp.TOTP(s["secret"].replace(" ", ""))
    r = a.post("/api/auth/mfa/enroll/confirm", {"code": totp.now()})
    codes = r.json()["recovery_codes"]
    assert r.json()["me"]["mfa_pending"] == "QUESTIONS"                     # after two-step: the questions
    a.csrf = r.json()["me"]["csrf_token"]
    assert a.setup_questions().json()["mfa_pending"] is None
    r, start = _forgot(app, "admin")
    assert start["needs_code"] is True and r.status_code == 400                     # the answer alone is not enough
    r, _ = _forgot(app, "admin", code="000000")
    assert r.status_code == 400
    r, _ = _forgot(app, "admin", code=codes[0])
    assert r.status_code == 200, r.text
    with _db(app) as db:
        from fmpoc.models import MfaRecoveryCode
        assert db.query(MfaRecoveryCode).filter(MfaRecoveryCode.used_at.is_not(None)).count() == 1
    r, _ = _forgot(app, "admin", code=codes[0], pw=NEW_PW + "x")
    assert r.status_code == 400                                                      # spent
    r, _ = _forgot(app, "admin", code=totp.at(time.time() + 30), pw=NEW_PW + "y")
    assert r.status_code == 200, r.text
    b = Api(app)
    b.pre_csrf()
    r = b.post("/api/auth/login", {"username": "admin", "password": NEW_PW + "y"})
    assert r.json()["mfa_pending"] == "VERIFY"                                      # trusted browsers were revoked
    b.csrf = r.json()["csrf_token"]
    b.csrf = b.post("/api/auth/mfa/verify", {"code": codes[1]}).json()["csrf_token"]
    methods = [x["after"]["method"] for x in b.get("/api/audit-events?action=PASSWORD_RESET_SELF_SERVICE").json()["items"]]
    assert methods == ["question_and_authenticator", "question_and_recovery_code"]


def test_local_with_two_step_needs_a_code(env, app):
    s = env.bu.post("/api/auth/mfa/enroll/start", {}).json()
    totp = pyotp.TOTP(s["secret"].replace(" ", ""))
    assert env.bu.post("/api/auth/mfa/enroll/confirm", {"code": totp.now()}).status_code == 200
    r, start = _forgot(app, "budgetuser")
    assert start["needs_code"] is True and r.status_code == 400
    r, _ = _forgot(app, "budgetuser", code=totp.at(time.time() + 30))
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ failed attempts and locks
def test_escalating_locks_disable_and_notices(lenient):
    env, app = lenient, lenient.app
    _new_user(env)
    Api(app).login("pat")

    def bad_login():
        return Api(app).login("pat", "Wrong-Password-1", setup=False)
    for _ in range(4):
        assert bad_login().status_code == 401
    r, _ = _forgot(app, "pat", answer="nope")                                       # reset failures count too
    assert r.status_code == 400
    u = _user(app, "pat")
    assert u.failed_attempts == 5 and u.locked_until is not None
    # locked: refused without checking, even the right password; the answer does not say whether it was right
    r = Api(app).login("pat", setup=False)
    assert r.status_code == 429 and r.json()["error"]["message"] == recovery.LOCKED_MESSAGE
    assert bad_login().status_code == 429 and _user(app, "pat").failed_attempts == 5
    r, _ = _forgot(app, "pat")
    assert r.status_code == 429
    assert env.admin.get("/api/security-notices").json() == []                       # 15 minutes: no notice yet
    # the lock survives a restart
    app2 = create_app(app.state.settings)
    assert Api(app2).login("pat", setup=False).status_code == 429
    # 10 -> 1 hour (+ notice), 15 -> 24 hours, 20 -> disabled
    expect = {10: 60, 15: 1440}
    for n in range(6, 21):
        _set(app, "pat", locked_until=None)
        assert bad_login().status_code == 401
        u = _user(app, "pat")
        if n in expect:
            assert abs((u.locked_until - dt.datetime.utcnow()).total_seconds() / 60 - expect[n]) < 2
        if n == 10:
            notes = env.admin.get("/api/security-notices").json()
            assert notes[0]["kind"] == "ACCOUNT_LOCKED" and "Pat Person" in notes[0]["message"]
    u = _user(app, "pat")
    assert u.active is False and u.failed_attempts == 20
    assert env.admin.get("/api/security-notices").json()[0]["kind"] == "ACCOUNT_DISABLED"
    ev = env.auditor.get("/api/audit-events?action=ACCOUNT_DISABLED_FAILED_ATTEMPTS").json()["items"]
    assert ev and ev[0]["category"] == "SECURITY"
    assert Api(app).login("pat", setup=False).status_code == 401                     # disabled
    users = {x["username"]: x for x in env.admin.get("/api/users").json()}
    assert users["pat"]["failed_attempts"] == 20 and users["pat"]["active"] is False
    # an Administrator re-enables it: the count is cleared, the user is told at the next sign-in
    env.admin.patch(f"/api/users/{u.id}", {"active": True})
    me = Api(app).login("pat").json()
    assert "FAILED_ATTEMPTS" in [n["kind"] for n in me["sign_in_notices"]]
    assert _user(app, "pat").failed_attempts == 0


def test_success_resets_the_count(lenient):
    env, app = lenient, lenient.app
    for _ in range(3):
        Api(app).login("budgetuser", "Wrong-Password-1")
    assert _user(app, "budgetuser").failed_attempts == 3
    assert Api(app).login("budgetuser").status_code == 200
    assert _user(app, "budgetuser").failed_attempts == 0


def test_thresholds_from_the_settings(tmp_path):
    app = create_app(load_settings({"data_dir": str(tmp_path / "cfg"), "login_max_failures": 10_000,
                                    "lockout_1_failures": 2, "lockout_1_minutes": 3, "lockout_disable_failures": 4}))
    from conftest import Env
    env = Env(app, app.state.settings)
    _new_user(env)
    Api(app).login("pat")
    for _ in range(2):
        Api(app).login("pat", "Wrong-Password-1")
    u = _user(app, "pat")
    assert u.locked_until is not None and (u.locked_until - dt.datetime.utcnow()).total_seconds() < 200
    _set(app, "pat", locked_until=None)
    for _ in range(2):
        Api(app).login("pat", "Wrong-Password-1")
    assert _user(app, "pat").active is False


def test_unknown_usernames_are_braked_like_accounts(env, app):
    for _ in range(5):
        assert Api(app).login("ghost-user", "Wrong-Password-1").status_code in (401, 429)
    assert Api(app).login("ghost-user", "Wrong-Password-1").status_code == 429


# ------------------------------------------------------------------ Administrator tools and host commands
def test_admin_reset_security_questions(env, app):
    _new_user(env)
    Api(app).login("pat")
    uid = _user(app, "pat").id
    assert env.admin.post(f"/api/users/{uid}/reset-security-questions", {"reason": ""}).status_code == 422
    r = env.admin.post(f"/api/users/{uid}/reset-security-questions", {"reason": "Forgot the answers"})
    assert r.status_code == 200 and r.json()["security_questions_set"] is False
    assert Api(app).login("pat", setup=False).json()["mfa_pending"] == "QUESTIONS"
    ev = env.admin.get("/api/audit-events?action=SECURITY_QUESTIONS_RESET").json()["items"][0]
    assert ev["after"]["reason"] == "Forgot the answers"
    assert env.bm.post(f"/api/users/{uid}/reset-security-questions", {"reason": "x"}).status_code == 403


def test_host_reset_password_and_reset_mfa_reenable(env, app, capsys):
    data_dir = str(app.state.settings.data_dir)
    _new_user(env)
    Api(app).login("pat")
    _set(app, "pat", active=False, failed_attempts=20)
    assert main(["reset-password", "--user", "PAT", "--data-dir", data_dir]) == 0
    out = capsys.readouterr().out
    temp = out.split("Temporary password for 'pat': ")[1].split()[0]
    assert "enabled again" in out
    u = _user(app, "pat")
    assert u.active and u.failed_attempts == 0 and u.must_change_password
    a = Api(app)
    r = a.login("pat", temp, setup=False)
    assert r.json()["mfa_pending"] == "PASSWORD"
    assert a.post("/api/auth/setup/password", {"new_password": temp, "new_password_confirmation": temp}).status_code == 422
    r = a.post("/api/auth/setup/password", {"new_password": NEW_PW, "new_password_confirmation": NEW_PW})
    assert r.status_code == 200 and r.json()["mfa_pending"] is None
    assert Api(app).login("pat", NEW_PW, setup=False).json()["mfa_pending"] is None
    ev = env.admin.get("/api/audit-events?action=USER_PASSWORD_RESET").json()["items"][0]
    assert ev["after"]["via"] == "host_cli" and temp not in str(ev)
    # reset-mfa also re-enables and clears the count
    _set(app, "pat", active=False, failed_attempts=20)
    assert main(["reset-mfa", "--user", "pat", "--data-dir", data_dir, "--reason", "locked out"]) == 0
    u = _user(app, "pat")
    assert u.active and u.failed_attempts == 0
    assert main(["reset-password", "--user", "nobody", "--data-dir", data_dir]) == 1


def test_users_list_shows_questions_and_lock(lenient):
    env, app = lenient, lenient.app
    _new_user(env)
    for _ in range(5):
        Api(app).login("pat", "Wrong-Password-1", setup=False)
    users = {x["username"]: x for x in env.admin.get("/api/users").json()}
    assert users["pat"]["security_questions_set"] is False and users["pat"]["locked_until"]
    assert users["budgetuser"]["security_questions_set"] is True and users["budgetuser"]["locked_until"] is None
