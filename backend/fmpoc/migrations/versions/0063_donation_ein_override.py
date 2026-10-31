"""2.3.0 (#393): Include EIN on receipts - donation.ein_override_reason: the reason a donor's details include the EIN
while it is turned off for donations (empty for every existing donation). The option itself lives in the donation
setup settings (JSON) and defaults to on, so existing setups print as before.

Revision ID: 0063_donation_ein_override
Revises: 0062_estimated_years
"""
import sqlalchemy as sa
from alembic import op

revision = "0063_donation_ein_override"
down_revision = "0062_estimated_years"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("donation") as b:
        b.add_column(sa.Column("ein_override_reason", sa.String(500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("donation") as b:
        b.drop_column("ein_override_reason")
