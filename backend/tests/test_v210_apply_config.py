"""2.1.0 (#237, #236): `pennywarden apply-config` and the Linux installer using it.

The systemd folder is redirected with PENNYWARDEN_SYSTEMD_DIR, and the restart is replaced, so the tests need neither
root nor systemd. The installer itself is checked for using the command (one implementation).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from fmpoc import __main__ as entry
from fmpoc import cli_apply_config as ac
from fmpoc.config import load_settings
from fmpoc.db import make_engine, make_session_factory
from fmpoc.models import AuditEvent

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "packaging" / "linux" / "install-server.sh"


@pytest.fixture
def sysd(tmp_path, monkeypatch):
    d = tmp_path / "systemd"
    d.mkdir()
    monkeypatch.setenv(ac.SYSTEMD_DIR_ENV, str(d))
    return d


def _data(tmp_path, body: str) -> Path:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "config.toml").write_text("[server]\n" + body)
    return data


def _unit(sysd: Path, data: Path) -> None:
    (sysd / "pennywarden.service").write_text(
        f"[Service]\nExecStart=/opt/pennywarden/current/pennywarden --mode server --no-browser --data-dir {data}\n")


def _run(data: Path | None, *args) -> int:
    argv = ["apply-config", *args] + (["--data-dir", str(data)] if data else [])
    return entry.main(argv)


# ------------------------------------------------------------------ checks
def test_check_valid(tmp_path):
    folder = tmp_path / "bk"
    folder.mkdir()
    folders, problems, warnings = ac.check({"mode": "server", "host": "127.0.0.1", "port": 8765,
                                            "trusted_proxies": "127.0.0.1", "secure_cookies": "true",
                                            "backup_folders": [str(folder), str(folder) + "/", str(tmp_path / "nope")]})
    assert problems == []
    assert folders == [str(folder), str(tmp_path / "nope")]   # duplicates dropped
    assert any("doesn't exist yet" in w for w in warnings)


@pytest.mark.parametrize("server,needle", [
    ({"backup_folders": ["relative/path"]}, "absolute path"),
    ({"backup_folders": ["/home/kyle/backups"]}, "protected home folder"),
    ({"backup_folders": ["/root/x"]}, "protected home folder"),
    ({"backup_folders": ["/run/user/1000/x"]}, "protected home folder"),
    ({"backup_folders": 5}, "must be a list"),
    ({"port": 70000}, "port"),
    ({"port": "8765"}, "port"),
    ({"mode": "cloud"}, "mode"),
    ({"trusted_proxies": "127.0.0.1, not-an-ip"}, "trusted_proxies"),
    ({"secure_cookies": "maybe"}, "secure_cookies"),
    ({"host": ""}, "host"),
    ({"session_idle_minutes": "thirty"}, "wrong type"),
])
def test_check_problems(server, needle):
    _f, problems, _w = ac.check(server)
    assert problems and any(needle in p for p in problems), problems


def test_check_warnings_for_network_binding():
    _f, problems, warnings = ac.check({"mode": "server", "host": "0.0.0.0", "secure_cookies": "auto"})
    assert problems == []
    assert any("secure_cookies" in w for w in warnings)
    assert any("trusted_proxies" in w for w in warnings)


# ------------------------------------------------------------------ addresses (#236)
@pytest.mark.parametrize("host,expect", [("127.0.0.1", "127.0.0.1"), ("0.0.0.0", "127.0.0.1"), ("::", "[::1]"),
                                         ("localhost", "localhost"), ("192.168.1.40", "192.168.1.40"),
                                         ("fd00::5", "[fd00::5]"), ("::1", "[::1]")])
def test_connect_host(host, expect):
    assert ac.connect_host(host) == expect


def test_endpoints_loopback_unchanged():
    assert ac.endpoints({"host": "127.0.0.1", "port": 8765}) == [
        "Point your tunnel/reverse proxy at http://127.0.0.1:8765"]


def test_endpoints_all_interfaces_lists_lan_and_loopback():
    lines = ac.endpoints({"host": "0.0.0.0", "port": 9000}, lan=lambda: ["192.168.1.40", "10.8.0.2"])
    text = "\n".join(lines)
    assert "http://192.168.1.40:9000   (from another machine)" in text
    assert "http://10.8.0.2:9000" in text
    assert "http://127.0.0.1:9000   (if the tunnel runs on this machine)" in text
    assert "firewall" in text and "trusted_proxies" in text


def test_endpoints_specific_address():
    assert ac.endpoints({"host": "192.168.1.40", "port": 8765}) == [
        "Point your tunnel/reverse proxy at http://192.168.1.40:8765"]


def test_lan_addresses_skip_loopback_and_link_local(monkeypatch):
    from fmpoc import cli_restore
    seen = []
    monkeypatch.setattr(cli_restore, "_run", lambda args: seen.append(args) or
                        "192.168.1.40 127.0.0.1 fe80::1 172.17.0.1 fd00::5 \n")
    assert ac.lan_addresses() == ["192.168.1.40", "172.17.0.1", "[fd00::5]"]
    assert seen == [["hostname", "-I"]]


def test_show_url_and_endpoints(tmp_path, sysd, capsys):
    data = _data(tmp_path, 'host = "0.0.0.0"\nport = 8800\n')
    assert _run(data, "--show-url") == 0
    assert capsys.readouterr().out.strip() == "http://127.0.0.1:8800"
    data = _data(tmp_path, 'host = "192.168.1.40"\nport = 8765\n')
    assert _run(data, "--show-url") == 0
    assert capsys.readouterr().out.strip() == "http://192.168.1.40:8765"
    assert _run(data, "--show-endpoints") == 0
    assert "http://192.168.1.40:8765" in capsys.readouterr().out


def test_show_url_defaults_without_config(tmp_path, sysd, capsys):
    data = tmp_path / "empty"
    data.mkdir()
    assert _run(data, "--show-url") == 0
    assert capsys.readouterr().out.strip() == "http://127.0.0.1:8765"


# ------------------------------------------------------------------ the drop-in
def test_dry_run_changes_nothing(tmp_path, sysd, capsys):
    folder = tmp_path / "bk"
    folder.mkdir()
    data = _data(tmp_path, f'backup_folders = ["{folder}"]\n')
    _unit(sysd, data)
    assert _run(data, "--dry-run") == 0
    out = capsys.readouterr().out
    assert f'ReadWritePaths="-{folder}"' in out and "nothing was changed" in out
    assert not (sysd / "pennywarden.service.d" / "backup-folders.conf").exists()


def test_invalid_toml_stops_before_anything(tmp_path, sysd, capsys):
    data = _data(tmp_path, 'backup_folders = ["/srv/x"\n')
    _unit(sysd, data)
    assert _run(data, "--no-restart") == 2
    assert "Nothing was changed" in capsys.readouterr().err
    assert not (sysd / "pennywarden.service.d").exists()


def test_problem_stops_before_anything(tmp_path, sysd, capsys):
    data = _data(tmp_path, 'backup_folders = ["/home/kyle/bk"]\n')
    _unit(sysd, data)
    assert _run(data, "--no-restart") == 2
    assert "protected home folder" in capsys.readouterr().err
    assert not (sysd / "pennywarden.service.d").exists()


def test_writes_the_same_dropin_format_as_2_0_0(tmp_path, sysd, capsys):
    a, b = tmp_path / "bk a", tmp_path / 'b"q'
    a.mkdir()
    b.mkdir()
    data = _data(tmp_path, f'backup_folders = ["{a}", \'{b}\']\n')
    _unit(sysd, data)
    # a 2.0.0 drop-in (written by install-server.sh) is recognised and replaced
    dd = sysd / "pennywarden.service.d"
    dd.mkdir()
    (dd / "backup-folders.conf").write_text(
        f"# Written by install-server.sh from backup_folders in {data}/config.toml - run the installer again after "
        f'changing it.\n[Service]\nReadWritePaths="-/srv/old"\n')
    assert _run(data, "--no-restart") == 0
    text = (dd / "backup-folders.conf").read_text()
    lines = text.splitlines()
    assert lines[0].startswith('# Written by "pennywarden apply-config"')
    assert lines[1] == "[Service]"
    assert lines[2] == f'ReadWritePaths="-{a}"'
    assert lines[3] == 'ReadWritePaths="-' + str(b).replace('"', '\\"') + '"'
    assert ac.parse_dropin(text) == [str(a), str(b)]
    out = capsys.readouterr().out
    assert "removed /srv/old" in out and f"added {a}" in out
    assert "Not restarted (--no-restart)" in out


def test_empty_list_removes_the_dropin(tmp_path, sysd):
    data = _data(tmp_path, "backup_folders = []\n")
    _unit(sysd, data)
    dd = sysd / "pennywarden.service.d"
    dd.mkdir()
    (dd / "backup-folders.conf").write_text('# Written by install-server.sh ...\n[Service]\nReadWritePaths="-/srv/x"\n')
    assert _run(data, "--no-restart") == 0
    assert not (dd / "backup-folders.conf").exists()


def test_foreign_dropin_is_not_replaced(tmp_path, sysd, capsys):
    data = _data(tmp_path, "backup_folders = []\n")
    _unit(sysd, data)
    dd = sysd / "pennywarden.service.d"
    dd.mkdir()
    (dd / "backup-folders.conf").write_text("[Service]\nReadWritePaths=/srv/mine\n")
    assert _run(data, "--no-restart") == 2
    assert "not written by PennyWarden" in capsys.readouterr().err
    assert (dd / "backup-folders.conf").read_text() == "[Service]\nReadWritePaths=/srv/mine\n"


def test_override_conf_is_noted_never_edited(tmp_path, sysd, capsys):
    data = _data(tmp_path, "backup_folders = []\n")
    _unit(sysd, data)
    dd = sysd / "pennywarden.service.d"
    dd.mkdir()
    (dd / "override.conf").write_text("[Service]\nReadWritePaths=/srv/handmade\n")
    assert _run(data, "--no-restart") == 0
    assert "override.conf" in capsys.readouterr().out
    assert (dd / "override.conf").read_text() == "[Service]\nReadWritePaths=/srv/handmade\n"


def test_data_dir_defaults_to_the_service(tmp_path, sysd, capsys, monkeypatch):
    monkeypatch.delenv("FM_DATA_DIR", raising=False)
    data = _data(tmp_path, 'host = "0.0.0.0"\nport = 8801\n')
    _unit(sysd, data)
    assert entry.main(["apply-config", "--show-url"]) == 0
    assert capsys.readouterr().out.strip() == "http://127.0.0.1:8801"


# ------------------------------------------------------------------ restart, rollback, audit
def test_restart_and_audit(env, tmp_path, sysd, monkeypatch, capsys):
    data = env.settings.data_dir
    folder = tmp_path / "bk"
    folder.mkdir()
    (data / "config.toml").write_text(f'[server]\nmode = "server"\nport = 8765\nbackup_folders = ["{folder}"]\n')
    _unit(sysd, data)
    seen = []
    monkeypatch.setattr(ac, "restart_and_wait", lambda url: seen.append(url) or True)
    assert _run(data) == 0
    assert seen == ["http://127.0.0.1:8765"]
    out = capsys.readouterr().out
    assert str(folder) in out and "Point your tunnel/reverse proxy at http://127.0.0.1:8765" in out
    s = load_settings({"data_dir": str(data)})
    eng = make_engine(s.database_url)
    with make_session_factory(eng)() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "CONFIG_APPLIED")).one()
        assert ev.category == "SECURITY"
        assert ev.before_snapshot == {"backup_folders": []}
        assert ev.after_snapshot["backup_folders"] == [str(folder)]
        assert ev.after_snapshot["via"] == "host_cli" and ev.after_snapshot["applied_by"].startswith("host:")
        assert ev.after_snapshot["restarted"] is True
    eng.dispose()


def test_failed_restart_puts_the_previous_dropin_back(tmp_path, sysd, monkeypatch, capsys):
    folder = tmp_path / "new"
    folder.mkdir()
    data = _data(tmp_path, f'backup_folders = ["{folder}"]\n')
    _unit(sysd, data)
    dd = sysd / "pennywarden.service.d"
    dd.mkdir()
    old = '# Written by "pennywarden apply-config" ...\n[Service]\nReadWritePaths="-/srv/old"\n'
    (dd / "backup-folders.conf").write_text(old)
    calls = []

    def fake(url):
        calls.append((dd / "backup-folders.conf").read_text())
        return len(calls) > 1   # the first restart (new drop-in) fails, the second (previous) works

    monkeypatch.setattr(ac, "restart_and_wait", fake)
    assert _run(data) == 1
    assert f'ReadWritePaths="-{folder}"' in calls[0]
    assert calls[1] == old
    assert (dd / "backup-folders.conf").read_text() == old
    assert "previous drop-in is back and the service is running again" in capsys.readouterr().err


def test_no_service_here_only_checks(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(ac.SYSTEMD_DIR_ENV, raising=False)
    monkeypatch.setattr(ac, "systemd_dir", lambda: tmp_path / "no-systemd")
    data = _data(tmp_path, "backup_folders = []\n")
    assert _run(data) == 0
    assert "nothing to apply" in capsys.readouterr().out


def test_docker_style_no_browser_prefix(monkeypatch):
    seen = []
    monkeypatch.setattr(ac, "main", lambda argv: seen.append(argv) or 0)
    assert entry.main(["--no-browser", "apply-config", "--dry-run"]) == 0
    assert seen == [["--dry-run"]]


# ------------------------------------------------------------------ the installer uses the command
def test_installer_uses_apply_config():
    text = INSTALLER.read_text()
    assert '"$REL/pennywarden" apply-config --no-restart --installer --data-dir "$DATA"' in text
    assert "apply-config --dry-run" in text           # checked before anything is stopped
    assert "apply-config --show-url" in text          # #236: health check on the configured address
    assert "apply-config --show-endpoints" in text    # #236: the final message
    assert "tomllib" not in text and "ReadWritePaths=\"-" not in text   # no second implementation
    assert "http://127.0.0.1:$PORT" not in text
    assert "$URL/api/health" in text and "$URL/api/system/status" in text


def test_docs_say_apply_config():
    for doc in ("backup-restore.md", "configuration.md", "deployment.md", "upgrade.md"):
        text = (ROOT / "docs" / doc).read_text()
        assert "apply-config" in text, doc
        assert "run the installer again after changing `backup_folders`" not in text.lower(), doc
