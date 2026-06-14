from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.real_provider_runtime_release_gate import (
    capture_real_provider_runtime_release_gate,
)
from xmuse_core.platform.release_readiness_capture import capture_release_readiness


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _stage_timings(offset: float) -> dict[str, dict[str, float]]:
    return {
        "ray_actor_delivery_start": {"at": offset + 1.0},
        "codex_app_server_turn_start": {"at": offset + 2.0},
        "chat_post_message": {"at": offset + 3.0},
        "trace_persisted": {"at": offset + 4.0},
    }


def _runtime_artifact(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "xmuse.real_provider_runtime.v1",
        "proof_level": "real_provider_proof",
        "fact_state": "observed",
        "run_id": "real-soak-pr43-ecbcf9d",
        "conversation_id": "conv-real-1",
        "source_refs": ["chat:conversation:conv-real-1"],
        "provider_runtime": {
            "provider_id": "codex",
            "runtime_backend": "ray",
            "transport": "codex-app-server",
            "provider_session_id": "codex-thread-1",
            "mcp_writeback": True,
        },
        "restart_resume": {
            "fresh_provider_session_id": "codex-thread-1",
            "resumed_provider_session_id": "codex-thread-1",
            "provider_session_reused": True,
        },
        "turns": [
            {
                "turn_id": "turn-fresh-1",
                "phase": "fresh",
                "delivery_mode": "mcp_writeback",
                "degraded_reason": None,
                "provider_id": "codex",
                "runtime_backend": "ray",
                "transport": "codex-app-server",
                "provider_session_id": "codex-thread-1",
                "stage_timings": _stage_timings(1.0),
            },
            {
                "turn_id": "turn-resume-1",
                "phase": "resume",
                "delivery_mode": "mcp_writeback",
                "degraded_reason": None,
                "provider_id": "codex",
                "runtime_backend": "ray",
                "transport": "codex-app-server",
                "provider_session_id": "codex-thread-1",
                "stage_timings": _stage_timings(10.0),
            },
        ],
        "blockers": [],
    }
    payload.update(overrides)
    return payload


def test_real_provider_runtime_gate_accepts_live_soak_artifact(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "real-provider-runtime.json"
    gate_output = tmp_path / "gates" / "real-provider-runtime.json"
    _write_json(artifact, _runtime_artifact())

    gate = capture_real_provider_runtime_release_gate(
        artifact_path=artifact,
        output_path=gate_output,
    )

    assert gate_output.exists()
    assert gate["schema_version"] == "xmuse.production_evidence.v1"
    assert gate["gate_id"] == "real-provider-runtime"
    assert gate["kind"] == "real_provider"
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "real_provider_proof"
    assert gate["source_refs"] == [
        "chat:conversation:conv-real-1",
        "provider_runtime:real-soak-pr43-ecbcf9d",
        "conversation:conv-real-1",
        "provider:codex",
        "provider_session:codex-thread-1",
    ]
    assert gate["real_provider_runtime"] == {
        "authority": "real_provider_runtime_release_gate",
        "run_id": "real-soak-pr43-ecbcf9d",
        "conversation_id": "conv-real-1",
        "provider_id": "codex",
        "runtime_backend": "ray",
        "transport": "codex-app-server",
        "provider_session_id": "codex-thread-1",
        "mcp_writeback": True,
        "provider_session_reused": True,
        "fresh_provider_session_id": "codex-thread-1",
        "resumed_provider_session_id": "codex-thread-1",
        "turn_count": 2,
        "phases": ["fresh", "resume"],
        "mcp_writeback_turn_count": 2,
        "degraded_turn_count": 0,
        "blocker_count": 0,
    }
    report = capture_release_readiness(
        artifacts_dir=tmp_path / "gates",
        output_path=tmp_path / "release-readiness.json",
    )
    assert report["decision"] == "ready"


def test_real_provider_runtime_gate_blocks_contract_or_fake_proof(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "fake-provider-runtime.json"
    _write_json(
        artifact,
        _runtime_artifact(
            proof_level="contract_proof",
            provider_runtime={
                "provider_id": "codex",
                "runtime_backend": "fake",
                "transport": "fake-provider-app-server",
                "provider_session_id": "fake-thread-1",
                "mcp_writeback": True,
            },
        ),
    )

    gate = capture_real_provider_runtime_release_gate(
        artifact_path=artifact,
        output_path=tmp_path / "gate.json",
    )

    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "requires real_provider_proof" in gate["summary"]


def test_real_provider_runtime_gate_blocks_degraded_stdout_fallback(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "degraded-runtime.json"
    payload = _runtime_artifact()
    turns = payload["turns"]
    assert isinstance(turns, list)
    assert isinstance(turns[0], dict)
    turns[0]["delivery_mode"] = "stdout_fallback"
    turns[0]["degraded_reason"] = "stdout_fallback"
    _write_json(artifact, payload)

    gate = capture_real_provider_runtime_release_gate(
        artifact_path=artifact,
        output_path=tmp_path / "gate.json",
    )

    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "mcp_writeback" in gate["summary"]


def test_real_provider_runtime_gate_blocks_missing_restart_resume(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "single-phase-runtime.json"
    payload = _runtime_artifact(restart_resume={"provider_session_reused": False})
    turns = payload["turns"]
    assert isinstance(turns, list)
    assert isinstance(turns[1], dict)
    turns[1]["phase"] = "fresh"
    _write_json(artifact, payload)

    gate = capture_real_provider_runtime_release_gate(
        artifact_path=artifact,
        output_path=tmp_path / "gate.json",
    )

    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "fresh and resume turns" in gate["summary"]


def test_real_provider_runtime_gate_blocks_unresolved_blockers_but_keeps_real_proof(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "blocked-runtime.json"
    _write_json(
        artifact,
        _runtime_artifact(
            fact_state="blocked",
            blockers=[
                {
                    "reason": "provider writeback latency exceeded release threshold",
                    "source_refs": ["trace:turn-resume-1"],
                }
            ],
        ),
    )

    gate = capture_real_provider_runtime_release_gate(
        artifact_path=artifact,
        output_path=tmp_path / "gate.json",
    )

    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "real_provider_proof"
    assert "unresolved blockers" in gate["summary"]


def test_real_provider_runtime_gate_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-real-provider-runtime-gate-capture"]
        == "xmuse.real_provider_runtime_gate_capture:main"
    )
