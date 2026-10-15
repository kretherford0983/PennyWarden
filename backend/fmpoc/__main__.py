"""Launcher for local and server modes (docs/06 §7).

    fmpoc [--mode local|server] [--host HOST] [--port PORT] [--data-dir DIR] [--no-browser]

Local mode binds to 127.0.0.1, applies migrations, waits for /api/health and opens the default browser.
Server mode binds to the configured interface; plain-HTTP network exposure logs a prominent warning.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import urllib.request
import webbrowser

from .config import VERSION, is_loopback, load_settings


def _open_browser_when_ready(url: str) -> None:
    for _ in range(120):
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as r:  # noqa: S310 - fixed loopback URL
                if r.status == 200:
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.25)


def reset_mfa_cli(argv: list[str]) -> int:
    """v1.4.1 CR-018: host-side MFA reset for a locked-out user (e.g. the only Administrator).

        pennywarden reset-mfa --user NAME [--reason TEXT] [--data-dir DIR]

    On the Linux server run it with sudo (sudo pennywarden reset-mfa ...); files it writes are handed back to the data
    folder's owner afterwards (2.0.0). The user sets MFA
    up again at the next sign-in. Recorded in the audit log as MFA_RESET via "host_cli".
    """
    p = argparse.ArgumentParser(prog="pennywarden reset-mfa", description="Reset a user's two-step verification")
    p.add_argument("--user", required=True, help="username")
    p.add_argument("--reason", default="Reset from the server command line")
    p.add_argument("--data-dir")
    a = p.parse_args(argv)
    from sqlalchemy import select

    from .db import make_engine, make_session_factory, upgrade_database
    from .models import User
    from .services import mfa

    settings = load_settings({"data_dir": a.data_dir})
    if not settings.database_path.is_file():
        print(f"No database found in {settings.data_dir}", file=sys.stderr)
        return 2
    upgrade_database(settings.database_url)
    factory = make_session_factory(make_engine(settings.database_url))
    with factory() as db:
        user = db.scalar(select(User).where(User.username_normalized == a.user.strip().lower()))
        if user is None:
            print(f"User '{a.user}' not found.", file=sys.stderr)
            return 1

        from types import SimpleNamespace
        host_ctx = SimpleNamespace(workspace_id=user.workspace_id, user=None, correlation_id="host-cli", ip=None)
        mfa.reset(db, host_ctx, user, a.reason, via="host_cli")  # audit context: host action, no signed-in user
        enabled = _reenable(db, host_ctx, user)   # 1.8.0 (#113)
        db.commit()
    _own_again(settings)
    print(f"Two-step verification for '{user.username}' was reset. They will set it up again at the next sign-in.")
    if enabled:
        print("The account was disabled; it is enabled again and its failed attempts are cleared.")
    return 0


def _own_again(settings) -> None:
    """2.0.0 build 13: run with sudo (as root), a host command may leave database files (SQLite journal/WAL) owned by
    root, which the service then can't write. Like restore and reinitialize, hand them back to the data folder's
    owner. Nothing happens when not run as root, or on Windows."""
    from .cli_restore import match_ownership
    match_ownership(settings.data_dir, ["database", "logs"])


def _reenable(db, host_ctx, user) -> bool:
    """1.8.0 (#113): the host commands also end a lock, clear the failed attempts and re-enable a disabled account
    (the way back in for the only Administrator)."""
    from . import audit
    was = bool(user.active)
    had = user.failed_attempts or 0
    user.active, user.failed_attempts, user.locked_until = True, 0, None
    if not was or had:
        audit.record(db, host_ctx, "USER_ENABLED" if not was else "ACCOUNT_UNLOCKED", "user", user.id,
                     {"active": was, "failed_attempts": had}, {"active": True, "failed_attempts": 0, "via": "host_cli"},
                     category="SECURITY")
    return not was


def reset_password_cli(argv: list[str]) -> int:
    """1.8.0 (#113): host-side password reset (e.g. the only Administrator forgot both the password and the answers).

        pennywarden reset-password --user NAME [--data-dir DIR]

    Prints a temporary password that must be changed at the next sign-in. Also ends a lock, clears the failed attempts
    and re-enables the account. Signs the user out everywhere. Audited as USER_PASSWORD_RESET via "host_cli".
    """
    p = argparse.ArgumentParser(prog="pennywarden reset-password", description="Reset a user's password")
    p.add_argument("--user", required=True, help="username")
    p.add_argument("--data-dir")
    a = p.parse_args(argv)
    import secrets
    from types import SimpleNamespace

    from sqlalchemy import select

    from . import audit
    from .db import make_engine, make_session_factory, upgrade_database
    from .models import User, utcnow
    from .security.passwords import hash_password
    from .services import mfa
    from .services.auth import revoke_user_sessions

    settings = load_settings({"data_dir": a.data_dir})
    if not settings.database_path.is_file():
        print(f"No database found in {settings.data_dir}", file=sys.stderr)
        return 2
    upgrade_database(settings.database_url)
    factory = make_session_factory(make_engine(settings.database_url))
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    temp = "".join(secrets.choice(alphabet) for _ in range(14)) + secrets.choice("23456789") + secrets.choice("abcdefghjk")
    with factory() as db:
        user = db.scalar(select(User).where(User.username_normalized == a.user.strip().lower()))
        if user is None:
            print(f"User '{a.user}' not found.", file=sys.stderr)
            return 1
        host_ctx = SimpleNamespace(workspace_id=user.workspace_id, user=None, correlation_id="host-cli", ip=None)
        user.password_hash = hash_password(temp)
        user.password_changed_at = utcnow()
        user.must_change_password = True
        sessions = revoke_user_sessions(db, user.id)
        trusted = mfa.revoke_trusted(db, user.id)
        audit.record(db, host_ctx, "USER_PASSWORD_RESET", "user", user.id, None,
                     {"via": "host_cli", "temporary": True, "sessions_revoked": sessions,
                      "trusted_browsers_revoked": trusted}, category="SECURITY")
        enabled = _reenable(db, host_ctx, user)
        db.commit()
    _own_again(settings)
    print(f"Temporary password for '{user.username}': {temp}")
    print("It must be changed at the next sign-in.")
    if enabled:
        print("The account was disabled; it is enabled again and its failed attempts are cleared.")
    return 0


def main(argv: list[str] | None = None, window: bool = False) -> int:
    """window=True (1.6.7, the macOS app): local mode runs behind a small status window instead of a console."""
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) > 1 and argv[0] == "--no-browser" and argv[1] in ("reset-mfa", "reset-password", "restore",
                                                               "reinitialize"):
        argv = argv[1:]   # 2.0.0: the Docker image's entrypoint adds --no-browser before a command
    if argv and argv[0] == "reset-mfa":
        return reset_mfa_cli(argv[1:])
    if argv and argv[0] == "reset-password":
        return reset_password_cli(argv[1:])
    if argv and argv[0] == "restore":   # 2.0.0 (#124)
        from .cli_restore import main as restore_cli
        return restore_cli(argv[1:])
    if argv and argv[0] == "reinitialize":   # 2.0.0 (#125)
        from .cli_restore import reinit_main
        return reinit_main(argv[1:])
    p = argparse.ArgumentParser(prog="pennywarden", description="PennyWarden")
    p.add_argument("--mode", choices=["local", "server"])
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--data-dir")
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--version", action="store_true")
    a = p.parse_args(argv)
    if a.version:
        print(VERSION)
        return 0
    overrides = {"mode": a.mode, "host": a.host, "port": a.port, "data_dir": a.data_dir}
    if a.no_browser:
        overrides["open_browser"] = False
    settings = load_settings(overrides)
    if settings.mode == "local" and not is_loopback(settings.host):
        print("WARNING: local mode is intended for loopback only; binding to", settings.host, file=sys.stderr)
    if settings.mode == "server" and not is_loopback(settings.host) and settings.secure_cookies != "true":
        print("\n" + "!" * 78 + "\n SECURITY WARNING: serving on a network interface over plain HTTP.\n"
              " This is NOT secure for authenticated use. Place the application behind an HTTPS reverse\n"
              " proxy (Caddy/nginx/Apache) and set FM_SECURE_COOKIES=true.\n" + "!" * 78 + "\n", file=sys.stderr)

    import uvicorn

    from .app import create_app

    app = create_app(settings)
    url = f"http://{'127.0.0.1' if settings.host in ('0.0.0.0', '::') else settings.host}:{settings.port}"
    print(f"PennyWarden {VERSION} - {settings.mode} mode - {url}")
    print(f"Application data: {settings.data_dir}")
    trusted = settings.trusted_proxies.strip()
    kwargs = dict(host=settings.host, port=settings.port, access_log=False, server_header=False,
                  proxy_headers=bool(trusted), forwarded_allow_ips=trusted or None, log_config=None)
    if window:
        from . import desktop

        if desktop.window_wanted(settings):
            return desktop.run_with_window(app, settings, url, VERSION, kwargs)  # opens the browser itself
    if settings.mode == "local" and settings.open_browser:
        threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()
    uvicorn.run(app, **kwargs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
