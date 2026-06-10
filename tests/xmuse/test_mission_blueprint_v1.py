from __future__ import annotations

import pytest
from pydantic import ValidationError

from xmuse_core.structuring.mission_blueprint_v1 import (
    MissionBlueprintStatus,
    MissionBlueprintV1,
    render_mission_blueprint_markdown,
)


def test_mission_blueprint_rejects_empty_acceptance_contracts() -> None:
    with pytest.raises(ValidationError):
        _blueprint(acceptance_contracts=[])


def test_frozen_blueprint_revision_is_immutable() -> None:
    blueprint = _blueprint(status=MissionBlueprintStatus.FROZEN)

    with pytest.raises(ValidationError):
        blueprint.revision = 2  # type: ignore[misc]


def test_blueprint_stable_json_preserves_source_refs() -> None:
    blueprint = _blueprint()

    assert blueprint.stable_json() == (
        '{"acceptance_contracts":["Unit tests prove protocol contracts are stable."],'
        '"approved_by":["god-review"],"blueprint_id":"bp-1","constraints":["Use uv run."],'
        '"conversation_id":"conv-1","decision_log":[{"decision":"Freeze protocol first.",'
        '"source_refs":["message:msg-2"]}],"goal":"Add contract-driven deliberation.",'
        '"non_goals":["No physical distributed transport."],'
        '"open_questions":["How large is quorum?"],'
        '"repo_areas":["src/xmuse_core/chat"],"revision":1,'
        '"scope":["Deliberation protocol","Blueprint artifact"],'
        '"source_refs":["message:msg-1","message:msg-2"],"status":"draft",'
        '"version":"mission_blueprint.v1"}'
    )


def test_blueprint_markdown_projection_is_deterministic_and_source_traceable() -> None:
    blueprint = _blueprint()

    markdown = render_mission_blueprint_markdown(blueprint)

    assert markdown == "\n".join(
        [
            "# Mission Blueprint bp-1 r1",
            "",
            "Status: `draft`",
            "Conversation: `conv-1`",
            "",
            "## Goal",
            "",
            "Add contract-driven deliberation.",
            "",
            "## Scope",
            "",
            "- Deliberation protocol",
            "- Blueprint artifact",
            "",
            "## Constraints",
            "",
            "- Use uv run.",
            "",
            "## Non-Goals",
            "",
            "- No physical distributed transport.",
            "",
            "## Acceptance Contracts",
            "",
            "- Unit tests prove protocol contracts are stable.",
            "",
            "## Repo Areas",
            "",
            "- `src/xmuse_core/chat`",
            "",
            "## Open Questions",
            "",
            "- How large is quorum?",
            "",
            "## Decision Log",
            "",
            "- Freeze protocol first. (refs: `message:msg-2`)",
            "",
            "## Source Refs",
            "",
            "- `message:msg-1`",
            "- `message:msg-2`",
            "",
            "## Approved By",
            "",
            "- `god-review`",
        ]
    )
    assert markdown == render_mission_blueprint_markdown(blueprint)


def test_blueprint_rejects_empty_source_refs() -> None:
    with pytest.raises(ValidationError):
        _blueprint(source_refs=["message:msg-1", ""])


def _blueprint(
    *,
    status: MissionBlueprintStatus = MissionBlueprintStatus.DRAFT,
    acceptance_contracts: list[str] | None = None,
    source_refs: list[str] | None = None,
) -> MissionBlueprintV1:
    return MissionBlueprintV1(
        blueprint_id="bp-1",
        conversation_id="conv-1",
        revision=1,
        goal="Add contract-driven deliberation.",
        scope=["Deliberation protocol", "Blueprint artifact"],
        constraints=["Use uv run."],
        non_goals=["No physical distributed transport."],
        acceptance_contracts=acceptance_contracts
        if acceptance_contracts is not None
        else ["Unit tests prove protocol contracts are stable."],
        repo_areas=["src/xmuse_core/chat"],
        open_questions=["How large is quorum?"],
        decision_log=[
            {
                "decision": "Freeze protocol first.",
                "source_refs": ["message:msg-2"],
            }
        ],
        source_refs=source_refs or ["message:msg-1", "message:msg-2"],
        status=status,
        approved_by=["god-review"],
    )
