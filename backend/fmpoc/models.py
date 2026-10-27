"""SQLAlchemy ORM models (docs/07). Monetary values are stored as integer cents to avoid
floating point storage in SQLite; the API exposes decimal strings with 2 places."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import false as sa_false
from sqlalchemy import true as sa_true
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


# ---------------------------------------------------------------- workspace / security
class Workspace(Base):
    __tablename__ = "workspace"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    # Bootstrap marker (BR-INIT-003 / docs/06 v1.1): set only in the same DB transaction that
    # creates the admin, roles and seed records. Empty/partial DBs therefore remain uninitialized.
    bootstrap_completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    # Key check value of the portable encryption key; detects key/database mismatch.
    key_check: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_entity_number: Mapped[int] = mapped_column(Integer, default=1)
    # v1.6.0 CR-033: optional modules, switched on by an Administrator
    fundraisers_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)
    # 2.0.0 (#156): the Payments module
    checks_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)
    # 2.1.0 (#312): the Donations module (optional; donation receipt letters)
    donations_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)
    # 2.0.0 (#126): Administrators are warned after this many days without a backup (0 = off)
    backup_warning_days: Mapped[int] = mapped_column(Integer, default=7, server_default="7", nullable=False)
    # 2.0.0 (#130): maintenance mode - on while a message is set (from maintenance_starts_at, if given): everyone but
    # Administrators can read but not change anything
    maintenance_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    maintenance_starts_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)   # UTC
    maintenance_set_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    maintenance_set_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    # 2.0.0 (#125): the last reinitialize, for the banner every user sees until an Administrator acknowledges it
    reinitialized_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    reinitialized_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reinitialize_backup: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reinitialize_ack_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    reinitialize_ack_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 2.2.0 (#243): the published demo. Set only by scripts/build_demo.py (directly in the database file) - no web or API
    # path writes it. While set: local loopback only, reset to demo-pristine/ on every start, the demo banner.
    demo_mode: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)


class Role(Base):
    __tablename__ = "role"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    security_domain: Mapped[str] = mapped_column(String(20))


class User(Base):
    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    username: Mapped[str] = mapped_column(String(64))
    username_normalized: Mapped[str] = mapped_column(String(64))
    email: Mapped[str] = mapped_column(String(254))
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # 2.0.0 (#134): real names - required for every account (users from before 2.0.0 get them from an Administrator)
    first_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    security_domain: Mapped[str] = mapped_column(String(20))  # ADMINISTRATOR | FINANCIAL | AUDITOR
    theme: Mapped[str] = mapped_column(String(10), default="light")
    nav_collapsed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)  # v1.3 CR-014
    dashboard_charts: Mapped[str | None] = mapped_column(String(200), nullable=True)  # v1.4.1 CR-020 (comma list)
    dashboard_layout: Mapped[str | None] = mapped_column(String(200), nullable=True)  # v1.5.0 CR-031 (comma list)
    # 2.0.0 (#164): the bank account of this user's last payment (Payments module), preselected next time
    last_payment_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 2.1.0 (#262): the user's register sort, "<column>:<asc|desc>" (None = Date, oldest first)
    register_sort: Mapped[str | None] = mapped_column(String(40), nullable=True)
    password_changed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)

    # 1.8.0 (#113): failed attempts in a row (sign-in passwords and Forgot password answers / codes together),
    # escalating locks, the temporary password from the host `reset-password`, the question currently offered by
    # Forgot password, and the notices shown once at the next sign-in.
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)
    reset_question_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reset_question_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    notice_failed_attempts_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    notice_password_reset_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    notice_password_reset_method: Mapped[str | None] = mapped_column(String(30), nullable=True)

    roles: Mapped[list[Role]] = relationship(secondary="user_role", lazy="selectin")

    __table_args__ = (UniqueConstraint("workspace_id", "username_normalized", name="uq_user_ws_username"),)

    @property
    def role_codes(self) -> set[str]:
        return {r.code for r in self.roles}


class UserRole(Base):
    __tablename__ = "user_role"
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id"), primary_key=True)


class AuthSession(Base):
    __tablename__ = "auth_session"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 of the cookie value
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    # v1.4.1 CR-018: NULL = fully signed in; VERIFY / ENROLL = password accepted, MFA step outstanding
    mfa_pending: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # 2.0.0 (#127): the client address of the latest request (shown to Administrators in the sessions list)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


# ---------------------------------------------------------------- fiscal years / budgets
class FiscalYear(Base):
    __tablename__ = "fiscal_year"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    identifier: Mapped[str] = mapped_column(String(20))
    display_name: Mapped[str] = mapped_column(String(24))
    start_date: Mapped[dt.date] = mapped_column(Date, index=True)
    end_date: Mapped[dt.date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(10), default="DRAFT", index=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    exception_confirmed: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # v1.3 CR-007: the organization produces no approval document (strong warning when set)
    approval_no_attachment: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)
    approval_no_attachment_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approval_no_attachment_set_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    approval_no_attachment_set_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)

    __table_args__ = (UniqueConstraint("workspace_id", "identifier", name="uq_fy_ws_identifier"),)


class Budget(Base):
    __tablename__ = "budget"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    fiscal_year_id: Mapped[int] = mapped_column(ForeignKey("fiscal_year.id"), index=True)
    parent_budget_id: Mapped[int | None] = mapped_column(ForeignKey("budget.id"), nullable=True, index=True)
    parent_code: Mapped[str] = mapped_column(String(10))
    child_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    budget_type: Mapped[str] = mapped_column(String(10))  # INCOME | EXPENSE
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    requested_amount_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="DRAFT")  # DRAFT|APPROVED|REJECTED|INACTIVE|DELETED (1.7.3)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    system_managed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_other: Mapped[bool] = mapped_column(Boolean, default=False)
    is_budget_zero: Mapped[bool] = mapped_column(Boolean, default=False)
    # 1.8.0 (#89): the budget of an earlier Fiscal Year this one continues (independent of the code, so a budget can
    # be renumbered and keep its history). At most one later budget continues a budget (checked in the service).
    continues_budget_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)

    __table_args__ = (Index("ix_budget_fy_type_status", "fiscal_year_id", "budget_type", "status"),)


# ---------------------------------------------------------------- entities / accounts
class Entity(Base):
    __tablename__ = "entity"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    entity_number: Mapped[str] = mapped_column(String(16))
    entity_type: Mapped[str] = mapped_column(String(14))  # INDIVIDUAL | ORGANIZATION | SYSTEM
    organization_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    primary_contact: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 1.6.7: position in the organization (individuals only), offered as the signer's title on the audit review
    # signature page and the cash count sheet
    position: Mapped[str | None] = mapped_column(String(60), nullable=True)
    address_line1: Mapped[str | None] = mapped_column(String(200), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state_region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_financial_institution: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    # 2.1.0 (#314): the organization itself - one per workspace, maintained by Administrators in System/About
    is_organization: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)
    ein: Mapped[str | None] = mapped_column(String(10), nullable=True)       # 12-3456789 (#314; other entities #315)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    name_key: Mapped[str] = mapped_column(String(200), index=True)  # normalized name for duplicate search
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)

    __table_args__ = (UniqueConstraint("workspace_id", "entity_number", name="uq_entity_ws_number"),)

    @property
    def display_name(self) -> str:
        if self.entity_type == "INDIVIDUAL":
            return self.primary_contact or ""
        return self.organization_name or ""


class BankAccount(Base):
    __tablename__ = "bank_account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    financial_institution_entity_id: Mapped[int] = mapped_column(ForeignKey("entity.id"))
    account_name: Mapped[str] = mapped_column(String(120))
    account_type: Mapped[str] = mapped_column(String(30))
    account_subtype: Mapped[str | None] = mapped_column(String(60), nullable=True)
    account_number_ciphertext: Mapped[str] = mapped_column(Text)
    account_number_fingerprint: Mapped[str] = mapped_column(String(64))
    account_number_visible_suffix: Mapped[str] = mapped_column(String(4))
    register_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # 1.7.1 (#74): order set by Budget Managers; only the order within a group (Checking & Savings / Investments and
    # Other) matters. New accounts go to the end of their group.
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    interest_rate: Mapped[str | None] = mapped_column(String(12), nullable=True)  # decimal percent string
    opening_balance_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    opening_balance_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    # 2.2.0 (#348): when the account was really opened (empty = it existed before PennyWarden)
    account_opened_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    manual_current_balance_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", index=True)  # ACTIVE | CLOSED
    closed_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)

    institution: Mapped[Entity] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("workspace_id", "account_number_fingerprint", name="uq_bank_ws_fingerprint"),
    )


class BankAccountBalance(Base):
    """1.7.3 (#88): dated balance history of a non-register account. Append-only: an entry is never edited or
    deleted; a correction is a new entry (for the same "as of" date the one entered last counts). The account's
    current balance (manual_current_balance_cents) is the entry with the latest "as of" date."""
    __tablename__ = "bank_account_balance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    bank_account_id: Mapped[int] = mapped_column(ForeignKey("bank_account.id"), index=True)
    as_of_date: Mapped[dt.date] = mapped_column(Date)
    balance_cents: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(12), default="UPDATE")  # OPENING | UPDATE | UPGRADE
    entered_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    entered_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (Index("ix_bank_account_balance_account_date", "bank_account_id", "as_of_date"),)


# ---------------------------------------------------------------- register
class RegisterTransaction(Base):
    __tablename__ = "register_transaction"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    bank_account_id: Mapped[int] = mapped_column(ForeignKey("bank_account.id"), index=True)
    transaction_type: Mapped[str] = mapped_column(String(10))  # DEPOSIT | WITHDRAWAL
    transaction_date: Mapped[dt.date] = mapped_column(Date, index=True)
    entry_timestamp: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    clear_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)
    parent_entity_id: Mapped[int | None] = mapped_column(ForeignKey("entity.id"), nullable=True)
    check_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="ACTIVE", index=True)  # ACTIVE | VOID | DELETED (1.7.3)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    voided_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    voided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    # v1.2 (migration 0003) - linked transfer legs share a group id
    transfer_group: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # v1.2 - user explicitly records that no supporting attachment will be provided (e.g. bank interest)
    no_attachment: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)
    no_attachment_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    no_attachment_set_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    no_attachment_set_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 1.7.3 (#53): marked Deleted by a Register Admin (uncleared only); kept for Auditors and the audit trail
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delete_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # 2.1.0 (#260): a withdrawal paid electronically (no physical check). The optional number is either a check number
    # from the organization's own sequence (check_number, CR-011/CR-012) or a bank/vendor reference (never in the
    # check sequence).
    electronic_payment: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payment_method_other: Mapped[str | None] = mapped_column(String(60), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(40), nullable=True)

    allocations: Mapped[list["TransactionAllocation"]] = relationship(
        back_populates="transaction", lazy="selectin", order_by="TransactionAllocation.id"
    )
    parent_entity: Mapped[Entity | None] = relationship(lazy="joined")

    @property
    def live_allocations(self) -> list["TransactionAllocation"]:
        return [a for a in self.allocations if a.removed_at is None]

    @property
    def total_cents(self) -> int:
        """BR-046: the parent total is always derived from its allocations."""
        return sum(a.amount_cents for a in self.live_allocations)


class TransactionAllocation(Base):
    __tablename__ = "transaction_allocation"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("register_transaction.id"), index=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budget.id"), index=True, nullable=False)
    entity_id: Mapped[int | None] = mapped_column(ForeignKey("entity.id"), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # 2.0.0 (#165): optional date of the invoice (withdrawals), printed in the payment cover letter
    invoice_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v1.2.1 (migration 0004) - per-allocation "no attachment will be provided" marker
    no_attachment: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)
    no_attachment_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    no_attachment_set_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    no_attachment_set_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Allocations removed from a transaction during an edit are retained (never hard deleted).
    removed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)

    transaction: Mapped[RegisterTransaction] = relationship(back_populates="allocations")
    budget: Mapped[Budget] = relationship(lazy="joined")
    entity: Mapped[Entity | None] = relationship(lazy="joined")


class FiscalYearReview(Base):
    __tablename__ = "fiscal_year_review"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    transaction_allocation_id: Mapped[int] = mapped_column(ForeignKey("transaction_allocation.id"), index=True)
    category: Mapped[str] = mapped_column(String(20))  # CROSS_FY | NO_FISCAL_YEAR
    natural_fiscal_year_id: Mapped[int | None] = mapped_column(ForeignKey("fiscal_year.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="PENDING", index=True)  # PENDING|REVIEWED|REASSIGNED
    review_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    allocation: Mapped[TransactionAllocation] = relationship(lazy="joined")


# ---------------------------------------------------------------- attachments
class Attachment(Base):
    __tablename__ = "attachment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(80), unique=True)  # application generated
    mime_type: Mapped[str] = mapped_column(String(40))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    # Explicit nullable FKs (instead of a polymorphic link) preserve referential integrity (docs/07 §8).
    fiscal_year_id: Mapped[int | None] = mapped_column(ForeignKey("fiscal_year.id"), nullable=True, index=True)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey("register_transaction.id"), nullable=True, index=True)
    allocation_id: Mapped[int | None] = mapped_column(ForeignKey("transaction_allocation.id"), nullable=True, index=True)
    # v1.6.1 CR-034: a fundraiser document (flyer, permit, tally sheet). No DB-level FK (added by a later migration
    # on SQLite); the service checks the owner.
    fundraiser_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    removed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    removed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    uploaded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    # v1.3 CR-007: APPROVAL | AUDIT_SIGNOFF | UNSPECIFIED for Fiscal Year attachments (None otherwise)
    document_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    system_generated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)
    # 2.1.0 (#259): position among its owner's attachments; None = upload order (listed by COALESCE(sort_order, id))
    sort_order: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RequestKey(Base):
    """v1.3 CR-011: a one-time key sent with a create request; a repeat returns the original result."""
    __tablename__ = "request_key"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    result_ids: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("workspace_id", "key", name="uq_request_key_ws_key"),)


class CheckNumberAcknowledgement(Base):
    """v1.3 CR-012: check numbers (or a range) confirmed as 'not missing' with a note."""
    __tablename__ = "check_number_acknowledgement"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    bank_account_id: Mapped[int] = mapped_column(ForeignKey("bank_account.id"), index=True)
    first_number: Mapped[int] = mapped_column(Integer)
    last_number: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(1000))
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------- audit
class AuditEvent(Base):
    __tablename__ = "audit_event"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspace.id"), nullable=True, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True, index=True)
    actor_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 2.0.0 (#134): the actor's real name when the event was written (later name changes don't rewrite history)
    actor_name: Mapped[str | None] = mapped_column(String(130), nullable=True)
    # 2.0.0 (#133): names of the related records when the event was written ("kind:id" -> name)
    labels: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    object_type: Mapped[str] = mapped_column(String(40))
    object_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    category: Mapped[str] = mapped_column(String(12), default="BUSINESS")  # BUSINESS | SECURITY
    before_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (Index("ix_audit_object", "object_type", "object_id"),)


class SignatureTemplate(Base):
    """v1.4.1 CR-016: organization-wide saved wording for the audit review signature page (max 4)."""
    __tablename__ = "signature_template"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class UserMfa(Base):
    """v1.4.1 CR-018: TOTP secret (encrypted with the portable key) - active and pending enrollment."""
    __tablename__ = "user_mfa"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), unique=True)
    secret_enc: Mapped[str | None] = mapped_column(String(200), nullable=True)
    enabled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)  # last accepted TOTP time step (replay)
    pending_secret_enc: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pending_created_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    # 2.2.0 (#327): after a reset marked as a possible compromise the next setup accepts only a newly generated key
    new_key_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(),
                                                   nullable=False)
    # the pending key was supplied by the user (recorded as own_key on MFA_ENROLLED / MFA_CHANGED)
    pending_own_key: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)


class MfaRecoveryCode(Base):
    """v1.4.1 CR-018: one-time recovery codes (SHA-256 of the normalized code; shown once)."""
    __tablename__ = "mfa_recovery_code"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class TrustedDevice(Base):
    """v1.4.1 CR-018: "trust this browser for 30 days" (SHA-256 of the cookie value)."""
    __tablename__ = "trusted_device"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------- v1.6.0 CR-033 fundraisers
class Fundraiser(Base):
    __tablename__ = "fundraiser"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[dt.date] = mapped_column(Date, index=True)  # physical event dates (display only)
    end_date: Mapped[dt.date] = mapped_column(Date)
    filter_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    filter_regex: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    archived_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # v1.6.4 CR-037: the fundraiser did not take place as planned (its transactions still count)
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 2.1.0 (#275): stakeholder report - narrative notes (Budget Managers) and "Mark results final"
    summary_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    results_final_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    results_final_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 2.1.0 (#277): the same event across years ("Continues from" puts it in the previous fundraiser's series)
    series_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    continues_from_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    budgets: Mapped[list["FundraiserBudget"]] = relationship(
        back_populates="fundraiser", lazy="selectin", cascade="all, delete-orphan", order_by="FundraiserBudget.id")


class FundraiserBudget(Base):
    """A budget chosen for a fundraiser: at most one INCOME and one EXPENSE budget per Fiscal Year, at most two
    Fiscal Years (adjacent). A parent budget includes all its children."""
    __tablename__ = "fundraiser_budget"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fundraiser_id: Mapped[int] = mapped_column(ForeignKey("fundraiser.id"), index=True)
    fiscal_year_id: Mapped[int] = mapped_column(ForeignKey("fiscal_year.id"))
    budget_id: Mapped[int] = mapped_column(ForeignKey("budget.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # INCOME | EXPENSE

    fundraiser: Mapped[Fundraiser] = relationship(back_populates="budgets")
    budget: Mapped["Budget"] = relationship(lazy="joined")

    __table_args__ = (UniqueConstraint("fundraiser_id", "fiscal_year_id", "kind", name="uq_fundraiser_budget_fy_kind"),)


# ---------------------------------------------------------------- v1.6.1 CR-034 fundraiser management
class FundraiserSeries(Base):
    """2.1.0 (#277): one fundraising event across years (e.g. "Golf Outing"). Created behind the scenes when a
    fundraiser continues an earlier one; renamed, grouped as Other or merged in the Fundraiser series list."""
    __tablename__ = "fundraiser_series"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    group_as_other: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    merged_into_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FundraiserSeriesResult(Base):
    """2.1.0 (#277): a year's result entered by hand (years before PennyWarden). Retired, never deleted (BR-001)."""
    __tablename__ = "fundraiser_series_result"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("fundraiser_series.id"), index=True)
    fiscal_year_label: Mapped[str] = mapped_column(String(40))
    year: Mapped[int] = mapped_column(Integer)
    net_cents: Mapped[int] = mapped_column(BigInteger)
    income_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expense_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    retired_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    retired_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retire_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class BudgetHistoryEntry(Base):
    """2.2.0 (#284): a budget's budgeted and actual figures for a year before PennyWarden, entered by a Budget Manager
    (labelled *Entered*; reporting only - never part of actuals, registers or closure). Stored against the oldest
    budget of the line (#89 links) and read for every budget of the line. Corrected or retired, never deleted."""
    __tablename__ = "budget_history_entry"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budget.id"), index=True)
    fiscal_year_label: Mapped[str] = mapped_column(String(40))
    year: Mapped[int] = mapped_column(Integer)
    budgeted_cents: Mapped[int] = mapped_column(BigInteger)
    actual_cents: Mapped[int] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    retired_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    retired_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retire_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TestingState(Base):
    """2.2.0 (#231): what a testing-mode Administrator moved that is otherwise taken from the audit log (which can't be
    changed): the time of the last successful backup, and when the reinitialize cooldown was cleared. Read only while
    the server is in testing mode."""
    __tablename__ = "testing_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), unique=True)
    last_backup_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    reinitialize_cooldown_cleared_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class FundraiserFyReportNote(Base):
    """2.1.0 (#277): the Fiscal Year fundraising report's notes, remembered per Fiscal Year."""
    __tablename__ = "fundraiser_fy_report_note"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    fiscal_year_id: Mapped[int] = mapped_column(ForeignKey("fiscal_year.id"), unique=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FundraiserBucketCategory(Base):
    """2.1.0 (#278): an optional heading that groups buckets of one fundraiser (presentation only)."""
    __tablename__ = "fundraiser_bucket_category"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fundraiser_id: Mapped[int] = mapped_column(ForeignKey("fundraiser.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FundraiserBucket(Base):
    """A sub-category of a fundraiser (e.g. food sales, raffle); holds income and expense lines by amount."""
    __tablename__ = "fundraiser_bucket"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fundraiser_id: Mapped[int] = mapped_column(ForeignKey("fundraiser.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 2.1.0 (#278): one category or none; display order (buckets numbered in name order by migration 0039)
    category_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FundraiserExclusion(Base):
    """A line (allocation) taken out of a fundraiser although its budget and the filter include it."""
    __tablename__ = "fundraiser_exclusion"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fundraiser_id: Mapped[int] = mapped_column(ForeignKey("fundraiser.id"), index=True)
    allocation_id: Mapped[int] = mapped_column(ForeignKey("transaction_allocation.id"))
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (UniqueConstraint("fundraiser_id", "allocation_id", name="uq_fundraiser_exclusion_line"),)


class FundraiserClassification(Base):
    """Part of a line that is not fundraiser income/expense: cash float taken out or returned."""
    __tablename__ = "fundraiser_classification"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fundraiser_id: Mapped[int] = mapped_column(ForeignKey("fundraiser.id"), index=True)
    allocation_id: Mapped[int] = mapped_column(ForeignKey("transaction_allocation.id"))
    kind: Mapped[str] = mapped_column(String(24))  # CASH_FLOAT_OUT | CASH_FLOAT_RETURNED
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (UniqueConstraint("fundraiser_id", "allocation_id", name="uq_fundraiser_classification_line"),)


class FundraiserLineContributor(Base):
    """2.1.0 (#303): the contributor shown on the fundraiser reports for the part of a line that is in no bucket (the
    "Other" lines, and every line of a fundraiser without buckets) - e.g. "Cash". Bucket parts keep their own
    (fundraiser_bucket_line.contributor_override)."""
    __tablename__ = "fundraiser_line_contributor"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fundraiser_id: Mapped[int] = mapped_column(ForeignKey("fundraiser.id"), index=True)
    allocation_id: Mapped[int] = mapped_column(ForeignKey("transaction_allocation.id"))
    contributor_override: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (UniqueConstraint("fundraiser_id", "allocation_id", name="uq_fundraiser_line_contributor"),)


class FundraiserBucketLine(Base):
    """Amount of a line assigned to a bucket (a line can be split across buckets)."""
    __tablename__ = "fundraiser_bucket_line"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bucket_id: Mapped[int] = mapped_column(ForeignKey("fundraiser_bucket.id"), index=True)
    allocation_id: Mapped[int] = mapped_column(ForeignKey("transaction_allocation.id"))
    amount_cents: Mapped[int] = mapped_column(BigInteger)   # the net (charge - less): what counts toward the line
    # 2.1.0 (#278): the full charge and a credit taken off it ("Less: pre-paid team credit"); detail only
    charge_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    less_cents: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    less_description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 2.1.0 (#278 feedback): shown instead of the Entity as the contributor on the fundraiser reports
    contributor_override: Mapped[str | None] = mapped_column(String(120), nullable=True)
    __table_args__ = (UniqueConstraint("bucket_id", "allocation_id", name="uq_fundraiser_bucket_line"),)


# ---------------------------------------------------------------- v1.6.3 CR-036 reminders
class Reminder(Base):
    """A reminder: PERSONAL (visible to its owner only) or ORGANIZATION (all financial users + Auditors).
    It becomes a notification on (due_date - notify_days_before) and stays until resolved.
    1.6.7: an ORGANIZATION reminder can repeat (every N days/weeks/months/years, optionally until a date). Each
    occurrence is its own row; resolving one creates the next (repeat_source_id points back at the resolved one).
    Due dates are counted from repeat_anchor (the first due date) so month ends do not drift."""
    __tablename__ = "reminder"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    scope: Mapped[str] = mapped_column(String(12))
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[dt.date] = mapped_column(Date, index=True)
    notify_days_before: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    link_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    link_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repeat_every: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repeat_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)  # DAY | WEEK | MONTH | YEAR
    repeat_until: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    repeat_anchor: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    repeat_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    repeat_source_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class UserSecurityQuestion(Base):
    """1.8.0 (#113): one of a user's three security questions (a code from the fixed list) and its answer, hashed
    like a password after normalization (case, spaces and punctuation ignored)."""
    __tablename__ = "user_security_question"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    slot: Mapped[int] = mapped_column(Integer)  # 1..3
    question_code: Mapped[str] = mapped_column(String(40))
    answer_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "slot", name="uq_user_security_question_slot"),)


class SecurityNotice(Base):
    """1.8.0 (#113): a notice for the Administrators (account locked for an hour or more, disabled after failed
    attempts, password reset with the security questions) until one of them dismisses it."""
    __tablename__ = "security_notice"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    subject_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(30))  # ACCOUNT_LOCKED | ACCOUNT_DISABLED | PASSWORD_RESET
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    dismissed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    dismissed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class BackupSchedule(Base):
    """1.9.0 (#62): scheduled automatic backups - one row per workspace. Only the public key and the private key
    wrapped with the backup passphrase are stored: the server can lock a backup but not open one."""
    __tablename__ = "backup_schedule"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)
    frequency: Mapped[str] = mapped_column(String(10), default="DAILY")  # DAILY | WEEKLY
    weekday: Mapped[int] = mapped_column(Integer, default=0)            # 0 = Monday (WEEKLY)
    time_of_day: Mapped[str] = mapped_column(String(5), default="02:00")  # HH:MM, server local time
    destination: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    keep_daily: Mapped[int] = mapped_column(Integer, default=7)
    keep_weekly: Mapped[int] = mapped_column(Integer, default=4)
    keep_monthly: Mapped[int] = mapped_column(Integer, default=6)
    public_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    wrapped_private_key: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON (scrypt + AES-GCM)
    key_fingerprint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    passphrase_set_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)   # UTC
    retry_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    retry_wait_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_success_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_failure_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class BudgetProjectionChoice(Base):
    """2.1.0 (#257, #261): whether a user projects a current-year budget to the Fiscal Year end (Budget Prep report,
    Planning Sheet). No row = the default (projected, unless the budget belongs to an ended or cancelled
    fundraiser). Remembered per user; a budget belongs to one Fiscal Year, so this is per Fiscal Year too."""
    __tablename__ = "budget_projection_choice"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budget.id"), index=True)
    project: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("user_id", "budget_id", name="uq_projection_choice_user_budget"),)


class BackupRun(Base):
    """1.9.0 (#62): one scheduled-style backup run (scheduled, retry, missed at start, or Run now). The file names of
    successful runs are what retention may delete - never any other file in the folder."""
    __tablename__ = "backup_run"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(12))   # SCHEDULED | RETRY | MISSED | RUN_NOW
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    result: Mapped[str] = mapped_column(String(10), default="RUNNING")   # RUNNING | SUCCESS | FAILED
    destination: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    key_fingerprint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)   # removed by retention
    deleted_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)


class UpdateCheck(Base):
    """1.10.0 (#58): the update notification - one row for the installation: whether the check is on (an
    Administrator can turn it off) and the last result, kept so that restarts do not fetch again."""
    __tablename__ = "update_check"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true(), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(10), nullable=True)      # stable | test (of the last check)
    checked_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)        # the newer releases found
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    updated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------- 2.0.0 check printing (#60)
class CheckStyle(Base):
    """2.0.0 (#156): a check style - the check stock, where each field prints on it and the ways it can be fed to the
    printer. The settings are one validated JSON document (services/checkprint/config.py). Deactivated, never
    deleted (BR-001)."""
    __tablename__ = "check_style"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    preset_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true(), nullable=False)
    config_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CheckSigner(Base):
    """2.0.0 (#159): a signer and their signature image. The PNG is stored encrypted with the application key and can
    never be downloaded; it is only drawn into printed checks and admin test prints."""
    __tablename__ = "check_signer"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str | None] = mapped_column(String(80), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true(), nullable=False)
    image_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_uploaded_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    image_uploaded_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CheckAccount(Base):
    """2.0.0 (#156): per bank account - the check style a Register User chose for it and the sheet counter (checks
    left on the sheet in the printer). Administrators cannot see bank accounts (BR-003), so they never set this."""
    __tablename__ = "check_account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    bank_account_id: Mapped[int] = mapped_column(ForeignKey("bank_account.id"), unique=True)
    check_style_id: Mapped[int] = mapped_column(ForeignKey("check_style.id"))
    sheet_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CheckPrinterSetting(Base):
    """2.0.0 (#162): a user's own printer settings for one check style and feed mode, applied on top of the
    Administrator's layout (never changing it): page option, guide position and a bounded personal adjustment."""
    __tablename__ = "check_printer_setting"
    __table_args__ = (UniqueConstraint("user_id", "check_style_id", "feed_key",
                                       name="uq_check_printer_setting_user_style_feed"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id"), index=True)
    check_style_id: Mapped[int | None] = mapped_column(ForeignKey("check_style.id"), nullable=True)
    # 2.0.0 (#166): or an envelope template (check_style_id empty, feed_key "envelope")
    document_id: Mapped[int | None] = mapped_column(ForeignKey("check_document.id"), nullable=True)
    feed_key: Mapped[str] = mapped_column(String(20))
    page: Mapped[str | None] = mapped_column(String(10), nullable=True)      # LETTER | CHECK (single feed only)
    guide: Mapped[str | None] = mapped_column(String(10), nullable=True)     # CENTER | LEFT | RIGHT
    dx_mils: Mapped[int] = mapped_column(Integer, default=0)                  # thousandths of an inch, check coordinates
    dy_mils: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    # 2.1.0 (#247): on the user's letter row (feed_key "letter", no style or template): cover-letter fold marks
    # FRONT | BACK; empty = use the template's setting
    fold_marks: Mapped[str | None] = mapped_column(String(10), nullable=True)


class CheckDocument(Base):
    """2.0.0 (#165, #166): a cover letter or envelope template of the Payments module - a validated JSON settings
    document like a check style. Deactivated, never deleted (BR-001); one default per kind."""
    __tablename__ = "check_document"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))            # LETTER | ENVELOPE
    name: Mapped[str] = mapped_column(String(80))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=sa_true(), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false(), nullable=False)
    config_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 2.0.0 #176: an optional logo for a cover letter (PNG, validated and re-encoded; not secret, so not encrypted)
    logo_png: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    logo_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    logo_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logo_height: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------- 2.1.0 (#312) Donations module: receipt letters
class DonationSettings(Base):
    """The organization's donation receipt setup (Administrator): EIN, mailing address and the receipt template, as
    validated JSON (services/donations.ReceiptConfig). One per workspace."""
    __tablename__ = "donation_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), unique=True)
    config_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class DonationLine(Base):
    """A deposit allocation marked as a donation (Register User), with an optional purpose and the goods or services
    given in exchange (value and description; none = no goods or services)."""
    __tablename__ = "donation_line"
    __table_args__ = (UniqueConstraint("allocation_id", name="uq_donation_line_allocation"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    allocation_id: Mapped[int] = mapped_column(ForeignKey("transaction_allocation.id"))
    purpose: Mapped[str | None] = mapped_column(String(200), nullable=True)
    goods_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    goods_description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 2.1.0 (Kyle, 2026-10-22): when the donation was received, if not the deposit's date (empty = the deposit's date)
    date_received: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class DonationDetail(Base):
    """2.1.0 (Kyle, 2026-10-22): the {DETAILS} text written for one donor's receipt on one deposit (may use the
    receipt's {VARIABLES}); printed where the template has {DETAILS}."""
    __tablename__ = "donation_detail"
    __table_args__ = (UniqueConstraint("transaction_id", "donor_entity_id", name="uq_donation_detail_donor"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("register_transaction.id"))
    donor_entity_id: Mapped[int] = mapped_column(ForeignKey("entity.id"))
    details: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class DonationReceipt(Base):
    """A printed donation receipt for one donor of one deposit. kind ORIGINAL (a new number), DUPLICATE (the same
    content again: the original's number) or CORRECTED (a new number replacing `replaces_id`). Never deleted; a
    voided deposit's receipts show as void."""
    __tablename__ = "donation_receipt"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id"), index=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("register_transaction.id"), index=True)
    donor_entity_id: Mapped[int] = mapped_column(ForeignKey("entity.id"))
    donor_name: Mapped[str] = mapped_column(String(200))
    number: Mapped[str] = mapped_column(String(20))
    year: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10))               # ORIGINAL | DUPLICATE | CORRECTED
    replaces_id: Mapped[int | None] = mapped_column(ForeignKey("donation_receipt.id"), nullable=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    goods_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    date_received: Mapped[dt.date] = mapped_column(Date)
    allocation_ids: Mapped[str] = mapped_column(String(500))    # comma-separated, for the record
    content_sha: Mapped[str] = mapped_column(String(64))
    attachment_id: Mapped[int | None] = mapped_column(ForeignKey("attachment.id"), nullable=True)
    printed_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    printed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
