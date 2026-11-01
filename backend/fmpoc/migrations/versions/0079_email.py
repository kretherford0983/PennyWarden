"""2.4.0 (#249): email invoices and statements - the empty tables email_settings (the Administrator's mail server,
off) and email_log.

Revision ID: 0079_email
Revises: 0078_invoice_batches
"""
import sqlalchemy as sa
from alembic import op

revision = "0079_email"
down_revision = "0078_invoice_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("host", sa.String(255), nullable=True),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("security", sa.String(10), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("password_enc", sa.Text(), nullable=True),
        sa.Column("from_address", sa.String(254), nullable=True),
        sa.Column("from_name", sa.String(120), nullable=True),
        sa.Column("reply_to", sa.String(254), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_table(
        "email_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoice.id"), nullable=True),
        sa.Column("customer_entity_id", sa.Integer(), nullable=True),
        sa.Column("to_address", sa.String(1000), nullable=False),
        sa.Column("cc_address", sa.String(1000), nullable=True),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("attachment_name", sa.String(255), nullable=True),
        sa.Column("attachment_sha256", sa.String(64), nullable=True),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("sent_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_email_log_workspace_id", "email_log", ["workspace_id"])
    op.create_index("ix_email_log_invoice_id", "email_log", ["invoice_id"])
    op.create_index("ix_email_log_customer_entity_id", "email_log", ["customer_entity_id"])


def downgrade() -> None:
    op.drop_table("email_log")
    op.drop_table("email_settings")
