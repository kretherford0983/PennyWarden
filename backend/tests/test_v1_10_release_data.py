"""1.10.0 (#83 / #58): the release data files on pennywarden.org - production releases only in releases.json, test
pre-releases plus production releases in releases-test.json, newest first, notes without the install footer,
downloads classified with their checksums; and the site assembly."""
import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _mod():
    spec = importlib.util.spec_from_file_location("release_data", ROOT / "scripts" / "release_data.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _rel(tag, pre=False, draft=False, date="2026-10-09T20:00:00Z", body="Notes", names=()):
    assets = [{"name": n, "browser_download_url": f"https://github.com/o/r/releases/download/{tag}/{n}", "size": 10}
              for n in names]
    return {"tag_name": tag, "prerelease": pre, "draft": draft, "published_at": date, "body": body,
            "html_url": f"https://github.com/o/r/releases/tag/{tag}", "assets": assets}


NAMES = ["PennyWarden-1.9.0-windows-x64.exe", "PennyWarden-windows-x64.zip", "PennyWarden-1.9.0-macos-arm64.dmg",
         "install.sh", "PennyWarden-linux-x64-portable.tar.gz", "install-server.sh", "build-info.json",
         "SHA256SUMS.txt"]


def test_channels_order_and_fields():
    m = _mod()
    rels = [_rel("v1.9.0", names=NAMES, body="**New** stuff\n\n---\nProduction release (commit abc). Install..."),
            _rel("v1.10.0-test.91", pre=True), _rel("v1.10.0-test.95", pre=True), _rel("v1.8.0"),
            _rel("v1.11.0", draft=True), _rel("weird-tag"), _rel("v1.9.0-test.86", pre=True)]
    sums = "a" * 64 + "  PennyWarden-1.9.0-windows-x64.exe\n" + "b" * 64 + " *install.sh\n"
    stable, test = m.build(rels, fetch=lambda url: sums)
    assert stable["latest"] == "1.9.0" and [r["version"] for r in stable["releases"]] == ["1.9.0", "1.8.0"]
    assert [(r["version"], r["build"]) for r in test["releases"]] == [
        ("1.10.0", 95), ("1.10.0", 91), ("1.9.0", None), ("1.9.0", 86), ("1.8.0", None)]
    r = stable["releases"][0]
    assert r["notes"] == "**New** stuff" and r["date"] == "2026-10-09" and r["channel"] == "stable"
    dl = {(d["os"], d["kind"]): d for d in r["downloads"]}
    assert set(dl) == {("windows", "installer"), ("windows", "portable"), ("mac", "installer"), ("linux", "installer"),
                       ("linux", "portable"), ("all", "checksums")}
    assert dl[("windows", "installer")]["sha256"] == "a" * 64 and dl[("linux", "installer")]["sha256"] == "b" * 64
    assert dl[("mac", "installer")]["sha256"] is None


def test_version_order_is_numeric():
    m = _mod()
    stable, _t = m.build([_rel("v1.9.0"), _rel("v1.10.0"), _rel("v1.2.3")], fetch=None)
    assert [r["version"] for r in stable["releases"]] == ["1.10.0", "1.9.0", "1.2.3"]


def test_site_assembles(tmp_path):
    api = tmp_path / "api.json"
    api.write_text(json.dumps([[_rel("v1.9.0", names=NAMES)]]))     # gh api --paginate --slurp: pages
    out = tmp_path / "site"
    r = subprocess.run(["bash", str(ROOT / "scripts" / "build_site.sh"), str(out), str(api)], capture_output=True,
                       text=True, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    # checksums are fetched over the network in CI; without it the build still succeeds
    assert r.returncode == 0, r.stderr
    for f in ("index.html", "site.css", "site.js", "favicon.svg", "releases.json", "releases-test.json",
              "screenshots/dashboard.png", ".nojekyll"):
        assert (out / f).exists(), f
    html = (out / "index.html").read_text()
    assert "Content-Security-Policy" in html and "releases/latest" in html
    js = (out / "site.js").read_text()
    assert ".innerHTML" not in js and "insertAdjacentHTML" not in js                                        # release data never becomes markup


def test_install_block_first_or_last_is_left_out_of_the_notes():
    """2.0.0 (#207): test builds put the install block first; production releases (and older test builds) last."""
    m = _mod()
    head = ("Test build from branch `test` (commit abc). Install or upgrade on the **test** server:\n```\n"
            "curl -fsSL https://github.com/o/r/releases/download/v2.0.0-test.130/install.sh | sudo bash -s -- "
            "--version v2.0.0-test.130\n```\nWindows: download it.\nMac (Apple Silicon): download it.\n\n---\n\n")
    notes = "## 2.0.0 — unreleased\n**Test build 9**\n- Change one.\n\n---\n\n- Not a footer: a rule in the notes."
    assert m.notes_of(head + notes) == notes
    assert m.notes_of(head.replace("\n", "\r\n") + notes) == notes
    old = notes + "\n\n---\nTest build from branch `test` (commit abc). Install or upgrade on the **test** server:\n```"
    assert m.notes_of(old) == notes
    prod = "**New** stuff\n\n---\nProduction release (commit abc). Install or upgrade:\n```\ncurl ...\n```"
    assert m.notes_of(prod) == "**New** stuff"
    assert m.notes_of("Plain notes.") == "Plain notes." and m.notes_of(None) == ""
