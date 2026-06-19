"""
Focused tests for the review_plane track — orchestrator integration improvements.

Covers:
- Rework verdict from stdout fallback is ingested through review plane
- Rework verdict lineage is preserved when lane is requeued after rejection
- verdict_lineage_for_run on orchestrator returns correct lineage for a graph
- verdict_lineage_for_run returns empty list for unknown graph
- verdict_lineage_for_run includes patch-forward descendants via source_lane_id
- Rework verdict ingestion is skipped gracefully when no review_task_id is set
- Rework verdict ingestion failure does not break the rejection path
- Multiple rework cycles produce multiple verdict entries in lineage
- verdict_lineage_for_run excludes lanes from other graphs
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from xmuse_core.agents.persistent_peer import PeerRequestResult
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.platform.agent_spawner import SpawnResult
from xmuse_core.platform.orchestrator import PlatformOrchestrator
from xmuse_core.platform.verdicts.writer import ingest_rework_verdict
from xmuse_core.structuring.models import ReviewDecision, ReviewTaskStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _make_orchestrator(tmp_path: Path, lanes: list[dict]) -> PlatformOrchestrator:
    lanes_path = tmp_path / "feature_lanes.json"
    _write_json(lanes_path, {"lanes": lanes})
    (tmp_path / "error_knowledge.json").write_text(json.dumps({"entries": []}))
    (tmp_path / "xmuse" / "god_prompts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "xmuse" / "god_prompts" / "execution_god.md").write_text("exec")
    (tmp_path / "xmuse" / "god_prompts" / "review_god.md").write_text("review")
    return PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )


def _make_final_action_orchestrator(
    tmp_path: Path,
    lanes: list[dict],
) -> PlatformOrchestrator:
    lanes_path = tmp_path / "feature_lanes.json"
    _write_json(lanes_path, {"lanes": lanes})
    (tmp_path / "error_knowledge.json").write_text(json.dumps({"entries": []}))
    (tmp_path / "xmuse" / "god_prompts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "xmuse" / "god_prompts" / "execution_god.md").write_text("exec")
    (tmp_path / "xmuse" / "god_prompts" / "review_god.md").write_text("review")
    return PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        require_final_action_approval=True,
    )


def _gated_lane(lane_id: str, **extra) -> dict:
    return {
        "feature_id": lane_id,
        "status": "gated",
        "prompt": f"Implement {lane_id}",
        "gate_passed": True,
        **extra,
    }


class FakePersistentReviewLayer:
    def __init__(
        self,
        received: list[StdoutMessage] | None = None,
        *,
        fail_ensure: bool = False,
        fail_send: bool = False,
        fail_receive: bool = False,
        echo_request_id: bool = True,
        enforce_stable_prompt_fingerprint: bool = False,
    ) -> None:
        self.ensured: list[dict[str, object]] = []
        self.sent: list[dict[str, object]] = []
        self.prompt_contracts: list[tuple[str, dict[str, object]]] = []
        self.received = list(received or [])
        self.fail_ensure = fail_ensure
        self.fail_send = fail_send
        self.fail_receive = fail_receive
        self.echo_request_id = echo_request_id
        self.enforce_stable_prompt_fingerprint = enforce_stable_prompt_fingerprint
        self._fingerprints_by_participant: dict[tuple[str, str], object] = {}
        self.aborted: list[str] = []

    async def ensure_conversation_session(self, **kwargs):
        if self.fail_ensure:
            raise RuntimeError("persistent ensure failed")
        if self.enforce_stable_prompt_fingerprint:
            key = (str(kwargs["conversation_id"]), str(kwargs["participant_id"]))
            fingerprint = kwargs.get("prompt_fingerprint")
            previous = self._fingerprints_by_participant.setdefault(key, fingerprint)
            if previous != fingerprint:
                raise RuntimeError("prompt fingerprint changed")
        self.ensured.append(dict(kwargs))
        return SimpleNamespace(
            god_session_id=f"god-{kwargs['conversation_id']}-{kwargs['participant_id']}"
        )

    async def send_message(self, **kwargs) -> None:
        self.sent.append(dict(kwargs))
        if self.fail_send:
            raise RuntimeError("persistent delivery failed")

    def record_prompt_contract(self, god_session_id, **kwargs) -> None:
        self.prompt_contracts.append((god_session_id, dict(kwargs)))

    async def receive_message(self, god_session_id: str):
        if self.fail_receive:
            raise RuntimeError("persistent receive failed")
        if self.received:
            message = self.received.pop(0)
            if self.echo_request_id and message.request_id is None and self.sent:
                return replace(message, request_id=str(self.sent[-1]["request_id"]))
            return message
        return None

    async def abort_session(self, god_session_id: str) -> None:
        self.aborted.append(god_session_id)

    def persistent_model_for_runtime(self, runtime) -> str:
        return "gpt-5.5"


class SlowPersistentReviewLayer(FakePersistentReviewLayer):
    def __init__(self) -> None:
        super().__init__()
        self.in_flight = 0
        self.max_in_flight = 0

    async def receive_message(self, god_session_id: str):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.05)
        self.in_flight -= 1
        return StdoutMessage(
            type="result",
            request_id=str(self.sent[-1]["request_id"]),
            status="success",
            artifacts={
                "review_verdict": {
                    "decision": "merge",
                    "summary": f"approved through {god_session_id}",
                }
            },
        )


class TimeoutPersistentReviewLayer(FakePersistentReviewLayer):
    async def receive_message(self, god_session_id: str):
        raise TimeoutError()


def _add_review_participant(tmp_path: Path, conversation_id: str):
    return ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conversation_id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )


def _add_opencode_review_participant(tmp_path: Path, conversation_id: str):
    return ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conversation_id,
        role="review",
        display_name="Review OpenCode",
        cli_kind="opencode",
        model="opencode-go/deepseek-v4-flash",
    )


def _add_architect_participant(tmp_path: Path, conversation_id: str):
    return ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conversation_id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )


# ---------------------------------------------------------------------------
# Rework verdict ingestion via stdout fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_review_peer_routing_empty_conversation_without_opencode_fails_closed(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Default review peer")
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-default-review-peer",
                conversation_id=conversation.id,
                feature_plan_feature_id="feature-default-peer",
            )
        ],
    )
    orch._default_review_peer_routing_enabled = True
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "Default peer approves.",
                    }
                },
            )
        ],
        enforce_stable_prompt_fingerprint=True,
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-default-review-peer")

    lane = orch._sm.get_lane("lane-default-review-peer")
    participants = ParticipantStore(tmp_path / "chat.db").list_by_conversation(
        conversation.id
    )
    review_participants = [item for item in participants if item.role == "review"]
    assert spawn.await_count == 0
    assert persistent.ensured == []
    assert persistent.sent == []
    assert review_participants == []
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "required_review_peer_unavailable"
    assert lane["failure_layer"] == "review"
    assert lane["review_peer_defaulted"] is True
    assert lane["review_peer_id"] == "default:opencode"
    assert lane["peer_routing_mode"] == "required"
    assert lane["peer_delivery_mode"] == "required_peer_failed"
    assert lane["peer_degraded_reason"] == "review_peer_runtime_unavailable"


@pytest.mark.asyncio
async def test_default_review_peer_routing_reuses_registered_opencode_review_peer(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Default OpenCode review peer")
    participant = _add_opencode_review_participant(tmp_path, conversation.id)
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-default-opencode-review-peer",
                conversation_id=conversation.id,
            )
        ],
    )
    orch._default_review_peer_routing_enabled = True
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "Registered OpenCode review peer approves.",
                    }
                },
            )
        ]
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-default-opencode-review-peer")

    lane = orch._sm.get_lane("lane-default-opencode-review-peer")
    participants = ParticipantStore(tmp_path / "chat.db").list_by_conversation(
        conversation.id
    )
    review_participants = [item for item in participants if item.role == "review"]
    assert spawn.await_count == 0
    assert review_participants == [participant]
    assert lane["status"] == "awaiting_final_action"
    assert lane["review_peer_defaulted"] is True
    assert lane["review_peer_id"] == participant.participant_id
    assert lane["peer_delivery_mode"] == "configured_peer"
    assert lane["peer_request_id"] in persistent.sent[0]["request_id"]
    assert lane["review_peer_cli_kind"] == participant.cli_kind
    assert lane["review_peer_model"] == participant.model
    assert persistent.ensured[0]["participant_id"] == participant.participant_id
    assert persistent.ensured[0]["feature_scope_id"] == (
        "configured-review:lane-default-opencode-review-peer"
    )
    assert persistent.prompt_contracts[0][0] == persistent.sent[0]["god_session_id"]
    assert persistent.prompt_contracts[0][1]["prompt_contract_version"] == (
        "xmuse-persistent-review-session-prompt-v1"
    )
    assert persistent.prompt_contracts[0][1]["prompt_layer_order"] == [
        "persistent_review_session_identity"
    ]
    assert persistent.prompt_contracts[0][1]["prompt_artifact_fingerprint"] == (
        persistent.ensured[0]["prompt_fingerprint"]
    )
    assert lane.get("persistent_review_degraded_reason") != "missing_feature_identity"


@pytest.mark.asyncio
async def test_default_review_peer_routing_ambiguous_opencode_fails_closed(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Ambiguous OpenCode review peer")
    first = _add_opencode_review_participant(tmp_path, conversation.id)
    second = _add_opencode_review_participant(tmp_path, conversation.id)
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-default-opencode-review-peer-ambiguous",
                conversation_id=conversation.id,
                feature_plan_feature_id="feature-default-peer-ambiguous",
            )
        ],
    )
    orch._default_review_peer_routing_enabled = True
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "Ambiguous review peer must not apply.",
                    }
                },
            )
        ]
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-default-opencode-review-peer-ambiguous")

    lane = orch._sm.get_lane("lane-default-opencode-review-peer-ambiguous")
    participants = ParticipantStore(tmp_path / "chat.db").list_by_conversation(
        conversation.id
    )
    review_participants = [item for item in participants if item.role == "review"]
    assert spawn.await_count == 0
    assert persistent.ensured == []
    assert persistent.sent == []
    assert review_participants == [first, second]
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "required_review_peer_unavailable"
    assert lane["failure_layer"] == "review"
    assert lane["review_peer_defaulted"] is True
    assert lane["review_peer_id"] == "default:opencode"
    assert lane["peer_routing_mode"] == "required"
    assert lane["peer_delivery_mode"] == "required_peer_failed"
    assert lane["peer_degraded_reason"] == "review_peer_runtime_ambiguous"


@pytest.mark.asyncio
async def test_default_review_peer_routing_missing_opencode_roster_fails_closed(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Missing OpenCode review peer")
    architect = _add_architect_participant(tmp_path, conversation.id)
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-default-opencode-review-peer-missing",
                conversation_id=conversation.id,
                feature_plan_feature_id="feature-default-peer-missing",
            )
        ],
    )
    orch._default_review_peer_routing_enabled = True
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "Missing review peer must not apply.",
                    }
                },
            )
        ]
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-default-opencode-review-peer-missing")

    lane = orch._sm.get_lane("lane-default-opencode-review-peer-missing")
    participants = ParticipantStore(tmp_path / "chat.db").list_by_conversation(
        conversation.id
    )
    review_participants = [item for item in participants if item.role == "review"]
    assert spawn.await_count == 0
    assert persistent.ensured == []
    assert persistent.sent == []
    assert review_participants == []
    assert participants == [architect]
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "required_review_peer_unavailable"
    assert lane["failure_layer"] == "review"
    assert lane["review_peer_defaulted"] is True
    assert lane["review_peer_id"] == "default:opencode"
    assert lane["peer_routing_mode"] == "required"
    assert lane["peer_delivery_mode"] == "required_peer_failed"
    assert lane["peer_degraded_reason"] == "review_peer_runtime_unavailable"


@pytest.mark.asyncio
async def test_default_review_peer_routing_passes_review_timeout_to_peer_service(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Default review peer timeout")
    participant = _add_opencode_review_participant(tmp_path, conversation.id)
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-default-review-peer-timeout",
                conversation_id=conversation.id,
                feature_plan_feature_id="feature-default-peer",
            )
        ],
    )
    orch._default_review_peer_routing_enabled = True
    orch._persistent_review_receive_timeout_s = 1800.0
    orch._review_god_session_layer = FakePersistentReviewLayer()
    captured_requests: list[dict[str, object]] = []

    class RecordingPeerService:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        async def request(self, **kwargs) -> PeerRequestResult:
            captured_requests.append(dict(kwargs))
            request_id = str(kwargs["request_id"])
            return PeerRequestResult(
                status="ok",
                request_id=request_id,
                message=StdoutMessage(
                    type="result",
                    request_id=request_id,
                    status="success",
                    artifacts={
                        "review_verdict": {
                            "decision": "merge",
                            "summary": "Default peer approves with long timeout.",
                        }
                    },
                ),
            )

    with patch(
        "xmuse_core.platform.execution.review_god.PersistentCliPeerService",
        RecordingPeerService,
    ), patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-default-review-peer-timeout")

    lane = orch._sm.get_lane("lane-default-review-peer-timeout")
    assert spawn.await_count == 0
    assert lane["status"] == "awaiting_final_action"
    assert lane["peer_delivery_mode"] == "configured_peer"
    assert captured_requests[0]["participant_id"] == participant.participant_id
    assert captured_requests[0]["timeout_s"] == 1800.0


@pytest.mark.asyncio
async def test_default_review_peer_routing_reuses_same_feature_peer_session(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Default review peer reuse")
    participant = _add_opencode_review_participant(tmp_path, conversation.id)
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-default-review-peer-a",
                conversation_id=conversation.id,
                feature_plan_feature_id="feature-default-peer",
            ),
            _gated_lane(
                "lane-default-review-peer-b",
                conversation_id=conversation.id,
                feature_plan_feature_id="feature-default-peer",
            ),
        ],
    )
    orch._default_review_peer_routing_enabled = True
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={"review_verdict": {"decision": "merge", "summary": "ok a"}},
            ),
            StdoutMessage(
                type="result",
                status="success",
                artifacts={"review_verdict": {"decision": "merge", "summary": "ok b"}},
            ),
        ],
        enforce_stable_prompt_fingerprint=True,
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-default-review-peer-a")
        await orch._run_review_god("lane-default-review-peer-b")

    participants = ParticipantStore(tmp_path / "chat.db").list_by_conversation(
        conversation.id
    )
    review_participants = [item for item in participants if item.role == "review"]
    assert spawn.await_count == 0
    assert review_participants == [participant]
    assert [call["participant_id"] for call in persistent.ensured] == [
        participant.participant_id,
        participant.participant_id,
    ]
    assert persistent.sent[0]["god_session_id"] == persistent.sent[1]["god_session_id"]
    assert (
        persistent.ensured[0]["prompt_fingerprint"]
        == persistent.ensured[1]["prompt_fingerprint"]
    )


@pytest.mark.asyncio
async def test_default_review_peer_routing_serializes_same_feature_requests(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Default review peer single flight")
    _add_opencode_review_participant(tmp_path, conversation.id)
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-default-review-peer-concurrent-a",
                conversation_id=conversation.id,
                feature_plan_feature_id="feature-default-peer",
            ),
            _gated_lane(
                "lane-default-review-peer-concurrent-b",
                conversation_id=conversation.id,
                feature_plan_feature_id="feature-default-peer",
            ),
        ],
    )
    orch._default_review_peer_routing_enabled = True
    persistent = SlowPersistentReviewLayer()
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await asyncio.gather(
            orch._run_review_god("lane-default-review-peer-concurrent-a"),
            orch._run_review_god("lane-default-review-peer-concurrent-b"),
        )

    assert spawn.await_count == 0
    assert persistent.max_in_flight == 1
    assert orch._sm.get_lane("lane-default-review-peer-concurrent-a")[
        "status"
    ] == "awaiting_final_action"
    assert orch._sm.get_lane("lane-default-review-peer-concurrent-b")[
        "status"
    ] == "awaiting_final_action"


@pytest.mark.asyncio
async def test_default_review_peer_routing_reuses_opencode_peer_across_feature_scopes(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Default review peer feature collision")
    participant = _add_opencode_review_participant(tmp_path, conversation.id)
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-default-review-peer-slash",
                conversation_id=conversation.id,
                feature_plan_feature_id="a/b",
            ),
            _gated_lane(
                "lane-default-review-peer-colon",
                conversation_id=conversation.id,
                feature_plan_feature_id="a:b",
            ),
        ],
    )
    orch._default_review_peer_routing_enabled = True
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={"review_verdict": {"decision": "merge", "summary": "slash"}},
            ),
            StdoutMessage(
                type="result",
                status="success",
                artifacts={"review_verdict": {"decision": "merge", "summary": "colon"}},
            ),
        ],
        enforce_stable_prompt_fingerprint=True,
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock):
        await orch._run_review_god("lane-default-review-peer-slash")
        await orch._run_review_god("lane-default-review-peer-colon")

    participants = ParticipantStore(tmp_path / "chat.db").list_by_conversation(
        conversation.id
    )
    review_participants = [item for item in participants if item.role == "review"]
    assert review_participants == [participant]
    assert (
        orch._sm.get_lane("lane-default-review-peer-slash")["review_peer_id"]
        == participant.participant_id
    )
    assert (
        orch._sm.get_lane("lane-default-review-peer-colon")["review_peer_id"]
        == participant.participant_id
    )
    assert [call["feature_scope_id"] for call in persistent.ensured] == ["a/b", "a:b"]


@pytest.mark.asyncio
async def test_missing_default_review_peer_does_not_fallback_to_one_shot(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Default review peer degraded")
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-default-peer-degraded",
                conversation_id=conversation.id,
                feature_plan_feature_id="feature-default-peer",
                peer_routing_mode="required",
            )
        ],
    )
    orch._default_review_peer_routing_enabled = True
    persistent = FakePersistentReviewLayer(
        [StdoutMessage(type="result", status="success", artifacts={})]
    )
    orch._review_god_session_layer = persistent

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
    ) as spawn:
        await orch._run_review_god("lane-default-peer-degraded")

    lane = orch._sm.get_lane("lane-default-peer-degraded")
    assert spawn.await_count == 0
    assert persistent.ensured == []
    assert persistent.sent == []
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "required_review_peer_unavailable"
    assert lane["failure_layer"] == "review"
    assert lane["review_peer_defaulted"] is True
    assert lane["review_peer_id"] == "default:opencode"
    assert lane["peer_routing_mode"] == "required"
    assert lane["peer_delivery_mode"] == "required_peer_failed"
    assert lane["peer_degraded_reason"] == "review_peer_runtime_unavailable"


@pytest.mark.asyncio
async def test_default_review_peer_participant_lookup_failure_fails_closed_without_peer_metadata(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Default review peer lookup failure")
    _add_opencode_review_participant(tmp_path, conversation.id)
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-default-peer-lookup-failure",
                conversation_id=conversation.id,
                feature_plan_feature_id="feature-default-peer",
            )
        ],
    )
    orch._default_review_peer_routing_enabled = True
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "Auto persistent fallback approves.",
                    }
                },
            )
        ]
    )
    orch._review_god_session_layer = persistent

    with patch(
        "xmuse_core.platform.execution.review_god._review_peer_participant",
        return_value="ensure_failed",
    ), patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-default-peer-lookup-failure")

    lane = orch._sm.get_lane("lane-default-peer-lookup-failure")
    assert spawn.await_count == 0
    assert persistent.ensured == []
    assert persistent.sent == []
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "required_review_peer_unavailable"
    assert lane["failure_layer"] == "review"
    assert lane["peer_routing_mode"] == "preferred"
    assert lane["peer_delivery_mode"] == "configured_peer_failed"
    assert lane["peer_degraded_reason"] == "ensure_failed"
    assert lane["review_peer_defaulted"] is True
    assert "review_peer_cli_kind" not in lane
    assert "review_peer_model" not in lane


@pytest.mark.asyncio
async def test_default_review_peer_missing_conversation_fails_closed(
    tmp_path: Path,
) -> None:
    ChatStore(tmp_path / "chat.db").create_conversation("Other conversation")
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-default-peer-missing-conversation",
                conversation_id="conv_missing",
                feature_plan_feature_id="feature-default-peer",
            )
        ],
    )
    orch._default_review_peer_routing_enabled = True
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "Auto persistent fallback approves.",
                    }
                },
            )
        ]
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-default-peer-missing-conversation")

    lane = orch._sm.get_lane("lane-default-peer-missing-conversation")
    assert spawn.await_count == 0
    assert persistent.ensured == []
    assert persistent.sent == []
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "required_review_peer_unavailable"
    assert lane["failure_layer"] == "review"
    assert lane["review_peer_defaulted"] is True
    assert lane["review_peer_id"] == "default:opencode"
    assert lane["peer_routing_mode"] == "required"
    assert lane["peer_delivery_mode"] == "required_peer_failed"
    assert lane["peer_degraded_reason"] == "review_peer_runtime_unavailable"


@pytest.mark.asyncio
async def test_default_review_peer_requires_feature_scope(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Default review peer no feature")
    orch = _make_final_action_orchestrator(
        tmp_path,
        [_gated_lane("lane-default-peer-no-feature", conversation_id=conversation.id)],
    )
    orch._default_review_peer_routing_enabled = True
    persistent = FakePersistentReviewLayer()
    orch._review_god_session_layer = persistent

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
    ) as spawn:
        await orch._run_review_god("lane-default-peer-no-feature")

    lane = orch._sm.get_lane("lane-default-peer-no-feature")
    participants = ParticipantStore(tmp_path / "chat.db").list_by_conversation(
        conversation.id
    )
    assert [item for item in participants if item.role == "review"] == []
    assert spawn.await_count == 0
    assert persistent.ensured == []
    assert persistent.sent == []
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "required_review_peer_unavailable"
    assert lane["failure_layer"] == "review"
    assert lane["review_peer_defaulted"] is True
    assert lane["review_peer_id"] == "default:opencode"
    assert lane["peer_routing_mode"] == "required"
    assert lane["peer_delivery_mode"] == "required_peer_failed"
    assert lane["peer_degraded_reason"] == "review_peer_runtime_unavailable"


@pytest.mark.asyncio
async def test_configured_review_peer_preferred_success_records_peer_metadata(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Configured review")
    participant = _add_review_participant(tmp_path, conversation.id)
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-configured-peer",
                conversation_id=conversation.id,
                feature_plan_feature_id="feature-a",
                review_peer_id=participant.participant_id,
                peer_routing_mode="preferred",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "Configured peer approves.",
                    }
                },
            )
        ]
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-configured-peer")

    lane = orch._sm.get_lane("lane-configured-peer")
    assert spawn.await_count == 0
    assert lane["status"] == "awaiting_final_action"
    assert lane["review_peer_id"] == participant.participant_id
    assert lane["peer_request_id"] in persistent.sent[0]["request_id"]
    assert lane["peer_delivery_mode"] == "configured_peer"
    assert lane["review_peer_cli_kind"] == participant.cli_kind
    assert lane["review_peer_model"] == participant.model
    assert "peer_degraded_reason" not in lane


@pytest.mark.asyncio
async def test_review_runtime_opencode_routes_to_existing_review_peer(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("OpenCode review runtime")
    participant = _add_opencode_review_participant(tmp_path, conversation.id)
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-opencode-review-runtime",
                conversation_id=conversation.id,
                feature_plan_feature_id="feature-opencode-review",
                review_runtime="opencode",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={
                    "stdout": "Findings: none\nVerdict: merge",
                },
            )
        ]
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-opencode-review-runtime")

    lane = orch._sm.get_lane("lane-opencode-review-runtime")
    assert spawn.await_count == 0
    assert lane["status"] == "awaiting_final_action"
    assert lane["review_peer_id"] == participant.participant_id
    assert lane["review_runtime_requested"] == "opencode"
    assert lane["peer_routing_mode"] == "required"
    assert lane["peer_delivery_mode"] == "configured_peer"
    assert "Verdict: merge" in lane["review_summary"]
    assert persistent.ensured[0]["participant_id"] == participant.participant_id


@pytest.mark.asyncio
async def test_review_runtime_opencode_without_feature_scope_uses_request_scope(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("OpenCode review runtime request scope")
    participant = _add_opencode_review_participant(tmp_path, conversation.id)
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-opencode-review-runtime-no-feature",
                conversation_id=conversation.id,
                review_runtime="opencode",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={
                    "stdout": "Findings: none\nVerdict: merge",
                },
            )
        ]
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-opencode-review-runtime-no-feature")

    lane = orch._sm.get_lane("lane-opencode-review-runtime-no-feature")
    assert spawn.await_count == 0
    assert lane["status"] == "awaiting_final_action"
    assert lane["review_peer_id"] == participant.participant_id
    assert lane["review_runtime_requested"] == "opencode"
    assert lane["peer_delivery_mode"] == "configured_peer"
    assert persistent.ensured[0]["feature_scope_id"] == (
        "configured-review:lane-opencode-review-runtime-no-feature"
    )


@pytest.mark.asyncio
async def test_review_runtime_opencode_without_peer_fails_closed(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Missing OpenCode review runtime")
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-opencode-review-runtime-missing",
                conversation_id=conversation.id,
                feature_plan_feature_id="feature-opencode-review-missing",
                review_runtime="opencode",
            )
        ],
    )
    orch._review_god_session_layer = FakePersistentReviewLayer()

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-opencode-review-runtime-missing")

    lane = orch._sm.get_lane("lane-opencode-review-runtime-missing")
    assert spawn.await_count == 0
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "required_review_peer_unavailable"
    assert lane["failure_layer"] == "review"
    assert lane["review_peer_id"] == "runtime:opencode"
    assert lane["review_runtime_requested"] == "opencode"
    assert lane["peer_routing_mode"] == "required"
    assert lane["peer_delivery_mode"] == "required_peer_failed"
    assert lane["peer_degraded_reason"] == "review_peer_runtime_unavailable"


@pytest.mark.asyncio
async def test_configured_review_peer_preferred_failure_fails_closed_before_auto_persistent(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Configured review fail closed")
    participant = _add_review_participant(tmp_path, conversation.id)
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-configured-peer-auto-fallback",
                conversation_id=conversation.id,
                feature_plan_feature_id="feature-a",
                review_peer_id=participant.participant_id,
                peer_routing_mode="preferred",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                request_id="wrong-request",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "configured peer must not apply",
                    }
                },
            ),
            StdoutMessage(
                type="result",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "auto persistent approves",
                    }
                },
            ),
        ]
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-configured-peer-auto-fallback")

    lane = orch._sm.get_lane("lane-configured-peer-auto-fallback")
    assert spawn.await_count == 0
    assert len(persistent.sent) == 1
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_peer_delivery_failed"
    assert lane["peer_delivery_mode"] == "configured_peer_failed"
    assert lane["peer_degraded_reason"] == "request_id_mismatch"
    assert lane["review_peer_cli_kind"] == participant.cli_kind
    assert lane["review_peer_model"] == participant.model


@pytest.mark.asyncio
async def test_configured_review_peer_preferred_failure_fails_closed_before_one_shot(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Configured one-shot fail closed")
    participant = _add_review_participant(tmp_path, conversation.id)
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-configured-peer-one-shot-fallback",
                conversation_id=conversation.id,
                review_peer_id=participant.participant_id,
                peer_routing_mode="preferred",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                request_id="wrong-request",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "configured peer must not apply",
                    }
                },
            )
        ]
    )
    orch._review_god_session_layer = persistent
    one_shot = SpawnResult(
        exit_code=0,
        stdout="Findings: ok\nVerdict: merge",
        stderr="",
    )

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        return_value=one_shot,
    ) as spawn:
        await orch._run_review_god("lane-configured-peer-one-shot-fallback")

    lane = orch._sm.get_lane("lane-configured-peer-one-shot-fallback")
    assert spawn.await_count == 0
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_peer_delivery_failed"
    assert lane["peer_delivery_mode"] == "configured_peer_failed"
    assert lane["peer_degraded_reason"] == "request_id_mismatch"
    assert lane["review_peer_cli_kind"] == participant.cli_kind
    assert lane["review_peer_model"] == participant.model


@pytest.mark.asyncio
async def test_required_configured_review_peer_unavailable_hard_fails(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Required missing peer")
    orch = _make_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-required-peer-missing",
                conversation_id=conversation.id,
                review_peer_id="part-missing",
                peer_routing_mode="required",
                feature_plan_feature_id="feature-a",
            )
        ],
    )
    orch._review_god_session_layer = FakePersistentReviewLayer()

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-required-peer-missing")

    lane = orch._sm.get_lane("lane-required-peer-missing")
    assert spawn.await_count == 0
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "required_review_peer_unavailable"
    assert lane["review_peer_id"] == "part-missing"
    assert lane["peer_routing_mode"] == "required"
    assert lane["peer_delivery_mode"] == "required_peer_failed"
    assert lane["peer_degraded_reason"] == "ensure_failed"


@pytest.mark.asyncio
async def test_required_configured_review_peer_without_session_layer_hard_fails(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Required no session layer")
    participant = _add_review_participant(tmp_path, conversation.id)
    orch = _make_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-required-peer-no-layer",
                conversation_id=conversation.id,
                review_peer_id=participant.participant_id,
                peer_routing_mode="required",
                feature_plan_feature_id="feature-a",
            )
        ],
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-required-peer-no-layer")

    lane = orch._sm.get_lane("lane-required-peer-no-layer")
    assert spawn.await_count == 0
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "required_review_peer_unavailable"
    assert lane["peer_delivery_mode"] == "required_peer_failed"
    assert lane["peer_degraded_reason"] == "session_layer_unavailable"


@pytest.mark.asyncio
async def test_required_configured_review_peer_delivery_failure_hard_fails(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Required delivery failure")
    participant = _add_review_participant(tmp_path, conversation.id)
    orch = _make_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-required-peer-delivery",
                conversation_id=conversation.id,
                review_peer_id=participant.participant_id,
                peer_routing_mode="required",
                feature_plan_feature_id="feature-a",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                request_id="wrong-request",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "must not apply",
                    }
                },
            )
        ]
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-required-peer-delivery")

    lane = orch._sm.get_lane("lane-required-peer-delivery")
    assert spawn.await_count == 0
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_peer_delivery_failed"
    assert lane["review_peer_id"] == participant.participant_id
    assert lane["peer_request_id"] in persistent.sent[0]["request_id"]
    assert lane["peer_delivery_mode"] == "required_peer_failed"
    assert lane["peer_degraded_reason"] == "request_id_mismatch"


@pytest.mark.asyncio
async def test_required_configured_review_peer_no_verdict_hard_fails(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Required no verdict")
    participant = _add_review_participant(tmp_path, conversation.id)
    orch = _make_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-required-peer-no-verdict",
                conversation_id=conversation.id,
                review_peer_id=participant.participant_id,
                peer_routing_mode="required",
                feature_plan_feature_id="feature-a",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={"latency_stages": {"turn_completed": {"at": 1.0}}},
            )
        ]
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-required-peer-no-verdict")

    lane = orch._sm.get_lane("lane-required-peer-no-verdict")
    assert spawn.await_count == 0
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_peer_delivery_failed"
    assert lane["peer_delivery_mode"] == "required_peer_failed"
    assert lane["peer_degraded_reason"] == "review_peer_no_verdict"
    assert lane["peer_result_status"] == "ok"
    assert lane["peer_result_message_type"] == "result"
    assert lane["peer_result_message_request_id"] == lane["peer_request_id"]
    assert lane["peer_result_message_status"] == "success"
    assert lane["peer_result_artifact_keys"] == ["latency_stages"]


@pytest.mark.asyncio
async def test_preferred_configured_review_peer_no_verdict_fails_closed(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Preferred no verdict")
    participant = _add_review_participant(tmp_path, conversation.id)
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-preferred-peer-no-verdict",
                conversation_id=conversation.id,
                review_peer_id=participant.participant_id,
                peer_routing_mode="preferred",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={},
            )
        ]
    )
    orch._review_god_session_layer = persistent
    one_shot = SpawnResult(
        exit_code=0,
        stdout="Findings: ok\nVerdict: merge",
        stderr="",
    )

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        return_value=one_shot,
    ) as spawn:
        await orch._run_review_god("lane-preferred-peer-no-verdict")

    lane = orch._sm.get_lane("lane-preferred-peer-no-verdict")
    assert spawn.await_count == 0
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_peer_delivery_failed"
    assert lane["peer_delivery_mode"] == "configured_peer_failed"
    assert lane["peer_degraded_reason"] == "review_peer_no_verdict"


@pytest.mark.asyncio
async def test_configured_review_peer_rejects_non_review_participant(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Wrong peer role")
    participant = _add_architect_participant(tmp_path, conversation.id)
    orch = _make_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-required-peer-wrong-role",
                conversation_id=conversation.id,
                review_peer_id=participant.participant_id,
                peer_routing_mode="required",
                feature_plan_feature_id="feature-a",
            )
        ],
    )
    orch._review_god_session_layer = FakePersistentReviewLayer()

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-required-peer-wrong-role")

    lane = orch._sm.get_lane("lane-required-peer-wrong-role")
    assert spawn.await_count == 0
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "required_review_peer_unavailable"
    assert lane["peer_degraded_reason"] == "review_peer_role_mismatch"


@pytest.mark.asyncio
async def test_review_god_uses_persistent_conversation_session_when_available(
    tmp_path: Path,
) -> None:
    """A conversation-scoped lane should be reviewed through persistent Review GOD."""
    chat = ChatStore(tmp_path / "chat.db")
    conversation = chat.create_conversation("Review lane")
    chat.add_message(
        conversation.id,
        author="human",
        role="human",
        content="Please review this against the blueprint.",
    )
    blueprint = tmp_path / "docs" / "blueprint.md"
    blueprint.parent.mkdir(parents=True)
    blueprint.write_text("Mission: keep review semantic in GOD.", encoding="utf-8")
    gate_report = tmp_path / "logs" / "gates" / "lane-persistent" / "report.json"
    gate_report.parent.mkdir(parents=True)
    gate_report.write_text(json.dumps({"passed": True}), encoding="utf-8")
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-persistent",
                conversation_id=conversation.id,
                blueprint_refs=["docs/blueprint.md"],
                acceptance_criteria=["Review GOD judges blueprint compliance."],
                feature_plan_feature_id="runtime-alignment",
                feature_title="Runtime Alignment",
                feature_goal="Persistent Review GOD owns review context.",
                retry_count=1,
                review_summary="Previous attempt missed acceptance criteria.",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "Persistent Review GOD approves with evidence.",
                    }
                },
            )
        ]
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-persistent")

    lane = orch._sm.get_lane("lane-persistent")
    assert lane["status"] == "awaiting_final_action"
    assert spawn.await_count == 0
    assert persistent.ensured[0]["conversation_id"] == conversation.id
    assert persistent.ensured[0]["model"] == "gpt-5.4"
    assert str(persistent.ensured[0]["worktree"]) == str(tmp_path)
    assert str(persistent.ensured[0]["prompt_fingerprint"]).startswith("sha256:")
    assert persistent.ensured[0]["feature_scope_id"] == "runtime-alignment"
    assert str(persistent.ensured[0]["participant_id"]).startswith(
        "review-god-feature-runtime-alignment-"
    )
    sent = persistent.sent[0]
    assert str(sent["god_session_id"]).startswith(
        f"god-{conversation.id}-review-god-feature-runtime-alignment-"
    )
    assert sent["message_type"] == "review"
    assert sent["request_id"] == lane["review_request_id"]
    assert "Mission: keep review semantic in GOD." in sent["prompt"]
    assert "Review GOD judges blueprint compliance." in sent["prompt"]
    assert "[human/human] Please review this against the blueprint." in sent["context"]
    assert "Gate report: logs/gates/lane-persistent/report.json" in sent["prompt"]
    assert "Previous attempt missed acceptance criteria." in sent["prompt"]


@pytest.mark.asyncio
async def test_persistent_review_ignores_progress_until_result(
    tmp_path: Path,
) -> None:
    """Progress text must not be parsed as a final Review GOD verdict."""
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-progress-before-result",
                conversation_id="conv-review-progress",
                feature_plan_feature_id="review-progress",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="progress",
                message="Findings:\n1. Important: still investigating.\nVerdict: rework",
            ),
            StdoutMessage(
                type="heartbeat",
                message="review still running",
            ),
            StdoutMessage(
                type="result",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "Final persistent review approved.",
                    }
                },
            ),
        ]
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-progress-before-result")

    lane = orch._sm.get_lane("lane-progress-before-result")
    assert spawn.await_count == 0
    assert lane["status"] == "awaiting_final_action"
    assert lane["review_decision"] == "merge"
    assert lane["review_summary"] == "Final persistent review approved."


@pytest.mark.asyncio
async def test_persistent_review_receives_lane_prompt_when_no_diff_is_available(
    tmp_path: Path,
) -> None:
    """Persistent Review GOD must receive lane context, not only metadata."""
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-context-only",
                conversation_id="conv-review-context",
                feature_plan_feature_id="review-context",
                prompt="Implement the durable review transcript export.",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "Persistent review had lane context.",
                    }
                },
            )
        ]
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock):
        await orch._run_review_god("lane-context-only")

    sent = persistent.sent[0]
    assert "Implement the durable review transcript export." in sent["context"]
    assert persistent.prompt_contracts[0][0] == sent["god_session_id"]
    assert persistent.prompt_contracts[0][1]["prompt_contract_version"] == (
        "xmuse-persistent-review-session-prompt-v1"
    )
    assert persistent.prompt_contracts[0][1]["prompt_artifact_fingerprint"] == (
        persistent.ensured[0]["prompt_fingerprint"]
    )


@pytest.mark.asyncio
async def test_persistent_review_receives_gate_report_in_session_context(
    tmp_path: Path,
) -> None:
    """Persistent Review GOD should get gate evidence in the session payload."""
    gate_report = tmp_path / "logs" / "gates" / "lane-gate-context" / "report.json"
    gate_report.parent.mkdir(parents=True)
    gate_report.write_text(json.dumps({"passed": True}), encoding="utf-8")
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-gate-context",
                conversation_id="conv-review-gate",
                feature_plan_feature_id="review-gate",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "Persistent review had gate evidence.",
                    }
                },
            )
        ]
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock):
        await orch._run_review_god("lane-gate-context")

    sent = persistent.sent[0]
    assert "Gate report: logs/gates/lane-gate-context/report.json" in sent["context"]


@pytest.mark.asyncio
async def test_persistent_review_session_selection_is_feature_scoped(
    tmp_path: Path,
) -> None:
    """Review GOD must reuse one session for same feature and split by feature."""
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-feature-a-1",
                conversation_id="conv-review-a",
                feature_plan_feature_id="feature-a",
            ),
            _gated_lane(
                "lane-feature-a-2",
                conversation_id="conv-review-a",
                feature_plan_feature_id="feature-a",
            ),
            _gated_lane(
                "lane-feature-b",
                conversation_id="conv-review-a",
                feature_plan_feature_id="feature-b",
            ),
        ],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={"review_verdict": {"decision": "merge", "summary": "ok a1"}},
            ),
            StdoutMessage(
                type="result",
                status="success",
                artifacts={"review_verdict": {"decision": "merge", "summary": "ok a2"}},
            ),
            StdoutMessage(
                type="result",
                status="success",
                artifacts={"review_verdict": {"decision": "merge", "summary": "ok b"}},
            ),
        ]
    )
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await orch._run_review_god("lane-feature-a-1")
        await orch._run_review_god("lane-feature-a-2")
        await orch._run_review_god("lane-feature-b")

    assert spawn.await_count == 0
    assert [call["conversation_id"] for call in persistent.ensured] == [
        "conv-review-a",
        "conv-review-a",
        "conv-review-a",
    ]
    assert [call["god_session_id"] for call in persistent.sent] == [
        persistent.sent[0]["god_session_id"],
        persistent.sent[0]["god_session_id"],
        persistent.sent[2]["god_session_id"],
    ]
    assert persistent.sent[0]["god_session_id"] != persistent.sent[2]["god_session_id"]


@pytest.mark.asyncio
async def test_persistent_review_requires_feature_identity_for_aligned_path(
    tmp_path: Path,
) -> None:
    orch = _make_orchestrator(
        tmp_path,
        [_gated_lane("lane-missing-feature", conversation_id="conv-review-missing-feature")],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={"review_verdict": {"decision": "merge", "summary": "bad"}},
            )
        ]
    )
    orch._review_god_session_layer = persistent
    empty_fallback = SpawnResult(exit_code=0, stdout="", stderr="")

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        return_value=empty_fallback,
    ) as spawn:
        await orch._run_review_god("lane-missing-feature")

    lane = orch._sm.get_lane("lane-missing-feature")
    assert persistent.ensured == []
    assert spawn.await_count == 1
    assert lane["persistent_review_degraded_reason"] == "missing_feature_identity"
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_no_verdict"


@pytest.mark.asyncio
async def test_persistent_review_same_feature_is_single_flight(tmp_path: Path) -> None:
    orch = _make_final_action_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-single-flight-a",
                conversation_id="conv-review-single-flight",
                feature_plan_feature_id="feature-single-flight",
            ),
            _gated_lane(
                "lane-single-flight-b",
                conversation_id="conv-review-single-flight",
                feature_plan_feature_id="feature-single-flight",
            ),
        ],
    )
    persistent = SlowPersistentReviewLayer()
    orch._review_god_session_layer = persistent

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        await asyncio.gather(
            orch._run_review_god("lane-single-flight-a"),
            orch._run_review_god("lane-single-flight-b"),
        )

    assert spawn.await_count == 0
    assert persistent.max_in_flight == 1
    assert [call["god_session_id"] for call in persistent.sent] == [
        persistent.sent[0]["god_session_id"],
        persistent.sent[0]["god_session_id"],
    ]


@pytest.mark.asyncio
async def test_persistent_delivery_failure_falls_back_without_auto_approval(
    tmp_path: Path,
) -> None:
    """A failed persistent delivery may use one-shot fallback but must not approve itself."""
    orch = _make_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-delivery-fail",
                conversation_id="conv-review-fail",
                feature_plan_feature_id="review-fail",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(fail_send=True)
    orch._review_god_session_layer = persistent
    empty_fallback = SpawnResult(exit_code=0, stdout="", stderr="")

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        return_value=empty_fallback,
    ) as spawn:
        await orch._run_review_god("lane-delivery-fail")

    lane = orch._sm.get_lane("lane-delivery-fail")
    assert spawn.await_count == 1
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_no_verdict"
    assert lane["persistent_review_degraded_reason"] == "send_failed"
    assert "review_fallback" not in lane
    assert persistent.aborted == [
        persistent.sent[0]["god_session_id"]
    ]


@pytest.mark.asyncio
async def test_persistent_ensure_failure_records_distinct_degraded_reason(
    tmp_path: Path,
) -> None:
    orch = _make_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-ensure-fail",
                conversation_id="conv-review-ensure-fail",
                feature_plan_feature_id="review-ensure-fail",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(fail_ensure=True)
    orch._review_god_session_layer = persistent
    empty_fallback = SpawnResult(exit_code=0, stdout="", stderr="")

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        return_value=empty_fallback,
    ):
        await orch._run_review_god("lane-ensure-fail")

    lane = orch._sm.get_lane("lane-ensure-fail")
    assert lane["persistent_review_degraded_reason"] == "ensure_failed"
    assert "review_fallback" not in lane


@pytest.mark.asyncio
async def test_persistent_receive_failure_falls_back_without_auto_approval(
    tmp_path: Path,
) -> None:
    orch = _make_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-receive-fail",
                conversation_id="conv-review-receive-fail",
                feature_plan_feature_id="review-receive-fail",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(fail_receive=True)
    orch._review_god_session_layer = persistent
    empty_fallback = SpawnResult(exit_code=0, stdout="", stderr="")

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        return_value=empty_fallback,
    ) as spawn:
        await orch._run_review_god("lane-receive-fail")

    lane = orch._sm.get_lane("lane-receive-fail")
    assert spawn.await_count == 1
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_no_verdict"
    assert lane["persistent_review_degraded_reason"] == "receive_failed"
    assert "review_fallback" not in lane
    assert persistent.aborted == [
        persistent.sent[0]["god_session_id"]
    ]


@pytest.mark.asyncio
async def test_persistent_review_timeout_aborts_session_before_fallback(
    tmp_path: Path,
) -> None:
    orch = _make_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-review-timeout",
                conversation_id="conv-review-timeout",
                feature_plan_feature_id="review-timeout",
            )
        ],
    )
    persistent = TimeoutPersistentReviewLayer()
    orch._review_god_session_layer = persistent
    empty_fallback = SpawnResult(exit_code=0, stdout="", stderr="")

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        return_value=empty_fallback,
    ) as spawn:
        await orch._run_review_god("lane-review-timeout")

    lane = orch._sm.get_lane("lane-review-timeout")
    assert spawn.await_count == 1
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_no_verdict"
    assert lane["persistent_review_degraded_reason"] == "receive_timeout"
    assert "review_fallback" not in lane
    assert persistent.aborted == [
        persistent.sent[0]["god_session_id"]
    ]


@pytest.mark.asyncio
async def test_persistent_review_error_message_aborts_session_before_fallback(
    tmp_path: Path,
) -> None:
    orch = _make_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-review-error",
                conversation_id="conv-review-error",
                feature_plan_feature_id="review-error",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(
        [StdoutMessage(type="error", message="review session failed")]
    )
    orch._review_god_session_layer = persistent
    empty_fallback = SpawnResult(exit_code=0, stdout="", stderr="")

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        return_value=empty_fallback,
    ) as spawn:
        await orch._run_review_god("lane-review-error")

    lane = orch._sm.get_lane("lane-review-error")
    assert spawn.await_count == 1
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_no_verdict"
    assert lane["persistent_review_degraded_reason"] == "receive_error"
    assert "review_fallback" not in lane
    assert persistent.aborted == [
        persistent.sent[0]["god_session_id"]
    ]


@pytest.mark.asyncio
async def test_persistent_review_no_message_aborts_session_before_fallback(
    tmp_path: Path,
) -> None:
    orch = _make_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-review-empty",
                conversation_id="conv-review-empty",
                feature_plan_feature_id="review-empty",
            )
        ],
    )
    persistent = FakePersistentReviewLayer()
    orch._review_god_session_layer = persistent
    empty_fallback = SpawnResult(exit_code=0, stdout="", stderr="")

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        return_value=empty_fallback,
    ) as spawn:
        await orch._run_review_god("lane-review-empty")

    lane = orch._sm.get_lane("lane-review-empty")
    assert spawn.await_count == 1
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_no_verdict"
    assert lane["persistent_review_degraded_reason"] == "no_result_message"
    assert "review_fallback" not in lane
    assert persistent.aborted == [
        persistent.sent[0]["god_session_id"]
    ]


@pytest.mark.asyncio
async def test_persistent_review_missing_request_id_falls_back_without_applying_verdict(
    tmp_path: Path,
) -> None:
    orch = _make_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-review-missing-request",
                conversation_id="conv-review-missing-request",
                feature_plan_feature_id="review-missing-request",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "must not apply",
                    }
                },
            )
        ],
        echo_request_id=False,
    )
    orch._review_god_session_layer = persistent
    empty_fallback = SpawnResult(exit_code=0, stdout="", stderr="")

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        return_value=empty_fallback,
    ) as spawn:
        await orch._run_review_god("lane-review-missing-request")

    lane = orch._sm.get_lane("lane-review-missing-request")
    assert spawn.await_count == 1
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_no_verdict"
    assert lane["persistent_review_degraded_reason"] == "request_id_missing"
    assert "review_summary" not in lane


@pytest.mark.asyncio
async def test_persistent_review_mismatched_request_id_falls_back_without_applying_verdict(
    tmp_path: Path,
) -> None:
    orch = _make_orchestrator(
        tmp_path,
        [
            _gated_lane(
                "lane-review-mismatch-request",
                conversation_id="conv-review-mismatch-request",
                feature_plan_feature_id="review-mismatch-request",
            )
        ],
    )
    persistent = FakePersistentReviewLayer(
        [
            StdoutMessage(
                type="result",
                request_id="wrong-request",
                status="success",
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "must not apply",
                    }
                },
            )
        ],
    )
    orch._review_god_session_layer = persistent
    empty_fallback = SpawnResult(exit_code=0, stdout="", stderr="")

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        return_value=empty_fallback,
    ) as spawn:
        await orch._run_review_god("lane-review-mismatch-request")

    lane = orch._sm.get_lane("lane-review-mismatch-request")
    assert spawn.await_count == 1
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_no_verdict"
    assert lane["persistent_review_degraded_reason"] == "request_id_mismatch"
    assert "review_summary" not in lane


@pytest.mark.asyncio
async def test_rework_verdict_from_stdout_fallback_is_ingested_in_review_plane(
    tmp_path: Path,
) -> None:
    """When _run_review_god infers rework from stdout, the verdict is persisted."""
    orch = _make_orchestrator(tmp_path, [_gated_lane("lane-rw")])

    review_result = SpawnResult(
        exit_code=0,
        stdout="**Findings**\n1. High: core behavior is incorrect.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock, return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock):
            await orch._run_review_god("lane-rw")

    lane = orch._sm.get_lane("lane-rw")
    task_id = lane.get("review_task_id")
    assert task_id is not None, "review_task_id must be stamped on the lane"

    # The rework verdict must be persisted in the review plane store.
    task = orch._review_plane.store.get_task(task_id)
    assert task.verdict_id is not None, "task must have a verdict_id after rework"
    verdict = orch._review_plane.store.get_verdict(task.verdict_id)
    assert verdict.lane_id == "lane-rw"
    assert verdict.decision == ReviewDecision.REWORK
    assert task.status == ReviewTaskStatus.VERDICT_EMITTED


@pytest.mark.asyncio
async def test_committed_mcp_rework_is_ingested_in_review_plane(
    tmp_path: Path,
) -> None:
    """A Review GOD MCP rejection closes the current ReviewTask as rework."""
    orch = _make_orchestrator(tmp_path, [_gated_lane("lane-mcp-rw")])

    async def _spawn_and_commit_rework(**_kwargs):
        orch._sm.transition(
            "lane-mcp-rw",
            "rejected",
            metadata={
                "review_decision": "rework",
                "review_summary": "keep contract coverage",
            },
        )
        return SpawnResult(exit_code=0, stdout="", stderr="")

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock) as spawn:
        spawn.side_effect = _spawn_and_commit_rework
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock):
            await orch._run_review_god("lane-mcp-rw")

    lane = orch._sm.get_lane("lane-mcp-rw")
    task_id = lane.get("review_task_id")
    assert task_id is not None
    task = orch._review_plane.store.get_task(task_id)
    assert task.status == ReviewTaskStatus.VERDICT_EMITTED
    assert task.verdict_id is not None
    verdict = orch._review_plane.store.get_verdict(task.verdict_id)
    assert verdict.decision == ReviewDecision.REWORK
    assert verdict.summary == "keep contract coverage"


@pytest.mark.asyncio
async def test_empty_review_stdout_closes_review_task_with_failure_verdict(
    tmp_path: Path,
) -> None:
    """A successful provider exit with no verdict is auditable, but not approval."""
    orch = _make_orchestrator(tmp_path, [_gated_lane("lane-no-verdict")])

    review_result = SpawnResult(
        exit_code=0,
        stdout="",
        stderr="transport transcript only",
        stdout_log_path="logs/agent_spawns/lane-no-verdict/stdout.log",
        stderr_log_path="logs/agent_spawns/lane-no-verdict/stderr.log",
        result_log_path="logs/agent_spawns/lane-no-verdict/result.json",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock, return_value=review_result):
        await orch._run_review_god("lane-no-verdict")

    lane = orch._sm.get_lane("lane-no-verdict")
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_no_verdict"
    task_id = lane.get("review_task_id")
    assert task_id is not None
    task = orch._review_plane.store.get_task(task_id)
    assert task.status == ReviewTaskStatus.VERDICT_EMITTED
    assert task.verdict_id is not None
    verdict = orch._review_plane.store.get_verdict(task.verdict_id)
    assert verdict.decision == ReviewDecision.TERMINATE
    assert verdict.status == "review_failed"
    assert verdict.terminate_reason == "review_no_verdict"
    assert verdict.evidence_refs == []
    assert "review_summary" not in lane


@pytest.mark.asyncio
async def test_rework_verdict_lineage_preserved_after_requeue(tmp_path: Path) -> None:
    """After a rework rejection, the original verdict is preserved in lineage."""
    orch = _make_orchestrator(tmp_path, [_gated_lane("lane-requeue")])

    rework_result = SpawnResult(
        exit_code=0,
        stdout="**Findings**\n1. High: logic is wrong.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock, return_value=rework_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock):
            await orch._run_review_god("lane-requeue")

    lineage = orch.verdict_lineage_for_lane("lane-requeue")

    assert len(lineage) == 1
    entry = lineage[0]
    assert entry["verdict"] is not None
    assert entry["verdict"]["decision"] == "rework"
    assert entry["task"]["verdict_id"] == entry["verdict"]["id"]


@pytest.mark.asyncio
async def test_rework_verdict_ingestion_skipped_when_no_task_id(tmp_path: Path) -> None:
    """ingest_rework_verdict is a no-op when review_task_id is absent."""
    orch = _make_orchestrator(
        tmp_path,
        [
            {
                "feature_id": "lane-no-task",
                "status": "rejected",
                "prompt": "fix",
                "review_decision": "rework",
                "review_summary": "Needs rework.",
                # No review_task_id
            }
        ],
    )

    # Should not raise.
    ingest_rework_verdict(
        "lane-no-task",
        "Needs rework.",
        lane=orch._sm.get_lane("lane-no-task"),
        review_plane=orch._review_plane,
    )

    # No tasks should exist in the store.
    tasks = orch._review_plane.store.list_tasks_for_lane("lane-no-task")
    assert tasks == []


@pytest.mark.asyncio
async def test_rework_verdict_ingestion_failure_does_not_break_rejection_path(
    tmp_path: Path,
) -> None:
    """A review plane failure during rework ingestion must not prevent lane rejection."""
    orch = _make_orchestrator(tmp_path, [_gated_lane("lane-fail-ingest")])

    rework_result = SpawnResult(
        exit_code=0,
        stdout="**Findings**\n1. High: logic is wrong.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock, return_value=rework_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock):
            with patch.object(
                orch._review_plane,
                "ingest_verdict",
                side_effect=RuntimeError("store failure"),
            ):
                # Should not raise.
                await orch._run_review_god("lane-fail-ingest")

    lane = orch._sm.get_lane("lane-fail-ingest")
    assert lane["status"] == "reworking"


@pytest.mark.asyncio
async def test_multiple_rework_cycles_produce_multiple_verdict_entries(
    tmp_path: Path,
) -> None:
    """Two rework cycles produce two verdict entries in the lineage."""
    orch = _make_orchestrator(tmp_path, [_gated_lane("lane-multi-rw")])

    rework_result = SpawnResult(
        exit_code=0,
        stdout="**Findings**\n1. High: logic is wrong.",
        stderr="",
    )

    # First rework cycle.
    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock, return_value=rework_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock):
            await orch._run_review_god("lane-multi-rw")

    # Simulate lane returning to gated for second review via the reworking path.
    # After on_lane_rejected, lane is already in reworking state.
    # reworking -> dispatched -> executed -> gated
    orch._sm.transition("lane-multi-rw", "dispatched")
    orch._sm.transition("lane-multi-rw", "executed")
    orch._sm.transition("lane-multi-rw", "gated", metadata={"gate_passed": True})

    # Second rework cycle.
    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock, return_value=rework_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock):
            await orch._run_review_god("lane-multi-rw")

    lineage = orch.verdict_lineage_for_lane("lane-multi-rw")

    assert len(lineage) == 2
    decisions = {entry["verdict"]["decision"] for entry in lineage if entry["verdict"]}
    assert decisions == {"rework"}


# ---------------------------------------------------------------------------
# verdict_lineage_for_run on orchestrator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verdict_lineage_for_run_returns_entries_for_graph_lanes(
    tmp_path: Path,
) -> None:
    """verdict_lineage_for_run returns lineage for all lanes in a graph."""
    graph_id = "graph-run-orch"
    lanes = [
        {**_gated_lane("lane-a"), "graph_id": graph_id},
        {**_gated_lane("lane-b"), "graph_id": graph_id},
    ]
    orch = _make_orchestrator(tmp_path, lanes)

    # Open tasks and ingest merge verdicts for both lanes.
    task_a = orch._review_plane.open_review_task("lane-a")
    task_b = orch._review_plane.open_review_task("lane-b")

    from xmuse_core.structuring.models import ReviewVerdict

    orch._review_plane.ingest_verdict(
        task_a.task_id,
        ReviewVerdict(
            id="verdict-run-a",
            lane_id="lane-a",
            decision=ReviewDecision.MERGE,
            summary="No findings.",
        ),
    )
    orch._review_plane.ingest_verdict(
        task_b.task_id,
        ReviewVerdict(
            id="verdict-run-b",
            lane_id="lane-b",
            decision=ReviewDecision.MERGE,
            summary="No findings.",
        ),
    )

    lineage = orch.verdict_lineage_for_run(graph_id)

    lane_ids = {entry["task"]["lane_id"] for entry in lineage}
    assert lane_ids == {"lane-a", "lane-b"}
    verdict_ids = {entry["verdict"]["id"] for entry in lineage if entry["verdict"]}
    assert verdict_ids == {"verdict-run-a", "verdict-run-b"}


def test_verdict_lineage_for_run_returns_empty_for_unknown_graph(tmp_path: Path) -> None:
    """verdict_lineage_for_run returns [] for a graph with no review tasks."""
    orch = _make_orchestrator(
        tmp_path,
        [{**_gated_lane("lane-x"), "graph_id": "graph-x"}],
    )

    lineage = orch.verdict_lineage_for_run("graph-nonexistent")

    assert lineage == []


@pytest.mark.asyncio
async def test_verdict_lineage_for_run_excludes_lanes_from_other_graphs(
    tmp_path: Path,
) -> None:
    """verdict_lineage_for_run only returns lanes belonging to the requested graph."""
    lanes = [
        {**_gated_lane("lane-target"), "graph_id": "graph-target"},
        {**_gated_lane("lane-other"), "graph_id": "graph-other"},
    ]
    orch = _make_orchestrator(tmp_path, lanes)

    from xmuse_core.structuring.models import ReviewVerdict

    task_target = orch._review_plane.open_review_task("lane-target")
    task_other = orch._review_plane.open_review_task("lane-other")
    orch._review_plane.ingest_verdict(
        task_target.task_id,
        ReviewVerdict(
            id="verdict-target",
            lane_id="lane-target",
            decision=ReviewDecision.MERGE,
            summary="ok",
        ),
    )
    orch._review_plane.ingest_verdict(
        task_other.task_id,
        ReviewVerdict(
            id="verdict-other",
            lane_id="lane-other",
            decision=ReviewDecision.MERGE,
            summary="ok",
        ),
    )

    lineage = orch.verdict_lineage_for_run("graph-target")

    lane_ids = {entry["task"]["lane_id"] for entry in lineage}
    assert lane_ids == {"lane-target"}
    assert "lane-other" not in lane_ids


@pytest.mark.asyncio
async def test_verdict_lineage_for_run_includes_patch_forward_descendants(
    tmp_path: Path,
) -> None:
    """Patch-forward lanes linked via source_lane_id appear in run lineage."""
    graph_id = "graph-pf-orch"
    lanes = [
        {**_gated_lane("lane-orig"), "graph_id": graph_id},
        {
            "feature_id": "lane-orig-patch-forward",
            "status": "gated",
            "prompt": "Fix edge case.",
            "graph_id": graph_id,
            "source_lane_id": "lane-orig",
            "gate_passed": True,
        },
    ]
    orch = _make_orchestrator(tmp_path, lanes)

    from xmuse_core.structuring.models import ReviewVerdict

    task_orig = orch._review_plane.open_review_task("lane-orig")
    task_pf = orch._review_plane.open_review_task("lane-orig-patch-forward")
    orch._review_plane.ingest_verdict(
        task_orig.task_id,
        ReviewVerdict(
            id="verdict-orig-pf",
            lane_id="lane-orig",
            decision=ReviewDecision.MERGE,
            summary="ok",
        ),
    )
    orch._review_plane.ingest_verdict(
        task_pf.task_id,
        ReviewVerdict(
            id="verdict-pf-pf",
            lane_id="lane-orig-patch-forward",
            decision=ReviewDecision.MERGE,
            summary="ok",
        ),
    )

    lineage = orch.verdict_lineage_for_run(graph_id)

    lane_ids = {entry["task"]["lane_id"] for entry in lineage}
    assert "lane-orig" in lane_ids
    assert "lane-orig-patch-forward" in lane_ids


# ---------------------------------------------------------------------------
# Rework verdict ingestion via on_lane_reviewed (existing path, regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_lane_reviewed_with_rework_decision_ingests_verdict(
    tmp_path: Path,
) -> None:
    """on_lane_reviewed with a rework decision ingests the verdict through review plane.

    The rework path in on_lane_reviewed calls ingest_verdict before transitioning
    to rejected.  This test verifies the verdict is persisted even when the lane
    is in the gated state and the review GOD stdout fallback produces a rework.
    """
    orch = _make_orchestrator(tmp_path, [_gated_lane("lane-rw-reviewed")])

    # Simulate review GOD returning a rework verdict via stdout fallback.
    rework_result = SpawnResult(
        exit_code=0,
        stdout="**Findings**\n1. High: core behavior is incorrect.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock, return_value=rework_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock):
            await orch._run_review_god("lane-rw-reviewed")

    lane = orch._sm.get_lane("lane-rw-reviewed")
    task_id = lane.get("review_task_id")
    assert task_id is not None

    # The verdict must be persisted with the rework decision.
    task = orch._review_plane.store.get_task(task_id)
    assert task.verdict_id is not None
    verdict = orch._review_plane.store.get_verdict(task.verdict_id)
    assert verdict.decision == ReviewDecision.REWORK
    assert verdict.task_id == task_id
