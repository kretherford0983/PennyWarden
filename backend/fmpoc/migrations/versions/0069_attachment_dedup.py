"""2.4.0 (#425): attachment deduplication. A stored file may now be shared by several attachment records (identical
content stored once per workspace), so storage_key is no longer unique; an index on (workspace_id, sha256) finds a
match. No row changes here: existing duplicates are merged at start-up after the migrations
(services/attachments.merge_duplicate_files), which verifies each file's hash first.

Revision ID: 0069_attachment_dedup
Revises: 0068_budget_inclusion
"""
from alembic import op

revision = "0069_attachment_dedup"
down_revision = "0068_budget_inclusion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("attachment") as b:
        b.drop_constraint("uq_attachment_storage_key", type_="unique")
        b.create_index("ix_attachment_storage_key", ["storage_key"])
        b.create_index("ix_attachment_workspace_sha256", ["workspace_id", "sha256"])


def downgrade() -> None:  # only valid while no file is shared
    with op.batch_alter_table("attachment") as b:
        b.drop_index("ix_attachment_workspace_sha256")
        b.drop_index("ix_attachment_storage_key")
        b.create_unique_constraint("uq_attachment_storage_key", ["storage_key"])
