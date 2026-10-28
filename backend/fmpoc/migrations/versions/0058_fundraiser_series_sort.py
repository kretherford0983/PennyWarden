"""2.2.0 (#351): each user's Fundraiser series sort - app_user.fundraiser_series_sort ("asc"; None = newest first).

Revision ID: 0058_fundraiser_series_sort
Revises: 0057_entity_names
"""
import sqlalchemy as sa
from alembic import op

revision = "0058_fundraiser_series_sort"
down_revision = "0057_entity_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("app_user") as b:
        b.add_column(sa.Column("fundraiser_series_sort", sa.String(4), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("app_user") as b:
        b.drop_column("fundraiser_series_sort")
