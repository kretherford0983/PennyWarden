"""2.1.0 (#247): check_printer_setting.fold_marks - a user's own default for cover-letter fold marks (FRONT or BACK;
empty = the template's setting), on a row with feed_key "letter". The template settings live in its JSON config
(fold_marks NONE after the upgrade, so letters print as before). Plain ADD COLUMN.

Revision ID: 0044_letter_fold_marks
Revises: 0043_line_contributor
"""
import sqlalchemy as sa
from alembic import op

revision = "0044_letter_fold_marks"
down_revision = "0043_line_contributor"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("check_printer_setting", sa.Column("fold_marks", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("check_printer_setting", "fold_marks")
