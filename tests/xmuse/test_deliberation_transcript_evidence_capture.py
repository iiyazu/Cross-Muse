from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.deliberation_transcript_evidence_capture import (
    capture_deliberation_transcript_evidence,
)
from xmuse_core.platform.overnight_replay_bundle_capture import (
    capture_overnight_replay_bundle,
)


def test_capture_deliberation_transcript_evidence_exports_replay_ready_artifact(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "natural-transcript.json"
    runtime = tmp_path / "god-runtime.json"
    _write_json(transcript, _transcript())
    _write_json(runtime, _runtime())
    output = tmp_path / "deliberation-transcript-production-evidence.json"

    artifact = capture_deliberation_transcript_evidence(
        run_id="overnight-transcript",
        transcript_artifact=transcript,
        god_runtime_artifact=runtime,
        output_path=output,
    )

    assert json.loads(output.read_text(encoding="utf-8")) == artifact
    assert artifact["schema_version"] == "xmuse.production_evidence.v1"
    assert artifact["run_id"] == "overnight-transcript"
    assert artifact["stage_id"] == "S5"
    assert artifact["action"] == "deliberation_transcript_verified"
    assert artifact["status"] == "ok"
    assert artifact["proof_level"] == "real_provider_proof"
    assert artifact["source_authority"] == "operator_transcript_v1"
    assert artifact["source_refs"] == [
        "memory://conversation/conv-prod-1/transcript",
        "conversation:conv-prod-1",
        "god:architect-god",
        "god:review-god",
        "provider:codex",
        "provider:opencode",
    ]
    assert artifact["target_refs"] == [
        "blueprint:prod:1",
        "lane:prod-a",
    ]
    assert artifact["artifacts"] == [str(transcript), str(runtime)]
    assert artifact["blocked_reason"] is None
    assert artifact["summary"] == (
        "Natural GOD deliberation transcript captured real provider proof from "
        "2 GOD participants."
    )

    replay_bundle = capture_overnight_replay_bundle(
        run_id="overnight-transcript",
        artifacts_dir=tmp_path / "empty-release-gates",
        output_path=tmp_path / "bundle.json",
        section_artifacts={"deliberation_transcript": output},
    )
    sections = {section["section_id"]: section for section in replay_bundle["sections"]}
    assert sections["deliberation_transcript"]["status"] == "ok"
    assert sections["deliberation_transcript"]["proof_level"] == "real_provider_proof"
    assert sections["deliberation_transcript"]["source_authority"] == (
        "operator_transcript_v1"
    )


def test_capture_deliberation_transcript_evidence_blocks_without_selected_runtime(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "natural-transcript.json"
    _write_json(transcript, _transcript())

    artifact = capture_deliberation_transcript_evidence(
        run_id="overnight-transcript",
        transcript_artifact=transcript,
        output_path=tmp_path / "deliberation-transcript-production-evidence.json",
    )

    assert artifact["status"] == "manual_gap"
    assert artifact["proof_level"] == "manual_gap"
    assert "requires selected GOD runtime continuity" in artifact["blocked_reason"]
    assert artifact["next_action"] == (
        "Capture selected GOD runtime continuity with "
        "xmuse-god-runtime-continuity-capture and rerun the natural "
        "deliberation release gate."
    )


def test_capture_deliberation_transcript_evidence_keeps_deterministic_replay_manual_gap(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "deterministic-transcript.json"
    _write_json(
        transcript,
        _transcript(proof_level="contract_proof", natural_deliberation=False),
    )

    artifact = capture_deliberation_transcript_evidence(
        run_id="overnight-transcript",
        transcript_artifact=transcript,
        output_path=tmp_path / "deliberation-transcript-production-evidence.json",
    )

    assert artifact["status"] == "manual_gap"
    assert artifact["proof_level"] == "manual_gap"
    assert "requires real_provider_proof" in artifact["blocked_reason"]
    assert artifact["next_action"] == (
        "Capture a natural multi-GOD transcript with real provider proof, "
        "provider session metadata, and no unresolved blockers."
    )


def test_capture_deliberation_transcript_evidence_preserves_blocked_real_transcript(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "blocked-transcript.json"
    runtime = tmp_path / "god-runtime.json"
    _write_json(
        transcript,
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

    artifact = capture_deliberation_transcript_evidence(
        run_id="overnight-transcript",
        transcript_artifact=transcript,
        god_runtime_artifact=runtime,
        output_path=tmp_path / "deliberation-transcript-production-evidence.json",
    )

    assert artifact["status"] == "blocked"
    assert artifact["proof_level"] == "real_provider_proof"
    assert artifact["blocked_reason"] == (
        "Natural GOD deliberation has 1 unresolved blockers."
    )


def test_deliberation_transcript_evidence_capture_cli_writes_artifact(
    tmp_path: Path,
) -> None:
    from xmuse.deliberation_transcript_evidence_capture import main

    transcript = tmp_path / "natural-transcript.json"
    runtime = tmp_path / "god-runtime.json"
    _write_json(transcript, _transcript())
    _write_json(runtime, _runtime())
    output = tmp_path / "deliberation-transcript-production-evidence.json"

    assert (
        main(
            [
                "--run-id",
                "overnight-transcript",
                "--transcript",
                str(transcript),
                "--god-runtime",
                str(runtime),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["status"] == "ok"
    assert artifact["action"] == "deliberation_transcript_verified"


def test_deliberation_transcript_evidence_capture_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-deliberation-transcript-evidence-capture"]
        == "xmuse.deliberation_transcript_evidence_capture:main"
    )


def _transcript(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "xmuse.operator_transcript.v1",
        "conversation_id": "conv-prod-1",
        "proof_level": "real_provider_proof",
        "fact_state": "observed",
        "natural_deliberation": True,
        "source_refs": ["memory://conversation/conv-prod-1/transcript"],
        "target_refs": ["blueprint:prod:1"],
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


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
