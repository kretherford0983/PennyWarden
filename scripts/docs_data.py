#!/usr/bin/env python3
"""2.4.0 (#488): adds the Invoices module to the demo organization, for the user guide's screenshots.

    python scripts/demo_data.py http://127.0.0.1:8801       # a NEW, empty installation first
    python scripts/docs_data.py http://127.0.0.1:8801
    node scripts/docs_screenshots.mjs http://127.0.0.1:8801

Everything is made up and goes through the normal web API (rules and audit trail apply). Adds the sign-in
demo-invoices (Invoice Manager), marks "4000 Membership dues" and a new "4400 Merchandise and events" budget as
Invoiced Income, and fills the catalog: tax rates and tax groups, categories (one with a product code pattern),
products (one with a product field), a tax-exempt customer, and a few invoices - a draft, a sent one and a paid one.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_data import ADMIN, PASSWORD, Api  # noqa: E402


def main(base: str) -> None:
    today = dt.date.today()
    admin = Api(base).login(ADMIN)
    users = admin.get("/api/users")
    if not any(u["username"] == "demo-budget" for u in (users["items"] if isinstance(users, dict) else users)):
        raise SystemExit("Run scripts/demo_data.py on a new installation first.")
    admin.put("/api/system/modules", {"invoices": True})
    admin.post("/api/users", {"username": "demo-invoices", "email": "demo-invoices@example.org", "password": PASSWORD,
                              "display_name": "Riley Brooks", "first_name": "Riley", "last_name": "Brooks",
                              "security_domain": "FINANCIAL", "roles": ["INVOICE_MANAGER"]})
    admin.post("/api/invoices/setup/fields", {"level": "PRODUCT", "field_type": "TEXT", "name": "Serial number",
                                              "required": True, "show_on_pdf": True})
    admin.post("/api/invoices/setup/fields", {"level": "INVOICE", "field_type": "TEXT", "name": "Purchase order",
                                              "required": False, "show_on_pdf": True})
    bm = Api(base).login("demo-budget")
    ru = Api(base).login("demo-register")
    im = Api(base).login("demo-invoices")

    fy = next(f for f in bm.get("/api/fiscal-years") if f["status"] != "CLOSED")
    budgets = bm.get(f"/api/budgets?fiscal_year_id={fy['id']}")
    rows = budgets["income"]
    dues = next(b for b in rows if b["code"] == "4000")
    bm.post(f"/api/budgets/{dues['id']}/unlock", {"reason": "Collect membership dues through invoices"})
    bm.put(f"/api/budgets/{dues['id']}/invoiced-income", {"invoiced_income": True})
    bm.post(f"/api/budgets/{dues['id']}/lock")
    merch = bm.post("/api/budgets", {"fiscal_year_id": fy["id"], "code": "4400", "name": "Merchandise and events",
                                     "amount": "3000.00", "budget_type": "INCOME"})
    bm.put(f"/api/budgets/{merch['id']}/invoiced-income", {"invoiced_income": True})

    pick = {o["code"] if "code" in o else o["label"].split(" ")[0]: o["id"] for g in im.get("/api/invoices/catalog/budget-options")
            for o in g["budgets"]}
    dues_leaf = next(v for k, v in pick.items() if k.startswith("4000"))
    merch_leaf = next(v for k, v in pick.items() if k.startswith("4400"))
    units = {u["name"]: u["id"] for u in im.get("/api/invoices/catalog/unit-types")}
    rate = lambda n, r: im.post("/api/invoices/catalog/tax-rates", {"name": n, "rate": r, "budget_id": merch_leaf})["id"]  # noqa: E731
    state, food = rate("State sales tax", "5.75"), rate("Food tax", "2")
    general = im.post("/api/invoices/catalog/tax-groups", {"name": "General merchandise", "rate_ids": [state]})["id"]
    meals = im.post("/api/invoices/catalog/tax-groups", {"name": "Food", "rate_ids": [food]})["id"]
    members = im.post("/api/invoices/catalog/categories", {"name": "Memberships", "budget_id": dues_leaf,
                                                          "code_pattern": "MBRSHP-{YY}-{SEQ:4}"})
    merchandise = im.post("/api/invoices/catalog/categories", {"name": "Merchandise", "budget_id": merch_leaf})
    events = im.post("/api/invoices/catalog/categories", {"name": "Events", "budget_id": merch_leaf,
                                                         "code_pattern": "EVT-{SEQ:3}"})
    fields = {f["name"]: f["id"] for f in im.get("/api/invoices/fields")}

    def product(name, price, unit, cat, group=None, code=None, fields_=()):
        c = im.get(f"/api/invoices/catalog/code-example?category_id={cat['id']}")["next_code"]
        return im.post("/api/invoices/catalog/products", {
            "name": name, "unit_price": price, "unit_type_id": units[unit], "category_id": cat["id"],
            "code": code or c, "tax_group_id": group, "custom_field_ids": list(fields_)})
    family = product("Family membership", "60.00", "Year", members)
    student = product("Student membership", "25.00", "Year", members)
    shirt = product("Concert t-shirt", "18.00", "Each", merchandise, general, "SHIRT-1")
    dinner = product("Spaghetti dinner ticket", "12.00", "Each", events, meals)
    rental = product("Instrument rental", "35.00", "Month", merchandise, general, "RENT-1", [fields["Serial number"]])

    def entity(name, street, exempt=None):
        body = {"entity_type": "ORGANIZATION", "organization_name": name, "address_line1": street, "city": "Riverside",
                "state_region": "OH", "postal_code": "45999", "confirmations": ["DUPLICATE_ENTITY"]}
        if exempt:
            body.update(tax_exempt=True, tax_exempt_certificate=exempt)
        return im.post("/api/entities", body)
    pto = entity("Lakeside Middle School PTO", "900 School Road", exempt="OH-EX-20417")
    family_a = im.post("/api/entities", {"entity_type": "INDIVIDUAL", "first_name": "Taylor", "last_name": "Nguyen",
                                         "address_line1": "14 Willow Court", "city": "Riverside", "state_region": "OH",
                                         "postal_code": "45999", "confirmations": ["DUPLICATE_ENTITY"]})
    family_b = im.post("/api/entities", {"entity_type": "INDIVIDUAL", "first_name": "Chris", "last_name": "Patel",
                                         "address_line1": "302 Oak Street", "city": "Riverside", "state_region": "OH",
                                         "postal_code": "45999", "confirmations": ["DUPLICATE_ENTITY"]})
    day = lambda n: min(today, today.replace(day=1) + dt.timedelta(days=n)).isoformat()  # noqa: E731

    paid = im.post("/api/invoices", {"customer_entity_id": family_a["id"], "invoice_date": day(1), "lines": [
        {"product_id": family["id"], "quantity": "1"}, {"product_id": shirt["id"], "quantity": "2"},
        {"product_id": dinner["id"], "quantity": "4"}]})
    im.post(f"/api/invoices/{paid['id']}/send")
    acct = next(a for a in ru.get("/api/bank-accounts") if a["is_primary"])
    ru.post(f"/api/invoices/{paid['id']}/payments", {"bank_account_id": acct["id"], "amount": paid["totals"]["total"],
                                                     "transaction_date": day(3)})
    sent = im.post("/api/invoices", {"customer_entity_id": pto["id"], "invoice_date": day(2),
                                     "custom_values": {str(fields["Purchase order"]): "PO-5531"}, "lines": [
        {"product_id": rental["id"], "quantity": "3", "custom_values": {str(fields["Serial number"]): "TRB-48213"}},
        {"product_id": dinner["id"], "quantity": "20", "discount_kind": "PERCENT", "discount_value": "10",
         "discount_reason": "Group of 20"}]})
    im.post(f"/api/invoices/{sent['id']}/send")
    im.post("/api/invoices", {"customer_entity_id": family_b["id"], "invoice_date": day(4), "lines": [
        {"product_id": student["id"], "quantity": "1"}, {"product_id": shirt["id"], "quantity": "1"}]})
    print(f"Invoices added for the user guide screenshots. Sign in as demo-invoices (Invoice Manager) with the demo password.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8801")
