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
            "fiscal_year": fy.display_name if fy else None, "invoiced_income": bool(b.invoiced_income)}


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


def needs_budget(db: Session, p: InvoiceProduct | InvoiceTaxRate, fy: FiscalYear | None) -> bool:
    if getattr(p, "is_system", False) or not p.active:
        return False
    return budget_for_year(db, p.budget_id, fy) is None


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
def list_simple(db: Session, ctx, kind: str, include_inactive: bool) -> list[dict]:
    _require_view(db, ctx)
    model = KINDS[kind]
    q = select(model).where(model.workspace_id == ctx.workspace_id).order_by(func.lower(model.name))
    if not include_inactive:
        q = q.where(model.active.is_(True))
    return [_simple(x) for x in db.scalars(q)]


def save_simple(db: Session, ctx, kind: str, oid: int | None, name: str) -> dict:
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
    return _simple(x)


# ------------------------------------------------------------------ products
def product_snapshot(p: InvoiceProduct) -> dict:
    return {"id": p.id, "name": p.name, "code": p.code, "description": p.description,
            "unit_price": fmt(p.unit_price_cents), "unit_type_id": p.unit_type_id, "category_id": p.category_id,
            "taxable": bool(p.taxable), "budget_id": p.budget_id, "is_system": bool(p.is_system),
            "active": bool(p.active)}


def product_out(db: Session, p: InvoiceProduct, fy: FiscalYear | None) -> dict:
    u = db.get(InvoiceUnitType, p.unit_type_id) if p.unit_type_id else None
    c = db.get(InvoiceProductCategory, p.category_id) if p.category_id else None
    now = budget_for_year(db, p.budget_id, fy)
    return {**product_snapshot(p), "unit_type": u.name if u else None, "category": c.name if c else None,
            "budget": _budget_brief(db, p.budget_id),
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
    if body.budget_id is None:
        raise validation("Choose the Invoiced Income budget the money goes to.", "budget_id")
    if p is None or body.budget_id != p.budget_id:
        _leaf_ok(db, db.get(Budget, body.budget_id), ctx.workspace_id)
    code = (body.code or "").strip() or None
    if code and db.scalar(select(InvoiceProduct.id).where(
            InvoiceProduct.workspace_id == ctx.workspace_id, func.lower(InvoiceProduct.code) == code.lower(),
            InvoiceProduct.id != (p.id if p else -1))) is not None:
        raise conflict("DUPLICATE_CODE", f"Another product already uses the code {code}.")
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
