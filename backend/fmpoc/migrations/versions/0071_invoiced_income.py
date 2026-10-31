"""2.4.0 (#250): Invoiced Income budgets - a flag on an Income parent budget (its sub-budgets and Other carry it
too). Off for every existing budget. Its rules take effect only with the Invoices module (later 2.4.0 builds).

Revision ID: 0071_invoiced_income
Revises: 0070_event_type
"""
import sqlalchemy as sa
from alembic import op

revision = "0071_invoiced_income"
down_revision = "0070_event_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("budget") as b:
        b.add_column(sa.Column("invoiced_income", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("budget") as b:
        b.drop_column("invoiced_income")
