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
from ..errors import AppError, forbidden, not_found, validation
from ..models import BankAccount
from ..services.checkprint import config as cfgmod
from ..services.checkprint import documents, fonts, patterns, presets, raster, render
from ..services.checkprint import service as svc
from ..services import pdf_preview
from ..services.common import get_scoped

router = APIRouter(prefix="/api/checks", tags=["checks"])

PDF_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
               "X-Frame-Options": "SAMEORIGIN", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'"}


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _pdf(ctx: Ctx, data: bytes, name: str) -> Response:
    headers = {**PDF_HEADERS, "Content-Disposition": f'inline; filename="{name}"'}
    # build 13 (#230): Safari shows an inline PDF blank - the screen can ask for a picture of this very PDF
    token = pdf_preview.keep(ctx.user.id, data)
    if token:
        headers["X-Preview-Token"] = token
    return Response(data, media_type="application/pdf", headers=headers)


def setup_ctx(db: Session = Depends(get_db), ctx: Ctx = Depends(require("checks.setup"))) -> Ctx:
    svc.require_module(db, ctx)
    return ctx


def print_ctx(db: Session = Depends(get_db), ctx: Ctx = Depends(require("checks.print"))) -> Ctx:
    svc.require_module(db, ctx)
    return ctx


def any_ctx(db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)) -> Ctx:
    from ..services import envelopes as env_lib
    payments = ctx.has("checks.setup") or ctx.has("checks.print")
    donations = ctx.has("donation.setup") or ctx.has("donation.print")   # 2.2.0 (#325): receipt envelopes
    if not (payments or donations):
        raise forbidden()
    on = env_lib.enabled(db, ctx.workspace_id)
    if not ((payments and env_lib.PAYMENTS in on) or (donations and env_lib.DONATIONS in on)):
        svc.require_module(db, ctx)
    return ctx


def doc_ctx(db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)) -> Ctx:
    """2.2.0 (#325): letter and envelope templates. Envelopes are one library shared by Payments and Donations, so an
    Administrator reaches them while either module is on; cover letters stay Payments' own (_kind_ok)."""
    from ..services import envelopes as env_lib
    if not (ctx.has("checks.setup") or ctx.has("donation.setup")):
        raise forbidden()
    env_lib.require_any_module(db, ctx)
    on = env_lib.enabled(db, ctx.workspace_id)
    if not ((ctx.has("checks.setup") and env_lib.PAYMENTS in on) or
            (ctx.has("donation.setup") and env_lib.DONATIONS in on)):
        raise forbidden()
    return ctx


def _kind_ok(db: Session, ctx: Ctx, kind: str, feature: str | None = None) -> None:
    from ..services import envelopes as env_lib
    if kind == "LETTER":
        if not ctx.has("checks.setup"):
            raise forbidden()
        svc.require_module(db, ctx)
    elif feature is not None:
        env_lib.require_feature(db, ctx, feature)


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
    return _pdf(ctx, render.scale_pdf(), "scale-check.pdf")


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
            "voucher_layouts": presets.voucher_layouts(),   # 2.1.0 (#246)
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


@router.post("/sample-stubs")
def sample_stubs(body: SampleIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    """#186: the voucher stubs with sample data, as text runs and lines in page inches, for the setup preview.
    Null when the style has no stubs."""
    cfg = svc.parse_config(body.config)
    return {"stubs": render.stub_drawing(cfg, svc.sample_stub(cfg))}


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
    return _pdf(ctx, pdf, "check-test-print.pdf")


class CalibrationIn(In):
    feed_key: str = Field(max_length=20)
    config: dict | None = None


@router.post("/styles/{style_id}/calibration")
def calibration(style_id: int, body: CalibrationIn, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    s, cfg = _test_cfg(db, ctx, style_id, body.config)
    feed = cfg.feed(body.feed_key)
    if feed is None:
        raise validation("Unknown feed mode.", "feed_key")
    return _pdf(ctx, render.calibration_pdf(cfg, render.placement_for(cfg, feed), svc.sample_stub(cfg)),
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


def _payments_envelope(db, ctx, doc_id: int):
    """2.2.0 (#325): Payments prints only the envelopes tagged for Payments."""
    from ..services import envelopes as env_lib
    d = svc.get_document(db, ctx, doc_id, "ENVELOPE")
    if env_lib.PAYMENTS not in env_lib.tags(d):
        raise not_found("Template")
    return d


def _payments_envelopes(db, ctx) -> list:
    from ..services import envelopes as env_lib
    return env_lib.envelopes(db, ctx, env_lib.PAYMENTS, active_only=True)


def _job(db, ctx, txn_id: int, body: JobIn):
    t = svc.get_printable(db, ctx, txn_id)
    style = svc.get_style(db, ctx, body.check_style_id)
    return svc.prepare(db, ctx, t, style, body.feed_key, memo_pattern=body.memo_pattern, payee_text=body.payee_text,
                       memo_text=body.memo_text, signer_id=body.signer_id, no_signature=body.no_signature,
                       page=body.page, guide=body.guide, signer2_id=body.signer2_id)


@router.get("/transactions/{txn_id}/options")
def print_options(txn_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    t = svc.get_printable(db, ctx, txn_id, for_check=False)
    acct = db.get(BankAccount, t.bank_account_id)
    styles = svc.list_styles(db, ctx, include_inactive=False)
    row = svc.account_row(db, ctx, acct.id)
    chosen = next((s for s in styles if row and s.id == row.check_style_id), None)
    out = {"transaction": {"id": t.id, "payee": t.parent_entity.display_name if t.parent_entity else None,
                           "amount": f"{t.total_cents // 100}.{t.total_cents % 100:02d}",
                           "transaction_date": t.transaction_date.isoformat(), "check_number": t.check_number,
                           "cleared": t.clear_date is not None, "bank_account_id": acct.id,
                           "electronic_payment": bool(t.electronic_payment),   # 2.1.0 (#260): letters/envelopes only
                           "bank_account_name": acct.account_name},
           "styles": [svc.style_out(s, full=False) for s in styles],
           "check_style_id": chosen.id if chosen else None,
           "signers": [svc.signer_out(s) for s in svc.list_signers(db, ctx) if s.active and s.image_ciphertext],
           "variables": patterns.variable_options(patterns.CHECK),
           "next_check_number": svc.next_check_number(db, ctx, acct.id),
           "print_status": svc.print_status(db, t), "last_printed_number": svc.last_printed_number(db, t),
           "is_reprint": svc.is_reprint(db, t),
           # #165/#166: letters and envelopes can be printed on their own when the check is written by hand
           "has_documents": bool(svc.list_documents(db, ctx, "LETTER", False) or
                                 _payments_envelopes(db, ctx))}
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
    return _pdf(ctx, pdf, "alignment-test.pdf")


@router.post("/transactions/{txn_id}/print")
def print_check(txn_id: int, body: PrintIn, request: Request, db: Session = Depends(get_db),
                ctx: Ctx = Depends(print_ctx)):
    job = _job(db, ctx, txn_id, body)
    pdf = svc.print_check(db, ctx, request.app.state.settings, request.app.state.key, job,
                          check_number=body.check_number, confirm_check_number=body.confirm_check_number,
                          reprint_reason=body.reprint_reason, confirmations=body.confirmations)
    return _pdf(ctx, pdf, f"check-{job.t.check_number}.pdf")


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
    preset: Literal["WINDOW"] | None = None          # build 11 (#217): a cover letter for a window envelope
    config: dict | None = None                        # build 13: the editor's draft settings, saved at once
    duplicate_of: int | None = None                   # build 13: a draft copied from this template (logo too)
    # 2.2.0 (#325): the feature whose setup page creates the envelope (tagged for it); None = the global Envelopes
    # page (Not used). Letters are always Payments'.
    feature: Literal["PAYMENTS", "DONATIONS"] | None = "PAYMENTS"


class DraftIn(In):
    """Build 13: preview or test-print a template that is not saved yet."""
    kind: Literal["LETTER", "ENVELOPE"]
    config: dict
    logo_from: int | None = None                      # a duplicated letter shows its source's logo


class DocUpdateIn(In):
    name: str = Field(max_length=80)
    config: dict


class DocFlagsIn(In):
    active: bool | None = None
    is_default: bool | None = None
    feature: Literal["PAYMENTS", "DONATIONS"] = "PAYMENTS"     # 2.2.0 (#325): whose default (envelopes)


class DocTestIn(In):
    config: dict | None = None


class LetterIn(In):
    document_id: int
    signer_id: int | None = None
    fold_marks: Literal["NONE", "FRONT", "BACK"] | None = None   # 2.1.0 (#247): this letter only (default: user/template)
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
def create_document(body: DocCreateIn, db: Session = Depends(get_db), ctx: Ctx = Depends(doc_ctx)):
    source = svc.get_document(db, ctx, body.duplicate_of) if body.duplicate_of is not None else None
    _kind_ok(db, ctx, source.kind if source is not None else body.kind, body.feature)
    d = svc.create_document(db, ctx, body.kind, body.name, body.preset, body.config, source,
                            body.feature if (source.kind if source is not None else body.kind) == "ENVELOPE"
                            else "PAYMENTS")
    db.commit()
    return svc.doc_out(d)


# build 13: a new or duplicated template is a draft in the editor until its first Save - nothing is stored before
@router.get("/documents/draft")
def document_draft(kind: Literal["LETTER", "ENVELOPE"], preset: Literal["WINDOW"] | None = None,
                   duplicate_of: int | None = None, feature: Literal["PAYMENTS", "DONATIONS", "NONE"] = "PAYMENTS",
                   db: Session = Depends(get_db), ctx: Ctx = Depends(doc_ctx)):
    source = svc.get_document(db, ctx, duplicate_of) if duplicate_of is not None else None
    f = None if feature == "NONE" else feature
    _kind_ok(db, ctx, source.kind if source is not None else kind, f)
    return svc.draft_document(db, ctx, kind, preset, source, f)


def _draft_parts(db, ctx, body: DraftIn):
    _kind_ok(db, ctx, body.kind)
    cfg = svc._doc_config_or_422(body.kind, body.config)
    logo = None
    if body.logo_from is not None and body.kind == "LETTER":
        logo = svc.get_document(db, ctx, body.logo_from, "LETTER").logo_png
    return cfg, logo


@router.post("/documents/draft/preview-image")
def draft_preview_image(body: DraftIn, db: Session = Depends(get_db), ctx: Ctx = Depends(doc_ctx)):
    cfg, logo = _draft_parts(db, ctx, body)
    if not raster.available():
        raise AppError(501, "PREVIEW_UNAVAILABLE", "The picture preview is not available on this server.")
    pdf = svc.sample_letter_pdf(cfg, logo) if body.kind == "LETTER" else svc.sample_envelope_pdf(cfg, preview=True)
    png, pages = raster.pdf_to_png(pdf)
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                             "X-Page-Count": str(pages)})


@router.post("/documents/draft/preview")
def draft_preview(body: DraftIn, db: Session = Depends(get_db), ctx: Ctx = Depends(doc_ctx)):
    cfg, logo = _draft_parts(db, ctx, body)
    pdf = svc.sample_letter_pdf(cfg, logo) if body.kind == "LETTER" else svc.sample_envelope_pdf(cfg, preview=True)
    return _pdf(ctx, pdf, f"{body.kind.lower()}-preview.pdf")


@router.post("/documents/draft/test-print")
def draft_test_print(body: DraftIn, db: Session = Depends(get_db), ctx: Ctx = Depends(doc_ctx)):
    cfg, logo = _draft_parts(db, ctx, body)
    pdf = svc.sample_letter_pdf(cfg, logo) if body.kind == "LETTER" else svc.sample_envelope_pdf(cfg)
    audit.record(db, ctx, "CHECK_DOCUMENT_TEST_PRINT", "check_document", None, None,
                 {"unsaved_settings": True, "draft": True, "kind": body.kind})
    db.commit()
    return _pdf(ctx, pdf, f"{body.kind.lower()}-test-print.pdf")


@router.post("/documents/{doc_id}/duplicate", status_code=201)
def duplicate_document(doc_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(doc_ctx)):
    """Build 11 (#217): copy a letter or envelope template with all its settings (logo included)."""
    d = svc.get_document(db, ctx, doc_id)
    _kind_ok(db, ctx, d.kind, "PAYMENTS" if d.kind == "ENVELOPE" else None)
    d = svc.duplicate_document(db, ctx, d)
    db.commit()
    return svc.doc_out(d)


@router.put("/documents/{doc_id}")
def update_document(doc_id: int, body: DocUpdateIn, db: Session = Depends(get_db), ctx: Ctx = Depends(doc_ctx)):
    d = svc.get_document(db, ctx, doc_id)
    _kind_ok(db, ctx, d.kind)
    d = svc.update_document(db, ctx, d, body.name, body.config)
    db.commit()
    return svc.doc_out(d)


@router.post("/documents/{doc_id}/flags")
def document_flags(doc_id: int, body: DocFlagsIn, db: Session = Depends(get_db), ctx: Ctx = Depends(doc_ctx)):
    d = svc.get_document(db, ctx, doc_id)
    _kind_ok(db, ctx, d.kind, body.feature if d.kind == "ENVELOPE" and body.is_default else None)
    d = svc.set_document_flags(db, ctx, d, body.active, body.is_default, body.feature)
    db.commit()
    return svc.doc_out(d)


@router.post("/documents/{doc_id}/logo")
async def document_logo(doc_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                        ctx: Ctx = Depends(setup_ctx)):
    """#176: upload a cover letter's logo (PNG or JPEG, at most 1 MB; re-encoded as PNG)."""
    d = svc.get_document(db, ctx, doc_id, "LETTER")
    data = await file.read(svc.MAX_LOGO_BYTES + 1)
    if len(data) > svc.MAX_LOGO_BYTES:
        raise AppError(413, "FILE_TOO_LARGE", "A logo may not exceed 1 MB.")
    svc.set_logo(db, ctx, d, data)
    db.commit()
    return svc.doc_out(d)


@router.post("/documents/{doc_id}/logo/remove")
def document_logo_remove(doc_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    d = svc.set_logo(db, ctx, svc.get_document(db, ctx, doc_id, "LETTER"), None)
    db.commit()
    return svc.doc_out(d)


@router.get("/documents/{doc_id}/logo")
def document_logo_image(doc_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(setup_ctx)):
    """The stored (re-encoded) logo, for the editor."""
    d = svc.get_document(db, ctx, doc_id, "LETTER")
    if not d.logo_png:
        raise not_found("Logo")
    return Response(d.logo_png, media_type="image/png",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                             "Content-Disposition": 'inline; filename="logo.png"'})


@router.post("/documents/{doc_id}/test-print")
def document_test(doc_id: int, body: DocTestIn, db: Session = Depends(get_db), ctx: Ctx = Depends(doc_ctx)):
    d = svc.get_document(db, ctx, doc_id)
    _kind_ok(db, ctx, d.kind)
    cfg = svc._doc_config_or_422(d.kind, body.config) if body.config is not None else svc.doc_config(d)
    pdf = svc.sample_letter_pdf(cfg, d.logo_png) if d.kind == "LETTER" else svc.sample_envelope_pdf(cfg)
    audit.record(db, ctx, "CHECK_DOCUMENT_TEST_PRINT", "check_document", d.id, None,
                 {"unsaved_settings": body.config is not None})
    db.commit()
    return _pdf(ctx, pdf, f"{d.kind.lower()}-test-print.pdf")


@router.post("/documents/{doc_id}/preview")
def document_preview(doc_id: int, body: DocTestIn, db: Session = Depends(get_db), ctx: Ctx = Depends(doc_ctx)):
    """#186: the live on-screen preview of a letter or envelope template with sample data (unsaved settings). Nothing
    is printed or stored, so it is not audited (the test print is)."""
    d = svc.get_document(db, ctx, doc_id)
    _kind_ok(db, ctx, d.kind)
    cfg = svc._doc_config_or_422(d.kind, body.config) if body.config is not None else svc.doc_config(d)
    pdf = svc.sample_letter_pdf(cfg, d.logo_png) if d.kind == "LETTER" else svc.sample_envelope_pdf(cfg, preview=True)
    return _pdf(ctx, pdf, f"{d.kind.lower()}-preview.pdf")


@router.post("/documents/{doc_id}/preview-image")
def document_preview_image(doc_id: int, body: DocTestIn, db: Session = Depends(get_db), ctx: Ctx = Depends(doc_ctx)):
    """Build 11 (#217): the same live preview as a PNG picture, which every browser shows (Safari shows an inline PDF
    blank). 501 PREVIEW_UNAVAILABLE where the PDF renderer can't load; the editor then falls back to the PDF."""
    d = svc.get_document(db, ctx, doc_id)
    _kind_ok(db, ctx, d.kind)
    cfg = svc._doc_config_or_422(d.kind, body.config) if body.config is not None else svc.doc_config(d)
    if not raster.available():
        raise AppError(501, "PREVIEW_UNAVAILABLE", "The picture preview is not available on this server.")
    pdf = svc.sample_letter_pdf(cfg, d.logo_png) if d.kind == "LETTER" else svc.sample_envelope_pdf(cfg, preview=True)
    png, pages = raster.pdf_to_png(pdf)
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                             "X-Page-Count": str(pages)})


@router.get("/transactions/{txn_id}/documents")
def transaction_documents(txn_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    """Letter and envelope templates for the print screen, with the user's envelope printer settings."""
    svc.get_printable(db, ctx, txn_id, for_check=False)
    letters = [{**svc.doc_out(d, full=False), "fold_default": svc.letter_fold_default(db, ctx, d)}
               for d in svc.list_documents(db, ctx, "LETTER", False)]
    from ..services import envelopes as env_lib
    envs = []
    for d in env_lib.envelopes(db, ctx, env_lib.PAYMENTS, active_only=True):   # 2.2.0 (#325): Payments' envelopes
        envs.append({**svc.doc_out(d, full=False), "printer": svc.envelope_options(db, ctx, d)})
    return {"letters": letters, "envelopes": envs, "my_letter_fold": svc.my_letter_fold(db, ctx)}


class LetterFoldIn(In):
    fold_marks: Literal["TEMPLATE", "FRONT", "BACK"]


@router.get("/my-printer/letter")
def my_letter_printer(db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    """2.1.0 (#247): the user's own cover-letter fold-mark default (My Printer Settings)."""
    return {"fold_marks": svc.my_letter_fold(db, ctx)}


@router.put("/my-printer/letter")
def save_my_letter_printer(body: LetterFoldIn, db: Session = Depends(get_db), ctx: Ctx = Depends(print_ctx)):
    v = svc.save_my_letter_fold(db, ctx, body.fold_marks)
    db.commit()
    return {"fold_marks": v}


@router.post("/transactions/{txn_id}/letter")
def print_letter(txn_id: int, body: LetterIn, request: Request, db: Session = Depends(get_db),
                 ctx: Ctx = Depends(print_ctx)):
    t = svc.get_printable(db, ctx, txn_id, for_check=False)
    d = svc.get_document(db, ctx, body.document_id, "LETTER")
    pdf = svc.print_letter(db, ctx, request.app.state.settings, t, d, body.signer_id, body.confirmations,
                           fold=body.fold_marks)
    return _pdf(ctx, pdf, f"letter-{t.check_number or t.id}.pdf")


@router.post("/transactions/{txn_id}/envelope")
def print_envelope(txn_id: int, body: EnvelopeIn, request: Request, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(print_ctx)):
    t = svc.get_printable(db, ctx, txn_id, for_check=False)
    d = _payments_envelope(db, ctx, body.document_id)
    pdf = svc.print_envelope(db, ctx, request.app.state.settings, t, d, return_address=body.return_address,
                             page=body.page, guide=body.guide, test=False, confirmations=body.confirmations)
    return _pdf(ctx, pdf, f"envelope-{t.check_number or t.id}.pdf")


@router.post("/transactions/{txn_id}/envelope-test")
def envelope_test(txn_id: int, body: EnvelopeIn, request: Request, db: Session = Depends(get_db),
                  ctx: Ctx = Depends(print_ctx)):
    t = svc.get_printable(db, ctx, txn_id, for_check=False)
    d = _payments_envelope(db, ctx, body.document_id)
    pdf = svc.print_envelope(db, ctx, request.app.state.settings, t, d, return_address=body.return_address,
                             page=body.page, guide=body.guide, test=True, confirmations=[])
    return _pdf(ctx, pdf, "envelope-test.pdf")


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
