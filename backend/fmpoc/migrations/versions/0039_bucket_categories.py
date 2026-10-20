"""2.1.0 (#278): fundraiser bucket categories, the display order of buckets and categories, and Charge / Less on a
bucket assignment.

* New table fundraiser_bucket_category (name, description, display_order).
* fundraiser_bucket.category_id (empty = uncategorized) and fundraiser_bucket.display_order. Existing buckets are
  numbered in the order they are listed today (name, then id), so nothing looks different until someone reorders.
* fundraiser_bucket_line.charge_cents, less_cents (0) and less_description. Existing assignments get
  charge = their amount and less = 0; amount_cents stays the net (charge - less), so every figure is unchanged.

Revision ID: 0039_bucket_categories
Revises: 0038_projection_choices
"""
import sqlalchemy as sa
from alembic import op

revision = "0039_bucket_categories"
down_revision = "0038_projection_choices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fundraiser_bucket_category",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fundraiser_id", sa.Integer(), sa.ForeignKey("fundraiser.id"), nullable=False, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column("fundraiser_bucket", sa.Column("category_id", sa.Integer(), nullable=True))
    op.add_column("fundraiser_bucket", sa.Column("display_order", sa.Integer(), nullable=True))
    op.create_index("ix_fundraiser_bucket_category_id", "fundraiser_bucket", ["category_id"])
    op.add_column("fundraiser_bucket_line", sa.Column("charge_cents", sa.BigInteger(), nullable=True))
    op.add_column("fundraiser_bucket_line", sa.Column("less_cents", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("fundraiser_bucket_line", sa.Column("less_description", sa.String(200), nullable=True))
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE fundraiser_bucket_line SET charge_cents = amount_cents, less_cents = 0"))
    rows = conn.execute(sa.text("SELECT id, fundraiser_id FROM fundraiser_bucket ORDER BY fundraiser_id, name, id")).fetchall()
    pos: dict[int, int] = {}
    for bid, fid in rows:
        pos[fid] = pos.get(fid, 0) + 1
        conn.execute(sa.text("UPDATE fundraiser_bucket SET display_order = :o WHERE id = :i"), {"o": pos[fid], "i": bid})


def downgrade() -> None:
    op.drop_column("fundraiser_bucket_line", "less_description")
    op.drop_column("fundraiser_bucket_line", "less_cents")
    op.drop_column("fundraiser_bucket_line", "charge_cents")
    op.drop_index("ix_fundraiser_bucket_category_id", table_name="fundraiser_bucket")
    op.drop_column("fundraiser_bucket", "display_order")
    op.drop_column("fundraiser_bucket", "category_id")
    op.drop_table("fundraiser_bucket_category")
