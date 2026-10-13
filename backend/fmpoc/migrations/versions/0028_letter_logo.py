"""2.0.0 (#176): an optional logo on cover letter templates - four empty columns on check_document. No existing data
changes.

Revision ID: 0028_letter_logo
Revises: 0027_letters_envelopes
"""
import sqlalchemy as sa
from alembic import op

revision = "0028_letter_logo"
down_revision = "0027_letters_envelopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("check_document", sa.Column("logo_png", sa.LargeBinary(), nullable=True))
    op.add_column("check_document", sa.Column("logo_sha256", sa.String(64), nullable=True))
    op.add_column("check_document", sa.Column("logo_width", sa.Integer(), nullable=True))
    op.add_column("check_document", sa.Column("logo_height", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("check_document") as b:
        for col in ("logo_height", "logo_width", "logo_sha256", "logo_png"):
            b.drop_column(col)
