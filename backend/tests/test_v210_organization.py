"""2.1.0 (#314): the organization profile - the organization itself as an entity, maintained by Administrators in
System/About, usable wherever an entity is chosen, read-only in Entities, and the source of the {ORG.*} variables."""
from __future__ import annotations

import io

from pypdf import PdfReader

from fmpoc.services.checkprint import patterns

PROFILE = {"name": "Acme Org", "address_line1": "400 Elm Street", "address_line2": "Suite 2", "city": "Cedar Valley",
           "state_region": "IA", "postal_code": "50000", "phone": "555-555-0100", "email": "office@example.org",
           "ein": "12-3456789"}


def text(pdf: bytes) -> str:
    return " ".join(" ".join(p.extract_text().split()) for p in PdfReader(io.BytesIO(pdf)).pages)


def org_entity(env):
    rows = env.bm.get("/api/entities?search=Acme").json()
    rows = rows["items"] if isinstance(rows, dict) else rows
    return next(e for e in rows if e["is_organization"])


def test_created_at_initialization_and_edited_by_administrators(env, base):
    p = env.admin.get("/api/system/organization").json()
    assert p["name"] == "Acme Org" and p["ein"] is None and p["entity_number"].startswith("ENT-")
    for c in (env.ru, env.bm, env.bu):
        assert c.put("/api/system/organization", PROFILE).status_code == 403
    assert env.auditor.get("/api/system/organization").status_code == 200        # read-only (system.view)
    r = env.admin.put("/api/system/organization", PROFILE)
    assert r.status_code == 200, r.text
    assert r.json()["address"] == ["400 Elm Street", "Suite 2", "Cedar Valley, IA 50000"]
    # a field left out keeps its value; the name can change on its own as before (#126)
    r = env.admin.put("/api/system/organization", {"name": "Acme Community Org"})
    assert r.json()["ein"] == "12-3456789" and r.json()["city"] == "Cedar Valley"
    assert env.admin.get("/api/system/status").json()["workspace_name"] == "Acme Community Org"
    assert env.admin.put("/api/system/organization", {"name": "Acme Org", "ein": "123456789"}).status_code == 422
    ev = env.admin.get("/api/audit-events?action=ORGANIZATION_UPDATED").json()["items"]
    assert ev and ev[0]["after"]["ein"] == "12-3456789"
    assert env.admin.get("/api/audit-events?action=ORGANIZATION_RENAMED").json()["items"]


def test_usable_as_an_entity_but_read_only_in_entities(env, base):
    env.admin.put("/api/system/organization", PROFILE)
    e = org_entity(env)
    assert e["display_name"] == "Acme Org" and e["is_organization"] and e["ein"] == "12-3456789"
    # a lump cash deposit recorded as the organization's
    t = env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "310.00",
                                                 "description": "Raffle table cash"}], entity_id=e["id"])
    assert t["entity"]["id"] == e["id"]
    for c in (env.ru, env.bm):
        r = c.patch(f"/api/entities/{e['id']}", {"organization_name": "Other"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "ORGANIZATION_ENTITY"
        r = c.post(f"/api/entities/{e['id']}/inactivate", {"reason": "x"})
        assert r.status_code == 409
    # renaming the organization renames its entity
    env.admin.put("/api/system/organization", {"name": "Acme Renamed"})
    assert env.bm.get(f"/api/entities/{e['id']}").json()["display_name"] == "Acme Renamed"


def test_org_variables_parse_and_resolve():
    for ctx in (patterns.CHECK, patterns.STUB, patterns.LETTER, patterns.ENVELOPE, patterns.RECEIPT):
        assert [t.var for t in patterns.parse("{ORG.NAME} {Org.Ein}", ctx) if t.var] == ["ORG.NAME", "ORG.EIN"]
    r = patterns.resolve("{ORG.CITY}, {ORG.STATE}", {"ORG.CITY": "Cedar Valley", "ORG.STATE": "IA"}, patterns.CHECK)
    assert r.text == "Cedar Valley, IA"
    for bad, ctx in (("{ORG.ADDRESS}", patterns.CHECK), ("{ORG.NOPE}", patterns.LETTER)):
        try:
            patterns.parse(bad, ctx)
            raise AssertionError(bad)
        except patterns.PatternError:
            pass
    assert patterns.parse("{ORG}", patterns.CHECK)[0].var == "ORG"                # the older name still works


def test_org_variables_in_a_letter_and_on_a_receipt(env, base):
    from tests.test_v200_checks import PRESET, enable
    from tests.test_v200_letters import setup_docs, vendor
    env.admin.put("/api/system/organization", PROFILE)
    enable(env)
    style = env.admin.post("/api/checks/styles", {"preset_key": PRESET}).json()
    letter, _env = setup_docs(env)
    cfg = dict(letter["config"], letterhead=["{ORG.NAME}", "{ORG.ADDRESS1}, {ORG.CITY}, {ORG.STATE} {ORG.ZIP}",
                                             "{ORG.PHONE} · {ORG.EMAIL} · EIN {ORG.EIN}"])
    assert env.admin.put(f"/api/checks/documents/{letter['id']}", {"name": letter["name"], "config": cfg}).status_code == 200
    env.ru.put(f"/api/checks/accounts/{base['acct']['id']}", {"check_style_id": style["id"]})
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "20.00"}],
                entity_id=vendor(env)["id"])
    r = env.ru.post(f"/api/checks/transactions/{t['id']}/letter", {"document_id": letter["id"]})
    assert r.status_code == 200, r.text
    body = text(r.content)
    assert "400 Elm Street, Cedar Valley, IA 50000" in body and "office@example.org" in body and "12-3456789" in body
    # the test print uses the sample organization, never real data
    r = env.admin.post(f"/api/checks/documents/{letter['id']}/test-print", {})
    assert "Sample Organization" in text(r.content) and "400 Elm Street" not in text(r.content)


def test_donations_use_the_profile_and_refuse_the_organization_as_donor(env, base):
    env.admin.put("/api/system/modules", {"donations": True})
    s = env.admin.get("/api/donations/setup").json()
    assert s["missing"] == ["the organization's EIN", "the organization's address"]
    env.admin.put("/api/system/organization", PROFILE)
    s = env.admin.get("/api/donations/setup").json()
    assert s["missing"] == [] and s["organization"]["ein"] == "12-3456789"
    assert "12-3456789" in text(env.admin.post("/api/donations/setup/test-print", {}).content)
    e = org_entity(env)
    t = env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "50.00"}], entity_id=e["id"])
    out = env.ru.get(f"/api/donations/transactions/{t['id']}").json()
    assert out["lines"][0]["donor_is_organization"] is True
    r = env.ru.put(f"/api/donations/transactions/{t['id']}/lines",
                   {"lines": [{"allocation_id": t["allocations"][0]["id"], "donation": True}]})
    assert r.status_code == 422 and "your own organization" in r.json()["error"]["message"]


def test_migration_creates_the_entity_and_moves_the_donation_ein(tmp_path):
    import json
    from alembic import command
    from sqlalchemy import create_engine
    from fmpoc.db import alembic_config, upgrade_database
    u = f"sqlite:///{tmp_path / 'm.sqlite3'}"
    command.upgrade(alembic_config(u), "0045_donation_receipts")
    eng = create_engine(u)
    cfg = {"ein": "98-7654321", "org_address": ["PO Box 12", "Cedar Valley, IA 50000-1234"], "title": "Thanks"}
    with eng.begin() as c:
        c.exec_driver_sql("INSERT INTO workspace (id, name, created_at, next_entity_number, bootstrap_completed_at) "
                          "VALUES (1, 'Sample Org', '2026-01-01', 7, '2026-01-01')")
        c.exec_driver_sql("INSERT INTO workspace (id, name, created_at, next_entity_number) "
                          "VALUES (2, 'not set up', '2026-01-01', 1)")
        c.exec_driver_sql("INSERT INTO donation_settings (workspace_id, config_json, updated_at) VALUES (1, ?, "
                          "'2026-01-01')", (json.dumps(cfg),))
    upgrade_database(u)
    with eng.connect() as c:
        rows = c.exec_driver_sql("SELECT workspace_id, entity_number, organization_name, address_line1, city, "
                                 "state_region, postal_code, ein FROM entity WHERE is_organization = 1").all()
        assert rows == [(1, "ENT-000007", "Sample Org", "PO Box 12", "Cedar Valley", "IA", "50000-1234",
                         "98-7654321")]
        assert c.exec_driver_sql("SELECT next_entity_number FROM workspace WHERE id = 1").scalar() == 8
        left = json.loads(c.exec_driver_sql("SELECT config_json FROM donation_settings").scalar())
        assert left == {"title": "Thanks"}
