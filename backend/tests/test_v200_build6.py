"""2.0.0 build 6: cover letter logo and pre-printed letterhead (#176), #10 double-window envelopes (#177)."""
from __future__ import annotations

import io

import pytest
from PIL import Image
from pypdf import PdfReader

from fmpoc.services.checkprint import documents
from test_v200_checks import _texts, enable, has_image


def img(fmt="PNG", size=(600, 240)) -> bytes:
    im = Image.new("RGB", size, (30, 80, 160))
    b = io.BytesIO()
    im.save(b, fmt)
    return b.getvalue()


def upload(client, doc_id, data, name="logo.png", mime="image/png"):
    return client.c.post(f"/api/checks/documents/{doc_id}/logo", files={"file": (name, data, mime)},
                         headers={"X-CSRF-Token": client.csrf})


@pytest.fixture
def letter(env):
    enable(env)
    d = env.admin.post("/api/checks/documents", {"kind": "LETTER"}).json()
    cfg = d["config"]
    cfg["letterhead"] = ["{ORG}", "789 Sample Street", "Sample Town, US 12345"]
    return env.admin.put(f"/api/checks/documents/{d['id']}", {"name": d["name"], "config": cfg}).json()


def _pdf_texts(pdf: bytes, page: int = 0):
    from pypdf import PdfWriter
    r = PdfReader(io.BytesIO(pdf))
    w = PdfWriter()
    w.add_page(r.pages[page])
    b = io.BytesIO()
    w.write(b)
    return _texts(b.getvalue())


# ------------------------------------------------------------------ #176 logo
def test_logo_upload_validation_and_audit(env, letter):
    did = letter["id"]
    assert letter["logo"] is None
    r = upload(env.admin, did, img("JPEG"), "logo.jpg", "image/jpeg")
    assert r.status_code == 200, r.text
    logo = r.json()["logo"]
    assert logo["width"] == 600 and logo["height"] == 240 and logo["version"]
    got = env.admin.get(f"/api/checks/documents/{did}/logo")
    assert got.status_code == 200 and got.content.startswith(b"\x89PNG")       # re-encoded as PNG
    # a large image is scaled down
    big = upload(env.admin, did, img(size=(3000, 3000))).json()["logo"]
    assert big["width"] <= 1500 and big["height"] <= 600
    # content, not the name or browser type, decides; too large; not an image
    assert upload(env.admin, did, b"GIF89a" + b"0" * 100, "x.png").status_code == 415
    assert upload(env.admin, did, b"\x89PNG\r\n\x1a\n" + b"junk" * 50).status_code == 415
    assert upload(env.admin, did, b"\x89PNG\r\n\x1a\n" + b"0" * (1024 * 1024 + 10)).status_code == 413
    assert upload(env.admin, did, img(size=(8, 8))).status_code == 422
    # other roles, envelopes
    for c in (env.ru, env.bm, env.bu, env.auditor):
        assert upload(c, did, img()).status_code == 403
        assert c.get(f"/api/checks/documents/{did}/logo").status_code == 403
    envelope = env.admin.post("/api/checks/documents", {"kind": "ENVELOPE"}).json()
    assert upload(env.admin, envelope["id"], img()).status_code == 404
    # audit: the fingerprint, never the image
    ev = env.admin.get("/api/audit-events?action=CHECK_DOCUMENT_LOGO_SET").json()["items"]
    assert len(ev) == 2 and "logo_png" not in str(ev)
    r = env.admin.post(f"/api/checks/documents/{did}/logo/remove", {})
    assert r.status_code == 200 and r.json()["logo"] is None
    assert env.admin.get(f"/api/checks/documents/{did}/logo").status_code == 404
    assert env.admin.get("/api/audit-events?action=CHECK_DOCUMENT_LOGO_REMOVED").json()["items"]


def test_logo_prints_left_or_centred(env, letter):
    did = letter["id"]
    upload(env.admin, did, img())
    pdf = env.admin.post(f"/api/checks/documents/{did}/test-print", {}).content
    assert has_image(pdf)
    t = {txt: (x, y) for txt, x, y in _texts(pdf)}
    assert t["Sample Organization"][0] < 1.2                                     # left: lines at the margin
    cfg = {**letter["config"], "logo_position": "CENTER"}
    pdf = env.admin.post(f"/api/checks/documents/{did}/preview", {"config": cfg}).content
    t = {txt: (x, y) for txt, x, y in _texts(pdf)}
    assert t["Sample Organization"][0] > 3.0                                     # centred with the logo
    # the logo is above the letterhead lines
    assert t["Sample Organization"][1] > 1.0 + 0.9


def test_preprinted_letterhead_keeps_the_space(env, letter):
    did = letter["id"]
    upload(env.admin, did, img())
    cfg = {**letter["config"], "preprinted": True, "preprinted_margin": 2.5}
    pdf = env.admin.post(f"/api/checks/documents/{did}/preview", {"config": cfg}).content
    texts = _texts(pdf)
    assert not has_image(pdf)
    assert not any(t in ("Sample Organization", "789 Sample Street") for t, *_ in texts)
    top = min(y for _t, _x, y in texts)
    assert 2.5 < top < 2.8                                                       # the date is the first line
    bad = env.admin.post(f"/api/checks/documents/{did}/preview",
                         {"config": {**cfg, "preprinted_margin": 0.25}})
    assert bad.status_code == 422


# ------------------------------------------------------------------ #177 double-window
def test_window_on_the_letter(env, letter):
    did = letter["id"]
    cfg = {**letter["config"], "window": "LETTER"}
    pdf = env.admin.post(f"/api/checks/documents/{did}/preview", {"config": cfg}).content
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 1
    t = {txt: (x, y) for txt, x, y in _texts(pdf)}
    ret, pay = documents.WINDOW_PRESET["return"], documents.WINDOW_PRESET["payee"]
    assert t["Sample Organization"][0] == pytest.approx(ret["x"], abs=0.01)
    assert t["SAMPLE VENDOR COMPANY"][0] == pytest.approx(pay["x"], abs=0.01)
    # each address inside its window
    for key, name in (("return", "Sample Organization"), ("payee", "SAMPLE VENDOR COMPANY")):
        left, top, w, h = documents.WINDOW_PRESET[key]["window"]
        x, y = t[name]
        assert left < x < left + w and top < y < top + h, key
    # the letter body starts below the first fold; no "To:" block
    assert t["Subject:"][1] > documents.FOLD_LINES[0]
    assert "To:" not in t
    # the test print shows the windows; offsets move the addresses; no return address when switched off
    assert "WINDOW ALIGNMENT - dashed boxes: #10 double-window envelope" in t
    moved = {**cfg, "payee_dx": 0.25, "payee_dy": -0.125, "window_return": False}
    t2 = {txt: (x, y) for txt, x, y in _texts(env.admin.post(f"/api/checks/documents/{did}/preview",
                                                              {"config": moved}).content)}
    assert t2["SAMPLE VENDOR COMPANY"][0] == pytest.approx(pay["x"] + 0.25, abs=0.01)
    assert t2["SAMPLE VENDOR COMPANY"][1] == pytest.approx(t["SAMPLE VENDOR COMPANY"][1] - 0.125, abs=0.01)
    assert "Sample Organization" not in t2
    assert env.admin.post(f"/api/checks/documents/{did}/preview",
                          {"config": {**cfg, "payee_dx": 2}}).status_code == 422


def test_window_on_a_separate_address_page(env, letter):
    did = letter["id"]
    cfg = {**letter["config"], "window": "ADDRESS_PAGE"}
    pdf = env.admin.post(f"/api/checks/documents/{did}/preview", {"config": cfg}).content
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 2
    first = {t for t, *_ in _pdf_texts(pdf, 0)}
    assert {"Sample Organization", "SAMPLE VENDOR COMPANY"} <= first and "Subject:" not in first
    second = {t for t, *_ in _pdf_texts(pdf, 1)}
    assert "Subject:" in second and "To:" in second


def test_real_letter_has_no_window_marks(env, base, letter):
    """A letter printed for a transaction carries the addresses but never the alignment marks."""
    from test_v200_letters import vendor
    from test_v200_checks import PRESET
    cfg = {**letter["config"], "window": "LETTER"}
    env.admin.put(f"/api/checks/documents/{letter['id']}", {"name": letter["name"], "config": cfg})
    style = env.admin.post("/api/checks/styles", {"preset_key": PRESET}).json()
    env.ru.put(f"/api/checks/accounts/{base['acct']['id']}", {"check_style_id": style["id"]})
    v = vendor(env)
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "12.00",
                                                    "invoice_number": "A1"}], entity_id=v["id"])
    r = env.ru.post(f"/api/checks/transactions/{t['id']}/handwritten",
                    {"check_number": "5001", "confirm_check_number": "5001"})
    assert r.status_code == 200, r.text
    r = env.ru.post(f"/api/checks/transactions/{t['id']}/letter", {"document_id": letter["id"]})
    assert r.status_code == 200, r.text
    texts = {x for x, *_ in _texts(r.content)}
    assert "Sample Vendor Company" in texts and "Acme Org" in texts
    assert not any("WINDOW ALIGNMENT" in x for x in texts)
