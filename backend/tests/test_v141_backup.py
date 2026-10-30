"""v1.4.1 CR-023 / CR-024 / CR-025: encrypted backup, restore after and before initialization."""
import io
import json
import tarfile
import time
from pathlib import Path

import pytest

from conftest import ADMIN, PASSWORD, PDF_BYTES, Api

from fmpoc.app import create_app
from fmpoc.config import load_settings
from fmpoc.services import backup as bk

PASS = "correct horse battery staple 42"


def _wait(client: Api, url: str, timeout: float = 60) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(url).json()
        if j.get("state") != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def _backup(env) -> bytes:
    a = env.admin
    r = a.post("/api/system/backups", {"password": PASSWORD, "passphrase": PASS, "passphrase_confirmation": PASS})
    assert r.status_code == 202, r.text
    j = _wait(a, f"/api/system/backups/{r.json()['id']}")
    assert j["state"] == "done", j
    assert j["result"]["filename"].startswith("pennywarden-backup-acme-org-") and j["result"]["filename"].endswith(".fmbak")
    assert "_path" not in j["result"]
    d = a.get(f"/api/system/backups/{r.json()['id']}/download")
    assert d.status_code == 200 and d.content.startswith(bk.MAGIC)
    return d.content


def _restore(client: Api, data: bytes, passphrase=PASS, password=None, confirm=None, part=7000,
             domains=("all",), missing_users="add") -> dict:
    """2.2.0 (#319): after the backup is checked, System/About asks what to restore (choose); `domains` answers it
    (default everything, as before). domains=None stops at the choice and returns the waiting job."""
    r = client.post("/api/system/restore/uploads", {"size": len(data), "filename": "b.fmbak"})
    assert r.status_code == 201, r.text
    uid = r.json()["upload_id"]
    off = 0
    while off < len(data):
        chunk = data[off:off + part]
        r = client.c.put(f"/api/system/restore/uploads/{uid}?offset={off}", content=chunk,
                         headers={"X-CSRF-Token": client.csrf, "Content-Type": "application/octet-stream"})
        assert r.status_code == 200, r.text
        off += len(chunk)
    body = {"passphrase": passphrase}
    if password is not None:
        body.update(password=password, confirm=confirm)
    r = client.post(f"/api/system/restore/uploads/{uid}/start", body)
    assert r.status_code == 202, r.text
    jid = r.json()["id"]
    j = _wait_choice(client, f"/api/system/restore/jobs/{jid}")
    if j["state"] != "choose" or domains is None:
        return j
    r = client.post(f"/api/system/restore/jobs/{jid}/choose", {"domains": list(domains), "missing_users": missing_users})
    assert r.status_code == 200, r.text
    return _wait(client, f"/api/system/restore/jobs/{jid}")


def _wait_choice(client: Api, url: str, timeout: float = 60) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(url).json()
        if j.get("state") != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("job did not reach the choice")


@pytest.fixture
def data_env(env, base):
    acct = base["acct"]["id"]
    t = env.txn(acct, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "12.34"}])
    r = env.ru.c.post(f"/api/attachments?owner_type=transaction&owner_id={t['id']}",
                      files={"file": ("receipt.pdf", PDF_BYTES)}, headers={"X-CSRF-Token": env.ru.csrf})
    assert r.status_code == 201
    return {"txn": t, "att": r.json(), "acct": acct}


def test_backup_validation_and_permissions(env):
    a = env.admin
    ok = {"password": PASSWORD, "passphrase": PASS, "passphrase_confirmation": PASS}
    assert a.post("/api/system/backups", {**ok, "passphrase": "short", "passphrase_confirmation": "short"}).status_code == 422
    assert a.post("/api/system/backups", {**ok, "passphrase_confirmation": PASS + "x"}).status_code == 422
    r = a.post("/api/system/backups", {**ok, "password": "wrong-password-1"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "INCORRECT_PASSWORD"
    assert env.bm.post("/api/system/backups", ok).status_code == 403
    assert env.auditor.post("/api/system/backups", ok).status_code == 403
    # an initialized system never accepts an anonymous restore
    anon = Api(env.app)
    anon.pre_csrf()
    assert anon.post("/api/system/restore/uploads", {"size": 10}).status_code == 401
    assert env.bm.post("/api/system/restore/uploads", {"size": 10}).status_code == 403


def test_backup_file_is_encrypted(env, data_env):
    blob = _backup(env)
    assert b"Acme Org" not in blob and PDF_BYTES[:20] not in blob and b"SQLite format" not in blob
    header = json.loads(blob[8:8 + int.from_bytes(blob[6:8], "big")])
    assert header["kdf"] == "scrypt" and header["cipher"] == "AES-256-GCM" and "passphrase" not in json.dumps(header)
    ev = env.admin.get("/api/audit-events?action=BACKUP_CREATED").json()["items"][0]
    assert ev["after"]["counts"]["transactions"] == 1 and PASS not in json.dumps(ev)


def test_restore_after_initialization_round_trip(env, data_env, tmp_path):
    blob = _backup(env)
    # change the data after the backup
    extra = env.entity("Created After Backup")
    a = env.admin
    # confirmation, password and passphrase are checked
    r = a.post("/api/system/restore/uploads", {"size": len(blob)})
    uid = r.json()["upload_id"]
    a.c.put(f"/api/system/restore/uploads/{uid}?offset=0", content=blob,
            headers={"X-CSRF-Token": a.csrf, "Content-Type": "application/octet-stream"})
    assert a.post(f"/api/system/restore/uploads/{uid}/start",
                  {"passphrase": PASS, "password": PASSWORD, "confirm": "yes"}).status_code == 422
    assert a.post(f"/api/system/restore/uploads/{uid}/start",
                  {"passphrase": PASS, "password": "nope-nope-nope", "confirm": "RESTORE"}).status_code == 400
    j = _restore(a, blob, passphrase="wrong passphrase!!", password=PASSWORD, confirm="RESTORE")
    assert j["state"] == "failed" and "Wrong passphrase" in j["error"] and "nothing was changed" in j["error"]
    assert env.bu.get(f"/api/entities/{extra['id']}").status_code == 200  # untouched
    # the real restore
    j = _restore(a, blob, password=PASSWORD, confirm="RESTORE")
    assert j["state"] == "done", j
    assert j["result"]["workspace"] == "Acme Org" and j["result"]["counts"]["transactions"] == 1
    assert [s for s in j["steps_done"] if s][:2] == ["Decrypting and checking the backup",
                                                    "Checking versions and the encryption key"]
    # every session was ended
    assert a.get("/api/auth/me").status_code == 401
    assert env.bu.get("/api/dashboard").status_code == 401
    # sign in again with the accounts from the backup
    bu = Api(env.app)
    assert bu.login("budgetuser").status_code == 200
    assert bu.get(f"/api/entities/{extra['id']}").status_code == 404  # created after the backup
    att = bu.get(f"/api/attachments/{data_env['att']['id']}/content")
    assert att.status_code == 200 and att.content == PDF_BYTES
    bm = Api(env.app)
    bm.login("budgetmgr")
    rv = bm.post(f"/api/bank-accounts/{data_env['acct']}/reveal", {})
    assert rv.status_code == 200 and rv.json().get("account_number")  # encryption key restored with the data
    adm = Api(env.app)
    adm.login("admin")
    ev = adm.get("/api/audit-events?action=SYSTEM_RESTORED").json()["items"][0]
    assert ev["after"]["restored_by"] == "admin" and ev["after"]["via"] == "system_about"
    pre = env.settings.data_dir / bk.PRE_RESTORE_DIR
    assert (pre / "database" / "fmpoc.sqlite3").is_file() and (pre / "secrets").is_dir()
    # work files are cleaned up
    assert not any(p.name.startswith("upload-") for p in (env.settings.data_dir / bk.WORK_DIR).iterdir())


def test_restore_in_initialization_wizard(env, data_env, tmp_path):
    blob = _backup(env)
    fresh = create_app(load_settings({"data_dir": str(tmp_path / "fresh")}))
    anon = Api(fresh)
    anon.pre_csrf()
    assert anon.get("/api/system/status").json()["initialized"] is False
    j = _restore(anon, blob)
    assert j["state"] == "done", j
    st = anon.get("/api/system/status").json()
    assert st["initialized"] is True and st["workspace_name"] == "Acme Org"
    # after initialization the anonymous restore is closed
    assert anon.post("/api/system/restore/uploads", {"size": 10}).status_code == 401
    bu = Api(fresh)
    assert bu.login("budgetuser").status_code == 200
    assert bu.get(f"/api/attachments/{data_env['att']['id']}/content").content == PDF_BYTES
    ev = Api(fresh)
    ev.login("admin")
    e = ev.get("/api/audit-events?action=SYSTEM_RESTORED").json()["items"][0]
    assert e["after"]["via"] == "initialization_wizard"
    # the key file of the fresh install was replaced by the backup's key
    assert (tmp_path / "fresh" / "secrets" / "portable-encryption-key.json").read_bytes() == \
        (env.settings.secrets_dir / "portable-encryption-key.json").read_bytes()


def test_damaged_truncated_and_foreign_files(env, data_env, tmp_path):
    blob = _backup(env)
    bad = bytearray(blob)
    bad[len(bad) // 2] ^= 0x55
    j = _restore(env.admin, bytes(bad), password=PASSWORD, confirm="RESTORE")
    assert j["state"] == "failed" and ("damaged" in j["error"] or "Wrong passphrase" in j["error"])
    j = _restore(env.admin, blob[:-40], password=PASSWORD, confirm="RESTORE")
    assert j["state"] == "failed" and ("incomplete" in j["error"] or "damaged" in j["error"])
    j = _restore(env.admin, b"PK\x03\x04 not a backup", password=PASSWORD, confirm="RESTORE")
    assert j["state"] == "failed" and "not a PennyWarden backup" in j["error"]
    assert env.bu.get("/api/dashboard").status_code == 200  # nothing changed, still signed in


def _encrypt(tar_bytes: bytes, out: Path) -> None:
    import base64
    import secrets as s
    salt, prefix = s.token_bytes(16), s.token_bytes(8)
    hdr = json.dumps({"format": 1, "kdf": "scrypt", **bk.SCRYPT, "salt": base64.b64encode(salt).decode(),
                      "nonce_prefix": base64.b64encode(prefix).decode(), "app_version": "1.4.1"}).encode()
    header = bk.MAGIC + len(hdr).to_bytes(2, "big") + hdr
    with open(out, "wb") as f:
        f.write(header)
        w = bk._EncryptWriter(f, bk._derive(PASS, salt, **bk.SCRYPT), header, prefix)
        w.write(tar_bytes)
        w.finish()


def test_unsafe_archive_member_is_refused(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        ti = tarfile.TarInfo("../../evil.txt")
        ti.size = 4
        t.addfile(ti, io.BytesIO(b"evil"))
    _encrypt(buf.getvalue(), tmp_path / "evil.fmbak")
    with pytest.raises(bk.BackupError, match="unexpected file"):
        bk.unpack(tmp_path / "evil.fmbak", PASS, tmp_path / "out")
    assert not (tmp_path.parent / "evil.txt").exists()


def test_newer_backup_is_refused(env, data_env, tmp_path):
    blob = _backup(env)
    (tmp_path / "b.fmbak").write_bytes(blob)
    bk.unpack(tmp_path / "b.fmbak", PASS, tmp_path / "u")
    import sqlite3
    con = sqlite3.connect(tmp_path / "u" / "data" / "database" / "fmpoc.sqlite3")
    con.execute("UPDATE alembic_version SET version_num='9999_future'")
    con.commit()
    con.close()
    with pytest.raises(bk.BackupError, match="newer version"):
        bk.check_compatible(tmp_path / "u" / "data", {"0008_mfa"})


def test_upload_parts_retry_and_order(env):
    a = env.admin
    uid = a.post("/api/system/restore/uploads", {"size": 10}).json()["upload_id"]
    put = lambda off, data: a.c.put(f"/api/system/restore/uploads/{uid}?offset={off}", content=data,  # noqa: E731
                                    headers={"X-CSRF-Token": a.csrf, "Content-Type": "application/octet-stream"})
    assert put(0, b"12345").json()["received"] == 5
    assert put(0, b"12345").json()["received"] == 5  # retried part
    assert put(8, b"xx").status_code == 409  # gap
    assert put(5, b"678901").status_code == 422  # longer than announced
    assert a.get(f"/api/system/restore/uploads/{uid}").json()["received"] == 5
    assert a.post(f"/api/system/restore/uploads/{uid}/start",
                  {"passphrase": PASS, "password": PASSWORD, "confirm": "RESTORE"}).status_code == 409
    # the upload part is not bound by the 6 MB attachment body limit (up to 20 MB), but beyond it is refused
    big = a.post("/api/system/restore/uploads", {"size": 30 * 1024 * 1024}).json()["upload_id"]
    r = a.c.put(f"/api/system/restore/uploads/{big}?offset=0", content=b"x" * (8 * 1024 * 1024),
                headers={"X-CSRF-Token": a.csrf, "Content-Type": "application/octet-stream"})
    assert r.status_code == 200
    r = a.c.put(f"/api/system/restore/uploads/{big}?offset={8 * 1024 * 1024}", content=b"x" * (22 * 1024 * 1024),
                headers={"X-CSRF-Token": a.csrf, "Content-Type": "application/octet-stream"})
    assert r.status_code == 413
    # CSRF is required
    assert a.c.put(f"/api/system/restore/uploads/{uid}?offset=5", content=b"x").status_code == 403


def test_maintenance_mode_blocks_other_requests(env):
    env.app.state.maintenance = "restore"
    try:
        r = env.bu.get("/api/dashboard")
        assert r.status_code == 503 and r.json()["error"]["code"] == "MAINTENANCE"
        assert env.bu.get("/api/health").status_code == 200
        assert env.bu.get("/api/system/status").json()["maintenance"] == "restore"
    finally:
        env.app.state.maintenance = None
    assert env.bu.get("/api/dashboard").status_code == 200


def test_about_notice_updated(env):
    about = env.admin.get("/api/system/about").json()
    assert "Backup / Restore" in about["backup_notice"] and about["restore_max_mb"] == 20480
    assert env.bu.get("/api/system/about").json()["restore_max_mb"] is None
    assert ADMIN  # fixture constants imported for clarity


def test_stream_encryption_multi_record_order_and_truncation(tmp_path):
    import os
    payload = os.urandom(int(3.5 * bk.CHUNK))
    _encrypt(payload, tmp_path / "x.fmbak")
    assert bk.decrypt_file(tmp_path / "x.fmbak", PASS, tmp_path / "x.out")["kdf"] == "scrypt"
    assert (tmp_path / "x.out").read_bytes() == payload
    raw = (tmp_path / "x.fmbak").read_bytes()
    hl = int.from_bytes(raw[6:8], "big")
    pos, recs = 8 + hl, []
    while pos < len(raw):
        n = int.from_bytes(raw[pos:pos + 4], "big")
        recs.append(raw[pos:pos + 4 + n])
        pos += 4 + n
    assert len(recs) == 4
    head = raw[:8 + hl]
    (tmp_path / "swap.fmbak").write_bytes(head + recs[1] + recs[0] + recs[2] + recs[3])
    with pytest.raises(bk.BackupError, match="Wrong passphrase|damaged"):
        bk.decrypt_file(tmp_path / "swap.fmbak", PASS, tmp_path / "o1")
    (tmp_path / "cut.fmbak").write_bytes(head + b"".join(recs[:3]))  # last (final) record removed
    with pytest.raises(bk.BackupError, match="incomplete"):
        bk.decrypt_file(tmp_path / "cut.fmbak", PASS, tmp_path / "o2")
    (tmp_path / "hdr.fmbak").write_bytes(raw.replace(b"1.4.1", b"9.9.9", 1))  # the header is authenticated
    with pytest.raises(bk.BackupError):
        bk.decrypt_file(tmp_path / "hdr.fmbak", PASS, tmp_path / "o3")
