"""2.1.0 (#259): the order of the attachments of one transaction, allocation, fundraiser or Fiscal Year (Unspecified
documents) - attachment.sort_order. Empty for every existing attachment, which keeps upload order (attachments are
listed by COALESCE(sort_order, id)). Plain ADD COLUMN, no existing value changes.

Revision ID: 0037_attachment_order
Revises: 0036_electronic_payment
"""
import sqlalchemy as sa
from alembic import op

revision = "0037_attachment_order"
down_revision = "0036_electronic_payment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attachment", sa.Column("sort_order", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("attachment", "sort_order")
