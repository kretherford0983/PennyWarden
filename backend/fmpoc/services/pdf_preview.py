"""2.0.0 build 13 (#230): pictures of the PDFs that the print screens show, for Safari.

Safari draws a PDF in an inline frame blank, so a Register User printing a check, cover letter or envelope saw an empty
preview. The endpoints that return such a PDF keep a copy here for a short time and name it in the `X-Preview-Token`
header; the screen can then ask for a PNG of that very PDF (`GET /api/pdf-preview/{token}`) instead of generating it
again - generating a check is recorded, so it must happen only once.

Copies are kept in memory only (one application process per data folder), for the user who made them, for
`TTL_SECONDS`, and at most `MAX_ENTRIES` / `MAX_TOTAL_BYTES` in all (oldest dropped first). A token is 192 random
bits and is useless to any other user.
"""
from __future__ import annotations

import secrets
import threading
import time
from collections import OrderedDict

TTL_SECONDS = 15 * 60
MAX_ENTRIES = 40
MAX_TOTAL_BYTES = 40 * 1024 * 1024
MAX_PDF_BYTES = 15 * 1024 * 1024          # a larger PDF gets no picture (the screen keeps the PDF itself)

_lock = threading.Lock()
_store: OrderedDict[str, tuple[int, float, bytes]] = OrderedDict()


def _expire(now: float) -> None:
    for token in [t for t, (_, at, _) in _store.items() if now - at > TTL_SECONDS]:
        del _store[token]
    while _store and (len(_store) > MAX_ENTRIES or sum(len(p) for _, _, p in _store.values()) > MAX_TOTAL_BYTES):
        _store.popitem(last=False)


def keep(user_id: int, pdf: bytes) -> str | None:
    """Keeps `pdf` for `user_id`; returns the token, or None when the PDF is too large to keep."""
    if len(pdf) > MAX_PDF_BYTES:
        return None
    token = secrets.token_urlsafe(24)
    with _lock:
        now = time.monotonic()
        _store[token] = (user_id, now, pdf)
        _expire(now)
    return token


def get(user_id: int, token: str) -> bytes | None:
    """The PDF kept under `token` for this user, or None (unknown, expired or another user's)."""
    with _lock:
        _expire(time.monotonic())
        entry = _store.get(token)
    if entry is None or entry[0] != user_id:
        return None
    return entry[2]


def clear() -> None:
    with _lock:
        _store.clear()
