"""2.2.0 (#325): one shared envelope library, tagged by feature. check_document.features (the features a template is
used for: PAYMENTS, DONATIONS) and default_for (the features it is the default for). Every existing template is
tagged Payments, and the Payments defaults stay the defaults. Addition only.

Revision ID: 0055_envelope_library
Revises: 0054_donations_part2
"""
import sqlalchemy as sa
from alembic import op

revision = "0055_envelope_library"
down_revision = "0054_donations_part2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("check_document") as b:
        b.add_column(sa.Column("features", sa.String(60), nullable=True))
        b.add_column(sa.Column("default_for", sa.String(60), nullable=True))
    op.execute("UPDATE check_document SET features = 'PAYMENTS'")
    op.execute("UPDATE check_document SET default_for = 'PAYMENTS' WHERE is_default = 1")


def downgrade() -> None:
    with op.batch_alter_table("check_document") as b:
        b.drop_column("default_for")
        b.drop_column("features")
