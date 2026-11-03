"""2.4.0 (#252): the Invoices product catalog - products, tax rates, unit types and categories.

BR-INV-CAT-001..004 / AC-INV-CAT-001..006 (recorded in docs/implementation-notes.md); regression for BR-001 (never
deleted), BR-003 (Administrator), BR-075..078, BR-098 (mass assignment), BR-099 (object scope), BR-108.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def cat(env, base):
    """Invoices on, an Invoice Manager, and an Invoiced Income budget."""
    assert env.admin.put("/api/system/modules", {"invoices": True}).status_code == 200
    im = env.user("invmgr", "FINANCIAL", ["INVOICE_MANAGER"])
    assert env.bm.put(f"/api/budgets/{base['inc']['id']}/invoiced-income", {"invoiced_income": True}).status_code == 200
    units = {u["name"]: u["id"] for u in im.get("/api/invoices/catalog/unit-types").json()}
    return {"im": im, "units": units, "budget": base["inc_leaf"]}


def _product(c, cat, name="Annual dues", price="120.00", **kw):
    body = {"name": name, "unit_price": price, "unit_type_id": cat["units"]["Year"], "budget_id": cat["budget"], **kw}
    return c.post("/api/invoices/catalog/products", body)


def test_seeded_unit_types_and_discount_item(env, cat):
    """AC-INV-CAT-001: common unit types and the built-in Discount item when the module is turned on."""
    assert {"Each", "Hour", "Day", "Week", "Month", "Year"} <= set(cat["units"])
    prods = cat["im"].get("/api/invoices/catalog/products").json()
    disc = [p for p in prods if p["is_system"]]
    assert len(disc) == 1 and disc[0]["name"] == "Discount" and disc[0]["needs_budget"] is False
    r = cat["im"].post(f"/api/invoices/catalog/products/{disc[0]['id']}/inactivate")
    assert r.status_code == 409
    # turning the module off and on again does not seed twice
    env.admin.put("/api/system/modules", {"invoices": False})
    env.admin.put("/api/system/modules", {"invoices": True})
    assert len(cat["im"].get("/api/invoices/catalog/unit-types").json()) == len(cat["units"])


def test_invoice_manager_maintains_everything_audited_never_deleted(env, cat):
    """AC-INV-CAT-002 (BR-001, BR-075/076)."""
    im = cat["im"]
    c = im.post("/api/invoices/catalog/categories", {"name": "Membership"})
    assert c.status_code == 201
    p = _product(im, cat, category_id=c.json()["id"], code="DUES", taxable=True)
    assert p.status_code == 201, p.text
    pj = p.json()
    assert pj["unit_type"] == "Year" and pj["category"] == "Membership" and pj["needs_budget"] is False
    assert pj["budget"]["label"].startswith("4000")
    u = im.put(f"/api/invoices/catalog/products/{pj['id']}", {"name": "Annual dues", "unit_price": "125.00",
                                                               "unit_type_id": cat["units"]["Year"], "budget_id": cat["budget"]})
    assert u.json()["unit_price"] == "125.00"
    ev = env.auditor.get(f"/api/audit-events?action=INVOICE_PRODUCT_UPDATED&object_id={pj['id']}").json()["items"]
    assert ev[0]["before"]["unit_price"] == "120.00" and ev[0]["after"]["unit_price"] == "125.00"
    assert im.post(f"/api/invoices/catalog/products/{pj['id']}/inactivate").json()["active"] is False
    assert pj["id"] not in [x["id"] for x in im.get("/api/invoices/catalog/products").json()]
    assert pj["id"] in [x["id"] for x in im.get("/api/invoices/catalog/products?include_inactive=true").json()]
    assert im.post(f"/api/invoices/catalog/products/{pj['id']}/restore").json()["active"] is True
    t = im.post("/api/invoices/catalog/tax-rates", {"name": "State sales tax", "rate": "7.25", "budget_id": cat["budget"]})
    assert t.status_code == 201 and t.json()["rate"] == "7.25"
    assert im.post(f"/api/invoices/catalog/tax-rates/{t.json()['id']}/inactivate").json()["active"] is False
    w = im.post("/api/invoices/catalog/unit-types", {"name": "Session"})
    assert w.status_code == 201
    assert im.post(f"/api/invoices/catalog/unit-types/{w.json()['id']}/inactivate").json()["active"] is False
    assert im.post("/api/invoices/catalog/unit-types", {"name": "session"}).status_code == 409    # name in use
    for url in (f"/api/invoices/catalog/products/{pj['id']}", f"/api/invoices/catalog/unit-types/{w.json()['id']}"):
        assert im.delete(url).status_code in (404, 405)
    for action in ("INVOICE_TAX_RATE_CREATED", "INVOICE_TAX_RATE_INACTIVATED", "INVOICE_UNIT_TYPE_INACTIVATED",
                   "INVOICE_CATEGORY_CREATED", "INVOICE_PRODUCT_RESTORED"):
        assert env.auditor.get(f"/api/audit-events?action={action}").json()["items"], action


def test_validation_and_budget_picker(env, base, cat):
    """AC-INV-CAT-003: only Invoiced Income budgets, code and name only; bad values refused server-side."""
    im = cat["im"]
    opts = im.get("/api/invoices/catalog/budget-options").json()
    assert len(opts) == 1
    assert [b["id"] for b in opts[0]["budgets"]] == [cat["budget"]]
    assert set(opts[0]["budgets"][0]) == {"id", "label"}                      # no amounts or actuals
    assert _product(im, cat, budget_id=base["exp_leaf"]).status_code == 422   # an Expense budget
    other = env.budget(base["fy"]["id"], "4100", "Grants", "INCOME", "50.00")
    sel = {o["label"]: o["id"] for o in env.selectable(base["fy"]["id"], "DEPOSIT")}
    assert _product(im, cat, budget_id=sel["4100 Grants"]).status_code == 422  # not Invoiced Income
    assert _product(im, cat, price="-5").status_code == 422
    assert _product(im, cat, price="abc").status_code == 422
    assert _product(im, cat, unit_type_id=None).status_code == 422
    assert im.post("/api/invoices/catalog/tax-rates", {"name": "T", "rate": "150", "budget_id": cat["budget"]}).status_code == 422
    assert im.post("/api/invoices/catalog/tax-rates", {"name": "T", "rate": "7.12345", "budget_id": cat["budget"]}).status_code == 422
    # mass assignment: is_system / active / workspace are not writable
    r = _product(im, cat, is_system=True)
    assert r.status_code == 422
    assert other["id"]


def test_roles_view_and_refusals(env, cat):
    """AC-INV-CAT-004 (BR-003, BR-108): BM, BU, Auditor view; nobody but IM changes; Administrator refused; RU no
    catalog access; off module refuses."""
    p = _product(cat["im"], cat).json()
    for c in (env.bm, env.bu, env.auditor):
        assert c.get("/api/invoices/catalog/products").status_code == 200
        assert c.get("/api/invoices/catalog/tax-rates").status_code == 200
        assert _product(c, cat, name="X").status_code == 403
        assert c.post(f"/api/invoices/catalog/products/{p['id']}/inactivate").status_code == 403
        assert c.post("/api/invoices/catalog/unit-types", {"name": "Lot"}).status_code == 403
        assert c.get("/api/invoices/catalog/budget-options").status_code == 403
    for url in ("/api/invoices/catalog/products", "/api/invoices/catalog/unit-types", "/api/invoices/catalog/tax-rates"):
        assert env.admin.get(url).status_code == 403
        assert env.ru.get(url).status_code == 403
    env.admin.put("/api/system/modules", {"invoices": False})
    r = cat["im"].get("/api/invoices/catalog/products")
    assert r.status_code == 404 and r.json()["error"]["code"] == "MODULE_DISABLED"


def test_budget_follows_continuation_and_needs_budget_flag(env, base, cat):
    """AC-INV-CAT-005: a copied (continued) Invoiced Income budget is resolved in the next Fiscal Year; a product
    whose budget has no continuation there shows needs budget."""
    from fmpoc.models import Budget, FiscalYear, InvoiceProduct
    from fmpoc.services import invoice_catalog as svc
    p = _product(cat["im"], cat).json()
    r = env.bm.post("/api/fiscal-years", {"identifier": "2028", "start_date": "2027-07-01", "end_date": "2028-06-30",
                                          "copy_from_fiscal_year_id": base["fy"]["id"], "copy_budget_ids": [base["inc"]["id"]]})
    assert r.status_code == 201, r.text
    fy28 = r.json()["id"]
    with env.app.state.session_factory() as db:
        nxt = svc.budget_for_year(db, p["budget_id"], db.get(FiscalYear, fy28))
        assert nxt is not None and nxt.fiscal_year_id == fy28 and nxt.invoiced_income
        assert db.get(Budget, nxt.parent_budget_id).continues_budget_id == base["inc"]["id"]
        assert svc.needs_budget(db, db.get(InvoiceProduct, p["id"]), db.get(FiscalYear, fy28)) is False
    # a year with no continued budget: needs budget
    fy29 = env.fy("2029", "2028-07-01", "2029-06-30")
    with env.app.state.session_factory() as db:
        assert svc.budget_for_year(db, p["budget_id"], db.get(FiscalYear, fy29["id"])) is None
        assert svc.needs_budget(db, db.get(InvoiceProduct, p["id"]), db.get(FiscalYear, fy29["id"])) is True


def test_object_scope_unknown_ids(env, cat):
    """AC-INV-CAT-006 (BR-099): unknown ids are not found; a reference to an unknown unit type is refused."""
    im = cat["im"]
    assert im.put("/api/invoices/catalog/products/999999", {"name": "X", "unit_price": "1", "unit_type_id": cat["units"]["Each"],
                                                             "budget_id": cat["budget"]}).status_code == 404
    assert _product(im, cat, unit_type_id=999999).status_code == 422
    assert im.post("/api/invoices/catalog/categories/999999/inactivate").status_code == 404


# ------------------------------------------------------------------ 2.4.0 polish (#483, #486)
def test_category_budget_is_followed_unless_the_product_sets_its_own(env, cat):
    """#483: a product without a budget of its own uses its category's current budget; a category whose budget is
    followed can't drop it; a product needs a budget one way or the other."""
    im = cat["im"]
    plain = im.post("/api/invoices/catalog/categories", {"name": "Plain"}).json()
    r = _product(im, cat, name="No budget anywhere", budget_id=None, category_id=plain["id"])
    assert r.status_code == 422 and r.json()["error"]["errors"][0]["field"] == "budget_id"
    c = im.post("/api/invoices/catalog/categories", {"name": "Dues", "budget_id": cat["budget"]})
    assert c.status_code == 201 and c.json()["budget"]["id"] == cat["budget"]
    c = c.json()
    p = _product(im, cat, name="Family dues", budget_id=None, category_id=c["id"])
    assert p.status_code == 201, p.text
    p = p.json()
    assert p["own_budget"] is False and p["budget"]["id"] == cat["budget"] and p["needs_budget"] is False
    assert im.get("/api/invoices/catalog/categories").json()[0]["products_following"] in (0, 1)
    r = im.put(f"/api/invoices/catalog/categories/{c['id']}", {"name": "Dues", "budget_id": None})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CATEGORY_BUDGET_IN_USE"
    own = _product(im, cat, name="Single dues", category_id=c["id"]).json()          # its own budget
    assert own["own_budget"] is True
    assert env.admin.get("/api/invoices/catalog/categories").status_code == 403       # BR-003
    ev = env.auditor.get("/api/audit-events?action=INVOICE_CATEGORY_CREATED").json()["items"]
    assert any("budget_id" in str(e) for e in ev)


def test_category_code_pattern_suggests_codes_and_counts_only_used_ones(env, cat):
    """#486: {SEQ} counts per category (per year when the pattern shows it); a number is used only when a product is
    saved with the suggested code; a code already taken is skipped; a bad pattern is refused."""
    import datetime as dt
    im = cat["im"]
    yy = f"{dt.date.today().year % 100:02d}"
    bad = im.post("/api/invoices/catalog/categories", {"name": "Bad", "code_pattern": "MB-{YY}"})
    assert bad.status_code == 422 and bad.json()["error"]["errors"][0]["field"] == "code_pattern"
    ex = im.get("/api/invoices/catalog/code-example?pattern=MBRSHP-{YY}-{SEQ:4}").json()
    assert ex["next_code"] == f"MBRSHP-{yy}-0001"
    c = im.post("/api/invoices/catalog/categories", {"name": "Memberships", "code_pattern": "MBRSHP-{YY}-{SEQ:4}",
                                                    "budget_id": cat["budget"]}).json()
    assert c["next_code"] == f"MBRSHP-{yy}-0001"
    _product(im, cat, name="Hand-coded", code="CUSTOM-1", category_id=c["id"], budget_id=None)
    assert im.get(f"/api/invoices/catalog/code-example?category_id={c['id']}").json()["next_code"] == f"MBRSHP-{yy}-0001"
    _product(im, cat, name="Gold", code=f"MBRSHP-{yy}-0001", category_id=c["id"], budget_id=None)
    assert im.get(f"/api/invoices/catalog/code-example?category_id={c['id']}").json()["next_code"] == f"MBRSHP-{yy}-0002"
    other = im.post("/api/invoices/catalog/categories", {"name": "Other", "budget_id": cat["budget"]}).json()
    _product(im, cat, name="Squatter", code=f"MBRSHP-{yy}-0002", category_id=other["id"], budget_id=None)
    assert im.get(f"/api/invoices/catalog/code-example?category_id={c['id']}").json()["next_code"] == f"MBRSHP-{yy}-0003"
    nyr = im.post("/api/invoices/catalog/categories", {"name": "Lockers", "code_pattern": "LCK-{SEQ:3}"}).json()
    assert nyr["next_code"] == "LCK-001"
