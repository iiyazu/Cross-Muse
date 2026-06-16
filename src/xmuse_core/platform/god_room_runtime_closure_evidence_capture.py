from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from xmuse_core.chat.god_room_runtime import (
    GodRoomEventV1,
    GodRoomParticipant,
    replay_god_room_turns,
)
from xmuse_core.chat.god_room_speaker_response import GodRoomSpeakerResponseCaptureV1
from xmuse_core.chat.god_room_speaker_runtime import GodRoomSpeakerAttemptV1
from xmuse_core.platform.god_room_review_chain_proof import (
    GOD_ROOM_REVIEW_CHAIN_PROOF_FORBIDDEN_CLAIMS,
    build_review_chain_proof_l10_handoff_evaluation,
)
from xmuse_core.platform.god_room_review_handoff import (
    build_review_closure_handoff_evaluation,
)
from xmuse_core.platform.production_evidence import (
    ProductionEvidenceEnvelope,
    ProductionEvidenceStatus,
)
from xmuse_core.platform.release_readiness import ProofLevel
from xmuse_core.structuring.god_room_blueprint_freeze import (
    GodRoomBlueprintFreezeArtifactV1,
    GodRoomBlueprintFreezeStatus,
)

GOD_ROOM_RUNTIME_CLOSURE_SECTION = "god_room_runtime_closure"
GOD_ROOM_RUNTIME_CLOSURE_ACTION = "god_room_runtime_closure_indexed"
GOD_ROOM_RUNTIME_CLOSURE_AUTHORITY = "god_room_runtime_closure_contract"


def capture_god_room_runtime_closure_evidence(
    *,
    run_id: str,
    output_path: str | Path,
    participants_artifact: str | Path | None = None,
    events_artifact: str | Path | None = None,
    blueprint_freeze_artifact: str | Path | None = None,
    lane_dag_artifact: str | Path | None = None,
    memory_trace_artifact: str | Path | None = None,
    tui_projection_artifact: str | Path | None = None,
    speaker_attempt_artifact: str | Path | None = None,
    speaker_response_artifact: str | Path | None = None,
    multi_turn_provider_speech_run_artifact: str | Path | None = None,
    review_closure_artifact: str | Path | None = None,
    review_chain_proof_artifact: str | Path | None = None,
    review_chain_proof_expected: bool = False,
    github_truth_artifact: str | Path | None = None,
    release_readiness_artifact: str | Path | None = None,
    stage_id: str = "S8",
) -> dict[str, object]:
    evidence = build_god_room_runtime_closure_evidence(
        run_id=run_id,
        stage_id=stage_id,
        participants_artifact=participants_artifact,
        events_artifact=events_artifact,
        blueprint_freeze_artifact=blueprint_freeze_artifact,
        lane_dag_artifact=lane_dag_artifact,
        memory_trace_artifact=memory_trace_artifact,
        tui_projection_artifact=tui_projection_artifact,
        speaker_attempt_artifact=speaker_attempt_artifact,
        speaker_response_artifact=speaker_response_artifact,
        multi_turn_provider_speech_run_artifact=multi_turn_provider_speech_run_artifact,
        review_closure_artifact=review_closure_artifact,
        review_chain_proof_artifact=review_chain_proof_artifact,
        review_chain_proof_expected=review_chain_proof_expected,
        github_truth_artifact=github_truth_artifact,
        release_readiness_artifact=release_readiness_artifact,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def build_god_room_runtime_closure_evidence(
    *,
    run_id: str,
    stage_id: str,
    participants_artifact: str | Path | None = None,
    events_artifact: str | Path | None = None,
    blueprint_freeze_artifact: str | Path | None = None,
    lane_dag_artifact: str | Path | None = None,
    memory_trace_artifact: str | Path | None = None,
    tui_projection_artifact: str | Path | None = None,
    speaker_attempt_artifact: str | Path | None = None,
    speaker_response_artifact: str | Path | None = None,
    multi_turn_provider_speech_run_artifact: str | Path | None = None,
    review_closure_artifact: str | Path | None = None,
    review_chain_proof_artifact: str | Path | None = None,
    review_chain_proof_expected: bool = False,
    github_truth_artifact: str | Path | None = None,
    release_readiness_artifact: str | Path | None = None,
) -> dict[str, object]:
    issues: list[str] = []
    missing_inputs = _missing_inputs(
        participants_artifact=participants_artifact,
        events_artifact=events_artifact,
        blueprint_freeze_artifact=blueprint_freeze_artifact,
        lane_dag_artifact=lane_dag_artifact,
        memory_trace_artifact=memory_trace_artifact,
        tui_projection_artifact=tui_projection_artifact,
        github_truth_artifact=github_truth_artifact,
        release_readiness_artifact=release_readiness_artifact,
    )
    issues.extend(_missing_input_issues(missing_inputs))

    participants, participant_refs, participant_details = _participants_from_artifact(
        participants_artifact,
        issues=issues,
    )
    events, event_refs, event_details = _events_from_artifact(
        events_artifact,
        issues=issues,
    )
    room_replay_details = _room_replay_details(
        participants=participants,
        events=events,
        participant_details=participant_details,
        event_details=event_details,
        issues=issues,
    )
    blueprint_details, blueprint_refs, blueprint_targets = _blueprint_freeze_details(
        blueprint_freeze_artifact,
        issues=issues,
    )
    lane_details, lane_refs, lane_targets = _lane_dag_details(
        lane_dag_artifact,
        issues=issues,
    )
    trace_details, trace_refs, trace_targets = _memory_trace_details(
        memory_trace_artifact,
        issues=issues,
    )
    tui_details, tui_refs = _tui_projection_details(
        tui_projection_artifact,
        issues=issues,
    )
    speaker_details, speaker_refs, speaker_targets = _speaker_attempt_details(
        speaker_attempt_artifact,
        issues=issues,
    )
    speaker_response_details, speaker_response_refs, speaker_response_targets = (
        _speaker_response_details(
            speaker_response_artifact,
            event_ids={event.event_id for event in events},
            issues=issues,
        )
    )
    multi_turn_details, multi_turn_refs, multi_turn_targets = (
        _multi_turn_provider_speech_run_details(
            multi_turn_provider_speech_run_artifact,
            event_ids={event.event_id for event in events},
            conversation_ids={event.conversation_id for event in events},
            room_ids={event.room_id for event in events},
            issues=issues,
        )
    )
    review_closure_details, review_closure_refs, review_closure_targets = (
        _review_closure_details(
            review_closure_artifact,
            issues=issues,
        )
    )
    review_chain_details, review_chain_refs, review_chain_targets = (
        _review_chain_proof_details(
            review_chain_proof_artifact,
            expected=review_chain_proof_expected,
            issues=issues,
        )
    )
    github_details, github_refs, github_targets = _github_truth_details(
        github_truth_artifact,
        issues=issues,
    )
    readiness_details, readiness_refs = _release_readiness_details(
        release_readiness_artifact,
        issues=issues,
    )

    status: ProductionEvidenceStatus = "manual_gap" if issues else "ok"
    proof_level: ProofLevel = "manual_gap" if issues else "contract_proof"
    blocked_reason = "; ".join(issues) if issues else None
    envelope = ProductionEvidenceEnvelope(
        run_id=run_id,
        stage_id=stage_id,
        action=GOD_ROOM_RUNTIME_CLOSURE_ACTION,
        status=status,
        proof_level=proof_level,
        source_authority=GOD_ROOM_RUNTIME_CLOSURE_AUTHORITY,
        source_refs=tuple(
            _dedupe(
                [
                    *participant_refs,
                    *event_refs,
                    *blueprint_refs,
                    *lane_refs,
                    *trace_refs,
                    *tui_refs,
                    *speaker_refs,
                    *speaker_response_refs,
                    *multi_turn_refs,
                    *review_closure_refs,
                    *review_chain_refs,
                    *github_refs,
                    *readiness_refs,
                ]
            )
        ),
        target_refs=tuple(
            _dedupe(
                [
                    *blueprint_targets,
                    *lane_targets,
                    *trace_targets,
                    *speaker_targets,
                    *speaker_response_targets,
                    *multi_turn_targets,
                    *review_closure_targets,
                    *review_chain_targets,
                    *github_targets,
                ]
            )
        ),
        artifacts=tuple(
            _artifact_refs(
                participants_artifact,
                events_artifact,
                blueprint_freeze_artifact,
                lane_dag_artifact,
                memory_trace_artifact,
                tui_projection_artifact,
                speaker_attempt_artifact,
                speaker_response_artifact,
                multi_turn_provider_speech_run_artifact,
                review_closure_artifact,
                review_chain_proof_artifact,
                github_truth_artifact,
                release_readiness_artifact,
            )
        ),
        blocked_reason=blocked_reason,
        owner="codex",
        next_action=_next_action(missing_inputs, issues),
        summary=_summary(
            room_replay=room_replay_details,
            lane_dag=lane_details,
            trace=trace_details,
            speaker=speaker_details,
            speaker_response=speaker_response_details,
            multi_turn_provider_speech=multi_turn_details,
            review_closure=review_closure_details,
            review_chain_proof=review_chain_details,
            readiness=readiness_details,
        ),
    )
    evidence = envelope.model_dump()
    evidence[GOD_ROOM_RUNTIME_CLOSURE_SECTION] = {
        "authority": GOD_ROOM_RUNTIME_CLOSURE_AUTHORITY,
        "missing_inputs": list(missing_inputs),
        "room_replay": room_replay_details,
        "blueprint_freeze": blueprint_details,
        "lane_dag": lane_details,
        "memory_trace": trace_details,
        "tui_projection": tui_details,
        "speaker_attempt": speaker_details,
        "speaker_response": speaker_response_details,
        "multi_turn_provider_speech": multi_turn_details,
        "review_closure": review_closure_details,
        "review_chain_proof": review_chain_details,
        "github_truth": github_details,
        "release_readiness": readiness_details,
    }
    return evidence


def _participants_from_artifact(
    path: str | Path | None,
    *,
    issues: list[str],
) -> tuple[list[GodRoomParticipant], list[str], dict[str, object]]:
    payload = _load_json(path, label="god room participants", issues=issues)
    rows = _row_list(payload, key="participants") if payload is not None else []
    participants: list[GodRoomParticipant] = []
    for index, row in enumerate(rows):
        try:
            participants.append(GodRoomParticipant.model_validate(row))
        except ValidationError as exc:
            issues.append(
                f"god room participant row {index} is invalid: {_one_line(str(exc))}"
            )
    refs = [f"god:{participant.god_id}" for participant in participants]
    details = {
        "participant_count": len(participants),
        "god_ids": _dedupe([participant.god_id for participant in participants]),
        "cli_ids": _dedupe(
            [
                participant.cli_id
                for participant in participants
                if participant.cli_id is not None
            ]
        ),
    }
    return participants, refs, details


def _events_from_artifact(
    path: str | Path | None,
    *,
    issues: list[str],
) -> tuple[list[GodRoomEventV1], list[str], dict[str, object]]:
    payload = _load_json(path, label="god room events", issues=issues)
    rows = _row_list(payload, key="events") if payload is not None else []
    events: list[GodRoomEventV1] = []
    for index, row in enumerate(rows):
        try:
            events.append(GodRoomEventV1.model_validate(row))
        except ValidationError as exc:
            issues.append(f"god room event row {index} is invalid: {_one_line(str(exc))}")
    refs: list[str] = []
    for event in events:
        refs.append(f"god-room-event:{event.event_id}")
        refs.extend(event.source_refs)
    details = {
        "event_count": len(events),
        "room_ids": _dedupe([event.room_id for event in events]),
        "conversation_ids": _dedupe([event.conversation_id for event in events]),
        "event_types": _counts([event.event_type.value for event in events]),
        "provider_profiles": _dedupe(
            [
                event.provider_profile
                for event in events
                if event.provider_profile is not None
            ]
        ),
    }
    return events, refs, details


def _room_replay_details(
    *,
    participants: list[GodRoomParticipant],
    events: list[GodRoomEventV1],
    participant_details: Mapping[str, object],
    event_details: Mapping[str, object],
    issues: list[str],
) -> dict[str, object]:
    if not participants or not events:
        issues.append("god room replay requires participants and events")
        return {
            "status": "manual_gap",
            "proof_level": "manual_gap",
            "participant_count": len(participants),
            "event_count": len(events),
            "decision_count": 0,
            "blocked_reason": "god room replay requires participants and events",
            **dict(participant_details),
            **dict(event_details),
        }
    try:
        replay = replay_god_room_turns(participants=participants, events=events)
    except ValueError as exc:
        issues.append(f"god room replay failed: {_one_line(str(exc))}")
        return {
            "status": "manual_gap",
            "proof_level": "manual_gap",
            "participant_count": len(participants),
            "event_count": len(events),
            "decision_count": 0,
            "blocked_reason": str(exc),
            **dict(participant_details),
            **dict(event_details),
        }
    if replay.status != "ok" and replay.blocked_reason is not None:
        issues.append(f"god room replay blocked: {replay.blocked_reason}")
    return {
        "status": replay.status,
        "proof_level": replay.proof_level,
        "participant_count": replay.participant_count,
        "event_count": replay.event_count,
        "decision_count": len(replay.decisions),
        "decisions": [decision.model_dump(mode="json") for decision in replay.decisions],
        "blocked_reason": replay.blocked_reason,
        **dict(participant_details),
        **dict(event_details),
    }


def _blueprint_freeze_details(
    path: str | Path | None,
    *,
    issues: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    payload = _load_json(path, label="blueprint freeze", issues=issues)
    if payload is None:
        return _manual_gap_details("blueprint freeze artifact is missing"), [], []
    try:
        artifact = GodRoomBlueprintFreezeArtifactV1.model_validate(payload)
    except ValidationError as exc:
        issues.append(f"blueprint freeze artifact is invalid: {_one_line(str(exc))}")
        return _manual_gap_details("blueprint freeze artifact is invalid"), [], []
    if artifact.status is not GodRoomBlueprintFreezeStatus.FROZEN:
        reason = artifact.blocked_reason or "blueprint freeze status is not frozen"
        issues.append(f"blueprint freeze blocked: {reason}")
    refs = list(artifact.source_refs)
    targets: list[str] = []
    blueprint_id = None
    revision = None
    if artifact.blueprint is not None:
        blueprint_id = artifact.blueprint.blueprint_id
        revision = artifact.blueprint.revision
        targets.append(f"blueprint:{blueprint_id}:{revision}")
    return (
        {
            "status": artifact.status.value,
            "blueprint_id": blueprint_id,
            "revision": revision,
            "decision_event_id": artifact.decision_event_id,
            "assumption_count": len(artifact.assumptions),
            "conflict_count": len(artifact.conflicts),
            "blocker_count": len(artifact.blockers),
            "blocked_reason": artifact.blocked_reason,
        },
        refs,
        targets,
    )


def _lane_dag_details(
    path: str | Path | None,
    *,
    issues: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    payload = _load_json(path, label="laneDAG", issues=issues)
    if not isinstance(payload, dict):
        return _manual_gap_details("laneDAG artifact is missing"), [], []
    lane_contracts = _dict_rows(payload.get("lane_contracts"))
    recovery_decisions = _dict_rows(payload.get("recovery_decisions"))
    source_event_lineage = _dict_rows(payload.get("source_event_lineage"))
    if not lane_contracts:
        issues.append("laneDAG artifact has no lane runtime contracts")
    lane_ids = _dedupe([_text(contract.get("lane_id")) for contract in lane_contracts])
    refs = _dedupe(
        [
            _text(payload.get("blueprint_ref")),
            *[f"lane:{lane_id}" for lane_id in lane_ids],
            *_lane_dag_source_event_lineage_refs(source_event_lineage),
        ]
    )
    targets = [f"lane:{lane_id}" for lane_id in lane_ids]
    return (
        {
            "blueprint_ref": _text(payload.get("blueprint_ref")),
            "lane_contract_count": len(lane_contracts),
            "lane_ids": lane_ids,
            "source_event_lineage_count": len(source_event_lineage),
            "source_event_lineage_event_types": _lineage_field_counts(
                source_event_lineage,
                "event_type",
            ),
            "source_event_lineage_proof_levels": _lineage_field_counts(
                source_event_lineage,
                "proof_level",
            ),
            "recovery_decision_count": len(recovery_decisions),
            "refactor_required_count": sum(
                1
                for decision in recovery_decisions
                if _text(decision.get("decision")) == "refactor_required"
            ),
        },
        refs,
        targets,
    )


def _lane_dag_source_event_lineage_refs(
    lineage: list[dict[str, Any]],
) -> list[str]:
    refs: list[str] = []
    for item in lineage:
        event_id = _text(item.get("event_id"))
        if event_id is not None:
            refs.append(f"god-room-event:{event_id}")
        provider_response_artifact_ref = _text(
            item.get("provider_response_artifact_ref")
        )
        if provider_response_artifact_ref is not None:
            refs.append(f"provider_response_artifact:{provider_response_artifact_ref}")
        refs.extend(_string_list(item.get("source_refs")))
    return refs


def _lineage_field_counts(
    lineage: list[dict[str, Any]],
    field_name: str,
) -> dict[str, int]:
    return _counts(
        [
            value
            for item in lineage
            if (value := _text(item.get(field_name))) is not None
        ]
    )


def _memory_trace_details(
    path: str | Path | None,
    *,
    issues: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    payload = _load_json(path, label="memory trace", issues=issues)
    if not isinstance(payload, dict):
        return _manual_gap_details("memory trace artifact is missing"), [], []
    anchors = _trace_anchors(payload)
    if not anchors:
        issues.append("memory trace artifact has no trace anchors")
    anchor_uris = _dedupe([_text(anchor.get("anchor_uri")) for anchor in anchors])
    source_refs: list[str] = []
    for anchor in anchors:
        source_refs.extend(_string_list(anchor.get("source_refs")))
    return (
        {
            "trace_anchor_count": len(anchors),
            "anchor_uris": anchor_uris,
            "proof_levels": _dedupe(
                [_text(anchor.get("proof_level")) for anchor in anchors]
            ),
        },
        source_refs,
        anchor_uris,
    )


def _tui_projection_details(
    path: str | Path | None,
    *,
    issues: list[str],
) -> tuple[dict[str, object], list[str]]:
    payload = _load_json(path, label="TUI projection", issues=issues)
    if not isinstance(payload, dict):
        return _manual_gap_details("TUI projection artifact is missing"), []
    execution = payload.get("execution")
    memory = payload.get("memory")
    if not isinstance(execution, dict):
        execution = {}
    if not isinstance(memory, dict):
        memory = {}
    lane_contracts = _dict_rows(execution.get("lane_contracts"))
    recovery_decisions = _dict_rows(execution.get("recovery_decisions"))
    trace_anchors = _dict_rows(memory.get("trace_anchors"))
    if not lane_contracts and not trace_anchors:
        issues.append("TUI projection has no lane contracts or trace anchors")
    refs = _dedupe(
        [
            *[
                f"lane:{lane_id}"
                for lane_id in (
                    _text(contract.get("lane_id")) for contract in lane_contracts
                )
                if lane_id is not None
            ],
            *[
                _text(anchor.get("anchor_uri")) or _text(anchor.get("trace_id"))
                for anchor in trace_anchors
            ],
        ]
    )
    return (
        {
            "lane_contract_count": len(lane_contracts),
            "recovery_decision_count": len(recovery_decisions),
            "trace_anchor_count": len(trace_anchors),
            "projection_authority": False,
        },
        refs,
    )


def _speaker_attempt_details(
    path: str | Path | None,
    *,
    issues: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    if path is None:
        return {
            "status": "not_provided",
            "proof_level": "manual_gap",
            "optional": True,
        }, [], []
    payload = _load_json(path, label="speaker attempt", issues=issues)
    if not isinstance(payload, dict):
        return _manual_gap_details("speaker attempt artifact is missing"), [], []
    try:
        attempt = GodRoomSpeakerAttemptV1.model_validate(payload)
    except ValidationError as exc:
        issues.append(f"speaker attempt artifact is invalid: {_one_line(str(exc))}")
        return _manual_gap_details("speaker attempt artifact is invalid"), [], []
    if attempt.status == "manual_gap":
        reason = attempt.blocked_reason or "speaker attempt is blocked"
        issues.append(f"speaker attempt blocked: {reason}")
    targets = _dedupe(
        [
            f"god-room-participant:{attempt.target_participant_id}"
            if attempt.target_participant_id
            else None,
            f"provider_session:{attempt.provider_session_id}"
            if attempt.provider_session_id
            else None,
        ]
    )
    return (
        {
            "status": attempt.status,
            "proof_level": attempt.proof_level,
            "selected_event_id": attempt.selected_event_id,
            "decision_reason": attempt.decision_reason,
            "target_participant_id": attempt.target_participant_id,
            "target_god_id": attempt.target_god_id,
            "provider_profile_ref": attempt.provider_profile_ref,
            "provider_session_id": attempt.provider_session_id,
            "provider_binding_status": attempt.provider_binding_status,
            "effective_session_status": attempt.effective_session_status,
            "blocked_reason": attempt.blocked_reason,
        },
        list(attempt.source_refs),
        targets,
    )


def _speaker_response_details(
    path: str | Path | None,
    *,
    event_ids: set[str],
    issues: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    if path is None:
        return {
            "status": "not_provided",
            "proof_level": "manual_gap",
            "optional": True,
        }, [], []
    payload = _load_json(path, label="speaker response", issues=issues)
    if not isinstance(payload, dict):
        return _manual_gap_details("speaker response artifact is missing"), [], []
    try:
        capture = GodRoomSpeakerResponseCaptureV1.model_validate(payload)
    except ValidationError as exc:
        issues.append(f"speaker response artifact is invalid: {_one_line(str(exc))}")
        return _manual_gap_details("speaker response artifact is invalid"), [], []
    if capture.status == "manual_gap":
        reason = capture.blocked_reason or "speaker response is blocked"
        issues.append(f"speaker response blocked: {reason}")
    provider_response_id = (
        capture.provider_response.response_id
        if capture.provider_response is not None
        else None
    )
    appended_event = capture.appended_event or capture.speak_event
    appended_event_id = appended_event.event_id if appended_event else None
    appended_event_type = appended_event.event_type.value if appended_event else None
    speak_event_id = capture.speak_event.event_id if capture.speak_event else None
    blocked_reason = capture.blocked_reason
    status = capture.status
    proof_level = capture.proof_level
    if capture.status in {"speak_event_appended", "event_appended"} and not str(
        capture.provider_response_artifact_ref or ""
    ).strip():
        blocked_reason = "provider response artifact missing"
        issues.append(f"speaker response blocked: {blocked_reason}")
        status = "manual_gap"
        proof_level = "manual_gap"
    elif capture.status in {"speak_event_appended", "event_appended"} and (
        appended_event_id is None or appended_event_id not in event_ids
    ):
        blocked_reason = "speaker response appended event is missing from god room events"
        issues.append(f"speaker response blocked: {blocked_reason}")
        status = "manual_gap"
        proof_level = "manual_gap"
    targets = _dedupe(
        [
            f"god-room-participant:{capture.target_participant_id}"
            if capture.target_participant_id
            else None,
            f"provider_session:{capture.provider_session_id}"
            if capture.provider_session_id
            else None,
            f"god-room-event:{appended_event_id}" if appended_event_id else None,
            f"god-room-event:{speak_event_id}" if speak_event_id else None,
        ]
    )
    return (
        {
            "status": status,
            "proof_level": proof_level,
            "selected_event_id": capture.selected_event_id,
            "target_participant_id": capture.target_participant_id,
            "target_god_id": capture.target_god_id,
            "provider_profile_ref": capture.provider_profile_ref,
            "provider_session_id": capture.provider_session_id,
            "provider_session_kind": capture.provider_session_kind,
            "provider_response_artifact_ref": capture.provider_response_artifact_ref,
            "append_status": capture.append_status,
            "blocked_reason": blocked_reason,
            "appended_event_id": appended_event_id,
            "appended_event_type": appended_event_type,
            "provider_response_id": provider_response_id,
            "speak_event_id": speak_event_id,
        },
        list(capture.source_refs),
        targets,
    )


def _multi_turn_provider_speech_run_details(
    path: str | Path | None,
    *,
    event_ids: set[str],
    conversation_ids: set[str],
    room_ids: set[str],
    issues: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    if path is None:
        return {
            "status": "not_provided",
            "proof_level": "manual_gap",
            "optional": True,
        }, [], []
    payload = _load_json(path, label="multi-turn provider speech run", issues=issues)
    if not isinstance(payload, dict):
        return (
            _manual_gap_details("multi-turn provider speech run artifact is missing"),
            [],
            [],
        )
    schema_version = _text(payload.get("schema_version"))
    status = _text(payload.get("status")) or "manual_gap"
    proof_level = _text(payload.get("proof_level")) or "manual_gap"
    conversation_id = _text(payload.get("conversation_id"))
    room_id = _text(payload.get("room_id"))
    if schema_version != "xmuse.god_room_multi_turn_provider_speech_run.v1":
        issues.append("multi-turn provider speech run artifact has unexpected schema")
    if conversation_id is not None and conversation_id not in conversation_ids:
        issues.append("multi-turn provider speech run conversation does not match room events")
    if room_id is not None and room_id not in room_ids:
        issues.append("multi-turn provider speech run room does not match room events")
    if status != "completed":
        issues.append("multi-turn provider speech run is not completed")
    if proof_level == "manual_gap":
        issues.append("multi-turn provider speech run is manual_gap")
    turns = payload.get("turns")
    if not isinstance(turns, list) or not turns:
        issues.append("multi-turn provider speech run has no turns")
        turns = []
    appended_event_ids: list[str] = []
    appended_event_types: list[str] = []
    provider_response_artifacts: list[str] = []
    speaker_response_artifacts: list[str] = []
    provider_response_ids: list[str] = []
    speaker_response_statuses: list[str] = []
    refs: list[str] = [f"multi_turn_provider_speech_run_artifact:{Path(path)}"]
    targets: list[str] = []
    for index, turn in enumerate(turns, start=1):
        if not isinstance(turn, dict):
            issues.append(f"multi-turn provider speech run turn {index} is invalid")
            continue
        event_id = _text(turn.get("appended_event_id"))
        if event_id is None:
            issues.append(
                f"multi-turn provider speech run turn {index} lacks appended_event_id"
            )
        else:
            appended_event_ids.append(event_id)
            refs.append(f"god-room-event:{event_id}")
            targets.append(f"god-room-event:{event_id}")
            if event_id not in event_ids:
                issues.append(
                    "multi-turn provider speech run appended event is missing "
                    f"from god room events: {event_id}"
                )
        artifacts = turn.get("artifacts")
        if isinstance(artifacts, dict):
            provider_response = _text(artifacts.get("provider_response"))
            speaker_response = _text(artifacts.get("speaker_response"))
            if provider_response is not None:
                provider_response_artifacts.append(provider_response)
                refs.append(f"provider_response_artifact:{provider_response}")
            if speaker_response is not None:
                speaker_response_artifacts.append(speaker_response)
                refs.append(f"speaker_response_artifact:{speaker_response}")
        speaker_response_payload = turn.get("speaker_response")
        if isinstance(speaker_response_payload, dict):
            speaker_status = _text(speaker_response_payload.get("status"))
            if speaker_status is not None:
                speaker_response_statuses.append(speaker_status)
            if speaker_status and speaker_status not in {
                "speak_event_appended",
                "event_appended",
            }:
                issues.append(
                    "multi-turn provider speech run turn "
                    f"{index} speaker response is {speaker_status}"
                )
            appended_event = speaker_response_payload.get("appended_event")
            if isinstance(appended_event, dict):
                event_type = _text(appended_event.get("event_type"))
                if event_type is not None:
                    appended_event_types.append(event_type)
            else:
                event_type = _text(speaker_response_payload.get("event_type"))
                if event_type is not None:
                    appended_event_types.append(event_type)
        provider_response_payload = turn.get("provider_response")
        if isinstance(provider_response_payload, dict):
            response_id = _text(provider_response_payload.get("response_id"))
            if response_id is not None:
                provider_response_ids.append(response_id)
    return (
        {
            "status": status,
            "proof_level": proof_level,
            "source_authority": _text(payload.get("source_authority")),
            "conversation_id": conversation_id,
            "room_id": room_id,
            "turn_count": _int(payload.get("turn_count")) or len(turns),
            "indexed_turn_count": len(appended_event_ids),
            "appended_event_ids": _dedupe(appended_event_ids),
            "appended_event_types": _counts(appended_event_types),
            "provider_response_artifacts": _dedupe(provider_response_artifacts),
            "speaker_response_artifacts": _dedupe(speaker_response_artifacts),
            "provider_response_ids": _dedupe(provider_response_ids),
            "speaker_response_statuses": _counts(speaker_response_statuses),
            "manual_gaps": _string_list(payload.get("manual_gaps")),
            "forbidden_claims": _string_list(payload.get("forbidden_claims")),
            "blocked_reason": _text(payload.get("blocked_reason")),
        },
        _dedupe(refs),
        _dedupe(targets),
    )


def _review_closure_details(
    path: str | Path | None,
    *,
    issues: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    if path is None:
        return {
            "status": "not_provided",
            "proof_level": "manual_gap",
            "optional": True,
        }, [], []
    payload = _load_json(path, label="GOD room review closure", issues=issues)
    if not isinstance(payload, dict):
        return _manual_gap_details("GOD room review closure artifact is missing"), [], []
    proof_level = _text(payload.get("proof_level")) or "manual_gap"
    review_truth_status = _text(payload.get("review_truth_status"))
    execution_truth_status = _text(payload.get("execution_truth_status"))
    server_truth_status = _text(payload.get("server_truth_status"))
    handoff_status = _text(payload.get("release_evidence_handoff_status"))
    handoff_evaluation = build_review_closure_handoff_evaluation(
        root=_review_closure_root(path, payload),
        review_closure=payload,
    )
    current_handoff_ready = handoff_evaluation.get("status") == "ready"
    current_handoff_summary = _text(handoff_evaluation.get("handoff_summary"))
    current_candidate_refs = _string_list(
        handoff_evaluation.get("candidate_artifact_refs")
    )
    current_handoff_source_refs = _string_list(handoff_evaluation.get("source_refs"))
    issues.extend(_review_closure_handoff_issues(handoff_evaluation))
    if handoff_status != "candidate_input_ready":
        issues.append(
            "GOD room review closure release handoff is not candidate_input_ready"
        )
    manual_gaps = _string_list(payload.get("manual_gaps"))
    forbidden_claims = _string_list(payload.get("forbidden_claims"))
    if "release_evidence_not_linked" not in manual_gaps:
        issues.append("GOD room review closure must preserve release evidence gap")
    candidate_refs = _string_list(payload.get("candidate_refs"))
    cited_candidate_refs = _string_list(payload.get("cited_candidate_refs"))
    failed_lane_id = _text(payload.get("failed_lane_id"))
    terminal_lane_id = _text(payload.get("terminal_lane_id"))
    source_event_lineage = _dict_rows(payload.get("source_event_lineage"))
    runner_recovery_raw = payload.get("runner_recovery_proof_lineage")
    runner_recovery_lineage = (
        runner_recovery_raw if isinstance(runner_recovery_raw, Mapping) else {}
    )
    refs = _dedupe(
        [
            *(current_handoff_source_refs if current_handoff_ready else []),
            *(current_candidate_refs if current_handoff_ready else []),
        ]
    )
    targets = _dedupe(
        [
            f"lane:{failed_lane_id}" if failed_lane_id else None,
            f"lane:{terminal_lane_id}" if terminal_lane_id else None,
        ]
    )
    return (
        {
            "status": handoff_status or "not_evaluated",
            "proof_level": proof_level,
            "review_truth_status": review_truth_status,
            "execution_truth_status": execution_truth_status,
            "server_truth_status": server_truth_status,
            "current_handoff_gate_ready": current_handoff_ready,
            "current_handoff_summary": current_handoff_summary,
            "handoff_evaluation": handoff_evaluation,
            "current_handoff_candidate_artifact_refs": current_candidate_refs,
            "current_handoff_candidate_artifact_ref_count": len(
                current_candidate_refs
            ),
            "current_handoff_source_ref_count": len(current_handoff_source_refs),
            "failed_lane_id": failed_lane_id,
            "terminal_lane_id": terminal_lane_id,
            "candidate_ref_count": len(candidate_refs),
            "cited_candidate_ref_count": len(cited_candidate_refs),
            "source_event_lineage_count": len(source_event_lineage),
            "source_event_lineage_event_types": _lineage_field_counts(
                source_event_lineage,
                "event_type",
            ),
            "source_event_lineage_proof_levels": _lineage_field_counts(
                source_event_lineage,
                "proof_level",
            ),
            "runner_recovery_proof_lineage": _runner_recovery_lineage_details(
                runner_recovery_lineage
            ),
            "manual_gaps": manual_gaps,
            "forbidden_claims": forbidden_claims,
        },
        refs,
        targets,
    )


def _review_closure_handoff_issues(
    handoff_evaluation: Mapping[str, Any],
) -> list[str]:
    if _text(handoff_evaluation.get("status")) == "ready":
        return []
    summary = _text(handoff_evaluation.get("handoff_summary"))
    return _dedupe(
        [
            (
                "GOD room review closure current handoff is not gate-ready: "
                f"{summary or 'unknown'}"
            ),
            *_string_list(handoff_evaluation.get("issues")),
        ]
    )


def _review_closure_root(path: str | Path, payload: Mapping[str, Any]) -> Path:
    root_ref = _text(payload.get("xmuse_root"))
    if root_ref is not None:
        return Path(root_ref)
    return Path(path).parent


def _review_chain_proof_details(
    path: str | Path | None,
    *,
    expected: bool = False,
    issues: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    if path is None:
        if expected:
            reason = "GOD room review chain proof artifact is expected but missing"
            issues.append(reason)
            return {
                "status": "manual_gap",
                "proof_level": "manual_gap",
                "optional": False,
                "expected": True,
                "blocked_reason": reason,
                "manual_gaps": [
                    "god_room_review_chain_proof_artifact_missing",
                    "review_truth_not_proven",
                    "server_truth_not_proven",
                    "live_memoryos_trace_not_proven",
                    "github_truth_not_checked",
                ],
                "forbidden_claims": list(
                    GOD_ROOM_REVIEW_CHAIN_PROOF_FORBIDDEN_CLAIMS
                ),
            }, [], []
        return {
            "status": "not_provided",
            "proof_level": "manual_gap",
            "optional": True,
            "expected": False,
        }, [], []
    payload = _load_json(path, label="GOD room review chain proof", issues=issues)
    if not isinstance(payload, dict):
        return _manual_gap_details("GOD room review chain proof artifact is missing"), [], []
    status = _text(payload.get("status")) or "manual_gap"
    proof_level = _text(payload.get("proof_level")) or "manual_gap"
    server_truth_status = _text(payload.get("server_truth_status"))
    forbidden_claims = _string_list(payload.get("forbidden_claims"))
    session_raw = payload.get("local_execution_review_session")
    session = session_raw if isinstance(session_raw, Mapping) else {}
    handoff_evaluation = build_review_chain_proof_l10_handoff_evaluation(
        root=_review_chain_root(path, payload),
        artifact_path=path,
        review_chain_proof=payload,
    )
    bounded_session_raw = handoff_evaluation.get("bounded_session_gate")
    bounded_session_gate = (
        bounded_session_raw if isinstance(bounded_session_raw, Mapping) else {}
    )
    handoff_ready = handoff_evaluation["status"] == "ready"
    current_handoff_ready = handoff_evaluation.get("current_handoff_gate_ready") is True
    current_handoff_summary = _text(handoff_evaluation.get("current_handoff_summary"))
    current_candidate_refs = _string_list(
        handoff_evaluation.get("current_handoff_candidate_artifact_refs")
    )
    current_handoff_source_refs = _string_list(handoff_evaluation.get("source_refs"))
    candidate_refs = _string_list(handoff_evaluation.get("candidate_artifact_refs"))
    if not handoff_ready:
        issues.extend(_string_list(handoff_evaluation.get("issues")))

    runner_recovery_raw = payload.get("runner_recovery_proof_lineage")
    runner_recovery_lineage = (
        runner_recovery_raw if isinstance(runner_recovery_raw, Mapping) else {}
    )
    worker_evidence_bundle_refs = _string_list(
        handoff_evaluation.get("worker_evidence_bundle_refs")
    )
    graph_id = _text(payload.get("graph_id"))
    failed_lane_id = _text(payload.get("failed_lane_id"))
    terminal_lane_id = _text(payload.get("terminal_lane_id"))
    refs = _dedupe(
        [
            f"god-room-review-chain-proof:{graph_id}:{failed_lane_id}:{terminal_lane_id}"
            if handoff_ready and graph_id and failed_lane_id and terminal_lane_id
            else None,
            f"review_chain_proof_artifact:{Path(path)}"
            if handoff_ready
            else None,
            _text(payload.get("review_closure_artifact"))
            if handoff_ready
            else None,
            f"lane:{failed_lane_id}" if handoff_ready and failed_lane_id else None,
            f"lane:{terminal_lane_id}"
            if handoff_ready and terminal_lane_id
            else None,
            *(current_handoff_source_refs if handoff_ready else []),
            *(candidate_refs if handoff_ready else []),
            *(
                _runner_recovery_lineage_refs(runner_recovery_lineage)
                if handoff_ready
                else []
            ),
            *(worker_evidence_bundle_refs if handoff_ready else []),
        ]
    )
    targets = _dedupe(
        [
            f"lane:{failed_lane_id}" if failed_lane_id else None,
            f"lane:{terminal_lane_id}" if terminal_lane_id else None,
        ]
    )
    manual_gaps = _string_list(payload.get("manual_gaps"))
    return (
        {
            "status": status,
            "proof_level": proof_level,
            "server_truth_status": server_truth_status,
            "conversation_id": _text(payload.get("conversation_id")),
            "graph_id": graph_id,
            "failed_lane_id": failed_lane_id,
            "terminal_lane_id": terminal_lane_id,
            "release_handoff_gate_ready": handoff_ready,
            "current_handoff_gate_ready": current_handoff_ready,
            "current_handoff_summary": current_handoff_summary,
            "handoff_evaluation": handoff_evaluation,
            "current_handoff_candidate_artifact_refs": current_candidate_refs,
            "current_handoff_candidate_artifact_ref_count": len(
                current_candidate_refs
            ),
            "current_handoff_source_ref_count": len(current_handoff_source_refs),
            "candidate_artifact_ref_count": len(candidate_refs),
            "bounded_session_gate": bounded_session_gate,
            "local_execution_review_session": _review_chain_session_details(
                session
            ),
            "runner_recovery_proof_lineage": _runner_recovery_lineage_details(
                runner_recovery_lineage
            ),
            "worker_evidence_bundle_refs": worker_evidence_bundle_refs
            if current_handoff_ready
            else [],
            "worker_evidence_bundle_ref_count": (
                len(worker_evidence_bundle_refs) if current_handoff_ready else 0
            ),
            "manual_gaps": manual_gaps,
            "forbidden_claims": forbidden_claims,
        },
        refs,
        targets,
    )


def _review_chain_root(path: str | Path, payload: Mapping[str, Any]) -> Path:
    root_ref = _text(payload.get("xmuse_root"))
    if root_ref is not None:
        return Path(root_ref)
    return Path(path).parent


def _root_relative_artifact_path(root: Path, artifact_ref: str) -> Path | None:
    raw_path = Path(artifact_ref)
    candidate = raw_path if raw_path.is_absolute() else root / raw_path
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return None
    return candidate


def _review_chain_session_details(payload: Mapping[str, Any]) -> dict[str, object]:
    if not payload:
        return {
            "status": "not_provided",
            "proof_level": "manual_gap",
            "optional": True,
        }
    return {
        "schema_version": _text(payload.get("schema_version")),
        "session_id": _text(payload.get("session_id")),
        "status": _text(payload.get("status")),
        "proof_level": _text(payload.get("proof_level")),
        "session_truth_status": _text(payload.get("session_truth_status")),
        "execution_truth_status": _text(payload.get("execution_truth_status")),
        "review_truth_status": _text(payload.get("review_truth_status")),
        "server_truth_status": _text(payload.get("server_truth_status")),
        "candidate_count": _int(payload.get("candidate_count")),
        "candidate_artifact_refs": _string_list(
            payload.get("candidate_artifact_refs")
        ),
        "candidate_run_ids": _string_list(payload.get("candidate_run_ids")),
        "candidate_worker_ids": _string_list(payload.get("candidate_worker_ids")),
        "candidate_output_refs": _string_list(
            payload.get("candidate_output_refs")
        ),
        "candidate_verification_refs": _string_list(
            payload.get("candidate_verification_refs")
        ),
        "session_artifact_ref_count": len(
            _string_list(payload.get("session_artifact_refs"))
        ),
        "session_source_ref_count": len(
            _string_list(payload.get("session_source_refs"))
        ),
        "session_scope_boundary": _review_chain_session_boundary_details(
            payload.get("session_scope_boundary")
        ),
        "session_artifact_validation": _review_chain_session_artifact_validation(
            payload.get("session_artifact_validation")
        ),
        "runner_recovery_proof_status": _text(
            payload.get("runner_recovery_proof_status")
        ),
        "runner_recovery_proof_level": _text(
            payload.get("runner_recovery_proof_level")
        ),
        "runner_recovery_lineage_boundary": _review_chain_session_boundary_details(
            payload.get("runner_recovery_lineage_boundary")
        ),
    }


def _review_chain_session_boundary_details(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {
            "status": "not_provided",
            "proof_level": "manual_gap",
            "issue_count": 0,
        }
    return {
        "schema_version": _text(value.get("schema_version")),
        "status": _text(value.get("status")) or "manual_gap",
        "proof_level": _text(value.get("proof_level")) or "manual_gap",
        "issue_count": len(_string_list(value.get("issues"))),
        "manual_gaps": _string_list(value.get("manual_gaps")),
    }


def _review_chain_session_artifact_validation(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {
            "status": "not_provided",
            "proof_level": "manual_gap",
            "artifact_count": 0,
            "issue_count": 0,
        }
    return {
        "schema_version": _text(value.get("schema_version")),
        "status": _text(value.get("status")) or "manual_gap",
        "proof_level": _text(value.get("proof_level")) or "manual_gap",
        "artifact_count": _int(value.get("artifact_count")),
        "artifact_refs": _string_list(value.get("artifact_refs")),
        "issue_count": len(_string_list(value.get("issues"))),
        "manual_gaps": _string_list(value.get("manual_gaps")),
    }


def _runner_recovery_lineage_refs(payload: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    artifact_ref = _text(payload.get("artifact_ref"))
    if artifact_ref is not None:
        refs.append(f"runner_recovery_proof_artifact:{artifact_ref}")
    refs.extend(_string_list(payload.get("source_refs")))
    return _dedupe(refs)


def _runner_recovery_lineage_details(payload: Mapping[str, Any]) -> dict[str, object]:
    if not payload:
        return {
            "status": "not_provided",
            "proof_level": "manual_gap",
            "optional": True,
        }
    return {
        "schema_version": _text(payload.get("schema_version")),
        "status": _text(payload.get("status")) or "not_evaluated",
        "proof_level": _text(payload.get("proof_level")) or "manual_gap",
        "source_authority": _text(payload.get("source_authority")),
        "artifact_ref": _text(payload.get("artifact_ref")),
        "source_ref_count": len(_string_list(payload.get("source_refs"))),
        "target_ref_count": len(_string_list(payload.get("target_refs"))),
        "manual_gaps": _string_list(payload.get("manual_gaps")),
        "forbidden_claims": _string_list(payload.get("forbidden_claims")),
    }


def _github_truth_details(
    path: str | Path | None,
    *,
    issues: list[str],
) -> tuple[dict[str, object], list[str], list[str]]:
    payload = _load_json(path, label="github truth", issues=issues)
    if not isinstance(payload, dict):
        return _manual_gap_details("github truth artifact is missing"), [], []
    merged = payload.get("merged") is True
    can_emit_pr_merged = payload.get("can_emit_pr_merged") is True
    pr_number = payload.get("pull_request_number")
    refs: list[str] = []
    targets: list[str] = []
    if isinstance(pr_number, int) and not isinstance(pr_number, bool):
        refs.append(f"github:pr:{pr_number}")
        targets.append(f"github:pr:{pr_number}")
    head_sha = _text(payload.get("head_sha"))
    if head_sha is not None:
        refs.append(f"github:head:{head_sha}")
    return (
        {
            "pull_request_number": pr_number if isinstance(pr_number, int) else None,
            "head_sha": head_sha,
            "head_sha_matches_expected": payload.get("head_sha_matches_expected")
            is True,
            "merged": merged,
            "can_emit_pr_merged": can_emit_pr_merged,
            "merge_truth": "pr_merged" if merged and can_emit_pr_merged else "missing",
            "gap_reason": _text(payload.get("gap_reason")),
        },
        refs,
        targets,
    )


def _release_readiness_details(
    path: str | Path | None,
    *,
    issues: list[str],
) -> tuple[dict[str, object], list[str]]:
    payload = _load_json(path, label="release readiness", issues=issues)
    if not isinstance(payload, dict):
        return _manual_gap_details("release readiness artifact is missing"), []
    blockers = _dict_rows(payload.get("blockers"))
    refs = [
        f"release_gate:{gate_id}"
        for gate_id in (_text(blocker.get("gate_id")) for blocker in blockers)
        if gate_id is not None
    ]
    return (
        {
            "decision": _text(payload.get("decision")) or "not_evaluated",
            "blocker_count": len(blockers),
            "proof_level_summary": payload.get("proof_level_summary")
            if isinstance(payload.get("proof_level_summary"), dict)
            else {},
        },
        refs,
    )


def _load_json(
    path: str | Path | None,
    *,
    label: str,
    issues: list[str],
) -> object | None:
    if path is None:
        return None
    artifact_path = Path(path)
    try:
        return json.loads(artifact_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        issues.append(f"{label} artifact does not exist: {artifact_path}")
    except json.JSONDecodeError as exc:
        issues.append(f"{label} artifact is not valid JSON: {exc}")
    except OSError as exc:
        issues.append(f"{label} artifact could not be read: {exc}")
    return None


def _row_list(payload: object, *, key: str) -> list[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return list(payload[key])
    return []


def _trace_anchors(payload: Mapping[str, object]) -> list[dict[str, Any]]:
    anchors = _dict_rows(payload.get("trace_anchors"))
    memory = payload.get("memory")
    if isinstance(memory, dict):
        anchors.extend(_dict_rows(memory.get("trace_anchors")))
    return anchors


def _missing_inputs(
    *,
    participants_artifact: object,
    events_artifact: object,
    blueprint_freeze_artifact: object,
    lane_dag_artifact: object,
    memory_trace_artifact: object,
    tui_projection_artifact: object,
    github_truth_artifact: object,
    release_readiness_artifact: object,
) -> list[str]:
    missing: list[str] = []
    for key, value in (
        ("god_room_participants", participants_artifact),
        ("god_room_events", events_artifact),
        ("blueprint_freeze", blueprint_freeze_artifact),
        ("lane_dag", lane_dag_artifact),
        ("memory_trace", memory_trace_artifact),
        ("tui_projection", tui_projection_artifact),
        ("github_truth", github_truth_artifact),
        ("release_readiness", release_readiness_artifact),
    ):
        if value is None:
            missing.append(key)
    return missing


def _missing_input_issues(missing_inputs: Sequence[str]) -> list[str]:
    messages = {
        "god_room_participants": "god room participants artifact is missing",
        "god_room_events": "god room events artifact is missing",
        "blueprint_freeze": "blueprint freeze artifact is missing",
        "lane_dag": "laneDAG artifact is missing",
        "memory_trace": "memory trace artifact is missing",
        "tui_projection": "TUI projection artifact is missing",
        "github_truth": "github truth artifact is missing",
        "release_readiness": "release readiness artifact is missing",
    }
    return [messages[item] for item in missing_inputs]


def _manual_gap_details(reason: str) -> dict[str, object]:
    return {
        "status": "manual_gap",
        "proof_level": "manual_gap",
        "blocked_reason": reason,
    }


def _next_action(missing_inputs: Sequence[str], issues: Sequence[str]) -> str | None:
    if not issues:
        return None
    if missing_inputs:
        return (
            "Attach GOD room runtime closure inputs and regenerate the release "
            "evidence pack."
        )
    return (
        "Fix invalid or blocked GOD room runtime closure evidence and regenerate "
        "the release evidence pack."
    )


def _summary(
    *,
    room_replay: Mapping[str, object],
    lane_dag: Mapping[str, object],
    trace: Mapping[str, object],
    speaker: Mapping[str, object],
    speaker_response: Mapping[str, object],
    multi_turn_provider_speech: Mapping[str, object],
    review_closure: Mapping[str, object],
    review_chain_proof: Mapping[str, object],
    readiness: Mapping[str, object],
) -> str:
    return (
        "GOD room runtime closure indexed "
        f"{_int(room_replay.get('event_count'))} room event(s), "
        f"{_int(lane_dag.get('lane_contract_count'))} lane contract(s), "
        f"{_int(trace.get('trace_anchor_count'))} MemoryOS trace anchor(s); "
        f"speaker attempt is {_text(speaker.get('status')) or 'not_provided'}; "
        "speaker response is "
        f"{_text(speaker_response.get('status')) or 'not_provided'}; "
        "multi-turn provider speech is "
        f"{_text(multi_turn_provider_speech.get('status')) or 'not_provided'}; "
        "review closure is "
        f"{_text(review_closure.get('status')) or 'not_provided'}; "
        "review chain proof is "
        f"{_text(review_chain_proof.get('status')) or 'not_provided'}; "
        f"release readiness is {_text(readiness.get('decision')) or 'not_evaluated'}."
    )


def _artifact_refs(*paths: str | Path | None) -> list[str]:
    return [str(Path(path)) for path in paths if path is not None]


def _dict_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _counts(values: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _dedupe(values: Sequence[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None or not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _one_line(value: str) -> str:
    return " ".join(value.split())
