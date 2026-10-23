"""2.1.0 (#240): the release is dated by the pipeline, not typed before the test -> main promotion.

- scripts/check_promotion.sh lets '## <version> — unreleased' reach main, still requires the section and still refuses
  a version that is already released; pull requests into test/main fail while an earlier, released version's heading
  still says 'unreleased'.
- scripts/release_notes.sh never prints the heading, so the published notes never say 'unreleased'.
- scripts/date_changelog.sh dates a released version's heading from its GitHub release (or --date).

Each test runs the real scripts in a throw-away copy of the repository layout with its own git repository and a local
bare 'origin' carrying the tags.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("git") and shutil.which("curl")),
                                reason="needs bash, git and curl")

CHANGELOG = """# Changelog

## {cur} — unreleased
New things.

## 2.0.0 — {prev}
Payments.

## 1.10.0 — 2026-10-10
Product page.
"""


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _repo(tmp_path: Path, version: str = "2.1.0", prev: str = "2026-10-15", tags=("v1.10.0", "v2.0.0"),
          changelog: str | None = None) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    for name in ("check_promotion.sh", "version.sh", "release_notes.sh", "date_changelog.sh"):
        shutil.copy(ROOT / "scripts" / name, repo / "scripts" / name)
    (repo / "backend" / "fmpoc").mkdir(parents=True)
    (repo / "backend" / "fmpoc" / "config.py").write_text(f'VERSION = "{version}"\n')
    (repo / "frontend").mkdir()
    (repo / "frontend" / "package.json").write_text(f'{{\n  "name": "x",\n  "version": "{version}",\n}}\n')
    (repo / "CHANGELOG.md").write_text(changelog if changelog is not None else CHANGELOG.format(cur=version, prev=prev))
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "x")
    for t in tags:
        _git(repo, "tag", t)
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "HEAD:refs/heads/main", "--tags")
    return repo


def _promote(repo: Path, base: str, head: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "scripts/check_promotion.sh", base, head], cwd=repo, capture_output=True, text=True)


def test_unreleased_heading_may_reach_main(tmp_path):
    r = _promote(_repo(tmp_path), "main", "test")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK: test -> main (version 2.1.0)" in r.stdout


def test_main_still_needs_the_section(tmp_path):
    repo = _repo(tmp_path, changelog="# Changelog\n\n## 2.0.0 — 2026-10-15\nPayments.\n")
    r = _promote(repo, "main", "test")
    assert r.returncode != 0
    assert "has no '## 2.1.0' section" in r.stdout


def test_main_refuses_a_released_version(tmp_path):
    repo = _repo(tmp_path, tags=("v1.10.0", "v2.0.0", "v2.1.0"))
    r = _promote(repo, "main", "test")
    assert r.returncode != 0
    assert "v2.1.0 is already released" in r.stdout


@pytest.mark.parametrize("base,head", [("test", "develop"), ("main", "test")])
def test_an_undated_earlier_release_blocks_test_and_main(tmp_path, base, head):
    repo = _repo(tmp_path, prev="unreleased")
    r = _promote(repo, base, head)
    assert r.returncode != 0
    assert "still says '## 2.0.0 — unreleased', but v2.0.0 is released" in r.stdout
    assert "date_changelog.sh 2.0.0" in r.stdout


def test_develop_is_not_blocked_by_an_undated_earlier_release(tmp_path):
    repo = _repo(tmp_path, prev="unreleased")
    r = _promote(repo, "develop", "feature/2.1.0-x")
    assert r.returncode == 0, r.stdout + r.stderr


def test_branch_rules_unchanged(tmp_path):
    repo = _repo(tmp_path)
    assert _promote(repo, "develop", "fix/x").returncode != 0
    assert _promote(repo, "test", "feature/x").returncode != 0
    assert _promote(repo, "main", "develop").returncode != 0
    assert _promote(repo, "main", "hotfix/x").returncode == 0


def test_release_notes_never_print_the_heading(tmp_path):
    repo = _repo(tmp_path)
    out = subprocess.run(["bash", "scripts/release_notes.sh", "2.1.0"], cwd=repo, capture_output=True, text=True,
                         check=True).stdout
    assert "unreleased" not in out
    assert out.strip() == "New things."


def test_date_changelog_with_date(tmp_path):
    repo = _repo(tmp_path, prev="unreleased")
    r = subprocess.run(["bash", "scripts/date_changelog.sh", "2.0.0", "--date", "2026-10-15"], cwd=repo,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    text = (repo / "CHANGELOG.md").read_text()
    assert "## 2.0.0 — 2026-10-15\n" in text
    assert "## 2.1.0 — unreleased" in text  # only the named version changes
    assert _promote(repo, "main", "test").returncode == 0


def test_date_changelog_already_dated_is_a_no_op(tmp_path):
    repo = _repo(tmp_path)
    before = (repo / "CHANGELOG.md").read_text()
    r = subprocess.run(["bash", "scripts/date_changelog.sh", "2.0.0"], cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0
    assert "already dated" in r.stdout
    assert (repo / "CHANGELOG.md").read_text() == before


def test_date_changelog_rejects_bad_input(tmp_path):
    repo = _repo(tmp_path, prev="unreleased")
    for args in (["2.0"], ["2.0.0", "--date", "15/10/2026"], ["9.9.9", "--date", "2026-10-15"]):
        r = subprocess.run(["bash", "scripts/date_changelog.sh", *args], cwd=repo, capture_output=True, text=True)
        assert r.returncode != 0, args


@pytest.fixture
def fake_api():
    seen: list[str] = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append(self.path)
            if self.path == "/repos/owner/PennyWarden/releases/tags/v2.0.0":
                body = json.dumps({"tag_name": "v2.0.0", "published_at": "2026-10-15T17:20:02Z"}, indent=2).encode()
                self.send_response(200)
            else:
                body = b'{"message": "Not Found"}'
                self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", seen
    srv.shutdown()


def test_date_changelog_reads_the_github_release(tmp_path, fake_api):
    api, seen = fake_api
    repo = _repo(tmp_path, prev="unreleased")
    env = {"PATH": "/usr/bin:/bin", "PENNYWARDEN_GITHUB_API": api, "PENNYWARDEN_REPO": "owner/PennyWarden",
           "TZ": "America/Chicago"}
    r = subprocess.run(["bash", "scripts/date_changelog.sh", "2.0.0"], cwd=repo, capture_output=True, text=True,
                       env=env)
    assert r.returncode == 0, r.stderr
    assert "## 2.0.0 — 2026-10-15" in (repo / "CHANGELOG.md").read_text()
    assert seen == ["/repos/owner/PennyWarden/releases/tags/v2.0.0"]
    r = subprocess.run(["bash", "scripts/date_changelog.sh", "1.10.0"], cwd=repo, capture_output=True, text=True,
                       env=env)
    assert r.returncode == 0 and "already dated" in r.stdout


def test_date_changelog_unreleased_version_fails(tmp_path, fake_api):
    api, _ = fake_api
    repo = _repo(tmp_path)
    env = {"PATH": "/usr/bin:/bin", "PENNYWARDEN_GITHUB_API": api, "PENNYWARDEN_REPO": "owner/PennyWarden"}
    r = subprocess.run(["bash", "scripts/date_changelog.sh", "2.1.0"], cwd=repo, capture_output=True, text=True,
                       env=env)
    assert r.returncode != 0
    assert "not found" in r.stderr
    assert "## 2.1.0 — unreleased" in (repo / "CHANGELOG.md").read_text()


def test_readme_names_no_version():
    head = (ROOT / "README.md").read_text().split("<p align=\"center\">")[0]
    assert "Current release:" not in head
    assert "releases/latest" in head
