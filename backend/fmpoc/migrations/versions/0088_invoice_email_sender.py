"""2.4.0 (#539): Invoices Setup's optional email sender overrides - the Reply-To and From name of invoice and statement
emails (empty: the Email setup's). Donations Setup keeps its own in its settings.

Revision ID: 0088_invoice_email_sender
Revises: 0087_invoice_credit
"""
import sqlalchemy as sa
from alembic import op

revision = "0088_invoice_email_sender"
down_revision = "0087_invoice_credit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("invoice_settings") as b:
        b.add_column(sa.Column("email_reply_to", sa.String(254), nullable=True))
        b.add_column(sa.Column("email_from_name", sa.String(120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("invoice_settings") as b:
        b.drop_column("email_from_name")
        b.drop_column("email_reply_to")
