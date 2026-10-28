"""2.2.0 (#231): testing mode - the table testing_state (the last-backup time and the reinitialize-cooldown clearing a
testing-mode Administrator set; read only while the server is in testing mode). Addition only.

Revision ID: 0050_testing_state
Revises: 0049_budget_history_entry
"""
import sqlalchemy as sa
from alembic import op

revision = "0050_testing_state"
down_revision = "0049_budget_history_entry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "testing_state",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspace.id"), nullable=False, unique=True),
        sa.Column("last_backup_at", sa.DateTime, nullable=True),
        sa.Column("reinitialize_cooldown_cleared_at", sa.DateTime, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("testing_state")
