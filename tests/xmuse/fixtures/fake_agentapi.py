#!/usr/bin/env python3
"""Scripted ``agentapi`` CLI used by Room Antigravity transport tests.

This is not a provider: it never contacts the Antigravity language server or any
network endpoint except the Room MCP URL injected through the environment, and
its stdout is the CLI's JSON contract (``new-conversation`` prints the created
conversation id; ``send-message`` prints an accepted acknowledgement).  Turn
progress is materialized as transcript steps under
``$XMUSE_TEST_AGENTAPI_BRAIN/<conversation_id>/.system_generated/logs/`` exactly
where the transport polls, and Room truth is committed only through
``chat_room_submit_outcome`` over HTTP.

Every observable fact is appended as one JSON line to the file named by
``XMUSE_TEST_AGENTAPI_LOG`` so the test process can assert on the CLI agent's
exact experience.

Modes (``XMUSE_TEST_AGENTAPI_MODE``):

- ``normal``     draft, one outcome tool call with a real MCP submission, done.
- ``tool-steps`` same, with a non-outcome tool call before the outcome call.
- ``silent``     finish the turn with a terminal step but submit no outcome.
- ``slow``       enqueue the turn and never finish it (SIGTERM terminates).
- ``mute``       print nothing and never finish it (SIGTERM terminates).
"""

from __future__ import annotations

import json
import os
import re
import signal
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOM_OUTCOME_TOOL_NAME = "chat_room_submit_outcome"
OUTCOME_TOOL_TITLE = "mcp__xmuse-room__chat_room_submit_outcome"

_LOG_PATH = os.environ.get("XMUSE_TEST_AGENTAPI_LOG", "")
_MODE = os.environ.get("XMUSE_TEST_AGENTAPI_MODE", "normal")
_MCP_URL = os.environ.get("XMUSE_TEST_AGENTAPI_MCP_URL", "")
_BRAIN = os.environ.get("XMUSE_TEST_AGENTAPI_BRAIN", "")
_COUNTER = os.environ.get("XMUSE_TEST_AGENTAPI_COUNTER", "")
_CONTENT = os.environ.get("XMUSE_TEST_AGENTAPI_CONTENT", "antigravity durable answer")
_FOLLOWUP_CONTENT = os.environ.get(
    "XMUSE_TEST_AGENTAPI_FOLLOWUP_CONTENT", "antigravity follow-up answer"
)
_DRAFT = os.environ.get("XMUSE_TEST_AGENTAPI_DRAFT", "antigravity draft answer")
_OUTCOME_TYPE = os.environ.get("XMUSE_TEST_AGENTAPI_OUTCOME_TYPE", "respond")
_STEP_DELAY_S = float(os.environ.get("XMUSE_TEST_AGENTAPI_STEP_DELAY_S", "0.3"))
_HTTP_TIMEOUT_S = float(os.environ.get("XMUSE_TEST_AGENTAPI_HTTP_TIMEOUT_S", "30"))

_CONTEXT_RE = re.compile(r"<xmuse_context>\n(?P<body>.*)\n</xmuse_context>", re.DOTALL)
_LOG_RELATIVE = Path(".system_generated") / "logs" / "transcript.jsonl"


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


def _transcript_path(conversation_id: str) -> Path:
    return Path(_BRAIN) / conversation_id / _LOG_RELATIVE


def _append_steps(conversation_id: str, steps: list[dict[str, Any]]) -> None:
    path = _transcript_path(conversation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        for step in steps:
            handle.write(json.dumps(step, sort_keys=True) + "\n")
        handle.flush()


def _count_steps(conversation_id: str) -> int:
    try:
        text = _transcript_path(conversation_id).read_text(encoding="utf-8")
    except OSError:
        return 0
    return len([line for line in text.splitlines() if line.strip()])


def _allocate_conversation_id() -> str:
    if _COUNTER:
        path = Path(_COUNTER)
        try:
            current = int(path.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            current = 0
        current += 1
        path.write_text(str(current), encoding="utf-8")
        return f"fake-conversation-{current}"
    return f"fake-conversation-{os.getpid()}"


def _step(
    index: int,
    *,
    source: str,
    type_: str,
    status: str,
    content: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "step_index": index,
        "source": source,
        "type": type_,
        "status": status,
        "created_at": time.time(),
        "content": content,
    }
    if tool_calls:
        step["tool_calls"] = tool_calls
    return step


def _parse_prompt(argv: list[str]) -> tuple[str | None, str | None, dict[str, Any] | None]:
    model: str | None = None
    prompt_parts: list[str] = []
    for arg in argv:
        if arg.startswith("--model="):
            model = arg.split("=", 1)[1]
        else:
            prompt_parts.append(arg)
    prompt = prompt_parts[-1] if prompt_parts else None
    context: dict[str, Any] | None = None
    if prompt:
        match = _CONTEXT_RE.search(prompt)
        if match is not None:
            try:
                parsed = json.loads(match.group("body"))
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                context = parsed
    return model, prompt, context


def _prompt_flags(prompt: str | None) -> dict[str, Any]:
    text = prompt or ""
    return {
        "prompt_has_context": "<xmuse_context>" in text,
        "prompt_has_readonly_instruction": "READ-ONLY" in text,
        "prompt_has_call_mcp_tool": "call_mcp_tool" in text,
    }


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
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_S) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
        return payload.get("result", {}).get("structuredContent", payload), response.status


def _run_turn(
    conversation_id: str,
    base_index: int,
    *,
    prompt: str | None,
    context: dict[str, Any] | None,
    content: str,
) -> None:
    steps: list[dict[str, Any]] = [
        _step(
            base_index,
            source="USER_EXPLICIT",
            type_="USER_INPUT",
            status="DONE",
            content=prompt or "",
        )
    ]
    if _MODE == "slow":
        _append_steps(conversation_id, steps)
        _log(
            "turn_started",
            conversation_id=conversation_id,
            base_step_index=base_index,
            mode=_MODE,
        )
        while True:
            time.sleep(3600)
    if _MODE == "silent":
        steps.append(
            _step(
                base_index + 1,
                source="MODEL",
                type_="PLANNER_RESPONSE",
                status="DONE",
                content="silent turn without durable outcome",
            )
        )
        _append_steps(conversation_id, steps)
        _log("turn_finished_without_outcome", conversation_id=conversation_id, mode=_MODE)
        return

    _append_steps(conversation_id, steps)
    time.sleep(_STEP_DELAY_S)
    _append_steps(
        conversation_id,
        [
            _step(
                base_index + 1,
                source="MODEL",
                type_="PLANNER_RESPONSE",
                status="RUNNING",
                content=_DRAFT,
            )
        ],
    )
    time.sleep(_STEP_DELAY_S)
    next_index = base_index + 2
    if _MODE == "tool-steps":
        _append_steps(
            conversation_id,
            [
                _step(
                    next_index,
                    source="MODEL",
                    type_="PLANNER_RESPONSE",
                    status="DONE",
                    tool_calls=[{"name": "run_command", "args": {"command": "ls"}}],
                )
            ],
        )
        _log("non_outcome_tool_steps", conversation_id=conversation_id, mode=_MODE)
        next_index += 1
        time.sleep(_STEP_DELAY_S)
    _append_steps(
        conversation_id,
        [
            _step(
                next_index,
                source="MODEL",
                type_="PLANNER_RESPONSE",
                status="DONE",
                tool_calls=[{"name": OUTCOME_TOOL_TITLE, "args": {}}],
            )
        ],
    )
    _log("outcome_tool_called", conversation_id=conversation_id)
    payload, status = _submit_outcome(context, content)
    _log("outcome_submission", http_status=status, result=payload)
    time.sleep(_STEP_DELAY_S)
    _append_steps(
        conversation_id,
        [
            _step(
                next_index + 1,
                source="MODEL",
                type_="PLANNER_RESPONSE",
                status="DONE",
                content=content,
            )
        ],
    )
    _log("turn_done", conversation_id=conversation_id, final_step_index=next_index + 1)


def _on_sigterm(*_args: Any) -> None:
    _log("sigterm_received")
    os._exit(0)


def main() -> int:
    signal.signal(signal.SIGTERM, _on_sigterm)
    argv = sys.argv[1:]
    command = argv[0] if argv else "unknown"
    _log(
        "startup",
        command=command,
        mode=_MODE,
        pid=os.getpid(),
        cwd=os.getcwd(),
        secret_env_names=_secret_env_names(),
        has_operator_token="XMUSE_OPERATOR_TOKEN" in os.environ,
        has_memoryos_api_key=(
            "XMUSE_MEMORYOS_API_KEY" in os.environ or "MEMORYOS_API_KEY" in os.environ
        ),
        has_anthropic_api_key="ANTHROPIC_API_KEY" in os.environ,
        has_csrf_token="ANTIGRAVITY_CSRF_TOKEN" in os.environ,
        has_ls_address="ANTIGRAVITY_LS_ADDRESS" in os.environ,
    )
    if _MODE == "mute":
        _log("muted", command=command)
        while True:
            time.sleep(3600)
    if command == "new-conversation":
        model, prompt, context = _parse_prompt(argv[1:])
        conversation_id = _allocate_conversation_id()
        # The real CLI pretty-prints its JSON response; emit it in two flushes
        # so the transport must accumulate across reads before parsing.
        response_text = json.dumps(
            {"response": {"newConversation": {"conversationId": conversation_id}}},
            indent=2,
        )
        split = len(response_text) // 2
        print(response_text[:split], end="", flush=True)
        time.sleep(0.05)
        print(response_text[split:], flush=True)
        _log(
            "new_conversation",
            conversation_id=conversation_id,
            model=model,
            **_prompt_flags(prompt),
        )
        _run_turn(conversation_id, 0, prompt=prompt, context=context, content=_CONTENT)
        return 0
    if command == "send-message":
        conversation_id = argv[1] if len(argv) > 1 else ""
        _model, prompt, context = _parse_prompt(argv[2:])
        base_index = _count_steps(conversation_id)
        print(
            json.dumps({"response": {"sendMessage": {"conversationId": conversation_id}}}),
            flush=True,
        )
        _log(
            "send_message",
            conversation_id=conversation_id,
            base_step_index=base_index,
            **_prompt_flags(prompt),
        )
        _run_turn(
            conversation_id,
            base_index,
            prompt=prompt,
            context=context,
            content=_FOLLOWUP_CONTENT,
        )
        return 0
    _log("unknown_command", argv=argv)
    return 2


if __name__ == "__main__":
    sys.exit(main())
