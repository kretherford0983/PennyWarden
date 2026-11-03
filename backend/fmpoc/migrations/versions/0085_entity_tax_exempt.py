"""2.4.0 polish (#485): a customer (entity) can be tax-exempt, with an optional exemption certificate number; invoices
to it charge no sales tax.

Revision ID: 0085_entity_tax_exempt
Revises: 0084_tax_groups
"""
import sqlalchemy as sa
from alembic import op

revision = "0085_entity_tax_exempt"
down_revision = "0084_tax_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("entity") as b:
        b.add_column(sa.Column("tax_exempt", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("tax_exempt_certificate", sa.String(60), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("entity") as b:
        b.drop_column("tax_exempt_certificate")
        b.drop_column("tax_exempt")
