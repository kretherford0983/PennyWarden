"""2.2.0 (#325): Donations part 2 - donations recorded before a deposit, item (in-kind) donations, the Donations page
and Create transaction from donations. One donation model for both flows; part 1 data is migrated into it.

Decisions (Kyle, 2026-10-23): "received" decides (money when linked to a deposit, items when ticked Received); not
received prints "Date received" blank; items by description only with the (editable) items note, the total covers
money only; the register wins after linking; voiding a linked deposit unlinks Donations page lines (receipts stay
valid) but voids part 1 receipts; Cancel only while nothing is received; received lines in a Closed Fiscal Year are
locked; the Audit and Close reports list the items received in the year."""
from __future__ import annotations

import io

import pytest
from pypdf import PdfReader
from sqlalchemy import create_engine, text as sql

from test_v210_donations import dep, donor, enable, mark_all, print_receipt, setup, text  # noqa: F401

from fmpoc.services import donations as svc


@pytest.fixture
def don(env, base):
    enable(env)
    setup(env)
    return {"a": donor(env), "b": donor(env, "Sample Donor Two"), "base": base}


def _create(env, d, lines, who="a", client=None, details=""):
    r = (client or env.ru).post("/api/donations", {"donor_entity_id": d[who]["id"], "details": details,
                                                    "lines": lines})
    return r


def _ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def _print(env, did, confirmations=("NOT_RECEIVED", "EMPTY_VARIABLES"), client=None):
    return (client or env.ru).post(f"/api/donations/{did}/receipts", {"confirmations": list(confirmations)})


def test_receipt_before_the_money_then_create_transaction(env, don):
    base = don["base"]
    d = _ok(_create(env, don, [{"kind": "MONEY", "amount_cents": 100000, "purpose": "Flags"},
                               {"kind": "ITEM", "description": "Television, 55 inch", "amount_cents": 40000}]), 201)
    assert d["status"] == "AWAITING_DEPOSIT" and d["money"] == "$1,000.00" and d["items"] == 1 and d["awaiting"] == 1
    # not received: the receipt prints the date blank, asks first, and is kept with the donation
    r = _print(env, d["id"], confirmations=())
    assert r.status_code == 409 and "NOT_RECEIVED" in r.text
    r = _print(env, d["id"])
    assert r.status_code == 200, r.text
    t = text(r.content)
    assert "Date received ________________" in t and "$1,000.00" in t and "Television, 55 inch" in t
    assert "$400.00" not in t                                  # an item's estimate is never printed
    assert "does not assign a monetary value to donated property" in t
    first = r.headers["X-Receipt-Number"]
    v = _ok(env.bu.get(f"/api/donations/{d['id']}"))
    assert v["receipts"][0]["number"] == first and v["receipts"][0]["date_received"] is None
    assert [x["kind"] for x in v["documents"]] == ["DONATION_RECEIPT"]
    # the awaiting money line is offered for Create transaction
    aw = _ok(env.ru.get("/api/donations/awaiting-lines"))["items"]
    line = next(x for x in aw if x["donation_id"] == d["id"])
    assert line["amount"] == "$1,000.00"
    body = {"transaction": {"bank_account_id": base["acct"]["id"], "transaction_type": "DEPOSIT",
                            "transaction_date": "2026-08-10", "allocations": [
                                {"budget_id": base["inc_leaf"], "amount": "600.00", "description": "Gift"},
                                {"budget_id": base["inc_leaf"], "amount": "400.00", "description": "Gift"}]},
            "links": [line["id"], line["id"]], "date_received": "2026-08-08"}
    bad = {**body, "transaction": {**body["transaction"], "allocations": [
        {"budget_id": base["inc_leaf"], "amount": "600.00"}, {"budget_id": base["inc_leaf"], "amount": "300.00"}]}}
    r = env.ru.post("/api/donations/create-transaction", bad)
    assert r.status_code == 422 and "must add up" in r.text
    t = _ok(env.ru.post("/api/donations/create-transaction", body), 201)
    assert t["transaction_type"] == "DEPOSIT" and t["deposit"] == "1000.00"
    assert all(a["entity"]["id"] == don["a"]["id"] for a in t["allocations"])        # the donor carried over
    v = _ok(env.ru.get(f"/api/donations/{d['id']}"))
    money = [x for x in v["lines"] if x["kind"] == "MONEY"]
    assert len(money) == 2 and all(x["linked"] and x["deposit_id"] == t["id"] for x in money)
    assert {x["date_received"] for x in money} == {"2026-08-08"}
    assert v["status"] == "NOT_RECEIVED" and v["awaiting"] == 0       # the item isn't received yet
    atts = env.ru.get(f"/api/attachments?owner_type=transaction&owner_id={t['id']}").json()
    names = [a["original_filename"] for a in (atts["items"] if isinstance(atts, dict) else atts)]
    assert any(n.startswith(f"receipt-{first}") for n in names)       # the printed receipt went with the deposit
    # the item is received: now the receipt can print the dates, as a corrected receipt
    lines = [{"id": x["id"], "kind": x["kind"], "amount_cents": x["amount_cents"], "description": x["description"],
              "purpose": x["purpose"], "date_received": x["date_received"],
              "item_received": x["kind"] == "ITEM"} for x in v["lines"]]
    for x in lines:
        if x["kind"] == "ITEM":
            x["date_received"] = "2026-08-12"
    v = _ok(env.ru.put(f"/api/donations/{d['id']}", {"donor_entity_id": don["a"]["id"], "lines": lines}))
    assert v["status"] == "RECEIVED" and v["next_kind"] == "CORRECTED"
    r = _print(env, d["id"], confirmations=("CORRECTED_RECEIPT", "EMPTY_VARIABLES"))
    assert r.status_code == 200, r.text
    assert r.headers["X-Receipt-Kind"] == "CORRECTED"
    assert "August 8, 2026 and August 12, 2026" in text(r.content)
    # the register wins after linking: the line's amount can't be changed here
    lines2 = [dict(x) for x in lines]
    money_line = next(x for x in lines2 if x["kind"] == "MONEY")
    money_line["amount_cents"] = 1
    r = env.ru.put(f"/api/donations/{d['id']}", {"donor_entity_id": don["a"]["id"], "lines": lines2})
    assert r.status_code == 422 and "follows the register" in r.text
    # received: can't be cancelled
    r = env.ru.post(f"/api/donations/{d['id']}/cancel", {"reason": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DONATION_RECEIVED"


def test_void_unlinks_page_donations_but_voids_part1_receipts(env, don, dep):  # noqa: F811
    base = don["base"]
    d = _ok(_create(env, don, [{"kind": "MONEY", "amount_cents": 2500}]), 201)
    line = next(x for x in _ok(env.ru.get("/api/donations/awaiting-lines"))["items"] if x["donation_id"] == d["id"])
    t = _ok(env.ru.post("/api/donations/create-transaction", {"transaction": {
        "bank_account_id": base["acct"]["id"], "transaction_type": "DEPOSIT", "transaction_date": "2026-08-15",
        "allocations": [{"budget_id": base["inc_leaf"], "amount": "25.00"}]}, "links": [line["id"]]}), 201)
    assert _print(env, d["id"], confirmations=("EMPTY_VARIABLES",)).status_code == 200
    r = env.ru.post(f"/api/transactions/{t['id']}/void", {"reason": "bounced", "confirm_irreversible": True})
    assert r.status_code == 200, r.text
    v = _ok(env.ru.get(f"/api/donations/{d['id']}"))
    assert v["status"] == "AWAITING_DEPOSIT" and not v["lines"][0]["linked"] and v["lines"][0]["amount_cents"] == 2500
    assert v["receipts"][0]["void"] is False                    # its receipts stay valid
    # part 1: a voided deposit voids its receipts (unchanged)
    mark_all(env, dep)
    assert print_receipt(env, dep, "a").status_code == 200
    r = env.ru.post(f"/api/transactions/{dep['t']['id']}/void", {"reason": "dup", "confirm_irreversible": True})
    assert r.status_code == 200
    out = _ok(env.ru.get(dep["url"]))
    assert out["receipts"] and all(x["void"] for x in out["receipts"])


def test_cancel_items_value_flag_and_list(env, don):
    d = _ok(_create(env, don, [{"kind": "ITEM", "description": "Auction basket"}]), 201)
    assert d["value_missing"] == 1
    lst = _ok(env.bu.get("/api/donations?show=value_missing"))
    assert [x["id"] for x in lst["items"]] == [d["id"]] and lst["counts"]["value_missing"] == 1
    # "No value will be provided" needs a reason, and silences the flag
    v = _ok(env.ru.get(f"/api/donations/{d['id']}"))
    ln = v["lines"][0]
    r = env.ru.put(f"/api/donations/{d['id']}", {"donor_entity_id": don["a"]["id"], "lines": [
        {"id": ln["id"], "kind": "ITEM", "description": "Auction basket", "item_no_value": True}]})
    assert r.status_code == 422
    v = _ok(env.ru.put(f"/api/donations/{d['id']}", {"donor_entity_id": don["a"]["id"], "lines": [
        {"id": ln["id"], "kind": "ITEM", "description": "Auction basket", "item_no_value": True,
         "item_no_value_reason": "Donor declined to say"}]}))
    assert v["value_missing"] == 0
    # an item needs a description; money needs an amount; the donor isn't the organization
    assert _create(env, don, [{"kind": "ITEM"}]).status_code == 422
    assert _create(env, don, [{"kind": "MONEY"}]).status_code == 422
    # cancelled with a reason while nothing is received; its receipts are void; nothing is deleted
    assert _print(env, d["id"]).status_code == 200
    assert env.ru.post(f"/api/donations/{d['id']}/cancel", {"reason": " "}).status_code == 422
    v = _ok(env.ru.post(f"/api/donations/{d['id']}/cancel", {"reason": "Donor changed plans"}))
    assert v["status"] == "CANCELLED" and v["receipts"][0]["void"] is True and not v["printable"]
    assert _print(env, d["id"]).status_code == 409
    assert env.ru.put(f"/api/donations/{d['id']}", {"donor_entity_id": don["a"]["id"], "lines": [
        {"kind": "ITEM", "description": "x"}]}).status_code == 409
    acts = {e["action"] for e in env.auditor.get("/api/audit-events?page_size=200").json()["items"]}
    assert {"DONATION_CREATED", "DONATION_UPDATED", "DONATION_CANCELLED", "DONATION_RECEIPT_PRINTED"} <= acts


def test_permissions(env, don):
    lines = [{"kind": "MONEY", "amount_cents": 500}]
    for c in (env.bm, env.bu, env.auditor, env.admin):
        assert _create(env, don, lines, client=c).status_code == 403
    d = _ok(_create(env, don, lines), 201)
    for c in (env.bm, env.bu, env.auditor):
        assert c.get(f"/api/donations/{d['id']}").status_code == 200
        assert c.get("/api/donations").status_code == 200
    assert env.admin.get(f"/api/donations/{d['id']}").status_code == 403        # BR-003
    assert env.admin.get("/api/donations").status_code == 403
    assert env.bu.post(f"/api/donations/{d['id']}/receipts", {}).status_code == 403
    assert env.ru.get("/api/donations/awaiting-lines").status_code == 200


def test_items_note_setup(env, don):
    s = env.admin.get("/api/donations/setup").json()
    assert s["items_note_default"].startswith("Donated items are listed by description only")
    cfg = dict(s["config"], items_note="No value.")
    r = env.admin.put("/api/donations/setup", {"config": cfg})
    assert r.status_code == 422 and "at least 8 words" in r.text
    cfg["items_note"] = "{ORG.NAME} lists donated property by its description and assigns no value."
    assert env.admin.put("/api/donations/setup", {"config": cfg}).status_code == 200
    d = _ok(_create(env, don, [{"kind": "ITEM", "description": "Lawn mower"}]), 201)
    r = _print(env, d["id"])
    assert "Acme Org lists donated property by its description and assigns no value." in text(r.content)
    cfg["items_note"] = ""                                    # empty = the default wording again
    assert env.admin.put("/api/donations/setup", {"config": cfg}).status_code == 200


def test_audit_report_lists_items_received(env, don):
    base = don["base"]
    d = _ok(_create(env, don, [{"kind": "ITEM", "description": "Generator", "amount_cents": 90000,
                                "item_received": True, "date_received": "2026-08-20"}]), 201)
    assert d["status"] == "RECEIVED"
    r = env.bu.get(f"/api/reports/audit?fiscal_year_id={base['fy']['id']}")
    assert r.status_code == 200, r.text
    t = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "Non-cash donations received" in t and "Generator" in t and "$900.00" in t


def test_deposit_dialog_shows_page_donations_read_only(env, don):
    base = don["base"]
    d = _ok(_create(env, don, [{"kind": "MONEY", "amount_cents": 3000}]), 201)
    line = next(x for x in _ok(env.ru.get("/api/donations/awaiting-lines"))["items"] if x["donation_id"] == d["id"])
    t = _ok(env.ru.post("/api/donations/create-transaction", {"transaction": {
        "bank_account_id": base["acct"]["id"], "transaction_type": "DEPOSIT", "transaction_date": "2026-08-15",
        "allocations": [{"budget_id": base["inc_leaf"], "amount": "30.00"}]}, "links": [line["id"]]}), 201)
    out = _ok(env.ru.get(f"/api/donations/transactions/{t['id']}"))
    assert out["lines"][0]["linked_donation_id"] == d["id"] and out["page_donations"][0]["id"] == d["id"]
    assert out["donors"] == []
    r = env.ru.put(f"/api/donations/transactions/{t['id']}/lines",
                   {"lines": [{"allocation_id": out["lines"][0]["allocation_id"], "donation": False}]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "LINKED_TO_DONATION"


def test_migration_moves_part1_into_donations(env, dep, tmp_path):  # noqa: F811
    """Part 1 data (marked lines, details, receipts) becomes donations that started from the deposit."""
    mark_all(env, dep)
    r = env.ru.put(dep["url"] + "/lines", {"lines": [], "donors": [{"entity_id": dep["a"]["id"],
                                                                   "details": "Thanks for the gift"}]})
    assert r.status_code == 200, r.text
    assert print_receipt(env, dep, "a").status_code == 200
    # rebuild the part 2 data from the part 1 shape: downgrade one revision and upgrade again
    from alembic import command
    from fmpoc.db import alembic_config
    url = f"sqlite:///{env.settings.database_path}"
    env.app.state.engine.dispose()
    eng = create_engine(url)
    with eng.begin() as c:            # put details back where part 1 kept them (the downgrade drops the donation)
        c.execute(sql("INSERT INTO donation_detail (workspace_id, transaction_id, donor_entity_id, details, updated_at) "
                      "SELECT workspace_id, transaction_id, donor_entity_id, details, updated_at FROM donation "
                      "WHERE details IS NOT NULL"))
    eng.dispose()
    cfg = alembic_config(url)
    command.downgrade(cfg, "0053_branding")
    command.upgrade(cfg, "head")
    eng = create_engine(url)
    with eng.connect() as c:
        rows = c.execute(sql("SELECT id, donor_entity_id, origin, transaction_id, details FROM donation "
                             "ORDER BY id")).fetchall()
        assert {(r[1], r[2], r[3]) for r in rows} == {(dep["a"]["id"], "DEPOSIT", dep["t"]["id"]),
                                                       (dep["b"]["id"], "DEPOSIT", dep["t"]["id"])}
        assert any(r[4] == "Thanks for the gift" for r in rows)
        assert c.execute(sql("SELECT COUNT(*) FROM donation_line WHERE donation_id IS NULL")).scalar() == 0
        assert c.execute(sql("SELECT COUNT(*) FROM donation_receipt WHERE donation_id IS NULL")).scalar() == 0
    eng.dispose()
    out = env.ru.get(dep["url"]).json()
    a = next(x for x in out["donors"] if x["entity_id"] == dep["a"]["id"])
    assert a["next_kind"] == "DUPLICATE" and a["details"] == "Thanks for the gift"


def test_note_words():
    assert svc.note_words("{ORG.NAME} gives no value to items given to it.") == 9
    assert svc.note_words("{ORG.NAME} {ORG.EIN}") == 2
