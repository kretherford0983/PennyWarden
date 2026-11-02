"""2.3.0 (#391): bank account balance history - Correct and Retire an entry (with a reason), and a record of
balances changed in a Closed Fiscal Year (Budget Admins).

* bank_account_balance: corrected_at/by/correct_reason, previous_balance_cents/previous_as_of_date (the values the
  last correction replaced), retired_at/by/retire_reason - all empty for existing entries (nothing changes);
* the table fiscal_year_balance_change (empty).

Revision ID: 0061_balance_correct_retire
Revises: 0060_fundraiser_goal
"""
import sqlalchemy as sa
from alembic import op

revision = "0061_balance_correct_retire"
down_revision = "0060_fundraiser_goal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("bank_account_balance") as b:
        b.add_column(sa.Column("corrected_at", sa.DateTime, nullable=True))
        b.add_column(sa.Column("corrected_by_user_id", sa.Integer, nullable=True))
        b.add_column(sa.Column("correct_reason", sa.String(500), nullable=True))
        b.add_column(sa.Column("previous_balance_cents", sa.BigInteger, nullable=True))
        b.add_column(sa.Column("previous_as_of_date", sa.Date, nullable=True))
        b.add_column(sa.Column("retired_at", sa.DateTime, nullable=True))
        b.add_column(sa.Column("retired_by_user_id", sa.Integer, nullable=True))
        b.add_column(sa.Column("retire_reason", sa.String(500), nullable=True))
    op.create_table(
        "fiscal_year_balance_change",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("fiscal_year_id", sa.Integer, sa.ForeignKey("fiscal_year.id"), nullable=False),
        sa.Column("bank_account_id", sa.Integer, sa.ForeignKey("bank_account.id"), nullable=False),
        sa.Column("balance_entry_id", sa.Integer, nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("before_json", sa.Text, nullable=True),
        sa.Column("after_json", sa.Text, nullable=True),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("changed_at", sa.DateTime, nullable=False),
        sa.Column("changed_by_user_id", sa.Integer, nullable=True),
    )
    op.create_index("ix_fiscal_year_balance_change_workspace_id", "fiscal_year_balance_change", ["workspace_id"])
    op.create_index("ix_fiscal_year_balance_change_fiscal_year_id", "fiscal_year_balance_change", ["fiscal_year_id"])


def downgrade() -> None:
    op.drop_index("ix_fiscal_year_balance_change_fiscal_year_id", "fiscal_year_balance_change")
    op.drop_index("ix_fiscal_year_balance_change_workspace_id", "fiscal_year_balance_change")
    op.drop_table("fiscal_year_balance_change")
    with op.batch_alter_table("bank_account_balance") as b:
        for c in ("retire_reason", "retired_by_user_id", "retired_at", "previous_as_of_date", "previous_balance_cents",
                  "correct_reason", "corrected_by_user_id", "corrected_at"):
            b.drop_column(c)
