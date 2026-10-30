"""v1.4.1 CR-018: multi-factor authentication - TOTP (RFC 6238), one-time recovery codes, trusted browsers.

* Required for every user in server mode; optional (but available) in local loopback mode (product owner Q4).
* The TOTP secret is encrypted with the portable key (own AAD), so a data set moves between machines intact.
* Codes: 6 digits, 30-second steps, SHA-1 (what authenticator apps expect), +/-1 step tolerance; a step that was
  already accepted is refused (replay protection).
* Recovery codes: 10 per enrollment, shown once, stored as SHA-256 of the normalized code, each usable once.
  New codes are only produced by setting MFA up again (product owner requirement).
* Trusted browsers (Q6): an HttpOnly cookie holding a random token; the server keeps only its SHA-256. Valid 30
  days; revoked by password change/reset, MFA change/reset/disable and on request.
"""
from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
import hmac
import secrets
import time
from urllib.parse import parse_qs, urlsplit

import pyotp
import segno
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, conflict, validation
from ..models import MfaRecoveryCode, TrustedDevice, User, UserMfa, Workspace, utcnow
from ..security import crypto

AAD = b"fmpoc:totp_secret:v1"
ISSUER = "PennyWarden"
RECOVERY_COUNT = 10
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
TRUST_COOKIE = "fm_trusted"
TRUST_DAYS = 30
PENDING_MINUTES = 10  # lifetime of a password-accepted, MFA-pending session
ENROLL_PENDING_MINUTES = 15
# 2.2.0 (#327): a key the user brings along. At least 16 Base32 characters (80 bits) so keys from most other sites
# work; PennyWarden's own keys are 32 (160 bits) and a shorter key gets a note. At most 100 (500 bits: far beyond any
# authenticator's keys, and the encrypted value still fits the column).
OWN_KEY_MIN = 16
OWN_KEY_OWN_LENGTH = 32
OWN_KEY_MAX = 100
_B32 = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def required(settings) -> bool:
    return settings.mode == "server"


def _row(db: Session, user_id: int) -> UserMfa | None:
    return db.scalar(select(UserMfa).where(UserMfa.user_id == user_id))


def enabled(db: Session, user: User) -> bool:
    r = _row(db, user.id)
    return bool(r and r.enabled_at and r.secret_enc)


def _sha(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def _norm_recovery(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def _new_recovery_codes() -> list[str]:
    out = []
    for _ in range(RECOVERY_COUNT):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(12))
        out.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    return out


def status(db: Session, settings, user: User) -> dict:
    r = _row(db, user.id)
    remaining = len(db.scalars(select(MfaRecoveryCode.id).where(MfaRecoveryCode.user_id == user.id,
                                                                MfaRecoveryCode.used_at.is_(None))).all())
    now = utcnow()
    devices = db.scalars(select(TrustedDevice).where(TrustedDevice.user_id == user.id,
                                                     TrustedDevice.revoked_at.is_(None),
                                                     TrustedDevice.expires_at > now)
                         .order_by(TrustedDevice.created_at.desc())).all()
    return {
        "enabled": bool(r and r.enabled_at and r.secret_enc),
        "enabled_at": r.enabled_at.isoformat() + "Z" if r and r.enabled_at else None,
        "required": required(settings),
        "recovery_codes_remaining": remaining,
        "trusted_browsers": [{"id": d.id, "label": d.label, "created_at": d.created_at.isoformat() + "Z",
                              "last_used_at": d.last_used_at.isoformat() + "Z" if d.last_used_at else None,
                              "expires_at": d.expires_at.isoformat() + "Z"} for d in devices],
    }


# ------------------------------------------------------------------ verification
def _check_totp(km, r: UserMfa, code: str, secret_enc: str | None = None) -> int | None:
    """Returns the accepted time step, or None. Uses the active secret unless secret_enc is given."""
    token = secret_enc or r.secret_enc
    if not token or len(code) != 6 or not code.isdigit():
        return None
    totp = pyotp.TOTP(crypto.decrypt(km, token, AAD))
    now_step = int(time.time()) // 30
    for step in (now_step - 1, now_step, now_step + 1):
        if hmac.compare_digest(totp.at(step * 30), code):
            if secret_enc is None and r.last_step is not None and step <= r.last_step:
                return None  # replay of an already accepted code
            return step
    return None


def verify(db: Session, km, user: User, code: str) -> str | None:
    """Checks a TOTP code or a recovery code for an enrolled user. Returns "totp", "recovery" or None."""
    r = _row(db, user.id)
    if not (r and r.enabled_at and r.secret_enc):
        return None
    c = (code or "").strip().replace(" ", "")
    if c.isdigit():
        step = _check_totp(km, r, c)
        if step is not None:
            r.last_step = step
            return "totp"
        return None
    norm = _norm_recovery(c)
    if len(norm) != 12:
        return None
    h = _sha(norm)
    rc = db.scalar(select(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id,
                                                 MfaRecoveryCode.used_at.is_(None),
                                                 MfaRecoveryCode.code_hash == h))
    if rc is None:
        return None
    rc.used_at = utcnow()
    return "recovery"


# ------------------------------------------------------------------ own key (2.2.0, #327)
def _own_key_error(message: str) -> AppError:
    """Describes the problem without ever repeating the key (BR-103)."""
    return validation(message, "own_key")


def parse_own_key(value: str | None) -> tuple[str, bool]:
    """A Base32 key (spaces, dashes, lower case and trailing '=' ignored) or an otpauth://totp/... link.
    Returns (normalized Base32 secret, shorter than PennyWarden's own keys). Raises 422 with the reason - never with
    the key in it."""
    raw = (value or "").strip()
    if not raw:
        raise _own_key_error("Enter your authenticator key, or remove the text to use the key shown above.")
    if raw.lower().startswith("otpauth"):
        parts = urlsplit(raw)
        if parts.scheme.lower() != "otpauth":
            raise _own_key_error("This link is not supported. Paste the key, or an otpauth://totp/ link.")
        if parts.netloc.lower() != "totp":
            raise _own_key_error("Only time-based (TOTP) authenticator links are supported; counter-based (HOTP) "
                                 "links are not.")
        q = {k.lower(): v for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
        if len(q.get("secret", [])) != 1:
            raise _own_key_error("The link has no key (secret) in it.")
        algorithm = (q.get("algorithm", ["SHA1"])[0] or "SHA1").upper().replace("-", "")
        digits = (q.get("digits", ["6"])[0] or "6").strip()
        period = (q.get("period", ["30"])[0] or "30").strip()
        unsupported = []
        if algorithm != "SHA1":
            unsupported.append("the SHA-1 algorithm")
        if digits != "6":
            unsupported.append("6-digit codes")
        if period != "30":
            unsupported.append("30-second codes")
        if unsupported:
            raise _own_key_error("PennyWarden supports only " + ", ".join(unsupported) + " for this setting"
                                 + ("s" if len(unsupported) > 1 else "") + ", and this link asks for something else. "
                                 "Use the key shown above instead.")
        raw = q["secret"][0]
    key = "".join(ch for ch in raw.upper() if ch not in " -\t").rstrip("=")
    if not key or any(ch not in _B32 for ch in key):
        raise _own_key_error("The key is not valid: an authenticator key uses only the letters A-Z and the digits 2-7.")
    if len(key) < OWN_KEY_MIN:
        raise _own_key_error(f"The key is too short: it must be at least {OWN_KEY_MIN} characters (80 bits).")
    if len(key) > OWN_KEY_MAX:
        raise _own_key_error(f"The key is too long: it can be at most {OWN_KEY_MAX} characters.")
    try:
        base64.b32decode(key + "=" * (-len(key) % 8))
    except (binascii.Error, ValueError):
        raise _own_key_error("The key is not valid: it is not a complete Base32 key (a character may be missing "
                             "or extra).") from None
    return key, len(key) < OWN_KEY_OWN_LENGTH


def _pending_payload(db: Session, user: User, secret: str, r: UserMfa) -> dict:
    ws = db.get(Workspace, user.workspace_id)
    issuer = f"{ISSUER} ({ws.name})" if ws else ISSUER
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name=issuer)
    qr = segno.make(uri, error="m").svg_data_uri(scale=5, border=2, dark="#000000", light="#ffffff")
    return {"secret": " ".join(secret[i:i + 4] for i in range(0, len(secret), 4)), "otpauth_uri": uri,
            "qr_svg": qr, "issuer": issuer, "account": user.username,
            "expires_in_minutes": ENROLL_PENDING_MINUTES,
            "own_key": False, "own_key_allowed": not r.new_key_required}


def use_own_key(db: Session, km, ctx, own_key: str | None) -> dict:
    """2.2.0 (#327): replaces the key of the setup in progress (started with `start_enrollment`, which already asked
    for a current code when an authenticator is being changed) with the user's own key - or, with no key, with a
    newly generated one again. The setup still needs a current code made with that key before anything is saved."""
    user = ctx.user
    r = _row(db, user.id)
    if r is None or not r.pending_secret_enc or r.pending_created_at is None or \
            r.pending_created_at + dt.timedelta(minutes=ENROLL_PENDING_MINUTES) < utcnow():
        raise conflict("MFA_NO_PENDING_SETUP", "Start the authenticator setup again.")
    if own_key is None:
        secret = pyotp.random_base32()
        r.pending_secret_enc, r.pending_own_key = crypto.encrypt(km, secret, AAD), False
        r.pending_created_at = utcnow()
        payload = _pending_payload(db, user, secret, r)
        db.commit()
        return payload
    if r.new_key_required:
        raise conflict("MFA_NEW_KEY_REQUIRED", "Your two-step verification was reset after a possible security problem, "
                                               "so it must be set up with the new key shown above.")
    key, short = parse_own_key(own_key)
    r.pending_secret_enc, r.pending_own_key = crypto.encrypt(km, key, AAD), True
    db.commit()
    return {"own_key": True, "short_key": short, "key_length": len(key), "own_key_length": OWN_KEY_OWN_LENGTH,
            "expires_in_minutes": ENROLL_PENDING_MINUTES, "own_key_allowed": True}


# ------------------------------------------------------------------ enrollment
def start_enrollment(db: Session, km, ctx, current_code: str | None) -> dict:
    """Creates a pending secret. Changing an existing authenticator needs a current code or a recovery code."""
    user = ctx.user
    r = _row(db, user.id)
    if r and r.enabled_at and r.secret_enc:
        used = verify(db, km, user, current_code or "")
        if used is None:
            audit.record(db, ctx, "MFA_FAILED", "user", user.id, None, {"stage": "change_authenticator"},
                         category="SECURITY")
            db.commit()
            raise AppError(400, "MFA_INVALID_CODE", "The code is not valid. Enter a current code from your "
                                                    "authenticator app or one of your recovery codes.")
        if used == "recovery":
            audit.record(db, ctx, "MFA_RECOVERY_CODE_USED", "user", user.id, None, {"stage": "change_authenticator"},
                         category="SECURITY")
    if r is None:
        r = UserMfa(user_id=user.id)
        db.add(r)
    secret = pyotp.random_base32()  # 160-bit
    r.pending_secret_enc = crypto.encrypt(km, secret, AAD)
    r.pending_created_at = utcnow()
    r.pending_own_key = False
    db.flush()
    payload = _pending_payload(db, user, secret, r)
    db.commit()
    return payload


def confirm_enrollment(db: Session, km, ctx, code: str) -> list[str]:
    user = ctx.user
    r = _row(db, user.id)
    if r is None or not r.pending_secret_enc or r.pending_created_at is None:
        raise conflict("MFA_NO_PENDING_SETUP", "Start the authenticator setup again.")
    if r.pending_created_at + dt.timedelta(minutes=ENROLL_PENDING_MINUTES) < utcnow():
        r.pending_secret_enc = r.pending_created_at = None
        db.commit()
        raise conflict("MFA_SETUP_EXPIRED", "The setup expired. Start the authenticator setup again.")
    step = _check_totp(km, r, (code or "").strip().replace(" ", ""), secret_enc=r.pending_secret_enc)
    if step is None:
        audit.record(db, ctx, "MFA_FAILED", "user", user.id, None, {"stage": "enrollment"}, category="SECURITY")
        db.commit()
        raise AppError(400, "MFA_INVALID_CODE", "The code does not match. Check the time on your phone and enter "
                                                "the current 6-digit code.")
    changed = bool(r.enabled_at and r.secret_enc)
    own_key = bool(r.pending_own_key)
    r.secret_enc, r.enabled_at, r.last_step = r.pending_secret_enc, utcnow(), step
    r.pending_secret_enc = r.pending_created_at = None
    r.pending_own_key = False
    r.new_key_required = False   # 2.2.0 (#327): a completed setup ends the "new key only" rule of a compromise reset
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    codes = _new_recovery_codes()
    for c in codes:
        db.add(MfaRecoveryCode(user_id=user.id, code_hash=_sha(_norm_recovery(c))))
    revoked = revoke_trusted(db, user.id) if changed else 0
    audit.record(db, ctx, "MFA_CHANGED" if changed else "MFA_ENROLLED", "user", user.id, None,
                 {"recovery_codes_issued": len(codes), "trusted_browsers_revoked": revoked, "own_key": own_key},
                 category="SECURITY")
    db.flush()
    return codes


# ------------------------------------------------------------------ trusted browsers
def issue_trusted(db: Session, ctx, user: User, label: str | None) -> tuple[str, dt.datetime]:
    token = secrets.token_urlsafe(32)
    exp = utcnow() + dt.timedelta(days=TRUST_DAYS)
    d = TrustedDevice(user_id=user.id, token_hash=_sha(token), label=(label or "")[:200] or None, expires_at=exp)
    db.add(d)
    db.flush()
    audit.record(db, ctx, "MFA_TRUSTED_BROWSER_ADDED", "user", user.id, None,
                 {"trusted_browser_id": d.id, "expires_at": exp}, category="SECURITY")
    return token, exp


def check_trusted(db: Session, user: User, token: str | None) -> bool:
    if not token or len(token) > 200:
        return False
    d = db.scalar(select(TrustedDevice).where(TrustedDevice.token_hash == _sha(token)))
    if d is None or d.user_id != user.id or d.revoked_at is not None or d.expires_at <= utcnow():
        return False
    d.last_used_at = utcnow()
    return True


def revoke_trusted(db: Session, user_id: int, device_id: int | None = None) -> int:
    stmt = update(TrustedDevice).where(TrustedDevice.user_id == user_id, TrustedDevice.revoked_at.is_(None))
    if device_id is not None:
        stmt = stmt.where(TrustedDevice.id == device_id)
    return db.execute(stmt.values(revoked_at=utcnow())).rowcount or 0


# ------------------------------------------------------------------ reset / disable
def reset(db: Session, ctx, user: User, reason: str, via: str = "administrator", compromised: bool = False) -> None:
    """Administrator (or host CLI) reset: the user sets MFA up again at the next sign-in.
    2.2.0 (#327): `compromised` marks a possible compromise - the next setup accepts only a newly generated key. The
    mark stays until a setup is completed (a later reset without the mark does not lift it)."""
    from .auth import revoke_user_sessions
    reason = (reason or "").strip()
    if not reason:
        raise validation("A reason is required.", "reason")
    had = enabled(db, user)
    prev = _row(db, user.id)
    new_key_only = bool(compromised or (prev is not None and prev.new_key_required))
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    db.execute(delete(UserMfa).where(UserMfa.user_id == user.id))
    if new_key_only:
        db.flush()
        db.add(UserMfa(user_id=user.id, new_key_required=True))
    trusted = revoke_trusted(db, user.id)
    sessions = revoke_user_sessions(db, user.id)
    audit.record(db, ctx, "MFA_RESET", "user", user.id, {"mfa_enabled": had},
                 {"mfa_enabled": False, "via": via, "reason": reason[:500], "sessions_revoked": sessions,
                  "trusted_browsers_revoked": trusted, "compromised": bool(compromised),
                  "new_key_required": new_key_only}, category="SECURITY")


def disable(db: Session, km, settings, ctx, code: str) -> None:
    """Local (loopback) mode only - in server mode MFA is required."""
    if required(settings):
        raise conflict("MFA_REQUIRED_BY_POLICY", "Two-step verification is required on this server.")
    user = ctx.user
    if verify(db, km, user, code) is None:
        audit.record(db, ctx, "MFA_FAILED", "user", user.id, None, {"stage": "disable"}, category="SECURITY")
        db.commit()
        raise AppError(400, "MFA_INVALID_CODE", "The code is not valid.")
    db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user.id))
    db.execute(delete(UserMfa).where(UserMfa.user_id == user.id))
    n = revoke_trusted(db, user.id)
    audit.record(db, ctx, "MFA_DISABLED", "user", user.id, {"mfa_enabled": True},
                 {"mfa_enabled": False, "trusted_browsers_revoked": n}, category="SECURITY")
