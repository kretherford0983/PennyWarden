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
# 2.4.0 (#473): the user guide - the current guide and the guides it links to, the archived release notes from 1.10.0
# on (the first public release), and versions.json for the guide page's version list (newest first)
mkdir -p "$OUT/guide/archive"
cp "$ROOT"/site/guide/index.html "$ROOT"/site/guide/guide.js "$OUT/guide/"
cp "$ROOT"/docs/user-guide.md "$ROOT"/docs/check-printing.md "$ROOT"/docs/backup-restore.md "$OUT/guide/"
python3 - "$ROOT/docs/archive" "$OUT/guide" <<'PY'
import json, re, shutil, sys
from pathlib import Path
src, out = Path(sys.argv[1]), Path(sys.argv[2])
found = []
for f in src.glob("user-guide-v*.md"):
    v = re.fullmatch(r"user-guide-v(\d+)\.(\d+)\.md", f.name)
    if v and (int(v[1]), int(v[2])) >= (1, 10):
        shutil.copy(f, out / "archive" / f.name)
        found.append(((int(v[1]), int(v[2])), {"version": f"{v[1]}.{v[2]}", "file": f"archive/{f.name}"}))
found.sort(reverse=True)
(out / "versions.json").write_text(json.dumps({"schema": 1, "versions": [x for _, x in found]}, indent=1) + "\n")
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
