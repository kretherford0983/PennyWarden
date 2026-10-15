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
