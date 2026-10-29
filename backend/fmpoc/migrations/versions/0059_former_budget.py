"""2.2.0 (#381): budgets from before PennyWarden ("former budgets").

* the table former_budget (code, name and type of a budget line from the old spreadsheets);
* budget_history_entry: the entries now belong to a former budget (former_budget_id), with the code and name of that
  year when they differ; budget_id becomes optional (entries made from now on don't set it);
* budget.continues_former_budget_id: the explicit link from a PennyWarden budget to the former budget it continues.

Existing entries (#284) are converted, so nothing visible changes: each line's entries become one former budget, named
after the budget they were stored on, and the oldest budget of that line (the #89 links) is linked to it. Entries on a
line whose oldest budget is deleted become a former budget nothing continues.

Revision ID: 0059_former_budget
Revises: 0058_fundraiser_series_sort
"""
import datetime as dt

import sqlalchemy as sa
from alembic import op

revision = "0059_former_budget"
down_revision = "0058_fundraiser_series_sort"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "former_budget",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspace.id"), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("budget_type", sa.String(10), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("retired_at", sa.DateTime, nullable=True),
        sa.Column("retired_by_user_id", sa.Integer, nullable=True),
        sa.Column("retire_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("created_by_user_id", sa.Integer, nullable=True),
        sa.Column("updated_at", sa.DateTime, nullable=True),
        sa.Column("updated_by_user_id", sa.Integer, nullable=True),
    )
    op.create_index("ix_former_budget_workspace_id", "former_budget", ["workspace_id"])
    with op.batch_alter_table("budget_history_entry") as b:
        b.alter_column("budget_id", existing_type=sa.Integer, nullable=True)
        b.add_column(sa.Column("former_budget_id", sa.Integer, sa.ForeignKey("former_budget.id",
                                                                              name="fk_bhe_former_budget"),
                               nullable=True))
        b.add_column(sa.Column("code", sa.String(20), nullable=True))
        b.add_column(sa.Column("name", sa.String(120), nullable=True))
        b.create_index("ix_budget_history_entry_former_budget_id", ["former_budget_id"])
    with op.batch_alter_table("budget") as b:
        b.add_column(sa.Column("continues_former_budget_id", sa.Integer, nullable=True))
        b.create_index("ix_budget_continues_former_budget_id", ["continues_former_budget_id"])
    _convert(op.get_bind())


def _convert(con) -> None:
    budgets = {r.id: r for r in con.execute(sa.text(
        "SELECT id, workspace_id, parent_budget_id, parent_code, child_code, name, budget_type, status, "
        "system_managed, continues_budget_id FROM budget"))}

    def code_of(b) -> str:
        parent = budgets.get(b.parent_budget_id) if b.parent_budget_id else None
        return f"{parent.parent_code}-{b.child_code}" if parent is not None else b.parent_code

    def oldest(b):
        seen, cur = {b.id}, b
        while cur.continues_budget_id and cur.continues_budget_id not in seen and cur.continues_budget_id in budgets:
            cur = budgets[cur.continues_budget_id]
            seen.add(cur.id)
        return cur

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    former_by_target: dict[int, int] = {}
    stored_on = [r[0] for r in con.execute(sa.text(
        "SELECT DISTINCT budget_id FROM budget_history_entry WHERE budget_id IS NOT NULL ORDER BY budget_id"))]
    for bid in stored_on:
        b = budgets.get(bid)
        if b is None:
            continue
        target = oldest(b)
        linkable = target.status != "DELETED" and not target.system_managed
        fid = former_by_target.get(target.id) if linkable else None
        if fid is None:
            fid = con.execute(sa.text(
                "INSERT INTO former_budget (workspace_id, code, name, budget_type, created_at) "
                "VALUES (:w, :c, :n, :t, :now)"),
                {"w": b.workspace_id, "c": code_of(b)[:20], "n": b.name, "t": b.budget_type, "now": now}).lastrowid
            if linkable:
                former_by_target[target.id] = fid
                con.execute(sa.text("UPDATE budget SET continues_former_budget_id = :f WHERE id = :b"),
                            {"f": fid, "b": target.id})
        con.execute(sa.text("UPDATE budget_history_entry SET former_budget_id = :f WHERE budget_id = :b"),
                    {"f": fid, "b": bid})


def downgrade() -> None:
    con = op.get_bind()
    # entries of former budgets added after the upgrade (no budget_id) go back to the budget that continues them
    con.execute(sa.text(
        "UPDATE budget_history_entry SET budget_id = (SELECT b.id FROM budget b WHERE "
        "b.continues_former_budget_id = budget_history_entry.former_budget_id LIMIT 1) WHERE budget_id IS NULL"))
    con.execute(sa.text("DELETE FROM budget_history_entry WHERE budget_id IS NULL"))
    with op.batch_alter_table("budget") as b:
        b.drop_index("ix_budget_continues_former_budget_id")
        b.drop_column("continues_former_budget_id")
    with op.batch_alter_table("budget_history_entry") as b:
        b.drop_index("ix_budget_history_entry_former_budget_id")
        b.drop_constraint("fk_bhe_former_budget", type_="foreignkey")
        b.drop_column("name")
        b.drop_column("code")
        b.drop_column("former_budget_id")
        b.alter_column("budget_id", existing_type=sa.Integer, nullable=False)
    op.drop_index("ix_former_budget_workspace_id", table_name="former_budget")
    op.drop_table("former_budget")
