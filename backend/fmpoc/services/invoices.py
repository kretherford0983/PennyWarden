"""2.4.0 (#251): the Invoices module (part of #218) - the switch, and the rules every invoice feature follows.

Separation of duties: the Budget Manager decides budgets and marks them Invoiced Income (#250); the Invoice Manager
decides what is billed and for how much; the Register User receives and records the money; the Auditor reviews.
Roles stay combinable, so a small organization may give one person the whole cycle (shown, not blocked, on the
Administrator's Security overview).

Invoices, products, payments and reports arrive with later 2.4.0 builds (#252-#255, #248, #249); this module holds
the switch, the overview and the Administrator's setup.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError
from ..models import Workspace

WHOLE_CYCLE = ("BUDGET_MANAGER", "INVOICE_MANAGER", "REGISTER_USER")


def module_enabled(db: Session, ws_id: int | None) -> bool:
    ws = db.get(Workspace, ws_id) if ws_id else None
    return bool(ws and ws.invoices_enabled)


def require_module(db: Session, ctx) -> None:
    """When the module is off its pages are hidden and its API refuses requests (BR-091)."""
    if not module_enabled(db, ctx.workspace_id):
        raise AppError(404, "MODULE_DISABLED", "The Invoices module is not turned on.")


def set_module(db: Session, ctx, enabled: bool) -> bool:
    ws = db.get(Workspace, ctx.workspace_id)
    before = bool(ws.invoices_enabled)
    if before != enabled:
        ws.invoices_enabled = enabled
        audit.record(db, ctx, "MODULE_ENABLED" if enabled else "MODULE_DISABLED", "module", "invoices",
                     {"invoices_enabled": before}, {"invoices_enabled": enabled}, category="SECURITY")
    return enabled


def overview(ctx) -> dict:
    """What the signed-in user may do in the module (the pages fill in with the later builds)."""
    return {"module": True, "can_manage": ctx.has("invoice.manage"), "can_view": ctx.has("invoice.view"),
            "sections": []}


def setup(db: Session, ctx) -> dict:
    """The Administrator's setup page (numbering, terms, custom fields, PDF template, reminder days and a dummy-data
    test print arrive with the Invoices build, #253). Never shows real invoices or products (BR-003)."""
    return {"module": module_enabled(db, ctx.workspace_id), "settings": {}, "pending": True}
