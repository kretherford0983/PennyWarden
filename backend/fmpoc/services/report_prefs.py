"""2.3.0 (#375): the Reports screen's per-user memory, kept server-side so it follows the user across devices:
*Recently run* (the last RECENT_MAX runs: report, parameters, a short label, when) and each report's last options.

Only report parameters are kept - never report output (04-security §3 as amended by #375). Values are short scalars
(free text such as a report's commentary is not remembered: the page leaves it out). The report ids are the Reports
registry's (frontend `pages/reports/registry.ts`); unknown ids are refused. A recently run entry never grants
anything: running it again goes through the report's own permission checks.
"""
from __future__ import annotations

import datetime as dt
import json

from sqlalchemy.orm import Session

from ..errors import validation
from ..models import User as AppUser

REPORT_IDS = ("quarterly", "fundraising-fy", "audit", "close", "fundraiser-detail", "entity", "flow",
              "budget-review", "planning-sheet", "count-sheet",
              # 2.4.0 (#255): the Invoices group
              "inv-open", "inv-aging", "inv-statement", "inv-sales-tax", "inv-register", "inv-sales", "inv-activity")
RECENT_MAX = 5
MAX_PARAMS = 16
MAX_VALUE = 200
MAX_LABEL = 160


def _load(u: AppUser) -> dict:
    try:
        d = json.loads(u.report_prefs or "{}")
    except ValueError:
        d = {}
    return {"recent": [r for r in d.get("recent", []) if r.get("report") in REPORT_IDS][:RECENT_MAX],
            "last": {k: v for k, v in (d.get("last") or {}).items() if k in REPORT_IDS}}


def get(u: AppUser) -> dict:
    return {**_load(u), "recent_max": RECENT_MAX, "reports": list(REPORT_IDS)}


def _clean(params: dict | None) -> dict:
    params = params or {}
    if len(params) > MAX_PARAMS:
        raise validation(f"At most {MAX_PARAMS} options.", "params")
    out: dict = {}
    for k, v in params.items():
        if not isinstance(k, str) or not k or len(k) > 40:
            raise validation("Option names are short words.", "params")
        if isinstance(v, list):
            if len(v) > 50 or any(not isinstance(x, (str, int)) or isinstance(x, bool) or len(str(x)) > 40 for x in v):
                raise validation("A list option holds up to 50 short values.", f"params.{k}")
            out[k] = [str(x) for x in v]
        elif v is None or isinstance(v, (bool, int)):
            out[k] = v
        elif isinstance(v, str):
            if len(v) > MAX_VALUE:
                raise validation(f"An option value is at most {MAX_VALUE} characters.", f"params.{k}")
            out[k] = v
        else:
            raise validation("Option values are text, numbers, yes/no or lists.", f"params.{k}")
    return out


def record_run(db: Session, u: AppUser, report: str, params: dict | None, label: str | None) -> dict:
    """A report was opened or downloaded: it becomes the first of Recently run (an identical earlier run moves up
    rather than repeating) and its options are remembered for the next time."""
    if report not in REPORT_IDS:
        raise validation("Unknown report.", "report")
    clean = _clean(params)
    label = (label or "").strip()[:MAX_LABEL] or None
    d = _load(u)
    run = {"report": report, "params": clean, "label": label,
           "at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()}
    d["recent"] = [run] + [r for r in d["recent"] if not (r["report"] == report and r.get("params") == clean)]
    d["recent"] = d["recent"][:RECENT_MAX]
    d["last"][report] = clean
    u.report_prefs = json.dumps(d, sort_keys=True)
    db.flush()
    return get(u)
