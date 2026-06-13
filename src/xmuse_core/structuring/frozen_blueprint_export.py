from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.chat.models import ResolutionStatus, StructuredResolution
from xmuse_core.chat.store import ChatStore
from xmuse_core.structuring.mission_blueprint_v1 import (
    MissionBlueprintStatus,
    MissionBlueprintV1,
)

DELIBERATION_FREEZE_APPROVAL_MODE = "deliberation_freeze"


def export_frozen_blueprint_from_chat_store(
    *,
    chat_db: str | Path,
    output_path: str | Path,
    resolution_id: str | None = None,
    conversation_id: str | None = None,
) -> Path:
    store = ChatStore(chat_db)
    resolution = (
        store.get_resolution(resolution_id)
        if resolution_id is not None
        else _latest_frozen_resolution(store, conversation_id=conversation_id)
    )
    blueprint = frozen_blueprint_from_resolution(resolution)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            blueprint.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return output


def frozen_blueprint_from_resolution(
    resolution: StructuredResolution,
) -> MissionBlueprintV1:
    if resolution.status is not ResolutionStatus.APPROVED:
        raise ValueError(f"resolution {resolution.id} must be approved")
    if resolution.approval_mode != DELIBERATION_FREEZE_APPROVAL_MODE:
        raise ValueError(
            f"resolution {resolution.id} approval_mode must be "
            f"{DELIBERATION_FREEZE_APPROVAL_MODE}"
        )
    if resolution.content.get("type") != "mission_blueprint":
        raise ValueError(f"resolution {resolution.id} content must be a mission blueprint")
    payload = resolution.content.get("blueprint_v1")
    if not isinstance(payload, dict):
        raise ValueError(f"resolution {resolution.id} must include blueprint_v1")
    blueprint = MissionBlueprintV1.model_validate(payload)
    if blueprint.status is not MissionBlueprintStatus.FROZEN:
        raise ValueError(
            f"mission blueprint {blueprint.blueprint_id} status is "
            f"{blueprint.status.value}, expected frozen"
        )
    if blueprint.conversation_id != resolution.conversation_id:
        raise ValueError(
            f"mission blueprint {blueprint.blueprint_id} conversation_id does not "
            f"match resolution {resolution.id}"
        )
    return _with_resolution_source_ref(blueprint, resolution)


def _latest_frozen_resolution(
    store: ChatStore,
    *,
    conversation_id: str | None,
) -> StructuredResolution:
    candidates: list[StructuredResolution] = []
    for resolution in store.list_resolutions(conversation_id):
        try:
            frozen_blueprint_from_resolution(resolution)
        except ValueError:
            continue
        candidates.append(resolution)
    if not candidates:
        scope = (
            f"conversation {conversation_id}"
            if conversation_id is not None
            else "chat store"
        )
        raise ValueError(f"no deliberation_freeze frozen blueprint found in {scope}")
    return candidates[-1]


def _with_resolution_source_ref(
    blueprint: MissionBlueprintV1,
    resolution: StructuredResolution,
) -> MissionBlueprintV1:
    refs = _dedupe([*blueprint.source_refs, f"resolution:{resolution.id}"])
    return blueprint.model_copy(update={"source_refs": refs})


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = value.strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result
