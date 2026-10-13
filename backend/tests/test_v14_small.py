"""v1.4 CR-017 (reasoned no-attachment = documented), CR-019 (income above budget), CR-021 (bank total),
CR-022 (version/build for every user)."""
import json

from conftest import PDF_BYTES

from fmpoc import config
from fmpoc.services.documentation import Child, classify


# ------------------------------------------------------------------ CR-022
def test_cr022_version_for_every_user_without_network_details(env, base, monkeypatch, tmp_path):
    for c in (env.bu, env.ru, env.auditor, env.bm, env.admin):
        r = c.get("/api/system/version")
        assert r.status_code == 200
        v = r.json()
        assert v["version"] == config.VERSION
        assert "bind_host" not in v and "port" not in v
    # About: network details only for Administrators
    assert env.admin.get("/api/system/about").json()["bind_host"] is not None
    about = env.bu.get("/api/system/about").json()
    assert about["bind_host"] is None and about["port"] is None
    # anonymous callers get nothing
    from conftest import Api
    assert Api(env.app).get("/api/system/version").status_code == 401


def test_cr022_build_info_from_package(env, monkeypatch, tmp_path):
    f = tmp_path / "build_info.json"
    monkeypatch.setattr(config, "BUILD_INFO_FILE", f)
    assert config.build_info() is None  # development build
    f.write_text(json.dumps({"version": "1.4.0", "branch": "test", "commit": "abc1234", "run": 42,
                             "built_at": "2026-10-01T12:00:00Z", "secret": "ignored"}))
    b = env.bu.get("/api/system/version").json()["build"]
    assert b.pop("built_at_local")  # 2.0.0 #185 (tested in test_v200_build5.py)
    assert b == {"version": "1.4.0", "branch": "test", "commit": "abc1234", "run": "42", "built_at": "2026-10-01T12:00:00Z"}
    f.write_text("not json")
    assert config.build_info() is None


# ------------------------------------------------------------------ CR-021
def test_cr021_bank_account_total(env, base):
    env.account(opening="250.50")
    env.account(opening="-50.25")
    d = env.bu.get("/api/dashboard").json()
    total = sum(round(float(a["current_balance"]) * 100) for a in d["bank_accounts"])
    assert len(d["bank_accounts"]) == 3
    assert d["bank_accounts_total"] == f"{total // 100}.{total % 100:02d}" == "1200.25"


# ------------------------------------------------------------------ CR-017
def test_cr017_truth_table_reason_counts_as_documented():
    none, att = Child(0, False), Child(1, False)
    flag, flag_r = Child(0, True), Child(0, True, True)
    # parent indicator: with reason -> documented; without -> still listed
    assert classify(0, True, [none], parent_has_reason=True) is None
    assert classify(0, True, [none]) == "NO_ATTACHMENT_MARKED"
    # children
    assert classify(0, False, [flag_r, flag_r]) is None
    assert classify(0, False, [att, flag_r]) is None
    assert classify(0, False, [flag_r, flag]) == "NO_ATTACHMENT_MARKED"
    assert classify(0, False, [flag_r, none]) == "MISSING_ATTACHMENTS"


def _review(env, fy_id):
    return {i["transaction_id"]: i for i in env.bu.get(f"/api/fiscal-years/{fy_id}/documentation-review").json()["items"]}


def test_cr017_review_closure_and_dashboard(env, base):
    fy, a = base["fy"]["id"], base["acct"]["id"]
    leaf = base["inc_leaf"]
    reasoned = env.txn(a, "DEPOSIT", [{"budget_id": leaf, "amount": "1.00"}], no_attachment=True,
                       no_attachment_reason="Bank interest - direct deposit")
    blank = env.txn(a, "DEPOSIT", [{"budget_id": leaf, "amount": "2.00"}], no_attachment=True,
                    no_attachment_reason="   ")
    bare = env.txn(a, "DEPOSIT", [{"budget_id": leaf, "amount": "3.00"}], no_attachment=True)
    missing = env.txn(a, "DEPOSIT", [{"budget_id": leaf, "amount": "4.00"}])
    split_ok = env.txn(a, "DEPOSIT", [
        {"budget_id": leaf, "amount": "5.00", "no_attachment": True, "no_attachment_reason": "cash"},
        {"budget_id": leaf, "amount": "6.00", "no_attachment": True, "no_attachment_reason": "cash too"}])
    split_mixed = env.txn(a, "DEPOSIT", [
        {"budget_id": leaf, "amount": "7.00", "no_attachment": True, "no_attachment_reason": "cash"},
        {"budget_id": leaf, "amount": "8.00", "no_attachment": True}])
    items = _review(env, fy)
    assert reasoned["id"] not in items and split_ok["id"] not in items
    assert items[blank["id"]]["category"] == "NO_ATTACHMENT_MARKED"
    assert items[bare["id"]]["category"] == "NO_ATTACHMENT_MARKED"
    assert items[missing["id"]]["category"] == "MISSING_ATTACHMENTS"
    assert items[split_mixed["id"]]["category"] == "NO_ATTACHMENT_MARKED"
    assert items[split_mixed["id"]]["allocations_marked_no_attachment"] == [split_mixed["allocations"][1]["id"]]
    # closure warning and dashboard count use the same list
    w = {x["code"]: x for x in env.bm.get(f"/api/fiscal-years/{fy}/closure-check").json()["warnings"]}
    assert set(w["NO_ATTACHMENT_MARKED"]["transaction_ids"]) == {blank["id"], bare["id"], split_mixed["id"]}
    assert "without a reason" in w["NO_ATTACHMENT_MARKED"]["message"]
    assert w["MISSING_ATTACHMENTS"]["transaction_ids"] == [missing["id"]]
    assert env.bu.get("/api/dashboard").json()["attention"]["documentation_warnings"] == 4
    # giving the bare marker a reason removes it
    r = env.ru.patch(f"/api/transactions/{bare['id']}", {"no_attachment": True, "no_attachment_reason": "ACH credit"})
    assert r.status_code == 200, r.text
    assert bare["id"] not in _review(env, fy)


def test_cr017_transfers_are_documented(env, base):
    """Transfers carry a system reason, so they no longer appear in the documentation review."""
    fy = base["fy"]["id"]
    b = env.account(opening="0.00")
    r = env.ru.post("/api/transfers", {"from_account_id": base["acct"]["id"], "to_account_id": b["id"],
                                       "transaction_date": "2026-08-03", "amount": "10.00"})
    assert r.status_code == 201, r.text
    assert not any(i["is_transfer"] for i in _review(env, fy).values())


# ------------------------------------------------------------------ CR-019
def _tree(env, fy):
    return env.bu.get(f"/api/budgets?fiscal_year_id={fy}").json()


def test_cr019_income_above_budget(env, base):
    fy, a = base["fy"]["id"], base["acct"]["id"]
    env.txn(a, "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "5250.00"}])
    t = _tree(env, fy)
    inc = t["income"][0]
    assert inc["remaining"] == "-250.00" and inc["above_budget"] == "250.00" and inc["over_budget"] is False
    assert t["income_summary"]["above_budget"] == "250.00"
    # expense rows never report above_budget; the expense summary never does either
    assert t["expense"][0]["above_budget"] is None and t["expense_summary"]["above_budget"] is None
    # budget selector labels
    opt = [o for o in env.selectable(fy, "DEPOSIT") if o["id"] == base["inc_leaf"]][0]
    assert opt["above_budget"] == "250.00"
    # dashboard summary carries it too
    d = env.bu.get("/api/dashboard").json()
    assert d["budget_summary"]["income"]["above_budget"] == "250.00"
    # no OVER_BUDGET closure warning for income
    w = {x["code"] for x in env.bm.get(f"/api/fiscal-years/{fy}/closure-check").json()["warnings"]}
    assert "OVER_BUDGET" not in w


def test_cr019_income_under_budget_unchanged(env, base):
    fy = base["fy"]["id"]
    env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "100.00"}])
    inc = _tree(env, fy)["income"][0]
    assert inc["remaining"] == "4900.00" and inc["above_budget"] is None


def test_cr019_pdf_prints_above_budget(env, base):
    fy = base["fy"]["id"]
    env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "5250.00"}])
    r = env.auditor.get(f"/api/reports/audit?fiscal_year_id={fy}")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    from pypdf import PdfReader
    import io
    text = "".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "above budget" in " ".join(text.split())


__all__ = ["PDF_BYTES"]


def test_v150_frontend_build_header_and_no_store_index(env):
    """v1.5.0: API responses name the served page build; the page itself is never cached."""
    from fmpoc.app import _frontend_build
    import pathlib
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "index.html").write_text('<script type="module" crossorigin src="/assets/index-AbC_12-x.js"></script>')
    assert _frontend_build(d) == "index-AbC_12-x.js"
    assert _frontend_build(d / "missing") is None
    r = env.bu.get("/api/auth/me")
    built = _frontend_build(pathlib.Path(__import__("fmpoc.app", fromlist=["STATIC_DIR"]).STATIC_DIR))
    assert r.headers.get("X-Frontend-Build") == built
    page = env.bu.get("/about")
    if page.status_code == 200 and "text/html" in page.headers.get("content-type", ""):
        assert page.headers["cache-control"] == "no-store"
