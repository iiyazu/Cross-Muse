from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from xmuse_core.chat.store import ChatStore
from xmuse_core.structuring.frozen_blueprint_export import (
    export_frozen_blueprint_from_chat_store,
)
from xmuse_core.structuring.mission_blueprint_v1 import (
    MissionBlueprintStatus,
    MissionBlueprintV1,
    render_mission_blueprint_markdown,
)


def test_export_frozen_blueprint_from_deliberation_resolution(tmp_path: Path) -> None:
    chat_db = tmp_path / "chat.db"
    resolution = _seed_blueprint_resolution(
        ChatStore(chat_db),
        approval_mode="deliberation_freeze",
        status=MissionBlueprintStatus.FROZEN,
    )
    output = tmp_path / "mission-blueprint.json"

    artifact = export_frozen_blueprint_from_chat_store(
        chat_db=chat_db,
        output_path=output,
        resolution_id=resolution.id,
    )

    assert artifact == output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["version"] == "mission_blueprint.v1"
    assert payload["blueprint_id"] == "bp-production"
    assert payload["conversation_id"] == resolution.conversation_id
    assert payload["revision"] == 3
    assert payload["status"] == "frozen"
    assert payload["approved_by"] == ["god-architect", "god-review"]
    assert payload["source_refs"] == [
        "message:proposal",
        "message:challenge",
        f"resolution:{resolution.id}",
    ]


def test_export_uses_latest_frozen_resolution_for_conversation(tmp_path: Path) -> None:
    chat_db = tmp_path / "chat.db"
    store = ChatStore(chat_db)
    first = _seed_blueprint_resolution(
        store,
        approval_mode="deliberation_freeze",
        status=MissionBlueprintStatus.FROZEN,
        revision=1,
    )
    second = _seed_blueprint_resolution(
        store,
        approval_mode="deliberation_freeze",
        status=MissionBlueprintStatus.FROZEN,
        revision=2,
        conversation_id=first.conversation_id,
    )
    output = tmp_path / "latest-blueprint.json"

    export_frozen_blueprint_from_chat_store(
        chat_db=chat_db,
        output_path=output,
        conversation_id=first.conversation_id,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["revision"] == 2
    assert payload["source_refs"][-1] == f"resolution:{second.id}"


def test_export_rejects_non_deliberation_freeze_resolution(tmp_path: Path) -> None:
    chat_db = tmp_path / "chat.db"
    resolution = _seed_blueprint_resolution(
        ChatStore(chat_db),
        approval_mode="manual_approval",
        status=MissionBlueprintStatus.FROZEN,
    )

    with pytest.raises(ValueError, match="deliberation_freeze"):
        export_frozen_blueprint_from_chat_store(
            chat_db=chat_db,
            output_path=tmp_path / "mission-blueprint.json",
            resolution_id=resolution.id,
        )


def test_export_rejects_non_frozen_blueprint(tmp_path: Path) -> None:
    chat_db = tmp_path / "chat.db"
    resolution = _seed_blueprint_resolution(
        ChatStore(chat_db),
        approval_mode="deliberation_freeze",
        status=MissionBlueprintStatus.DRAFT,
    )

    with pytest.raises(ValueError, match="expected frozen"):
        export_frozen_blueprint_from_chat_store(
            chat_db=chat_db,
            output_path=tmp_path / "mission-blueprint.json",
            resolution_id=resolution.id,
        )


def test_frozen_blueprint_export_cli_writes_artifact(tmp_path: Path) -> None:
    from xmuse.frozen_blueprint_export import main

    chat_db = tmp_path / "chat.db"
    resolution = _seed_blueprint_resolution(
        ChatStore(chat_db),
        approval_mode="deliberation_freeze",
        status=MissionBlueprintStatus.FROZEN,
    )
    output = tmp_path / "mission-blueprint.json"

    assert (
        main(
            [
                "--chat-db",
                str(chat_db),
                "--resolution-id",
                resolution.id,
                "--output",
                str(output),
            ]
        )
        == 0
    )

    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "frozen"


def test_frozen_blueprint_export_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-frozen-blueprint-export"]
        == "xmuse.frozen_blueprint_export:main"
    )


def _seed_blueprint_resolution(
    store: ChatStore,
    *,
    approval_mode: str,
    status: MissionBlueprintStatus,
    revision: int = 3,
    conversation_id: str | None = None,
):
    conversation = (
        store.create_conversation("Production blueprint")
        if conversation_id is None
        else next(
            item for item in store.list_conversations() if item.id == conversation_id
        )
    )
    blueprint = MissionBlueprintV1(
        blueprint_id="bp-production",
        conversation_id=conversation.id,
        revision=revision,
        goal="Close overnight autonomy evidence loop.",
        scope=["Frozen blueprint export", "Replay evidence"],
        constraints=["Use uv run.", "Keep TUI read models non-authoritative."],
        non_goals=["No merge proof before PR merge."],
        acceptance_contracts=[
            "Frozen blueprint is exported from chat.db resolution authority.",
            "Export refuses non-freeze approvals.",
        ],
        repo_areas=["src/xmuse_core/structuring", "xmuse"],
        open_questions=[],
        decision_log=[
            {
                "decision": "Freeze blueprint before execution evidence.",
                "source_refs": ["message:challenge"],
            }
        ],
        source_refs=["message:proposal", "message:challenge"],
        status=status,
        approved_by=["god-architect", "god-review"],
    )
    content = {
        "type": "mission_blueprint",
        "title": blueprint.goal,
        "body": render_mission_blueprint_markdown(blueprint),
        "acceptance_criteria": blueprint.acceptance_contracts,
        "references": blueprint.source_refs,
        "blueprint_v1": blueprint.model_dump(mode="json"),
        "markdown": render_mission_blueprint_markdown(blueprint),
    }
    proposal = store.create_proposal(
        conversation_id=conversation.id,
        author="xmuse-deliberation",
        proposal_type="mission_blueprint",
        content=json.dumps({"resolution_content": content}, sort_keys=True),
        references=blueprint.source_refs,
    )
    return store.approve_proposal(
        proposal.id,
        approved_by=blueprint.approved_by,
        approval_mode=approval_mode,
        goal_summary=blueprint.goal,
    )
