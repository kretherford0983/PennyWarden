"""2.0.0 build 11 (#217): several cover letters and envelopes (free names, Duplicate, a window-envelope preset) and
Payments Setup previews drawn as pictures (Safari shows inline PDFs blank)."""
import io

import pytest
from PIL import Image

from fmpoc.services.checkprint import raster
from tests.test_v200_checks import PRESET, enable, sig_png
from tests.test_v200_letters import vendor

DOCS = "/api/checks/documents"


def new(env, kind, **kw):
    r = env.admin.post(DOCS, {"kind": kind, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def upload_logo(env, doc_id):
    r = env.admin.c.post(f"{DOCS}/{doc_id}/logo", files={"file": ("logo.png", sig_png(300, 120), "image/png")},
                         headers={"X-CSRF-Token": env.admin.csrf})
    assert r.status_code == 200, r.text
    return r.json()


def test_new_templates_get_free_names_and_deactivated_ones_count(env):
    enable(env)
    names = [new(env, "LETTER")["name"] for _ in range(2)]
    assert names == ["Invoice payment letter", "Invoice payment letter 2"]
    first = env.admin.get("/api/checks/setup").json()["documents"][0]
    # deactivated templates keep their names (never deleted, BR-001), so the next one skips them
    assert env.admin.post(f"{DOCS}/{first['id']}/flags", {"active": False}).status_code == 200
    assert new(env, "LETTER")["name"] == "Invoice payment letter 3"
    assert [new(env, "ENVELOPE")["name"] for _ in range(2)] == ["#10 envelope", "#10 envelope 2"]
    # the first of each kind is the default; a new one becomes the default only when no active one is
    # (the default letter was deactivated above, so letter 3 took over)
    docs = env.admin.get("/api/checks/setup").json()["documents"]
    assert sorted(d["name"] for d in docs if d["is_default"]) == ["#10 envelope", "Invoice payment letter 3"]
    # a name the user types must still be unique (per kind, case-insensitive)
    r = env.admin.post(DOCS, {"kind": "LETTER", "name": "invoice PAYMENT letter"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_NAME"
    assert new(env, "ENVELOPE", name="Invoice payment letter")["name"] == "Invoice payment letter"
    # renaming onto another template's name is refused too
    two = next(d for d in docs if d["name"] == "Invoice payment letter 2")
    r = env.admin.put(f"{DOCS}/{two['id']}", {"name": "Invoice Payment Letter 3", "config": two["config"]})
    assert r.status_code == 409


def test_window_envelope_preset(env):
    enable(env)
    w = new(env, "LETTER", preset="WINDOW")
    assert w["name"] == "Window envelope letter" and w["config"]["window"] == "LETTER"
    assert new(env, "LETTER", preset="WINDOW")["name"] == "Window envelope letter 2"
    assert env.admin.post(DOCS, {"kind": "ENVELOPE", "preset": "WINDOW"}).status_code == 422
    assert env.admin.post(DOCS, {"kind": "LETTER", "preset": "NOPE"}).status_code == 422


def test_duplicate_copies_settings_and_logo_and_is_audited(env):
    enable(env)
    letter = new(env, "LETTER")
    cfg = {**letter["config"], "subject": "Refund {PAYEE}", "window": "ADDRESS_PAGE", "font": "SERIF"}
    letter = env.admin.put(f"{DOCS}/{letter['id']}", {"name": "Refund letter", "config": cfg}).json()
    letter = upload_logo(env, letter["id"])
    r = env.admin.post(f"{DOCS}/{letter['id']}/duplicate", {})
    assert r.status_code == 201, r.text
    copy = r.json()
    assert copy["id"] != letter["id"] and copy["name"] == "Refund letter copy"
    assert copy["config"] == letter["config"] and copy["logo"] == letter["logo"]
    assert copy["active"] and not copy["is_default"]
    assert env.admin.get(f"{DOCS}/{copy['id']}/logo").content == env.admin.get(f"{DOCS}/{letter['id']}/logo").content
    assert env.admin.post(f"{DOCS}/{letter['id']}/duplicate", {}).json()["name"] == "Refund letter copy 2"
    # the copy is independent of the original
    env.admin.put(f"{DOCS}/{copy['id']}", {"name": "Donation letter", "config": {**copy["config"], "subject": "Gift"}})
    setup = {d["id"]: d for d in env.admin.get("/api/checks/setup").json()["documents"]}
    assert setup[letter["id"]]["config"]["subject"] == "Refund {PAYEE}"
    # a deactivated template can be duplicated; the copy is active
    env.admin.post(f"{DOCS}/{letter['id']}/flags", {"active": False})
    assert env.admin.post(f"{DOCS}/{letter['id']}/duplicate", {}).json()["active"] is True
    envelope = new(env, "ENVELOPE")
    assert env.admin.post(f"{DOCS}/{envelope['id']}/duplicate", {}).json()["name"] == "#10 envelope copy"
    ev = [e for e in env.admin.get("/api/audit-events?action=CHECK_DOCUMENT_CREATED").json()["items"]
          if e["object_id"] == str(copy["id"])]
    assert len(ev) == 1 and ev[0]["after"]["duplicated_from"] == letter["id"] and ev[0]["after"]["logo_sha256"]
    for c in (env.ru, env.bm, env.auditor):
        assert c.post(f"{DOCS}/{letter['id']}/duplicate", {}).status_code == 403


def test_template_limit_applies_to_duplicates(env, monkeypatch):
    from fmpoc.services.checkprint import service
    enable(env)
    monkeypatch.setattr(service, "MAX_DOCUMENTS", 2)
    a = new(env, "LETTER")
    new(env, "ENVELOPE")
    assert env.admin.post(f"{DOCS}/{a['id']}/duplicate", {}).json()["error"]["code"] == "TOO_MANY"
    assert env.admin.post(DOCS, {"kind": "LETTER"}).json()["error"]["code"] == "TOO_MANY"


def test_free_name_stays_within_80_characters(env):
    enable(env)
    long = "L" * 80
    first = new(env, "LETTER", name=long)
    copy = env.admin.post(f"{DOCS}/{first['id']}/duplicate", {}).json()
    assert len(copy["name"]) <= 80 and copy["name"].endswith(" copy")
    again = env.admin.post(f"{DOCS}/{first['id']}/duplicate", {}).json()
    assert len(again["name"]) <= 80 and again["name"].endswith(" copy 2")


@pytest.mark.skipif(not raster.available(), reason="PDFium is not installed")
def test_preview_image_is_a_picture_of_the_print(env):
    enable(env)
    letter = new(env, "LETTER")
    envelope = new(env, "ENVELOPE")
    r = env.admin.post(f"{DOCS}/{letter['id']}/preview-image", {"config": letter["config"]})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "no-store" and r.headers["x-page-count"] == "1"
    im = Image.open(io.BytesIO(r.content))
    assert im.height == raster.MAX_SIDE_PX and abs(im.width / im.height - 8.5 / 11) < 0.01
    # the page is drawn (mostly white paper with dark text), not blank
    gray = im.convert("L")
    assert gray.getextrema()[0] < 80 and gray.resize((1, 1)).getpixel((0, 0)) > 200
    # an address page in front of the letter: two pages stacked
    r = env.admin.post(f"{DOCS}/{letter['id']}/preview-image", {"config": {**letter["config"], "window": "ADDRESS_PAGE"}})
    assert r.headers["x-page-count"] == "2"
    assert Image.open(io.BytesIO(r.content)).height == 2 * raster.MAX_SIDE_PX + raster.GAP_PX
    # the envelope on its own envelope-sized page
    im = Image.open(io.BytesIO(env.admin.post(f"{DOCS}/{envelope['id']}/preview-image", {}).content))
    assert im.width == raster.MAX_SIDE_PX and abs(im.width / im.height - 9.5 / 4.125) < 0.01
    # unsaved settings are validated, nothing is audited, and only Administrators may preview
    bad = env.admin.post(f"{DOCS}/{letter['id']}/preview-image", {"config": {**letter["config"], "subject": "{NOPE}"}})
    assert bad.status_code == 422
    assert not env.admin.get("/api/audit-events?action=CHECK_DOCUMENT_TEST_PRINT").json()["items"]
    for c in (env.ru, env.bm, env.bu, env.auditor):
        assert c.post(f"{DOCS}/{letter['id']}/preview-image", {}).status_code == 403


def test_preview_image_unavailable_falls_back(env, monkeypatch):
    enable(env)
    letter = new(env, "LETTER")
    monkeypatch.setattr(raster, "available", lambda: False)
    r = env.admin.post(f"{DOCS}/{letter['id']}/preview-image", {})
    assert r.status_code == 501 and r.json()["error"]["code"] == "PREVIEW_UNAVAILABLE"
    # the PDF preview (the fallback) still works
    assert env.admin.post(f"{DOCS}/{letter['id']}/preview", {}).status_code == 200


def test_print_screen_offers_active_letters_only(env, base):
    enable(env)
    style = env.admin.post("/api/checks/styles", {"preset_key": PRESET}).json()
    a, b, w = new(env, "LETTER"), new(env, "LETTER"), new(env, "LETTER", preset="WINDOW")
    env.admin.post(f"{DOCS}/{b['id']}/flags", {"active": False})
    v = vendor(env)
    acct = base["acct"]["id"]
    t = env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "10.00", "invoice_number": "A1"}],
                entity_id=v["id"])
    env.ru.put(f"/api/checks/accounts/{acct}", {"check_style_id": style["id"]})
    docs = env.ru.get(f"/api/checks/transactions/{t['id']}/documents").json()
    assert sorted(d["id"] for d in docs["letters"]) == sorted([a["id"], w["id"]])
    r = env.ru.post(f"/api/checks/transactions/{t['id']}/letter", {"document_id": b["id"],
                                                                     "confirmations": ["EMPTY_VARIABLES"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "TEMPLATE_INACTIVE"
    r = env.ru.post(f"/api/checks/transactions/{t['id']}/letter", {"document_id": w["id"],
                                                                     "confirmations": ["EMPTY_VARIABLES"]})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
