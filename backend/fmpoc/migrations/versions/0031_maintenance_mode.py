"""2.0.0 (#130): maintenance mode - four empty columns on workspace. No existing data changes.

Revision ID: 0031_maintenance_mode
Revises: 0030_session_client
"""
import sqlalchemy as sa
from alembic import op

revision = "0031_maintenance_mode"
down_revision = "0030_session_client"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace", sa.Column("maintenance_message", sa.Text(), nullable=True))
    op.add_column("workspace", sa.Column("maintenance_starts_at", sa.DateTime(), nullable=True))
    op.add_column("workspace", sa.Column("maintenance_set_by", sa.String(64), nullable=True))
    op.add_column("workspace", sa.Column("maintenance_set_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace") as b:
        for col in ("maintenance_set_at", "maintenance_set_by", "maintenance_starts_at", "maintenance_message"):
            b.drop_column(col)
