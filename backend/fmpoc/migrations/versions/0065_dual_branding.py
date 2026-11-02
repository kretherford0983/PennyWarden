"""2.3.0 (#386): dual branding - a dark theme beside the light one, the theme each type of output uses, and optional
logos for dark backgrounds.

branding_settings gets: dark_preset / dark_colors_json (the dark palette: a ready-made one or custom colors; empty =
the dark version of the light palette), theme_reports / theme_presentations (LIGHT | DARK), dark_logos (off) and the
dark full logo and small mark. Kyle (2026-10-29): on upgrade every existing installation stays light for every output
type until an Administrator turns dark on - so each existing organization gets a branding row with both outputs
LIGHT (a row without changes looks exactly like no row). Only new installations start with dark presentations.

Revision ID: 0065_dual_branding
Revises: 0064_shared_signers
"""
import sqlalchemy as sa
from alembic import op

revision = "0065_dual_branding"
down_revision = "0064_shared_signers"
branch_labels = None
depends_on = None

LOGO = ("png", "sha256", "width", "height")


def upgrade() -> None:
    with op.batch_alter_table("branding_settings") as b:
        b.add_column(sa.Column("dark_preset", sa.String(20), nullable=True))
        b.add_column(sa.Column("dark_colors_json", sa.Text(), nullable=True))
        b.add_column(sa.Column("theme_reports", sa.String(5), nullable=False, server_default="LIGHT"))
        b.add_column(sa.Column("theme_presentations", sa.String(5), nullable=False, server_default="LIGHT"))
        b.add_column(sa.Column("dark_logos", sa.Boolean(), nullable=False, server_default=sa.false()))
        for slot in ("full", "mark"):
            b.add_column(sa.Column(f"logo_dark_{slot}_png", sa.LargeBinary(), nullable=True))
            b.add_column(sa.Column(f"logo_dark_{slot}_sha256", sa.String(64), nullable=True))
            b.add_column(sa.Column(f"logo_dark_{slot}_width", sa.Integer(), nullable=True))
            b.add_column(sa.Column(f"logo_dark_{slot}_height", sa.Integer(), nullable=True))
    conn = op.get_bind()
    have = {r[0] for r in conn.execute(sa.text("SELECT workspace_id FROM branding_settings"))}
    for (ws,) in conn.execute(sa.text("SELECT id FROM workspace")).fetchall():
        if ws not in have:
            conn.execute(sa.text("INSERT INTO branding_settings (workspace_id, preset, theme_reports, theme_presentations, "
                                 "dark_logos) VALUES (:w, 'pennywarden', 'LIGHT', 'LIGHT', 0)"), {"w": ws})


def downgrade() -> None:
    with op.batch_alter_table("branding_settings") as b:
        for slot in ("full", "mark"):
            for k in LOGO:
                b.drop_column(f"logo_dark_{slot}_{k}")
        for c in ("dark_logos", "theme_presentations", "theme_reports", "dark_colors_json", "dark_preset"):
            b.drop_column(c)
