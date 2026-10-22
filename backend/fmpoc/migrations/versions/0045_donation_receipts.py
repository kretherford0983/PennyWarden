"""2.1.0 (#312): the Donations module, part 1 - donation receipt letters. workspace.donations_enabled (off), and the
tables donation_settings (EIN, address, receipt template), donation_line (a deposit allocation marked as a donation)
and donation_receipt (every printed receipt). Additions only: nothing existing changes.

Revision ID: 0045_donation_receipts
Revises: 0044_letter_fold_marks
"""
import sqlalchemy as sa
from alembic import op

revision = "0045_donation_receipts"
down_revision = "0044_letter_fold_marks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspace") as b:
        b.add_column(sa.Column("donations_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "donation_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspace.id"), nullable=False, unique=True),
        sa.Column("config_json", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("updated_by_user_id", sa.Integer, nullable=True),
    )
    op.create_table(
        "donation_line",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("allocation_id", sa.Integer, sa.ForeignKey("transaction_allocation.id"), nullable=False),
        sa.Column("purpose", sa.String(200), nullable=True),
        sa.Column("goods_cents", sa.BigInteger, nullable=True),
        sa.Column("goods_description", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("created_by_user_id", sa.Integer, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("updated_by_user_id", sa.Integer, nullable=True),
        sa.UniqueConstraint("allocation_id", name="uq_donation_line_allocation"),
    )
    op.create_index("ix_donation_line_workspace_id", "donation_line", ["workspace_id"])
    op.create_table(
        "donation_receipt",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("transaction_id", sa.Integer, sa.ForeignKey("register_transaction.id"), nullable=False),
        sa.Column("donor_entity_id", sa.Integer, sa.ForeignKey("entity.id"), nullable=False),
        sa.Column("donor_name", sa.String(200), nullable=False),
        sa.Column("number", sa.String(20), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("replaces_id", sa.Integer, sa.ForeignKey("donation_receipt.id"), nullable=True),
        sa.Column("amount_cents", sa.BigInteger, nullable=False),
        sa.Column("goods_cents", sa.BigInteger, nullable=False),
        sa.Column("date_received", sa.Date, nullable=False),
        sa.Column("allocation_ids", sa.String(500), nullable=False),
        sa.Column("content_sha", sa.String(64), nullable=False),
        sa.Column("attachment_id", sa.Integer, sa.ForeignKey("attachment.id"), nullable=True),
        sa.Column("printed_at", sa.DateTime, nullable=False),
        sa.Column("printed_by_user_id", sa.Integer, nullable=True),
    )
    op.create_index("ix_donation_receipt_workspace_id", "donation_receipt", ["workspace_id"])
    op.create_index("ix_donation_receipt_transaction_id", "donation_receipt", ["transaction_id"])


def downgrade() -> None:
    op.drop_index("ix_donation_receipt_transaction_id", table_name="donation_receipt")
    op.drop_index("ix_donation_receipt_workspace_id", table_name="donation_receipt")
    op.drop_table("donation_receipt")
    op.drop_index("ix_donation_line_workspace_id", table_name="donation_line")
    op.drop_table("donation_line")
    op.drop_table("donation_settings")
    with op.batch_alter_table("workspace") as b:
        b.drop_column("donations_enabled")
