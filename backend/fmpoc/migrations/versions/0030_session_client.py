"""2.0.0 (#127): auth_session.client_ip - the client address of a session's latest request, for the Administrators'
sessions list. Empty for existing sessions; no other data changes.

Revision ID: 0030_session_client
Revises: 0029_backup_warning
"""
import sqlalchemy as sa
from alembic import op

revision = "0030_session_client"
down_revision = "0029_backup_warning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auth_session", sa.Column("client_ip", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("auth_session") as b:
        b.drop_column("client_ip")
