"""2.0.0 (#133): audit_event.labels - the names of related records as they were when the event was written (empty
for existing events, which are never rewritten). Plain ADD COLUMN: audit_event carries the 0017 triggers.

Revision ID: 0034_audit_labels
Revises: 0033_real_names
"""
import sqlalchemy as sa
from alembic import op

revision = "0034_audit_labels"
down_revision = "0033_real_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_event", sa.Column("labels", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_event", "labels")
