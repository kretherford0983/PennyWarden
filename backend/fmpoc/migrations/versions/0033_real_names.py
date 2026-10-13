"""2.0.0 (#134): real names - app_user.first_name / last_name and audit_event.actor_name (all empty for existing
rows; existing audit events are never rewritten). app_user and audit_event carry triggers (0017), so plain
ADD COLUMN is used (no table copy).

Revision ID: 0033_real_names
Revises: 0032_reinitialize
"""
import sqlalchemy as sa
from alembic import op

revision = "0033_real_names"
down_revision = "0032_reinitialize"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("first_name", sa.String(60), nullable=True))
    op.add_column("app_user", sa.Column("last_name", sa.String(60), nullable=True))
    op.add_column("audit_event", sa.Column("actor_name", sa.String(130), nullable=True))


def downgrade() -> None:
    # SQLite 3.35+ drops a column in place (no table copy, the triggers stay)
    op.drop_column("audit_event", "actor_name")
    op.drop_column("app_user", "last_name")
    op.drop_column("app_user", "first_name")
