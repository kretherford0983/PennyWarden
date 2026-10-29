"""2.3.0 (#376): Report settings - how the Reports catalog is grouped (workspace-wide; Administrators). One row per
organization: the active scheme (PURPOSE, SUBJECT or AUDIENCE) and each customized scheme's categories with their
reports in order (JSON). No row = the Purpose grouping of 2.3.0 (#375), so nothing changes on upgrade.

Revision ID: 0067_report_grouping
Revises: 0066_report_prefs
"""
import sqlalchemy as sa
from alembic import op

revision = "0067_report_grouping"
down_revision = "0066_report_prefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_grouping",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False, unique=True),
        sa.Column("scheme", sa.String(10), nullable=False, server_default="PURPOSE"),
        sa.Column("config_json", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("report_grouping")
