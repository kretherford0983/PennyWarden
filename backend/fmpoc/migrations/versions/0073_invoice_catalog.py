"""2.4.0 (#252): the Invoices product catalog - unit types, product categories, products and tax rates (new, empty
tables; the common unit types and the built-in Discount item are added when the Invoices module is turned on).

Revision ID: 0073_invoice_catalog
Revises: 0072_invoices_module
"""
import sqlalchemy as sa
from alembic import op

revision = "0073_invoice_catalog"
down_revision = "0072_invoices_module"
branch_labels = None
depends_on = None


def _audit_cols():
    return [sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("updated_by_user_id", sa.Integer(), nullable=True)]


def upgrade() -> None:
    op.create_table("invoice_unit_type",
                    sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False),
                    sa.Column("name", sa.String(40), nullable=False), *_audit_cols())
    op.create_index("ix_invoice_unit_type_workspace_id", "invoice_unit_type", ["workspace_id"])
    op.create_table("invoice_product_category",
                    sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False),
                    sa.Column("name", sa.String(80), nullable=False), *_audit_cols())
    op.create_index("ix_invoice_product_category_workspace_id", "invoice_product_category", ["workspace_id"])
    op.create_table("invoice_product",
                    sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False),
                    sa.Column("name", sa.String(120), nullable=False),
                    sa.Column("code", sa.String(30), nullable=True),
                    sa.Column("description", sa.String(1000), nullable=True),
                    sa.Column("unit_price_cents", sa.BigInteger(), nullable=False, server_default="0"),
                    sa.Column("unit_type_id", sa.Integer(), sa.ForeignKey("invoice_unit_type.id"), nullable=True),
                    sa.Column("category_id", sa.Integer(), sa.ForeignKey("invoice_product_category.id"), nullable=True),
                    sa.Column("taxable", sa.Boolean(), nullable=False, server_default=sa.false()),
                    sa.Column("budget_id", sa.Integer(), sa.ForeignKey("budget.id"), nullable=True),
                    sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
                    *_audit_cols())
    op.create_index("ix_invoice_product_workspace_id", "invoice_product", ["workspace_id"])
    op.create_index("ix_invoice_product_budget_id", "invoice_product", ["budget_id"])
    op.create_table("invoice_tax_rate",
                    sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False),
                    sa.Column("name", sa.String(80), nullable=False),
                    sa.Column("rate_milli_pct", sa.Integer(), nullable=False),
                    sa.Column("budget_id", sa.Integer(), sa.ForeignKey("budget.id"), nullable=True),
                    *_audit_cols())
    op.create_index("ix_invoice_tax_rate_workspace_id", "invoice_tax_rate", ["workspace_id"])
    op.create_index("ix_invoice_tax_rate_budget_id", "invoice_tax_rate", ["budget_id"])


def downgrade() -> None:
    for t in ("invoice_tax_rate", "invoice_product", "invoice_product_category", "invoice_unit_type"):
        op.drop_table(t)
