"""v1.4.1 CR-023 / CR-024 / CR-025: Backup / Restore endpoints (System/About and the initialization wizard)."""
from __future__ import annotations

import logging
import secrets
import shutil
import threading
import time
from types import SimpleNamespace

from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from fastapi.responses import FileResponse
from sqlalchemy import update
from sqlalchemy.orm import Session

from .. import audit
from ..db import alembic_config, make_engine, make_session_factory, upgrade_database
from ..deps import Ctx, get_ctx, get_db, require
from ..errors import AppError, validation
from ..models import AuthSession, TrustedDevice, utcnow
from ..schemas import BackupCreateIn, BackupFolderTestIn, BackupScheduleIn, RestoreStartIn, RestoreUploadIn
from ..security import crypto
from ..security.passwords import verify_password
from ..services import backup as bk
from ..services import bootstrap
from ..services import restore_report
from ..services import scheduled_backup as sched
from ..services import server_recovery
from ..services.auth import LoginRateLimiter

log = logging.getLogger("fmpoc")
router = APIRouter(prefix="/api/system", tags=["backup"])


def _check_password(request: Request, db: Session, ctx: Ctx, password: str, action: str) -> None:
    lim = request.app.state.limiter
    keys = (f"u:{ctx.user.username_normalized}", f"ip:{ctx.ip}")
    if lim.blocked(*keys):
        raise AppError(429, "RATE_LIMITED", "Too many failed attempts. Try again later.")
    if not verify_password(ctx.user.password_hash, password or ""):
        lim.fail(*keys)
        audit.record(db, ctx, f"{action}_DENIED", "workspace", ctx.workspace_id, None,
                     {"reason": "incorrect_password"}, category="SECURITY")
        db.commit()
        raise AppError(400, "INCORRECT_PASSWORD", "Your password is incorrect.")


def _passphrase_ok(p: str, confirm: str | None = None) -> None:
    if len(p or "") < bk.MIN_PASSPHRASE:
        raise validation(f"The backup passphrase must be at least {bk.MIN_PASSPHRASE} characters.", "passphrase")
    if confirm is not None and p != confirm:
        raise validation("The passphrase and its confirmation do not match.", "passphrase_confirmation")


# ------------------------------------------------------------------ backup (CR-023)
@router.post("/backups", status_code=202)
def start_backup(body: BackupCreateIn, request: Request, db: Session = Depends(get_db),
                 ctx: Ctx = Depends(require("users.manage"))):
    _passphrase_ok(body.passphrase, body.passphrase_confirmation)
    _check_password(request, db, ctx, body.password, "BACKUP")
    app = request.app
    if app.state.jobs.running():
        raise AppError(409, "JOB_RUNNING", "A backup or restore is already running.")
    settings = app.state.settings
    bk.cleanup_work(settings)
    job = app.state.jobs.new("backup")
    audit.record(db, ctx, "BACKUP_STARTED", "workspace", ctx.workspace_id, None, {"job": job.id[:8]},
                 category="SECURITY")
    db.commit()
    from ..services.users import label as user_label   # 2.0.0 (#134): "First Last - username"
    actor = {"user_id": ctx.user.id, "username": ctx.user.username, "label": user_label(ctx.user),
             "workspace_id": ctx.workspace_id,
             "ip": ctx.ip, "cid": ctx.correlation_id}

    def run():
        try:
            path, name, manifest = bk.create_backup(settings, body.passphrase, job)
            rec = None
            if body.recoverable:   # 2.0.0 (#124): the passphrase locked with the server key, bound to this file
                job.advance("Saving the server's recovery file")
                rec = server_recovery.write_recovery(settings, path, name, body.passphrase,
                                                     actor.get("label") or actor["username"])
            job.result = {"filename": name, "size": path.stat().st_size, "created_at": manifest["created_at"],
                          "counts": manifest["counts"], "files": len(manifest["files"]), "_path": str(path),
                          "recoverable": rec is not None}
            with app.state.session_factory() as s:
                audit.record(s, _Actor(actor), "BACKUP_CREATED", "workspace", actor["workspace_id"], None,
                             {"filename": name, "size": job.result["size"], "counts": manifest["counts"],
                              "app_version": manifest["app_version"], "recoverable": rec is not None,
                              **({"recovery_id": rec["id"]} if rec else {})}, category="SECURITY")
                s.commit()
            job.advance("")
            job.state = "done"
        except Exception as e:  # pragma: no cover - reported to the admin
            log.exception("backup failed")
            job.state, job.error = "failed", f"The backup could not be created ({type(e).__name__})."

    threading.Thread(target=run, name="fmpoc-backup", daemon=True).start()
    return job.out()


def _Actor(a: dict) -> SimpleNamespace:
    """Audit context for work finished in a background thread."""
    user = SimpleNamespace(id=a.get("user_id"), username=a.get("username")) if a.get("username") else None
    return SimpleNamespace(workspace_id=a.get("workspace_id"), correlation_id=a.get("cid"), ip=a.get("ip"), user=user)


@router.get("/backups/{job_id}")
def backup_status(job_id: str, request: Request, ctx: Ctx = Depends(require("users.manage"))):
    job = request.app.state.jobs.get(job_id)
    if job is None or job.kind != "backup":
        raise AppError(404, "NOT_FOUND", "Backup not found (finished backups are kept for one hour).")
    return job.out()


@router.get("/backups/{job_id}/download")
def backup_download(job_id: str, request: Request, ctx: Ctx = Depends(require("users.manage"))):
    job = request.app.state.jobs.get(job_id)
    path = job.result.get("_path") if job and job.kind == "backup" and job.state == "done" else None
    if not path:
        raise AppError(404, "NOT_FOUND", "Backup not found (finished backups are kept for one hour).")
    from pathlib import Path
    if not Path(path).is_file():
        raise AppError(404, "NOT_FOUND", "The backup file is no longer available. Create a new backup.")
    return FileResponse(path, media_type="application/octet-stream", filename=job.result["filename"],
                        headers={"Cache-Control": "private, no-store"})


# ------------------------------------------------------------------ 1.9.0 (#62) scheduled automatic backups
@router.get("/backup-schedule")
def schedule_get(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(require("users.manage"))):
    return sched.out(db, request.app.state.settings, ctx.workspace_id)


@router.put("/backup-schedule")
def schedule_put(body: BackupScheduleIn, request: Request, db: Session = Depends(get_db),
                 ctx: Ctx = Depends(require("users.manage"))):
    if body.passphrase:   # setting or changing the passphrase needs the Administrator's own password
        _check_password(request, db, ctx, body.password or "", "BACKUP_PASSPHRASE")
    sched.save(db, request.app.state.settings, ctx, body)
    db.commit()
    return sched.out(db, request.app.state.settings, ctx.workspace_id)


@router.post("/backup-schedule/test")
def schedule_test(body: BackupFolderTestIn, request: Request, ctx: Ctx = Depends(require("users.manage"))):
    """Writes and removes a small file in the folder."""
    return sched.test_folder(request.app.state.settings, body.destination)


@router.post("/backup-schedule/run", status_code=202)
def schedule_run_now(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(require("users.manage"))):
    sched.run_now_async(request.app, ctx)
    return {"started": True}


@router.get("/backup-schedule/alert")
def schedule_alert(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(require("users.manage"))):
    """The banner shown to Administrators while the last scheduled backup has failed, and (2.0.0 #126) when no
    backup has been made for the set number of days."""
    from ..services.admin_settings import backup_age
    age = backup_age(db, ctx.workspace_id)
    from ..services.diagnostics import disk, low_disk   # 2.0.0 (#129): low disk space, in the same banner
    d = disk(request.app.state.settings)
    low = low_disk(d)
    return {**sched.alert(db, ctx.workspace_id), "stale": age["stale"], "stale_message": age.get("message"),
            "low_disk": low, "low_disk_message": "Low disk space where PennyWarden keeps its data: "
            f"{d['free'] / 1024 ** 3:.1f} GB free. See System/About → Health." if low else None}


# ------------------------------------------------------------------ restore (CR-024 wizard / CR-025 System/About)
def _restore_actor(request: Request, db: Session) -> tuple[Ctx, bool]:
    """Returns (ctx, initialized). Before initialization anyone may restore (like running the wizard); afterwards
    only an Administrator."""
    ctx = get_ctx(request, db)
    initialized = bootstrap.is_initialized(db)
    if initialized:
        if ctx.user is None or ctx.mfa_pending:
            raise AppError(401, "UNAUTHENTICATED", "Authentication required.")
        ctx.require("users.manage")
    return ctx, initialized


def _upload(request: Request, upload_id: str) -> dict:
    up = request.app.state.uploads.get(upload_id)
    if up is None:
        raise AppError(404, "NOT_FOUND", "Upload not found. Start the restore again.")
    return up


@router.post("/restore/uploads", status_code=201)
def restore_upload_start(body: RestoreUploadIn, request: Request, db: Session = Depends(get_db)):
    ctx, initialized = _restore_actor(request, db)
    app = request.app
    settings = app.state.settings
    if body.size > settings.restore_max_mb * 1024 * 1024:
        raise validation(f"The backup is larger than the allowed {settings.restore_max_mb} MB (setting "
                         "restore_max_mb).", "size")
    if app.state.jobs.running():
        raise AppError(409, "JOB_RUNNING", "A backup or restore is already running.")
    for old in list(app.state.uploads.values()):  # one upload at a time
        shutil.rmtree(old["dir"], ignore_errors=True)
    app.state.uploads.clear()
    bk.cleanup_work(settings)
    uid = secrets.token_urlsafe(24)
    d = bk.work_dir(settings) / f"upload-{secrets.token_hex(8)}"
    d.mkdir()
    (d / "backup.fmbak").write_bytes(b"")
    app.state.uploads[uid] = {"dir": d, "path": d / "backup.fmbak", "size": body.size, "received": 0,
                              "user_id": ctx.user.id if ctx.user else None, "created": time.time(),
                              "filename": body.filename[:200]}
    return {"upload_id": uid, "chunk_size": bk.UPLOAD_CHUNK_MAX, "received": 0}


@router.get("/restore/uploads/{upload_id}")
def restore_upload_status(upload_id: str, request: Request, db: Session = Depends(get_db)):
    _restore_actor(request, db)
    up = _upload(request, upload_id)
    return {"upload_id": upload_id, "size": up["size"], "received": up["received"]}


@router.put("/restore/uploads/{upload_id}")
async def restore_upload_chunk(upload_id: str, request: Request, offset: int = Query(..., ge=0),
                               db: Session = Depends(get_db)):
    _restore_actor(request, db)
    up = _upload(request, upload_id)
    if offset > up["received"]:
        raise AppError(409, "UPLOAD_OFFSET", "Parts arrived out of order.", received=up["received"])
    data = bytearray()
    async for part in request.stream():
        data += part
        if len(data) > bk.UPLOAD_CHUNK_MAX:
            raise AppError(413, "PAYLOAD_TOO_LARGE", "Upload part too large.")
    end = offset + len(data)
    if end > up["size"]:
        raise AppError(422, "UPLOAD_TOO_LONG", "More data than the announced file size.")
    if end > up["received"]:  # a retried part that was already stored is accepted without writing it twice
        with open(up["path"], "r+b") as f:
            f.seek(offset)
            f.write(bytes(data))
        up["received"] = end
    return {"received": up["received"], "size": up["size"]}


@router.post("/restore/uploads/{upload_id}/start", status_code=202)
def restore_start(upload_id: str, body: RestoreStartIn, request: Request, db: Session = Depends(get_db)):
    ctx, initialized = _restore_actor(request, db)
    up = _upload(request, upload_id)
    if up["received"] != up["size"]:
        raise AppError(409, "UPLOAD_INCOMPLETE", "The upload is not complete yet.", received=up["received"])
    if initialized:
        if (body.confirm or "").strip() != "RESTORE":
            raise validation('Type RESTORE to confirm that the current data will be replaced.', "confirm")
        _check_password(request, db, ctx, body.password or "", "RESTORE")
    if not body.passphrase:
        raise validation("Enter the backup passphrase.", "passphrase")
    app = request.app
    if app.state.jobs.running():
        raise AppError(409, "JOB_RUNNING", "A backup or restore is already running.")
    job = app.state.jobs.new("restore")
    if initialized:
        audit.record(db, ctx, "RESTORE_STARTED", "workspace", ctx.workspace_id, None,
                     {"filename": up["filename"], "size": up["size"]}, category="SECURITY")
        db.commit()
    actor = {"username": ctx.user.username if ctx.user else None, "ip": ctx.ip, "cid": ctx.correlation_id,
             "via": "system_about" if initialized else "initialization_wizard"}
    app.state.uploads.pop(upload_id, None)
    threading.Thread(target=run_restore, args=(app, job, up, body.passphrase, actor), name="fmpoc-restore",
                     daemon=True).start()
    return job.out()


@router.get("/restore/jobs/{job_id}")
def restore_status(job_id: str, request: Request):
    """Polled during the restore (no session needed: sessions are revoked by the restore; the random job id is the
    capability)."""
    job = request.app.state.jobs.get(job_id)
    if job is None or job.kind != "restore":
        raise AppError(404, "NOT_FOUND", "Restore not found.")
    return job.out()


# ------------------------------------------------------------------ the restore itself (background thread)
def _known_revisions(url: str) -> set[str]:
    return {r.revision for r in ScriptDirectory.from_config(alembic_config(url)).walk_revisions()}


def _write_report(settings, data, manifest: dict, job) -> dict:
    """2.0.0 (#124): the re-entry report of what the restore replaces (before the swap; the database is closed)."""
    if not settings.database_path.is_file():
        return {}
    job.advance("Writing the re-entry report")
    engine = make_engine(settings.database_url)
    try:
        with make_session_factory(engine)() as s:
            ws = bootstrap.current_workspace(s) if bootstrap.is_initialized(s) else None
            if ws is None:
                return {}
            return restore_report.build(s, ws.id, data / "database" / bk.DB_NAME, manifest.get("created_at"),
                                        settings.data_dir / restore_report.REPORT_DIR)
    finally:
        engine.dispose()


def run_restore(app, job, up: dict, passphrase: str, actor: dict) -> None:
    settings = app.state.settings
    work = up["dir"]
    swapped = False
    try:
        manifest = bk.unpack(up["path"], passphrase, work / "unpacked", job)
        try:
            up["path"].unlink()
        except OSError:
            pass
        job.advance("Checking versions and the encryption key")
        facts = bk.check_compatible(work / "unpacked" / "data", _known_revisions(settings.database_url))
        job.advance("Pausing the application")
        app.state.maintenance = "restore"
        time.sleep(0.5)  # let requests in flight finish
        app.state.engine.dispose()
        report = _write_report(settings, work / "unpacked" / "data", manifest, job)   # 2.0.0 (#124)
        job.advance("Saving a safety copy of the current data")
        bk.swap_in(settings, work / "unpacked" / "data")
        swapped = True
        job.advance("Updating the database to this version")
        upgrade_database(settings.database_url)
        job.advance("Restarting the application")
        engine = make_engine(settings.database_url)
        factory = make_session_factory(engine)
        with factory() as s:
            now = utcnow()
            s.execute(update(AuthSession).where(AuthSession.revoked_at.is_(None)).values(revoked_at=now))
            s.execute(update(TrustedDevice).where(TrustedDevice.revoked_at.is_(None)).values(revoked_at=now))
            ws = bootstrap.current_workspace(s)
            # the restoring user belongs to the replaced data: recorded by name only, no user id
            ctx = SimpleNamespace(workspace_id=ws.id if ws else None, correlation_id=actor.get("cid"),
                                  ip=actor.get("ip"), user=None)
            audit.record(s, ctx, "SYSTEM_RESTORED", "workspace", ws.id if ws else None, None,
                         {"restored_by": actor.get("username") or "initialization wizard", "via": actor["via"],
                          "backup_created_at": manifest.get("created_at"),
                          "backup_app_version": manifest.get("app_version"), "counts": manifest.get("counts"),
                          "report": report.get("report"), "report_transactions": report.get("transactions", 0),
                          "sessions_revoked": "all"}, category="SECURITY")
            s.commit()
        app.state.engine, app.state.session_factory = engine, factory
        app.state.key = crypto.load_key(settings.secrets_dir)
        app.state.limiter = LoginRateLimiter(settings.login_max_failures, settings.login_lockout_seconds)
        job.result = {"workspace": facts["workspace"], "backup_created_at": manifest.get("created_at"),
                      "backup_app_version": manifest.get("app_version"), "counts": manifest.get("counts"),
                      "report_summary": restore_report.summary_text(report) if report else None}
        job.advance("")
        job.state = "done"
        log.info("restore completed")
    except Exception as e:
        log.exception("restore failed")
        if swapped:
            try:
                app.state.engine.dispose()
                bk.rollback(settings)
                app.state.engine = make_engine(settings.database_url)
                app.state.session_factory = make_session_factory(app.state.engine)
                app.state.key = crypto.load_key(settings.secrets_dir)
                msg = "the previous data was put back"
            except Exception:  # pragma: no cover - last resort, reported
                log.exception("rollback failed")
                msg = f"putting the previous data back failed - it is in {bk.PRE_RESTORE_DIR}/ in the data folder"
        else:
            msg = "nothing was changed"
        detail = str(e) if isinstance(e, bk.BackupError) else f"unexpected error ({type(e).__name__})"
        job.state, job.error = "failed", f"{detail} Restore stopped at \"{job.step}\"; {msg}."
    finally:
        app.state.maintenance = None
        shutil.rmtree(work, ignore_errors=True)


# ------------------------------------------------------------------ 2.0.0 (#124) server-recoverable backups
@router.get("/server-backups")
def server_backups(request: Request, ctx: Ctx = Depends(require("users.manage"))):
    """Backups made on this server that its owner can restore without the passphrase (metadata only)."""
    return {"backups": server_recovery.list_backups(request.app.state.settings)}


@router.post("/server-backups/{rid}/remove-recovery")
def server_backup_remove_recovery(rid: str, request: Request, db: Session = Depends(get_db),
                                  ctx: Ctx = Depends(require("users.manage"))):
    try:
        r = server_recovery.remove_recovery(request.app.state.settings, rid)
    except server_recovery.RecoveryError as e:
        if str(e) == "protected":
            raise AppError(409, "PROTECTED", "The safety backup of a reinitialize always stays recoverable.") from None
        raise AppError(404, "NOT_FOUND", "Not found.") from None
    audit.record(db, ctx, "BACKUP_RECOVERY_REMOVED", "workspace", ctx.workspace_id, None,
                 {"recovery_id": r["id"], "filename": r["filename"], "created_at": r["created_at"]}, category="SECURITY")
    db.commit()
    return {"removed": r["id"]}


# ------------------------------------------------------------------ 2.0.0 (#124) restore re-entry reports
@router.get("/restore-reports")
def restore_reports(request: Request, ctx: Ctx = Depends(get_ctx)):
    """The roles that read the register list and download the reports; an Administrator sees the summary only."""
    if ctx.user is None or ctx.mfa_pending:
        raise AppError(401, "UNAUTHENTICATED", "Authentication required.")
    can_download = ctx.has("financial.view")
    if not can_download and not ctx.has("users.manage"):
        raise AppError(403, "FORBIDDEN", "You do not have permission to perform this action.")
    rows = restore_report.list_reports(request.app.state.settings)
    return {"reports": rows, "can_download": can_download}


@router.get("/restore-reports/{name}")
def restore_report_download(name: str, request: Request, db: Session = Depends(get_db),
                            ctx: Ctx = Depends(require("financial.view"))):
    p = restore_report.report_path(request.app.state.settings, name)
    if p is None:
        raise AppError(404, "NOT_FOUND", "Report not found.")
    audit.record(db, ctx, "RESTORE_REPORT_DOWNLOADED", "workspace", ctx.workspace_id, None, {"report": name})
    db.commit()
    return FileResponse(p, media_type="text/csv", filename=name, headers={"Cache-Control": "private, no-store"})


# ------------------------------------------------------------------ 2.0.0 (#125) reinitialize (keeping users)
class ReinitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str = Field(max_length=40)
    password: str = Field(max_length=200)
    code: str | None = Field(default=None, max_length=40)
    passphrase: str | None = Field(default=None, max_length=500)
    passphrase_confirmation: str | None = Field(default=None, max_length=500)


@router.get("/reinitialize")
def reinitialize_info(request: Request, db: Session = Depends(get_db), ctx: Ctx = Depends(require("users.manage"))):
    from ..services import mfa
    from ..services import reinitialize as reinit
    until = reinit.cooldown_until(db, ctx.workspace_id)
    return {"counts": reinit.counts(db, ctx.workspace_id), "cooldown_until": until.isoformat() + "Z" if until else None,
            "code_required": mfa.enabled(db, ctx.user), "confirm_word": reinit.CONFIRM_WORD,
            "kept": ["users and their roles", "passwords, two-step verification and security questions",
                     "the organization name", "the encryption key", "module switches", "personal preferences and "
                     "reminders", "backup settings", "the audit log"],
            "removed": ["Fiscal Years and budgets", "entities", "bank accounts", "the register (transactions)",
                        "attachments", "fundraisers", "Payments module data (check styles, signers, letters, "
                        "envelopes)", "organization reminders"]}


@router.post("/reinitialize", status_code=202)
def reinitialize_start(body: ReinitIn, request: Request, db: Session = Depends(get_db),
                       ctx: Ctx = Depends(require("users.manage"))):
    from ..services import mfa
    from ..services import reinitialize as reinit
    if (body.confirm or "").strip() != reinit.CONFIRM_WORD:
        raise validation(f'Type "{reinit.CONFIRM_WORD}" to confirm.', "confirm")
    until = reinit.cooldown_until(db, ctx.workspace_id)
    if until:
        raise AppError(409, "COOLDOWN", "The data was reinitialized less than 24 hours ago. Try again after "
                                        f"{until:%Y-%m-%d %H:%M} UTC, or use the server's command line.")
    if body.passphrase or body.passphrase_confirmation:
        _passphrase_ok(body.passphrase or "", body.passphrase_confirmation or "")
    _check_password(request, db, ctx, body.password or "", "REINITIALIZE")
    if mfa.enabled(db, ctx.user):
        if not body.code or mfa.verify(db, request.app.state.key, ctx.user, body.code) is None:
            audit.record(db, ctx, "REINITIALIZE_DENIED", "workspace", ctx.workspace_id, None,
                         {"reason": "incorrect_code"}, category="SECURITY")
            db.commit()
            raise AppError(400, "INCORRECT_CODE", "The two-step verification code is not correct.")
    app = request.app
    if app.state.jobs.running():
        raise AppError(409, "JOB_RUNNING", "A backup, restore or reinitialize is already running.")
    job = app.state.jobs.new("reinitialize")
    audit.record(db, ctx, "REINITIALIZE_STARTED", "workspace", ctx.workspace_id, None,
                 {"own_passphrase": bool(body.passphrase)}, category="SECURITY")
    db.commit()
    from ..services.users import label as user_label   # 2.0.0 (#134): "First Last - username"
    actor = {"user_id": ctx.user.id, "username": ctx.user.username, "label": user_label(ctx.user),
             "workspace_id": ctx.workspace_id, "ip": ctx.ip,
             "cid": ctx.correlation_id, "session_id": ctx.session.id if ctx.session else None}
    passphrase = body.passphrase or reinit.new_passphrase()
    threading.Thread(target=run_reinitialize, args=(app, job, passphrase, bool(body.passphrase), actor),
                     name="fmpoc-reinitialize", daemon=True).start()
    return job.out()


@router.get("/reinitialize/jobs/{job_id}")
def reinitialize_status(job_id: str, request: Request):
    """Polled while the application is paused (the random job id is the capability, like the restore's)."""
    job = request.app.state.jobs.get(job_id)
    if job is None or job.kind != "reinitialize":
        raise AppError(404, "NOT_FOUND", "Not found.")
    return job.out()


def run_reinitialize(app, job, passphrase: str, own_passphrase: bool, actor: dict) -> None:
    from ..services import reinitialize as reinit
    settings = app.state.settings
    try:
        job.advance("Pausing the application")
        app.state.maintenance = "reinitialize"   # nothing can change between the safety backup and the removal
        time.sleep(0.5)  # let requests in flight finish
        job.advance("Creating the safety backup")
        safety = reinit.safety_backup(settings, passphrase, actor.get("label") or actor["username"], job)
        job.advance("Removing the financial data")
        with app.state.session_factory() as s:
            try:
                ctx = _Actor(actor)
                before = reinit.counts(s, actor["workspace_id"])
                reinit.wipe(s, actor["workspace_id"], ctx, actor.get("label") or actor["username"], safety["filename"],
                            "system_about", before)
                q = update(AuthSession).where(AuthSession.revoked_at.is_(None))
                if actor.get("session_id"):
                    q = q.where(AuthSession.id != actor["session_id"])
                s.execute(q.values(revoked_at=utcnow()))
                s.commit()
            except Exception:
                s.rollback()
                raise
        job.advance("Removing the attachment files")
        reinit.remove_attachment_files(settings)
        restore_cmd = (f"pennywarden restore \"{safety['path']}\" --use-server-key --data-dir \"{settings.data_dir}\"")
        job.result = {"filename": safety["filename"], "folder": safety["folder"], "restore_command": restore_cmd,
                      "own_passphrase": own_passphrase}
        job.advance("")
        job.state = "done"
        log.info("reinitialize completed")
    except reinit.ReinitError as e:
        job.state, job.error = "failed", str(e)
    except Exception as e:  # pragma: no cover - reported to the admin
        log.exception("reinitialize failed")
        job.state, job.error = "failed", f"The reinitialize failed ({type(e).__name__}); the data was not changed."
    finally:
        app.state.maintenance = None


@router.get("/reinitialized")
def reinitialized(db: Session = Depends(get_db), ctx: Ctx = Depends(get_ctx)):
    """The banner every signed-in user sees after a reinitialize, until an Administrator acknowledges it."""
    if ctx.user is None or ctx.mfa_pending:
        raise AppError(401, "UNAUTHENTICATED", "Authentication required.")
    from ..models import Workspace
    from ..services import reinitialize as reinit
    return {**reinit.banner(db.get(Workspace, ctx.workspace_id)), "can_acknowledge": ctx.has("users.manage")}


@router.post("/reinitialized/acknowledge")
def reinitialized_ack(db: Session = Depends(get_db), ctx: Ctx = Depends(require("users.manage"))):
    from ..services import reinitialize as reinit
    out = reinit.acknowledge(db, ctx)
    db.commit()
    return out
