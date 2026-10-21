#!/usr/bin/env python3
"""2.1.0 (#272): the private TEST data set - a larger made-up organization for refreshing a test server.

    PW_TESTDATA_PASSWORD=... [PW_TESTDATA_PASSPHRASE=...] \\
        python scripts/demo_data.py --profile test [--fy-start-month 7] [--backup out.fmbak] [--summary out.json] URL

Like the demo (scripts/demo_data.py), everything goes through the normal web API of a NEW, uninitialized installation,
so every rule and the audit trail apply, and it refuses an installation whose wizard is completed. Unlike the demo:
- the sign-in password comes from PW_TESTDATA_PASSWORD (never from this file) and also answers the security
  questions; with --backup, the backup passphrase comes from PW_TESTDATA_PASSPHRASE. Neither is ever printed;
- several Fiscal Years relative to today: two closed ones, the current approved one and a Draft next year whose
  budgets continue the current ones; July-June by default (--fy-start-month);
- three fundraiser series recorded in the app for three years, with four years before PennyWarden entered by hand;
  buckets and categories, Charge / Less, a contributor override, an upcoming and a cancelled fundraiser;
- checks printed with the Payments module, electronic payments, a VOID and a deleted transaction, attachments,
  reminders.

Sign-ins: admin (Administrator), budgetmgr (Budget Manager), bookkeeper (Register User), auditor (Auditor) and
treasurer (Budget Manager + Register User, also Register Admin so it can delete a transaction). In server mode each
one enrolls two-step verification at its first sign-in after the backup is restored.

All names, people, vendors and account numbers are invented.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time

import demo_data as demo

ORG = "Cedar Valley Community Association"
USERS = (  # username, first, last, security domain, roles
    ("budgetmgr", "Robin", "Hale", "FINANCIAL", ["BUDGET_MANAGER"]),
    ("bookkeeper", "Casey", "Nguyen", "FINANCIAL", ["REGISTER_USER"]),
    ("auditor", "Avery", "Brooks", "AUDITOR", ["AUDITOR"]),
    ("treasurer", "Jamie", "Ellison", "FINANCIAL", ["BUDGET_MANAGER", "REGISTER_USER", "REGISTER_ADMIN"]),
)
QUESTIONS = ("FIRST_TEACHER", "FIRST_PET", "FIRST_CAR")


def secret(name: str, required: bool = True) -> str | None:
    v = os.environ.get(name, "")
    if required and not v:
        raise SystemExit(f"{name} is not set. The test data set takes its credentials from the environment only.")
    return v or None             # never printed; in Actions, GitHub masks values that come from secrets


class Api(demo.Api):
    """The demo's client with the password (and security answers) from the environment, and secrets redacted from
    any error text."""
    password = ""
    hidden: tuple[str, ...] = ()

    def call(self, method, url, json=None, ok=(200, 201), **kw):
        r = self.c.request(method, url, json=json, headers=self._h(), **kw)
        if r.status_code not in ok:
            text = r.text[:500]
            for h in self.hidden:
                text = text.replace(h, "***")
            raise SystemExit(f"{method} {url} -> {r.status_code}: {text}")
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else r

    def login(self, user: str) -> "Api":
        r = self.post("/api/auth/login", {"username": user, "password": self.password})
        self.csrf = r["csrf_token"]
        if r.get("mfa_pending") == "QUESTIONS":
            self.questions()
        return self

    def questions(self) -> None:
        self.csrf = self.post("/api/auth/setup/security-questions", {"questions": [
            {"question": q, "answer": self.password} for q in QUESTIONS]})["csrf_token"]


# ------------------------------------------------------------------ Fiscal Years
class FY:
    """A twelve-month Fiscal Year starting on the first of a month, named after the year it ends in."""

    def __init__(self, start: dt.date):
        self.start = start
        self.end = dt.date(start.year + 1, start.month, 1) - dt.timedelta(days=1)
        self.label = str(self.end.year)

    def date(self, month: int, day: int) -> dt.date:
        """The `day` of the `month`-th month of the year (0 = the first)."""
        y, m = divmod(self.start.month - 1 + month, 12)
        return dt.date(self.start.year + y, m + 1, min(day, 28))


def fiscal_years(today: dt.date, start_month: int) -> list[FY]:
    """Two years before the current one, the current one (containing today) and the next."""
    y = today.year if today.month >= start_month else today.year - 1
    return [FY(dt.date(y + k, start_month, 1)) for k in (-2, -1, 0, 1)]


# budget code, name, type, parent code, base amount (grows a little each year)
BUDGETS = (
    ("4000", "Membership dues", "INCOME", None, 9000),
    ("4100", "Donations and grants", "INCOME", None, 12000),
    ("4200", "Fundraising", "INCOME", None, 0),
    ("4210", "Golf Outing", None, "4200", 14000),
    ("4220", "Pancake Breakfasts", None, "4200", 5200),
    ("4230", "Holiday Raffle", None, "4200", 4800),
    ("4300", "Hall rentals", "INCOME", None, 6000),
    ("5000", "Programs and events", "EXPENSE", None, 8000),
    ("5100", "Facility", "EXPENSE", None, 0),
    ("5110", "Rent and utilities", None, "5100", 9600),
    ("5120", "Repairs and maintenance", None, "5100", 3000),
    ("5200", "Insurance", "EXPENSE", None, 2400),
    ("5400", "Fundraising costs", "EXPENSE", None, 0),
    ("5410", "Golf Outing costs", None, "5400", 6500),
    ("5420", "Pancake Breakfast supplies", None, "5400", 1600),
    ("5430", "Raffle prizes", None, "5400", 1500),
    ("5500", "Community grants given", "EXPENSE", None, 5000),
    ("5900", "Administration", "EXPENSE", None, 1800),
)

VENDORS = ("Cedar Valley Hardware", "Northfield Utilities", "Lakeside Insurance Agency", "Prairie Print & Copy",
           "Greenway Golf Club", "Hometown Foods Wholesale", "Bright Spark Electric", "Riverbend Party Rentals",
           "Members (dues)", "Community donors", "Hall rental guests", "Cedar Valley Community Foundation")
SPONSORS = ("Harper Family Dental", "Oakline Auto Repair", "Summit Ridge Realty", "Blue Heron Bakery",
            "Maplewood Pharmacy", "Ironwood Builders")
PEOPLE = (("Taylor Brennan", "President"), ("Morgan Price", "Secretary"), ("Riley Okafor", "Event chair"),
          ("Quinn Delgado", "Volunteer"))


def main(base: str, start_month: int = 7, backup: str | None = None, summary: str | None = None,
         today: dt.date | None = None) -> dict:
    Api.password = secret("PW_TESTDATA_PASSWORD")
    passphrase = secret("PW_TESTDATA_PASSPHRASE", required=bool(backup))
    Api.hidden = tuple(x for x in (Api.password, passphrase) if x)
    today = today or dt.date.today()
    if not 1 <= start_month <= 12:
        raise SystemExit("--fy-start-month must be 1-12.")
    years = fiscal_years(today, start_month)
    prev2, prev1, cur, nxt = years

    admin = Api(base)
    if admin.get("/api/system/status").get("initialized"):
        raise SystemExit("This installation is already initialized - test data is only for a new, empty one.")
    admin.post("/api/system/initialize", {"workspace_name": ORG, "admin_username": "admin",
                                          "admin_email": "admin@example.org", "admin_first_name": "Sydney",
                                          "admin_last_name": "Marsh", "password": Api.password,
                                          "password_confirmation": Api.password})
    admin.csrf = admin.get("/api/auth/me")["csrf_token"]
    admin.questions()
    for name, first, last, domain, roles in USERS:
        admin.post("/api/users", {"username": name, "email": f"{name}@example.org", "password": Api.password,
                                  "display_name": f"{first} {last}", "first_name": first, "last_name": last,
                                  "security_domain": domain, "roles": roles})
    admin.put("/api/system/modules", {"fundraisers": True, "checks": True})
    tr = Api(base).login("treasurer")              # Budget Manager + Register User (+ Register Admin)
    for u in ("budgetmgr", "bookkeeper", "auditor"):
        Api(base).login(u)                         # their first sign-in: security questions set

    # ---- entities and bank accounts
    def org(name, bank=False):
        return tr.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": name,
                                         "is_financial_institution": bank, "confirmations": ["DUPLICATE_ENTITY"]})

    bank = org("Prairie State Credit Union", bank=True)
    ent = {n: org(n) for n in VENDORS + SPONSORS}
    for name, pos in PEOPLE:
        ent[name] = tr.post("/api/entities", {"entity_type": "INDIVIDUAL", "primary_contact": name, "position": pos,
                                              "confirmations": ["DUPLICATE_ENTITY"]})
    acct = {}
    for key, name, kind, number, opening, primary in (
            ("chk", "Operating Checking", "CHECKING", "000555012345", "12400.00", True),
            ("sav", "Building Fund Savings", "SAVINGS", "000555098765", "30000.00", False)):
        acct[key] = tr.post("/api/bank-accounts", {
            "account_name": name, "financial_institution_entity_id": bank["id"], "account_type": kind,
            "account_number": number, "is_primary": primary, "opening_balance": opening,
            "opening_balance_date": prev2.start.isoformat()})

    # ---- Payments module: a voucher check style with a made-up signer
    signer = admin.call("POST", "/api/checks/signers", data={"name": "Jamie Ellison", "title": "Treasurer"},
                        files={"file": ("signature.png", demo.signature_png(), "image/png")})
    style = admin.post("/api/checks/styles", {"preset_key": "VOUCHER_TOP", "name": "Voucher checks"})
    cfg = style["config"]
    cfg.update(memo_default="{BUDGET_CODE}, INVOICE {INVOICE}", default_signer_id=signer["id"])
    admin.put(f"/api/checks/styles/{style['id']}", {"name": "Voucher checks", "config": cfg})
    tr.put(f"/api/checks/accounts/{acct['chk']['id']}", {"check_style_id": style["id"]})

    counts = {"transactions": 0, "printed_checks": 0, "electronic_payments": 0, "fundraisers": 0, "entered_years": 0}
    check_no = iter(range(2101, 9999))
    budget_ids: dict[str, dict[str, int]] = {}

    def make_budgets(fy_row: dict, fy: FY, k: int, prev: dict[str, int] | None) -> dict[str, int]:
        ids: dict[str, int] = {}
        grown = {code: round(amount * (1 + 0.04 * k)) for code, _n, _t, _p, amount in BUDGETS}
        for code, _n, _t, parent, _a in BUDGETS:
            if parent:
                grown[parent] += grown[code]         # a parent covers its sub-budgets
        for code, name, btype, parent, amount in BUDGETS:
            body = {"fiscal_year_id": fy_row["id"], "code": code, "name": name, "amount": f"{grown[code]:.2f}"}
            body.update({"parent_budget_id": ids[parent]} if parent else {"budget_type": btype})
            if prev and code in prev:
                body["continues_budget_id"] = prev[code]
            ids[code] = tr.post("/api/budgets", body)["id"]
        return ids

    def leaves(fy_row: dict) -> dict[str, int]:
        out = {}
        for kind in ("WITHDRAWAL", "DEPOSIT"):
            for o in tr.get(f"/api/budgets/selectable?fiscal_year_id={fy_row['id']}&transaction_type={kind}"):
                out[o["label"].split(" ")[0].split("-")[-1]] = o["id"]
        return out

    def txn(leaf, account, kind, when: dt.date, entity, lines, *, cleared=True, attach=None, check=True,
            electronic=None, **kw):
        if when > today:
            return None
        body = {"bank_account_id": acct[account]["id"], "transaction_type": kind, "transaction_date": when.isoformat(),
                "entity_id": ent[entity]["id"] if entity else None,
                "allocations": [{"budget_id": leaf[c], "amount": a, "description": desc, **(extra[0] if extra else {})}
                                for c, a, desc, *extra in lines], **kw}
        if electronic:
            method, ref = electronic
            body.update(electronic_payment=True, payment_method=method, payment_reference=ref)
            counts["electronic_payments"] += 1
        elif kind == "WITHDRAWAL" and account == "chk" and check:
            body["check_number"] = str(next(check_no))
        if cleared:
            body["clear_date"] = min(when + dt.timedelta(days=4), today).isoformat()
        t = tr.post("/api/transactions", body)
        counts["transactions"] += 1
        if attach:
            tr.upload("transaction", t["id"], attach, demo.pdf(attach.rsplit(".", 1)[0].replace("-", " ").title(),
                                                               [f"{entity or ORG} - {when.isoformat()}"]
                                                               + [f"{x[2]}: ${x[1]}" for x in lines]))
        return t

    def amt(base_amount: float, k: int, wobble: int = 0) -> str:
        return f"{base_amount * (1 + 0.05 * k) + wobble:.2f}"

    latest: dict[str, dict] = {}            # series key -> its latest fundraiser so far
    earlier: dict[str, dict] = {}           # the same, as of the end of the previous Fiscal Year
    series_ids: dict[str, int] = {}

    def fundraiser(key: str, body: dict) -> dict:
        """"Continues from" the series' latest fundraiser of an earlier Fiscal Year (a link must go back a year)."""
        if key in earlier:
            body["continues_from_id"] = earlier[key]["id"]
        f = tr.post("/api/fundraisers", body)
        latest[key] = f
        counts["fundraisers"] += 1
        if f["series_link"]["series"]:
            series_ids[key] = f["series_link"]["series"]["id"]
        return f

    def lines_of(f: dict) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for x in tr.get(f"/api/fundraisers/{f['id']}")["lines"]:
            out.setdefault(x["description"], []).append(x)
        return out

    def golf_buckets(f: dict) -> None:
        url = f"/api/fundraisers/{f['id']}"
        for name in ("Registrations", "Hole sponsors", "Raffle", "Food & beverage", "Course fees"):
            f = tr.post(f"{url}/buckets", {"name": name})
        bucket = {b["name"]: b["id"] for b in f["buckets"]["items"] if b.get("id")}
        def category(name):
            r = tr.post(f"{url}/categories", {"name": name})
            return next(c for c in r["buckets"]["categories"] if c["name"] == name)
        sponsor_cat, day_cat = category("Sponsorships"), category("Day-of event")
        tr.put(f"{url}/buckets/{bucket['Hole sponsors']}", {"name": "Hole sponsors", "category_id": sponsor_cat["id"]})
        for b in ("Raffle", "Food & beverage"):
            tr.put(f"{url}/buckets/{bucket[b]}", {"name": b, "category_id": day_cat["id"]})
        lines = lines_of(f)
        for desc, x in ((d, x) for d, xs in lines.items() for x in xs):
            if desc.startswith("Registration"):
                b = [{"bucket_id": bucket["Registrations"], "amount": x["amount"]}]
            elif desc.startswith("Hole sponsor"):
                if desc.endswith("(card)"):     # paid by card: $500 charged, less the card fee
                    gross = f"{float(x['amount']) + 25:.2f}"
                    b = [{"bucket_id": bucket["Hole sponsors"], "charge": gross, "less": "25.00",
                          "less_description": "Card processing fee"}]
                else:
                    b = [{"bucket_id": bucket["Hole sponsors"], "amount": x["amount"]}]
            elif desc.startswith("Raffle"):     # lump cash from the raffle table
                b = [{"bucket_id": bucket["Raffle"], "amount": x["amount"], "contributor_override": "Cash"}]
            elif desc.startswith(("Lunch", "Beverage")):
                b = [{"bucket_id": bucket["Food & beverage"], "amount": x["amount"]}]
            elif desc.startswith("Greens"):
                b = [{"bucket_id": bucket["Course fees"], "amount": x["amount"]}]
            else:
                continue
            tr.put(f"{url}/lines/{x['allocation_id']}", {"buckets": b})

    # ---- each Fiscal Year: budgets, approval, register, fundraisers; the past ones are closed
    prev_ids = None
    rows = []
    for k, fy in enumerate(years):
        row = tr.post("/api/fiscal-years", {"identifier": fy.label, "start_date": fy.start.isoformat(),
                                            "end_date": fy.end.isoformat(), "confirmations": []})
        rows.append(row)
        prev_ids = budget_ids[fy.label] = make_budgets(row, fy, k, prev_ids)
        if fy is nxt:
            break                                  # the next year stays a Draft, its budgets continue this year's
        tr.upload("fiscal_year", row["id"], "board-approval.pdf",
                  demo.pdf("Budget approval", [f"{ORG} - Fiscal Year {fy.label}", "Approved by the board (test document)."]),
                  "&document_type=APPROVAL")
        tr.post(f"/api/fiscal-years/{row['id']}/approve", {"confirm_irreversible": True})
        leaf = leaves(row)
        W, D = "WITHDRAWAL", "DEPOSIT"
        recent = fy is cur
        # dues and donations
        for m in (0, 3, 6, 9):
            txn(leaf, "chk", D, fy.date(m, 8), "Members (dues)", [("4000", amt(2150, k, m * 7), f"Member dues - quarter {m // 3 + 1}")],
                attach="dues-deposit.pdf" if m == 0 else None)
        for m in (2, 5, 8, 11):
            txn(leaf, "chk", D, fy.date(m, 15), "Community donors", [("4100", amt(1900, k, m * 11), "Donations")])
        txn(leaf, "chk", D, fy.date(4, 20), "Cedar Valley Community Foundation",
            [("4100", amt(4000, k), "Community Foundation grant")], attach="foundation-award-letter.pdf")
        for m in (1, 4, 7, 10):
            txn(leaf, "chk", D, fy.date(m, 22), "Hall rental guests", [("4300", amt(1400, k, m * 5), "Hall rentals")])
        # facility: rent by ACH, utilities through the online portal, repairs by check
        for m in range(12):
            txn(leaf, "chk", W, fy.date(m, 1), "Northfield Utilities", [("5110", amt(780, k, m * 3), "Rent and utilities")],
                electronic=("ACH" if m % 2 == 0 else "ONLINE_PORTAL", f"NU{fy.label}{m + 1:02d}"),
                cleared=not (recent and fy.date(m, 1) > today - dt.timedelta(days=10)))
        txn(leaf, "chk", W, fy.date(3, 12), "Bright Spark Electric", [("5120", amt(640, k), "Hall lighting repair")],
            attach="bright-spark-invoice.pdf")
        txn(leaf, "chk", W, fy.date(8, 3), "Cedar Valley Hardware", [("5120", amt(215.4, k), "Paint and supplies"),
                                                                     ("5000", amt(88.15, k), "Program craft supplies")],
            electronic=("DEBIT_CARD", None))
        txn(leaf, "chk", W, fy.date(0, 18), "Lakeside Insurance Agency", [("5200", amt(2350, k), "Liability insurance")],
            electronic=("WIRE", f"WIRE-{fy.label}-0718"), attach="insurance-renewal.pdf")
        for m in (1, 5, 9):
            txn(leaf, "chk", W, fy.date(m, 10), "Riverbend Party Rentals", [("5000", amt(950, k, m), "Community event rentals")])
        txn(leaf, "chk", W, fy.date(6, 14), "Cedar Valley Community Foundation",
            [("5500", amt(2500, k), "Youth sports grant")], attach="grant-minutes.pdf")
        txn(leaf, "chk", W, fy.date(10, 5), "Prairie Print & Copy", [("5900", amt(310, k), "Newsletters and envelopes")])

        # fundraisers: the Golf Outing (with buckets), two Pancake Breakfasts, the Holiday Raffle
        golf_day = fy.date(2, 14)
        for i, s in enumerate(SPONSORS):
            card = i == 0
            txn(leaf, "chk", D, golf_day - dt.timedelta(days=20 - i), s,
                [("4210", "475.00" if card else amt(500, k), f"Hole sponsor - {s}" + (" (card)" if card else ""))])
        txn(leaf, "chk", D, golf_day + dt.timedelta(days=1), "Community donors",
            [("4210", amt(5200, k, 40), "Registrations - 26 foursomes"), ("4210", amt(1310, k, 7), "Raffle table cash")],
            attach="golf-count-sheet.pdf")
        txn(leaf, "chk", W, golf_day + dt.timedelta(days=3), "Greenway Golf Club",
            [("5410", amt(3900, k), "Greens fees and carts"), ("5410", amt(1650, k), "Lunch buffet"),
             ("5410", amt(420, k), "Beverage cart")], attach="greenway-invoice.pdf")
        earlier.update(latest)
        g = fundraiser("golf", {"name": f"{golf_day.year} Golf Outing", "start_date": golf_day.isoformat(),
                                     "end_date": golf_day.isoformat(), "description": "Annual charity golf outing.",
                                     "budget_ids": [budget_ids[fy.label]["4210"], budget_ids[fy.label]["5410"]]})
        if golf_day <= today:
            golf_buckets(g)
        breakfasts = []
        for m, season in ((3, "Fall"), (9, "Spring")):
            day = fy.date(m, 9)
            txn(leaf, "chk", D, day, "Community donors", [("4220", amt(1650, k, m), f"{season} pancake breakfast tickets")])
            txn(leaf, "chk", W, day - dt.timedelta(days=2), "Hometown Foods Wholesale",
                [("5420", amt(420, k, m), f"{season} pancake breakfast supplies")])
            breakfasts.append(fundraiser("pancake", {"name": f"{season} Pancake Breakfast {day.year}",
                                                     "start_date": day.isoformat(), "filter_text": f"{season} pancake",
                                                     "budget_ids": [budget_ids[fy.label]["4220"], budget_ids[fy.label]["5420"]]}))
        if k == 0:
            # held twice a year: in the first year neither can continue from an earlier one, so each starts a series
            # and the two are merged into one (2.1.0, #292 / #277)
            a, b = (tr.post(f"/api/fundraisers/{f['id']}/series")["series_id"] for f in breakfasts)
            tr.post(f"/api/fundraiser-series/{b}/merge", {"into_series_id": a})
            tr.call("PATCH", f"/api/fundraiser-series/{a}", {"name": "Pancake Breakfast"})
            series_ids["pancake"] = a
        raffle_day = fy.date(5, 12)
        txn(leaf, "chk", D, raffle_day, "Community donors", [("4230", amt(4350, k, 15), "Holiday raffle tickets")])
        txn(leaf, "chk", W, raffle_day - dt.timedelta(days=30), "Cedar Valley Hardware",
            [("5430", amt(1100, k), "Raffle prizes - grill and gift cards")])
        fundraiser("raffle", {"name": f"Holiday Raffle {raffle_day.year}", "start_date": raffle_day.isoformat(),
                                   "budget_ids": [budget_ids[fy.label]["4230"], budget_ids[fy.label]["5430"]]})
        if fy is prev1:   # a fundraiser that did not happen
            wash = tr.post("/api/fundraisers", {"name": f"Summer Car Wash {fy.date(11, 1).year}",
                                                "start_date": fy.date(11, 20).isoformat(),
                                                "budget_ids": [budget_ids[fy.label]["4220"]], "filter_text": "car wash"})
            tr.post(f"/api/fundraisers/{wash['id']}/cancel", {"reason": "Rained out twice; not rescheduled"})
            counts["fundraisers"] += 1

        if fy is cur:
            # printed checks, a VOID and a deleted transaction, the most recent ones still uncleared
            for t in [x for x in (txn(leaf, "chk", W, min(today, fy.date(0, 25)), "Prairie Print & Copy",
                                      [("5900", "184.60", "Membership cards", {"invoice_number": "PP-4471"})], cleared=False),
                                  txn(leaf, "chk", W, min(today, fy.date(0, 26)), "Cedar Valley Hardware",
                                      [("5120", "96.35", "Door hardware", {"invoice_number": "CVH-20931"})], cleared=False)) if x]:
                tr.post(f"/api/checks/transactions/{t['id']}/print",
                        {"check_style_id": style["id"], "feed_key": "voucher", "confirm_check_number": t["check_number"]})
                counts["printed_checks"] += 1
            v = txn(leaf, "chk", W, min(today, fy.date(0, 20)), "Riverbend Party Rentals",
                    [("5000", "250.00", "Tent rental - cancelled event")], cleared=False)
            if v:
                tr.post(f"/api/transactions/{v['id']}/void", {"reason": "Event cancelled; check never sent",
                                                               "confirm_irreversible": True})
            dl = txn(leaf, "chk", W, min(today, fy.date(0, 21)), "Hometown Foods Wholesale",
                     [("5000", "75.00", "Entered twice")], cleared=False)
            if dl:
                tr.post(f"/api/transactions/{dl['id']}/delete", {"reason": "Duplicate entry"})
            tr.post("/api/transfers", {"from_account_id": acct["chk"]["id"], "to_account_id": acct["sav"]["id"],
                                       "amount": "5000.00", "transaction_date": min(today, fy.date(0, 28)).isoformat(),
                                       "clear_date": min(today, fy.date(0, 28)).isoformat(),
                                       "notes": "Building fund contribution"})
    # the past years are closed, oldest first
    for fy, row in zip(years[:2], rows[:2]):
        tr.upload("fiscal_year", row["id"], "audit-signoff.pdf",
                  demo.pdf("Audit signoff", [f"{ORG} - Fiscal Year {fy.label}",
                                             "Reviewed by the audit committee (test document)."]),
                  "&document_type=AUDIT_SIGNOFF")
        tr.post(f"/api/fiscal-years/{row['id']}/close", {"confirm_reviewed": True})

    # ---- years before PennyWarden, entered by hand on each series
    first = prev2.start.year
    for key, base_net, note in (("golf", 8200, None), ("pancake", 2300, "Spring and fall together"),
                                ("raffle", 2600, None)):
        sid = series_ids.get(key)
        if not sid:
            continue
        for i, y in enumerate(range(first - 4, first)):
            label = f"FY{y + (1 if start_month > 1 else 0)}"
            net = base_net * (0.82 + 0.05 * i)
            body = {"fiscal_year_label": label, "net": f"{net:.2f}", "note": note}
            if key == "golf" and i >= 2:           # the recent ones have income and expenses too
                body.update(income=f"{net * 1.6:.2f}", expense=f"{net * 0.6:.2f}")
            tr.post(f"/api/fundraiser-series/{sid}/results", body)
            counts["entered_years"] += 1

    # ---- reminders
    tr.post("/api/reminders", {"scope": "ORGANIZATION", "title": "Reconcile the bank statements",
                               "details": "Both accounts. Attach the statements to the Fiscal Year.",
                               "due_date": today.isoformat(), "repeat_every": 1, "repeat_unit": "MONTH",
                               "link_type": "BANK_ACCOUNT", "link_id": acct["chk"]["id"]})
    tr.post("/api/reminders", {"scope": "ORGANIZATION", "title": f"Present the FY{nxt.label} budget to the board",
                               "due_date": min(cur.end, today + dt.timedelta(days=45)).isoformat(),
                               "notify_days_before": 14, "link_type": "FISCAL_YEAR", "link_id": rows[3]["id"]})
    tr.post("/api/reminders", {"scope": "ORGANIZATION", "title": "Renew the liability insurance",
                               "due_date": (today - dt.timedelta(days=3)).isoformat(), "repeat_every": 1,
                               "repeat_unit": "YEAR"})
    tr.post("/api/reminders", {"scope": "PERSONAL", "title": "Order deposit slips", "due_date": today.isoformat()})

    status = admin.get("/api/system/status")
    out = {"organization": ORG, "app_version": status.get("version"), "fiscal_years": [
        {"label": f"FY{fy.label}", "start": fy.start.isoformat(), "end": fy.end.isoformat(),
         "status": ("Closed" if i < 2 else "Approved" if i == 2 else "Draft")} for i, fy in enumerate(years)],
        "sign_ins": ["admin"] + [u[0] for u in USERS], "counts": counts}
    if backup:
        out["backup"] = make_backup(admin, passphrase, backup)
    if summary:
        with open(summary, "w") as fh:
            json.dump(out, fh, indent=2)
    print(f"Test organization '{ORG}' created at {base}: " + ", ".join(f"{v} {k.replace('_', ' ')}"
                                                                     for k, v in counts.items()) + ".")
    return out


def make_backup(admin: Api, passphrase: str, path: str) -> dict:
    """A normal encrypted backup (.fmbak) through the backup API, written to `path`."""
    job = admin.call("POST", "/api/system/backups", {"password": Api.password, "passphrase": passphrase,
                                      "passphrase_confirmation": passphrase, "recoverable": False}, ok=(202,))
    for _ in range(600):
        job = admin.get(f"/api/system/backups/{job['id']}")
        if job["state"] in ("done", "failed"):
            break
        time.sleep(0.5)
    if job["state"] != "done":
        raise SystemExit(f"The backup failed: {job.get('error')}")
    r = admin.c.get(f"/api/system/backups/{job['id']}/download")
    r.raise_for_status()
    with open(path, "wb") as fh:
        fh.write(r.content)
    res = job.get("result") or {}
    return {"file": os.path.basename(path), "size": len(r.content), "counts": res.get("counts")}


if __name__ == "__main__":   # pragma: no cover - run through demo_data.py --profile test
    sys.exit("Run it as: python scripts/demo_data.py --profile test URL")
