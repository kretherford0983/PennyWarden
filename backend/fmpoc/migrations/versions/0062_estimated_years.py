"""2.3.0 (#390): entered years before PennyWarden can be marked estimated (a note is then required) -
fundraiser_series_result.estimated and budget_history_entry.estimated, off for every existing entry.

Revision ID: 0062_estimated_years
Revises: 0061_balance_correct_retire
"""
import sqlalchemy as sa
from alembic import op

revision = "0062_estimated_years"
down_revision = "0061_balance_correct_retire"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("fundraiser_series_result", "budget_history_entry"):
        with op.batch_alter_table(table) as b:
            b.add_column(sa.Column("estimated", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for table in ("budget_history_entry", "fundraiser_series_result"):
        with op.batch_alter_table(table) as b:
            b.drop_column("estimated")
