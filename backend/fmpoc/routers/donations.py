"""2.1.0 (#312): Donations module API - donation receipt letters.

Setup (Administrators, donation.setup): the organization's EIN and mailing address, the receipt template and signer,
a live preview and a test print with sample data only (BR-003).
Deposits (donation.view: Budget Managers, Budget Users, Register Users, Auditors): a deposit's donation lines and
receipts. Marking lines and printing receipts: Register Users (donation.print).
Every endpoint needs the module switched on (404 MODULE_DISABLED otherwise)."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import audit
from ..deps import Ctx, get_db, require
from ..errors import AppError, not_found
from ..schemas import TransactionCreateIn
from ..services import donations as svc
from ..services import donation_statements as stm
from ..services import idempotency
from ..services import register as reg
from ..services.checkprint import raster
from .checks import EnvelopeIn, EnvelopePrinterIn, _pdf

router = APIRouter(prefix="/api/donations", tags=["donations"])


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SetupIn(In):
    config: dict


class PreviewIn(In):
    config: dict | None = None        # the setup screen's unsaved settings


class LinesIn(In):
    lines: list[svc.LineIn] = Field(max_length=200)
    confirmations: list[str] = Field(default_factory=list, max_length=10)   # 2.4.0 (#562): linking
    donors: list[svc.DonorIn] = Field(default_factory=list, max_length=200)   # {DETAILS} per donor


class ReceiptIn(In):
    donor_entity_id: int
    confirmations: list[str] = Field(default_factory=list, max_length=10)
    signer_id: int | None = None          # 2.3.0 polish: the signer chosen when printing


class SignerChoiceIn(In):
    signer_id: int | None = None          # 2.3.0 polish: the signer chosen when printing


def setup_ctx(db: Session = Depends(get_db), ctx: Ctx = Depends(require("donation.setup"))) -> Ctx:
    svc.require_module(db, ctx)
    return ctx


def view_ctx(db: Session = Depends(get_db), ctx: Ctx = Depends(require("donation.view"))) -> Ctx:
    svc.require_module(db, ctx)
    return ctx


def print_ctx(db: Session = Depends(get_db), ctx: Ctx = Depends(require("donation.print"))) -> Ctx:
    svc.require_module(db, ctx)
    return ctx


@router.get("/setup")
def get_setup(db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    return svc.setup_out(db, ctx)


@router.put("/setup")
def save_setup(body: SetupIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    svc.save_config(db, ctx, body.config)
    db.commit()
    return svc.setup_out(db, ctx)


# 2.4.0 polish (#503): the receipt letter's and the year-end statement's own logos
@router.post("/setup/logo/{which}")
async def letter_logo(which: str, file: UploadFile = File(...), db: Session = Depends(get_db),
                      ctx: Ctx = Depends(setup_ctx)):
    from ..services.checkprint.service import MAX_LOGO_BYTES
    data = await file.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise AppError(413, "FILE_TOO_LARGE", "A logo may not exceed 1 MB.")
    svc.set_letter_logo(db, ctx, which, data)
    db.commit()
    return svc.setup_out(db, ctx)


@router.post("/setup/logo/{which}/remove")
def letter_logo_remove(which: str, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    svc.set_letter_logo(db, ctx, which, None)
    db.commit()
    return svc.setup_out(db, ctx)


@router.get("/setup/logo/{which}")
def letter_logo_image(which: str, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    row = svc._settings_row(db, ctx.workspace_id)
    png = getattr(row, f"{which}_logo_png", None) if row is not None and which in ("receipt", "statement") else None
    if not png:
        raise AppError(404, "NOT_FOUND", "Logo not found.")
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/setup/preview")
def setup_preview(body: PreviewIn, request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    """The live preview with sample data (unsaved settings). Nothing is printed or stored, so not audited. 2.3.0
    (#395): the Administrator's preview shows the real signature for Signature image + printed."""
    return _pdf(ctx, svc.sample_pdf(db, ctx, body.config, request.app.state.key), "receipt-preview.pdf")


@router.post("/setup/preview-image")
def setup_preview_image(body: PreviewIn, request: Request, db: Session = Depends(get_db),
                        ctx: Ctx = Depends(setup_ctx)):
    if not raster.available():
        raise AppError(501, "PREVIEW_UNAVAILABLE", "The picture preview is not available on this server.")
    png, pages = raster.pdf_to_png(svc.sample_pdf(db, ctx, body.config, request.app.state.key))
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                             "X-Page-Count": str(pages)})


@router.post("/setup/test-print")
def setup_test_print(body: PreviewIn, request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    pdf = svc.sample_pdf(db, ctx, body.config, request.app.state.key)
    audit.record(db, ctx, "DONATION_RECEIPT_TEST", "donation_settings", None, None,
                 {"unsaved_settings": body.config is not None})
    db.commit()
    return _pdf(ctx, pdf, "receipt-test-print.pdf")


@router.get("/transactions/{txn_id}")
def transaction(txn_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(view_ctx)):
    return svc.transaction_out(db, ctx, svc.get_deposit(db, ctx, txn_id))


@router.put("/transactions/{txn_id}/lines")
def set_lines(txn_id: int, body: LinesIn, request: Request, db: Session = Depends(get_db),
              ctx: Ctx = Depends(print_ctx)):
    t = svc.get_deposit(db, ctx, txn_id)
    svc.set_lines(db, ctx, t, body.lines, request.app.state.settings, body.confirmations)
    svc.set_details(db, ctx, t, body.donors)
    db.commit()
    return svc.transaction_out(db, ctx, t)


class PreviewReceiptIn(In):
    donor_entity_id: int
    lines: list[svc.LineIn] = Field(default_factory=list, max_length=200)     # unsaved lines on screen (optional)
    donors: list[svc.DonorIn] = Field(default_factory=list, max_length=200)   # unsaved details on screen (optional)
    signer_id: int | None = None          # 2.3.0 polish: the signer chosen when printing


@router.post("/transactions/{txn_id}/receipts/preview")
def preview_receipt(txn_id: int, body: PreviewReceiptIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    """2.1.0: the receipt as it would print, from the unsaved screen, watermarked; nothing is saved or attached."""
    t = svc.get_deposit(db, ctx, txn_id)
    pdf, info = svc.preview_receipt(db, ctx, t, body.donor_entity_id, body.lines, body.donors, body.signer_id)
    resp = _pdf(ctx, pdf, "receipt-preview.pdf")
    resp.headers["X-Receipt-Kind"] = info["kind"]
    if info["replaces"]:
        resp.headers["X-Receipt-Replaces"] = info["replaces"]
    return resp


@router.post("/transactions/{txn_id}/receipts")
def print_receipt(txn_id: int, body: ReceiptIn, request: Request, db: Session = Depends(get_db),
                  ctx: Ctx = Depends(print_ctx)):
    t = svc.get_deposit(db, ctx, txn_id)
    pdf, r = svc.print_receipt(db, ctx, request.app.state.settings, t, body.donor_entity_id, body.confirmations,
                               km=request.app.state.key, signer_id=body.signer_id)
    resp = _pdf(ctx, pdf, f"receipt-{r.number}{'-duplicate' if r.kind == svc.DUPLICATE else ''}.pdf")
    resp.headers["X-Receipt-Number"] = r.number
    resp.headers["X-Receipt-Kind"] = r.kind
    return resp


# ------------------------------------------------------------------ 2.2.0 (#325): the Donations page
class CancelIn(In):
    reason: str = Field(max_length=500)


class DonationPrintIn(In):
    confirmations: list[str] = Field(default_factory=list, max_length=10)
    signer_id: int | None = None          # 2.3.0 polish: the signer chosen when printing


class CreateTransactionIn(In):
    transaction: TransactionCreateIn
    links: list[int | None] = Field(max_length=100)       # the donation line of each allocation (or none)
    date_received: dt.date | None = None                   # for lines with no date received yet


@router.get("")
def list_donations(show: str = "all", q: str | None = None, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(view_ctx)):
    if show not in ("all", "active", "awaiting", "value_missing", "cancelled"):
        show = "all"
    return svc.list_out(db, ctx, show, (q or "")[:120] or None)


@router.post("", status_code=201)
def create_donation(body: svc.DonationIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    d = svc.create(db, ctx, body)
    db.commit()
    return svc.donation_out(db, ctx, d)


class LinkIn(In):                             # 2.4.0 (#562)
    allocation_id: int
    confirmations: list[str] = Field(default_factory=list, max_length=10)


def _awaiting_line(db: Session, ctx, donation_id: int, line_id: int):
    d = svc.get_donation(db, ctx, donation_id)
    x = db.get(svc.DonationLine, line_id)
    if x is None or x.donation_id != d.id:
        raise not_found("Donation line")
    return d, x


@router.get("/{donation_id}/lines/{line_id}/link-candidates")
def link_candidates(donation_id: int, line_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    d, x = _awaiting_line(db, ctx, donation_id, line_id)
    return {"items": svc.link_candidates(db, ctx, d, x), "amount": svc.money(x.amount_cents or 0),
            "amount_cents": x.amount_cents or 0}


@router.post("/{donation_id}/lines/{line_id}/link")
def link_line(donation_id: int, line_id: int, body: LinkIn, request: Request, db: Session = Depends(get_db),
              ctx: Ctx = Depends(print_ctx)):
    d, x = _awaiting_line(db, ctx, donation_id, line_id)
    a = db.get(svc.TransactionAllocation, body.allocation_id)
    if a is None or a.transaction.workspace_id != ctx.workspace_id:
        raise not_found("Deposit line")
    svc.link_line(db, ctx, x, a.transaction, a, body.confirmations, settings=request.app.state.settings)
    db.commit()
    return svc.donation_out(db, ctx, d)


@router.get("/awaiting-lines")
def awaiting_lines(db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    return {"items": svc.awaiting_lines(db, ctx)}


# ------------------------------------------------------------------ 2.2.0 (#256): year-end statements, donor report
class DonationEmailIn(In):                    # 2.4.0 (#539): print (issue) and email in one step
    confirmations: list[str] = Field(default_factory=list, max_length=10)
    signer_id: int | None = None
    to: list[str] = Field(default_factory=list, max_length=10)
    cc: list[str] = Field(default_factory=list, max_length=10)
    subject: str = Field(default="", max_length=200)
    message: str = Field(default="", max_length=8000)
    donor_entity_id: int | None = None    # a deposit's receipts: which donor


class StatementPrintIn(In):
    confirmations: list[str] = Field(default_factory=list, max_length=10)
    signer_id: int | None = None          # 2.3.0 polish: the signer chosen when printing


class PrintAllIn(In):
    min_cents: int = Field(default=0, ge=0, le=10**13)
    confirmations: list[str] = Field(default_factory=list, max_length=10)
    signer_id: int | None = None          # 2.3.0 polish: the signer chosen when printing


@router.post("/setup/statement-preview")
def setup_statement_preview(body: PreviewIn, request: Request, db: Session = Depends(get_db),
                            ctx: Ctx = Depends(setup_ctx)):
    """The year-end statement's live preview with sample data (unsaved settings); not audited."""
    return _pdf(ctx, stm.sample_pdf(db, ctx, body.config, request.app.state.key), "statement-preview.pdf")


@router.post("/setup/statement-preview-image")
def setup_statement_preview_image(body: PreviewIn, request: Request, db: Session = Depends(get_db),
                                  ctx: Ctx = Depends(setup_ctx)):
    if not raster.available():
        raise AppError(501, "PREVIEW_UNAVAILABLE", "The picture preview is not available on this server.")
    png, pages = raster.pdf_to_png(stm.sample_pdf(db, ctx, body.config, request.app.state.key))
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                             "X-Page-Count": str(pages)})


@router.post("/setup/statement-test-print")
def setup_statement_test_print(body: PreviewIn, request: Request, db: Session = Depends(get_db),
                               ctx: Ctx = Depends(setup_ctx)):
    pdf = stm.sample_pdf(db, ctx, body.config, request.app.state.key)
    audit.record(db, ctx, "DONATION_STATEMENT_TEST", "donation_settings", None, None,
                 {"unsaved_settings": body.config is not None})
    db.commit()
    return _pdf(ctx, pdf, "statement-test-print.pdf")


@router.get("/statements")
def statements(year: int, min_cents: int = 0, q: str | None = None, db: Session = Depends(get_db),
               ctx: Ctx = Depends(view_ctx)):
    return stm.summary(db, ctx, year, max(0, min_cents), (q or "")[:120] or None)


@router.get("/statements/{year}/donors/{donor_id}")
def statement_detail(year: int, donor_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(view_ctx)):
    return stm.detail(db, ctx, year, donor_id)


@router.post("/statements/{year}/donors/{donor_id}/preview")
def statement_preview(year: int, donor_id: int, body: SignerChoiceIn | None = None, db: Session = Depends(get_db),
                      ctx: Ctx = Depends(print_ctx)):
    pdf, info = stm.preview(db, ctx, year, donor_id, body.signer_id if body else None)
    resp = _pdf(ctx, pdf, "statement-preview.pdf")
    resp.headers["X-Statement-Kind"] = info["kind"]
    return resp


@router.post("/statements/{year}/donors/{donor_id}")
def print_statement(year: int, donor_id: int, body: StatementPrintIn, request: Request,
                    db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    pdf, s = stm.print_one(db, ctx, request.app.state.settings, year, donor_id, body.confirmations,
                           km=request.app.state.key, signer_id=body.signer_id)
    resp = _pdf(ctx, pdf, f"statement-{s.number}{'-duplicate' if s.kind == svc.DUPLICATE else ''}.pdf")
    resp.headers["X-Statement-Number"] = s.number
    resp.headers["X-Statement-Kind"] = s.kind
    resp.headers["X-Statement-Id"] = str(s.id)
    return resp


@router.post("/statements/{year}/print-all")
def print_all_statements(year: int, body: PrintAllIn, request: Request, db: Session = Depends(get_db),
                         ctx: Ctx = Depends(print_ctx)):
    pdf, made = stm.print_all(db, ctx, request.app.state.settings, year, body.min_cents, body.confirmations,
                              km=request.app.state.key, signer_id=body.signer_id)
    resp = _pdf(ctx, pdf, f"statements-{year}.pdf")
    resp.headers["X-Statement-Count"] = str(len(made))
    return resp


# ------------------------------------------------------------------ 2.4.0 (#539): email a receipt or statement
@router.get("/email/defaults")
def email_defaults(kind: str = "RECEIPT", donor_entity_id: int | None = None, donation_id: int | None = None,
                   transaction_id: int | None = None, year: int | None = None, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(print_ctx)):
    """The Email form's To, subject and message (Donations Setup's, filled in)."""
    from ..models import Entity, RegisterTransaction
    from ..services import donation_email as de
    from ..services import donation_statements as _stm
    if kind == "STATEMENT":
        e = _stm._donor(db, ctx, donor_entity_id)
        amount = _stm._content(db, ctx.workspace_id, e, _stm._year(year or 0))["total"]
        return de.defaults(db, ctx, de.STATEMENT, e, amount, year)
    if donation_id is not None:
        d = svc.get_donation(db, ctx, donation_id)
    else:
        t = db.get(RegisterTransaction, transaction_id) if transaction_id else None
        if t is None or t.workspace_id != ctx.workspace_id:
            from ..errors import not_found
            raise not_found("Transaction")
        d = svc._deposit_donation(db, t, donor_entity_id)
    e = db.get(Entity, d.donor_entity_id)
    c = svc._compose(db, ctx, d)
    return de.defaults(db, ctx, de.RECEIPT, e, c["c"]["amount"])


@router.post("/{donation_id}/receipts/email")
def email_donation_receipt(donation_id: int, body: DonationEmailIn, request: Request, db: Session = Depends(get_db),
                           ctx: Ctx = Depends(print_ctx)):
    from ..services import donation_email as de
    return de.email_donation(db, ctx, request.app.state.key, request.app.state.settings,
                             svc.get_donation(db, ctx, donation_id), body)


@router.post("/transactions/{txn_id}/receipts/email")
def email_deposit_receipt(txn_id: int, body: DonationEmailIn, request: Request, db: Session = Depends(get_db),
                          ctx: Ctx = Depends(print_ctx)):
    from ..models import RegisterTransaction
    from ..services import donation_email as de
    t = db.get(RegisterTransaction, txn_id)
    if t is None or t.workspace_id != ctx.workspace_id:
        from ..errors import not_found
        raise not_found("Transaction")
    return de.email_deposit_receipt(db, ctx, request.app.state.key, request.app.state.settings, t,
                                    body.donor_entity_id, body)


@router.post("/statements/{year}/donors/{donor_id}/email")
def email_statement(year: int, donor_id: int, body: DonationEmailIn, request: Request, db: Session = Depends(get_db),
                    ctx: Ctx = Depends(print_ctx)):
    from ..services import donation_email as de
    return de.email_statement(db, ctx, request.app.state.key, request.app.state.settings, year, donor_id, body)


@router.get("/statements/printed/{statement_id}/document")
def statement_document(statement_id: int, request: Request, db: Session = Depends(get_db),
                       ctx: Ctx = Depends(view_ctx)):
    data, name = stm.document(db, ctx, request.app.state.settings, stm.get_statement(db, ctx, statement_id))
    return _pdf(ctx, data, name)


@router.post("/statements/printed/{statement_id}/envelope")
def statement_envelope(statement_id: int, body: EnvelopeIn, request: Request, db: Session = Depends(get_db),
                       ctx: Ctx = Depends(print_ctx)):
    s = stm.get_statement(db, ctx, statement_id)
    pdf = stm.print_envelope(db, ctx, request.app.state.settings, s, body.document_id,
                             return_address=body.return_address, page=body.page, guide=body.guide, test=False,
                             confirmations=body.confirmations)
    return _pdf(ctx, pdf, f"envelope-{s.number}.pdf")


@router.post("/statements/printed/{statement_id}/envelope-test")
def statement_envelope_test(statement_id: int, body: EnvelopeIn, request: Request, db: Session = Depends(get_db),
                            ctx: Ctx = Depends(print_ctx)):
    s = stm.get_statement(db, ctx, statement_id)
    pdf = stm.print_envelope(db, ctx, request.app.state.settings, s, body.document_id,
                             return_address=body.return_address, page=body.page, guide=body.guide, test=True,
                             confirmations=[])
    return _pdf(ctx, pdf, "envelope-test.pdf")


@router.get("/report")
def donor_report(start_year: int, end_year: int, donor_id: int | None = None, min_cents: int = 0,
                 format: str = "json", detail: bool = False, db: Session = Depends(get_db),
                 ctx: Ctx = Depends(view_ctx)):
    """The donor giving report (all financial roles and Auditors; never Administrators)."""
    if format not in ("json", "pdf", "csv"):
        format = "json"
    rep = stm.report(db, ctx, start_year, end_year, donor_id, max(0, min_cents))
    if format == "json":
        return rep
    name = f"donor-report-{rep['years'][0]}-{rep['years'][-1]}"
    audit.record(db, ctx, "REPORT_GENERATED", "report", "donor_giving", None,
                 {"report": "DONOR_GIVING", "format": format.upper(), "years": rep["years"], "donor_id": donor_id,
                  "min_cents": rep["min_cents"], "detail": detail, "donors": len(rep["rows"])})
    db.commit()
    if format == "csv":
        return Response(stm.report_csv(rep, detail), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"',
                                 "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
    return _pdf(ctx, stm.report_pdf(db, ctx, rep, detail), f"{name}.pdf")


@router.get("/fundraisers/{fundraiser_id}/unreceipted")
def fundraiser_unreceipted(fundraiser_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(view_ctx)):
    """2.2.0 (#256): a fundraiser's donation-bucket deposits without a receipt yet (Print receipts opens each)."""
    return svc.fundraiser_unreceipted(db, ctx, fundraiser_id)


# 2.2.0 (#325): receipt envelopes - templates tagged for Donations in the shared envelope library
@router.get("/envelopes")
def envelopes(db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    return svc.envelope_choices(db, ctx)


@router.put("/my-printer/envelope")
def save_envelope_printer(body: EnvelopePrinterIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    """My envelope printer settings: they belong to the template, so they carry over to Payments when it shares it."""
    from ..services.checkprint import service as cp
    d = svc._donation_envelope(db, ctx, body.document_id)
    out = cp.save_envelope_printer(db, ctx, d, body.page, body.guide, body.dx, body.dy)
    db.commit()
    return out


@router.post("/create-transaction", status_code=201)
def create_transaction(body: CreateTransactionIn, request: Request, db: Session = Depends(get_db),
                       ctx: Ctx = Depends(print_ctx)):
    """Create transaction from donations: the deposit, linked to the chosen donation lines, receipts attached."""
    if not ctx.has("transaction.manage"):
        raise AppError(403, "FORBIDDEN", "Recording a deposit needs the Register User role.")
    replay = idempotency.claim(db, ctx, body.transaction.request_key, "transaction")
    if replay:
        return reg.out(db, reg.get(db, ctx, replay[0]))
    t = svc.create_transaction(db, ctx, request.app.state.settings, body.transaction, body.links, body.date_received)
    idempotency.complete(db, ctx, body.transaction.request_key, [t.id])
    db.commit()
    return reg.out(db, t)


@router.get("/{donation_id}")
def get_donation(donation_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(view_ctx)):
    return svc.donation_out(db, ctx, svc.get_donation(db, ctx, donation_id))


@router.put("/{donation_id}")
def update_donation(donation_id: int, body: svc.DonationIn, db: Session = Depends(get_db),
                    ctx: Ctx = Depends(print_ctx)):
    d = svc.update(db, ctx, svc.get_donation(db, ctx, donation_id), body)
    db.commit()
    return svc.donation_out(db, ctx, d)


@router.post("/{donation_id}/cancel")
def cancel_donation(donation_id: int, body: CancelIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    d = svc.cancel(db, ctx, svc.get_donation(db, ctx, donation_id), body.reason)
    db.commit()
    return svc.donation_out(db, ctx, d)


@router.post("/{donation_id}/receipts/preview")
def preview_donation(donation_id: int, body: SignerChoiceIn | None = None, db: Session = Depends(get_db),
                     ctx: Ctx = Depends(print_ctx)):
    pdf, info = svc.preview_donation(db, ctx, svc.get_donation(db, ctx, donation_id), body.signer_id if body else None)
    resp = _pdf(ctx, pdf, "receipt-preview.pdf")
    resp.headers["X-Receipt-Kind"] = info["kind"]
    if info["replaces"]:
        resp.headers["X-Receipt-Replaces"] = info["replaces"]
    return resp


@router.post("/{donation_id}/receipts")
def print_donation(donation_id: int, body: DonationPrintIn, request: Request, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(print_ctx)):
    d = svc.get_donation(db, ctx, donation_id)
    pdf, r = svc.print_donation(db, ctx, request.app.state.settings, d, body.confirmations, km=request.app.state.key,
                                signer_id=body.signer_id)
    resp = _pdf(ctx, pdf, f"receipt-{r.number}{'-duplicate' if r.kind == svc.DUPLICATE else ''}.pdf")
    resp.headers["X-Receipt-Number"] = r.number
    resp.headers["X-Receipt-Kind"] = r.kind
    return resp


@router.get("/{donation_id}/documents/{attachment_id}")
def donation_document(donation_id: int, attachment_id: int, request: Request, db: Session = Depends(get_db),
                      ctx: Ctx = Depends(view_ctx)):
    """A printed receipt kept with a donation not linked to a deposit (view only; audited like attachments)."""
    from ..models import Attachment
    from ..services import attachments as att_svc
    d = svc.get_donation(db, ctx, donation_id)
    a = db.get(Attachment, attachment_id)
    if a is None or a.donation_id != d.id or not a.active:
        raise AppError(404, "NOT_FOUND", "Document not found.")
    data = att_svc.path_for(request.app.state.settings, a).read_bytes()
    audit.record(db, ctx, "ATTACHMENT_VIEWED", "attachment", a.id, None, {"donation_id": d.id})
    db.commit()
    return _pdf(ctx, data, a.original_filename)


@router.post("/{donation_id}/envelope")
def print_envelope(donation_id: int, body: EnvelopeIn, request: Request, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(print_ctx)):
    d = svc.get_donation(db, ctx, donation_id)
    pdf = svc.print_envelope(db, ctx, request.app.state.settings, d, body.document_id,
                             return_address=body.return_address, page=body.page, guide=body.guide, test=False,
                             confirmations=body.confirmations)
    return _pdf(ctx, pdf, f"envelope-donation-{d.id}.pdf")


@router.post("/{donation_id}/envelope-test")
def envelope_test(donation_id: int, body: EnvelopeIn, request: Request, db: Session = Depends(get_db),
                  ctx: Ctx = Depends(print_ctx)):
    """Test on plain paper: the real addresses, marked TEST; not kept."""
    d = svc.get_donation(db, ctx, donation_id)
    pdf = svc.print_envelope(db, ctx, request.app.state.settings, d, body.document_id,
                             return_address=body.return_address, page=body.page, guide=body.guide, test=True,
                             confirmations=[])
    return _pdf(ctx, pdf, "envelope-test.pdf")
