"""Argon2id password hashing and password policy (BR-089)."""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ph = PasswordHasher()  # argon2id with library-recommended parameters
_DUMMY = _ph.hash("dummy-password-for-timing-equalisation")

MIN_LENGTH = 12
MAX_LENGTH = 128


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw_hash: str | None, pw: str) -> bool:
    try:
        return _ph.verify(pw_hash or _DUMMY, pw) and pw_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def policy_requirements() -> dict:
    """2.2.0 (#343): the password requirements as the screens list them, so the browser shows a checklist without a
    copy of the rules of its own. The numbers and texts come from here; the browser only knows how to tick each `id`
    it recognises (an unknown one stays unticked and is checked when the password is saved). `applies`: `always`, or
    only where that comparison makes sense - `change` (a current password is typed), `temporary` (after a temporary
    password; only the server can compare), `confirm` (a confirmation field exists). `policy_errors` below stays the
    authority."""
    return {"min_length": MIN_LENGTH, "max_length": MAX_LENGTH,
            "requirements": [
                {"id": "length", "applies": "always",
                 "text": f"At least {MIN_LENGTH} characters (at most {MAX_LENGTH})"},
                {"id": "letter_digit", "applies": "always", "text": "At least one letter and one digit"},
                {"id": "not_username", "applies": "always", "text": "Not the same as the username"},
                {"id": "differs_current", "applies": "change", "text": "Different from the current password"},
                {"id": "differs_temporary", "applies": "temporary", "server_only": True,
                 "text": "Different from the temporary password (checked when you save)"},
                {"id": "confirm_matches", "applies": "confirm",
                 "text": "New password and Confirm new password are the same"},
            ]}


def policy_errors(pw: str, username: str | None = None) -> list[str]:
    errs: list[str] = []
    if not isinstance(pw, str):
        return ["Password is required."]
    if len(pw) < MIN_LENGTH:
        errs.append(f"Password must be at least {MIN_LENGTH} characters.")
    if len(pw) > MAX_LENGTH:
        errs.append(f"Password must be at most {MAX_LENGTH} characters.")
    if not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
        errs.append("Password must contain at least one letter and one digit.")
    if username and pw.strip().lower() == username.strip().lower():
        errs.append("Password must not equal the username.")
    return errs
