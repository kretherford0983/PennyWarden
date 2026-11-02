"""2.3.0 (#375): the Reports screen remembers, per user, the last 5 report runs and each report's last options
(app_user.report_prefs, JSON; empty for every existing user). Parameters only - never report output.

Revision ID: 0066_report_prefs
Revises: 0065_dual_branding
"""
import sqlalchemy as sa
from alembic import op

revision = "0066_report_prefs"
down_revision = "0065_dual_branding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("app_user") as b:
        b.add_column(sa.Column("report_prefs", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("app_user") as b:
        b.drop_column("report_prefs")
