"""2.4.0 (#253 part 2): invoice custom fields (Administrator-defined, on invoices or lines) and their values.

Revision ID: 0075_invoice_custom_fields
Revises: 0074_invoices
"""
import sqlalchemy as sa
from alembic import op

revision = "0075_invoice_custom_fields"
down_revision = "0074_invoices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_custom_field",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("level", sa.String(10), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("field_type", sa.String(10), nullable=False),
        sa.Column("options", sa.Text(), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("show_on_pdf", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True))
    op.create_index("ix_invoice_custom_field_workspace_id", "invoice_custom_field", ["workspace_id"])
    with op.batch_alter_table("invoice") as b:
        b.add_column(sa.Column("custom_values", sa.Text(), nullable=True))
    with op.batch_alter_table("invoice_line") as b:
        b.add_column(sa.Column("custom_values", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("invoice_line") as b:
        b.drop_column("custom_values")
    with op.batch_alter_table("invoice") as b:
        b.drop_column("custom_values")
    op.drop_table("invoice_custom_field")
