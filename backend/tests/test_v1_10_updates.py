"""1.10.0 (#58): the update notification - backend fetch from the release data file of the build's channel, daily
(kept across restarts), newer releases with their notes newest first, test builds see newer test builds, production
builds only production releases, other builds and a disabled check make no request, failures show nothing."""
import datetime as dt
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import Api

from fmpoc import VERSION
from fmpoc.app import create_app
from fmpoc.config import load_settings
from fmpoc.services import updates

MAJ, MIN, PAT = (int(x) for x in VERSION.split("."))
NEXT = f"{MAJ}.{MIN + 1}.0"
NEXT2 = f"{MAJ}.{MIN + 2}.0"
OLDER = f"{MAJ}.{MIN - 1}.0"


def _rel(v, build=None, notes="notes", channel="stable"):
    return {"version": v, "tag": f"v{v}" + (f"-test.{build}" if build else ""), "channel": channel, "build": build,
            "date": "2026-10-20", "url": f"https://github.com/o/r/releases/tag/v{v}", "notes": notes, "downloads": []}


class Feed:
    """A stand-in for pennywarden.org: serves releases.json / releases-test.json and counts the requests."""

    def __init__(self):
        self.files = {"/releases.json": {"schema": 1, "releases": []}, "/releases-test.json": {"schema": 1, "releases": []}}
        self.hits = []
        feed = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                feed.hits.append(self.path)
                body = feed.files.get(self.path)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *a):
                pass
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"


@pytest.fixture
def feed():
    f = Feed()
    yield f
    f.srv.shutdown()


def _app(tmp_path, feed, channel="stable", name="u", **kw):
    return create_app(load_settings({"data_dir": str(tmp_path / name), "update_base_url": feed.url,
                                     "update_channel": channel, "login_max_failures": 1000, **kw}))


@pytest.fixture
def env_up(tmp_path, feed):
    from conftest import Env
    app = _app(tmp_path, feed)
    return Env(app, app.state.settings)


def test_stable_build_sees_newer_production_releases_with_notes(env_up, feed):
    feed.files["/releases.json"]["releases"] = [_rel(NEXT2, notes="**two**"), _rel(NEXT, notes="one"), _rel(VERSION),
                                                 _rel(OLDER)]
    assert updates.check(env_up.app) is True
    for c in (env_up.bu, env_up.ru, env_up.auditor, env_up.admin):
        s = c.get("/api/updates").json()
        assert s["available"] and s["latest"]["version"] == NEXT2
        assert [r["version"] for r in s["releases"]] == [NEXT2, NEXT]          # newest first, every newer one
    s = env_up.bu.get("/api/updates").json()
    assert s["releases"][0]["notes"] == "**two**" and s["download_url"] == "https://pennywarden.org/#download"
    assert feed.hits == ["/releases.json"]


def test_checked_once_a_day_and_not_again_after_a_restart(tmp_path, feed):
    app = _app(tmp_path, feed, name="r")
    t0 = dt.datetime(2026, 10, 10, 8)
    assert updates.check(app, now=t0) is True
    assert updates.check(app, now=t0 + dt.timedelta(hours=3)) is False
    app2 = _app(tmp_path, feed, name="r")                                      # restarted
    assert updates.check(app2, now=t0 + dt.timedelta(hours=5)) is False
    assert updates.check(app2, now=t0 + dt.timedelta(hours=25)) is True
    assert len(feed.hits) == 2


def test_test_build_sees_newer_test_builds_and_production_never_does(tmp_path, feed, monkeypatch):
    monkeypatch.setattr(updates, "build_info", lambda: {"branch": "test", "run": "90"})
    feed.files["/releases-test.json"]["releases"] = [_rel(VERSION, 95, channel="test"), _rel(VERSION, 88, channel="test"),
                                                      _rel(VERSION)]
    app = _app(tmp_path, feed, channel="auto", name="t")
    updates.check(app)
    with app.state.session_factory() as db:
        s = updates.status(db, app.state.settings)
    assert s["channel"] == "test" and s["current"]["build"] == 90
    assert [(r["version"], r["build"]) for r in s["releases"]] == [(VERSION, 95)]   # not 88, not the same production
    assert s["download_url"].startswith("https://github.com/")
    assert feed.hits == ["/releases-test.json"]
    # a production (main) build reads only the production file: a newer test build is never offered
    monkeypatch.setattr(updates, "build_info", lambda: {"branch": "main", "run": "100"})
    feed.files["/releases.json"]["releases"] = [_rel(VERSION)]
    app2 = _app(tmp_path, feed, channel="auto", name="m")
    updates.check(app2)
    with app2.state.session_factory() as db:
        assert updates.status(db, app2.state.settings)["available"] is False
    assert feed.hits[-1] == "/releases.json"


def test_develop_or_hand_made_builds_do_not_check(tmp_path, feed, monkeypatch):
    for bi in ({"branch": "develop", "run": "5"}, None):
        monkeypatch.setattr(updates, "build_info", lambda bi=bi: bi)
        app = _app(tmp_path, feed, channel="auto", name=f"d{bool(bi)}")
        assert updates.check(app, force=True) is False
    assert feed.hits == []


def test_failures_show_nothing(tmp_path, feed):
    app = _app(tmp_path, feed, name="f", update_base_url="http://127.0.0.1:9")    # nothing listens there
    assert updates.check(app) is True
    with app.state.session_factory() as db:
        s = updates.status(db, app.state.settings)
    assert s["available"] is False and s["error"] is True
    feed.files["/releases.json"] = b"<html>not json</html>"
    app2 = _app(tmp_path, feed, name="g")
    updates.check(app2)
    with app2.state.session_factory() as db:
        assert updates.status(db, app2.state.settings)["available"] is False
    feed.files["/releases.json"] = {"schema": 1, "releases": [{"version": "<script>", "url": "javascript:x"},
                                                               {**_rel(NEXT), "url": "javascript:alert(1)"}]}
    app3 = _app(tmp_path, feed, name="h")
    updates.check(app3)
    with app3.state.session_factory() as db:
        s = updates.status(db, app3.state.settings)
    assert [r["version"] for r in s["releases"]] == [NEXT] and s["releases"][0]["url"] == ""


def test_admin_turns_it_off_no_request_no_indicator(env_up, feed):
    feed.files["/releases.json"]["releases"] = [_rel(NEXT)]
    updates.check(env_up.app)
    assert env_up.bu.get("/api/updates").json()["available"] is True
    assert env_up.bm.put("/api/updates/settings", {"enabled": False}).status_code == 403
    r = env_up.admin.put("/api/updates/settings", {"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert env_up.bu.get("/api/updates").json()["available"] is False
    n = len(feed.hits)
    assert updates.check(env_up.app, force=True) is False and len(feed.hits) == n
    ev = env_up.admin.get("/api/audit-events?action=UPDATE_CHECK_SETTING_CHANGED").json()["items"][0]
    assert ev["after"] == {"enabled": False}
    env_up.admin.put("/api/updates/settings", {"enabled": True})
    s = env_up.admin.post("/api/updates/check").json()
    assert s["available"] is True and len(feed.hits) == n + 1
    assert env_up.bu.post("/api/updates/check").status_code == 403
    assert Api(env_up.app).get("/api/updates").status_code == 401


def test_is_newer_rules():
    cur = {"version": "1.10.0", "build": 57}
    assert updates.is_newer({"version": "1.10.1", "build": None}, cur, "stable")
    # 2.3.0 (#379): a test build on the production channel is told about its own version's production release
    assert updates.is_newer({"version": "1.10.0", "build": None}, cur, "stable")
    assert not updates.is_newer({"version": "1.10.0", "build": None}, {"version": "1.10.0", "build": None}, "stable")
    assert not updates.is_newer({"version": "1.9.9", "build": None}, cur, "stable")
    assert updates.is_newer({"version": "1.10.0", "build": 60}, cur, "test")
    assert not updates.is_newer({"version": "1.10.0", "build": None}, cur, "test")
    assert updates.is_newer({"version": "1.11.0", "build": 3}, cur, "test")
