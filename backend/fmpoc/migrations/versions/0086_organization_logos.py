"""2.4.0 polish (#503): organization logos (the logo, the small mark and their dark-background versions) that cover
letters, envelopes, the invoice PDF, donation letters and Branding can use - each place chooses Organization logo,
its own logo, or none.

Upgrade (Kyle, 2026-11-03): Branding's logos become the organization logos and Branding's slots use them; a cover
letter or the invoice PDF whose logo is the identical file uses the organization logo; any other keeps its own. Places
without a logo stay without one. Nothing prints differently.

Revision ID: 0086_organization_logos
Revises: 0085_entity_tax_exempt
"""
import datetime as dt
import json

import sqlalchemy as sa
from alembic import op

revision = "0086_organization_logos"
down_revision = "0085_entity_tax_exempt"
branch_labels = None
depends_on = None

SLOTS = ("full", "mark", "dark_full", "dark_mark")


def upgrade() -> None:
    op.create_table(
        "organization_logo",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False, index=True),
        sa.Column("slot", sa.String(10), nullable=False),
        sa.Column("png", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint("workspace_id", "slot", name="uq_organization_logo_slot"),
    )
    with op.batch_alter_table("branding_settings") as b:
        b.add_column(sa.Column("logo_sources", sa.Text(), nullable=True))
    with op.batch_alter_table("donation_settings") as b:
        b.add_column(sa.Column("receipt_logo_png", sa.LargeBinary(), nullable=True))
        b.add_column(sa.Column("receipt_logo_sha256", sa.String(64), nullable=True))
        b.add_column(sa.Column("statement_logo_png", sa.LargeBinary(), nullable=True))
        b.add_column(sa.Column("statement_logo_sha256", sa.String(64), nullable=True))

    con = op.get_bind()
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    org_full: dict[int, str] = {}                    # workspace -> the organization logo's fingerprint
    cols = ", ".join(f"logo_{s}_png, logo_{s}_sha256, logo_{s}_width, logo_{s}_height" for s in SLOTS)
    for row in con.execute(sa.text(f"SELECT id, workspace_id, {cols} FROM branding_settings")).fetchall():
        bid, ws = row[0], row[1]
        sources = {}
        for i, slot in enumerate(SLOTS):
            png, sha, w, h = row[2 + 4 * i: 6 + 4 * i]
            if png is None:
                continue
            con.execute(sa.text("INSERT INTO organization_logo (workspace_id, slot, png, sha256, width, height, "
                                "updated_at) VALUES (:ws, :slot, :png, :sha, :w, :h, :now)"),
                        {"ws": ws, "slot": slot, "png": png, "sha": sha, "w": w, "h": h, "now": now})
            sources[slot] = "ORG"
            if slot == "full":
                org_full[ws] = sha
        if sources:                                  # Branding uses the same files from the organization now
            sets = ", ".join(f"logo_{s}_png = NULL, logo_{s}_sha256 = NULL, logo_{s}_width = NULL, "
                             f"logo_{s}_height = NULL" for s in sources)
            con.execute(sa.text(f"UPDATE branding_settings SET logo_sources = :src, {sets} WHERE id = :id"),
                        {"src": json.dumps(sources), "id": bid})

    def source(ws: int, sha: str | None) -> str:
        if sha is None:
            return "NONE"
        return "ORG" if org_full.get(ws) == sha else "OWN"

    # cover letters: the source goes into the template's settings; an identical logo is dropped (the org one is used)
    for did, ws, cfg_json, sha in con.execute(sa.text(
            "SELECT id, workspace_id, config_json, logo_sha256 FROM check_document WHERE kind = 'LETTER'")).fetchall():
        cfg = json.loads(cfg_json or "{}")
        cfg["logo_source"] = source(ws, sha)
        extra = (", logo_png = NULL, logo_sha256 = NULL, logo_width = NULL, logo_height = NULL"
                 if cfg["logo_source"] == "ORG" else "")
        con.execute(sa.text(f"UPDATE check_document SET config_json = :c{extra} WHERE id = :id"),
                    {"c": json.dumps(cfg), "id": did})
    # the invoice PDF
    for sid, ws, tpl, sha in con.execute(sa.text(
            "SELECT id, workspace_id, template_json, logo_sha256 FROM invoice_settings")).fetchall():
        cfg = json.loads(tpl) if tpl else {}
        cfg["logo_source"] = source(ws, sha)
        extra = ", logo_png = NULL, logo_sha256 = NULL" if cfg["logo_source"] == "ORG" else ""
        con.execute(sa.text(f"UPDATE invoice_settings SET template_json = :c{extra} WHERE id = :id"),
                    {"c": json.dumps(cfg), "id": sid})
    # envelopes and donation letters had no logo: their settings default to No logo


def downgrade() -> None:
    with op.batch_alter_table("donation_settings") as b:
        b.drop_column("statement_logo_sha256")
        b.drop_column("statement_logo_png")
        b.drop_column("receipt_logo_sha256")
        b.drop_column("receipt_logo_png")
    with op.batch_alter_table("branding_settings") as b:
        b.drop_column("logo_sources")
    op.drop_table("organization_logo")
