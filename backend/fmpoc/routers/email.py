"""2.4.0 (#249): the outgoing mail server (Administrator) and emailing invoices and statements (Invoice Managers)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..deps import Ctx, get_db, require
from ..errors import AppError
from ..schemas import EmailSendIn, EmailSettingsIn, EmailTestIn, StatementEmailIn
from ..services import email as svc
from ..services import invoice_docs as docs

router = APIRouter(tags=["email"])


def _key(request: Request):
    km = request.app.state.key
    if km is None:
        raise AppError(503, "KEY_UNAVAILABLE", "The application key is not available.")
    return km


@router.get("/api/system/email")
def email_settings(db: Session = Depends(get_db), ctx: Ctx = Depends(require("email.setup"))):
    r = svc.settings_out(db, ctx)
    db.commit()
    return r


@router.put("/api/system/email")
def save_email_settings(body: EmailSettingsIn, request: Request, db: Session = Depends(get_db),
                        ctx: Ctx = Depends(require("email.setup"))):
    r = svc.save_settings(db, ctx, _key(request), body)
    db.commit()
    return r


@router.post("/api/system/email/test")
def test_email(body: EmailTestIn, request: Request, db: Session = Depends(get_db),
               ctx: Ctx = Depends(require("email.setup"))):
    r = svc.send_test(db, ctx, _key(request), body.to)
    db.commit()
    return r


@router.get("/api/invoices/{iid}/email")
def invoice_email_form(iid: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("invoice.view"))):
    """The Send email form's starting values (Invoice Managers) and the invoice's email log (every viewer)."""
    i = docs.get(db, ctx, iid)
    out = {"log": svc.invoice_log(db, ctx, i)}
    if ctx.has("invoice.email"):
        out["defaults"] = svc.defaults(db, ctx, i)
    db.commit()
    return out


@router.post("/api/invoices/{iid}/email")
def email_invoice(iid: int, body: EmailSendIn, request: Request, db: Session = Depends(get_db),
                  ctx: Ctx = Depends(require("invoice.email"))):
    i = docs.get(db, ctx, iid)
    log = svc.email_invoice(db, ctx, _key(request), request.app.state.settings, i, body)
    db.commit()                    # the log and audit entry are kept whether or not the server took the message
    svc.raise_if_failed(log)
    return svc.log_out(db, [log])[0]


@router.get("/api/invoice-statements/email")
def statement_email_form(customer_entity_id: int, db: Session = Depends(get_db),
                         ctx: Ctx = Depends(require("invoice.email"))):
    from ..models import Entity
    from ..services import invoices as inv
    inv.require_module(db, ctx)
    e = db.get(Entity, customer_entity_id)
    if e is None or e.workspace_id != ctx.workspace_id:
        from ..errors import not_found
        raise not_found("Customer")
    r = svc.defaults(db, ctx, customer=e, kind="STATEMENT")
    db.commit()
    return r


@router.post("/api/invoice-statements/email")
def email_statement(body: StatementEmailIn, request: Request, db: Session = Depends(get_db),
                    ctx: Ctx = Depends(require("invoice.email"))):
    log = svc.email_statement(db, ctx, _key(request), body)
    db.commit()
    svc.raise_if_failed(log)
    return svc.log_out(db, [log])[0]
