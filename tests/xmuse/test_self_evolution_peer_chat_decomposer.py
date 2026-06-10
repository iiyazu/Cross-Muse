from __future__ import annotations

import json

import pytest

from xmuse_core.self_evolution.decomposer import SingleLaneDecomposer
from xmuse_core.self_evolution.models import (
    RunTerminalStatus,
    StructuredEvidenceBundle,
)
from xmuse_core.self_evolution.peer_chat_decomposer import PeerChatDecomposer


def _evidence() -> StructuredEvidenceBundle:
    return StructuredEvidenceBundle(
        bundle_id="evbundle-multi",
        source_run_id="src-multi",
        source_resolution_id="src-multi",
        selection_policy_id="test",
        selection_policy_version="0",
        summary="prior run merged",
        run_terminal_status=RunTerminalStatus.MERGED,
        verdict_refs=[],
        gate_report_refs=[],
        lineage_refs=[],
        artifact_refs=[],
        signal_refs=[],
        primary_refs=[],
        created_at="2026-05-28T00:00:00Z",
    )


def _fallback() -> SingleLaneDecomposer:
    return SingleLaneDecomposer(
        lane_id_factory=lambda evidence, track: f"fallback-{track}-{evidence.source_run_id}",
        prompt_factory=lambda evidence, track: f"fallback prompt {track}",
    )


def _codex_output(inner: dict) -> str:
    return json.dumps(inner)


def test_peer_chat_decomposer_rejects_claude_runtime() -> None:
    with pytest.raises(ValueError, match="codex-only"):
        PeerChatDecomposer(fallback=_fallback(), runtime="claude")


def test_peer_chat_decomposer_ignores_claude_runtime_env(monkeypatch) -> None:
    monkeypatch.setenv("XMUSE_PEER_CHAT_RUNTIME", "claude")
    decomposer = PeerChatDecomposer(fallback=_fallback())

    assert decomposer._runtime == "codex"


def test_peer_chat_decomposer_ignores_legacy_non_god_model_env(monkeypatch) -> None:
    monkeypatch.setenv("XMUSE_NON_GOD_CODEX_MODEL", "gpt-5.4")
    monkeypatch.delenv("XMUSE_CODEX_MODEL", raising=False)

    decomposer = PeerChatDecomposer(fallback=_fallback())

    assert decomposer._model == "gpt-5.4"


def test_peer_chat_decomposer_emits_multi_feature_lanes(monkeypatch) -> None:
    decomposer = PeerChatDecomposer(fallback=_fallback(), runtime="codex")
    plan = {
        "features": [
            {
                "name": "ingest-pipeline",
                "lanes": [
                    {
                        "id_suffix": "impl",
                        "prompt": "implement ingest pipeline",
                        "capabilities": ["code"],
                        "depends_on": [],
                    }
                ],
            },
            {
                "name": "review-flow",
                "lanes": [
                    {
                        "id_suffix": "impl",
                        "prompt": "implement review flow",
                        "capabilities": ["code"],
                        "depends_on": [],
                    },
                    {
                        "id_suffix": "tests",
                        "prompt": "add review-flow tests",
                        "capabilities": ["test"],
                        "depends_on": ["review-flow:impl"],
                    },
                ],
            },
        ]
    }
    monkeypatch.setattr(
        decomposer,
        "_call_codex",
        lambda track, evidence: type(
            "Result",
            (),
            {"raw_output": _codex_output(plan), "features": []},
        )(),
    )

    lanes = decomposer.decompose("graph_authority", _evidence())

    assert len(lanes) == 3
    impl_ingest = lanes[0]
    impl_review = lanes[1]
    tests_review = lanes[2]

    assert impl_ingest["feature_group"] == "graph_authority/ingest-pipeline"
    assert impl_ingest["depends_on"] == []
    assert impl_review["feature_group"] == "graph_authority/review-flow"
    assert impl_review["depends_on"] == []
    assert tests_review["depends_on"] == [impl_review["feature_id"]]
    assert all("evbundle-multi" in lane["prompt"] for lane in lanes)


def test_peer_chat_decomposer_falls_back_on_invalid_json(monkeypatch) -> None:
    decomposer = PeerChatDecomposer(fallback=_fallback(), runtime="codex")
    monkeypatch.setattr(
        decomposer,
        "_call_codex",
        lambda track, evidence: type(
            "Result",
            (),
            {"raw_output": "not json at all", "features": []},
        )(),
    )

    lanes = decomposer.decompose("review_plane", _evidence())

    assert len(lanes) == 1
    assert lanes[0]["feature_id"] == "fallback-review_plane-src-multi"


def test_peer_chat_decomposer_falls_back_when_codex_call_raises(monkeypatch) -> None:
    decomposer = PeerChatDecomposer(fallback=_fallback(), runtime="codex")

    def _boom(track, evidence):
        raise RuntimeError("codex exit 1")

    monkeypatch.setattr(decomposer, "_call_codex", _boom)

    lanes = decomposer.decompose("review_plane", _evidence())

    assert len(lanes) == 1
    assert lanes[0]["feature_id"] == "fallback-review_plane-src-multi"


def test_peer_chat_decomposer_strips_markdown_fence(monkeypatch) -> None:
    decomposer = PeerChatDecomposer(fallback=_fallback(), runtime="codex")
    inner_payload = {
        "features": [
            {
                "name": "f1",
                "lanes": [
                    {"id_suffix": "impl", "prompt": "do it", "depends_on": []},
                ],
            }
        ]
    }
    fenced = f"```json\n{json.dumps(inner_payload)}\n```"
    monkeypatch.setattr(
        decomposer,
        "_call_codex",
        lambda track, evidence: type(
            "Result",
            (),
            {"raw_output": fenced, "features": []},
        )(),
    )

    lanes = decomposer.decompose("graph_authority", _evidence())

    assert len(lanes) == 1
    assert lanes[0]["feature_group"] == "graph_authority/f1"
