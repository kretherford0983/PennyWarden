"""2.0.0 (#165, #166): cover letters and envelopes - transaction_allocation.invoice_date (empty), the table
check_document (letter and envelope templates), and check_printer_setting gains document_id (envelope printer
settings) with check_style_id now optional. No existing data changes.

Revision ID: 0027_letters_envelopes
Revises: 0026_last_payment_account
"""
import sqlalchemy as sa
from alembic import op

revision = "0027_letters_envelopes"
down_revision = "0026_last_payment_account"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transaction_allocation", sa.Column("invoice_date", sa.Date(), nullable=True))
    op.create_table(
        "check_document",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(),
                  sa.ForeignKey("workspace.id", name="fk_check_document_workspace_id_workspace"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_check_document_workspace_id", "check_document", ["workspace_id"])
    # check_printer_setting has no triggers: batch mode (table copy) is safe here
    with op.batch_alter_table("check_printer_setting") as b:
        b.alter_column("check_style_id", existing_type=sa.Integer(), nullable=True)
        b.add_column(sa.Column("document_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_check_printer_setting_document_id_check_document", "check_document",
                             ["document_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("check_printer_setting") as b:
        b.drop_constraint("fk_check_printer_setting_document_id_check_document", type_="foreignkey")
        b.drop_column("document_id")
    op.drop_table("check_document")
    op.drop_column("transaction_allocation", "invoice_date")
