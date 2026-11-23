"""2.5.0 (#594): a resolved reminder can point to the transaction or event that resolved it.

Revision ID: 0091_reminder_resolution_link
Revises: 0090_late_proceeds
"""
import sqlalchemy as sa
from alembic import op

revision = "0091_reminder_resolution_link"
down_revision = "0090_late_proceeds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("reminder") as b:
        b.add_column(sa.Column("resolution_link_type", sa.String(16), nullable=True))
        b.add_column(sa.Column("resolution_link_id", sa.Integer, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("reminder") as b:
        b.drop_column("resolution_link_id")
        b.drop_column("resolution_link_type")
