"""2.1.0 (#262): each user's register sort - app_user.register_sort ("<column>:<direction>", e.g. "clear_date:desc").
Empty for existing users, meaning the default (Date, oldest first). app_user carries triggers (0017), so plain ADD
COLUMN is used (no table copy).

Revision ID: 0035_register_sort
Revises: 0034_audit_labels
"""
import sqlalchemy as sa
from alembic import op

revision = "0035_register_sort"
down_revision = "0034_audit_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("register_sort", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("app_user", "register_sort")
