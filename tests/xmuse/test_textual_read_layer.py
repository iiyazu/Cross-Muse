from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from xmuse.tui.adapter.xmuse_adapter import XmuseAdapter
from xmuse.tui.widgets.card_renderer import render_card
from xmuse_core.platform.read_envelopes import build_tui_worklist_envelope

CONTRACT_ROOT = Path("tests/fixtures/xmuse/contracts")


def _fixture(relative_path: str) -> dict:
    return json.loads((CONTRACT_ROOT / relative_path).read_text(encoding="utf-8"))


def _runtime_inventory() -> dict[str, object]:
    return {
        "runner_pids": [],
        "mcp_pids": [],
        "services": [],
        "counts_by_service": {},
        "warnings": [],
        "evidence": {"hard": [], "degraded": []},
    }


def test_chat_execution_card_emitter_imports_in_fresh_tui_process():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from xmuse_core.chat.execution_cards import ChatExecutionCardEmitter; "
            "print(ChatExecutionCardEmitter.__name__)",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ChatExecutionCardEmitter"


async def test_textual_adapter_consumes_s0_worklist_and_cards(monkeypatch, tmp_path):
    envelope = _fixture("read_envelopes/tui_worklist.v1.json")
    adapter = XmuseAdapter(tmp_path)

    monkeypatch.setattr(adapter, "poll_messages", lambda conv_id: ([], None))
    monkeypatch.setattr(adapter, "poll_cards", lambda conv_id: ([], None))

    async def _poll_worklist_envelope(conv_id: str | None = None):
        return envelope, None

    monkeypatch.setattr(adapter, "poll_worklist_envelope", _poll_worklist_envelope)

    delta = await adapter.poll_delta(conv_id="conv_demo")

    assert delta.lanes == envelope["worklist"]
    assert [card["card_type"] for card in delta.cards] == [
        card["card_type"] for card in envelope["cards"]
    ]
    assert {card["conversation_id"] for card in delta.cards} == {"conv_demo"}
    assert delta.run_health == envelope["run_health"]


async def test_textual_adapter_dedupes_embedded_cards_across_envelope_refresh(
    monkeypatch,
    tmp_path,
):
    first_envelope = _fixture("read_envelopes/tui_worklist.v1.json")
    second_envelope = {
        **first_envelope,
        "generated_at": "2026-06-02T00:09:00Z",
        "run_health": {"status": "degraded", "warnings": [{"code": "still_blocked"}]},
    }
    adapter = XmuseAdapter(tmp_path)

    monkeypatch.setattr(adapter, "poll_messages", lambda conv_id: ([], None))
    monkeypatch.setattr(adapter, "poll_cards", lambda conv_id: ([], None))
    envelopes = [first_envelope, second_envelope]

    async def _poll_worklist_envelope(conv_id: str | None = None):
        return envelopes.pop(0), None

    monkeypatch.setattr(adapter, "poll_worklist_envelope", _poll_worklist_envelope)

    first_delta = await adapter.poll_delta(conv_id="conv_demo")
    second_delta = await adapter.poll_delta(conv_id="conv_demo")

    assert [card["intent_id"] for card in first_delta.cards] == [
        card["intent_id"] for card in first_envelope["cards"]
    ]
    assert second_delta.cards == []
    assert second_delta.run_health == second_envelope["run_health"]


def test_textual_card_renderer_uses_s0_drilldown_refs():
    card = _fixture("cards/lane_blocked.v1.json")

    panel = render_card(card)

    rendered = panel.renderable.plain
    assert "The lane needs an S0-reviewed adapter contract" in rendered
    assert "/api/dashboard/lanes/lane_demo" in rendered


def test_textual_card_renderer_uses_embedded_card_title_and_status():
    envelope = _fixture("read_envelopes/tui_worklist.v1.json")
    card = envelope["cards"][0]

    panel = render_card(card)

    rendered = panel.renderable.plain
    assert "Feature plan ready" in rendered
    assert "ready" in rendered


def test_tui_worklist_envelope_defaults_to_ray_runtime_backend(tmp_path, monkeypatch):
    monkeypatch.delenv("XMUSE_RUNTIME_BACKEND", raising=False)
    (tmp_path / "feature_lanes.json").write_text(
        json.dumps({"projection_revision": 1, "lanes": []}),
        encoding="utf-8",
    )

    envelope = build_tui_worklist_envelope(
        tmp_path,
        process_inventory=_runtime_inventory(),
    )

    assert envelope.runtime_backend.configured == "ray"


def test_tui_worklist_envelope_allows_explicit_native_fallback(tmp_path):
    (tmp_path / "feature_lanes.json").write_text(
        json.dumps({"projection_revision": 1, "lanes": []}),
        encoding="utf-8",
    )

    envelope = build_tui_worklist_envelope(
        tmp_path,
        configured_backend="native",
        process_inventory=_runtime_inventory(),
    )

    assert envelope.runtime_backend.configured == "native"
