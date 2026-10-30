"""2.2.0 (#284): budget history before PennyWarden - the table budget_history_entry (a budget line's budgeted and actual
figures for a year before the first Fiscal Year in PennyWarden, entered by a Budget Manager). Addition only.

Revision ID: 0049_budget_history_entry
Revises: 0048_mfa_own_key
"""
import sqlalchemy as sa
from alembic import op

revision = "0049_budget_history_entry"
down_revision = "0048_mfa_own_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budget_history_entry",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("budget_id", sa.Integer, sa.ForeignKey("budget.id"), nullable=False),
        sa.Column("fiscal_year_label", sa.String(40), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("budgeted_cents", sa.BigInteger, nullable=False),
        sa.Column("actual_cents", sa.BigInteger, nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("retired_at", sa.DateTime, nullable=True),
        sa.Column("retired_by_user_id", sa.Integer, nullable=True),
        sa.Column("retire_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("created_by_user_id", sa.Integer, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("updated_by_user_id", sa.Integer, nullable=True),
    )
    op.create_index("ix_budget_history_entry_workspace_id", "budget_history_entry", ["workspace_id"])
    op.create_index("ix_budget_history_entry_budget_id", "budget_history_entry", ["budget_id"])


def downgrade() -> None:
    op.drop_index("ix_budget_history_entry_budget_id", table_name="budget_history_entry")
    op.drop_index("ix_budget_history_entry_workspace_id", table_name="budget_history_entry")
    op.drop_table("budget_history_entry")
