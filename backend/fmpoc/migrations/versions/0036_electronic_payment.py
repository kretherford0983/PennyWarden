"""2.1.0 (#260): electronic payments on withdrawals - register_transaction.electronic_payment (off for every
existing transaction), payment_method (ACH | DEBIT_CARD | WIRE | ONLINE_PORTAL | OTHER), payment_method_other (the
short description for OTHER) and payment_reference (a bank/vendor confirmation number, kept apart from check_number
so it never enters the check sequence, CR-011/CR-012). Plain ADD COLUMN, no existing value changes.

Revision ID: 0036_electronic_payment
Revises: 0035_register_sort
"""
import sqlalchemy as sa
from alembic import op

revision = "0036_electronic_payment"
down_revision = "0035_register_sort"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("register_transaction", sa.Column("electronic_payment", sa.Boolean(), nullable=False,
                                                    server_default=sa.false()))
    op.add_column("register_transaction", sa.Column("payment_method", sa.String(20), nullable=True))
    op.add_column("register_transaction", sa.Column("payment_method_other", sa.String(60), nullable=True))
    op.add_column("register_transaction", sa.Column("payment_reference", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("register_transaction", "payment_reference")
    op.drop_column("register_transaction", "payment_method_other")
    op.drop_column("register_transaction", "payment_method")
    op.drop_column("register_transaction", "electronic_payment")
