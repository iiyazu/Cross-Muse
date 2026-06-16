from __future__ import annotations

import json
import tomllib
from pathlib import Path

import httpx
import pytest

from xmuse_core.integrations.memoryos_namespace import task_namespace
from xmuse_core.platform.memoryos_live_release_gate import (
    build_memoryos_live_release_gate,
)
from xmuse_core.platform.memoryos_live_trace_capture import (
    capture_memoryos_lite_live_trace_artifact,
)


def _namespace():
    return task_namespace(
        repo_id="iiyazu/Cross-Muse",
        workspace_id="xmuse",
        god_id="god-review",
        conversation_id="conv-live",
        thread_id="thread-1",
        blueprint_id="bp-1",
        feature_id="feature-1",
        lane_id="lane-1",
    )


@pytest.mark.asyncio
async def test_memoryos_live_trace_capture_runs_rest_sequence_and_writes_live_artifact(
    tmp_path: Path,
) -> None:
    namespace = _namespace()
    requests: list[tuple[str, dict[str, object]]] = []

    def route(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode() or "{}")
        requests.append((request.url.path, payload))
        if request.url.path == "/sessions":
            return httpx.Response(200, json={"id": "ses-live-1"})
        if request.url.path == "/sessions/ses-live-1/ingest":
            return httpx.Response(
                200,
                json={
                    "message": {
                        "id": "msg-live-1",
                        "metadata": payload["metadata"],
                    }
                },
            )
        if request.url.path == "/sessions/ses-live-1/build-context":
            return httpx.Response(
                200,
                json={
                    "metadata": {"xmuse_source_refs": ["context:metadata"]},
                    "retrieved_evidence": [
                        {
                            "message_id": "msg-live-1",
                            "text": "Live MemoryOS Lite context.",
                            "metadata": {"xmuse_source_refs": ["context:retrieved"]},
                        }
                    ],
                },
            )
        if request.url.path == "/sessions/ses-live-1/trace":
            return httpx.Response(
                200,
                json={
                    "events": [
                        {
                            "kind": "session_created",
                            "metadata": {"xmuse_source_refs": ["trace:session"]},
                        },
                        {
                            "kind": "context_built",
                            "estimated_tokens": 96,
                            "metadata": {"xmuse_source_refs": ["trace:context"]},
                        },
                    ]
                },
            )
        raise AssertionError(f"unexpected endpoint: {request.url.path}")

    output = tmp_path / "memoryos-trace.json"
    async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as http_client:
        artifact = await capture_memoryos_lite_live_trace_artifact(
            base_url="http://memoryos-lite.test",
            namespace=namespace,
            actor_id="god-review",
            content="Live MemoryOS Lite production evidence.",
            query="production evidence",
            source_refs=["lane:lane-1", "blueprint:bp-1"],
            output_path=output,
            http_client=http_client,
            binding_store_path=tmp_path / "memoryos_lite_sessions.json",
        )

    assert output.exists()
    assert artifact == json.loads(output.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == "xmuse.memoryos_lite_trace.v1"
    assert str(artifact["trace_id"]).startswith("xmuse-memoryos-trace:")
    assert artifact["proof_level"] == "live_service_proof"
    assert artifact["fact_state"] == "observed"
    assert artifact["namespace_uri"] == namespace.uri
    assert artifact["session_id"] == "ses-live-1"
    assert artifact["estimated_tokens"] == 96
    assert artifact["blockers"] == []
    assert artifact["source_refs"] == [
        "lane:lane-1",
        "blueprint:bp-1",
        f"{namespace.uri}/messages/msg-live-1",
        "context:metadata",
        "context:retrieved",
        "memoryos-lite-message:msg-live-1",
        "trace:session",
        "trace:context",
    ]
    assert artifact["target_refs"] == [
        f"memoryos:namespace:{namespace.uri}",
        "memoryos:session:ses-live-1",
    ]
    assert [path for path, _payload in requests] == [
        "/sessions",
        "/sessions/ses-live-1/ingest",
        "/sessions/ses-live-1/build-context",
        "/sessions/ses-live-1/trace",
    ]

    gate = build_memoryos_live_release_gate(artifact, artifact_path=output)
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "live_service_proof"


@pytest.mark.asyncio
async def test_memoryos_live_trace_capture_blocks_when_trace_is_missing(
    tmp_path: Path,
) -> None:
    namespace = _namespace()

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sessions":
            return httpx.Response(200, json={"id": "ses-live-1"})
        if request.url.path == "/sessions/ses-live-1/ingest":
            return httpx.Response(200, json={"message": {"id": "msg-live-1"}})
        if request.url.path == "/sessions/ses-live-1/build-context":
            return httpx.Response(200, json={"recent_messages": []})
        if request.url.path == "/sessions/ses-live-1/trace":
            return httpx.Response(503, json={"detail": "trace unavailable"})
        raise AssertionError(f"unexpected endpoint: {request.url.path}")

    output = tmp_path / "memoryos-trace.json"
    async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as http_client:
        artifact = await capture_memoryos_lite_live_trace_artifact(
            base_url="http://memoryos-lite.test",
            namespace=namespace,
            actor_id="god-review",
            content="Live MemoryOS Lite production evidence.",
            query="production evidence",
            source_refs=["lane:lane-1"],
            output_path=output,
            http_client=http_client,
            binding_store_path=tmp_path / "memoryos_lite_sessions.json",
        )

    assert artifact["schema_version"] == "xmuse.memoryos_lite_trace.v1"
    assert artifact["trace_id"] is None
    assert artifact["proof_level"] == "manual_gap"
    assert artifact["fact_state"] == "blocked"
    assert artifact["namespace_uri"] == namespace.uri
    assert artifact["session_id"] == "ses-live-1"
    assert artifact["trace_events"] == []
    assert artifact["blockers"] == [
        {
            "reason": "memoryos_lite_trace_unavailable",
            "source_refs": ["lane:lane-1"],
        }
    ]

    gate = build_memoryos_live_release_gate(artifact, artifact_path=output)
    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert "requires live_service_proof" in gate["summary"]


def test_memoryos_live_trace_capture_cli_writes_manual_gap_when_unconfigured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xmuse.memoryos_live_trace_capture import main

    monkeypatch.delenv("XMUSE_LIVE_MEMORYOS_LITE", raising=False)
    monkeypatch.delenv("XMUSE_MEMORYOS_LITE_URL", raising=False)
    output = tmp_path / "memoryos-trace.json"

    assert (
        main(
            [
                "--repo-id",
                "iiyazu/Cross-Muse",
                "--workspace-id",
                "xmuse",
                "--god-id",
                "god-review",
                "--conversation-id",
                "conv-live",
                "--thread-id",
                "thread-1",
                "--blueprint-id",
                "bp-1",
                "--feature-id",
                "feature-1",
                "--lane-id",
                "lane-1",
                "--actor-id",
                "god-review",
                "--content",
                "Live MemoryOS Lite production evidence.",
                "--query",
                "production evidence",
                "--source-ref",
                "lane:lane-1",
                "--output",
                str(output),
            ]
        )
        == 2
    )

    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == "xmuse.memoryos_lite_trace.v1"
    assert artifact["proof_level"] == "manual_gap"
    assert artifact["fact_state"] == "blocked"
    assert artifact["namespace_uri"] == _namespace().uri
    assert artifact["session_id"] == ""
    assert artifact["trace_events"] == []
    assert artifact["source_refs"] == ["lane:lane-1"]
    assert artifact["blockers"] == [
        {
            "reason": "memoryos_lite_live_environment_missing",
            "source_refs": ["lane:lane-1"],
        }
    ]

    gate = build_memoryos_live_release_gate(artifact, artifact_path=output)
    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"


def test_memoryos_live_trace_capture_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-memoryos-live-trace-capture"]
        == "xmuse.memoryos_live_trace_capture:main"
    )
