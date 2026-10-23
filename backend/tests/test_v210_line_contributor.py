"""2.1.0 (#303): "Different contributor on reports" for the part of a line in no bucket - shown under "Other (not in
a bucket)" and in the plain line list of a fundraiser without buckets, like the per-bucket override; bucket parts keep
their own. Audited with the line, removed when the line is excluded."""
from __future__ import annotations

from test_v161_fundraiser_manage import gala, put_line  # noqa: F401  (fixture)
from test_v210_fundraiser_deck import all_text, deck
from test_v210_fundraiser_summary import buckets, get, pdf_text, url  # noqa: F401  (fixture)


def line_of(env, g, desc):
    return next(x for x in env.bu.get(url(g)).json()["lines"] if x["description"] == desc)


def test_other_line_shows_the_override(env, buckets):
    assert "Unrelated donation" in pdf_text(get(env, buckets).content)
    r = put_line(env.ru, buckets, "Unrelated donation", {"contributor_override": "Anonymous donors"})
    assert r.status_code == 200, r.text
    assert line_of(env, buckets, "Unrelated donation")["contributor_override"] == "Anonymous donors"
    t = pdf_text(get(env, buckets).content)
    assert "Anonymous donors" in t
    assert "Anonymous donors" in all_text(deck(env, buckets).content)
    # names off: its own "Contributor N", never the text
    off = pdf_text(get(env, buckets, names=False).content)
    assert "Anonymous donors" not in off and "Contributor" in off
    # cleared by saving without it
    put_line(env.ru, buckets, "Unrelated donation", {})
    assert line_of(env, buckets, "Unrelated donation")["contributor_override"] is None


def test_bucket_part_and_other_part_each_keep_their_own(env, buckets):
    ent = env.entity("Jordan Benefactor")
    env.txn(buckets["base"]["acct"]["id"], "DEPOSIT", [{"budget_id": buckets["base"]["inc_leaf"], "amount": "300.00",
                                                       "description": "Sponsor table"}], date="2026-09-15", entity_id=ent["id"])
    line = line_of(env, buckets, "Sponsor table")
    r = env.ru.put(url(buckets, f"/lines/{line['allocation_id']}"),
                   {"buckets": [{"bucket_id": buckets["ids"]["Raffle"], "amount": "100.00", "contributor_override": "Cash"}],
                    "contributor_override": "Table sponsors"})
    assert r.status_code == 200, r.text
    got = line_of(env, buckets, "Sponsor table")
    assert got["buckets"][0]["contributor_override"] == "Cash" and got["contributor_override"] == "Table sponsors"
    assert got["unassigned"] == "200.00"
    t = pdf_text(get(env, buckets).content)
    assert "Cash" in t and "Table sponsors" in t and "Jordan Benefactor" not in t


def test_fundraiser_without_buckets_plain_list(env, gala):
    assert put_line(env.ru, gala, "Gala takings", {"contributor_override": "Ticket sales at the door"}).status_code == 200
    t = pdf_text(get(env, gala, plain_lines=True).content)
    assert "Ticket sales at the door" in t


def test_audited_and_removed_when_excluded(env, gala):
    put_line(env.ru, gala, "Unrelated donation", {"contributor_override": "Anonymous donors"})
    ev = env.auditor.get("/api/audit-events?action=FUNDRAISER_LINE_UPDATED").json()["items"]
    assert any((e.get("after") or {}).get("contributor_override") == "Anonymous donors"
               and (e.get("before") or {}).get("contributor_override") is None for e in ev)
    r = put_line(env.ru, gala, "Unrelated donation", {"excluded": True, "exclusion_reason": "Not part of the gala"})
    assert r.status_code == 200, r.text
    assert line_of(env, gala, "Unrelated donation")["contributor_override"] is None
    put_line(env.ru, gala, "Unrelated donation", {})
    assert line_of(env, gala, "Unrelated donation")["contributor_override"] is None       # gone, not hidden


def test_access_and_delete_protection(env, gala):
    for c in (env.bu, env.auditor, env.admin):
        assert put_line(c, gala, "Gala takings", {"contributor_override": "X"}).status_code == 403
    assert put_line(env.ru, gala, "Gala takings", {"contributor_override": "Cash"}).status_code == 200
    r = env.bm.delete(url(gala))
    assert r.status_code == 409 and r.json()["error"]["code"] == "FUNDRAISER_IN_USE"
    assert put_line(env.ru, gala, "Gala takings", {"contributor_override": "x" * 121}).status_code == 422
