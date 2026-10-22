"""2.1.0 (#272): the private test data set (scripts/demo_data.py --profile test): built through the API of a real,
running PennyWarden, credentials only from the environment and never printed, an encrypted backup that restores into a
server-mode installation where the test users sign in and are asked to enroll two-step verification."""
from __future__ import annotations

import datetime as dt
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import test_data as td  # noqa: E402

PASSWORD = "Synthetic-Only-" + "Pw-4821!"          # made up for this test; never a real credential
PASSPHRASE = "synthetic only " + "test backup passphrase"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(data: Path, *extra: str) -> tuple[subprocess.Popen, str, Path]:
    port = free_port()
    log = data.parent / f"{data.name}-server.log"
    proc = subprocess.Popen([sys.executable, "-m", "fmpoc", "--no-browser", "--port", str(port), "--data-dir", str(data),
                             *extra], cwd=ROOT / "backend", stdout=open(log, "w"), stderr=subprocess.STDOUT,
                            env={**os.environ, "FM_LOGIN_MAX_FAILURES": "50"})
    url = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            if httpx.get(f"{url}/api/system/status", timeout=2).status_code == 200:
                return proc, url, log
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    proc.kill()
    raise RuntimeError("server did not start: " + log.read_text()[-2000:])


def login(url: str, user: str, password: str = PASSWORD) -> httpx.Response:
    c = httpx.Client(base_url=url)
    csrf = c.get("/api/auth/csrf").json()["csrf_token"]
    return c.post("/api/auth/login", json={"username": user, "password": password}, headers={"X-CSRF-Token": csrf})


def test_fiscal_years_follow_the_start_month():
    july = td.fiscal_years(dt.date(2026, 10, 21), 7)
    assert [(f.label, f.start.isoformat(), f.end.isoformat()) for f in july] == [
        ("2025", "2024-07-01", "2025-06-30"), ("2026", "2025-07-01", "2026-06-30"),
        ("2027", "2026-07-01", "2027-06-30"), ("2028", "2027-07-01", "2028-06-30")]
    assert td.fiscal_years(dt.date(2026, 3, 5), 7)[2].label == "2026"           # before July: the year ending in June
    jan = td.fiscal_years(dt.date(2026, 10, 21), 1)
    assert [(f.label, f.start.isoformat(), f.end.isoformat()) for f in jan][2] == ("2026", "2026-01-01", "2026-12-31")
    assert td.fiscal_years(dt.date(2026, 10, 21), 7)[2].date(11, 31) == dt.date(2027, 6, 28)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("testdata")
    proc, url, log = serve(tmp / "data")
    env = {**os.environ, "PW_TESTDATA_PASSWORD": PASSWORD, "PW_TESTDATA_PASSPHRASE": PASSPHRASE}
    try:
        # without the password variable: refused before anything is created
        r = subprocess.run([sys.executable, str(ROOT / "scripts/demo_data.py"), "--profile", "test", url],
                           env={k: v for k, v in env.items() if not k.startswith("PW_TESTDATA")},
                           capture_output=True, text=True)
        assert r.returncode != 0 and "PW_TESTDATA_PASSWORD is not set" in r.stderr
        assert httpx.get(f"{url}/api/system/status").json()["initialized"] is False
        run = subprocess.run([sys.executable, str(ROOT / "scripts/demo_data.py"), "--profile", "test",
                              "--backup", str(tmp / "test.fmbak"), "--summary", str(tmp / "summary.json"), url],
                             env=env, capture_output=True, text=True, timeout=900)
        assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
        # a second run is refused: the installation is initialized now
        again = subprocess.run([sys.executable, str(ROOT / "scripts/demo_data.py"), "--profile", "test", url],
                               env=env, capture_output=True, text=True)
        assert again.returncode != 0 and "already initialized" in again.stderr
        yield {"tmp": tmp, "url": url, "run": run, "again": again, "log": log}
    finally:
        proc.terminate()
        proc.wait(10)


def test_data_set(built):
    import json
    s = json.loads((built["tmp"] / "summary.json").read_text())
    assert s["sign_ins"] == ["admin", "budgetmgr", "bookkeeper", "auditor", "treasurer"]
    assert [y["status"] for y in s["fiscal_years"]] == ["Closed", "Closed", "Approved", "Draft"]
    assert s["counts"]["printed_checks"] == 2 and s["counts"]["entered_years"] == 12
    assert s["counts"]["fundraisers"] >= 10 and s["counts"]["electronic_payments"] > 0
    db = sqlite3.connect(built["tmp"] / "data/database/fmpoc.sqlite3")
    q = lambda sql: db.execute(sql).fetchall()  # noqa: E731
    assert q("SELECT status, COUNT(*) FROM register_transaction WHERE status != 'ACTIVE' GROUP BY status ORDER BY 1") \
        == [("DELETED", 1), ("VOID", 1)]
    # every budget of the Draft next year (and of the years after the first) continues last year's
    rows = q("SELECT f.status, SUM(b.continues_budget_id IS NOT NULL) FROM budget b JOIN fiscal_year f "
             "ON f.id = b.fiscal_year_id WHERE b.system_managed = 0 AND b.is_other = 0 AND b.is_budget_zero = 0 "
             "GROUP BY f.id ORDER BY f.start_date")
    assert [r[1] for r in rows] == [0, len(td.BUDGETS), len(td.BUDGETS), len(td.BUDGETS)]
    series = {n: c for n, c in q("SELECT s.name, COUNT(r.id) FROM fundraiser_series s LEFT JOIN fundraiser_series_result r "
                                  "ON r.series_id = s.id WHERE s.merged_into_id IS NULL GROUP BY s.id")}
    assert series == {"Golf Outing": 4, "Holiday Raffle": 4, "Pancake Breakfast": 4}
    assert q("SELECT COUNT(*) FROM fundraiser WHERE cancelled_at IS NOT NULL") == [(1,)]
    # nothing real: the organization and sign-ins are the invented ones
    assert q("SELECT name FROM workspace") == [(td.ORG,)]


def test_no_secret_is_printed_or_logged(built):
    for text in (built["run"].stdout, built["run"].stderr, built["again"].stdout, built["again"].stderr,
                 built["log"].read_text(), (built["tmp"] / "summary.json").read_text()):
        assert PASSWORD not in text and PASSPHRASE not in text
    for f in (built["tmp"] / "data/logs").rglob("*"):
        if f.is_file():
            data = f.read_bytes()
            assert PASSWORD.encode() not in data and PASSPHRASE.encode() not in data
    assert PASSWORD.encode() not in (built["tmp"] / "test.fmbak").read_bytes()      # encrypted


def test_backup_restores_into_a_server_and_asks_for_two_step_enrollment(built):
    tmp = built["tmp"]
    pp = tmp / "pp.txt"
    pp.write_text(PASSPHRASE)
    pp.chmod(0o600)
    r = subprocess.run([sys.executable, "-m", "fmpoc", "restore", str(tmp / "test.fmbak"), "--passphrase-file", str(pp),
                        "--data-dir", str(tmp / "restored"), "--yes"], cwd=ROOT / "backend",
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Restore complete." in r.stdout and PASSPHRASE not in r.stdout + r.stderr
    proc, url, _log = serve(tmp / "restored", "--mode", "server", "--host", "127.0.0.1")
    try:
        assert httpx.get(f"{url}/api/system/status").json()["workspace_name"] == td.ORG
        for user in ("admin", "budgetmgr", "bookkeeper", "auditor", "treasurer"):
            r = login(url, user)
            assert r.status_code == 200 and r.json()["mfa_pending"] == "ENROLL", (user, r.text)
        assert login(url, "treasurer", "not-the-password").status_code != 200
    finally:
        proc.terminate()
        proc.wait(10)
