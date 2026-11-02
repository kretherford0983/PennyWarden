"""2.3.0 polish (Kyle, 2026-10-31): donation receipts and year-end statements can have their signer chosen when
printing. Each printed receipt/statement records who signed it, so a reprint can start from the same signer.
New nullable columns only (plain integers, like printed_by_user_id); nothing existing changes.

Revision ID: 0069_donation_signer_at_print
Revises: 0068_budget_inclusion
"""
import sqlalchemy as sa
from alembic import op

revision = "0069_donation_signer_at_print"
down_revision = "0068_budget_inclusion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("donation_receipt") as b:
        b.add_column(sa.Column("signer_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("donation_statement") as b:
        b.add_column(sa.Column("signer_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("donation_statement") as b:
        b.drop_column("signer_id")
    with op.batch_alter_table("donation_receipt") as b:
        b.drop_column("signer_id")
