"""2.1.0 (#257, #261): which current-year budgets a user projects to the Fiscal Year end in the Budget Prep report and
the Planning Sheet - budget_projection_choice (one row per user and budget; no row = the default). New table only.

Revision ID: 0038_projection_choices
Revises: 0037_attachment_order
"""
import sqlalchemy as sa
from alembic import op

revision = "0038_projection_choices"
down_revision = "0037_attachment_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budget_projection_choice",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_user.id"), nullable=False, index=True),
        sa.Column("budget_id", sa.Integer(), sa.ForeignKey("budget.id"), nullable=False, index=True),
        sa.Column("project", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "budget_id", name="uq_projection_choice_user_budget"),
    )


def downgrade() -> None:
    op.drop_table("budget_projection_choice")
