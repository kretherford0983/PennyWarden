"""2.3.0 build 7 (#395): one shared list of signers (own Signers page, Administrators, Payments or Donations on),
tagged for the areas they may be used in; each letter chooses its signer and signature mode (None, Printed only,
Signature image + printed, Printed with space to sign by hand); the image goes only into the printed copy, never the
record copy kept with the record; the cover letter can use the check's signer; the statement its own; the typed names
of 2.2.0 become signers on upgrade. A signer in use can't be retired or lose that area."""
from __future__ import annotations

import io
import json
import sqlite3

from pypdf import PdfReader

from test_v200_checks import has_image, sig_png
from test_v200_letters import setup_docs, vendor
from test_v210_donations import ORG, donor, mark_all, print_receipt, text  # noqa: F401


def _enable(env, checks=True, donations=True):
    assert env.admin.put("/api/system/modules", {"checks": checks, "donations": donations}).status_code == 200


def _signer(env, name, title="Treasurer", areas="DONATIONS", image=True, client=None):
    c = client or env.admin
    r = c.c.post("/api/signers", data={"name": name, "title": title, "areas": areas},
                 files={"file": ("sig.png", sig_png(), "image/png")} if image else None,
                 headers={"X-CSRF-Token": c.csrf})
    return r


def _dsetup(env, **kw):
    assert env.admin.put("/api/system/organization", ORG).status_code == 200
    cfg = dict(env.admin.get("/api/donations/setup").json()["config"], **kw)
    return env.admin.put("/api/donations/setup", {"config": cfg})


def _deposit(env, base):
    a = donor(env)
    t = env.txn(base["acct"]["id"], "DEPOSIT", [
        {"budget_id": base["inc_leaf"], "amount": "100.00", "entity_id": a["id"], "description": "Gift"}], date="2026-08-03")
    dep = {"t": t, "a": a, "allocs": [x["id"] for x in t["allocations"]], "url": f"/api/donations/transactions/{t['id']}"}
    r = env.ru.put(dep["url"] + "/lines", {"lines": [{"allocation_id": dep["allocs"][0], "donation": True}]})
    assert r.status_code == 200, r.text
    return dep


def _atts(env, tid):
    return env.auditor.get(f"/api/attachments?owner_type=transaction&owner_id={tid}").json()


def _att_bytes(env, att):
    r = env.auditor.get(f"/api/attachments/{att['id']}/content")
    assert r.status_code == 200, r.text
    return r.content


# ------------------------------------------------------------------ the Signers page
def test_signers_page_access_and_areas(env, base):
    assert env.admin.get("/api/signers").status_code == 404              # neither module on
    _enable(env, checks=False, donations=True)
    for c in (env.bm, env.ru, env.auditor):
        assert c.get("/api/signers").status_code == 403
    r = _signer(env, "Jordan Sample", areas="DONATIONS,COVER_LETTERS")
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["areas"] == ["COVER_LETTERS", "DONATIONS"] and s["has_image"]
    d = env.admin.get("/api/signers").json()
    assert [a["id"] for a in d["areas"]] == ["CHECKS", "COVER_LETTERS", "DONATIONS"]
    assert {a["id"]: a["enabled"] for a in d["areas"]} == {"CHECKS": False, "COVER_LETTERS": False, "DONATIONS": True}
    assert _signer(env, "X", areas="EVERYTHING").status_code == 422
    r = env.admin.put(f"/api/signers/{s['id']}/areas", {"areas": ["DONATIONS"]})
    assert r.status_code == 200 and r.json()["areas"] == ["DONATIONS"]
    ev = env.admin.get("/api/audit-events?action=SIGNER_AREAS_CHANGED").json()["items"][0]
    assert ev["after"] == {"areas": ["DONATIONS"]} and "image" not in json.dumps(ev).lower().replace("image_sha256", "")
    # never downloadable: only the SAMPLE preview
    p = env.admin.get(f"/api/signers/{s['id']}/preview")
    assert p.status_code == 200 and p.headers["content-type"] == "image/png"


def test_area_tags_are_enforced_and_in_use_signers_kept(env, base):
    _enable(env)
    don = _signer(env, "Dana Donations", areas="DONATIONS").json()
    chk = _signer(env, "Chris Checks", areas="CHECKS").json()
    # Donations Setup accepts only DONATIONS signers
    r = _dsetup(env, signer_id=chk["id"], signature_mode="PRINTED")
    assert r.status_code == 422 and "not tagged" in r.json()["error"]["message"]
    assert _dsetup(env, signer_id=don["id"], signature_mode="PRINTED").status_code == 200
    assert [s["id"] for s in env.admin.get("/api/donations/setup").json()["signers"]] == [don["id"]]
    # a check style's default signer must be tagged for checks
    preset = env.admin.get("/api/checks/setup").json()["presets"][0]["key"]
    style = env.admin.post("/api/checks/styles", {"preset_key": preset}).json()
    cfg = dict(style["config"], default_signer_id=don["id"])
    assert env.admin.put(f"/api/checks/styles/{style['id']}", {"name": style["name"], "config": cfg}).status_code == 422
    # a cover letter's chosen signer must be tagged for cover letters
    letter = env.admin.post("/api/checks/documents", {"kind": "LETTER"}).json()
    lc = dict(letter["config"], signer_source="FIXED", signer_id=don["id"])
    assert env.admin.put(f"/api/checks/documents/{letter['id']}", {"name": letter["name"], "config": lc}).status_code == 422
    # in use: can't be retired, can't lose the area
    r = env.admin.post(f"/api/signers/{don['id']}/active", {"active": False})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SIGNER_IN_USE"
    r = env.admin.put(f"/api/signers/{don['id']}/areas", {"areas": ["CHECKS"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "SIGNER_IN_USE"
    assert "Donation receipt" in next(s for s in env.admin.get("/api/signers").json()["signers"] if s["id"] == don["id"])["in_use"]
    assert env.admin.post(f"/api/signers/{chk['id']}/active", {"active": False}).status_code == 200


def test_receipt_signature_modes_and_the_record_copy_has_no_image(env, base):
    _enable(env, checks=False)
    s = _signer(env, "Jordan Sample").json()
    dep = _deposit(env, base)
    for mode, name_shown in (("NONE", False), ("PRINTED", True), ("SPACE", True)):
        assert _dsetup(env, signer_id=s["id"], signature_mode=mode).status_code == 200
        pdf = env.admin.post("/api/donations/setup/preview", {}).content
        assert ("Jordan Sample" in text(pdf)) is name_shown and not has_image(pdf), mode
    # Signature image + printed: the Administrator's preview shows the real image
    assert _dsetup(env, signer_id=s["id"], signature_mode="IMAGE").status_code == 200
    assert has_image(env.admin.post("/api/donations/setup/preview", {}).content)
    # the Register User's print: the image in the printed copy, never in the copy kept with the deposit
    r = print_receipt(env, dep, "a", ["NO_DONOR_ADDRESS", "EMPTY_VARIABLES"])
    assert r.status_code == 200, r.text
    assert has_image(r.content) and "Jordan Sample" in text(r.content)
    kept = [a for a in _atts(env, dep["t"]["id"]) if a["original_filename"].startswith("receipt-")]
    assert len(kept) == 1
    copy = _att_bytes(env, kept[0])
    assert not has_image(copy) and "Jordan Sample" in text(copy)
    # the preview a Register User sees has no image either
    pv = env.ru.post(dep["url"] + "/receipts/preview", {"donor_entity_id": dep["a"]["id"]})
    assert pv.status_code == 200 and not has_image(pv.content)
    # no image on the signer: IMAGE falls back to space to sign, with a setup warning
    plain = _signer(env, "Pat Plain", image=False).json()
    assert _dsetup(env, signer_id=plain["id"], signature_mode="IMAGE").status_code == 200
    assert "SIGNER_NO_IMAGE" in [w["code"] for w in env.admin.get("/api/donations/setup").json()["warnings"]]
    # Register Users can't change the signer or mode for a print (fixed by settings)
    assert env.ru.post(dep["url"] + "/receipts", {"donor_entity_id": dep["a"]["id"], "signer_id": s["id"]}).status_code == 422


def test_statement_has_its_own_signer(env, base):
    _enable(env, checks=False)
    a = _signer(env, "Alex Receipts").json()
    b = _signer(env, "Bea Statements").json()
    dep = _deposit(env, base)
    assert _dsetup(env, signer_id=a["id"], signature_mode="PRINTED").status_code == 200
    r = env.ru.post(f"/api/donations/statements/2026/donors/{dep['a']['id']}", {"confirmations": ["NO_DONOR_ADDRESS"]})
    assert r.status_code == 200 and "Alex Receipts" in text(r.content)          # default: the receipt's
    assert _dsetup(env, signer_id=a["id"], signature_mode="PRINTED", statement_signer_id=b["id"],
                   statement_signature_mode="IMAGE").status_code == 200
    r = env.ru.post(f"/api/donations/statements/2026/donors/{dep['a']['id']}",
                    {"confirmations": ["NO_DONOR_ADDRESS", "CORRECTED_STATEMENT"]})
    assert r.status_code == 200, r.text
    assert "Bea Statements" in text(r.content) and has_image(r.content)
    doc = env.ru.get(f"/api/donations/statements/printed/{r.headers['X-Statement-Id']}/document")
    assert doc.status_code == 200 and not has_image(doc.content)          # the kept copy: the printed name only


def test_cover_letter_same_as_check_or_fixed_signer(env, base):
    _enable(env, donations=False)
    style = env.admin.post("/api/checks/styles", {"preset_key": env.admin.get("/api/checks/setup").json()["presets"][0]["key"]}).json()
    letter, _envelope = setup_docs(env)
    chk = _signer(env, "Chris Checks", areas="CHECKS").json()
    fixed = _signer(env, "Fran Letters", title="Secretary", areas="COVER_LETTERS").json()
    v = vendor(env)
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "10.00", "invoice_number": "1"}],
                entity_id=v["id"])
    env.ru.put(f"/api/checks/accounts/{base['acct']['id']}", {"check_style_id": style["id"]})
    url = f"/api/checks/transactions/{t['id']}/letter"
    # Same as the check's signer (the 2.2.0 behavior), printed only
    tx = text(env.ru.post(url, {"document_id": letter["id"], "signer_id": chk["id"]}).content)
    assert "Chris Checks" in tx
    # the check had no signer: the template's chosen signer
    cfg = dict(letter["config"], signer_source="SAME_AS_CHECK", signer_id=fixed["id"], signature_mode="IMAGE")
    assert env.admin.put(f"/api/checks/documents/{letter['id']}", {"name": letter["name"], "config": cfg}).status_code == 200
    pdf = env.ru.post(url, {"document_id": letter["id"]}).content
    assert "Fran Letters" in text(pdf) and has_image(pdf)
    kept = [a for a in _atts(env, t["id"]) if a["original_filename"].startswith("letter-")]
    assert kept and not any(has_image(_att_bytes(env, a)) for a in kept)
    # fixed: always the chosen signer, whatever the check's
    cfg["signer_source"] = "FIXED"
    env.admin.put(f"/api/checks/documents/{letter['id']}", {"name": letter["name"], "config": cfg})
    tx = text(env.ru.post(url, {"document_id": letter["id"], "signer_id": chk["id"]}).content)
    assert "Fran Letters" in tx and "Chris Checks" not in tx
    # the Administrator's preview shows the real signature
    assert has_image(env.admin.post(f"/api/checks/documents/{letter['id']}/test-print", {}).content)


def test_upgrade_turns_typed_names_into_signers(tmp_path):
    """0064: existing check signers get CHECKS; Donations' typed signer -> a DONATIONS signer, mode SPACE; a cover
    letter's typed fallback without variables -> a COVER_LETTERS signer chosen by the template."""
    from alembic import command

    from fmpoc.db import alembic_config
    url = f"sqlite:///{tmp_path / 'm.sqlite3'}"
    command.upgrade(alembic_config(url), "0063_donation_ein_override")
    c = sqlite3.connect(tmp_path / "m.sqlite3")
    c.execute("pragma foreign_keys=off")
    wcols = [r[1] for r in c.execute("pragma table_info(workspace)")]
    row = {k: None for k in wcols}
    row.update(id=1, name="Acme", created_at="2026-01-01 00:00:00")
    for r in c.execute("pragma table_info(workspace)").fetchall():          # NOT NULL columns without a default
        if r[3] and row.get(r[1]) is None:
            row[r[1]] = 0 if "INT" in (r[2] or "").upper() or "BOOL" in (r[2] or "").upper() else ""
    c.execute(f"insert into workspace ({','.join(row)}) values ({','.join('?' * len(row))})", list(row.values()))
    c.execute("insert into check_signer (id, workspace_id, name, title, active, created_at, updated_at) "
              "values (1, 1, 'Chris Checks', 'Treasurer', 1, '2026-01-01', '2026-01-01')")
    c.execute("insert into donation_settings (id, workspace_id, config_json, updated_at) values (1, 1, ?, '2026-01-01')",
              (json.dumps({"signer_name": "Jordan Sample", "signer_title": "Treasurer", "title": "Receipt"}),))
    for i, (fname, frole) in enumerate([("Pat Example", "Treasurer"), ("{ORG} office", "")], start=1):
        c.execute("insert into check_document (id, workspace_id, kind, name, active, is_default, config_json, created_at, "
                  "updated_at) values (?, 1, 'LETTER', ?, 1, 0, ?, '2026-01-01', '2026-01-01')",
                  (i, f"L{i}", json.dumps({"fallback_name": fname, "fallback_role": frole})))
    c.commit()
    c.close()
    command.upgrade(alembic_config(url), "head")
    c = sqlite3.connect(tmp_path / "m.sqlite3")
    signers = {r[1]: (r[0], r[2], r[3]) for r in c.execute("select id, name, title, areas from check_signer")}
    assert signers["Chris Checks"][2] == "CHECKS"
    assert signers["Jordan Sample"][1:] == ("Treasurer", "DONATIONS")
    assert signers["Pat Example"][1:] == ("Treasurer", "COVER_LETTERS")
    cfg = json.loads(c.execute("select config_json from donation_settings").fetchone()[0])
    assert cfg["signer_id"] == signers["Jordan Sample"][0] and cfg["signature_mode"] == "SPACE" and "signer_name" not in cfg
    l1, l2 = [json.loads(r[0]) for r in c.execute("select config_json from check_document order by id")]
    assert l1["signer_id"] == signers["Pat Example"][0] and l1["signer_source"] == "SAME_AS_CHECK"
    assert l1["signature_mode"] == "PRINTED"
    assert "signer_id" not in l2 and l2["fallback_name"] == "{ORG} office"          # variables: kept as typed
    c.close()


def test_setup_pages_offer_only_tagged_signers(env, base):
    _enable(env)
    _signer(env, "Dana Donations", areas="DONATIONS")
    _signer(env, "Lee Letters", areas="COVER_LETTERS")
    _signer(env, "Chris Checks", areas="CHECKS")
    cs = env.admin.get("/api/checks/setup").json()
    assert [x["name"] for x in cs["signers"]] == ["Chris Checks"]
    assert [x["name"] for x in cs["letter_signers"]] == ["Lee Letters"]
    assert [m["id"] for m in cs["signature_modes"]] == ["NONE", "PRINTED", "IMAGE", "SPACE"]
    ds = env.admin.get("/api/donations/setup").json()
    assert [x["name"] for x in ds["signers"]] == ["Dana Donations"]
