"""2.2.0 (#302, #351): Fundraiser series - "Add to an existing series" for an event held more than once a year, and
one list per series by year (newest first by default, flipped per user and remembered)."""
from __future__ import annotations

from test_v210_fundraiser_series import years  # noqa: F401  (fixture)


def _series(env, name, direction=None):
    q = f"?direction={direction}" if direction else ""
    return next(s for s in env.bm.get(f"/api/fundraiser-series{q}").json() if s["name"] == name)


def _fall_raffle(env, years):
    r = env.bm.post("/api/fundraisers", {"name": "Fall Raffle", "start_date": "2026-11-01",
                                         "budget_ids": [years["base"]["inc"]["id"]]})
    assert r.status_code == 201, r.text
    return r.json()


def test_twice_a_year_event_in_its_first_year(env, years):
    rid = years["raffle"]["id"]
    sid = env.bm.post(f"/api/fundraisers/{rid}/series").json()["series_id"]
    fall = _fall_raffle(env, years)
    opts = env.bm.get(f"/api/fundraisers/{fall['id']}/series-add-options").json()
    assert {o["name"]: o["allowed"] for o in opts} == {"Golf Outing": True, "Raffle": True}
    r = env.bm.put(f"/api/fundraisers/{fall['id']}/series", {"series_id": sid})
    assert r.status_code == 200, r.text
    assert r.json()["series_id"] == sid
    link = env.bm.get(f"/api/fundraisers/{fall['id']}").json()["series_link"]
    assert link["series"] == {"id": sid, "name": "Raffle"} and link["continues_from"] is None
    s = _series(env, "Raffle")
    # same year: recorded fundraisers by start date, newest first
    assert [(x["kind"], x["name"], x["year"]) for x in s["rows"]] == [("recorded", "Fall Raffle", 2027), ("recorded", "Raffle", 2027)]
    ev = env.auditor.get("/api/audit-events?action=FUNDRAISER_SERIES_LINK_UPDATED").json()["items"]
    assert any(str(e["object_id"]) == str(fall["id"]) and (e.get("after") or {}).get("series_id") == sid for e in ev)
    # already in a series: merge instead
    r = env.bm.put(f"/api/fundraisers/{fall['id']}/series", {"series_id": _series(env, "Golf Outing")["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ALREADY_IN_SERIES"


def test_add_refused_when_the_year_is_entered(env, years):
    sid = env.bm.post(f"/api/fundraisers/{years['raffle']['id']}/series").json()["series_id"]
    assert env.bm.post(f"/api/fundraiser-series/{sid}/results", {"fiscal_year_label": "FY2026", "net": "50.00"}).status_code == 201
    b26 = env.budget(years["f26"]["id"], "4200", "Raffle 2026", "INCOME", "100.00")
    old = env.bm.post("/api/fundraisers", {"name": "Raffle 2026", "start_date": "2025-10-01", "budget_ids": [b26["id"]]}).json()
    opts = {o["name"]: o for o in env.bm.get(f"/api/fundraisers/{old['id']}/series-add-options").json()}
    assert opts["Raffle"]["allowed"] is False and "FY2026" in opts["Raffle"]["reason"] and opts["Golf Outing"]["allowed"]
    r = env.bm.put(f"/api/fundraisers/{old['id']}/series", {"series_id": sid})
    assert r.status_code == 409 and r.json()["error"]["code"] == "YEAR_ENTERED"
    assert env.bm.get(f"/api/fundraisers/{old['id']}").json()["series_link"]["series"] is None
    rid = _series(env, "Raffle")["results"][0]["id"]
    assert env.bm.post(f"/api/fundraiser-series/{sid}/results/{rid}/retire", {"reason": "now in PennyWarden"}).status_code == 200
    assert env.bm.put(f"/api/fundraisers/{old['id']}/series", {"series_id": sid}).status_code == 200


def test_access(env, years):
    sid = env.bm.post(f"/api/fundraisers/{years['raffle']['id']}/series").json()["series_id"]
    fall = _fall_raffle(env, years)
    assert env.bu.get(f"/api/fundraisers/{fall['id']}/series-add-options").status_code == 403
    assert env.bu.put(f"/api/fundraisers/{fall['id']}/series", {"series_id": sid}).status_code == 403


def test_rows_by_year_both_directions(env, years):
    sid = _series(env, "Golf Outing")["id"]
    for label, net in (("FY2024", "400.00"), ("FY2025", "500.00")):
        assert env.bm.post(f"/api/fundraiser-series/{sid}/results", {"fiscal_year_label": label, "net": net}).status_code == 201
    old = next(r for r in _series(env, "Golf Outing")["results"] if r["year"] == 2025)
    assert env.bm.post(f"/api/fundraiser-series/{sid}/results/{old['id']}/retire", {"reason": "typo"}).status_code == 200
    assert env.bm.post(f"/api/fundraiser-series/{sid}/results", {"fiscal_year_label": "FY2025", "net": "550.00"}).status_code == 201

    def order(direction=None):
        return [(r["year"], r["kind"], r.get("retired", False)) for r in _series(env, "Golf Outing", direction)["rows"]]
    newest = [(2027, "recorded", False), (2026, "recorded", False), (2025, "entered", False), (2025, "entered", True),
              (2024, "entered", False)]
    assert order() == newest                                                  # the default
    assert order("asc") == [(2024, "entered", False), (2025, "entered", False), (2025, "entered", True),
                            (2026, "recorded", False), (2027, "recorded", False)]   # within a year: unchanged
    # the old lists stay as they were (oldest first)
    s = _series(env, "Golf Outing")
    assert [f["year"] for f in s["fundraisers"]] == [2026, 2027] and [r["year"] for r in s["results"]] == [2024, 2025, 2025]


def test_sort_remembered_per_user(env, years):
    assert env.bm.get("/api/auth/me").json()["fundraiser_series_sort"] == "desc"
    r = env.bm.put("/api/me/preferences", {"fundraiser_series_sort": "asc"})
    assert r.status_code == 200 and r.json()["fundraiser_series_sort"] == "asc"
    assert env.bm.get("/api/auth/me").json()["fundraiser_series_sort"] == "asc"
    assert [x["year"] for x in _series(env, "Golf Outing")["rows"]] == [2026, 2027]   # no ?direction: the user's choice
    # another user keeps the default
    assert env.admin.get("/api/auth/me").json()["fundraiser_series_sort"] == "desc"
    # mutations return the list in the user's order
    sid = _series(env, "Golf Outing")["id"]
    out = env.bm.post(f"/api/fundraiser-series/{sid}/results", {"fiscal_year_label": "FY2025", "net": "1.00"}).json()
    assert [x["year"] for x in next(s for s in out if s["id"] == sid)["rows"]] == [2025, 2026, 2027]
    assert env.bm.put("/api/me/preferences", {"fundraiser_series_sort": "desc"}).status_code == 200
    assert [x["year"] for x in _series(env, "Golf Outing")["rows"]] == [2027, 2026, 2025]
    assert env.bm.put("/api/me/preferences", {"fundraiser_series_sort": "sideways"}).status_code == 422
