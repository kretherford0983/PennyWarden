"""2.0.0 (#126): workspace.backup_warning_days - the days without a backup before Administrators are warned
(default 7, 0 = off). No existing data changes.

Revision ID: 0029_backup_warning
Revises: 0028_letter_logo
"""
import sqlalchemy as sa
from alembic import op

revision = "0029_backup_warning"
down_revision = "0028_letter_logo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace", sa.Column("backup_warning_days", sa.Integer(), nullable=False, server_default="7"))


def downgrade() -> None:
    with op.batch_alter_table("workspace") as b:
        b.drop_column("backup_warning_days")
