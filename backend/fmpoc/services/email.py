"""2.4.0 (#249): email invoices and statements.

- The Administrator sets the outgoing mail server (System/About → Settings → Email): host, port, security
  (STARTTLS / SSL / none), user name, password, sender address and name, reply-to. The password is encrypted with the
  application key, is replace-only (never returned, logged, audited or put in an error message: BR-103/104) and an
  empty password field keeps the saved one. A **test email** goes to an address the Administrator types.
- An Invoice Manager emails an invoice (its kept PDF of the current sent version) or a customer statement (PDF) to
  the customer: To (pre-filled with the customer's email), Cc, subject and message are shown and editable; one click,
  one email. Nothing is ever sent automatically.
- Every email (and every failed attempt) is in the email log - kind, invoice/customer, recipients, subject, message,
  attachment name and SHA-256, who and when, result - and in the audit log (without the message text).
"""
from __future__ import annotations

import hashlib
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, conflict, not_found, validation
from ..money import fmt
from ..models import Attachment, EmailLog, EmailSettings, Entity, Invoice, InvoiceRevision, User, Workspace
from ..security import crypto
from . import invoice_docs as docs
from . import invoices as inv

AAD = b"fmpoc:smtp_password:v1"
SECURITY = ("STARTTLS", "SSL", "NONE")
TIMEOUT = 20
MAX_RECIPIENTS = 10
ADDR = re.compile(r"^[^@\s<>,;\"']{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")


# ------------------------------------------------------------------ settings (Administrator)
def settings_of(db: Session, ws_id: int) -> EmailSettings:
    s = db.scalar(select(EmailSettings).where(EmailSettings.workspace_id == ws_id))
    if s is None:
        s = EmailSettings(workspace_id=ws_id, enabled=False, port=587, security="STARTTLS")
        db.add(s)
        db.flush()
    return s


def _public(s: EmailSettings) -> dict:
    """What may be shown or audited - never the password, only whether one is saved."""
    return {"enabled": bool(s.enabled), "host": s.host, "port": s.port, "security": s.security, "username": s.username,
            "password_saved": bool(s.password_enc), "from_address": s.from_address, "from_name": s.from_name,
            "reply_to": s.reply_to}


def ready(s: EmailSettings) -> bool:
    return bool(s.enabled and s.host and s.from_address)


def settings_out(db: Session, ctx) -> dict:
    ctx.require("email.setup")
    s = settings_of(db, ctx.workspace_id)
    return {**_public(s), "ready": ready(s)}


def _addr(v: str | None, field: str, required: bool = False) -> str | None:
    v = (v or "").strip()
    if not v:
        if required:
            raise validation("Enter an email address.", field)
        return None
    if not ADDR.match(v) or len(v) > 254:
        raise validation(f"\"{v[:80]}\" is not an email address.", field)
    return v


def save_settings(db: Session, ctx, km: crypto.KeyMaterial, body) -> dict:
    ctx.require("email.setup")
    s = settings_of(db, ctx.workspace_id)
    before = _public(s)
    host = (body.host or "").strip() or None
    if host and not HOST.match(host):
        raise validation("Enter the mail server's name (for example smtp.example.org).", "host")
    if body.security not in SECURITY:
        raise validation("Choose STARTTLS, SSL or none.", "security")
    if not 1 <= body.port <= 65535:
        raise validation("The port is 1 to 65535.", "port")
    if body.enabled and not host:
        raise validation("Enter the mail server to turn email on.", "host")
    s.host, s.port, s.security = host, body.port, body.security
    s.username = (body.username or "").strip() or None
    s.from_address = _addr(body.from_address, "from_address", required=bool(body.enabled))
    s.from_name = (body.from_name or "").strip()[:120] or None
    s.reply_to = _addr(body.reply_to, "reply_to")
    if body.clear_password:
        s.password_enc = None
    elif body.password:                         # empty = keep the saved one (replace only)
        s.password_enc = crypto.encrypt(km, body.password, AAD)
    s.enabled = bool(body.enabled)
    s.updated_by_user_id = ctx.user.id
    db.flush()
    after = _public(s)
    if after != before or body.password:
        audit.record(db, ctx, "EMAIL_SETTINGS_UPDATED", "email_settings", s.id, before,
                     {**after, "password_changed": bool(body.password or body.clear_password)})
    return {**after, "ready": ready(s)}


# ------------------------------------------------------------------ sending
def _smtp_send(s: EmailSettings, km: crypto.KeyMaterial, msg: EmailMessage) -> None:
    """One message through the configured server (the only place the password is decrypted). Tests replace this."""
    password = crypto.decrypt(km, s.password_enc, AAD) if s.password_enc else None
    ctx = ssl.create_default_context()
    if s.security == "SSL":
        server = smtplib.SMTP_SSL(s.host, s.port, timeout=TIMEOUT, context=ctx)
    else:
        server = smtplib.SMTP(s.host, s.port, timeout=TIMEOUT)
    try:
        server.ehlo()
        if s.security == "STARTTLS":
            server.starttls(context=ctx)
            server.ehlo()
        if s.username and password:
            server.login(s.username, password)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:                      # noqa: BLE001 - the message is already sent or failed
            pass


def _safe_error(x: Exception) -> str:
    """A short reason without anything secret (server replies don't contain our password; the exception text of a
    login failure is the server's reply)."""
    if isinstance(x, smtplib.SMTPAuthenticationError):
        return "The mail server refused the user name or password."
    if isinstance(x, smtplib.SMTPRecipientsRefused):
        return "The mail server refused the recipient address."
    if isinstance(x, (smtplib.SMTPConnectError, ConnectionError, TimeoutError, OSError)) and not isinstance(x, smtplib.SMTPException):
        return f"Could not reach the mail server ({type(x).__name__})."
    if isinstance(x, ssl.SSLError):
        return "A secure connection to the mail server failed."
    text = str(x).replace("\n", " ")[:200]
    return f"The mail server refused the message: {text}"


def _recipients(raw: list[str] | None, field: str, required: bool) -> list[str]:
    out = []
    for v in raw or []:
        a = _addr(v, field)
        if a and a.lower() not in [x.lower() for x in out]:
            out.append(a)
    if required and not out:
        raise validation("Enter the recipient's email address.", field)
    if len(out) > MAX_RECIPIENTS:
        raise validation(f"At most {MAX_RECIPIENTS} addresses.", field)
    return out


def _org_name(db: Session, ws_id: int) -> str:
    from . import organization as org_svc
    org = org_svc.get(db, ws_id)
    ws = db.get(Workspace, ws_id)
    return (org.organization_name if org else None) or (ws.name if ws else "")


def _message(s: EmailSettings, to: list[str], cc: list[str], subject: str, body: str,
             attachment: tuple[str, bytes] | None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((s.from_name or "", s.from_address))
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if s.reply_to:
        msg["Reply-To"] = s.reply_to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=(s.from_address or "localhost").split("@")[-1])
    msg.set_content(body or "")
    if attachment:
        msg.add_attachment(attachment[1], maintype="application", subtype="pdf", filename=attachment[0])
    return msg


def _send_logged(db: Session, ctx, km, kind: str, to: list[str], cc: list[str], subject: str, body: str,
                 attachment: tuple[str, bytes] | None, invoice_id: int | None = None,
                 customer_id: int | None = None) -> EmailLog:
    s = settings_of(db, ctx.workspace_id)
    if not ready(s):
        raise conflict("EMAIL_NOT_SET_UP", "Email isn't set up: an Administrator sets the mail server in "
                       "System/About → Settings → Email.")
    subject = (subject or "").strip().replace("\r", " ").replace("\n", " ")
    if not subject:
        raise validation("Enter a subject.", "subject")
    msg = _message(s, to, cc, subject[:200], body or "", attachment)
    log = EmailLog(workspace_id=ctx.workspace_id, kind=kind, invoice_id=invoice_id, customer_entity_id=customer_id,
                   to_address=", ".join(to), cc_address=", ".join(cc) or None, subject=subject[:200], body=body or None,
                   attachment_name=attachment[0] if attachment else None,
                   attachment_sha256=hashlib.sha256(attachment[1]).hexdigest() if attachment else None,
                   sent_by_user_id=ctx.user.id, status="SENT")
    try:
        _smtp_send(s, km, msg)
    except Exception as x:                     # noqa: BLE001 - logged and reported, never with the password
        log.status, log.error = "FAILED", _safe_error(x)
    db.add(log)
    db.flush()
    action = {"INVOICE": "INVOICE_EMAILED", "STATEMENT": "STATEMENT_EMAILED", "TEST": "EMAIL_TEST_SENT"}[kind]
    audit.record(db, ctx, action if log.status == "SENT" else "EMAIL_SEND_FAILED", "invoice" if invoice_id else "email_log", invoice_id or log.id, None,
                 {"kind": kind, "email_log_id": log.id, "to": log.to_address, "cc": log.cc_address, "subject": log.subject,
                  "attachment": log.attachment_name, "attachment_sha256": log.attachment_sha256,
                  "customer_entity_id": customer_id, "status": log.status, "error": log.error})
    return log


def log_out(db: Session, rows: list[EmailLog]) -> list[dict]:
    users = {u.id: u.username for u in db.scalars(select(User).where(User.id.in_({r.sent_by_user_id for r in rows if r.sent_by_user_id} or {0})))}
    return [{"id": r.id, "kind": r.kind, "invoice_id": r.invoice_id, "to": r.to_address, "cc": r.cc_address,
             "subject": r.subject, "attachment": r.attachment_name, "status": r.status, "error": r.error,
             "sent_at": r.sent_at.isoformat() + "Z", "sent_by": users.get(r.sent_by_user_id)} for r in rows]


def send_test(db: Session, ctx, km, to: str) -> dict:
    ctx.require("email.setup")
    a = _addr(to, "to", required=True)
    log = _send_logged(db, ctx, km, "TEST", [a], [], f"PennyWarden test email from {_org_name(db, ctx.workspace_id)}",
                       "This is a test email from PennyWarden. If you received it, the mail server settings work.", None)
    return log_out(db, [log])[0]


def defaults(db: Session, ctx, i: Invoice | None = None, customer: Entity | None = None, kind: str = "INVOICE") -> dict:
    """What the Send email form starts with: the customer's address, a subject and a short message (all editable)."""
    org = _org_name(db, ctx.workspace_id)
    s = settings_of(db, ctx.workspace_id)
    if kind == "INVOICE":
        e = db.get(Entity, i.customer_entity_id)
        t = docs.totals_of(i)
        from .invoice_payments import figures
        due = figures(db, i)["open"]
        subject = f"Invoice {docs.display_number(i)} from {org}"
        body = (f"Hello,\n\nPlease find attached invoice {docs.display_number(i)} for {fmt(t['total'])}"
                + (f", due {i.due_date:%B} {i.due_date.day}, {i.due_date.year}" if due else "") + ".\n\nThank you,\n" + org)
    else:
        e = customer
        subject = f"Statement from {org}"
        body = f"Hello,\n\nPlease find attached your statement.\n\nThank you,\n{org}"
    return {"to": [e.email] if e is not None and e.email else [], "cc": [], "subject": subject, "message": body,
            "ready": ready(s), "customer": e.display_name if e else None}


def _invoice_pdf(db: Session, settings, i: Invoice) -> tuple[str, bytes]:
    """The PDF kept when the current version was marked as sent (exactly what the customer gets)."""
    from . import attachments as att_svc
    r = db.scalar(select(InvoiceRevision).where(InvoiceRevision.invoice_id == i.id, InvoiceRevision.revision == i.revision))
    a = db.get(Attachment, r.attachment_id) if r and r.attachment_id else None
    if a is None:
        return f"invoice-{docs.display_number(i)}.pdf", docs.invoice_pdf(db, i.workspace_id, i)
    return a.original_filename, att_svc.path_for(settings, a).read_bytes()


def email_invoice(db: Session, ctx, km, settings, i: Invoice, body) -> EmailLog:
    inv.require_module(db, ctx)
    ctx.require("invoice.email")
    if i.status not in ("SENT", "PARTLY_PAID", "PAID"):
        raise conflict("INVALID_STATE", "Mark the invoice as sent first: the email carries the sent version's PDF. "
                       "A void or written-off invoice isn't emailed.")
    to = _recipients(body.to, "to", True)
    cc = _recipients(body.cc, "cc", False)
    att = _invoice_pdf(db, settings, i)
    return _send_logged(db, ctx, km, "INVOICE", to, cc, body.subject, body.message, att, invoice_id=i.id,
                        customer_id=i.customer_entity_id)


def email_statement(db: Session, ctx, km, body) -> EmailLog:
    from . import invoice_reports as rep
    inv.require_module(db, ctx)
    ctx.require("invoice.email")
    e = db.get(Entity, body.customer_entity_id) if isinstance(body.customer_entity_id, int) else None
    if e is None or e.workspace_id != ctx.workspace_id:
        raise not_found("Customer")
    to = _recipients(body.to, "to", True)
    cc = _recipients(body.cc, "cc", False)
    r = rep.statement(db, ctx, e.id, body.date_from, body.date_to)
    pdf = rep.as_pdf(db, ctx, r)
    name = f"statement-{body.date_to.isoformat()}.pdf"
    return _send_logged(db, ctx, km, "STATEMENT", to, cc, body.subject, body.message, (name, pdf), customer_id=e.id)


def invoice_log(db: Session, ctx, i: Invoice) -> list[dict]:
    return log_out(db, list(db.scalars(select(EmailLog).where(EmailLog.invoice_id == i.id).order_by(EmailLog.id.desc()))))


def raise_if_failed(log: EmailLog) -> None:
    if log.status != "SENT":
        raise AppError(502, "EMAIL_FAILED", f"The email was not sent. {log.error}", email_log_id=log.id)
