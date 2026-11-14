"""2.4.0 polish (#483, #486): a product category's optional Invoiced Income budget (followed by its products unless
they set their own) and optional product code pattern (+ the per-year counters of its {SEQ}).

Revision ID: 0082_category_defaults
Revises: 0081_invoice_template
"""
import sqlalchemy as sa
from alembic import op

revision = "0082_category_defaults"
down_revision = "0081_invoice_template"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("invoice_product_category") as b:
        b.add_column(sa.Column("budget_id", sa.Integer(), sa.ForeignKey("budget.id", name="fk_invoice_category_budget"),
                               nullable=True))
        b.add_column(sa.Column("code_pattern", sa.String(40), nullable=True))
        b.add_column(sa.Column("code_counters", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("invoice_product_category") as b:
        b.drop_column("code_counters")
        b.drop_column("code_pattern")
        b.drop_column("budget_id")
