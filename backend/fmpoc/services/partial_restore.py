"""2.2.0 (#319): restore - choose what to restore.

A backup holds four domains (Kyle, 2026-10-22/24):

* **data** - Fiscal Years, budgets, entities, bank accounts, the register and attachments, Payments records (printed
  checks, each account's check style and sheet counter), Fundraisers and Donations. **Never split**: the records refer
  to each other, so Data is restored or kept as one unit, attachments included.
* **settings** - in sections: ``settings.general`` (the organization profile and name, optional modules, the audit
  review signature wording), ``settings.backups`` (backup reminder, scheduled backups and their history),
  ``settings.payments`` (check styles, signers, letter and envelope templates), ``settings.donations``,
  ``settings.branding`` (2.2.0, #280).
* **reminders** - organization and personal reminders.
* **users** - users, roles, passwords, two-step verification, security questions and notices, personal preferences,
  each user's printer settings.

Everything chosen is a full restore exactly as before (the files are swapped in, the audit log is the backup's). A
partial restore builds the result instead: a copy of the current database where the chosen domains are replaced by
the backup's (migrated to this version first, in the work folder), in one SQLite transaction, then swapped in like a
full restore (safety copy in pre-restore/, rollback on failure):

* the current **audit log is kept** (it is a superset of the backup's); one SYSTEM_RESTORED event lists what was
  restored (decision, point 1);
* the **backup's encryption key is always installed**; values kept from the current installation (bank account
  numbers and fingerprints, two-step secrets, signature images) are re-encrypted with it when the keys differ (2);
* **users restored, data not**: current users missing from the backup are kept, inactivated and reported (4);
* **records referring to users that aren't there** (data or reminders from a later backup than the users): the
  restore lists them before anything changes; the restorer includes Users, or adds just those users from the backup
  (the default - it never blocks) (4a);
* **data without settings.general**: the organization entity comes back with the data, its profile is put back to
  the current settings; a bank account's check style is kept if that style exists, otherwise cleared (5);
* **reminder links** to records that aren't there are cleared (6); a restored Backups section that names folders this
  server doesn't allow is reported (7a).
"""
from __future__ import annotations

import re
import shutil
import sqlite3
from pathlib import Path

from ..security import crypto

DATA_TABLES = (
    "fiscal_year", "budget", "former_budget", "budget_history_entry", "budget_inclusion", "budget_projection_choice", "entity", "bank_account",
    "bank_account_balance", "fiscal_year_balance_change", "register_transaction", "transaction_allocation", "fiscal_year_review", "attachment",
    "check_number_acknowledgement", "request_key", "check_account",
    "fundraiser", "fundraiser_budget", "fundraiser_series", "fundraiser_series_result", "fundraiser_fy_report_note",
    "fundraiser_bucket_category", "fundraiser_bucket", "fundraiser_exclusion", "fundraiser_classification",
    "fundraiser_line_contributor", "fundraiser_bucket_line",
    "donation", "donation_line", "donation_detail", "donation_receipt", "donation_statement",
)
SETTINGS_SECTIONS = {
    "settings.general": {"tables": ("signature_template", "report_grouping"),     # 2.3.0 (#376): report grouping
                         "workspace": ("name", "fundraisers_enabled", "checks_enabled", "donations_enabled", "invoices_enabled"),
                         "label": "General (organization profile, optional modules)"},
    "settings.backups": {"tables": ("backup_schedule", "backup_run"), "workspace": ("backup_warning_days",),
                         "label": "Backups (backup reminder, scheduled backups)"},
    "settings.payments": {"tables": ("check_style", "check_signer", "check_document"), "workspace": (),
                          "label": "Payments Setup (check styles, signers, letters and envelopes)"},
    "settings.donations": {"tables": ("donation_settings",), "workspace": (), "label": "Donations Setup"},
    # 2.2.0 (#280)
    "settings.branding": {"tables": ("branding_settings",), "workspace": (),
                          "label": "Branding (report and presentation colors, logos, footer text)"},
}
REMINDER_TABLES = ("reminder",)
USER_TABLES = ("app_user", "user_role", "user_mfa", "mfa_recovery_code", "user_security_question", "security_notice",
               "check_printer_setting", "trusted_device")
# never copied from a backup in a partial restore: seed data, live state, the append-only log
KEPT_TABLES = ("workspace", "role", "auth_session", "update_check", "audit_event", "alembic_version", "testing_state")
DATA_WORKSPACE_COLUMNS = ("next_entity_number",)

DOMAINS = ("data", *SETTINGS_SECTIONS, "reminders", "users")
LABELS = {"data": "Data (Fiscal Years, budgets, entities, bank accounts, the register and attachments, Payments "
                  "records, Fundraisers, Donations)",
          **{k: v["label"] for k, v in SETTINGS_SECTIONS.items()},
          "reminders": "Reminders (organization and personal)",
          "users": "Users (passwords, two-step verification, security questions, preferences, printer settings)"}

USER_ID_COLUMN = re.compile(r"(^|_)user_id$")
LINK_TABLES = {"FISCAL_YEAR": "fiscal_year", "BUDGET": "budget", "BANK_ACCOUNT": "bank_account"}
ORG_PROFILE = ("organization_name", "address_line1", "address_line2", "city", "state_region", "postal_code", "country",
               "phone", "email", "ein")
MFA_AAD = b"fmpoc:totp_secret:v1"


class RestoreChoiceError(ValueError):
    pass


# ------------------------------------------------------------------ choices
def parse_names(text: str | None) -> list[str]:
    """'data,settings.payments' -> names; 'settings' means every Settings section. Unknown names are refused."""
    out: list[str] = []
    for raw in (text or "").split(","):
        n = raw.strip().lower()
        if not n:
            continue
        if n == "all":
            out += list(DOMAINS)
        elif n == "settings":
            out += list(SETTINGS_SECTIONS)
        elif n in DOMAINS:
            out.append(n)
        elif n.startswith("data."):
            raise RestoreChoiceError("Data is never split: restore or keep it as a whole (use 'data').")
        else:
            raise RestoreChoiceError(f"Unknown part '{raw.strip()}'. Use: data, settings (or "
                                     + ", ".join(SETTINGS_SECTIONS) + "), reminders, users.")
    return [d for d in DOMAINS if d in set(out)]


def normalize(chosen) -> list[str]:
    names = parse_names(",".join(chosen or []))
    if not names:
        raise RestoreChoiceError("Choose at least one part to restore.")
    return names


def is_full(chosen: list[str]) -> bool:
    return set(chosen) == set(DOMAINS)


def summary(chosen: list[str]) -> dict:
    return {"restored": [{"name": d, "label": LABELS[d]} for d in DOMAINS if d in chosen],
            "kept": [{"name": d, "label": LABELS[d]} for d in DOMAINS if d not in chosen]}


# ------------------------------------------------------------------ what a backup holds
def _count(con, table: str) -> int:
    try:
        return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]   # noqa: S608 - fixed names
    except sqlite3.Error:
        return 0


def domains_in(db_path: Path) -> list[dict]:
    """The domains of a (migrated) backup database with counts only - never financial content (BR-003)."""
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        counts = {
            "data": {"fiscal_years": _count(con, "fiscal_year"), "budgets": _count(con, "budget"),
                     "entities": _count(con, "entity"), "bank_accounts": _count(con, "bank_account"),
                     "transactions": _count(con, "register_transaction"), "attachments": _count(con, "attachment"),
                     "fundraisers": _count(con, "fundraiser")},
            "settings.general": {"signature_wordings": _count(con, "signature_template")},
            "settings.backups": {"schedules": _count(con, "backup_schedule"), "runs": _count(con, "backup_run")},
            "settings.payments": {"check_styles": _count(con, "check_style"), "signers": _count(con, "check_signer"),
                                  "letters_and_envelopes": _count(con, "check_document")},
            "settings.donations": {"settings": _count(con, "donation_settings")},
            "settings.branding": {"settings": _count(con, "branding_settings")},   # 2.2.0 (#280)
            "reminders": {"reminders": _count(con, "reminder")},
            "users": {"users": _count(con, "app_user")},
        }
    finally:
        con.close()
    return [{"name": d, "label": LABELS[d], "counts": counts[d]} for d in DOMAINS]


# ------------------------------------------------------------------ helpers
def _cols(con, schema: str, table: str) -> list[str]:
    return [r[1] for r in con.execute(f'PRAGMA {schema}.table_info("{table}")')]


def _notnull(con, table: str) -> dict[str, bool]:
    return {r[1]: bool(r[3]) for r in con.execute(f'PRAGMA main.table_info("{table}")')}


def _ws_ids(con) -> tuple[int, int]:
    cur = con.execute("SELECT id FROM main.workspace WHERE bootstrap_completed_at IS NOT NULL ORDER BY id LIMIT 1")
    bk = con.execute("SELECT id FROM bk.workspace WHERE bootstrap_completed_at IS NOT NULL ORDER BY id LIMIT 1")
    a, b = cur.fetchone(), bk.fetchone()
    if a is None or b is None:
        raise RestoreChoiceError("Both the current installation and the backup must hold an initialized organization.")
    return a[0], b[0]


def _replace(con, table: str, ws_id: int, where: str = "") -> int:
    """Replaces main.table by bk.table (same schema after the migration); workspace_id becomes the current one."""
    cols = _cols(con, "main", table)
    bcols = set(_cols(con, "bk", table))
    sel = []
    for c in cols:
        if c == "workspace_id":
            sel.append(f"{int(ws_id)}")
        elif c in bcols:
            sel.append(f'"{c}"')
        else:
            sel.append("NULL")
    con.execute(f'DELETE FROM main."{table}"')   # noqa: S608 - fixed names
    cur = con.execute(f'INSERT INTO main."{table}" ({", ".join(chr(34) + c + chr(34) for c in cols)}) '
                      f'SELECT {", ".join(sel)} FROM bk."{table}" {where}')
    return cur.rowcount or 0


def _user_ref_columns(con, tables) -> list[tuple[str, str]]:
    out = []
    for t in tables:
        for c in _cols(con, "main", t):
            if USER_ID_COLUMN.search(c):
                out.append((t, c))
    return out


def _referenced_users(con, tables, schema: str = "main") -> set[int]:
    ids: set[int] = set()
    for t, c in _user_ref_columns(con, tables):
        for (v,) in con.execute(f'SELECT DISTINCT "{c}" FROM {schema}."{t}" WHERE "{c}" IS NOT NULL'):
            ids.add(int(v))
    return ids


# ------------------------------------------------------------------ the check before anything changes (4a)
def check(current_db: Path, backup_db: Path, chosen: list[str]) -> dict:
    """Before anything changes: the users that the restored records refer to but that the result wouldn't have, and
    host-specific settings. Read-only."""
    con = sqlite3.connect(f"file:{current_db.as_posix()}?mode=ro", uri=True)
    try:
        con.execute(f"ATTACH DATABASE 'file:{backup_db.as_posix()}?mode=ro' AS bk")
        return _check(con, chosen)
    finally:
        con.close()


def _check(con, chosen: list[str]) -> dict:
    users_from = "bk" if "users" in chosen else "main"
    have = {r[0] for r in con.execute(f"SELECT id FROM {users_from}.app_user")}
    if "users" in chosen:   # current users missing from the backup are kept (inactivated)
        have |= {r[0] for r in con.execute("SELECT id FROM main.app_user")}
    refs: set[int] = set()
    restored_tables = []
    if "data" in chosen:
        restored_tables += [t for t in DATA_TABLES if t != "budget_projection_choice"]
    if "reminders" in chosen:
        restored_tables += list(REMINDER_TABLES)
    for name, sec in SETTINGS_SECTIONS.items():
        if name in chosen:
            restored_tables += list(sec["tables"])
    if users_from == "main":
        refs = _referenced_users(con, restored_tables, "bk")
    missing = sorted(refs - have)
    names = {r[0]: r[1] for r in con.execute("SELECT id, username FROM bk.app_user")}
    in_backup = [i for i in missing if i in names]
    # a different person under the same user id (a backup from another installation)
    clash = []
    if users_from == "main":
        cur = {r[0]: (r[1] or "").lower() for r in con.execute("SELECT id, username_normalized FROM main.app_user")}
        for i in sorted(refs & set(cur)):
            if i in names and (names[i] or "").lower() != cur[i]:
                clash.append({"id": i, "backup_username": names[i], "current_username": cur[i]})
    hosts = []
    if "settings.backups" in chosen:
        for (folder,) in con.execute("SELECT destination FROM bk.backup_schedule WHERE destination IS NOT NULL"):
            # (7a) a folder of the old server: reported; the scheduled backup shows as failing until it is fixed
            hosts.append({"setting": "scheduled backups folder", "value": folder, "exists": Path(folder).is_dir()})
    return {"missing_users": [{"id": i, "username": names[i]} for i in in_backup],
            "missing_users_not_in_backup": [i for i in missing if i not in names],
            "user_id_clashes": clash, "host_settings": hosts}


# ------------------------------------------------------------------ re-encryption (point 2)
def _reencrypt(con, old: crypto.KeyMaterial, new: crypto.KeyMaterial, tables: set[str]) -> dict:
    """Re-encrypts the encrypted values of `tables` in main (they came from the current installation) with the
    backup's key."""
    from .checkprint.service import SIGNATURE_AAD
    n = {"bank_accounts": 0, "two_step": 0, "signatures": 0}
    if "bank_account" in tables:
        for rid, ct in con.execute("SELECT id, account_number_ciphertext FROM main.bank_account").fetchall():
            if not ct:
                continue
            plain = crypto.decrypt(old, ct)
            con.execute("UPDATE main.bank_account SET account_number_ciphertext = ?, account_number_fingerprint = ? "
                        "WHERE id = ?", (crypto.encrypt(new, plain), crypto.fingerprint(new, plain), rid))
            n["bank_accounts"] += 1
    if "user_mfa" in tables:
        for rid, s, p in con.execute("SELECT id, secret_enc, pending_secret_enc FROM main.user_mfa").fetchall():
            con.execute("UPDATE main.user_mfa SET secret_enc = ?, pending_secret_enc = ? WHERE id = ?",
                        (crypto.encrypt(new, crypto.decrypt(old, s, MFA_AAD), MFA_AAD) if s else None,
                         crypto.encrypt(new, crypto.decrypt(old, p, MFA_AAD), MFA_AAD) if p else None, rid))
            n["two_step"] += 1
    if "check_signer" in tables:
        for rid, ct in con.execute("SELECT id, image_ciphertext FROM main.check_signer").fetchall():
            if not ct:
                continue
            con.execute("UPDATE main.check_signer SET image_ciphertext = ? WHERE id = ?",
                        (crypto.encrypt(new, crypto.decrypt(old, ct, SIGNATURE_AAD), SIGNATURE_AAD), rid))
            n["signatures"] += 1
    return n


# ------------------------------------------------------------------ the merge
def build(current_db: Path, current_key: crypto.KeyMaterial | None, backup_db: Path,
          backup_key: crypto.KeyMaterial, out_db: Path, chosen: list[str], missing_users: str = "add") -> dict:
    """Writes the result database to out_db: the current database with the chosen domains replaced by the backup's.
    One transaction; out_db is only a work file (the swap happens afterwards). Returns the facts for the report.
    missing_users: 'add' (just those users from the backup) or 'include_users' (the caller added 'users')."""
    chosen = list(chosen)
    if missing_users == "include_users" and "users" not in chosen:
        chosen.append("users")
    out_db.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{current_db.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(out_db)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    # uri=True so the ATTACH below reads "file:...?mode=ro" as a URI; SQLite builds without SQLITE_USE_URI
    # (e.g. the server's) would otherwise treat it as a literal file name and fail to open it
    con = sqlite3.connect(f"file:{out_db.as_posix()}", uri=True, isolation_level=None)
    facts: dict = {"restored": [d for d in DOMAINS if d in chosen], "kept": [d for d in DOMAINS if d not in chosen]}
    try:
        con.execute("PRAGMA foreign_keys=OFF")
        con.execute(f"ATTACH DATABASE 'file:{backup_db.as_posix()}?mode=ro' AS bk")
        con.execute("BEGIN")
        ws_id, bk_ws = _ws_ids(con)
        pre = _check(con, chosen)
        # (2) everything still from the current installation is re-encrypted with the backup's key
        if current_key is None or current_key.check_value != backup_key.check_value:
            if current_key is None:
                raise RestoreChoiceError("The current encryption key can't be read, so a partial restore can't keep "
                                         "the current data. Restore everything instead.")
            kept_tables = set()
            if "data" not in chosen:
                kept_tables.add("bank_account")
            # two-step secrets always: kept users (all of them, or those missing from the backup) carry theirs
            kept_tables.add("user_mfa")
            if "settings.payments" not in chosen:
                kept_tables.add("check_signer")
            facts["reencrypted"] = _reencrypt(con, current_key, backup_key, kept_tables)
        else:
            facts["reencrypted"] = None
        # users: keep the current users that the backup doesn't have (4)
        kept_users: list[dict] = []
        if "users" in chosen:
            bk_ids = {r[0] for r in con.execute("SELECT id FROM bk.app_user")}
            extra = [r for r in con.execute("SELECT id, username FROM main.app_user").fetchall() if r[0] not in bk_ids]
            saved = {}
            ids = [r[0] for r in extra]
            if ids:
                marks = ",".join("?" * len(ids))
                for t in USER_TABLES:
                    key = "id" if t == "app_user" else "user_id"
                    if key not in _cols(con, "main", t):
                        continue
                    cols = _cols(con, "main", t)
                    saved[t] = (cols, con.execute(f'SELECT * FROM main."{t}" WHERE "{key}" IN ({marks})', ids).fetchall())
            for t in USER_TABLES:
                _replace(con, t, ws_id)
            for t, (cols, rows) in saved.items():
                for row in rows:
                    con.execute(f'INSERT OR IGNORE INTO main."{t}" ({", ".join(chr(34) + c + chr(34) for c in cols)}) '
                                f'VALUES ({",".join("?" * len(cols))})', row)
            if ids:
                con.execute(f"UPDATE main.app_user SET active = 0 WHERE id IN ({','.join('?' * len(ids))})", ids)
            kept_users = [{"id": r[0], "username": r[1]} for r in extra]
        facts["kept_users_inactivated"] = kept_users
        # data
        if "data" in chosen:
            cur_org = con.execute(f"SELECT {', '.join(ORG_PROFILE)} FROM main.entity WHERE is_organization = 1 "
                                  "ORDER BY id LIMIT 1").fetchone()
            for t in DATA_TABLES:
                _replace(con, t, ws_id)
            for c in DATA_WORKSPACE_COLUMNS:
                con.execute(f'UPDATE main.workspace SET "{c}" = (SELECT "{c}" FROM bk.workspace WHERE id = ?) '
                            "WHERE id = ?", (bk_ws, ws_id))
            if "settings.general" not in chosen and cur_org is not None:   # (5) the profile stays the current one
                con.execute(f"UPDATE main.entity SET {', '.join(c + ' = ?' for c in ORG_PROFILE)} "
                            "WHERE is_organization = 1", cur_org)
        # settings sections
        for name, sec in SETTINGS_SECTIONS.items():
            if name not in chosen:
                continue
            for t in sec["tables"]:
                _replace(con, t, ws_id)
            for c in sec["workspace"]:
                con.execute(f'UPDATE main.workspace SET "{c}" = (SELECT "{c}" FROM bk.workspace WHERE id = ?) '
                            "WHERE id = ?", (bk_ws, ws_id))
            if name == "settings.general" and "data" not in chosen:
                prof = con.execute(f"SELECT {', '.join(ORG_PROFILE)} FROM bk.entity WHERE is_organization = 1 "
                                   "ORDER BY id LIMIT 1").fetchone()
                if prof is not None:
                    con.execute(f"UPDATE main.entity SET {', '.join(c + ' = ?' for c in ORG_PROFILE)} "
                                "WHERE is_organization = 1", prof)
        if "reminders" in chosen:
            for t in REMINDER_TABLES:
                _replace(con, t, ws_id)
        # (4a) users the result's records refer to but doesn't have: added from the backup
        added = []
        if pre["missing_users"]:
            ids = [u["id"] for u in pre["missing_users"]]
            marks = ",".join("?" * len(ids))
            for t in USER_TABLES:
                cols = _cols(con, "main", t)
                key = "id" if t == "app_user" else "user_id"
                if key not in cols:
                    continue
                bcols = set(_cols(con, "bk", t))
                sel = [str(ws_id) if c == "workspace_id" else (f'"{c}"' if c in bcols else "NULL") for c in cols]
                con.execute(f'INSERT OR IGNORE INTO main."{t}" ({", ".join(chr(34) + c + chr(34) for c in cols)}) '
                            f'SELECT {", ".join(sel)} FROM bk."{t}" WHERE "{key}" IN ({marks})', ids)
            added = pre["missing_users"]
        facts["users_added_from_backup"] = added
        facts["user_id_clashes"] = pre["user_id_clashes"]
        facts["host_settings"] = pre["host_settings"]
        facts["cleared"] = _clean_references(con)
        con.execute("UPDATE main.workspace SET key_check = ? WHERE id = ?", (backup_key.check_value, ws_id))
        problems = con.execute("PRAGMA main.foreign_key_check").fetchall()
        if problems:
            tables = sorted({p[0] for p in problems})
            raise RestoreChoiceError("The chosen parts don't fit together (" + ", ".join(tables) + "). Nothing was "
                                     "changed. Include more parts, or restore everything.")
        con.execute("COMMIT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        con.close()
        out_db.unlink(missing_ok=True)
        raise
    con.close()
    return facts


def _clean_references(con) -> dict:
    """References between domains that the chosen combination left pointing at nothing (points 5 and 6)."""
    out = {}
    # (5) a bank account's check style kept only if that style exists
    out["account_check_styles"] = con.execute(
        "DELETE FROM main.check_account WHERE check_style_id NOT IN (SELECT id FROM main.check_style)").rowcount
    out["printer_settings"] = con.execute(
        "DELETE FROM main.check_printer_setting WHERE (check_style_id IS NOT NULL AND check_style_id NOT IN "
        "(SELECT id FROM main.check_style)) OR (document_id IS NOT NULL AND document_id NOT IN "
        "(SELECT id FROM main.check_document)) OR user_id NOT IN (SELECT id FROM main.app_user)").rowcount
    # (6) reminder links to records that aren't there
    n = 0
    for lt, table in LINK_TABLES.items():
        n += con.execute(f"UPDATE main.reminder SET link_type = NULL, link_id = NULL WHERE link_type = ? AND link_id "
                         f'NOT IN (SELECT id FROM main."{table}")', (lt,)).rowcount
    out["reminder_links"] = n
    out["projection_choices"] = con.execute(
        "DELETE FROM main.budget_projection_choice WHERE user_id NOT IN (SELECT id FROM main.app_user)").rowcount
    con.execute("UPDATE main.app_user SET last_payment_account_id = NULL WHERE last_payment_account_id IS NOT NULL "
                "AND last_payment_account_id NOT IN (SELECT id FROM main.bank_account)")
    # references to users that are not there (a user missing from the backup too): nullable columns are cleared
    for t, c in _user_ref_columns(con, [r[0] for r in con.execute(
            "SELECT name FROM main.sqlite_master WHERE type = 'table'") if r[0] not in ("audit_event",)]):
        if t in ("app_user",) and c in ("id",):
            continue
        if not _notnull(con, t).get(c):
            con.execute(f'UPDATE main."{t}" SET "{c}" = NULL WHERE "{c}" IS NOT NULL AND "{c}" NOT IN '
                        "(SELECT id FROM main.app_user)")
    return out


def attachments_for(chosen: list[str], current: Path, backup: Path, dest: Path) -> None:
    """The attachments folder of the result: the backup's with Data, otherwise a copy of the current one (hard links
    where possible, so nothing large is copied)."""
    if dest.exists():
        shutil.rmtree(dest)
    if "data" in chosen:
        if backup.exists():
            shutil.move(str(backup), str(dest))
        else:
            dest.mkdir(parents=True)
        return
    if not current.exists():
        dest.mkdir(parents=True)
        return

    def link(s, d):
        try:
            import os
            os.link(s, d)
        except OSError:
            shutil.copy2(s, d)
    shutil.copytree(current, dest, copy_function=link)


def prepare_result(settings, data: Path, chosen: list[str], missing_users: str = "add") -> tuple[Path, dict]:
    """Builds the result of a partial restore next to the unpacked backup (data = its 'data' folder): database (the
    merge), attachments (the backup's with Data, else the current ones) and secrets (always the backup's key). The
    caller swaps it in exactly like a full restore. The application must be paused (nothing may change the current
    database meanwhile)."""
    from . import backup as bk
    result = data.parent / "result"
    if result.exists():
        shutil.rmtree(result)
    backup_key = crypto.load_key(data / "secrets")
    if backup_key is None:
        raise bk.BackupError("The encryption key in the backup can't be read.")
    facts = build(settings.database_path, crypto.load_key(settings.secrets_dir), data / "database" / bk.DB_NAME,
                  backup_key, result / "database" / bk.DB_NAME, chosen, missing_users)
    attachments_for(facts["restored"], settings.attachments_dir, data / "attachments", result / "attachments")
    shutil.copytree(data / "secrets", result / "secrets")
    return result, facts


def report_lines(facts: dict) -> list[str]:
    """What the restorer should know afterwards (also in the audit record)."""
    out = []
    if facts.get("kept_users_inactivated"):
        out.append("Users not in the backup were kept and inactivated: "
                   + ", ".join(u["username"] for u in facts["kept_users_inactivated"]) + ".")
    if facts.get("users_added_from_backup"):
        out.append("Users added from the backup (the restored records refer to them): "
                   + ", ".join(u["username"] for u in facts["users_added_from_backup"]) + ".")
    if facts.get("user_id_clashes"):
        out.append("Some restored records refer to a user id that belongs to a different user here (a backup from "
                   "another installation): " + ", ".join(f"{c['backup_username']} → {c['current_username']}"
                                                         for c in facts["user_id_clashes"]) + ".")
    c = facts.get("cleared") or {}
    if c.get("account_check_styles"):
        out.append(f"{c['account_check_styles']} bank account check style(s) cleared: the style isn't in the current "
                   "Payments Setup; a Register User chooses it again.")
    if c.get("reminder_links"):
        out.append(f"{c['reminder_links']} reminder link(s) to records that aren't there were cleared.")
    for h in facts.get("host_settings") or []:
        if not h.get("exists"):
            out.append(f"The restored {h['setting']} ({h['value']}) doesn't exist on this server: scheduled backups "
                       "will fail until it is changed under Backups → Scheduled.")
    if facts.get("reencrypted"):
        out.append("The backup came from another installation: kept values were re-encrypted with its key.")
    return out
