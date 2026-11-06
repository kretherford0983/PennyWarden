"""2.4.0 (#539, decided with Kyle 2026-11-06): donation receipts and year-end statements by email, through the mail
server set up for Invoices (System/About -> Email, #249) and its code: the same form (To pre-filled with the donor's
address, Cc, subject and message editable), the same email log and audit.

* The subject and message start from Donations Setup (editable there by the Administrator, with variables).
* Who: whoever can print receipts. Emailing **issues** the receipt or statement exactly as printing does (number,
  original / duplicate / corrected, the copy kept with the record) - it counts as issued, so it isn't printed twice.
* The send happens before the receipt is committed: if the mail server refuses it, the receipt isn't issued; the
  failure is still in the email log (and the audit log).
* With email off or not set up the Email button isn't shown (`me.email_ready`) and the endpoints refuse.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, conflict
from ..models import EmailLog, Entity
from . import donation_statements as stm
from . import donations as dn
from . import email as em

RECEIPT, STATEMENT = "RECEIPT", "DONOR_STMT"


class _NotSent(Exception):
    def __init__(self, log: EmailLog):
        super().__init__(log.error or "not sent")
        self.fields = {c: getattr(log, c) for c in ("workspace_id", "kind", "customer_entity_id", "to_address",
                                                   "cc_address", "subject", "body", "attachment_name",
                                                   "attachment_sha256", "status", "error", "sent_by_user_id")}


def _fill(text: str, values: dict[str, str]) -> str:
    for k, v in values.items():
        text = text.replace("{" + k + "}", v)
    return text


def _org(db: Session, ws_id: int) -> str:
    return em._org_name(db, ws_id)


def defaults(db: Session, ctx, kind: str, donor: Entity, amount_cents: int | None = None,
             year: int | None = None) -> dict:
    """What the Email form starts with: the donor's address and the setup's subject and message, filled in."""
    dn.require_module(db, ctx)
    cfg = dn.get_config(db, ctx.workspace_id)
    s = em.settings_of(db, ctx.workspace_id)
    values = {"DONOR_NAME": donor.display_name, "ORG.NAME": _org(db, ctx.workspace_id),
              "AMOUNT": dn.money(amount_cents) if amount_cents is not None else "",
              "YEAR": str(year or ""), "TOTAL": dn.money(amount_cents) if amount_cents is not None else ""}
    subject, message = ((cfg.email_subject, cfg.email_message) if kind == RECEIPT
                        else (cfg.statement_email_subject, cfg.statement_email_message))
    return {"ready": em.ready(s), "to": [donor.email] if donor.email else [], "cc": [],
            "subject": _fill(subject, values)[:200], "message": _fill(message, values), "donor": donor.display_name}


def _sender(db: Session, ctx, km, kind: str, donor_id: int, body, number_of):
    """The before-commit hook: send now; a refused send raises so the receipt isn't issued."""
    to = em._recipients(body.to, "to", True)
    cc = em._recipients(body.cc, "cc", False)
    if not em.ready(em.settings_of(db, ctx.workspace_id)):
        raise conflict("EMAIL_NOT_SET_UP", "Email isn't set up: an Administrator sets the mail server in "
                       "System/About → Settings → Email.")

    def send(printed: bytes, record) -> None:
        name = f"{'receipt' if kind == RECEIPT else 'statement'}-{number_of(record)}.pdf"
        cfg = dn.get_config(db, ctx.workspace_id)
        log = em._send_logged(db, ctx, km, kind, to, cc, body.subject, body.message, (name, printed),
                              customer_id=donor_id, sender={"reply_to": cfg.email_reply_to or None,
                                                            "from_name": cfg.email_from_name or None})
        if log.status != "SENT":
            raise _NotSent(log)
    return send


def _after_failure(db: Session, ctx, x: _NotSent) -> AppError:
    """The receipt was rolled back with the send; the failed attempt is still logged."""
    log = EmailLog(**x.fields)
    db.add(log)
    db.flush()
    audit.record(db, ctx, "EMAIL_SEND_FAILED", "email_log", log.id, None,
                 {"kind": log.kind, "email_log_id": log.id, "to": log.to_address, "subject": log.subject,
                  "customer_entity_id": log.customer_entity_id, "status": log.status, "error": log.error})
    db.commit()
    return AppError(502, "EMAIL_NOT_SENT", f"The email wasn't sent, so nothing was issued: {log.error}")


def email_donation(db: Session, ctx, km, settings, d, body) -> dict:
    send = _sender(db, ctx, km, RECEIPT, d.donor_entity_id, body, lambda r: r.number)
    try:
        _pdf, r = dn.print_donation(db, ctx, settings, d, body.confirmations, km=km, signer_id=body.signer_id,
                                    before_commit=send)
    except _NotSent as x:
        raise _after_failure(db, ctx, x) from None
    return {"number": r.number, "kind": r.kind, "emailed": True}


def email_deposit_receipt(db: Session, ctx, km, settings, t, donor_entity_id: int, body) -> dict:
    send = _sender(db, ctx, km, RECEIPT, donor_entity_id, body, lambda r: r.number)
    try:
        _pdf, r = dn.print_receipt(db, ctx, settings, t, donor_entity_id, body.confirmations, km=km,
                                   signer_id=body.signer_id, before_commit=send)
    except _NotSent as x:
        raise _after_failure(db, ctx, x) from None
    return {"number": r.number, "kind": r.kind, "emailed": True}


def email_statement(db: Session, ctx, km, settings, year: int, donor_id: int, body) -> dict:
    send = _sender(db, ctx, km, STATEMENT, donor_id, body, lambda s: s.number)
    try:
        _pdf, s = stm.print_one(db, ctx, settings, year, donor_id, body.confirmations, km=km,
                                signer_id=body.signer_id, before_commit=send)
    except _NotSent as x:
        raise _after_failure(db, ctx, x) from None
    return {"number": s.number, "kind": s.kind, "emailed": True, "id": s.id}


def emailed_numbers(db: Session, ws_id: int, kind: str) -> set[str]:
    """The receipt / statement numbers that went out by email (from the email log's attachment names)."""
    prefix = "receipt-" if kind == RECEIPT else "statement-"
    out = set()
    for name in db.scalars(select(EmailLog.attachment_name).where(EmailLog.workspace_id == ws_id, EmailLog.kind == kind,
                                                                  EmailLog.status == "SENT")):
        if name and name.startswith(prefix) and name.endswith(".pdf"):
            out.add(name[len(prefix):-4])
    return out
