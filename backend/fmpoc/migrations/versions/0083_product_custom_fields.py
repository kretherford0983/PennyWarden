"""2.4.0 polish (#484): custom fields applied to specific products - the product-scope fields attached to a product
(their values are entered on each invoice line using it).

Revision ID: 0083_product_custom_fields
Revises: 0082_category_defaults
"""
import sqlalchemy as sa
from alembic import op

revision = "0083_product_custom_fields"
down_revision = "0082_category_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("invoice_product") as b:
        b.add_column(sa.Column("custom_field_ids", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("invoice_product") as b:
        b.drop_column("custom_field_ids")
