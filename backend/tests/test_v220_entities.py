"""2.2.0 (#315, #316, #317): entity display name, mailing address and EIN; first and last name with a name order per
user and Names to review; {PAYEE.*} / {DONOR.*} variables and a configurable addressee block.

Decisions (Kyle, 2026-10-22): "same as" falls back at read time (nothing is copied); the name prints on checks,
envelopes, letters and receipts, the display name everywhere else; the upgrade splits the Primary Contact at the first
space and lists every split name until it is edited or confirmed."""
from __future__ import annotations

from sqlalchemy import create_engine, text as sql

from test_v210_donations import enable, setup, text  # noqa: F401


def _ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def _ent(env, **body):
    return _ok(env.ru.post("/api/entities", {"confirmations": ["DUPLICATE_ENTITY"], **body}), 201)


def test_first_and_last_name_and_the_legacy_contact(env):
    """BR-028 / AC-ENT-001: an Individual needs a first name; the last name is optional."""
    assert env.ru.post("/api/entities", {"entity_type": "INDIVIDUAL", "last_name": "Doe"}).status_code == 422
    e = _ent(env, entity_type="INDIVIDUAL", first_name="Jane", last_name="Doe")
    assert (e["first_name"], e["last_name"], e["display_name"], e["primary_contact"]) == ("Jane", "Doe", "Jane Doe",
                                                                                          "Jane Doe")
    one = _ent(env, entity_type="INDIVIDUAL", first_name="Cher")
    assert one["display_name"] == "Cher" and one["last_name"] is None
    # the older `primary_contact` is still accepted, split at the first space
    old = _ent(env, entity_type="INDIVIDUAL", primary_contact="  Mary   Ann Smith ")
    assert (old["first_name"], old["last_name"]) == ("Mary", "Ann Smith")
    org = _ent(env, entity_type="ORGANIZATION", organization_name="Acme Supplies", first_name="Bob", last_name="Smith")
    assert org["display_name"] == "Acme Supplies" and org["primary_contact"] == "Bob Smith"
    # search matches the last name and the full name
    assert old["id"] in {x["id"] for x in _ok(env.bu.get("/api/entities?search=Mary Ann"))}
    assert old["id"] in {x["id"] for x in _ok(env.bu.get("/api/entities?search=Smith"))}


def test_display_name_mailing_address_and_ein(env, base):
    """#315: the display name everywhere but printed documents; the mailing address on letters, envelopes and
    receipts; both fall back when "same as"; EIN for organizations only; duplicates compare both names."""
    e = _ent(env, entity_type="ORGANIZATION", organization_name="Example Volunteer Fire Club Inc",
             display_name_custom="Fire Club", address_line1="1 Station Road", city="Sample Town", state_region="US",
             postal_code="55555", mailing_address_line1="P.O. Box 77", mailing_city="Sample Town",
             mailing_state_region="US", mailing_postal_code="55556", ein="123456789")
    assert e["display_name"] == "Fire Club" and e["name"] == "Example Volunteer Fire Club Inc"
    assert e["ein"] == "12-3456789" and e["mailing_same"] is False and e["display_name_same"] is False
    assert env.ru.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "X",
                                         "ein": "12-34"}).status_code == 422
    assert env.ru.post("/api/entities", {"entity_type": "INDIVIDUAL", "first_name": "Y",
                                         "ein": "12-3456789"}).status_code == 422
    # the register shows the display name (BR-029)
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "1.00"}],
                entity_id=e["id"])
    assert t["entity"]["display_name"] == "Fire Club"
    # the display name is a duplicate candidate too (BR-030)
    r = env.ru.post("/api/entities", {"entity_type": "ORGANIZATION", "organization_name": "Fire Club"})
    assert r.status_code == 409 and "DUPLICATE_ENTITY" in r.text
    assert env.bu.get("/api/entities?search=Fire Club").json()[0]["id"] == e["id"]
    # ticking "same as" again (empty values) clears them: back to the name and the address
    e2 = _ok(env.ru.patch(f"/api/entities/{e['id']}", {"display_name_custom": None, "mailing_address_line1": None,
                                                      "mailing_city": None, "mailing_state_region": None,
                                                      "mailing_postal_code": None}))
    assert e2["display_name"] == "Example Volunteer Fire Club Inc" and e2["mailing_same"] is True


def test_receipt_prints_the_name_and_mailing_address_and_the_addressee_block(env, base):
    """#315 / #317: receipts print the name (not the display name) and the mailing address; the addressee block is
    configurable with {DONOR.*} and its default prints as before."""
    enable(env)
    setup(env)
    d = _ent(env, entity_type="INDIVIDUAL", first_name="Robert", last_name="Example", display_name_custom="Bobby",
             address_line1="12 Home Street", city="Sample Town", state_region="US", postal_code="55555",
             mailing_address_line1="P.O. Box 9", mailing_city="Sample Town", mailing_state_region="US",
             mailing_postal_code="55555")
    don = _ok(env.ru.post("/api/donations", {"donor_entity_id": d["id"], "details": "",
                                             "lines": [{"kind": "MONEY", "amount_cents": 1000}]}), 201)
    pdf = env.ru.post(f"/api/donations/{don['id']}/receipts/preview").content
    t = text(pdf)
    assert "Robert Example" in t and "P.O. Box 9" in t and "12 Home Street" not in t and "Bobby" not in t
    cfg = _ok(env.admin.get("/api/donations/setup"))["config"]
    assert cfg["addressee"] == ["{DONOR.NAME}", "{DONOR.MAILING_ADDRESS}"]
    assert env.admin.put("/api/donations/setup", {"config": {**cfg, "addressee": ["{PAYEE.NAME}"]}}).status_code == 422
    _ok(env.admin.put("/api/donations/setup", {"config": {**cfg, "addressee": [
        "{DONOR.FIRST_NAME} {donor.last_name}", "Attn: {DONOR.ENTITY_NUMBER}", "{DONOR.ADDRESS}"],
        "salutation": "Dear {DONOR.FIRST_NAME},"}}))
    t = text(env.ru.post(f"/api/donations/{don['id']}/receipts/preview").content)
    assert "Attn: " + d["entity_number"] in t and "12 Home Street" in t and "Dear Robert," in t
    assert "P.O. Box 9" not in t


def test_letter_addressee_and_payee_variables(env, base):
    """#317: {PAYEE.*} in letters; the letter's addressee block is validated and defaults to name + mailing."""
    assert env.admin.put("/api/system/modules", {"checks": True}).status_code == 200
    letter = _ok(env.admin.post("/api/checks/documents", {"kind": "LETTER"}), 201)
    assert letter["config"]["addressee"] == ["{PAYEE.NAME}", "{PAYEE.MAILING_ADDRESS}"]
    cfg = {**letter["config"], "addressee": ["{DONOR.NAME}"]}
    assert env.admin.put(f"/api/checks/documents/{letter['id']}", {"name": letter["name"], "config": cfg}).status_code == 422
    cfg = {**letter["config"], "addressee": ["{PAYEE.DISPLAY_NAME}", "{PAYEE.MAILING_ADDRESS}"],
           "salutation": "Hello {PAYEE.FIRST_NAME},"}
    _ok(env.admin.put(f"/api/checks/documents/{letter['id']}", {"name": letter["name"], "config": cfg}))
    p = env.admin.post(f"/api/checks/documents/{letter['id']}/preview", {})
    assert p.status_code == 200 and "SAMPLE VENDOR COMPANY" in text(p.content)


def test_name_order_preference(env):
    assert _ok(env.ru.get("/api/auth/me"))["name_order"] == "FIRST_LAST"
    _ok(env.ru.put("/api/me/preferences", {"name_order": "LAST_FIRST"}))
    assert _ok(env.ru.get("/api/auth/me"))["name_order"] == "LAST_FIRST"
    assert env.ru.put("/api/me/preferences", {"name_order": "SIDEWAYS"}).status_code == 422


def test_upgrade_splits_names_and_lists_them_to_review(env, tmp_path):
    """#316: the migration splits the Primary Contact at the first space; Names to review lists every split name
    (Budget Managers) until it is edited or confirmed."""
    a = _ent(env, entity_type="INDIVIDUAL", first_name="Placeholder")
    b = _ent(env, entity_type="ORGANIZATION", organization_name="Club", first_name="Placeholder")
    c = _ent(env, entity_type="INDIVIDUAL", first_name="Placeholder")
    from alembic import command
    from fmpoc.db import alembic_config
    url = f"sqlite:///{env.settings.database_path}"
    env.app.state.engine.dispose()
    cfg = alembic_config(url)
    command.downgrade(cfg, "0056_year_end_statements")
    eng = create_engine(url)
    with eng.begin() as con:
        for eid, contact in ((a["id"], "John Smith Jr."), (b["id"], "Pat"), (c["id"], "   ")):
            con.execute(sql("UPDATE entity SET primary_contact = :p WHERE id = :i"), {"p": contact, "i": eid})
    eng.dispose()
    command.upgrade(cfg, "head")
    rv = _ok(env.bm.get("/api/entities/names-to-review"))
    by = {x["id"]: x for x in rv}
    assert (by[a["id"]]["first_name"], by[a["id"]]["last_name"]) == ("John", "Smith Jr.")
    assert (by[b["id"]]["first_name"], by[b["id"]]["last_name"]) == ("Pat", None)
    assert c["id"] not in by                                      # nothing to split
    assert env.ru.get("/api/entities/names-to-review").status_code == 403
    assert env.admin.get("/api/entities/names-to-review").status_code == 403
    _ok(env.bm.post(f"/api/entities/{b['id']}/confirm-name"))
    # another change leaves it listed; saving the names (as the entity form does) counts as reviewed
    _ok(env.bm.patch(f"/api/entities/{a['id']}", {"notes": "x", "confirmations": ["DUPLICATE_ENTITY"]}))
    assert a["id"] in {x["id"] for x in _ok(env.bm.get("/api/entities/names-to-review"))}
    _ok(env.bm.patch(f"/api/entities/{a['id']}", {"first_name": "John", "last_name": "Smith, Jr.",
                                                  "confirmations": ["DUPLICATE_ENTITY"]}))
    assert _ok(env.bm.get("/api/entities/names-to-review")) == []
    ev = _ok(env.auditor.get("/api/audit-events?action=ENTITY_NAME_CONFIRMED"))["items"]
    assert len(ev) == 1
