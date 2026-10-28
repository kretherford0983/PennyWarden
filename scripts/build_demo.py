#!/usr/bin/env python3
"""2.2.0 (#243): builds the published demo - `pennywarden-demo-<version>.fmbak` and its SHA-256.

    python scripts/build_demo.py --out release/pennywarden-demo-2.2.0.fmbak

1. Starts a brand-new PennyWarden (this checkout, local mode, loopback, a temporary data folder).
2. Fills it with the synthetic demo organization through the normal web API (scripts/demo_data.py): the current Fiscal
   Year is the build year, the year before is closed (Kyle, 2026-10-24: no date shifting - a fresh demo per release).
3. Sets the demo marker (workspace.demo_mode) directly in the database file. This script is the only thing that sets
   it: no web or API path does.
4. Makes a normal encrypted backup through the backup API with the published passphrase, and writes
   `<file>.sha256`.

Everything in the demo is made up. The sign-in password (scripts/demo_data.py PASSWORD) and the passphrase below are
published with the demo on pennywarden.org - by design: the demo runs only on the evaluator's own computer.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import demo_data  # noqa: E402

PASSPHRASE = "pennywarden demo"     # published with the demo (synthetic data only)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_up(base: str, proc) -> None:
    import httpx
    for _ in range(240):
        if proc.poll() is not None:
            raise SystemExit("PennyWarden stopped while starting.")
        try:
            if httpx.get(base + "/api/health", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit("PennyWarden did not start.")


def mark_demo(db_path: Path) -> None:
    con = sqlite3.connect(db_path)
    try:
        n = con.execute("UPDATE workspace SET demo_mode = 1 WHERE bootstrap_completed_at IS NOT NULL").rowcount
        con.commit()
    finally:
        con.close()
    if n != 1:
        raise SystemExit("Could not set the demo marker.")


def backup(base: str, out: Path) -> None:
    admin = demo_data.Api(base).login(demo_data.ADMIN)
    job = admin.call("POST", "/api/system/backups", {"password": demo_data.PASSWORD, "passphrase": PASSPHRASE,
                                                     "passphrase_confirmation": PASSPHRASE, "recoverable": False},
                     ok=(202,))
    for _ in range(600):
        job = admin.get(f"/api/system/backups/{job['id']}")
        if job["state"] in ("done", "failed"):
            break
        time.sleep(0.5)
    if job["state"] != "done":
        raise SystemExit(f"The backup failed: {job.get('error')}")
    r = admin.c.get(f"/api/system/backups/{job['id']}/download")
    r.raise_for_status()
    out.write_bytes(r.content)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the published PennyWarden demo backup")
    ap.add_argument("--out", required=True, help="the .fmbak file to write")
    ap.add_argument("--python", default=sys.executable, help="the Python that runs PennyWarden")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pw-demo-") as tmp:
        data = Path(tmp) / "data"
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = {**os.environ, "FM_LOGIN_MAX_FAILURES": "50", "FM_UPDATE_CHANNEL": "off"}
        env.pop("FM_TESTING_MODE", None)
        proc = subprocess.Popen([a.python, "-m", "fmpoc", "--no-browser", "--port", str(port), "--data-dir",
                                 str(data)], cwd=ROOT / "backend", env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_up(base, proc)
            summary = demo_data.main(base)
            demo_data.Api(base).login("demo-auditor")       # security questions done for every published sign-in
            mark_demo(data / "database" / "fmpoc.sqlite3")
            backup(base, out)
        finally:
            proc.terminate()
            try:
                proc.wait(20)
            except subprocess.TimeoutExpired:   # pragma: no cover
                proc.kill()
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    Path(str(out) + ".sha256").write_text(f"{digest}  {out.name}\n", encoding="utf-8")
    print(f"Demo backup: {out} ({out.stat().st_size:,} bytes), SHA-256 {digest}")
    print(f"Organization: {summary['organization']}; Fiscal Years {summary['fiscal_years']}; "
          f"sign-ins {', '.join(summary['sign_ins'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
