"""`xmuse transcript`: each vendor's session record rendered as readable text (read-only)."""
import json

import pytest
import zstandard

from xmuse import cli, db, transcript as tr


def _session(h, agent, sid, cwd=None):
    with db.tx(h.conn()) as c:
        c.execute("insert into sessions(agent_id, vendor_session, cwd, origin, created_at) values(?,?,?,?,?)",
                  (agent, sid, cwd, "hub", 0))


def test_claude_transcript_keeps_streamed_blocks_once(tmp_path):
    p = tmp_path / "t.jsonl"
    recs = [
        {"type": "user", "message": {"content": "review calc.py"}},
        {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "Looking."}]}},
        {"type": "assistant", "message": {"id": "m1", "content": [  # the same message re-recorded while streaming
            {"type": "text", "text": "Looking."}, {"type": "tool_use", "name": "Read", "input": {"file": "calc.py"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": [{"type": "text", "text": "x" * 50}]}]}},
        {"type": "summary"},
    ]
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\nnot json\n", encoding="utf-8")
    entries = tr.claude(p)
    assert entries == [("user", "review calc.py"), ("assistant", "Looking."),
                       ("tool Read", '{"file": "calc.py"}'), ("tool result", "x" * 50)]
    text = tr.render(entries, clip=10)
    assert text.startswith("[user]\nreview cal") and "[40 more chars]" in text


def _dsh_log(path, recs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(zstandard.ZstdCompressor().compress("\n".join(json.dumps(r) for r in recs).encode()))


DSH = [
    {"type": "user/message", "data": {"content": [{"type": "text", "text": "fix the bug"}], "source": {"kind": "user"}}},
    {"type": "user/message", "data": {"content": [{"type": "text", "text": "<system-reminder>\nrules"}],
                                      "source": {"kind": "user"}}},
    {"type": "assistant/message", "data": {"message": {"content": [{"type": "text", "text": "On it."}]}}},
    {"type": "tool/call", "data": {"name": "read_file", "arguments": "{\"path\":\"a.py\"}"}},
    {"type": "tool/result", "data": {"message": {"content": [{"type": "text", "text": "boom"}], "isError": True}}},
    {"type": "turn/end", "data": {"reason": {"kind": "completed"}}},
    {"type": "turn/end", "data": {"reason": {"kind": "interrupted"}}},
]


def test_dsh_transcript(tmp_path):
    p = tmp_path / "session.v4.jsonl.zstd"
    _dsh_log(p, DSH)
    assert tr.dsh(p) == [("user", "fix the bug"), ("assistant", "On it."), ("tool read_file", '{"path":"a.py"}'),
                         ("tool error", "boom"), ("turn end", "interrupted")]


def test_opencode_transcript_orders_by_time():
    msgs = [
        {"type": "assistant", "time": {"created": 2}, "content": [
            {"type": "reasoning", "text": "hidden"}, {"type": "text", "text": "Done."},
            {"type": "tool", "name": "bash", "state": {"status": "completed", "input": {"command": "pytest"},
                                                       "content": [{"type": "text", "text": "3 passed"}]}}]},
        {"type": "user", "time": {"created": 1}, "text": "run the tests"},
        {"type": "model-switched", "time": {"created": 0}},
    ]
    assert tr.opencode(msgs) == [("user", "run the tests"), ("assistant", "Done."),
                                 ("tool bash", '{"command": "pytest"}'), ("tool result", "3 passed")]


def test_cli_transcript_per_vendor(make, tmp_path):
    h = make([("claude-1", "claude"), ("oc", "opencode"), ("ds", "dsh")])
    with pytest.raises(SystemExit, match="no current session"):
        cli.transcript(h.state, "claude-1")
    with pytest.raises(SystemExit, match="no agent"):
        cli.transcript(h.state, "nobody")
    # claude: the transcript Claude Code keeps for the session's cwd
    from xmuse.adapters.claude import transcript as claude_path
    _session(h, "claude-1", "sid-c")
    p = claude_path(h.ws, "sid-c")
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"type": "user", "message": {"content": "hello claude"}}) + "\n", encoding="utf-8")
    assert cli.transcript(h.state, "claude-1") == "[user]\nhello claude"
    # dsh: the session log under dsh_home
    _session(h, "ds", "sid-d")
    _dsh_log(h.tmp / "dsh-home" / "sessions" / "--C-ws--" / "sid-d" / "session.v4.jsonl.zstd", DSH[:1])
    assert cli.transcript(h.state, "ds") == "[user]\nfix the bug"
    # opencode: through the hub, which owns the server
    _session(h, "oc", "ses_x")
    h.oc.messages["ses_x"] = [{"type": "user", "time": {"created": 1}, "text": "hello oc"}]
    assert cli.transcript(h.state, "oc") == "[user]\nhello oc"
    # --path reads a file directly
    assert cli.transcript(h.state, "", path=p) == "[user]\nhello claude"
