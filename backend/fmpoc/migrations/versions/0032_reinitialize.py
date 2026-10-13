"""2.0.0 (#125): reinitialize - five empty columns on workspace (who reinitialized, when, the safety backup, and the
acknowledgement of the banner). No existing data changes.

Revision ID: 0032_reinitialize
Revises: 0031_maintenance_mode
"""
import sqlalchemy as sa
from alembic import op

revision = "0032_reinitialize"
down_revision = "0031_maintenance_mode"
branch_labels = None
depends_on = None

COLS = (("reinitialized_at", sa.DateTime()), ("reinitialized_by", sa.String(64)),
        ("reinitialize_backup", sa.String(255)), ("reinitialize_ack_at", sa.DateTime()),
        ("reinitialize_ack_by", sa.String(64)))


def upgrade() -> None:
    for name, type_ in COLS:
        op.add_column("workspace", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspace") as b:
        for name, _t in reversed(COLS):
            b.drop_column(name)
