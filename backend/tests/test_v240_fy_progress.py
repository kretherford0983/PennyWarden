"""2.4.0 (#553): the Dashboard's FY Progress box - the result so far (surplus / deficit), the projected year end (this
year so far + the median of the up to 3 previous Fiscal Years' rest of the year; this year's pace without one; not in
the first 3 months) and the budgeted result (BR-DASH-FYP-001..003, AC-DASH-FYP-001..004)."""
import datetime as dt

from sqlalchemy.orm import Session

from fmpoc.models import FiscalYear
from fmpoc.services import fy_progress as fyp

D = dt.date


def year(env, y, inc_budget="5000.00", exp_budget="3000.00"):
    fy = env.fy(str(y), f"{y}-01-01", f"{y}-12-31")
    inc = env.budget(fy["id"], "4000", "Donations", "INCOME", inc_budget)
    exp = env.budget(fy["id"], "1000", "Operations", "EXPENSE", exp_budget)
    return {"fy": fy, "inc": inc, "exp": exp}


def money_in(env, acct, y, kind, when, amount):
    ttype, b = ("DEPOSIT", y["inc"]) if kind == "in" else ("WITHDRAWAL", y["exp"])
    env.txn(acct["id"], ttype, [{"budget_id": b["id"], "amount": amount}], date=when)


def progress(env, fy_id, as_of):
    with Session(env.app.state.engine) as db:
        fy = db.get(FiscalYear, fy_id)
        from fmpoc.services import budgets as bsvc
        t = bsvc.tree(db, fy)
        return fyp.progress(db, fy, {"income": t["income_summary"], "expense": t["expense_summary"]}, as_of)


def history(env):
    """Three previous calendar years and the current one (2027); income comes in January and June, expenses later."""
    acct = env.account(opening="100000.00", primary=True, opening_balance_date="2023-01-01")
    y24, y25, y26, y27 = (year(env, y) for y in (2024, 2025, 2026, 2027))
    for n, y, rest_in, rest_out in ((2024, y24, "2000.00", "700.00"), (2025, y25, "2200.00", "800.00"),
                                    (2026, y26, "9000.00", "600.00")):    # 2026: a one-time $9,000 grant in June
        money_in(env, acct, y, "in", f"{n}-01-15", "1000.00")             # before the same point (Apr 30)
        money_in(env, acct, y, "in", f"{n}-06-01", rest_in)               # after it
        money_in(env, acct, y, "out", f"{n}-03-01", "500.00")
        money_in(env, acct, y, "out", f"{n}-09-01", rest_out)
    money_in(env, acct, y27, "in", "2027-01-15", "1500.00")
    money_in(env, acct, y27, "out", "2027-02-01", "400.00")
    return acct, y27


def test_projection_uses_the_median_of_three_previous_years(env):
    """AC-DASH-FYP-003: rest of the year income 2000 / 2200 / 9000 -> 2200 (the grant year is ignored); expenses
    700 / 800 / 600 -> 700. Projected: income 1500 + 2200, expenses 400 + 700 -> +2600."""
    _acct, y27 = history(env)
    p = progress(env, y27["fy"]["id"], D(2027, 4, 30))
    assert (p["result"], p["result_word"], p["income"], p["expense"]) == ("1100.00", "surplus", "1500.00", "400.00")
    assert (p["budgeted"], p["budgeted_word"]) == ("2000.00", "surplus")
    pr = p["projection"]
    assert pr["state"] == "PROJECTED" and (pr["income"], pr["expense"], pr["result"]) == ("3700.00", "1100.00", "2600.00")
    assert pr["basis"]["kind"] == "PREVIOUS_YEARS" and len(pr["basis"]["fiscal_years"]) == 3


def test_not_enough_information_in_the_first_three_months_and_the_final_result_after_the_year(env):
    """AC-DASH-FYP-002"""
    _acct, y27 = history(env)
    early = progress(env, y27["fy"]["id"], D(2027, 3, 30))
    assert early["projection"]["state"] == "TOO_EARLY" and early["projection"]["result"] is None
    assert early["result"] == "1100.00"                       # the result so far is shown anyway
    ended = progress(env, y27["fy"]["id"], D(2028, 1, 5))
    assert ended["projection"]["state"] == "YEAR_ENDED" and ended["projection"]["result"] == "1100.00"


def test_without_a_previous_year_this_years_pace(env):
    """AC-DASH-FYP-004: Jan-Apr is 4 of 12 months: income 1500 -> 4500, expenses 400 -> 1200."""
    acct = env.account(opening="1000.00", primary=True, opening_balance_date="2027-01-01")
    y27 = year(env, 2027)
    money_in(env, acct, y27, "in", "2027-01-15", "1500.00")
    money_in(env, acct, y27, "out", "2027-02-01", "400.00")
    pr = progress(env, y27["fy"]["id"], D(2027, 4, 30))["projection"]
    assert pr["basis"]["kind"] == "THIS_YEAR_PACE" and (pr["income"], pr["expense"], pr["result"]) == (
        "4500.00", "1200.00", "3300.00")


def test_a_deficit_is_worded_as_one(env):
    """AC-DASH-FYP-001"""
    acct = env.account(opening="9000.00", primary=True, opening_balance_date="2027-01-01")
    y27 = year(env, 2027, inc_budget="1000.00", exp_budget="4000.00")
    money_in(env, acct, y27, "out", "2027-02-01", "2500.00")
    p = progress(env, y27["fy"]["id"], D(2027, 2, 10))
    assert (p["result"], p["result_word"], p["budgeted"], p["budgeted_word"]) == ("-2500.00", "deficit", "-3000.00",
                                                                                  "deficit")


def test_median():
    assert fyp.median([2000000, 2200000, 4500000]) == 2200000
    assert fyp.median([100, 201]) == 151          # two years: their average, to the cent
    assert fyp.median([700]) == 700


def test_the_dashboard_carries_it(env, base):
    s = env.bm.get("/api/dashboard").json()["budget_summary"]
    assert {"result", "result_word", "budgeted", "projection"} <= set(s["progress"])
