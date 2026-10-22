"""2.1.0 (#314): the organization as an entity. entity.is_organization (off) and entity.ein (empty); every initialized
workspace gets its organization entity, named like the workspace. The EIN and mailing address saved in Donations
Setup (#312) move onto it and leave the donation settings.

Revision ID: 0046_organization_entity
Revises: 0045_donation_receipts
"""
import datetime as dt
import json
import re

import sqlalchemy as sa
from alembic import op

revision = "0046_organization_entity"
down_revision = "0045_donation_receipts"
branch_labels = None
depends_on = None

LAST_LINE = re.compile(r"^(?P<city>.+?),\s*(?P<state>[A-Za-z][A-Za-z .]*?)\s+(?P<zip>\d{5}(?:-\d{4})?)$")


def name_key(s):
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(inc|llc|ltd|co|corp|corporation|company|the)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()[:200]


def split_address(lines):
    """Free address lines (Donations Setup) -> entity address fields; a last line "City, ST 12345" is split."""
    lines = [x.strip() for x in lines or [] if x and x.strip()]
    out = {"address_line1": None, "address_line2": None, "city": None, "state_region": None, "postal_code": None}
    if lines:
        m = LAST_LINE.match(lines[-1])
        if m:
            out.update(city=m["city"].strip()[:100], state_region=m["state"].strip()[:100], postal_code=m["zip"])
            lines = lines[:-1]
    if lines:
        out["address_line1"] = lines[0][:200]
    if len(lines) > 1:
        out["address_line2"] = ", ".join(lines[1:])[:200]
    return out


def upgrade() -> None:
    with op.batch_alter_table("entity") as b:
        b.add_column(sa.Column("is_organization", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("ein", sa.String(10), nullable=True))
    conn = op.get_bind()
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    for ws_id, name, nxt in conn.execute(sa.text(
            "SELECT id, name, next_entity_number FROM workspace WHERE bootstrap_completed_at IS NOT NULL")).fetchall():
        fields = {"address_line1": None, "address_line2": None, "city": None, "state_region": None,
                  "postal_code": None}
        ein = None
        row = conn.execute(sa.text("SELECT id, config_json FROM donation_settings WHERE workspace_id = :w"),
                           {"w": ws_id}).fetchone()
        if row:
            cfg = json.loads(row[1] or "{}")
            ein = (cfg.pop("ein", None) or "").strip() or None
            fields = split_address(cfg.pop("org_address", None))
            conn.execute(sa.text("UPDATE donation_settings SET config_json = :c WHERE id = :i"),
                         {"c": json.dumps(cfg, sort_keys=True), "i": row[0]})
        n = nxt or 1
        conn.execute(sa.text("UPDATE workspace SET next_entity_number = :n WHERE id = :w"), {"n": n + 1, "w": ws_id})
        conn.execute(sa.text(
            "INSERT INTO entity (workspace_id, entity_number, entity_type, organization_name, address_line1, "
            "address_line2, city, state_region, postal_code, is_financial_institution, is_system, is_organization, "
            "ein, active, name_key, created_at, updated_at) VALUES (:w, :num, 'ORGANIZATION', :name, :a1, :a2, :city, "
            ":st, :zip, 0, 0, 1, :ein, 1, :key, :now, :now)"),
            {"w": ws_id, "num": f"ENT-{n:06d}", "name": name, "a1": fields["address_line1"],
             "a2": fields["address_line2"], "city": fields["city"], "st": fields["state_region"],
             "zip": fields["postal_code"], "ein": ein, "key": name_key(name), "now": now})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM entity WHERE is_organization = 1 AND id NOT IN "
                         "(SELECT parent_entity_id FROM register_transaction WHERE parent_entity_id IS NOT NULL) "
                         "AND id NOT IN (SELECT entity_id FROM transaction_allocation WHERE entity_id IS NOT NULL)"))
    with op.batch_alter_table("entity") as b:
        b.drop_column("ein")
        b.drop_column("is_organization")
