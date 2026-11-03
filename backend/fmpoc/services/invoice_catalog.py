"""2.4.0 (#252): the Invoices product catalog - products, tax rates, unit types and categories.

* Maintained by Invoice Managers (`invoice.catalog_manage`); Budget Managers, Budget Users and Auditors view it
  (`invoice.catalog_view`); the Administrator has no access (BR-003). The module must be on.
* Inactivated (retired) and restored, never deleted (BR-001); every change audited with before/after (BR-075/076).
* A product's and a tax rate's budget is an **Invoiced Income** budget (#250), picked from a list that shows code and
  name only - no amounts, actuals or links to budget screens.
* Prices are copied onto invoice lines when added (later build), so a catalog change never alters an issued invoice.
* Across Fiscal Years a product's budget follows the continuation link (#89): `budget_for_year()`. A product whose
  budget has no Invoiced Income continuation in the current Fiscal Year shows *needs budget*.
"""
from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, conflict, not_found, validation
from ..models import (Budget, FiscalYear, InvoiceProduct, InvoiceProductCategory, InvoiceTaxRate, InvoiceUnitType,
                      utcnow)
from ..money import fmt, parse_amount
from . import budgets as bsvc
from . import invoices as inv
from .common import budget_label

DEFAULT_UNIT_TYPES = ("Each", "Hour", "Day", "Week", "Month", "Year")
DISCOUNT_NAME = "Discount"
KINDS = {"unit-types": InvoiceUnitType, "categories": InvoiceProductCategory}


# ------------------------------------------------------------------ seed (when the module is turned on)
def ensure_seeded(db: Session, ctx) -> None:
    """The common unit types and the built-in Discount item, once per workspace (audited as created)."""
    ws = ctx.workspace_id
    if db.scalar(select(func.count(InvoiceUnitType.id)).where(InvoiceUnitType.workspace_id == ws)) == 0:
        for name in DEFAULT_UNIT_TYPES:
            u = InvoiceUnitType(workspace_id=ws, name=name, created_by_user_id=ctx.user.id if ctx.user else None)
            db.add(u)
            db.flush()
            audit.record(db, ctx, "INVOICE_UNIT_TYPE_CREATED", "invoice_unit_type", u.id, None, _simple(u))
    if db.scalar(select(InvoiceProduct.id).where(InvoiceProduct.workspace_id == ws,
                                                 InvoiceProduct.is_system.is_(True))) is None:
        d = InvoiceProduct(workspace_id=ws, name=DISCOUNT_NAME, is_system=True, unit_price_cents=0,
                           description="A fixed amount or a percentage off a line or the whole invoice, with a reason.",
                           created_by_user_id=ctx.user.id if ctx.user else None)
        db.add(d)
        db.flush()
        audit.record(db, ctx, "INVOICE_PRODUCT_CREATED", "invoice_product", d.id, None, product_snapshot(d))


# ------------------------------------------------------------------ Invoiced Income budgets (the picker)
def _leaf_ok(db: Session, b: Budget | None, ws_id: int) -> Budget:
    """A budget id as offered by the picker (a selectable leaf, like the Register's) on an Invoiced Income family."""
    if b is None or b.workspace_id != ws_id:
        raise not_found("Budget")
    if b.budget_type != "INCOME" or not b.invoiced_income or b.is_budget_zero:
        raise validation("Choose an Invoiced Income budget.", "budget_id")
    if b.status in ("REJECTED", "INACTIVE", "DELETED"):
        raise validation("That budget is rejected, inactive or deleted; choose another.", "budget_id")
    fy = db.get(FiscalYear, b.fiscal_year_id)
    if fy.status == "CLOSED":
        raise validation(f"{fy.display_name} is closed; choose a budget of an open Fiscal Year.", "budget_id")
    if b.parent_budget_id is None:
        explicit, _other = bsvc.children_of(db, b)
        if explicit:
            raise validation("This budget has sub-budgets; choose one of them.", "budget_id")
        raise validation("Choose the budget as offered in the list.", "budget_id")
    return b


def budget_options(db: Session, ctx) -> list[dict]:
    """Per open Fiscal Year, the Invoiced Income budgets a product or tax rate can use: code and name only."""
    out = []
    for fy in db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ctx.workspace_id,
                                                  FiscalYear.status != "CLOSED").order_by(FiscalYear.start_date)):
        opts = []
        for o in bsvc.selectable(db, ctx.workspace_id, fy, "DEPOSIT"):
            b = db.get(Budget, o["id"])
            if b is not None and b.invoiced_income and not b.is_budget_zero:
                opts.append({"id": b.id, "label": o["label"]})
        if opts:
            out.append({"fiscal_year": {"id": fy.id, "display_name": fy.display_name, "status": fy.status},
                        "budgets": opts})
    return out


def _budget_brief(db: Session, budget_id: int | None) -> dict | None:
    if budget_id is None:
        return None
    b = db.get(Budget, budget_id)
    if b is None:
        return None
    p = db.get(Budget, b.parent_budget_id) if b.parent_budget_id else None
    simple = b.is_other and p is not None and not bsvc.children_of(db, p)[0]
    fy = db.get(FiscalYear, b.fiscal_year_id)
    return {"id": b.id, "label": budget_label(p, None) if simple else budget_label(b, p),
            "fiscal_year": fy.display_name if fy else None, "fiscal_year_id": b.fiscal_year_id,
            "invoiced_income": bool(b.invoiced_income)}


def current_fiscal_year(db: Session, ws_id: int, today: dt.date | None = None) -> FiscalYear | None:
    """The open Fiscal Year covering today, else the latest open one (where new invoices go)."""
    today = today or dt.date.today()
    fys = list(db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ws_id, FiscalYear.status != "CLOSED")
                          .order_by(FiscalYear.start_date)))
    covering = [f for f in fys if f.start_date <= today <= f.end_date]
    return covering[0] if covering else (fys[-1] if fys else None)


def budget_for_year(db: Session, budget_id: int | None, fy: FiscalYear | None) -> Budget | None:
    """The Invoiced Income budget a product's budget continues into in `fy` (#89 continuation links), or None.
    A simple budget is chosen by its Other leaf: its parent's chain is followed and that year's simple leaf used."""
    if budget_id is None or fy is None:
        return None
    b = db.get(Budget, budget_id)
    if b is None:
        return None
    if b.fiscal_year_id == fy.id:
        return b
    parent = db.get(Budget, b.parent_budget_id) if b.parent_budget_id else None
    via_parent = b.is_other and parent is not None
    cur = parent if via_parent else b
    seen = set()
    while cur is not None and cur.fiscal_year_id != fy.id and cur.id not in seen:
        seen.add(cur.id)
        cur = bsvc._continued_by(db, cur.id)
    if cur is None or cur.fiscal_year_id != fy.id:
        return None
    if via_parent:
        explicit, other = bsvc.children_of(db, cur)
        cur = other if not explicit else None
    if cur is None or not cur.invoiced_income or cur.status in ("REJECTED", "INACTIVE", "DELETED"):
        return None
    return cur


def product_budget_id(db: Session, p: InvoiceProduct) -> int | None:
    """2.4.0 polish (#483): the budget a product uses - its own, else its category's current one."""
    if p.budget_id is not None or p.category_id is None:
        return p.budget_id
    c = db.get(InvoiceProductCategory, p.category_id)
    return c.budget_id if c is not None else None


def needs_budget(db: Session, p: InvoiceProduct | InvoiceTaxRate, fy: FiscalYear | None) -> bool:
    if getattr(p, "is_system", False) or not p.active:
        return False
    bid = product_budget_id(db, p) if isinstance(p, InvoiceProduct) else p.budget_id
    return budget_for_year(db, bid, fy) is None


# ------------------------------------------------------------------ shared
def _require_view(db: Session, ctx) -> None:
    inv.require_module(db, ctx)
    ctx.require("invoice.catalog_view")


def _require_manage(db: Session, ctx) -> None:
    inv.require_module(db, ctx)
    ctx.require("invoice.catalog_manage")


def _get(db: Session, ctx, model, oid: int, what: str):
    x = db.get(model, oid) if isinstance(oid, int) else None
    if x is None or x.workspace_id != ctx.workspace_id:      # BR-099: another workspace's id is simply not found
        raise not_found(what)
    return x


def _name(value: str | None, field: str, max_len: int) -> str:
    v = (value or "").strip()
    if not v:
        raise validation("Enter a name.", field)
    if len(v) > max_len:
        raise validation(f"At most {max_len} characters.", field)
    return v


def _unique(db: Session, model, ws_id: int, name: str, exclude_id: int | None, what: str) -> None:
    q = select(model.id).where(model.workspace_id == ws_id, func.lower(model.name) == name.lower())
    if exclude_id is not None:
        q = q.where(model.id != exclude_id)
    if db.scalar(q) is not None:
        raise conflict("DUPLICATE_NAME", f"A {what} named \"{name}\" already exists (it may be inactive).")


def _simple(x) -> dict:
    return {"id": x.id, "name": x.name, "active": bool(x.active)}


# ------------------------------------------------------------------ unit types and categories
def category_snapshot(c: InvoiceProductCategory) -> dict:
    return {**_simple(c), "budget_id": c.budget_id, "code_pattern": c.code_pattern}


def category_out(db: Session, c: InvoiceProductCategory) -> dict:
    """A category with its budget (code and name) and the next product code its pattern gives (#483, #486)."""
    return {**category_snapshot(c), "budget": _budget_brief(db, c.budget_id),
            "next_code": next_code(db, c) if c.code_pattern else None,
            "products_following": db.scalar(select(func.count(InvoiceProduct.id)).where(
                InvoiceProduct.category_id == c.id, InvoiceProduct.budget_id.is_(None),
                InvoiceProduct.is_system.is_(False))) or 0}


def list_simple(db: Session, ctx, kind: str, include_inactive: bool) -> list[dict]:
    _require_view(db, ctx)
    model = KINDS[kind]
    q = select(model).where(model.workspace_id == ctx.workspace_id).order_by(func.lower(model.name))
    if not include_inactive:
        q = q.where(model.active.is_(True))
    if kind == "categories":
        return [category_out(db, x) for x in db.scalars(q)]
    return [_simple(x) for x in db.scalars(q)]


# ------------------------------------------------------------------ 2.4.0 polish (#486): product code patterns
def check_code_pattern(p: str | None) -> str | None:
    """Like the invoice number pattern: exactly one {SEQ} / {SEQ:n}, optional {YY} / {YYYY}, and a code that fits."""
    from .invoice_docs import check_pattern, format_number
    p = (p or "").strip()
    if not p:
        return None
    try:
        p = check_pattern(p)
    except AppError as e:
        raise validation(str(e.message).replace("pattern needs", "code pattern needs"), "code_pattern") from None
    if len(format_number(p, dt.date(2099, 1, 1), 99999)) > 30:
        raise validation("The codes this pattern makes would be longer than 30 characters.", "code_pattern")
    return p


def _period(pattern: str, d: dt.date) -> str:
    """The counter a pattern uses: one per year when the pattern shows the year, else one that never restarts."""
    return str(d.year) if ("{YY}" in pattern or "{YYYY}" in pattern) else "0"


def _counters(c: InvoiceProductCategory) -> dict:
    try:
        return json.loads(c.code_counters) if c.code_counters else {}
    except ValueError:
        return {}


def _code_taken(db: Session, ws_id: int, code: str, exclude_id: int | None = None) -> bool:
    q = select(InvoiceProduct.id).where(InvoiceProduct.workspace_id == ws_id, func.lower(InvoiceProduct.code) == code.lower())
    if exclude_id is not None:
        q = q.where(InvoiceProduct.id != exclude_id)
    return db.scalar(q) is not None


def _next(db: Session, c: InvoiceProductCategory, pattern: str, today: dt.date | None = None) -> tuple[str, int]:
    from .invoice_docs import format_number
    today = today or dt.date.today()
    n = int(_counters(c).get(_period(pattern, today), 1)) if c.id is not None and pattern == c.code_pattern else 1
    while True:                                          # skip a number whose code another product already has
        code = format_number(pattern, today, n)
        if not _code_taken(db, c.workspace_id, code):
            return code, n
        n += 1


def next_code(db: Session, c: InvoiceProductCategory, pattern: str | None = None) -> str | None:
    p = pattern if pattern is not None else c.code_pattern
    return _next(db, c, p)[0] if p else None


def code_example(db: Session, ctx, category_id: int | None, pattern: str | None) -> dict:
    """The next product code for a category (its saved pattern) or for a pattern being typed."""
    _require_view(db, ctx)
    c = _get(db, ctx, InvoiceProductCategory, category_id, "Category") if category_id else \
        InvoiceProductCategory(workspace_id=ctx.workspace_id)
    p = check_code_pattern(pattern) if pattern is not None else c.code_pattern
    return {"pattern": p, "next_code": next_code(db, c, p) if p else None,
            "budget": _budget_brief(db, c.budget_id) if category_id else None}


def _use_code(db: Session, c: InvoiceProductCategory | None, code: str | None) -> None:
    """A product was saved with the code the category suggested: that number is used, the next one is offered next."""
    if c is None or not c.code_pattern or not code:
        return
    sug, n = _next(db, c, c.code_pattern)
    if code.lower() != sug.lower():
        return
    k = _counters(c)
    k[_period(c.code_pattern, dt.date.today())] = n + 1
    c.code_counters = json.dumps(k, sort_keys=True)


def save_category(db: Session, ctx, oid: int | None, body) -> dict:
    """#483 / #486: a category's name, optional budget and optional code pattern (audited)."""
    _require_manage(db, ctx)
    name = _name(body.name, "name", 80)
    _unique(db, InvoiceProductCategory, ctx.workspace_id, name, oid, "category")
    pattern = check_code_pattern(getattr(body, "code_pattern", None))
    budget_id = getattr(body, "budget_id", None)
    c = None if oid is None else _get(db, ctx, InvoiceProductCategory, oid, "Category")
    if budget_id is not None and (c is None or budget_id != c.budget_id):
        _leaf_ok(db, db.get(Budget, budget_id), ctx.workspace_id)
    if c is not None and c.budget_id is not None and budget_id is None:
        following = db.scalar(select(func.count(InvoiceProduct.id)).where(
            InvoiceProduct.category_id == c.id, InvoiceProduct.budget_id.is_(None), InvoiceProduct.is_system.is_(False)))
        if following:
            raise conflict("CATEGORY_BUDGET_IN_USE", f"{following} product{'s' if following != 1 else ''} use this "
                           "category's budget. Give them their own budget, or choose another budget for the category.")
    before = None if c is None else category_snapshot(c)
    if c is None:
        c = InvoiceProductCategory(workspace_id=ctx.workspace_id, created_by_user_id=ctx.user.id)
        db.add(c)
    c.name, c.budget_id, c.code_pattern, c.updated_by_user_id = name, budget_id, pattern, ctx.user.id
    db.flush()
    after = category_snapshot(c)
    if before is None:
        audit.record(db, ctx, "INVOICE_CATEGORY_CREATED", "invoice_product_category", c.id, None, after)
    elif after != before:
        audit.record(db, ctx, "INVOICE_CATEGORY_UPDATED", "invoice_product_category", c.id, before, after)
    return category_out(db, c)


def save_simple(db: Session, ctx, kind: str, oid: int | None, name: str, body=None) -> dict:
    if kind == "categories":
        return save_category(db, ctx, oid, body)
    _require_manage(db, ctx)
    model = KINDS[kind]
    what = "unit type" if kind == "unit-types" else "category"
    name = _name(name, "name", 40 if kind == "unit-types" else 80)
    _unique(db, model, ctx.workspace_id, name, oid, what)
    tag = "INVOICE_UNIT_TYPE" if kind == "unit-types" else "INVOICE_CATEGORY"
    if oid is None:
        x = model(workspace_id=ctx.workspace_id, name=name, created_by_user_id=ctx.user.id,
                  updated_by_user_id=ctx.user.id)
        db.add(x)
        db.flush()
        audit.record(db, ctx, f"{tag}_CREATED", model.__tablename__, x.id, None, _simple(x))
        return _simple(x)
    x = _get(db, ctx, model, oid, what.capitalize())
    before = _simple(x)
    if x.name != name:
        x.name, x.updated_by_user_id = name, ctx.user.id
        db.flush()
        audit.record(db, ctx, f"{tag}_UPDATED", model.__tablename__, x.id, before, _simple(x))
    return _simple(x)


def set_simple_active(db: Session, ctx, kind: str, oid: int, active: bool) -> dict:
    _require_manage(db, ctx)
    model = KINDS[kind]
    what = "Unit type" if kind == "unit-types" else "Category"
    x = _get(db, ctx, model, oid, what)
    if bool(x.active) == active:
        return _simple(x)
    before = _simple(x)
    x.active, x.updated_by_user_id = active, ctx.user.id
    db.flush()
    tag = "INVOICE_UNIT_TYPE" if kind == "unit-types" else "INVOICE_CATEGORY"
    audit.record(db, ctx, f"{tag}_{'RESTORED' if active else 'INACTIVATED'}", model.__tablename__, x.id, before,
                 _simple(x))
    return category_out(db, x) if kind == "categories" else _simple(x)


# ------------------------------------------------------------------ products
def product_snapshot(p: InvoiceProduct) -> dict:
    return {"id": p.id, "name": p.name, "code": p.code, "description": p.description,
            "unit_price": fmt(p.unit_price_cents), "unit_type_id": p.unit_type_id, "category_id": p.category_id,
            "taxable": bool(p.taxable), "budget_id": p.budget_id, "is_system": bool(p.is_system),
            "active": bool(p.active)}


def product_out(db: Session, p: InvoiceProduct, fy: FiscalYear | None) -> dict:
    u = db.get(InvoiceUnitType, p.unit_type_id) if p.unit_type_id else None
    c = db.get(InvoiceProductCategory, p.category_id) if p.category_id else None
    eff = product_budget_id(db, p)
    now = budget_for_year(db, eff, fy)
    return {**product_snapshot(p), "unit_type": u.name if u else None, "category": c.name if c else None,
            "budget": _budget_brief(db, eff),
            "own_budget": p.budget_id is not None,                       # 2.4.0 polish (#483): else the category's
            "category_budget": _budget_brief(db, c.budget_id) if c is not None else None,
            "current_budget": _budget_brief(db, now.id) if now is not None else None,
            "needs_budget": needs_budget(db, p, fy)}


def list_products(db: Session, ctx, include_inactive: bool) -> list[dict]:
    _require_view(db, ctx)
    q = select(InvoiceProduct).where(InvoiceProduct.workspace_id == ctx.workspace_id).order_by(
        InvoiceProduct.is_system.desc(), func.lower(InvoiceProduct.name))
    if not include_inactive:
        q = q.where(InvoiceProduct.active.is_(True))
    fy = current_fiscal_year(db, ctx.workspace_id)
    return [product_out(db, p, fy) for p in db.scalars(q)]


def _ref(db: Session, ctx, model, oid: int | None, field: str, what: str):
    if oid is None:
        return None
    x = db.get(model, oid)
    if x is None or x.workspace_id != ctx.workspace_id:
        raise validation(f"Unknown {what}.", field)
    if not x.active:
        raise validation(f"That {what} is inactive.", field)
    return x


def save_product(db: Session, ctx, pid: int | None, body) -> dict:
    _require_manage(db, ctx)
    name = _name(body.name, "name", 120)
    try:
        price = parse_amount(body.unit_price)
    except ValueError as e:
        raise validation(str(e), "unit_price") from None
    if body.unit_type_id is None:
        raise validation("Choose a unit type.", "unit_type_id")
    p = None if pid is None else _get(db, ctx, InvoiceProduct, pid, "Product")
    if p is not None and p.is_system:
        raise conflict("SYSTEM_ITEM", "The built-in Discount item can't be changed.")
    unit = _ref(db, ctx, InvoiceUnitType, body.unit_type_id, "unit_type_id", "unit type")
    cat = _ref(db, ctx, InvoiceProductCategory, body.category_id, "category_id", "category")
    # 2.4.0 polish (#483): no budget of its own = the category's (which then must have one)
    if body.budget_id is None and (cat is None or cat.budget_id is None):
        raise validation("Choose the Invoiced Income budget the money goes to, or a category that has one.", "budget_id")
    if body.budget_id is not None and (p is None or body.budget_id != p.budget_id):
        _leaf_ok(db, db.get(Budget, body.budget_id), ctx.workspace_id)
    code = (body.code or "").strip() or None
    if code and _code_taken(db, ctx.workspace_id, code, p.id if p else None):
        raise conflict("DUPLICATE_CODE", f"Another product already uses the code {code}.")
    if p is None or (code or "") != (p.code or ""):
        _use_code(db, cat, code)                         # #486: the category's suggested number is used up
    before = None if p is None else product_snapshot(p)
    if p is None:
        p = InvoiceProduct(workspace_id=ctx.workspace_id, created_by_user_id=ctx.user.id)
        db.add(p)
    p.name, p.code, p.description = name, code, (body.description or "").strip() or None
    p.unit_price_cents, p.unit_type_id, p.category_id = price, unit.id, cat.id if cat else None
    p.taxable, p.budget_id, p.updated_by_user_id = bool(body.taxable), body.budget_id, ctx.user.id
    db.flush()
    after = product_snapshot(p)
    if before is None:
        audit.record(db, ctx, "INVOICE_PRODUCT_CREATED", "invoice_product", p.id, None, after)
    elif after != before:
        audit.record(db, ctx, "INVOICE_PRODUCT_UPDATED", "invoice_product", p.id, before, after)
    return product_out(db, p, current_fiscal_year(db, ctx.workspace_id))


def set_product_active(db: Session, ctx, pid: int, active: bool) -> dict:
    _require_manage(db, ctx)
    p = _get(db, ctx, InvoiceProduct, pid, "Product")
    if p.is_system:
        raise conflict("SYSTEM_ITEM", "The built-in Discount item can't be inactivated.")
    if bool(p.active) != active:
        before = product_snapshot(p)
        p.active, p.updated_by_user_id = active, ctx.user.id
        db.flush()
        audit.record(db, ctx, "INVOICE_PRODUCT_RESTORED" if active else "INVOICE_PRODUCT_INACTIVATED",
                     "invoice_product", p.id, before, product_snapshot(p))
    return product_out(db, p, current_fiscal_year(db, ctx.workspace_id))


# ------------------------------------------------------------------ tax rates
def _rate(value: str | None) -> int:
    """'7.25' -> 7250 (thousandths of a percent); 0 to 100, at most three decimals."""
    raw = (value or "").strip().rstrip("%").strip()
    try:
        whole, _, frac = raw.partition(".")
        if not whole.isdigit() and not (whole == "" and frac):
            raise ValueError
        if frac and (not frac.isdigit() or len(frac) > 3):
            raise ValueError
        milli = int(whole or "0") * 1000 + int((frac + "000")[:3] or "0")
    except ValueError:
        raise validation("Enter the rate as a percentage such as 7 or 7.25 (up to three decimals).", "rate") from None
    if milli <= 0 or milli > 100000:
        raise validation("The rate must be more than 0 and at most 100 %.", "rate")
    return milli


def rate_text(milli: int) -> str:
    s = f"{milli // 1000}.{milli % 1000:03d}".rstrip("0").rstrip(".")
    return s


def tax_snapshot(t: InvoiceTaxRate) -> dict:
    return {"id": t.id, "name": t.name, "rate": rate_text(t.rate_milli_pct), "budget_id": t.budget_id,
            "active": bool(t.active)}


def tax_out(db: Session, t: InvoiceTaxRate, fy: FiscalYear | None) -> dict:
    now = budget_for_year(db, t.budget_id, fy)
    return {**tax_snapshot(t), "budget": _budget_brief(db, t.budget_id),
            "current_budget": _budget_brief(db, now.id) if now is not None else None,
            "needs_budget": needs_budget(db, t, fy)}


def list_tax_rates(db: Session, ctx, include_inactive: bool) -> list[dict]:
    _require_view(db, ctx)
    q = select(InvoiceTaxRate).where(InvoiceTaxRate.workspace_id == ctx.workspace_id).order_by(
        func.lower(InvoiceTaxRate.name))
    if not include_inactive:
        q = q.where(InvoiceTaxRate.active.is_(True))
    fy = current_fiscal_year(db, ctx.workspace_id)
    return [tax_out(db, t, fy) for t in db.scalars(q)]


def save_tax_rate(db: Session, ctx, tid: int | None, body) -> dict:
    _require_manage(db, ctx)
    name = _name(body.name, "name", 80)
    milli = _rate(body.rate)
    t = None if tid is None else _get(db, ctx, InvoiceTaxRate, tid, "Tax rate")
    _unique(db, InvoiceTaxRate, ctx.workspace_id, name, t.id if t else None, "tax rate")
    if body.budget_id is None:
        raise validation("Choose the Invoiced Income budget the tax is collected into.", "budget_id")
    if t is None or body.budget_id != t.budget_id:
        _leaf_ok(db, db.get(Budget, body.budget_id), ctx.workspace_id)
    before = None if t is None else tax_snapshot(t)
    if t is None:
        t = InvoiceTaxRate(workspace_id=ctx.workspace_id, created_by_user_id=ctx.user.id)
        db.add(t)
    t.name, t.rate_milli_pct, t.budget_id, t.updated_by_user_id = name, milli, body.budget_id, ctx.user.id
    db.flush()
    after = tax_snapshot(t)
    if before is None:
        audit.record(db, ctx, "INVOICE_TAX_RATE_CREATED", "invoice_tax_rate", t.id, None, after)
    elif after != before:
        audit.record(db, ctx, "INVOICE_TAX_RATE_UPDATED", "invoice_tax_rate", t.id, before, after)
    return tax_out(db, t, current_fiscal_year(db, ctx.workspace_id))


def set_tax_active(db: Session, ctx, tid: int, active: bool) -> dict:
    _require_manage(db, ctx)
    t = _get(db, ctx, InvoiceTaxRate, tid, "Tax rate")
    if bool(t.active) != active:
        before = tax_snapshot(t)
        t.active, t.updated_by_user_id = active, ctx.user.id
        db.flush()
        audit.record(db, ctx, "INVOICE_TAX_RATE_RESTORED" if active else "INVOICE_TAX_RATE_INACTIVATED",
                     "invoice_tax_rate", t.id, before, tax_snapshot(t))
    return tax_out(db, t, current_fiscal_year(db, ctx.workspace_id))


__all__ = ["AppError", "utcnow"]
