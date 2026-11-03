"""2.3.0 build 12 (#376): Report settings - the Reports catalog's grouping scheme and categories (workspace-wide,
Administrators, audited, display only)."""
from fmpoc.services import report_grouping as rg
from fmpoc.services.report_prefs import REPORT_IDS

URL = "/api/system/report-settings"


def test_defaults_cover_every_report_once():
    for k, cats in rg.DEFAULTS.items():
        placed = [x for c in cats for x in c["reports"]]
        assert sorted(placed) == sorted(REPORT_IDS), k


def test_catalog_default_is_purpose_and_admin_switches_scheme(env, base):
    g = env.bm.get("/api/reports/grouping").json()
    assert g["scheme"] == "PURPOSE" and not g["customized"]
    assert [c["id"] for c in g["categories"]] == ["share", "audit", "analyze", "plan", "fundraisers", "invoices"]  # 2.4.0 (#255): Invoices
    v = env.admin.put(URL, {"scheme": "AUDIENCE"}).json()
    assert v["scheme"] == "AUDIENCE"
    g = env.auditor.get("/api/reports/grouping").json()
    assert g["scheme"] == "AUDIENCE" and g["categories"][0]["name"] == "Board & members"


def test_customize_validate_reset_and_audit(env, base):
    v = env.admin.get(URL).json()
    subj = next(s for s in v["schemes"] if s["id"] == "SUBJECT")["categories"]
    # rename, reorder, add a category, move a report into it, remove "System"
    cats = [c for c in subj if c["id"] != "system"]
    cats[0]["name"] = "The Fiscal Year"
    cats.reverse()
    cats.append({"name": "Board packet", "reports": []})
    cats[0]["reports"].remove("fundraising-fy")
    cats[-1]["reports"].append("fundraising-fy")
    r = env.admin.put(URL, {"scheme": "SUBJECT", "categories": cats})
    assert r.status_code == 200, r.text
    s = next(x for x in r.json()["schemes"] if x["id"] == "SUBJECT")
    assert s["customized"] and s["categories"][-1] == {"id": "board-packet", "name": "Board packet", "reports": ["fundraising-fy"]}
    assert s["categories"][-2]["name"] == "The Fiscal Year"
    g = env.bm.get("/api/reports/grouping").json()
    assert g["scheme"] == "SUBJECT" and g["customized"] and g["categories"][0]["id"] == "fundraisers"
    # every report exactly once; names unique and not empty
    bad = [dict(c) for c in cats]
    bad[-1] = {**bad[-1], "reports": []}
    r = env.admin.put(URL, {"scheme": "SUBJECT", "categories": bad})
    assert r.status_code == 422 and "needs a category" in r.text
    dup = [dict(c) for c in cats] + [{"name": "x", "reports": ["audit"]}]
    assert env.admin.put(URL, {"scheme": "SUBJECT", "categories": dup}).status_code == 422
    same = [dict(c) for c in cats]
    same[1] = {**same[1], "name": same[0]["name"]}
    assert env.admin.put(URL, {"scheme": "SUBJECT", "categories": same}).status_code == 422
    assert env.admin.put(URL, {"scheme": "SUBJECT", "categories": [{"name": " ", "reports": list(REPORT_IDS)}]}).status_code == 422
    assert env.admin.put(URL, {"scheme": "SUBJECT", "categories": [{"name": "All", "reports": ["nope"]}]}).status_code == 422
    assert env.admin.put(URL, {"scheme": "COLOR"}).status_code == 422
    # each scheme keeps its own customization; reset puts one back
    env.admin.put(URL, {"scheme": "PURPOSE"})
    v = env.admin.get(URL).json()
    assert next(x for x in v["schemes"] if x["id"] == "SUBJECT")["customized"]
    v = env.admin.post(f"{URL}/reset", {"scheme": "SUBJECT"}).json()
    assert not next(x for x in v["schemes"] if x["id"] == "SUBJECT")["customized"]
    acts = {e["action"] for e in env.auditor.get("/api/audit-events?object_type=report_grouping").json()["items"]}
    assert {"REPORT_GROUPING_UPDATED", "REPORT_GROUPING_RESET"} <= acts


def test_administrators_only_and_display_only(env, base):
    for c in (env.bm, env.bu, env.ru, env.auditor):
        assert c.get(URL).status_code == 403
        assert c.put(URL, {"scheme": "SUBJECT"}).status_code == 403
        assert c.post(f"{URL}/reset", {"scheme": "SUBJECT"}).status_code == 403
    # grouping never grants access: moving Budget Review into a category doesn't let a Register User run it
    cats = [{"name": "Everything", "reports": list(REPORT_IDS)}]
    assert env.admin.put(URL, {"scheme": "PURPOSE", "categories": cats}).status_code == 200
    assert env.ru.get(f"/api/reports/budget-review?fiscal_year_id={base['fy']['id']}&format=json").status_code == 403
