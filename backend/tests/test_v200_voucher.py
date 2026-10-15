"""2.0.0 build 4 (#167): voucher (stub) checks and dual signature lines. Synthetic data only."""
import io
import re

import pytest
from pypdf import PdfReader

from fmpoc.services.checkprint import config, presets, render
from tests.test_v200_checks import _texts, enable, has_image, make_signer


def text(pdf: bytes) -> str:
    return " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


def image_draws(pdf: bytes) -> int:
    """How many times an image XObject is drawn (one per printed signature)."""
    n = 0
    for page in PdfReader(io.BytesIO(pdf)).pages:
        xo = (page.get("/Resources") or {}).get("/XObject") or {}
        names = {k for k, o in xo.items() if o.get_object().get("/Subtype") == "/Image"}
        data = page.get_contents().get_data().decode("latin-1")
        n += sum(len(re.findall(re.escape(k) + r"\s+Do", data)) for k in names)
    return n


def voucher_style(env, **changes):
    s = env.admin.post("/api/checks/styles", {"preset_key": "VOUCHER_TOP"}).json()
    if changes:
        cfg = s["config"]
        for k, v in changes.items():
            cfg[k] = v
        r = env.admin.put(f"/api/checks/styles/{s['id']}", {"name": s["name"], "config": cfg})
        assert r.status_code == 200, r.text
        s = r.json()
    return s


def dual_config(cfg: dict, **kw) -> dict:
    cfg = {**cfg, "stock": {**cfg["stock"], "signature_lines": 2},
           "fields": {**cfg["fields"], "signature": {"x": 5.605, "y": 2.4, "w": 2.25, "h": 0.42},
                      "signature2": dict(presets.SIGNATURE2_DEFAULT)}}
    cfg.update(kw)
    return cfg


@pytest.fixture
def vsetup(env, base):
    enable(env)
    style = voucher_style(env)
    payee = env.entity("Sample Supply Company, Inc")
    lines = [{"budget_id": base["exp_leaf"], "amount": "100.00", "invoice_number": "INV-1", "description": "Paper",
              "invoice_date": "2026-09-01"},
             {"budget_id": base["exp_leaf"], "amount": "23.45", "invoice_number": "INV-2", "description": "Toner"}]
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", lines, entity_id=payee["id"], check_number="5001")
    assert env.ru.put(f"/api/checks/accounts/{base['acct']['id']}", {"check_style_id": style["id"]}).status_code == 200
    return {"style": style, "txn": t, "payee": payee, **base}


def vjob(s, **kw):
    return {"check_style_id": s["style"]["id"], "feed_key": "voucher", **kw}


# ------------------------------------------------------------------ the preset and validation
def test_voucher_preset_and_validation():
    cfg = config.parse(presets.config_for("VOUCHER_TOP"))
    assert cfg.stock.check_tops == [0.0] and [(s.top, s.height, s.copy_kind) for s in cfg.stubs] == \
        [(3.5, 3.5, "VENDOR"), (7.0, 4.0, "OFFICE")]
    assert [c.key for c in cfg.stub_columns] == ["INVOICE", "INVOICE_DATE", "DESCRIPTION", "AMOUNT"]
    base = presets.config_for("VOUCHER_TOP")
    bad = [
        ({**base, "stubs": [{"top": 3.0, "height": 3.0}]}, "overlaps the check"),
        ({**base, "stubs": [{"top": 3.5, "height": 3.5}, {"top": 6.0, "height": 3.0}]}, "overlaps stub 1"),
        ({**base, "stubs": [{"top": 8.0, "height": 3.5}]}, "past the bottom"),
        ({**base, "stubs": [{"top": 3.5, "height": 3.5, "title": "{dtae}"}]}, "not a variable"),
        ({**base, "feed_modes": base["feed_modes"] + [{"key": "one", "label": "One", "kind": "SINGLE"}]},
         "single-check feed modes"),
        ({**base, "stock": {**base["stock"], "check_tops": [0.0, 3.5]}}, "one check per sheet"),
        ({**base, "stub_columns": [{"key": "AMOUNT", "heading": "A"}, {"key": "AMOUNT", "heading": "B"}]},
         "used once"),
    ]
    for data, msg in bad:
        with pytest.raises(ValueError, match=msg):
            config.parse(data)


def test_dual_signature_validation():
    base = presets.config_for("STANDARD_3UP")
    config.parse(dual_config(base))
    with pytest.raises(ValueError, match="place the second signature"):
        config.parse({**base, "stock": {**base["stock"], "signature_lines": 2}})
    with pytest.raises(ValueError, match="overlap"):
        c = dual_config(base)
        c["fields"]["signature2"] = dict(c["fields"]["signature"])
        config.parse(c)
    with pytest.raises(ValueError, match="below the no-signature limit"):
        config.parse(dual_config(base, signature_limit_cents=100000, second_line_limit_cents=100000))
    with pytest.raises(ValueError, match="need two signature lines"):
        config.parse({**base, "second_line_limit_cents": 5000})
    with pytest.raises(ValueError, match="bottom 5/8 inch"):
        c = dual_config(base)
        c["fields"]["signature2"]["y"] = 2.6
        config.parse(c)
    # one line again: the second box is dropped
    c = config.parse({**dual_config(base), "stock": {**base["stock"], "signature_lines": 1}})
    assert c.fields.signature2 is None


# ------------------------------------------------------------------ stubs on the printed check
def test_voucher_print_stubs_check_number_and_spoil(env, vsetup):
    signer = make_signer(env)
    tid = vsetup["txn"]["id"]
    opts = env.ru.get(f"/api/checks/transactions/{tid}/options").json()
    assert opts["checks_per_sheet"] == 1 and opts["suggested_feed"] == "voucher"
    prep = env.ru.post(f"/api/checks/transactions/{tid}/prepare", vjob(vsetup, signer_id=signer["id"])).json()
    assert prep["can_print"] and prep["stub_lines"] == 2 and prep["warnings"] == []
    r = env.ru.post(f"/api/checks/transactions/{tid}/print", vjob(vsetup, signer_id=signer["id"],
                                                                 confirm_check_number="5001"))
    assert r.status_code == 200, r.text
    t = text(r.content)
    assert t.count("CHECK #5001") == 2 and "OFFICE COPY" in t and "INV-1" in t and "INV-2" in t
    assert "Total: $123.45" in t and "09/01/2026" in t and "Pay to: Sample Supply Company, Inc" in t
    # the vendor copy has no budget column; the office copy does (budget code + name)
    pos = _texts(r.content)
    vendor_y = [y for s, _x, y in pos if 3.5 < y < 7.0]
    office = [s for s, _x, y in pos if y > 7.0]
    assert any("Budget" == s for s in office)
    assert not any(s == "Budget" for s, _x, y in pos if 3.5 < y < 7.0) and vendor_y
    # the check face never shows the check number: nothing with 5001 in the top 3.5 inches
    assert not any("5001" in s for s, _x, y in pos if y < 3.5)
    assert has_image(r.content)
    # record copy: the whole sheet, stubs included, no image
    atts = env.auditor.get(f"/api/attachments?owner_type=transaction&owner_id={tid}").json()
    copy = env.auditor.get(f"/api/attachments/{atts[0]['id']}/content").content
    assert not has_image(copy) and "OFFICE COPY" in text(copy) and "COPY - NOT NEGOTIABLE" in text(copy)
    # spoiled: the reprint's stubs show the new number
    r = env.ru.post(f"/api/checks/transactions/{tid}/spoil", {"reason": "jam", "new_check_number": "5002"})
    assert r.status_code == 200
    r = env.ru.post(f"/api/checks/transactions/{tid}/print", vjob(vsetup, signer_id=signer["id"],
                                                                 confirm_check_number="5002"))
    assert r.status_code == 200 and text(r.content).count("CHECK #5002") == 2 and "CHECK #5001" not in text(r.content)


def test_stub_check_number_off_and_alignment_test(env, vsetup):
    cfg = vsetup["style"]["config"]
    cfg["stubs"] = [dict(s, show_check_number=False) for s in cfg["stubs"]]
    assert env.admin.put(f"/api/checks/styles/{vsetup['style']['id']}",
                         {"name": vsetup["style"]["name"], "config": cfg}).status_code == 200
    tid = vsetup["txn"]["id"]
    r = env.ru.post(f"/api/checks/transactions/{tid}/print", vjob(vsetup, no_signature=True,
                                                                 confirm_check_number="5001"))
    assert r.status_code == 200 and "CHECK #" not in text(r.content) and "INV-2" in text(r.content)
    a = env.ru.post(f"/api/checks/transactions/{tid}/alignment-test", vjob(vsetup)).content
    assert "INV-1" in text(a) and "ALIGNMENT TEST" in text(a) and not has_image(a)


def test_stub_overflow_warning(env, vsetup):
    leaf = vsetup["exp_leaf"]
    lines = [{"budget_id": leaf, "amount": "1.00", "invoice_number": f"N-{i:02d}"} for i in range(30)]
    t = env.txn(vsetup["acct"]["id"], "WITHDRAWAL", lines, entity_id=vsetup["payee"]["id"], check_number="5100")
    prep = env.ru.post(f"/api/checks/transactions/{t['id']}/prepare", vjob(vsetup, no_signature=True)).json()
    w = next(w for w in prep["warnings"] if w["code"] == "STUB_OVERFLOW")
    assert "30 lines" in w["message"] and "see enclosed letter" in w["message"]
    body = vjob(vsetup, no_signature=True, confirm_check_number="5100")
    assert env.ru.post(f"/api/checks/transactions/{t['id']}/print", body).json()["error"]["code"] == \
        "CONFIRMATION_REQUIRED"
    r = env.ru.post(f"/api/checks/transactions/{t['id']}/print", {**body, "confirmations": ["STUB_OVERFLOW"]})
    assert r.status_code == 200
    cap = render.stub_capacity(config.parse(vsetup["style"]["config"]).stubs[0])
    assert f"…and {30 - (cap - 1)} more, see enclosed letter" in text(r.content)
    assert "N-00" in text(r.content) and "N-29" not in text(r.content)


def test_admin_test_print_and_calibration_show_sample_stubs(env, vsetup):
    sid = vsetup["style"]["id"]
    t = text(env.admin.post(f"/api/checks/styles/{sid}/test-print", {"feed_key": "voucher"}).content)
    assert "SAMPLE PAYEE COMPANY INC" in t and "158092" in t and "OFFICE COPY" in t and "TEST - NOT A CHECK" in t
    t = text(env.admin.post(f"/api/checks/styles/{sid}/calibration", {"feed_key": "voucher"}).content)
    assert "158092" in t and "CALIBRATION PAGE" in t


# ------------------------------------------------------------------ dual signature lines
@pytest.fixture
def dual(env, vsetup):
    s = vsetup["style"]
    cfg = dual_config(s["config"], signature_limit_cents=500000, second_line_limit_cents=10000)
    r = env.admin.put(f"/api/checks/styles/{s['id']}", {"name": s["name"], "config": cfg})
    assert r.status_code == 200, r.text
    a, b = make_signer(env, "Jordan Sample", "Treasurer"), make_signer(env, "Pat Example", "Chair")
    return {**vsetup, "style": r.json(), "a": a, "b": b}


def test_dual_signatures_two_different_signers(env, dual):
    tid = dual["txn"]["id"]       # $123.45: over the second-line limit ($100.00) -> only the first prints
    assert env.ru.get(f"/api/checks/transactions/{tid}/options").json()["signature_lines"] == 2
    leaf = dual["exp_leaf"]
    small = env.txn(dual["acct"]["id"], "WITHDRAWAL", [{"budget_id": leaf, "amount": "50.00"}],
                    entity_id=dual["payee"]["id"], check_number="5200")
    # the same signer twice is refused
    r = env.ru.post(f"/api/checks/transactions/{small['id']}/prepare",
                    vjob(dual, signer_id=dual["a"]["id"], signer2_id=dual["a"]["id"]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "SAME_SIGNER"
    body = vjob(dual, signer_id=dual["a"]["id"], signer2_id=dual["b"]["id"], confirm_check_number="5200",
                confirmations=["EMPTY_VARIABLES"])
    prep = env.ru.post(f"/api/checks/transactions/{small['id']}/prepare",
                       {k: v for k, v in body.items() if k not in ("confirm_check_number", "confirmations")}).json()
    assert prep["signature"] == "SIGNATURE ON FILE: JORDAN SAMPLE" and prep["signature2"] == \
        "SIGNATURE ON FILE: PAT EXAMPLE"
    r = env.ru.post(f"/api/checks/transactions/{small['id']}/print", body)
    assert r.status_code == 200 and image_draws(r.content) == 2
    atts = env.auditor.get(f"/api/attachments?owner_type=transaction&owner_id={small['id']}").json()
    copy = text(env.auditor.get(f"/api/attachments/{atts[0]['id']}/content").content)
    assert "SIGNATURE ON FILE: JORDAN SAMPLE" in copy and "SIGNATURE ON FILE: PAT EXAMPLE" in copy
    ev = env.auditor.get("/api/audit-events?action=CHECK_PRINTED").json()["items"][0]["after"]
    assert ev["signer_id"] == dual["a"]["id"] and ev["signer2_id"] == dual["b"]["id"]
    # no second signer chosen: the line is left for a hand signature
    t2 = env.txn(dual["acct"]["id"], "WITHDRAWAL", [{"budget_id": leaf, "amount": "60.00"}],
                 entity_id=dual["payee"]["id"], check_number="5201")
    prep = env.ru.post(f"/api/checks/transactions/{t2['id']}/prepare", vjob(dual, signer_id=dual["a"]["id"])).json()
    assert prep["signature2"] == "SECOND SIGNATURE BY HAND" and "signed by hand" in prep["signature_notice"]


def test_second_line_and_no_signature_limits(env, dual):
    tid = dual["txn"]["id"]       # $123.45 is between $100.00 and $5,000.00
    body = vjob(dual, signer_id=dual["a"]["id"], signer2_id=dual["b"]["id"], confirm_check_number="5001")
    prep = env.ru.post(f"/api/checks/transactions/{tid}/prepare",
                       {k: v for k, v in body.items() if k not in ("confirm_check_number", "confirmations")}).json()
    assert prep["signature"] == "SIGNATURE ON FILE: JORDAN SAMPLE"
    assert prep["signature2"] == "SECOND SIGNATURE BY HAND (OVER LIMIT)" and "$100.00" in prep["signature_notice"]
    r = env.ru.post(f"/api/checks/transactions/{tid}/print", body)
    assert r.status_code == 200 and image_draws(r.content) == 1
    big = env.txn(dual["acct"]["id"], "WITHDRAWAL", [{"budget_id": dual["exp_leaf"], "amount": "6000.00"}],
                  entity_id=dual["payee"]["id"], check_number="5300")
    body = vjob(dual, signer_id=dual["a"]["id"], signer2_id=dual["b"]["id"], confirm_check_number="5300",
                confirmations=["EMPTY_VARIABLES"])
    prep = env.ru.post(f"/api/checks/transactions/{big['id']}/prepare",
                       {k: v for k, v in body.items() if k not in ("confirm_check_number", "confirmations")}).json()
    assert prep["signature"] == prep["signature2"] == "NO SIGNATURE PRINTED (OVER LIMIT)"
    r = env.ru.post(f"/api/checks/transactions/{big['id']}/print", body)
    assert r.status_code == 200 and image_draws(r.content) == 0


def test_dual_default_signers_validated(env, dual):
    s = dual["style"]
    cfg = dict(s["config"], default_signer_id=dual["a"]["id"], default_signer2_id=dual["a"]["id"])
    r = env.admin.put(f"/api/checks/styles/{s['id']}", {"name": s["name"], "config": cfg})
    assert r.status_code == 422 and "different" in r.json()["error"]["message"]
    cfg["default_signer2_id"] = dual["b"]["id"]
    assert env.admin.put(f"/api/checks/styles/{s['id']}", {"name": s["name"], "config": cfg}).status_code == 200
    opts = env.ru.get(f"/api/checks/transactions/{dual['txn']['id']}/options").json()
    assert opts["default_signer2_id"] == dual["b"]["id"] and opts["second_line_limit"] == "100.00"
