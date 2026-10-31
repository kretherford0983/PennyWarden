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


# ------------------------------------------------------------------ 2.4.0 (#253): invoices
from fastapi import Query, Request  # noqa: E402
from fastapi.responses import Response  # noqa: E402

from ..schemas import InvoiceFieldIn, InvoiceIn, InvoiceSetupIn, InvoiceWriteOffDecisionIn, ReasonIn  # noqa: E402
from ..services import invoice_docs as docs  # noqa: E402


@router.put("/setup")
def save_setup(body: InvoiceSetupIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.setup"))):
    out = docs.save_setup(db, ctx, body)
    db.commit()
    return out


@router.get("/setup/test-print")
def setup_test_print(db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.setup"))):
    """The Administrator's test print: sample data only (BR-003) - no invoice, customer or product is read."""
    svc.require_module(db, ctx)
    pdf = docs.invoice_pdf(db, ctx.workspace_id, None, sample=True, watermark="SAMPLE")
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="invoice-sample.pdf"', "Cache-Control": "no-store"})


@router.get("/fields")
def invoice_fields(db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.view"))):
    """2.4.0 (#253 part 2): the active custom fields, for the invoice form."""
    svc.require_module(db, ctx)
    return [docs.field_out(f) for f in docs.fields_of(db, ctx.workspace_id)]


@router.post("/setup/fields", status_code=201)
def create_field(body: InvoiceFieldIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.setup"))):
    out = docs.save_field(db, ctx, None, body)
    db.commit()
    return out


@router.put("/setup/fields/{fid}")
def update_field(fid: int, body: InvoiceFieldIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.setup"))):
    out = docs.save_field(db, ctx, fid, body)
    db.commit()
    return out


@router.post("/setup/fields/{fid}/{action}")
def field_active(fid: int, action: Literal["retire", "restore"], db: Session = Depends(get_db),
                 ctx: Ctx = Depends(require("invoice.setup"))):
    out = docs.set_field_active(db, ctx, fid, action == "restore")
    db.commit()
    return out


@router.get("")
def list_invoices(status: Literal["DRAFT", "SENT", "PARTLY_PAID", "PAID", "VOID", "WRITTEN_OFF", "OPEN"] | None = None,
                  customer_entity_id: int | None = None, search: str | None = Query(None, max_length=100),
                  db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.view"))):
    return docs.list_out(db, ctx, status, customer_entity_id, search)


@router.post("", status_code=201)
def create_invoice(body: InvoiceIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.manage"))):
    i = docs.create(db, ctx, body)
    db.commit()
    return docs.out(db, ctx, i)


@router.get("/{iid}")
def get_invoice(iid: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.view"))):
    return docs.out(db, ctx, docs.get(db, ctx, iid))


@router.put("/{iid}")
def update_invoice(iid: int, body: InvoiceIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.manage"))):
    i = docs.update(db, ctx, docs.get(db, ctx, iid), body)
    db.commit()
    return docs.out(db, ctx, i)


@router.get("/{iid}/pdf")
def invoice_pdf(iid: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.view"))):
    """The current version as a PDF (a draft is marked DRAFT). Sent versions are kept as attachments."""
    i = docs.get(db, ctx, iid)
    pdf = docs.invoice_pdf(db, ctx.workspace_id, i, watermark="DRAFT" if i.status == "DRAFT" else None)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="invoice-{docs.display_number(i)}.pdf"',
                             "Cache-Control": "no-store"})


@router.post("/{iid}/send")
def send_invoice(iid: int, request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.manage"))):
    i = docs.send(db, ctx, request.app.state.settings, docs.get(db, ctx, iid))
    return docs.out(db, ctx, i)


@router.post("/{iid}/revise")
def revise_invoice(iid: int, body: ReasonIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.manage"))):
    i = docs.revise(db, ctx, docs.get(db, ctx, iid), body.reason)
    db.commit()
    return docs.out(db, ctx, i)


@router.post("/{iid}/void")
def void_invoice(iid: int, body: ReasonIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.manage"))):
    i = docs.void(db, ctx, docs.get(db, ctx, iid), body.reason)
    db.commit()
    return docs.out(db, ctx, i)


@router.post("/{iid}/write-off")
def request_write_off(iid: int, body: ReasonIn, db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.manage"))):
    i = docs.request_write_off(db, ctx, docs.get(db, ctx, iid), body.reason)
    db.commit()
    return docs.out(db, ctx, i)


@router.post("/{iid}/write-off/decision")
def decide_write_off(iid: int, body: InvoiceWriteOffDecisionIn, db: Session = Depends(get_db),
                     ctx: Ctx = Depends(require("invoice.write_off_decide"))):
    i = docs.decide_write_off(db, ctx, docs.get(db, ctx, iid), body.approve, body.note)
    db.commit()
    return docs.out(db, ctx, i)


# ------------------------------------------------------------------ 2.4.0 (#254): payments
from ..schemas import InvoiceLinkIn, InvoicePaymentIn, InvoiceRefundIn, InvoiceUnlinkIn  # noqa: E402
from ..services import invoice_payments as pay  # noqa: E402
from ..services import register as reg_svc  # noqa: E402


@router.post("/{iid}/payments", status_code=201)
def record_payment(iid: int, body: InvoicePaymentIn, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(require("invoice.record_payment"))):
    """Register User: creates the deposit (allocations on the lines' Invoiced Income budgets) and links it."""
    i = docs.get(db, ctx, iid)
    t = pay.record_payment(db, ctx, i, body)
    db.commit()
    return {"invoice": docs.out(db, ctx, i), "transaction": reg_svc.out(db, t)}


@router.get("/{iid}/link-candidates")
def link_candidates(iid: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.link_payment"))):
    return pay.candidates(db, ctx, docs.get(db, ctx, iid))


@router.post("/{iid}/links", status_code=201)
def link_payment(iid: int, body: InvoiceLinkIn, db: Session = Depends(get_db),
                 ctx: Ctx = Depends(require("invoice.link_payment"))):
    i = docs.get(db, ctx, iid)
    pay.link(db, ctx, i, body.allocation_id, body.confirmations)
    db.commit()
    return docs.out(db, ctx, i)


@router.post("/{iid}/links/{link_id}/unlink")
def unlink_payment(iid: int, link_id: int, body: InvoiceUnlinkIn, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(require("transaction.manage"))):
    i = docs.get(db, ctx, iid)
    pay.unlink(db, ctx, i, link_id, body.move_to_budget_id, body.reason)
    db.commit()
    return docs.out(db, ctx, i)


@router.post("/{iid}/refunds", status_code=201)
def refund(iid: int, body: InvoiceRefundIn, db: Session = Depends(get_db),
           ctx: Ctx = Depends(require("invoice.record_payment"))):
    i = docs.get(db, ctx, iid)
    t = pay.refund(db, ctx, i, body)
    db.commit()
    return {"invoice": docs.out(db, ctx, i), "transaction": reg_svc.out(db, t)}
