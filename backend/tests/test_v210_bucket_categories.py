"""2.1.0 (#278): fundraiser bucket categories (one per bucket, or none), the display order of buckets and categories,
and Charge / Less on a bucket assignment. Totals stay on the actual money (the net); categories and order are
presentation only."""
from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

from test_v161_fundraiser_manage import gala, put_line  # noqa: F401  (fixture)


def url(g, tail=""):
    return f"/api/fundraisers/{g['id']}{tail}"


def bucket(env, g, name, client=None, **kw):
    r = (client or env.ru).post(url(g, "/buckets"), {"name": name, **kw})
    assert r.status_code == 201, r.text
    return next(b for b in r.json()["buckets"]["items"] if b["name"] == name)


def category(env, g, name, client=None, **kw):
    r = (client or env.ru).post(url(g, "/categories"), {"name": name, **kw})
    assert r.status_code == 201, r.text
    return next(c for c in r.json()["buckets"]["categories"] if c["name"] == name)


def detail(env, g):
    return env.bu.get(url(g)).json()


def test_categories_group_buckets_with_subtotals(env, gala):
    food = bucket(env, gala, "Food Sales")
    raffle = bucket(env, gala, "Raffle")
    day = category(env, gala, "Day-of event", description="Everything sold on the day")
    assert env.ru.put(url(gala, f"/buckets/{food['id']}"), {"name": "Food Sales", "category_id": day["id"]}).status_code == 200
    # a mixed bucket keeps both income and expenses: net = income - expenses
    put_line(env.ru, gala, "Gala takings", {"buckets": [{"bucket_id": food["id"], "amount": "1000.00"},
                                                        {"bucket_id": raffle["id"], "amount": "450.00"}]})
    put_line(env.ru, gala, "Food supplies", {"buckets": [{"bucket_id": food["id"], "amount": "300.00"}]})
    b = detail(env, gala)["buckets"]
    cat = b["categories"][0]
    assert cat["name"] == "Day-of event" and cat["bucket_ids"] == [food["id"]]
    assert (cat["income"], cat["expense"], cat["net"]) == ("1000.00", "300.00", "700.00")
    assert b["uncategorized_ids"] == [raffle["id"]]
    items = {x["name"]: x for x in b["items"]}
    assert items["Food Sales"]["category_id"] == day["id"] and items["Raffle"]["category_id"] is None
    # a bucket in an unknown category is refused
    r = env.ru.put(url(gala, f"/buckets/{raffle['id']}"), {"name": "Raffle", "category_id": 999999})
    assert r.status_code == 404
    # names are unique per fundraiser, case-insensitively
    assert env.ru.post(url(gala, "/categories"), {"name": "day-of EVENT"}).status_code == 422


def test_delete_category_leaves_buckets_uncategorized_and_figures_unchanged(env, gala):
    food = bucket(env, gala, "Food Sales")
    cat = category(env, gala, "Day-of event")
    env.ru.put(url(gala, f"/buckets/{food['id']}"), {"name": "Food Sales", "category_id": cat["id"]})
    put_line(env.ru, gala, "Gala takings", {"buckets": [{"bucket_id": food["id"], "amount": "1000.00"}]})
    before = detail(env, gala)
    r = env.ru.delete(url(gala, f"/categories/{cat['id']}"))
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["buckets"]["categories"] == [] and after["buckets"]["uncategorized_ids"] == [food["id"]]
    assert after["totals"] == before["totals"]
    assert [x["net"] for x in after["buckets"]["items"]] == [x["net"] for x in before["buckets"]["items"]]
    ev = env.auditor.get("/api/audit-events?action=FUNDRAISER_CATEGORY_DELETED").json()["items"]
    assert ev[0]["before"]["bucket_ids"] == [food["id"]]


def test_display_order_buckets_and_categories(env, gala):
    z = bucket(env, gala, "Zebra")
    a = bucket(env, gala, "Apple")          # new buckets go to the end
    assert [x["name"] for x in detail(env, gala)["buckets"]["items"]] == ["Zebra", "Apple"]
    r = env.ru.put(url(gala, "/buckets/order"), {"ids": [a["id"], z["id"]]})
    assert r.status_code == 200, r.text
    assert [x["name"] for x in r.json()["buckets"]["items"]] == ["Apple", "Zebra"]
    c1, c2 = category(env, gala, "Sponsorships"), category(env, gala, "Registrations")
    r = env.ru.put(url(gala, "/categories/order"), {"ids": [c2["id"], c1["id"]]})
    assert [c["name"] for c in r.json()["buckets"]["categories"]] == ["Registrations", "Sponsorships"]
    # every one exactly once
    assert env.ru.put(url(gala, "/categories/order"), {"ids": [c2["id"]]}).status_code == 422
    assert env.ru.put(url(gala, "/buckets/order"), {"ids": [a["id"], a["id"]]}).status_code == 422
    acts = {e["action"] for e in env.auditor.get("/api/audit-events").json()["items"]}
    assert {"FUNDRAISER_BUCKETS_REORDERED", "FUNDRAISER_CATEGORIES_REORDERED", "FUNDRAISER_CATEGORY_CREATED"} <= acts


def test_charge_less_on_an_expense_counts_the_net(env, gala):
    venue = bucket(env, gala, "Venue")
    r = put_line(env.ru, gala, "Food supplies", {"buckets": [
        {"bucket_id": venue["id"], "charge": "450.00", "less": "150.00", "less_description": "Pre-paid team credit"}]})
    assert r.status_code == 200, r.text
    d = r.json()
    line = next(x for x in d["lines"] if x["description"] == "Food supplies")
    assert line["buckets"] == [{"bucket_id": venue["id"], "amount": "300.00", "charge": "450.00", "less": "150.00",
                                "less_description": "Pre-paid team credit"}]
    assert line["unassigned"] == "0.00"
    v = next(x for x in d["buckets"]["items"] if x["id"] == venue["id"])
    assert v["expense"] == "300.00" and v["credits_expense"] == "150.00"
    assert d["totals"]["expense"] == "500.00"                    # unchanged: the register's money
    ev = env.auditor.get("/api/audit-events?action=FUNDRAISER_LINE_UPDATED").json()["items"][0]
    assert ev["after"]["buckets"][0]["charge"] == "450.00" and ev["after"]["buckets"][0]["less_description"] == "Pre-paid team credit"


def test_charge_less_on_income_and_fully_credited(env, gala):
    s = bucket(env, gala, "Sponsorships")
    comp = bucket(env, gala, "Comped")
    r = put_line(env.ru, gala, "Unrelated donation", {"buckets": [
        {"bucket_id": s["id"], "charge": "81.00", "less": "6.00", "less_description": "Card fee"}]})
    assert r.status_code == 200, r.text
    r = put_line(env.ru, gala, "Gala takings", {"buckets": [
        {"bucket_id": comp["id"], "charge": "500.00", "less": "500.00", "less_description": "Comped by venue"}]})
    assert r.status_code == 200, r.text
    line = next(x for x in r.json()["lines"] if x["description"] == "Gala takings")
    assert line["buckets"][0]["amount"] == "0.00" and line["unassigned"] == "1450.00"


@pytest.mark.parametrize("item,field", [
    ({"charge": "100.00", "less": "100.01", "less_description": "x"}, "buckets"),          # less > charge
    ({"charge": "100.00", "less": "10.00"}, "less_description"),                          # no description
    ({"charge": "0.00"}, "buckets"),                                                       # charge must be > 0
    ({"charge": "400.00", "less": "50.00", "less_description": "x"}, "buckets"),           # net 350 > line 300
    ({"less": "5.00", "less_description": "x"}, "buckets"),                                # less without a charge
    ({"charge": "100.00", "less": "-1.00", "less_description": "x"}, "buckets"),
])
def test_charge_less_validation(env, gala, item, field):
    venue = bucket(env, gala, "Venue")
    r = put_line(env.ru, gala, "Food supplies", {"buckets": [{"bucket_id": venue["id"], **item}]})
    assert r.status_code == 422, r.text
    errs = r.json()["error"].get("errors") or [r.json()["error"]]
    assert any(e.get("field") == field for e in errs) or r.json()["error"].get("field") == field, r.text


def test_plain_amount_still_works(env, gala):
    b = bucket(env, gala, "Food")
    r = put_line(env.ru, gala, "Food supplies", {"buckets": [{"bucket_id": b["id"], "amount": "120.00"}]})
    assert r.status_code == 200
    line = next(x for x in r.json()["lines"] if x["description"] == "Food supplies")
    assert line["buckets"][0] == {"bucket_id": b["id"], "amount": "120.00", "charge": "120.00", "less": "0.00",
                                  "less_description": None}


def test_closed_year_locks_assignments_but_not_categories(env, gala, app):
    from sqlalchemy.orm import Session
    from fmpoc.models import FiscalYear
    b = bucket(env, gala, "Food")
    cat = category(env, gala, "Day-of")
    with Session(app.state.engine) as db:
        db.get(FiscalYear, gala["base"]["fy"]["id"]).status = "CLOSED"
        db.commit()
    r = put_line(env.ru, gala, "Food supplies", {"buckets": [{"bucket_id": b["id"], "charge": "10.00"}]})
    assert r.status_code == 409
    # presentation still changes: categories, a bucket's category, order
    assert env.ru.put(url(gala, f"/categories/{cat['id']}"), {"name": "Day-of event"}).status_code == 200
    assert env.ru.put(url(gala, f"/buckets/{b['id']}"), {"name": "Food", "category_id": cat["id"]}).status_code == 200
    assert env.ru.post(url(gala, "/categories"), {"name": "Later"}).status_code == 201
    # renaming the bucket follows the closed-year rule as before
    assert env.ru.put(url(gala, f"/buckets/{b['id']}"), {"name": "Food sales", "category_id": cat["id"]}).status_code == 409


def test_permissions(env, gala):
    cat = category(env, gala, "Sponsorships", client=env.bm)
    for c in (env.bu, env.auditor, env.admin):
        assert c.post(url(gala, "/categories"), {"name": "X"}).status_code == 403
        assert c.put(url(gala, f"/categories/{cat['id']}"), {"name": "X"}).status_code == 403
        assert c.delete(url(gala, f"/categories/{cat['id']}")).status_code == 403
        assert c.put(url(gala, "/categories/order"), {"ids": [cat["id"]]}).status_code == 403
        assert c.put(url(gala, "/buckets/order"), {"ids": [1]}).status_code == 403


def test_module_off_is_404(env, gala):
    assert env.admin.put("/api/system/modules", {"fundraisers": False}).status_code == 200
    assert env.ru.post(url(gala, "/categories"), {"name": "X"}).status_code == 404


def test_categories_block_delete_and_report_shows_them(env, gala):
    food = bucket(env, gala, "Food Sales")
    cat = category(env, gala, "Day-of event")
    env.ru.put(url(gala, f"/buckets/{food['id']}"), {"name": "Food Sales", "category_id": cat["id"]})
    put_line(env.ru, gala, "Food supplies", {"buckets": [
        {"bucket_id": food["id"], "charge": "450.00", "less": "150.00", "less_description": "Pre-paid team credit"}]})
    r = env.bu.get(url(gala, "/report"))
    assert r.status_code == 200
    text = " ".join(" ".join((p.extract_text() or "").split()) for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "Day-of event" in text and "Day-of event subtotal" in text
    assert "less $150.00 Pre-paid team credit" in text


def test_migration_keeps_figures(tmp_path):
    """Existing assignments: charge = amount, less = 0; buckets numbered in name order (as listed before)."""
    from alembic import command
    from sqlalchemy import create_engine
    from fmpoc.db import alembic_config, upgrade_database
    u = f"sqlite:///{tmp_path / 'm.sqlite3'}"
    command.upgrade(alembic_config(u), "0038_projection_choices")
    eng = create_engine(u)
    with eng.begin() as c:
        c.exec_driver_sql("INSERT INTO workspace (id, name, created_at, next_entity_number) VALUES (1, 'w', '2026-01-01', 1)")
        c.exec_driver_sql("INSERT INTO fundraiser (id, workspace_id, name, start_date, end_date, filter_regex, created_at, updated_at) "
                          "VALUES (1, 1, 'F', '2026-09-01', '2026-09-01', 0, '2026-01-01', '2026-01-01')")
        for i, n in ((1, "Zebra"), (2, "Apple"), (3, "Mango")):
            c.exec_driver_sql(f"INSERT INTO fundraiser_bucket (id, fundraiser_id, name, created_at) VALUES ({i}, 1, '{n}', '2026-01-01')")
        c.exec_driver_sql("INSERT INTO fundraiser_bucket_line (id, bucket_id, allocation_id, amount_cents) VALUES (1, 1, 7, 12345)")
    upgrade_database(u)
    with eng.connect() as c:
        assert c.exec_driver_sql("SELECT amount_cents, charge_cents, less_cents, less_description FROM fundraiser_bucket_line").one() == (12345, 12345, 0, None)
        order = c.exec_driver_sql("SELECT name FROM fundraiser_bucket ORDER BY display_order").scalars().all()
        assert order == ["Apple", "Mango", "Zebra"]
        assert c.exec_driver_sql("SELECT category_id FROM fundraiser_bucket").scalars().all() == [None, None, None]
