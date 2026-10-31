"""2.4.0 (#425): attachment deduplication - identical content is stored once per workspace and linked.

BR-ATT-DEDUP-001..004 / AC-ATT-DEDUP-001..008 (recorded in docs/implementation-notes.md); regression for BR-073/074,
BR-099/100, BR-069/070, BR-077 and AC-ATT-001..004, AC-SEC-014..017, AC-AUD-001/003.
"""
from __future__ import annotations

import hashlib
import shutil

import pytest
from sqlalchemy import select

from conftest import png_bytes
from fmpoc import audit as audit_mod
from fmpoc.models import Attachment
from fmpoc.services import attachments as att_svc


def _up(env, owner_type, owner_id, name, data, client=None, anyway=False):
    c = client or env.ru
    extra = "&attach_anyway=true" if anyway else ""
    return c.c.post(f"/api/attachments?owner_type={owner_type}&owner_id={owner_id}{extra}",
                    files={"file": (name, data)}, headers={"X-CSRF-Token": c.csrf})


def _txn(env, base, amount="10.00"):
    return env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": amount}],
                   date="2026-08-01")


def _rows(env, *ids):
    with env.app.state.session_factory() as db:
        return [db.get(Attachment, i) for i in ids]


def _files(settings) -> list:
    return [p for p in settings.attachments_dir.rglob("*.bin")]


def _added_event(env, att_id):
    ev = env.auditor.get(f"/api/audit-events?action=ATTACHMENT_ADDED&object_type=attachment&object_id={att_id}").json()
    return ev["items"][0]


def test_identical_file_on_another_record_is_linked_not_stored_again(env, base, settings):
    """AC-ATT-DEDUP-001: a match on a different record is a silent link; each record keeps its own attachment."""
    t1, t2 = _txn(env, base), _txn(env, base, "11.00")
    data = png_bytes((9, 9))
    r1 = _up(env, "transaction", t1["id"], "receipt.png", data)
    r2 = _up(env, "transaction", t2["id"], "copy-of-receipt.png", data)
    assert r1.status_code == 201 and r2.status_code == 201, r2.text
    a1, a2 = _rows(env, r1.json()["id"], r2.json()["id"])
    assert a1.storage_key == a2.storage_key and len(_files(settings)) == 1
    assert a2.transaction_id == t2["id"] and a2.original_filename == "copy-of-receipt.png"
    # AC-SEC-014 / BR-099: the response does not reveal the other record
    assert set(r2.json()) == set(r1.json()) and r2.json()["transaction_id"] == t2["id"]
    # each record serves the content through its own attachment
    for att_id in (a1.id, a2.id):
        got = env.bu.get(f"/api/attachments/{att_id}/content")
        assert got.status_code == 200 and got.content == data
    # AC-AUD-001 + the link note on the second add only
    assert _added_event(env, a1.id)["before"] is None
    assert "shares_file_with_attachment_id" not in _added_event(env, a1.id)["after"]
    assert _added_event(env, a2.id)["after"]["shares_file_with_attachment_id"] == a1.id


def test_same_file_twice_on_one_record_warns_and_user_decides(env, base, settings):
    """AC-ATT-DEDUP-002/003: server-side DUPLICATE_ON_RECORD; Cancel adds nothing, Attach anyway adds a linked record."""
    t = _txn(env, base)
    data = png_bytes((7, 7))
    first = _up(env, "transaction", t["id"], "a.png", data)
    assert first.status_code == 201
    again = _up(env, "transaction", t["id"], "b.png", data)
    assert again.status_code == 409 and again.json()["error"]["code"] == "DUPLICATE_ON_RECORD"
    assert "a.png" in again.json()["error"]["message"]
    lst = env.ru.get(f"/api/attachments?owner_type=transaction&owner_id={t['id']}").json()
    assert [a["original_filename"] for a in lst] == ["a.png"]           # Cancel = nothing added
    added = env.auditor.get("/api/audit-events?action=ATTACHMENT_ADDED&object_type=attachment").json()["items"]
    assert len(added) == 1
    ok = _up(env, "transaction", t["id"], "b.png", data, anyway=True)   # Attach anyway (AC-ATT-003)
    assert ok.status_code == 201, ok.text
    lst = env.ru.get(f"/api/attachments?owner_type=transaction&owner_id={t['id']}").json()
    assert [a["original_filename"] for a in lst] == ["a.png", "b.png"] and len(_files(settings)) == 1
    # a removed copy no longer counts as "already attached here"
    assert env.ru.post(f"/api/attachments/{lst[1]['id']}/remove").status_code == 200
    assert env.ru.post(f"/api/attachments/{lst[0]['id']}/remove").status_code == 200
    assert _up(env, "transaction", t["id"], "c.png", data).status_code == 201


def test_same_record_warning_on_fiscal_year_and_allocation(env, base):
    """The rule applies to every owner type (Fiscal Year documents of different types included)."""
    data = png_bytes((5, 6))
    fy = base["fy"]["id"]
    assert _up(env, "fiscal_year", fy, "plan.png", data, client=env.bm).status_code == 201
    r = env.bm.c.post(f"/api/attachments?owner_type=fiscal_year&owner_id={fy}&document_type=APPROVAL",
                      files={"file": ("approval.png", data)}, headers={"X-CSRF-Token": env.bm.csrf})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_ON_RECORD"
    t = _txn(env, base)
    alloc = t["allocations"][0]["id"]
    assert _up(env, "allocation", alloc, "x.png", data).status_code == 201          # other record: linked silently
    assert _up(env, "allocation", alloc, "y.png", data).status_code == 409


def test_validation_runs_before_any_match(env, base):
    """AC-SEC-016/017 unchanged: a disguised or oversized file is rejected even when identical content is stored."""
    t1, t2 = _txn(env, base), _txn(env, base, "12.00")
    data = png_bytes((8, 8))
    assert _up(env, "transaction", t1["id"], "ok.png", data).status_code == 201
    assert _up(env, "transaction", t2["id"], "fake.pdf", data).status_code == 415     # PNG content named .pdf
    assert _up(env, "transaction", t2["id"], "fake.jpg", data).status_code == 415
    big = data + b"\0" * (5 * 1024 * 1024)
    assert _up(env, "transaction", t2["id"], "big.png", big).status_code == 413
    assert env.ru.get(f"/api/attachments?owner_type=transaction&owner_id={t2['id']}").json() == []


def test_removing_one_link_never_affects_another(env, base, settings):
    """AC-ATT-DEDUP-004 / BR-069, BR-070: a shared file stays while any record references it."""
    t1, t2 = _txn(env, base), _txn(env, base, "13.00")
    data = png_bytes((6, 6))
    a1 = _up(env, "transaction", t1["id"], "r.png", data).json()
    a2 = _up(env, "transaction", t2["id"], "r.png", data).json()
    assert env.ru.post(f"/api/attachments/{a1['id']}/remove").status_code == 200
    got = env.bu.get(f"/api/attachments/{a2['id']}/content")
    assert got.status_code == 200 and got.content == data
    assert len(_files(settings)) == 1
    # a VOID transaction keeps its attachment; uploading the same file elsewhere still links to it
    v = env.ru.post(f"/api/transactions/{t2['id']}/void", {"reason": "wrong", "confirm_irreversible": True})
    assert v.status_code == 200, v.text
    t3 = _txn(env, base, "14.00")
    a3 = _up(env, "transaction", t3["id"], "r.png", data).json()
    assert _rows(env, a3["id"])[0].storage_key == _rows(env, a2["id"])[0].storage_key


def test_failed_save_keeps_a_shared_file(env, base, settings, monkeypatch):
    """AC-AUD-003 + #425: the add rolls back with its audit event and never removes a file another record uses."""
    t1, t2 = _txn(env, base), _txn(env, base, "15.00")
    data = png_bytes((10, 3))
    a1 = _up(env, "transaction", t1["id"], "r.png", data).json()
    real = audit_mod.record

    def boom(db, ctx, action, *a, **k):
        if action == "ATTACHMENT_ADDED":
            raise RuntimeError("audit store unavailable")
        return real(db, ctx, action, *a, **k)
    monkeypatch.setattr(audit_mod, "record", boom)
    assert _up(env, "transaction", t2["id"], "r.png", data).status_code == 500
    # a new (unshared) file written by the failed request is removed as before
    assert _up(env, "transaction", t2["id"], "new.png", png_bytes((11, 3))).status_code == 500
    monkeypatch.setattr(audit_mod, "record", real)
    assert env.ru.get(f"/api/attachments?owner_type=transaction&owner_id={t2['id']}").json() == []
    assert len(_files(settings)) == 1
    assert env.bu.get(f"/api/attachments/{a1['id']}/content").content == data


def _duplicate_on_disk(env, settings, att_id) -> Attachment:
    """Simulates data from before 2.4.0: a second attachment row with its own copy of the same content."""
    with env.app.state.session_factory() as db:
        a = db.get(Attachment, att_id)
        src = att_svc.path_for(settings, a)
        key = hashlib.md5(f"{att_id}-copy".encode()).hexdigest()
        dst = settings.attachments_dir / key[:2] / (key + ".bin")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        db.get(Attachment, att_id).storage_key = key
        db.commit()
        return key


def test_upgrade_merge_links_existing_duplicates_and_removes_extra_copies(env, base, settings):
    """AC-ATT-DEDUP-005 (BR-ATT-DEDUP-004): existing duplicates are merged after a verified hash; a damaged file is
    left alone and reported; a second run has nothing to do."""
    t1, t2, t3 = _txn(env, base), _txn(env, base, "16.00"), _txn(env, base, "17.00")
    data, other = png_bytes((12, 12)), png_bytes((13, 13))
    a1 = _up(env, "transaction", t1["id"], "r.png", data).json()["id"]
    a2 = _up(env, "transaction", t2["id"], "r.png", data).json()["id"]
    b1 = _up(env, "transaction", t1["id"], "s.png", other).json()["id"]
    b2 = _up(env, "transaction", t3["id"], "s.png", other).json()["id"]
    _duplicate_on_disk(env, settings, a2)                         # a clean old-style duplicate
    bad_key = _duplicate_on_disk(env, settings, b2)               # ... and one whose stored copy got damaged
    (settings.attachments_dir / bad_key[:2] / (bad_key + ".bin")).write_bytes(b"\x89PNG damaged")
    assert len(_files(settings)) == 4
    res = att_svc.merge_duplicate_files(env.app.state.session_factory, settings)
    assert res["records_relinked"] == 1 and res["files_removed"] == 1 and res["files_not_verified"] == 1
    r1, r2, s1, s2 = _rows(env, a1, a2, b1, b2)
    assert r1.storage_key == r2.storage_key
    assert s1.storage_key != s2.storage_key and s2.storage_key == bad_key   # damaged one left as it is
    assert len(_files(settings)) == 3
    assert env.bu.get(f"/api/attachments/{a2}/content").content == data
    ev = env.auditor.get("/api/audit-events?action=ATTACHMENT_FILES_MERGED").json()["items"]
    assert len(ev) == 1 and ev[0]["after"]["records_relinked"] == 1 and ev[0]["after"]["files_not_verified"] == 1
    again = att_svc.merge_duplicate_files(env.app.state.session_factory, settings)
    assert again["records_relinked"] == 0 and again["files_removed"] == 0


def test_merge_runs_at_start_up(env, base, settings):
    """AC-ATT-DEDUP-005: the merge runs when the application starts (after the migrations)."""
    from fmpoc.app import create_app
    t1, t2 = _txn(env, base), _txn(env, base, "18.00")
    data = png_bytes((14, 2))
    _up(env, "transaction", t1["id"], "r.png", data)
    a2 = _up(env, "transaction", t2["id"], "r.png", data).json()["id"]
    _duplicate_on_disk(env, settings, a2)
    assert len(_files(settings)) == 2
    create_app(settings)
    assert len(_files(settings)) == 1


def test_generated_copies_share_the_rule(env, base, settings):
    """AC-ATT-DEDUP-006 (decision 2): application-generated attachments link to an identical stored file too."""
    from fmpoc.services.checkprint import service as cp
    t1, t2 = _txn(env, base), _txn(env, base, "19.00")
    pdf = b"%PDF-1.4\n% generated copy\n%%EOF\n"
    with env.app.state.session_factory() as db:
        from types import SimpleNamespace
        from fmpoc.models import RegisterTransaction, User
        u = db.scalar(select(User).where(User.username == "reguser"))
        ctx = SimpleNamespace(workspace_id=u.workspace_id, user=u, correlation_id=None, ip=None)
        x1, p1 = cp.store_transaction_document(db, ctx, settings, db.get(RegisterTransaction, t1["id"]), "c1.pdf", pdf)
        x2, p2 = cp.store_transaction_document(db, ctx, settings, db.get(RegisterTransaction, t2["id"]), "c2.pdf", pdf)
        db.commit()
        assert p1 is not None and p2 is None and x1.storage_key == x2.storage_key
    assert len(_files(settings)) == 1


def test_diagnostics_counts_shared_files(env, base):
    """AC-ATT-DEDUP-008: the Administrator's health check shows counts only (no names or owners)."""
    t1, t2 = _txn(env, base), _txn(env, base, "20.00")
    data = png_bytes((15, 4))
    _up(env, "transaction", t1["id"], "r.png", data)
    _up(env, "transaction", t2["id"], "r.png", data)
    h = env.admin.get("/api/system/health-check").json()
    assert h["attachment_files"] == 1 and h["attachment_records"] == 2 and h["attachment_shared_files"] == 1
    assert h["attachment_bytes_saved"] == len(data)


@pytest.mark.parametrize("name", ["../r.png", "..\\r.png", "/etc/r.png"])
def test_traversal_names_still_metadata_only_when_linked(env, base, settings, name):
    """AC-SEC-015 / AC-ATT-004: a linked upload never writes or overwrites anything; its name stays metadata."""
    t1, t2 = _txn(env, base), _txn(env, base, "21.00")
    data = png_bytes((16, 5))
    _up(env, "transaction", t1["id"], "r.png", data)
    before = sorted(p.name for p in _files(settings))
    r = _up(env, "transaction", t2["id"], name, data)
    assert r.status_code == 201 and r.json()["original_filename"] == "r.png"
    assert sorted(p.name for p in _files(settings)) == before
