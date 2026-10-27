"""2.2.0 (#327): two-step verification set up with the user's own authenticator key. Two columns on user_mfa, additions
only: new_key_required (a reset marked as a possible compromise: the next setup accepts only a newly generated key)
and pending_own_key (the pending setup uses a key the user supplied, recorded as own_key on MFA_ENROLLED/CHANGED).

Revision ID: 0048_mfa_own_key
Revises: 0047_donation_date_details
"""
import sqlalchemy as sa
from alembic import op

revision = "0048_mfa_own_key"
down_revision = "0047_donation_date_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_mfa", sa.Column("new_key_required", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("user_mfa", sa.Column("pending_own_key", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("user_mfa") as b:
        b.drop_column("pending_own_key")
        b.drop_column("new_key_required")
