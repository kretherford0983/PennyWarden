"""2.4.0 polish (#487): tax groups - several tax rates per item. A product picks a tax group (a named set of rates);
each invoice line carries the rates that apply to it; the invoice no longer picks one rate.

Existing invoices keep their figures: the invoice's one rate is copied onto its taxable lines. Products keep no tax
until a group is chosen (invoices were not released before 2.4.0, so only test data exists).

Revision ID: 0084_tax_groups
Revises: 0083_product_custom_fields
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0084_tax_groups"
down_revision = "0083_product_custom_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_tax_group",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("rate_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer()),
    )
    with op.batch_alter_table("invoice_product") as b:
        b.add_column(sa.Column("tax_group_id", sa.Integer(), sa.ForeignKey("invoice_tax_group.id",
                                                                            name="fk_invoice_product_tax_group"), nullable=True))
    with op.batch_alter_table("invoice_line") as b:
        b.add_column(sa.Column("taxes", sa.Text(), nullable=True))
    conn = op.get_bind()
    invs = conn.execute(sa.text("SELECT id, tax_rate_id, tax_name, tax_rate_milli_pct, tax_budget_id FROM invoice "
                                "WHERE tax_rate_milli_pct IS NOT NULL")).fetchall()
    for iid, rid, name, milli, bid in invs:
        taxes = json.dumps([{"rate_id": rid, "name": name or "Sales tax", "milli": milli, "budget_id": bid}])
        conn.execute(sa.text("UPDATE invoice_line SET taxes = :t WHERE invoice_id = :i AND taxable = :yes"),
                     {"t": taxes, "i": iid, "yes": True})


def downgrade() -> None:
    with op.batch_alter_table("invoice_line") as b:
        b.drop_column("taxes")
    with op.batch_alter_table("invoice_product") as b:
        b.drop_column("tax_group_id")
    op.drop_table("invoice_tax_group")
