#!/usr/bin/env python3
"""Fills a NEW, empty PennyWarden installation with a small made-up organization - for screenshots and demos.

    python scripts/demo_data.py http://127.0.0.1:8787

Everything goes through the normal web API, exactly like a person clicking through the application, so every rule
and the audit trail apply. The installation must not be initialized yet (the script runs the Initialization Wizard).
Never run it against an installation with real data - it refuses when the wizard has already been completed.

Sign-ins afterwards (local mode; all with the password below) - 2.2.0 (#243), one per main role, as published with the
demo: demo-admin (Administrator), demo-budget (Budget Manager), demo-register (Register User), demo-auditor (Auditor).
The current Fiscal Year is the year it is built in; the year before is closed (with its approval and audit signoff).
scripts/build_demo.py turns the result into the published demo backup.
"""
from __future__ import annotations

import datetime as dt
import io
import sys

import httpx
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

PASSWORD = "Demo-PennyWarden-2026"
ORG = "Riverside Band Boosters"


class Api:
    def __init__(self, base: str):
        self.c = httpx.Client(base_url=base, timeout=60)
        self.csrf = self.c.get("/api/auth/csrf").json()["csrf_token"]

    def _h(self):
        return {"X-CSRF-Token": self.csrf}

    def call(self, method: str, url: str, json=None, ok=(200, 201), **kw):
        r = self.c.request(method, url, json=json, headers=self._h(), **kw)
        if r.status_code not in ok:
            raise SystemExit(f"{method} {url} -> {r.status_code}: {r.text[:500]}")
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else r

    def post(self, url, json=None, **kw):
        return self.call("POST", url, json, **kw)

    def put(self, url, json=None, **kw):
        return self.call("PUT", url, json, **kw)

    def get(self, url):
        return self.call("GET", url)

    def login(self, user: str) -> "Api":
        r = self.post("/api/auth/login", {"username": user, "password": PASSWORD})
        self.csrf = r["csrf_token"]
        if r.get("mfa_pending") == "QUESTIONS":
            self.questions()
        return self

    def questions(self) -> None:
        """1.8.0: a first sign-in chooses three security questions (made-up answers)."""
        self.csrf = self.post("/api/auth/setup/security-questions", {"questions": [
            {"question": q, "answer": a} for q, a in (("FIRST_TEACHER", "Mrs. Demo"), ("FIRST_PET", "Demo dog"),
                                                      ("FIRST_CAR", "Demo car"))]})["csrf_token"]

    def upload(self, owner_type: str, owner_id: int, name: str, data: bytes, extra: str = ""):
        return self.call("POST", f"/api/attachments?owner_type={owner_type}&owner_id={owner_id}{extra}",
                         files={"file": (name, data, "application/pdf")})


def pdf(title: str, lines: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(72, 720, title)
    c.setFont("Helvetica", 11)
    for i, line in enumerate(lines):
        c.drawString(72, 690 - 18 * i, line)
    c.save()
    return buf.getvalue()


def signature_png(w: int = 360, h: int = 90) -> bytes:
    """A made-up signature: a smooth pen stroke drawn as a transparent PNG (no real person's signature)."""
    import math
    import struct
    import zlib
    raw = bytearray()
    ink = set()
    for x in range(10, w - 10):
        t = x / w
        y = h / 2 + (h / 4) * math.sin(x / 9) * (1 - t / 2) + (h / 8) * math.sin(x / 31)
        for dy in (-1, 0, 1):
            for dx in (0, 1):
                ink.add((x + dx, int(y) + dy))
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes((25, 35, 90, 255)) if (x, y) in ink else bytes(4)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b""))


ADMIN = "demo-admin"
USERS = (  # 2.2.0 (#243): one sign-in per main role
    ("demo-budget", "Jordan", "Lee", "FINANCIAL", ["BUDGET_MANAGER"]),
    ("demo-register", "Sam", "Carter", "FINANCIAL", ["REGISTER_USER"]),
    ("demo-auditor", "Morgan", "Diaz", "AUDITOR", ["AUDITOR"]),
)


def main(base: str) -> dict:
    today = dt.date.today()
    year = today.year
    d = lambda m, day: min(dt.date(year, m, day), today).isoformat()  # noqa: E731 - never in the future
    p = lambda m, day: dt.date(year - 1, m, day).isoformat()          # noqa: E731 - last (closed) year

    admin = Api(base)
    if admin.get("/api/system/status").get("initialized"):
        raise SystemExit("This installation is already initialized - demo data is only for a new, empty one.")
    admin.post("/api/system/initialize", {"workspace_name": ORG, "admin_username": ADMIN,
                                          "admin_email": "admin@example.org", "admin_first_name": "Alex",
                                          "admin_last_name": "Morgan", "password": PASSWORD,
                                          "password_confirmation": PASSWORD})
    admin.csrf = admin.get("/api/auth/me")["csrf_token"]
    admin.questions()
    for name, first, last, domain, roles in USERS:
        admin.post("/api/users", {"username": name, "email": f"{name}@example.org", "password": PASSWORD,
                                  "display_name": f"{first} {last}", "first_name": first,
                                  "last_name": last, "security_domain": domain, "roles": roles})
    admin.put("/api/system/modules", {"fundraisers": True, "checks": True})   # 2.0.0: the Payments module
    bm = Api(base).login("demo-budget")
    ru = Api(base).login("demo-register")

    # ---- last year (closed at the end) and this year, January to December
    last = bm.post("/api/fiscal-years", {"identifier": str(year - 1), "start_date": f"{year - 1}-01-01",
                                         "end_date": f"{year - 1}-12-31", "confirmations": []})
    prev: dict[str, int] = {}
    for code, name, amount, btype in (("4000", "Membership dues", "5800.00", "INCOME"),
                                      ("4100", "Donations and sponsors", "8000.00", "INCOME"),
                                      ("4300", "Concessions", "7000.00", "INCOME"),
                                      ("5000", "Instruments and repairs", "9000.00", "EXPENSE"),
                                      ("5200", "Travel and competitions", "10500.00", "EXPENSE"),
                                      ("5300", "Concession supplies", "3400.00", "EXPENSE"),
                                      ("5900", "Administration", "1100.00", "EXPENSE")):
        prev[code] = bm.post("/api/budgets", {"fiscal_year_id": last["id"], "code": code, "name": name,
                                              "amount": amount, "budget_type": btype})["id"]
    fy = bm.post("/api/fiscal-years", {"identifier": str(year), "start_date": f"{year}-01-01",
                                       "end_date": f"{year}-12-31", "confirmations": []})

    def budget(code, name, amount, btype=None, parent=None):
        body = {"fiscal_year_id": fy["id"], "code": code, "name": name, "amount": amount}
        body.update({"parent_budget_id": parent} if parent else {"budget_type": btype})
        if not parent and code in prev:
            body["continues_budget_id"] = prev[code]     # #89: one line of history across the years
        return bm.post("/api/budgets", body)

    budget("4000", "Membership dues", "6000.00", "INCOME")
    budget("4100", "Donations and sponsors", "9000.00", "INCOME")
    fundraising = budget("4200", "Fundraising", "14000.00", "INCOME")
    b_spring = budget("4210", "Spring Concert & Silent Auction", "8500.00", parent=fundraising["id"])
    b_fall = budget("4220", "Fall Mattress Sale", "5500.00", parent=fundraising["id"])
    budget("4300", "Concessions", "7500.00", "INCOME")
    budget("5000", "Instruments and repairs", "9500.00", "EXPENSE")
    budget("5100", "Uniforms", "4200.00", "EXPENSE")
    travel = budget("5200", "Travel and competitions", "11500.00", "EXPENSE")
    budget("5210", "Buses", "7000.00", parent=travel["id"])
    budget("5220", "Entry fees", "4500.00", parent=travel["id"])
    budget("5300", "Concession supplies", "3600.00", "EXPENSE")
    b_costs = budget("5400", "Fundraising costs", "2600.00", "EXPENSE")
    budget("5500", "Scholarships", "3000.00", "EXPENSE")
    budget("5900", "Administration", "1200.00", "EXPENSE")

    # ---- people, vendors, bank accounts
    def org(name, bank=False):
        return bm.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": name,
                                         "is_financial_institution": bank, "confirmations": ["DUPLICATE_ENTITY"]})

    def person(name, position=None):
        return bm.post("/api/entities", {"entity_type": "INDIVIDUAL", "primary_contact": name, "position": position,
                                         "confirmations": ["DUPLICATE_ENTITY"]})

    bank = org("First River Credit Union", bank=True)
    e = {n: org(n) for n in ("Harmony Music Supply", "Valley Coach Lines", "Stitchworks Uniforms",
                             "Wholesale Club", "State Band Association", "Riverside Print Shop",
                             "Members (dues)", "Community donors", "Concession stand sales", "DreamRest Mattress Co.")}
    person("Dana Whitfield", "Treasurer")
    person("Marcus Ortega", "President")
    person("Priya Raman", "Audit Committee Chair")
    acct = {}
    for key, name, kind, number, opening, primary in (
            ("chk", "Operating Checking", "CHECKING", "000123456789", "8450.00", True),
            ("sav", "Reserve Savings", "SAVINGS", "000987654321", "15000.00", False)):
        acct[key] = bm.post("/api/bank-accounts", {
            "account_name": name, "financial_institution_entity_id": bank["id"], "account_type": kind,
            "account_number": number, "is_primary": primary, "opening_balance": opening,
            "opening_balance_date": f"{year - 1}-01-01"})

    # ---- 2.0.0: Payments module - a voucher check style with a (made-up) signer, used by the checking account
    signer = admin.call("POST", "/api/checks/signers", data={"name": "Dana Whitfield", "title": "Treasurer"},
                        files={"file": ("signature.png", signature_png(), "image/png")})
    style = admin.post("/api/checks/styles", {"preset_key": "VOUCHER_TOP", "name": "Voucher checks"})
    cfg = style["config"]
    cfg.update(memo_default="{BUDGET_CODE}, INVOICE {INVOICE}", default_signer_id=signer["id"])
    admin.put(f"/api/checks/styles/{style['id']}", {"name": "Voucher checks", "config": cfg})
    ru.put(f"/api/checks/accounts/{acct['chk']['id']}", {"check_style_id": style["id"]})

    for f, label in ((last, year - 1), (fy, year)):
        bm.upload("fiscal_year", f["id"], "board-approval.pdf",
                  pdf("Budget approval", [f"{ORG} - Fiscal Year {label}", "Approved by the board (demo document)."]),
                  "&document_type=APPROVAL")
        bm.post(f"/api/fiscal-years/{f['id']}/approve", {"confirm_irreversible": True})

    # ---- register
    def leaves(f):
        out = {}
        for kind in ("WITHDRAWAL", "DEPOSIT"):
            for o in ru.get(f"/api/budgets/selectable?fiscal_year_id={f['id']}&transaction_type={kind}"):
                out[o["label"].split(" ")[0].split("-")[-1]] = o["id"]
        return out
    leaf = leaves(fy)
    check = iter(range(1001, 1200))

    def txn(account, kind, when, entity, lines, cleared=True, attach=None, leaf=leaf, **kw):
        body = {"bank_account_id": acct[account]["id"], "transaction_type": kind, "transaction_date": when,
                "entity_id": e[entity]["id"] if entity else None,
                "allocations": [{"budget_id": leaf[c], "amount": a, "description": desc} for c, a, desc in lines], **kw}
        if kind == "WITHDRAWAL" and account == "chk" and "check_number" not in kw:
            body["check_number"] = str(next(check))
        if cleared:
            body["clear_date"] = when
        t = ru.post("/api/transactions", body)
        if attach:
            ru.upload("transaction", t["id"], attach, pdf(attach.rsplit(".", 1)[0].replace("-", " ").title(),
                                                           [f"{entity} - {when}"] + [f"{desc}: ${a}" for _, a, desc in lines]))
        return t

    W, D = "WITHDRAWAL", "DEPOSIT"
    # last year: a short year in summary, every item cleared and documented, so it can be closed
    pl = leaves(last)
    for when, kind, ent, code, amount, desc, doc in (
            (p(1, 15), D, "Members (dues)", "4000", "5640.00", "Member dues", "dues-summary.pdf"),
            (p(3, 2), W, "Harmony Music Supply", "5000", "4120.00", "Instrument repairs and reeds", "harmony-invoices.pdf"),
            (p(4, 12), D, "Community donors", "4100", "7350.00", "Sponsors and alumni appeal", "sponsor-letters.pdf"),
            (p(6, 20), W, "Valley Coach Lines", "5200", "6980.00", "Buses and festival entries", "travel-invoices.pdf"),
            (p(9, 30), D, "Concession stand sales", "4300", "6810.00", "Football season concessions", "concession-tally.pdf"),
            (p(10, 4), W, "Wholesale Club", "5300", "3275.40", "Concession stock", "wholesale-receipts.pdf"),
            (p(11, 18), W, "Riverside Print Shop", "5900", "980.00", "Printing, postage and fees", "print-shop-receipts.pdf")):
        txn("chk", kind, when, ent, [(code, amount, desc)], attach=doc, leaf=pl)
    txn("chk", D, d(1, 12), "Members (dues)", [("4000", "2850.00", "Member dues - January")], attach="dues-deposit-slip.pdf")
    txn("chk", W, d(1, 20), "Harmony Music Supply", [("5000", "1240.00", "Tuba valve repair, 2 clarinets serviced")], attach="harmony-invoice-2291.pdf")
    txn("chk", D, d(2, 3), "Community donors", [("4100", "2500.00", "Rotary Club sponsorship")], attach="rotary-letter.pdf")
    txn("chk", W, d(2, 14), "State Band Association", [("5220", "850.00", "Regional festival entry")], attach="festival-entry-form.pdf")
    txn("chk", W, d(2, 27), "Valley Coach Lines", [("5210", "1650.00", "2 buses - regional festival")], attach="valley-coach-invoice.pdf")
    txn("chk", D, d(3, 9), "Members (dues)", [("4000", "1900.00", "Member dues - March")])
    t_print = txn("chk", W, d(3, 18), "Riverside Print Shop", [("5400", "310.00", "Spring concert programs and posters"),
                                                      ("5900", "45.00", "Letterhead")], attach="print-shop-receipt.pdf")
    t_gate = txn("chk", D, d(4, 20), "Community donors", [("4210", "3120.00", "Spring concert tickets"),
                                                            ("4210", "4675.00", "Spring concert silent auction")],
                 attach="spring-concert-count-sheet.pdf")
    t_food = txn("chk", W, d(4, 22), "Wholesale Club", [("5400", "420.50", "Spring concert reception supplies")],
                 attach="wholesale-receipt-0422.pdf")
    txn("chk", D, d(4, 25), "Concession stand sales", [("4300", "1385.00", "Spring concert concessions")])
    txn("chk", W, d(5, 6), "Stitchworks Uniforms", [("5100", "2380.00", "12 marching jackets")], attach="stitchworks-invoice.pdf")
    txn("chk", W, d(5, 19), "Harmony Music Supply", [("5000", "3150.00", "Marimba - used, refurbished")], attach="harmony-invoice-2407.pdf")
    txn("chk", D, d(6, 2), "Community donors", [("4100", "1800.00", "Alumni appeal")])
    txn("chk", W, d(6, 10), None, [("5500", "1500.00", "Senior scholarships (3 x $500)")], attach="scholarship-minutes.pdf")
    txn("chk", D, d(8, 24), "Members (dues)", [("4000", "1150.00", "Member dues - fall sign-up")])
    txn("chk", W, d(8, 28), "Wholesale Club", [("5300", "960.75", "Concession stock - football season")], attach="wholesale-receipt-0828.pdf")
    txn("chk", D, d(9, 8), "Concession stand sales", [("4300", "1742.00", "Home game 1 concessions")])
    txn("chk", D, d(9, 22), "Concession stand sales", [("4300", "1968.50", "Home game 2 concessions")])
    txn("chk", W, d(9, 25), "Valley Coach Lines", [("5210", "2100.00", "3 buses - state marching preview")], attach="valley-coach-invoice-2.pdf")
    txn("chk", D, d(9, 29), "DreamRest Mattress Co.", [("4220", "4380.00", "Mattress sale commission")], attach="dreamrest-statement.pdf")
    txn("chk", W, d(9, 30), "Riverside Print Shop", [("5400", "185.00", "Mattress sale yard signs")])
    txn("chk", W, d(10, 1), "State Band Association", [("5220", "1200.00", "State championship entry")], cleared=False)
    txn("chk", W, d(10, 2), "Wholesale Club", [("5300", "640.20", "Concession restock")], cleared=False)
    txn("chk", D, d(10, 3), "Concession stand sales", [("4300", "1510.00", "Home game 3 concessions")], cleared=False)
    ru.post("/api/transfers", {"from_account_id": acct["chk"]["id"], "to_account_id": acct["sav"]["id"],
                               "amount": "2500.00", "transaction_date": d(7, 1), "clear_date": d(7, 1),
                               "notes": "Move surplus to the reserve"})

    # ---- fundraisers
    spring = bm.post("/api/fundraisers", {"name": "Spring Concert & Silent Auction", "start_date": d(4, 18),
                                          "end_date": d(4, 18), "description": "Annual spring concert with a silent auction in the lobby.",
                                          "budget_ids": [b_spring["id"], b_costs["id"]], "filter_text": "spring concert"})
    for name in ("Tickets", "Silent auction", "Reception"):
        spring = bm.post(f"/api/fundraisers/{spring['id']}/buckets", {"name": name})
    bucket = {b["name"]: b["id"] for b in spring["buckets"]["items"] if b.get("id")}
    for t, i, name in ((t_gate, 0, "Tickets"), (t_gate, 1, "Silent auction"), (t_print, 0, "Tickets"),
                       (t_food, 0, "Reception")):
        al = t["allocations"][i]
        bm.put(f"/api/fundraisers/{spring['id']}/lines/{al['id']}",
               {"buckets": [{"bucket_id": bucket[name], "amount": al["amount"]}]})
    bm.post("/api/fundraisers", {"name": "Fall Mattress Sale", "start_date": d(9, 27), "end_date": d(9, 27),
                                 "budget_ids": [b_fall["id"]]})

    # ---- reminders
    month_end = (today.replace(day=1) + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
    bm.post("/api/reminders", {"scope": "ORGANIZATION", "title": "Reconcile the bank statements",
                               "details": "Both accounts. Attach the statements to the Fiscal Year.",
                               "due_date": today.isoformat(), "repeat_every": 1, "repeat_unit": "MONTH",
                               "link_type": "BANK_ACCOUNT", "link_id": acct["chk"]["id"]})
    bm.post("/api/reminders", {"scope": "ORGANIZATION", "title": "File the quarterly sales tax return",
                               "due_date": (today - dt.timedelta(days=2)).isoformat(), "repeat_every": 3,
                               "repeat_unit": "MONTH"})
    bm.post("/api/reminders", {"scope": "ORGANIZATION", "title": f"Present the {year + 1} budget to the board",
                               "due_date": month_end.isoformat(), "notify_days_before": 14,
                               "link_type": "FISCAL_YEAR", "link_id": fy["id"]})
    bm.post("/api/reminders", {"scope": "PERSONAL", "title": "Order deposit slips", "due_date": today.isoformat()})
    bm.post("/api/reminders", {"scope": "ORGANIZATION", "title": "Renew the liability insurance",
                               "due_date": (today + dt.timedelta(days=75)).isoformat(), "notify_days_before": 30,
                               "repeat_every": 1, "repeat_unit": "YEAR"})
    # ---- last year is closed (its audit signoff attached)
    bm.upload("fiscal_year", last["id"], "audit-signoff.pdf",
              pdf("Audit signoff", [f"{ORG} - Fiscal Year {year - 1}", "Reviewed by the audit committee (demo document)."]),
              "&document_type=AUDIT_SIGNOFF")
    bm.post(f"/api/fiscal-years/{last['id']}/close", {"confirm_reviewed": True})
    # 1.6.8 (#66): the password is not printed (CodeQL: clear-text logging) - it is the PASSWORD constant above.
    print(f"Demo organization '{ORG}' created at {base}. Sign in as {ADMIN}, demo-budget, demo-register or "
          f"demo-auditor with the demo password (PASSWORD near the top of scripts/demo_data.py).")
    return {"organization": ORG, "fiscal_years": [year - 1, year],
            "sign_ins": [ADMIN] + [u[0] for u in USERS]}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Fill a new, empty PennyWarden installation with made-up data.")
    ap.add_argument("url", nargs="?", default="http://127.0.0.1:8787")
    ap.add_argument("--profile", choices=("demo", "test"), default="demo",
                    help="demo: the small published demo (default); test: the larger private test data set (#272), "
                         "credentials from PW_TESTDATA_PASSWORD / PW_TESTDATA_PASSPHRASE")
    ap.add_argument("--fy-start-month", type=int, default=7, help="test profile: first month of the Fiscal Year (1-12)")
    ap.add_argument("--backup", help="test profile: also write an encrypted backup (.fmbak) to this file")
    ap.add_argument("--summary", help="test profile: write a JSON summary (no secrets) to this file")
    a = ap.parse_args()
    if a.profile == "demo":
        main(a.url.rstrip("/"))
    else:
        import test_data
        test_data.main(a.url.rstrip("/"), a.fy_start_month, a.backup, a.summary)
