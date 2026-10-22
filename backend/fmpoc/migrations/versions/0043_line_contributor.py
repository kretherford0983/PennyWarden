"""2.1.0 (#303): fundraiser_line_contributor - the contributor shown on the fundraiser reports for the part of a line
that is in no bucket ("Other", or every line of a fundraiser without buckets), like the per-bucket override of 0042.
A new, empty table: nothing existing changes.

Revision ID: 0043_line_contributor
Revises: 0042_bucket_contributor
"""
import sqlalchemy as sa
from alembic import op

revision = "0043_line_contributor"
down_revision = "0042_bucket_contributor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundraiser_line_contributor",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fundraiser_id", sa.Integer, sa.ForeignKey("fundraiser.id"), nullable=False),
        sa.Column("allocation_id", sa.Integer, sa.ForeignKey("transaction_allocation.id"), nullable=False),
        sa.Column("contributor_override", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("created_by_user_id", sa.Integer, nullable=True),
        sa.UniqueConstraint("fundraiser_id", "allocation_id", name="uq_fundraiser_line_contributor"),
    )
    op.create_index("ix_fundraiser_line_contributor_fundraiser_id", "fundraiser_line_contributor", ["fundraiser_id"])


def downgrade() -> None:
    op.drop_index("ix_fundraiser_line_contributor_fundraiser_id", table_name="fundraiser_line_contributor")
    op.drop_table("fundraiser_line_contributor")
