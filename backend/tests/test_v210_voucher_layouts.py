"""2.1.0 (#246): voucher checks with the check on top, in the middle or at the bottom, and with one tall invoice stub.
Starting presets from the published layouts (fine-tuned per style); stubs above the check print like stubs below it."""
from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

from fmpoc.services.checkprint import config, presets, render
from tests.test_v200_checks import _texts, enable, make_signer
from tests.test_v210_fold_marks import segments

NEW = {  # preset: (check top, [(stub top, height, copy)])
    "VOUCHER_MIDDLE": (3.5, [(0.0, 3.5, "OFFICE"), (7.0, 4.0, "VENDOR")]),
    "VOUCHER_BOTTOM": (7.5, [(0.0, 3.5, "OFFICE"), (3.5, 4.0, "VENDOR")]),
    "VOUCHER_TOP_INVOICE": (0.0, [(3.5, 7.5, "VENDOR")]),
    "VOUCHER_TOP_INVOICE_7": (0.0, [(3.5, 7.0, "VENDOR")]),
    "VOUCHER_BOTTOM_INVOICE": (7.5, [(0.0, 7.5, "VENDOR")]),
}


def test_presets_match_the_published_layouts():
    for key, (top, stubs) in NEW.items():
        cfg = config.parse(presets.config_for(key))
        assert cfg.stock.check_tops == [top], key
        assert [(s.top, s.height, s.copy_kind) for s in cfg.stubs] == stubs, key
        assert [m.key for m in cfg.feed_modes] == ["voucher"] and cfg.stock.check_height == 3.5
    # the 2.0.0 preset is unchanged
    old = config.parse(presets.config_for("VOUCHER_TOP"))
    assert old.stock.check_tops == [0.0] and [(s.top, s.height, s.copy_kind) for s in old.stubs] == \
        [(3.5, 3.5, "VENDOR"), (7.0, 4.0, "OFFICE")]
    names = {o["key"]: o["name"] for o in presets.options()}
    assert names["VOUCHER_TOP_INVOICE_7"] == "Voucher - check on top, 7-inch invoice stub"


def test_tall_invoice_stub_holds_more_lines():
    short = config.parse(presets.config_for("VOUCHER_TOP")).stubs[0]
    tall = config.parse(presets.config_for("VOUCHER_TOP_INVOICE")).stubs[0]
    seven = config.parse(presets.config_for("VOUCHER_TOP_INVOICE_7")).stubs[0]
    assert render.stub_capacity(tall) > render.stub_capacity(seven) > render.stub_capacity(short)


def test_validation_with_the_check_anywhere():
    base = presets.config_for("VOUCHER_MIDDLE")
    moved = {**base, "stock": {**base["stock"], "check_tops": [2.0]}}           # onto the top stub
    with pytest.raises(ValueError, match="overlaps the check"):
        config.parse(moved)
    off = {**base, "stock": {**base["stock"], "check_tops": [8.0]}}             # runs past the sheet
    with pytest.raises(ValueError, match="past the bottom"):
        config.parse(off)
    fine = presets.config_for("VOUCHER_MIDDLE")
    fine["stock"]["check_tops"] = [3.55]                                          # fine-tuned a little lower
    fine["stubs"][1]["top"], fine["stubs"][1]["height"] = 7.05, 3.95
    assert config.parse(fine).stock.check_tops == [3.55]


@pytest.fixture
def lines_txn(env, base):
    enable(env)
    payee = env.entity("Sample Supply Company, Inc")
    lines = [{"budget_id": base["exp_leaf"], "amount": "100.00", "invoice_number": "INV-1", "description": "Paper"},
             {"budget_id": base["exp_leaf"], "amount": "23.45", "invoice_number": "INV-2", "description": "Toner"}]
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", lines, entity_id=payee["id"], check_number="5001")
    return {"t": t, "acct": base["acct"]["id"], "signer": make_signer(env), "base": base}


@pytest.mark.parametrize("preset", list(NEW))
def test_print_places_check_and_stubs(env, lines_txn, preset):
    top, stubs = NEW[preset]
    style = env.admin.post("/api/checks/styles", {"preset_key": preset}).json()
    assert style["config"]["stock"]["check_tops"] == [top]
    assert env.ru.put(f"/api/checks/accounts/{lines_txn['acct']}", {"check_style_id": style["id"]}).status_code == 200
    tid = lines_txn["t"]["id"]
    r = env.ru.post(f"/api/checks/transactions/{tid}/print",
                    {"check_style_id": style["id"], "feed_key": "voucher", "signer_id": lines_txn["signer"]["id"],
                     "confirm_check_number": "5001"})
    assert r.status_code == 200, r.text
    pos = _texts(r.content)
    # the check face: the payee prints inside the check, and the check number never does
    on_check = [(s, y) for s, _x, y in pos if top <= y <= top + 3.5]
    assert any("SAMPLE SUPPLY COMPANY" in s.upper() for s, _y in on_check)
    assert not any("5001" in s for s, _y in on_check)
    # each stub in its section, with the right copy
    for st_top, h, kind in stubs:
        inside = [s for s, _x, y in pos if st_top <= y <= st_top + h]
        joined = " ".join(inside)
        assert "CHECK #5001" in joined and "INV-1" in joined, (preset, st_top)
        assert ("OFFICE COPY" in joined) == (kind == "OFFICE")
        assert (any(s == "Budget" for s in inside)) == (kind == "OFFICE")      # invoice stub: no budget column
    assert ("OFFICE COPY" in " ".join(s for s, _x, _y in pos)) == any(k == "OFFICE" for _t, _h, k in stubs)
    # the record copy is the whole sheet in the same positions
    atts = env.auditor.get(f"/api/attachments?owner_type=transaction&owner_id={tid}").json()
    copy = env.auditor.get(f"/api/attachments/{atts[0]['id']}/content").content
    cpos = _texts(copy)
    for st_top, h, _kind in stubs:
        assert "CHECK #5001" in " ".join(s for s, _x, y in cpos if st_top <= y <= st_top + h)
    assert any("COPY - NOT NEGOTIABLE" in s and top <= y <= top + 3.5 for s, _x, y in cpos)


def test_calibration_marks_the_perforations_around_a_middle_check(env, base):
    enable(env)
    style = env.admin.post("/api/checks/styles", {"preset_key": "VOUCHER_MIDDLE"}).json()
    pdf = env.admin.post(f"/api/checks/styles/{style['id']}/calibration", {"feed_key": "voucher"}).content
    r = PdfReader(io.BytesIO(pdf))
    full = {round(11 - y1 / 72, 2) for x1, y1, x2, y2 in segments(r, 0) if y1 == y2 and x1 <= 1 and x2 >= 611}
    assert {3.5, 7.0} <= full
    t = " ".join(s for s, _x, _y in _texts(pdf))
    assert "CALIBRATION PAGE" in t and "OFFICE COPY" in t


def test_setup_offers_the_layouts_to_administrators_only(env, base):
    enable(env)
    s = env.admin.get("/api/checks/setup").json()
    assert set(s["voucher_layouts"]) == {"TOP_TWO", "MIDDLE_TWO", "BOTTOM_TWO", "TOP_INVOICE", "TOP_INVOICE_7",
                                         "BOTTOM_INVOICE"}
    assert s["voucher_layouts"]["BOTTOM_INVOICE"]["check_top"] == 7.5
    assert {p["key"] for p in s["presets"]} >= set(NEW)
    for c in (env.bm, env.bu, env.ru, env.auditor):
        assert c.post("/api/checks/styles", {"preset_key": "VOUCHER_MIDDLE"}).status_code == 403
