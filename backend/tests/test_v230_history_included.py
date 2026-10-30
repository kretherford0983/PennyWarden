"""2.3.0 (#414): a Budget Manager marks, on a budget's History, the years its money was included in another budget
(no figures of its own); the Budget Review shows "included in ..." there instead of "—". Decisions (Kyle,
2026-10-30): any budget of the same type at any level, former or PennyWarden; years before and in PennyWarden; shown
only on the marked budget; not counted in Avg; #415's automatic "history on parent" stays for parents without
sub-budgets. Never deleted (BR-001), audited, reporting only (BR-048), Budget Managers mark (BR-003)."""
from __future__ import annotations

import io

from pypdf import PdfReader

AS_OF = "2026-09-30"


def _former(env, code, name, btype="EXPENSE"):
    r = env.bm.post("/api/budgets/former", {"code": code, "name": name, "budget_type": btype})
    assert r.status_code == 201, r.text
    return r.json()


def _year(env, former_id, label, budgeted, actual):
    r = env.bm.post(f"/api/budgets/former/{former_id}/entries",
                    {"fiscal_year_label": label, "budgeted": budgeted, "actual": actual})
    assert r.status_code == 201, r.text


def _mark(env, budget_id, expect=201, client=None, **body):
    r = (client or env.bm).post(f"/api/budgets/{budget_id}/history/inclusions", body)
    assert r.status_code == expect, r.text
    return r.json()


def _review(env, fy_id, **q):
    r = env.bm.get("/api/reports/budget-review", params={"fiscal_year_id": fy_id, "as_of": AS_OF, "years": 5, **q})
    assert r.status_code == 200, r.text
    return r.json() if q.get("format", "json") == "json" else r


def _row(rep, rid):
    return next(r for s in ("income", "expense") for r in rep[s] if r["id"] == rid)


def _audit(env, action):
    return env.auditor.get(f"/api/audit-events?action={action}").json()["items"]


def _kiwanis(env, base):
    """Kyle's case: 100-05 Kiwanis is new in this Fiscal Year; in FY2025 its money was in 102 Fundraisers (a budget
    from before PennyWarden), which today's 1000-00 Other continues. FY2024 had nothing of it."""
    fr = _former(env, "102", "Fundraisers")
    _year(env, fr["id"], "FY2025", "900.00", "950.00")
    _year(env, fr["id"], "FY2024", "800.00", "700.00")
    kiw = env.budget(base["fy"]["id"], "05", "Kiwanis", amount="50.00", parent=base["exp"]["id"])
    r = env.bm.put(f"/api/budgets/{_other(env, base['fy']['id'], base['exp']['id'])}/former-link",
                   {"former_budget_id": fr["id"]})
    assert r.status_code == 200, r.text
    return fr, kiw


def _other(env, fy_id, parent_id):
    tree = env.bm.get(f"/api/budgets?fiscal_year_id={fy_id}").json()
    return next(c["id"] for r in tree["expense"] if r["id"] == parent_id for c in r["children"] if c["is_other"])


def test_mark_a_year_before_pennywarden(env, base):
    fr, kiw = _kiwanis(env, base)
    opts = env.bm.get(f"/api/budgets/{kiw['id']}/history/inclusion-options").json()
    assert [f["label"] for f in opts["formers"]] == ["102 Fundraisers → 1000-00 Other"]
    m = _mark(env, kiw["id"], fiscal_year_label="FY2025", included_former_budget_id=fr["id"], note="Kiwanis night")
    assert m["text"] == "included in 102 Fundraisers → 1000-00 Other" and m["in_pennywarden"] is False
    rep = _review(env, base["fy"]["id"])
    labels = [y["display_name"] for y in rep["years"]]
    k = _row(rep, kiw["id"])
    i25, i24 = labels.index("FY2025"), labels.index("FY2024")
    assert k["history"][i25] is None and k["history_notes"][i25] == "included in 102 Fundraisers → 1000-00 Other"
    assert k["history_notes"][i24] is None                              # unmarked: "—"
    assert k["average"] is None                                         # no figures: not counted in Avg
    assert k["history_note"] is None
    # shown only on the marked budget: the other budget's cell is unchanged
    o = next(r for r in rep["expense"] if r["is_other"] and r["parent_id"] == base["exp"]["id"])
    assert o["history"][i25]["budgeted"] == "900.00" and o["history_notes"][i25] is None
    # the History lists it
    v = env.bm.get(f"/api/budgets/{kiw['id']}/history/entered").json()
    assert [(x["fiscal_year_label"], x["included_in"], x["note"], x["counted"]) for x in v["inclusions"]] == [
        ("FY2025", "102 Fundraisers → 1000-00 Other", "Kiwanis night", True)]
    # CSV and PDF print the text
    assert "included in 102 Fundraisers → 1000-00 Other" in _review(env, base["fy"]["id"], format="csv").text
    pdf = _review(env, base["fy"]["id"], format="pdf")
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "included in 102 Fundraisers, now 1000-00 Other" in " ".join(text.split())   # no arrow glyph in the PDF font
    a = _audit(env, "BUDGET_HISTORY_INCLUSION_MARKED")
    assert a and a[0]["after"]["marked_on_budget_id"] == kiw["id"]


def test_a_mark_takes_the_place_of_history_on_parent(env, base):
    """#415's automatic note stays where the parent had one amount of its own; a mark in that year comes first."""
    fr = _former(env, "102", "Fundraisers")
    _year(env, fr["id"], "FY2025", "10.00", "10.00")
    r = env.bm.post(f"/api/budgets/{base['exp']['id']}/history/entered",
                    {"fiscal_year_label": "FY2025", "budgeted": "600.00", "actual": "470.00"})
    assert r.status_code == 201, r.text
    r = env.bm.post(f"/api/budgets/{base['exp']['id']}/history/entered",
                    {"fiscal_year_label": "FY2024", "budgeted": "500.00", "actual": "400.00"})
    assert r.status_code == 201, r.text
    kiw = env.budget(base["fy"]["id"], "05", "Kiwanis", amount="50.00", parent=base["exp"]["id"])
    rep = _review(env, base["fy"]["id"])
    labels = [y["display_name"] for y in rep["years"]]
    assert _row(rep, kiw["id"])["history_notes"] == ["history on parent"] * len(labels)
    _mark(env, kiw["id"], fiscal_year_label="FY2025", included_former_budget_id=fr["id"])
    k = _row(_review(env, base["fy"]["id"]), kiw["id"])
    assert k["history_notes"][labels.index("FY2025")] == "included in 102 Fundraisers"
    assert k["history_notes"][labels.index("FY2024")] == "history on parent"


def test_mark_a_year_in_pennywarden(env, base):
    """Kyle: years in PennyWarden too - a sub-budget split out of Other whose money sat in Other the year before."""
    fy26 = env.fy("2026", "2025-07-01", "2026-06-30")
    ops26 = env.budget(fy26["id"], "1000", "Operations", amount="900.00")
    env.budget(fy26["id"], "01", "Travel", amount="100.00", parent=ops26["id"])
    other26 = _other(env, fy26["id"], ops26["id"])
    inc26 = env.budget(fy26["id"], "4000", "Donations", "INCOME", "10.00")
    kiw = env.budget(base["fy"]["id"], "05", "Kiwanis", amount="50.00", parent=base["exp"]["id"])
    opts = env.bm.get(f"/api/budgets/{kiw['id']}/history/inclusion-options").json()
    fy_opt = next(y for y in opts["fiscal_years"] if y["id"] == fy26["id"])
    assert other26 in [b["id"] for b in fy_opt["budgets"]] and inc26["id"] not in [b["id"] for b in fy_opt["budgets"]]
    # type must match
    _mark(env, kiw["id"], 422, fiscal_year_id=fy26["id"], included_budget_id=inc26["id"])
    # a budget of another Fiscal Year is refused
    _mark(env, kiw["id"], 422, fiscal_year_id=fy26["id"], included_budget_id=base["exp"]["id"])
    m = _mark(env, kiw["id"], fiscal_year_id=fy26["id"], included_budget_id=other26)
    assert m["in_pennywarden"] and m["text"] == "included in 1000-00 Other"
    rep = _review(env, base["fy"]["id"])
    i = [y["display_name"] for y in rep["years"]].index(fy26["display_name"])
    k = _row(rep, kiw["id"])
    assert k["history"][i] is None and k["history_notes"][i] == "included in 1000-00 Other"
    # the same year twice is refused; retire, then it can be marked again
    _mark(env, kiw["id"], 409, fiscal_year_id=fy26["id"], included_budget_id=other26)
    r = env.bm.post(f"/api/budgets/history-inclusions/{m['id']}/retire", {"reason": "wrong year"})
    assert r.status_code == 200 and r.json()["retired"], r.text
    assert _row(_review(env, base["fy"]["id"]), kiw["id"])["history_notes"][i] is None
    assert _audit(env, "BUDGET_HISTORY_INCLUSION_RETIRED")
    v = env.bm.get(f"/api/budgets/{kiw['id']}/history/entered").json()["inclusions"]
    assert v[0]["retired"] and v[0]["retire_reason"] == "wrong year"
    _mark(env, kiw["id"], fiscal_year_id=fy26["id"], included_budget_id=other26)


def test_refusals(env, base):
    fr, kiw = _kiwanis(env, base)
    inc_former = _former(env, "401", "Old donations", "INCOME")
    # type mismatch, years in PennyWarden as a label, a year of this budget or later, the line's own former
    _mark(env, kiw["id"], 422, fiscal_year_label="FY2025", included_former_budget_id=inc_former["id"])
    _mark(env, kiw["id"], 409, fiscal_year_label="FY2027", included_former_budget_id=fr["id"])
    _mark(env, kiw["id"], 422, fiscal_year_label="FY2025")
    other = next(r for r in _review(env, base["fy"]["id"])["expense"] if r["is_other"])
    _mark(env, other["id"], 409, fiscal_year_label="FY2025", included_former_budget_id=fr["id"])   # has figures
    _mark(env, kiw["id"], 422, fiscal_year_label="FY2025", included_former_budget_id=fr["id"], note="x" * 501)
    _mark(env, kiw["id"], 422, fiscal_year_label="FY2025", included_former_budget_id=fr["id"], extra="no")
    # Budget Managers only; every financial role and Auditors see the marks
    for c in (env.ru, env.auditor):
        _mark(env, kiw["id"], 403, client=c, fiscal_year_label="FY2025", included_former_budget_id=fr["id"])
    _mark(env, kiw["id"], fiscal_year_label="FY2025", included_former_budget_id=fr["id"])
    for c in (env.ru, env.auditor):
        r = c.get(f"/api/budgets/{kiw['id']}/history/entered")
        assert r.status_code == 200 and len(r.json()["inclusions"]) == 1
    # Budget 0 has no history to mark
    zero = next(o for o in env.selectable(base["fy"]["id"], "WITHDRAWAL") if o["label"].startswith("0 "))
    _mark(env, zero["id"], 422, fiscal_year_label="FY2025", included_former_budget_id=fr["id"])
