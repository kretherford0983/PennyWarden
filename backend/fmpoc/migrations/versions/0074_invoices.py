"""2.4.0 (#253): invoices - Administrator setup (numbering, terms), invoices, their catalog lines and sent
revisions, and attachment.invoice_id for each sent version's PDF. New, empty tables; nothing existing changes.

Revision ID: 0074_invoices
Revises: 0073_invoice_catalog
"""
import sqlalchemy as sa
from alembic import op

revision = "0074_invoices"
down_revision = "0073_invoice_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("number_pattern", sa.String(60), nullable=False),
        sa.Column("next_seq", sa.Integer(), nullable=False),
        sa.Column("terms_days", sa.Integer(), nullable=False),
        sa.Column("terms_text", sa.String(200), nullable=True),
        sa.Column("default_notes", sa.String(2000), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint("workspace_id", name="uq_invoice_settings_workspace_id"))
    op.create_table(
        "invoice",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("number", sa.String(60), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("customer_entity_id", sa.Integer(), sa.ForeignKey("entity.id"), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("terms_text", sa.String(200), nullable=True),
        sa.Column("notes", sa.String(2000), nullable=True),
        sa.Column("tax_rate_id", sa.Integer(), sa.ForeignKey("invoice_tax_rate.id"), nullable=True),
        sa.Column("tax_name", sa.String(80), nullable=True),
        sa.Column("tax_rate_milli_pct", sa.Integer(), nullable=True),
        sa.Column("tax_budget_id", sa.Integer(), nullable=True),
        sa.Column("discount_kind", sa.String(10), nullable=True),
        sa.Column("discount_value", sa.BigInteger(), nullable=True),
        sa.Column("discount_reason", sa.String(200), nullable=True),
        sa.Column("status", sa.String(14), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("sent_by_user_id", sa.Integer(), nullable=True),
        sa.Column("void_reason", sa.String(500), nullable=True),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("write_off_status", sa.String(10), nullable=True),
        sa.Column("write_off_reason", sa.String(500), nullable=True),
        sa.Column("write_off_requested_at", sa.DateTime(), nullable=True),
        sa.Column("write_off_requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("write_off_decided_at", sa.DateTime(), nullable=True),
        sa.Column("write_off_decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("write_off_note", sa.String(500), nullable=True),
        sa.Column("write_off_self_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint("workspace_id", "seq", name="uq_invoice_ws_seq"))
    op.create_index("ix_invoice_workspace_id", "invoice", ["workspace_id"])
    op.create_index("ix_invoice_customer_entity_id", "invoice", ["customer_entity_id"])
    op.create_index("ix_invoice_status", "invoice", ["status"])
    op.create_table(
        "invoice_line",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoice.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("invoice_product.id"), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("unit_type", sa.String(40), nullable=True),
        sa.Column("unit_price_cents", sa.BigInteger(), nullable=False),
        sa.Column("quantity_milli", sa.BigInteger(), nullable=False),
        sa.Column("taxable", sa.Boolean(), nullable=False),
        sa.Column("budget_id", sa.Integer(), nullable=True),
        sa.Column("discount_kind", sa.String(10), nullable=True),
        sa.Column("discount_value", sa.BigInteger(), nullable=True),
        sa.Column("discount_reason", sa.String(200), nullable=True))
    op.create_index("ix_invoice_line_invoice_id", "invoice_line", ["invoice_id"])
    op.create_table(
        "invoice_revision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoice.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(70), nullable=False),
        sa.Column("total_cents", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("attachment_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("sent_by_user_id", sa.Integer(), nullable=True))
    op.create_index("ix_invoice_revision_invoice_id", "invoice_revision", ["invoice_id"])
    with op.batch_alter_table("attachment") as b:
        b.add_column(sa.Column("invoice_id", sa.Integer(), nullable=True))
        b.create_index("ix_attachment_invoice_id", ["invoice_id"])


def downgrade() -> None:
    with op.batch_alter_table("attachment") as b:
        b.drop_index("ix_attachment_invoice_id")
        b.drop_column("invoice_id")
    for t in ("invoice_revision", "invoice_line", "invoice", "invoice_settings"):
        op.drop_table(t)
