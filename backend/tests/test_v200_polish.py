"""2.0.0 build 3 polish (#174): the setup preview and test print use the style's default memo with sample data."""
import io

from pypdf import PdfReader

from tests.test_v200_checks import PRESET, enable


def test_default_memo_in_sample_preview_and_test_print(env, base):
    enable(env)
    st = env.admin.post("/api/checks/styles", {"preset_key": PRESET}).json()
    cfg = st["config"]
    cfg["memo_default"] = "FBA {budget_code}, INVOICE {INVOICE}"     # unsaved: only sent with the request
    out = env.admin.post("/api/checks/sample-layout", {"config": cfg, "sample": "NORMAL"}).json()
    assert out["memo"]["text"] == "FBA 51, INVOICE 12345"
    pdf = env.admin.post(f"/api/checks/styles/{st['id']}/test-print",
                         {"feed_key": "sheet_top", "config": cfg}).content
    assert "FBA 51, INVOICE 12345" in PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    # an empty default memo prints no memo; an invalid one is refused with the suggestion
    cfg["memo_default"] = ""
    assert env.admin.post("/api/checks/sample-layout", {"config": cfg}).json()["memo"]["text"] == ""
    cfg["memo_default"] = "{dtae}"
    r = env.admin.post("/api/checks/sample-layout", {"config": cfg})
    assert r.status_code == 422 and r.json()["error"]["suggestion"] == "DATE"
    # the long sample fills split-style values
    cfg["memo_default"] = "{BUDGET_CODE}, INVOICE {INVOICE}"
    long = env.admin.post("/api/checks/sample-layout", {"config": cfg, "sample": "LONG"}).json()
    assert long["memo"]["text"].startswith("51-02 AND OTHERS, INVOICE INV-2026-000123456")
    assert long["payee"]["fits"] is False
