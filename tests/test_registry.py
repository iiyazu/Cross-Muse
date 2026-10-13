"""Local join (contract v0.1 section 8.1, T0): the machine registry (hubs.json), the sidebar key, POST /v1/join without
a code, GET/POST /v1/rooms with the key, the member_add / member_edit acts, and the shell policy refusing the key."""
import json
import os
import stat
import subprocess
import sys
import threading

import pytest

from conftest import sidebar_key
from xmuse import db
from test_init_cli import run, ws  # noqa: F401  (ws: fixture)
from test_room import act, call, open_room, view
from test_trust import OC
from xmuse import config, registry, room as rooms
from xmuse.adapters.opencode import auto_decision, shell_auto_ok

NT = os.name == "nt"


def entry(room_id, pid=None, **kw):
    return {"room_id": room_id, "name": room_id, "dir": "/x/" + room_id, "url": "http://127.0.0.1:1", "host": None,
            "pid": os.getpid() if pid is None else pid, "started_at": 1.0, **kw}


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def join(h, key="", **body):
    return call(h, "POST", "/v1/join", {"dir": str(h.ws), "vendor": "claude", "session_id": "S-j", **body},
                key=h.key() if key == "" else key)


# ---- the registry ----------------------------------------------------------------------------------------------

def test_registry_dir_follows_the_override_then_the_platform(monkeypatch, tmp_path):
    assert registry.directory() == tmp_path / "registry"  # conftest: never the real one
    monkeypatch.delenv("XMUSE_REGISTRY_DIR")
    if NT:
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lad"))
        assert registry.directory() == tmp_path / "lad" / "xmuse"
    else:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
        assert registry.directory() == tmp_path / "xdg" / "xmuse"
        monkeypatch.delenv("XDG_STATE_HOME")
        monkeypatch.setenv("HOME", str(tmp_path / "h"))
        assert registry.directory() == tmp_path / "h" / ".local" / "state" / "xmuse"


def test_register_updates_by_room_and_unregister_removes_only_its_own():
    assert registry.hubs() == []
    registry.register(entry("r-a", name="first"))
    registry.register(entry("r-b"))
    registry.register(entry("r-a", name="second", host="lead"))  # same room: replaced, not duplicated
    got = {e["room_id"]: e for e in registry.hubs()}
    assert set(got) == {"r-a", "r-b"} and got["r-a"]["name"] == "second" and got["r-a"]["host"] == "lead"
    assert set(got["r-a"]) == {"room_id", "name", "dir", "url", "host", "pid", "started_at"}
    registry.unregister("r-a", pid=os.getpid() + 12345)  # another hub's entry for the room stays
    assert len(registry.hubs()) == 2
    registry.unregister("r-a")
    assert [e["room_id"] for e in registry.hubs()] == ["r-b"]
    assert sorted(p.name for p in registry.directory().iterdir()) == ["hubs.json"]  # no temp or lock files left


def test_install_record_says_how_to_start_a_hub(monkeypatch):
    """The panel starts a hub after a reboot from this record: the interpreter and the WSL distro; kept, not churned."""
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-X")
    monkeypatch.setenv("PATH", "/opt/agents/bin" + os.pathsep + os.environ["PATH"])
    registry.write_install()
    got = json.loads(registry.install_path().read_text(encoding="utf-8"))
    assert got == {"python": sys.executable, "distro": "Ubuntu-X", "os": os.name, "path": os.environ["PATH"]}
    before = registry.install_path().stat().st_mtime_ns
    registry.write_install()  # unchanged: not rewritten
    assert registry.install_path().stat().st_mtime_ns == before
    assert sorted(p.name for p in registry.directory().iterdir()) == ["install.json"]


def test_dead_pids_are_dropped_on_read_and_on_write():
    gone = dead_pid()
    registry.hubs_path().parent.mkdir(parents=True, exist_ok=True)
    registry.hubs_path().write_text(json.dumps({"hubs": [entry("r-dead", gone), entry("r-live")]}), encoding="utf-8")
    assert [e["room_id"] for e in registry.hubs()] == ["r-live"]
    assert "r-dead" in registry.hubs_path().read_text(encoding="utf-8")  # reading does not rewrite
    registry.register(entry("r-new"))
    assert "r-dead" not in registry.hubs_path().read_text(encoding="utf-8")
    registry.hubs_path().write_text("{not json", encoding="utf-8")  # a broken file is an empty registry
    assert registry.hubs() == []
    registry.register(entry("r-after"))
    assert [e["room_id"] for e in registry.hubs()] == ["r-after"]


def test_concurrent_writers_lose_nothing():
    errors = []

    def go(i):
        try:
            registry.register(entry(f"r-{i}"))
            registry.register(entry(f"r-{i}", name="again"))
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    ts = [threading.Thread(target=go, args=(i,)) for i in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    assert not errors
    assert sorted(e["room_id"] for e in registry.hubs()) == sorted(f"r-{i}" for i in range(12))
    assert sorted(p.name for p in registry.directory().iterdir()) == ["hubs.json"]


def test_stale_lock_of_a_crashed_writer_is_broken(monkeypatch):
    registry.directory().mkdir(parents=True, exist_ok=True)
    lock = registry.directory() / "hubs.lock"
    lock.write_text("", encoding="utf-8")
    os.utime(lock, (1, 1))  # very old
    registry.register(entry("r-a"))
    assert [e["room_id"] for e in registry.hubs()] == ["r-a"] and not lock.exists()


# ---- the sidebar key --------------------------------------------------------------------------------------------

def test_key_is_generated_once_as_hex_with_owner_only_access():
    assert registry.read_key() is None and not registry.check_key("anything")
    k = registry.ensure_key()
    assert len(k) == 64 and int(k, 16) >= 0 and k == k.lower()
    assert registry.key_path().read_text(encoding="utf-8").strip() == k
    assert registry.ensure_key() == k == sidebar_key()  # the second start keeps it
    if not NT:
        assert stat.S_IMODE(registry.key_path().stat().st_mode) == 0o600
    assert sorted(p.name for p in registry.directory().iterdir()) == ["sidebar.key"]


def test_concurrent_first_starts_agree_on_one_key():
    out = []
    ts = [threading.Thread(target=lambda: out.append(registry.ensure_key())) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    assert len(out) == 8 and len(set(out)) == 1 and out[0] == registry.read_key()


def test_check_key_is_exact_and_constant_time(monkeypatch):
    k = registry.ensure_key()
    calls = []
    real = registry.hmac.compare_digest
    monkeypatch.setattr(registry.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    assert registry.check_key(k) and registry.check_key(" " + k + "\n")
    assert not registry.check_key(k[:-1]) and not registry.check_key(k + "0") and not registry.check_key(k.upper())
    assert not registry.check_key("") and not registry.check_key(None) and not registry.check_key(5)
    assert not registry.check_key("é" * 64)  # non-ASCII must not raise
    assert len(calls) >= 6


def test_mentions_key_sees_the_name_quoting_and_globs():
    for c in ("cat ~/.local/state/xmuse/sidebar.key", "cat C:\\Users\\a\\AppData\\Local\\xmuse\\SIDEBAR.KEY",
              "cat \"/x/side\"bar.key", "cat /x/'sidebar'.key", "cat /x/side\\bar.key", "cat /x/side*",
              "cat /x/*.key", "cat /x/sidebar.k?y", "head -c 5 /x/s[i]debar.key", "XMUSE=1 cat $D/sidebar.key"):
        assert registry.mentions_key(c), c
    for c in ("ls", "grep foo *", "git status --short", "cat sidebar.txt", "ls -la ~/.local/state/xmuse",
              "python -m pytest tests/test_x.py -k key", "cat *.py"):
        assert not registry.mentions_key(c), c


def test_mentions_key_lets_a_search_for_the_name_through():
    # a member reading the hub's source (dev room, 10-12): searching for the name is not opening the file, and a
    # refused command ends the member's turn
    for c in ('grep -n "def \\|hubs.json\\|sidebar.key\\|sidebar_key" hub/src/xmuse/registry.py',
              "grep -n sidebar.key hub/src/xmuse/registry.py", "rg 'sidebar\\.key' hub", "git grep -n sidebar.key",
              "grep -rn -e sidebar.key integrations"):
        assert not registry.mentions_key(c), c
    for c in ("grep . ~/.local/state/xmuse/sidebar.key", "grep -e x /a/sidebar.key", "rg x /a/side*",
              "ls; cat /a/sidebar.key", "grep foo x && cat 'side'bar.key", "cat \"unbalanced /a/sidebar.key"):
        assert registry.mentions_key(c), c


# ---- the hub registers itself -------------------------------------------------------------------------------------

def test_hub_registers_on_start_follows_the_room_and_leaves_on_shutdown(make, monkeypatch):
    h = make()
    hj = json.loads((h.state / "hub.json").read_text(encoding="utf-8"))
    [e] = registry.hubs()
    ws = h.hub.ws
    assert e == {"room_id": rooms.room_id(ws), "name": ws.name, "dir": str(ws), "host": None, "pid": os.getpid(),
                 "url": f"http://127.0.0.1:{hj['port']}", "started_at": h.hub.started_at}
    assert registry.read_key()  # the first hub made the key
    room = open_room(h)
    [e] = registry.hubs()
    assert e["name"] == "dev" and e["host"] == "lead" and e["url"].endswith(str(hj["port"]))
    assert act(h, room["operator_token"], act="transfer_host", member="claude-1")[0] == 200
    assert registry.hubs()[0]["host"] == "claude-1"
    real = h.hub.shutdown
    h.hub.shutdown = lambda: None  # the fixture closes it again at the end
    real()
    assert registry.hubs() == []


def test_two_hubs_have_separate_entries_and_one_key(make, tmp_path):
    h = make()
    other = {"room_id": "r-other", "name": "o", "dir": "/o", "url": "http://127.0.0.1:9", "host": None,
             "pid": os.getpid(), "started_at": 2.0}
    registry.register(other)  # as a second hub in the same registry would
    assert {e["room_id"] for e in registry.hubs()} == {rooms.room_id(h.hub.ws), "r-other"}
    assert registry.ensure_key() == h.key()


def test_hub_cli_start_registers_and_stop_unregisters(ws):  # noqa: F811  a real hub process, stopped by SIGTERM
    run(ws, "init", ".")
    run(ws, "agent", "add", "claude-1", "--vendor", "claude")
    state = config.find_state(ws)
    try:
        assert "hub started" in run(ws, "hub", "start").stdout
        [e] = registry.hubs()
        hub = json.loads((state / "hub.json").read_text(encoding="utf-8"))
        assert e["pid"] == hub["pid"] != os.getpid() and e["url"].endswith(f":{hub['port']}")
        assert e["room_id"] == rooms.room_id(ws.resolve()) and registry.read_key()
    finally:
        run(ws, "hub", "stop")
    assert registry.hubs() == []


# ---- POST /v1/join without a code ----------------------------------------------------------------------------------

def test_join_by_dir_and_by_room_id(make):
    h = make()
    lead = open_room(h)
    st, j = join(h, role="reviewer", description="reviews D4", client_info={"client": "t"})
    assert st == 200 and j["member_id"] == "claude" and j["room"]["id"] == rooms.room_id(h.ws)
    assert j["room"]["host"] == "lead"
    assert j["member_token"].startswith("xmt_") and j["operator_token"].startswith("xmo_")
    a = h.q("select role, description, bound_session, settings from agents where id='claude'")[0]
    assert (a["role"], a["description"], a["bound_session"]) == ("reviewer", "reviews D4", "S-j")
    assert json.loads(a["settings"]).get("desktop")  # lives in the user's own session
    st, v = view(h, j["member_token"], "S-j")
    assert st == 200 and v["me"] == {"kind": "member", "id": "claude"}
    assert any(t["from"] == "hub" and "claude joined the room" in t["text"] and t["thread"] == "#room"
               for t in v["timeline"])
    assert view(h, j["operator_token"])[1]["me"] == {"kind": "operator", "id": "claude"}
    # by room id, no name: the next free id of the vendor, and role/description are optional
    st, j2 = call(h, "POST", "/v1/join", {"room_id": rooms.room_id(h.ws), "vendor": "claude", "session_id": "S-k"},
                  key=h.key())
    assert st == 200 and j2["member_id"] == "claude-2"
    assert h.q("select role, description from agents where id='claude-2'") == [{"role": "", "description": ""}]
    # a name picks the id
    st, j3 = join(h, name="rev-1", session_id="S-o")
    assert st == 200 and j3["member_id"] == "rev-1" and j3["member_token"] != j["member_token"]
    assert lead["member_id"] == "lead"


def test_join_errors(make):
    h = make()
    open_room(h)
    post = lambda body, **kw: call(h, "POST", "/v1/join", body, key=h.key(), **kw)  # noqa: E731
    base = {"dir": str(h.ws), "vendor": "claude", "session_id": "S"}
    st, out = post({**base, "dir": "/elsewhere"})
    assert st == 400 and out["error"] == "wrong_dir"
    st, out = post({"room_id": "r-0000", "vendor": "claude", "session_id": "S"})
    assert st == 404 and out["error"] == "unknown_room"
    assert post({"vendor": "claude", "session_id": "S"})[1]["error"] == "bad_request"  # neither dir nor room_id
    assert post({**base, "vendor": "gemini"})[1]["error"] == "bad_request"
    assert post({**base, "session_id": ""})[1]["error"] == "bad_request"
    assert post({**base, "name": "human"})[1]["error"] == "bad_request"
    assert [post({**base, **bad})[0] for bad in ({"name": "a b"}, {"role": 5}, {"dir": 5})] == [400, 400, 400]
    assert post([1])[0] == 400


def test_join_credential_errors_are_401(make):
    h = make()
    open_room(h)
    body = {"dir": str(h.ws), "vendor": "claude", "session_id": "S"}
    for key in (None, "wrong", h.key()[:-1], h.key().upper(), "é"):
        st, out = call(h, "POST", "/v1/join", body, key=key)
        assert st == 401 and out["error"] == "bad_sidebar_key", key
    registry.key_path().unlink()  # no key on disk: nothing is valid, not even an empty string
    assert call(h, "POST", "/v1/join", body, key="")[0] == 401
    assert h.q("select count(*) n from agents where vendor='claude'")[0]["n"] == 2  # claude-1 and lead only


def test_join_with_a_code_works_as_before_without_the_key(make):
    h = make()
    ot = open_room(h)["operator_token"]
    _, inv = act(h, ot, act="invite", vendor="claude")
    st, j = call(h, "POST", "/v1/join", {"code": inv["code"], "vendor": "claude", "session_id": "S2"})
    assert st == 200 and j["member_id"] == "claude"
    st, out = call(h, "POST", "/v1/join", {"code": "ZZZZ-ZZ", "vendor": "claude", "session_id": "S"})
    assert st == 404 and out["error"] == "unknown_code"  # a bad code is not a key problem


def test_join_takes_over_a_registered_member_or_conflicts(make):
    h = make([("dog", "claude", {"desktop": True})])  # `xmuse agent add --desktop`: no session yet, no room row yet
    st, j = join(h, name="dog", description="the coordinator", role="coordinator")
    assert st == 200 and j["member_id"] == "dog" and j["member_token"] == h.token("dog")
    assert j["room"]["host"] == "dog"
    a = h.q("select bound_session, description, role from agents where id='dog'")[0]
    assert a == {"bound_session": "S-j", "description": "the coordinator", "role": "coordinator"}
    before = h.q("select count(*) n from agents")[0]["n"]
    st, out = join(h, name="dog", session_id="S-2")  # already bound
    assert st == 409 and out["error"] == "member_exists"
    st, out = join(h, name="dog", vendor="opencode")  # id taken by another vendor
    assert st == 409 and out["error"] == "member_exists"
    assert h.q("select count(*) n from agents")[0]["n"] == before
    assert h.q("select bound_session from agents where id='dog'")[0]["bound_session"] == "S-j"
    # after /v1/leave it is free again and the same sidebar (or another) may take it over
    assert call(h, "POST", "/v1/leave", {}, j["member_token"], "S-j")[0] == 200
    assert join(h, name="dog", session_id="S-3")[0] == 200


def test_join_needs_a_room_first(make):
    h = make()  # one headless claude, no sidebar has opened the room
    st, out = join(h)
    assert st == 404 and out["error"] == "no_room"
    st, out = call(h, "GET", "/v1/rooms", key=h.key())
    assert st == 200 and out["room"] is None and [m["id"] for m in out["members"]] == ["claude-1"]
    open_room(h)
    assert join(h)[0] == 200


def test_removed_members_id_cannot_be_reused_by_name(make):
    h = make()
    ot = open_room(h)["operator_token"]
    _, j = join(h)
    assert act(h, ot, act="remove", member=j["member_id"])[0] == 200
    st, out = join(h, name=j["member_id"], session_id="S-again")
    assert st == 409 and out["error"] == "member_exists"
    assert join(h)[1]["member_id"] == "claude-2"  # the removed id is not handed out again either


# ---- POST/GET /v1/rooms ------------------------------------------------------------------------------------------

def test_rooms_need_the_key(make):
    h = make()
    body = {"dir": str(h.ws), "vendor": "claude", "session_id": "S", "member_id": "lead"}
    for key in (None, "nope"):
        st, out = call(h, "POST", "/v1/rooms", body, key=key)
        assert st == 401 and out["error"] == "bad_sidebar_key"
        st, out = call(h, "GET", "/v1/rooms", key=key)
        assert st == 401 and out["error"] == "bad_sidebar_key"
    assert not h.q("select 1 from room") and not h.q("select 1 from agents where id='lead'")
    assert call(h, "POST", "/v1/rooms", body, key=h.key())[0] == 200


def test_get_rooms_lists_room_and_members(make):
    h = make()
    room = open_room(h, role="x")
    _, j = join(h, role="reviewer")
    st, out = call(h, "GET", "/v1/rooms", key=h.key())
    assert st == 200 and out["room"]["id"] == rooms.room_id(h.ws) and out["room"]["host"] == "lead"
    assert set(out["room"]) == {"id", "name", "dir", "host", "created_at"}
    ms = {m["id"]: m for m in out["members"]}
    assert set(ms) == {"claude-1", "lead", "claude"}
    assert all(set(m) == {"id", "vendor", "role", "online"} for m in ms.values())
    assert ms["claude"] == {"id": "claude", "vendor": "claude", "role": "reviewer", "online": True}
    assert ms["lead"]["role"] == "coordinator"
    # an operator token does not replace the key
    assert call(h, "GET", "/v1/rooms", None, room["operator_token"])[0] == 401


def test_member_tokens_get_403_on_join_and_rooms(make):
    h = make()
    room = open_room(h)
    mt, key = room["member_token"], h.key()
    body = {"dir": str(h.ws), "vendor": "claude", "session_id": "S"}
    for method, path in (("POST", "/v1/join"), ("POST", "/v1/rooms"), ("GET", "/v1/rooms")):
        for k in (key, None):  # the token is refused before the key is looked at
            st, out = call(h, method, path, body if method == "POST" else None, mt, "S-lead", key=k)
            assert st == 403 and out["error"] == "member_forbidden", (path, k)
    _, inv = act(h, room["operator_token"], act="invite", vendor="claude")
    st, out = call(h, "POST", "/v1/join", {"code": inv["code"], "vendor": "claude", "session_id": "S"}, mt, "S-lead")
    assert st == 403 and out["error"] == "member_forbidden"  # the old path too
    assert h.q("select used_at from invites where code=?", inv["code"])[0]["used_at"] is None
    assert h.q("select count(*) n from agents")[0]["n"] == 2
    # a hub-run member's token (never bound) is a member token as well
    st, out = call(h, "POST", "/v1/join", body, h.token("claude-1"), key=key)
    assert st == 403


# ---- member_add / member_edit ---------------------------------------------------------------------------------------

def roomlog(h):
    return [m["body"] for m in h.q("select body from messages where thread_id='#room' order by id")]


def test_member_add_registers_a_hub_run_member_like_agent_add(make):
    h = make(OC)
    ot = open_room(h, vendor="claude")["operator_token"]
    st, out = act(h, ot, act="member_add", vendor="opencode", name="oc-new", role="executor",
                  description="writes the parser", model="opencode-go/other-model")
    assert (st, out) == (200, {"member_id": "oc-new"})
    a = h.q("select * from agents where id='oc-new'")[0]
    assert (a["vendor"], a["role"], a["description"], a["model"], a["removed"], a["bound_session"]) == (
        "opencode", "executor", "writes the parser", "opencode-go/other-model", 0, None)
    assert a["family"] == config.family("opencode", "opencode-go/other-model")
    assert json.loads(a["settings"]) == {}  # not desktop, not foreground: the hub starts its turns
    assert (h.state / "tokens" / "oc-new").exists() and (h.state / "oc" / "oc-new" / "opencode.json").exists()
    _, v = view(h, ot)
    m = next(m for m in v["members"] if m["id"] == "oc-new")
    assert (m["vendor"], m["role"], m["description"], m["model"], m["paused"]) == (
        "opencode", "executor", "writes the parser", "opencode-go/other-model", False)
    ev = [t for t in v["timeline"] if t["thread"] == "#room" and "oc-new 已加入" in t["text"]]
    assert len(ev) == 1 and ev[0]["from"] == "hub" and "opencode · opencode-go/other-model" in ev[0]["text"] \
        and ev[0]["kind"] == "system"
    assert not h.q("select 1 from deliveries d join messages m on m.id=d.message_id"
                   " where m.body like '%oc-new 已加入%' and d.recipient='oc-new' and d.wake=1")  # event, no wake
    assert h.q("select wake, state from deliveries d join messages m on m.id=d.message_id"
               " where m.body like '%oc-new 已加入%' and d.recipient='lead'") == [
               {"wake": 1, "state": "queued"}]  # the host gets a wake delivery and can hand work out at once
    # no name: the vendor's name, then numbered
    assert act(h, ot, act="member_add", vendor="opencode")[1] == {"member_id": "opencode"}
    assert act(h, ot, act="member_add", vendor="opencode")[1] == {"member_id": "opencode-2"}
    assert h.q("select model from agents where id='opencode-2'")[0]["model"] == config.MODELS["opencode"]


def test_member_add_errors(make):
    h = make(OC)
    ot = open_room(h)["operator_token"]
    n = h.q("select count(*) n from agents")[0]["n"]
    for body, status, code in (({"vendor": "gemini"}, 400, "bad_vendor"), ({}, 400, "bad_vendor"),
                               ({"vendor": "opencode", "name": "opencode-1"}, 409, "member_exists"),
                               ({"vendor": "opencode", "name": "lead"}, 409, "member_exists"),
                               ({"vendor": "opencode", "name": "human"}, 400, "bad_request"),
                               ({"vendor": "opencode", "name": "a b"}, 400, "bad_request"),
                               ({"vendor": "opencode", "model": "no-provider"}, 400, "bad_request"),
                               ({"vendor": "opencode", "role": 7}, 400, "bad_request"),
                               ({"vendor": "claude", "name": "c2"}, 400, "cannot_add")):  # root already has a claude
        st, out = act(h, ot, act="member_add", **body)
        assert (st, out["error"]) == (status, code), body
    assert "claude" in act(h, ot, act="member_add", vendor="claude", name="c2")[1]["message"]
    assert h.q("select count(*) n from agents")[0]["n"] == n and not h.q("select 1 from agents where id='c2'")


def test_member_add_dsh_is_not_foreground(make, monkeypatch):
    monkeypatch.setattr("xmuse.init._dsh_ws_ok", lambda ws: True)  # the temp workspace is not on a Windows drive
    h = make(OC)
    ot = open_room(h)["operator_token"]
    assert act(h, ot, act="member_add", vendor="dsh", name="dsh-w", role="executor")[1] == {"member_id": "dsh-w"}
    a = h.q("select * from agents where id='dsh-w'")[0]
    assert a["vendor"] == "dsh" and json.loads(a["settings"]) == {} and not a["bound_session"]
    assert "dsh" in h.hub.engine.drivers  # a vendor first seen here gets its driver


def test_member_added_claude_gets_its_turns_from_the_hub(make, monkeypatch):
    monkeypatch.setattr("xmuse.init._dsh_ws_ok", lambda ws: True)
    h = make(agents=())
    ot = open_room(h, vendor="dsh", member_id="lead")["operator_token"]  # a dsh host leaves the root to a claude
    # the join notice wakes the host (T8a2); this dsh host runs no turns here, so park it to let the hub go quiet
    with db.tx(h.conn()) as c:
        c.execute("update agents set paused=1 where id='lead'")
    assert act(h, ot, act="member_add", vendor="claude", name="worker", role="executor")[1] == {"member_id": "worker"}
    h.plan_claude({})
    assert act(h, ot, act="say", to="worker", text="please build the parser")[0] == 200
    h.wait_quiet()
    assert any("please build the parser" in c["prompt"] for c in h.claude_calls())
    assert h.q("select count(*) n from turns where agent_id='worker'")[0]["n"] == 1


def test_member_edit_changes_role_description_and_model(make):
    h = make()
    ot = open_room(h)["operator_token"]
    before = h.q("select * from agents where id='claude-1'")[0]
    st, out = act(h, ot, act="member_edit", member="claude-1", role="reviewer", description="reviews the API",
                  model="claude-sonnet-x")
    assert (st, out) == (200, {"ok": True})
    a = h.q("select * from agents where id='claude-1'")[0]
    assert (a["role"], a["description"], a["model"]) == ("reviewer", "reviews the API", "claude-sonnet-x")
    assert a["family"] == config.family("claude", "claude-sonnet-x")
    assert a["token_digest"] == before["token_digest"] and a["settings"] == before["settings"]
    v1 = view(h, ot)[1]
    m = next(m for m in v1["members"] if m["id"] == "claude-1")
    assert (m["role"], m["description"], m["model"]) == ("reviewer", "reviews the API", "claude-sonnet-x")
    [ev] = [t for t in v1["timeline"] if t["thread"] == "#room" and "claude-1 was edited" in t["text"]]
    assert "role = reviewer" in ev["text"] and "model = claude-sonnet-x" in ev["text"]
    # partial edits leave the rest alone; an empty string clears; the view version moves
    act(h, ot, act="member_edit", member="claude-1", description="")
    a = h.q("select role, description, model from agents where id='claude-1'")[0]
    assert a == {"role": "reviewer", "description": "", "model": "claude-sonnet-x"}
    assert view(h, ot)[1]["version"] > v1["version"]
    # the model change is what the next turn uses
    h.plan_claude({})
    h.send("claude-1", "which model?")
    h.wait_quiet()
    assert "claude-sonnet-x" in h.claude_calls()[-1]["argv"]


def test_models_lists_what_a_member_can_switch_to(make, monkeypatch):
    """The panel's model picker: the current model first, the defaults, OpenCode's own catalog, Claude's aliases;
    operator only. A pick is a member_edit, which the next turn uses (above)."""
    h = make(OC + [("claude-1", "claude")])
    ot = open_room(h)["operator_token"]

    class Srv:
        def api(self, method, path):
            assert (method, path) == ("GET", "/api/model")
            return {"data": [{"providerID": "zai", "id": "glm-9", "name": "GLM 9"}, {"providerID": "oc", "id": "m2"}]}

    class Drv:
        def prompt_for(self, aid):
            return type("P", (), {"server": Srv()})()

        def close(self):
            pass

    monkeypatch.setitem(h.hub.engine.drivers, "opencode", Drv())
    st, out = act(h, ot, act="models", member="opencode-1")
    cur = h.q("select model from agents where id='opencode-1'")[0]["model"]
    vals = [o["value"] for o in out["options"]]
    assert st == 200 and out["current"] == cur and vals[0] == cur and out["free"] is True
    assert "zai/glm-9" in vals and "oc/m2" in vals and out["format"] == "<provider>/<model>"
    assert next(o for o in out["options"] if o["value"] == "zai/glm-9")["label"] == "zai/GLM 9"
    st, out = act(h, ot, act="models", member="claude-1")
    assert {"sonnet", "haiku", "opus"} <= {o["value"] for o in out["options"]} and out["format"] == ""
    monkeypatch.delitem(h.hub.engine.drivers, "opencode")  # no catalog: still the known ones
    st, out = act(h, ot, act="models", member="opencode-1")
    assert st == 200 and out["options"][0]["value"] == cur
    tok = (h.state / "tokens" / "claude-1").read_text(encoding="utf-8").strip()
    assert act(h, tok, "S-x", act="models", member="opencode-1")[0] == 403


def test_member_edit_errors(make):
    h = make(OC + [("claude-1", "claude")])
    ot = open_room(h)["operator_token"]
    for body, status, code in (({"member": "ghost", "role": "x"}, 404, "unknown_member"),
                               ({"role": "x"}, 404, "unknown_member"),
                               ({"member": "claude-1"}, 400, "bad_request"),
                               ({"member": "claude-1", "role": 3}, 400, "bad_request"),
                               ({"member": "claude-1", "model": " "}, 400, "bad_request"),
                               ({"member": "opencode-1", "model": "no-slash"}, 400, "bad_request")):
        st, out = act(h, ot, act="member_edit", **body)
        assert (st, out["error"]) == (status, code), body
    assert h.q("select role from agents where id='claude-1'")[0]["role"] == ""
    st, out = act(h, ot, act="member_add", vendor="dsh", model="no-slash")  # dsh splits at "/" too
    assert (st, out["error"]) == (400, "bad_request")
    act(h, ot, act="remove", member="claude-1")
    assert act(h, ot, act="member_edit", member="claude-1", role="x")[0] == 404  # removed members are gone


def test_member_acts_are_operator_only(make):
    h = make()
    room = open_room(h)
    mt = room["member_token"]
    for body in ({"act": "member_add", "vendor": "opencode"},
                 {"act": "member_edit", "member": "claude-1", "role": "x"}):
        st, out = act(h, mt, "S-lead", **body)
        assert st == 403 and out["error"] == "operator_only", body
        st, out = act(h, h.token("claude-1"), **body)  # a hub-run member, never bound
        assert st == 403 and out["error"] == "operator_only", body
    assert h.q("select role from agents where id='claude-1'")[0]["role"] == ""
    assert not h.q("select 1 from agents where vendor='opencode'")
    # the CLI's admin token is not a member: it may manage
    assert act(h, h.token("human"), act="member_edit", member="claude-1", role="coder") == (200, {"ok": True})


# ---- the shell policy refuses the key ---------------------------------------------------------------------------

KEY_CMDS = ["cat ~/.local/state/xmuse/sidebar.key", "cat $HOME/.local/state/xmuse/sidebar.key",
            "head -c 64 /mnt/c/Users/u/AppData/Local/xmuse/sidebar.key", "grep . ~/.local/state/xmuse/side*",
            "PYTHONPATH=x cat '/x/sidebar.key'", "cat /x/sidebar.key | head -c 4", "echo $(cat /x/sidebar.key)"]


def test_shell_policy_refuses_commands_naming_the_key():
    for c in KEY_CMDS:
        for policy in ("allowlist", "blocklist-experiment"):
            assert not shell_auto_ok("shell", [c], policy), (c, policy)
            assert auto_decision("shell", [c], policy) == "reject", (c, policy)
        assert auto_decision("shell", ["git status --short", c]) == "reject"  # one of several commands is enough
    # the same commands without the key keep their old answers
    assert auto_decision("shell", ["cat ~/.local/state/xmuse/hub.json"]) == "once"
    assert auto_decision("shell", ["cat notes.txt"], "blocklist-experiment") == "once"
    assert auto_decision("shell", ["git push origin main"]) is None
    assert auto_decision("edit", ["/x/sidebar.key"]) is None  # only shell commands are judged here
    # open-experiment approves everything by definition (user 10-12): unchanged
    assert auto_decision("shell", [KEY_CMDS[0]], "open-experiment") == "once"


@pytest.mark.parametrize("policy", [None, "blocklist-experiment"])
def test_hub_rejects_a_key_reading_command_without_asking_the_human(make, monkeypatch, policy):
    if policy:
        monkeypatch.setenv("XMUSE_SHELL_POLICY", policy)
    h = make(OC)
    h.oc.plan = [{"result": "hang"}]
    h.send("opencode-1", "go")
    h.wait(lambda: h.hub.engine.drivers["opencode"].headless.turns, what="tracked")
    h.oc.ask_permission("ses_fake1", "per_k", "cat ~/.local/state/xmuse/sidebar.key")
    h.wait(lambda: h.oc.replies, what="auto reply")
    assert h.oc.replies == [{"session": "ses_fake1", "request": "per_k", "decision": "reject"}]
    assert h.q("select state, decision from approvals")[0] == {"state": "decided", "decision": "reject"}
    assert not any("per_k" in n["body"] for n in h.q("select body from messages where kind='notice'"))
    h.admin("stop")
