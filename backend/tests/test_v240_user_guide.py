"""2.4.0 (#473, book #488): the user guide is a book - Contents, chapters and task pages in docs/guide - bundled into
the app (Help) and published on pennywarden.org per version; the per-release notes of 1.10-2.3 stay archived as they
were.

BR-DOC-001..005 / AC-DOC-001..008 are recorded in docs/implementation-notes.md. The in-app behaviour is exercised by
the E2E test "#473 / #488 AC-DOC"; these tests keep the book, its pictures and the code that bundles and publishes it
in step, so a renamed page or a missing picture is caught before a build ships a broken help link.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
BOOK = DOCS / "guide"
HELP_TS = ROOT / "frontend" / "src" / "help.ts"
HELP_DOCS_TS = ROOT / "frontend" / "src" / "helpDocs.ts"


def _manifest() -> dict:
    return json.loads((BOOK / "guide.json").read_text("utf-8"))


def _pages():
    """(chapter, page, path of its Markdown) for every page."""
    for c in _manifest()["chapters"]:
        for p in c["pages"]:
            yield c["id"], p, (BOOK / p["source"]).resolve() if p.get("source") else BOOK / c["id"] / f"{p['id']}.md"


def test_ac_doc_book_structure_is_complete():
    """BR-DOC-004: Contents -> chapters -> task pages; every page has a title, summary and Markdown; ids are unique."""
    m = _manifest()
    assert re.fullmatch(r"\d+\.\d+", m["version"]) and m["chapters"]
    ids = [c["id"] for c in m["chapters"]]
    assert len(ids) == len(set(ids))
    for c in m["chapters"]:
        assert c["title"] and c["summary"] and c["pages"], c["id"]
        pids = [p["id"] for p in c["pages"]]
        assert len(pids) == len(set(pids)), c["id"]
    for cid, p, path in _pages():
        assert p["title"] and p["summary"], f"{cid}/{p['id']}"
        assert path.is_file(), f"{cid}/{p['id']}: {path}"
    on_disk = {f"{f.parent.name}/{f.stem}" for f in BOOK.glob("*/*.md")}
    listed = {f"{c}/{p['id']}" for c, p, _ in _pages() if not p.get("source")}
    assert on_disk == listed, f"pages not in guide.json: {sorted(on_disk - listed)}; missing: {sorted(listed - on_disk)}"


def test_ac_doc_archived_notes_stay_single_documents():
    """BR-DOC-003: 1.10-2.3 keep their single "what's new" document; no single current guide any more."""
    assert not (DOCS / "user-guide.md").exists()
    assert not list(DOCS.glob("user-guide-v*.md")), "per-release notes belong in docs/archive/"
    archived = {p.name for p in (DOCS / "archive").glob("user-guide-v*.md")}
    assert {"user-guide-v1.10.md", "user-guide-v2.0.md", "user-guide-v2.3.md"} <= archived


def test_ac_doc_001_every_screen_has_a_help_page():
    """AC-DOC-001: each screen's ? button points at a page that exists in the book."""
    targets = re.findall(r'^\s*"/[a-z-]*":\s*"([a-z0-9-]+)/([a-z0-9-]+)",', HELP_TS.read_text("utf-8"), flags=re.M)
    assert len(targets) >= 20
    pages = {(c, p["id"]) for c, p, _ in _pages()}
    missing = [f"{c}/{p}" for c, p in targets if (c, p) not in pages]
    assert not missing, missing


def test_ac_doc_links_and_pictures_resolve():
    """Every link between pages lands on a page, every picture exists, and every picture is used (AC-DOC-007)."""
    pages = {(c, p["id"]) for c, p, _ in _pages()}
    broken, used = [], set()
    for cid, p, path in _pages():
        if p.get("source"):
            continue
        for m in re.finditer(r"(!?)\[[^\]]*\]\(([^)\s]+)\)", path.read_text("utf-8")):
            href = m.group(2).split("#")[0]
            if href.startswith("http"):
                continue
            target = (path.parent / href).resolve()
            if m.group(1):
                if not target.is_file() or target.parent != (BOOK / "img").resolve():
                    broken.append(f"{cid}/{p['id']}: picture {href}")
                used.add(target.name)
                continue
            rel = target.relative_to(BOOK.resolve()) if target.is_relative_to(BOOK.resolve()) else None
            if rel is None or len(rel.parts) != 2 or (rel.parts[0], rel.stem) not in pages:
                broken.append(f"{cid}/{p['id']}: link {m.group(2)}")
    assert not broken, broken
    unused = {f.name for f in (BOOK / "img").glob("*.png")} - used
    assert not unused, f"pictures no page shows: {sorted(unused)}"


def test_ac_doc_pages_have_no_raw_html():
    """BR-096: the renderers understand only the `<a id>` marker lines; any other HTML would show as text."""
    other = []
    for cid, p, path in _pages():
        fenced = False
        for line in path.read_text("utf-8").splitlines():
            if line.startswith("```"):
                fenced = not fenced
            if fenced:
                continue
            if re.search(r"<[a-zA-Z/]", line) and not re.fullmatch(r'<a id="[a-z0-9-]+"></a>\s*', line) \
                    and not re.search(r"`[^`]*<[^`]*`", line):
                other.append(f"{cid}/{p['id']}: {line[:80]}")
    assert not other, other


def test_ac_doc_screenshots_are_synthetic_and_reproducible():
    """AC-DOC-007: the pictures come from the made-up demo organization via the docs scripts (never real data)."""
    shots = (ROOT / "scripts" / "docs_screenshots.mjs").read_text("utf-8")
    assert "docs/guide/img" in shots.replace('"docs", "guide", "img"', "docs/guide/img")
    for name in re.findall(r"\(\.\./img/([a-z0-9-]+)\.png\)", "\n".join(p.read_text("utf-8") for _, _, p in _pages())):
        assert f'"{name}"' in shots, f"{name}.png is not made by scripts/docs_screenshots.mjs"
    assert "Riverside Band Boosters" in (ROOT / "scripts" / "demo_data.py").read_text("utf-8")


def test_ac_doc_github_contents_is_up_to_date():
    """docs/guide/README.md (the contents for reading on GitHub) matches guide.json."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("gc", ROOT / "scripts" / "guide_contents.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (BOOK / "README.md").read_text("utf-8") == mod.contents(), "run: python scripts/guide_contents.py"


def test_ac_doc_003_the_book_ships_in_every_build():
    """AC-DOC-003: the book (and the reference guides) are bundled into the UI build, including the Docker image's."""
    ts = HELP_DOCS_TS.read_text("utf-8")
    assert "../../docs/guide/guide.json" in ts and "../../docs/guide/*/*.md" in ts and "../../docs/guide/img/*.png" in ts
    for name in re.findall(r'from "\.\./\.\./docs/([a-z0-9-]+\.md)\?raw"', ts):
        assert (DOCS / name).is_file(), name
    dockerfile = (ROOT / "packaging" / "docker" / "Dockerfile").read_text("utf-8")
    assert "COPY docs/guide docs/guide" in dockerfile
    assert "docs/check-printing.md" in dockerfile and "docs/backup-restore.md" in dockerfile


def test_ac_doc_006_nothing_links_to_a_moved_guide():
    """AC-DOC-006: no README, site, app or doc link points at the removed docs/user-guide.md or user-guide-v*.md."""
    hits = []
    candidates = [ROOT / "README.md", *DOCS.glob("*.md"), *BOOK.rglob("*.md"), *(ROOT / "site").rglob("*.*"),
                  *(ROOT / "frontend" / "src").rglob("*.ts*"), *(ROOT / "backend" / "fmpoc").rglob("*.py")]
    for f in candidates:
        if not f.is_file() or "node_modules" in f.parts or "static" in f.parts or f.suffix == ".png":
            continue
        for n, line in enumerate(f.read_text("utf-8", errors="ignore").splitlines(), 1):
            if re.search(r"(?<!archive/)user-guide-v\d|\(user-guide\.md|docs/user-guide\.md", line) and f.name not in ("CHANGELOG.md", "implementation-notes.md"):
                hits.append(f"{f.relative_to(ROOT)}:{n}")
    assert not hits, hits


def test_ac_doc_005_008_site_has_the_book_per_version_and_the_older_notes(tmp_path):
    """AC-DOC-005/008: pennywarden.org/guide/ gets the book of each version from 2.4 (pages, pictures, reference
    guides, search index) and the single documents of 1.10-2.3, newest first, in versions.json."""
    import subprocess
    api = tmp_path / "api.json"
    api.write_text("[[]]")
    out = tmp_path / "site"
    r = subprocess.run(["bash", str(ROOT / "scripts" / "build_site.sh"), str(out), str(api)], capture_output=True,
                       text=True, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    g = out / "guide"
    for f in ("index.html", "guide.js", "versions.json"):
        assert (g / f).is_file(), f
    info = json.loads((g / "versions.json").read_text())
    v = _manifest()["version"]
    assert info["current"] == v and info["books"][0]["version"] == v
    book = g / v
    assert (book / "guide.json").is_file() and (book / "img").is_dir() and (book / "ref" / "check-printing.md").is_file()
    for cid, p, _ in _pages():
        if not p.get("source"):
            assert (book / cid / f"{p['id']}.md").is_file()
    index = json.loads((book / "search.json").read_text())
    assert any(x["page"] == "set-up-tax" and "tax group" in x["text"].lower() for x in index)
    nums = [tuple(int(n) for n in d["version"].split(".")) for d in info["docs"]]
    assert nums == sorted(nums, reverse=True) and nums[-1] == (1, 10) and (2, 4) not in nums
    assert all((g / d["file"]).is_file() for d in info["docs"])
    assert not (g / "archive" / "user-guide-v1.9.md").exists()
    assert 'href="guide/"' in (out / "index.html").read_text("utf-8")
