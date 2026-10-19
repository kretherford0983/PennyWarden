#!/usr/bin/env bash
# Pull-request rules for the branch flow  feature/* -> develop -> test -> main   (hotfix/* -> main, then back-merged).
# dependabot/* (1.6.8): dependency update pull requests opened by Dependabot - into develop only.
# Usage: check_promotion.sh <base branch> <head branch>
set -euo pipefail
BASE="$1"; HEAD="$2"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
fail() { echo "::error::$1"; exit 1; }
case "$BASE" in
  develop) [[ "$HEAD" =~ ^(feature|hotfix|dependabot)/ || "$HEAD" == "main" || "$HEAD" == "test" ]] \
             || fail "Only feature/*, hotfix/*, dependabot/* (or back-merges from test/main) may be merged into develop (got '$HEAD')." ;;
  test)    [[ "$HEAD" == "develop" || "$HEAD" =~ ^hotfix/ || "$HEAD" == "main" ]] \
             || fail "Only develop (or hotfix/*, or a back-merge from main) may be merged into test (got '$HEAD')." ;;
  main)    [[ "$HEAD" == "test" || "$HEAD" =~ ^hotfix/ ]] \
             || fail "Only test (or hotfix/*) may be merged into main (got '$HEAD')." ;;
  *) echo "No promotion rule for base '$BASE'."; exit 0 ;;
esac
VERSION=$(bash "$ROOT/scripts/version.sh")
bash "$ROOT/scripts/version.sh" --check
case "$BASE" in main|test) git fetch --tags --quiet origin 2>/dev/null || true ;; esac
released() { git rev-parse -q --verify "refs/tags/v$1" >/dev/null; }
if [ "$BASE" = "main" ]; then
  if released "$VERSION"; then
    fail "v$VERSION is already released. Bump the version (backend/fmpoc/config.py + frontend/package.json) and add a CHANGELOG entry before merging into main."
  fi
  grep -q "^## $VERSION\( \|$\)" "$ROOT/CHANGELOG.md" || fail "CHANGELOG.md has no '## $VERSION' section."
  # 2.1.0 (#240): '## <version> — unreleased' may reach main - the release is dated when it is published (the GitHub
  # release, releases.json and What's new carry the date) and in CHANGELOG.md by the first commit of the next version
  # (scripts/date_changelog.sh). The 1.7.3 rule that refused 'unreleased' here is gone.
fi
if [ "$BASE" = "main" ] || [ "$BASE" = "test" ]; then
  # 2.1.0 (#240): an earlier, already released version must not still say 'unreleased' - the next version's first
  # feature branch dates it with: bash scripts/date_changelog.sh <that version>
  while read -r v; do
    [ "$v" = "$VERSION" ] && continue
    if released "$v"; then
      fail "CHANGELOG.md still says '## $v — unreleased', but v$v is released. Date it on a feature branch: bash scripts/date_changelog.sh $v"
    fi
  done < <(sed -n 's/^## \([0-9][0-9.]*\) .*unreleased.*$/\1/Ip' "$ROOT/CHANGELOG.md")
fi
echo "OK: $HEAD -> $BASE (version $VERSION)"
