from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from xmuse_core.skills.catalog import SkillCatalog
from xmuse_core.skills.selector import SELECTOR_VERSION, SkillSelectorError


def _write_skill(
    root: Path,
    name: str,
    *,
    role: str,
    triggers: list[str],
    not_for: list[str] | None = None,
    priority: int = 100,
) -> None:
    directory = root / name
    directory.mkdir(parents=True)
    policy = {
        "roles": [role],
        "triggers": triggers,
        "not_for": not_for or ["small talk"],
        "priority": priority,
    }
    (directory / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: Instructions for {name}.\n"
        "metadata:\n"
        '  version: "1.0.0"\n'
        f"  xmuse: '{json.dumps(policy, separators=(',', ':'))}'\n"
        "---\n"
        f"# {name}\n",
        encoding="utf-8",
    )


def test_bundled_selector_applies_role_trigger_not_for_and_none_contract():
    catalog = SkillCatalog.load_bundled()

    selected = catalog.select(participant_role="architect", source_text="请给出实现 PLAN")
    assert selected.selector_version == SELECTOR_VERSION
    assert selected.decision == "selected"
    assert selected.skill_id == "implementation-planning"
    assert selected.selection_reason == "trigger"
    assert selected.matched_terms == ("plan", "实现")
    assert selected.selection_input_sha256 == (
        f"sha256:{hashlib.sha256('请给出实现 PLAN'.encode()).hexdigest()}"
    )

    role_mismatch = catalog.select(participant_role="review", source_text="请给出实现 plan")
    assert role_mismatch.decision == "none"
    assert role_mismatch.selection_reason == "no_match"
    assert role_mismatch.matched_terms == ()

    excluded = catalog.select(participant_role="review", source_text="审计风险，但只是闲聊")
    assert excluded.decision == "none"
    assert excluded.skill_id is None


def test_explicit_marker_is_exact_first_nonempty_ascii_line_and_does_not_count_as_trigger():
    catalog = SkillCatalog.load_bundled()

    decision = catalog.select(
        participant_role="review",
        source_text="\n[skill:evidence-review]\nPlease inspect the claim.",
    )
    assert decision.decision == "selected"
    assert decision.selection_reason == "explicit"
    assert decision.matched_terms == ()

    blocked = catalog.select(
        participant_role="review",
        source_text="[skill:evidence-review]\n这只是闲聊",
    )
    assert blocked.decision == "none"
    assert blocked.selection_reason == "no_match"


@pytest.mark.parametrize(
    "source_text",
    [
        "before\n[skill:evidence-review]",
        " [skill:evidence-review]",
        "[skill:evidence-review]\n[skill:evidence-review]",
        "[skill:evidence-review",
        "[skill:unknown-skill]",
        "[skill:a--b]",
    ],
)
def test_malformed_multiple_or_unknown_explicit_markers_fail_stably(source_text):
    with pytest.raises(SkillSelectorError) as exc_info:
        SkillCatalog.load_bundled().select(participant_role="review", source_text=source_text)
    assert exc_info.value.code == "room_skill_explicit_marker_invalid"


def test_unicode_casefold_whitespace_and_normalized_marker_behavior():
    catalog = SkillCatalog.load_bundled()

    normalized = catalog.select(participant_role="ARCHITECT", source_text="ＤＥＳＩＧＮ\t 方案")
    assert normalized.decision == "selected"
    assert normalized.matched_terms == ("design", "方案")

    fullwidth_marker = catalog.select(
        participant_role="review",
        source_text="［skill:evidence-review］",
    )
    assert fullwidth_marker.selection_reason != "explicit"

    with pytest.raises(SkillSelectorError):
        catalog.select(
            participant_role="review",
            source_text="[skill:evidence-\u200breview]",
        )


def test_oversize_input_returns_none_without_hash_or_marker_scan():
    catalog = SkillCatalog.load_bundled()

    too_many_characters = catalog.select(
        participant_role="review",
        source_text="[skill:unknown]" + ("x" * 65_536),
    )
    assert too_many_characters.decision == "none"
    assert too_many_characters.selection_reason == "input_too_large"
    assert too_many_characters.selection_input_sha256 is None

    too_many_bytes = catalog.select(participant_role="review", source_text="审" * 22_000)
    assert too_many_bytes.selection_reason == "input_too_large"
    assert too_many_bytes.selection_input_sha256 is None

    at_boundary = catalog.select(participant_role="review", source_text="x" * 65_536)
    assert at_boundary.selection_reason == "no_match"
    assert at_boundary.selection_input_sha256 is not None


def test_tie_break_is_match_count_then_priority_then_skill_id_and_catalog_order_independent(
    tmp_path,
):
    root = tmp_path / "skills"
    _write_skill(root, "z-skill", role="review", triggers=["review", "risk"], priority=100)
    _write_skill(root, "low-skill", role="review", triggers=["review"], priority=1000)
    _write_skill(root, "a-skill", role="review", triggers=["review", "risk"], priority=100)
    catalog = SkillCatalog.load(root)

    decision = catalog.select(participant_role="review", source_text="REVIEW the RISK")
    assert decision.skill_id == "a-skill"
    assert decision.matched_terms == ("review", "risk")

    explicit = catalog.select(
        participant_role="review",
        source_text="[skill:low-skill]\nNo trigger is required.",
    )
    assert explicit.skill_id == "low-skill"
    assert explicit.selection_reason == "explicit"
