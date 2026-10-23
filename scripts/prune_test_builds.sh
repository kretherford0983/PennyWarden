#!/usr/bin/env bash
# 2.1.0 (#329): remove old test builds (GitHub pre-release vX.Y.Z-test.N and its tag) of one version.
#
#   scripts/prune_test_builds.sh VERSION release      all test builds of VERSION (after VERSION is released)
#   scripts/prune_test_builds.sh VERSION test [KEEP]  all but the newest KEEP (default 3) test builds of VERSION
#
# Only tags matching exactly ^vVERSION-test.<number>$ are touched; production releases and other versions never are.
# DRY_RUN=1 lists what would be removed. Needs GH_TOKEN with contents: write and GITHUB_REPOSITORY (owner/repo).
# Never fails the caller: problems are reported as warnings (exit 0), so a release is never failed by the clean-up.
set -uo pipefail

VERSION="${1:?version}"
MODE="${2:?release or test}"
KEEP="${3:-3}"
REPO="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY}"
SUMMARY="${GITHUB_STEP_SUMMARY:-/dev/null}"
warn() { echo "::warning::$*"; }

case "$MODE" in release|test) ;; *) warn "prune_test_builds: unknown mode '$MODE'"; exit 0 ;; esac
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { warn "prune_test_builds: '$VERSION' is not a version"; exit 0; }
[[ "$KEEP" =~ ^[0-9]+$ ]] || KEEP=3
RE="^v${VERSION//./\\.}-test\\.([0-9]+)$"

# test-build tags of this version, from the releases and from the tags (a tag can outlive its release)
if ! rel=$(gh api "repos/$REPO/releases?per_page=100" --paginate --jq '.[].tag_name' 2>&1); then
  warn "prune_test_builds: could not list releases: $rel"; exit 0
fi
tags=$(gh api "repos/$REPO/git/matching-refs/tags/v$VERSION-test." --paginate --jq '.[].ref' 2>/dev/null \
       | sed 's#^refs/tags/##' || true)
mapfile -t found < <(printf '%s\n%s\n' "$rel" "$tags" | grep -E "$RE" | sort -u)

# newest first by build number
mapfile -t found < <(for t in "${found[@]}"; do [[ "$t" =~ $RE ]] && echo "${BASH_REMATCH[1]} $t"; done | sort -rn | awk '{print $2}')
if [ "$MODE" = test ]; then
  remove=("${found[@]:$KEEP}")
  kept=("${found[@]:0:$KEEP}")
else
  remove=("${found[@]}")
  kept=()
fi

{
  echo "### Test builds of $VERSION ($MODE)"
  echo
  echo "- Kept: ${kept[*]:-none}"
  echo "- Removed: ${remove[*]:-none}${DRY_RUN:+ (dry run: nothing removed)}"
} >> "$SUMMARY"
echo "keep: ${kept[*]:-none}"
echo "remove: ${remove[*]:-none}"
[ "${DRY_RUN:-}" ] && exit 0

for t in "${remove[@]}"; do
  [[ "$t" =~ $RE ]] || continue                    # belt and braces: never anything but this version's test tags
  if printf '%s\n' "$rel" | grep -qx -- "$t"; then
    if id=$(gh api "repos/$REPO/releases/tags/$t" --jq .id 2>/dev/null) && [ -n "$id" ]; then
      gh api -X DELETE "repos/$REPO/releases/$id" >/dev/null 2>&1 || warn "could not remove release $t"
    fi
  fi
  # then its tag (also a tag that was left without a release)
  gh api -X DELETE "repos/$REPO/git/refs/tags/$t" >/dev/null 2>&1 || warn "could not remove tag $t"
done
exit 0
