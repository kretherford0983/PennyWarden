"""2.3.0 build 6 (#393): Include EIN on receipts (Donations Setup, default on). On + no EIN: warned and printing
blocked; off: no EIN row and {ORG.EIN} blank in the setup text (receipts and statements), a setup warning when the
text still uses it; a one-off EIN in a donor's {DETAILS} needs a confirmation and a reason when saved, and another
confirmation when printed (backend-enforced), audited with the reason; refused when no EIN is entered."""
from __future__ import annotations

from test_v210_donations import ORG, dep, donor, enable, mark_all, print_receipt, setup, text  # noqa: F401


def _cfg(env):
    return env.admin.get("/api/donations/setup").json()


def _set(env, **kw):
    cfg = dict(_cfg(env)["config"], **kw)
    r = env.admin.put("/api/donations/setup", {"config": cfg})
    assert r.status_code == 200, r.text
    return r.json()


def _details(env, dep, who, details, **kw):
    return env.ru.put(dep["url"] + "/lines", {"lines": [], "donors": [{"entity_id": dep[who]["id"], "details": details, **kw}]})


def test_default_on_and_existing_setups_keep_it(env, dep):  # noqa: F811
    assert _cfg(env)["config"]["include_ein"] is True
    assert _cfg(env)["defaults"]["include_ein"] is True
    mark_all(env, dep)
    r = print_receipt(env, dep, "a", ["NO_DONOR_ADDRESS", "EMPTY_VARIABLES"])
    assert r.status_code == 200, r.text
    assert "EIN 12-3456789" in text(r.content)


def test_on_and_no_ein_warns_and_blocks(env, dep):  # noqa: F811
    assert env.admin.put("/api/system/organization", {**ORG, "ein": ""}).status_code == 200
    w = _cfg(env)["warnings"]
    assert [x["code"] for x in w] == ["EIN_MISSING"] and "System/About" in w[0]["message"]
    mark_all(env, dep)
    r = print_receipt(env, dep, "a")
    assert r.status_code == 409 and r.json()["error"]["code"] == "SETUP_INCOMPLETE"
    # turned off: printable without an EIN
    _set(env, include_ein=False)
    assert _cfg(env)["warnings"] == []
    r = print_receipt(env, dep, "a", ["NO_DONOR_ADDRESS", "EMPTY_VARIABLES"])
    assert r.status_code == 200, r.text


def test_off_no_ein_row_blank_placeholder_and_setup_warning(env, dep):  # noqa: F811
    _set(env, include_ein=False, body="Thank you. Our EIN is {ORG.EIN}.\n\n{DETAILS}")
    w = _cfg(env)["warnings"]
    assert [x["code"] for x in w] == ["EIN_PLACEHOLDER_OFF"] and "body" in w[0]["message"]
    mark_all(env, dep)
    r = print_receipt(env, dep, "a", ["NO_DONOR_ADDRESS"])
    assert r.status_code == 200, r.text                   # no EMPTY_VARIABLES question for the EIN left blank on purpose
    t = text(r.content)
    assert "12-3456789" not in t and "EIN" in t           # "Our EIN is ." - the template text, not the row
    assert "EIN 12-3456789" not in t
    ev = env.admin.get("/api/audit-events?action=DONATION_SETUP_UPDATED").json()["items"][0]
    assert ev["after"]["include_ein"] is False


def test_details_override_needs_confirmation_reason_and_print_confirmation(env, dep):  # noqa: F811
    _set(env, include_ein=False)
    mark_all(env, dep)
    r = _details(env, dep, "a", "Non-cash gift over $500; our EIN is {ORG.EIN} for Form 8283.")
    assert r.status_code == 409 and r.json()["error"]["code"] == "EIN_OVERRIDE_REQUIRED"
    r = _details(env, dep, "a", "Our EIN is {ORG.EIN}.", confirm_ein_override=True)
    assert r.status_code == 409                                                     # a reason is required too
    r = _details(env, dep, "a", "Our EIN is {ORG.EIN}.", confirm_ein_override=True, ein_override_reason="  ")
    assert r.status_code == 409
    r = _details(env, dep, "a", "Our EIN is {ORG.EIN}.", confirm_ein_override=True,
                 ein_override_reason="Form 8283 for a car donation")
    assert r.status_code == 200, r.text
    ev = env.auditor.get("/api/audit-events?action=DONATION_DETAILS_UPDATED").json()["items"][0]
    assert ev["after"]["ein_override_reason"] == "Form 8283 for a car donation"
    # print: one more confirmation, enforced by the backend
    r = print_receipt(env, dep, "a", ["NO_DONOR_ADDRESS"])
    assert r.status_code == 409 and "EIN_OVERRIDE" in [w["code"] for w in r.json()["error"]["warnings"]]
    r = print_receipt(env, dep, "a", ["NO_DONOR_ADDRESS", "EIN_OVERRIDE"])
    assert r.status_code == 200, r.text
    t = text(r.content)
    assert "Our EIN is 12-3456789." in t and "EIN 12-3456789" not in t             # only where the details put it
    ev = env.auditor.get("/api/audit-events?action=DONATION_RECEIPT_PRINTED").json()["items"][0]
    assert ev["after"]["ein_override"] is True and ev["after"]["ein_override_reason"] == "Form 8283 for a car donation"


def test_override_refused_without_an_ein(env, dep):  # noqa: F811
    _set(env, include_ein=False)
    assert env.admin.put("/api/system/organization", {**ORG, "ein": ""}).status_code == 200
    mark_all(env, dep)
    r = _details(env, dep, "a", "EIN {ORG_EIN}", confirm_ein_override=True, ein_override_reason="x")
    assert r.status_code == 409 and r.json()["error"]["code"] == "EIN_NOT_ENTERED"


def test_statement_follows_the_setting(env, dep):  # noqa: F811
    mark_all(env, dep)
    _set(env, include_ein=False)
    r = env.ru.post(f"/api/donations/statements/2026/donors/{dep['a']['id']}", {"confirmations": ["NO_DONOR_ADDRESS"]})
    assert r.status_code == 200, r.text
    assert "12-3456789" not in text(r.content)
    _set(env, include_ein=True)
    r = env.ru.post(f"/api/donations/statements/2026/donors/{dep['a']['id']}",
                    {"confirmations": ["NO_DONOR_ADDRESS", "CORRECTED_STATEMENT"]})
    assert r.status_code == 200, r.text
    assert "EIN 12-3456789" in text(r.content)


def test_only_administrators_change_it(env, dep):  # noqa: F811
    cfg = dict(_cfg(env)["config"], include_ein=False)
    for c in (env.ru, env.bm, env.auditor):
        assert c.put("/api/donations/setup", {"config": cfg}).status_code == 403
    assert env.admin.put("/api/donations/setup", {"config": {**cfg, "include_ein": "maybe"}}).status_code == 422
