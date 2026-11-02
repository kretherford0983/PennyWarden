"""1.7.0 (#70): rename to PennyWarden. A local installation keeps its data (the default Fundwarden folder is renamed
once), backups made as Fundwarden restore, names shown to users are PennyWarden, and install.sh can still install a
1.6.6 - 1.6.8 release, which only has the Fundwarden package name."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fmpoc import config, legal
from fmpoc.services import mfa
from tests.test_v150_install_sh import PKG, ROOT, STUB, _tarball, gh, pytestmark, run  # noqa: F401  (gh is a fixture)

FUNDWARDEN_PKG = "Fundwarden-linux-x64-portable.tar.gz"


def _dirs(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("FM_DATA_DIR", raising=False)
    fundwarden, poc = config.previous_default_data_dirs()
    return poc, fundwarden, config.default_data_dir()


def _fill(folder: Path, marker: bytes, port: int) -> None:
    (folder / "database").mkdir(parents=True)
    (folder / "database" / "fmpoc.sqlite3").write_bytes(marker)
    (folder / "secrets").mkdir()
    (folder / "secrets" / "key.json").write_text("{}")
    (folder / "attachments").mkdir()
    (folder / "attachments" / "0a1b").write_bytes(b"receipt")
    (folder / "config.toml").write_text(f"[server]\nport = {port}\n")


def test_names(tmp_path, monkeypatch):
    poc, fundwarden, new = _dirs(tmp_path, monkeypatch)
    assert config.APP_NAME == "PennyWarden" and new.name.lower() == "pennywarden"
    assert fundwarden.name.lower() == "fundwarden" and poc.name in ("FinancialManagementPOC", "financial-management-poc")
    assert len({poc, fundwarden, new}) == 3
    assert mfa.ISSUER == "PennyWarden"
    assert legal.SOURCE_URL == "https://github.com/kretherford0983/PennyWarden"


def test_fundwarden_data_folder_is_renamed_once_and_keeps_every_file(tmp_path, monkeypatch):
    poc, fundwarden, new = _dirs(tmp_path, monkeypatch)
    _fill(fundwarden, b"fundwarden data", 9002)
    s = config.load_settings()
    assert s.data_dir == new and not fundwarden.exists()
    assert (new / "database" / "fmpoc.sqlite3").read_bytes() == b"fundwarden data"
    assert (new / "secrets" / "key.json").is_file() and (new / "attachments" / "0a1b").read_bytes() == b"receipt"
    assert s.port == 9002                                   # config.toml moved with the folder and is still read
    assert config.load_settings().data_dir == new           # second start: nothing left to adopt


def test_fundwarden_folder_wins_over_the_one_from_before_1_6_6(tmp_path, monkeypatch):
    """A machine that went 1.6.5 -> 1.6.6 normally has only the Fundwarden folder; if an older one is also there
    (e.g. restored by hand), the newest name is the installation in use and the older folder is left alone."""
    poc, fundwarden, new = _dirs(tmp_path, monkeypatch)
    _fill(poc, b"old", 9001)
    _fill(fundwarden, b"current", 9002)
    s = config.load_settings()
    assert s.data_dir == new and s.port == 9002
    assert (new / "database" / "fmpoc.sqlite3").read_bytes() == b"current"
    assert (poc / "database" / "fmpoc.sqlite3").read_bytes() == b"old" and not fundwarden.exists()


def test_existing_pennywarden_folder_wins_and_fundwarden_is_left_alone(tmp_path, monkeypatch):
    poc, fundwarden, new = _dirs(tmp_path, monkeypatch)
    _fill(fundwarden, b"fundwarden data", 9002)
    _fill(new, b"pennywarden data", 9003)
    s = config.load_settings()
    assert s.data_dir == new and s.port == 9003
    assert (fundwarden / "database" / "fmpoc.sqlite3").read_bytes() == b"fundwarden data"


def test_explicit_data_dir_never_touches_the_fundwarden_folder(tmp_path, monkeypatch):
    poc, fundwarden, new = _dirs(tmp_path, monkeypatch)
    _fill(fundwarden, b"fundwarden data", 9002)
    chosen = tmp_path / "elsewhere"
    assert config.load_settings({"data_dir": str(chosen)}).data_dir == chosen
    monkeypatch.setenv("FM_DATA_DIR", str(chosen))
    assert config.load_settings().data_dir == chosen
    assert fundwarden.is_dir() and not new.exists()


def test_fundwarden_folder_is_used_in_place_when_it_cannot_be_renamed(tmp_path, monkeypatch, capsys):
    poc, fundwarden, new = _dirs(tmp_path, monkeypatch)
    _fill(fundwarden, b"fundwarden data", 9002)

    def boom(self, target):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "rename", boom)
    s = config.load_settings()
    assert s.data_dir == fundwarden and s.port == 9002
    assert "could not be renamed" in capsys.readouterr().err


def test_backup_made_as_fundwarden_restores(env, tmp_path, monkeypatch):
    """A backup written by 1.6.6 - 1.6.8 has the file name fundwarden-backup-... and "app": "Fundwarden" in its
    manifest. Neither is looked at on restore: it is unpacked and checked exactly like a PennyWarden one."""
    from tests.test_v141_backup import PASS, _wait
    from conftest import PASSWORD
    from fmpoc.services import backup as bk

    monkeypatch.setattr(config, "APP_NAME", "Fundwarden")          # write the file the way 1.6.8 does
    r = env.admin.post("/api/system/backups", {"password": PASSWORD, "passphrase": PASS, "passphrase_confirmation": PASS})
    assert r.status_code == 202, r.text
    j = _wait(env.admin, f"/api/system/backups/{r.json()['id']}")
    assert j["state"] == "done" and j["result"]["filename"].startswith("fundwarden-backup-"), j
    old = tmp_path / j["result"]["filename"]
    old.write_bytes(env.admin.get(f"/api/system/backups/{r.json()['id']}/download").content)
    monkeypatch.setattr(config, "APP_NAME", "PennyWarden")
    manifest = bk.unpack(old, PASS, tmp_path / "unpacked")
    assert manifest["app"] == "Fundwarden" and (tmp_path / "unpacked" / "data" / "database").is_dir()
    # and a backup written now carries the new name
    r = env.admin.post("/api/system/backups", {"password": PASSWORD, "passphrase": PASS, "passphrase_confirmation": PASS})
    j = _wait(env.admin, f"/api/system/backups/{r.json()['id']}")
    assert j["state"] == "done" and j["result"]["filename"].startswith("pennywarden-backup-"), j


def test_install_sh_installs_a_release_from_before_this_rename(gh, tmp_path):  # noqa: F811
    """Rollback to (or deliberate install of) v1.6.8: that release only has the Fundwarden package name."""
    tag, tb = "v1.6.8", _tarball()
    sums = "".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in ((FUNDWARDEN_PKG, tb), ("install-server.sh", STUB)))
    gh.files.update({f"/dl/{tag}/{FUNDWARDEN_PKG}": tb, f"/dl/{tag}/install-server.sh": STUB,
                     f"/dl/{tag}/SHA256SUMS.txt": sums.encode()})
    code, out, recorded = run(gh, tmp_path, "--version", tag)
    assert code == 0, out
    assert "before the rename" in out
    assert recorded and recorded[0].endswith(FUNDWARDEN_PKG)


def test_no_user_facing_file_still_says_fundwarden():
    """The old name may appear only where it is history or migration: the installers and their docs, the tests of
    the two renames, the changelog and the documents of earlier versions
    (the per-release notes are in docs/archive/, which this check does not scan - 2.4.0 #473)."""
    allowed = {"CHANGELOG.md", "README.md", "THIRD-PARTY-NOTICES.txt", "backend/fmpoc/config.py", "docs/upgrade.md",
               "docs/implementation-notes.md", "docs/backup-restore.md", "docs/branching.md",
               "docs/deployment.md", "docs/configuration.md",  # 1.8.0 (#112): the earlier folder names
               "packaging/linux/install-server.sh", "packaging/linux/install.sh",
               "backend/tests/test_v166_rename.py", "backend/tests/test_v170_rename.py"}
    hits = []
    for base, pattern in ((ROOT / "backend" / "fmpoc", "**/*.py"), (ROOT / "frontend" / "src", "**/*.ts*"),
                          (ROOT / "frontend", "index.html"), (ROOT / "packaging", "**/*"), (ROOT / "scripts", "*"),
                          (ROOT / ".github", "**/*"), (ROOT, "README.md"), (ROOT / "docs", "*.md")):
        for f in base.glob(pattern):
            rel = f.relative_to(ROOT).as_posix()
            if not f.is_file() or rel in allowed or "/static/" in rel or "node_modules" in rel:
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if re.search("fundwarden", text, re.I):
                hits.append(rel)
    assert not hits, hits
