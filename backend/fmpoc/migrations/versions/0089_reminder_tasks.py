"""2.4.0 (#551): reminder tasks - a checklist on a reminder, each task with an optional contact (a fixed entity or a
position) and an optional app function to open.

Revision ID: 0089_reminder_tasks
Revises: 0088_invoice_email_sender
"""
import sqlalchemy as sa
from alembic import op

revision = "0089_reminder_tasks"
down_revision = "0088_invoice_email_sender"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reminder_task",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("reminder_id", sa.Integer, sa.ForeignKey("reminder.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False, server_default="0"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("done_at", sa.DateTime, nullable=True),
        sa.Column("done_by_user_id", sa.Integer, nullable=True),
        sa.Column("contact_kind", sa.String(8), nullable=True),
        sa.Column("contact_entity_id", sa.Integer, nullable=True),
        sa.Column("contact_position", sa.String(60), nullable=True),
        sa.Column("function_id", sa.String(48), nullable=True),
    )
    op.create_index("ix_reminder_task_reminder_id", "reminder_task", ["reminder_id"])


def downgrade() -> None:
    op.drop_index("ix_reminder_task_reminder_id", "reminder_task")
    op.drop_table("reminder_task")
