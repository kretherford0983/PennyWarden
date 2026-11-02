"""2.3.0 (#376): Report settings - how the Reports catalog (#375) is grouped, for the whole organization.

The Administrator chooses a scheme - **Purpose** (the 2.3.0 default), **Subject** or **Audience** - and, within it, may
add, rename, reorder and remove categories and move reports between them (and order them). Each scheme keeps its own
customization; *Reset* puts a scheme back to its defaults. Every report belongs to exactly one category of the
active scheme (a removed category's reports must go to another one; the screen offers "Other"). A category may be
empty: the catalog hides it, as it hides a category whose reports the user can't run.

Display only: grouping never grants access - each report's permission and module checks still apply (business rule
recorded in implementation-notes as the issue's new BR). Workspace configuration, Administrators only, audited.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import validation
from ..models import ReportGrouping, utcnow
from .report_prefs import REPORT_IDS

SCHEMES = {"PURPOSE": "Purpose", "SUBJECT": "Subject", "AUDIENCE": "Audience"}
DEFAULT_SCHEME = "PURPOSE"
MAX_CATEGORIES = 20
MAX_NAME = 60
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,19}$")

DEFAULTS: dict[str, list[dict]] = {
    "PURPOSE": [
        {"id": "share", "name": "Share with the board and members", "short": "Share", "reports": ["quarterly", "fundraising-fy"]},
        {"id": "audit", "name": "Audit and year-end close", "short": "Audit and close", "reports": ["audit", "close", "fundraiser-detail"]},
        {"id": "analyze", "name": "Analyze activity", "short": "Analyze", "reports": ["entity", "flow"]},
        {"id": "plan", "name": "Plan budgets", "short": "Plan", "reports": ["budget-review", "planning-sheet"]},
        {"id": "fundraisers", "name": "Fundraisers", "short": "Fundraisers", "reports": ["count-sheet"]},
    ],
    "SUBJECT": [
        {"id": "fiscal-year", "name": "Fiscal Year", "reports": ["quarterly", "audit", "close"]},
        {"id": "budgets", "name": "Budgets", "reports": ["budget-review", "planning-sheet"]},
        {"id": "accounts", "name": "Accounts / Register", "reports": ["flow"]},
        {"id": "entities", "name": "Entities", "reports": ["entity"]},
        {"id": "fundraisers", "name": "Fundraisers", "reports": ["fundraising-fy", "fundraiser-detail", "count-sheet"]},
        {"id": "system", "name": "System", "reports": []},
    ],
    "AUDIENCE": [
        {"id": "board", "name": "Board & members", "reports": ["quarterly", "fundraising-fy"]},
        {"id": "treasurer", "name": "Treasurer / Budget Managers",
         "reports": ["entity", "flow", "budget-review", "planning-sheet", "count-sheet"]},
        {"id": "auditors", "name": "Auditors", "reports": ["audit", "close", "fundraiser-detail"]},
    ],
}


def _row(db: Session, ws_id: int) -> ReportGrouping | None:
    return db.scalar(select(ReportGrouping).where(ReportGrouping.workspace_id == ws_id))


def _stored(r: ReportGrouping | None) -> dict:
    try:
        return json.loads(r.config_json or "{}") if r else {}
    except ValueError:
        return {}


def _complete(cats: list[dict]) -> list[dict]:
    """Stored categories, with any report added since they were saved put in an Other category (never lost)."""
    cats = [{**c, "reports": [x for x in c.get("reports", []) if x in REPORT_IDS]} for c in cats]
    seen = {x for c in cats for x in c["reports"]}
    missing = [x for x in REPORT_IDS if x not in seen]
    if missing:
        other = next((c for c in cats if c["name"].lower() == "other"), None)
        if other is None:
            other = {"id": "other", "name": "Other", "reports": []}
            cats.append(other)
        other["reports"] += missing
    return cats


def scheme_categories(r: ReportGrouping | None, scheme: str) -> tuple[list[dict], bool]:
    cfg = _stored(r).get(scheme)
    if cfg:
        return _complete(cfg), True
    return [dict(c, reports=list(c["reports"])) for c in DEFAULTS[scheme]], False


def active(db: Session, ws_id: int) -> dict:
    """The grouping the Reports catalog shows (every user)."""
    r = _row(db, ws_id)
    scheme = r.scheme if r and r.scheme in SCHEMES else DEFAULT_SCHEME
    cats, custom = scheme_categories(r, scheme)
    return {"scheme": scheme, "scheme_label": SCHEMES[scheme], "customized": custom, "categories": cats}


def admin_view(db: Session, ctx) -> dict:
    r = _row(db, ctx.workspace_id)
    out = {"scheme": r.scheme if r and r.scheme in SCHEMES else DEFAULT_SCHEME,
           "schemes": [], "reports": list(REPORT_IDS), "max_categories": MAX_CATEGORIES, "max_name": MAX_NAME}
    for k, label in SCHEMES.items():
        cats, custom = scheme_categories(r, k)
        out["schemes"].append({"id": k, "label": label, "customized": custom, "categories": cats,
                               "defaults": DEFAULTS[k]})
    return out


def _ensure(db: Session, ws_id: int) -> ReportGrouping:
    r = _row(db, ws_id)
    if r is None:
        r = ReportGrouping(workspace_id=ws_id, scheme=DEFAULT_SCHEME)
        db.add(r)
        db.flush()
    return r


def _validate(categories: list) -> list[dict]:
    if not categories or len(categories) > MAX_CATEGORIES:
        raise validation(f"Use 1 to {MAX_CATEGORIES} categories.", "categories")
    out, names, ids, placed = [], set(), set(), []
    for i, c in enumerate(categories):
        name = (c.get("name") or "").strip()
        if not name or len(name) > MAX_NAME or "\n" in name:
            raise validation(f"Each category needs a name of up to {MAX_NAME} characters.", f"categories.{i}.name")
        if name.lower() in names:
            raise validation(f"Two categories are called “{name}”.", f"categories.{i}.name")
        names.add(name.lower())
        cid = (c.get("id") or "").strip().lower()
        if not cid:
            base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:16] or "category"
            cid, n = base, 2
            while cid in ids:
                cid, n = f"{base}-{n}", n + 1
        if not ID_RE.match(cid) or cid in ids:
            raise validation("Category ids are short and unique.", f"categories.{i}.id")
        ids.add(cid)
        reps = list(c.get("reports") or [])
        unknown = [x for x in reps if x not in REPORT_IDS]
        if unknown:
            raise validation(f"Unknown report: {unknown[0]}.", f"categories.{i}.reports")
        placed += reps
        item = {"id": cid, "name": name, "reports": reps}
        if c.get("short"):
            item["short"] = str(c["short"]).strip()[:30]
        out.append(item)
    twice = sorted({x for x in placed if placed.count(x) > 1})
    if twice:
        raise validation(f"A report can be in only one category ({twice[0]}).", "categories")
    missing = [x for x in REPORT_IDS if x not in placed]
    if missing:
        raise validation(f"Every report needs a category ({missing[0]} has none).", "categories")
    return out


def save(db: Session, ctx, scheme: str, categories: list | None) -> dict:
    """Makes `scheme` the active one and, with categories, saves its customization."""
    if scheme not in SCHEMES:
        raise validation("Choose Purpose, Subject or Audience.", "scheme")
    r = _ensure(db, ctx.workspace_id)
    before = {"scheme": r.scheme, "categories": scheme_categories(r, scheme)[0]}
    cfg = _stored(r)
    if categories is not None:
        cfg[scheme] = _validate(categories)
    r.scheme = scheme
    r.config_json = json.dumps(cfg, sort_keys=True) if cfg else None
    r.updated_at, r.updated_by_user_id = utcnow(), ctx.user.id
    db.flush()
    after = {"scheme": r.scheme, "categories": scheme_categories(r, scheme)[0]}
    if after != before:
        audit.record(db, ctx, "REPORT_GROUPING_UPDATED", "report_grouping", r.id, before, after)
    return admin_view(db, ctx)


def reset(db: Session, ctx, scheme: str) -> dict:
    """*Reset to defaults* for one scheme (it stays the active one if it is)."""
    if scheme not in SCHEMES:
        raise validation("Choose Purpose, Subject or Audience.", "scheme")
    r = _row(db, ctx.workspace_id)
    cfg = _stored(r)
    if r is None or scheme not in cfg:
        return admin_view(db, ctx)
    before = {"scheme": r.scheme, "categories": scheme_categories(r, scheme)[0]}
    cfg.pop(scheme)
    r.config_json = json.dumps(cfg, sort_keys=True) if cfg else None
    r.updated_at, r.updated_by_user_id = utcnow(), ctx.user.id
    db.flush()
    audit.record(db, ctx, "REPORT_GROUPING_RESET", "report_grouping", r.id, before,
                 {"scheme": scheme, "categories": scheme_categories(r, scheme)[0]})
    return admin_view(db, ctx)
