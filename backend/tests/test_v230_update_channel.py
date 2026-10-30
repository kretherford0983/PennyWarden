"""2.3.0 build 2 (#379): Administrators choose the update channel in the Settings editor - written to config.toml,
applied without a restart, editable on local installs too (the only one), a confirmation when a production build
is switched to test builds; a test build on production releases only hears about its own version's release."""
from __future__ import annotations

import tomllib

import pytest

from fmpoc import VERSION, config
from fmpoc.services import updates

from test_v200_admin_settings import CFG, rows, server  # noqa: F401  (the server-mode fixture)
from test_v1_10_updates import NEXT, _app, _rel, feed  # noqa: F401


def _channel_row(r):
    return rows(r)["update_channel"]


def test_server_editor_offers_the_four_choices_default_follow_the_build(server):  # noqa: F811
    env = server
    r = env.admin.get("/api/system/settings")
    ch = _channel_row(r)
    assert ch["editable"] and ch["value"] == "auto" and ch["source"] == "default" and ch["live"] is True
    assert ch["choices"] == ["auto", "stable", "test", "off"]
    assert ch["choice_labels"]["auto"] == "Follow this build" and ch["choice_labels"]["stable"] == "Production releases only"
    # Auditors see it, can't change it - also not with a direct request
    a = env.auditor.get("/api/system/settings")
    assert a.status_code == 200 and not _channel_row(a)["editable"]
    for c in (env.auditor, env.ru, env.bm, env.bu):
        assert c.put("/api/system/settings", {"changes": {"update_channel": "stable"}}).status_code == 403


def test_change_writes_config_applies_at_once_no_restart_and_is_audited(server):  # noqa: F811
    env = server
    path = env.settings.data_dir / "config.toml"
    r = env.admin.put("/api/system/settings", {"changes": {"update_channel": "stable"}})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == ["update_channel"]
    ch = _channel_row(r)
    assert ch["value"] == "stable" and ch["restart_required"] is False and r.json()["restart_required"] is False
    assert env.app.state.settings.update_channel == "stable"                     # the running process switched
    assert updates.channel(env.app.state.settings) == "stable"
    text = path.read_text(encoding="utf-8")
    assert tomllib.loads(text)["server"]["update_channel"] == "stable" and "# a comment in the middle" in text
    assert (env.settings.data_dir / "config.toml.bak").read_text(encoding="utf-8") == CFG
    ev = env.admin.get("/api/audit-events?action=SERVER_SETTINGS_CHANGED").json()["items"][0]
    assert ev["before"] == {"update_channel": "auto"} and ev["after"] == {"update_channel": "stable"}


@pytest.mark.parametrize("bad", ["beta", "", 3, True])
def test_invalid_value_refused_and_nothing_written(server, bad):  # noqa: F811
    env = server
    r = env.admin.put("/api/system/settings", {"changes": {"update_channel": bad}})
    assert r.status_code == 422, r.text
    assert (env.settings.data_dir / "config.toml").read_text(encoding="utf-8") == CFG


def test_locked_by_environment(server, monkeypatch):  # noqa: F811
    env = server
    monkeypatch.setenv("FM_UPDATE_CHANNEL", "stable")
    ch = _channel_row(env.admin.get("/api/system/settings"))
    assert ch["locked"] and not ch["editable"] and "environment" in ch["read_only_reason"]
    r = env.admin.put("/api/system/settings", {"changes": {"update_channel": "test"}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SETTING_LOCKED"


def test_production_build_to_test_builds_needs_confirmation(server, monkeypatch):  # noqa: F811
    env = server
    path = env.settings.data_dir / "config.toml"
    monkeypatch.setattr(config, "build_info", lambda: {"branch": "main", "run": "100"})
    r = env.admin.put("/api/system/settings", {"changes": {"update_channel": "test"}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    w = r.json()["error"]["warnings"][0]
    assert w["code"] == "PRE_RELEASE_CHANNEL" and "not production ready" in w["message"]
    assert path.read_text(encoding="utf-8") == CFG and env.app.state.settings.update_channel == "auto"
    r = env.admin.put("/api/system/settings", {"changes": {"update_channel": "test"}, "confirmations": ["PRE_RELEASE_CHANNEL"]})
    assert r.status_code == 200 and env.app.state.settings.update_channel == "test"
    # other changes (and test builds) save without one
    assert env.admin.put("/api/system/settings", {"changes": {"update_channel": "stable"}}).status_code == 200
    monkeypatch.setattr(config, "build_info", lambda: {"branch": "test", "run": "90"})
    assert env.admin.put("/api/system/settings", {"changes": {"update_channel": "test"}}).status_code == 200


def test_local_install_only_the_update_channel_is_editable(env):
    r = env.admin.get("/api/system/settings")
    assert r.json()["editor"] is True and r.json()["mode"] == "local"
    editable = [x["name"] for x in r.json()["settings"] if x["editable"]]
    assert editable == ["update_channel"]
    for ro in ("host", "port", "mode"):                   # BR-081/BR-082: stay read-only
        assert not rows(r)[ro]["editable"]
    r = env.admin.put("/api/system/settings", {"changes": {"update_channel": "off"}})
    assert r.status_code == 200, r.text
    assert env.app.state.settings.update_channel == "off" and updates.channel(env.app.state.settings) is None
    for other in ({"host": "0.0.0.0"}, {"session_idle_minutes": 20}, {"update_channel": "auto", "hsts": True}):
        r = env.admin.put("/api/system/settings", {"changes": other})
        assert r.status_code == 409 and r.json()["error"]["code"] == "SERVER_ONLY"


def test_upgrade_without_a_setting_keeps_following_the_build(env):
    assert env.app.state.settings.update_channel == "auto"
    assert _channel_row(env.admin.get("/api/system/settings"))["value"] == "auto"


# ------------------------------------------------------------------ the update check
def test_test_build_on_production_channel_hears_about_its_own_release(tmp_path, feed, monkeypatch):  # noqa: F811
    monkeypatch.setattr(updates, "build_info", lambda: {"branch": "test", "run": "90"})
    feed.files["/releases.json"]["releases"] = [_rel(VERSION)]
    app = _app(tmp_path, feed, channel="stable", name="ts")
    updates.check(app)
    with app.state.session_factory() as db:
        s = updates.status(db, app.state.settings)
    assert s["channel"] == "stable" and s["current"]["build"] == 90
    assert s["available"] and s["latest"]["version"] == VERSION and s["latest"]["build"] is None


def test_production_build_on_test_channel_sees_test_builds_with_github_link(tmp_path, feed, monkeypatch):  # noqa: F811
    monkeypatch.setattr(updates, "build_info", lambda: {"branch": "main", "run": "100"})
    feed.files["/releases-test.json"]["releases"] = [_rel(NEXT, 7, channel="test"), _rel(VERSION)]
    app = _app(tmp_path, feed, channel="test", name="pt")
    updates.check(app)
    with app.state.session_factory() as db:
        s = updates.status(db, app.state.settings)
    assert s["channel"] == "test" and s["current"]["build"] is None
    assert [(r["version"], r["build"]) for r in s["releases"]] == [(NEXT, 7)]          # not its own release
    assert s["download_url"].startswith("https://github.com/")


def test_channel_change_is_picked_up_by_the_next_tick(tmp_path, feed, monkeypatch):  # noqa: F811
    from dataclasses import replace
    monkeypatch.setattr(updates, "build_info", lambda: {"branch": "main", "run": "100"})
    app = _app(tmp_path, feed, channel="stable", name="tick")
    assert updates.check(app) is True and feed.hits == ["/releases.json"]
    assert updates.check(app) is False                                    # not due for 24 hours
    app.state.settings = replace(app.state.settings, update_channel="test")
    assert updates.check(app) is True and feed.hits[-1] == "/releases-test.json"   # a new channel: checked at once
