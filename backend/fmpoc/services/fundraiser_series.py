"""2.1.0 (#277): fundraisers across years and the Fiscal Year fundraising report.

* **Series.** "Continues from (previous fundraiser)" puts a fundraiser in the previous one's series, creating the
  series behind the scenes (named after it, with any four-digit year removed). The link can change in any Fiscal Year,
  closed ones included - it is reporting only. Budget Managers rename series, mark them *Group as Other*, enter
  results of earlier years by hand (labelled *Entered*, retired - never deleted) and merge series started twice.
* **Years.** A Fiscal Year's number is the four-digit year in its name (FY2027 -> 2027), else its end year. A
  fundraiser counts wholly in the Fiscal Year of its event start date; an entered result names its year in its label.
  An entered result is refused for a year in which the series already has a fundraiser in PennyWarden.
* **The report** covers the fundraisers chosen on /fundraisers for one Fiscal Year (figures from
  `fundraiser_summary.summary()`, so each row equals that fundraiser's stakeholder report) and the history of their
  series. No contributor names: it is about events, not donors.
"""
from __future__ import annotations

import datetime as dt
import re
from fractions import Fraction

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import AppError, not_found, validation
from ..models import (Budget, FiscalYear, Fundraiser, FundraiserBucket, FundraiserBucketCategory, FundraiserFyReportNote,
                      FundraiserSeries, FundraiserSeriesResult, utcnow)
from ..money import fmt, parse_amount
from . import budgets as bsvc
from . import fundraisers as fsvc
from .common import covering_fiscal_years, fy_brief, get_scoped

YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
OTHER_SHARE = Fraction(5, 100)


# ------------------------------------------------------------------ years
def fy_year(fy: FiscalYear) -> int:
    m = YEAR_RE.search(fy.display_name or "")
    return int(m.group(0)) if m else fy.end_date.year


def label_year(label: str) -> int | None:
    m = YEAR_RE.search(label or "")
    return int(m.group(0)) if m else None


def date_year(db: Session, ws_id: int, d: dt.date) -> int:
    """The Fiscal Year number of a date: the year covering it, else counted on from the nearest year (a fundraiser
    planned before next year's Fiscal Year exists still belongs to "next year")."""
    cov = covering_fiscal_years(db, ws_id, d)
    if cov:
        return fy_year(cov[0])
    fys = list(db.scalars(select(FiscalYear).where(FiscalYear.workspace_id == ws_id).order_by(FiscalYear.start_date)))
    if not fys:
        return d.year
    before = [f for f in fys if f.end_date < d]
    if before:
        last = before[-1]
        return fy_year(last) + 1 + int((d - last.end_date - dt.timedelta(days=1)).days // 365.25)
    first = fys[0]
    return fy_year(first) - 1 - int((first.start_date - d - dt.timedelta(days=1)).days // 365.25)


def fundraiser_year(db: Session, f: Fundraiser) -> int:
    return date_year(db, f.workspace_id, f.start_date)


def series_name_for(name: str) -> str:
    """"2026 Golf Outing" -> "Golf Outing"."""
    out = YEAR_RE.sub("", name)
    out = re.sub(r"\s{2,}", " ", out).strip(" -–—:,")
    return out or name


def next_name(name: str) -> str:
    """Every four-digit year moves on one: "Golf Outing 2026" -> "Golf Outing 2027"."""
    return YEAR_RE.sub(lambda m: str(int(m.group(0)) + 1), name)


# ------------------------------------------------------------------ series
def _series(db: Session, ctx, series_id: int) -> FundraiserSeries:
    s = get_scoped(db, FundraiserSeries, series_id, ctx, "Fundraiser series")
    if s.merged_into_id is not None:
        raise not_found("Fundraiser series")
    return s


def _link_snapshot(f: Fundraiser) -> dict:
    return {"series_id": f.series_id, "continues_from_id": f.continues_from_id}


def continue_options(db: Session, ctx, start_date: dt.date, exclude_id: int | None = None) -> list[dict]:
    """The latest fundraiser of each series plus fundraisers in no series, from earlier Fiscal Years (so a skipped
    year still links), newest first."""
    year = date_year(db, ctx.workspace_id, start_date)
    cands = [f for f in db.scalars(select(Fundraiser).where(Fundraiser.workspace_id == ctx.workspace_id))
             if f.id != exclude_id and fundraiser_year(db, f) < year]
    latest: dict[object, Fundraiser] = {}
    for f in cands:
        key = ("s", f.series_id) if f.series_id else ("f", f.id)
        if key not in latest or (f.start_date, f.id) > (latest[key].start_date, latest[key].id):
            latest[key] = f
    names = {s.id: s.name for s in db.scalars(select(FundraiserSeries).where(FundraiserSeries.workspace_id == ctx.workspace_id))}
    out = sorted(latest.values(), key=lambda f: (f.start_date, f.id), reverse=True)
    return [{"id": f.id, "name": f.name, "start_date": f.start_date.isoformat(), "year": fundraiser_year(db, f),
             "series_id": f.series_id, "series_name": names.get(f.series_id)} for f in out]


def set_link(db: Session, ctx, f: Fundraiser, previous_id: int | None, *, record: bool = True) -> Fundraiser:
    """Put the fundraiser in the previous one's series (creating it), or take it out (None). Any Fiscal Year."""
    before = _link_snapshot(f)
    if previous_id is None and f.continues_from_id is None:
        pass        # nothing to unlink; a series started on this fundraiser (start_series, #292) keeps it and its history
    elif previous_id is None:
        f.series_id, f.continues_from_id = None, None
    else:
        prev = fsvc.get(db, ctx, previous_id)
        if prev.id == f.id or fundraiser_year(db, prev) >= fundraiser_year(db, f):
            raise validation("Choose a fundraiser of an earlier Fiscal Year.", "continues_from_id")
        if prev.series_id is None:
            s = FundraiserSeries(workspace_id=ctx.workspace_id, name=series_name_for(prev.name), created_by_user_id=ctx.user.id)
            db.add(s)
            db.flush()
            prev.series_id = s.id
            audit.record(db, ctx, "FUNDRAISER_SERIES_CREATED", "fundraiser_series", s.id, None,
                         {"name": s.name, "fundraiser_ids": [prev.id]})
        f.series_id, f.continues_from_id = prev.series_id, prev.id
    db.flush()
    if record and _link_snapshot(f) != before:
        audit.record(db, ctx, "FUNDRAISER_SERIES_LINK_UPDATED", "fundraiser", f.id, before, _link_snapshot(f))
    return f


def start_series(db: Session, ctx, f: Fundraiser) -> FundraiserSeries:
    """The fundraiser's series, creating it when the fundraiser is in none - so results of years before PennyWarden
    can be entered for an event whose earlier years exist only outside the app (nothing to "continue from").
    Named like an auto-created series ("2026 Golf Outing" -> "Golf Outing"). Any Fiscal Year: reporting only."""
    if f.series_id is not None:
        return _series(db, ctx, f.series_id)
    before = _link_snapshot(f)
    s = FundraiserSeries(workspace_id=ctx.workspace_id, name=series_name_for(f.name), created_by_user_id=ctx.user.id)
    db.add(s)
    db.flush()
    f.series_id = s.id
    db.flush()
    audit.record(db, ctx, "FUNDRAISER_SERIES_CREATED", "fundraiser_series", s.id, None,
                 {"name": s.name, "fundraiser_ids": [f.id]})
    audit.record(db, ctx, "FUNDRAISER_SERIES_LINK_UPDATED", "fundraiser", f.id, before, _link_snapshot(f))
    return s


def start_options(db: Session, ctx) -> list[dict]:
    """Fundraisers in no series, newest first - the choices for "Start a series"."""
    out = sorted(db.scalars(select(Fundraiser).where(Fundraiser.workspace_id == ctx.workspace_id,
                                                     Fundraiser.series_id.is_(None))),
                 key=lambda f: (f.start_date, f.id), reverse=True)
    return [{"id": f.id, "name": f.name, "start_date": f.start_date.isoformat(), "year": fundraiser_year(db, f),
             "series_name": series_name_for(f.name)} for f in out]


def _result_out(r: FundraiserSeriesResult) -> dict:
    return {"id": r.id, "fiscal_year_label": r.fiscal_year_label, "year": r.year, "net": fmt(r.net_cents),
            "income": fmt(r.income_cents), "expense": fmt(r.expense_cents), "note": r.note,
            "retired": r.retired_at is not None, "retire_reason": r.retire_reason}


SORT_DIRECTIONS = ("desc", "asc")
DEFAULT_SERIES_SORT = "desc"     # 2.2.0 (#351): newest year first; stored as no preference


def series_sort_of(user) -> str:
    return user.fundraiser_series_sort or DEFAULT_SERIES_SORT


def _rows(fundraisers: list[dict], results: list[dict], direction: str) -> list[dict]:
    """2.2.0 (#351): one list per series, recorded fundraisers and entered results mixed by year (newest first unless
    `direction` is "asc"). Within a year the order is the same either way: recorded fundraisers by start date, newest
    first; then active entered results; then retired ones (the record of the change)."""
    rows = [{"kind": "recorded", **f} for f in fundraisers] + [{"kind": "entered", **r} for r in results]

    def within(r):
        if r["kind"] == "recorded":
            return (0, -dt.date.fromisoformat(r["start_date"]).toordinal(), -r["id"])
        return (2 if r["retired"] else 1, 0, r["id"])
    rows.sort(key=within)
    rows.sort(key=lambda r: r["year"], reverse=direction != "asc")      # stable: the within-year order is kept
    return rows


def series_list(db: Session, ctx, direction: str | None = None) -> list[dict]:
    """Every series with its fundraisers and entered results. `rows` (2.2.0, #351) is the one ordered list the page
    shows; `direction` defaults to the user's remembered choice."""
    direction = direction if direction in SORT_DIRECTIONS else series_sort_of(ctx.user)
    out = []
    frs = list(db.scalars(select(Fundraiser).where(Fundraiser.workspace_id == ctx.workspace_id, Fundraiser.series_id.is_not(None))))
    for s in db.scalars(select(FundraiserSeries).where(FundraiserSeries.workspace_id == ctx.workspace_id,
                                                      FundraiserSeries.merged_into_id.is_(None)).order_by(FundraiserSeries.name)):
        members = sorted((f for f in frs if f.series_id == s.id), key=lambda f: f.start_date)
        results = list(db.scalars(select(FundraiserSeriesResult).where(FundraiserSeriesResult.series_id == s.id)
                                  .order_by(FundraiserSeriesResult.year, FundraiserSeriesResult.id)))
        fundraisers = [{"id": f.id, "name": f.name, "start_date": f.start_date.isoformat(),
                        "year": fundraiser_year(db, f), "status": fsvc.status_of(f)} for f in members]
        entered = [_result_out(r) for r in results]
        out.append({"id": s.id, "name": s.name, "group_as_other": s.group_as_other,
                    "fundraisers": fundraisers, "results": entered, "rows": _rows(fundraisers, entered, direction)})
    return out


def add_options(db: Session, ctx, f: Fundraiser) -> list[dict]:
    """2.2.0 (#302): the series a fundraiser in no series can be added to. A series with an active entered result
    for the fundraiser's year is listed but not allowed (a year is never counted twice)."""
    year = fundraiser_year(db, f)
    out = []
    for s in db.scalars(select(FundraiserSeries).where(FundraiserSeries.workspace_id == ctx.workspace_id,
                                                      FundraiserSeries.merged_into_id.is_(None)).order_by(FundraiserSeries.name)):
        entered = db.scalar(select(FundraiserSeriesResult).where(FundraiserSeriesResult.series_id == s.id,
                                                                 FundraiserSeriesResult.year == year,
                                                                 FundraiserSeriesResult.retired_at.is_(None)))
        out.append({"id": s.id, "name": s.name, "allowed": entered is None,
                    "reason": None if entered is None else f"{entered.fiscal_year_label} is entered on this series"})
    return out


def add_to_series(db: Session, ctx, f: Fundraiser, series_id: int) -> FundraiserSeries:
    """2.2.0 (#302): put a fundraiser in no series into an existing one - e.g. the second of an event held twice a
    year, in its first year in PennyWarden (nothing earlier to continue from). "Continues from" stays empty. Refused
    when the series has an active entered result for the fundraiser's year. Audited like a link change."""
    if f.series_id is not None:
        raise AppError(409, "ALREADY_IN_SERIES", "This fundraiser is already in a series. To combine two series, "
                       "use Merge into… on Fundraiser series.")
    s = _series(db, ctx, series_id)
    year = fundraiser_year(db, f)
    entered = db.scalar(select(FundraiserSeriesResult).where(FundraiserSeriesResult.series_id == s.id,
                                                             FundraiserSeriesResult.year == year,
                                                             FundraiserSeriesResult.retired_at.is_(None)))
    if entered is not None:
        raise AppError(409, "YEAR_ENTERED", f"{s.name} already has an entered result for {entered.fiscal_year_label}, "
                       "the year of this fundraiser. Retire it first, so the year is not counted twice.")
    before = _link_snapshot(f)
    f.series_id = s.id
    db.flush()
    audit.record(db, ctx, "FUNDRAISER_SERIES_LINK_UPDATED", "fundraiser", f.id, before, _link_snapshot(f))
    return s


def update_series(db: Session, ctx, s: FundraiserSeries, name: str | None, group_as_other: bool | None) -> None:
    before = {"name": s.name, "group_as_other": s.group_as_other}
    if name is not None:
        s.name = name
    if group_as_other is not None:
        s.group_as_other = group_as_other
    after = {"name": s.name, "group_as_other": s.group_as_other}
    if after != before:
        db.flush()
        audit.record(db, ctx, "FUNDRAISER_SERIES_UPDATED", "fundraiser_series", s.id, before, after)


def _app_years(db: Session, s: FundraiserSeries) -> set[int]:
    return {fundraiser_year(db, f) for f in db.scalars(select(Fundraiser).where(Fundraiser.series_id == s.id))}


def _cents(v, field, allow_negative=False, required=True):
    if v in (None, ""):
        if required:
            raise validation("This amount is required.", field)
        return None
    try:
        return parse_amount(v, allow_negative=allow_negative, allow_zero=True)
    except ValueError as e:
        raise validation(str(e).capitalize() + ".", field) from None


def add_result(db: Session, ctx, s: FundraiserSeries, body) -> FundraiserSeriesResult:
    label = body.fiscal_year_label.strip()
    year = label_year(label)
    if year is None:
        raise validation("Include the year in the Fiscal Year label, for example FY2019.", "fiscal_year_label")
    if year in _app_years(db, s):
        raise AppError(409, "YEAR_RECORDED", f"{label}: this series already has a fundraiser in PennyWarden for that "
                       "year, so its figures come from there.")
    dup = db.scalar(select(FundraiserSeriesResult).where(FundraiserSeriesResult.series_id == s.id,
                                                         FundraiserSeriesResult.year == year,
                                                         FundraiserSeriesResult.retired_at.is_(None)))
    if dup is not None:
        raise AppError(409, "YEAR_ENTERED", f"{label}: a result is already entered for that year; retire it first.")
    r = FundraiserSeriesResult(series_id=s.id, fiscal_year_label=label, year=year,
                               net_cents=_cents(body.net, "net", allow_negative=True),
                               income_cents=_cents(body.income, "income", required=False),
                               expense_cents=_cents(body.expense, "expense", required=False),
                               note=(body.note or "").strip() or None, created_by_user_id=ctx.user.id)
    db.add(r)
    db.flush()
    audit.record(db, ctx, "FUNDRAISER_RESULT_ENTERED", "fundraiser_series", s.id, None, _result_out(r))
    return r


def retire_result(db: Session, ctx, s: FundraiserSeries, result_id: int, reason: str) -> None:
    r = db.get(FundraiserSeriesResult, result_id)
    if r is None or r.series_id != s.id:
        raise not_found("Entered result")
    if r.retired_at is not None:
        raise AppError(409, "ALREADY_RETIRED", "This entered result is already retired.")
    before = _result_out(r)
    r.retired_at, r.retired_by_user_id, r.retire_reason = utcnow(), ctx.user.id, reason
    db.flush()
    audit.record(db, ctx, "FUNDRAISER_RESULT_RETIRED", "fundraiser_series", s.id, before, _result_out(r))


def merge(db: Session, ctx, s: FundraiserSeries, into: FundraiserSeries) -> None:
    """Moves the fundraisers and entered results into `into`. Refused when both have an entered result for the same
    year (retire one first, so nothing is counted twice)."""
    if s.id == into.id:
        raise validation("Choose another series to merge into.", "into_series_id")
    active = lambda x: {r.year for r in db.scalars(select(FundraiserSeriesResult).where(  # noqa: E731
        FundraiserSeriesResult.series_id == x.id, FundraiserSeriesResult.retired_at.is_(None)))}
    both = active(s) & active(into)
    if both:
        raise AppError(409, "ENTERED_RESULT_CONFLICT", "Both series have an entered result for "
                       + ", ".join(str(y) for y in sorted(both)) + ". Retire one of them first.")
    moved_f = list(db.scalars(select(Fundraiser).where(Fundraiser.series_id == s.id)))
    moved_r = list(db.scalars(select(FundraiserSeriesResult).where(FundraiserSeriesResult.series_id == s.id)))
    for f in moved_f:
        f.series_id = into.id
    for r in moved_r:
        r.series_id = into.id
    s.merged_into_id = into.id
    db.flush()
    audit.record(db, ctx, "FUNDRAISER_SERIES_MERGED", "fundraiser_series", s.id,
                 {"name": s.name, "fundraiser_ids": [f.id for f in moved_f], "result_ids": [r.id for r in moved_r]},
                 {"merged_into_id": into.id, "merged_into_name": into.name})


def series_history(db: Session, ctx, f: Fundraiser, current: dict) -> list[dict]:
    """Year over year for one fundraiser: every year of its series up to its own year, oldest first. A year is the
    sum of the series' fundraisers counted in it (Recorded) or its entered result (Entered). `current` holds this
    fundraiser's own totals (avoids computing them twice)."""
    from .fundraiser_summary import pct, summary
    me = fundraiser_year(db, f)
    root = f.series_id
    seen = set()
    while root and root not in seen:
        seen.add(root)
        s = db.get(FundraiserSeries, root)
        if s is None or not s.merged_into_id:
            break
        root = s.merged_into_id
    years: dict[int, dict] = {}

    def cell(y):
        return years.setdefault(y, {"year": y, "names": [], "income": 0, "expense": 0, "net": 0, "partial": False,
                                    "sources": set(), "notes": []})
    c = cell(me)
    c["names"].append(f.name)
    c["sources"].add("Recorded")
    c["income"] += _c(current["net_revenue"])
    c["expense"] += _c(current["expenses"])
    c["net"] += _c(current["net_proceeds"])
    if root:
        members = set(db.scalars(select(Fundraiser.id).where(Fundraiser.series_id.in_(
            [root] + list(db.scalars(select(FundraiserSeries.id).where(FundraiserSeries.merged_into_id == root)))))))
        for other in db.scalars(select(Fundraiser).where(Fundraiser.id.in_(members), Fundraiser.id != f.id)):
            y = fundraiser_year(db, other)
            if y > me:
                continue
            t = summary(db, ctx, other, itemized=False, names=False, history=False)["totals"]
            c = cell(y)
            c["names"].append(other.name)
            c["sources"].add("Recorded")
            c["income"] += _c(t["net_revenue"])
            c["expense"] += _c(t["expenses"])
            c["net"] += _c(t["net_proceeds"])
        for r in db.scalars(select(FundraiserSeriesResult).where(FundraiserSeriesResult.series_id == root,
                                                                 FundraiserSeriesResult.retired_at.is_(None))):
            if r.year >= me:
                continue
            c = cell(r.year)
            c["names"].append(r.fiscal_year_label)
            c["sources"].add("Entered")
            c["net"] += r.net_cents
            if r.income_cents is None or r.expense_cents is None:
                c["partial"] = True
            c["income"] += r.income_cents or 0
            c["expense"] += r.expense_cents or 0
            if r.note:
                c["notes"].append(r.note)
    out, prev = [], None
    for y in sorted(years):
        c = years[y]
        row = {"year": y, "label": ", ".join(c["names"]), "source": " + ".join(sorted(c["sources"])),
               "net_revenue": None if c["partial"] else fmt(c["income"]),
               "expenses": None if c["partial"] else fmt(c["expense"]), "net_proceeds": fmt(c["net"]),
               "net_margin": None if c["partial"] else pct(c["net"], c["income"]), "note": "; ".join(c["notes"]) or None,
               "change": None, "change_pct": None}
        if prev is not None:
            row["change"] = fmt(c["net"] - prev)
            row["change_pct"] = pct(c["net"] - prev, abs(prev)) if prev else None
        prev = c["net"]
        out.append(row)
    return out


def _c(v: str) -> int:
    return int(round(float(v) * 100))


# ------------------------------------------------------------------ "Create next year's from this one"
def next_year_draft(db: Session, ctx, f: Fundraiser) -> dict:
    """Pre-filled values for the create form; everything stays editable before saving."""
    def plus_year(d: dt.date) -> dt.date:
        try:
            return d.replace(year=d.year + 1)
        except ValueError:            # 29 February
            return d.replace(year=d.year + 1, day=28)
    budget_ids = []
    for fb in f.budgets:
        nxt = bsvc._continued_by(db, fb.budget_id)
        if nxt is not None and nxt.status not in ("DELETED", "REJECTED", "INACTIVE"):
            budget_ids.append(nxt.id)
    return {"name": next_name(f.name), "description": f.description, "start_date": plus_year(f.start_date).isoformat(),
            "end_date": plus_year(f.end_date).isoformat(), "filter_text": f.filter_text, "filter_regex": bool(f.filter_regex),
            "budget_ids": budget_ids, "continues_from_id": f.id, "copy_buckets_from_id": f.id,
            "buckets": [b.name for b in fsvc.ordered_buckets(db, f)],
            "categories": [c.name for c in fsvc.ordered_categories(db, f)]}


def copy_buckets(db: Session, ctx, src: Fundraiser, dst: Fundraiser) -> None:
    """Categories and buckets (names, descriptions, order), without amounts."""
    cat_map = {}
    for c in fsvc.ordered_categories(db, src):
        n = FundraiserBucketCategory(fundraiser_id=dst.id, name=c.name, description=c.description,
                                     display_order=c.display_order, created_by_user_id=ctx.user.id)
        db.add(n)
        db.flush()
        cat_map[c.id] = n.id
    for b in fsvc.ordered_buckets(db, src):
        db.add(FundraiserBucket(fundraiser_id=dst.id, name=b.name, description=b.description,
                                category_id=cat_map.get(b.category_id), display_order=b.display_order,
                                created_by_user_id=ctx.user.id))
    db.flush()
    audit.record(db, ctx, "FUNDRAISER_BUCKETS_COPIED", "fundraiser", dst.id, None,
                 {"from_fundraiser_id": src.id, "categories": len(cat_map),
                  "buckets": len(fsvc.ordered_buckets(db, dst))})


# ------------------------------------------------------------------ report notes
def get_notes(db: Session, ctx, fy: FiscalYear) -> str | None:
    n = db.scalar(select(FundraiserFyReportNote).where(FundraiserFyReportNote.fiscal_year_id == fy.id))
    return n.notes if n else None


def set_notes(db: Session, ctx, fy: FiscalYear, notes: str | None) -> str | None:
    notes = (notes or "").strip() or None
    n = db.scalar(select(FundraiserFyReportNote).where(FundraiserFyReportNote.fiscal_year_id == fy.id))
    before = n.notes if n else None
    if before == notes:
        return notes
    if n is None:
        n = FundraiserFyReportNote(workspace_id=ctx.workspace_id, fiscal_year_id=fy.id)
        db.add(n)
    n.notes, n.updated_by_user_id = notes, ctx.user.id
    db.flush()
    audit.record(db, ctx, "FUNDRAISER_FY_REPORT_NOTES_UPDATED", "fiscal_year", fy.id, {"notes": before}, {"notes": notes})
    return notes


# ------------------------------------------------------------------ the Fiscal Year report
def _pct(part: int, whole: int) -> str | None:
    from .fundraiser_summary import pct
    return pct(part, whole)


def default_selection(db: Session, ctx, fy: FiscalYear) -> list[int]:
    """Every non-archived, non-cancelled fundraiser whose event starts in the Fiscal Year."""
    y = fy_year(fy)
    return [f.id for f in db.scalars(select(Fundraiser).where(Fundraiser.workspace_id == ctx.workspace_id,
                                                              Fundraiser.archived_at.is_(None),
                                                              Fundraiser.cancelled_at.is_(None)))
            if fundraiser_year(db, f) == y]


def fy_report(db: Session, ctx, fy: FiscalYear, ids: list[int], *, years: int = 5, targeted: bool = False,
              avg_years: int = 5, notes: str | None = None) -> dict:
    from .fundraiser_summary import report_status, summary
    Y = fy_year(fy)
    selected = []
    for fid in dict.fromkeys(ids):
        f = fsvc.get(db, ctx, fid)
        selected.append(f)
    if not selected:
        raise validation("Choose at least one fundraiser.", "ids")
    all_f = list(db.scalars(select(Fundraiser).where(Fundraiser.workspace_id == ctx.workspace_id)))
    series = {s.id: s for s in db.scalars(select(FundraiserSeries).where(FundraiserSeries.workspace_id == ctx.workspace_id))}

    def root(sid):  # follow merges
        while sid in series and series[sid].merged_into_id:
            sid = series[sid].merged_into_id
        return sid

    def key_of(f: Fundraiser):
        return ("s", root(f.series_id)) if f.series_id else ("f", f.id)

    def name_of(key) -> str:
        if key[0] == "s":
            return series[key[1]].name
        return next(f.name for f in all_f if f.id == key[1])

    cache: dict[int, dict] = {}

    def figures(f: Fundraiser) -> dict:
        if f.id not in cache:
            cache[f.id] = summary(db, ctx, f, itemized=False, names=False)["totals"]
        return cache[f.id]

    # this year: the selected fundraisers
    rows, year_total = [], 0
    for f in sorted(selected, key=lambda x: (x.start_date, x.name)):
        t = figures(f)
        net = int(round(float(t["net_proceeds"]) * 100))
        year_total += net
        rows.append({"id": f.id, "name": f.name, "start_date": f.start_date.isoformat(), "end_date": f.end_date.isoformat(),
                     "status": report_status(db, f)["text"], "net_revenue": t["net_revenue"], "expenses": t["expenses"],
                     "net_proceeds": t["net_proceeds"], "net_margin": t["net_margin"], "_net": net, "key": key_of(f)})
    for r in rows:
        r["share"] = _pct(r["_net"], year_total)
    top = max(rows, key=lambda r: r["_net"]) if rows else None

    # history: recorded (fundraisers in the app, counted in their start year) and entered results
    hist: dict[tuple, dict[int, dict]] = {}   # key -> year -> {amount, kinds, notes}

    def add(key, year, cents, kind, note=None):
        cell = hist.setdefault(key, {}).setdefault(year, {"amount": 0, "kinds": set(), "notes": []})
        cell["amount"] += cents
        cell["kinds"].add(kind)
        if note:
            cell["notes"].append(note)
    for r in rows:
        add(r["key"], Y, r["_net"], "Recorded")
    for f in all_f:
        yr = fundraiser_year(db, f)
        if yr < Y:
            add(key_of(f), yr, int(round(float(figures(f)["net_proceeds"]) * 100)), "Recorded")
    entered_any = False
    for r in db.scalars(select(FundraiserSeriesResult).where(FundraiserSeriesResult.retired_at.is_(None))):
        if root(r.series_id) in series and series[root(r.series_id)].workspace_id == ctx.workspace_id and r.year < Y:
            add(("s", root(r.series_id)), r.year, r.net_cents, "Entered", r.note)
            entered_any = True
    # only the series of the selected fundraisers and those with history are relevant; every series with any year
    all_years = sorted({y for v in hist.values() for y in v})
    first = min(all_years) if all_years else Y
    start = first if years < 0 else max(first, Y - max(years, 1) + 1)
    period = list(range(start, Y + 1))
    year_totals = {y: sum(v.get(y, {}).get("amount", 0) for v in hist.values()) for y in period}
    keys = sorted({k for k, v in hist.items() if any(y in v for y in period)}, key=lambda k: name_of(k).casefold())

    # targeted total: an estimate for each series that has not held its event yet this year
    estimates = []
    if targeted:
        held_keys = {r["key"] for r in rows if any(f.id == r["id"] and fsvc.status_of(f) not in ("PLANNED",) for f in selected)}
        for k, v in hist.items():
            if k[0] != "s" or k in held_keys:
                continue
            prior = sorted((y for y in v if y < Y), reverse=True)[:max(avg_years, 1)]
            if not prior:
                continue
            avg = _round(Fraction(sum(v[y]["amount"] for y in prior), len(prior)))
            ytd = v.get(Y, {}).get("amount", 0)
            extra = max(0, avg - ytd)
            if extra:
                estimates.append({"series": name_of(k), "years": len(prior), "average": fmt(avg), "ytd": fmt(ytd),
                                  "estimate": fmt(extra)})
    est_total = sum(int(round(float(e["estimate"]) * 100)) for e in estimates)

    # shares over the period, with Other
    period_total = sum(year_totals.values())
    per_series = []
    for k in keys:
        cells = {y: hist[k][y] for y in period if y in hist[k]}
        total = sum(c["amount"] for c in cells.values())
        active = len(cells)
        per_series.append({"name": name_of(k), "total": fmt(total), "_total": total, "active_years": active,
                           "average": fmt(_round(Fraction(total, active))) if active else "0.00",
                           "group_as_other": k[0] == "s" and series[k[1]].group_as_other})
    share, other_members, other_total = [], [], 0
    for p in sorted(per_series, key=lambda x: -x["_total"]):
        small = period_total > 0 and Fraction(p["_total"], period_total) < OTHER_SHARE
        if p["group_as_other"] or small:
            other_members.append(p["name"])
            other_total += p["_total"]
        else:
            share.append({"name": p["name"], "total": p["total"], "share": _pct(p["_total"], period_total)})
    if other_members:
        share.append({"name": "Other", "total": fmt(other_total), "share": _pct(other_total, period_total),
                      "members": sorted(other_members)})

    # year over year by series (#277 feedback): each series' amount per year and the change on the year before
    yoy = []
    for k in keys:
        vals = [hist[k][y]["amount"] if y in hist[k] else None for y in period]
        last = hist[k].get(Y, {}).get("amount")
        before = next((hist[k][y]["amount"] for y in sorted(hist[k], reverse=True) if y < Y), None)
        yoy.append({"name": name_of(k), "values": [fmt(v) if v is not None else None for v in vals],
                    "change": fmt(last - before) if last is not None and before is not None else None,
                    "change_pct": (_pct(last - before, abs(before)) if last is not None and before else None)})

    history_rows = []
    for k in keys:
        for y in period:
            c = hist[k].get(y)
            if c:
                history_rows.append({"year": y, "series": name_of(k), "amount": fmt(c["amount"]),
                                     "source": " + ".join(sorted(c["kinds"])), "note": "; ".join(c["notes"]) or None})
    history_rows.sort(key=lambda r: (r["year"], r["series"].casefold()))
    prev = year_totals.get(Y - 1)
    linked_history = any(y < Y for y in all_years)
    fy_ended = dt.date.today() > fy.end_date
    peak = max(period, key=lambda y: year_totals[y]) if period else Y
    foot = []
    for f in selected:
        fys = fsvc._fys_of(db, f)
        if len(fys) > 1 or (fys and fy_year(fys[0]) != Y):
            foot.append(f"{f.name} has activity in more than one Fiscal Year; it counts wholly in the year its event "
                        f"starts ({fundraiser_year(db, f)}).")
    if entered_any:
        foot.append("Entered = a result of a year before PennyWarden entered by hand; Recorded = from the fundraisers "
                    "in PennyWarden.")
    if estimates:
        foot.append("Targeted total = this year's figures so far plus, for each series that has not held its event yet "
                    f"this year, the average of its last {avg_years} active years (less what it already has this year).")
    if other_members:
        foot.append("Other combines series marked Group as Other and series under 5% of the period total: "
                    + ", ".join(sorted(other_members)) + ".")
    return {
        "fiscal_year": fy_brief(fy), "year": Y, "period": period, "years_option": years, "targeted": targeted,
        "avg_years": avg_years, "linked_history": linked_history, "fy_ended": fy_ended,
        "this_year": [{k: v for k, v in r.items() if not k.startswith("_") and k != "key"} for r in rows],
        "year_total": fmt(year_total), "top": ({"name": top["name"], "net": fmt(top["_net"]), "share": top["share"]}
                                              if top else None),
        "growth_vs_last": _pct(year_total - prev, prev) if prev else None,
        "growth_vs_first": (_pct(year_total - year_totals[period[0]], year_totals[period[0]])
                            if len(period) > 1 and year_totals[period[0]] else None),
        "cumulative": fmt(period_total), "peak_year": peak, "peak_total": fmt(year_totals.get(peak, 0)),
        "trend": [{"year": y, "total": fmt(year_totals[y]), "current": y == Y} for y in period],
        "estimates": estimates, "estimate_total": fmt(est_total), "targeted_total": fmt(year_total + est_total),
        "share": share, "averages": [{k: v for k, v in p.items() if not k.startswith("_")} for p in per_series],
        "history": history_rows, "notes": notes, "footnotes": foot, "year_over_year": yoy if linked_history else [],
        "generated_at": utcnow().isoformat(timespec="seconds") + "Z",
        "selected_ids": [f.id for f in selected],
    }


def _round(x: Fraction) -> int:
    n = int(abs(x) + Fraction(1, 2))
    return n if x >= 0 else -n
