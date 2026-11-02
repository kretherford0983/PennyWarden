"""2.3.0 polish (Kyle, 2026-10-31): a letter's signer can be chosen when printing. Donation receipts, year-end
statements and payment cover letters: the settings say Fixed or Chosen when printing (the setting's signer the
default); the print screen asks only when more than one active signer is tagged for the area; a reprint starts from
the signer of the copy it reprints (receipts/statements) or the check's signer (cover letters); a signer not tagged
for the area, retired, or a change while the setting is Fixed, is refused (BR-078/BR-098/BR-099). Each printed
receipt/statement records its signer (migration 0069)."""
from __future__ import annotations

from test_v200_letters import setup_docs, vendor
from test_v210_donations import text
from test_v230_shared_signers import _deposit, _dsetup, _enable, _signer


def _signing(env, dep):
    return env.ru.get(dep["url"]).json()["donors"][0]["signing"]


def test_receipt_fixed_signer_is_not_asked_and_cant_be_changed(env, base):
    _enable(env, checks=False)
    a = _signer(env, "Alex One").json()
    b = _signer(env, "Bea Two").json()
    assert _dsetup(env, signer_id=a["id"], signature_mode="PRINTED").status_code == 200
    dep = _deposit(env, base)
    sg = _signing(env, dep)
    assert sg["choice"] == "FIXED" and sg["ask"] is False and sg["signers"] == []
    body = {"donor_entity_id": dep["a"]["id"], "confirmations": ["NO_DONOR_ADDRESS", "EMPTY_VARIABLES"]}
    r = env.ru.post(dep["url"] + "/receipts", {**body, "signer_id": b["id"]})
    assert r.status_code == 422 and r.json()["error"]["errors"][0]["field"] == "signer_id"
    r = env.ru.post(dep["url"] + "/receipts", body)
    assert r.status_code == 200 and "Alex One" in text(r.content)


def test_receipt_chosen_when_printing(env, base):
    _enable(env, checks=False)
    a = _signer(env, "Alex One").json()
    b = _signer(env, "Bea Two").json()
    other = _signer(env, "Cory Checks", areas="CHECKS").json()
    assert _dsetup(env, signer_id=a["id"], signature_mode="PRINTED", signer_choice="AT_PRINT").status_code == 200
    dep = _deposit(env, base)
    sg = _signing(env, dep)
    assert sg["choice"] == "AT_PRINT" and sg["ask"] is True and sg["default_id"] == a["id"]
    assert [s["name"] for s in sg["signers"]] == ["Alex One", "Bea Two"]           # tagged for donations only
    url = dep["url"] + "/receipts"
    body = {"donor_entity_id": dep["a"]["id"], "confirmations": ["NO_DONOR_ADDRESS", "EMPTY_VARIABLES"]}
    # not tagged for donation letters, or an unknown id: refused
    assert env.ru.post(url, {**body, "signer_id": other["id"]}).status_code == 422
    assert env.ru.post(url, {**body, "signer_id": 999999}).status_code == 422
    # the preview uses the chosen signer too
    pv = env.ru.post(url + "/preview", {"donor_entity_id": dep["a"]["id"], "signer_id": b["id"]})
    assert pv.status_code == 200 and "Bea Two" in text(pv.content)
    r = env.ru.post(url, {**body, "signer_id": b["id"]})
    assert r.status_code == 200, r.text
    assert "Bea Two" in text(r.content) and "Alex One" not in text(r.content)
    ev = env.auditor.get("/api/audit-events?action=DONATION_RECEIPT_PRINTED").json()["items"][0]
    assert ev["after"]["signer_id"] == b["id"]
    # a reprint starts from the last receipt's signer
    assert _signing(env, dep)["default_id"] == b["id"]
    # no signer chosen: the default signs
    r = env.ru.post(url, body)
    assert r.status_code == 200 and "Alex One" in text(r.content) and r.headers["X-Receipt-Kind"] == "DUPLICATE"


def test_receipt_one_tagged_signer_is_not_asked(env, base):
    _enable(env, checks=False)
    a = _signer(env, "Alex One").json()
    assert _dsetup(env, signer_id=a["id"], signature_mode="PRINTED", signer_choice="AT_PRINT").status_code == 200
    dep = _deposit(env, base)
    sg = _signing(env, dep)
    assert sg["choice"] == "AT_PRINT" and sg["ask"] is False and sg["default_id"] == a["id"]
    r = env.ru.post(dep["url"] + "/receipts", {"donor_entity_id": dep["a"]["id"],
                                               "confirmations": ["NO_DONOR_ADDRESS", "EMPTY_VARIABLES"]})
    assert r.status_code == 200 and "Alex One" in text(r.content)


def test_no_signature_means_no_choice(env, base):
    _enable(env, checks=False)
    a = _signer(env, "Alex One").json()
    _signer(env, "Bea Two")
    assert _dsetup(env, signer_id=a["id"], signature_mode="NONE", signer_choice="AT_PRINT").status_code == 200
    dep = _deposit(env, base)
    assert _signing(env, dep)["ask"] is False
    r = env.ru.post(dep["url"] + "/receipts", {"donor_entity_id": dep["a"]["id"], "signer_id": a["id"],
                                               "confirmations": ["NO_DONOR_ADDRESS", "EMPTY_VARIABLES"]})
    assert r.status_code == 422


def test_statements_chosen_when_printing_one_and_all(env, base):
    _enable(env, checks=False)
    a = _signer(env, "Alex One").json()
    b = _signer(env, "Bea Two").json()
    assert _dsetup(env, signer_id=a["id"], signature_mode="PRINTED",
                   statement_signer_choice="AT_PRINT").status_code == 200
    dep = _deposit(env, base)
    url = f"/api/donations/statements/2026/donors/{dep['a']['id']}"
    sg = env.ru.get(url).json()["signing"]
    assert sg["ask"] is True and sg["default_id"] == a["id"]
    assert env.ru.get("/api/donations/statements?year=2026").json()["signing"]["ask"] is True
    pv = env.ru.post(url + "/preview", {"signer_id": b["id"]})
    assert pv.status_code == 200 and "Bea Two" in text(pv.content)
    r = env.ru.post(url, {"confirmations": ["NO_DONOR_ADDRESS"], "signer_id": b["id"]})
    assert r.status_code == 200 and "Bea Two" in text(r.content)
    assert env.ru.get(url).json()["signing"]["default_id"] == b["id"]            # a reprint starts from Bea
    # Print all: one signer for the batch
    r = env.ru.post("/api/donations/statements/2026/print-all",
                    {"confirmations": ["PRINT_ALL", "NO_DONOR_ADDRESS"], "signer_id": a["id"]})
    assert r.status_code == 200, r.text
    assert "Alex One" in text(r.content) and "Bea Two" not in text(r.content)
    # the receipt stays Fixed: its signer can't be changed when printing
    r = env.ru.post(dep["url"] + "/receipts", {"donor_entity_id": dep["a"]["id"], "signer_id": b["id"],
                                               "confirmations": ["NO_DONOR_ADDRESS", "EMPTY_VARIABLES"]})
    assert r.status_code == 422


def test_cover_letter_chosen_when_printing(env, base):
    _enable(env, donations=False)
    style = env.admin.post("/api/checks/styles", {"preset_key": env.admin.get("/api/checks/setup").json()["presets"][0]["key"]}).json()
    letter, _envelope = setup_docs(env)
    chk = _signer(env, "Chris Checks", areas="CHECKS,COVER_LETTERS").json()
    fran = _signer(env, "Fran Letters", title="Secretary", areas="COVER_LETTERS").json()
    only_checks = _signer(env, "Olive Only", areas="CHECKS").json()
    v = vendor(env)
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "10.00", "invoice_number": "1"}],
                entity_id=v["id"])
    env.ru.put(f"/api/checks/accounts/{base['acct']['id']}", {"check_style_id": style["id"]})
    url = f"/api/checks/transactions/{t['id']}/letter"
    docs = f"/api/checks/transactions/{t['id']}/documents"
    # Fixed: not asked, and a different letter signer is refused
    cfg = dict(letter["config"], signer_source="FIXED", signer_id=fran["id"], signature_mode="PRINTED")
    assert env.admin.put(f"/api/checks/documents/{letter['id']}", {"name": letter["name"], "config": cfg}).status_code == 200
    sg = next(x for x in env.ru.get(docs).json()["letters"] if x["id"] == letter["id"])["signing"]
    assert sg["ask"] is False
    r = env.ru.post(url, {"document_id": letter["id"], "letter_signer_id": chk["id"]})
    assert r.status_code == 422 and r.json()["error"]["errors"][0]["field"] == "letter_signer_id"
    # Chosen when printing: asked; starts from the check's signer when tagged for cover letters
    cfg["signer_source"] = "AT_PRINT"
    assert env.admin.put(f"/api/checks/documents/{letter['id']}", {"name": letter["name"], "config": cfg}).status_code == 200
    sg = next(x for x in env.ru.get(f"{docs}?check_signer_id={chk['id']}").json()["letters"] if x["id"] == letter["id"])["signing"]
    assert sg["ask"] is True and sg["default_id"] == chk["id"]
    assert [s["name"] for s in sg["signers"]] == ["Chris Checks", "Fran Letters"]
    sg = next(x for x in env.ru.get(docs).json()["letters"] if x["id"] == letter["id"])["signing"]
    assert sg["default_id"] == fran["id"]                                        # no check signer: the default
    assert env.ru.post(url, {"document_id": letter["id"], "letter_signer_id": only_checks["id"]}).status_code == 422
    tx = text(env.ru.post(url, {"document_id": letter["id"], "signer_id": chk["id"],
                                "letter_signer_id": fran["id"]}).content)
    assert "Fran Letters" in tx and "Chris Checks" not in tx
    tx = text(env.ru.post(url, {"document_id": letter["id"], "signer_id": chk["id"]}).content)
    assert "Fran Letters" in tx                                                  # nothing chosen: the default
    ev = env.auditor.get("/api/audit-events?action=CHECK_LETTER_PRINTED").json()["items"][0]
    assert ev["after"]["signer_id"] == fran["id"]


def test_setup_validates_the_choice(env, base):
    _enable(env)
    a = _signer(env, "Alex One").json()
    assert _dsetup(env, signature_mode="PRINTED", signer_choice="AT_PRINT").status_code == 422     # needs a default
    assert _dsetup(env, signer_id=a["id"], signature_mode="PRINTED", signer_choice="SOMETIMES").status_code == 422
    letter = env.admin.post("/api/checks/documents", {"kind": "LETTER"}).json()
    lc = dict(letter["config"], signer_source="AT_PRINT", signer_id=None, signature_mode="PRINTED")
    assert env.admin.put(f"/api/checks/documents/{letter['id']}", {"name": letter["name"], "config": lc}).status_code == 422
