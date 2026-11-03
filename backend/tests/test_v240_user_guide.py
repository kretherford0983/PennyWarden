"""2.4.0 (#473): one current user guide, the per-release notes archived, and Help in the app.

BR-DOC-001..003 / AC-DOC-001..006 are recorded in docs/implementation-notes.md. The in-app behaviour (AC-DOC-001..004)
is exercised by the E2E test "#473 AC-DOC-001..004"; these tests keep the documents and the code that bundles them in
step, so a renamed section or a moved file is caught before a build ships a broken help link.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
GUIDE = DOCS / "user-guide.md"
HELP_TS = ROOT / "frontend" / "src" / "help.ts"
HELP_DOCS_TS = ROOT / "frontend" / "src" / "helpDocs.ts"


def _anchors(text: str) -> set[str]:
    return set(re.findall(r'^<a id="([a-z0-9-]+)"></a>\s*$', text, flags=re.M))


def test_ac_doc_one_current_guide_and_the_notes_archived():
    """BR-DOC-003: a single current guide in docs/; the per-release notes live in docs/archive/."""
    assert GUIDE.is_file()
    assert not list(DOCS.glob("user-guide-v*.md")), "per-release notes belong in docs/archive/"
    archived = {p.name for p in (DOCS / "archive").glob("user-guide-v*.md")}
    assert {"user-guide-v1.10.md", "user-guide-v2.0.md", "user-guide-v2.4.md"} <= archived


def test_ac_doc_001_every_page_section_exists_in_the_guide():
    """AC-DOC-001: each page's help link points at a section marker that exists in the guide."""
    sections = set(re.findall(r'^\s*"/[a-z-]*":\s*"([a-z0-9-]+)",', HELP_TS.read_text("utf-8"), flags=re.M))
    assert {"dashboard", "register", "budgets", "users", "system-about"} <= sections
    missing = sections - _anchors(GUIDE.read_text("utf-8"))
    assert not missing, f"user-guide.md has no <a id> marker for: {sorted(missing)}"


def test_ac_doc_guide_contents_links_resolve():
    """The guide's own #links (the contents line and cross-references) all land on a section."""
    text = GUIDE.read_text("utf-8")
    ids = _anchors(text)
    for heading in re.findall(r"^#{1,6} (.+)$", text, flags=re.M):   # GitHub-style ids of the headings too
        ids.add(re.sub(r"[^\w -]", "", heading.lower().replace("*", "")).strip().replace(" ", "-"))
    broken = {h for h in re.findall(r"\]\(#([^)]+)\)", text) if h not in ids}
    assert not broken, f"broken in-guide links: {sorted(broken)}"


def test_ac_doc_003_bundled_documents_exist_and_ship_in_every_build():
    """AC-DOC-003: the guide (and the guides it links to) are bundled into the UI build, including the Docker image's."""
    bundled = re.findall(r'from "\.\./\.\./docs/([a-z0-9-]+\.md)\?raw"', HELP_DOCS_TS.read_text("utf-8"))
    assert "user-guide.md" in bundled
    for name in bundled:
        assert (DOCS / name).is_file(), name
    dockerfile = (ROOT / "packaging" / "docker" / "Dockerfile").read_text("utf-8")
    for name in bundled:
        assert f"docs/{name}" in dockerfile, f"the Docker UI stage must copy docs/{name}"


def test_ac_doc_006_nothing_links_to_a_moved_guide():
    """AC-DOC-006: no README, site, app or doc link still points at docs/user-guide-v*.md outside the archive."""
    hits = []
    candidates = [ROOT / "README.md", *DOCS.glob("*.md"), *(ROOT / "site").rglob("*.*"),
                  *(ROOT / "frontend" / "src").rglob("*.ts*"), *(ROOT / "backend" / "fmpoc").rglob("*.py")]
    for f in candidates:
        if not f.is_file() or "node_modules" in f.parts or "static" in f.parts:
            continue
        for n, line in enumerate(f.read_text("utf-8", errors="ignore").splitlines(), 1):
            if re.search(r"(?<!archive/)user-guide-v\d", line):
                hits.append(f"{f.relative_to(ROOT)}:{n}")
    assert not hits, hits


def test_ac_doc_guide_has_no_raw_html_besides_section_markers():
    """BR-096: the in-app renderer understands only the `<a id>` marker lines; any other HTML would show as text."""
    other = [line for line in GUIDE.read_text("utf-8").splitlines()
             if re.search(r"<[a-zA-Z/]", line) and not re.fullmatch(r'<a id="[a-z0-9-]+"></a>\s*', line)
             and not re.search(r"`[^`]*<[^`]*`", line)]
    assert not other, other


def test_ac_doc_005_site_offers_the_current_guide_and_releases_from_1_10(tmp_path):
    """AC-DOC-005: pennywarden.org/guide/ gets the current guide and the archived notes from 1.10.0 on, newest first."""
    import json
    import subprocess
    api = tmp_path / "api.json"
    api.write_text("[[]]")
    out = tmp_path / "site"
    r = subprocess.run(["bash", str(ROOT / "scripts" / "build_site.sh"), str(out), str(api)], capture_output=True,
                       text=True, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    for f in ("index.html", "guide.js", "user-guide.md", "check-printing.md", "backup-restore.md", "versions.json"):
        assert (out / "guide" / f).is_file(), f
    versions = json.loads((out / "guide" / "versions.json").read_text())["versions"]
    numbers = [tuple(int(n) for n in v["version"].split(".")) for v in versions]
    assert numbers == sorted(numbers, reverse=True) and numbers[-1] == (1, 10)
    assert all((out / "guide" / v["file"]).is_file() for v in versions)
    assert not (out / "guide" / "archive" / "user-guide-v1.9.md").exists()
    assert 'href="guide/"' in (out / "index.html").read_text("utf-8")
