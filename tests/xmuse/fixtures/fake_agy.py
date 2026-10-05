#!/usr/bin/env python3
"""Scripted ``agy`` CLI used by Room agy transport tests.

This is not a provider: it never contacts any model endpoint except the Room
MCP URL injected through the environment.  It speaks the ``agy
--input-format stream-json --output-format stream-json`` protocol: it prints
one ``init`` line at startup (honoring ``--conversation <id>``), then reads
one NDJSON ``user`` message per stdin line and runs one turn each, keeping the
conversation id across turns.  Room truth is committed only through
``chat_room_submit_outcome`` over HTTP, exactly like a real CLI agent.

Every observable fact is appended as one JSON line to the file named by
``XMUSE_TEST_AGY_LOG`` so the test process can assert on the CLI agent's
exact experience.  The full argv is appended to ``XMUSE_TEST_AGY_ARGV_LOG``
when set, so resume tests can assert on ``--conversation``.

Modes (``XMUSE_TEST_AGY_MODE``):

- ``normal``    draft + outcome MCP tool steps with a real Room MCP submission.
- ``tool``      same, with a ``run_command`` tool step before the outcome call.
- ``silent``    end the turn with a SUCCESS result but submit no outcome.
- ``forgetful`` answer the observation in plain text only, then submit the
  stored outcome when the next (reminder) prompt arrives without context.
- ``error``     end the turn with an ERROR result and no outcome.
- ``exit``      exit mid-turn without printing a result.

``XMUSE_TEST_AGY_START_FAILURES=N`` (needs the argv log) makes the first N
process starts exit before ``init``, like agy's startup eligibility check
failing on a lost network request.
"""

from __future__ import annotations

import json
import os
import re
import signal
import sys
import time
import urllib.request
import uuid
from typing import Any

ROOM_OUTCOME_TOOL_NAME = "chat_room_submit_outcome"

_LOG_PATH = os.environ.get("XMUSE_TEST_AGY_LOG", "")
_ARGV_LOG_PATH = os.environ.get("XMUSE_TEST_AGY_ARGV_LOG", "")
_MODE = os.environ.get("XMUSE_TEST_AGY_MODE", "normal")
_MCP_URL = os.environ.get("XMUSE_TEST_AGY_MCP_URL", "")
_CONTENT = os.environ.get("XMUSE_TEST_AGY_CONTENT", "agy durable answer")
_FOLLOWUP_CONTENT = os.environ.get("XMUSE_TEST_AGY_FOLLOWUP_CONTENT", "agy follow-up answer")
_DRAFT = os.environ.get("XMUSE_TEST_AGY_DRAFT", "agy draft answer")
_OUTCOME_TYPE = os.environ.get("XMUSE_TEST_AGY_OUTCOME_TYPE", "respond")
_STEP_DELAY_S = float(os.environ.get("XMUSE_TEST_AGY_STEP_DELAY_S", "0.05"))
_HTTP_TIMEOUT_S = float(os.environ.get("XMUSE_TEST_AGY_HTTP_TIMEOUT_S", "30"))

_CONTEXT_RE = re.compile(r"<xmuse_context>\n(?P<body>.*)\n</xmuse_context>", re.DOTALL)


def _log(event: str, **fields: Any) -> None:
    if not _LOG_PATH:
        return
    line = json.dumps({"event": event, **fields}, sort_keys=True, default=str)
    with open(_LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()


def _secret_env_names() -> list[str]:
    return sorted(
        key
        for key in os.environ
        if key in {"ANTHROPIC_API_KEY"}
        or (key.startswith(("XMUSE_", "MEMORYOS_")) and key.endswith(("_API_KEY", "_TOKEN")))
    )


def _parse_argv(argv: list[str]) -> tuple[str | None, str | None]:
    """Return the (model, resume conversation id) from agy CLI arguments."""

    model: str | None = None
    resume: str | None = None
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--model" and index + 1 < len(argv):
            model = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--model="):
            model = arg.split("=", 1)[1]
            index += 1
            continue
        if arg == "--conversation" and index + 1 < len(argv):
            resume = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--conversation="):
            resume = arg.split("=", 1)[1]
            index += 1
            continue
        index += 1
    return model, resume


def _emit(event: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(event, sort_keys=True) + "\n")
    sys.stdout.flush()


def _step(conversation_id: str, index: int, **fields: Any) -> None:
    _emit(
        {
            "event": "step_update",
            "step_update": {"conversation_id": conversation_id, "step_index": index, **fields},
        }
    )


def _submit_outcome(context: dict[str, Any] | None, content: str) -> tuple[Any, int]:
    if context is None:
        return {"error": "xmuse_context_missing"}, 0
    if not _MCP_URL:
        return {"error": "room_mcp_url_missing"}, 0
    arguments = {
        "conversation_id": context["conversation_id"],
        "participant_id": context["participant_id"],
        "god_session_id": context["god_session_id"],
        "observation_id": context["observation_id"],
        "observation_batch_id": context["durable_outcome"]["observation_batch_id"],
        "lease_token": context["lease_token"],
        "client_request_id": context["client_request_id"],
        "outcome_type": _OUTCOME_TYPE,
        "outcome_payload": {"content": content},
    }
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "outcome-call-1",
            "method": "tools/call",
            "params": {"name": ROOM_OUTCOME_TOOL_NAME, "arguments": arguments},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        _MCP_URL,
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_S) as response:
        payload = json.loads(response.read().decode("utf-8"))
        return payload.get("result", {}).get("structuredContent", payload), response.status


def _parse_input(line: str) -> tuple[str, dict[str, Any] | None]:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        return "", None
    prompt = ""
    if isinstance(message, dict):
        content = (
            ((message.get("message") or {}).get("content"))
            if isinstance(message.get("message"), dict)
            else None
        )
        if isinstance(content, list):
            prompt = "".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
    context: dict[str, Any] | None = None
    match = _CONTEXT_RE.search(prompt)
    if match is not None:
        try:
            parsed = json.loads(match.group("body"))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            context = parsed
    return prompt, context


def main() -> int:
    argv = sys.argv[1:]
    model, resume = _parse_argv(argv)
    conversation_id = resume or f"agy-conversation-{uuid.uuid4().hex}"

    def _on_sigterm(*_args: Any) -> None:
        _log("sigterm_received", conversation_id=conversation_id)
        os._exit(0)

    signal.signal(signal.SIGTERM, _on_sigterm)
    if _ARGV_LOG_PATH:
        with open(_ARGV_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(
                json.dumps({"argv": argv, "conversation_id": conversation_id}, sort_keys=True)
                + "\n"
            )
        start_failures = int(os.environ.get("XMUSE_TEST_AGY_START_FAILURES", "0"))
        with open(_ARGV_LOG_PATH, encoding="utf-8") as handle:
            starts = sum(1 for _ in handle)
        if starts <= start_failures:
            _log("startup_failed", conversation_id=conversation_id, start=starts)
            print("error: Eligibility check failed: EOF", file=sys.stderr, flush=True)
            return 1
    _log(
        "startup",
        mode=_MODE,
        conversation_id=conversation_id,
        resumed=resume is not None,
        model=model,
        cwd=os.getcwd(),
        pid=os.getpid(),
        last_arg=argv[-1] if argv else None,
        secret_env_names=_secret_env_names(),
        has_operator_token="XMUSE_OPERATOR_TOKEN" in os.environ,
        has_memoryos_api_key=(
            "XMUSE_MEMORYOS_API_KEY" in os.environ or "MEMORYOS_API_KEY" in os.environ
        ),
        has_anthropic_api_key="ANTHROPIC_API_KEY" in os.environ,
    )
    _emit(
        {
            "event": "init",
            "conversation_id": conversation_id,
            "init": {
                "model": model,
                "cwd": os.getcwd(),
                "tools": ["call_mcp_tool", "run_command", "view_file"],
                "permission_mode": "always-proceed",
            },
        }
    )

    pending_context: dict[str, Any] | None = None
    turn_count = 0
    stdin = sys.stdin
    while True:
        line = stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        turn_count += 1
        prompt, context = _parse_input(line)
        if context is not None:
            pending_context = context
        _log(
            "prompt_received",
            conversation_id=conversation_id,
            turn=turn_count,
            mode=_MODE,
            has_context=context is not None,
            observation_id=(context or {}).get("observation_id"),
            participant_id=(context or {}).get("participant_id"),
        )
        content = _CONTENT if turn_count == 1 else _FOLLOWUP_CONTENT
        step_index = 0
        _step(conversation_id, step_index, state="DONE", step_type="user_input")
        step_index += 1

        if _MODE == "exit":
            _log("mid_turn_exit", conversation_id=conversation_id, turn=turn_count)
            os._exit(1)

        if _MODE == "error":
            _step(
                conversation_id,
                step_index,
                state="ACTIVE",
                step_type="agent_response",
                text_delta=_DRAFT,
            )
            _emit(
                {
                    "event": "result",
                    "result": {
                        "conversation_id": conversation_id,
                        "status": "ERROR",
                        "response": "",
                        "error": "fake agy turn failed",
                        "duration_seconds": 0.1,
                        "num_turns": turn_count,
                        "usage": {
                            "input_tokens": 1,
                            "output_tokens": 1,
                            "thinking_tokens": 0,
                            "cache_read_tokens": 0,
                            "total_tokens": 2,
                        },
                    },
                }
            )
            _log("result_sent", conversation_id=conversation_id, status="ERROR")
            continue

        if _MODE == "silent":
            _step(
                conversation_id,
                step_index,
                state="ACTIVE",
                step_type="agent_response",
                text_delta="silent turn without durable outcome",
            )
            time.sleep(_STEP_DELAY_S)
            _emit(
                {
                    "event": "result",
                    "result": {
                        "conversation_id": conversation_id,
                        "status": "SUCCESS",
                        "response": "silent turn without durable outcome",
                        "duration_seconds": 0.1,
                        "num_turns": turn_count,
                        "usage": {
                            "input_tokens": 1,
                            "output_tokens": 1,
                            "thinking_tokens": 0,
                            "cache_read_tokens": 0,
                            "total_tokens": 2,
                        },
                    },
                }
            )
            _log("turn_finished_without_outcome", conversation_id=conversation_id, turn=turn_count)
            continue

        if _MODE == "forgetful" and context is not None:
            _step(
                conversation_id,
                step_index,
                state="ACTIVE",
                step_type="agent_response",
                text_delta=_DRAFT,
            )
            time.sleep(_STEP_DELAY_S)
            _emit(
                {
                    "event": "result",
                    "result": {
                        "conversation_id": conversation_id,
                        "status": "SUCCESS",
                        "response": _DRAFT,
                        "duration_seconds": 0.1,
                        "num_turns": turn_count,
                        "usage": {
                            "input_tokens": 1,
                            "output_tokens": 1,
                            "thinking_tokens": 0,
                            "cache_read_tokens": 0,
                            "total_tokens": 2,
                        },
                    },
                }
            )
            _log("turn_finished_without_outcome", conversation_id=conversation_id, turn=turn_count)
            continue

        # Normal outcome path (also used for the forgetful reminder turn, which
        # arrives without context while pending_context is stored).
        _step(
            conversation_id,
            step_index,
            state="ACTIVE",
            step_type="agent_response",
            text_delta=_DRAFT,
        )
        time.sleep(_STEP_DELAY_S)
        step_index += 1
        if _MODE == "tool":
            tool_params: dict[str, Any] = {"command": "ls"}
            _step(
                conversation_id,
                step_index,
                state="ACTIVE",
                step_type="tool",
                tool_name="run_command",
                tool_info={"name": "run_command", "parameters": tool_params},
            )
            time.sleep(_STEP_DELAY_S)
            _step(
                conversation_id,
                step_index,
                state="DONE",
                step_type="tool",
                tool_name="run_command",
                tool_info={
                    "name": "run_command",
                    "parameters": tool_params,
                    "output": "api\nclient\n",
                },
            )
            _log("non_outcome_tool_steps", conversation_id=conversation_id, mode=_MODE)
            step_index += 1
        outcome_params: dict[str, Any] = {"server": "xmuse-room", "tool": ROOM_OUTCOME_TOOL_NAME}
        _step(
            conversation_id,
            step_index,
            state="ACTIVE",
            step_type="tool",
            tool_name="call_mcp_tool",
            tool_info={"name": "call_mcp_tool", "parameters": outcome_params},
        )
        payload, status = _submit_outcome(pending_context, content)
        _log("outcome_submission", http_status=status, result=payload)
        _step(
            conversation_id,
            step_index,
            state="DONE",
            step_type="tool",
            tool_name="call_mcp_tool",
            tool_info={"name": "call_mcp_tool", "parameters": outcome_params, "output": "ok"},
        )
        step_index += 1
        time.sleep(_STEP_DELAY_S)
        _emit(
            {
                "event": "result",
                "result": {
                    "conversation_id": conversation_id,
                    "status": "SUCCESS",
                    "response": content,
                    "duration_seconds": 0.1,
                    "num_turns": turn_count,
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "thinking_tokens": 0,
                        "cache_read_tokens": 0,
                        "total_tokens": 15,
                    },
                },
            }
        )
        _log("result_sent", conversation_id=conversation_id, status="SUCCESS", turn=turn_count)
    _log("agent_exit", conversation_id=conversation_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
