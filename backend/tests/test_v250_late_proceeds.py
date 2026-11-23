"""2.5.0 (#588): events whose proceeds are paid later by an outside organization (the county fair: held in August,
the check months later in the next Fiscal Year)."""
import io

from pypdf import PdfReader

from fmpoc.models import FiscalYear


def _text(pdf: bytes) -> str:
    return " ".join(" ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages).split())


def _set_status(env, fy_id: int, status: str) -> None:
    with env.app.state.session_factory() as db:
        db.get(FiscalYear, fy_id).status = status
        db.commit()


def _fair(env, base):
    """FY2027 (Jul-Jun): the fair in Aug 2026 with its supplies; FY2028: the fair board's check in Sep 2027 into the
    year's Donations budget (no budget of the fair's own) and next year's fair using the same budgets + a filter."""
    assert env.admin.put("/api/system/modules", {"fundraisers": True}).status_code == 200
    acct = base["acct"]["id"]
    board = env.entity("County Fair Board")
    env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "300.00", "description": "Fair supplies"}],
            date="2026-08-09")
    r = env.bm.post("/api/fundraisers", {"name": "2027 County Fair", "event_type": "EVENT", "start_date": "2026-08-10",
                                         "end_date": "2026-08-14", "budget_ids": [base["exp"]["id"]],
                                         "proceeds_later": True, "proceeds_payer_entity_id": board["id"],
                                         "proceeds_expected_month": "2027-09"})
    assert r.status_code == 201, r.text
    fair = r.json()
    fy28 = env.fy("2028", "2027-07-01", "2028-06-30")
    inc28 = env.budget(fy28["id"], "4000", "Donations", "INCOME", "8000.00")
    exp28 = env.budget(fy28["id"], "1000", "Operations", "EXPENSE", "8000.00")
    leaf_in = {o["label"]: o["id"] for o in env.selectable(fy28["id"], "DEPOSIT")}["4000 Donations"]
    leaf_ex = {o["label"]: o["id"] for o in env.selectable(fy28["id"], "WITHDRAWAL")}["1000 Operations"]
    dep = env.txn(acct, "DEPOSIT", [{"budget_id": leaf_in, "amount": "2500.00", "description": "Fair check 2026",
                                     "entity_id": board["id"]}], date="2027-09-15", entity_id=board["id"])
    env.txn(acct, "WITHDRAWAL", [{"budget_id": leaf_ex, "amount": "200.00", "description": "Fair supplies 2027"}],
            date="2027-08-01")
    r = env.bm.post("/api/fundraisers", {"name": "2028 County Fair", "event_type": "EVENT", "start_date": "2027-08-09",
                                         "budget_ids": [inc28["id"], exp28["id"]], "filter_text": "Fair",
                                         "proceeds_later": True, "proceeds_payer_entity_id": board["id"]})
    assert r.status_code == 201, r.text
    return {"fair": fair, "next": r.json(), "fy28": fy28, "board": board, "dep": dep}


def _alloc(env, fid: int, desc: str) -> int:
    cands = env.ru.get(f"/api/fundraisers/{fid}/proceeds-candidates").json()
    return next(c["allocation_id"] for c in cands if c["description"] == desc)


def test_awaiting_then_linked_and_received(env, base):
    s = _fair(env, base)
    fid = s["fair"]["id"]
    d = s["fair"]
    assert d["proceeds"]["awaiting"] and "expected September 2027" in d["proceeds"]["text"]
    assert "County Fair Board" in d["proceeds"]["text"]
    assert any(n["code"] == "AWAITING_PROCEEDS" for n in d["notices"])
    # the Dashboard / deposit question: events awaiting proceeds from this payer
    aw = env.ru.get(f"/api/fundraisers/awaiting-proceeds?entity_id={s['board']['id']}").json()
    assert {x["name"] for x in aw} == {"2027 County Fair", "2028 County Fair"}
    # the next fair (same budgets, filter "Fair") picks up the check before it is linked
    nxt = env.ru.get(f"/api/fundraisers/{s['next']['id']}").json()
    assert nxt["totals"]["income"] == "2500.00"
    # candidates: deposits dated on/after the event, the expected payer's first; link the check (Register User)
    cands = env.ru.get(f"/api/fundraisers/{fid}/proceeds-candidates").json()
    assert cands[0]["description"] == "Fair check 2026" and cands[0]["payer_match"]
    aid = cands[0]["allocation_id"]
    r = env.ru.post(f"/api/fundraisers/{fid}/proceeds-lines", {"allocation_id": aid})
    assert r.status_code == 201, r.text
    d = r.json()
    assert (d["totals"]["income"], d["totals"]["expense"], d["totals"]["net"]) == ("2500.00", "300.00", "2200.00")
    assert d["proceeds"]["received"] == "2500.00" and d["proceeds"]["lines"] == 1
    assert [p["fiscal_year"]["display_name"] for p in d["per_fiscal_year"]] == ["FY2027", "FY2028"]
    # counted once: the next fair leaves it out now
    assert env.ru.get(f"/api/fundraisers/{s['next']['id']}").json()["totals"]["income"] == "0.00"
    # a line is one event's proceeds at a time; only deposit lines
    assert env.bm.post(f"/api/fundraisers/{s['next']['id']}/proceeds-lines", {"allocation_id": aid}).status_code == 409
    wd = next(x["allocation_id"] for x in d["lines"] if x["description"] == "Fair supplies")
    assert env.ru.post(f"/api/fundraisers/{fid}/proceeds-lines", {"allocation_id": wd}).status_code == 422
    # still awaiting until marked: not final
    assert env.bm.put(f"/api/fundraisers/{fid}/results-final", {"final": True}).status_code == 409
    assert env.bm.put(f"/api/fundraisers/{fid}", {"name": "2027 County Fair", "event_type": "EVENT",
                                                  "start_date": "2026-08-10", "end_date": "2026-08-14",
                                                  "budget_ids": [base["exp"]["id"]], "proceeds_later": False}).status_code == 409
    r = env.ru.put(f"/api/fundraisers/{fid}/proceeds-outcome", {"outcome": "RECEIVED"})
    assert r.status_code == 200 and not r.json()["proceeds"]["awaiting"]
    assert r.json()["proceeds"]["text"] == "All proceeds received"
    assert env.bm.put(f"/api/fundraisers/{fid}/results-final", {"final": True}).status_code == 200
    ev = env.auditor.get(f"/api/audit-events?object_type=fundraiser&object_id={fid}").json()["items"]
    acts = {e["action"] for e in ev}
    assert {"FUNDRAISER_PROCEEDS_LINKED", "FUNDRAISER_PROCEEDS_OUTCOME"} <= acts


def test_no_proceeds_needs_a_budget_manager_and_a_reason(env, base):
    s = _fair(env, base)
    url = f"/api/fundraisers/{s['fair']['id']}/proceeds-outcome"
    assert env.ru.put(url, {"outcome": "NONE", "reason": "Fair cancelled"}).status_code == 403
    assert env.bm.put(url, {"outcome": "NONE"}).status_code == 422
    r = env.bm.put(url, {"outcome": "NONE", "reason": "The board kept the proceeds"})
    assert r.status_code == 200 and "No proceeds received (The board kept the proceeds)" == r.json()["proceeds"]["text"]
    assert env.ru.put(url, {"outcome": None}).json()["proceeds"]["awaiting"]          # back to awaiting


def test_never_final_while_awaiting_and_closed_years_are_budget_manager_only(env, base):
    s = _fair(env, base)
    fid = s["fair"]["id"]
    aid = _alloc(env, fid, "Fair check 2026")
    _set_status(env, base["fy"]["id"], "CLOSED")
    d = env.ru.get(f"/api/fundraisers/{fid}").json()
    assert d["report_status"]["code"] == "AWAITING_PROCEEDS" and not d["report_status"]["final"]
    _set_status(env, s["fy28"]["id"], "CLOSED")
    assert env.ru.post(f"/api/fundraisers/{fid}/proceeds-lines", {"allocation_id": aid}).status_code == 403
    d = env.bm.post(f"/api/fundraisers/{fid}/proceeds-lines", {"allocation_id": aid}).json()
    link = next(x["proceeds_link_id"] for x in d["lines"] if x["proceeds_link_id"])
    assert env.ru.post(f"/api/fundraisers/{fid}/proceeds-lines/{link}/unlink", {}).status_code == 403
    d = env.bm.post(f"/api/fundraisers/{fid}/proceeds-lines/{link}/unlink", {"reason": "Wrong check"}).json()
    assert d["proceeds"]["lines"] == 0 and d["totals"]["income"] == "0.00"
    ev = env.auditor.get(f"/api/audit-events?action=FUNDRAISER_PROCEEDS_UNLINKED").json()["items"]
    assert ev and ev[0]["after"]["retire_reason"] == "Wrong check"


def test_reporting_only_event_in_a_closed_year(env, base):
    assert env.admin.put("/api/system/modules", {"fundraisers": True}).status_code == 200
    _set_status(env, base["fy"]["id"], "CLOSED")
    r = env.bm.post("/api/fundraisers", {"name": "Old Fair", "event_type": "EVENT", "start_date": "2026-08-10",
                                         "budget_ids": [base["exp"]["id"]]})
    assert r.status_code == 201, r.text
    assert any(n["code"] == "REPORTING_ONLY" for n in r.json()["notices"])
    assert r.json()["report_status"]["final"]                               # every year closed, not awaiting
    # Register Users don't set up events at all
    assert env.ru.post("/api/fundraisers", {"name": "X", "start_date": "2026-08-10", "budget_ids": []}).status_code == 403


def test_reports_show_pending_and_proceeds_received_for_earlier_events(env, base):
    s = _fair(env, base)
    fid = s["fair"]["id"]
    # FY2027 audit report: the fair is pending
    text = _text(env.auditor.get(f"/api/reports/audit?fiscal_year_id={base['fy']['id']}&include_fundraisers=true").content)
    assert "Proceeds paid later: Proceeds pending — expected September 2027, County Fair Board" in text
    env.ru.post(f"/api/fundraisers/{fid}/proceeds-lines", {"allocation_id": _alloc(env, fid, "Fair check 2026")})
    # FY2028 audit report includes the 2027 fair (its proceeds arrived in FY2028)
    text = _text(env.auditor.get(f"/api/reports/audit?fiscal_year_id={s['fy28']['id']}&include_fundraisers=true").content)
    assert "Fundraiser — 2027 County Fair" in text and "1 deposit line(s) linked, $2,500.00 received" in text
    # FY2028 fundraising report: the check is listed as proceeds received for an earlier event
    rep = env.ru.get(f"/api/fundraisers/fy-report?fiscal_year_id={s['fy28']['id']}&ids={s['next']['id']}&format=json").json()
    assert [(x["event"], x["event_year"], x["amount"]) for x in rep["late_proceeds"]] == [("2027 County Fair", 2027, "2500.00")]
    assert rep["pending_proceeds"] and rep["pending_proceeds"][0]["name"] == "2028 County Fair"
    pdf = env.ru.get(f"/api/fundraisers/fy-report?fiscal_year_id={s['fy28']['id']}&ids={s['next']['id']}")
    assert "Proceeds received this year for earlier events" in _text(pdf.content)
    deck = env.ru.get(f"/api/fundraisers/fy-report?fiscal_year_id={s['fy28']['id']}&ids={s['next']['id']}&format=pptx")
    assert deck.status_code == 200
    # FY2027 report: the fair counts in its own year with the check
    rep27 = env.ru.get(f"/api/fundraisers/fy-report?fiscal_year_id={base['fy']['id']}&ids={fid}&format=json").json()
    assert rep27["events"][0]["net"] == "2200.00"


def test_module_off_awaiting_list_is_empty(env, base):
    _fair(env, base)
    env.admin.put("/api/system/modules", {"fundraisers": False})
    assert env.ru.get("/api/fundraisers/awaiting-proceeds").json() == []
