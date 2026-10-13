from __future__ import annotations

import secrets
import threading

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from .. import VERSION
from ..deps import PRE_CSRF_COOKIE, SESSION_COOKIE, Ctx, auth_ctx, get_ctx, get_db
from ..config import build_info
from ..errors import AppError
from ..legal import legal_file, legal_payload
from ..permissions import ADMINISTRATOR
from ..schemas import InitializeIn
from ..security.passwords import policy_errors
from ..services import auth as auth_svc
from ..services import bootstrap
from ..services.mfa import required as mfa_required
from .auth import set_session_cookie

router = APIRouter(prefix="/api", tags=["system"])
_init_lock = threading.Lock()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/system/status")
def status(request: Request, response: Response, db: Session = Depends(get_db)):
    if request.app.state.maintenance:  # v1.4.1: no database access while a restore swaps the data
        return {"initialized": None, "workspace_name": None, "version": VERSION, "maintenance": "restore",
                "mode": request.app.state.settings.mode, "insecure_transport_warning": False, **legal_payload()}
    initialized = bootstrap.is_initialized(db)
    ws = bootstrap.current_workspace(db) if initialized else None
    s = request.app.state.settings
    from ..services.maintenance import state as maintenance_state   # 2.0.0 (#130): shown on the sign-in page too
    return {"initialized": initialized, "workspace_name": ws.name if ws else None, "version": VERSION,
            "maintenance_mode": maintenance_state(ws),
            "maintenance": request.app.state.maintenance,
            "mode": s.mode, "insecure_transport_warning": request.app.state.insecure_transport_warning,
            **legal_payload()}


@router.post("/system/initialize")
def initialize(body: InitializeIn, request: Request, response: Response, db: Session = Depends(get_db),
               ctx: Ctx = Depends(get_ctx)):
    if body.password != body.password_confirmation:
        raise AppError(422, "VALIDATION_ERROR", "Password and confirmation do not match.",
                       errors=[{"field": "password_confirmation", "message": "Passwords do not match."}])
    errs = policy_errors(body.password, body.admin_username)
    if errs:
        raise AppError(422, "PASSWORD_POLICY", " ".join(errs), errors=[{"field": "password", "message": e} for e in errs])
    settings = request.app.state.settings
    with _init_lock:
        try:
            admin = bootstrap.initialize(db, settings, ctx, workspace_name=body.workspace_name,
                                         username=body.admin_username, email=body.admin_email, password=body.password)
            # v1.4.1 CR-018: in server mode the first Administrator sets up MFA before using the application
            # 1.8.0 (#113): ... and chooses the security questions (after MFA when it is required)
            token, sess = auth_svc.create_session(db, settings, admin, "ENROLL" if mfa_required(settings) else "QUESTIONS",
                                                  ctx.ip)
            db.commit()
        except Exception:
            db.rollback()
            raise
    from ..security import crypto
    request.app.state.key = crypto.load_key(settings.secrets_dir)
    set_session_cookie(request, response, token)
    response.delete_cookie(PRE_CSRF_COOKIE, path="/")
    return {"initialized": True, "username": admin.username}


def version_payload(request: Request) -> dict:
    s = request.app.state.settings
    return {"version": VERSION, "build": build_info(), "mode": s.mode, **legal_payload()}


@router.get("/system/legal/{doc}", response_class=PlainTextResponse)
def legal(doc: str):
    """v1.5.0: the license (AGPL-3.0) and third-party notices shipped with this build - public, like the source."""
    p = legal_file(doc)
    if p is None:
        raise AppError(404, "NOT_FOUND", "Not available in this build.")
    return PlainTextResponse(p.read_text(encoding="utf-8", errors="replace"), headers={"Cache-Control": "no-cache"})


@router.get("/system/version")
def version(request: Request, ctx: Ctx = Depends(auth_ctx)):
    """v1.4 CR-022: version/build for every signed-in user (My Account → About); no network details."""
    return version_payload(request)


@router.get("/system/about")
def about(request: Request, ctx: Ctx = Depends(auth_ctx)):
    s = request.app.state.settings
    admin = ADMINISTRATOR in ctx.roles
    return {**version_payload(request), "bind_host": s.host if admin else None, "port": s.port if admin else None,
            # v1.4.1 CR-023: backup/restore is built in (supersedes BR-092)
            "backup_notice": "Create backups regularly (Backup / Restore below) and keep them off this machine, "
                             "together with their passphrase. A backup contains the database, all attachments and "
                             "the encryption key; config.toml is not included.",
            "restore_max_mb": s.restore_max_mb if ADMINISTRATOR in ctx.roles else None,
            "insecure_transport_warning": request.app.state.insecure_transport_warning}


__all__ = ["SESSION_COOKIE", "secrets"]
