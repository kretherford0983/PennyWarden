#!/usr/bin/env bash
# 2.1.0 (#240): puts the release date into a released version's CHANGELOG heading:
#   '## <version> — unreleased'  ->  '## <version> — <YYYY-MM-DD>'
# The date is read from the GitHub release v<version> (its publish date, in this machine's time zone), not typed.
# Standing step: the first feature branch of the next version runs it for the previous version (docs/branching.md).
# Usage: date_changelog.sh <version> [--date YYYY-MM-DD]
#   --date  use this date instead of asking GitHub (e.g. offline)
# Env:    PENNYWARDEN_GITHUB_API (default https://api.github.com), PENNYWARDEN_REPO (default: from git remote origin)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHANGELOG="$ROOT/CHANGELOG.md"
fail() { echo "error: $1" >&2; exit 1; }
[ $# -ge 1 ] || fail "usage: date_changelog.sh <version> [--date YYYY-MM-DD]"
V="$1"; shift
[[ "$V" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "version must look like 2.1.0 (got '$V')"
DATE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --date) DATE="${2:-}"; shift 2 ;;
    *) fail "unknown option '$1'" ;;
  esac
done
VE="${V//./\\.}"
grep -qE "^## $VE( |$)" "$CHANGELOG" || fail "CHANGELOG.md has no '## $V' section."
if ! grep -qiE "^## $VE .*unreleased" "$CHANGELOG"; then
  echo "CHANGELOG.md: '## $V' is already dated - nothing to do."
  exit 0
fi
if [ -z "$DATE" ]; then
  API="${PENNYWARDEN_GITHUB_API:-https://api.github.com}"
  REPO="${PENNYWARDEN_REPO:-}"
  if [ -z "$REPO" ]; then
    URL=$(git -C "$ROOT" remote get-url origin 2>/dev/null || true)
    REPO=$(printf '%s' "$URL" | sed -E 's#^(https?://[^/]+/|git@[^:]+:)##; s#\.git$##')
  fi
  [ -n "$REPO" ] || fail "can't tell the GitHub repository (set PENNYWARDEN_REPO=owner/name or use --date)."
  JSON=$(curl -fsSL "$API/repos/$REPO/releases/tags/v$V") || fail "GitHub release v$V not found ($REPO). Is it released? (or use --date)"
  PUBLISHED=$(printf '%s' "$JSON" | sed -n 's/.*"published_at": *"\([^"]*\)".*/\1/p' | head -1)
  [ -n "$PUBLISHED" ] || fail "release v$V has no publish date yet."
  DATE=$(date -d "$PUBLISHED" +%Y-%m-%d)
fi
[[ "$DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || fail "date must look like 2026-10-23 (got '$DATE')"
# replace the heading's 'unreleased' only (keeps the dash style of the heading)
sed -i -E "s/^(## $VE .*)[Uu]nreleased/\1$DATE/" "$CHANGELOG"
grep -E "^## $VE " "$CHANGELOG"
