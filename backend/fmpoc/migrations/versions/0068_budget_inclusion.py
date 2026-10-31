"""2.3.0 (#414): years a budget's money was included in another budget (marked on its History; Budget Review shows
"included in ..."). New table only; nothing existing changes.

Revision ID: 0068_budget_inclusion
Revises: 0067_report_grouping
"""
import sqlalchemy as sa
from alembic import op

revision = "0068_budget_inclusion"
down_revision = "0067_report_grouping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budget_inclusion",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("budget_id", sa.Integer(), sa.ForeignKey("budget.id"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("fiscal_year_label", sa.String(40), nullable=False),
        sa.Column("fiscal_year_id", sa.Integer(), sa.ForeignKey("fiscal_year.id"), nullable=True),
        sa.Column("included_former_budget_id", sa.Integer(), sa.ForeignKey("former_budget.id"), nullable=True),
        sa.Column("included_budget_id", sa.Integer(), sa.ForeignKey("budget.id"), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.Column("retired_by_user_id", sa.Integer(), nullable=True),
        sa.Column("retire_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_budget_inclusion_workspace_id", "budget_inclusion", ["workspace_id"])
    op.create_index("ix_budget_inclusion_budget_id", "budget_inclusion", ["budget_id"])


def downgrade() -> None:
    op.drop_index("ix_budget_inclusion_budget_id", table_name="budget_inclusion")
    op.drop_index("ix_budget_inclusion_workspace_id", table_name="budget_inclusion")
    op.drop_table("budget_inclusion")
