"""2.2.0 (#243): the downloadable demo.

The demo is a PennyWarden backup (``pennywarden-demo-<version>.fmbak``, built by ``scripts/build_demo.py`` and attached
to each release) restored on the first screen of a new local install. Decisions (Kyle, 2026-10-15 and 2026-10-24):

* The demo database carries ``workspace.demo_mode``. Only the build script sets it, directly in the database file;
  nothing in the web or API writes it.
* **Local loopback only**: with the marker, the application refuses server mode or a non-loopback address (the
  passwords and the key are published).
* **Nothing is kept**: the restore keeps an untouched copy in ``demo-pristine/``; it is put back on every start and
  by *Reset demo data* (on the banner and on the sign-in page, so a locked-out evaluator can always recover).
* **Remove the demo** (the demo Administrator, or ``pennywarden remove-demo``): removes the database, attachments,
  the published key and ``demo-pristine/``; ``config.toml`` stays; no safety copy and no cooldown; the next screen is
  the Initialization Wizard, which makes a new key. Nothing of the demo remains.
* Reset and Remove replace or discard a disposable demo installation; neither edits an audit event (confirmed
  2026-10-24). A real workspace is never affected: without the marker these actions don't exist.
* Restoring a backup over the demo is always a full restore; a non-demo backup leaves demo mode.
* Scheduled backups and the update check are off in demo mode.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from pathlib import Path

log = logging.getLogger("fmpoc")

PRISTINE = "demo-pristine"
PARTS = ("database", "attachments", "secrets")
LOOPBACK_ONLY = ("This is the PennyWarden demo: its passwords and encryption key are published, so it runs only on "
                 "this computer (local mode, 127.0.0.1). Start it without --mode server and without a network "
                 "address, or remove the demo (pennywarden remove-demo) to start fresh.")


class DemoError(Exception):
    pass


def is_demo_db(db_path: Path) -> bool:
    """Reads the marker straight from a database file (current or restored), without the application."""
    if not db_path.is_file():
        return False
    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            cols = [r[1] for r in con.execute("PRAGMA table_info(workspace)")]
            if "demo_mode" not in cols:
                return False
            r = con.execute("SELECT demo_mode FROM workspace WHERE bootstrap_completed_at IS NOT NULL "
                            "ORDER BY id LIMIT 1").fetchone()
            return bool(r and r[0])
        finally:
            con.close()
    except sqlite3.Error:
        return False


def pristine_dir(settings) -> Path:
    return settings.data_dir / PRISTINE


def _copy_parts(src_root: Path, dst_root: Path) -> None:
    for part in PARTS:
        src, dst = src_root / part, dst_root / part
        if dst.exists():
            shutil.rmtree(dst)
        if src.exists():
            shutil.copytree(src, dst)
        else:
            dst.mkdir(parents=True)
    try:
        os.chmod(dst_root / "secrets", 0o700)
    except OSError:  # pragma: no cover - Windows ACLs
        pass


def keep_pristine(settings) -> None:
    """After a demo backup was restored: keep an untouched copy to go back to. After a non-demo restore: none."""
    p = pristine_dir(settings)
    if p.exists():
        shutil.rmtree(p)
    if is_demo_db(settings.database_path):
        p.mkdir()
        _copy_parts(settings.data_dir, p)
        (p / "README.txt").write_text("The PennyWarden demo as it was restored. It is put back on every start and by "
                                      "Reset demo data. Remove the demo to start fresh.\n", encoding="utf-8")
        log.info("demo: pristine copy kept")


def reset_files(settings) -> bool:
    """Puts the pristine demo back (the application must not have the database open). Returns True when it did."""
    p = pristine_dir(settings)
    if not (p / "database").is_dir():
        return False
    _copy_parts(p, settings.data_dir)
    log.info("demo: data reset to the pristine copy")
    return True


def at_start(settings) -> bool:
    """create_app, before the database is opened: a demo installation starts from the pristine copy, and only on
    loopback. Returns whether this is a demo."""
    from ..config import is_loopback
    if pristine_dir(settings).is_dir() and not is_demo_db(pristine_dir(settings) / "database" / "fmpoc.sqlite3"):
        shutil.rmtree(pristine_dir(settings), ignore_errors=True)   # left over from a demo that was replaced
    demo = is_demo_db(settings.database_path) or (pristine_dir(settings) / "database").is_dir()
    if not demo:
        return False
    if settings.mode == "server" or not is_loopback(settings.host):
        raise DemoError(LOOPBACK_ONLY)
    if not reset_files(settings):     # restored before 2.2.0's restore kept a copy (e.g. by hand): keep one now
        keep_pristine(settings)
    return True


def remove_files(settings) -> None:
    """Remove the demo: database, attachments, key and the pristine copy. config.toml, logs and reports stay."""
    for part in (*PARTS, PRISTINE):
        d = settings.data_dir / part
        if d.exists():
            shutil.rmtree(d)
    settings.ensure_dirs()
    log.info("demo: removed - the next start shows the Initialization Wizard")


def remove_cli(argv: list[str]) -> int:
    """pennywarden remove-demo [--data-dir DIR] [--yes]"""
    import argparse

    from ..config import load_settings
    p = argparse.ArgumentParser(prog="pennywarden remove-demo",
                                description="Remove the PennyWarden demo and start fresh (Initialization Wizard)")
    p.add_argument("--data-dir")
    p.add_argument("--yes", action="store_true", help="don't ask")
    a = p.parse_args(argv)
    settings = load_settings({"data_dir": a.data_dir})
    if not (is_demo_db(settings.database_path) or (pristine_dir(settings) / "database").is_dir()):
        print("This installation is not the demo; nothing was removed.")
        return 1
    if not a.yes:
        try:
            ok = input("Remove the demo (its data, users and key) and start fresh? [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:
            ok = False
        if not ok:
            print("Nothing was removed.")
            return 4
    remove_files(settings)
    print("The demo was removed. Start PennyWarden to set up your own organization.")
    return 0
