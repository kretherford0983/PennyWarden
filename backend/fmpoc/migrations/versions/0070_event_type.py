"""2.4.0 (#429): Events & Fundraisers - each event is a Fundraiser or an Event. Every existing record becomes a
Fundraiser (server default). Nothing else changes; internal names (tables, API paths, audit object types) stay.

Revision ID: 0070_event_type
Revises: 0069_attachment_dedup
"""
import sqlalchemy as sa
from alembic import op

revision = "0070_event_type"
down_revision = "0069_attachment_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fundraiser") as b:
        b.add_column(sa.Column("event_type", sa.String(20), nullable=False, server_default="FUNDRAISER"))


def downgrade() -> None:
    with op.batch_alter_table("fundraiser") as b:
        b.drop_column("event_type")
