from __future__ import annotations

import re
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, object_session

from .. import audit
from ..deps import PRE_CSRF_COOKIE, SESSION_COOKIE, Ctx, auth_ctx, get_ctx, get_db, pre_mfa_ctx, require
from ..errors import AppError
from ..permissions import permissions_for
from ..schemas import (ChangePasswordIn, ForgotCompleteIn, ForgotStartIn, LoginIn, MfaCodeIn, MfaEnrollStartIn, MfaOwnKeyIn,
                       MfaVerifyIn, PreferencesIn, SecurityQuestionsChangeIn, SecurityQuestionsIn, SetupPasswordIn)
from ..services import auth as svc
from ..services import mfa
from ..services import recovery
from ..services import report_prefs
from ..services import users as users_svc
from ..services.charts import charts_for
from ..services.dashboard_layout import encode as encode_layout
from ..services.dashboard_layout import is_customized, layout_for
from ..services.checkprint.service import module_enabled as checks_enabled
from ..services.donations import module_enabled as donations_enabled
from ..services.invoices import module_enabled as invoices_enabled   # 2.4.0 (#251)
from ..services.fundraisers import module_enabled
from ..services.register import DEFAULT_REGISTER_SORT

router = APIRouter(prefix="/api", tags=["auth"])
_PRE_CSRF_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")  # secrets.token_urlsafe(32)


def _secure(request: Request) -> bool:
    mode = request.app.state.settings.secure_cookies
    return mode == "true" or (mode == "auto" and request.url.scheme == "https")


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    s = request.app.state.settings
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", secure=_secure(request), path="/",
                        max_age=s.session_absolute_hours * 3600)


@router.get("/auth/csrf")
def pre_auth_csrf(request: Request, response: Response):
    """Double-submit token for the unauthenticated login/initialize forms.

    1.6.8 (#66, CodeQL "construction of a cookie using user-supplied input"): the cookie is only ever written with a
    token generated here. A browser that already has one gets it back in the answer and no cookie is set; a cookie
    that does not look like one of our tokens is replaced."""
    token = request.cookies.get(PRE_CSRF_COOKIE) or ""
    if not _PRE_CSRF_TOKEN.fullmatch(token):
        token = secrets.token_urlsafe(32)
        response.set_cookie(PRE_CSRF_COOKIE, token, httponly=False, samesite="strict", secure=_secure(request),
                            path="/")
    return {"csrf_token": token}


@router.get("/auth/password-policy")
def password_policy():
    """2.2.0 (#343): the password requirements for the checklist beside every new-password field (sign-in steps and
    the first-run wizard included, so no session is needed). Contains no user data."""
    from ..security.passwords import policy_requirements
    return policy_requirements()


def me_payload(ctx: Ctx) -> dict:
    u = ctx.user
    if ctx.mfa_pending:  # v1.4.1 CR-018: only what the two-step screen needs
        return {"id": u.id, "username": u.username, "email": u.email, "display_name": u.display_name,
                "security_domain": u.security_domain, "roles": [], "permissions": [], "theme": u.theme,
                "nav_collapsed": bool(u.nav_collapsed), "mfa_pending": ctx.mfa_pending,
                "csrf_token": ctx.session.csrf_token}
    return {"mfa_pending": None,"id": u.id, "username": u.username, "email": u.email, "display_name": u.display_name,
            "security_domain": u.security_domain, "roles": sorted(ctx.roles), "permissions": sorted(ctx.perms),
            "theme": u.theme, "nav_collapsed": bool(u.nav_collapsed), "dashboard_charts": charts_for(u),
            "dashboard_layout": layout_for(u), "dashboard_layout_customized": is_customized(u),
            "register_sort": u.register_sort or DEFAULT_REGISTER_SORT,   # 2.1.0 (#262)
            "name_order": u.name_order or "FIRST_LAST",                  # 2.2.0 (#316)
            "fundraiser_series_sort": u.fundraiser_series_sort or "desc",  # 2.2.0 (#351)
            "modules": {"fundraisers": module_enabled(object_session(u), u.workspace_id),  # v1.6.0 CR-033
                        "checks": checks_enabled(object_session(u), u.workspace_id),  # 2.0.0 (#156)
                        "donations": donations_enabled(object_session(u), u.workspace_id),  # 2.1.0 (#312)
                        "invoices": invoices_enabled(object_session(u), u.workspace_id)},  # 2.4.0 (#251)
            "sign_in_notices": recovery.sign_in_notices(u),  # 1.8.0 (#113)
            "first_name": u.first_name, "last_name": u.last_name,   # 2.0.0 (#134)
            # 2.0.0 (#134): an Administrator completes the missing names before continuing
            "names_needed": len(users_svc.names_needed(object_session(u), u.workspace_id))
            if "users.manage" in ctx.perms else 0,
            "csrf_token": ctx.session.csrf_token}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db), ctx: Ctx = Depends(get_ctx)):
    s = request.app.state.settings
    user, token, sess = svc.login(db, s, request.app.state.limiter, ctx, body.username, body.password,
                                  request.cookies.get(SESSION_COOKIE), request.cookies.get(mfa.TRUST_COOKIE))
    db.commit()
    set_session_cookie(request, response, token)
    response.delete_cookie(PRE_CSRF_COOKIE, path="/")
    ctx.session, ctx.mfa_pending = sess, sess.mfa_pending
    if not sess.mfa_pending:
        ctx.roles = user.role_codes
        ctx.perms = permissions_for(ctx.roles)
    return me_payload(ctx)


@router.post("/auth/logout")
def logout(response: Response, db: Session = Depends(get_db), ctx: Ctx = Depends(pre_mfa_ctx)):
    svc.logout(db, ctx)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(ctx: Ctx = Depends(pre_mfa_ctx)):
    return me_payload(ctx)


# ------------------------------------------------------------------ v1.4.1 CR-018: two-step verification
def _set_trusted_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(mfa.TRUST_COOKIE, token, httponly=True, samesite="strict", secure=_secure(request), path="/",
                        max_age=mfa.TRUST_DAYS * 86400)


def _finish(request: Request, response: Response, db: Session, ctx: Ctx, how: str, trust: bool) -> dict:
    s = request.app.state.settings
    token, _sess = svc.complete_mfa(db, s, ctx, how)
    if trust:
        t, _exp = mfa.issue_trusted(db, ctx, ctx.user, request.headers.get("user-agent"))
        _set_trusted_cookie(request, response, t)
    db.commit()
    set_session_cookie(request, response, token)
    if not ctx.mfa_pending:   # 1.8.0 (#113): a setup step may still follow
        ctx.roles = ctx.user.role_codes
        ctx.perms = permissions_for(ctx.roles)
    return me_payload(ctx)


def _mfa_limited(request: Request, ctx: Ctx):
    keys = (f"mfa:{ctx.user.id}", f"mfaip:{ctx.ip}")
    lim = request.app.state.limiter
    if lim.blocked(*keys):
        raise AppError(429, "RATE_LIMITED", "Too many incorrect codes. Try again later.")
    return lim, keys


@router.post("/auth/mfa/verify")
def mfa_verify(body: MfaVerifyIn, request: Request, response: Response, db: Session = Depends(get_db),
               ctx: Ctx = Depends(pre_mfa_ctx)):
    if ctx.mfa_pending != "VERIFY":
        raise AppError(409, "MFA_NOT_PENDING", "No two-step verification is waiting for this session.")
    lim, keys = _mfa_limited(request, ctx)
    used = mfa.verify(db, request.app.state.key, ctx.user, body.code)
    if used is None:
        lim.fail(*keys)
        audit.record(db, ctx, "MFA_FAILED", "user", ctx.user.id, None, {"stage": "sign_in"}, category="SECURITY")
        db.commit()
        raise AppError(400, "MFA_INVALID_CODE", "The code is not valid. Enter the current 6-digit code from your "
                                                "authenticator app, or a recovery code.")
    lim.reset(*keys)
    if used == "recovery":
        audit.record(db, ctx, "MFA_RECOVERY_CODE_USED", "user", ctx.user.id, None, {"stage": "sign_in"},
                     category="SECURITY")
    return _finish(request, response, db, ctx, "recovery_code" if used == "recovery" else "totp", body.trust_browser)


@router.post("/auth/mfa/enroll/start")
def mfa_enroll_start(body: MfaEnrollStartIn, request: Request, db: Session = Depends(get_db),
                     ctx: Ctx = Depends(pre_mfa_ctx)):
    """First setup (at sign-in when required, or from My Account) or change of authenticator (current code needed)."""
    if ctx.mfa_pending == "VERIFY":
        raise AppError(401, "MFA_REQUIRED", "Complete two-step verification first.")
    lim, keys = _mfa_limited(request, ctx)
    try:
        return mfa.start_enrollment(db, request.app.state.key, ctx, body.current_code)
    except AppError as e:
        if e.code == "MFA_INVALID_CODE":
            lim.fail(*keys)
        raise


@router.post("/auth/mfa/enroll/own-key")
def mfa_enroll_own_key(body: MfaOwnKeyIn, request: Request, db: Session = Depends(get_db),
                       ctx: Ctx = Depends(pre_mfa_ctx)):
    """2.2.0 (#327): use your own authenticator key for the setup in progress (or a newly generated key again). The key
    is saved only by /enroll/confirm with a current code made with it; it is never logged, audited or echoed."""
    if ctx.mfa_pending == "VERIFY":
        raise AppError(401, "MFA_REQUIRED", "Complete two-step verification first.")
    return mfa.use_own_key(db, request.app.state.key, ctx, body.own_key)


@router.post("/auth/mfa/enroll/confirm")
def mfa_enroll_confirm(body: MfaCodeIn, request: Request, response: Response, db: Session = Depends(get_db),
                       ctx: Ctx = Depends(pre_mfa_ctx)):
    if ctx.mfa_pending == "VERIFY":
        raise AppError(401, "MFA_REQUIRED", "Complete two-step verification first.")
    lim, keys = _mfa_limited(request, ctx)
    try:
        codes = mfa.confirm_enrollment(db, request.app.state.key, ctx, body.code)
    except AppError as e:
        if e.code == "MFA_INVALID_CODE":
            lim.fail(*keys)
        raise
    lim.reset(*keys)
    if ctx.mfa_pending == "ENROLL":
        me = _finish(request, response, db, ctx, "enrolled", False)
    else:
        db.commit()
        me = me_payload(ctx)
    return {"recovery_codes": codes, "me": me}


@router.get("/me/mfa")
def mfa_status(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)):
    return mfa.status(db, request.app.state.settings, ctx.user)


@router.post("/me/mfa/trusted-browsers/{device_id}/revoke")
def mfa_revoke_browser(device_id: int, request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)):
    n = mfa.revoke_trusted(db, ctx.user.id, device_id)
    if n:
        audit.record(db, ctx, "MFA_TRUSTED_BROWSER_REVOKED", "user", ctx.user.id, None,
                     {"trusted_browser_id": device_id}, category="SECURITY")
    db.commit()
    return mfa.status(db, request.app.state.settings, ctx.user)


@router.post("/me/mfa/trusted-browsers/revoke-all")
def mfa_revoke_all(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)):
    n = mfa.revoke_trusted(db, ctx.user.id)
    audit.record(db, ctx, "MFA_TRUSTED_BROWSER_REVOKED", "user", ctx.user.id, None, {"all": True, "count": n},
                 category="SECURITY")
    db.commit()
    return mfa.status(db, request.app.state.settings, ctx.user)


@router.post("/me/mfa/disable")
def mfa_disable(body: MfaCodeIn, request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)):
    mfa.disable(db, request.app.state.key, request.app.state.settings, ctx, body.code)
    db.commit()
    return mfa.status(db, request.app.state.settings, ctx.user)


@router.post("/auth/change-password")
def change_password(body: ChangePasswordIn, db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)):
    svc.change_own_password(db, ctx, body.current_password, body.new_password, body.new_password_confirmation)
    return {"ok": True, "other_sessions_revoked": True}


@router.put("/me/preferences")
def preferences(body: PreferencesIn, db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)):
    if body.theme is not None:
        ctx.user.theme = body.theme  # persisted per user (BR-UI-THEME-002)
    if body.nav_collapsed is not None:
        ctx.user.nav_collapsed = body.nav_collapsed  # v1.3 CR-014
    if body.dashboard_charts is not None:  # v1.4.1 CR-020
        ctx.user.dashboard_charts = ",".join(dict.fromkeys(body.dashboard_charts))
    if body.reset_register_sort:  # 2.1.0 (#262)
        ctx.user.register_sort = None
    elif body.register_sort is not None:
        ctx.user.register_sort = None if body.register_sort == DEFAULT_REGISTER_SORT else body.register_sort
    if body.name_order is not None:  # 2.2.0 (#316)
        ctx.user.name_order = None if body.name_order == "FIRST_LAST" else body.name_order
    if body.fundraiser_series_sort is not None:  # 2.2.0 (#351): the default (newest first) is stored as none
        ctx.user.fundraiser_series_sort = None if body.fundraiser_series_sort == "desc" else body.fundraiser_series_sort
    if body.reset_dashboard_layout:  # v1.5.0 CR-031
        ctx.user.dashboard_layout = None
    elif body.dashboard_layout is not None:
        ctx.user.dashboard_layout = encode_layout(body.dashboard_layout)
    db.commit()
    return {"theme": ctx.user.theme, "nav_collapsed": bool(ctx.user.nav_collapsed),
            "dashboard_charts": charts_for(ctx.user), "dashboard_layout": layout_for(ctx.user),
            "dashboard_layout_customized": is_customized(ctx.user),
            "register_sort": ctx.user.register_sort or DEFAULT_REGISTER_SORT,
            "fundraiser_series_sort": ctx.user.fundraiser_series_sort or "desc"}


# ------------------------------------------------------------------ 2.3.0 (#375): the Reports screen's memory
class ReportRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report: str = Field(max_length=40)
    params: dict[str, Any] | None = Field(default=None, max_length=report_prefs.MAX_PARAMS)
    label: str | None = Field(default=None, max_length=report_prefs.MAX_LABEL + 40)


@router.get("/me/report-preferences")
def report_preferences(ctx: Ctx = Depends(auth_ctx)):
    """Recently run and each report's last options for the signed-in user (parameters only)."""
    return report_prefs.get(ctx.user)


@router.post("/me/report-runs")
def report_run(body: ReportRunIn, db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)):
    out = report_prefs.record_run(db, ctx.user, body.report, body.params, body.label)
    db.commit()
    return out


# ------------------------------------------------------------------ 1.8.0 (#113): forgotten password
@router.get("/auth/security-questions")
def question_catalog():
    """The fixed list of security questions."""
    return recovery.catalog()


def _gate(ctx: Ctx, step: str) -> None:
    if ctx.mfa_pending != step:
        raise AppError(409, "STEP_NOT_PENDING", "This step is not waiting for this session.")


@router.post("/auth/setup/password")
def setup_password(body: SetupPasswordIn, request: Request, response: Response, db: Session = Depends(get_db),
                   ctx: Ctx = Depends(pre_mfa_ctx)):
    """After the host `reset-password`: the temporary password is replaced before anything else."""
    _gate(ctx, "PASSWORD")
    svc.set_new_password(db, ctx, body.new_password, body.new_password_confirmation)
    return _finish(request, response, db, ctx, "password_changed", False)


@router.post("/auth/setup/security-questions")
def setup_questions(body: SecurityQuestionsIn, request: Request, response: Response, db: Session = Depends(get_db),
                    ctx: Ctx = Depends(pre_mfa_ctx)):
    """First sign-in (or the next one after the upgrade / an Administrator's reset): choose and answer 3 questions."""
    _gate(ctx, "QUESTIONS")
    recovery.set_questions(db, ctx, ctx.user, body.questions, "sign_in")
    return _finish(request, response, db, ctx, "questions_set", False)


@router.get("/me/security-questions")
def my_questions(db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)):
    return recovery.my_questions(db, ctx.user)


@router.put("/me/security-questions")
def change_questions(body: SecurityQuestionsChangeIn, db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)):
    """My account: new questions and answers (the current password is needed)."""
    svc.check_current_password(db, ctx, body.current_password, "security_questions")
    recovery.set_questions(db, ctx, ctx.user, body.questions, "my_account")
    db.commit()
    return recovery.my_questions(db, ctx.user)


@router.post("/me/sign-in-notices/dismiss")
def dismiss_notices(db: Session = Depends(get_db), ctx: Ctx = Depends(auth_ctx)):
    recovery.dismiss_sign_in_notices(ctx.user)
    db.commit()
    return {"sign_in_notices": []}


@router.post("/auth/forgot/start")
def forgot_start(body: ForgotStartIn, request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(get_ctx)):
    """One of the user's questions, chosen at random (the same one until a failed attempt or a timeout). An unknown
    username gets a question too, so the answer never tells whether an account exists."""
    s = request.app.state.settings
    return recovery.forgot_start(db, s, request.app.state.limiter, ctx, body.username)


@router.post("/auth/forgot/complete")
def forgot_complete(body: ForgotCompleteIn, request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(get_ctx)):
    s = request.app.state.settings
    return recovery.forgot_complete(db, s, request.app.state.key, request.app.state.limiter, ctx, body)


@router.get("/security-notices")
def security_notices(db: Session = Depends(get_db), ctx: Ctx = Depends(require("users.manage"))):
    """Administrators: locks of an hour or more, accounts disabled after failed attempts, self-service resets."""
    return recovery.admin_notices(db, ctx.workspace_id)


@router.post("/security-notices/{notice_id}/dismiss")
def dismiss_security_notice(notice_id: int, db: Session = Depends(get_db), ctx: Ctx = Depends(require("users.manage"))):
    recovery.dismiss_admin_notice(db, ctx, notice_id)
    db.commit()
    return recovery.admin_notices(db, ctx.workspace_id)
