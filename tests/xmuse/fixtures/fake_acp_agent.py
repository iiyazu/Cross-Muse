#!/usr/bin/env python3
"""Scripted ACP agent used by Room ACP transport tests.

This is an agent-side SDK program, not a provider: it never contacts Claude or any
network endpoint except the Room MCP URL injected through ``session/new``, and it
writes nothing to stdout (stdout carries ACP framing).  Every observable fact is
appended as one JSON line to the file named by ``XMUSE_TEST_ACP_LOG`` so the test
process can assert on the agent's exact experience.

Modes (``XMUSE_TEST_ACP_MODE``):

- ``normal``    draft + outcome tool permission + real Room MCP submission.
- ``forbidden`` request ``Bash`` first (must be rejected), then submit normally.
- ``silent``    end the turn without submitting any durable outcome.
- ``slow``      block the turn until ``session/cancel`` delivers it.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import sys
import urllib.request
from typing import Any

import acp
from acp.helpers import start_tool_call, update_agent_message_text, update_tool_call
from acp.schema import (
    AgentCapabilities,
    HttpMcpServer,
    InitializeResponse,
    McpCapabilities,
    NewSessionResponse,
    PermissionOption,
    PromptResponse,
    ToolCallUpdate,
)

ROOM_OUTCOME_TOOL_NAME = "chat_room_submit_outcome"
OUTCOME_TOOL_TITLE = "mcp__xmuse-room__chat_room_submit_outcome"

_LOG_PATH = os.environ.get("XMUSE_TEST_ACP_LOG", "")
_MODE = os.environ.get("XMUSE_TEST_ACP_MODE", "normal")
_CONTENT = os.environ.get("XMUSE_TEST_ACP_CONTENT", "fake acp draft answer")
_OUTCOME_TYPE = os.environ.get("XMUSE_TEST_ACP_OUTCOME_TYPE", "respond")
_HTTP_TIMEOUT_S = float(os.environ.get("XMUSE_TEST_ACP_HTTP_TIMEOUT_S", "30"))

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


class FakeAcpAgent:
    """One scripted ACP agent process."""

    def __init__(self) -> None:
        self._conn: Any = None
        self._cancel_event = asyncio.Event()
        self._mcp_urls: dict[str, str | None] = {}

    def on_connect(self, conn: Any) -> None:
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: Any = None,
        client_info: Any = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        _log(
            "initialize",
            protocol_version=protocol_version,
            client_name=getattr(client_info, "name", None),
        )
        return InitializeResponse(
            protocol_version=acp.PROTOCOL_VERSION,
            agent_capabilities=AgentCapabilities(
                mcp_capabilities=McpCapabilities(http=True),
            ),
        )

    async def new_session(
        self,
        cwd: str,
        additional_directories: Any = None,
        mcp_servers: Any = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        session_id = f"fake-session-{len(self._mcp_urls) + 1}"
        url: str | None = None
        server_name: str | None = None
        for server in mcp_servers or []:
            if isinstance(server, HttpMcpServer):
                url = server.url
                server_name = server.name
        self._mcp_urls[session_id] = url
        _log("new_session", session_id=session_id, cwd=cwd, mcp_url=url, server_name=server_name)
        return NewSessionResponse(session_id=session_id)

    async def prompt(self, session_id: str, prompt: list[Any], **kwargs: Any) -> PromptResponse:
        text = "".join(
            str(block.text) for block in prompt if getattr(block, "type", None) == "text"
        )
        match = _CONTEXT_RE.search(text)
        if match is None:
            _log("prompt_without_context", session_id=session_id)
            return PromptResponse(stop_reason="end_turn")
        context = json.loads(match.group("body"))
        _log(
            "prompt_received",
            session_id=session_id,
            mode=_MODE,
            observation_id=context.get("observation_id"),
            participant_id=context.get("participant_id"),
        )
        if _MODE == "slow":
            await self._cancel_event.wait()
            _log("slow_turn_released", session_id=session_id)
            return PromptResponse(stop_reason="cancelled")
        if _MODE == "silent":
            return PromptResponse(stop_reason="end_turn")
        if _MODE == "forbidden":
            allowed = await self._request_permission(
                session_id, tool_call_id="call-bash", title="Bash"
            )
            _log("forbidden_tool_decision", tool="Bash", allowed=allowed)

        await self._conn.session_update(session_id, update_agent_message_text(_CONTENT))
        tool_call_id = "call-outcome"
        await self._conn.session_update(
            session_id,
            update=start_tool_call(
                tool_call_id, OUTCOME_TOOL_TITLE, kind="execute", status="pending"
            ),
        )
        allowed = await self._request_permission(
            session_id, tool_call_id=tool_call_id, title=OUTCOME_TOOL_TITLE
        )
        if not allowed:
            _log("outcome_permission_denied", tool_call_id=tool_call_id)
            return PromptResponse(stop_reason="end_turn")
        payload, status = self._submit_outcome(session_id, context, _CONTENT)
        _log("outcome_submission", http_status=status, result=payload)
        await self._conn.session_update(
            session_id, update=update_tool_call(tool_call_id, status="completed")
        )
        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        _log("cancel_received", session_id=session_id)
        self._cancel_event.set()

    async def _request_permission(self, session_id: str, *, tool_call_id: str, title: str) -> bool:
        options = [
            PermissionOption(option_id="allow-once", name="Allow once", kind="allow_once"),
            PermissionOption(option_id="allow-always", name="Allow always", kind="allow_always"),
            PermissionOption(option_id="reject-once", name="Reject", kind="reject_once"),
        ]
        response = await self._conn.request_permission(
            session_id,
            ToolCallUpdate(tool_call_id=tool_call_id, title=title, status="pending"),
            options,
        )
        outcome = getattr(response, "outcome", None)
        chosen_id = getattr(outcome, "option_id", None)
        chosen_kind = next(
            (option.kind for option in options if option.option_id == chosen_id), None
        )
        allowed = getattr(outcome, "outcome", None) == "selected" and chosen_kind in {
            "allow_once",
            "allow_always",
        }
        _log(
            "permission_decision",
            tool=title,
            allowed=allowed,
            outcome=getattr(outcome, "outcome", None),
            chosen_kind=chosen_kind,
        )
        return allowed

    def _submit_outcome(
        self, session_id: str, context: dict[str, Any], content: str
    ) -> tuple[Any, int]:
        url = self._mcp_urls.get(session_id)
        if not url:
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
            url,
            data=body,
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT_S) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("result", {}).get("structuredContent", payload), response.status


async def _serve() -> None:
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(
        lambda _loop, ctx: _log("loop_exception", message=str(ctx.get("message")))
    )
    _log(
        "startup",
        mode=_MODE,
        cwd=os.getcwd(),
        pid=os.getpid(),
        secret_env_names=_secret_env_names(),
        has_operator_token="XMUSE_OPERATOR_TOKEN" in os.environ,
        has_memoryos_api_key=(
            "XMUSE_MEMORYOS_API_KEY" in os.environ or "MEMORYOS_API_KEY" in os.environ
        ),
        has_anthropic_api_key="ANTHROPIC_API_KEY" in os.environ,
    )
    agent = FakeAcpAgent()

    def _on_sigterm(*_args: Any) -> None:
        _log("sigterm_received")
        os._exit(0)

    signal.signal(signal.SIGTERM, _on_sigterm)
    try:
        await acp.run_agent(agent)
    finally:
        _log("agent_exit")


def main() -> int:
    try:
        asyncio.run(_serve())
    except Exception as exc:
        _log("agent_crashed", error=f"{type(exc).__name__}: {exc}")
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
