"""2.0.0 build 1 (#156-#162): Payments module - switch and access, check styles, amounts, patterns, PDF
positions, signers, printing, reprint, spoiled checks, record copies and personal printer settings."""
from __future__ import annotations

import io

import pytest
from PIL import Image
from pypdf import PdfReader

from fmpoc.services.checkprint import amounts, config, patterns, presets, render
from fmpoc.services.checkprint.service import SAMPLES

PRESET = "STANDARD_3UP"


def has_image(pdf: bytes) -> bool:
    """True when any page draws an image XObject (the signature)."""
    for page in PdfReader(io.BytesIO(pdf)).pages:
        xo = (page.get("/Resources") or {}).get("/XObject") or {}
        if any(o.get_object().get("/Subtype") == "/Image" for o in xo.values()):
            return True
    return False


def enable(env, on=True):
    r = env.admin.put("/api/system/modules", {"checks": on})
    assert r.status_code == 200, r.text
    return r.json()


def sig_png(w=400, h=120) -> bytes:
    im = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    for x in range(20, w - 20):
        im.putpixel((x, h // 2 + (x % 30) - 15), (0, 0, 0, 255))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def make_style(env) -> dict:
    r = env.admin.post("/api/checks/styles", {"preset_key": PRESET})
    assert r.status_code == 201, r.text
    return r.json()


def make_signer(env, name="Jordan Sample", title="Treasurer") -> dict:
    r = env.admin.c.post("/api/checks/signers", data={"name": name, "title": title},
                         files={"file": ("sig.png", sig_png(), "image/png")}, headers={"X-CSRF-Token": env.admin.csrf})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def setup(env, base):
    enable(env)
    style = make_style(env)
    payee = env.entity("Sample Supply Company, Inc")
    t = env.txn(base["acct"]["id"], "WITHDRAWAL",
                [{"budget_id": base["exp_leaf"], "amount": "3199.30", "invoice_number": "48513",
                  "description": "Event supplies"}], entity_id=payee["id"], check_number="6175")
    r = env.ru.put(f"/api/checks/accounts/{base['acct']['id']}", {"check_style_id": style["id"]})
    assert r.status_code == 200, r.text
    return {"style": style, "txn": t, "payee": payee, **base}


def job(setup, **kw):
    return {"check_style_id": setup["style"]["id"], "feed_key": "sheet_top", **kw}


def do_print(env, setup, **kw):
    body = job(setup, confirm_check_number=kw.pop("confirm", "6175"), **kw)
    return env.ru.post(f"/api/checks/transactions/{setup['txn']['id']}/print", body)


# ------------------------------------------------------------------ module switch and access (#156)
def test_module_off_by_default_and_access(env, base):
    assert env.ru.get("/api/auth/me").json()["modules"] == {"fundraisers": False, "checks": False}
    assert env.admin.get("/api/checks/setup").json()["error"]["code"] == "MODULE_DISABLED"
    assert env.bm.put("/api/system/modules", {"checks": True}).status_code == 403
    assert enable(env) == {"fundraisers": False, "checks": True}
    assert env.ru.get("/api/auth/me").json()["modules"]["checks"] is True
    assert any(e["after"] == {"checks_enabled": True}
               for e in env.admin.get("/api/audit-events?action=MODULE_ENABLED").json()["items"])
    # setup: Administrators only
    assert env.admin.get("/api/checks/setup").status_code == 200
    for c in (env.bm, env.bu, env.ru, env.auditor):
        assert c.get("/api/checks/setup").status_code == 403
        assert c.post("/api/checks/styles", {"preset_key": PRESET}).status_code == 403
    style = make_style(env)
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "10.00"}],
                entity_id=env.entity()["id"])
    # printing: Register Users only - never Budget Managers, Budget Users, Auditors or Administrators
    assert env.ru.get(f"/api/checks/transactions/{t['id']}/options").status_code == 200
    for c in (env.bm, env.bu, env.auditor, env.admin):
        assert c.get(f"/api/checks/transactions/{t['id']}/options").status_code == 403
        assert c.post(f"/api/checks/transactions/{t['id']}/print",
                      {"check_style_id": style["id"], "feed_key": "sheet_top", "confirm_check_number": "1"}
                      ).status_code == 403
        assert c.put(f"/api/checks/accounts/{base['acct']['id']}", {"check_style_id": style["id"]}).status_code == 403
    # off again: everything refused, settings kept
    enable(env, False)
    assert env.ru.get(f"/api/checks/transactions/{t['id']}/options").status_code == 404
    enable(env, True)
    assert [s["name"] for s in env.admin.get("/api/checks/setup").json()["styles"]] == [style["name"]]


def test_local_combined_user_gets_module_through_register_user(env, base):
    from fmpoc.permissions import permissions_for
    perms = permissions_for({"ADMINISTRATOR", "BUDGET_MANAGER", "REGISTER_USER", "AUDITOR"})
    assert {"checks.setup", "checks.print"} <= perms
    assert "checks.print" not in permissions_for({"BUDGET_MANAGER", "BUDGET_ADMIN"})
    assert "checks.print" in permissions_for({"REGISTER_USER", "REGISTER_ADMIN"})


# ------------------------------------------------------------------ check styles (#156)
def test_preset_values_exactly(env, base):
    enable(env)
    s = make_style(env)
    cfg = s["config"]
    assert s["name"] == "3 per page - standard laser (top check first)" and s["checks_per_sheet"] == 3
    assert cfg["stock"]["check_tops"] == [0.0, 3.5, 7.0] and cfg["stock"]["check_height"] == 3.5
    f = cfg["fields"]
    assert (f["payee"]["x"], f["payee"]["y"], f["payee"]["w"], f["payee"]["h"]) == (1.275, 1.206, 5.35, 0.25)
    assert f["amount_words"]["x"] == 0.72 and f["amount_words"]["x"] + f["amount_words"]["w"] == pytest.approx(7.65)
    assert f["amount_number"]["font"] == "MONO" and f["amount_number"]["align"] == "RIGHT"
    assert f["memo"]["font"] == "SERIF" and cfg["defaults"] == {"font": "SANS", "size": 10.0, "upper": True}
    assert (f["signature"]["x"], f["signature"]["y"], f["signature"]["w"], f["signature"]["h"]) == (5.605, 2.15, 2.25, 0.7)
    assert [m["key"] for m in cfg["feed_modes"]] == ["sheet_top", "last_check"]
    last = cfg["feed_modes"][1]
    assert (last["kind"], last["lead"], last["page"], last["guide"]) == ("SINGLE", "DATE_END", "LETTER", "CENTER")
    assert cfg["amount_words"]["and_mode"] == "CENTS" and cfg["amount_words"]["fill_placement"] == "BETWEEN"
    assert cfg["amount_number"] == {"commas": True, "dollar_sign": False, "lead_fill": "**"}


def test_style_validation_copy_deactivate_and_audit(env, base):
    enable(env)
    s = make_style(env)
    url = f"/api/checks/styles/{s['id']}"
    cfg = s["config"]

    def put(c):
        return env.admin.put(url, {"name": s["name"], "config": c})

    import copy
    bad = copy.deepcopy(cfg)
    bad["fields"]["memo"]["h"] = 0.4            # bottom at 2.91" > 3.5 - 0.625
    r = put(bad)
    assert r.status_code == 422 and "bottom 5/8 inch" in r.json()["error"]["message"]
    bad = copy.deepcopy(cfg)
    bad["fields"]["payee"]["w"] = 8.0            # past the right edge
    assert "right edge" in put(bad).json()["error"]["message"]
    bad = copy.deepcopy(cfg)
    bad["fields"]["payee"]["font"] = "Comic Sans"
    assert put(bad).status_code == 422
    bad = copy.deepcopy(cfg)
    bad["fields"]["payee"]["w"] = 0
    assert put(bad).status_code == 422
    bad = copy.deepcopy(cfg)
    bad["feed_modes"][0]["dx"] = 0.75            # offset out of range
    assert put(bad).status_code == 422
    bad = copy.deepcopy(cfg)
    bad["fields"]["memo"]["sneaky"] = 1          # BR-098: unknown settings are refused
    assert put(bad).status_code == 422
    bad = copy.deepcopy(cfg)
    bad["memo_default"] = "{dtae}"
    r = put(bad)
    assert r.json()["error"]["code"] == "PATTERN_INVALID" and r.json()["error"]["suggestion"] == "DATE"
    good = copy.deepcopy(cfg)
    good["fields"]["payee"]["x"] = 1.3
    good["fields"]["payee"]["font"] = "CARLITO"
    r = put(good)
    assert r.status_code == 200 and r.json()["config"]["fields"]["payee"]["x"] == 1.3
    ev = env.admin.get("/api/audit-events?action=CHECK_STYLE_UPDATED").json()["items"][0]
    assert ev["before"]["config"]["fields"]["payee"]["x"] == 1.275
    assert ev["after"]["config"]["fields"]["payee"]["x"] == 1.3
    # copy, unique names, deactivate (never deleted)
    c = env.admin.post(f"{url}/copy", {"name": "Copy"}).json()
    assert c["config"]["fields"]["payee"]["x"] == 1.3
    assert env.admin.post(f"{url}/copy", {"name": "copy"}).status_code == 409
    assert env.admin.post(f"/api/checks/styles/{c['id']}/active", {"active": False}).json()["active"] is False
    assert len(env.admin.get("/api/checks/setup").json()["styles"]) == 2
    assert env.ru.put(f"/api/checks/accounts/{base['acct']['id']}", {"check_style_id": c["id"]}).status_code == 409


# ------------------------------------------------------------------ amounts (#157)
@pytest.mark.parametrize("cents,words", [
    (1, "ZERO AND"), (50, "ZERO AND"), (100, "ONE AND"), (1300, "THIRTEEN AND"), (2100, "TWENTY-ONE AND"),
    (9900, "NINETY-NINE AND"), (10000, "ONE HUNDRED AND"), (10800, "ONE HUNDRED EIGHT AND"),
    (11500, "ONE HUNDRED FIFTEEN AND"), (100000, "ONE THOUSAND AND"), (100100, "ONE THOUSAND ONE AND"),
    (319930, "THREE THOUSAND ONE HUNDRED NINETY-NINE AND"), (1100000, "ELEVEN THOUSAND AND"),
    (10000000, "ONE HUNDRED THOUSAND AND"), (100000000, "ONE MILLION AND"),
    (99999999, "NINE HUNDRED NINETY-NINE THOUSAND NINE HUNDRED NINETY-NINE AND"),
    (99999999999, "NINE HUNDRED NINETY-NINE MILLION NINE HUNDRED NINETY-NINE THOUSAND NINE HUNDRED "
                  "NINETY-NINE AND"),
])
def test_amount_words_bank_convention(cents, words):
    p = amounts.words_parts(cents, {})
    assert p.words == words and p.cents == f"{cents % 100:02d}/100"


def test_amount_styles_and_number():
    assert amounts.words_parts(10850, {"and_mode": "HUNDREDS", "hyphens": False}).words == "ONE HUNDRED AND EIGHT AND"
    assert amounts.words_parts(10800, {"cents": "NO"}).cents == "NO/100"
    assert amounts.words_parts(10800, {"trailing_word": "DOLLARS"}).trailing == "DOLLARS"
    assert amounts.words_parts(9950, {"case": "TITLE"}).words == "Ninety-Nine and"
    assert amounts.number_text(319930, {"lead_fill": "**"}) == "**3,199.30"
    assert amounts.number_text(319930, {"commas": False, "lead_fill": "", "dollar_sign": True}) == "$3199.30"
    for bad in (0, -5, amounts.MAX_CENTS + 1):
        with pytest.raises(ValueError):
            amounts.words_parts(bad, {})


# ------------------------------------------------------------------ patterns (#160)
def test_patterns():
    v = {"BUDGET_CODE": "51", "INVOICE": "48513", "DATE": "10/05/2026"}
    assert patterns.resolve("FBA {BUDGET_CODE}, INVOICE {invoice}", v).text == "FBA 51, INVOICE 48513"
    assert patterns.resolve("{date}|{Date}|{DATE}", v).text == "10/05/2026|10/05/2026|10/05/2026"
    assert patterns.resolve("{{x}} }}", v).text == "{x} }"
    assert patterns.resolve("{{INVOICE}}", v).text == "{INVOICE}"
    r = patterns.resolve("INVOICE {INVOICE} {NOTES}", {"INVOICE": "1"})
    assert r.empty == ["NOTES"]
    with pytest.raises(patterns.PatternError) as e:
        patterns.parse("{dtae}")
    assert e.value.suggestion == "DATE" and "Did you mean {DATE}?" in str(e.value)
    for bad in ("{INVOICE", "x}", "{ }", "{1a}", "{CHECK_NUMBER}", "a\nb", "x" * 201):
        with pytest.raises(patterns.PatternError):
            patterns.parse(bad)
    assert patterns.parse("{CHECK_NUMBER}", patterns.LETTER)[0].var == "CHECK_NUMBER"
    assert patterns.first_and_others(["48513", "48514", None]) == "48513 and others"
    assert patterns.first_and_others([None, ""]) == ""
    assert {o["name"] for o in patterns.variable_options()} >= {"BUDGET", "BUDGET_CODE", "PAYEE"}
    assert "CHECK_NUMBER" not in {o["name"] for o in patterns.variable_options(patterns.CHECK)}


# ------------------------------------------------------------------ PDF drawing (#157)
def _texts(pdf: bytes) -> list[tuple[str, float, float]]:
    """(text, x, y) in inches from the page's top-left corner, for every text run."""
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    h = float(page.mediabox.height)
    out = []

    def visit(text, cm, tm, _fd, _fs):
        if text.strip():
            x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
            y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
            out.append((text.strip(), round(x / 72, 3), round((h - y) / 72, 3)))

    page.extract_text(visitor_text=visit)
    return out


def _cfg():
    return config.parse(presets.config_for(PRESET))


def test_pdf_field_positions_sheet_mode():
    cfg = _cfg()
    lay = render.layout(cfg, render.Content(319930, "10/05/2026", "Sample Supply Company, Inc", "51, INVOICE 48513"))
    assert not lay.problems
    pdf = render.check_pdf(cfg, render.placement_for(cfg, cfg.feed("sheet_top")), lay, None)
    t = {txt: (x, y) for txt, x, y in _texts(pdf)}
    from fmpoc.services.checkprint import fonts
    for name, text in (("payee", "SAMPLE SUPPLY COMPANY, INC"), ("date", "10/05/2026"), ("memo", "51, INVOICE 48513")):
        f = getattr(cfg.fields, name)
        key, size, bold, _u = cfg.field_font(name)
        baseline = f.y + f.h - fonts.descent(key, size) / 72
        assert abs(t[text][0] - f.x) < 0.01 and abs(t[text][1] - baseline) < 0.01, name
    # number right-aligned in its box; cents end at the right edge of the words box
    num = cfg.fields.amount_number
    w = fonts.width("**3,199.30", "MONO", 10) / 72
    assert abs(t["**3,199.30"][0] - (num.x + num.w - w)) < 0.01
    words = cfg.fields.amount_words
    assert abs(t["30/100"][0] + fonts.width("30/100", "SANS", 10) / 72 - (words.x + words.w)) < 0.01
    assert t["THREE THOUSAND ONE HUNDRED NINETY-NINE AND"][0] == pytest.approx(words.x, abs=0.01)
    # nothing in the bank-number clear zone
    assert all(y <= 3.5 - config.CLEAR_ZONE for _t, _x, y in _texts(pdf))


def test_pdf_feed_modes_offsets_and_turning():
    cfg = _cfg()
    lay = render.layout(cfg, render.Content(10850, "09/23/2026", "Pat Example", "BUDGET 51, EVENT SUPPLIES"))
    feed = cfg.feed("last_check")
    # envelope feed, Letter page, guides centered: the check's top edge is at x = (8.5 - 3.5) / 2, date end at top
    pdf = render.check_pdf(cfg, render.placement_for(cfg, feed), lay, None)
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == (612, 792)
    t = {txt: (x, y) for txt, x, y in _texts(pdf)}
    date = cfg.fields.date
    # check (x, y_down) -> page (x_left = 2.5 + y_down', y_top = 8.5 - x)
    assert t["09/23/2026"][1] == pytest.approx(8.5 - date.x, abs=0.01)
    assert 2.5 < t["09/23/2026"][0] < 6.0 and 2.5 < t["PAT EXAMPLE"][0] < 6.0
    assert t["PAT EXAMPLE"][1] > t["09/23/2026"][1]          # payee further from the leading (date) end
    # check-sized page
    pdf = render.check_pdf(cfg, render.placement_for(cfg, feed, {"page": "CHECK"}), lay, None)
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == (252, 612)
    # pay-to end first: the date is now at the bottom
    pdf = render.check_pdf(cfg, render.Placement(feed.model_copy(update={"lead": "PAYTO_END"})), lay, None)
    t2 = {txt: (x, y) for txt, x, y in _texts(pdf)}
    assert t2["09/23/2026"][1] == pytest.approx(date.x, abs=0.01)
    # offsets: dx right / dy down in check coordinates, sheet mode
    base = {x: v for x, *v in _texts(render.check_pdf(cfg, render.placement_for(cfg, cfg.feed("sheet_top")), lay, None))}
    moved = {x: v for x, *v in _texts(render.check_pdf(
        cfg, render.placement_for(cfg, cfg.feed("sheet_top"), {"dx": 0.125, "dy": -0.0625}), lay, None))}
    assert moved["PAT EXAMPLE"][0] - base["PAT EXAMPLE"][0] == pytest.approx(0.125, abs=0.002)
    assert moved["PAT EXAMPLE"][1] - base["PAT EXAMPLE"][1] == pytest.approx(-0.0625, abs=0.002)


def test_fit_rules_and_record_copy_never_has_signature():
    cfg = _cfg()
    long = SAMPLES["LONG"]
    lay = render.layout(cfg, render.Content(long.cents, "10/10/2026", long.payee, long.memo))
    probs = {p.name: p for p in lay.problems}
    assert set(probs) == {"payee", "memo"}
    assert probs["memo"].suggestion.endswith("…") and probs["memo"].editable
    with pytest.raises(render.NotFitting):
        render.check_pdf(cfg, render.placement_for(cfg, cfg.feed("sheet_top")), lay, None)
    # a slightly long payee shrinks instead (down to the minimum size)
    lay = render.layout(cfg, render.Content(100, "10/10/2026", "A" * 60, ""))
    assert lay.fields["payee"].fits and lay.fields["payee"].shrunk and lay.fields["payee"].size >= 8
    # the record copy shows replacement text and never contains an image
    lay = render.layout(cfg, render.Content(319930, "10/05/2026", "Payee", "Memo"))
    copy_pdf = render.record_copy_pdf(cfg, lay, "SIGNATURE ON FILE: JORDAN SAMPLE", ["footer"])
    texts = " ".join(t for t, *_ in _texts(copy_pdf))
    assert "SIGNATURE ON FILE: JORDAN SAMPLE" in texts and "COPY - NOT NEGOTIABLE" in texts
    assert not has_image(copy_pdf)
    signed = render.check_pdf(cfg, render.placement_for(cfg, cfg.feed("sheet_top")), lay, sig_png())
    assert has_image(signed)
    # test, alignment and calibration pages all carry the 5-inch scale check
    pl = render.placement_for(cfg, cfg.feed("sheet_top"))
    for pdf in (render.test_pdf(cfg, pl, lay, None), render.alignment_pdf(cfg, pl, lay), render.calibration_pdf(cfg, pl),
                render.scale_pdf()):
        assert "5.000 in" in " ".join(t for t, *_ in _texts(pdf))
    assert not has_image(render.alignment_pdf(cfg, pl, lay))


def test_centered_fill_height():
    from fmpoc.services.checkprint import fonts
    cfg = _cfg()
    calls = []

    class C:
        def saveState(self): pass
        def restoreState(self): pass
        def circle(self, x, y, r, stroke, fill): calls.append(y)

    render._fill(C(), "DOTS", 0, 100, 50, 10, "SANS", False)
    assert calls and all(abs(y - (50 + fonts.cap_height("SANS", 10) / 2)) < 1e-6 for y in calls)
    assert cfg.amount_words.fill == "DOTS"


# ------------------------------------------------------------------ signers (#159)
def test_signers_upload_protection_and_limit(env, setup):
    s = make_signer(env)
    assert s["has_image"] and s["active"]
    # never downloadable: there is no endpoint for the image, only a low-resolution SAMPLE preview for admins
    r = env.admin.get(f"/api/checks/signers/{s['id']}/preview")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(r.content)).size[0] <= 220
    for c in (env.ru, env.bm, env.auditor):
        assert c.get(f"/api/checks/signers/{s['id']}/preview").status_code == 403
    assert env.admin.get(f"/api/checks/signers/{s['id']}/image").status_code in (404, 405)
    # stored encrypted
    from fmpoc.models import CheckSigner
    with env.app.state.session_factory() as db:
        row = db.get(CheckSigner, s["id"])
        assert row.image_ciphertext and b"PNG" not in row.image_ciphertext.encode()
    # disguised / wrong files refused
    h = {"X-CSRF-Token": env.admin.csrf}
    for name, data in (("x.png", b"%PDF-1.4 not png"), ("x.png", b"\x89PNG\r\n\x1a\nbroken"), ("x.png", b"")):
        r = env.admin.c.post(f"/api/checks/signers/{s['id']}/image", files={"file": (name, data, "image/png")},
                             headers=h)
        assert r.status_code in (413, 415, 422), r.text
    # audit, deactivate
    assert env.admin.get("/api/audit-events?action=CHECK_SIGNER_CREATED").json()["items"]
    assert env.admin.post(f"/api/checks/signers/{s['id']}/active", {"active": False}).json()["active"] is False
    opts = env.ru.get(f"/api/checks/transactions/{setup['txn']['id']}/options").json()
    assert opts["signers"] == []


# ------------------------------------------------------------------ printing (#161)
def test_print_flow_record_copy_reprint_and_spoil(env, setup):
    signer = make_signer(env)
    tid = setup["txn"]["id"]
    opts = env.ru.get(f"/api/checks/transactions/{tid}/options").json()
    assert opts["check_style_id"] == setup["style"]["id"] and opts["sheet_remaining"] == 3
    assert opts["suggested_feed"] == "sheet_top" and opts["memo_default"] == "{BUDGET_CODE}, INVOICE {INVOICE}"
    assert opts["print_status"] is None and opts["next_check_number"] == "6176"
    prep = env.ru.post(f"/api/checks/transactions/{tid}/prepare", job(setup, signer_id=signer["id"])).json()
    assert prep["fields"]["payee"]["text"] == "SAMPLE SUPPLY COMPANY, INC"
    assert prep["fields"]["memo"]["text"] == "1000, INVOICE 48513"
    assert prep["fields"]["amount_words"]["text"] == "THREE THOUSAND ONE HUNDRED NINETY-NINE AND 30/100"
    assert prep["signature"] == "SIGNATURE ON FILE: JORDAN SAMPLE" and prep["can_print"]
    # the amount can never be supplied by the client
    assert env.ru.post(f"/api/checks/transactions/{tid}/prepare", job(setup, amount="1.00")).status_code == 422
    # confirmation of the loaded check number is required and must match
    r = do_print(env, setup, signer_id=signer["id"], confirm="6176")
    assert r.status_code == 409 and r.json()["error"]["code"] == "CHECK_NUMBER_MISMATCH"
    r = do_print(env, setup, signer_id=signer["id"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["cache-control"] == "private, no-store" and has_image(r.content)
    # record copy attached (system generated, no image); counter stepped down; status shown
    atts = env.auditor.get(f"/api/attachments?owner_type=transaction&owner_id={tid}").json()
    assert len(atts) == 1 and atts[0]["original_filename"] == "check-6175-record-copy.pdf"
    content = env.auditor.get(f"/api/attachments/{atts[0]['id']}/content").content
    assert not has_image(content)
    assert env.ru.post(f"/api/attachments/{atts[0]['id']}/remove").status_code in (403, 409)
    opts = env.ru.get(f"/api/checks/transactions/{tid}/options").json()
    assert opts["sheet_remaining"] == 2 and opts["print_status"]["copies"] == 1 and opts["is_reprint"]
    ev = env.auditor.get("/api/audit-events?action=CHECK_PRINTED").json()["items"][0]
    assert ev["after"]["check_number"] == "6175" and ev["after"]["signer_id"] == signer["id"]
    # reprint: reason required, same number, no new copy, counter unchanged
    r = do_print(env, setup, signer_id=signer["id"])
    assert r.json()["error"]["code"] == "REPRINT_REASON_REQUIRED"
    assert do_print(env, setup, signer_id=signer["id"], check_number="6176").json()["error"]["code"] == \
        "CHECK_NUMBER_LOCKED"
    r = do_print(env, setup, signer_id=signer["id"], reprint_reason="printer jam, check undamaged")
    assert r.status_code == 200
    assert len(env.ru.get(f"/api/attachments?owner_type=transaction&owner_id={tid}").json()) == 1
    assert env.ru.get(f"/api/checks/transactions/{tid}/options").json()["sheet_remaining"] == 2
    assert env.auditor.get("/api/audit-events?action=CHECK_REPRINTED").json()["items"][0]["after"]["reason"] \
        == "printer jam, check undamaged"
    # spoiled: zero-dollar VOID keeps 6175, the transaction moves to 6176; printing 6176 is a new check
    r = env.ru.post(f"/api/checks/transactions/{tid}/spoil", {"reason": "misaligned print", "new_check_number": "6176"})
    assert r.status_code == 200, r.text
    void = env.ru.get(f"/api/transactions/{r.json()['void_record_id']}").json()
    assert void["status"] == "VOID" and void["check_number"] == "6175" and void["zero_dollar_void"]
    assert "Spoiled check #6175" in void["void_reason"]
    assert env.ru.get(f"/api/transactions/{tid}").json()["check_number"] == "6176"
    r = env.txn(setup["acct"]["id"], "WITHDRAWAL", [{"budget_id": setup["exp_leaf"], "amount": "1.00"}],
                check_number="6175", expect=409)
    assert r["error"]["code"] == "DUPLICATE_CHECK_NUMBER"
    r = do_print(env, setup, signer_id=signer["id"], confirm="6176")
    assert r.status_code == 200, r.text
    atts = env.ru.get(f"/api/attachments?owner_type=transaction&owner_id={tid}").json()
    assert [a["original_filename"] for a in atts] == ["check-6175-record-copy.pdf", "check-6176-record-copy.pdf"]
    assert env.ru.get(f"/api/checks/transactions/{tid}/options").json()["sheet_remaining"] == 1
    # at one check left the envelope feed is suggested; after it, a fresh sheet
    assert env.ru.get(f"/api/checks/transactions/{tid}/options").json()["suggested_feed"] == "last_check"


def test_print_eligibility_and_warnings(env, setup):
    acct, leaf = setup["acct"]["id"], setup["exp_leaf"]
    dep = env.txn(acct, "DEPOSIT", [{"budget_id": setup["inc_leaf"], "amount": "5.00"}])
    assert env.ru.get(f"/api/checks/transactions/{dep['id']}/options").json()["error"]["code"] == "NOT_PRINTABLE"
    v = env.txn(acct, "WITHDRAWAL", [{"budget_id": leaf, "amount": "5.00"}], entity_id=setup["payee"]["id"])
    env.ru.post(f"/api/transactions/{v['id']}/void", {"reason": "x", "confirm_irreversible": True})
    assert env.ru.get(f"/api/checks/transactions/{v['id']}/options").status_code == 409
    # no payee: blocked
    np = env.txn(acct, "WITHDRAWAL", [{"budget_id": leaf, "amount": "5.00"}])
    r = env.ru.post(f"/api/checks/transactions/{np['id']}/prepare", job(setup))
    assert r.json()["error"]["code"] == "NO_PAYEE"
    # no check number yet: entered at print time (uniqueness checked)
    t = env.txn(acct, "WITHDRAWAL", [{"budget_id": leaf, "amount": "12.00"}], entity_id=setup["payee"]["id"],
                notes="")
    body = job(setup, confirm_check_number="6175", check_number="6175", memo_pattern="INV {INVOICE}",
               confirmations=["EMPTY_VARIABLES"])
    assert env.ru.post(f"/api/checks/transactions/{t['id']}/print", body).json()["error"]["code"] == \
        "DUPLICATE_CHECK_NUMBER"
    # empty variable warning must be confirmed
    body.update(check_number="7001", confirm_check_number="7001", confirmations=[])
    r = env.ru.post(f"/api/checks/transactions/{t['id']}/print", body)
    assert r.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert r.json()["error"]["warnings"][0]["code"] == "EMPTY_VARIABLES"
    body["confirmations"] = ["EMPTY_VARIABLES"]
    assert env.ru.post(f"/api/checks/transactions/{t['id']}/print", body).status_code == 200
    assert env.ru.get(f"/api/transactions/{t['id']}").json()["check_number"] == "7001"
    # unknown variable blocks printing
    r = env.ru.post(f"/api/checks/transactions/{t['id']}/prepare", job(setup, memo_pattern="{dtae}"))
    assert r.json()["error"]["code"] == "PATTERN_INVALID" and r.json()["error"]["suggestion"] == "DATE"
    # text too long: problems returned, printing blocked until the user accepts or edits
    long_memo = "INVOICES 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20 FOR LOTS OF SUPPLIES"
    p = env.ru.post(f"/api/checks/transactions/{setup['txn']['id']}/prepare",
                    job(setup, memo_text=long_memo)).json()
    assert not p["can_print"] and p["fields"]["memo"]["suggestion"]
    r = do_print(env, setup, memo_text=long_memo)
    assert r.json()["error"]["code"] == "TEXT_DOES_NOT_FIT"
    r = do_print(env, setup, memo_text=p["fields"]["memo"]["suggestion"])
    assert r.status_code == 200
    ev = env.auditor.get("/api/audit-events?action=CHECK_PRINTED").json()["items"][0]["after"]
    assert ev["memo"] == p["fields"]["memo"]["suggestion"] and ev["memo_overridden"]


def test_signature_limit_and_no_signature(env, setup):
    signer = make_signer(env)
    cfg = setup["style"]["config"]
    cfg["signature_limit_cents"] = 100000   # $1,000.00
    assert env.admin.put(f"/api/checks/styles/{setup['style']['id']}",
                         {"name": setup["style"]["name"], "config": cfg}).status_code == 200
    p = env.ru.post(f"/api/checks/transactions/{setup['txn']['id']}/prepare",
                    job(setup, signer_id=signer["id"])).json()
    assert p["signature"] == "NO SIGNATURE PRINTED (OVER LIMIT)" and "over $1000.00" in p["signature_notice"]
    r = do_print(env, setup, signer_id=signer["id"])
    assert r.status_code == 200 and not has_image(r.content)


def test_closed_fiscal_year_and_cleared(env, setup):
    tid = setup["txn"]["id"]
    from fmpoc.models import RegisterTransaction
    import datetime as dt
    with env.app.state.session_factory() as db:
        db.get(RegisterTransaction, tid).clear_date = dt.date(2026, 8, 5)
        db.commit()
    r = do_print(env, setup)
    assert r.json()["error"]["warnings"][0]["code"] == "CLEARED"
    assert do_print(env, setup, confirmations=["CLEARED"]).status_code == 200


def test_alignment_test_and_admin_test_print(env, setup):
    tid = setup["txn"]["id"]
    signer = make_signer(env)
    r = env.ru.post(f"/api/checks/transactions/{tid}/alignment-test", job(setup, signer_id=signer["id"]))
    assert r.status_code == 200 and not has_image(r.content)
    texts = " ".join(t for t, *_ in _texts(r.content))
    assert "ALIGNMENT TEST - NOT A CHECK" in texts and "SAMPLE SUPPLY" in texts
    assert env.ru.get(f"/api/attachments?owner_type=transaction&owner_id={tid}").json() == []
    assert env.ru.get(f"/api/checks/transactions/{tid}/options").json()["sheet_remaining"] == 3
    # admin test print: dummy data only
    sid = setup["style"]["id"]
    r = env.admin.post(f"/api/checks/styles/{sid}/test-print", {"feed_key": "last_check"})
    texts = " ".join(t for t, *_ in _texts(r.content))
    assert r.status_code == 200 and "SAMPLE PAYEE COMPANY INC" in texts and "TEST - NOT A CHECK" in texts
    assert "SAMPLE SUPPLY" not in texts
    r = env.admin.post(f"/api/checks/styles/{sid}/test-print", {"feed_key": "sheet_top", "signer_id": signer["id"]})
    assert has_image(r.content)
    r = env.admin.post(f"/api/checks/styles/{sid}/test-print", {"feed_key": "sheet_top", "sample": "LONG"})
    assert r.status_code == 200
    assert env.admin.post(f"/api/checks/styles/{sid}/calibration", {"feed_key": "sheet_top"}).status_code == 200
    assert env.admin.get("/api/audit-events?action=CHECK_TEST_PRINT").json()["items"]
    s = env.admin.post("/api/checks/sample-layout", {"config": setup["style"]["config"], "sample": "LONG"}).json()
    assert s["payee"]["fits"] is False and s["payee"]["suggestion"]
    assert env.ru.post(f"/api/checks/styles/{sid}/test-print", {"feed_key": "sheet_top"}).status_code == 403


# ------------------------------------------------------------------ my printer settings (#162)
def test_personal_printer_settings(env, setup):
    sid = setup["style"]["id"]
    r = env.ru.put("/api/checks/my-printer", {"check_style_id": sid, "feed_key": "last_check", "page": "CHECK",
                                              "dx": 0.0, "dy": -0.125})
    assert r.status_code == 200 and r.json()["page"] == "CHECK" and r.json()["dy"] == -0.125
    assert env.ru.put("/api/checks/my-printer", {"check_style_id": sid, "feed_key": "last_check",
                                                 "dx": 0.3}).status_code == 422
    p = env.ru.post(f"/api/checks/transactions/{setup['txn']['id']}/prepare", job(setup, feed_key="last_check")).json()
    assert p["placement"] == {"feed_key": "last_check", "page": "CHECK", "guide": "CENTER", "dx": 0.0, "dy": -0.125}
    # the admin layout is unchanged; another user has their own settings
    assert env.admin.get("/api/checks/setup").json()["styles"][0]["config"]["feed_modes"][1]["dy"] == 0.0
    assert env.admin.get("/api/audit-events?action=CHECK_PRINTER_SETTINGS").json()["items"]
    reset = env.ru.post("/api/checks/my-printer/reset", {"check_style_id": sid, "feed_key": "last_check"}).json()
    assert reset["customized"] is False and reset["page"] == "LETTER"
    assert env.ru.get("/api/checks/scale-check").status_code == 200
    assert env.bm.get("/api/checks/scale-check").status_code == 403
