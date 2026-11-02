"""2.3.0 build 11 (#375): the Reports screen remembers each user's last 5 runs and each report's last options,
server-side (so they follow the user across devices). Parameters only, never report output."""


def test_recent_runs_and_last_options(env, base):
    bm = env.bm
    p = bm.get("/api/me/report-preferences").json()
    assert p["recent"] == [] and p["last"] == {} and p["recent_max"] == 5 and "quarterly" in p["reports"]
    fy = str(base["fy"]["id"])
    r = bm.post("/api/me/report-runs", {"report": "quarterly", "params": {"fiscal_year_id": fy, "period": "Q1"},
                                         "label": "FY2027 · Q1"})
    assert r.status_code == 200, r.text
    for i in range(6):
        bm.post("/api/me/report-runs", {"report": "audit", "params": {"fiscal_year_id": fy, "bank_account_id": str(i)}})
    p = bm.get("/api/me/report-preferences").json()
    assert len(p["recent"]) == 5 and all(x["report"] == "audit" for x in p["recent"])     # newest first, 5 at most
    assert p["recent"][0]["params"]["bank_account_id"] == "5"
    assert p["last"]["quarterly"] == {"fiscal_year_id": fy, "period": "Q1"}               # remembered per report
    assert p["last"]["audit"]["bank_account_id"] == "5"
    # the same run again moves up instead of repeating
    bm.post("/api/me/report-runs", {"report": "audit", "params": {"fiscal_year_id": fy, "bank_account_id": "3"}})
    p = bm.get("/api/me/report-preferences").json()
    assert [x["params"]["bank_account_id"] for x in p["recent"]] == ["3", "5", "4", "2", "1"]
    # per user: another user starts empty; it follows the user to another session (device)
    assert env.auditor.get("/api/me/report-preferences").json()["recent"] == []
    from conftest import Api
    other = Api(env.app)
    assert other.login("budgetmgr").status_code == 200
    assert other.get("/api/me/report-preferences").json()["last"]["quarterly"]["period"] == "Q1"


def test_validation(env, base):
    bm = env.bm
    assert bm.post("/api/me/report-runs", {"report": "nonsense"}).status_code == 422
    assert bm.post("/api/me/report-runs", {"report": "audit", "params": {"x": "y" * 201}}).status_code == 422
    assert bm.post("/api/me/report-runs", {"report": "audit", "params": {"x": {"nested": 1}}}).status_code == 422
    assert bm.post("/api/me/report-runs", {"report": "audit", "params": {f"k{i}": 1 for i in range(17)}}).status_code == 422
    assert bm.post("/api/me/report-runs", {"report": "audit", "extra": 1}).status_code == 422
    assert bm.post("/api/me/report-runs", {"report": "fundraising-fy", "params": {"ids": ["1", "2"], "targeted": False}}).status_code == 200
