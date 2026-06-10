"""Tests for platform/selection/god_picker.py."""

from __future__ import annotations

from xmuse_core.platform.agent_spawner import GodConfig
from xmuse_core.platform.selection.god_picker import GodPicker


def _god(name: str, runtime: str) -> GodConfig:
    return GodConfig(
        name=name, runtime=runtime, timeout_s=60,
        skill_prompt_path="fake.md",
    )


def _make_picker(
    runtime_mode: str, lanes: dict | None = None,
) -> GodPicker:
    store = lanes or {}

    def reader(lane_id: str):
        if lane_id in store:
            return store[lane_id]
        raise KeyError(lane_id)

    return GodPicker(
        runtime_mode=runtime_mode,
        execution_gods=[_god("exec-codex", "codex"), _god("exec-claude", "claude")],
        review_gods=[_god("rev-codex", "codex"), _god("rev-claude", "claude")],
        lane_reader=reader,
    )


def test_codex_mode_always_returns_first_god():
    picker = _make_picker("codex")
    assert picker.pick_execution("any-lane").runtime == "codex"
    assert picker.pick_execution("other-lane").runtime == "codex"
    assert picker.pick_review("any-lane").runtime == "codex"


def test_claude_mode_still_returns_codex_god():
    picker = _make_picker("claude")
    assert picker.pick_execution("x").runtime == "codex"
    assert picker.pick_review("x").runtime == "codex"


def test_mixed_mode_no_longer_round_robins_to_claude():
    picker = _make_picker("mixed")
    assert picker.pick_execution("lane-a").runtime == "codex"
    assert picker.pick_execution("lane-b").runtime == "codex"


def test_mixed_mode_ignores_recorded_claude_runtime():
    lanes = {
        "lane-pinned": {"god_runtime": "claude"},
    }
    picker = _make_picker("mixed", lanes)
    assert picker.pick_execution("lane-pinned").runtime == "codex"


def test_mixed_mode_review_ignores_recorded_claude_runtime():
    lanes = {
        "lane-claude": {"god_runtime": "claude"},
        "lane-codex": {"god_runtime": "codex"},
    }
    picker = _make_picker("mixed", lanes)
    assert picker.pick_review("lane-claude").runtime == "codex"
    assert picker.pick_review("lane-codex").runtime == "codex"


def test_mixed_mode_review_falls_back_to_first_when_unknown():
    lanes = {
        "lane-unknown": {"god_runtime": "grok"},
    }
    picker = _make_picker("mixed", lanes)
    assert picker.pick_review("lane-unknown").runtime == "codex"


def test_runtime_mode_property():
    picker = _make_picker("mixed")
    assert picker.runtime_mode == "mixed"


def test_missing_lane_stays_codex():
    picker = _make_picker("mixed")
    r1 = picker.pick_execution("missing-1").runtime
    r2 = picker.pick_execution("missing-2").runtime
    assert r1 == "codex"
    assert r2 == "codex"
