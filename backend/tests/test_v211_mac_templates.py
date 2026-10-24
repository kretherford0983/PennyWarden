"""2.1.1: the fundraiser slide deck (and the Word report's footer) failed in the macOS app with
FileNotFoundError .../pptx/oxml/../templates/notesMaster.xml - python-pptx / python-docx open their templates through a
subfolder that only exists inside the archive. The PyInstaller specs bundle a file in each such subfolder, and the
smoke tests run `self-check-documents` inside the built app."""
from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

from fmpoc.__main__ import main

ROOT = Path(__file__).resolve().parents[2]
SPECS = ["pennywarden-mac.spec", "fmpoc.spec", "fmpoc-onefile.spec"]
UP_TO_TEMPLATES = re.compile(r"""["']\.\.["']\s*,\s*["']templates["']""")


def _parents_needed() -> set[tuple[str, str]]:
    """(package, subfolder) of every module in python-pptx / python-docx that opens '<its folder>/../templates/...'."""
    needed = set()
    for pkg in ("pptx", "docx"):
        base = Path(importlib.import_module(pkg).__file__).parent
        for py in base.rglob("*.py"):
            if UP_TO_TEMPLATES.search(py.read_text(encoding="utf-8")):
                rel = py.parent.relative_to(base)
                assert len(rel.parts) == 1, f"{py}: deeper than one subfolder - extend TEMPLATE_PARENTS handling"
                needed.add((pkg, rel.parts[0]))
    return needed


def _spec_parents(spec: str) -> set[tuple[str, str]]:
    text = (ROOT / "packaging/pyinstaller" / spec).read_text()
    m = re.search(r"^TEMPLATE_PARENTS = (\[.*?\])$", text, re.M)
    assert m, f"{spec} has no TEMPLATE_PARENTS"
    return set(ast.literal_eval(m.group(1)))


def test_every_spec_bundles_each_template_parent_folder():
    needed = _parents_needed()
    assert ("pptx", "oxml") in needed and ("docx", "parts") in needed   # the two that broke the deck and Word report
    for spec in SPECS:
        assert needed <= _spec_parents(spec), spec


def test_the_self_check_builds_a_deck_and_a_word_file(capsys):
    assert main(["self-check-documents"]) == 0
    out = capsys.readouterr().out
    assert "OK: slide deck with speaker notes" in out and "OK: Word file with header, footer and comments" in out


def test_the_smoke_tests_run_it_inside_the_built_app():
    mac = (ROOT / "packaging/macos/smoke_test.sh").read_text()
    assert '"$BIN" self-check-documents' in mac and mac.index("self-check-documents") < mac.index('"$BIN" --no-browser')
    win = (ROOT / "packaging/windows/smoke_test.ps1").read_text()
    assert "& $Command self-check-documents" in win and "$LASTEXITCODE -ne 0" in win
