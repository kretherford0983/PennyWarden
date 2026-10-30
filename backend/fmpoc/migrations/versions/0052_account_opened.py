"""2.2.0 (#348): bank_account.account_opened_date - when the account was really opened (empty = it existed before
PennyWarden). Comparisons to a date before it start at $0; otherwise a date before any data uses the earliest data.
Addition only.

Revision ID: 0052_account_opened
Revises: 0051_demo_mode
"""
import sqlalchemy as sa
from alembic import op

revision = "0052_account_opened"
down_revision = "0051_demo_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bank_account", sa.Column("account_opened_date", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("bank_account") as b:
        b.drop_column("account_opened_date")
