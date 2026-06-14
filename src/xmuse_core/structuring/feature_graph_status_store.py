from __future__ import annotations

import fcntl
import json
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, TypeAlias

from xmuse_core.structuring.feature_review_contracts import (
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphStatusEventRecord,
    ProviderSessionBindingDegradationEvidence,
)
from xmuse_core.structuring.models import FeatureGraphSet, FeaturePlanFeature, LaneGraph

SCHEMA_VERSION = "xmuse.feature_graph_statuses.v1"
FeatureGraphExecutionStatusRecords: TypeAlias = list[
    FeatureGraphExecutionStatusRecord
]
FeatureGraphStatusEvents: TypeAlias = list[FeatureGraphStatusEventRecord]
_ALLOWED_STATUS_TRANSITIONS: dict[
    FeatureGraphExecutionStatus,
    set[FeatureGraphExecutionStatus],
] = {
    FeatureGraphExecutionStatus.PLANNED: {
        FeatureGraphExecutionStatus.READY,
        FeatureGraphExecutionStatus.BLOCKED,
        FeatureGraphExecutionStatus.FAILED,
    },
    FeatureGraphExecutionStatus.READY: {
        FeatureGraphExecutionStatus.RUNNING,
        FeatureGraphExecutionStatus.BLOCKED,
        FeatureGraphExecutionStatus.FAILED,
    },
    FeatureGraphExecutionStatus.RUNNING: {
        FeatureGraphExecutionStatus.REVIEWING,
        FeatureGraphExecutionStatus.REWORKING,
        FeatureGraphExecutionStatus.BLOCKED,
        FeatureGraphExecutionStatus.FAILED,
    },
    FeatureGraphExecutionStatus.REVIEWING: {
        FeatureGraphExecutionStatus.MERGED,
        FeatureGraphExecutionStatus.REWORKING,
        FeatureGraphExecutionStatus.BLOCKED,
        FeatureGraphExecutionStatus.FAILED,
    },
    FeatureGraphExecutionStatus.REWORKING: {
        FeatureGraphExecutionStatus.RUNNING,
        FeatureGraphExecutionStatus.BLOCKED,
        FeatureGraphExecutionStatus.FAILED,
    },
    FeatureGraphExecutionStatus.BLOCKED: {
        FeatureGraphExecutionStatus.READY,
        FeatureGraphExecutionStatus.RUNNING,
        FeatureGraphExecutionStatus.FAILED,
    },
    FeatureGraphExecutionStatus.MERGED: set(),
    FeatureGraphExecutionStatus.FAILED: set(),
}


class FeatureGraphStatusStore:
    """Durable graph-native execution status store.

    This store is intentionally independent from ``feature_lanes.json``.  The
    flat lane file may keep a compatibility projection ref on each record, but
    status queries here only use graph-native feature graph records.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    def upsert(
        self,
        record: FeatureGraphExecutionStatusRecord,
    ) -> FeatureGraphExecutionStatusRecord:
        validated = FeatureGraphExecutionStatusRecord.model_validate(
            record.model_dump(mode="json")
        )
        with self._locked_file():
            records = self._read_records_unlocked()
            events = self._read_events_unlocked()
            updated: FeatureGraphExecutionStatusRecords = []
            replaced = False
            for existing in records:
                _raise_if_status_id_replay_conflict(existing, validated)
                if _same_feature_graph(existing, validated):
                    _raise_if_stale(existing, validated)
                    _raise_if_provider_binding_degradation_evidence_upsert_changed(
                        existing,
                        validated,
                    )
                    if (
                        validated.blueprint_proof_level is None
                        and existing.blueprint_proof_level is not None
                    ):
                        validated = validated.model_copy(
                            update={
                                "blueprint_proof_level": existing.blueprint_proof_level
                            }
                        )
                    validated = _preserve_or_validate_source_event_lineage(
                        existing,
                        validated,
                    )
                    if not replaced:
                        updated.append(validated)
                        replaced = True
                    continue
                updated.append(existing)
            if not replaced:
                updated.append(validated)
            self._write_payload_unlocked(updated, events)
        return validated

    def transition(
        self,
        record: FeatureGraphExecutionStatusRecord,
        *,
        expected_status: FeatureGraphExecutionStatus | None = None,
    ) -> FeatureGraphExecutionStatusRecord:
        validated = FeatureGraphExecutionStatusRecord.model_validate(
            record.model_dump(mode="json")
        )
        with self._locked_file():
            records = self._read_records_unlocked()
            events = self._read_events_unlocked()
            updated: FeatureGraphExecutionStatusRecords = []
            transitioned: FeatureGraphExecutionStatusRecord | None = None
            event: FeatureGraphStatusEventRecord | None = None
            found = False
            for existing in records:
                _raise_if_status_id_replay_conflict(existing, validated)
                if not _same_feature_graph(existing, validated):
                    updated.append(existing)
                    continue

                found = True
                _raise_if_stale(existing, validated)
                if _same_record(existing, validated):
                    updated.append(existing)
                    transitioned = existing
                    continue
                if expected_status is not None and existing.status is not expected_status:
                    raise ValueError(
                        "expected feature graph status "
                        f"{expected_status.value}, found {existing.status.value}"
                    )
                _raise_if_provider_binding_degradation_evidence_changed(
                    existing,
                    validated,
                )
                if (
                    validated.blueprint_proof_level is None
                    and existing.blueprint_proof_level is not None
                ):
                    validated = validated.model_copy(
                        update={
                                "blueprint_proof_level": existing.blueprint_proof_level
                            }
                        )
                validated = _preserve_or_validate_source_event_lineage(
                    existing,
                    validated,
                )
                _raise_if_conflicting_replay(existing, validated)
                _raise_if_illegal_transition(existing.status, validated.status)
                updated.append(validated)
                transitioned = validated
                event = _transition_event(existing, validated)

            if not found:
                raise KeyError(
                    "feature graph status not found: "
                    f"{validated.graph_set_id}:{validated.feature_graph_id}"
                )
            if transitioned is None:
                raise RuntimeError("feature graph status transition did not resolve")
            self._write_payload_unlocked(updated, _append_event(events, event))
            return transitioned

    def initialize_from_graph_set(
        self,
        graph_set: FeatureGraphSet,
        *,
        updated_at: str,
        blueprint_proof_level: str | None = None,
    ) -> FeatureGraphExecutionStatusRecords:
        initialized: FeatureGraphExecutionStatusRecords = []
        with self._locked_file():
            records = self._read_records_unlocked()
            events = self._read_events_unlocked()
            existing_by_graph_id = {
                record.feature_graph_id: record
                for record in records
                if record.graph_set_id == graph_set.id
                and record.graph_set_version == graph_set.version
            }
            previous_by_graph_id = {
                record.feature_graph_id: record
                for record in records
                if record.graph_set_id == graph_set.id
            }
            updated = list(records)
            updated_events = list(events)
            for feature, graph in _feature_graph_pairs(graph_set):
                existing = existing_by_graph_id.get(graph.id)
                if existing is not None:
                    initialized.append(existing)
                    continue
                record = _status_from_graph_set(
                    graph_set,
                    feature=feature,
                    graph=graph,
                    status=(
                        FeatureGraphExecutionStatus.READY
                        if not feature.dependencies
                        else FeatureGraphExecutionStatus.PLANNED
                    ),
                    updated_at=updated_at,
                    blueprint_proof_level=blueprint_proof_level,
                )
                previous = previous_by_graph_id.get(graph.id)
                if previous is not None:
                    record = record.model_copy(
                        update={
                            "blueprint_proof_level": (
                                blueprint_proof_level
                                if blueprint_proof_level is not None
                                else previous.blueprint_proof_level
                            ),
                            "provider_session_binding_degradations": list(
                                previous.provider_session_binding_degradations
                            ),
                            "source_event_lineage": (
                                list(graph_set.source_event_lineage)
                                or list(previous.source_event_lineage)
                            ),
                        }
                    )
                updated = _upsert_record(updated, record)
                updated_events = _append_event(updated_events, _initialized_event(record))
                initialized.append(record)
            self._write_payload_unlocked(updated, updated_events)
        return initialized

    def release_ready_dependents(
        self,
        graph_set: FeatureGraphSet,
        *,
        updated_at: str,
    ) -> FeatureGraphExecutionStatusRecords:
        expected_graph_id_by_feature_id = {
            feature.feature_id: feature.graph_id
            for feature in graph_set.feature_plan.features
        }
        existing_by_feature_id = _current_records_by_feature_id(
            self.list(graph_set_id=graph_set.id),
            graph_set=graph_set,
            expected_graph_id_by_feature_id=expected_graph_id_by_feature_id,
        )
        released: FeatureGraphExecutionStatusRecords = []
        for feature, graph in _feature_graph_pairs(graph_set):
            current = existing_by_feature_id.get(feature.feature_id)
            if current is None:
                continue
            if current.status is not FeatureGraphExecutionStatus.PLANNED:
                continue
            if not _feature_dependencies_merged(feature, existing_by_feature_id):
                continue
            ready = _status_from_graph_set(
                graph_set,
                feature=feature,
                graph=graph,
                status=FeatureGraphExecutionStatus.READY,
                updated_at=updated_at,
                previous=current,
            )
            released.append(self.transition(ready, expected_status=current.status))
        return released

    def claim_ready(
        self,
        *,
        graph_set_id: str,
        feature_graph_id: str,
        worker_session_id: str,
        provider_session_binding_ref: str | None,
        updated_at: str,
        active_lane_ids: list[str] | None = None,
    ) -> FeatureGraphExecutionStatusRecord:
        current = self.get(
            graph_set_id=graph_set_id,
            feature_graph_id=feature_graph_id,
        )
        if _is_same_claim_replay(
            current,
            worker_session_id=worker_session_id,
            provider_session_binding_ref=provider_session_binding_ref,
            updated_at=updated_at,
            active_lane_ids=active_lane_ids,
        ):
            return current
        claimed = current.model_copy(
            update={
                "status_id": _feature_graph_status_id(
                    graph_set_id=current.graph_set_id,
                    feature_graph_id=current.feature_graph_id,
                    status=FeatureGraphExecutionStatus.RUNNING,
                    updated_at=updated_at,
                ),
                "status": FeatureGraphExecutionStatus.RUNNING,
                "ready_lane_ids": [],
                "active_lane_ids": (
                    list(active_lane_ids)
                    if active_lane_ids is not None
                    else list(current.ready_lane_ids)
                ),
                "active_worker_session_id": worker_session_id,
                "active_provider_session_binding_ref": provider_session_binding_ref,
                "updated_at": updated_at,
            }
        )
        return self.transition(
            claimed,
            expected_status=FeatureGraphExecutionStatus.READY,
        )

    def record_provider_session_binding_degradation(
        self,
        *,
        graph_set_id: str,
        feature_graph_id: str,
        evidence: ProviderSessionBindingDegradationEvidence,
        updated_at: str,
    ) -> FeatureGraphExecutionStatusRecord:
        validated_evidence = ProviderSessionBindingDegradationEvidence.model_validate(
            evidence.model_dump(mode="json")
        )
        with self._locked_file():
            records = self._read_records_unlocked()
            events = self._read_events_unlocked()
            updated_records: FeatureGraphExecutionStatusRecords = []
            updated_record: FeatureGraphExecutionStatusRecord | None = None
            event: FeatureGraphStatusEventRecord | None = None
            for current in records:
                if (
                    current.graph_set_id != graph_set_id
                    or current.feature_graph_id != feature_graph_id
                ):
                    updated_records.append(current)
                    continue

                existing_evidence = _matching_provider_binding_degradation(
                    current,
                    validated_evidence,
                )
                if existing_evidence is not None:
                    if existing_evidence != validated_evidence:
                        raise ValueError(
                            "provider session binding degradation replay conflict: "
                            f"{validated_evidence.binding_id}:"
                            f"{validated_evidence.reason}"
                        )
                    updated_records.append(current)
                    updated_record = current
                    continue

                candidate = current.model_copy(
                    update={
                        "status_id": _provider_binding_degradation_status_id(
                            current,
                            evidence=validated_evidence,
                            updated_at=updated_at,
                        ),
                        "provider_session_binding_degradations": [
                            *current.provider_session_binding_degradations,
                            validated_evidence,
                        ],
                        "updated_at": updated_at,
                    }
                )
                _raise_if_stale(current, candidate)
                updated_records.append(candidate)
                updated_record = candidate
                event = _provider_binding_degradation_event(
                    current,
                    candidate,
                    evidence=validated_evidence,
                )

            if updated_record is None:
                raise KeyError(
                    "feature graph status not found: "
                    f"{graph_set_id}:{feature_graph_id}"
                )
            self._write_payload_unlocked(
                updated_records,
                _append_event(events, event),
            )
            return updated_record

    def get(
        self,
        *,
        graph_set_id: str,
        feature_graph_id: str,
    ) -> FeatureGraphExecutionStatusRecord:
        for record in self.list(graph_set_id=graph_set_id):
            if record.feature_graph_id == feature_graph_id:
                return record
        raise KeyError(
            f"feature graph status not found: {graph_set_id}:{feature_graph_id}"
        )

    def list(
        self,
        *,
        graph_set_id: str | None = None,
        conversation_id: str | None = None,
    ) -> FeatureGraphExecutionStatusRecords:
        with self._locked_file():
            records = self._read_records_unlocked()
        if graph_set_id is not None:
            records = [record for record in records if record.graph_set_id == graph_set_id]
        if conversation_id is not None:
            records = [
                record for record in records if record.conversation_id == conversation_id
            ]
        return records

    def list_ready(
        self,
        *,
        graph_set_id: str | None = None,
        conversation_id: str | None = None,
    ) -> FeatureGraphExecutionStatusRecords:
        return [
            record
            for record in self.list(
                graph_set_id=graph_set_id,
                conversation_id=conversation_id,
            )
            if record.status is FeatureGraphExecutionStatus.READY
        ]

    def list_events(
        self,
        *,
        graph_set_id: str | None = None,
        feature_graph_id: str | None = None,
    ) -> FeatureGraphStatusEvents:
        with self._locked_file():
            events = self._read_events_unlocked()
        if graph_set_id is not None:
            events = [event for event in events if event.graph_set_id == graph_set_id]
        if feature_graph_id is not None:
            events = [
                event
                for event in events
                if event.feature_graph_id == feature_graph_id
            ]
        return events

    def _read_payload_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": SCHEMA_VERSION, "statuses": []}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("feature graph status payload must be an object")
        return payload

    def _read_records_unlocked(self) -> FeatureGraphExecutionStatusRecords:
        payload = self._read_payload_unlocked()
        return self._read_records_from_payload(payload)

    def _read_events_unlocked(self) -> FeatureGraphStatusEvents:
        payload = self._read_payload_unlocked()
        records = self._read_records_from_payload(payload)
        events = payload.get("events", [])
        if not isinstance(events, list):
            raise ValueError("feature graph status events must be a list")
        for event in events:
            if not isinstance(event, dict):
                raise ValueError("feature graph status event must be an object")
        parsed = [
            FeatureGraphStatusEventRecord.model_validate(event)
            for event in events
        ]
        _raise_if_event_replay_conflicts(parsed)
        _raise_if_events_reference_missing_status_identity(parsed, records)
        _raise_if_events_drift_from_status_records(parsed, records)
        _raise_if_event_status_lineage_gaps(parsed, records)
        return parsed

    def _read_records_from_payload(
        self,
        payload: dict[str, Any],
    ) -> FeatureGraphExecutionStatusRecords:
        statuses = payload.get("statuses", [])
        if not isinstance(statuses, list):
            raise ValueError("feature graph statuses must be a list")
        for status in statuses:
            if not isinstance(status, dict):
                raise ValueError("feature graph status must be an object")
        records = [
            FeatureGraphExecutionStatusRecord.model_validate(row)
            for row in statuses
        ]
        _raise_if_status_record_replay_conflicts(records)
        _raise_if_duplicate_feature_graph_status_identities(records)
        return records

    def _write_records_unlocked(
        self,
        records: FeatureGraphExecutionStatusRecords,
    ) -> None:
        self._write_payload_unlocked(records, self._read_events_unlocked())

    def _write_payload_unlocked(
        self,
        records: FeatureGraphExecutionStatusRecords,
        events: FeatureGraphStatusEvents,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "statuses": [
                record.model_dump(mode="json")
                for record in records
            ],
            "events": [
                event.model_dump(mode="json")
                for event in events
            ],
        }
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f"{self.path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(self.path)

    @contextmanager
    def _locked_file(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _same_feature_graph(
    left: FeatureGraphExecutionStatusRecord,
    right: FeatureGraphExecutionStatusRecord,
) -> bool:
    return (
        left.graph_set_id == right.graph_set_id
        and left.feature_graph_id == right.feature_graph_id
    )


def _preserve_or_validate_source_event_lineage(
    existing: FeatureGraphExecutionStatusRecord,
    candidate: FeatureGraphExecutionStatusRecord,
) -> FeatureGraphExecutionStatusRecord:
    if not candidate.source_event_lineage and existing.source_event_lineage:
        return candidate.model_copy(
            update={"source_event_lineage": list(existing.source_event_lineage)}
        )
    if (
        candidate.source_event_lineage
        and existing.source_event_lineage
        and candidate.source_event_lineage != existing.source_event_lineage
    ):
        raise ValueError("feature graph status source_event_lineage cannot change")
    return candidate


def _is_same_claim_replay(
    current: FeatureGraphExecutionStatusRecord,
    *,
    worker_session_id: str,
    provider_session_binding_ref: str | None,
    updated_at: str,
    active_lane_ids: list[str] | None,
) -> bool:
    if current.status is not FeatureGraphExecutionStatus.RUNNING:
        return False
    if current.updated_at != updated_at:
        return False
    if current.active_worker_session_id != worker_session_id:
        return False
    if current.active_provider_session_binding_ref != provider_session_binding_ref:
        return False
    return active_lane_ids is None or list(active_lane_ids) == current.active_lane_ids


def _upsert_record(
    records: FeatureGraphExecutionStatusRecords,
    candidate: FeatureGraphExecutionStatusRecord,
) -> FeatureGraphExecutionStatusRecords:
    updated: FeatureGraphExecutionStatusRecords = []
    replaced = False
    for existing in records:
        _raise_if_status_id_replay_conflict(existing, candidate)
        if _same_feature_graph(existing, candidate):
            _raise_if_stale(existing, candidate)
            if not replaced:
                updated.append(candidate)
                replaced = True
            continue
        updated.append(existing)
    if not replaced:
        updated.append(candidate)
    return updated


def _feature_graph_pairs(
    graph_set: FeatureGraphSet,
) -> list[tuple[FeaturePlanFeature, LaneGraph]]:
    graphs_by_id = {graph.id: graph for graph in graph_set.graphs}
    pairs: list[tuple[FeaturePlanFeature, LaneGraph]] = []
    for feature in graph_set.feature_plan.features:
        graph = graphs_by_id.get(feature.graph_id)
        if graph is None:
            raise ValueError(f"feature graph missing for feature: {feature.feature_id}")
        pairs.append((feature, graph))
    return pairs


def _feature_dependencies_merged(
    feature: FeaturePlanFeature,
    records_by_feature_id: dict[str, FeatureGraphExecutionStatusRecord],
) -> bool:
    return all(
        records_by_feature_id.get(dependency) is not None
        and records_by_feature_id[dependency].status is FeatureGraphExecutionStatus.MERGED
        for dependency in feature.dependencies
    )


def _current_records_by_feature_id(
    records: FeatureGraphExecutionStatusRecords,
    *,
    graph_set: FeatureGraphSet,
    expected_graph_id_by_feature_id: dict[str, str],
) -> dict[str, FeatureGraphExecutionStatusRecord]:
    current: dict[str, FeatureGraphExecutionStatusRecord] = {}
    for record in records:
        if record.graph_set_version != graph_set.version:
            continue
        if expected_graph_id_by_feature_id.get(record.feature_id) != record.feature_graph_id:
            continue
        current[record.feature_id] = record
    return current


def _status_from_graph_set(
    graph_set: FeatureGraphSet,
    *,
    feature: FeaturePlanFeature,
    graph: LaneGraph,
    status: FeatureGraphExecutionStatus,
    updated_at: str,
    blueprint_proof_level: str | None = None,
    previous: FeatureGraphExecutionStatusRecord | None = None,
) -> FeatureGraphExecutionStatusRecord:
    root_lane_ids = [lane.feature_id for lane in graph.lanes if not lane.depends_on]
    graph_set_version = graph_set.version
    if graph_set_version is None:
        raise ValueError("feature graph status requires graph_set version")
    return FeatureGraphExecutionStatusRecord(
        status_id=_feature_graph_status_id(
            graph_set_id=graph_set.id,
            feature_graph_id=graph.id,
            status=status,
            updated_at=updated_at,
        ),
        conversation_id=graph_set.feature_plan.conversation_id,
        planning_run_id=previous.planning_run_id if previous is not None else None,
        graph_set_id=graph_set.id,
        graph_set_version=graph_set_version,
        feature_plan_id=graph_set.feature_plan.id,
        feature_plan_version=graph_set.feature_plan.version,
        feature_id=feature.feature_id,
        feature_graph_id=graph.id,
        blueprint_proof_level=(
            blueprint_proof_level
            if blueprint_proof_level is not None
            else previous.blueprint_proof_level if previous is not None else None
        ),
        source_event_lineage=(
            list(graph_set.source_event_lineage)
            or list(previous.source_event_lineage)
            if previous is not None
            else list(graph_set.source_event_lineage)
        ),
        status=status,
        ready_lane_ids=root_lane_ids if status is FeatureGraphExecutionStatus.READY else [],
        active_lane_ids=[],
        completed_lane_ids=(
            list(previous.completed_lane_ids)
            if previous is not None
            and status is not FeatureGraphExecutionStatus.READY
            else []
        ),
        blocked_lane_ids=[],
        projection_lane_ids=[],
        feature_lanes_projection_ref=(
            previous.feature_lanes_projection_ref if previous is not None else None
        ),
        provider_session_binding_degradations=(
            list(previous.provider_session_binding_degradations)
            if previous is not None
            else []
        ),
        updated_at=updated_at,
    )


def _feature_graph_status_id(
    *,
    graph_set_id: str,
    feature_graph_id: str,
    status: FeatureGraphExecutionStatus,
    updated_at: str,
) -> str:
    safe_updated_at = (
        updated_at.replace(":", "")
        .replace("-", "")
        .replace("+", "")
        .replace("Z", "z")
    )
    return f"fgs:{graph_set_id}:{feature_graph_id}:{status.value}:{safe_updated_at}"


def _initialized_event(
    record: FeatureGraphExecutionStatusRecord,
) -> FeatureGraphStatusEventRecord:
    event_id = (
        "fgse:initialized:"
        f"{record.graph_set_id}:{record.feature_graph_id}:{record.status_id}"
    )
    return FeatureGraphStatusEventRecord(
        event_id=event_id,
        event_type="feature_graph_status.initialized",
        graph_set_id=record.graph_set_id,
        graph_set_version=record.graph_set_version,
        feature_graph_id=record.feature_graph_id,
        feature_id=record.feature_id,
        from_status=None,
        to_status=record.status,
        from_status_id=None,
        status_id=record.status_id,
        updated_at=record.updated_at,
        idempotency_key=(
            "feature_graph_status.initialized:"
            f"{record.graph_set_id}:{record.feature_graph_id}:{record.status_id}"
        ),
    )


def _transition_event(
    existing: FeatureGraphExecutionStatusRecord,
    candidate: FeatureGraphExecutionStatusRecord,
) -> FeatureGraphStatusEventRecord:
    event_id = (
        "fgse:transition:"
        f"{candidate.graph_set_id}:{candidate.feature_graph_id}:"
        f"{existing.status_id}:{candidate.status_id}"
    )
    return FeatureGraphStatusEventRecord(
        event_id=event_id,
        event_type="feature_graph_status.transitioned",
        graph_set_id=candidate.graph_set_id,
        graph_set_version=candidate.graph_set_version,
        feature_graph_id=candidate.feature_graph_id,
        feature_id=candidate.feature_id,
        from_status=existing.status,
        to_status=candidate.status,
        from_status_id=existing.status_id,
        status_id=candidate.status_id,
        updated_at=candidate.updated_at,
        idempotency_key=(
            "feature_graph_status.transitioned:"
            f"{candidate.graph_set_id}:{candidate.feature_graph_id}:"
            f"{existing.status_id}:{candidate.status_id}"
        ),
    )


def _provider_binding_degradation_event(
    existing: FeatureGraphExecutionStatusRecord,
    candidate: FeatureGraphExecutionStatusRecord,
    *,
    evidence: ProviderSessionBindingDegradationEvidence,
) -> FeatureGraphStatusEventRecord:
    safe_binding_id = _safe_event_part(evidence.binding_id)
    event_id = (
        "fgse:provider-session-binding-degraded:"
        f"{candidate.graph_set_id}:{candidate.feature_graph_id}:"
        f"{existing.status_id}:{safe_binding_id}:{evidence.reason}"
    )
    return FeatureGraphStatusEventRecord(
        event_id=event_id,
        event_type="feature_graph_status.provider_session_binding_degraded",
        graph_set_id=candidate.graph_set_id,
        graph_set_version=candidate.graph_set_version,
        feature_graph_id=candidate.feature_graph_id,
        feature_id=candidate.feature_id,
        from_status=existing.status,
        to_status=candidate.status,
        from_status_id=existing.status_id,
        status_id=candidate.status_id,
        updated_at=candidate.updated_at,
        idempotency_key=(
            "feature_graph_status.provider_session_binding_degraded:"
            f"{candidate.graph_set_id}:{candidate.feature_graph_id}:"
            f"{evidence.binding_id}:{evidence.reason}"
        ),
    )


def _append_event(
    events: FeatureGraphStatusEvents,
    event: FeatureGraphStatusEventRecord | None,
) -> FeatureGraphStatusEvents:
    if event is None:
        return events
    for existing in events:
        if existing.idempotency_key == event.idempotency_key:
            if not _same_event(existing, event):
                raise ValueError(
                    "feature graph status event replay conflict: "
                    f"{event.idempotency_key}"
                )
            return events
    return [*events, event]


def _raise_if_event_replay_conflicts(
    events: FeatureGraphStatusEvents,
) -> None:
    by_event_id: dict[str, FeatureGraphStatusEventRecord] = {}
    by_idempotency_key: dict[str, FeatureGraphStatusEventRecord] = {}
    for event in events:
        existing_by_event_id = by_event_id.get(event.event_id)
        if existing_by_event_id is not None:
            raise ValueError(
                "feature graph status event replay conflict: "
                f"{event.event_id}"
            )
        existing_by_idempotency_key = by_idempotency_key.get(event.idempotency_key)
        if existing_by_idempotency_key is not None:
            raise ValueError(
                "feature graph status event replay conflict: "
                f"{event.idempotency_key}"
            )
        by_event_id[event.event_id] = event
        by_idempotency_key[event.idempotency_key] = event


def _raise_if_events_reference_missing_status_identity(
    events: FeatureGraphStatusEvents,
    records: FeatureGraphExecutionStatusRecords,
) -> None:
    status_identities = {
        (record.graph_set_id, record.feature_graph_id)
        for record in records
    }
    for event in events:
        identity = (event.graph_set_id, event.feature_graph_id)
        if identity not in status_identities:
            raise ValueError(
                "feature graph status event references missing status identity: "
                f"{event.graph_set_id}:{event.feature_graph_id}"
            )


def _raise_if_events_drift_from_status_records(
    events: FeatureGraphStatusEvents,
    records: FeatureGraphExecutionStatusRecords,
) -> None:
    records_by_identity = {
        (record.graph_set_id, record.feature_graph_id): record
        for record in records
    }
    for event in events:
        record = records_by_identity[(event.graph_set_id, event.feature_graph_id)]
        if event.feature_id != record.feature_id:
            raise ValueError(
                "feature graph status event metadata does not match status identity: "
                f"{event.graph_set_id}:{event.feature_graph_id}:feature_id"
            )
        if event.graph_set_version > record.graph_set_version:
            raise ValueError(
                "feature graph status event metadata does not match status identity: "
                f"{event.graph_set_id}:{event.feature_graph_id}:graph_set_version"
            )


def _raise_if_event_status_lineage_gaps(
    events: FeatureGraphStatusEvents,
    records: FeatureGraphExecutionStatusRecords,
) -> None:
    records_by_identity = {
        (record.graph_set_id, record.feature_graph_id): record
        for record in records
    }
    latest_status_id_by_identity_version: dict[tuple[str, str, int], str] = {}
    for event in events:
        identity = (event.graph_set_id, event.feature_graph_id)
        lineage_key = (*identity, event.graph_set_version)
        previous_status_id = latest_status_id_by_identity_version.get(lineage_key)
        if (
            event.from_status_id is not None
            and previous_status_id is not None
            and event.from_status_id != previous_status_id
        ):
            raise ValueError(
                "feature graph status event lineage does not match status record: "
                f"{event.graph_set_id}:{event.feature_graph_id}:{event.from_status_id}"
            )
        latest_status_id_by_identity_version[lineage_key] = event.status_id

        record = records_by_identity[identity]
        if (
            event.graph_set_version == record.graph_set_version
            and event.status_id == record.status_id
            and event.to_status is not record.status
        ):
            raise ValueError(
                "feature graph status event lineage does not match status record: "
                f"{event.graph_set_id}:{event.feature_graph_id}:{event.status_id}"
            )



def _raise_if_duplicate_feature_graph_status_identities(
    records: FeatureGraphExecutionStatusRecords,
) -> None:
    seen: set[tuple[str, str]] = set()
    for record in records:
        identity = (record.graph_set_id, record.feature_graph_id)
        if identity in seen:
            raise ValueError(
                "duplicate feature graph status identity: "
                f"{record.graph_set_id}:{record.feature_graph_id}"
            )
        seen.add(identity)


def _raise_if_status_record_replay_conflicts(
    records: FeatureGraphExecutionStatusRecords,
) -> None:
    by_status_id: dict[str, FeatureGraphExecutionStatusRecord] = {}
    for record in records:
        existing = by_status_id.get(record.status_id)
        if existing is not None and not _same_record(existing, record):
            raise ValueError(f"feature graph status replay conflict: {record.status_id}")
        by_status_id[record.status_id] = record


def _raise_if_stale(
    existing: FeatureGraphExecutionStatusRecord,
    candidate: FeatureGraphExecutionStatusRecord,
) -> None:
    if candidate.graph_set_version < existing.graph_set_version:
        raise ValueError(
            "stale feature graph status update: "
            f"graph_set_version {candidate.graph_set_version} < {existing.graph_set_version}"
        )
    existing_updated_at = _parse_updated_at(existing.updated_at)
    candidate_updated_at = _parse_updated_at(candidate.updated_at)
    if candidate_updated_at < existing_updated_at:
        raise ValueError(
            "stale feature graph status update: "
            f"updated_at {candidate.updated_at} < {existing.updated_at}"
        )


def _raise_if_conflicting_replay(
    existing: FeatureGraphExecutionStatusRecord,
    candidate: FeatureGraphExecutionStatusRecord,
) -> None:
    if candidate.status is existing.status:
        raise ValueError(
            "same-status transition must be an exact replay: "
            f"{candidate.graph_set_id}:{candidate.feature_graph_id}"
        )


def _raise_if_provider_binding_degradation_evidence_changed(
    existing: FeatureGraphExecutionStatusRecord,
    candidate: FeatureGraphExecutionStatusRecord,
) -> None:
    if (
        existing.provider_session_binding_degradations
        != candidate.provider_session_binding_degradations
    ):
        raise ValueError(
            "provider session binding degradation evidence cannot be dropped "
            "or changed by status transition"
        )


def _raise_if_provider_binding_degradation_evidence_upsert_changed(
    existing: FeatureGraphExecutionStatusRecord,
    candidate: FeatureGraphExecutionStatusRecord,
) -> None:
    if (
        existing.provider_session_binding_degradations
        == candidate.provider_session_binding_degradations
    ):
        return
    if (
        existing.provider_session_binding_degradations
        and not candidate.provider_session_binding_degradations
    ):
        raise ValueError(
            "provider session binding degradation evidence cannot be dropped"
        )
    raise ValueError(
        "provider session binding degradation evidence cannot be changed by upsert"
    )


def _raise_if_status_id_replay_conflict(
    existing: FeatureGraphExecutionStatusRecord,
    candidate: FeatureGraphExecutionStatusRecord,
) -> None:
    if existing.status_id == candidate.status_id and not _same_record(existing, candidate):
        raise ValueError(f"feature graph status replay conflict: {candidate.status_id}")


def _raise_if_illegal_transition(
    source: FeatureGraphExecutionStatus,
    target: FeatureGraphExecutionStatus,
) -> None:
    if target is source:
        return
    if target not in _ALLOWED_STATUS_TRANSITIONS[source]:
        raise ValueError(
            "cannot transition feature graph status "
            f"from {source.value} to {target.value}"
        )


def _matching_provider_binding_degradation(
    record: FeatureGraphExecutionStatusRecord,
    evidence: ProviderSessionBindingDegradationEvidence,
) -> ProviderSessionBindingDegradationEvidence | None:
    for existing in record.provider_session_binding_degradations:
        if existing.binding_id == evidence.binding_id and existing.reason == evidence.reason:
            return existing
    return None


def _provider_binding_degradation_status_id(
    record: FeatureGraphExecutionStatusRecord,
    *,
    evidence: ProviderSessionBindingDegradationEvidence,
    updated_at: str,
) -> str:
    return (
        f"fgs:{record.graph_set_id}:{record.feature_graph_id}:"
        "provider-session-binding-degraded:"
        f"{_safe_event_part(evidence.binding_id)}:"
        f"{evidence.reason}:{_safe_timestamp(updated_at)}"
    )


def _safe_event_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "value"


def _safe_timestamp(value: str) -> str:
    return (
        value.replace(":", "")
        .replace("-", "")
        .replace("+", "")
        .replace("Z", "z")
    )


def _same_record(
    left: FeatureGraphExecutionStatusRecord,
    right: FeatureGraphExecutionStatusRecord,
) -> bool:
    return left.model_dump(mode="json") == right.model_dump(mode="json")


def _same_event(
    left: FeatureGraphStatusEventRecord,
    right: FeatureGraphStatusEventRecord,
) -> bool:
    return left.model_dump(mode="json") == right.model_dump(mode="json")


def _parse_updated_at(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"updated_at must be ISO-8601: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"updated_at must include timezone offset: {value}")
    return parsed.astimezone(UTC)
