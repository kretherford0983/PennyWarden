"""2.0.0 (#124): `pennywarden restore` - restore a backup from the server's command line.

    pennywarden restore FILE.fmbak [--use-server-key | --passphrase-file PATH] [--data-dir DIR]
                        [--only PARTS | --skip PARTS] [--missing-users add|include-users]
                        [--stop-service] [--yes]
    pennywarden restore FILE.fmbak --list [...]     the parts this backup holds (2.2.0, #319); nothing changes
    pennywarden restore --list [--data-dir DIR]     the backups this server can recover

2.2.0 (#319): PARTS is a comma-separated list of data, settings (or settings.general, settings.backups,
settings.payments, settings.donations, settings.branding), reminders and users. Data is never split. Without --only/--skip everything is
restored, as before.

Order of checks: (1) elevation (only where it is needed), (2) the backup file and its passphrase (decrypted and
verified against its manifest before anything changes), (3) whether the service is running, then the restore - the
same steps as the web restore: re-entry report, safety copy in pre-restore/, swap, migrate, revoke every session,
audit (via host_cli, with the operating-system user), with automatic rollback if anything fails after the swap.

The passphrase is never a command-line value: a hidden prompt, a file (`--passphrase-file`, or the environment
variable PENNYWARDEN_PASSPHRASE_FILE), or `--use-server-key` for a backup made on this server with recovery on. It is
never printed, logged or audited. Service managers are called with fixed argument lists (no shell, BR-102).
"""
from __future__ import annotations

import argparse
import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE = "pennywarden"            # systemd unit (packaging/linux/install-server.sh)
WINDOWS_SERVICE = "PennyWarden"    # Windows service (docs/install-windows-server.md, NSSM)
PASSPHRASE_ENV = "PENNYWARDEN_PASSPHRASE_FILE"


class CliError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def say(msg: str = "") -> None:
    print(msg, flush=True)


# ------------------------------------------------------------------ environment checks
def in_container() -> bool:
    return Path("/.dockerenv").exists() or os.environ.get("container") in ("docker", "podman") or \
        os.environ.get("PENNYWARDEN_IN_CONTAINER") == "1"


def host_command(settings) -> tuple[str, str]:
    """2.0.0 build 13: the command that runs a host command (restore, reinitialize ...) on THIS installation, and where
    to run it - shown to the Administrator, so it must work when pasted:
      Linux/macOS server  "sudo pennywarden" (the installer adds /usr/local/bin/pennywarden; before that, the program's
                          full path), from a shell on the server;
      Windows             the full path of PennyWarden.cmd, in a terminal opened as Administrator;
      local install       the program itself, no sudo (quit PennyWarden first);
      container           "pennywarden" in a one-off container on the same data volume (docs/backup-restore.md)."""
    if in_container():
        return "pennywarden", "in a one-off container on the same data volume (see docs/backup-restore.md, Docker)"
    if os.name == "nt":
        exe = Path(sys.executable)          # <install>\current\python\python.exe
        cmd = exe.parent.parent / "PennyWarden.cmd"
        return (f'"{cmd}"' if cmd.is_file() else "PennyWarden.cmd"), "in a terminal opened as Administrator on the server"
    found = shutil.which("pennywarden") or ("/usr/local/bin/pennywarden" if Path("/usr/local/bin/pennywarden").is_file()
                                            else None)
    if found:
        prog = "pennywarden"
    else:   # a portable install without the command: the launcher next to the bundled Python (or the frozen program)
        exe = Path(sys.executable)
        launcher = exe.parent.parent.parent / "pennywarden" if exe.parent.name == "bin" else exe
        prog = f'"{launcher}"' if " " in str(launcher) else str(launcher)
    if getattr(settings, "mode", "server") == "server":
        return f"sudo {prog}", "in a shell on the server"
    return prog, "on this computer, with PennyWarden quit"


def restore_command(settings, path) -> str:
    cmd, _where = host_command(settings)
    return f'{cmd} restore "{path}" --use-server-key --data-dir "{settings.data_dir}"'


def is_elevated() -> bool:
    if os.name == "nt":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())   # type: ignore[attr-defined]
        except Exception:   # pragma: no cover
            return False
    return os.geteuid() == 0


def service_installed() -> bool:
    if in_container():
        return False
    if os.name == "nt":
        return _run(["sc.exe", "query", WINDOWS_SERVICE]) is not None
    return Path(f"/etc/systemd/system/{SERVICE}.service").is_file()


def needs_elevation(data_dir: Path) -> bool:
    """Elevation only where it is needed: a system service, or a data folder this user can't write."""
    if is_elevated():
        return False
    if service_installed():
        return True
    probe = data_dir if data_dir.exists() else data_dir.parent
    return not os.access(probe, os.W_OK)


def _run(args: list[str]) -> str | None:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)  # noqa: S603 - fixed args
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def service_running() -> bool:
    if in_container() or not service_installed():
        return False
    if os.name == "nt":
        out = _run(["sc.exe", "query", WINDOWS_SERVICE]) or ""
        return "RUNNING" in out
    return _run(["systemctl", "is-active", "--quiet", SERVICE]) is not None


def stop_service() -> None:
    ok = _run(["sc.exe", "stop", WINDOWS_SERVICE] if os.name == "nt" else ["systemctl", "stop", SERVICE])
    if ok is None and service_running():
        raise CliError("The service could not be stopped. Stop it yourself and run the command again.", 5)
    if os.name == "nt":   # sc stop returns at once; wait until it has stopped
        import time
        for _ in range(60):
            if not service_running():
                break
            time.sleep(1)


def start_service() -> bool:
    return _run(["sc.exe", "start", WINDOWS_SERVICE] if os.name == "nt" else ["systemctl", "start", SERVICE]) is not None


def stop_instructions() -> str:
    if os.name == "nt":
        return f"Stop the service first (as Administrator: sc.exe stop {WINDOWS_SERVICE}), or answer yes."
    return f"Stop the service first (sudo systemctl stop {SERVICE}), or answer yes."


def app_answering(settings) -> bool:
    """A local install has no service: is the app itself running on this data folder?"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{settings.port}/api/health", timeout=1) as r:  # noqa: S310
            return r.status == 200
    except Exception:
        return False


def ask(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def match_ownership(data_dir: Path, parts: list[str]) -> None:
    """After a restore run as root on Linux/macOS: the restored files belong to the data folder's owner again and
    secrets/ stays owner-only."""
    if os.name == "nt" or os.geteuid() != 0:
        return
    st = data_dir.stat()
    for part in parts:
        top = data_dir / part
        if not top.exists():
            continue
        for root, dirs, files in os.walk(top):
            for n in [root, *[os.path.join(root, d) for d in dirs], *[os.path.join(root, f) for f in files]]:
                try:
                    os.chown(n, st.st_uid, st.st_gid)
                except OSError:
                    pass
    sec = data_dir / "secrets"
    if sec.is_dir():
        os.chmod(sec, 0o700)
        for f in sec.iterdir():
            os.chmod(f, 0o600)


# ------------------------------------------------------------------ passphrase
def read_passphrase(args, settings, backup: Path) -> str:
    from .services import server_recovery
    if args.use_server_key:
        p = server_recovery.passphrase_for(settings, backup)
        if p is None:
            raise CliError("This server can't unlock that backup: it was not made here with \"Let this server recover "
                           "the passphrase\", or it comes from another system. Use --passphrase-file or type the "
                           "passphrase.", 2)
        return p
    path = args.passphrase_file or os.environ.get(PASSPHRASE_ENV)
    if path:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            raise CliError("The passphrase file can't be read.", 2) from None
        if text.endswith("\r\n"):
            text = text[:-2]
        elif text.endswith("\n"):
            text = text[:-1]
        return text
    if not sys.stdin.isatty():
        raise CliError("No passphrase: use --passphrase-file, --use-server-key or run it in a terminal.", 2)
    return getpass.getpass("Backup passphrase: ")


# ------------------------------------------------------------------ the restore
def restore(args) -> int:
    from .config import load_settings
    from .services import backup as bk

    settings = load_settings({"data_dir": args.data_dir})
    data_dir = settings.data_dir
    if args.list and not args.file:
        return list_backups(settings)
    from .services import partial_restore as pr
    try:
        if args.only:
            chosen = pr.normalize([args.only])
        elif args.skip:
            skip = set(pr.parse_names(args.skip))
            chosen = pr.normalize([d for d in pr.DOMAINS if d not in skip])
        else:
            chosen = list(pr.DOMAINS)
    except pr.RestoreChoiceError as e:
        raise CliError(f"{e} Nothing was changed.", 2) from None
    missing_users = (args.missing_users or "add").replace("-", "_")
    if missing_users == "include_users" and "users" not in chosen:
        chosen = pr.normalize(chosen + ["users"])
    if not args.file:
        raise CliError("Give the backup file: pennywarden restore FILE.fmbak", 2)
    # (1) elevation
    if needs_elevation(data_dir):
        raise CliError("This needs administrator rights: run it again with sudo (Linux) or from a terminal opened "
                       "as Administrator (Windows). Nothing was changed.", 3)
    # (2) the file and the passphrase
    src = Path(args.file).expanduser()
    if not src.is_file():
        raise CliError("The backup file was not found.", 2)
    passphrase = read_passphrase(args, settings, src)
    settings.ensure_dirs()
    work = bk.work_dir(settings) / f"cli-{os.getpid()}"
    shutil.rmtree(work, ignore_errors=True)
    try:
        say("Decrypting and checking the backup ...")
        try:
            manifest = bk.unpack(src, passphrase, work / "unpacked")
            facts = bk.check_compatible(work / "unpacked" / "data", known_revisions(settings))
            from .services.testing import enabled_for
            testing_backup = bk.check_testing(manifest, enabled_for(settings), args.accept_testing_backup)
        except bk.BackupError as e:
            raise CliError(f"{e} Nothing was changed.", 2) from None
        say(f"  Backup of \"{facts['workspace']}\" made {manifest.get('created_at')} with version "
            f"{manifest.get('app_version')}.")
        if testing_backup:
            say("  It was made on a server in TESTING MODE (its audit trail may have gaps).")
        from .config import is_loopback
        from .services import demo as demo_svc     # 2.2.0 (#243): the demo is restored whole, on this computer only
        if demo_svc.is_demo_db(work / "unpacked" / "data" / "database" / bk.DB_NAME) or \
                demo_svc.is_demo_db(settings.database_path):
            if demo_svc.is_demo_db(work / "unpacked" / "data" / "database" / bk.DB_NAME) and \
                    (settings.mode == "server" or not is_loopback(settings.host)):
                raise CliError(f"{demo_svc.LOOPBACK_ONLY} Nothing was changed.", 2)
            if not pr.is_full(chosen):
                say("  The demo is always restored (or replaced) whole: --only/--skip are ignored.")
                chosen = list(pr.DOMAINS)
        full = pr.is_full(chosen)
        if args.list or not full:
            # 2.2.0 (#319, point 9): the backup is brought to this version in the work folder before anything else
            from .db import upgrade_database
            backup_db = work / "unpacked" / "data" / "database" / bk.DB_NAME
            upgrade_database(f"sqlite:///{backup_db.as_posix()}")
        if args.list:
            say("The backup holds (restore them with --only or --skip):")
            for d in pr.domains_in(backup_db):
                counts = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in d["counts"].items())
                say(f"  {d['name']:<19} {d['label']}  [{counts}]")
            return 0
        if not full:
            sm = pr.summary(chosen)
            say("Restoring:     " + ", ".join(x["name"] for x in sm["restored"]))
            say("Keeping as is: " + ", ".join(x["name"] for x in sm["kept"]) + " (and the current audit log)")
            if settings.database_path.is_file():
                chk = pr.check(settings.database_path, backup_db, chosen)
                if chk["missing_users"]:
                    names = ", ".join(u["username"] for u in chk["missing_users"])
                    if missing_users == "add":
                        say(f"The restored records refer to users that aren't here: {names}. They will be added from "
                            "the backup (or use --missing-users include-users to restore Users too).")
                for c in chk["user_id_clashes"]:
                    say(f"Warning: user id {c['id']} is {c['backup_username']} in the backup but "
                        f"{c['current_username']} here (a backup from another installation).")
            if not ask("Continue?", args.yes):
                raise CliError("Nothing was changed.", 4)
        # (3) the service
        stopped = False
        if in_container():
            say("Running in a container: nothing is stopped here. Stop the PennyWarden container first and run this "
                "in a one-off container on the same data volume (docs/backup-restore.md).")
        elif service_running():
            if not (args.stop_service or ask("The PennyWarden service is running. Stop it now? All signed-in users "
                                             "will be signed out.", args.yes)):
                raise CliError(f"Nothing was changed. {stop_instructions()}", 4)
            say("Stopping the service ...")
            stop_service()
            stopped = True
        elif app_answering(settings):
            raise CliError("PennyWarden is running on this data folder. Quit it first, then run the command again. "
                           "Nothing was changed.", 4)
        summary = run_offline_restore(settings, work / "unpacked" / "data", manifest, src.name, chosen,
                                      missing_users, testing_backup)
        say("Restore complete.")
        for line in summary.get("notes") or []:
            say("  " + line)
        from .services.restore_report import summary_text
        say("  " + summary_text(summary))
        if stopped:
            if ask("Start the PennyWarden service again?", args.yes):
                say("Service started." if start_service() else "The service could not be started: start it yourself.")
            else:
                say(f"Start it when ready (sudo systemctl start {SERVICE})." if os.name != "nt" else
                    f"Start it when ready (sc.exe start {WINDOWS_SERVICE}).")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


def known_revisions(settings) -> set[str]:
    from alembic.script import ScriptDirectory

    from .db import alembic_config
    return {r.revision for r in ScriptDirectory.from_config(alembic_config(settings.database_url)).walk_revisions()}


def os_user() -> str:
    try:
        return getpass.getuser()[:40]
    except Exception:   # pragma: no cover
        return "unknown"


def run_offline_restore(settings, data: Path, manifest: dict, source_name: str, chosen: list[str] | None = None,
                        missing_users: str = "add", testing_backup: bool = False) -> dict:
    """Report, swap, migrate, revoke sessions and audit - with the service stopped. Rolls back on failure.
    2.2.0 (#319): chosen - the parts to restore (default everything); a partial restore keeps the rest and the
    current audit log."""
    from types import SimpleNamespace

    from sqlalchemy import update

    from . import audit
    from .db import make_engine, make_session_factory, upgrade_database
    from .models import AuthSession, TrustedDevice, utcnow
    from .services import backup as bk
    from .services import bootstrap
    from .services import partial_restore as pr
    from .services.restore_report import REPORT_DIR, build

    chosen = chosen or list(pr.DOMAINS)
    full = pr.is_full(chosen) or not settings.database_path.is_file()
    if full:
        chosen = list(pr.DOMAINS)
    summary: dict = {}
    if settings.database_path.is_file() and "data" in chosen:
        say("Comparing the current data with the backup (re-entry report) ...")
        engine = make_engine(settings.database_url)
        try:
            with make_session_factory(engine)() as s:
                ws = bootstrap.current_workspace(s) if bootstrap.is_initialized(s) else None
                if ws is not None:
                    summary = build(s, ws.id, data / "database" / bk.DB_NAME, manifest.get("created_at"),
                                    settings.data_dir / REPORT_DIR)
        finally:
            engine.dispose()
    facts: dict = {}
    if not full:
        say("Combining the chosen parts with the current data ...")
        try:
            data, facts = pr.prepare_result(settings, data, chosen, missing_users)
        except (pr.RestoreChoiceError, bk.BackupError) as e:
            raise CliError(f"{e} Nothing was changed.", 6) from None
    say("Saving a safety copy of the current data (pre-restore/) and putting the backup in place ...")
    bk.swap_in(settings, data)
    try:
        say("Updating the database to this version ...")
        upgrade_database(settings.database_url)
        engine = make_engine(settings.database_url)
        try:
            with make_session_factory(engine)() as s:
                now = utcnow()
                s.execute(update(AuthSession).where(AuthSession.revoked_at.is_(None)).values(revoked_at=now))
                s.execute(update(TrustedDevice).where(TrustedDevice.revoked_at.is_(None)).values(revoked_at=now))
                ws = bootstrap.current_workspace(s)
                if ws is None:
                    raise bk.BackupError("The restored database has no organization.")
                ctx = SimpleNamespace(workspace_id=ws.id, correlation_id="host-cli", ip=None, user=None)
                audit.record(s, ctx, "SYSTEM_RESTORED", "workspace", ws.id, None,
                             {"restored_by": f"host:{os_user()}", "via": "host_cli", "file": source_name[:200],
                              "backup_created_at": manifest.get("created_at"),
                              "backup_app_version": manifest.get("app_version"), "counts": manifest.get("counts"),
                              "report": summary.get("report"), "report_transactions": summary.get("transactions", 0),
                              "sessions_revoked": "all", "restored": chosen,
                              "kept": [d for d in pr.DOMAINS if d not in chosen], "partial": not full,
                              "notes": pr.report_lines(facts) if not full else [],
                              "testing_backup": testing_backup}, category="SECURITY")
                s.commit()
        finally:
            engine.dispose()
        from .security import crypto
        if crypto.load_key(settings.secrets_dir) is None:
            raise bk.BackupError("The restored encryption key can't be read.")
    except Exception as e:
        say("The restore failed; putting the previous data back ...")
        bk.rollback(settings)
        detail = str(e) if isinstance(e, bk.BackupError) else type(e).__name__
        raise CliError(f"Restore failed ({detail}); the previous data was put back.", 6) from None
    from .services import demo as demo_svc     # 2.2.0 (#243)
    demo_svc.keep_pristine(settings)
    match_ownership(settings.data_dir, list(bk.PARTS) + [bk.PRE_RESTORE_DIR, REPORT_DIR, demo_svc.PRISTINE])
    return {**summary, "notes": pr.report_lines(facts) if not full else []}


def list_backups(settings) -> int:
    from .services import server_recovery
    rows = server_recovery.list_backups(settings)
    if not rows:
        say("No backups made on this server can be recovered with the server key.")
        return 0
    say(f"{'Created (UTC)':<22} {'Size':>10}  {'Kind':<17} {'By':<16} File")
    first_path = None
    for r in rows:
        size = f"{(r['size'] or 0) / 1024 / 1024:.1f} MB"
        say(f"{(r['created_at'] or '')[:19]:<22} {size:>10}  {r['kind']:<17} {(r['created_by'] or '')[:16]:<16} "
            f"{r['filename']}")
        # build 13: the full path of a copy kept on this server, ready to paste (the folder is readable only with
        # sudo, so a shell can't complete the name)
        p = settings.data_dir / r["location"] if r.get("location") else None
        if p is not None and p.is_file():
            say(f"{'':<22} {'':>10}  {'':<17} {'':<16} {p}")
            first_path = first_path or p
        elif r.get("location"):
            say(f"{'':<22} {'':>10}  {'':<17} {'':<16} (was {r['location']}; no longer on this server)")
    say("Each of these can be restored with --use-server-key (only the file itself: a copy elsewhere is matched by its "
        "content).")
    if first_path is not None:
        say("The newest kept on this server, for example:")
        say(f"    {restore_command(settings, first_path)}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="pennywarden restore", description="Restore a PennyWarden backup (.fmbak)")
    p.add_argument("file", nargs="?", help="the backup file")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--use-server-key", action="store_true",
                   help="unlock a backup made on this server with recovery on (no passphrase needed)")
    g.add_argument("--passphrase-file", help=f"read the passphrase from a file (or set {PASSPHRASE_ENV})")
    p.add_argument("--data-dir")
    p.add_argument("--stop-service", action="store_true", help="stop the running service without asking")
    p.add_argument("--yes", action="store_true", help="answer yes to the questions")
    p.add_argument("--list", action="store_true",
                   help="without FILE: the backups this server can recover; with FILE: the parts it holds")
    g2 = p.add_mutually_exclusive_group()
    g2.add_argument("--only", help="restore only these parts: data, settings[.general|.backups|.payments|.donations], "
                                   "reminders, users (comma-separated)")
    g2.add_argument("--skip", help="restore everything except these parts")
    p.add_argument("--accept-testing-backup", action="store_true",
                   help="restore a backup made on a server in testing mode onto a server that isn't (2.2.0)")
    p.add_argument("--missing-users", choices=["add", "include-users"],
                   help="restored records referring to users that aren't here: add just those users from the backup "
                        "(default) or restore Users too")
    a = p.parse_args(argv)
    try:
        return restore(a)
    except CliError as e:
        print(str(e), file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        print("Stopped. Nothing was changed unless the output said otherwise.", file=sys.stderr)
        return 130


# ------------------------------------------------------------------ 2.0.0 (#125) pennywarden reinitialize
def reinitialize(args) -> int:
    """Offline reinitialize with the same safety backup as the web; no cooldown (a limit would only push owners to
    delete the data folder, which leaves no backup)."""
    from sqlalchemy import update

    from .config import load_settings
    from .db import make_engine, make_session_factory, upgrade_database
    from .models import AuthSession, TrustedDevice, utcnow
    from .services import bootstrap
    from .services import reinitialize as reinit

    settings = load_settings({"data_dir": args.data_dir})
    if needs_elevation(settings.data_dir):
        raise CliError("This needs administrator rights: run it again with sudo (Linux) or from a terminal opened "
                       "as Administrator (Windows). Nothing was changed.", 3)
    if not settings.database_path.is_file():
        raise CliError("No PennyWarden data was found in that folder.", 2)
    if not args.yes:
        if not sys.stdin.isatty():
            raise CliError("Confirm with --yes or run it in a terminal.", 2)
        say("This removes ALL financial data (Fiscal Years, budgets, entities, bank accounts, the register, "
            "attachments, fundraisers, Payments data) and keeps the users. A safety backup is made first.")
        if input(f'Type "{reinit.CONFIRM_WORD}" to continue: ').strip() != reinit.CONFIRM_WORD:
            raise CliError("Not confirmed. Nothing was changed.", 4)
    own = bool(args.passphrase_file or os.environ.get(PASSPHRASE_ENV))
    if own:
        args.use_server_key = False
        passphrase = read_passphrase(args, settings, Path(os.devnull))
        if len(passphrase) < 12:
            raise CliError("The backup passphrase must be at least 12 characters.", 2)
    else:
        passphrase = reinit.new_passphrase()
    stopped = False
    if in_container():
        say("Running in a container: stop the PennyWarden container first and run this in a one-off container on the "
            "same data volume (docs/backup-restore.md).")
    elif service_running():
        if not (args.stop_service or ask("The PennyWarden service is running. Stop it now? All signed-in users will "
                                         "be signed out.", args.yes)):
            raise CliError(f"Nothing was changed. {stop_instructions()}", 4)
        say("Stopping the service ...")
        stop_service()
        stopped = True
    elif app_answering(settings):
        raise CliError("PennyWarden is running on this data folder. Quit it first. Nothing was changed.", 4)
    upgrade_database(settings.database_url)
    say("Creating and checking the safety backup ...")
    try:
        safety = reinit.safety_backup(settings, passphrase, f"host:{os_user()}")
    except reinit.ReinitError as e:
        raise CliError(str(e), 6) from None
    say("Removing the financial data ...")
    engine = make_engine(settings.database_url)
    try:
        with make_session_factory(engine)() as s:
            ws = bootstrap.current_workspace(s)
            if ws is None:
                raise CliError("The data folder has no initialized organization.", 2)
            from types import SimpleNamespace
            ctx = SimpleNamespace(workspace_id=ws.id, correlation_id="host-cli", ip=None, user=None)
            try:
                before = reinit.counts(s, ws.id)
                reinit.wipe(s, ws.id, ctx, f"host:{os_user()}", safety["filename"], "host_cli", before)
                now = utcnow()
                s.execute(update(AuthSession).where(AuthSession.revoked_at.is_(None)).values(revoked_at=now))
                s.execute(update(TrustedDevice).where(TrustedDevice.revoked_at.is_(None)).values(revoked_at=now))
                s.commit()
            except Exception:
                s.rollback()
                raise CliError("The removal failed and was rolled back; the data is unchanged.", 6) from None
    finally:
        engine.dispose()
    reinit.remove_attachment_files(settings)
    match_ownership(settings.data_dir, ["database", "attachments", reinit.PRE_DIR, "backup-recovery", "server-key"])
    say("Reinitialized. The users are kept; everyone must sign in again.")
    say(f"Safety backup: {safety['path']}")
    say(f"To undo, run ({host_command(settings)[1]}; it stops the service first):")
    say(f"    {restore_command(settings, safety['path'])}")
    if stopped:
        if ask("Start the PennyWarden service again?", args.yes):
            say("Service started." if start_service() else "The service could not be started: start it yourself.")
    return 0


def reinit_main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="pennywarden reinitialize",
                                description="Remove all financial data, keep the users (a safety backup is made first)")
    p.add_argument("--data-dir")
    p.add_argument("--passphrase-file", help=f"your own passphrase for the safety backup (or set {PASSPHRASE_ENV}); "
                                             "otherwise a random one, recoverable by this server")
    p.add_argument("--stop-service", action="store_true")
    p.add_argument("--yes", action="store_true", help='skip typing "reinitialize" and answer yes to the questions')
    a = p.parse_args(argv)
    a.use_server_key = False
    try:
        return reinitialize(a)
    except CliError as e:
        print(str(e), file=sys.stderr)
        return e.code
