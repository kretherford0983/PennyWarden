"""2.0.0 (#156, #159, #162): the Check Printing module - workspace.checks_enabled (off), check_style, check_signer,
check_account (per bank account: style and sheet counter) and check_printer_setting (per user). No existing data
changes.

Revision ID: 0025_check_printing
Revises: 0024_update_check
"""
import sqlalchemy as sa
from alembic import op

revision = "0025_check_printing"
down_revision = "0024_update_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace", sa.Column("checks_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "check_style",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id", name="fk_check_style_workspace_id_workspace"),
                  nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("preset_key", sa.String(40), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_check_style_workspace_id", "check_style", ["workspace_id"])
    op.create_table(
        "check_signer",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspace.id", name="fk_check_signer_workspace_id_workspace"),
                  nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("title", sa.String(80), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("image_ciphertext", sa.Text(), nullable=True),
        sa.Column("image_sha256", sa.String(64), nullable=True),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
        sa.Column("image_uploaded_at", sa.DateTime(), nullable=True),
        sa.Column("image_uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_check_signer_workspace_id", "check_signer", ["workspace_id"])
    op.create_table(
        "check_account",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(),
                  sa.ForeignKey("workspace.id", name="fk_check_account_workspace_id_workspace"), nullable=False),
        sa.Column("bank_account_id", sa.Integer(),
                  sa.ForeignKey("bank_account.id", name="fk_check_account_bank_account_id_bank_account"), nullable=False),
        sa.Column("check_style_id", sa.Integer(),
                  sa.ForeignKey("check_style.id", name="fk_check_account_check_style_id_check_style"), nullable=False),
        sa.Column("sheet_remaining", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint("bank_account_id", name="uq_check_account_bank_account_id"),
    )
    op.create_index("ix_check_account_workspace_id", "check_account", ["workspace_id"])
    op.create_table(
        "check_printer_setting",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(),
                  sa.ForeignKey("workspace.id", name="fk_check_printer_setting_workspace_id_workspace"), nullable=False),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("app_user.id", name="fk_check_printer_setting_user_id_app_user"), nullable=False),
        sa.Column("check_style_id", sa.Integer(),
                  sa.ForeignKey("check_style.id", name="fk_check_printer_setting_check_style_id_check_style"),
                  nullable=False),
        sa.Column("feed_key", sa.String(20), nullable=False),
        sa.Column("page", sa.String(10), nullable=True),
        sa.Column("guide", sa.String(10), nullable=True),
        sa.Column("dx_mils", sa.Integer(), nullable=False),
        sa.Column("dy_mils", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "check_style_id", "feed_key", name="uq_check_printer_setting_user_style_feed"),
    )
    op.create_index("ix_check_printer_setting_workspace_id", "check_printer_setting", ["workspace_id"])
    op.create_index("ix_check_printer_setting_user_id", "check_printer_setting", ["user_id"])


def downgrade() -> None:
    op.drop_table("check_printer_setting")
    op.drop_table("check_account")
    op.drop_table("check_signer")
    op.drop_table("check_style")
    with op.batch_alter_table("workspace") as b:
        b.drop_column("checks_enabled")
