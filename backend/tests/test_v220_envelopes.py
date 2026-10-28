"""2.2.0 (#325): one shared envelope library tagged by feature, receipt envelopes and window receipts.

Decisions (Kyle, 2026-10-23): templates have *Used for* tags (Payments, Donations) and each feature its own default;
the global Envelopes page and each feature's setup page manage them; removing a feature's tag from its default asks
for another default, from its last template leaves the feature with no envelope; an untagged template stays as *Not
used* (never deleted); *Duplicate for <feature> only* moves the tag (and default) to the copy. Receipts get the cover
letter's window options and fold marks; a printed receipt envelope is kept with the donation and on its deposit."""
from __future__ import annotations

import io

import pytest
from pypdf import PdfReader

from test_v210_donations import donor, enable as enable_donations, setup, text  # noqa: F401
from tests.test_v200_checks import enable as enable_payments


def _ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def _env(env, feature="PAYMENTS", name=None):
    body = {"kind": "ENVELOPE", "feature": feature}
    if name:
        body["name"] = name
    return _ok(env.admin.post("/api/checks/documents", body), 201)


def _lib(env, client=None):
    return _ok((client or env.admin).get("/api/envelopes"))


def _row(lib, doc_id):
    return next(x for x in lib["envelopes"] if x["id"] == doc_id)


def _feature(lib, f):
    return next(x for x in lib["features"] if x["id"] == f)


@pytest.fixture
def both(env, base):
    enable_payments(env)
    enable_donations(env)
    setup(env)
    return {"donor": donor(env), "base": base}


def _donation(env, d, lines=None):
    lines = lines or [{"kind": "MONEY", "amount_cents": 25000, "purpose": "General"}]
    return _ok(env.ru.post("/api/donations", {"donor_entity_id": d["id"], "details": "", "lines": lines}), 201)


def test_tags_defaults_and_payments_unchanged(env, both):
    """AC-AUD-001/002: tag changes audited. Payments-created templates are tagged Payments; Payments' default stays."""
    a = _env(env)
    assert a["features"] == ["PAYMENTS"] and a["default_for"] == ["PAYMENTS"] and a["is_default"]
    b = _env(env, "DONATIONS", "Receipt envelope")
    assert b["features"] == ["DONATIONS"] and b["default_for"] == ["DONATIONS"] and not b["is_default"]
    lib = _lib(env)
    assert _feature(lib, "PAYMENTS")["default"] == a["id"] and _feature(lib, "DONATIONS")["default"] == b["id"]
    assert _row(lib, a["id"])["used_for"] == ["Payments"]
    # Payments' print list shows only Payments' envelopes; Donations' only its own
    t = env.txn(both["base"]["acct"]["id"], "WITHDRAWAL", [{"budget_id": both["base"]["exp_leaf"], "amount": "5.00"}])
    docs = _ok(env.ru.get(f"/api/checks/transactions/{t['id']}/documents"))
    assert [x["id"] for x in docs["envelopes"]] == [a["id"]]
    assert env.ru.post(f"/api/checks/transactions/{t['id']}/envelope-test", {"document_id": b["id"]}).status_code == 404
    ch = _ok(env.ru.get("/api/donations/envelopes"))
    assert [x["id"] for x in ch["envelopes"]] == [b["id"]] and ch["envelopes"][0]["is_default"]
    # share the Payments template with Donations: listed second (the Donations default stays first)
    lib = _ok(env.admin.post(f"/api/envelopes/{a['id']}/tags", {"feature": "DONATIONS", "on": True}))
    assert _row(lib, a["id"])["used_for"] == ["Payments", "Donations"]
    assert [x["id"] for x in _ok(env.ru.get("/api/donations/envelopes"))["envelopes"]] == [b["id"], a["id"]]
    # make it the Donations default too; b loses that default
    lib = _ok(env.admin.post(f"/api/envelopes/{a['id']}/default", {"feature": "DONATIONS"}))
    assert _row(lib, a["id"])["default_for"] == ["PAYMENTS", "DONATIONS"] and _row(lib, b["id"])["default_for"] == []
    ev = [e for e in _ok(env.auditor.get("/api/audit-events?action=ENVELOPE_TAGS_UPDATED"))["items"]]
    assert ev and all("account_number" not in str(e) for e in ev)


def test_removing_tags_needs_a_new_default_and_untagged_is_not_used(env, both):
    a = _env(env)
    b = _env(env, name="Second envelope")
    assert b["default_for"] == []                        # Payments already has a default
    r = env.admin.post(f"/api/envelopes/{a['id']}/tags", {"feature": "PAYMENTS", "on": False})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DEFAULT_NEEDED"
    assert [c["id"] for c in r.json()["error"]["candidates"]] == [b["id"]]
    lib = _ok(env.admin.post(f"/api/envelopes/{a['id']}/tags",
                             {"feature": "PAYMENTS", "on": False, "new_default_id": b["id"]}))
    assert _row(lib, a["id"])["used_for"] == ["Not used"] and _feature(lib, "PAYMENTS")["default"] == b["id"]
    assert _row(lib, b["id"])["is_default"]              # Payments' print screen reads is_default
    # the last one: no envelope for Payments any more (printing an envelope is hidden); nothing is deleted
    lib = _ok(env.admin.post(f"/api/envelopes/{b['id']}/tags", {"feature": "PAYMENTS", "on": False}))
    assert _feature(lib, "PAYMENTS")["default"] is None and len(lib["envelopes"]) == 2
    t = env.txn(both["base"]["acct"]["id"], "WITHDRAWAL", [{"budget_id": both["base"]["exp_leaf"], "amount": "5.00"}])
    assert _ok(env.ru.get(f"/api/checks/transactions/{t['id']}/documents"))["envelopes"] == []
    # a deactivated template is no feature's default
    lib = _ok(env.admin.post(f"/api/envelopes/{a['id']}/tags", {"feature": "DONATIONS", "on": True}))
    assert _feature(lib, "DONATIONS")["default"] == a["id"]
    _ok(env.admin.post(f"/api/checks/documents/{a['id']}/flags", {"active": False}))
    assert _feature(_lib(env), "DONATIONS")["default"] is None


def test_duplicate_for_one_feature_moves_the_tag(env, both):
    a = _env(env)
    _ok(env.admin.post(f"/api/envelopes/{a['id']}/tags", {"feature": "DONATIONS", "on": True}))
    out = _ok(env.admin.post(f"/api/envelopes/{a['id']}/duplicate-for", {"feature": "DONATIONS"}), 201)
    copy = out["created"]
    assert copy["features"] == ["DONATIONS"] and copy["default_for"] == ["DONATIONS"]
    assert _row(out, a["id"])["features"] == ["PAYMENTS"] and _row(out, a["id"])["default_for"] == ["PAYMENTS"]
    assert copy["config"] == _row(out, a["id"])["config"]
    # not used for Payments -> can't be duplicated "for Payments only"
    r = env.admin.post(f"/api/envelopes/{copy['id']}/duplicate-for", {"feature": "PAYMENTS"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_TAGGED"


def test_permissions_and_modules(env, both):
    """AC-SEC-003/005/014: Administrators manage the library; financial roles and Auditors are refused; a feature's
    tag needs its module on. Cover letters stay Payments' own."""
    a = _env(env)
    for c in (env.ru, env.bm, env.bu, env.auditor):
        assert c.get("/api/envelopes").status_code == 403
        assert c.post(f"/api/envelopes/{a['id']}/tags", {"feature": "DONATIONS", "on": True}).status_code == 403
    # mass assignment: unknown fields are refused
    assert env.admin.post(f"/api/envelopes/{a['id']}/tags",
                          {"feature": "DONATIONS", "on": True, "features": "PAYMENTS,DONATIONS"}).status_code == 422
    assert env.admin.post(f"/api/envelopes/{a['id']}/tags", {"feature": "OTHER", "on": True}).status_code == 422
    # Donations only: envelopes are still managed, letters and Payments printing are not reachable
    enable_payments(env, False)
    assert env.admin.get("/api/envelopes").status_code == 200
    b = _env(env, "DONATIONS", "Receipt envelope")
    assert b["features"] == ["DONATIONS"]
    assert env.admin.post("/api/checks/documents", {"kind": "LETTER"}).status_code == 404
    assert env.admin.post("/api/checks/documents", {"kind": "ENVELOPE", "feature": "PAYMENTS"}).status_code == 404
    assert env.admin.post(f"/api/envelopes/{a['id']}/tags", {"feature": "PAYMENTS", "on": False}).status_code == 404
    assert env.admin.get("/api/checks/setup").status_code == 404
    enable_donations(env, False)
    assert env.admin.get("/api/envelopes").status_code == 404


def test_receipt_envelope_is_kept_with_the_donation_and_its_deposit(env, both):
    """AC-ATT-004, AC-AUD-001: printed envelopes are record copies (generated names), kept and audited; the test on
    plain paper is not kept."""
    a = _env(env, "DONATIONS")
    d = _donation(env, both["donor"])
    r = env.ru.post(f"/api/donations/{d['id']}/envelope-test", {"document_id": a["id"]})
    assert r.status_code == 200 and "Sample Donor One" in text(r.content)
    assert _ok(env.ru.get(f"/api/donations/{d['id']}"))["documents"] == []
    r = env.ru.post(f"/api/donations/{d['id']}/envelope", {"document_id": a["id"], "return_address": True})
    assert r.status_code == 200, r.text
    t = text(r.content)
    assert "Sample Donor One" in t and "12 Example Road" in t
    docs = _ok(env.ru.get(f"/api/donations/{d['id']}"))["documents"]
    assert [x["kind"] for x in docs] == ["DONATION_ENVELOPE"]
    # the same envelope again is not kept twice
    env.ru.post(f"/api/donations/{d['id']}/envelope", {"document_id": a["id"], "return_address": True})
    assert len(_ok(env.ru.get(f"/api/donations/{d['id']}"))["documents"]) == 1
    # read-only roles can't print; an envelope not tagged for Donations can't be used
    assert env.bu.post(f"/api/donations/{d['id']}/envelope", {"document_id": a["id"]}).status_code == 403
    p = _env(env, "PAYMENTS", "Payments only")
    assert env.ru.post(f"/api/donations/{d['id']}/envelope", {"document_id": p["id"]}).status_code == 404
    # Create transaction: the printed envelope goes with the deposit
    line = next(x for x in _ok(env.ru.get("/api/donations/awaiting-lines"))["items"] if x["donation_id"] == d["id"])
    base = both["base"]
    t = _ok(env.ru.post("/api/donations/create-transaction", {
        "transaction": {"bank_account_id": base["acct"]["id"], "transaction_type": "DEPOSIT",
                        "transaction_date": "2026-08-10",
                        "allocations": [{"budget_id": base["inc_leaf"], "amount": "250.00"}]},
        "links": [line["id"]]}), 201)
    atts = _ok(env.ru.get(f"/api/attachments?owner_type=transaction&owner_id={t['id']}"))
    atts = atts["items"] if isinstance(atts, dict) else atts
    assert any(x.get("document_type") == "DONATION_ENVELOPE" for x in atts)
    ev = _ok(env.auditor.get("/api/audit-events?action=DONATION_ENVELOPE_PRINTED"))["items"]
    assert len(ev) == 2 and ev[0]["before"] is None
    # cancelled donations print no envelope
    d2 = _donation(env, both["donor"])
    _ok(env.ru.post(f"/api/donations/{d2['id']}/cancel", {"reason": "Never given"}))
    assert env.ru.post(f"/api/donations/{d2['id']}/envelope", {"document_id": a["id"]}).status_code == 409


def test_my_envelope_printer_settings_belong_to_the_template(env, both):
    a = _env(env)
    _ok(env.admin.post(f"/api/envelopes/{a['id']}/tags", {"feature": "DONATIONS", "on": True}))
    _ok(env.ru.put("/api/donations/my-printer/envelope", {"document_id": a["id"], "page": "ENVELOPE", "dy": 0.125}))
    t = env.txn(both["base"]["acct"]["id"], "WITHDRAWAL", [{"budget_id": both["base"]["exp_leaf"], "amount": "5.00"}])
    p = _ok(env.ru.get(f"/api/checks/transactions/{t['id']}/documents"))["envelopes"][0]["printer"]
    assert p["page"] == "ENVELOPE" and p["dy"] == 0.125 and p["customized"]
    assert env.ru.put("/api/donations/my-printer/envelope", {"document_id": a["id"], "dx": 0.5}).status_code == 422


def test_window_receipt_and_fold_marks(env, both):
    """The receipt gets the cover letter's window options: addresses at the window positions, an address page, fold
    marks; a window receipt hides the envelope step."""
    d = _donation(env, both["donor"])
    plain = env.ru.post(f"/api/donations/{d['id']}/receipts/preview").content
    assert len(PdfReader(io.BytesIO(plain)).pages) == 1
    setup(env, window="ADDRESS_PAGE", fold_marks="BACK")
    assert _ok(env.ru.get("/api/donations/envelopes"))["receipt_window"] is True
    pdf = env.ru.post(f"/api/donations/{d['id']}/receipts/preview").content
    pages = PdfReader(io.BytesIO(pdf)).pages
    assert len(pages) == 4                              # address page + its back, letter + its back
    assert "Sample Donor One" in pages[0].extract_text() and "Receipt No." not in pages[0].extract_text()
    setup(env, window="LETTER", fold_marks="NONE", window_return=False)
    pdf = env.ru.post(f"/api/donations/{d['id']}/receipts/preview").content
    t = text(pdf)
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 1 and "12 Example Road" in t
    # the setup preview shows the windows with sample data only (BR-003)
    s = env.admin.post("/api/donations/setup/preview", {"config": {**_ok(env.admin.get("/api/donations/setup"))
                                                                   ["config"], "window": "LETTER"}})
    assert s.status_code == 200 and "SAMPLE DONOR" in text(s.content) and "Sample Donor One" not in text(s.content)
    bad = env.admin.put("/api/donations/setup", {"config": {**_ok(env.admin.get("/api/donations/setup"))["config"],
                                                           "window": "SIDEWAYS"}})
    assert bad.status_code == 422
    setup(env, window="NONE")
    assert _ok(env.ru.get("/api/donations/envelopes"))["receipt_window"] is False
