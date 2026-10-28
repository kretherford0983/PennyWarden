"""2.2.0 (#256): year-end giving statements and fundraiser donation buckets.

- `donation_statement`: a printed year-end giving statement for one donor and one calendar year, numbered per year
  (S-2026-0001) like receipts: ORIGINAL, DUPLICATE (same content: same number) or CORRECTED (new number, replaces one).
- `attachment.donation_statement_id`: the statement's kept copy (and its envelope).
- `fundraiser_bucket.is_donation`: a bucket that holds donations; deposits classified into it get the Donation box
  pre-ticked as a suggestion.
Additions only.

Revision ID: 0056_year_end_statements
Revises: 0055_envelope_library
"""
import sqlalchemy as sa
from alembic import op

revision = "0056_year_end_statements"
down_revision = "0055_envelope_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "donation_statement",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspace.id"), nullable=False, index=True),
        sa.Column("donor_entity_id", sa.Integer, sa.ForeignKey("entity.id"), nullable=False, index=True),
        sa.Column("donor_name", sa.String(200), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("number", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("replaces_id", sa.Integer, sa.ForeignKey("donation_statement.id"), nullable=True),
        sa.Column("total_cents", sa.BigInteger, nullable=False),
        sa.Column("goods_cents", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("gifts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("items", sa.Integer, nullable=False, server_default="0"),
        sa.Column("line_ids", sa.Text, nullable=False, server_default=""),
        sa.Column("content_sha", sa.String(64), nullable=False),
        sa.Column("attachment_id", sa.Integer, sa.ForeignKey("attachment.id"), nullable=True),
        sa.Column("printed_at", sa.DateTime, nullable=False),
        sa.Column("printed_by_user_id", sa.Integer, nullable=True),
    )
    op.create_index("ix_donation_statement_year", "donation_statement", ["workspace_id", "year"])
    with op.batch_alter_table("attachment") as b:
        b.add_column(sa.Column("donation_statement_id", sa.Integer, nullable=True))
        b.create_index("ix_attachment_donation_statement_id", ["donation_statement_id"])
    with op.batch_alter_table("fundraiser_bucket") as b:
        b.add_column(sa.Column("is_donation", sa.Boolean, nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("fundraiser_bucket") as b:
        b.drop_column("is_donation")
    with op.batch_alter_table("attachment") as b:
        b.drop_index("ix_attachment_donation_statement_id")
        b.drop_column("donation_statement_id")
    op.drop_index("ix_donation_statement_year", "donation_statement")
    op.drop_table("donation_statement")
