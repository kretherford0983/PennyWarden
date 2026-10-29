"""2.3.0 (#395): one shared list of signers for checks and letters.

* check_signer.areas - the areas a signer may be used in; every existing signer gets CHECKS;
* the Donations Setup's typed signer (signer_name / signer_title) becomes a signer tagged DONATIONS (or an existing
  signer with the same name and title gets that tag); the receipt then uses it with "Printed with space to sign by
  hand" - what it printed before. No typed name: the signature is None (the letter ended at the closing before too);
* each payment cover letter template: "Same as the check's signer", "Printed only" (as before); its typed fallback
  name and role (used when the check had no signer) become a signer tagged COVER_LETTERS chosen by the template -
  unless they contain {VARIABLES}, in which case the template keeps them as its typed fallback.

Revision ID: 0064_shared_signers
Revises: 0063_donation_ein_override
"""
import datetime as dt
import json

import sqlalchemy as sa
from alembic import op

revision = "0064_shared_signers"
down_revision = "0063_donation_ein_override"
branch_labels = None
depends_on = None

AREAS = ("CHECKS", "COVER_LETTERS", "DONATIONS")


def _signer(con, ws_id: int, name: str, title: str | None, area: str) -> int:
    title = (title or "").strip()[:80] or None
    name = name.strip()[:120]
    for sid, n, t, areas in con.execute(sa.text("SELECT id, name, title, areas FROM check_signer WHERE workspace_id = :w"),
                                        {"w": ws_id}).fetchall():
        if (n or "").strip().lower() == name.lower() and ((t or "").strip().lower() == (title or "").lower()):
            have = [a for a in (areas or "").split(",") if a]
            if area not in have:
                have.append(area)
                con.execute(sa.text("UPDATE check_signer SET areas = :a WHERE id = :i"),
                            {"a": ",".join(a for a in AREAS if a in have), "i": sid})
            return sid
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    con.execute(sa.text("INSERT INTO check_signer (workspace_id, name, title, active, areas, created_at, updated_at) "
                        "VALUES (:w, :n, :t, 1, :a, :c, :c)"), {"w": ws_id, "n": name, "t": title, "a": area, "c": now})
    return con.execute(sa.text("SELECT max(id) FROM check_signer WHERE workspace_id = :w"), {"w": ws_id}).scalar()


def upgrade() -> None:
    with op.batch_alter_table("check_signer") as b:
        b.add_column(sa.Column("areas", sa.String(100), nullable=True))
    con = op.get_bind()
    con.execute(sa.text("UPDATE check_signer SET areas = 'CHECKS'"))
    for rid, ws_id, raw in con.execute(sa.text("SELECT id, workspace_id, config_json FROM donation_settings")).fetchall():
        try:
            cfg = json.loads(raw or "{}")
        except ValueError:
            continue
        name = (cfg.pop("signer_name", "") or "").strip()
        title = cfg.pop("signer_title", "") or ""
        if name:
            cfg["signer_id"] = _signer(con, ws_id, name, title, "DONATIONS")
            cfg["signature_mode"] = "SPACE"
        # no typed signer: nothing to add - an absent signature_mode reads as NONE (the setting's default)
        con.execute(sa.text("UPDATE donation_settings SET config_json = :c WHERE id = :i"),
                    {"c": json.dumps(cfg, sort_keys=True), "i": rid})
    for rid, ws_id, raw in con.execute(sa.text("SELECT id, workspace_id, config_json FROM check_document "
                                               "WHERE kind = 'LETTER'")).fetchall():
        try:
            cfg = json.loads(raw or "{}")
        except ValueError:
            continue
        cfg.setdefault("signer_source", "SAME_AS_CHECK")
        cfg.setdefault("signature_mode", "PRINTED")
        name, role = (cfg.get("fallback_name") or "").strip(), (cfg.get("fallback_role") or "").strip()
        if name and "{" not in name + role and not cfg.get("signer_id"):
            cfg["signer_id"] = _signer(con, ws_id, name, role, "COVER_LETTERS")
        con.execute(sa.text("UPDATE check_document SET config_json = :c WHERE id = :i"),
                    {"c": json.dumps(cfg), "i": rid})


def downgrade() -> None:
    with op.batch_alter_table("check_signer") as b:
        b.drop_column("areas")
