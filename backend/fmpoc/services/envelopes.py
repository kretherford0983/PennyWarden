"""2.2.0 (#325): one shared envelope library, tagged by feature (Kyle, 2026-10-23).

- Each envelope template has *Used for* tags (PAYMENTS, DONATIONS, later features) and each feature has its own
  default. A user's envelope printer adjustments belong to the template, so they carry over to every feature using it.
- Managed on the global Envelopes page (Administrators; any tag can be removed there) and on each feature's setup
  page: a template created there gets that feature's tag; the page lists the other templates so the feature's tag can
  be added; a feature's page removes only its own tag.
- Upgrading: existing templates are tagged Payments and the Payments default stays the default (migration 0055).
- Editing a template another feature also uses shows "Also used for ..."; *Duplicate for <feature> only* makes a copy
  tagged for that feature and moves the tag (and the default) from the original to the copy.
- Removing a feature's tag from its default asks for another default among the remaining tagged templates; removing it
  from the last one leaves the feature with no envelope (printing an envelope is hidden for it). A template with no tag
  stays listed as *Not used*; it is never deleted (printed copies refer to it).
Cover letters stay Payments' own (receipts have their own letter in Donations Setup).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, conflict, forbidden, validation
from ..models import CheckDocument, Workspace, utcnow
from .checkprint import service as cp

PAYMENTS, DONATIONS = "PAYMENTS", "DONATIONS"
FEATURES = (PAYMENTS, DONATIONS)
LABELS = {PAYMENTS: "Payments", DONATIONS: "Donations"}


def _split(v: str | None) -> list[str]:
    return [x for x in (v or "").split(",") if x in FEATURES]


def tags(d: CheckDocument) -> list[str]:
    return _split(d.features)


def defaults(d: CheckDocument) -> list[str]:
    return _split(d.default_for)


def _set(d: CheckDocument, features: list[str], default_for: list[str]) -> None:
    d.features = ",".join(f for f in FEATURES if f in features) or None
    d.default_for = ",".join(f for f in FEATURES if f in default_for and f in features) or None
    if d.kind == "ENVELOPE":
        d.is_default = PAYMENTS in defaults(d)          # Payments' print screen reads is_default


def clear_defaults(d: CheckDocument) -> None:
    """A deactivated template is no feature's default any more (its tags stay)."""
    _set(d, tags(d), [])


def enabled(db: Session, ws_id: int) -> list[str]:
    ws = db.get(Workspace, ws_id)
    out = []
    if ws is not None and ws.checks_enabled:
        out.append(PAYMENTS)
    if ws is not None and ws.donations_enabled:
        out.append(DONATIONS)
    return out


def require_any_module(db: Session, ctx) -> None:
    if not enabled(db, ctx.workspace_id):
        raise AppError(404, "MODULE_DISABLED", "Envelopes are used by the Payments and Donations modules; neither is "
                                               "turned on.")


FEATURE_PERMISSION = {PAYMENTS: "checks.setup", DONATIONS: "donation.setup"}


def require_feature(db: Session, ctx, feature: str) -> None:
    """Tagging, defaults and templates created for a feature need that feature's setup permission and its module on."""
    feature = _feature(feature)
    if not ctx.has(FEATURE_PERMISSION[feature]):
        raise forbidden()
    if feature not in enabled(db, ctx.workspace_id):
        raise AppError(404, "MODULE_DISABLED", f"The {LABELS[feature]} module is not turned on.")


def envelopes(db: Session, ctx, feature: str | None = None, active_only: bool = False) -> list[CheckDocument]:
    out = cp.list_documents(db, ctx, "ENVELOPE", include_inactive=not active_only)
    return [d for d in out if feature is None or feature in tags(d)]


def default_of(db: Session, ctx, feature: str) -> CheckDocument | None:
    return next((d for d in envelopes(db, ctx, feature, True) if feature in defaults(d)), None)


def out(db: Session, ctx, d: CheckDocument) -> dict:
    return {**cp.doc_out(d), "features": tags(d), "default_for": defaults(d),
            "used_for": [LABELS[f] for f in tags(d)] or ["Not used"]}


def library(db: Session, ctx) -> dict:
    return {"envelopes": [out(db, ctx, d) for d in envelopes(db, ctx)],
            "features": [{"id": f, "label": LABELS[f], "enabled": f in enabled(db, ctx.workspace_id),
                          "default": (default_of(db, ctx, f).id if default_of(db, ctx, f) else None)}
                         for f in FEATURES]}


def _feature(f: str) -> str:
    if f not in FEATURES:
        raise validation("Unknown feature.", "feature")
    return f


def _snap(d: CheckDocument) -> dict:
    return {"features": tags(d), "default_for": defaults(d)}


def set_tag(db: Session, ctx, d: CheckDocument, feature: str, on: bool, new_default_id: int | None = None) -> None:
    """Adds or removes a feature's tag. Removing it from the feature's default needs another default among the
    remaining tagged templates (409 DEFAULT_NEEDED lists them) - unless it is the last one."""
    feature = _feature(feature)
    if d.kind != "ENVELOPE":
        raise validation("Only envelope templates are shared between features.", "feature")
    before = _snap(d)
    if on:
        if feature in tags(d):
            return
        first = default_of(db, ctx, feature) is None and d.active
        _set(d, tags(d) + [feature], defaults(d) + ([feature] if first else []))
    else:
        if feature not in tags(d):
            return
        others = [x for x in envelopes(db, ctx, feature, True) if x.id != d.id]
        if feature in defaults(d) and others:
            nxt = next((x for x in others if x.id == new_default_id), None)
            if nxt is None:
                raise AppError(409, "DEFAULT_NEEDED", f"This is the {LABELS[feature]} default. Choose another "
                                                      f"default for {LABELS[feature]} first.",
                               candidates=[{"id": x.id, "name": x.name} for x in others])
            _set(nxt, tags(nxt), defaults(nxt) + [feature])
        _set(d, [f for f in tags(d) if f != feature], [f for f in defaults(d) if f != feature])
    d.updated_by_user_id, d.updated_at = ctx.user.id, utcnow()
    db.flush()
    audit.record(db, ctx, "ENVELOPE_TAGS_UPDATED", "check_document", d.id, before,
                 {**_snap(d), "feature": feature, "on": on, "new_default_id": new_default_id if not on else None})


def set_default(db: Session, ctx, d: CheckDocument, feature: str) -> None:
    feature = _feature(feature)
    if feature not in tags(d):
        raise conflict("NOT_TAGGED", f"Add the template to {LABELS[feature]} first.")
    if not d.active:
        raise conflict("TEMPLATE_INACTIVE", "A deactivated template can't be the default.")
    for x in envelopes(db, ctx, feature):
        if x.id != d.id and feature in defaults(x):
            b = _snap(x)
            _set(x, tags(x), [f for f in defaults(x) if f != feature])
            audit.record(db, ctx, "ENVELOPE_TAGS_UPDATED", "check_document", x.id, b, _snap(x))
    before = _snap(d)
    _set(d, tags(d), defaults(d) + [feature])
    db.flush()
    if _snap(d) != before:
        audit.record(db, ctx, "ENVELOPE_TAGS_UPDATED", "check_document", d.id, before,
                     {**_snap(d), "default": feature})


def duplicate_for(db: Session, ctx, d: CheckDocument, feature: str) -> CheckDocument:
    """*Duplicate for <feature> only*: a copy tagged for this feature; the tag (and the default) move from the
    original to the copy, for when the two should differ."""
    feature = _feature(feature)
    if feature not in tags(d):
        raise conflict("NOT_TAGGED", f"This template isn't used for {LABELS[feature]}.")
    was_default = feature in defaults(d)
    copy = cp.duplicate_document(db, ctx, d, None)
    before = _snap(d)
    _set(copy, [feature], [feature] if was_default else [])
    _set(d, [f for f in tags(d) if f != feature], [f for f in defaults(d) if f != feature])
    db.flush()
    audit.record(db, ctx, "ENVELOPE_TAGS_UPDATED", "check_document", d.id, before,
                 {**_snap(d), "moved_to": copy.id, "feature": feature})
    audit.record(db, ctx, "ENVELOPE_TAGS_UPDATED", "check_document", copy.id, None,
                 {**_snap(copy), "duplicated_for": feature, "from": d.id})
    return copy


def tag_new(d: CheckDocument, feature: str | None, db: Session, ctx) -> None:
    """A template created on a feature's setup page gets that feature's tag (default when it has none); on the global
    page it can be created for no feature (Not used)."""
    if d.kind != "ENVELOPE":
        _set(d, [PAYMENTS], [PAYMENTS] if d.is_default else [])
        return
    if feature is None:
        _set(d, [], [])
        return
    feature = _feature(feature)
    first = default_of(db, ctx, feature) is None
    _set(d, [feature], [feature] if first else [])
