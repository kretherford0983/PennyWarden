"""Fiscal Years. AC-FY-001..013, AC-FY-VIS-001..011."""
import datetime as dt

from conftest import PDF_BYTES, unique_pdf


def upload_fy_doc(env, fy_id, document_type="AUDIT_SIGNOFF"):
    r = env.bm.c.post(f"/api/attachments?owner_type=fiscal_year&owner_id={fy_id}&document_type={document_type}",
                      files={"file": ("signoff.pdf", unique_pdf(), "application/pdf")},
                      headers={"X-CSRF-Token": env.bm.csrf})
    assert r.status_code == 201, r.text
    return r.json()


def test_ac_fy_001_naming(env):
    fy = env.fy("2028", "2027-07-01", "2028-06-30")
    assert fy["display_name"] == "FY2028" and fy["label"] == "FY2028 — Draft"


def test_ac_fy_002_relative_quarters(env):
    fy = env.fy("2027", "2026-07-01", "2027-06-30")
    q = env.bm.get(f"/api/budgets?fiscal_year_id={fy['id']}").json()["quarters"]
    assert [(x["start_date"], x["end_date"]) for x in q] == [
        ("2026-07-01", "2026-09-30"), ("2026-10-01", "2026-12-31"), ("2027-01-01", "2027-03-31"),
        ("2027-04-01", "2027-06-30")]


def test_ac_fy_002_quarter_activity_by_transaction_date(env, base):
    for d, amt in [("2026-08-01", "1.00"), ("2026-11-15", "2.00"), ("2027-02-01", "3.00"), ("2027-06-30", "4.00")]:
        env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": amt}], date=d)
    row = env.bu.get(f"/api/fiscal-years/{base['fy']['id']}").json()["budgets"]["expense"][0]
    assert row["quarters"] == ["1.00", "2.00", "3.00", "4.00"] and row["actual"] == "10.00"


def test_ac_fy_003_consecutive_no_warning(env):
    env.fy("2027", "2026-07-01", "2027-06-30")
    r = env.bm.post("/api/fiscal-years", {"identifier": "2028", "start_date": "2027-07-01", "end_date": "2028-06-30"})
    assert r.status_code == 201


def test_ac_fy_004_gap_warning(env):
    env.fy("2027", "2026-07-01", "2027-06-30")
    body = {"identifier": "2028", "start_date": "2027-08-01", "end_date": "2028-07-31"}
    r = env.bm.post("/api/fiscal-years", body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    w = r.json()["error"]["warnings"][0]
    assert w["code"] == "FY_GAP" and "WARNING" in w["message"]
    assert w["details"]["gaps"][0]["from"] == "2027-07-01" and w["details"]["gaps"][0]["to"] == "2027-07-31"
    assert len(env.bm.get("/api/fiscal-years").json()) == 1
    r = env.bm.post("/api/fiscal-years", {**body, "confirmations": ["FY_GAP"]})
    assert r.status_code == 201 and r.json()["exception_confirmed"] == "FY_GAP"


def test_ac_fy_005_overlap_warning_with_readiness(env):
    env.fy("2027", "2026-07-01", "2027-06-30")
    body = {"identifier": "2027B", "start_date": "2027-01-01", "end_date": "2027-12-31"}
    r = env.bm.post("/api/fiscal-years", body)
    assert r.status_code == 409
    w = [x for x in r.json()["error"]["warnings"] if x["code"] == "FY_OVERLAP"][0]
    ov = w["details"]["overlapping"][0]
    assert ov["display_name"] == "FY2027" and ov["status"] == "DRAFT"
    assert "readiness" in ov and any(b["code"] == "NOT_APPROVED" for b in ov["readiness"]["blockers"])
    # only Budget Manager may confirm
    assert env.ru.post("/api/fiscal-years", {**body, "confirmations": ["FY_OVERLAP"]}).status_code == 403
    assert env.bm.post("/api/fiscal-years", {**body, "confirmations": ["FY_OVERLAP"]}).status_code == 201


def test_ac_fy_006_ambiguous_overlapping_date(env):
    a = env.fy("2027", "2026-07-01", "2027-06-30")
    b = env.fy("2027C", "2027-01-01", "2027-12-31", confirmations=["FY_OVERLAP"])
    ba = env.budget(a["id"], "1000", "Ops A")
    bb = env.budget(b["id"], "1000", "Ops B")
    acct = env.account()
    nat = env.ru.get("/api/fiscal-years/natural?date=2027-03-01").json()
    assert nat["ambiguous"] is True and nat["default_fiscal_year_id"] is None
    leaf_a = env.selectable(a["id"], "WITHDRAWAL")[0]["id"]
    # without explicit Fiscal Year selection the backend refuses to choose
    r = env.ru.post("/api/transactions", {"bank_account_id": acct["id"], "transaction_type": "WITHDRAWAL",
                                          "transaction_date": "2027-03-01",
                                          "allocations": [{"budget_id": leaf_a, "amount": "5.00"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "AMBIGUOUS_FISCAL_YEAR"
    assert len(r.json()["error"]["candidates"]) == 2
    r = env.ru.post("/api/transactions", {"bank_account_id": acct["id"], "transaction_type": "WITHDRAWAL",
                                          "transaction_date": "2027-03-01",
                                          "allocations": [{"budget_id": leaf_a, "fiscal_year_id": a["id"], "amount": "5.00"}]})
    assert r.status_code == 201
    assert bb


def test_ac_fy_007_copy_prior_budgets(env):
    src = env.fy("2027", "2026-07-01", "2027-06-30")
    p = env.budget(src["id"], "1000", "Operations", "EXPENSE", "100000.00")
    env.budget(src["id"], "01", "Travel", amount="25000.00", parent=p["id"])
    q = env.budget(src["id"], "2000", "Facilities", "EXPENSE", "500.00")
    inc = env.budget(src["id"], "4000", "Grants", "INCOME", "7000.00")
    r = env.bm.post("/api/fiscal-years", {"identifier": "2028", "start_date": "2027-07-01", "end_date": "2028-06-30",
                                          "copy_from_fiscal_year_id": src["id"],
                                          "copy_budget_ids": [p["id"], inc["id"]]})  # Facilities removed in wizard
    assert r.status_code == 201
    tree = env.bm.get(f"/api/budgets?fiscal_year_id={r.json()['id']}").json()
    exp = tree["expense"]
    assert [x["display_code"] for x in exp] == ["1000"]
    assert exp[0]["amount"] == "100000.00" and exp[0]["status"] == "DRAFT"
    child = exp[0]["children"][0]
    assert child["label"] == "1000-01 Travel" and child["amount"] == "25000.00" and child["status"] == "DRAFT"
    assert exp[0]["other_amount"] == "75000.00"
    assert tree["income"][0]["label"] == "4000 Grants" and tree["income"][0]["amount"] == "7000.00"
    assert q


def test_ac_fy_008_draft_accepts_transactions(env, base):
    assert base["fy"]["status"] == "DRAFT"
    t = env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "50.00"}])
    assert t["status"] == "ACTIVE"


def test_ac_fy_009_approval(env, base):
    fy = base["fy"]["id"]
    assert env.ru.post(f"/api/fiscal-years/{fy}/approve", {"confirm_irreversible": True}).status_code == 403
    assert env.bu.post(f"/api/fiscal-years/{fy}/approve", {"confirm_irreversible": True}).status_code == 403
    # v1.3 CR-007: an Approval document (or the "no approval document" mark) is required first
    r = env.bm.post(f"/api/fiscal-years/{fy}/approve", {"confirm_irreversible": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "APPROVAL_DOCUMENT_REQUIRED"
    upload_fy_doc(env, fy, "UNSPECIFIED")  # an unspecified document does not count
    assert env.bm.post(f"/api/fiscal-years/{fy}/approve", {"confirm_irreversible": True}).status_code == 409
    upload_fy_doc(env, fy, "APPROVAL")
    assert env.bm.post(f"/api/fiscal-years/{fy}/approve", {"confirm_irreversible": False}).status_code == 409
    r = env.bm.post(f"/api/fiscal-years/{fy}/approve", {"confirm_irreversible": True})
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    tree = env.bm.get(f"/api/budgets?fiscal_year_id={fy}").json()
    for row in tree["expense"] + tree["income"]:
        assert row["status"] == "APPROVED" and row["locked"] and row["state"]["code"] == "APPROVED_LOCKED"
    # irreversible: no un-approve route and status cannot be patched
    assert env.bm.post(f"/api/fiscal-years/{fy}/approve", {"confirm_irreversible": True}).status_code == 409
    assert env.bm.patch(f"/api/fiscal-years/{fy}", {"status": "DRAFT"}).status_code == 422
    assert env.bm.patch(f"/api/fiscal-years/{fy}", {"identifier": "X"}).status_code == 409
    # locked budget cannot be edited
    assert env.bm.patch(f"/api/budgets/{base['exp']['id']}", {"amount": "1.00"}).status_code == 409


def _ready_to_close(env, base):
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "10.00"}],
                clear_date="2026-08-05")
    env.approve(base["fy"]["id"])
    upload_fy_doc(env, base["fy"]["id"])
    return t


def _blockers(env, fy_id):
    return {b["code"] for b in env.bm.get(f"/api/fiscal-years/{fy_id}/closure-check").json()["blockers"]}


def test_ac_fy_010_011_closure_blockers_each_independently(env, base):
    fy = base["fy"]["id"]
    # not approved + no attachment
    assert {"NOT_APPROVED", "NO_AUDIT_SIGNOFF", "APPROVAL_DOCUMENT_MISSING"} <= _blockers(env, fy)
    r = env.bm.post(f"/api/fiscal-years/{fy}/close", {"confirm_reviewed": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CLOSURE_BLOCKED"
    _ready_to_close(env, base)
    assert _blockers(env, fy) == set()
    # unlocked budget blocks
    env.bm.post(f"/api/budgets/{base['exp']['id']}/unlock", {"reason": "amendment"})
    assert _blockers(env, fy) == {"UNLOCKED_BUDGETS"}
    env.bm.post(f"/api/budgets/{base['exp']['id']}/lock")
    assert _blockers(env, fy) == set()
    # uncleared transaction blocks
    u = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "1.00"}])
    assert _blockers(env, fy) == {"UNCLEARED_TRANSACTIONS"}
    env.ru.patch(f"/api/transactions/{u['id']}", {"clear_date": "2026-08-20"})
    assert _blockers(env, fy) == set()
    # unresolved review blocks (cross-FY allocation into this FY from a date outside it)
    t = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "2.00"}],
                date="2027-07-15", clear_date="2027-07-16", confirmations=["NO_FISCAL_YEAR"])
    assert _blockers(env, fy) == {"UNRESOLVED_REVIEWS"}
    rid = t["allocations"][0]["reviews"][0]["id"]
    assert env.bm.post(f"/api/fiscal-year-reviews/{rid}/confirm", {"note": "intentional"}).status_code == 200
    assert _blockers(env, fy) == set()
    # missing Audit Signoff blocks (v1.3 CR-007: other document types don't count)
    atts = env.bm.get(f"/api/attachments?owner_type=fiscal_year&owner_id={fy}").json()
    signoff = [a for a in atts if a["document_type"] == "AUDIT_SIGNOFF"][0]
    env.bm.post(f"/api/attachments/{signoff['id']}/remove")
    assert _blockers(env, fy) == {"NO_AUDIT_SIGNOFF"}
    upload_fy_doc(env, fy, "UNSPECIFIED")
    assert _blockers(env, fy) == {"NO_AUDIT_SIGNOFF"}
    # missing Approval document blocks (unless marked "no approval document", which is a warning)
    approval = [a for a in atts if a["document_type"] == "APPROVAL"][0]
    env.bm.post(f"/api/attachments/{approval['id']}/remove")
    upload_fy_doc(env, fy)
    assert _blockers(env, fy) == {"APPROVAL_DOCUMENT_MISSING"}
    env.bm.post(f"/api/fiscal-years/{fy}/approval-no-attachment", {"no_attachment": True, "reason": "Board votes orally"})
    chk = env.bm.get(f"/api/fiscal-years/{fy}/closure-check").json()
    assert chk["blockers"] == [] and "APPROVAL_NO_ATTACHMENT" in {w["code"] for w in chk["warnings"]}
    # confirmation required
    assert env.bm.post(f"/api/fiscal-years/{fy}/close", {"confirm_reviewed": False}).status_code == 409
    assert env.ru.post(f"/api/fiscal-years/{fy}/close", {"confirm_reviewed": True}).status_code == 403
    r = env.bm.post(f"/api/fiscal-years/{fy}/close", {"confirm_reviewed": True})
    assert r.status_code == 200 and r.json()["status"] == "CLOSED"


def test_ac_fy_010_invalid_allocation_state_blocks(env, base, app):
    """Invalid allocation state (e.g. allocation to a roll-up parent created by legacy data) blocks closure."""
    _ready_to_close(env, base)
    from fmpoc.models import TransactionAllocation
    with app.state.session_factory() as db:
        a = db.query(TransactionAllocation).first()
        a.budget_id = base["exp"]["id"]  # parent roll-up budget: not a valid leaf
        db.commit()
    assert "INVALID_ALLOCATIONS" in _blockers(env, base["fy"]["id"])


def test_ac_fy_012_closure_warnings_budget0_not_warning(env, base):
    fy = base["fy"]["id"]
    # zero-dollar void on Budget 0 only -> no warning
    env.ru.post("/api/transactions", {"bank_account_id": base["acct"]["id"], "transaction_type": "WITHDRAWAL",
                                      "transaction_date": "2026-08-01", "check_number": "1001",
                                      "create_as_void": True, "void_reason": "Damaged check"})
    t = _ready_to_close(env, base)
    env.ru.c.post(f"/api/attachments?owner_type=transaction&owner_id={t['id']}",
                  files={"file": ("receipt.pdf", PDF_BYTES)}, headers={"X-CSRF-Token": env.ru.csrf})
    w = {x["code"] for x in env.bm.get(f"/api/fiscal-years/{fy}/closure-check").json()["warnings"]}
    assert w == set()
    # voided normal transaction + over budget -> warnings
    v = env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "5.00"}])
    env.ru.post(f"/api/transactions/{v['id']}/void", {"reason": "error", "confirm_irreversible": True})
    # v1.4 CR-019: income received above budget is NOT an over-budget warning ...
    env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "106000.00"}], clear_date="2026-08-02")
    w = {x["code"] for x in env.bm.get(f"/api/fiscal-years/{fy}/closure-check").json()["warnings"]}
    assert "VOIDED_TRANSACTIONS" in w and "OVER_BUDGET" not in w
    # ... but spending above an expense budget still is
    env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "100000.00"}], clear_date="2026-08-02")
    w = {x["code"] for x in env.bm.get(f"/api/fiscal-years/{fy}/closure-check").json()["warnings"]}
    assert {"VOIDED_TRANSACTIONS", "OVER_BUDGET"} <= w
    assert _blockers(env, fy) == set()


def test_ac_fy_012_rejected_budget_activity_warning(env, base):
    fy = base["fy"]["id"]
    b = env.budget(fy, "3000", "Temp", "EXPENSE", "10.00")
    leaf = [o for o in env.selectable(fy, "WITHDRAWAL") if o["label"] == "3000 Temp"][0]["id"]
    env.txn(base["acct"]["id"], "WITHDRAWAL", [{"budget_id": leaf, "amount": "3.00"}], clear_date="2026-08-02")
    env.bm.post(f"/api/budgets/{b['id']}/reject", {"reason": "not approved"})
    w = {x["code"] for x in env.bm.get(f"/api/fiscal-years/{fy}/closure-check").json()["warnings"]}
    assert "REJECTED_BUDGET_ACTIVITY" in w


def test_ac_fy_013_closed_immutability(env, base):
    t = _ready_to_close(env, base)
    fy = base["fy"]["id"]
    assert env.bm.post(f"/api/fiscal-years/{fy}/close", {"confirm_reviewed": True}).status_code == 200
    # no new allocations
    r = env.ru.post("/api/transactions", {"bank_account_id": base["acct"]["id"], "transaction_type": "WITHDRAWAL",
                                          "transaction_date": "2026-09-01",
                                          "allocations": [{"budget_id": base["exp_leaf"], "amount": "1.00"}]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "FISCAL_YEAR_CLOSED"
    # existing allocations cannot be edited or voided
    assert env.ru.patch(f"/api/transactions/{t['id']}", {"allocations": [
        {"id": t["allocations"][0]["id"], "budget_id": base["exp_leaf"], "amount": "99.00"}],
        "confirmations": ["CLEARED_EDIT"]}).status_code == 409
    assert env.ru.patch(f"/api/transactions/{t['id']}", {"clear_date": None, "confirmations": ["CLEARED_EDIT"]}).status_code == 409
    assert env.ru.post(f"/api/transactions/{t['id']}/void", {"reason": "x", "confirm_irreversible": True}).status_code == 409
    # budgets immutable, cannot unlock/approve/reopen
    assert env.bm.patch(f"/api/budgets/{base['exp']['id']}", {"name": "x"}).status_code == 409
    assert env.bm.post(f"/api/budgets/{base['exp']['id']}/unlock", {"reason": "x"}).status_code == 409
    assert env.bm.post("/api/budgets", {"fiscal_year_id": fy, "code": "9", "name": "n", "budget_type": "EXPENSE",
                                        "amount": "1"}).status_code == 409
    assert env.bm.post(f"/api/fiscal-years/{fy}/close", {"confirm_reviewed": True}).status_code == 409
    # AC-FY-VIS-009: still visible historically
    assert env.bu.get(f"/api/fiscal-years/{fy}").json()["status"] == "CLOSED"
    assert any(f["id"] == fy for f in env.bu.get("/api/fiscal-years").json())
    assert env.selectable(fy, "WITHDRAWAL") == []
    assert env.ru.get(f"/api/transactions/{t['id']}").json()["closed_fiscal_year_protected"] is True
    # non-financial supporting note is still permitted
    assert env.ru.post(f"/api/transactions/{t['id']}/notes", {"note": "post-close memo"}).status_code == 200


def test_ac_fy_vis_001_to_011_draft_visibility(env):
    fy = env.fy("2029", "2028-07-01", "2029-06-30")
    assert fy["status"] == "DRAFT"
    for c in (env.bm, env.bu, env.ru, env.auditor):
        lst = c.get("/api/fiscal-years").json()
        assert any(f["id"] == fy["id"] and f["label"] == "FY2029 — Draft" for f in lst)  # VIS-001/007/010
        d = c.get(f"/api/fiscal-years/{fy['id']}")
        assert d.status_code == 200 and d.json()["display_name"] == "FY2029"  # VIS-002/011
        assert c.get(f"/api/budgets?fiscal_year_id={fy['id']}").status_code == 200  # VIS-003
    b = env.budget(fy["id"], "1000", "Ops", "EXPENSE", "10.00")  # VIS-004/005
    assert b["status"] == "DRAFT"
    acct = env.account()
    opts = env.selectable(fy["id"], "WITHDRAWAL")
    assert opts[0]["fiscal_year_label"] == "FY2029 — Draft"
    t = env.txn(acct["id"], "WITHDRAWAL", [{"budget_id": opts[0]["id"], "amount": "3.00"}], date="2028-08-01")  # VIS-006
    assert t["allocations"][0]["budget"]["fiscal_year"]["display_name"] == "FY2029"
    nat = env.ru.get("/api/fiscal-years/natural?date=2028-08-01").json()
    assert nat["default_fiscal_year_id"] == fy["id"]
    # VIS-008: approval preserves identity and route
    env.approve(fy["id"])
    d = env.bu.get(f"/api/fiscal-years/{fy['id']}").json()
    assert d["id"] == fy["id"] and d["display_name"] == "FY2029" and d["label"] == "FY2029 — Approved"
    dash = env.bu.get("/api/dashboard").json()
    assert any(f["id"] == fy["id"] for f in dash["fiscal_years"])


def test_fy_validation(env):
    bad = [{"identifier": "20 28", "start_date": "2027-07-01", "end_date": "2028-06-30"},
           {"identifier": "2028", "start_date": "2028-07-01", "end_date": "2027-06-30"},
           {"identifier": "2028", "start_date": "07/01/2027", "end_date": "2028-06-30"},
           {"identifier": "<script>", "start_date": "2027-07-01", "end_date": "2028-06-30"}]
    for b in bad:
        assert env.bm.post("/api/fiscal-years", b).status_code == 422, b
    env.fy("2028", "2027-07-01", "2028-06-30")
    r = env.bm.post("/api/fiscal-years", {"identifier": "2028", "start_date": "2028-07-01", "end_date": "2029-06-30"})
    assert r.status_code == 409


def test_fy_start_balance_derived(env, base):
    """BR-043: FY starting balance = balance at end of the prior day (not a stored transaction)."""
    env.txn(base["acct"]["id"], "DEPOSIT", [{"budget_id": base["inc_leaf"], "amount": "250.00"}], date="2026-06-15",
            confirmations=["NO_FISCAL_YEAR"])
    reg = env.ru.get(f"/api/register?bank_account_id={base['acct']['id']}&fiscal_year_id={base['fy']['id']}").json()
    assert reg["starting_balance"] == "1250.00"
    assert dt.date.fromisoformat(reg["date_from"]) == dt.date(2026, 7, 1)
