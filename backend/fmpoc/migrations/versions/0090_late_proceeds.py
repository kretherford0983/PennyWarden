"""2.5.0 (#588): events whose proceeds are paid later by an outside organization.

On the event: the "proceeds paid later" flag with an optional expected payer (entity) and month, and how the wait
ended (all proceeds received / no proceeds received, with a reason). A new table links the deposit lines that are the
event's proceeds, received in a later Fiscal Year against any Income budget. Links are retired, never deleted (BR-001).

Revision ID: 0090_late_proceeds
Revises: 0089_reminder_tasks
"""
import sqlalchemy as sa
from alembic import op

revision = "0090_late_proceeds"
down_revision = "0089_reminder_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fundraiser") as b:
        b.add_column(sa.Column("proceeds_later", sa.Boolean, nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("proceeds_payer_entity_id", sa.Integer, nullable=True))
        b.add_column(sa.Column("proceeds_expected_month", sa.String(7), nullable=True))
        b.add_column(sa.Column("proceeds_outcome", sa.String(10), nullable=True))
        b.add_column(sa.Column("proceeds_outcome_reason", sa.String(500), nullable=True))
        b.add_column(sa.Column("proceeds_outcome_at", sa.DateTime, nullable=True))
        b.add_column(sa.Column("proceeds_outcome_by_user_id", sa.Integer, nullable=True))
    op.create_table(
        "fundraiser_proceeds_line",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fundraiser_id", sa.Integer, sa.ForeignKey("fundraiser.id"), nullable=False),
        sa.Column("allocation_id", sa.Integer, sa.ForeignKey("transaction_allocation.id"), nullable=False),
        sa.Column("linked_at", sa.DateTime, nullable=False),
        sa.Column("linked_by_user_id", sa.Integer, nullable=True),
        sa.Column("retired_at", sa.DateTime, nullable=True),
        sa.Column("retired_by_user_id", sa.Integer, nullable=True),
        sa.Column("retire_reason", sa.String(500), nullable=True),
    )
    op.create_index("ix_fundraiser_proceeds_line_fundraiser_id", "fundraiser_proceeds_line", ["fundraiser_id"])
    op.create_index("ix_fundraiser_proceeds_line_allocation_id", "fundraiser_proceeds_line", ["allocation_id"])


def downgrade() -> None:
    op.drop_index("ix_fundraiser_proceeds_line_allocation_id", "fundraiser_proceeds_line")
    op.drop_index("ix_fundraiser_proceeds_line_fundraiser_id", "fundraiser_proceeds_line")
    op.drop_table("fundraiser_proceeds_line")
    with op.batch_alter_table("fundraiser") as b:
        for c in ("proceeds_outcome_by_user_id", "proceeds_outcome_at", "proceeds_outcome_reason", "proceeds_outcome",
                  "proceeds_expected_month", "proceeds_payer_entity_id", "proceeds_later"):
            b.drop_column(c)
