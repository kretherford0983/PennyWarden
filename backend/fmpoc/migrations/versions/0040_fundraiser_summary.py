"""2.1.0 (#275): the fundraiser stakeholder report - fundraiser.summary_notes (narrative printed under the key
takeaways) and results_final_at / results_final_by_user_id (Mark results final). Plain ADD COLUMN, empty for every
existing fundraiser.

Revision ID: 0040_fundraiser_summary
Revises: 0039_bucket_categories
"""
import sqlalchemy as sa
from alembic import op

revision = "0040_fundraiser_summary"
down_revision = "0039_bucket_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fundraiser", sa.Column("summary_notes", sa.Text(), nullable=True))
    op.add_column("fundraiser", sa.Column("results_final_at", sa.DateTime(), nullable=True))
    op.add_column("fundraiser", sa.Column("results_final_by_user_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("fundraiser", "results_final_by_user_id")
    op.drop_column("fundraiser", "results_final_at")
    op.drop_column("fundraiser", "summary_notes")
