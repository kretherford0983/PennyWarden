"""2.1.0 (#233): the Kept as column of the scheduled backups history - Daily / Weekly / Monthly (one or more),
Latest, Removed - computed with the same code as retention (keep_levels), with the current keep settings."""
from __future__ import annotations

import datetime as dt

from test_v190_scheduled_backups import _save, folder  # noqa: F401  (fixture)

from fmpoc.services import scheduled_backup as sb


class R:
    def __init__(self, i, d):
        self.id, self.started_at = i, d


def runs_from(newest: dt.datetime, n: int) -> list[R]:
    return [R(i, newest - dt.timedelta(days=i)) for i in range(n)]       # daily, newest first


def test_levels_one_or_more_and_latest():
    # newest is Monday 2026-04-27 (local noon): the newest daily is also the first backup of its week
    runs = runs_from(dt.datetime(2026, 4, 27, 17), 40)
    lv = sb.keep_levels(runs, 3, 2, 2)
    assert lv[0] == ["Daily", "Weekly"]
    assert set(lv) == sb.keep_set(runs, 3, 2, 2)                         # the same calculation as retention
    # no rule covers the newest: it is kept as Latest
    thursday = runs_from(dt.datetime(2026, 4, 30, 17), 10)
    lv = sb.keep_levels(thursday, 0, 1, 0)
    assert lv[0] == ["Latest"] and lv[3] == ["Weekly"]                   # Monday 2026-04-27
    assert sb.keep_levels([], 3, 2, 2) == {}


def history(env):
    d = env.admin.get("/api/system/backup-schedule").json()
    return {sb._to_local(dt.datetime.fromisoformat(h["started_at"].rstrip("Z"))).date(): h for h in d["history"]}


def test_kept_as_column_follows_the_settings_and_retention(env, folder):
    _save(env, folder)                                      # keep 3 daily, 2 weekly, 2 monthly
    start = dt.datetime(2026, 3, 22, 12, 0)                  # 40 days of daily backups, the last Thu 2026-04-30
    for i in range(40):
        sb.run_backup(env.app, 1, "SCHEDULED", now=start + dt.timedelta(days=i))
    h = history(env)
    day = lambda d: h[dt.date(2026, 4, d)]["kept_as"]      # noqa: E731
    assert (day(30), day(29), day(28)) == ("Daily", "Daily", "Daily")
    assert (day(27), day(20)) == ("Weekly", "Weekly")       # the first backup of the 2 newest weeks
    assert day(1) == "Monthly"
    assert day(26) == "Removed" and day(2) == "Removed"
    kept = {d for d, x in h.items() if x["kept_as"] != "Removed"}
    assert all(not h[d]["deleted"] for d in kept) and all(x["deleted"] for x in h.values() if x["kept_as"] == "Removed")
    # fewer weekly backups: shown at the next page load, removed at the next run
    assert _save(env, folder, keep_weekly=0).status_code == 200
    h = history(env)
    assert day(27) == "Removed at the next backup" and day(20) == "Removed at the next backup"
    assert day(30) == "Daily" and day(1) == "Monthly"
    sb.run_backup(env.app, 1, "SCHEDULED", now=start + dt.timedelta(days=40))
    h = history(env)
    assert day(27) == "Removed" and day(20) == "Removed"
    # a failed or running backup has no Kept as
    assert all(x["kept_as"] is None for x in h.values() if x["result"] != "SUCCESS")
