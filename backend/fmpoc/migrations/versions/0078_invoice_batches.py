"""2.4.0 (#248): batch invoicing - the empty table invoice_batch and invoice.batch_id (empty).

Revision ID: 0078_invoice_batches
Revises: 0077_invoice_overdue_reminder
"""
import sqlalchemy as sa
from alembic import op

revision = "0078_invoice_batches"
down_revision = "0077_invoice_overdue_reminder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_batch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_invoice_batch_workspace_id", "invoice_batch", ["workspace_id"])
    with op.batch_alter_table("invoice") as b:
        b.add_column(sa.Column("batch_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_invoice_batch_id", "invoice_batch", ["batch_id"], ["id"])
        b.create_index("ix_invoice_batch_id", ["batch_id"])


def downgrade() -> None:
    with op.batch_alter_table("invoice") as b:
        b.drop_index("ix_invoice_batch_id")
        b.drop_constraint("fk_invoice_batch_id", type_="foreignkey")
        b.drop_column("batch_id")
    op.drop_index("ix_invoice_batch_workspace_id", "invoice_batch")
    op.drop_table("invoice_batch")
