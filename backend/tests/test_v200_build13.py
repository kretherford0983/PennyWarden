"""2.0.0 build 13: polish from release-candidate testing - the host command shown to the Administrator."""
from __future__ import annotations

import types
from pathlib import Path

from fmpoc import cli_restore as cr


def settings(mode="server", data="/var/lib/pennywarden"):
    return types.SimpleNamespace(mode=mode, data_dir=Path(data))


def test_linux_server_shows_sudo_pennywarden(monkeypatch):
    monkeypatch.setattr(cr, "in_container", lambda: False)
    monkeypatch.setattr(cr.shutil, "which", lambda n: "/usr/local/bin/pennywarden")
    cmd, where = cr.host_command(settings())
    assert cmd == "sudo pennywarden" and "shell on the server" in where
    full = cr.restore_command(settings(), "/var/lib/pennywarden/pre-reinitialize/x.fmbak")
    assert full == 'sudo pennywarden restore "/var/lib/pennywarden/pre-reinitialize/x.fmbak" --use-server-key ' \
                   '--data-dir "/var/lib/pennywarden"'


def test_without_the_command_the_launchers_full_path(monkeypatch, tmp_path):
    monkeypatch.setattr(cr, "in_container", lambda: False)
    monkeypatch.setattr(cr.shutil, "which", lambda n: None)
    real = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: False if str(p) == "/usr/local/bin/pennywarden" else real(p))
    monkeypatch.setattr(cr.sys, "executable", "/opt/pennywarden/releases/20261014-1/python/bin/python3")
    assert cr.host_command(settings())[0] == "sudo /opt/pennywarden/releases/20261014-1/pennywarden"


def test_local_install_has_no_sudo(monkeypatch):
    monkeypatch.setattr(cr, "in_container", lambda: False)
    monkeypatch.setattr(cr.shutil, "which", lambda n: "/usr/local/bin/pennywarden")
    cmd, where = cr.host_command(settings(mode="local"))
    assert cmd == "pennywarden" and "quit" in where


def test_windows_shows_pennywarden_cmd_as_administrator(monkeypatch, tmp_path):
    cur = tmp_path / "current"
    (cur / "python").mkdir(parents=True)
    (cur / "PennyWarden.cmd").write_text("@echo off")
    monkeypatch.setattr(cr, "in_container", lambda: False)
    monkeypatch.setattr(cr, "os", types.SimpleNamespace(name="nt"))
    monkeypatch.setattr(cr.sys, "executable", str(cur / "python" / "python.exe"))
    cmd, where = cr.host_command(settings(data=r"C:\ProgramData\PennyWarden"))
    assert cmd == f'"{cur / "PennyWarden.cmd"}"' and "Administrator" in where and "sudo" not in cmd


def test_container_has_no_sudo(monkeypatch):
    monkeypatch.setattr(cr, "in_container", lambda: True)
    cmd, where = cr.host_command(settings())
    assert cmd == "pennywarden" and "container" in where


# ------------------------------------------------------------------ new letters and envelopes are drafts until saved
from tests.test_v200_build11 import DOCS, upload_logo  # noqa: E402
from tests.test_v200_checks import enable  # noqa: E402


def doc_count(env):
    return len(env.admin.get("/api/checks/setup").json()["documents"])


def test_a_new_template_is_a_draft_until_saved(env):
    enable(env)
    before = doc_count(env)
    d = env.admin.get(f"{DOCS}/draft?kind=LETTER").json()
    assert d["id"] is None and d["draft"] is True and d["name"] == "Invoice payment letter" and d["is_default"]
    assert d["config"]["window"] == "NONE" and d["logo"] is None
    w = env.admin.get(f"{DOCS}/draft?kind=LETTER&preset=WINDOW").json()
    assert w["name"] == "Window envelope letter" and w["config"]["window"] == "LETTER"
    # previews and the test print of the draft work without storing anything
    r = env.admin.post(f"{DOCS}/draft/preview", {"kind": "LETTER", "config": d["config"]})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    r = env.admin.post(f"{DOCS}/draft/test-print", {"kind": "ENVELOPE",
                                                    "config": env.admin.get(f"{DOCS}/draft?kind=ENVELOPE").json()["config"]})
    assert r.status_code == 200
    assert env.admin.post(f"{DOCS}/draft/preview", {"kind": "LETTER", "config": {**d["config"], "subject": "{NOPE}"}}
                          ).status_code == 422
    assert doc_count(env) == before                         # backing out keeps nothing
    assert not [e for e in env.admin.get("/api/audit-events?action=CHECK_DOCUMENT_CREATED").json()["items"]]
    # the first Save creates it, with the edited settings
    cfg = {**w["config"], "subject": "Refund"}
    r = env.admin.post(DOCS, {"kind": "LETTER", "name": "Refund letter", "config": cfg})
    assert r.status_code == 201, r.text
    saved = r.json()
    assert saved["id"] and saved["name"] == "Refund letter" and saved["config"]["subject"] == "Refund"
    assert saved["config"]["window"] == "LETTER" and doc_count(env) == before + 1
    # a name taken meanwhile is refused at Save; invalid settings too
    assert env.admin.post(DOCS, {"kind": "LETTER", "name": "refund LETTER", "config": cfg}).status_code == 409
    assert env.admin.post(DOCS, {"kind": "LETTER", "name": "X", "config": {**cfg, "evil": 1}}).status_code == 422
    for c in (env.ru, env.bm, env.auditor):
        assert c.get(f"{DOCS}/draft?kind=LETTER").status_code == 403
        assert c.post(f"{DOCS}/draft/preview", {"kind": "LETTER", "config": cfg}).status_code == 403


def test_duplicate_is_a_draft_and_saving_copies_the_logo(env):
    enable(env)
    src = env.admin.post(DOCS, {"kind": "LETTER", "name": "Invoices"}).json()
    src = upload_logo(env, src["id"])
    before = doc_count(env)
    d = env.admin.get(f"{DOCS}/draft?kind=LETTER&duplicate_of={src['id']}").json()
    assert d["id"] is None and d["name"] == "Invoices copy" and d["duplicate_of"] == src["id"]
    assert d["config"] == src["config"] and d["logo"]["from"] == src["id"]
    img = env.admin.post(f"{DOCS}/draft/preview-image", {"kind": "LETTER", "config": d["config"], "logo_from": src["id"]})
    assert img.status_code in (200, 501)
    assert doc_count(env) == before
    saved = env.admin.post(DOCS, {"kind": "LETTER", "name": d["name"], "config": d["config"],
                                  "duplicate_of": src["id"]}).json()
    assert saved["logo"] == src["logo"] and doc_count(env) == before + 1
    ev = [e for e in env.admin.get("/api/audit-events?action=CHECK_DOCUMENT_CREATED").json()["items"]
          if e["object_id"] == str(saved["id"])]
    assert ev[0]["after"]["duplicated_from"] == src["id"]


def test_reset_commands_hand_files_back_to_the_data_folders_owner(monkeypatch):
    """Build 13: `sudo pennywarden reset-mfa/reset-password` must not leave root-owned database files behind."""
    from fmpoc import __main__ as m
    seen = []
    monkeypatch.setattr(cr, "match_ownership", lambda d, parts: seen.append((d, parts)))
    m._own_again(types.SimpleNamespace(data_dir=Path("/var/lib/pennywarden")))
    assert seen == [(Path("/var/lib/pennywarden"), ["database", "logs"])]


def test_match_ownership_does_nothing_unless_root(tmp_path, monkeypatch):
    (tmp_path / "database").mkdir()
    called = []
    monkeypatch.setattr(cr.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(cr.os, "chown", lambda *a: called.append(a))
    cr.match_ownership(tmp_path, ["database"])
    assert called == []
    monkeypatch.setattr(cr.os, "geteuid", lambda: 0)
    cr.match_ownership(tmp_path, ["database"])
    assert called and all(c[1:] == (tmp_path.stat().st_uid, tmp_path.stat().st_gid) for c in called)


# ---- #230: Safari shows an inline PDF blank - the print screens ask for a picture of the very PDF
def test_printed_pdfs_have_a_picture_for_their_user_only(env, anon):
    from fmpoc.services import pdf_preview
    enable(env)
    cfg = env.admin.get(f"{DOCS}/draft?kind=ENVELOPE").json()["config"]
    r = env.admin.post(f"{DOCS}/draft/test-print", {"kind": "ENVELOPE", "config": cfg})
    token = r.headers["X-Preview-Token"]
    assert len(token) >= 32
    pic = env.admin.get(f"/api/pdf-preview/{token}")
    assert pic.status_code == 200 and pic.headers["content-type"] == "image/png"
    assert pic.content[:8] == b"\x89PNG\r\n\x1a\n" and pic.headers["X-Page-Count"] == "1"
    assert pic.headers["Cache-Control"] == "private, no-store"
    assert env.admin.get(f"/api/pdf-preview/{token}").status_code == 200        # can be shown again
    # another user, an unknown token, no session
    assert env.ru.get(f"/api/pdf-preview/{token}").status_code == 404
    assert env.admin.get("/api/pdf-preview/nope").status_code == 404
    assert env.admin.get("/api/pdf-preview/" + "x" * 65).status_code == 404
    anon.pre_csrf()
    assert anon.get(f"/api/pdf-preview/{token}").status_code == 401
    # a Register User's own PDFs (here the scale check) and the audit log PDF carry a token as well
    r = env.ru.get("/api/checks/scale-check")
    assert env.ru.get(f"/api/pdf-preview/{r.headers['X-Preview-Token']}").status_code == 200
    r = env.auditor.post("/api/audit-events/export", {"format": "pdf"})
    assert env.auditor.get(f"/api/pdf-preview/{r.headers['X-Preview-Token']}").status_code == 200
    assert "X-Preview-Token" not in env.auditor.post("/api/audit-events/export", {"format": "csv"}).headers
    # kept for a short time only
    pdf_preview.clear()
    assert env.admin.get(f"/api/pdf-preview/{token}").status_code == 404


def test_preview_store_limits(monkeypatch):
    from fmpoc.services import pdf_preview as pp
    pp.clear()
    tokens = [pp.keep(1, b"%PDF-" + bytes([i])) for i in range(pp.MAX_ENTRIES + 5)]
    assert pp.get(1, tokens[0]) is None and pp.get(1, tokens[-1]) is not None      # oldest dropped first
    assert pp.keep(1, b"x" * (pp.MAX_PDF_BYTES + 1)) is None
    t = pp.keep(2, b"%PDF-late")
    now = pp.time.monotonic()
    monkeypatch.setattr(pp.time, "monotonic", lambda: now + pp.TTL_SECONDS + 1)
    assert pp.get(2, t) is None
    pp.clear()
