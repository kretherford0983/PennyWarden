"""2.4.0 (#253 part 3): the invoice PDF template and logo on invoice_settings (empty: the built-in layout).

Revision ID: 0081_invoice_template
Revises: 0080_email
"""
import sqlalchemy as sa
from alembic import op

revision = "0081_invoice_template"
down_revision = "0080_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("invoice_settings") as b:
        b.add_column(sa.Column("template_json", sa.Text(), nullable=True))
        b.add_column(sa.Column("logo_png", sa.LargeBinary(), nullable=True))
        b.add_column(sa.Column("logo_sha256", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("invoice_settings") as b:
        b.drop_column("logo_sha256")
        b.drop_column("logo_png")
        b.drop_column("template_json")
