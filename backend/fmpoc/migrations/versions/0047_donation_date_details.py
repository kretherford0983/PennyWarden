"""2.1.0 (Kyle, 2026-10-22): donation polish. donation_line.date_received (empty = the deposit's date) and the table
donation_detail (the {DETAILS} text per donor and deposit). Additions only.

Revision ID: 0047_donation_date_details
Revises: 0046_organization_entity
"""
import sqlalchemy as sa
from alembic import op

revision = "0047_donation_date_details"
down_revision = "0046_organization_entity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("donation_line") as b:
        b.add_column(sa.Column("date_received", sa.Date(), nullable=True))
    op.create_table(
        "donation_detail",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("transaction_id", sa.Integer, sa.ForeignKey("register_transaction.id"), nullable=False),
        sa.Column("donor_entity_id", sa.Integer, sa.ForeignKey("entity.id"), nullable=False),
        sa.Column("details", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("updated_by_user_id", sa.Integer, nullable=True),
        sa.UniqueConstraint("transaction_id", "donor_entity_id", name="uq_donation_detail_donor"),
    )
    op.create_index("ix_donation_detail_workspace_id", "donation_detail", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_donation_detail_workspace_id", table_name="donation_detail")
    op.drop_table("donation_detail")
    with op.batch_alter_table("donation_line") as b:
        b.drop_column("date_received")
