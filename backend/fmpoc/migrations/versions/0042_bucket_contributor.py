"""2.1.0 (#278 feedback): fundraiser_bucket_line.contributor_override - the name shown as the contributor on the
fundraiser reports for that bucket's part of a line (e.g. "Cash" for lump cash the organization collected, or the
name people know a business by). Plain ADD COLUMN, empty for every existing assignment.

Revision ID: 0042_bucket_contributor
Revises: 0041_fundraiser_series
"""
import sqlalchemy as sa
from alembic import op

revision = "0042_bucket_contributor"
down_revision = "0041_fundraiser_series"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fundraiser_bucket_line", sa.Column("contributor_override", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("fundraiser_bucket_line", "contributor_override")
