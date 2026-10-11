"""2.0.0 (#156-#162): Payments module API.

Setup (Administrators, checks.setup): check styles, signers, test prints with dummy data, calibration pages.
Printing (Register Users, checks.print): print checks from register transactions, reprint, spoil, alignment tests,
own printer settings. Every endpoint needs the module switched on (404 MODULE_DISABLED otherwise); Budget Managers,
Budget Users and Auditors are refused by permission (BR-078, BR-091)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import audit
from ..deps import Ctx, auth_ctx, get_db, require
from ..errors import AppError, forbidden, validation
from ..models import BankAccount
from ..services.checkprint import config as cfgmod
from ..services.checkprint import documents, fonts, patterns, presets, render
from ..services.checkprint import service as svc
from ..services.common import get_scoped

router = APIRouter(prefix="/api/checks", tags=["checks"])

PDF_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
               "X-Frame-Options": "SAMEORIGIN", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'"}


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _pdf(data: bytes, name: str) -> Response:
    return Response(data, media_type="application/pdf",
                    headers={**PDF_HEADERS, "Content-Disposition": f'inline; filename="{name}"'})


def setup_ctx(db: Session = Depends(get_db), ctx: Ctx = Depends(require("checks.setup"))) -> Ctx:
    svc.require_module(db, ctx)
    return ctx


def print_ctx(db: Session = Depends(get_db), ctx: Ctx = Depends(require("checks.print"))) -> Ctx:
    svc.require_module(db, ctx)
    return ctx


def any_ctx(db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)) -> Ctx:
    if not (ctx.has("checks.setup") or ctx.has("checks.print")):
        raise forbidden()
    svc.require_module(db, ctx)
    return ctx


# ------------------------------------------------------------------ shared
@router.get("/fonts/{key}/{weight}")
def font_file(key: str, weight: Literal["regular", "bold"], ctx: Ctx = Depends(any_ctx)):
    """The built-in font files, so the setup preview draws with exactly the fonts that print."""
    if key not in fonts.FONTS:
        raise AppError(404, "NOT_FOUND", "Not found.")
    return FileResponse(fonts.file_for(key, weight == "bold"), media_type="font/ttf",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.get("/scale-check")
def scale_check(db: Session = Depends(get_db), ctx: Ctx = Depends(any_ctx)):
    return _pdf(render.scale_pdf(), "scale-check.pdf")


# ------------------------------------------------------------------ setup (Administrators)
class StyleCreateIn(In):
    preset_key: str = Field(max_length=40)
    name: str | None = Field(default=None, max_length=80)


class StyleCopyIn(In):
    name: str = Field(max_length=80)


class StyleUpdateIn(In):
    name: str = Field(max_length=80)
    config: dict


class ActiveIn(In):
    active: bool


class TestPrintIn(In):
    feed_key: str = Field(max_length=20)
    sample: Literal["NORMAL", "LONG"] = "NORMAL"
    signer_id: int | None = None
    config: dict | None = None        # unsaved settings from the setup screen; validated like a save


class SampleIn(In):
    config: dict
    sample: Literal["NORMAL", "LONG"] = "NORMAL"


@router.get("/setup")
def setup(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    return {"styles": [svc.style_out(s) for s in svc.list_styles(db, ctx)], "presets": presets.options(),
            "signature2_default": presets.SIGNATURE2_DEFAULT,
            "fonts": fonts.options(), "font_sizes": {"min": fonts.MIN_SIZE, "max": fonts.MAX_SIZE},
            "variables": patterns.variable_options(patterns.CHECK),
            "signers": [svc.signer_out(s) for s in svc.list_signers(db, ctx)],
            "documents": [svc.doc_out(d) for d in svc.list_documents(db, ctx)],
            "letter_variables": patterns.variable_options(patterns.LETTER),
            "stub_variables": patterns.variable_options(patterns.STUB),
            "envelope_variables": patterns.variable_options(patterns.ENVELOPE),
            "letter_columns": [{"key": k, "heading": v} for k, v in documents.COLUMN_KEYS.items()],
            "limits": {"clear_zone": cfgmod.CLEAR_ZONE, "feed_offset_max": cfgmod.FEED_OFFSET_MAX,
                       "personal_max": cfgmod.PERSONAL_MAX},
            "date_formats": list(cfgmod.DATE_FORMATS)}


@router.post("/styles", status_code=201)
def create_style(body: StyleCreateIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    s = svc.create_style(db, ctx, body.preset_key, body.name)
    db.commit()
    return svc.style_out(s)


@router.post("/styles/{style_id}/copy", status_code=201)
def copy_style(style_id: int, body: StyleCopyIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    s = svc.copy_style(db, ctx, svc.get_style(db, ctx, style_id), body.name)
    db.commit()
    return svc.style_out(s)


@router.put("/styles/{style_id}")
def update_style(style_id: int, body: StyleUpdateIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    s = svc.update_style(db, ctx, svc.get_style(db, ctx, style_id), body.name, body.config)
    db.commit()
    return svc.style_out(s)


@router.post("/styles/{style_id}/active")
def style_active(style_id: int, body: ActiveIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    s = svc.set_style_active(db, ctx, svc.get_style(db, ctx, style_id), body.active)
    db.commit()
    return svc.style_out(s)


def _test_cfg(db, ctx, style_id: int, config: dict | None) -> tuple:
    s = svc.get_style(db, ctx, style_id)
    cfg = svc.parse_config(config) if config is not None else svc.style_config(s)
    return s, cfg


@router.post("/sample-layout")
def sample_layout(body: SampleIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    """How the dummy data fits with unsaved settings (the setup screen shows fit warnings live)."""
    return svc.sample_out(svc.parse_config(body.config), body.sample)


@router.post("/styles/{style_id}/test-print")
def test_print(style_id: int, body: TestPrintIn, request: Request, db: Session = Depends(get_db),
               ctx: Ctx = Depends(setup_ctx)):
    s, cfg = _test_cfg(db, ctx, style_id, body.config)
    feed = cfg.feed(body.feed_key)
    if feed is None:
        raise validation("Unknown feed mode.", "feed_key")
    sig = None
    if body.signer_id is not None:
        signer = svc.get_signer(db, ctx, body.signer_id)
        sig = svc.signature_png(request.app.state.key, signer)
        if sig is None:
            raise validation("That signer has no signature image.", "signer_id")
    pdf = render.test_pdf(cfg, render.placement_for(cfg, feed), svc.sample_layout(cfg, body.sample), sig,
                          svc.sample_stub(cfg))
    audit.record(db, ctx, "CHECK_TEST_PRINT", "check_style", s.id, None,
                 {"feed_key": feed.key, "sample": body.sample, "signer_id": body.signer_id,
                  "unsaved_settings": body.config is not None})
    db.commit()
    return _pdf(pdf, "check-test-print.pdf")


class CalibrationIn(In):
    feed_key: str = Field(max_length=20)
    config: dict | None = None


@router.post("/styles/{style_id}/calibration")
def calibration(style_id: int, body: CalibrationIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    s, cfg = _test_cfg(db, ctx, style_id, body.config)
    feed = cfg.feed(body.feed_key)
    if feed is None:
        raise validation("Unknown feed mode.", "feed_key")
    return _pdf(render.calibration_pdf(cfg, render.placement_for(cfg, feed), svc.sample_stub(cfg)),
                "check-calibration.pdf")


# ---- signers (#159)
class SignerIn(In):
    name: str = Field(max_length=120)
    title: str | None = Field(default=None, max_length=80)


async def _read_png(file: UploadFile) -> bytes:
    data = await file.read(svc.MAX_SIGNATURE_BYTES + 1)
    if len(data) > svc.MAX_SIGNATURE_BYTES:
        raise AppError(413, "FILE_TOO_LARGE", "A signature image may not exceed 1 MB.")
    return data


@router.post("/signers", status_code=201)
async def create_signer(request: Request, name: str = Form(..., max_length=120),
                        title: str | None = Form(default=None, max_length=80), file: UploadFile | None = File(None),
                        db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    data = await _read_png(file) if file is not None else None
    s = svc.create_signer(db, ctx, request.app.state.key, name, title, data)
    db.commit()
    return svc.signer_out(s)


@router.put("/signers/{signer_id}")
def update_signer(signer_id: int, body: SignerIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    s = svc.update_signer(db, ctx, svc.get_signer(db, ctx, signer_id), body.name, body.title)
    db.commit()
    return svc.signer_out(s)


@router.post("/signers/{signer_id}/image")
async def replace_image(signer_id: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                        ctx: Ctx = Depends(setup_ctx)):
    s = svc.get_signer(db, ctx, signer_id)
    data = await _read_png(file)
    svc.replace_signature(db, ctx, request.app.state.key, s, data)
    db.commit()
    return svc.signer_out(s)


@router.post("/signers/{signer_id}/image/remove")
def remove_image(signer_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    s = svc.remove_signature(db, ctx, svc.get_signer(db, ctx, signer_id))
    db.commit()
    return svc.signer_out(s)


@router.post("/signers/{signer_id}/active")
def signer_active(signer_id: int, body: ActiveIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    s = svc.set_signer_active(db, ctx, svc.get_signer(db, ctx, signer_id), body.active)
    db.commit()
    return svc.signer_out(s)


@router.get("/signers/{signer_id}/preview")
def signer_preview(signer_id: int, request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    """A low-resolution image marked SAMPLE. The signature image itself can never be downloaded."""
    png = svc.signature_preview(request.app.state.key, svc.get_signer(db, ctx, signer_id))
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, no-store",
                                                          "X-Content-Type-Options": "nosniff"})


# ------------------------------------------------------------------ printing (Register Users)
class AccountIn(In):
    check_style_id: int
    sheet_remaining: int | None = Field(default=None, ge=1, le=3)


class JobIn(In):
    check_style_id: int
    feed_key: str = Field(max_length=20)
    memo_pattern: str | None = Field(default=None, max_length=patterns.MAX_PATTERN)
    payee_text: str | None = Field(default=None, max_length=200)
    memo_text: str | None = Field(default=None, max_length=200)
    signer_id: int | None = None
    signer2_id: int | None = None            # #167: the second signature line of a two-line style
    no_signature: bool = False
    page: Literal["LETTER", "CHECK"] | None = None
    guide: Literal["CENTER", "LEFT", "RIGHT"] | None = None


class PrintIn(JobIn):
    check_number: str | None = Field(default=None, max_length=20)
    confirm_check_number: str = Field(max_length=20)
    reprint_reason: str | None = Field(default=None, max_length=500)
    confirmations: list[str] = Field(default_factory=list, max_length=10)


class SpoilIn(In):
    reason: str = Field(max_length=400)
    new_check_number: str = Field(max_length=20)


class PrinterIn(In):
    check_style_id: int
    feed_key: str = Field(max_length=20)
    page: Literal["LETTER", "CHECK"] | None = None
    guide: Literal["CENTER", "LEFT", "RIGHT"] | None = None
    dx: float = Field(default=0, ge=-cfgmod.PERSONAL_MAX, le=cfgmod.PERSONAL_MAX)
    dy: float = Field(default=0, ge=-cfgmod.PERSONAL_MAX, le=cfgmod.PERSONAL_MAX)


class PrinterResetIn(In):
    check_style_id: int
    feed_key: str = Field(max_length=20)


def _job(db, ctx, txn_id: int, body: JobIn):
    t = svc.get_printable(db, ctx, txn_id)
    style = svc.get_style(db, ctx, body.check_style_id)
    return svc.prepare(db, ctx, t, style, body.feed_key, memo_pattern=body.memo_pattern, payee_text=body.payee_text,
                       memo_text=body.memo_text, signer_id=body.signer_id, no_signature=body.no_signature,
                       page=body.page, guide=body.guide, signer2_id=body.signer2_id)


@router.get("/transactions/{txn_id}/options")
def print_options(txn_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    t = svc.get_printable(db, ctx, txn_id)
    acct = db.get(BankAccount, t.bank_account_id)
    styles = svc.list_styles(db, ctx, include_inactive=False)
    row = svc.account_row(db, ctx, acct.id)
    chosen = next((s for s in styles if row and s.id == row.check_style_id), None)
    out = {"transaction": {"id": t.id, "payee": t.parent_entity.display_name if t.parent_entity else None,
                           "amount": f"{t.total_cents // 100}.{t.total_cents % 100:02d}",
                           "transaction_date": t.transaction_date.isoformat(), "check_number": t.check_number,
                           "cleared": t.clear_date is not None, "bank_account_id": acct.id,
                           "bank_account_name": acct.account_name},
           "styles": [svc.style_out(s, full=False) for s in styles],
           "check_style_id": chosen.id if chosen else None,
           "signers": [svc.signer_out(s) for s in svc.list_signers(db, ctx) if s.active and s.image_ciphertext],
           "variables": patterns.variable_options(patterns.CHECK),
           "next_check_number": svc.next_check_number(db, ctx, acct.id),
           "print_status": svc.print_status(db, t), "last_printed_number": svc.last_printed_number(db, t),
           "is_reprint": svc.is_reprint(db, t),
           # #165/#166: letters and envelopes can be printed on their own when the check is written by hand
           "has_documents": bool(svc.list_documents(db, ctx, None, False))}
    if chosen:
        cfg = svc.style_config(chosen)
        left = svc.remaining(row, cfg)
        out.update({"style_config": cfg.model_dump(), "fonts": fonts.options(),
                    "sheet_remaining": left, "checks_per_sheet": len(cfg.stock.check_tops),
                    "suggested_feed": svc.suggested_feed(cfg, left).key, "memo_default": cfg.memo_default,
                    "default_signer_id": cfg.default_signer_id,
                    "signature_lines": cfg.stock.signature_lines, "default_signer2_id": cfg.default_signer2_id,
                    "second_line_limit": None if cfg.second_line_limit_cents is None
                    else f"{cfg.second_line_limit_cents // 100}.{cfg.second_line_limit_cents % 100:02d}",
                    "signature_limit": None if cfg.signature_limit_cents is None
                    else f"{cfg.signature_limit_cents // 100}.{cfg.signature_limit_cents % 100:02d}",
                    "printer": [svc.printer_out(svc.printer_setting(db, ctx, chosen.id, m.key), m)
                                for m in cfg.feed_modes]})
    return out


@router.put("/accounts/{account_id}")
def set_account(account_id: int, body: AccountIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    acct = get_scoped(db, BankAccount, account_id, ctx, "Bank Account")
    style = svc.get_style(db, ctx, body.check_style_id)
    row = svc.set_account_style(db, ctx, acct, style, body.sheet_remaining)
    db.commit()
    return {"bank_account_id": acct.id, "check_style_id": row.check_style_id,
            "sheet_remaining": svc.remaining(row, svc.style_config(style))}


@router.post("/transactions/{txn_id}/prepare")
def prepare(txn_id: int, body: JobIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    return svc.job_out(db, _job(db, ctx, txn_id, body))


@router.post("/transactions/{txn_id}/alignment-test")
def alignment_test(txn_id: int, body: JobIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    """Test print of the actual check on plain paper. Never the signature, never stored, no check used."""
    job = _job(db, ctx, txn_id, body)
    pdf = render.alignment_pdf(job.cfg, job.placement, job.layout, svc.stub_data(job))
    audit.record(db, ctx, "CHECK_ALIGNMENT_TEST", "register_transaction", job.t.id, None,
                 {"check_style_id": job.style.id, "feed_key": job.feed.key, "page": job.placement.page,
                  "guide": job.placement.guide})
    db.commit()
    return _pdf(pdf, "alignment-test.pdf")


@router.post("/transactions/{txn_id}/print")
def print_check(txn_id: int, body: PrintIn, request: Request, db: Session = Depends(get_db),
                ctx: Ctx = Depends(print_ctx)):
    job = _job(db, ctx, txn_id, body)
    pdf = svc.print_check(db, ctx, request.app.state.settings, request.app.state.key, job,
                          check_number=body.check_number, confirm_check_number=body.confirm_check_number,
                          reprint_reason=body.reprint_reason, confirmations=body.confirmations)
    return _pdf(pdf, f"check-{job.t.check_number}.pdf")


@router.post("/transactions/{txn_id}/spoil")
def spoil(txn_id: int, body: SpoilIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    t = svc.get_printable(db, ctx, txn_id)
    v = svc.spoil(db, ctx, t, body.reason, body.new_check_number)
    db.commit()
    return {"transaction_id": t.id, "check_number": t.check_number, "void_record_id": v.id}


@router.get("/my-printer")
def my_printer(check_style_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    style = svc.get_style(db, ctx, check_style_id)
    cfg = svc.style_config(style)
    return [svc.printer_out(svc.printer_setting(db, ctx, style.id, m.key), m) | {"label": m.label, "kind": m.kind}
            for m in cfg.feed_modes]


@router.put("/my-printer")
def save_my_printer(body: PrinterIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    style = svc.get_style(db, ctx, body.check_style_id)
    p = svc.save_printer_setting(db, ctx, style, body.feed_key, body.page, body.guide, body.dx, body.dy)
    db.commit()
    return svc.printer_out(p, svc.style_config(style).feed(body.feed_key))


@router.post("/my-printer/reset")
def reset_my_printer(body: PrinterResetIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    style = svc.get_style(db, ctx, body.check_style_id)
    feed = svc.style_config(style).feed(body.feed_key)
    if feed is None:
        raise validation("Unknown feed mode.", "feed_key")
    svc.reset_printer_setting(db, ctx, style, body.feed_key)
    db.commit()
    return svc.printer_out(None, feed)



# ------------------------------------------------------------------ payments (#164)
class LastAccountIn(In):
    bank_account_id: int


class AmountPreviewIn(In):
    bank_account_id: int | None = None
    amount: str = Field(max_length=20)


@router.get("/payments/options")
def payment_options(db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    return {"last_bank_account_id": svc.last_payment_account(db, ctx),
            "styles_available": bool(svc.list_styles(db, ctx, include_inactive=False))}


@router.put("/payments/last-account")
def set_last_account(body: LastAccountIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    acct = get_scoped(db, BankAccount, body.bank_account_id, ctx, "Bank Account")
    svc.set_last_payment_account(db, ctx, acct)
    db.commit()
    return {"last_bank_account_id": svc.last_payment_account(db, ctx)}


@router.post("/payments/amount-preview")
def amount_preview(body: AmountPreviewIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    from ..money import parse_amount
    acct = get_scoped(db, BankAccount, body.bank_account_id, ctx, "Bank Account") if body.bank_account_id else None
    try:
        cents = parse_amount(body.amount, allow_zero=True)
    except ValueError:
        return {"number": None, "words": None}
    return svc.amount_preview(db, ctx, acct, cents)


@router.get("/payments/recent")
def recent(bank_account_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    acct = get_scoped(db, BankAccount, bank_account_id, ctx, "Bank Account")
    return svc.recent_checks(db, ctx, acct)


# ------------------------------------------------------------------ cover letters and envelopes (#165, #166)
class DocCreateIn(In):
    kind: Literal["LETTER", "ENVELOPE"]
    name: str | None = Field(default=None, max_length=80)


class DocUpdateIn(In):
    name: str = Field(max_length=80)
    config: dict


class DocFlagsIn(In):
    active: bool | None = None
    is_default: bool | None = None


class DocTestIn(In):
    config: dict | None = None


class LetterIn(In):
    document_id: int
    signer_id: int | None = None
    confirmations: list[str] = Field(default_factory=list, max_length=10)


class EnvelopeIn(In):
    document_id: int
    return_address: bool | None = None
    page: Literal["LETTER", "ENVELOPE"] | None = None
    guide: Literal["CENTER", "LEFT", "RIGHT"] | None = None
    confirmations: list[str] = Field(default_factory=list, max_length=10)


class HandwrittenIn(In):
    check_number: str = Field(max_length=20)
    confirm_check_number: str = Field(max_length=20)


class EnvelopePrinterIn(In):
    document_id: int
    page: Literal["LETTER", "ENVELOPE"] | None = None
    guide: Literal["CENTER", "LEFT", "RIGHT"] | None = None
    dx: float = Field(default=0, ge=-cfgmod.PERSONAL_MAX, le=cfgmod.PERSONAL_MAX)
    dy: float = Field(default=0, ge=-cfgmod.PERSONAL_MAX, le=cfgmod.PERSONAL_MAX)


@router.post("/documents", status_code=201)
def create_document(body: DocCreateIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    d = svc.create_document(db, ctx, body.kind, body.name)
    db.commit()
    return svc.doc_out(d)


@router.put("/documents/{doc_id}")
def update_document(doc_id: int, body: DocUpdateIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    d = svc.update_document(db, ctx, svc.get_document(db, ctx, doc_id), body.name, body.config)
    db.commit()
    return svc.doc_out(d)


@router.post("/documents/{doc_id}/flags")
def document_flags(doc_id: int, body: DocFlagsIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    d = svc.set_document_flags(db, ctx, svc.get_document(db, ctx, doc_id), body.active, body.is_default)
    db.commit()
    return svc.doc_out(d)


@router.post("/documents/{doc_id}/test-print")
def document_test(doc_id: int, body: DocTestIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    d = svc.get_document(db, ctx, doc_id)
    cfg = svc._doc_config_or_422(d.kind, body.config) if body.config is not None else svc.doc_config(d)
    pdf = svc.sample_letter_pdf(cfg) if d.kind == "LETTER" else svc.sample_envelope_pdf(cfg)
    audit.record(db, ctx, "CHECK_DOCUMENT_TEST_PRINT", "check_document", d.id, None,
                 {"unsaved_settings": body.config is not None})
    db.commit()
    return _pdf(pdf, f"{d.kind.lower()}-test-print.pdf")


@router.get("/transactions/{txn_id}/documents")
def transaction_documents(txn_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    """Letter and envelope templates for the print screen, with the user's envelope printer settings."""
    svc.get_printable(db, ctx, txn_id)
    letters = [svc.doc_out(d, full=False) for d in svc.list_documents(db, ctx, "LETTER", False)]
    envs = []
    for d in svc.list_documents(db, ctx, "ENVELOPE", False):
        envs.append({**svc.doc_out(d, full=False), "printer": svc.envelope_options(db, ctx, d)})
    return {"letters": letters, "envelopes": envs}


@router.post("/transactions/{txn_id}/letter")
def print_letter(txn_id: int, body: LetterIn, request: Request, db: Session = Depends(get_db),
                 ctx: Ctx = Depends(print_ctx)):
    t = svc.get_printable(db, ctx, txn_id)
    d = svc.get_document(db, ctx, body.document_id, "LETTER")
    pdf = svc.print_letter(db, ctx, request.app.state.settings, t, d, body.signer_id, body.confirmations)
    return _pdf(pdf, f"letter-{t.check_number or t.id}.pdf")


@router.post("/transactions/{txn_id}/envelope")
def print_envelope(txn_id: int, body: EnvelopeIn, request: Request, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(print_ctx)):
    t = svc.get_printable(db, ctx, txn_id)
    d = svc.get_document(db, ctx, body.document_id, "ENVELOPE")
    pdf = svc.print_envelope(db, ctx, request.app.state.settings, t, d, return_address=body.return_address,
                             page=body.page, guide=body.guide, test=False, confirmations=body.confirmations)
    return _pdf(pdf, f"envelope-{t.check_number or t.id}.pdf")


@router.post("/transactions/{txn_id}/envelope-test")
def envelope_test(txn_id: int, body: EnvelopeIn, request: Request, db: Session = Depends(get_db),
                  ctx: Ctx = Depends(print_ctx)):
    t = svc.get_printable(db, ctx, txn_id)
    d = svc.get_document(db, ctx, body.document_id, "ENVELOPE")
    pdf = svc.print_envelope(db, ctx, request.app.state.settings, t, d, return_address=body.return_address,
                             page=body.page, guide=body.guide, test=True, confirmations=[])
    return _pdf(pdf, "envelope-test.pdf")


@router.post("/transactions/{txn_id}/handwritten")
def handwritten(txn_id: int, body: HandwrittenIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    """The check is written by hand: record its number (confirmed twice) without printing a check."""
    from ..services import checks as checknum
    if checknum.check_key(body.check_number) != checknum.check_key(body.confirm_check_number):
        raise AppError(409, "CHECK_NUMBER_MISMATCH", "The two check numbers don't match.")
    t = svc.get_printable(db, ctx, txn_id)
    svc.handwritten_check(db, ctx, t, body.check_number)
    db.commit()
    return {"transaction_id": t.id, "check_number": t.check_number}


@router.put("/my-printer/envelope")
def save_envelope_printer(body: EnvelopePrinterIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    d = svc.get_document(db, ctx, body.document_id, "ENVELOPE")
    out = svc.save_envelope_printer(db, ctx, d, body.page, body.guide, body.dx, body.dy)
    db.commit()
    return out
