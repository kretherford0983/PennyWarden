"""2.2.0 (#315, #316): entity display name, mailing address and EIN; first and last name; a name order per user.

- `entity.display_name_custom`: the display name when *Display name same as Name* is unticked (empty = same).
- `entity.mailing_*`: the mailing address when *Mailing address same as Address* is unticked (all empty = same).
  "Same as" falls back at read time (Kyle, 2026-10-22): nothing is copied.
- `entity.first_name`, `entity.last_name` replace `primary_contact` (the person of an Individual, the contact person of
  an Organization). The migration trims the Primary Contact and splits it at the first space (one word = first name);
  every split name is listed in *Names to review* (`name_review`) until it is edited or confirmed.
- `app_user.name_order`: FIRST_LAST (default) or LAST_FIRST - how each user sees and sorts Individuals.

Revision ID: 0057_entity_names
Revises: 0056_year_end_statements
"""
import sqlalchemy as sa
from alembic import op

revision = "0057_entity_names"
down_revision = "0056_year_end_statements"
branch_labels = None
depends_on = None

MAILING = ("mailing_address_line1", "mailing_address_line2", "mailing_city", "mailing_state_region",
           "mailing_postal_code", "mailing_country")
SIZES = {"mailing_address_line1": 200, "mailing_address_line2": 200, "mailing_city": 100,
         "mailing_state_region": 100, "mailing_postal_code": 20, "mailing_country": 100}


def upgrade() -> None:
    with op.batch_alter_table("entity") as b:
        b.add_column(sa.Column("display_name_custom", sa.String(200), nullable=True))
        for c in MAILING:
            b.add_column(sa.Column(c, sa.String(SIZES[c]), nullable=True))
        b.add_column(sa.Column("first_name", sa.String(100), nullable=True))
        b.add_column(sa.Column("last_name", sa.String(100), nullable=True))
        b.add_column(sa.Column("name_review", sa.Boolean, nullable=False, server_default=sa.false()))
    con = op.get_bind()
    rows = con.execute(sa.text("SELECT id, primary_contact FROM entity WHERE primary_contact IS NOT NULL")).fetchall()
    for eid, contact in rows:
        name = " ".join((contact or "").split())
        if not name:
            continue
        first, _, last = name.partition(" ")
        con.execute(sa.text("UPDATE entity SET first_name = :f, last_name = :l, name_review = :r WHERE id = :i"),
                    {"f": first[:100], "l": (last or None) and last[:100], "r": True, "i": eid})
    with op.batch_alter_table("entity") as b:
        b.drop_column("primary_contact")
    with op.batch_alter_table("app_user") as b:
        b.add_column(sa.Column("name_order", sa.String(12), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("app_user") as b:
        b.drop_column("name_order")
    with op.batch_alter_table("entity") as b:
        b.add_column(sa.Column("primary_contact", sa.String(200), nullable=True))
    op.execute("UPDATE entity SET primary_contact = TRIM(COALESCE(first_name, '') || ' ' || COALESCE(last_name, '')) "
               "WHERE first_name IS NOT NULL OR last_name IS NOT NULL")
    with op.batch_alter_table("entity") as b:
        b.drop_column("name_review")
        b.drop_column("last_name")
        b.drop_column("first_name")
        for c in reversed(MAILING):
            b.drop_column(c)
        b.drop_column("display_name_custom")
