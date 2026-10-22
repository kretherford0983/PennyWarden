"""2.1.0 (#247): fold marks on cover letters - four small unlabeled ticks at the fold lines (11/3 and 22/3 in from the
top) on the first sheet, front or back; set on the template, as the user's own default, or for one letter."""
from __future__ import annotations

import io

import pytest
from pypdf import PdfReader
from pypdf.generic import ContentStream

from tests.test_v200_checks import PRESET, enable, make_signer
from tests.test_v200_letters import setup_docs, vendor

PT = 72.0
FOLDS = ((11 - 11 / 3) * PT, (11 - 22 / 3) * PT)


def segments(reader: PdfReader, i: int) -> list[tuple[float, float, float, float]]:
    """Straight lines (m ... l) drawn on page i, in page coordinates."""
    page = reader.pages[i]
    if page.get_contents() is None:
        return []
    out, cur = [], None
    for operands, op in ContentStream(page.get_contents(), reader).operations:
        if op == b"m":
            cur = (float(operands[0]), float(operands[1]))
        elif op == b"l" and cur is not None:
            out.append((cur[0], cur[1], float(operands[0]), float(operands[1])))
            cur = None
    return out


def ticks(reader: PdfReader, i: int) -> list[tuple[float, float, float, float]]:
    return sorted(s for s in segments(reader, i) if s[1] == s[3] and any(abs(s[1] - y) < 0.01 for y in FOLDS)
                  and (s[0] < 0.6 * PT or s[2] > 7.9 * PT))


def pdf(content: bytes) -> PdfReader:
    return PdfReader(io.BytesIO(content))


@pytest.fixture
def letter_case(env, base):
    enable(env)
    style = env.admin.post("/api/checks/styles", {"preset_key": PRESET}).json()
    letter, _envelope = setup_docs(env)
    make_signer(env, "Jordan Sample", "Treasurer")
    acct = base["acct"]["id"]
    env.ru.put(f"/api/checks/accounts/{acct}", {"check_style_id": style["id"]})
    t = env.txn(acct, "WITHDRAWAL", [{"budget_id": base["exp_leaf"], "amount": "200.00", "invoice_number": "158092",
                                      "invoice_date": "2026-08-29"}], entity_id=vendor(env)["id"])
    return {"letter": letter, "tid": t["id"]}


def set_cfg(env, letter, **kw):
    cfg = dict(letter["config"], **kw)
    r = env.admin.put(f"/api/checks/documents/{letter['id']}", {"name": letter["name"], "config": cfg})
    return r


def print_letter(env, c, client=None, **kw):
    r = (client or env.ru).post(f"/api/checks/transactions/{c['tid']}/letter", {"document_id": c["letter"]["id"], **kw})
    assert r.status_code == 200, r.text
    return pdf(r.content)


def test_off_by_default_and_for_existing_templates(env, letter_case):
    assert letter_case["letter"]["config"]["fold_marks"] == "NONE"
    r = print_letter(env, letter_case)
    assert len(r.pages) == 1 and ticks(r, 0) == []


def test_window_templates_start_with_marks_on_the_front(env, base):
    enable(env)
    draft = env.admin.get("/api/checks/documents/draft?kind=LETTER&preset=WINDOW").json()
    assert draft["config"]["fold_marks"] == "FRONT"
    made = env.admin.post("/api/checks/documents", {"kind": "LETTER", "preset": "WINDOW"}).json()
    assert made["config"]["fold_marks"] == "FRONT"
    plain = env.admin.get("/api/checks/documents/draft?kind=LETTER").json()
    assert plain["config"]["fold_marks"] == "NONE"


def test_front_four_small_ticks_on_the_first_page(env, letter_case):
    assert set_cfg(env, letter_case["letter"], fold_marks="FRONT").status_code == 200
    r = print_letter(env, letter_case)
    tk = ticks(r, 0)
    assert len(tk) == 4
    left = [s for s in tk if s[0] < 1 * PT]
    assert all(abs(s[0] - 0.25 * PT) < 0.01 and abs(s[2] - s[0] - 0.15 * PT) < 0.01 for s in left)   # defaults
    right = [s for s in tk if s[0] > 4 * PT]
    assert all(abs(s[2] - 8.25 * PT) < 0.01 for s in right)
    assert "fold" not in (r.pages[0].extract_text() or "").lower()                              # no label


def test_address_page_letter_marks_the_address_page_only(env, letter_case):
    set_cfg(env, letter_case["letter"], fold_marks="FRONT", window="ADDRESS_PAGE")
    r = print_letter(env, letter_case)
    assert len(r.pages) == 2 and len(ticks(r, 0)) == 4 and ticks(r, 1) == []


def test_back_a_back_page_after_every_page(env, letter_case):
    set_cfg(env, letter_case["letter"], fold_marks="BACK", window="ADDRESS_PAGE")
    r = print_letter(env, letter_case)
    assert len(r.pages) == 4                                     # address page, its back, letter, blank back
    assert ticks(r, 0) == [] and len(ticks(r, 1)) == 4 and ticks(r, 2) == [] and segments(r, 3) == []
    assert "Total Payment Enclosed" in (r.pages[2].extract_text() or "")


def test_tuning_and_limits(env, letter_case):
    ok = set_cfg(env, letter_case["letter"], fold_marks="FRONT", fold_length=0.3, fold_edge=0.4,
                 fold_weight="MEDIUM", fold_shade="DARK")
    assert ok.status_code == 200, ok.text
    tk = ticks(print_letter(env, letter_case), 0)
    left = [s for s in tk if s[0] < 1 * PT]
    assert all(abs(s[0] - 0.4 * PT) < 0.01 and abs(s[2] - 0.7 * PT) < 0.01 for s in left)
    for bad in ({"fold_length": 0.6}, {"fold_length": 0.05}, {"fold_edge": 0.55}, {"fold_weight": "THICK"},
                {"fold_shade": "BLACK"}, {"fold_marks": "BOTH"}):
        assert set_cfg(env, letter_case["letter"], **bad).status_code == 422, bad
    # the test print and the preview show the ticks too (the test print keeps its labeled marks for windows)
    tp = pdf(env.admin.post(f"/api/checks/documents/{letter_case['letter']['id']}/test-print", {}).content)
    assert len(ticks(tp, 0)) >= 4
    ev = env.admin.get("/api/audit-events?action=CHECK_DOCUMENT_UPDATED").json()["items"]
    assert any("fold_marks" in str(e.get("after")) and "FRONT" in str(e.get("after")) for e in ev)   # audited


def test_user_default_and_per_letter_choice(env, letter_case):
    other = env.user("regtwo", "FINANCIAL", ["REGISTER_USER"])
    assert env.ru.get("/api/checks/my-printer/letter").json() == {"fold_marks": "TEMPLATE"}
    assert env.ru.put("/api/checks/my-printer/letter", {"fold_marks": "BACK"}).json() == {"fold_marks": "BACK"}
    docs = env.ru.get(f"/api/checks/transactions/{letter_case['tid']}/documents").json()
    assert docs["my_letter_fold"] == "BACK" and docs["letters"][0]["fold_default"] == "BACK"
    assert docs["letters"][0]["fold_marks"] == "NONE"                               # the template is unchanged
    r = print_letter(env, letter_case)
    assert len(r.pages) == 2 and len(ticks(r, 1)) == 4                              # this user's default: the back
    r = print_letter(env, letter_case, client=other)
    assert len(r.pages) == 1 and ticks(r, 0) == []                                  # another user: the template
    r = print_letter(env, letter_case, fold_marks="FRONT")                          # this letter only
    assert len(r.pages) == 1 and len(ticks(r, 0)) == 4
    assert env.ru.get("/api/checks/my-printer/letter").json() == {"fold_marks": "BACK"}   # nothing else changed
    ev = env.auditor.get("/api/audit-events?action=CHECK_LETTER_PRINTED").json()["items"]
    assert [e["after"]["fold_marks"] for e in ev][:3] == ["FRONT", "NONE", "BACK"]
    ps = env.admin.get("/api/audit-events?action=CHECK_PRINTER_SETTINGS").json()["items"]
    assert any((e.get("after") or {}).get("fold_marks") == "BACK" for e in ps)
    assert env.ru.put("/api/checks/my-printer/letter", {"fold_marks": "TEMPLATE"}).json() == {"fold_marks": "TEMPLATE"}
    assert env.ru.put("/api/checks/my-printer/letter", {"fold_marks": "SIDEWAYS"}).status_code == 422


def test_access(env, letter_case):
    for c in (env.bm, env.bu, env.auditor):
        assert c.get("/api/checks/my-printer/letter").status_code == 403
        assert c.put("/api/checks/my-printer/letter", {"fold_marks": "FRONT"}).status_code == 403
    assert env.ru.put(f"/api/checks/documents/{letter_case['letter']['id']}",
                      {"name": "x", "config": letter_case["letter"]["config"]}).status_code == 403
