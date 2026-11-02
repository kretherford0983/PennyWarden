"""2.3.0 build 4 (#382): the Budget Review lists the budgets of the years shown that are not in the chosen Fiscal Year.

Decisions (Kyle, 2026-10-29): mixed into Income and Expense (code order), tagged "not in <FY>, last <year>", shown under
the line's most recent code and name; lines group on the links (#89, #381), never on the code; averages over the years
with figures, no projection, no current-year figures; screen, PDF and CSV (and so the Planning Sheet's appended review).
"""
from __future__ import annotations

import csv
import io

from pypdf import PdfReader

AS_OF = "2026-09-30"


def _review(env, fy_id, client=None, **q):
    r = (client or env.bm).get("/api/reports/budget-review", params={"fiscal_year_id": fy_id, "as_of": AS_OF, "years": 5, **q})
    assert r.status_code == 200, r.text
    return r.json() if q.get("format", "json") == "json" else r


def _rows(rep, sec="expense"):
    return [(r["code"], r["name"], (r.get("not_in_year") or {}).get("last_year")) for r in rep[sec]]


def _years(env, base):
    fy26 = env.fy("2026", "2025-07-01", "2026-06-30")     # adjacent first (no gap warning)
    fy25 = env.fy("2025", "2024-07-01", "2025-06-30")
    return fy25, fy26


def test_a_dropped_line_shows_under_its_latest_name_with_its_years(env, base):
    fy25, fy26 = _years(env, base)
    b25 = env.budget(fy25["id"], "106", "Bowling", "EXPENSE", "800.00")
    b26 = env.budget(fy26["id"], "106", "Bowling Tournament", "EXPENSE", "900.00")
    assert env.bm.patch(f"/api/budgets/{b26['id']}", {"continues_budget_id": b25["id"]}).status_code == 200
    rep = _review(env, base["fy"]["id"])
    assert [y["display_name"] for y in rep["years"]] == ["FY2025", "FY2026"]
    # one row for the line (never two by code), under the most recent code and name, before 1000 Operations
    assert _rows(rep) == [("106", "Bowling Tournament", "FY2026"), ("1000", "Operations", None)]
    row = rep["expense"][0]
    assert row["not_in_year"] == {"fiscal_year": "FY2027", "last_year": "FY2026"}
    assert row["current"] is None and row["projection"] is None and row["next"] is None and row["state"] is None
    assert [c["budgeted"] for c in row["history"]] == ["800.00", "900.00"]
    assert row["history"][0]["renumbered"] is False and row["history"][0]["name"] == "Bowling"
    assert row["average"]["budgeted"] == "850.00" and row["average"]["years"] == 2
    # projected review: still no projection for it
    rep = _review(env, base["fy"]["id"], projected=True)
    assert rep["expense"][0]["projection"] is None


def test_a_line_that_continues_into_the_chosen_year_has_no_extra_row(env, base):
    fy25, fy26 = _years(env, base)
    o26 = env.budget(fy26["id"], "1000", "Operations", "EXPENSE", "90000.00")
    assert env.bm.patch(f"/api/budgets/{base['exp']['id']}", {"continues_budget_id": o26["id"]}).status_code == 200
    # same code, no link: a different line (links decide, never the code)
    env.budget(fy25["id"], "1000", "Old operations", "EXPENSE", "50.00")
    rep = _review(env, base["fy"]["id"])
    assert _rows(rep) == [("1000", "Operations", None), ("1000", "Old operations", "FY2025")]


def test_a_dropped_sub_budget_of_a_continuing_parent_gets_a_row(env, base):
    fy25, fy26 = _years(env, base)
    p26 = env.budget(fy26["id"], "4000", "Donations", "INCOME", "500.00")
    raffle = env.budget(fy26["id"], "04", "Raffle", "INCOME", "200.00", parent=p26["id"])
    assert env.bm.patch(f"/api/budgets/{base['inc']['id']}", {"continues_budget_id": p26["id"]}).status_code == 200
    rep = _review(env, base["fy"]["id"])
    assert ("4000-04", "Raffle", "FY2026") in _rows(rep, "income")
    assert all(r["id"] != raffle["id"] for r in rep["income"] if not r.get("not_in_year"))
    # a discontinued parent: its sub-budgets are in its figures, no rows of their own
    dropped = env.budget(fy26["id"], "4500", "Gala", "INCOME", "300.00")
    env.budget(fy26["id"], "01", "Tickets", "INCOME", "100.00", parent=dropped["id"])
    codes = [c for c, _n, _l in _rows(_review(env, base["fy"]["id"]), "income")]
    assert "4500" in codes and "4500-01" not in codes


def test_former_budgets_nothing_continues_and_ones_on_a_dropped_line(env, base):
    fy25, fy26 = _years(env, base)
    car = env.bm.post("/api/budgets/former", {"code": "98", "name": "Car Wash", "budget_type": "EXPENSE"}).json()
    assert env.bm.post(f"/api/budgets/former/{car['id']}/entries", {"fiscal_year_label": "FY2023", "budgeted": "50",
                                                                     "actual": "40"}).status_code == 201
    assert env.bm.post(f"/api/budgets/former/{car['id']}/entries", {"fiscal_year_label": "FY2024", "budgeted": "60",
                                                                     "actual": "55", "code": "99"}).status_code == 201
    bowl = env.bm.post("/api/budgets/former", {"code": "450", "name": "Bowling", "budget_type": "EXPENSE"}).json()
    env.bm.post(f"/api/budgets/former/{bowl['id']}/entries", {"fiscal_year_label": "FY2024", "budgeted": "700", "actual": "650"})
    b25 = env.budget(fy25["id"], "450", "Bowling Tournament", "EXPENSE", "800.00")
    assert env.bm.put(f"/api/budgets/{b25['id']}/former-link", {"former_budget_id": bowl["id"]}).status_code == 200
    rep = _review(env, base["fy"]["id"])
    assert [y["display_name"] for y in rep["years"]] == ["FY2023", "FY2024", "FY2025", "FY2026"]
    rows = {r["code"]: r for r in rep["expense"]}
    # the former budget nothing continues: its most recent code and name, its own years only
    cw = rows["99"]
    assert cw["name"] == "Car Wash" and cw["not_in_year"]["last_year"] == "FY2024"
    assert [c and c["actual"] for c in cw["history"]] == ["40.00", "55.00", None, None]
    assert cw["history"][0]["entered_as"] == "98 Car Wash"
    # the dropped PennyWarden line carries the entered years of the former budget it continues (one row)
    bt = rows["450"]
    assert bt["name"] == "Bowling Tournament" and bt["not_in_year"]["last_year"] == "FY2025"
    assert [c and c["actual"] for c in bt["history"]] == [None, "650.00", "0.00", None]
    assert sum(1 for r in rep["expense"] if r.get("not_in_year")) == 2
    # a filtered review (one budget, or one parent) shows only what was chosen
    one = _review(env, base["fy"]["id"], budget_id=base["exp"]["id"])
    assert [r["id"] for r in one["expense"]] == [base["exp"]["id"]]


def test_csv_and_pdf_carry_the_tag(env, base):
    fy25, fy26 = _years(env, base)
    env.budget(fy26["id"], "106", "Bowling Tournament", "EXPENSE", "900.00")
    c = _review(env, base["fy"]["id"], format="csv")
    rows = list(csv.reader(io.StringIO(c.text)))
    head, bowl = rows[0], next(r for r in rows if r[2] == "106")
    assert bowl[4] == "Not in FY2027, last FY2026"
    assert bowl[head.index("FY2027 budgeted")] == "—"
    p = _review(env, base["fy"]["id"], format="pdf", projected=True, include_next=True)
    text = " ".join(" ".join((pg.extract_text() or "").split()) for pg in PdfReader(io.BytesIO(p.content)).pages)
    assert "106 Bowling Tournament" in text and "not in FY2027, last FY2026" in text


def test_who_sees_it(env, base):
    fy25, fy26 = _years(env, base)
    env.budget(fy26["id"], "106", "Bowling Tournament", "EXPENSE", "900.00")
    assert env.admin.get("/api/reports/budget-review", params={"fiscal_year_id": base["fy"]["id"]}).status_code == 403
    for c in (env.bu, env.ru, env.auditor):
        r = c.get("/api/reports/budget-review", params={"fiscal_year_id": base["fy"]["id"], "as_of": AS_OF})
        assert r.status_code in (200, 403)          # the review's own permission rule is unchanged
