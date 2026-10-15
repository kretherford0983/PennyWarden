"""2.0.0 (#164): app_user.last_payment_account_id - the bank account of the user's last payment, preselected on the
next one. Empty for everyone; no existing data changes. Plain add_column (app_user carries the 0017 triggers).

Revision ID: 0026_last_payment_account
Revises: 0025_check_printing
"""
import sqlalchemy as sa
from alembic import op

revision = "0026_last_payment_account"
down_revision = "0025_check_printing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("last_payment_account_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("app_user", "last_payment_account_id")
