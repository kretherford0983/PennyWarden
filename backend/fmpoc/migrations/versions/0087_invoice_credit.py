"""2.4.0 (#534): customer account credit - a payment link made by applying a customer's credit (an overpayment on
another of their invoices) remembers that invoice, so the credit can be taken back off. Existing overpayments not
refunded count as credit (decision 2: nothing moves).

Revision ID: 0087_invoice_credit
Revises: 0086_organization_logos
"""
import sqlalchemy as sa
from alembic import op

revision = "0087_invoice_credit"
down_revision = "0086_organization_logos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("invoice_payment") as b:
        b.add_column(sa.Column("credit_from_invoice_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("invoice_payment") as b:
        b.drop_column("credit_from_invoice_id")
