"""2.3.0 (#372): an optional fundraiser goal - fundraiser.goal_amount_cents (None = no goal; informational only).

Revision ID: 0060_fundraiser_goal
Revises: 0059_former_budget
"""
import sqlalchemy as sa
from alembic import op

revision = "0060_fundraiser_goal"
down_revision = "0059_former_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fundraiser") as b:
        b.add_column(sa.Column("goal_amount_cents", sa.Integer, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("fundraiser") as b:
        b.drop_column("goal_amount_cents")
