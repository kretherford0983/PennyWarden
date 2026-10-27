#!/usr/bin/env python3
"""Builds the release data files published on pennywarden.org (1.10.0, #83 / #58).

    releases.json       production releases (tags vX.Y.Z), newest first - read by the product page's download
                        buttons and by production installs for the update notification
    releases-test.json  test pre-releases (vX.Y.Z-test.N) and production releases, newest first - read by test builds
                        only; never by the product page

Each release: version, tag, channel (stable | test), build (the test build number, or null), date, url (its GitHub
release page), notes (the release text without the install footer), and the downloads with size and SHA-256.

Usage (CI, repo root):
    gh api "repos/OWNER/REPO/releases?per_page=100" --paginate --slurp > releases-api.json
    python scripts/release_data.py releases-api.json OUTPUT_DIR
SHA256SUMS.txt of each release is downloaded to fill in the checksums (skipped with --no-checksums).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import urllib.request
from pathlib import Path

SCHEMA = 1
STABLE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
TEST = re.compile(r"^v(\d+)\.(\d+)\.(\d+)-test\.(\d+)$")
MAX_NOTES = 20_000
FOOTER = re.compile(r"\n-{3,}\s*\n(Test build from branch|Production release \(commit)", re.S)
# 2.0.0 (#207): test builds put the install block first, before a rule
HEADER = re.compile(r"^\s*Test build from branch.*?\n-{3,}[ \t]*\n", re.S)


def kind_of(name: str) -> tuple[str, str] | None:
    """(os, kind) of a download, or None for files that are not offered on the page."""
    n = name.lower()
    if n.endswith("-windows-x64.exe"):
        return "windows", "installer"
    if n.endswith("windows-x64.zip"):
        return "windows", "portable"
    if n.endswith("-macos-arm64.dmg"):
        return "mac", "installer"
    if n == "install.sh":
        return "linux", "installer"
    if n.endswith("linux-x64-portable.tar.gz"):
        return "linux", "portable"
    if n.startswith("pennywarden-demo-") and n.endswith(".fmbak"):   # 2.2.0 (#243): the Try the demo page
        return "demo", "backup"
    if n == "sha256sums.txt":
        return "all", "checksums"
    return None


def notes_of(body: str | None) -> str:
    text = (body or "").replace("\r\n", "\n")
    h = HEADER.match(text)
    if h:
        text = text[h.end():]
    m = FOOTER.search(text)
    if m:
        text = text[:m.start()]
    return text.strip()[:MAX_NOTES]


def parse_sums(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            out[parts[1].lstrip("*")] = parts[0]
    return out


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "pennywarden-release-data"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - GitHub release asset URL
        return r.read(1_000_000).decode("utf-8", "replace")


def entry(rel: dict, fetch=_fetch) -> dict | None:
    tag = rel.get("tag_name") or ""
    if rel.get("draft"):
        return None
    m, t = STABLE.match(tag), TEST.match(tag)
    if m and not rel.get("prerelease"):
        version, channel, build = ".".join(m.groups()), "stable", None
    elif t and rel.get("prerelease"):
        version, channel, build = ".".join(t.groups()[:3]), "test", int(t.group(4))
    else:
        return None
    assets = rel.get("assets") or []
    sums: dict[str, str] = {}
    sums_asset = next((a for a in assets if a.get("name", "").lower() == "sha256sums.txt"), None)
    if sums_asset and fetch is not None:
        try:
            sums = parse_sums(fetch(sums_asset["browser_download_url"]))
        except Exception as e:  # noqa: BLE001 - the page still works without checksums
            print(f"warning: no checksums for {tag}: {e}", file=sys.stderr)
    downloads = []
    for a in assets:
        k = kind_of(a.get("name", ""))
        if k is None:
            continue
        downloads.append({"os": k[0], "kind": k[1], "name": a["name"], "url": a["browser_download_url"],
                          "size": a.get("size"), "sha256": sums.get(a["name"])})
    return {"version": version, "tag": tag, "channel": channel, "build": build,
            "date": (rel.get("published_at") or rel.get("created_at") or "")[:10],
            "published_at": rel.get("published_at"), "url": rel.get("html_url"), "notes": notes_of(rel.get("body")),
            "downloads": downloads}


def sort_key(e: dict) -> tuple:
    return tuple(int(x) for x in e["version"].split(".")) + ((10 ** 9) if e["build"] is None else e["build"],)


def build(releases: list[dict], fetch=_fetch) -> tuple[dict, dict]:
    entries = [e for e in (entry(r, fetch) for r in releases) if e]
    entries.sort(key=sort_key, reverse=True)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stable = [e for e in entries if e["channel"] == "stable"]

    def doc(channel, items):
        return {"schema": SCHEMA, "channel": channel, "generated_at": now,
                "latest": items[0]["version"] if items else None,
                "latest_tag": items[0]["tag"] if items else None, "releases": items}
    return doc("stable", stable), doc("test", entries)


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    raw = json.loads(Path(args[0]).read_text())
    if raw and isinstance(raw[0], list):      # gh api --paginate --slurp: a list of pages
        raw = [r for page in raw for r in page]
    stable, test = build(raw, None if "--no-checksums" in argv else _fetch)
    out = Path(args[1])
    out.mkdir(parents=True, exist_ok=True)
    (out / "releases.json").write_text(json.dumps(stable, indent=1) + "\n")
    (out / "releases-test.json").write_text(json.dumps(test, indent=1) + "\n")
    print(f"releases.json: {len(stable['releases'])} releases, latest {stable['latest']}; "
          f"releases-test.json: {len(test['releases'])} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
