"""2.6.0 (#610): the user guide's Roles and responsibilities page stays in step with what the server enforces.

- every role (permissions.ROLE_DEFS) has its own subsection, so a new role can't ship undocumented;
- the "Who can do what" table matches permissions.PERMISSIONS tick for tick;
- the error quoted for mixing security domains on a server is the one the server returns (BR-002; local installs
  allow combined roles, #54).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fmpoc import permissions as perms

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "guide"
PAGE = GUIDE / "users" / "roles-and-responsibilities.md"

# table row -> the permission it describes (one row per task; the page words them for people)
ROWS = {"Manage users and roles": "users.manage", "See the list of users": "users.view",
        "Read the Audit Log": "audit.view", "See the financial values in Audit Log entries": "audit.view_financial_snapshots",
        "Change System/About settings, backups and sessions": "system.manage",
        "Turn optional modules on or off": "modules.manage",
        "Set up checks, donation receipts, invoices and email (test prints only)": "checks.setup",
        "See budgets, Fiscal Years and the reports": "financial.view", "See the Register": "register.view",
        "Create, approve and close Fiscal Years": "fiscal_year.manage", "Create and change budgets": "budget.manage",
        "Delete a budget of a Fiscal Year not yet approved": "budget.delete",
        "Change a non-register balance in a Closed year": "bank_account.closed_year",
        "Manage bank accounts and see full account numbers": "bank_account.manage",
        "Enter, edit and void transactions": "transaction.manage",
        "Delete a transaction that hasn't cleared": "transaction.delete", "Add and edit entities": "entity.manage",
        "Resolve Fiscal Year review items": "review.resolve", "Create and manage events": "fundraiser.manage",
        "Assign event lines to buckets": "fundraiser.lines", "Create organization reminders": "reminder.org_manage",
        "Print checks and make payments": "checks.print", "Print donation receipts": "donation.print",
        "Create and send invoices": "invoice.manage", "Keep the product catalog": "invoice.catalog_manage",
        "Record invoice payments and refunds": "invoice.record_payment",
        "Link an existing deposit to an invoice": "invoice.link_payment",
        "Approve or reject invoice write-offs": "invoice.write_off_decide"}


def _table() -> tuple[list[str], dict[str, list[bool]]]:
    lines = PAGE.read_text("utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("| Task |"))
    head = [c.strip() for c in lines[start].strip("|").split("|")][1:]
    rows = {}
    for ln in lines[start + 2:]:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) != len(head) + 1:
            break
        rows[cells[0]] = [c == "✓" for c in cells[1:]]
    return head, rows


def test_every_role_has_a_subsection():
    text = PAGE.read_text("utf-8")
    for _code, name, _domain in perms.ROLE_DEFS:
        assert re.search(rf"^### {re.escape(name)}\b", text, re.M), f"no subsection for {name}"


def test_who_can_do_what_matches_the_permissions():
    names = {n: c for c, n, _d in perms.ROLE_DEFS}
    head, rows = _table()
    assert sorted(head) == sorted(names), "the table needs one column per role"
    assert set(rows) == set(ROWS), "table rows and the test's mapping differ"
    for label, ticks in rows.items():
        allowed = perms.PERMISSIONS[ROWS[label]]
        for name, tick in zip(head, ticks):
            assert tick == (names[name] in allowed), f"{label} / {name}"
    # the setup row stands for every Administrator-only setup permission
    for p in ("donation.setup", "invoice.setup", "email.setup"):
        assert perms.PERMISSIONS[p] == perms.PERMISSIONS["checks.setup"]


def test_domain_rules_quoted_as_the_server_enforces_them():
    text = PAGE.read_text("utf-8").replace("\n", " ")
    msg = perms.validate_role_set("ADMINISTRATOR", {perms.ADMINISTRATOR, perms.BUDGET_MANAGER}, "server")
    assert msg and msg.replace("\n", " ") in text
    assert perms.validate_role_set(perms.COMBINED, {perms.ADMINISTRATOR, perms.BUDGET_MANAGER}, "local") is None
    assert perms.validate_role_set("FINANCIAL", {perms.BUDGET_MANAGER, perms.REGISTER_USER}, "server") is None
    assert "Combined" in text and "Local-only roles" in text
    assert perms.BUDGET_USER not in perms.LOCAL_FIRST_USER_ROLES and "every role except Budget User" in text


def test_page_is_in_the_guide_and_linked():
    g = json.loads((GUIDE / "guide.json").read_text("utf-8"))
    users = next(c for c in g["chapters"] if c["id"] == "users") if "chapters" in g else next(
        c for c in g if c["id"] == "users")
    assert any(p["id"] == "roles-and-responsibilities" for p in users["pages"])
    for f in ("users/manage-users.md", "getting-started/who-does-what.md"):
        assert "roles-and-responsibilities.md" in (GUIDE / f).read_text("utf-8")
