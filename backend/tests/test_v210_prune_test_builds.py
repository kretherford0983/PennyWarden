"""2.1.0 (#329): scripts/prune_test_builds.sh - remove a version's old test builds (release and tag), with a fake `gh`
on PATH (no network): the newest 3 kept while testing, all of the version at its release, never anything else."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/prune_test_builds.sh"

RELEASES = ["v2.1.0", "v2.1.0-test.201", "v2.1.0-test.199", "v2.1.0-test.196", "v2.1.0-test.193", "v2.0.0",
            "v2.2.0-test.210", "v2.1.0-test.19x", "v12.1.0-test.5", "v2.1.0-test.7"]
TAG_ONLY = ["v2.1.0-test.150"]                     # a tag left without its release

FAKE_GH = r'''#!/usr/bin/env bash
# fake gh: answers the calls prune_test_builds.sh makes; records deletions
echo "$*" >> "$GH_LOG"
case "$*" in
  "api repos/o/r/releases?per_page=100 --paginate --jq .[].tag_name") cat "$GH_RELEASES" ;;
  "api repos/o/r/git/matching-refs/tags/"*) sed 's#^#refs/tags/#' "$GH_TAGS" ;;
  "api repos/o/r/releases/tags/"*" --jq .id") echo 42 ;;
  "api -X DELETE "*) : ;;
  *) echo "unexpected: $*" >&2; exit 1 ;;
esac
'''


def run(tmp: Path, *args: str, dry: bool = False) -> tuple[subprocess.CompletedProcess, list[str]]:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    (tmp / "releases").write_text("\n".join(RELEASES) + "\n")
    (tmp / "tags").write_text("\n".join(t for t in RELEASES + TAG_ONLY if "-test." in t) + "\n")
    log = tmp / "gh.log"
    log.write_text("")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GITHUB_REPOSITORY": "o/r",
           "GH_LOG": str(log), "GH_RELEASES": str(tmp / "releases"), "GH_TAGS": str(tmp / "tags"),
           "GITHUB_STEP_SUMMARY": str(tmp / "summary.md")}
    env.pop("DRY_RUN", None)
    if dry:
        env["DRY_RUN"] = "1"
    r = subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)
    deleted = [line.split("/")[-1] for line in log.read_text().splitlines() if "DELETE" in line and "refs/tags" in line]
    return r, deleted


def test_while_testing_keeps_the_newest_three(tmp_path):
    r, deleted = run(tmp_path, "2.1.0", "test", "3")
    assert r.returncode == 0, r.stderr
    assert "keep: v2.1.0-test.201 v2.1.0-test.199 v2.1.0-test.196" in r.stdout
    assert sorted(deleted) == ["v2.1.0-test.150", "v2.1.0-test.193", "v2.1.0-test.7"]
    assert "Removed:" in (tmp_path / "summary.md").read_text()


def test_at_the_release_all_of_that_version_and_nothing_else(tmp_path):
    r, deleted = run(tmp_path, "2.1.0", "release")
    assert r.returncode == 0, r.stderr
    assert sorted(deleted) == sorted(["v2.1.0-test.201", "v2.1.0-test.199", "v2.1.0-test.196", "v2.1.0-test.193",
                                      "v2.1.0-test.7", "v2.1.0-test.150"])
    for never in ("v2.1.0", "v2.0.0", "v2.2.0-test.210", "v2.1.0-test.19x", "v12.1.0-test.5"):
        assert never not in deleted


def test_dry_run_and_bad_input_remove_nothing(tmp_path):
    r, deleted = run(tmp_path, "2.1.0", "release", dry=True)
    assert r.returncode == 0 and deleted == [] and "dry run" in (tmp_path / "summary.md").read_text()
    for args in (("2.1.0;rm -rf /", "release"), ("2.1.0", "everything"), ("2.1", "release")):
        r, deleted = run(tmp_path, *args)
        assert r.returncode == 0 and deleted == [] and "::warning::" in r.stdout, args


def test_the_build_runs_it_after_publishing_and_never_fails_on_it():
    wf = (ROOT / ".github/workflows/build.yml").read_text()
    publish = wf.index("- name: Publish GitHub release")
    prune = wf.index("- name: Remove old test builds")
    assert publish < prune < wf.index("\n  site:")
    step = wf[prune:wf.index("\n  site:")]
    assert "continue-on-error: true" in step and "prune_test_builds.sh \"$VERSION\" release" in step
    assert "prune_test_builds.sh \"$VERSION\" test 3" in step
