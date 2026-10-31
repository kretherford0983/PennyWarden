"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

import logging
import logging.handlers
import re
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from . import VERSION
from .config import Settings, is_loopback, load_settings
from .db import make_engine, make_session_factory, upgrade_database
from .deps import enforce_csrf, enforce_maintenance
from .errors import install_handlers
from .routers import (admin, attachments, audit_log, auth, backup, bank_accounts, branding, budgets, checks, dashboard, donations,
                      envelopes,
                      entities, fiscal_years, fundraisers, pdf_preview, register, reminders, reports, system, updates,
                      demo, invoices, report_settings, signers, testing, users)
from .security import crypto
from .services import bootstrap
from .services.auth import LoginRateLimiter

log = logging.getLogger("fmpoc")
STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY = 6 * 1024 * 1024  # 5 MB attachment + multipart overhead
UPLOAD_PART_LIMIT = 21 * 1024 * 1024  # v1.4.1: one 20 MB part of a backup upload
_RESTORE_PART = re.compile(r"^/api/system/restore/uploads/[A-Za-z0-9_-]+$")
MAINTENANCE_OPEN = {"/api/health", "/api/system/status"}

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
       "font-src 'self'; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'none'; "
       "form-action 'self'; frame-ancestors 'none'")


class _Redact(logging.Filter):
    """Last-line defence: redact secret-looking key/value pairs from log records (BR-103)."""
    _re = re.compile(r"(?i)(password|passwd|secret|token|cookie|csrf|session|account_number|enc_key|fp_key)"
                     r"([\"']?\s*[:=]\s*)([^\s,;&\"']+)")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover
            return True
        red = self._re.sub(r"\1\2[REDACTED]", msg)
        if red != msg:
            record.msg, record.args = red, ()
        return True


def setup_logging(settings: Settings) -> None:
    root = logging.getLogger("fmpoc")
    root.setLevel(settings.log_level.upper())
    for h in [h for h in root.handlers if getattr(h, "_fmpoc", False)]:
        root.removeHandler(h)
        h.close()
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(settings.logs_dir / "fmpoc.log", maxBytes=5_000_000, backupCount=5,
                                              encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    fh.addFilter(_Redact())
    fh._fmpoc = True  # type: ignore[attr-defined]
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    sh.addFilter(_Redact())
    sh._fmpoc = True  # type: ignore[attr-defined]
    root.addHandler(fh)
    root.addHandler(sh)
    root.propagate = False


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, limit: int = MAX_BODY):
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        limit = self.limit
        if _RESTORE_PART.match(scope.get("path", "")) and scope.get("method") == "PUT":
            limit = UPLOAD_PART_LIMIT  # v1.4.1 CR-024/025: backup upload parts
        cl = headers.get(b"content-length")
        if cl is not None and cl.isdigit() and int(cl) > limit:
            resp = JSONResponse({"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body too large."}}, 413)
            return await resp(scope, receive, send)
        seen = 0

        async def limited():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    raise _TooLarge()
            return msg

        try:
            await self.app(scope, limited, send)
        except _TooLarge:
            resp = JSONResponse({"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body too large."}}, 413)
            await resp(scope, receive, send)


class _TooLarge(Exception):
    pass


def _frontend_build(static_dir: Path) -> str | None:
    """Name of the hashed entry script referenced by index.html (changes with every frontend build)."""
    try:
        m = re.search(r'src="/assets/(index-[A-Za-z0-9_-]+\.js)"', (static_dir / "index.html").read_text("utf-8"))
    except OSError:
        return None
    return m.group(1) if m else None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.ensure_dirs()
    setup_logging(settings)
    # 2.2.0 (#243): the demo starts from its pristine copy every time, and only on this computer (raises DemoError)
    from .services import demo as demo_svc
    is_demo = demo_svc.at_start(settings)
    upgrade_database(settings.database_url)
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app):
        # 1.9.0 (#62): the scheduled-backup thread runs while the web server runs (not in tests' TestClient,
        # which does not start the lifespan unless used as a context manager)
        from .services.scheduled_backup import Scheduler
        sched = Scheduler(app)
        sched.start()
        try:
            yield
        finally:
            sched.stop()

    app = FastAPI(title="PennyWarden", version=VERSION, debug=False,
                  docs_url=None, redoc_url=None, openapi_url=None,  # no dev consoles in production (BR-107)
                  dependencies=[Depends(enforce_csrf), Depends(enforce_maintenance)], lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.limiter = LoginRateLimiter(settings.login_max_failures, settings.login_lockout_seconds)
    app.state.insecure_transport_warning = (
        settings.mode == "server" and not is_loopback(settings.host) and settings.secure_cookies != "true"
    )
    if app.state.insecure_transport_warning:
        log.warning("SECURITY WARNING: server mode on a network interface without HTTPS configuration. Deploy behind "
                    "an HTTPS reverse proxy and set secure_cookies=true. Plain HTTP is NOT secure.")

    # Portable key: must match the initialized database (BR-085, AC-DEP-006).
    with session_factory() as db:
        initialized = bootstrap.is_initialized(db)
        ws = bootstrap.current_workspace(db) if initialized else None
    km = crypto.load_key(settings.secrets_dir)
    if initialized and (km is None or km.check_value != ws.key_check):
        raise RuntimeError("The portable encryption key in the application data 'secrets' directory is missing or "
                           "does not match this database. Restore the key file from the same data set.")
    app.state.key = km
    # 2.4.0 (#425): identical attachment files are stored once - merge any left from earlier versions or a restore
    from .services.attachments import merge_duplicate_files
    try:
        merge_duplicate_files(session_factory, settings)
    except Exception:  # noqa: BLE001 - never stops the application from starting; tried again at the next start
        log.exception("Merging identical attachment files failed; nothing was removed.")
    # v1.4.1 CR-023/024/025: background backup/restore jobs, restore uploads, maintenance mode during a restore
    from .services.backup import Jobs, cleanup_work
    app.state.jobs, app.state.uploads, app.state.maintenance = Jobs(), {}, None
    cleanup_work(settings)
    # 2.2.0 (#231): testing mode - server installs only (a local install ignores the setting, phase 2)
    from .services import testing as testing_svc
    app.state.testing_mode = testing_svc.configure(settings)
    app.state.demo = is_demo

    install_handlers(app)
    frontend_build = _frontend_build(settings.frontend_dir or STATIC_DIR)

    @app.middleware("http")
    async def security_and_logging(request, call_next):
        cid = uuid.uuid4().hex[:16]
        request.state.correlation_id = cid
        start = time.perf_counter()
        path = request.url.path
        if (app.state.maintenance and path.startswith("/api/") and path not in MAINTENANCE_OPEN
                and not path.startswith(("/api/system/restore/jobs/", "/api/system/reinitialize/jobs/"))):
            what = "reinitialize" if app.state.maintenance == "reinitialize" else "restore"   # 2.0.0 (#125)
            response = JSONResponse({"error": {"code": "MAINTENANCE", "message": f"A {what} is in progress. Try "
                                                                                  "again in a moment."}}, status_code=503)
        else:
            response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Content-Security-Policy", CSP)
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        h.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        h["X-Correlation-Id"] = cid
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
            if frontend_build:  # v1.5.0: lets an open page notice that the server was upgraded (api.ts)
                h["X-Frontend-Build"] = frontend_build
        if settings.hsts and request.url.scheme == "https":
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Path only - never query strings, bodies, cookies or headers.
        log.info("%s %s %s %.1fms cid=%s", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - start) * 1000, cid)
        return response

    app.add_middleware(BodyLimitMiddleware)

    for r in (system, backup, auth, users, audit_log, fiscal_years, budgets, entities, bank_accounts, register,
              attachments, dashboard, reports, fundraisers, reminders, updates, checks, donations, pdf_preview, admin,
              testing, demo, branding, envelopes, signers, report_settings, invoices):
        app.include_router(r.router)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_404(rest: str):
        return JSONResponse({"error": {"code": "NOT_FOUND", "message": "Not found."}}, status_code=404)

    static_dir = settings.frontend_dir or STATIC_DIR
    if (static_dir / "index.html").is_file():
        if (static_dir / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
        index = static_dir / "index.html"
        root_files = {p.name: p for p in static_dir.iterdir() if p.is_file()}

        @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        def spa(path: str):
            f = root_files.get(path)
            if f is not None:
                return FileResponse(f)
            return FileResponse(index, headers={"Cache-Control": "no-store"})  # v1.5.0: never serve a stale page

    return app
