"""2.2.0 (#280): organization branding for generated reports and presentations - one row per organization: the palette
(a ready-made one or custom resolved colors), the full logo and small mark (PNG, re-encoded), the footer text. No row =
the PennyWarden palette, no logos. Addition only.

Revision ID: 0053_branding
Revises: 0052_account_opened
"""
import sqlalchemy as sa
from alembic import op

revision = "0053_branding"
down_revision = "0052_account_opened"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "branding_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False, unique=True),
        sa.Column("preset", sa.String(20), nullable=False, server_default="pennywarden"),
        sa.Column("source_primary", sa.String(7), nullable=True),
        sa.Column("source_secondary", sa.String(7), nullable=True),
        sa.Column("colors_json", sa.Text(), nullable=True),
        sa.Column("footer_text", sa.String(120), nullable=True),
        sa.Column("logo_full_png", sa.LargeBinary(), nullable=True),
        sa.Column("logo_full_sha256", sa.String(64), nullable=True),
        sa.Column("logo_full_width", sa.Integer(), nullable=True),
        sa.Column("logo_full_height", sa.Integer(), nullable=True),
        sa.Column("logo_mark_png", sa.LargeBinary(), nullable=True),
        sa.Column("logo_mark_sha256", sa.String(64), nullable=True),
        sa.Column("logo_mark_width", sa.Integer(), nullable=True),
        sa.Column("logo_mark_height", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("branding_settings")
