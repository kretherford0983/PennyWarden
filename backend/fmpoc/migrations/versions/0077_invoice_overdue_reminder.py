"""2.4.0 (#255): the overdue reminder to Invoice Managers - due date + N days, N set by the Administrator (default 0).

Revision ID: 0077_invoice_overdue_reminder
Revises: 0076_invoice_payments
"""
import sqlalchemy as sa
from alembic import op

revision = "0077_invoice_overdue_reminder"
down_revision = "0076_invoice_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("invoice_settings") as b:
        b.add_column(sa.Column("overdue_reminder_days", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("invoice_settings") as b:
        b.drop_column("overdue_reminder_days")
