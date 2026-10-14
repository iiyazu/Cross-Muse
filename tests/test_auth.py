"""Bearer JWTs (auth.py): what the hub accepts, what it refuses, and the move from pre-JWT tokens."""
import json

import jwt

from xmuse import auth, db
from xmuse.server import Hub

WHOAMI = "/v1/tools/xmuse_whoami"


def test_member_and_admin_tokens_are_signed_jwts(make):
    h = make()
    c = auth.claims(h.hub.key, h.token("claude-1"))
    assert (c["iss"], c["sub"], c["kind"]) == ("xmuse", "claude-1", "member") and c["jti"]
    assert auth.claims(h.hub.key, h.token("human"))["kind"] == "admin"
    assert "result" in h.post(WHOAMI, {"args": {}}, h.token("claude-1"))
    assert (h.state / "tokens" / "_signing.key").stat().st_mode & 0o777 == 0o600


def test_tokens_the_hub_did_not_issue_are_refused(make):
    h = make()
    other = jwt.encode({"iss": "xmuse", "sub": "claude-1", "kind": "member", "jti": "x"},
                       b"another key of 32 bytes or more!", algorithm="HS256")
    assert h.post(WHOAMI, {"args": {}}, other)["status"] == 401
    # signed with the right key, but not the token on record (re-issued, or never issued)
    stale = auth.mint(h.hub.key, "claude-1", "member")
    assert h.post(WHOAMI, {"args": {}}, stale)["status"] == 401
    assert h.post("/v1/admin/runs", {}, auth.mint(h.hub.key, "human", "admin"))["status"] == 401
    # alg=none and a wrong issuer
    none = jwt.encode({"iss": "xmuse", "sub": "claude-1", "kind": "member", "jti": "x"}, None, algorithm="none")
    assert h.post(WHOAMI, {"args": {}}, none)["status"] == 401
    wrong = jwt.encode({"iss": "elsewhere", "sub": "claude-1", "kind": "member", "jti": "x"}, h.hub.key,
                       algorithm="HS256")
    assert h.post(WHOAMI, {"args": {}}, wrong)["status"] == 401


def test_a_token_speaks_only_for_its_own_subject_and_kind(make):
    h = make()
    tok = h.token("claude-1")
    with db.tx(h.conn()) as c:  # a row whose digest matches but whose id is not the token's subject
        c.execute("update agents set id='mallory' where id='claude-1'")
    assert h.post(WHOAMI, {"args": {}}, tok)["status"] == 401


def test_a_removed_members_token_is_refused(make):
    h = make()
    tok = h.token("claude-1")
    with db.tx(h.conn()) as c:
        c.execute("update agents set removed=1 where id='claude-1'")
    assert h.post(WHOAMI, {"args": {}}, tok)["status"] == 401


def test_risk_answers_for_the_members_own_directory(make):
    h = make()
    ask = lambda **b: h.post("/v1/risk", b, h.token("claude-1"))  # noqa: E731
    assert ask(command="pytest -q", cwd=str(h.ws))["result"]["why"] is None
    assert "git push" in ask(command="cd sub && git push")["result"]["why"]
    assert "outside" in ask(command="rm -rf build", cwd="/")["result"]["why"]
    assert ask(paths=[str(h.ws / "a.py")])["result"]["why"] is None
    assert "outside" in ask(paths=["/etc/hosts"])["result"]["why"]
    assert ask(paths="x")["error"]["code"] == "bad_request"
    assert h.post("/v1/risk", {"command": "ls"}, "nope")["status"] == 401


def test_pre_jwt_tokens_are_reissued_at_start(make):
    h = make()
    h.hub.shutdown()
    old = "xmt_legacy"
    (h.state / "tokens" / "claude-1").write_text(old, encoding="utf-8")
    (h.state / "tokens" / "_admin").write_text("xmt_admin", encoding="utf-8")
    with db.tx(h.conn()) as c:
        c.execute("update agents set token_digest=? where id='claude-1'", (auth.digest(old),))
    h.hub = Hub(h.state, human_check=False)
    h.hub.start()
    new = h.token("claude-1")
    assert new != old and auth.claims(h.hub.key, new)["sub"] == "claude-1"
    assert h.post(WHOAMI, {"args": {}}, old)["status"] == 401
    assert "result" in h.post(WHOAMI, {"args": {}}, new)
    assert h.post("/v1/admin/runs", {}, h.token("human"))["error"]["code"] == "invalid_arguments"  # past auth
    assert json.loads((h.state / "hub.json").read_text())["port"] == h.hub.api.port
