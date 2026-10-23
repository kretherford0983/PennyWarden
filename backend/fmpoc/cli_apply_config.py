"""2.1.0 (#237, #236): `pennywarden apply-config` - apply config.toml to the Linux server service.

    sudo pennywarden apply-config [--dry-run] [--no-restart] [--data-dir DIR]
    pennywarden apply-config --show-url | --show-endpoints [--data-dir DIR]      (read-only, used by the installer)

1. Reads and checks config.toml **without stopping anything**: the file must parse; `backup_folders` entries must be
   absolute and outside /home, /root and /run/user (ProtectHome); host, port, mode, trusted_proxies and secure_cookies
   must be valid. Problems are reported and nothing is changed. A backup folder that doesn't exist yet is a warning
   (the service still starts: the drop-in marks every folder optional with "-").
2. Writes the systemd drop-in /etc/systemd/system/pennywarden.service.d/backup-folders.conf - one
   `ReadWritePaths="-<folder>"` per folder, exactly as 2.0.0's installer did (same file, same format) - or removes it
   when the list is empty. The owner's own `override.conf` (`systemctl edit`) is never edited; a note is printed when it
   still lists `ReadWritePaths` (folders probably added by hand before 2.0.0).
3. Unless --no-restart: `systemctl daemon-reload`, `systemctl restart pennywarden`, then waits for /api/health on the
   configured Bind Address and port. If the service doesn't come back, the previous drop-in is put back, the service is
   restarted again and the command fails.
4. Prints the folders the service may write to, what changed, and where it listens. Recorded in the audit log
   (CONFIG_APPLIED, Security) with the folders before and after, by the operating-system user ("host:<name>").

install-server.sh uses the same command (`--no-restart`, then `--show-url` / `--show-endpoints`), so the installer and
the command always produce the same result from the same config.toml. Service managers and `hostname` are called with
fixed argument lists through cli_restore's runner (no shell, BR-102).
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import re
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

SERVICE = "pennywarden"
SYSTEMD_DIR_ENV = "PENNYWARDEN_SYSTEMD_DIR"   # tests only: where the unit and its drop-in folder live
DROPIN_NAME = "backup-folders.conf"
HEADER = '# Written by "pennywarden apply-config" from backup_folders in {cfg} - don\'t edit; change config.toml and run: sudo pennywarden apply-config'
# headers of earlier PennyWarden-written versions of the drop-in (2.0.0 build 13: install-server.sh)
KNOWN_HEADERS = ("# Written by install-server.sh", '# Written by "pennywarden apply-config"')
PROTECTED = ("/home", "/root", "/run/user")
HEALTH_WAIT_SECONDS = 60


class ConfigProblem(Exception):
    pass


def say(msg: str = "") -> None:
    print(msg, flush=True)


# ------------------------------------------------------------------ where things are
def systemd_dir() -> Path:
    return Path(os.environ.get(SYSTEMD_DIR_ENV) or "/etc/systemd/system")


def unit_path() -> Path:
    return systemd_dir() / f"{SERVICE}.service"


def dropin_dir() -> Path:
    return systemd_dir() / f"{SERVICE}.service.d"


def service_data_dir() -> Path | None:
    """The data folder the installed service runs with (its ExecStart --data-dir), if there is a service."""
    try:
        text = unit_path().read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"^ExecStart=.*--data-dir\s+(\S+)", text, re.M)
    return Path(m.group(1)) if m else None


def resolve_data_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    if os.environ.get("FM_DATA_DIR"):
        return Path(os.environ["FM_DATA_DIR"])
    found = service_data_dir()
    if found:
        return found
    from .config import default_data_dir
    return default_data_dir()


# ------------------------------------------------------------------ checks
def _folders(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):   # 2.0.0's installer accepted a string too: one folder, or ':'/newline separated
        return [p for p in value.replace("\n", ":").split(":")]
    raise ConfigProblem("backup_folders must be a list of folders, e.g. backup_folders = [\"/srv/pennywarden-backups\"]")


def read_config(data_dir: Path) -> dict:
    cfg = data_dir / "config.toml"
    if not cfg.is_file():
        return {}
    try:
        with cfg.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as e:
        raise ConfigProblem(f"{cfg} can't be read: {e}") from None
    except OSError as e:
        raise ConfigProblem(f"{cfg} can't be opened: {e.strerror or e}") from None
    server = data.get("server", {})
    if not isinstance(server, dict):
        raise ConfigProblem(f"{cfg}: [server] must be a section.")
    return server


def check(server: dict) -> tuple[list[str], list[str], list[str]]:
    """(folders for the drop-in, problems, warnings). Problems stop the command before anything changes."""
    problems: list[str] = []
    warnings: list[str] = []
    folders: list[str] = []
    try:
        raw = _folders(server.get("backup_folders"))
    except ConfigProblem as e:
        problems.append(str(e))
        raw = []
    for p in raw:
        f = p.strip()
        if not f:
            continue
        if any(ord(c) < 32 for c in f):
            problems.append(f"backup_folders: {f!r} contains a control character.")
        elif not f.startswith("/"):
            problems.append(f"backup_folders: \"{f}\" must be an absolute path (start with /).")
        elif any(f == d or f.startswith(d + "/") for d in PROTECTED):
            problems.append(f"backup_folders: \"{f}\" is under a protected home folder (/home, /root or /run/user) - "
                            "the service can't use it (ProtectHome). Choose a folder such as /srv/pennywarden-backups.")
        elif f.rstrip("/") in folders:
            continue
        else:
            folders.append(f.rstrip("/") or "/")
            fp = Path(f)
            if not fp.exists():
                warnings.append(f"backup folder {f} doesn't exist yet (the service starts anyway; create or mount it "
                                "before choosing it for scheduled backups).")
            elif not fp.is_dir():
                problems.append(f"backup_folders: {f} exists but is not a folder.")

    mode = str(server.get("mode", "server")).strip()
    if mode not in ("local", "server"):
        problems.append(f"mode: \"{mode}\" - must be \"local\" or \"server\".")
    host = str(server.get("host", "127.0.0.1")).strip()
    if not host:
        problems.append("host (Bind Address) is empty.")
    elif host != "localhost":
        try:
            ipaddress.ip_address(host)
        except ValueError:
            warnings.append(f"host \"{host}\" is not an IP address; it must resolve on this server.")
    port = server.get("port", 8765)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        problems.append(f"port: {port!r} - must be a whole number from 1 to 65535.")
    proxies = server.get("trusted_proxies", "")
    if not isinstance(proxies, str):
        problems.append("trusted_proxies must be text: addresses separated by commas, e.g. \"127.0.0.1\".")
        proxies = ""
    for p in [x.strip() for x in proxies.split(",") if x.strip()]:
        try:
            ipaddress.ip_network(p, strict=False)
        except ValueError:
            problems.append(f"trusted_proxies: \"{p[:60]}\" is not an IP address or network.")
    sc = str(server.get("secure_cookies", "auto")).strip().lower()
    if sc not in ("auto", "true", "false"):
        problems.append(f"secure_cookies: \"{sc}\" - must be \"auto\", \"true\" or \"false\".")
    if not problems and mode == "server" and not is_loopback(host) and sc != "true":
        warnings.append("the app listens on a network interface without secure_cookies = \"true\": reach it only "
                        "through an HTTPS tunnel or reverse proxy (docs/deployment.md).")
    if not problems and host in ("0.0.0.0", "::") and not [x for x in proxies.split(",") if x.strip()]:
        warnings.append("listening on all interfaces with no trusted_proxies: add the tunnel/proxy machine's address "
                        "so client addresses and HTTPS are recognised.")
    if not problems:   # the application must accept the file too (types of every other setting)
        try:
            from .config import Settings, _coerce
            base = Settings()
            for k, v in server.items():
                if hasattr(base, k) and k not in ("data_dir", "frontend_dir", "backup_folders"):
                    _coerce(k, v, getattr(base, k))
        except (TypeError, ValueError) as e:
            problems.append(f"a setting has the wrong type: {e}")
    return folders, problems, warnings


# ------------------------------------------------------------------ addresses (#236)
def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def connect_host(host: str) -> str:
    """The address to CONNECT to for a Bind Address: all interfaces -> loopback; anything else as is (IPv6 in [])."""
    host = (host or "127.0.0.1").strip()
    if host in ("0.0.0.0", ""):
        return "127.0.0.1"
    if host == "::":
        return "[::1]"
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def connect_url(server: dict) -> str:
    return f"http://{connect_host(str(server.get('host', '127.0.0.1')))}:{server.get('port', 8765)}"


def lan_addresses() -> list[str]:
    from .cli_restore import _run   # the one place that starts OS programs: fixed argument lists, no shell (BR-102)
    out = _run(["hostname", "-I"]) or ""
    found = []
    for a in out.split():
        try:
            ip = ipaddress.ip_address(a.split("%")[0])
        except ValueError:
            continue
        if ip.is_loopback or ip.is_link_local:
            continue
        found.append(f"[{ip}]" if ip.version == 6 else str(ip))
    return found


def endpoints(server: dict, lan=lan_addresses) -> list[str]:
    host = str(server.get("host", "127.0.0.1")).strip() or "127.0.0.1"
    port = server.get("port", 8765)
    if is_loopback(host):
        return [f"Point your tunnel/reverse proxy at http://{connect_host(host)}:{port}"]
    if host in ("0.0.0.0", "::"):
        lines = [f"Listening on all network interfaces (Bind Address {host}), port {port}. Point your tunnel/reverse "
                 "proxy at:"]
        lines += [f"    http://{a}:{port}   (from another machine)" for a in lan()]
        lines.append(f"    http://{connect_host(host)}:{port}   (if the tunnel runs on this machine)")
        lines.append("Restrict the port with the firewall to the tunnel/proxy machine, and list that machine's address "
                     "in trusted_proxies (config.toml).")
        return lines
    return [f"Point your tunnel/reverse proxy at http://{connect_host(host)}:{port}"]


# ------------------------------------------------------------------ the drop-in
def render(folders: list[str], cfg: Path) -> str | None:
    if not folders:
        return None
    lines = [HEADER.format(cfg=cfg), "[Service]"]
    lines += ['ReadWritePaths="-%s"' % f.replace("\\", "\\\\").replace('"', '\\"') for f in folders]
    return "\n".join(lines) + "\n"


def parse_dropin(text: str | None) -> list[str]:
    if not text:
        return []
    out = []
    for m in re.finditer(r'^ReadWritePaths="-((?:[^"\\]|\\.)*)"\s*$', text, re.M):
        out.append(m.group(1).replace('\\"', '"').replace("\\\\", "\\"))
    return out


def override_note() -> str | None:
    p = dropin_dir() / "override.conf"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    if re.search(r"^\s*ReadWritePaths\s*=", text, re.M):
        return (f"NOTE: {p} (your own 'systemctl edit' override) also lists ReadWritePaths. Those folders were probably "
                "added by hand before 2.0.0; now that backup_folders handles them you can remove those lines "
                f"(sudo systemctl edit {SERVICE}). This command never edits override.conf.")
    return None


def _write(path: Path, text: str | None) -> None:
    if text is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


# ------------------------------------------------------------------ service control (monkeypatched in tests)
def systemctl(*args: str) -> bool:
    from .cli_restore import _run   # fixed argument lists, no shell (BR-102)
    return _run(["systemctl", *args]) is not None


def healthy(url: str, wait: int = HEALTH_WAIT_SECONDS) -> bool:
    for _ in range(wait):
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=2) as r:  # noqa: S310 - fixed scheme
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False


def restart_and_wait(url: str) -> bool:
    return systemctl("daemon-reload") and systemctl("restart", SERVICE) and healthy(url)


# ------------------------------------------------------------------ audit
def record_audit(data_dir: Path, before: list[str], after: list[str], restarted: bool) -> None:
    """CONFIG_APPLIED (Security), by the operating-system user. Skipped when there is no database yet (a new install)."""
    from .config import load_settings
    settings = load_settings({"data_dir": str(data_dir)})
    if not settings.database_path.is_file():
        return
    from types import SimpleNamespace

    from sqlalchemy import select

    from . import audit
    from .cli_restore import match_ownership, os_user
    from .db import make_engine, make_session_factory, upgrade_database
    from .models import Workspace
    upgrade_database(settings.database_url)
    engine = make_engine(settings.database_url)
    try:
        with make_session_factory(engine)() as db:
            ws = db.scalar(select(Workspace).order_by(Workspace.id))
            ctx = SimpleNamespace(workspace_id=ws.id if ws else None, user=None, correlation_id="host-cli", ip=None)
            audit.record(db, ctx, "CONFIG_APPLIED", "server_config", "backup_folders", {"backup_folders": before},
                         {"backup_folders": after, "via": "host_cli", "applied_by": f"host:{os_user()}",
                          "restarted": restarted}, category="SECURITY")
            db.commit()
    finally:
        engine.dispose()
    match_ownership(data_dir, ["database", "logs"])


# ------------------------------------------------------------------ the command
def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="pennywarden apply-config",
                                description="Apply config.toml to the PennyWarden service: check it, let the service "
                                            "write to the backup_folders, restart and wait until it answers.")
    p.add_argument("--data-dir", help="the data folder (default: the installed service's)")
    p.add_argument("--dry-run", action="store_true", help="check and show what would be written; change nothing")
    p.add_argument("--no-restart", action="store_true", help="write the drop-in but don't restart the service")
    p.add_argument("--show-url", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--show-endpoints", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--installer", action="store_true", help=argparse.SUPPRESS)   # install-server.sh restarts itself
    a = p.parse_args(argv)
    data_dir = resolve_data_dir(a.data_dir)
    cfg = data_dir / "config.toml"
    try:
        server = read_config(data_dir)
    except ConfigProblem as e:
        print(f"error: {e}", file=sys.stderr)
        print("Nothing was changed.", file=sys.stderr)
        return 2
    if a.show_url:
        say(connect_url(server))
        return 0
    if a.show_endpoints:
        for line in endpoints(server):
            say(line)
        return 0

    folders, problems, warnings = check(server)
    if problems:
        print(f"error: {cfg} has problems - nothing was changed:", file=sys.stderr)
        for x in problems:
            print(f"  - {x}", file=sys.stderr)
        return 2
    for w in warnings:
        say(f"warning: {w}")

    path = dropin_dir() / DROPIN_NAME
    try:
        old_text = path.read_text(encoding="utf-8")
    except OSError:
        old_text = None
    before = parse_dropin(old_text)
    new_text = render(folders, cfg)
    added = [f for f in folders if f not in before]
    removed = [f for f in before if f not in folders]
    if old_text is not None and not old_text.startswith(KNOWN_HEADERS):
        print(f"error: {path} was not written by PennyWarden; move it aside first (it is not replaced).",
              file=sys.stderr)
        return 2
    note = override_note()
    systemd = unit_path().is_file()

    if a.dry_run:
        say(f"Checked {cfg}: OK." if server else f"No {cfg} - the defaults apply.")
        if new_text is None:
            say(f"Would remove {path}." if old_text is not None else "No backup_folders: no drop-in needed.")
        else:
            say(f"Would write {path}:")
            for line in new_text.splitlines():
                say(f"    {line}")
        if added or removed:
            say(f"Changes: added {', '.join(added) or 'none'}; removed {', '.join(removed) or 'none'}.")
        if note:
            say(note)
        say("Dry run: nothing was changed.")
        return 0

    if not systemd and SYSTEMD_DIR_ENV not in os.environ:
        say(f"Checked {cfg}: OK.")
        say(f"No systemd service ({unit_path()}) on this machine, so there is nothing to apply: restart PennyWarden "
            "to use the changed settings.")
        return 0
    if os.name != "nt" and os.geteuid() != 0 and SYSTEMD_DIR_ENV not in os.environ:
        print("error: run it with sudo: sudo pennywarden apply-config", file=sys.stderr)
        return 1

    _write(path, new_text)
    restarted = False
    if not a.no_restart:
        url = connect_url(server)
        say(f"==> restarting {SERVICE} and waiting for {url}/api/health")
        if not restart_and_wait(url):
            say("==> the service did not come back - putting the previous drop-in back and restarting it")
            _write(path, old_text)
            back = restart_and_wait(url)
            print(f"error: {SERVICE} did not start with the new settings. The previous drop-in is back"
                  + (" and the service is running again." if back else ", but the service is still not answering: "
                     f"see journalctl -u {SERVICE} -n 50."), file=sys.stderr)
            return 1
        restarted = True
    try:
        record_audit(data_dir, before, folders, restarted)
    except Exception as e:   # the change is applied; the audit failing must not hide that
        say(f"warning: the change was applied but could not be recorded in the audit log ({type(e).__name__}).")

    if folders:
        say("Scheduled-backup folders the service may write to:")
        for f in folders:
            say(f"    {f}")
    else:
        say("No scheduled-backup folders (backup_folders is empty).")
    if added or removed:
        say(f"Changes: added {', '.join(added) or 'none'}; removed {', '.join(removed) or 'none'}.")
    else:
        say("No change to the folders.")
    if note:
        say(note)
    if restarted:
        for line in endpoints(server):
            say(line)
    elif not a.installer:
        say(f"Not restarted (--no-restart): run sudo systemctl daemon-reload && sudo systemctl restart {SERVICE}.")
    return 0
