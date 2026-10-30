"""2.2.0 (#325): Donations part 2 - one donation model for both flows.

- New table `donation`: the receipt's unit (donor, the {DETAILS} text, where it started - the Donations page or a
  deposit -, Cancelled with a reason; never deleted).
- `donation_line`: belongs to a donation; money or an item; a money line links to a deposit allocation (empty =
  awaiting deposit) and keeps its own amount until then; an item has an optional estimated value (not printed),
  Received, and "No value will be provided" with a reason.
- `donation_receipt`: belongs to a donation; the deposit is empty for a donation not yet linked to one; the date
  received is empty when the receipt printed it blank.
- `attachment.donation_id`: printed receipts (and envelopes) of a donation not linked to a deposit.

Data: every part 1 donation (the donation lines of one donor on one deposit) becomes a donation that started from the
deposit, with its lines, details and receipts. No amount, date or receipt changes.

Revision ID: 0054_donations_part2
Revises: 0053_branding
"""
import sqlalchemy as sa
from alembic import op

revision = "0054_donations_part2"
down_revision = "0053_branding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "donation",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("donor_entity_id", sa.Integer, sa.ForeignKey("entity.id"), nullable=False),
        sa.Column("origin", sa.String(10), nullable=False),               # PAGE | DEPOSIT
        sa.Column("transaction_id", sa.Integer, nullable=True),           # DEPOSIT: the deposit it was marked on
        sa.Column("status", sa.String(10), nullable=False, server_default="ACTIVE"),   # ACTIVE | CANCELLED
        sa.Column("cancel_reason", sa.String(500), nullable=True),
        sa.Column("cancelled_at", sa.DateTime, nullable=True),
        sa.Column("cancelled_by_user_id", sa.Integer, nullable=True),
        sa.Column("details", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("created_by_user_id", sa.Integer, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("updated_by_user_id", sa.Integer, nullable=True),
    )
    op.create_index("ix_donation_workspace_id", "donation", ["workspace_id"])
    op.create_index("ix_donation_transaction_id", "donation", ["transaction_id"])
    with op.batch_alter_table("donation_line") as b:
        b.add_column(sa.Column("donation_id", sa.Integer, nullable=True))
        b.add_column(sa.Column("kind", sa.String(6), nullable=False, server_default="MONEY"))     # MONEY | ITEM
        b.add_column(sa.Column("amount_cents", sa.BigInteger, nullable=True))
        b.add_column(sa.Column("description", sa.String(200), nullable=True))
        b.add_column(sa.Column("item_received", sa.Boolean, nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("item_no_value", sa.Boolean, nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("item_no_value_reason", sa.String(500), nullable=True))
        b.alter_column("allocation_id", existing_type=sa.Integer, nullable=True)
        b.create_index("ix_donation_line_donation_id", ["donation_id"])
    with op.batch_alter_table("donation_receipt") as b:
        b.add_column(sa.Column("donation_id", sa.Integer, nullable=True))
        b.alter_column("transaction_id", existing_type=sa.Integer, nullable=True)
        b.alter_column("date_received", existing_type=sa.Date, nullable=True)
        b.create_index("ix_donation_receipt_donation_id", ["donation_id"])
    with op.batch_alter_table("attachment") as b:
        b.add_column(sa.Column("donation_id", sa.Integer, nullable=True))
        b.create_index("ix_attachment_donation_id", ["donation_id"])

    con = op.get_bind()
    # every (deposit, donor) with marked lines becomes a donation that started from the deposit
    rows = con.execute(sa.text(
        "SELECT dl.id, dl.workspace_id, t.id, COALESCE(a.entity_id, t.parent_entity_id), dl.created_at, "
        "dl.created_by_user_id, dl.updated_at, dl.updated_by_user_id "
        "FROM donation_line dl JOIN transaction_allocation a ON a.id = dl.allocation_id "
        "JOIN register_transaction t ON t.id = a.transaction_id ORDER BY dl.id")).fetchall()
    made: dict[tuple[int, int], int] = {}
    for line_id, ws, txn, donor, created, created_by, updated, updated_by in rows:
        if donor is None:
            continue
        key = (txn, donor)
        if key not in made:
            res = con.execute(sa.text(
                "INSERT INTO donation (workspace_id, donor_entity_id, origin, transaction_id, status, created_at, "
                "created_by_user_id, updated_at, updated_by_user_id) VALUES (:ws, :donor, 'DEPOSIT', :txn, 'ACTIVE', "
                ":c, :cb, :u, :ub)"), {"ws": ws, "donor": donor, "txn": txn, "c": created, "cb": created_by,
                                       "u": updated, "ub": updated_by})
            made[key] = res.lastrowid
        con.execute(sa.text("UPDATE donation_line SET donation_id = :d WHERE id = :i"), {"d": made[key], "i": line_id})
    for (txn, donor), did in made.items():
        con.execute(sa.text("UPDATE donation_receipt SET donation_id = :d WHERE transaction_id = :t AND "
                            "donor_entity_id = :e"), {"d": did, "t": txn, "e": donor})
        det = con.execute(sa.text("SELECT details FROM donation_detail WHERE transaction_id = :t AND "
                                  "donor_entity_id = :e"), {"t": txn, "e": donor}).fetchone()
        if det is not None:
            con.execute(sa.text("UPDATE donation SET details = :x WHERE id = :d"), {"x": det[0], "d": did})
    # receipts of a donor whose lines were all unmarked later: their own donation, so nothing is left without one
    orphans = con.execute(sa.text(
        "SELECT DISTINCT r.workspace_id, r.transaction_id, r.donor_entity_id, MIN(r.printed_at) FROM donation_receipt r "
        "WHERE r.donation_id IS NULL GROUP BY r.workspace_id, r.transaction_id, r.donor_entity_id")).fetchall()
    for ws, txn, donor, printed in orphans:
        res = con.execute(sa.text(
            "INSERT INTO donation (workspace_id, donor_entity_id, origin, transaction_id, status, created_at, "
            "updated_at) VALUES (:ws, :donor, 'DEPOSIT', :txn, 'ACTIVE', :c, :c)"),
            {"ws": ws, "donor": donor, "txn": txn, "c": printed})
        con.execute(sa.text("UPDATE donation_receipt SET donation_id = :d WHERE transaction_id = :t AND "
                            "donor_entity_id = :e AND donation_id IS NULL"),
                    {"d": res.lastrowid, "t": txn, "e": donor})
    con.execute(sa.text("DELETE FROM donation_line WHERE donation_id IS NULL"))   # lines without any donor (none)


def downgrade() -> None:
    with op.batch_alter_table("attachment") as b:
        b.drop_index("ix_attachment_donation_id")
        b.drop_column("donation_id")
    with op.batch_alter_table("donation_receipt") as b:
        b.drop_index("ix_donation_receipt_donation_id")
        b.drop_column("donation_id")
    with op.batch_alter_table("donation_line") as b:
        b.drop_index("ix_donation_line_donation_id")
        for c in ("item_no_value_reason", "item_no_value", "item_received", "description", "amount_cents", "kind",
                  "donation_id"):
            b.drop_column(c)
    op.drop_index("ix_donation_transaction_id", table_name="donation")
    op.drop_index("ix_donation_workspace_id", table_name="donation")
    op.drop_table("donation")
