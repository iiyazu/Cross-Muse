from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from xmuse_core.agents import codex_persistent
from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.agents.persistent_peer import (
    PeerCompatibilityError,
    PersistentCliPeerService,
)
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.store import ChatStore


class FakeSessionLayer:
    def __init__(
        self,
        *,
        message: StdoutMessage | None = None,
        messages: list[StdoutMessage | None] | None = None,
        ensure_error: Exception | None = None,
        send_error: Exception | None = None,
        receive_error: Exception | None = None,
        receive_delay_s: float = 0,
    ) -> None:
        self.messages = list(messages if messages is not None else [message])
        self.ensure_error = ensure_error
        self.send_error = send_error
        self.receive_error = receive_error
        self.receive_delay_s = receive_delay_s
        self.ensure_calls: list[dict[str, Any]] = []
        self.sent: list[dict[str, Any]] = []
        self._record: GodSessionRecord | None = None

    async def ensure_conversation_session(self, **kwargs: Any) -> GodSessionRecord:
        self.ensure_calls.append(kwargs)
        if self.ensure_error is not None:
            raise self.ensure_error
        if self._record is None:
            self._record = GodSessionRecord(
                god_session_id="god-peer-1",
                role=kwargs["role"],
                agent_name=kwargs["agent"].name,
                runtime=kwargs["agent"].runtime.value,
                session_address="@peer",
                session_inbox_id="inbox-peer",
                conversation_id=kwargs["conversation_id"],
                participant_id=kwargs["participant_id"],
                model=kwargs.get("model"),
                prompt_fingerprint=kwargs.get("prompt_fingerprint"),
                worktree=str(kwargs.get("worktree")),
                feature_scope_id=kwargs.get("feature_scope_id"),
            )
        return self._record

    async def send_message(self, **kwargs: Any) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(kwargs)

    async def receive_message(self, god_session_id: str) -> StdoutMessage | None:
        if self.receive_delay_s:
            await asyncio.sleep(self.receive_delay_s)
        if self.receive_error is not None:
            raise self.receive_error
        if self.messages:
            return self.messages.pop(0)
        return None


def _conversation_with_participant(
    tmp_path: Path,
    *,
    role: str = "review",
    status: str = "active",
    model: str = "gpt-5.5",
) -> tuple[Path, str, str]:
    db_path = tmp_path / "chat.db"
    chat = ChatStore(db_path)
    conversation = chat.create_conversation("Peer service")
    participants = ParticipantStore(db_path)
    participant = participants.add(
        conversation_id=conversation.id,
        role=role,
        display_name=f"{role.title()} GOD",
        cli_kind="codex",
        model=model,
    )
    if status == "stopped":
        participants.update_status(participant.participant_id, "stopped")
    return db_path, conversation.id, participant.participant_id


def test_codex_persistent_echoes_request_id_on_success(monkeypatch, capsys, tmp_path):
    def fake_run(_config, _prompt):
        return subprocess.CompletedProcess(
            args=["codex"],
            returncode=0,
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr(codex_persistent, "_run_codex_exec", fake_run)

    codex_persistent._run_codex_turn(
        codex_persistent.RunnerConfig(
            model="gpt-5.5",
            mcp_port=8100,
            worktree=tmp_path,
            role="review",
            timeout_s=10,
        ),
        {"type": "review", "request_id": "req-1", "prompt": "review", "context": "ctx"},
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["request_id"] == "req-1"
    assert payload["artifacts"]["request_id"] == "req-1"


def test_codex_persistent_echoes_request_id_on_error(monkeypatch, capsys, tmp_path):
    def fake_run(_config, _prompt):
        return subprocess.CompletedProcess(
            args=["codex"],
            returncode=2,
            stdout="",
            stderr="failed",
        )

    monkeypatch.setattr(codex_persistent, "_run_codex_exec", fake_run)

    codex_persistent._run_codex_turn(
        codex_persistent.RunnerConfig(
            model="gpt-5.5",
            mcp_port=8100,
            worktree=tmp_path,
            role="review",
            timeout_s=10,
        ),
        {"type": "review", "request_id": "req-1", "prompt": "review", "context": "ctx"},
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["request_id"] == "req-1"
    assert payload["artifacts"]["request_id"] == "req-1"


def test_codex_persistent_preserves_execute_request_id_with_generic_request_id(
    monkeypatch,
    capsys,
    tmp_path,
):
    def fake_run(_config, _prompt):
        return subprocess.CompletedProcess(
            args=["codex"],
            returncode=0,
            stdout="ok",
            stderr="",
        )

    monkeypatch.setattr(codex_persistent, "_run_codex_exec", fake_run)

    codex_persistent._run_codex_turn(
        codex_persistent.RunnerConfig(
            model="gpt-5.5",
            mcp_port=8100,
            worktree=tmp_path,
            role="execute",
            timeout_s=10,
        ),
        {
            "type": "execute",
            "request_id": "req-1",
            "execute_request_id": "execute-1",
            "prompt": "execute",
            "context": "ctx",
        },
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["request_id"] == "req-1"
    assert payload["artifacts"]["request_id"] == "req-1"
    assert payload["artifacts"]["execute_result"]["execute_request_id"] == "execute-1"


def test_stdout_protocol_ignores_non_string_request_id() -> None:
    from xmuse_core.agents.protocol import parse_stdout_line

    parsed = parse_stdout_line('{"type":"result","request_id":123,"artifacts":{}}')

    assert parsed is not None
    assert parsed.request_id is None


@pytest.mark.asyncio
async def test_ensure_peer_rejects_unknown_participant(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    ChatStore(db_path).create_conversation("Peer service")
    service = PersistentCliPeerService(db_path=db_path, session_layer=FakeSessionLayer())

    with pytest.raises(PeerCompatibilityError, match="unknown_participant"):
        await service.ensure_peer(
            conversation_id="conv-missing",
            participant_id="part-missing",
            model="gpt-5.5",
            prompt="review",
            worktree=tmp_path,
        )


@pytest.mark.asyncio
async def test_ensure_peer_rejects_conversation_mismatch(tmp_path: Path) -> None:
    db_path, _conversation_id, participant_id = _conversation_with_participant(tmp_path)
    other_conversation = ChatStore(db_path).create_conversation("Other")
    service = PersistentCliPeerService(db_path=db_path, session_layer=FakeSessionLayer())

    with pytest.raises(PeerCompatibilityError, match="conversation_mismatch"):
        await service.ensure_peer(
            conversation_id=other_conversation.id,
            participant_id=participant_id,
            model="gpt-5.5",
            prompt="review",
            worktree=tmp_path,
        )


@pytest.mark.asyncio
async def test_ensure_peer_rejects_stopped_participant(tmp_path: Path) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(
        tmp_path,
        status="stopped",
    )
    service = PersistentCliPeerService(db_path=db_path, session_layer=FakeSessionLayer())

    with pytest.raises(PeerCompatibilityError, match="participant_inactive"):
        await service.ensure_peer(
            conversation_id=conversation_id,
            participant_id=participant_id,
            model="gpt-5.5",
            prompt="review",
            worktree=tmp_path,
        )


@pytest.mark.asyncio
async def test_ensure_peer_rejects_model_mismatch(tmp_path: Path) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(
        tmp_path,
        model="gpt-4o",
    )
    service = PersistentCliPeerService(db_path=db_path, session_layer=FakeSessionLayer())

    with pytest.raises(PeerCompatibilityError, match="model_mismatch"):
        await service.ensure_peer(
            conversation_id=conversation_id,
            participant_id=participant_id,
            model="gpt-5.4",
            prompt="review",
            worktree=tmp_path,
        )


@pytest.mark.asyncio
async def test_ensure_peer_creates_and_reuses_session_with_metadata(
    tmp_path: Path,
) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(tmp_path)
    layer = FakeSessionLayer()
    service = PersistentCliPeerService(db_path=db_path, session_layer=layer)

    first = await service.ensure_peer(
        conversation_id=conversation_id,
        participant_id=participant_id,
        model="gpt-5.5",
        prompt="review prompt",
        worktree=tmp_path,
        feature_scope_id="feature-a",
    )
    second = await service.ensure_peer(
        conversation_id=conversation_id,
        participant_id=participant_id,
        model="gpt-5.5",
        prompt="review prompt",
        worktree=tmp_path,
        feature_scope_id="feature-a",
    )

    assert first.god_session_id == second.god_session_id == "god-peer-1"
    assert first.conversation_id == conversation_id
    assert first.participant_id == participant_id
    assert first.cli_kind == "codex"
    assert first.runtime == "codex"
    assert first.model == "gpt-5.4"
    assert first.worktree == str(tmp_path)
    assert first.feature_scope_id == "feature-a"
    assert first.prompt_fingerprint.startswith("sha256:")
    assert len(layer.ensure_calls) == 2
    assert layer.ensure_calls[0]["model"] == "gpt-5.4"
    assert layer.ensure_calls[0]["prompt_fingerprint"] == first.prompt_fingerprint
    assert layer.ensure_calls[0]["feature_scope_id"] == "feature-a"


@pytest.mark.asyncio
async def test_request_can_use_stable_session_prompt_with_different_request_prompts(
    tmp_path: Path,
) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(tmp_path)
    layer = FakeSessionLayer(
        messages=[
            StdoutMessage(type="result", request_id="req-1", status="success"),
            StdoutMessage(type="result", request_id="req-2", status="success"),
        ]
    )
    service = PersistentCliPeerService(db_path=db_path, session_layer=layer)

    first = await service.request(
        conversation_id=conversation_id,
        participant_id=participant_id,
        model="gpt-5.5",
        prompt="review lane one with request req-1",
        session_prompt="stable review peer prompt",
        worktree=tmp_path,
        request_id="req-1",
        message_type="review",
        context="ctx-1",
        feature_scope_id="feature-a",
    )
    second = await service.request(
        conversation_id=conversation_id,
        participant_id=participant_id,
        model="gpt-5.5",
        prompt="review lane two with request req-2",
        session_prompt="stable review peer prompt",
        worktree=tmp_path,
        request_id="req-2",
        message_type="review",
        context="ctx-2",
        feature_scope_id="feature-a",
    )

    assert first.status == "ok"
    assert second.status == "ok"
    assert len(layer.ensure_calls) == 2
    assert (
        layer.ensure_calls[0]["prompt_fingerprint"]
        == layer.ensure_calls[1]["prompt_fingerprint"]
    )
    assert layer.sent[0]["prompt"] == "review lane one with request req-1"
    assert layer.sent[1]["prompt"] == "review lane two with request req-2"


@pytest.mark.asyncio
async def test_ensure_peer_wraps_session_layer_compatibility_failure(
    tmp_path: Path,
) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(tmp_path)
    service = PersistentCliPeerService(
        db_path=db_path,
        session_layer=FakeSessionLayer(ensure_error=RuntimeError("shape mismatch")),
    )

    with pytest.raises(PeerCompatibilityError, match="session_compatibility_mismatch"):
        await service.ensure_peer(
            conversation_id=conversation_id,
            participant_id=participant_id,
            model="gpt-5.5",
            prompt="review",
            worktree=tmp_path,
        )


@pytest.mark.asyncio
async def test_ensure_peer_reports_ensure_failure(tmp_path: Path) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(tmp_path)
    service = PersistentCliPeerService(
        db_path=db_path,
        session_layer=FakeSessionLayer(ensure_error=RuntimeError("boom")),
    )

    result = await service.request(
        conversation_id=conversation_id,
        participant_id=participant_id,
        model="gpt-5.5",
        prompt="review",
        worktree=tmp_path,
        request_id="req-1",
        message_type="review",
        context="ctx",
    )

    assert result.status == "peer_unavailable"
    assert result.reason == "ensure_failed"


@pytest.mark.asyncio
async def test_send_request_sends_structured_request_id(tmp_path: Path) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(tmp_path)
    layer = FakeSessionLayer()
    service = PersistentCliPeerService(db_path=db_path, session_layer=layer)
    handle = await service.ensure_peer(
        conversation_id=conversation_id,
        participant_id=participant_id,
        model="gpt-5.5",
        prompt="review",
        worktree=tmp_path,
    )

    result = await service.send_request(
        handle,
        message_type="review",
        request_id="req-1",
        prompt="review lane",
        context="ctx",
    )

    assert result.status == "ok"
    assert layer.sent == [
        {
            "god_session_id": "god-peer-1",
            "message_type": "review",
            "request_id": "req-1",
            "prompt": "review lane",
            "context": "ctx",
        }
    ]


@pytest.mark.asyncio
async def test_request_dispatches_execute_envelope_over_native_peer_handle(
    tmp_path: Path,
) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(
        tmp_path,
        role="execute",
    )
    layer = FakeSessionLayer(
        message=StdoutMessage(type="result", request_id="exec-1", status="success")
    )
    service = PersistentCliPeerService(db_path=db_path, session_layer=layer)

    result = await service.request(
        conversation_id=conversation_id,
        participant_id=participant_id,
        model="gpt-5.5",
        prompt="execute lane request",
        session_prompt="stable execute peer prompt",
        worktree=tmp_path,
        request_id="exec-1",
        message_type="execute",
        context="lane context",
        feature_scope_id="feature-a",
    )

    assert result.status == "ok"
    assert layer.ensure_calls[0]["role"] == "execute"
    assert layer.ensure_calls[0]["feature_scope_id"] == "feature-a"
    assert layer.sent == [
        {
            "god_session_id": "god-peer-1",
            "message_type": "execute",
            "request_id": "exec-1",
            "prompt": "execute lane request",
            "context": "lane context",
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "status", "reason"),
    [
        (StdoutMessage(type="result", request_id="req-1"), "ok", None),
        (StdoutMessage(type="result"), "request_id_missing", "request_id_missing"),
        (
            StdoutMessage(type="result", request_id="other"),
            "request_id_mismatch",
            "request_id_mismatch",
        ),
        (
            StdoutMessage(type="error", request_id="req-1", code="bad", message="failed"),
            "peer_error",
            "bad",
        ),
    ],
)
async def test_receive_result_correlates_request_id(
    tmp_path: Path,
    message: StdoutMessage,
    status: str,
    reason: str | None,
) -> None:
    service = PersistentCliPeerService(
        db_path=_conversation_with_participant(tmp_path)[0],
        session_layer=FakeSessionLayer(message=message),
    )

    result = await service.receive_result(
        god_session_id="god-peer-1",
        request_id="req-1",
        timeout_s=1,
    )

    assert result.status == status
    assert result.reason == reason


@pytest.mark.asyncio
async def test_receive_result_reports_timeout(tmp_path: Path) -> None:
    service = PersistentCliPeerService(
        db_path=_conversation_with_participant(tmp_path)[0],
        session_layer=FakeSessionLayer(
            message=StdoutMessage(type="result", request_id="req-1"),
            receive_delay_s=0.05,
        ),
    )

    result = await service.receive_result(
        god_session_id="god-peer-1",
        request_id="req-1",
        timeout_s=0.001,
    )

    assert result.status == "timeout"
    assert result.reason == "timeout"


@pytest.mark.asyncio
async def test_receive_result_ignores_progress_until_terminal_result(
    tmp_path: Path,
) -> None:
    service = PersistentCliPeerService(
        db_path=_conversation_with_participant(tmp_path)[0],
        session_layer=FakeSessionLayer(
            messages=[
                StdoutMessage(type="progress", request_id="req-1", message="working"),
                StdoutMessage(type="heartbeat", request_id="req-1", message="alive"),
                StdoutMessage(type="result", request_id="req-1"),
            ],
        ),
    )

    result = await service.receive_result(
        god_session_id="god-peer-1",
        request_id="req-1",
        timeout_s=1,
    )

    assert result.status == "ok"


@pytest.mark.asyncio
async def test_request_reports_send_and_receive_failures(tmp_path: Path) -> None:
    db_path, conversation_id, participant_id = _conversation_with_participant(tmp_path)
    send_service = PersistentCliPeerService(
        db_path=db_path,
        session_layer=FakeSessionLayer(send_error=RuntimeError("send")),
    )

    send_result = await send_service.request(
        conversation_id=conversation_id,
        participant_id=participant_id,
        model="gpt-5.5",
        prompt="review",
        worktree=tmp_path,
        request_id="req-1",
        message_type="review",
        context="ctx",
    )

    receive_service = PersistentCliPeerService(
        db_path=db_path,
        session_layer=FakeSessionLayer(receive_error=RuntimeError("receive")),
    )
    receive_result = await receive_service.request(
        conversation_id=conversation_id,
        participant_id=participant_id,
        model="gpt-5.5",
        prompt="review",
        worktree=tmp_path,
        request_id="req-1",
        message_type="review",
        context="ctx",
    )

    assert send_result.status == "delivery_failed"
    assert send_result.reason == "send_failed"
    assert receive_result.status == "delivery_failed"
    assert receive_result.reason == "receive_failed"
