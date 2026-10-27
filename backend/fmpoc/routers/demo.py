"""2.2.0 (#243): the demo's Reset demo data (also from the sign-in page) and Remove the demo. 404 unless this is the
demo (local mode, loopback only - see services/demo.py)."""
from __future__ import annotations

import logging
import threading
import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from ..db import make_engine, make_session_factory, upgrade_database
from ..deps import Ctx, require
from ..errors import AppError, validation
from ..security import crypto
from ..services import demo as svc
from ..services.auth import LoginRateLimiter

log = logging.getLogger("fmpoc")
router = APIRouter(prefix="/api/system/demo", tags=["demo"])


def _demo(request: Request) -> None:
    if not getattr(request.app.state, "demo", False):
        raise AppError(404, "NOT_FOUND", "Not found.")


def _swap(app, action, after=None) -> None:
    """Pauses the application at once, then - in the background, once this request has closed its database session
    (Windows can't replace open files) - closes the database, runs `action` on the files and opens it again. The page
    waits until /api/system/status no longer reports the pause."""
    if app.state.jobs.running() or app.state.maintenance:
        raise AppError(409, "JOB_RUNNING", "A backup or restore is running; try again in a moment.")
    app.state.maintenance = "restore"
    threading.Thread(target=_run_swap, args=(app, action, after), name="pennywarden-demo", daemon=True).start()


def _run_swap(app, action, after) -> None:
    settings = app.state.settings
    try:
        time.sleep(0.5)                # let the request (and any in flight) finish
        app.state.engine.dispose()
        action(settings)
        upgrade_database(settings.database_url)
        app.state.engine = make_engine(settings.database_url)
        app.state.session_factory = make_session_factory(app.state.engine)
        app.state.key = crypto.load_key(settings.secrets_dir)
        app.state.limiter = LoginRateLimiter(settings.login_max_failures, settings.login_lockout_seconds)
        if after:
            after(app)
    except Exception:   # pragma: no cover - logged; the next start resets the demo again
        log.exception("demo reset/remove failed")
    finally:
        app.state.maintenance = None


@router.post("/reset", dependencies=[Depends(_demo)])
def reset(request: Request):
    """Reset demo data: the pristine demo again (users, data and the audit log). No sign-in needed - it is on the
    sign-in page too, so an evaluator who locked themselves out can always recover; it exists only in the demo."""
    _swap(request.app, svc.reset_files)
    return {"ok": True}


class RemoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str = Field(max_length=20)


@router.post("/remove", dependencies=[Depends(_demo)])
def remove(body: RemoveIn, request: Request, ctx: Ctx = Depends(require("users.manage"))):
    """Remove the demo and start fresh: the Initialization Wizard comes next and makes a new key."""
    if body.confirm.strip() != "REMOVE":
        raise validation("Type REMOVE to confirm.", "confirm")
    _swap(request.app, svc.remove_files, after=lambda app: setattr(app.state, "demo", False))
    return {"ok": True}
