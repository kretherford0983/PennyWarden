"""2.1.0 (#312): the Donations module, part 1 - donation receipt letters. Administrators set up the receipt (EIN,
address, template) and test print with sample data only; Register Users mark deposit lines as donations and print one
receipt per donor; the other financial roles and Auditors see them. Reprints: DUPLICATE (same number) for the same
content, CORRECTED (new number, replaces the last) for changed content; a voided deposit's receipts are void."""
from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

SETUP = {"signer_name": "Jordan Sample", "signer_title": "Treasurer"}
# 2.1.0 (#314): the EIN and address are on the organization profile (System/About)
ORG = {"name": "Acme Org", "ein": "12-3456789", "address_line1": "100 Sample Avenue", "city": "Sample Town",
       "state_region": "US", "postal_code": "55555"}


def text(pdf: bytes) -> str:
    return " ".join(" ".join(p.extract_text().split()) for p in PdfReader(io.BytesIO(pdf)).pages)


def enable(env, on=True):
    r = env.admin.put("/api/system/modules", {"donations": on})
    assert r.status_code == 200, r.text
    return r.json()


def setup(env, **kw):
    r = env.admin.put("/api/system/organization", ORG)
    assert r.status_code == 200, r.text
    cfg = dict(env.admin.get("/api/donations/setup").json()["config"], **SETUP, **kw)
    r = env.admin.put("/api/donations/setup", {"config": cfg})
    assert r.status_code == 200, r.text
    return r.json()


def donor(env, name="Sample Donor One", address=True):
    body = {"entity_type": "INDIVIDUAL", "primary_contact": name, "confirmations": ["DUPLICATE_ENTITY"]}
    if address:
        body.update({"address_line1": "12 Example Road", "city": "Sample Town", "state_region": "US",
                     "postal_code": "55555"})
    r = env.ru.post("/api/entities", body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def dep(env, base):
    enable(env)
    setup(env)
    a, b = donor(env), donor(env, "Sample Donor Two")
    t = env.txn(base["acct"]["id"], "DEPOSIT", [
        {"budget_id": base["inc_leaf"], "amount": "100.00", "entity_id": a["id"], "description": "Gift"},
        {"budget_id": base["inc_leaf"], "amount": "50.00", "entity_id": a["id"], "description": "Gift 2"},
        {"budget_id": base["inc_leaf"], "amount": "75.00", "entity_id": b["id"], "description": "Gift"},
        {"budget_id": base["inc_leaf"], "amount": "20.00", "entity_id": b["id"], "description": "Dues"}],
        date="2026-08-03")
    allocs = [x["id"] for x in t["allocations"]]
    return {"t": t, "a": a, "b": b, "allocs": allocs, "url": f"/api/donations/transactions/{t['id']}"}


def mark(env, dep, lines, client=None):
    return (client or env.ru).put(dep["url"] + "/lines", {"lines": lines})


def mark_all(env, dep, **extra):
    r = mark(env, dep, [{"allocation_id": x, "donation": True, **extra} for x in dep["allocs"][:3]]
             + [{"allocation_id": dep["allocs"][3], "donation": False}])
    assert r.status_code == 200, r.text
    return r.json()


def print_receipt(env, dep, who, confirmations=(), client=None):
    return (client or env.ru).post(dep["url"] + "/receipts", {"donor_entity_id": dep[who]["id"],
                                                              "confirmations": list(confirmations)})


def test_module_off_by_default(env, base):
    assert env.admin.get("/api/system/modules").json()["donations"] is False
    assert env.ru.get("/api/auth/me").json()["modules"]["donations"] is False
    assert env.admin.get("/api/donations/setup").status_code == 404
    enable(env)
    assert env.ru.get("/api/auth/me").json()["modules"]["donations"] is True
    rows = env.admin.get("/api/audit-events?action=MODULE_ENABLED").json()
    items = rows["items"] if isinstance(rows, dict) else rows
    assert any("donations_enabled" in str(i) for i in items)


def test_setup_is_administrator_only_and_validated(env, base):
    enable(env)
    for c in (env.ru, env.bm, env.auditor):
        assert c.get("/api/donations/setup").status_code == 403
    s = env.admin.get("/api/donations/setup").json()
    assert s["missing"] == ["the organization's EIN", "the organization's address"]
    assert {v["name"] for v in s["variables"]} >= {"DONOR_NAME", "AMOUNT", "ORG.EIN", "ORG.NAME", "RECEIPT_NO",
                                                   "SIGNER"}
    bad = env.admin.put("/api/system/organization", {**ORG, "ein": "12345678"})
    assert bad.status_code == 422 and "12-3456789" in bad.json()["error"]["message"]
    bad = env.admin.put("/api/donations/setup", {"config": {**s["config"], "body": "Thanks {DONOR_NAM}"}})
    assert bad.status_code == 422 and "DONOR_NAM" in bad.text
    assert setup(env)["missing"] == []
    # the preview and the test print use sample data only
    r = env.admin.post("/api/donations/setup/test-print", {})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    body = text(r.content)
    assert "SAMPLE DONOR" in body and "SAMPLE - NOT A RECEIPT" in body and "12-3456789" in body
    r = env.admin.post("/api/donations/setup/preview", {"config": {**setup(env)["config"], "title": "Gift Receipt"}})
    assert "Gift Receipt" in text(r.content)


def test_administrator_never_sees_deposits(env, dep):
    assert env.admin.get(dep["url"]).status_code == 403
    assert mark(env, dep, [], client=env.admin).status_code == 403
    assert print_receipt(env, dep, "a", client=env.admin).status_code == 403


def test_view_roles_see_but_only_register_users_mark_and_print(env, dep):
    for c in (env.bm, env.bu, env.auditor, env.ru):
        assert c.get(dep["url"]).status_code == 200
    for c in (env.bm, env.bu, env.auditor):
        assert mark(env, dep, [{"allocation_id": dep["allocs"][0], "donation": True}], client=c).status_code == 403
        assert print_receipt(env, dep, "a", client=c).status_code == 403


def test_one_receipt_per_donor_with_the_required_statement(env, dep):
    out = mark_all(env, dep, purpose="Building fund")
    donors = {d["name"]: d for d in out["donors"]}
    assert donors["Sample Donor One"]["amount"] == "$150.00" and donors["Sample Donor Two"]["amount"] == "$75.00"
    assert all(d["next_kind"] == "ORIGINAL" for d in out["donors"])
    r = print_receipt(env, dep, "a")
    assert r.status_code == 200, r.text
    assert r.headers["x-receipt-number"] == "R-2026-0001" and r.headers["x-receipt-kind"] == "ORIGINAL"
    body = text(r.content)
    for s in ("Sample Donor One", "12-3456789", "$150.00", "August 3, 2026", "R-2026-0001", "Building fund",
              "No goods or services were provided in exchange for this contribution.", "Jordan Sample",
              "Treasurer"):
        assert s in body, s
    r2 = print_receipt(env, dep, "b")
    assert r2.headers["x-receipt-number"] == "R-2026-0002"
    # the record copies are attachments of the deposit
    atts = env.auditor.get(f"/api/attachments?owner_type=transaction&owner_id={dep['t']['id']}").json()
    docs = [x for x in atts if x.get("document_type") == "DONATION_RECEIPT"]
    assert len(docs) == 2
    seen = env.auditor.get(dep["url"]).json()
    assert [(x["number"], x["kind"], x["donor"]) for x in seen["receipts"]] == [
        ("R-2026-0001", "ORIGINAL", "Sample Donor One"), ("R-2026-0002", "ORIGINAL", "Sample Donor Two")]


def test_goods_or_services_statement(env, dep):
    r = mark(env, dep, [{"allocation_id": dep["allocs"][0], "donation": True, "goods_cents": 3000}])
    assert r.status_code == 422 and "Describe" in r.json()["error"]["message"]
    r = mark(env, dep, [{"allocation_id": dep["allocs"][0], "donation": True, "goods_cents": 99999,
                         "goods_description": "Dinner"}])
    assert r.status_code == 422
    r = mark(env, dep, [{"allocation_id": dep["allocs"][0], "donation": True, "goods_cents": 3000,
                         "goods_description": "Dinner for one"}])
    assert r.status_code == 200
    body = text(print_receipt(env, dep, "a").content)
    assert "Goods or services valued at $30.00 were provided in exchange for this contribution (Dinner for one)." \
        in body
    assert "No goods or services" not in body


def test_duplicate_then_corrected(env, dep):
    mark_all(env, dep)
    first = print_receipt(env, dep, "a")
    again = print_receipt(env, dep, "a")
    assert again.headers["x-receipt-kind"] == "DUPLICATE" and again.headers["x-receipt-number"] == "R-2026-0001"
    assert "DUPLICATE of receipt R-2026-0001" in text(again.content)
    # the amount changes: a corrected receipt with a new number, after a confirmation
    mark(env, dep, [{"allocation_id": dep["allocs"][1], "donation": False}])
    assert {d["name"]: d["next_kind"] for d in env.ru.get(dep["url"]).json()["donors"]}["Sample Donor One"] == \
        "CORRECTED"
    r = print_receipt(env, dep, "a")
    assert r.status_code == 409 and r.json()["error"]["warnings"][0]["code"] == "CORRECTED_RECEIPT"
    r = print_receipt(env, dep, "a", ["CORRECTED_RECEIPT"])
    assert r.headers["x-receipt-kind"] == "CORRECTED" and r.headers["x-receipt-number"] == "R-2026-0002"
    body = text(r.content)
    assert "replaces receipt R-2026-0001" in body and "$100.00" in body
    rec = env.ru.get(dep["url"]).json()["receipts"]
    assert [(x["number"], x["kind"], x["replaces"], x["superseded"]) for x in rec] == [
        ("R-2026-0001", "ORIGINAL", None, True), ("R-2026-0001", "DUPLICATE", "R-2026-0001", True),
        ("R-2026-0002", "CORRECTED", "R-2026-0001", False)]
    assert first.status_code == 200


def test_void_deposit_refuses_and_shows_receipts_void(env, dep):
    mark_all(env, dep)
    print_receipt(env, dep, "a")
    r = env.ru.post(f"/api/transactions/{dep['t']['id']}/void", {"reason": "error", "confirm_irreversible": True})
    assert r.status_code == 200, r.text
    out = env.ru.get(dep["url"]).json()
    assert out["printable"] is False and all(x["void"] for x in out["receipts"])
    r = print_receipt(env, dep, "a")
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_PRINTABLE"
    assert mark(env, dep, [{"allocation_id": dep["allocs"][0], "donation": False}]).status_code == 409


def test_setup_incomplete_and_no_address(env, base):
    enable(env)
    d = donor(env, "No Address Donor", address=False)
    t = env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "10.00",
                                                 "entity_id": d["id"]}])
    dep = {"url": f"/api/donations/transactions/{t['id']}", "a": d}
    assert mark(env, dep, [{"allocation_id": t["allocations"][0]["id"], "donation": True}]).status_code == 200
    r = print_receipt(env, dep, "a")
    assert r.status_code == 409 and r.json()["error"]["code"] == "SETUP_INCOMPLETE"
    setup(env)
    r = print_receipt(env, dep, "a")
    assert r.status_code == 409 and r.json()["error"]["warnings"][0]["code"] == "NO_DONOR_ADDRESS"
    assert print_receipt(env, dep, "a", ["NO_DONOR_ADDRESS"]).status_code == 200


def test_withdrawals_are_not_deposits(env, base):
    enable(env)
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "10.00"}])
    r = env.ru.get(f"/api/donations/transactions/{t['id']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_A_DEPOSIT"


def test_marking_is_audited(env, dep):
    mark_all(env, dep, purpose="Scholarships")
    mark(env, dep, [{"allocation_id": dep["allocs"][2], "donation": False}])
    print_receipt(env, dep, "a")
    rows = env.auditor.get("/api/audit-events?action=DONATION_MARKED").json()
    items = rows["items"] if isinstance(rows, dict) else rows
    assert len(items) == 4
    rows = env.auditor.get("/api/audit-events?action=DONATION_RECEIPT_PRINTED").json()
    items = rows["items"] if isinstance(rows, dict) else rows
    assert len(items) == 1


# ---------------------------------------------------------------- 2.1.0 polish (Kyle, 2026-10-22): date received, {DETAILS}
def test_date_received_per_line(env, dep):
    a1, a2 = dep["allocs"][0], dep["allocs"][1]
    r = mark(env, dep, [{"allocation_id": a1, "donation": True, "date_received": "2026-08-04"}])
    assert r.status_code == 422 and "after the deposit" in r.json()["error"]["message"]       # deposit: 2026-08-03
    r = mark(env, dep, [{"allocation_id": a1, "donation": True, "date_received": "2026-07-28"},
                        {"allocation_id": a2, "donation": True}])
    assert r.status_code == 200, r.text
    lines = {x["allocation_id"]: x for x in r.json()["lines"]}
    assert lines[a1]["date_received"] == "2026-07-28" and lines[a2]["date_received"] is None
    donor = next(x for x in r.json()["donors"] if x["name"] == "Sample Donor One")
    assert donor["dates"] == ["2026-07-28", "2026-08-03"]
    body = text(print_receipt(env, dep, "a").content)
    assert "July 28, 2026 and August 3, 2026" in body
    # one line, its own date: just that date; changing it makes the next receipt a corrected one
    mark(env, dep, [{"allocation_id": a2, "donation": False}])
    body = text(print_receipt(env, dep, "a", ["CORRECTED_RECEIPT"]).content)
    assert "July 28, 2026" in body and "August 3, 2026" not in body.split("Receipt No.")[1].split("Amount")[0]


def test_details_are_written_per_donor_and_dropped_when_empty(env, dep):
    s = env.admin.get("/api/donations/setup").json()
    assert "{DETAILS}" in s["defaults"]["body"]
    setup(env, body="Thank you for your gift to {ORG.NAME}.\n\n{DETAILS}\n\nPlease keep this letter.")
    out = mark_all(env, dep)
    assert out["details_enabled"] is True and "DETAILS" not in {v["name"] for v in out["variables"]}
    # a bad variable or {DETAILS} itself is refused
    for bad in ("Gift of {AMOUNTT}", "Again: {DETAILS}"):
        r = env.ru.put(dep["url"] + "/lines", {"lines": [], "donors": [{"entity_id": dep["a"]["id"], "details": bad}]})
        assert r.status_code == 422, bad
    r = env.ru.put(dep["url"] + "/lines", {"lines": [], "donors": [
        {"entity_id": dep["a"]["id"], "details": "Your donation of ${AMOUNT} will feed 4 families of 5."}]})
    assert r.status_code == 200, r.text
    assert next(x for x in r.json()["donors"] if x["entity_id"] == dep["a"]["id"])["details"].startswith("Your donation")
    body = text(print_receipt(env, dep, "a").content)
    assert "Your donation of $150.00 will feed 4 families of 5." in body
    # the other donor has none: no empty paragraph, no "no data" warning for {DETAILS}
    r = print_receipt(env, dep, "b")
    assert r.status_code == 200, r.text
    assert "Thank you for your gift to Acme Org. Please keep this letter." in text(r.content)
    # changing the details is a change to the receipt: corrected, not a duplicate
    env.ru.put(dep["url"] + "/lines", {"lines": [], "donors": [{"entity_id": dep["a"]["id"], "details": "Changed."}]})
    assert next(x for x in env.ru.get(dep["url"]).json()["donors"] if x["entity_id"] == dep["a"]["id"])["next_kind"] \
        == "CORRECTED"
    ev = env.auditor.get("/api/audit-events?action=DONATION_DETAILS_UPDATED").json()["items"]
    assert len(ev) == 2
    # a template without {DETAILS}: the dialog doesn't offer them
    setup(env, body="Thank you.")
    assert env.ru.get(dep["url"]).json()["details_enabled"] is False
    assert env.ru.put(dep["url"] + "/lines", {"lines": [], "donors": [{"entity_id": 999999, "details": "x"}]}
                      ).status_code == 422
