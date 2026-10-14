#!/usr/bin/env python3
"""Generates THIRD-PARTY-NOTICES.txt (v1.5.0): every third-party component shipped in the PennyWarden packages with its
license text.

  Python: the closure of backend/requirements.txt as installed in the running interpreter (+ colorama, which only the
          Windows package adds), license files from each package's metadata.
  Web UI: npm production dependencies (`npm ls --omit=dev --all`) bundled into the page, LICENSE file of each.
  Runtime: the CPython license (bundled interpreter), plus a pointer for the runtime's own components.

Usage (repo root, with backend/requirements.txt installed and `npm --prefix frontend ci` done):
  python scripts/third_party_notices.py            # rewrite THIRD-PARTY-NOTICES.txt
  python scripts/third_party_notices.py --check    # CI: fail when the inventory differs from the committed file,
                                                   # or a shipped Python package is not pinned in requirements.txt
  python scripts/third_party_notices.py --regenerate   # CI on Dependabot pull requests and develop (1.8.0, #98):
                                                   # rewrite the file when it is out of date and report what changed
                                                   # (GitHub warnings + job summary) instead of failing
"""
from __future__ import annotations

import importlib.metadata as md
import json
import re
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "THIRD-PARTY-NOTICES.txt"
EXTRA_PY = {"colorama": ("0.4.6", "BSD-3-Clause", "https://github.com/tartley/colorama",
                         "Windows package only. Copyright (c) 2010 Jonathan Hartley. All rights reserved. "
                         "Redistribution and use in source and binary forms, with or without modification, are "
                         "permitted under the BSD 3-Clause License (https://opensource.org/license/bsd-3-clause).")}
LICENSE_NAMES = re.compile(r"(^|/)(licen[cs]e|copying|notice|authors)[^/]*$", re.I)
SEP = "=" * 100


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pins() -> dict[str, bool]:
    pins = {}
    for line in (ROOT / "backend" / "requirements.txt").read_text().splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==", line.strip())
        if m:
            pins[_norm(m.group(1))] = True
    return pins


def unpinned(components: list[dict]) -> list[str]:
    """1.8.0 (#98): shipped Python packages that requirements.txt does not pin (it pins the whole tree, so a package
    that an update brings in has to be added by hand)."""
    pins = _pins()
    return sorted(f"{c['name']}=={c['version']}" for c in components
                  if _norm(c["name"]) not in pins and _norm(c["name"]) not in EXTRA_PY)


def python_components() -> list[dict]:
    pins = _pins()
    todo, seen = list(pins), {}
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            raise SystemExit(f"{name} is not installed - install backend/requirements.txt first")
        seen[name] = dist
        for req in dist.requires or []:
            if "extra ==" in req:
                continue
            marker = req.split(";", 1)[1] if ";" in req else ""
            if "sys_platform" in marker or "platform_system" in marker or "os_name" in marker:
                continue  # platform-only extras (colorama is listed separately)
            if "python_version" in marker and not _marker_ok(marker):
                continue
            todo.append(_norm(re.split(r"[ ;<>=!~\[(]", req, maxsplit=1)[0]))
    out = []
    for name, dist in sorted(seen.items()):
        meta = dist.metadata
        lic = meta.get("License-Expression") or _classifier_license(meta) or (meta.get("License") or "").split("\n")[0]
        texts = []
        for f in dist.files or []:
            # 2.0.0 build 11: also every file in a PEP 639 licenses/ folder (pypdfium2 ships PDFium's dependency licenses
            # there under their own names, e.g. BUILD_LICENSES/freetype.txt)
            if (LICENSE_NAMES.search(str(f)) or ".dist-info/licenses/" in str(f)) and ".dist-info/" in str(f) \
                    or str(f).endswith("bitstream-vera-license.txt"):
                p = Path(dist.locate_file(f))
                if p.is_file():
                    texts.append((str(f).split("/")[-1], p.read_text(errors="replace").strip()))
        out.append({"name": meta["Name"], "version": dist.version, "license": lic.strip() or "see text",
                    "url": _home(meta), "texts": texts})
    for name, (ver, lic, url, text) in EXTRA_PY.items():
        out.append({"name": name, "version": ver, "license": lic, "url": url, "texts": [("LICENSE", text)]})
    return sorted(out, key=lambda c: c["name"].lower())


def _marker_ok(marker: str) -> bool:
    try:
        from packaging.markers import Marker
        return Marker(marker).evaluate({"python_version": "3.12", "python_full_version": "3.12.12"})
    except Exception:
        return True


def _classifier_license(meta) -> str:
    c = [x.split("::")[-1].strip() for x in meta.get_all("Classifier") or [] if x.startswith("License ::")]
    return ", ".join(c)


def _home(meta) -> str:
    for u in meta.get_all("Project-URL") or []:
        label, _, url = u.partition(",")
        if label.strip().lower() in ("homepage", "home", "source", "source code", "repository", "github"):
            return url.strip()
    return meta.get("Home-page") or ""


def npm_components() -> list[dict]:
    fe = ROOT / "frontend"
    raw = subprocess.run(["npm", "ls", "--omit=dev", "--all", "--json", "--long"], cwd=fe, capture_output=True,
                         text=True, check=False).stdout
    tree = json.loads(raw)
    found: dict[str, dict] = {}

    def walk(deps):
        for name, d in (deps or {}).items():
            key = f"{name}@{d.get('version')}"
            if key not in found and d.get("path"):
                p = Path(d["path"])
                pj = json.loads((p / "package.json").read_text())
                lic = pj.get("license") or (pj.get("licenses") or [{}])[0].get("type", "")
                texts = [(f.name, f.read_text(errors="replace").strip()) for f in sorted(p.iterdir())
                         if f.is_file() and LICENSE_NAMES.search(f.name)]
                repo = pj.get("repository")
                url = pj.get("homepage") or (repo.get("url") if isinstance(repo, dict) else repo) or ""
                found[key] = {"name": name, "version": d.get("version"), "license": lic, "url": url, "texts": texts}
            walk(d.get("dependencies"))

    walk(tree.get("dependencies"))
    return sorted(found.values(), key=lambda c: (c["name"].lower(), c["version"]))


def runtime_component() -> dict:
    lic = Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt"
    text = lic.read_text(errors="replace").strip() if lic.is_file() else \
        "PSF License Agreement for Python - https://docs.python.org/3/license.html"
    return {"name": "CPython (Python runtime)", "version": "3.12", "license": "PSF-2.0",
            "url": "https://www.python.org/", "texts": [("LICENSE.txt", text)]}


def font_components() -> list[dict]:
    """2.0.0 (#157): the fonts shipped for check printing (backend/fmpoc/fonts), with their license files."""
    d = ROOT / "backend" / "fmpoc" / "fonts"
    lib = (d / "LICENSE-Liberation.txt").read_text().strip()
    car = (d / "LICENSE-Carlito.txt").read_text().strip()
    return [{"name": "Carlito", "version": "20230309", "license": "OFL-1.1",
             "url": "https://github.com/googlefonts/carlito", "texts": [("LICENSE-Carlito.txt", car)]},
            {"name": "Liberation Fonts (Sans, Serif, Mono)", "version": "2.1.5", "license": "OFL-1.1",
             "url": "https://github.com/liberationfonts/liberation-fonts", "texts": [("LICENSE-Liberation.txt", lib)]}]


def inventory(groups) -> list[str]:
    lines = []
    for title, comps in groups:
        lines.append(f"{title}:")
        lines += [f"  {c['name']} {c['version']} - {c['license']}" for c in comps]
    return lines


def render(groups) -> str:
    out = [
        "PennyWarden - third-party notices",
        "",
        "PennyWarden is licensed under the GNU Affero General Public License v3.0 (see LICENSE).",
        "The packages also contain the third-party components listed below, each under its own license.",
        "Generated by scripts/third_party_notices.py - do not edit by hand.",
        "",
        "The Linux/Windows packages bundle a relocatable Python build from python-build-standalone",
        "(https://github.com/astral-sh/python-build-standalone). Besides CPython it contains components such as",
        "OpenSSL (Apache-2.0), SQLite (public domain), libffi (MIT), zlib (zlib), bzip2, xz/liblzma, mpdecimal",
        "and Tcl/Tk; their licenses are documented at",
        "https://gregoryszorc.com/docs/python-build-standalone/main/running.html#licensing",
        "The google-re2 package contains the RE2 library (BSD-3-Clause, below) built with Abseil",
        "(https://github.com/abseil/abseil-cpp, Apache-2.0).",
        "",
        "INVENTORY",
    ] + inventory(groups) + [""]
    for title, comps in groups:
        out += [SEP, title.upper(), SEP, ""]
        for c in comps:
            out += [f"{c['name']} {c['version']}", f"License: {c['license']}"]
            if c["url"]:
                out.append(f"Source: {c['url']}")
            out.append("")
            if not c["texts"]:
                out += ["(no license file in the distribution; see the license named above)", ""]
            for fname, text in c["texts"]:
                out += [f"--- {fname} ---", text, ""]
            out.append("-" * 100)
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def _diff(groups) -> list[str]:
    committed = OUT.read_text() if OUT.exists() else ""
    want = inventory(groups)
    have = committed.split("INVENTORY\n", 1)[1].split("\n\n", 1)[0].splitlines() if "INVENTORY\n" in committed else []
    return [("missing: " if line in want else "stale:   ") + line for line in sorted(set(want) ^ set(have))]


def _summary(lines: list[str]) -> None:
    import os
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


def main() -> int:
    groups = [("Python runtime", [runtime_component()]), ("Python packages (server)", python_components()),
              ("JavaScript packages (web interface)", npm_components()),
              ("Fonts (check printing)", font_components())]
    loose = unpinned(groups[1][1])
    n = sum(len(c) for _, c in groups)
    if "--check" in sys.argv:
        diff = _diff(groups)
        if diff:
            print("THIRD-PARTY-NOTICES.txt is out of date - run: python scripts/third_party_notices.py", file=sys.stderr)
            for line in diff:
                print("  " + line, file=sys.stderr)
        for p in loose:
            print(f"::error::{p} is shipped but not pinned in backend/requirements.txt - add '{p}'", file=sys.stderr)
        if diff or loose:
            return 1
        print(f"THIRD-PARTY-NOTICES.txt up to date ({n} components)")
        return 0
    if "--regenerate" in sys.argv:
        diff = _diff(groups)
        report = ["### Third-party notices"]
        if diff:
            OUT.write_text(render(groups))
            print("::warning::THIRD-PARTY-NOTICES.txt was out of date and was regenerated for this run. Before "
                  "promoting to test, run 'python scripts/third_party_notices.py' on develop, review the new "
                  "licenses and commit the file (the check on test and main is strict).")
            for line in diff:
                print("  " + line)
            report += ["THIRD-PARTY-NOTICES.txt was **out of date** and was regenerated for this run (not committed). "
                       "Regenerate it on develop and review the licenses before promoting to test:", "",
                       "```", *diff, "```"]
        else:
            print(f"THIRD-PARTY-NOTICES.txt up to date ({n} components)")
            report.append(f"Up to date ({n} components).")
        for p in loose:
            print(f"::warning::{p} is shipped but not pinned in backend/requirements.txt - add '{p}'")
        if loose:
            report += ["", "**Not pinned in backend/requirements.txt** (add these):", "",
                       *[f"- `{p}`" for p in loose]]
        _summary(report)
        return 0
    OUT.write_text(render(groups))
    print(f"wrote {OUT.relative_to(ROOT)} ({n} components)")
    for p in loose:
        print(f"warning: {p} is shipped but not pinned in backend/requirements.txt - add '{p}'", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
