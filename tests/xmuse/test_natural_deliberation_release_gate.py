from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.natural_deliberation_release_gate import (
    capture_natural_deliberation_release_gate,
)
from xmuse_core.platform.release_readiness_capture import capture_release_readiness


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _transcript(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "xmuse.operator_transcript.v1",
        "conversation_id": "conv-prod-1",
        "proof_level": "real_provider_proof",
        "fact_state": "observed",
        "natural_deliberation": True,
        "source_refs": ["memory://conversation/conv-prod-1/transcript"],
        "target_refs": ["blueprint:prod:1", "lane:prod-a"],
        "messages": [
            {
                "message_id": "msg-1",
                "conversation_id": "conv-prod-1",
                "god_id": "architect-god",
                "provider_id": "codex",
                "provider_profile": "codex-prod",
                "session_id": "codex-session-1",
                "speech_act": "propose",
                "decision_scope": "blueprint.freeze",
                "source_refs": ["memory://conversation/conv-prod-1/source"],
                "target_refs": ["blueprint:prod:1"],
                "blocking": False,
            },
            {
                "message_id": "msg-2",
                "conversation_id": "conv-prod-1",
                "god_id": "review-god",
                "provider_id": "opencode",
                "provider_profile": "opencode-prod",
                "session_id": "opencode-session-1",
                "speech_act": "vote",
                "decision_scope": "blueprint.freeze",
                "source_refs": ["message:msg-1"],
                "target_refs": ["blueprint:prod:1", "lane:prod-a"],
                "blocking": False,
            },
        ],
        "blockers": [],
    }
    payload.update(overrides)
    return payload


def _runtime(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "xmuse.god_runtime_continuity.v1",
        "conversation_id": "conv-prod-1",
        "proof_level": "real_provider_proof",
        "fact_state": "observed",
        "source_refs": ["god_cli_selection:conv-prod-1"],
        "items": [
            {
                "god_id": "architect-god",
                "cli_id": "codex.god",
                "peer_god_ready": True,
                "bounded": False,
                "provider_session_ready": True,
                "proof_level": "real_provider_proof",
                "source_refs": ["god_session:architect"],
            },
            {
                "god_id": "review-god",
                "cli_id": "review.peer",
                "peer_god_ready": True,
                "bounded": False,
                "provider_session_ready": True,
                "proof_level": "real_provider_proof",
                "source_refs": ["god_session:review"],
            },
        ],
    }
    payload.update(overrides)
    return payload


def test_natural_deliberation_gate_blocks_real_transcript_without_selected_runtime(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "natural-transcript.json"
    gate_output = tmp_path / "gates" / "natural-deliberation.json"
    _write_json(artifact, _transcript())

    gate = capture_natural_deliberation_release_gate(
        artifact_path=artifact,
        output_path=gate_output,
    )

    assert gate_output.exists()
    assert gate["schema_version"] == "xmuse.production_evidence.v1"
    assert gate["gate_id"] == "natural-god-deliberation"
    assert gate["kind"] == "natural_deliberation"
    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "requires selected GOD runtime continuity" in gate["summary"]
    assert gate["source_refs"] == [
        "memory://conversation/conv-prod-1/transcript",
        "conversation:conv-prod-1",
        "god:architect-god",
        "god:review-god",
        "provider:codex",
        "provider:opencode",
    ]
    report = capture_release_readiness(
        artifacts_dir=tmp_path / "gates",
        output_path=tmp_path / "release-readiness.json",
    )
    assert report["decision"] == "blocked"


def test_natural_deliberation_gate_accepts_real_multi_god_transcript_with_selected_runtime(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "natural-transcript.json"
    runtime = tmp_path / "god-runtime.json"
    gate_output = tmp_path / "gates" / "natural-deliberation.json"
    _write_json(artifact, _transcript())
    _write_json(runtime, _runtime())

    gate = capture_natural_deliberation_release_gate(
        artifact_path=artifact,
        output_path=gate_output,
        god_runtime_path=runtime,
    )

    assert gate_output.exists()
    assert gate["schema_version"] == "xmuse.production_evidence.v1"
    assert gate["gate_id"] == "natural-god-deliberation"
    assert gate["kind"] == "natural_deliberation"
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "real_provider_proof"
    assert gate["source_refs"] == [
        "memory://conversation/conv-prod-1/transcript",
        "conversation:conv-prod-1",
        "god:architect-god",
        "god:review-god",
        "provider:codex",
        "provider:opencode",
    ]
    assert str(runtime) in gate["artifacts"]
    report = capture_release_readiness(
        artifacts_dir=tmp_path / "gates",
        output_path=tmp_path / "release-readiness.json",
    )
    assert report["decision"] == "ready"


def test_natural_deliberation_gate_blocks_contract_replay(tmp_path: Path) -> None:
    artifact = tmp_path / "replay-transcript.json"
    _write_json(
        artifact,
        _transcript(
            proof_level="contract_proof",
            natural_deliberation=False,
        ),
    )

    gate = capture_natural_deliberation_release_gate(
        artifact_path=artifact,
        output_path=tmp_path / "gate.json",
    )

    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "requires real_provider_proof" in gate["summary"]
    assert "natural_deliberation" in gate["summary"]


def test_natural_deliberation_gate_blocks_single_god_transcript(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "single-god-transcript.json"
    payload = _transcript()
    messages = payload["messages"]
    assert isinstance(messages, list)
    for message in messages:
        assert isinstance(message, dict)
        message["god_id"] = "architect-god"
    _write_json(artifact, payload)

    gate = capture_natural_deliberation_release_gate(
        artifact_path=artifact,
        output_path=tmp_path / "gate.json",
    )

    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "at least two distinct GOD participants" in gate["summary"]


def test_natural_deliberation_gate_blocks_unresolved_blockers(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "blocked-transcript.json"
    runtime = tmp_path / "god-runtime.json"
    _write_json(
        artifact,
        _transcript(
            fact_state="blocked",
            blockers=[
                {
                    "message_id": "msg-2",
                    "reason": "acceptance criteria unresolved",
                    "target_refs": ["blueprint:prod:1"],
                }
            ],
        ),
    )
    _write_json(runtime, _runtime())

    gate = capture_natural_deliberation_release_gate(
        artifact_path=artifact,
        output_path=tmp_path / "gate.json",
        god_runtime_path=runtime,
    )

    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "real_provider_proof"
    assert "unresolved blockers" in gate["summary"]


def test_natural_deliberation_gate_blocks_bounded_selected_god_runtime(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "natural-transcript.json"
    runtime = tmp_path / "god-runtime.json"
    _write_json(artifact, _transcript())
    _write_json(
        runtime,
        {
            "schema_version": "xmuse.god_runtime_continuity.v1",
            "conversation_id": "conv-prod-1",
            "proof_level": "contract_proof",
            "fact_state": "blocked",
            "source_refs": ["god_cli_selection:conv-prod-1"],
            "items": [
                {
                    "god_id": "architect-god",
                    "cli_id": "codex.god",
                    "peer_god_ready": True,
                    "bounded": False,
                    "provider_session_ready": True,
                    "proof_level": "contract_proof",
                    "source_refs": ["god_session:architect"],
                },
                {
                    "god_id": "review-god",
                    "cli_id": "opencode.deepseek_flash_worker",
                    "peer_god_ready": False,
                    "bounded": True,
                    "provider_session_ready": True,
                    "waiting_reason": "selected CLI lacks peer_god capability",
                    "proof_level": "contract_proof",
                    "source_refs": ["god_session:review"],
                },
            ],
        },
    )

    gate = capture_natural_deliberation_release_gate(
        artifact_path=artifact,
        output_path=tmp_path / "gate.json",
        god_runtime_path=runtime,
    )

    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "selected GOD runtime is not peer-GOD ready for review-god" in gate["summary"]
    assert gate["source_refs"] == [
        "memory://conversation/conv-prod-1/transcript",
        "conversation:conv-prod-1",
        "god:architect-god",
        "god:review-god",
        "provider:codex",
        "provider:opencode",
        "god_cli_selection:conv-prod-1",
        "god_session:architect",
        "god_session:review",
    ]


def test_natural_deliberation_gate_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-natural-deliberation-gate-capture"]
        == "xmuse.natural_deliberation_gate_capture:main"
    )

    script = Path("xmuse/natural_deliberation_gate_capture.py").read_text(encoding="utf-8")
    assert "--god-runtime" in script
