"""2.2.0 (#343): the password requirements come from the server (one source of truth for the checklist beside every
new-password field). The policy checks themselves (`policy_errors`) are unchanged."""
from fmpoc.security.passwords import MAX_LENGTH, MIN_LENGTH, policy_errors, policy_requirements


def test_policy_endpoint_without_session(anon):
    r = anon.get("/api/auth/password-policy")
    assert r.status_code == 200
    body = r.json()
    assert body["min_length"] == MIN_LENGTH == 12 and body["max_length"] == MAX_LENGTH == 128
    ids = [x["id"] for x in body["requirements"]]
    assert ids == ["length", "letter_digit", "not_username", "differs_current", "differs_temporary", "confirm_matches"]
    texts = {x["id"]: x["text"] for x in body["requirements"]}
    assert "12" in texts["length"] and "128" in texts["length"]
    temp = next(x for x in body["requirements"] if x["id"] == "differs_temporary")
    assert temp["server_only"] is True and temp["applies"] == "temporary"
    assert body == policy_requirements()


def test_policy_endpoint_signed_in_and_no_user_data(env):
    body = env.admin.get("/api/auth/password-policy").json()
    assert "admin" not in str(body).lower()


def test_policy_errors_unchanged():
    assert policy_errors("short1") == ["Password must be at least 12 characters."]
    assert policy_errors("a" * 129 + "1") == ["Password must be at most 128 characters."]
    assert policy_errors("abcdefghijklmn") == ["Password must contain at least one letter and one digit."]
    assert policy_errors("treasurer2026", "Treasurer2026") == ["Password must not equal the username."]
    assert policy_errors("correct horse 42") == []
