"""2.4.0 (#254): invoice payments - links between invoices and the register allocations that pay them (and their
overpayment and its refund). New, empty table.

Revision ID: 0076_invoice_payments
Revises: 0075_invoice_custom_fields
"""
import sqlalchemy as sa
from alembic import op

revision = "0076_invoice_payments"
down_revision = "0075_invoice_custom_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_payment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoice.id"), nullable=False),
        sa.Column("allocation_id", sa.Integer(), sa.ForeignKey("transaction_allocation.id"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.Column("removed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("remove_reason", sa.String(500), nullable=True))
    for c in ("workspace_id", "invoice_id", "allocation_id"):
        op.create_index(f"ix_invoice_payment_{c}", "invoice_payment", [c])


def downgrade() -> None:
    op.drop_table("invoice_payment")
