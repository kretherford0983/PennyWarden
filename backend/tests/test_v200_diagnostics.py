"""2.0.0 build 6 (#128): the sanitized diagnostics download."""
from __future__ import annotations

import json
import logging

from fmpoc.services import diagnostics


def download(client):
    return client.post("/api/system/diagnostics", {})


def test_diagnostics_contents(env, base):
    r = download(env.admin)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert 'filename="pennywarden-diagnostics-' in r.headers["content-disposition"]
    d = r.json()
    assert d["version"] and d["mode"] == "local" and d["system"]["python"]
    assert {"name", "value", "source"} <= set(d["settings"][0])
    st = d["storage"]
    assert st["database_bytes"] > 0 and st["disk"]["free"] > 0 and st["migrations"]["up_to_date"] is True
    assert st["migrations"]["current"] == st["migrations"]["head"]
    assert d["counts"]["users"] >= 5 and d["counts"]["active_sessions"] >= 1
    ev = env.admin.get("/api/audit-events?action=DIAGNOSTICS_DOWNLOADED").json()["items"][0]
    assert ev["category"] == "SECURITY" and ev["after"]["bytes"] == len(r.content)


def test_no_secrets_financial_values_or_identifiers(env, base):
    s = env.settings
    acct_number = base["acct"].get("account_number") or ""
    # log lines with a token, an amount, an account number, a password and an email
    log = logging.getLogger("fmpoc")
    token = env.ru.c.cookies.get("fm_session") or "x" * 43
    log.warning("debug token=%s paid $3,199.30 to acct 0001987654321 password=hunter2 jordan@example.org", token)
    log.warning("raw session %s amount 1,250.00 other 199.30", token)
    for h in log.handlers:
        h.flush()
    text = download(env.admin).text
    key = (s.secrets_dir).glob("*")
    for f in key:
        if f.is_file():
            raw = f.read_bytes()
            assert raw.decode("latin-1") not in text
    for secret in (token, "hunter2", "3,199.30", "1,250.00", "199.30", "0001987654321", "jordan@example.org",
                   env.ru.csrf, env.admin.csrf):
        assert secret not in text, secret
    for v in env.ru.c.cookies.values():
        assert v not in text
    if acct_number:
        assert acct_number not in text
    assert "[AMOUNT]" in text and "[REDACTED]" in text and "[EMAIL]" in text
    # the home folder is shortened
    from pathlib import Path
    home = str(Path.home())
    if home not in ("/", ""):
        assert home not in text


def test_scrub_keeps_ordinary_log_lines():
    line = "2026-10-12 21:15:03,123 INFO fmpoc GET /api/checks/transactions/47/options 200 15.3ms cid=87d4953c38674036"
    assert diagnostics.scrub(line) == line
    assert diagnostics.scrub("from 192.168.1.10") == "from 192.168.1.10"


def test_bounded_log_lines(env):
    log = logging.getLogger("fmpoc")
    for i in range(1200):
        log.info("line %d", i)
    for h in log.handlers:
        h.flush()
    lines = download(env.admin).json()["log"]["lines"]
    assert len(lines) == 1000 and lines[-1].endswith("line 1199")


def test_only_administrators(env):
    for c in (env.auditor, env.ru, env.bm, env.bu):
        assert download(c).status_code == 403
    assert env.admin.c.post("/api/system/diagnostics", json={}).status_code == 403     # CSRF
    assert env.admin.get("/api/system/diagnostics").status_code in (404, 405)
