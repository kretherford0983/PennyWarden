"""2.1.0 (#277): fundraisers linked across years - fundraiser_series (the same event across years, created behind
the scenes when a fundraiser continues an earlier one), fundraiser.series_id / continues_from_id, results of years
before PennyWarden entered by hand (fundraiser_series_result, retired - never deleted) and the Fiscal Year
fundraising report's remembered notes (fundraiser_fy_report_note). New tables and empty columns only.

Revision ID: 0041_fundraiser_series
Revises: 0040_fundraiser_summary
"""
import sqlalchemy as sa
from alembic import op

revision = "0041_fundraiser_series"
down_revision = "0040_fundraiser_summary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundraiser_series",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("group_as_other", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("merged_into_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column("fundraiser", sa.Column("series_id", sa.Integer(), nullable=True))
    op.add_column("fundraiser", sa.Column("continues_from_id", sa.Integer(), nullable=True))
    op.create_index("ix_fundraiser_series_id", "fundraiser", ["series_id"])
    op.create_table(
        "fundraiser_series_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("series_id", sa.Integer(), sa.ForeignKey("fundraiser_series.id"), nullable=False, index=True),
        sa.Column("fiscal_year_label", sa.String(40), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("net_cents", sa.BigInteger(), nullable=False),
        sa.Column("income_cents", sa.BigInteger(), nullable=True),
        sa.Column("expense_cents", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.Column("retired_by_user_id", sa.Integer(), nullable=True),
        sa.Column("retire_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_table(
        "fundraiser_fy_report_note",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id"), nullable=False, index=True),
        sa.Column("fiscal_year_id", sa.Integer(), sa.ForeignKey("fiscal_year.id"), nullable=False, unique=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("fundraiser_fy_report_note")
    op.drop_table("fundraiser_series_result")
    op.drop_index("ix_fundraiser_series_id", table_name="fundraiser")
    op.drop_column("fundraiser", "continues_from_id")
    op.drop_column("fundraiser", "series_id")
    op.drop_table("fundraiser_series")
