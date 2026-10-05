"""Host-side checks for xmuse-ctl (no install, no network beyond loopback).

A tiny ``http.server`` thread serves, per room, the golden board_v2
scenario payloads at the same route paths the Claude Code mod uses, plus
a rooms list and an events route that answers immediately. Every golden
scenario must render in ``status`` and ``board`` without leaking any
agent-authored text.
"""

from __future__ import annotations

import ast
import json
import os
import re
import stat
import sys
import threading
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CTL_ROOT = REPO_ROOT / "integrations" / "xmuse-ctl"
PKG_ROOT = CTL_ROOT / "xmuse_ctl"
README_PATH = CTL_ROOT / "README.md"
FIXTURE_DIR = REPO_ROOT / "docs" / "contracts" / "fixtures" / "board_v2"

sys.path.insert(0, str(CTL_ROOT))

from xmuse_ctl import cli as ctl_cli  # noqa: E402

# 12 pre-review scenarios, the 6 review scenarios and the 8 integration
# scenarios. Sidecar goldens (<scenario>.review.json, .integration.json
# etc.) are never scenarios and are never read.
EXPECTED_SCENARIOS = [
    "contract_revised_stale_dependent",
    "empty",
    "injection_text",
    "integration_conflicted",
    "integration_dependency_upgrade",
    "integration_error",
    "integration_fallback_to_incumbent",
    "integration_gate_failed",
    "integration_integrated",
    "integration_pending_running",
    "lifecycle_mix",
    "review_endorsed",
    "review_endorsed_integrated",
    "review_escalated",
    "review_objected",
    "review_operator_pending",
    "review_participant_pending",
    "review_superseded",
    "split_approved_via_plugin",
    "split_pending",
    "superseded_done",
    "verification_error",
    "verification_escalated",
    "verification_failed_rework",
    "verified",
    "verifying_and_waiting",
]


def _scenario_files() -> list[Path]:
    files = sorted(FIXTURE_DIR.glob("*.json"))
    return [path for path in files if "." not in path.stem]


def _room_id(stem: str) -> str:
    return "conv-" + stem.replace("_", "-")


def _rewrite_conversation(payload: object, room_id: str) -> object:
    if isinstance(payload, dict):
        out = dict(payload)
        if "conversation_id" in out:
            out["conversation_id"] = room_id
        return out
    return payload


def _build_state() -> dict[str, object]:
    rooms: list[dict[str, object]] = []
    by_room: dict[str, dict[str, object]] = {}
    files = _scenario_files()
    for index, path in enumerate(files):
        stem = path.stem
        room_id = _room_id(stem)
        fixture = json.loads(path.read_text(encoding="utf-8"))
        by_room[room_id] = {
            "summary": _rewrite_conversation(fixture["summary"], room_id),
            "projection": _rewrite_conversation(fixture["projection"], room_id),
            "events_page": _rewrite_conversation(fixture["events_page"], room_id),
        }
        updated = f"2026-01-01T00:00:{index:02d}Z"
        rooms.append(
            {
                "conversation_id": room_id,
                "title": "Room " + stem,
                "updated_at": updated,
                "created_at": updated,
                "href": "/rooms/" + room_id,
                "note": "unknown fields are tolerated",
            }
        )
    # A room with a hostile title: ANSI, bidi controls and over-long text.
    funky_id = "conv-funky-title"
    by_room[funky_id] = {
        "summary": {
            "schema_version": "room_board_summary/v1",
            "conversation_id": funky_id,
            "server_time": "2026-01-01T00:00:00Z",
            "board_seq": 1,
            "revision": "1:funky",
            "capabilities": {"verification": 1, "reviews": 0, "integrations": 0, "lessons": 0},
            "modules_total": 0,
            "counts": {
                "assigned": 0,
                "claimed": 0,
                "working": 0,
                "blocked": 0,
                "ready_for_review": 0,
                "done_claimed": 0,
                "verifying": 0,
                "waiting_for_provider": 0,
                "verified": 0,
                "verification_failed": 0,
                "verification_error": 0,
            },
            "accepted_total": 0,
            "attention_total": 0,
            "attention": [],
        },
        "projection": {
            "schema_version": "room_board_projection/v2",
            "metrics_version": "board_metrics/v1",
            "conversation_id": funky_id,
            "server_time": "2026-01-01T00:00:00Z",
            "board_seq": 1,
            "revision": "1:funky",
            "capabilities": {"verification": 1, "reviews": 0, "integrations": 0, "lessons": 0},
            "review_policy": "off",
            "participants": [],
            "modules": [],
            "contracts": [],
            "splits": [],
            "stale_dependents": [],
            "attention": [],
            "events": [],
        },
        "events_page": {
            "schema_version": "room_board_events/v1",
            "conversation_id": funky_id,
            "board_seq": 1,
            "revision": "1:funky",
            "events": [],
            "has_more": False,
            "reset": False,
        },
    }
    rooms.append(
        {
            "conversation_id": funky_id,
            "title": "\x1b[31mRed\u200eTitle\u202e" + "T" * 100,
            "updated_at": "2026-01-02T00:00:00Z",
            "created_at": "2026-01-02T00:00:00Z",
            "href": "/rooms/" + funky_id,
        }
    )
    # Two rooms for the attach tests: bbb is newer but has no modules, so a
    # bare attach must pick aaa (most recent room that has modules).
    for room_id, updated, total, accepted in [
        ("conv-aaa-111", "2026-02-01T00:00:00Z", 2, 1),
        ("conv-bbb-222", "2026-02-02T00:00:00Z", 0, 0),
    ]:
        by_room[room_id] = {
            "summary": {
                "schema_version": "room_board_summary/v1",
                "conversation_id": room_id,
                "server_time": updated,
                "board_seq": 3,
                "revision": "3:attach",
                "capabilities": {
                    "verification": 1,
                    "reviews": 0,
                    "integrations": 0,
                    "lessons": 0,
                },
                "modules_total": total,
                "counts": {
                    "assigned": 0,
                    "claimed": 0,
                    "working": total - accepted,
                    "blocked": 0,
                    "ready_for_review": 0,
                    "done_claimed": 0,
                    "verifying": 0,
                    "waiting_for_provider": 0,
                    "verified": accepted,
                    "verification_failed": 0,
                    "verification_error": 0,
                },
                "accepted_total": accepted,
                "attention_total": 0,
                "attention": [],
            },
            "projection": by_room[_room_id("empty")]["projection"],
            "events_page": by_room[_room_id("empty")]["events_page"],
        }
        rooms.append(
            {
                "conversation_id": room_id,
                "title": "Attach room " + room_id,
                "updated_at": updated,
                "created_at": updated,
                "href": "/rooms/" + room_id,
            }
        )
    # The watch room serves two synthetic events newer than its projection.
    watch_id = "conv-watch-001"
    watch_projection = json.loads(json.dumps(by_room[_room_id("verified")]["projection"]))
    watch_projection["conversation_id"] = watch_id
    by_room[watch_id] = {
        "summary": _rewrite_conversation(
            json.loads(json.dumps(by_room[_room_id("verified")]["summary"])), watch_id
        ),
        "projection": watch_projection,
        "events_page": {
            "schema_version": "room_board_events/v1",
            "conversation_id": watch_id,
            "board_seq": 8,
            "revision": "8:watchtest",
            "events": [
                {
                    "seq": 7,
                    "kind": "verification",
                    "at": "2026-01-01T00:00:07Z",
                    "module_id": "alpha",
                    "actor": {"kind": "infrastructure", "participant_id": None},
                    "data": {
                        "verification_id": "ver_watch_1",
                        "status": "passed",
                        "reason_code": None,
                        "gate_ids": [],
                        "escalated": False,
                        "stacked": [],
                    },
                },
                {
                    "seq": 8,
                    "kind": "progress",
                    "at": "2026-01-01T00:00:08Z",
                    "module_id": "beta",
                    "actor": {
                        "kind": "participant",
                        "participant_id": "part_00000000000000000000000000000003",
                    },
                    "data": {
                        "status": "working",
                        "summary": {
                            "text": "WATCHMARKER-AGENT-SECRET must never print",
                            "untrusted": True,
                            "truncated": False,
                        },
                        "claims": [],
                        "claims_total": 0,
                    },
                },
            ],
            "has_more": False,
            "reset": False,
        },
    }
    rooms.append(
        {
            "conversation_id": watch_id,
            "title": "Watch room",
            "updated_at": "2026-01-03T00:00:00Z",
            "created_at": "2026-01-03T00:00:00Z",
            "href": "/rooms/" + watch_id,
        }
    )
    return {"rooms": rooms, "by_room": by_room, "log": []}


def _make_handler(state: dict[str, object]) -> type[BaseHTTPRequestHandler]:
    rooms = state["rooms"]
    by_room = state["by_room"]
    log = state["log"]
    assert isinstance(rooms, list)
    assert isinstance(by_room, dict)
    assert isinstance(log, list)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def _send(self, payload: object) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            assert isinstance(self.path, str)
            log.append(self.path)
            parsed = urlparse(self.path)
            if parsed.path == "/api/chat/rooms":
                self._send({"rooms": rooms})
                return
            match = re.match(
                r"^/api/chat/conversations/([^/]+)/(board|board/summary|board/events)$",
                parsed.path,
            )
            if match is None:
                self.send_response(404)
                self.end_headers()
                return
            room_id, leaf = match.group(1), match.group(2)
            entry = by_room.get(room_id)
            if not isinstance(entry, dict):
                self.send_response(404)
                self.end_headers()
                return
            if leaf == "board":
                self._send(entry["projection"])
            elif leaf == "board/summary":
                self._send(entry["summary"])
            else:
                query = parse_qs(parsed.query)
                try:
                    after_seq = max(0, int(query.get("after_seq", ["0"])[0]))
                except ValueError:
                    after_seq = 0
                try:
                    limit = max(1, min(200, int(query.get("limit", ["100"])[0])))
                except ValueError:
                    limit = 100
                page = entry["events_page"]
                assert isinstance(page, dict)
                events = page["events"]
                assert isinstance(events, list)
                # Answers immediately in tests; wait is accepted, never required.
                fresh = [event for event in events if event["seq"] > after_seq][:limit]
                self._send(
                    {
                        "schema_version": "room_board_events/v1",
                        "conversation_id": room_id,
                        "board_seq": page["board_seq"],
                        "revision": page["revision"],
                        "events": fresh,
                        "has_more": False,
                        "reset": False,
                    }
                )

    return Handler


@pytest.fixture(scope="module")
def server() -> object:
    state = _build_state()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    info = {"base": f"http://127.0.0.1:{httpd.server_port}", "state": state, "httpd": httpd}
    yield info
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=10)


def _run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    argv: list[str],
    cwd: Path | None = None,
    xdg: Path | None = None,
    api_base: str | None = None,
) -> tuple[int, str, str]:
    assert isinstance(server, dict)
    if cwd is not None:
        monkeypatch.chdir(cwd)
    if xdg is not None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("XMUSE_API_BASE", api_base or str(server["base"]))
    monkeypatch.delenv("XMUSE_WEB_BASE", raising=False)
    code = ctl_cli.main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def _assert_clean(text: str) -> None:
    assert "\x1b" not in text
    for char in text:
        code = ord(char)
        assert char == "\n" or code >= 0x20, f"control character U+{code:04X}"
        assert not 0x80 <= code <= 0x9F, f"C1 character U+{code:04X}"
        assert unicodedata.category(char) != "Cf", f"format character U+{code:04X}"
        assert not 0xD800 <= code <= 0xDFFF, f"surrogate U+{code:04X}"


def _agent_texts(fixture: object) -> list[str]:
    out: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            text = value.get("text")
            if value.get("untrusted") is True and isinstance(text, str) and text != "":
                out.append(text)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(fixture)
    return out


def test_expected_scenario_set() -> None:
    stems = sorted(path.stem for path in _scenario_files())
    assert stems == sorted(EXPECTED_SCENARIOS)


@pytest.mark.parametrize("stem", EXPECTED_SCENARIOS)
def test_all_scenarios_render_without_agent_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
    stem: str,
) -> None:
    assert isinstance(server, dict)
    room_id = _room_id(stem)
    fixture = json.loads((FIXTURE_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    forbidden = _agent_texts(fixture)
    if stem != "empty":
        assert forbidden, f"no agent text found in {stem}"
    # A module title may equal its structured module id (the integration
    # scenarios title "m1" as m1); the id itself is allowed in the output.
    structured_ids = {
        str(module["module_id"]) for module in fixture["projection"].get("modules", [])
    }
    forbidden = [text for text in forbidden if text not in structured_ids]
    for argv in (
        ["status", "--line", "--room", room_id],
        ["board", "--room", room_id],
        ["board", "--json", "--room", room_id],
    ):
        code, out, err = _run(monkeypatch, capsys, server, argv, cwd=tmp_path)
        assert code == 0, f"{argv} exited {code}: {out} {err}"
        _assert_clean(out)
        for secret in forbidden:
            assert secret not in out, f"{argv} leaked agent text in {stem}"
        if "--json" in argv:
            json.loads(out)


def test_status_line_verified(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    code, out, _ = _run(
        monkeypatch,
        capsys,
        server,
        ["status", "--line", "--room", _room_id("verified")],
        cwd=tmp_path,
    )
    assert code == 0
    assert out.strip() == "看板 2 模块 · ✓1"


def test_status_block_operator_pending(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    room_id = _room_id("review_operator_pending")
    code, out, _ = _run(
        monkeypatch, capsys, server, ["status", "--line", "--room", room_id], cwd=tmp_path
    )
    assert code == 0
    assert out.strip() == "看板 2 模块 · ✓1 · 待你处理 1"
    code, out, _ = _run(monkeypatch, capsys, server, ["status", "--room", room_id], cwd=tmp_path)
    assert code == 0
    assert "待你复核" in out
    assert "rev " in out


def test_board_verified_shows_accepted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    code, out, _ = _run(
        monkeypatch, capsys, server, ["board", "--room", _room_id("verified")], cwd=tmp_path
    )
    assert code == 0
    # reviews are off in this scenario: the pre-review row, no completion mark
    assert "已验收" not in out
    assert "✓ 已验证" in out
    assert "alpha" in out
    assert "在 Web 打开：http://127.0.0.1:3000/rooms/" in out


def test_board_review_operator_pending(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    code, out, _ = _run(
        monkeypatch,
        capsys,
        server,
        ["board", "--room", _room_id("review_operator_pending")],
        cwd=tmp_path,
    )
    assert code == 0
    assert "待你复核" in out
    assert "✓ 已验收" in out  # alpha is endorsed and accepted
    beta_line = next(line for line in out.splitlines() if line.startswith("beta "))
    assert "✓ 已验证" in beta_line  # beta is verified but not accepted
    assert "· 待你复核" in beta_line


def test_board_review_endorsed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    code, out, _ = _run(
        monkeypatch, capsys, server, ["board", "--room", _room_id("review_endorsed")], cwd=tmp_path
    )
    assert code == 0
    assert "✓ 已验收" in out
    assert "已背书" in out


def test_board_split_pending(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    room_id = _room_id("split_pending")
    code, out, _ = _run(monkeypatch, capsys, server, ["board", "--room", room_id], cwd=tmp_path)
    assert code == 0
    assert "待审批 split_00000000000000000000000000000018" in out
    assert "在 Web 审批：http://127.0.0.1:3000/rooms/" + room_id in out
    assert "在 Web 打开：http://127.0.0.1:3000/rooms/" + room_id in out


def test_board_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    code, out, _ = _run(
        monkeypatch, capsys, server, ["board", "--room", _room_id("empty")], cwd=tmp_path
    )
    assert code == 0
    assert "暂无模块" in out
    _assert_clean(out)


def test_offline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    import socket as _socket

    probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    finally:
        probe.close()
    code, out, _ = _run(
        monkeypatch,
        capsys,
        {"base": f"http://127.0.0.1:{port}"},
        ["status", "--line", "--room", "conv-x"],
        cwd=tmp_path,
    )
    assert code == 3
    assert out.strip() == "xmuse 离线"


def test_rooms_newest_first_and_title_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    code, out, _ = _run(monkeypatch, capsys, server, ["rooms"], cwd=tmp_path)
    assert code == 0
    _assert_clean(out)
    lines = out.splitlines()
    assert lines[0].startswith("conv-bbb")
    assert lines[1].startswith("conv-aaa")
    assert lines[2].startswith("conv-wat")
    funky = next(line for line in lines if line.startswith("conv-fun"))
    assert "\x1b" not in funky
    title = funky.split("  ")[-1]
    assert len(title) <= 60
    assert "Red" in title
    code, out, _ = _run(monkeypatch, capsys, server, ["rooms", "--json"], cwd=tmp_path)
    assert code == 0
    payload = json.loads(out)
    ids = [entry["conversation_id"] for entry in payload["rooms"]]
    assert len(ids) > 0
    updated = [entry["updated_at"] for entry in payload["rooms"]]
    assert updated == sorted(updated, reverse=True)
    shorts = [entry["short_id"] for entry in payload["rooms"]]
    assert [line.split("  ")[0] for line in lines] == shorts


def test_not_bound(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    xdg = tmp_path / "xdg"
    code, out, _ = _run(monkeypatch, capsys, server, ["status", "--line"], cwd=work, xdg=xdg)
    assert code == 4
    assert "xmuse 未绑定房间" in out
    code, out, _ = _run(monkeypatch, capsys, server, ["where"], cwd=work, xdg=xdg)
    assert code == 4
    assert "not bound" in out


def test_attach_where_detach_flow(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    work_a = tmp_path / "a"
    work_a.mkdir()
    work_b = tmp_path / "b"
    work_b.mkdir()
    xdg = tmp_path / "xdg"

    code, out, _ = _run(monkeypatch, capsys, server, ["attach", "conv-aaa"], cwd=work_a, xdg=xdg)
    assert code == 0
    assert "已绑定" in out
    code, out, _ = _run(monkeypatch, capsys, server, ["where"], cwd=work_a, xdg=xdg)
    assert code == 0
    assert out.strip() == "conv-aaa-111"

    # Ambiguous prefix lists short ids, exit 4.
    code, out, _ = _run(monkeypatch, capsys, server, ["attach", "conv-"], cwd=work_a, xdg=xdg)
    assert code == 4
    assert "conv-aaa-111" in out
    assert "conv-bbb-222" in out

    # Unknown prefix, exit 4.
    code, out, _ = _run(monkeypatch, capsys, server, ["attach", "nope"], cwd=work_a, xdg=xdg)
    assert code == 4

    # Bare attach picks the most recent room that has modules (aaa, not bbb).
    code, out, _ = _run(monkeypatch, capsys, server, ["attach"], cwd=work_b, xdg=xdg)
    assert code == 0
    code, out, _ = _run(monkeypatch, capsys, server, ["where"], cwd=work_b, xdg=xdg)
    assert code == 0
    assert out.strip() == "conv-aaa-111"

    # A second cwd keeps a separate binding.
    code, out, _ = _run(
        monkeypatch, capsys, server, ["attach", "conv-bbb-222"], cwd=work_b, xdg=xdg
    )
    assert code == 0
    code, out, _ = _run(monkeypatch, capsys, server, ["where"], cwd=work_b, xdg=xdg)
    assert out.strip() == "conv-bbb-222"
    code, out, _ = _run(monkeypatch, capsys, server, ["where"], cwd=work_a, xdg=xdg)
    assert out.strip() == "conv-aaa-111"

    bindings_file = xdg / "xmuse-ctl" / "bindings.json"
    assert bindings_file.is_file()
    assert stat.S_IMODE(os.stat(bindings_file).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(bindings_file.parent).st_mode) == 0o700
    stored = json.loads(bindings_file.read_text(encoding="utf-8"))
    assert stored == {str(work_a): "conv-aaa-111", str(work_b): "conv-bbb-222"}

    code, out, _ = _run(monkeypatch, capsys, server, ["detach"], cwd=work_a, xdg=xdg)
    assert code == 0
    assert "已解绑" in out
    code, out, _ = _run(monkeypatch, capsys, server, ["where"], cwd=work_a, xdg=xdg)
    assert code == 4
    assert "not bound" in out


def test_watch_once_fixed_words_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    code, out, _ = _run(
        monkeypatch, capsys, server, ["watch", "--once", "--room", "conv-watch-001"], cwd=tmp_path
    )
    assert code == 0
    _assert_clean(out)
    lines = out.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("#7 verification alpha ")
    assert "已通过" in lines[0]
    assert lines[1].startswith("#8 progress beta ")
    assert "进行中" in lines[1]
    assert "WATCHMARKER-AGENT-SECRET" not in out


def test_route_paths_match_mod(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    assert isinstance(server, dict)
    state = server["state"]
    assert isinstance(state, dict)
    log = state["log"]
    assert isinstance(log, list)
    log.clear()
    room_id = _room_id("verified")
    assert _run(monkeypatch, capsys, server, ["status", "--room", room_id], cwd=tmp_path)[0] == 0
    assert _run(monkeypatch, capsys, server, ["board", "--room", room_id], cwd=tmp_path)[0] == 0
    assert (
        _run(monkeypatch, capsys, server, ["watch", "--once", "--room", room_id], cwd=tmp_path)[0]
        == 0
    )
    seen = {urlparse(entry).path for entry in log}
    assert f"/api/chat/conversations/{room_id}/board/summary" in seen
    assert f"/api/chat/conversations/{room_id}/board" in seen
    assert f"/api/chat/conversations/{room_id}/board/events" in seen
    assert "/api/chat/rooms" in seen
    for entry in log:
        assert not urlparse(entry).path.endswith("/board/stream")


def _package_sources() -> list[Path]:
    files = sorted(PKG_ROOT.glob("*.py"))
    assert files, "no xmuse_ctl sources found"
    return files


def test_only_get_method() -> None:
    texts = {path: path.read_text(encoding="utf-8") for path in _package_sources()}
    assert any('"GET"' in text for text in texts.values())
    for path, text in texts.items():
        for needle in ('"POST"', '"PUT"', '"DELETE"', '"PATCH"'):
            assert needle not in text, f"{path.name} spells {needle}"


def test_no_tokens_or_state_changing_names() -> None:
    for path in _package_sources():
        text = path.read_text(encoding="utf-8")
        for needle in ("Authorization", "XMUSE_OPERATOR_TOKEN", "Cookie"):
            assert needle not in text, f"{path.name} contains {needle}"


def test_no_server_imports_and_no_process_spawn() -> None:
    for path in _package_sources():
        text = path.read_text(encoding="utf-8")
        assert "xmuse_core" not in text, f"{path.name} mentions xmuse_core"
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if re.match(r"import\s+xmuse\b", stripped) and "xmuse_ctl" not in stripped:
                raise AssertionError(f"{path.name}:{lineno}: server import")
            if re.match(r"from\s+xmuse\s+import", stripped):
                raise AssertionError(f"{path.name}:{lineno}: server import")
            if re.match(r"from\s+xmuse\.", stripped) and "xmuse_ctl" not in stripped:
                raise AssertionError(f"{path.name}:{lineno}: server import")
        assert "subprocess" not in text, f"{path.name} mentions subprocess"
        assert "os.system" not in text, f"{path.name} uses os.system"


def test_stdlib_imports_only() -> None:
    import sys as _sys

    allowed = set(_sys.stdlib_module_names) | {"xmuse_ctl"}
    for path in _package_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] in allowed, (
                        f"{path.name} imports non-stdlib {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.level != 0:
                    continue
                root = (node.module or "").split(".")[0]
                assert root in allowed, f"{path.name} imports non-stdlib {node.module}"


def test_loopback_refused_before_any_request(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    assert isinstance(server, dict)
    state = server["state"]
    assert isinstance(state, dict)
    log = state["log"]
    assert isinstance(log, list)
    log.clear()
    code, out, err = _run(
        monkeypatch,
        capsys,
        server,
        ["status", "--room", "conv-x", "--api-base", "http://example.com"],
        cwd=tmp_path,
    )
    assert code == 2
    assert "base URL must be loopback" in err
    assert log == []
    code, _, err = _run(
        monkeypatch,
        capsys,
        server,
        ["status", "--api-base", "https://127.0.0.1:8201"],
        cwd=tmp_path,
    )
    assert code == 2
    assert "base URL must be loopback" in err
    assert log == []


def test_readme_documents_commands() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    for needle in (
        "rooms",
        "attach",
        "detach",
        "where",
        "status",
        "board",
        "watch",
        "--json",
        "--line",
        "--once",
        "--room",
        "--api-base",
        "XMUSE_API_BASE",
        "XMUSE_WEB_BASE",
        "bindings.json",
        "Decisions stay in the Web",
        "read-only",
        "xmuse 离线",
        "not bound",
        "base URL must be loopback",
        "未知原因",
        "已验收",
        "✓ 已验证",
        "· 待复核",
        "在 Web 打开",
    ):
        assert needle in readme, f"README missing {needle!r}"
    for code in ("0", "2", "3", "4", "5"):
        assert code in readme, f"README missing exit code {code}"


INTEGRATION_SCENARIOS = [
    "integration_conflicted",
    "integration_dependency_upgrade",
    "integration_error",
    "integration_fallback_to_incumbent",
    "integration_gate_failed",
    "integration_integrated",
    "integration_pending_running",
    "review_endorsed_integrated",
]

OLD_SCENARIOS = [stem for stem in EXPECTED_SCENARIOS if stem not in INTEGRATION_SCENARIOS]


def _integration_sidecar_texts(stem: str) -> tuple[list[str], list[str], list[str]]:
    """Paths, output tails and job ids that must never reach host output."""
    sidecar = FIXTURE_DIR / f"{stem}.integration.json"
    paths: list[str] = []
    tails: list[str] = []
    if sidecar.is_file():
        detail = json.loads(sidecar.read_text(encoding="utf-8"))
        for item in detail.get("items", []):
            if not isinstance(item, dict):
                continue
            for conflict in item.get("conflicts", []):
                if isinstance(conflict, dict):
                    path = conflict.get("path")
                    if isinstance(path, str) and path != "":
                        paths.append(path)
        for gate in detail.get("gates", []):
            if not isinstance(gate, dict):
                continue
            tail = gate.get("output_tail")
            if isinstance(tail, dict):
                text = tail.get("text")
                if isinstance(text, str) and text != "":
                    tails.append(text)
    fixture = json.loads((FIXTURE_DIR / f"{stem}.json").read_text(encoding="utf-8"))
    job_ids: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ("integration_id", "applied_verification_id") and isinstance(item, str):
                    if item.startswith("boardintegration_"):
                        job_ids.append(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(fixture)
    return paths, tails, sorted(set(job_ids))


@pytest.mark.parametrize("stem", INTEGRATION_SCENARIOS)
def test_integration_scenarios_show_words_not_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
    stem: str,
) -> None:
    room_id = _room_id(stem)
    paths, tails, job_ids = _integration_sidecar_texts(stem)
    # The conflicted fixtures are where a path would leak: they must have
    # at least one path in the sidecar to make this test meaningful.
    if stem in ("integration_conflicted", "integration_fallback_to_incumbent"):
        assert paths, f"no conflict paths in {stem}.integration.json"
    if stem == "integration_gate_failed":
        assert tails, "no gate output tail in integration_gate_failed.integration.json"
    for argv in (
        ["status", "--line", "--room", room_id],
        ["status", "--room", room_id],
        ["status", "--json", "--room", room_id],
        ["board", "--room", room_id],
        ["board", "--json", "--room", room_id],
        ["watch", "--once", "--room", room_id],
    ):
        code, out, err = _run(monkeypatch, capsys, server, argv, cwd=tmp_path)
        assert code == 0, f"{argv} exited {code}: {out} {err}"
        _assert_clean(out)
        for path in paths:
            assert path not in out, f"{argv} leaked conflict path {path!r} in {stem}"
        for tail in tails:
            assert tail not in out, f"{argv} leaked output_tail in {stem}"
        for job_id in job_ids:
            assert job_id not in out, f"{argv} leaked job id in {stem}"
        assert "boardintegration_" not in out, f"{argv} leaked job id prefix in {stem}"
        if "--json" in argv:
            payload = json.loads(out)
            text = json.dumps(payload, ensure_ascii=False)
            for path in paths:
                assert path not in text
            assert "boardintegration_" not in text


def test_integration_fallback_exact_words(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    room_id = _room_id("integration_fallback_to_incumbent")
    code, out, _ = _run(monkeypatch, capsys, server, ["board", "--room", room_id], cwd=tmp_path)
    assert code == 0
    m1_line = next(line for line in out.splitlines() if line.startswith("m1 "))
    assert "集成冲突 1 路径·分支为旧版本" in m1_line
    # reviews are off here: accepted shows as 已验证, integrated as 已集成.
    assert "已验证 3 · 已集成 2" in out
    assert "集成分支 8d191a5e" in out
    code, out, _ = _run(
        monkeypatch, capsys, server, ["status", "--line", "--room", room_id], cwd=tmp_path
    )
    assert code == 0
    assert "已集成 2" in out
    # The job itself integrated: no job word on the status line.
    assert "集成冲突" not in out


def test_integration_gate_failed_exact_words(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    room_id = _room_id("integration_gate_failed")
    code, out, _ = _run(monkeypatch, capsys, server, ["board", "--room", room_id], cwd=tmp_path)
    assert code == 0
    m2_line = next(line for line in out.splitlines() if line.startswith("m2 "))
    assert "门禁失败·嫌疑" in m2_line
    assert "·未入分支" in m2_line
    assert "集成门禁失败" in out  # lead room-level item label, no job id
    assert "boardintegration_" not in out
    code, out, _ = _run(
        monkeypatch, capsys, server, ["status", "--line", "--room", room_id], cwd=tmp_path
    )
    assert code == 0
    assert "已集成 1" in out
    assert "集成门禁失败" in out


def test_integration_error_exact_words(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    room_id = _room_id("integration_error")
    code, out, _ = _run(monkeypatch, capsys, server, ["board", "--room", room_id], cwd=tmp_path)
    assert code == 0
    m1_line = next(line for line in out.splitlines() if line.startswith("m1 "))
    assert "集成异常·自动重试" in m1_line
    assert "·未入分支" in m1_line
    assert "集成异常（宿主自动重试）" in out  # operator room-level item, no target
    code, out, _ = _run(
        monkeypatch, capsys, server, ["status", "--line", "--room", room_id], cwd=tmp_path
    )
    assert code == 0
    assert "集成异常" in out
    assert "boardintegration_" not in out


def test_integrations_off_shows_no_integration_word(tmp_path: Path) -> None:
    sys.path.insert(0, str(CTL_ROOT))
    from xmuse_ctl import api as ctl_api
    from xmuse_ctl import render as ctl_render

    # Old quiet fixture with the flag flipped off: no integration word
    # anywhere, even in JSON labels.
    fixture = json.loads((FIXTURE_DIR / "verified.json").read_text(encoding="utf-8"))
    summary_payload = dict(fixture["summary"])
    summary_payload["capabilities"] = {"verification": 1, "reviews": 0, "integrations": 0}
    board_payload = dict(fixture["projection"])
    board_payload["capabilities"] = {"verification": 1, "reviews": 0, "integrations": 0}
    summary = ctl_api.normalize_summary(summary_payload)
    board = ctl_api.normalize_board(board_payload)
    assert summary is not None and board is not None
    for text in (
        ctl_render.status_line(summary),
        ctl_render.status_block(summary),
        ctl_render.board_text(board, "http://127.0.0.1:3000"),
        json.dumps(ctl_render.board_json(board, "http://127.0.0.1:3000"), ensure_ascii=False),
        json.dumps(ctl_render.status_json(summary), ensure_ascii=False),
    ):
        assert "集成" not in text
        assert "集成分支" not in text
        assert "门禁失败" not in text
    # Fallback data with the flag off: module words hidden even though the
    # payload still carries conflicted state (stale attention aside).
    fallback = json.loads(
        (FIXTURE_DIR / "integration_fallback_to_incumbent.json").read_text(encoding="utf-8")
    )
    fb_board_payload = dict(fallback["projection"])
    fb_board_payload["capabilities"] = {"verification": 1, "reviews": 0, "integrations": 0}
    fb_board = ctl_api.normalize_board(fb_board_payload)
    assert fb_board is not None
    fb_text = ctl_render.board_text(fb_board, "http://127.0.0.1:3000")
    assert "集成冲突" not in fb_text
    assert "分支为旧版本" not in fb_text


@pytest.mark.parametrize("stem", OLD_SCENARIOS)
def test_old_scenarios_status_line_has_no_integration_word(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
    stem: str,
) -> None:
    room_id = _room_id(stem)
    code, out, _ = _run(
        monkeypatch, capsys, server, ["status", "--line", "--room", room_id], cwd=tmp_path
    )
    assert code == 0
    assert "集成" not in out
    assert "集成分支" not in out


def test_never_fetch_integration_detail() -> None:
    for path in _package_sources():
        text = path.read_text(encoding="utf-8")
        assert "board/integrations" not in text, f"{path.name} references §5.3"


def test_status_board_watch_never_hit_integration_detail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    server: object,
    tmp_path: Path,
) -> None:
    assert isinstance(server, dict)
    state = server["state"]
    assert isinstance(state, dict)
    log = state["log"]
    assert isinstance(log, list)
    log.clear()
    room_id = _room_id("integration_conflicted")
    assert _run(monkeypatch, capsys, server, ["status", "--room", room_id], cwd=tmp_path)[0] == 0
    assert _run(monkeypatch, capsys, server, ["board", "--room", room_id], cwd=tmp_path)[0] == 0
    assert (
        _run(monkeypatch, capsys, server, ["watch", "--once", "--room", room_id], cwd=tmp_path)[0]
        == 0
    )
    for entry in log:
        assert "board/integrations" not in entry


def test_vocabulary_matches_hosts() -> None:
    sys.path.insert(0, str(CTL_ROOT))
    from xmuse_ctl import labels as ctl_labels

    assert ctl_labels.ATTENTION_REASON_LABELS["board_attention_integration_error"] == (
        "集成异常（宿主自动重试）"
    )
    assert (
        ctl_labels.ATTENTION_REASON_LABELS["board_attention_integration_conflict"]
        == "集成冲突待处理"
    )
    assert (
        ctl_labels.ATTENTION_REASON_LABELS["board_attention_integration_gate_failed"]
        == "集成门禁失败"
    )
    assert ctl_labels.INTEGRATION_REASON_LABELS["board_integration_conflict"] == "集成冲突"
    assert ctl_labels.INTEGRATION_REASON_LABELS["board_integration_gate_failed"] == "集成门禁未通过"
    assert (
        ctl_labels.INTEGRATION_REASON_LABELS["board_integration_waiting_for_dependency"]
        == "等待依赖集成"
    )
    assert (
        ctl_labels.INTEGRATION_REASON_LABELS["board_integration_would_drop_accepted"]
        == "集成会丢失已验收代码，已停止"
    )
    assert (
        ctl_labels.INTEGRATION_REASON_LABELS["board_integration_attempts_exhausted"]
        == "集成多次失败"
    )
    # One table per code base: the TS sources must carry the same words.
    claude_labels = (REPO_ROOT / "integrations" / "claude-code" / "src" / "labels.ts").read_text(
        encoding="utf-8"
    )
    for needle in (
        "集成异常（宿主自动重试）",
        "集成冲突待处理",
        "集成门禁失败",
        "集成冲突",
        "集成门禁未通过",
        "等待依赖集成",
        "集成会丢失已验收代码，已停止",
        "集成多次失败",
        "排队集成",
        "集成中",
        "已集成",
        "门禁失败·嫌疑",
        "集成异常·自动重试",
        "分支为旧版本",
        "未入分支",
    ):
        assert needle in claude_labels, f"claude labels.ts missing {needle!r}"


def test_execution_reason_codes_have_fixed_labels() -> None:
    from xmuse_ctl import labels

    for code in (
        "execution_gate_failed",
        "execution_gate_timeout",
        "execution_gate_memory_limit",
        "execution_gate_process_limit",
        "execution_gate_scratch_limit",
        "execution_gate_resource_probe_failed",
        "execution_cancelled",
        "execution_git_metadata_invalid",
        "execution_sandbox_unavailable",
        "execution_gate_profile_marker_invalid",
        "execution_toolchain_capability_drift",
        "execution_repo_busy",
    ):
        label = labels.reason_label(code)
        assert code not in label
        assert "未知原因" not in label
    # A code that is new but in the family stays an execution problem, with the code shown.
    assert labels.reason_label("execution_future_thing") == "执行环境问题（execution_future_thing）"
    assert labels.reason_label("something_else") == "未知原因（something_else）"
