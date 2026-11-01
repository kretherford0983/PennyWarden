"""2.4.0 (#251): the Invoices module switch (off) and the Invoice Manager role (Financial). Nothing existing changes;
no user gets the new role.

Revision ID: 0072_invoices_module
Revises: 0071_invoiced_income
"""
import sqlalchemy as sa
from alembic import op

revision = "0072_invoices_module"
down_revision = "0071_invoiced_income"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspace") as b:
        b.add_column(sa.Column("invoices_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    bind = op.get_bind()
    have = {r[0] for r in bind.execute(sa.text("SELECT code FROM role")).fetchall()}
    if "INVOICE_MANAGER" not in have:
        bind.execute(sa.text("INSERT INTO role (code, name, security_domain) VALUES (:c, :n, :d)"),
                     {"c": "INVOICE_MANAGER", "n": "Invoice Manager", "d": "FINANCIAL"})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM user_role WHERE role_id IN (SELECT id FROM role WHERE code = 'INVOICE_MANAGER')"))
    bind.execute(sa.text("DELETE FROM role WHERE code = 'INVOICE_MANAGER'"))
    with op.batch_alter_table("workspace") as b:
        b.drop_column("invoices_enabled")
