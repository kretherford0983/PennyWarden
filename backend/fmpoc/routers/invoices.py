"""2.4.0 (#251): the Invoices module API (empty module; the invoice features arrive with later 2.4.0 builds)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..services import invoices as svc

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


@router.get("/overview")
def overview(db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.view"))):
    """The Invoices landing page: what this user may do. Refused while the module is off (BR-091)."""
    svc.require_module(db, ctx)
    return svc.overview(ctx)


@router.get("/setup")
def setup(db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.setup"))):
    """The Administrator's module setup (filled in by the Invoices build). No real invoices or products (BR-003)."""
    svc.require_module(db, ctx)
    return svc.setup(db, ctx)


# ------------------------------------------------------------------ 2.4.0 (#252): the product catalog
from typing import Literal  # noqa: E402

from ..schemas import CatalogNameIn, InvoiceProductIn, InvoiceTaxRateIn  # noqa: E402
from ..services import invoice_catalog as cat  # noqa: E402

Simple = Literal["unit-types", "categories"]


@router.get("/catalog/budget-options")
def catalog_budget_options(db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.catalog_manage"))):
    """Invoiced Income budgets by code and name only - no amounts, no budget screens."""
    svc.require_module(db, ctx)
    return cat.budget_options(db, ctx)


@router.get("/catalog/products")
def products(include_inactive: bool = False, db: Session = Depends(get_db),
             ctx: Ctx = Depends(require("invoice.catalog_view"))):
    return cat.list_products(db, ctx, include_inactive)


@router.post("/catalog/products", status_code=201)
def create_product(body: InvoiceProductIn, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(require("invoice.catalog_manage"))):
    out = cat.save_product(db, ctx, None, body)
    db.commit()
    return out


@router.put("/catalog/products/{pid}")
def update_product(pid: int, body: InvoiceProductIn, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(require("invoice.catalog_manage"))):
    out = cat.save_product(db, ctx, pid, body)
    db.commit()
    return out


@router.post("/catalog/products/{pid}/{action}")
def product_active(pid: int, action: Literal["inactivate", "restore"], db: Session = Depends(get_db),
                   ctx: Ctx = Depends(require("invoice.catalog_manage"))):
    out = cat.set_product_active(db, ctx, pid, action == "restore")
    db.commit()
    return out


@router.get("/catalog/tax-rates")
def tax_rates(include_inactive: bool = False, db: Session = Depends(get_db),
              ctx: Ctx = Depends(require("invoice.catalog_view"))):
    return cat.list_tax_rates(db, ctx, include_inactive)


@router.post("/catalog/tax-rates", status_code=201)
def create_tax_rate(body: InvoiceTaxRateIn, db: Session = Depends(get_db),
                    ctx: Ctx = Depends(require("invoice.catalog_manage"))):
    out = cat.save_tax_rate(db, ctx, None, body)
    db.commit()
    return out


@router.put("/catalog/tax-rates/{tid}")
def update_tax_rate(tid: int, body: InvoiceTaxRateIn, db: Session = Depends(get_db),
                    ctx: Ctx = Depends(require("invoice.catalog_manage"))):
    out = cat.save_tax_rate(db, ctx, tid, body)
    db.commit()
    return out


@router.post("/catalog/tax-rates/{tid}/{action}")
def tax_active(tid: int, action: Literal["inactivate", "restore"], db: Session = Depends(get_db),
               ctx: Ctx = Depends(require("invoice.catalog_manage"))):
    out = cat.set_tax_active(db, ctx, tid, action == "restore")
    db.commit()
    return out


@router.get("/catalog/{kind}")
def simple_list(kind: Simple, include_inactive: bool = False, db: Session = Depends(get_db),
                ctx: Ctx = Depends(require("invoice.catalog_view"))):
    return cat.list_simple(db, ctx, kind, include_inactive)


@router.post("/catalog/{kind}", status_code=201)
def simple_create(kind: Simple, body: CatalogNameIn, db: Session = Depends(get_db),
                  ctx: Ctx = Depends(require("invoice.catalog_manage"))):
    out = cat.save_simple(db, ctx, kind, None, body.name)
    db.commit()
    return out


@router.put("/catalog/{kind}/{oid}")
def simple_update(kind: Simple, oid: int, body: CatalogNameIn, db: Session = Depends(get_db),
                  ctx: Ctx = Depends(require("invoice.catalog_manage"))):
    out = cat.save_simple(db, ctx, kind, oid, body.name)
    db.commit()
    return out


@router.post("/catalog/{kind}/{oid}/{action}")
def simple_active(kind: Simple, oid: int, action: Literal["inactivate", "restore"], db: Session = Depends(get_db),
                  ctx: Ctx = Depends(require("invoice.catalog_manage"))):
    out = cat.set_simple_active(db, ctx, kind, oid, action == "restore")
    db.commit()
    return out
