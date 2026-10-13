"""Attachments, audit and cross-cutting security.
AC-ATT-001..004, AC-AUD-001..005, AC-SEC-009..013, AC-SEC-015..019, AC-SEC-021, AC-SEC-023, AC-SEC-025."""
import json
import os
import re
import sqlite3
from pathlib import Path

import pytest
from conftest import PASSWORD, PDF_BYTES, Api, jpeg_bytes, png_bytes


def upload(client, owner_type, owner_id, name, data, mime="application/octet-stream"):
    return client.c.post(f"/api/attachments?owner_type={owner_type}&owner_id={owner_id}",
                         files={"file": (name, data, mime)}, headers={"X-CSRF-Token": client.csrf})


@pytest.fixture
def txn(env, base):
    return env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "10.00"}])


# ------------------------------------------------------------------ attachments
def test_ac_att_001_003_allowed_formats_and_multiple(env, txn):
    for name, data in [("a.pdf", PDF_BYTES), ("b.png", png_bytes()), ("c.jpg", jpeg_bytes()), ("d.JPEG", jpeg_bytes())]:
        r = upload(env.ru, "transaction", txn["id"], name, data)
        assert r.status_code == 201, (name, r.text)
    lst = env.bu.get(f"/api/attachments?owner_type=transaction&owner_id={txn['id']}").json()
    assert [a["mime_type"] for a in lst] == ["application/pdf", "image/png", "image/jpeg", "image/jpeg"]
    c = env.bu.get(lst[1]["content_url"])
    assert c.status_code == 200 and c.content == png_bytes() and c.headers["content-type"] == "image/png"
    assert c.headers["x-content-type-options"] == "nosniff"
    # allocation-level attachment
    aid = txn["allocations"][0]["id"]
    assert upload(env.ru, "allocation", aid, "inv.pdf", PDF_BYTES).status_code == 201
    # exactly 5 MB accepted
    big_ok = PDF_BYTES[:-6] + b" " * (5 * 1024 * 1024 - len(PDF_BYTES)) + b"%%EOF\n"
    assert len(big_ok) == 5 * 1024 * 1024
    assert upload(env.ru, "transaction", txn["id"], "big.pdf", big_ok).status_code == 201


def test_ac_att_002_ac_sec_017_rejected_formats_and_size(env, txn):
    for name, data in [("a.gif", b"GIF89a....."), ("a.exe", b"MZ\x90\x00"), ("a.txt", b"hello"),
                       ("a.webp", b"RIFF....WEBP"), ("a.tiff", b"II*\x00")]:
        assert upload(env.ru, "transaction", txn["id"], name, data).status_code == 415, name
    too_big = PDF_BYTES + b"0" * (5 * 1024 * 1024)
    r = upload(env.ru, "transaction", txn["id"], "big.pdf", too_big, "application/pdf")
    assert r.status_code == 413
    assert env.bu.get(f"/api/attachments?owner_type=transaction&owner_id={txn['id']}").json() == []


def test_ac_sec_016_disguised_files_rejected(env, txn):
    elf = b"\x7fELF\x02\x01\x01" + b"\x00" * 100
    mz = b"MZ" + b"\x00" * 200
    script = b"#!/bin/sh\nrm -rf /\n"
    html = b"<html><script>alert(1)</script></html>"
    for name, data, mime in [("r.pdf", mz, "application/pdf"), ("r.jpg", elf, "image/jpeg"), ("r.png", script, "image/png"),
                             ("r.jpeg", html, "image/jpeg"), ("r.pdf", png_bytes(), "application/pdf"),
                             ("r.png", PDF_BYTES, "image/png"), ("r.png", b"\x89PNG\r\n\x1a\n" + b"junk" * 10, "image/png"),
                             ("r.pdf", b"%PDF-1.4 no trailer", "application/pdf")]:
        r = upload(env.ru, "transaction", txn["id"], name, data, mime)
        assert r.status_code == 415, name


def test_ac_sec_015_ac_att_004_path_traversal(env, txn, settings):
    names = ["../receipt.pdf", "..\\receipt.pdf", "/etc/passwd.pdf", "C:\\Windows\\win.pdf", "../../../../app.pdf",
             "..%2F..%2Fx.pdf", "\x00evil.pdf"]
    for n in names:
        r = upload(env.ru, "transaction", txn["id"], n, PDF_BYTES)
        assert r.status_code == 201, n
        meta = r.json()
        assert "/" not in meta["original_filename"] and "\\" not in meta["original_filename"]
    base = settings.attachments_dir.resolve()
    stored = [p for p in base.rglob("*") if p.is_file()]
    assert len(stored) == len(names)
    for p in stored:
        assert re.fullmatch(r"[0-9a-f]{32}\.bin", p.name) and base in p.resolve().parents
    assert not (settings.data_dir / "receipt.pdf").exists() and not (settings.attachments_dir.parent / "receipt.pdf").exists()
    con = sqlite3.connect(settings.database_path)
    keys = [r[0] for r in con.execute("SELECT storage_key FROM attachment")]
    con.close()
    assert all(re.fullmatch(r"[0-9a-f]{32}", k) for k in keys)


def test_attachment_permissions(env, base, txn):
    assert upload(env.bm, "transaction", txn["id"], "a.pdf", PDF_BYTES).status_code == 403
    assert upload(env.ru, "fiscal_year", base["fy"]["id"], "a.pdf", PDF_BYTES).status_code == 403
    assert upload(env.auditor, "transaction", txn["id"], "a.pdf", PDF_BYTES).status_code == 403
    assert upload(env.admin, "transaction", txn["id"], "a.pdf", PDF_BYTES).status_code == 403
    assert upload(env.ru, "transaction", 99999, "a.pdf", PDF_BYTES).status_code == 404


# ------------------------------------------------------------------ audit
def test_ac_aud_001_002_snapshots(env, base):
    e = env.entity("Audit Me")
    env.ru.patch(f"/api/entities/{e['id']}", {"notes": "changed"})
    ev = env.auditor.get(f"/api/audit-events?object_type=entity&object_id={e['id']}&sort=id&direction=asc").json()["items"]
    assert ev[0]["action"] == "ENTITY_CREATED" and ev[0]["before"] is None and ev[0]["after"]["display_name"] == "Audit Me"
    assert ev[1]["action"] == "ENTITY_UPDATED" and ev[1]["before"]["notes"] is None and ev[1]["after"]["notes"] == "changed"
    assert ev[1]["actor_username"] == "reguser" and ev[1]["timestamp"]


def test_ac_aud_003_atomic_rollback(env, base, monkeypatch):
    from fmpoc import audit

    def boom(*a, **k):
        raise RuntimeError("audit store unavailable")

    before = env.bu.get(f"/api/register?bank_account_id={base['acct']['id']}").json()["transactions"]
    monkeypatch.setattr(audit, "record", boom)
    for mod in ("register", "entities", "budgets", "fiscal_years", "bank_accounts"):
        monkeypatch.setattr(f"fmpoc.services.{mod}.audit.record", boom, raising=False)
    r = env.ru.post("/api/transactions", {"bank_account_id": base["acct"]["id"], "transaction_type": "WITHDRAWAL",
                                          "transaction_date": "2026-08-01",
                                          "allocations": [{"budget_id": base["exp_leaf"], "amount": "10.00"}]})
    assert r.status_code == 500 and "audit store" not in r.text
    r = env.ru.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "Ghost Corp"})
    assert r.status_code == 500
    r = env.bm.patch(f"/api/budgets/{base['exp']['id']}", {"amount": "1.00"})
    assert r.status_code == 500
    monkeypatch.undo()
    assert env.bu.get(f"/api/register?bank_account_id={base['acct']['id']}").json()["transactions"] == before
    assert "Ghost Corp" not in str(env.bu.get("/api/entities").json())
    assert env.bu.get(f"/api/budgets?fiscal_year_id={base['fy']['id']}").json()["expense"][0]["amount"] == "100000.00"


def test_ac_aud_003_db_level_audit_failure_rolls_back(env, base, settings):
    """Simulate an audit persistence failure inside SQLite (trigger) - business change must roll back."""
    con = sqlite3.connect(settings.database_path)
    con.execute("CREATE TRIGGER t_fail BEFORE INSERT ON audit_event WHEN NEW.action='ENTITY_CREATED' "
                "BEGIN SELECT RAISE(ABORT, 'fail'); END;")
    con.commit()
    con.close()
    r = env.ru.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "Atomic Test"})
    assert r.status_code == 500
    con = sqlite3.connect(settings.database_path)
    assert con.execute("SELECT COUNT(*) FROM entity WHERE organization_name='Atomic Test'").fetchone()[0] == 0
    con.close()


def test_ac_aud_004_append_only(env, base, settings):
    for c in (env.admin, env.auditor, env.bm, env.ru):
        assert c.delete("/api/audit-events/1").status_code in (403, 404, 405)
        assert c.patch("/api/audit-events/1", {"action": "X"}).status_code in (403, 404, 405)
        assert c.post("/api/audit-events", {"action": "X"}).status_code in (403, 404, 405)
    con = sqlite3.connect(settings.database_path)
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE audit_event SET action='TAMPER'")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("DELETE FROM audit_event")
    con.close()


def test_ac_aud_005_ac_sec_019_sensitive_values_absent(env, base, settings):
    acct = env.account(number="7777888899990000")
    env.bm.post(f"/api/bank-accounts/{acct['id']}/reveal")
    env.bm.patch(f"/api/bank-accounts/{acct['id']}", {"account_number": "7777888899991111"})
    bad = Api(env.app)
    bad.pre_csrf()
    bad.post("/api/auth/login", {"username": "reguser", "password": "Wrong-Pass-Attempt-1"})
    env.ru.post("/api/auth/change-password", {"current_password": PASSWORD, "new_password": "Changed-Pass-2024",
                                               "new_password_confirmation": "Changed-Pass-2024"})
    env.ru.post("/api/transactions", {"bank_account_id": "not-an-int"})  # error path
    env.app.state.engine.dispose()
    con = sqlite3.connect(settings.database_path)
    audit_dump = json.dumps(con.execute("SELECT * FROM audit_event").fetchall())
    hashes = [r[0] for r in con.execute("SELECT password_hash FROM app_user")]
    sessions = [r[0] for r in con.execute("SELECT token_hash FROM auth_session")]
    csrf = [r[0] for r in con.execute("SELECT csrf_token FROM auth_session")]
    con.close()
    key = json.loads((settings.secrets_dir / "portable-encryption-key.json").read_text())
    log = (settings.logs_dir / "fmpoc.log").read_text()
    secrets = ["7777888899990000", "7777888899991111", PASSWORD, "Wrong-Pass-Attempt-1", "Changed-Pass-2024",
               key["enc_key"], key["fp_key"], env.ru.c.cookies.get("fm_session"), env.bm.c.cookies.get("fm_session"),
               *hashes, *sessions, *csrf]
    for s in secrets:
        assert s not in audit_dump, s[:6]
        assert s not in log, s[:6]
    assert "$argon2" not in log and "$argon2" not in audit_dump


# ------------------------------------------------------------------ injection / validation / mass assignment
INJECTIONS = ["' OR 1=1 --", "\" OR \"\"=\"", "1; DROP TABLE entity; --", "%' OR '1'='1", "') UNION SELECT * FROM app_user --",
              "_", "%"]


def test_ac_sec_009_sql_injection_resistance(env, base):
    env.entity("Alpha Co")
    env.entity("Beta Co")
    total = len(env.bu.get("/api/entities").json())
    for s in INJECTIONS:
        r = env.bu.get("/api/entities", params={"search": s})
        assert r.status_code == 200 and len(r.json()) == 0, s  # no filter bypass / extra records
        r = env.bu.get("/api/register", params={"bank_account_id": base["acct"]["id"], "search": s})
        assert r.status_code == 200 and r.json()["transactions"] == []
        r = env.admin.get("/api/audit-events", params={"actor": s})
        assert r.status_code == 200 and r.json()["items"] == []
    for s in INJECTIONS:  # injection-looking text is stored literally
        e = env.ru.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": s,
                                          "confirmations": ["DUPLICATE_ENTITY"]})
        assert e.status_code == 201 and e.json()["organization_name"] == s
    assert len(env.bu.get("/api/entities").json()) == total + len(INJECTIONS)
    # wildcard characters are escaped: searching "%" or "_" matches only the literal names containing them
    und = [e["display_name"] for e in env.bu.get("/api/entities", params={"search": "_"}).json()]
    assert sorted(und) == sorted(s for s in INJECTIONS if "_" in s)
    pct = [e["display_name"] for e in env.bu.get("/api/entities", params={"search": "%"}).json()]
    assert sorted(pct) == sorted(["%' OR '1'='1", "%"])
    # path parameters
    assert env.bu.get("/api/entities/1%20OR%201=1").status_code == 422
    r = env.bu.get("/api/fiscal-years/1'--")
    assert r.status_code == 422 and "sql" not in r.text.lower()


def test_ac_sec_010_structural_allowlists(env, base):
    for q in ["sort=password_hash", "sort=name;DROP", "direction=sideways", "sort=id desc"]:
        assert env.bu.get(f"/api/entities?{q}").status_code == 422, q
        assert env.admin.get(f"/api/audit-events?{q}").status_code == 422, q
    assert env.bu.get(f"/api/register?bank_account_id={base['acct']['id']}&sort=1").status_code == 422
    assert env.bu.get(f"/api/register?bank_account_id={base['acct']['id']}&status=deleted").status_code == 422
    assert env.bu.get("/api/entities?status=everything").status_code == 422


def test_ac_sec_011_script_payloads_stored_as_inert_text(env, base):
    payload = "<script>alert(1)</script><img src=x onerror=alert(2)>"
    e = env.ru.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": payload, "notes": payload}).json()
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "1.00",
                                                     "description": payload, "notes": payload}], notes=payload)
    r = env.bu.get(f"/api/transactions/{t['id']}")
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["allocations"][0]["description"] == payload  # returned as data, rendered as text by React
    assert e["organization_name"] == payload
    # the SPA shell is never built from user data and CSP forbids inline script
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert "unsafe-inline" not in r.headers["content-security-policy"].split("script-src")[1].split(";")[0]


def test_ac_sec_012_server_side_validation(env, base):
    a = base["acct"]["id"]
    bad = [
        {"bank_account_id": a, "transaction_type": "TRANSFER", "allocations": [{"budget_id": base["exp_leaf"], "amount": "1"}]},
        {"bank_account_id": a, "transaction_type": "WITHDRAWAL", "transaction_date": "2026-13-45",
         "allocations": [{"budget_id": base["exp_leaf"], "amount": "1"}]},
        {"bank_account_id": a, "transaction_type": "WITHDRAWAL", "allocations": [{"budget_id": base["exp_leaf"], "amount": "1.999"}]},
        {"bank_account_id": a, "transaction_type": "WITHDRAWAL", "allocations": [{"budget_id": base["exp_leaf"], "amount": "-5"}]},
        {"bank_account_id": a, "transaction_type": "WITHDRAWAL", "allocations": [{"budget_id": base["exp_leaf"]}]},
        {"bank_account_id": a, "transaction_type": "WITHDRAWAL", "notes": "x" * 5000,
         "allocations": [{"budget_id": base["exp_leaf"], "amount": "1"}]},
        {"transaction_type": "WITHDRAWAL", "allocations": [{"budget_id": base["exp_leaf"], "amount": "1"}]},
        {"bank_account_id": a, "transaction_type": "DEPOSIT", "check_number": "12",
         "allocations": [{"budget_id": base["inc_leaf"], "amount": "1"}]},
        {"bank_account_id": a, "transaction_type": "WITHDRAWAL", "transaction_date": "1800-01-01",
         "allocations": [{"budget_id": base["exp_leaf"], "amount": "1"}]},
    ]
    for b in bad:
        r = env.ru.post("/api/transactions", b)
        assert r.status_code == 422, (b, r.text)
        assert "Traceback" not in r.text
    for b in [{"entity_type": "ALIEN", "organization_name": "x"},
              {"entity_type": "ORGANIZATION", "organization_name": "x", "email": "bad"},
              {"entity_type": "ORGANIZATION", "organization_name": "x" * 201},
              {"entity_type": "ORGANIZATION", "organization_name": "x", "phone": "<b>1</b>"}]:
        assert env.ru.post("/api/entities", b).status_code == 422, b
    r = env.ru.c.post("/api/entities", content=b"{not json", headers={"X-CSRF-Token": env.ru.csrf,
                                                                     "Content-Type": "application/json"})
    assert r.status_code == 422


def test_ac_sec_013_mass_assignment(env, base):
    acct = base["acct"]
    other = env.account()
    cases = [
        (env.ru, "post", "/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "M", "is_system": True}),
        (env.ru, "post", "/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "M", "created_by_user_id": 1}),
        (env.ru, "post", "/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "M", "entity_number": "ENT-1"}),
        (env.bm, "patch", f"/api/budgets/{base['exp']['id']}", {"locked": True}),
        (env.bm, "patch", f"/api/budgets/{base['exp']['id']}", {"status": "APPROVED"}),
        (env.bm, "patch", f"/api/budgets/{base['exp']['id']}", {"is_budget_zero": True}),
        (env.bm, "patch", f"/api/fiscal-years/{base['fy']['id']}", {"closed_at": "2026-01-01T00:00:00"}),
        (env.bm, "patch", f"/api/fiscal-years/{base['fy']['id']}", {"status": "CLOSED"}),
        (env.bm, "patch", f"/api/bank-accounts/{acct['id']}", {"current_balance": "0.00"}),
        (env.bm, "patch", f"/api/bank-accounts/{acct['id']}", {"status": "CLOSED"}),
        (env.bm, "patch", f"/api/bank-accounts/{acct['id']}", {"is_primary": False}),
        (env.admin, "post", "/api/users", {"username": "zz1", "email": "z@z.org", "password": "Abcdefgh12345",
                                           "security_domain": "FINANCIAL", "roles": ["BUDGET_USER"], "is_admin": True}),
        (env.ru, "put", "/api/me/preferences", {"theme": "dark", "roles": ["ADMINISTRATOR"]}),
        (env.ru, "post", "/api/auth/change-password", {"current_password": PASSWORD, "new_password": "Xyzxyzxyz12345",
                                                       "new_password_confirmation": "Xyzxyzxyz12345", "security_domain": "ADMINISTRATOR"}),
    ]
    for client, m, url, body in cases:
        r = getattr(client, m)(url, body)
        assert r.status_code == 422, (url, body, r.status_code)
    t = env.txn(acct["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "5.00"}])
    for extra in [{"bank_account_id": other["id"]}, {"total": "1.00"}, {"status": "VOID"}, {"entry_timestamp": "2020-01-01"},
                  {"created_by_user_id": 1}, {"workspace_id": 2}]:
        assert env.ru.patch(f"/api/transactions/{t['id']}", extra).status_code == 422, extra
    t2 = env.ru.get(f"/api/transactions/{t['id']}").json()
    assert t2["bank_account_id"] == acct["id"] and t2["total"] == "5.00" and t2["status"] == "ACTIVE"
    b = env.bm.get(f"/api/budgets/{base['exp']['id']}").json()
    assert b["locked"] is False and b["status"] == "DRAFT"
    me = env.ru.get("/api/auth/me").json()
    assert me["roles"] == ["REGISTER_USER"]


def test_ac_sec_018_safe_error_responses(env, base, monkeypatch):
    from fmpoc.services import entities
    monkeypatch.setattr(entities, "create", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError(f"boom sqlite:///{env.settings.database_path} SELECT * FROM app_user password_hash")))
    r = env.ru.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "Err"})
    assert r.status_code == 500
    body = r.text
    for s in ["Traceback", "sqlite", "SELECT", str(env.settings.data_dir), "password_hash", "boom", ".py"]:
        assert s not in body, s
    assert r.json()["error"]["code"] == "INTERNAL_ERROR" and r.json()["error"]["correlation_id"]
    # validation errors do not echo submitted values
    r = env.ru.post("/api/auth/change-password", {"current_password": "SuperSecret-Value-1", "new_password": 5,
                                                   "new_password_confirmation": None})
    assert r.status_code == 422 and "SuperSecret-Value-1" not in r.text
    r = env.bm.post("/api/bank-accounts", {"account_name": "X", "financial_institution_entity_id": "abc",
                                           "account_type": "CHECKING", "account_number": "SECRET123456789"})
    assert r.status_code == 422 and "SECRET123456789" not in r.text
    # unknown api route
    r = env.ru.get("/api/does-not-exist")
    assert r.status_code == 404 and "Traceback" not in r.text


def test_ac_sec_021_security_headers(env):
    for url in ["/api/system/status", "/api/auth/me", "/"]:
        h = env.ru.get(url).headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"
        csp = h["content-security-policy"]
        assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp


def test_ac_sec_021_hsts_when_https_configured(tmp_path):
    from fmpoc.app import create_app
    from fmpoc.config import load_settings
    app = create_app(load_settings({"data_dir": str(tmp_path / "d"), "hsts": True, "secure_cookies": "true"}))
    from fastapi.testclient import TestClient
    c = TestClient(app, base_url="https://testserver")
    assert "max-age" in c.get("/api/system/status").headers.get("strict-transport-security", "")
    c2 = TestClient(app)
    assert "strict-transport-security" not in c2.get("/api/system/status").headers


def test_ac_sec_023_no_shell_command_construction():
    """Static review: application code never invokes a shell or builds OS commands."""
    root = Path(__file__).resolve().parents[1] / "fmpoc"
    pattern = re.compile(r"\b(os\.system|os\.popen|subprocess|shell\s*=\s*True|pty\.spawn|commands\.getoutput|eval\(|exec\()")
    # 2.0.0 (#124, #125): the one documented exception (BR-102 "if unavoidable"): the host commands `pennywarden
    # restore` / `reinitialize` stop and start the service through its manager - fixed argument lists, no shell.
    allowed = {"cli_restore.py": {"subprocess"}}
    offenders = []
    for p in root.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            if m.group(0) not in allowed.get(p.name, set()):
                offenders.append(f"{p.name}:{m.group(0)}")
    assert offenders == []
    cli = (root / "cli_restore.py").read_text(encoding="utf-8")
    uses = re.findall(r"subprocess\.\w+(?:\([^)]*)?", cli)
    assert sorted(set(uses)) == ["subprocess.SubprocessError", "subprocess.run(args, capture_output=True, text=True, "
                                                                "timeout=60, check=False"], uses
    calls = re.findall(r"_run\((\[[^\]]*\]|[^)]*)\)", cli)
    assert calls and all(c.startswith("[") or c.startswith('["sc.exe"') or c.startswith('["systemctl"') or
                         c.startswith("args: list") or c.startswith("[\"") for c in calls), calls


def test_request_body_limit(env, txn):
    huge = b"x" * (7 * 1024 * 1024)
    r = env.ru.c.post(f"/api/attachments?owner_type=transaction&owner_id={txn['id']}",
                      files={"file": ("x.pdf", huge)}, headers={"X-CSRF-Token": env.ru.csrf})
    assert r.status_code == 413


def test_no_localstorage_token_in_frontend():
    """AC-SEC-006: the SPA source never stores auth tokens in localStorage."""
    src = Path(__file__).resolve().parents[2] / "frontend" / "src"
    if not src.exists():
        pytest.skip("frontend not present")
    for p in src.rglob("*.ts*"):
        t = p.read_text(encoding="utf-8")
        assert not re.search(r"\b(localStorage|sessionStorage|indexedDB)\s*[.\[]", t), p.name
        assert "dangerouslySetInnerHTML" not in t, p.name


def test_key_file_permissions(env, settings):
    if os.name != "posix":
        pytest.skip("POSIX permissions only")
    mode = (settings.secrets_dir / "portable-encryption-key.json").stat().st_mode & 0o777
    assert mode == 0o600
