"""xmuse-ctl command line. Read-only: every command prints structured
text (or a stable JSON object with --json). Decisions stay in the Web.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import api, binding
from . import hook as hook_module
from .render import (
    board_json,
    board_text,
    event_line,
    rooms_json,
    rooms_text,
    status_block,
    status_json,
    status_line,
)
from .sanitize import safe, short_room


class _Exit(Exception):
    """A command outcome with an exit code and an optional message."""

    def __init__(self, code: int, message: str | None = None, stream: str = "stdout"):
        super().__init__(message)
        self.code = code
        self.message = message
        self.stream = stream


def _api_base(args: argparse.Namespace) -> str:
    raw = args.api_base or os.environ.get("XMUSE_API_BASE", "") or api.DEFAULT_API_BASE
    return raw.strip()


def _web_base() -> str:
    raw = os.environ.get("XMUSE_WEB_BASE", "") or api.DEFAULT_WEB_BASE
    return raw.strip()


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _fetch_rooms(base: str) -> list[dict[str, str]]:
    try:
        payload = api.get_json(base, api.ROOMS_PATH)
    except api.Offline as exc:
        raise _Exit(3, "xmuse 离线") from exc
    except (api.BadShape, api.UnknownRoom) as exc:
        raise _Exit(5, "unexpected response shape", "stderr") from exc
    rooms = api.normalize_rooms(payload)
    if rooms is None:
        raise _Exit(5, "unexpected response shape", "stderr")
    return api.sort_rooms_newest(rooms)


def _match_rooms(rooms: list[dict[str, str]], want: str) -> tuple[str, list[dict[str, str]]]:
    exact = [room for room in rooms if room["conversation_id"] == want]
    if exact:
        return (exact[0]["conversation_id"], [])
    matches = [room for room in rooms if room["conversation_id"].startswith(want)]
    if len(matches) == 1:
        return (matches[0]["conversation_id"], [])
    return ("", matches)


def _resolve_room(base: str, room_arg: str | None) -> str:
    if room_arg is not None and room_arg.strip() != "":
        want = room_arg.strip()
        rooms = _fetch_rooms(base)
        target, matches = _match_rooms(rooms, want)
        if target != "":
            return target
        if not matches:
            raise _Exit(4, "xmuse 绑定失败: 未找到房间")
        listed = "\n".join(short_room(room["conversation_id"]) for room in matches)
        raise _Exit(4, "xmuse 绑定失败: 前缀匹配到多个房间\n" + listed)
    bound = binding.load_bindings().get(os.getcwd())
    if bound is None:
        raise _Exit(4, "xmuse 未绑定房间")
    return bound


def _fetch_summary(base: str, conversation_id: str) -> dict[str, object]:
    try:
        payload = api.get_json(base, api.summary_path(conversation_id))
    except api.Offline as exc:
        raise _Exit(3, "xmuse 离线") from exc
    except api.UnknownRoom as exc:
        raise _Exit(4, "xmuse 未找到房间") from exc
    except api.BadShape as exc:
        raise _Exit(5, "unexpected response shape", "stderr") from exc
    summary = api.normalize_summary(payload)
    if summary is None:
        raise _Exit(5, "unexpected response shape", "stderr")
    return summary


def _fetch_board(base: str, conversation_id: str) -> dict[str, object]:
    try:
        payload = api.get_json(base, api.board_path(conversation_id))
    except api.Offline as exc:
        raise _Exit(3, "xmuse 离线") from exc
    except api.UnknownRoom as exc:
        raise _Exit(4, "xmuse 未找到房间") from exc
    except api.BadShape as exc:
        raise _Exit(5, "unexpected response shape", "stderr") from exc
    board = api.normalize_board(payload)
    if board is None:
        raise _Exit(5, "unexpected response shape", "stderr")
    return board


def _cmd_rooms(base: str, args: argparse.Namespace) -> int:
    rooms = _fetch_rooms(base)
    if args.json:
        _print_json(rooms_json(rooms))
    else:
        print(rooms_text(rooms))
    return 0


def _cmd_attach(base: str, args: argparse.Namespace) -> int:
    want = args.prefix.strip() if args.prefix is not None and args.prefix.strip() != "" else None
    rooms = _fetch_rooms(base)
    target = ""
    if want is None:
        # Most recent room that has modules, as the mod auto-binds.
        for room in rooms[:8]:
            try:
                summary = _fetch_summary(base, room["conversation_id"])
            except _Exit as exc:
                if exc.code == 3:
                    raise
                continue
            modules_total = summary["modules_total"]
            assert isinstance(modules_total, int)
            if modules_total > 0:
                target = room["conversation_id"]
                break
        if target == "":
            raise _Exit(4, "xmuse 绑定失败: 暂无房间")
    else:
        picked, matches = _match_rooms(rooms, want)
        if picked != "":
            target = picked
        elif not matches:
            raise _Exit(4, "xmuse 绑定失败: 未找到房间")
        else:
            listed = "\n".join(short_room(room["conversation_id"]) for room in matches)
            raise _Exit(4, "xmuse 绑定失败: 前缀匹配到多个房间\n" + listed)
    stored = binding.load_bindings()
    stored[os.getcwd()] = target
    binding.save_bindings(stored)
    if args.json:
        _print_json({"conversation_id": safe(target, 128), "short_id": short_room(target)})
    else:
        print("xmuse 已绑定 " + short_room(target))
    return 0


def _cmd_detach(args: argparse.Namespace) -> int:
    stored = binding.load_bindings()
    if os.getcwd() in stored:
        del stored[os.getcwd()]
        binding.save_bindings(stored)
    if args.json:
        _print_json({"bound": False})
    else:
        print("xmuse 已解绑")
    return 0


def _cmd_where(args: argparse.Namespace) -> int:
    bound = binding.load_bindings().get(os.getcwd())
    if bound is None:
        raise _Exit(4, "not bound")
    if args.json:
        _print_json({"conversation_id": safe(bound, 128)})
    else:
        print(safe(bound, 128))
    return 0


def _cmd_status(base: str, args: argparse.Namespace) -> int:
    conversation_id = _resolve_room(base, args.room)
    summary = _fetch_summary(base, conversation_id)
    if args.json:
        _print_json(status_json(summary))
    elif args.line:
        print(status_line(summary))
    else:
        print(status_block(summary))
    return 0


def _cmd_board(base: str, args: argparse.Namespace) -> int:
    conversation_id = _resolve_room(base, args.room)
    board = _fetch_board(base, conversation_id)
    if args.json:
        _print_json(board_json(board, _web_base()))
    else:
        print(board_text(board, _web_base()))
    return 0


def _cmd_hook(base: str, args: argparse.Namespace) -> int:
    host = args.host if isinstance(args.host, str) else ""
    event = args.event if isinstance(args.event, str) else ""
    return hook_module.main_hook(host, event, base)


def _fetch_events(
    base: str, conversation_id: str, after_seq: int, wait: int, revision: str | None
) -> dict[str, object]:
    query = {"after_seq": str(max(0, after_seq)), "limit": "100", "wait": str(wait)}
    if revision is not None and revision != "":
        query["revision"] = revision
    timeout = float(wait) + 15.0
    try:
        payload = api.get_json(base, api.board_path(conversation_id) + "/events", query, timeout)
    except api.Offline as exc:
        raise _Exit(3, "xmuse 离线") from exc
    except api.UnknownRoom as exc:
        raise _Exit(4, "xmuse 未找到房间") from exc
    except api.BadShape as exc:
        raise _Exit(5, "unexpected response shape", "stderr") from exc
    page = api.normalize_events_page(payload)
    if page is None:
        raise _Exit(5, "unexpected response shape", "stderr")
    return page


def _cmd_watch(base: str, args: argparse.Namespace) -> int:
    conversation_id = _resolve_room(base, args.room)
    board = _fetch_board(base, conversation_id)
    board_seq = board["board_seq"]
    assert isinstance(board_seq, int)
    revision = board["revision"]
    assert isinstance(revision, str)
    if args.once:
        page = _fetch_events(base, conversation_id, board_seq, 0, revision)
        events = page["events"]
        assert isinstance(events, list)
        lines = []
        for event in events:
            assert isinstance(event, dict)
            lines.append(event_line(event))
        if lines:
            print("\n".join(lines))
        return 0
    after_seq = board_seq
    current_revision: str | None = revision
    backoff = 0
    while True:
        try:
            page = _fetch_events(base, conversation_id, after_seq, 25, current_revision)
        except _Exit:
            delay = min(30, 2**backoff)
            backoff += 1
            time.sleep(delay)
            continue
        backoff = 0
        if page["reset"] is True:
            board = _fetch_board(base, conversation_id)
            after_seq = board["board_seq"]
            assert isinstance(after_seq, int)
            current_revision = board["revision"]
            assert isinstance(current_revision, str)
            continue
        events = page["events"]
        assert isinstance(events, list)
        for event in events:
            assert isinstance(event, dict)
            seq = event["seq"]
            assert isinstance(seq, int)
            print(event_line(event), flush=True)
            if seq > after_seq:
                after_seq = seq
        page_revision = page["revision"]
        if isinstance(page_revision, str) and page_revision != "":
            current_revision = page_revision
        else:
            board_seq_now = page["board_seq"]
            assert isinstance(board_seq_now, int)
            if board_seq_now > after_seq:
                after_seq = board_seq_now
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the xmuse-ctl argument parser."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-base", default=None, help="xmuse chat API base URL (loopback only)")
    common.add_argument("--room", default=None, help="room id or unique prefix (overrides binding)")
    common.add_argument("--json", action="store_true", help="print a stable JSON object instead")
    parser = argparse.ArgumentParser(prog="xmuse-ctl", description="Read-only xmuse board client.")
    sub = parser.add_subparsers(dest="command", required=True)
    rooms_p = sub.add_parser("rooms", parents=[common], help="list rooms, newest first")
    rooms_p.set_defaults(func=_cmd_rooms)
    attach_p = sub.add_parser("attach", parents=[common], help="bind the cwd to a room")
    attach_p.add_argument("prefix", nargs="?", default=None, help="room id or unique prefix")
    attach_p.set_defaults(func=_cmd_attach)
    detach_p = sub.add_parser("detach", parents=[common], help="clear the cwd binding")
    detach_p.set_defaults(func=_cmd_detach)
    where_p = sub.add_parser("where", parents=[common], help="print the bound room")
    where_p.set_defaults(func=_cmd_where)
    status_p = sub.add_parser("status", parents=[common], help="one structured status block")
    status_p.add_argument("--line", action="store_true", help="print only the one-line status")
    status_p.set_defaults(func=_cmd_status)
    board_p = sub.add_parser("board", parents=[common], help="module table with attention")
    board_p.set_defaults(func=_cmd_board)
    watch_p = sub.add_parser("watch", parents=[common], help="long-poll board events")
    watch_p.add_argument("--once", action="store_true", help="print new events once and exit")
    watch_p.set_defaults(func=_cmd_watch)
    hook_p = sub.add_parser("hook", help="opt-in status line for agy/dsh hooks")
    hook_p.add_argument("--host", default="", help="host the line is injected into: agy or dsh")
    hook_p.add_argument("--event", default="UserPromptSubmit", help="dsh hook event name")
    hook_p.add_argument("--api-base", default=None, help="xmuse chat API base URL (loopback only)")
    hook_p.set_defaults(func=_cmd_hook)
    return parser


def _run_command(base: str, args: argparse.Namespace) -> int:
    func = args.func
    name = getattr(func, "__name__", "")
    if name in ("_cmd_detach", "_cmd_where"):
        return int(func(args))
    return int(func(base, args))


def main(argv: list[str] | None = None) -> int:
    """Entry point for the xmuse-ctl console script."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        return 2
    if getattr(args, "command", None) == "hook":
        # The hook is the only command that always exits 0 and stays
        # silent on stderr: even a refused base URL yields "{}".
        try:
            return _cmd_hook(_api_base(args), args)
        except Exception:
            print("{}")
            return 0
    base = _api_base(args)
    if not api.is_loopback_base(base):
        print("base URL must be loopback", file=sys.stderr)
        return 2
    try:
        return _run_command(base, args)
    except _Exit as exc:
        if exc.message is not None:
            if exc.stream == "stderr":
                print(exc.message, file=sys.stderr)
            else:
                print(exc.message)
        return exc.code
    except KeyboardInterrupt:
        return 0
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
