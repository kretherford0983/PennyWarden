"""Explicit API input contracts (BR-097/098). Every request model forbids unknown fields, so protected
properties (is_system, locked, created_by, bank_account_id on edit, roles on self-service, derived totals,
...) cannot be mass-assigned."""
from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, field_validator

Str = lambda n: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=n)]  # noqa: E731
OptStr = lambda n: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=n)]  # noqa: E731

_EMAIL_RE = re.compile(r"^[^@\s<>\"']{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9-]{1,63})+$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,64}$")
_DATE_MIN, _DATE_MAX = dt.date(1900, 1, 1), dt.date(2200, 12, 31)


def _email(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    if len(v) > 254 or not _EMAIL_RE.match(v):
        raise ValueError("must be a valid email address")
    return v


def _date_range(v: dt.date | None) -> dt.date | None:
    if v is not None and not (_DATE_MIN <= v <= _DATE_MAX):
        raise ValueError("date is out of the supported range")
    return v


Email = Annotated[str, StringConstraints(strip_whitespace=True, max_length=254), AfterValidator(_email)]
OptEmail = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=254), AfterValidator(_email)]
Date = Annotated[dt.date, AfterValidator(_date_range)]
OptDate = Annotated[dt.date | None, AfterValidator(_date_range)]
Amount = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
Confirmations = Annotated[list[Annotated[str, StringConstraints(max_length=40)]], Field(max_length=20)]


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ------------------------------------------------------------------ system / auth / users
class InitializeIn(In):
    workspace_name: Str(120)
    admin_username: Str(64)
    admin_first_name: OptStr(200) = None   # 2.0.0 (#134): required - checked like any user's names
    admin_last_name: OptStr(200) = None
    admin_email: Email
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    password_confirmation: Annotated[str, StringConstraints(min_length=1, max_length=256)]

    @field_validator("admin_username")
    @classmethod
    def _u(cls, v):
        if not _USERNAME_RE.match(v):
            raise ValueError("username must be 3-64 characters: letters, digits, '.', '_' or '-'")
        return v

    @field_validator("admin_email")
    @classmethod
    def _e(cls, v):
        if not v:
            raise ValueError("email is required")
        return v


class LoginIn(In):
    username: Annotated[str, StringConstraints(max_length=64)]
    password: Annotated[str, StringConstraints(max_length=256)]


class ChangePasswordIn(In):
    current_password: Annotated[str, StringConstraints(max_length=256)]
    new_password: Annotated[str, StringConstraints(max_length=256)]
    new_password_confirmation: Annotated[str, StringConstraints(max_length=256)]


class DashboardSectionIn(In):
    key: Literal["notifications", "fiscal_year", "budget", "review", "bank", "attention", "invoices", "charts"]   # 2.4.0 (#255): invoices
    visible: bool


class PreferencesIn(In):
    theme: Literal["light", "dark"] | None = None
    nav_collapsed: bool | None = None  # v1.3 CR-014
    # v1.4.1 CR-020: which dashboard charts to show, in order (empty list = none)
    dashboard_charts: list[Literal["income_pie", "monthly", "expense_vs_budget", "balances", "expense_pie",
                                   "cumulative_net"]] | None = Field(None, max_length=6)
    # v1.5.0 CR-031: dashboard sections in display order with visibility; reset_dashboard_layout -> default
    dashboard_layout: list[DashboardSectionIn] | None = Field(None, max_length=7)
    reset_dashboard_layout: bool | None = None
    # 2.1.0 (#262): the register's sort, remembered per user; reset_register_sort -> Date, oldest first
    register_sort: Literal["transaction_date:asc", "transaction_date:desc", "clear_date:asc", "clear_date:desc"] | None = None
    reset_register_sort: bool | None = None
    # 2.2.0 (#316): how Individuals show and sort for this user
    name_order: Literal["FIRST_LAST", "LAST_FIRST"] | None = None
    # 2.2.0 (#351): Fundraiser series years, newest first ("desc", the default) or oldest first
    fundraiser_series_sort: Literal["desc", "asc"] | None = None


Domain = Literal["ADMINISTRATOR", "FINANCIAL", "AUDITOR", "COMBINED"]  # 1.9.0 (#54): COMBINED on local installs
RoleCode = Literal["ADMINISTRATOR", "BUDGET_MANAGER", "BUDGET_USER", "REGISTER_USER", "AUDITOR",
                   "BUDGET_ADMIN", "REGISTER_ADMIN",  # 1.7.3 (#52, #53)
                   "INVOICE_MANAGER"]  # 2.4.0 (#251)


class UserCreateIn(In):
    username: Str(64)
    email: Email
    display_name: OptStr(120) = None
    first_name: OptStr(200) = None   # 2.0.0 (#134): required (checked by the service with a clear message)
    last_name: OptStr(200) = None
    password: Annotated[str, StringConstraints(max_length=256)]
    security_domain: Domain
    roles: Annotated[list[RoleCode], Field(min_length=1, max_length=7)]

    @field_validator("username")
    @classmethod
    def _u(cls, v):
        if not _USERNAME_RE.match(v):
            raise ValueError("username must be 3-64 characters: letters, digits, '.', '_' or '-'")
        return v

    @field_validator("email")
    @classmethod
    def _e(cls, v):
        if not v:
            raise ValueError("email is required")
        return v


class UserUpdateIn(In):
    email: OptEmail = None
    display_name: OptStr(120) = None
    first_name: OptStr(200) = None
    last_name: OptStr(200) = None
    active: bool | None = None
    security_domain: Domain | None = None
    roles: Annotated[list[RoleCode] | None, Field(max_length=7)] = None


class NameRowIn(In):
    id: int
    first_name: OptStr(200) = None
    last_name: OptStr(200) = None


class NamesIn(In):
    """2.0.0 (#134): completing the names of accounts from before 2.0.0."""
    users: Annotated[list[NameRowIn], Field(min_length=1, max_length=500)]


class PasswordResetIn(In):
    new_password: Annotated[str, StringConstraints(max_length=256)]


# ------------------------------------------------------------------ fiscal years
FY_IDENTIFIER = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9-]{1,20}$")]


class FiscalYearCreateIn(In):
    identifier: FY_IDENTIFIER
    start_date: Date
    end_date: Date
    copy_from_fiscal_year_id: int | None = None
    copy_budget_ids: Annotated[list[int], Field(max_length=2000)] = []
    confirmations: Confirmations = []


class FiscalYearUpdateIn(In):
    identifier: FY_IDENTIFIER | None = None
    start_date: OptDate = None
    end_date: OptDate = None
    confirmations: Confirmations = []


class FiscalYearApproveIn(In):
    confirm_irreversible: bool


class AttachmentTypeIn(In):
    """v1.3 CR-007: Fiscal Year document type."""
    document_type: Literal["APPROVAL", "AUDIT_SIGNOFF", "UNSPECIFIED"]


class AttachmentOrderIn(In):
    """2.1.0 (#259): the new order of an owner's attachments (every active one shown there, exactly once)."""
    owner_type: Literal["fiscal_year", "transaction", "allocation", "fundraiser"]
    owner_id: int
    attachment_ids: Annotated[list[int], Field(min_length=1, max_length=500)]


class ApprovalNoAttachmentIn(In):
    """v1.3 CR-007: the organization produces no approval document (strong warning in the UI)."""
    no_attachment: bool
    reason: OptStr(500) = None


class FiscalYearCloseIn(In):
    confirm_reviewed: bool
    confirmations: Confirmations = []


# ------------------------------------------------------------------ budgets
BudgetCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9]{1,10}$")]


class BudgetCreateIn(In):
    fiscal_year_id: int
    parent_budget_id: int | None = None
    code: BudgetCode
    name: Str(120)
    budget_type: Literal["INCOME", "EXPENSE"] | None = None
    amount: Amount
    notes: OptStr(4000) = None
    continues_budget_id: int | None = None  # 1.8.0 (#89)
    continues_former_budget_id: int | None = None  # 2.2.0 (#381)


class BudgetUpdateIn(In):
    name: Str(120) | None = None
    amount: Amount | None = None
    notes: OptStr(4000) = None
    continues_budget_id: int | None = None  # 1.8.0 (#89): send null to remove the link
    continues_former_budget_id: int | None = None  # 2.2.0 (#381): a budget from before PennyWarden instead


class ReasonIn(In):
    reason: Str(500)


class OptionalReasonIn(In):
    reason: OptStr(500) = None


# ------------------------------------------------------------------ entities
class EntityFields(In):
    entity_type: Literal["INDIVIDUAL", "ORGANIZATION"] | None = None
    organization_name: OptStr(200) = None
    first_name: OptStr(100) = None      # 2.2.0 (#316): the person (Individual) or contact person (Organization)
    last_name: OptStr(100) = None
    primary_contact: OptStr(200) = None  # legacy input: split into first and last name at the first space
    position: OptStr(60) = None  # 1.6.7: individuals only; same limit as a signer title
    # 2.2.0 (#315): empty = "same as" (the name / the address)
    display_name_custom: OptStr(200) = None
    mailing_address_line1: OptStr(200) = None
    mailing_address_line2: OptStr(200) = None
    mailing_city: OptStr(100) = None
    mailing_state_region: OptStr(100) = None
    mailing_postal_code: OptStr(20) = None
    mailing_country: OptStr(100) = None
    ein: OptStr(12) = None                # organizations only, 12-3456789
    address_line1: OptStr(200) = None
    address_line2: OptStr(200) = None
    city: OptStr(100) = None
    state_region: OptStr(100) = None
    postal_code: OptStr(20) = None
    country: OptStr(100) = None
    phone: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=40,
                                                    pattern=r"^[0-9+().\-\s xX#eEtT]*$")] = None  # 1.6.7: checked and tidied by fmpoc.phone
    email: OptEmail = None
    notes: OptStr(4000) = None
    is_financial_institution: bool | None = None
    confirmations: Confirmations = []


class EntityCreateIn(EntityFields):
    entity_type: Literal["INDIVIDUAL", "ORGANIZATION"]


class EntityUpdateIn(EntityFields):
    pass


# ------------------------------------------------------------------ bank accounts
AccountType = Literal["CHECKING", "SAVINGS", "MONEY_MARKET", "CERTIFICATE_OF_DEPOSIT", "INVESTMENT", "CASH", "OTHER"]


class BankAccountCreateIn(In):
    account_name: Str(120)
    financial_institution_entity_id: int
    account_type: AccountType
    account_subtype: OptStr(60) = None
    account_number: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=60)]
    register_enabled: bool | None = None
    is_primary: bool = False
    interest_rate: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=12)] = None
    opening_balance: Amount | None = None
    opening_balance_date: OptDate = None
    account_opened_date: OptDate = None     # 2.2.0 (#348)
    current_balance: Amount | None = None
    notes: OptStr(4000) = None


class BankAccountUpdateIn(In):
    account_name: Str(120) | None = None
    financial_institution_entity_id: int | None = None
    account_type: AccountType | None = None
    account_subtype: OptStr(60) = None
    account_number: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=4, max_length=60)] = None
    register_enabled: bool | None = None
    interest_rate: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=12)] = None
    opening_balance: Amount | None = None
    opening_balance_date: OptDate = None
    account_opened_date: OptDate = None     # 2.2.0 (#348): send null to clear it
    notes: OptStr(4000) = None


class ManualBalanceIn(In):
    current_balance: Amount
    reason: OptStr(500) = None
    as_of_date: OptDate = None  # 1.7.3 (#88): defaults to today
    confirmations: list[str] = Field(default_factory=list, max_length=5)   # 2.3.0 (#391): CLOSED_FISCAL_YEAR


class BalanceCorrectIn(In):                 # 2.3.0 (#391)
    balance: Amount | None = None
    as_of_date: OptDate = None
    reason: Str(500)
    confirmations: list[str] = Field(default_factory=list, max_length=5)


class BalanceRetireIn(In):                  # 2.3.0 (#391)
    reason: Str(500)
    confirmations: list[str] = Field(default_factory=list, max_length=5)


class MoveAccountIn(In):
    direction: Literal["up", "down"]


class CloseAccountIn(In):
    reason: Str(500)
    closed_date: OptDate = None


# ------------------------------------------------------------------ register
class AllocationIn(In):
    id: int | None = None
    budget_id: int
    fiscal_year_id: int | None = None
    entity_id: int | None = None
    invoice_number: OptStr(60) = None
    invoice_date: dt.date | None = None   # 2.0.0 (#165)
    description: OptStr(500) = None
    amount: Amount
    notes: OptStr(4000) = None
    no_attachment: bool | None = None  # v1.2.1 per-allocation "no attachment will be provided"
    no_attachment_reason: OptStr(500) = None


RequestKeyStr = Annotated[str | None, StringConstraints(pattern=r"^[A-Za-z0-9-]{16,64}$")]
CheckNumberStr = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=20, pattern=r"^[A-Za-z0-9-]*$")]


# 2.1.0 (#260): electronic payment methods (withdrawals)
PaymentMethod = Literal["ACH", "DEBIT_CARD", "WIRE", "ONLINE_PORTAL", "OTHER"]
PaymentReferenceStr = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=40,
                                                              pattern=r"^[A-Za-z0-9 ._/#-]*$")]


class TransactionCreateIn(In):
    bank_account_id: int
    transaction_type: Literal["DEPOSIT", "WITHDRAWAL"]
    transaction_date: OptDate = None
    clear_date: OptDate = None
    entity_id: int | None = None
    check_number: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=20,
                                                          pattern=r"^[A-Za-z0-9-]*$")] = None
    notes: OptStr(4000) = None
    allocations: Annotated[list[AllocationIn], Field(max_length=100)] = []
    create_as_void: bool = False
    void_reason: OptStr(1000) = None
    fiscal_year_id: int | None = None  # only for zero-dollar VOID accountability records
    no_attachment: bool = False
    no_attachment_reason: OptStr(500) = None
    request_key: RequestKeyStr = None  # v1.3 CR-011: one-time key per opened form (repeat submit = same result)
    # 2.1.0 (#260): paid electronically (withdrawals); the number is check_number (from our sequence) OR
    # payment_reference (a bank/vendor confirmation number) - never both
    electronic_payment: bool | None = None
    payment_method: PaymentMethod | None = None
    payment_method_other: OptStr(60) = None
    payment_reference: PaymentReferenceStr = None
    confirmations: Confirmations = []


class TransactionUpdateIn(In):
    transaction_type: Literal["DEPOSIT", "WITHDRAWAL"] | None = None
    transaction_date: OptDate = None
    clear_date: OptDate = None
    entity_id: int | None = None
    check_number: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=20,
                                                          pattern=r"^[A-Za-z0-9-]*$")] = None
    notes: OptStr(4000) = None
    allocations: Annotated[list[AllocationIn] | None, Field(max_length=100)] = None
    no_attachment: bool | None = None
    no_attachment_reason: OptStr(500) = None
    # 2.1.0 (#260): paid electronically (withdrawals); the number is check_number (from our sequence) OR
    # payment_reference (a bank/vendor confirmation number) - never both
    electronic_payment: bool | None = None
    payment_method: PaymentMethod | None = None
    payment_method_other: OptStr(60) = None
    payment_reference: PaymentReferenceStr = None
    confirmations: Confirmations = []


class TransferIn(In):
    """v1.2 transfer between two register-enabled accounts (descriptions are system generated)."""
    from_account_id: int
    to_account_id: int
    amount: Amount
    transaction_date: OptDate = None
    clear_date: OptDate = None
    entity_id: int | None = None  # v1.2.1: recorded on both legs; used in the generated description
    notes: OptStr(4000) = None
    fiscal_year_id: int | None = None
    request_key: RequestKeyStr = None


class VoidIn(In):
    reason: Str(1000)
    confirm_irreversible: bool


class VoidDateIn(In):
    """CR-001: correct the Transaction Date of a VOID transaction (no other field is writable)."""
    transaction_date: Date
    fiscal_year_id: int | None = None
    reason: OptStr(500) = None


class VoidCheckNumberIn(In):
    """v1.3 CR-011: correct (clear or change) the check number of a VOID record; the reason is required."""
    check_number: CheckNumberStr = None
    reason: Str(500)


class CheckAckIn(In):
    """v1.3 CR-012: confirm that check number(s) are not missing."""
    bank_account_id: int
    first_number: Annotated[int, Field(ge=0, le=10**12)]
    last_number: Annotated[int, Field(ge=0, le=10**12)]
    note: Str(1000)


class NoteIn(In):
    note: Str(4000)


class ReviewResolveIn(In):
    note: OptStr(1000) = None


class SignatureTemplateIn(In):
    """v1.4.1 CR-016: wording saved for the audit review signature page."""
    text: str = Field(min_length=1, max_length=4000)


class MfaCodeIn(In):
    """v1.4.1 CR-018: a 6-digit TOTP code or a recovery code (XXXX-XXXX-XXXX)."""
    code: str = Field(min_length=1, max_length=40)


class MfaVerifyIn(MfaCodeIn):
    trust_browser: bool = False


class MfaEnrollStartIn(In):
    current_code: str | None = Field(None, max_length=40)  # required when changing an existing authenticator


class MfaOwnKeyIn(In):
    """2.2.0 (#327): the key for the setup in progress - the user's own (Base32 or otpauth://totp link), or null for
    a newly generated key again."""
    own_key: str | None = Field(None, max_length=2000)


class MfaResetIn(In):
    reason: str = Field(min_length=1, max_length=500)


class MfaResetUserIn(MfaResetIn):
    compromised: bool = False   # 2.2.0 (#327): possible compromise - the next setup needs a newly generated key


class BackupCreateIn(In):
    """v1.4.1 CR-023."""
    password: str = Field(min_length=1, max_length=200)
    passphrase: str = Field(min_length=1, max_length=500)
    passphrase_confirmation: str = Field(min_length=1, max_length=500)
    # 2.0.0 (#124): also write a recovery file so this server's owner can restore it without the passphrase
    recoverable: bool = True


class RestoreUploadIn(In):
    """v1.4.1 CR-024/025: announces the size of the backup file to be uploaded in parts."""
    size: int = Field(gt=0, le=1024 ** 4)
    filename: str = Field("backup.fmbak", max_length=255)


class RestoreStartIn(In):
    passphrase: str = Field(min_length=1, max_length=500)
    password: str | None = Field(None, max_length=200)  # required once the application is initialized
    confirm: str | None = Field(None, max_length=20)  # "RESTORE" once the application is initialized


# ------------------------------------------------------------------ v1.6.0 CR-033 fundraisers
class FundraiserIn(In):
    name: Str(120)
    description: OptStr(2000) = None
    start_date: Date
    end_date: OptDate = None  # defaults to the start date (one-day event)
    budget_ids: list[int] = Field(default_factory=list, max_length=4)
    filter_text: OptStr(200) = None
    filter_regex: bool = False
    continues_from_id: int | None = None       # 2.1.0 (#277): the previous fundraiser of the series
    copy_buckets_from_id: int | None = None    # 2.1.0 (#277): "Create next year's from this one" (create only)
    goal_amount: Amount | None = None          # 2.3.0 (#372): optional goal; blank/None = no goal (left unchanged if omitted on edit)
    event_type: Literal["FUNDRAISER", "EVENT"] | None = None   # 2.4.0 (#429): create default Fundraiser; omitted on edit = unchanged


class CatalogNameIn(In):                     # 2.4.0 (#252): a unit type or category
    name: Str(80)


class InvoiceProductIn(In):                  # 2.4.0 (#252)
    name: Str(120)
    code: OptStr(30) = None
    description: OptStr(1000) = None
    unit_price: Amount
    unit_type_id: int | None = None
    category_id: int | None = None
    taxable: bool = False
    budget_id: int | None = None


class InvoiceTaxRateIn(In):                  # 2.4.0 (#252)
    name: Str(80)
    rate: Str(12)
    budget_id: int | None = None


class InvoiceDiscountIn(In):                 # 2.4.0 (#253)
    kind: Literal["AMOUNT", "PERCENT"]
    value: Str(20)
    reason: Str(200)


class InvoiceLineIn(In):                     # 2.4.0 (#253): every line comes from the catalog
    id: int | None = None
    product_id: int
    quantity: Str(14)
    discount_kind: Literal["AMOUNT", "PERCENT"] | None = None
    discount_value: OptStr(20) = None
    discount_reason: OptStr(200) = None
    custom_values: dict[str, str | None] | None = None    # 2.4.0 (#253 part 2): {field id: value}


class InvoiceIn(In):                         # 2.4.0 (#253)
    customer_entity_id: int
    invoice_date: Date
    due_date: OptDate = None
    terms_text: OptStr(200) = None
    notes: OptStr(2000) = None
    tax_rate_id: int | None = None
    discount: InvoiceDiscountIn | None = None
    lines: list[InvoiceLineIn] = Field(default_factory=list, max_length=200)
    custom_values: dict[str, str | None] | None = None    # 2.4.0 (#253 part 2)


class InvoiceFieldIn(In):                    # 2.4.0 (#253 part 2): an Administrator-defined field
    level: Literal["INVOICE", "LINE"] | None = None
    field_type: Literal["TEXT", "NUMBER", "DATE", "PICKLIST"] | None = None
    name: Str(60)
    options: list[Str(80)] = Field(default_factory=list, max_length=50)
    required: bool = False
    show_on_pdf: bool = True


class InvoiceSetupIn(In):                    # 2.4.0 (#253): the Administrator's setup
    number_pattern: Str(40)
    terms_days: int = 30
    terms_text: OptStr(200) = None
    default_notes: OptStr(2000) = None
    overdue_reminder_days: int | None = None      # 2.4.0 (#255): reminder to Invoice Managers, due date + N days


class InvoiceWriteOffDecisionIn(In):          # 2.4.0 (#253)
    approve: bool
    note: OptStr(500) = None


class InvoicePaymentIn(In):                   # 2.4.0 (#254): Record payment (Register User)
    bank_account_id: int
    amount: Amount
    transaction_date: OptDate = None
    clear_date: OptDate = None
    notes: OptStr(4000) = None
    confirm_overpayment: bool = False
    confirmations: Confirmations = []


class InvoiceLinkIn(In):                      # 2.4.0 (#254)
    allocation_id: int
    confirmations: Confirmations = []


class InvoiceUnlinkIn(In):                    # 2.4.0 (#254)
    move_to_budget_id: int
    reason: Str(500)


class InvoiceRefundIn(In):                    # 2.4.0 (#254): refund of an overpayment
    bank_account_id: int
    amount: Amount
    transaction_date: OptDate = None
    clear_date: OptDate = None
    check_number: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=20,
                                                          pattern=r"^[A-Za-z0-9-]*$")] = None
    electronic_payment: bool | None = None
    payment_method: PaymentMethod | None = None
    payment_reference: PaymentReferenceStr = None
    notes: OptStr(4000) = None
    confirmations: Confirmations = []


class InvoicedIncomeIn(In):                   # 2.4.0 (#250)
    invoiced_income: bool


class FundraiserLinkIn(In):                    # 2.1.0 (#277)
    continues_from_id: int | None = None


class FundraiserSeriesIn(In):
    name: OptStr(120) = None
    group_as_other: bool | None = None


class FundraiserSeriesResultIn(In):
    fiscal_year_label: Str(40)
    net: Amount
    income: Amount | None = None
    expense: Amount | None = None
    note: OptStr(500) = None
    estimated: bool = False                    # 2.3.0 (#390): the note is then required


class FundraiserSeriesResultCorrectIn(In):     # 2.3.0 (#390)
    net: Amount
    income: Amount | None = None
    expense: Amount | None = None
    note: OptStr(500) = None
    estimated: bool = False
    reason: Str(500)


class BudgetHistoryIn(In):
    """2.2.0 (#284): a year before PennyWarden, entered on a budget's History (#381: or on a former budget, with the
    code and name it had that year, optional)."""
    fiscal_year_label: Str(40)
    budgeted: Amount
    actual: Amount
    note: OptStr(500) = None
    code: OptStr(20) = None
    name: OptStr(120) = None
    estimated: bool = False                    # 2.3.0 (#390): the note is then required


class BudgetHistoryCorrectIn(In):
    fiscal_year_label: Str(40) | None = None
    budgeted: Amount | None = None
    actual: Amount | None = None
    note: OptStr(500) = None
    code: OptStr(20) = None
    name: OptStr(120) = None
    estimated: bool | None = None              # 2.3.0 (#390)
    reason: Str(500)


class BudgetInclusionIn(In):
    """2.3.0 (#414): a year the budget's money was included in another budget. A year in PennyWarden:
    fiscal_year_id + included_budget_id; a year before PennyWarden: fiscal_year_label + included_former_budget_id."""
    fiscal_year_id: int | None = None
    included_budget_id: int | None = None
    fiscal_year_label: OptStr(40) = None
    included_former_budget_id: int | None = None
    note: OptStr(500) = None


class BudgetHistoryCsvIn(In):
    fiscal_year_id: int
    csv: str = Field(min_length=1, max_length=600_000)


class FormerBudgetIn(In):
    """2.2.0 (#381): a budget from before PennyWarden."""
    code: Str(20)
    name: Str(120)
    budget_type: Literal["INCOME", "EXPENSE"]
    note: OptStr(500) = None


class FormerBudgetUpdateIn(In):
    code: Str(20) | None = None
    name: Str(120) | None = None
    budget_type: Literal["INCOME", "EXPENSE"] | None = None
    note: OptStr(500) = None
    reason: OptStr(500) = None


class FormerLinkIn(In):
    """2.2.0 (#381): the former budget a budget continues; null removes the link."""
    former_budget_id: int | None = None


class FundraiserSeriesMergeIn(In):
    into_series_id: int


class FundraiserSeriesAddIn(In):
    """2.2.0 (#302): put a fundraiser in no series into an existing series."""
    series_id: int


class FundraiserFyNotesIn(In):
    fiscal_year_id: int
    notes: OptStr(10000) = None


class FundraiserPreviewIn(In):
    budget_ids: list[int] = Field(default_factory=list, max_length=4)
    filter_text: OptStr(200) = None
    filter_regex: bool = False


class ModulesIn(In):
    fundraisers: bool | None = None
    checks: bool | None = None   # 2.0.0 (#156): Check Printing
    donations: bool | None = None   # 2.1.0 (#312): Donations (receipt letters)
    invoices: bool | None = None    # 2.4.0 (#251): Invoices


# ------------------------------------------------------------------ v1.6.1 CR-034 fundraiser management
class FundraiserBucketIn(In):
    name: Str(80)
    description: OptStr(500) = None
    category_id: int | None = None      # 2.1.0 (#278): one category or none
    is_donation: bool | None = None     # 2.2.0 (#256): the bucket holds donations (None: unchanged)


class FundraiserNotesIn(In):           # 2.1.0 (#275): the stakeholder report's summary notes
    summary_notes: OptStr(10000) = None


class FundraiserFinalIn(In):           # 2.1.0 (#275): Mark results final (reversible)
    final: bool


class FundraiserCategoryIn(In):         # 2.1.0 (#278)
    name: Str(80)
    description: OptStr(500) = None


class FundraiserOrderIn(In):            # 2.1.0 (#278): every category (or bucket) of the fundraiser, in the new order
    ids: list[int] = Field(min_length=1, max_length=60)


class FundraiserClassificationIn(In):
    kind: Literal["CASH_FLOAT_OUT", "CASH_FLOAT_RETURNED"]
    amount: Amount
    note: OptStr(500) = None


class FundraiserBucketAmountIn(In):
    """A bucket's part of a line. Either `amount` (as before 2.1.0), or 2.1.0 (#278) `charge` with an optional `less`
    and `less_description`: the net (charge - less) is what counts toward the line."""
    bucket_id: int
    amount: Amount | None = None
    charge: Amount | None = None
    less: Amount | None = None
    less_description: OptStr(200) = None
    contributor_override: OptStr(120) = None   # 2.1.0: the contributor shown on the fundraiser reports (e.g. "Cash")


class FundraiserLineIn(In):
    excluded: bool = False
    exclusion_reason: OptStr(500) = None
    classification: FundraiserClassificationIn | None = None
    buckets: list[FundraiserBucketAmountIn] = Field(default_factory=list, max_length=30)
    # 2.1.0 (#303): the contributor shown on the reports for the part of the line in no bucket (e.g. "Cash")
    contributor_override: OptStr(120) = None


# ------------------------------------------------------------------ v1.6.3 CR-036 reminders
class ReminderIn(In):
    scope: Literal["PERSONAL", "ORGANIZATION"] = "PERSONAL"
    title: Str(200)
    details: OptStr(2000) = None
    due_date: Date
    notify_days_before: int = Field(0, ge=0, le=365)
    link_type: Literal["FISCAL_YEAR", "BUDGET", "BANK_ACCOUNT"] | None = None
    link_id: int | None = None
    # 1.6.7: organization reminders can repeat
    repeat_every: int | None = Field(None, ge=1, le=365)
    repeat_unit: Literal["DAY", "WEEK", "MONTH", "YEAR"] | None = None
    repeat_until: Date | None = None


class ReminderResolveIn(In):
    note: OptStr(500) = None
    stop_repeating: bool = False


# ------------------------------------------------------------------ 1.8.0 (#106) Financial Flow Report
class FlowReportIn(In):
    title: Str(120)
    date_from: Date
    date_to: OptDate = None                     # empty = today, printed as "Current"
    bank_account_ids: list[int] = Field(min_length=1, max_length=50)
    include_balances: bool = False
    compare_date: OptDate = None                # only with include_balances; earlier than the Through Date
    notes: OptStr(4000) = None
    show_substitution_notes: bool = False       # 2.2.0 (#348): notes on substituted starting values in the PDF


class FlowExclusionIn(In):
    key: str = Field(min_length=2, max_length=24)
    reason: str = Field(max_length=1000)        # required (checked by the service so the message names the line)


class FlowLineNoteIn(In):
    key: str = Field(min_length=2, max_length=24)
    note: OptStr(1000) = None


class FlowReportPdfIn(FlowReportIn):
    exclusions: list[FlowExclusionIn] = Field(default_factory=list, max_length=5000)
    line_notes: list[FlowLineNoteIn] = Field(default_factory=list, max_length=5000)
    download: bool = False


# ------------------------------------------------------------------ 1.8.0 (#113) forgotten password
class SecurityAnswerIn(In):
    question: Annotated[str, StringConstraints(max_length=40)]
    answer: Annotated[str, StringConstraints(max_length=200)]


class SecurityQuestionsIn(In):
    questions: list[SecurityAnswerIn] = Field(max_length=10)


class SecurityQuestionsChangeIn(SecurityQuestionsIn):
    current_password: Annotated[str, StringConstraints(max_length=256)]


class SetupPasswordIn(In):
    new_password: Annotated[str, StringConstraints(max_length=256)]
    new_password_confirmation: Annotated[str, StringConstraints(max_length=256)]


class ForgotStartIn(In):
    username: Annotated[str, StringConstraints(max_length=64)]


class ForgotCompleteIn(In):
    username: Annotated[str, StringConstraints(max_length=64)]
    answer: Annotated[str, StringConstraints(max_length=200)]
    code: Annotated[str | None, StringConstraints(max_length=40)] = None
    new_password: Annotated[str, StringConstraints(max_length=256)]
    new_password_confirmation: Annotated[str, StringConstraints(max_length=256)]


# ------------------------------------------------------------------ 1.9.0 (#62) scheduled automatic backups
class BackupScheduleIn(In):
    enabled: bool = False
    frequency: Literal["DAILY", "WEEKLY"] = "DAILY"
    weekday: int | None = Field(default=0, ge=0, le=6)          # 0 = Monday
    time_of_day: Annotated[str, StringConstraints(max_length=5)] = "02:00"
    destination: OptStr(1000) = None
    keep_daily: int | None = Field(default=None, ge=0, le=366)
    keep_weekly: int | None = Field(default=None, ge=0, le=366)
    keep_monthly: int | None = Field(default=None, ge=0, le=366)
    # setting or changing the backup passphrase (needs the Administrator's own password)
    passphrase: Annotated[str | None, StringConstraints(max_length=500)] = None
    passphrase_confirmation: Annotated[str | None, StringConstraints(max_length=500)] = None
    password: Annotated[str | None, StringConstraints(max_length=200)] = None


class BackupFolderTestIn(In):
    destination: OptStr(1000) = None


# ------------------------------------------------------------------ 1.10.0 (#58) update notification
class UpdateSettingsIn(In):
    enabled: bool


# ------------------------------------------------------------------ 2.1.0 (#257, #261) budget planning
class ProjectionChoiceIn(In):
    budget_id: int
    project: bool


class ProjectionChoicesIn(In):
    fiscal_year_id: int
    choices: list[ProjectionChoiceIn] = Field(default_factory=list, max_length=2000)
    reset: bool = False      # forget this user's choices for the year (back to the defaults)
