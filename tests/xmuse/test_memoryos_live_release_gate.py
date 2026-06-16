from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.memoryos_live_release_gate import (
    capture_memoryos_live_release_gate,
)
from xmuse_core.platform.release_readiness_capture import capture_release_readiness


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _trace_artifact(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "xmuse.memoryos_lite_trace.v1",
        "trace_id": "xmuse-memoryos-trace:live-1",
        "proof_level": "live_service_proof",
        "fact_state": "observed",
        "namespace_uri": "memory://conversation/conv-live/god-review/thread-1",
        "session_id": "ses-live-1",
        "trace_events": [
            {
                "kind": "session_created",
                "metadata": {"xmuse_source_refs": ["conversation:conv-live"]},
            },
            {
                "kind": "ingest",
                "metadata": {"xmuse_source_refs": ["lane:lane-1"]},
            },
            {
                "kind": "context_built",
                "estimated_tokens": 96,
                "metadata": {"xmuse_source_refs": ["blueprint:bp-1"]},
            },
        ],
        "source_refs": ["conversation:conv-live", "lane:lane-1", "blueprint:bp-1"],
        "target_refs": [
            "memoryos:namespace:memory://conversation/conv-live/god-review/thread-1",
            "memoryos:session:ses-live-1",
        ],
        "estimated_tokens": 96,
        "blockers": [],
    }
    payload.update(overrides)
    return payload


def test_memoryos_live_gate_accepts_live_trace_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "memoryos-trace.json"
    gate_output = tmp_path / "gates" / "live-memoryos.json"
    _write_json(artifact, _trace_artifact())

    gate = capture_memoryos_live_release_gate(
        artifact_path=artifact,
        output_path=gate_output,
    )

    assert gate_output.exists()
    assert gate["schema_version"] == "xmuse.production_evidence.v1"
    assert gate["gate_id"] == "live-memoryos"
    assert gate["kind"] == "live_memoryos"
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "live_service_proof"
    assert gate["source_refs"] == [
        "conversation:conv-live",
        "lane:lane-1",
        "blueprint:bp-1",
        "memoryos:namespace:memory://conversation/conv-live/god-review/thread-1",
        "memoryos:session:ses-live-1",
    ]
    assert gate["memoryos_trace"] == {
        "authority": "memoryos_live_release_gate",
        "trace_id": "xmuse-memoryos-trace:live-1",
        "namespace_uri": "memory://conversation/conv-live/god-review/thread-1",
        "session_id": "ses-live-1",
        "trace_event_count": 3,
        "event_kinds": ["session_created", "ingest", "context_built"],
        "estimated_tokens": 96,
        "source_ref_count": 5,
        "upstream_source_ref_count": 3,
        "target_refs": [
            "memoryos:namespace:memory://conversation/conv-live/god-review/thread-1",
            "memoryos:session:ses-live-1",
        ],
        "target_ref_count": 2,
        "blocker_count": 0,
        "live_service_proof": True,
    }
    report = capture_release_readiness(
        artifacts_dir=tmp_path / "gates",
        output_path=tmp_path / "release-readiness.json",
    )
    assert report["decision"] == "ready"


def test_memoryos_live_gate_blocks_contract_or_fake_trace(tmp_path: Path) -> None:
    artifact = tmp_path / "contract-memoryos-trace.json"
    _write_json(
        artifact,
        _trace_artifact(
            proof_level="contract_proof",
            trace_events=[
                {
                    "kind": "fixture_trace",
                    "metadata": {"xmuse_source_refs": ["lane:lane-1"]},
                }
            ],
        ),
    )

    gate = capture_memoryos_live_release_gate(
        artifact_path=artifact,
        output_path=tmp_path / "gate.json",
    )

    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "requires live_service_proof" in gate["summary"]


def test_memoryos_live_gate_blocks_empty_trace(tmp_path: Path) -> None:
    artifact = tmp_path / "empty-memoryos-trace.json"
    _write_json(artifact, _trace_artifact(trace_events=[]))

    gate = capture_memoryos_live_release_gate(
        artifact_path=artifact,
        output_path=tmp_path / "gate.json",
    )

    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "trace events" in gate["summary"]


def test_memoryos_live_gate_blocks_missing_trace_id(tmp_path: Path) -> None:
    artifact = tmp_path / "missing-trace-id.json"
    payload = _trace_artifact()
    payload.pop("trace_id")
    _write_json(artifact, payload)

    gate = capture_memoryos_live_release_gate(
        artifact_path=artifact,
        output_path=tmp_path / "gate.json",
    )

    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "requires a trace_id" in gate["summary"]


def test_memoryos_live_gate_blocks_trace_without_upstream_source_refs(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "missing-upstream-source-refs.json"
    _write_json(
        artifact,
        _trace_artifact(
            source_refs=[],
            trace_events=[
                {"kind": "session_created", "metadata": {"xmuse_source_refs": []}},
                {"kind": "ingest", "metadata": {"xmuse_source_refs": []}},
            ],
        ),
    )

    gate = capture_memoryos_live_release_gate(
        artifact_path=artifact,
        output_path=tmp_path / "gate.json",
    )

    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "non-MemoryOS upstream source_ref" in gate["summary"]


def test_memoryos_live_gate_blocks_unresolved_blockers_but_keeps_live_proof(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "blocked-memoryos-trace.json"
    _write_json(
        artifact,
        _trace_artifact(
            fact_state="blocked",
            blockers=[
                {
                    "reason": "trace continuity missing latest lane source ref",
                    "source_refs": ["lane:lane-1"],
                }
            ],
        ),
    )

    gate = capture_memoryos_live_release_gate(
        artifact_path=artifact,
        output_path=tmp_path / "gate.json",
    )

    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "live_service_proof"
    assert "unresolved blockers" in gate["summary"]


def test_memoryos_live_gate_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-memoryos-live-gate-capture"]
        == "xmuse.memoryos_live_gate_capture:main"
    )
