"""2.2.0 (#243): the demo marker workspace.demo_mode (off). Set only by scripts/build_demo.py. Addition only.

Revision ID: 0051_demo_mode
Revises: 0050_testing_state
"""
import sqlalchemy as sa
from alembic import op

revision = "0051_demo_mode"
down_revision = "0050_testing_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace", sa.Column("demo_mode", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("workspace") as b:
        b.drop_column("demo_mode")
