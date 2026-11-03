#!/usr/bin/env bash
# Assembles pennywarden.org (1.10.0, #83) into OUT (default _site): the hand-written page in site/, the app icon, a few
# README screenshots and the release data files built from the repository's GitHub releases (scripts/release_data.py).
#   bash scripts/build_site.sh [OUT] [RELEASES_API_JSON]
# Without RELEASES_API_JSON the releases are read with `gh api` (needs GH_TOKEN in CI).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-_site}"
API="${2:-}"
REPO="${GITHUB_REPOSITORY:-kretherford0983/PennyWarden}"
rm -rf "$OUT"
mkdir -p "$OUT/screenshots"
cp "$ROOT"/site/index.html "$ROOT"/site/site.css "$ROOT"/site/site.js "$OUT/"
cp "$ROOT/frontend/public/favicon.svg" "$OUT/favicon.svg"
# 2.4.0 (#473, book #488): the user guide - the book of the current release (docs/guide) and of earlier releases kept in
# docs/archive/guide-v<version>/, each in guide/<version>/ with its pictures, the reference guides (ref/) and a search
# index; the single "what's new" documents of 1.10 to 2.3; and versions.json for the page's version picker
mkdir -p "$OUT/guide/archive"
cp "$ROOT"/site/guide/index.html "$ROOT"/site/guide/guide.js "$OUT/guide/"
python3 - "$ROOT" "$OUT/guide" <<'PY'
import json, re, shutil, sys
from pathlib import Path
root, out = Path(sys.argv[1]), Path(sys.argv[2])
docs = root / "docs"
books = []
sources = [docs / "guide"] + sorted((docs / "archive").glob("guide-v*/"))
for src in sources:
    if not (src / "guide.json").is_file():
        continue
    m = json.loads((src / "guide.json").read_text("utf-8"))
    v = m["version"]
    dst = out / v
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("README.md"))
    (dst / "ref").mkdir(exist_ok=True)
    index = []
    for c in m["chapters"]:
        for p in c["pages"]:
            if p.get("source"):
                f = (src / p["source"]).resolve()
                shutil.copy(f, dst / "ref" / f.name)
                text = f.read_text("utf-8")
            else:
                text = (src / c["id"] / f"{p['id']}.md").read_text("utf-8")
            text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
            text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
            text = re.sub(r"[*`#|>]", "", re.sub(r'<a id="[^"]*"></a>', "", text))
            index.append({"chapter": c["id"], "page": p["id"], "title": p["title"], "summary": p["summary"],
                          "chapter_title": c["title"], "text": " ".join(text.split())})
    (dst / "search.json").write_text(json.dumps(index, ensure_ascii=False) + "\n", "utf-8")
    books.append(((tuple(int(n) for n in v.split(".")), v)))
books.sort(reverse=True)
found = []
for f in (docs / "archive").glob("user-guide-v*.md"):
    v = re.fullmatch(r"user-guide-v(\d+)\.(\d+)\.md", f.name)
    if v and (1, 10) <= (int(v[1]), int(v[2])) and f"{v[1]}.{v[2]}" not in {b[1] for b in books}:
        shutil.copy(f, out / "archive" / f.name)
        found.append(((int(v[1]), int(v[2])), {"version": f"{v[1]}.{v[2]}", "file": f"archive/{f.name}"}))
found.sort(reverse=True)
(out / "versions.json").write_text(json.dumps({"schema": 2, "current": books[0][1],
                                               "books": [{"version": v} for _, v in books],
                                               "docs": [x for _, x in found]}, indent=1) + "\n")
PY
for s in dashboard budgets register audit-report-transaction fundraiser payment check-print; do
  cp "$ROOT/docs/screenshots/readme/$s.png" "$OUT/screenshots/"
done
if [ -z "$API" ]; then
  API="$(mktemp)"
  gh api "repos/$REPO/releases?per_page=100" --paginate --slurp > "$API"
fi
python3 "$ROOT/scripts/release_data.py" "$API" "$OUT"
touch "$OUT/.nojekyll"
echo "site assembled in $OUT"
