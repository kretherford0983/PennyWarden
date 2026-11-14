"""2.4.0 polish (#503): organization logos shared by cover letters, envelopes, the invoice PDF, donation letters and
Branding - each place chooses the organization logo, its own, or none.

BR-ORG-LOGO-001..003 / AC-ORG-LOGO-001..005 (recorded in docs/implementation-notes.md); regression for BR-003 (only
Administrators manage them), BR-096 (validated, re-encoded uploads) and the audit rules.
"""
from __future__ import annotations

import hashlib
import io
import json

import pytest
from PIL import Image
from pypdf import PdfReader

from test_v200_build6 import img, upload
from test_v200_checks import enable, has_image
from test_v210_donations import enable as enable_donations
from test_v210_donations import setup as donation_setup


def org_upload(client, slot, data, name="logo.png"):
    return client.c.post(f"/api/system/organization/logos/{slot}", files={"file": (name, data, "image/png")},
                         headers={"X-CSRF-Token": client.csrf})


def colored(rgb) -> bytes:
    im = Image.new("RGB", (600, 240), rgb)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def doc(env, did):
    return next(x for x in env.admin.get("/api/checks/setup").json()["documents"] if x["id"] == did)


def image_colors(pdf: bytes) -> set[tuple]:
    """The color of each picture drawn on the first page (our test logos are one solid color)."""
    out = set()
    for im in PdfReader(io.BytesIO(pdf)).pages[0].images:
        out.add(Image.open(io.BytesIO(im.data)).convert("RGB").getpixel((5, 5)))
    return out


RED, GREEN, BLUE = (200, 30, 30), (30, 160, 60), (30, 80, 160)


@pytest.fixture
def org_logo(env):
    r = org_upload(env.admin, "full", colored(RED))
    assert r.status_code == 200, r.text
    return r.json()


def test_only_administrators_manage_the_organization_logos_and_it_is_audited(env, base, org_logo):
    assert org_logo["logos"]["full"]["width"] == 600 and org_logo["logos"]["mark"] is None
    got = env.admin.get("/api/system/organization/logos/full")
    assert got.status_code == 200 and got.content.startswith(b"\x89PNG")          # re-encoded
    for c in (env.bm, env.ru):
        assert org_upload(c, "full", img()).status_code == 403
        assert c.get("/api/system/organization/logos").status_code == 403
    assert org_upload(env.admin, "full", b"GIF89a" + b"0" * 100).status_code == 415
    assert org_upload(env.admin, "nope", img()).status_code == 422
    ev = env.admin.get("/api/audit-events?action=ORGANIZATION_LOGO_SET").json()["items"]
    assert ev and "iVBOR" not in json.dumps(ev) and "sha256" in json.dumps(ev)    # the fingerprint, never the image


def test_ac_org_logo_001_002_a_letter_follows_the_organization_logo(env, base, org_logo):
    enable(env)
    d = env.admin.post("/api/checks/documents", {"kind": "LETTER"}).json()
    assert d["config"]["logo_source"] == "NONE"                                     # BR-ORG-LOGO-002: default none
    pdf = env.admin.post(f"/api/checks/documents/{d['id']}/test-print", {}).content
    assert not has_image(pdf)
    cfg = {**d["config"], "logo_source": "ORG"}
    d = env.admin.put(f"/api/checks/documents/{d['id']}", {"name": d["name"], "config": cfg}).json()
    pdf = env.admin.post(f"/api/checks/documents/{d['id']}/test-print", {}).content
    assert image_colors(pdf) == {RED}
    org_upload(env.admin, "full", colored(GREEN))                                   # AC-ORG-LOGO-002: replaced
    pdf = env.admin.post(f"/api/checks/documents/{d['id']}/test-print", {}).content
    assert image_colors(pdf) == {GREEN}
    # its own logo overrides it; "No logo" prints none
    upload(env.admin, d["id"], colored(BLUE))
    d = doc(env, d["id"])
    assert d["config"]["logo_source"] == "OWN"
    assert image_colors(env.admin.post(f"/api/checks/documents/{d['id']}/test-print", {}).content) == {BLUE}
    pdf = env.admin.post(f"/api/checks/documents/{d['id']}/preview", {"config": {**d["config"], "logo_source": "NONE"}}).content
    assert not has_image(pdf)


def test_ac_org_logo_003_envelopes_print_the_logo_beside_the_return_address(env, base, org_logo):
    enable(env)
    d = env.admin.post("/api/checks/documents", {"kind": "ENVELOPE"}).json()
    plain = env.admin.post(f"/api/checks/documents/{d['id']}/test-print", {}).content
    assert not has_image(plain)
    cfg = {**d["config"], "logo_source": "ORG"}
    pdf = env.admin.post(f"/api/checks/documents/{d['id']}/test-print", {"config": cfg}).content
    assert image_colors(pdf) == {RED}


def test_ac_org_logo_003_invoice_pdf_uses_the_organization_logo(env, base, org_logo):
    assert env.admin.put("/api/system/modules", {"invoices": True}).status_code == 200
    cfg = env.admin.get("/api/invoices/setup/template").json()["config"]
    assert cfg["logo_source"] == "NONE"
    pdf = env.admin.post("/api/invoices/setup/template/preview", {**cfg, "logo_source": "ORG"}).content
    assert image_colors(pdf) == {RED}
    assert not has_image(env.admin.post("/api/invoices/setup/template/preview", cfg).content)


def test_ac_org_logo_003_donation_receipt_and_statement_letters(env, base, org_logo):
    enable_donations(env)
    out = donation_setup(env, logo_source="ORG", logo_position="RIGHT_ABOVE")
    assert out["config"]["statement_logo_source"] == "FOLLOW"
    assert image_colors(env.admin.post("/api/donations/setup/test-print", {}).content) == {RED}
    # the statement follows the receipt
    assert image_colors(env.admin.post("/api/donations/setup/statement-test-print", {}).content) == {RED}
    # its own logo for the statement
    r = env.admin.c.post("/api/donations/setup/logo/statement", files={"file": ("l.png", colored(BLUE), "image/png")},
                         headers={"X-CSRF-Token": env.admin.csrf})
    assert r.status_code == 200, r.text
    assert r.json()["config"]["statement_logo_source"] == "OWN" and r.json()["logos"]["statement"]
    assert image_colors(env.admin.post("/api/donations/setup/statement-test-print", {}).content) == {BLUE}
    assert image_colors(env.admin.post("/api/donations/setup/test-print", {}).content) == {RED}
    # none for the receipt: no picture (signature mode SPACE draws none either)
    cfg = env.admin.get("/api/donations/setup").json()["config"]
    pdf = env.admin.post("/api/donations/setup/preview", {"config": {**cfg, "logo_source": "NONE"}}).content
    assert not has_image(pdf)
    assert env.ru.post("/api/donations/setup/logo/receipt/remove").status_code == 403


def test_branding_slots_use_the_organization_logo(env, base, org_logo):
    b = env.admin.get("/api/system/branding").json()
    assert b["logo_sources"]["full"] == "OWN" and b["org_logos"]["full"]
    assert env.admin.get("/api/system/branding/logo/full").status_code == 404     # nothing of its own yet
    r = env.admin.put("/api/system/branding/logo/full/source", {"source": "ORG"})
    assert r.status_code == 200 and r.json()["logo_sources"]["full"] == "ORG"
    got = env.admin.get("/api/system/branding/logo/full")
    assert got.status_code == 200
    assert hashlib.sha256(got.content).hexdigest() == hashlib.sha256(
        env.admin.get("/api/system/organization/logos/full").content).hexdigest()
    assert env.admin.put("/api/system/branding/logo/full/source", {"source": "X"}).status_code == 422
    assert env.admin.get("/api/audit-events?action=BRANDING_LOGO_SOURCE_SET").json()["items"]


def test_ac_org_logo_005_removing_a_logo_in_use_warns_and_lists_the_places(env, base, org_logo):
    enable(env)
    d = env.admin.post("/api/checks/documents", {"kind": "LETTER"}).json()
    env.admin.put(f"/api/checks/documents/{d['id']}", {"name": d["name"], "config": {**d["config"], "logo_source": "ORG"}})
    env.admin.put("/api/system/branding/logo/full/source", {"source": "ORG"})
    usage = env.admin.get("/api/system/organization/logos").json()["usage"]["full"]
    assert f"Cover letter: {d['name']}" in usage and "Branding: logo" in usage
    r = env.admin.post("/api/system/organization/logos/full/remove", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert f"Cover letter: {d['name']}" in r.json()["error"]["warnings"][0]["details"]["places"]
    r = env.admin.post("/api/system/organization/logos/full/remove", {"confirmations": ["ORG_LOGO_IN_USE"]})
    assert r.status_code == 200 and r.json()["logos"]["full"] is None
    d = doc(env, d["id"])
    assert d["config"]["logo_source"] == "ORG"                                     # the setting stays
    assert not has_image(env.admin.post(f"/api/checks/documents/{d['id']}/test-print", {}).content)
    ev = env.admin.get("/api/audit-events?action=ORGANIZATION_LOGO_REMOVED").json()["items"]
    assert ev
    # an unused logo goes without a question
    org_upload(env.admin, "mark", img())
    assert env.admin.post("/api/system/organization/logos/mark/remove", {}).status_code == 200


def test_ac_org_logo_004_upgrade_moves_branding_logos_and_keeps_every_print_the_same(tmp_path):
    """Branding's logos become the organization logos; a letter / invoice PDF with the identical file uses them; a
    different file stays its own; places without a logo stay without."""
    from alembic import command
    from sqlalchemy import create_engine

    from fmpoc.db import alembic_config, upgrade_database
    u = f"sqlite:///{tmp_path / 'm.sqlite3'}"
    command.upgrade(alembic_config(u), "0085_entity_tax_exempt")
    eng = create_engine(u)
    same, other = colored(RED), colored(BLUE)
    sh_same, sh_other = hashlib.sha256(same).hexdigest(), hashlib.sha256(other).hexdigest()
    with eng.begin() as c:
        c.exec_driver_sql("INSERT INTO workspace (id, name, created_at, next_entity_number, bootstrap_completed_at) "
                          "VALUES (1, 'Sample Org', '2026-01-01', 1, '2026-01-01')")
        c.exec_driver_sql("INSERT INTO branding_settings (workspace_id, preset, logo_full_png, logo_full_sha256, "
                          "logo_full_width, logo_full_height, dark_logos, updated_at) "
                          "VALUES (1, 'pennywarden', ?, ?, 600, 240, 0, '2026-01-01')", (same, sh_same))
        for i, (png, sha) in enumerate([(same, sh_same), (other, sh_other), (None, None)], 1):
            c.exec_driver_sql("INSERT INTO check_document (id, workspace_id, kind, name, active, is_default, "
                              "config_json, created_at, updated_at, logo_png, logo_sha256) VALUES "
                              "(?, 1, 'LETTER', ?, 1, 0, '{}', '2026-01-01', '2026-01-01', ?, ?)",
                              (i, f"Letter {i}", png, sha))
        c.exec_driver_sql("INSERT INTO check_document (id, workspace_id, kind, name, active, is_default, config_json, "
                          "created_at, updated_at) VALUES (4, 1, 'ENVELOPE', 'Env', 1, 0, '{}', '2026-01-01', "
                          "'2026-01-01')")
        c.exec_driver_sql("INSERT INTO invoice_settings (workspace_id, number_pattern, next_seq, terms_days, "
                          "overdue_reminder_days, template_json, logo_png, logo_sha256, updated_at) VALUES "
                          "(1, 'INV-{SEQ:4}', 1, 30, 0, '{\"title\": \"Bill\"}', ?, ?, '2026-01-01')", (other, sh_other))
    upgrade_database(u)
    with eng.connect() as c:
        assert c.exec_driver_sql("SELECT slot, sha256 FROM organization_logo").all() == [("full", sh_same)]
        b = c.exec_driver_sql("SELECT logo_sources, logo_full_png FROM branding_settings").one()
        assert json.loads(b[0]) == {"full": "ORG"} and b[1] is None
        docs = {r[0]: (json.loads(r[1]).get("logo_source"), r[2] is not None) for r in
                c.exec_driver_sql("SELECT id, config_json, logo_png FROM check_document ORDER BY id").all()}
        assert docs == {1: ("ORG", False), 2: ("OWN", True), 3: ("NONE", False), 4: (None, False)}
        tpl = json.loads(c.exec_driver_sql("SELECT template_json FROM invoice_settings").scalar())
        assert tpl == {"title": "Bill", "logo_source": "OWN"}
