from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from xmuse_core.platform.live_gate_status_capture import CommandRunner, capture_live_gate_status
from xmuse_core.platform.projection.allowlist import stamp_mutation_audit
from xmuse_core.platform.release_evidence_pack import capture_release_evidence_pack
from xmuse_core.platform.release_readiness import evaluate_release_readiness
from xmuse_core.platform.release_readiness_capture import load_release_gate_artifacts
from xmuse_core.platform.state_machine import (
    InvalidTransitionError,
    LaneStateMachine,
)
from xmuse_core.platform.state_validation import StateValidationError
from xmuse_core.providers.god_cli_registration_store import GodCliRegistrationStore
from xmuse_core.providers.god_cli_registry import (
    PEER_GOD_SPEECH_ACTS,
    GodCliCapability,
    GodCliRegistration,
    GodCliRegistry,
)
from xmuse_core.providers.god_cli_registry import (
    ProofLevel as GodCliProofLevel,
)
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionStore

ActionStatus = Literal["ok", "denied", "blocked", "manual_gap"]
ProofLevel = Literal["contract_proof", "manual_gap"]

_RELEASE_EVIDENCE_EXPORT_ACTIONS = {
    "export_natural_deliberation_transcript",
    "export_natural_transcript",
    "natural_deliberation_transcript_export",
    "natural_transcript_export",
    "export_real_provider_runtime_soak",
    "export_provider_runtime_soak",
    "real_provider_runtime_soak_export",
    "provider_runtime_soak_export",
    "export_memoryos_live_trace",
    "capture_memoryos_live_trace",
    "memoryos_live_trace_export",
    "memoryos_live_trace_capture",
    "export_github_server_truth",
    "export_github_truth",
    "capture_github_server_truth",
    "github_server_truth_export",
    "github_truth_export",
    "export_god_runtime_continuity",
    "export_selected_god_runtime",
    "export_god_runtime",
    "god_runtime_continuity_export",
    "selected_god_runtime_export",
}
_RELEASE_EVIDENCE_CANDIDATE_ACTIONS = {
    "inspect_release_evidence_candidates",
    "release_evidence_candidates",
    "release_candidates",
}
_RELEASE_EVIDENCE_ATTEMPT_ACTIONS = {
    "attempt_release_evidence",
    "release_evidence_attempt",
    "release_attempt",
}


class OperatorActionCapability(StrEnum):
    REGISTER_GOD_CLI = "register_god_cli"
    SELECT_GOD_CLI = "select_god_cli"
    WORKFLOW_WRITE = "workflow_write"
    RELEASE_GATE = "release_gate"
    CHAT_FREEZE_BLUEPRINT = "chat_freeze_blueprint"


@dataclass(frozen=True)
class OperatorActionRequest:
    action: str
    actor_id: str
    capabilities: tuple[OperatorActionCapability | str, ...]
    idempotency_key: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "tui"


@dataclass(frozen=True)
class OperatorActionResult:
    action: str
    status: ActionStatus
    proof_level: ProofLevel
    fact_state: str
    actor_id: str
    audit_id: str | None
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp_utc: str = field(default_factory=lambda: _utcnow())

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


class OperatorActionBlockedError(Exception):
    def __init__(
        self,
        summary: str,
        *,
        payload: dict[str, Any] | None = None,
        proof_level: ProofLevel = "contract_proof",
        fact_state: str = "blocked",
    ) -> None:
        super().__init__(summary)
        self.summary = summary
        self.payload = payload or {}
        self.proof_level: ProofLevel = proof_level
        self.fact_state = fact_state


class OperatorActionService:
    def __init__(
        self,
        *,
        god_cli_registry: GodCliRegistry,
        audit_dir: Path,
        registration_store: GodCliRegistrationStore | None = None,
        selection_store: GodCliSelectionStore | None = None,
        lane_state_machine: LaneStateMachine | None = None,
        release_readiness_dir: Path | None = None,
        live_gate_env: Mapping[str, str] | None = None,
        live_gate_command_runner: CommandRunner | None = None,
        blueprint_freeze_handler: Callable[[OperatorActionRequest], dict[str, Any]] | None = None,
        release_evidence_export_handler: Callable[
            [OperatorActionRequest], dict[str, Any]
        ]
        | None = None,
        release_evidence_candidate_handler: Callable[
            [OperatorActionRequest], dict[str, Any]
        ]
        | None = None,
        release_evidence_attempt_handler: Callable[[OperatorActionRequest], dict[str, Any]]
        | None = None,
    ) -> None:
        self._god_cli_registry = god_cli_registry
        self._audit_dir = audit_dir
        self._registration_store = registration_store
        self._selection_store = selection_store
        self._lane_state_machine = lane_state_machine
        self._release_readiness_dir = release_readiness_dir or (
            audit_dir.parent / "release_readiness"
        )
        self._live_gate_env = live_gate_env
        self._live_gate_command_runner = live_gate_command_runner
        self._blueprint_freeze_handler = blueprint_freeze_handler
        self._release_evidence_export_handler = release_evidence_export_handler
        self._release_evidence_candidate_handler = release_evidence_candidate_handler
        self._release_evidence_attempt_handler = release_evidence_attempt_handler

    def handle(self, request: OperatorActionRequest) -> OperatorActionResult:
        action = request.action.strip().lower()
        audit_id = f"operator-action:{uuid4().hex}"
        if action == "register_god_cli":
            result = self._handle_register_god_cli(request, audit_id=audit_id)
        elif action == "select_god_cli":
            result = self._handle_select_god_cli(request, audit_id=audit_id)
        elif action in {
            "capture_release_evidence_pack",
            "release_evidence_pack",
            "capture_release_gate",
        }:
            result = self._handle_capture_release_evidence_pack(request, audit_id=audit_id)
        elif action in {
            "refresh_live_gate_status",
            "capture_live_gate_status",
            "live_gate_status",
        }:
            result = self._handle_refresh_live_gate_status(request, audit_id=audit_id)
        elif action in _RELEASE_EVIDENCE_EXPORT_ACTIONS:
            result = self._handle_export_release_evidence(request, audit_id=audit_id)
        elif action in _RELEASE_EVIDENCE_CANDIDATE_ACTIONS:
            result = self._handle_inspect_release_evidence_candidates(
                request,
                audit_id=audit_id,
            )
        elif action in _RELEASE_EVIDENCE_ATTEMPT_ACTIONS:
            result = self._handle_attempt_release_evidence(
                request,
                audit_id=audit_id,
            )
        elif action in {"retry_lane", "lane_retry"}:
            result = self._handle_retry_lane(request, audit_id=audit_id)
        elif action in {"abort_lane", "lane_abort"}:
            result = self._handle_abort_lane(request, audit_id=audit_id)
        elif action in {"freeze_blueprint", "request_blueprint_freeze", "blueprint_freeze"}:
            result = self._handle_freeze_blueprint(request, audit_id=audit_id)
        else:
            result = OperatorActionResult(
                action=action or "unknown",
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=f"unknown operator action: {request.action}",
            )
        return self._audit(request, result, audit_id=audit_id)

    def _handle_register_god_cli(
        self,
        request: OperatorActionRequest,
        *,
        audit_id: str,
    ) -> OperatorActionResult:
        action = "register_god_cli"
        missing = self._missing_capability(
            request,
            OperatorActionCapability.REGISTER_GOD_CLI,
        )
        if missing is not None:
            return OperatorActionResult(
                action=action,
                status="denied",
                proof_level="contract_proof",
                fact_state="denied",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=missing,
            )
        if self._registration_store is None:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary="register_god_cli requires a durable registration store",
            )
        try:
            registration = _registration_from_payload(request.payload)
            self._effective_god_cli_registry().get(registration.cli_id)
        except KeyError:
            pass
        except ValueError as exc:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="contract_proof",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=str(exc),
            )
        else:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="contract_proof",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=f"GOD CLI already registered: {registration.cli_id}",
            )
        record = self._registration_store.record_registration(
            registration=registration,
            registered_by=request.actor_id,
            audit_id=audit_id,
            idempotency_key=request.idempotency_key,
        )
        return OperatorActionResult(
            action=action,
            status="ok",
            proof_level="contract_proof",
            fact_state="god_cli_registered",
            actor_id=request.actor_id,
            audit_id=audit_id,
            summary=f"Registered GOD CLI {registration.cli_id}.",
            payload={
                "registration": registration.model_dump(),
                "durable_state_ref": f"god_cli_registration:{registration.cli_id}",
                "record": record.model_dump(),
            },
        )

    def _handle_select_god_cli(
        self,
        request: OperatorActionRequest,
        *,
        audit_id: str,
    ) -> OperatorActionResult:
        missing = self._missing_capability(
            request,
            OperatorActionCapability.SELECT_GOD_CLI,
        )
        if missing is not None:
            return OperatorActionResult(
                action="select_god_cli",
                status="denied",
                proof_level="contract_proof",
                fact_state="denied",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=missing,
            )
        cli_id = _text(request.payload.get("cli_id"))
        conversation_id = _text(request.payload.get("conversation_id"))
        if cli_id is None:
            return OperatorActionResult(
                action="select_god_cli",
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary="select_god_cli requires payload.cli_id",
                payload={"selection_allowed": False},
            )
        if self._selection_store is not None and conversation_id is None:
            return OperatorActionResult(
                action="select_god_cli",
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary="select_god_cli requires payload.conversation_id for durable selection",
                payload={"selection_allowed": False},
            )
        selection = self._effective_god_cli_registry().select_for_god(cli_id)
        if not selection.allowed:
            return OperatorActionResult(
                action="select_god_cli",
                status="blocked",
                proof_level="contract_proof",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=selection.reason,
                payload={
                    "selection_allowed": False,
                    "selection": selection.model_dump(),
                },
            )
        selection_payload = {
            "cli_id": cli_id,
            "conversation_id": conversation_id,
            "source_authority": "operator_action_contract",
            "registration": selection.registration.model_dump()
            if selection.registration is not None
            else None,
        }
        if self._selection_store is not None and conversation_id is not None:
            record = self._selection_store.record_selection(
                conversation_id=conversation_id,
                cli_id=cli_id,
                selected_by=request.actor_id,
                audit_id=audit_id,
                idempotency_key=request.idempotency_key,
            )
            selection_payload["durable_state_ref"] = f"god_cli_selection:{conversation_id}"
            selection_payload["record"] = record.model_dump()
        return OperatorActionResult(
            action="select_god_cli",
            status="ok",
            proof_level="contract_proof",
            fact_state="god_cli_selected",
            actor_id=request.actor_id,
            audit_id=audit_id,
            summary=f"Selected GOD CLI {cli_id}.",
            payload={"selection": selection_payload},
        )

    def _handle_retry_lane(
        self,
        request: OperatorActionRequest,
        *,
        audit_id: str,
    ) -> OperatorActionResult:
        action = "retry_lane"
        missing = self._missing_capability(
            request,
            OperatorActionCapability.WORKFLOW_WRITE,
        )
        if missing is not None:
            return OperatorActionResult(
                action=action,
                status="denied",
                proof_level="contract_proof",
                fact_state="denied",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=missing,
            )
        if self._lane_state_machine is None:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary="retry_lane requires a lane state machine",
            )
        lane_id = _text(request.payload.get("lane_id"))
        current_status = _text(request.payload.get("current_status"))
        if lane_id is None:
            return _blocked_missing_lane_field(
                action=action,
                actor_id=request.actor_id,
                audit_id=audit_id,
                field_name="payload.lane_id",
            )
        if current_status is None:
            return _blocked_missing_lane_field(
                action=action,
                actor_id=request.actor_id,
                audit_id=audit_id,
                field_name="payload.current_status",
            )
        reason = _text(request.payload.get("reason")) or "operator requested lane retry"
        metadata = stamp_mutation_audit(
            {},
            audit={
                "actor": request.actor_id,
                "reason": reason,
                "request_id": request.idempotency_key,
            },
            tool_name=action,
        )
        try:
            if current_status == "failed":
                lane = self._lane_state_machine.controlled_terminal_update(
                    lane_id,
                    "reworking",
                    metadata=metadata,
                    guard=_status_guard(current_status, action=action),
                )
            else:
                candidate_lane = self._lane_state_machine.transition_if_metadata(
                    lane_id,
                    "reworking",
                    expected_metadata={"status": current_status},
                    metadata=metadata,
                )
                if candidate_lane is None:
                    raise ValueError(
                        f"state guard mismatch for {action}: "
                        f"expected status {current_status}"
                    )
                lane = candidate_lane
        except (InvalidTransitionError, StateValidationError, KeyError, ValueError) as exc:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="contract_proof",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=str(exc),
            )
        return OperatorActionResult(
            action=action,
            status="ok",
            proof_level="contract_proof",
            fact_state="lane_retry_requested",
            actor_id=request.actor_id,
            audit_id=audit_id,
            summary=f"Retry requested for lane {lane_id}.",
            payload={
                "lane": lane,
                "source_authority": "operator_action_contract",
                "durable_state_ref": f"lane_state:{lane_id}",
            },
        )

    def _handle_abort_lane(
        self,
        request: OperatorActionRequest,
        *,
        audit_id: str,
    ) -> OperatorActionResult:
        action = "abort_lane"
        missing = self._missing_capability(
            request,
            OperatorActionCapability.WORKFLOW_WRITE,
        )
        if missing is not None:
            return OperatorActionResult(
                action=action,
                status="denied",
                proof_level="contract_proof",
                fact_state="denied",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=missing,
            )
        if self._lane_state_machine is None:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary="abort_lane requires a lane state machine",
            )
        lane_id = _text(request.payload.get("lane_id"))
        current_status = _text(request.payload.get("current_status"))
        if lane_id is None:
            return _blocked_missing_lane_field(
                action=action,
                actor_id=request.actor_id,
                audit_id=audit_id,
                field_name="payload.lane_id",
            )
        if current_status is None:
            return _blocked_missing_lane_field(
                action=action,
                actor_id=request.actor_id,
                audit_id=audit_id,
                field_name="payload.current_status",
            )
        reason = _text(request.payload.get("reason")) or "operator aborted lane"
        metadata = stamp_mutation_audit(
            {"failure_reason": reason},
            audit={
                "actor": request.actor_id,
                "reason": reason,
                "request_id": request.idempotency_key,
            },
            tool_name=action,
        )
        try:
            lane = self._lane_state_machine.transition_if_metadata(
                lane_id,
                "failed",
                expected_metadata={"status": current_status},
                metadata=metadata,
            )
            if lane is None:
                raise ValueError(
                    f"state guard mismatch for {action}: "
                    f"expected status {current_status}"
                )
        except (InvalidTransitionError, StateValidationError, KeyError, ValueError) as exc:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="contract_proof",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=str(exc),
            )
        return OperatorActionResult(
            action=action,
            status="ok",
            proof_level="contract_proof",
            fact_state="lane_aborted",
            actor_id=request.actor_id,
            audit_id=audit_id,
            summary=f"Aborted lane {lane_id}.",
            payload={
                "lane": lane,
                "source_authority": "operator_action_contract",
                "durable_state_ref": f"lane_state:{lane_id}",
            },
        )

    def _handle_freeze_blueprint(
        self,
        request: OperatorActionRequest,
        *,
        audit_id: str,
    ) -> OperatorActionResult:
        action = "freeze_blueprint"
        missing = self._missing_capability(
            request,
            OperatorActionCapability.CHAT_FREEZE_BLUEPRINT,
        )
        if missing is not None:
            return OperatorActionResult(
                action=action,
                status="denied",
                proof_level="contract_proof",
                fact_state="denied",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=missing,
            )
        if self._blueprint_freeze_handler is None:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary="freeze_blueprint requires a blueprint freeze handler",
            )
        try:
            freeze = self._blueprint_freeze_handler(request)
        except OperatorActionBlockedError as exc:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level=exc.proof_level,
                fact_state=exc.fact_state,
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=exc.summary,
                payload=exc.payload,
            )
        except Exception as exc:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=f"blueprint freeze failed: {exc}",
            )
        blueprint = freeze.get("blueprint") if isinstance(freeze, dict) else None
        blueprint_id = (
            _text(blueprint.get("blueprint_id"))
            if isinstance(blueprint, dict)
            else None
        )
        summary = "Frozen mission blueprint."
        if blueprint_id:
            summary = f"Frozen mission blueprint {blueprint_id}."
        return OperatorActionResult(
            action=action,
            status="ok",
            proof_level="contract_proof",
            fact_state="blueprint_frozen",
            actor_id=request.actor_id,
            audit_id=audit_id,
            summary=summary,
            payload={
                "freeze": freeze,
                "source_authority": "operator_action_contract",
            },
        )

    def _handle_inspect_release_evidence_candidates(
        self,
        request: OperatorActionRequest,
        *,
        audit_id: str,
    ) -> OperatorActionResult:
        action = request.action.strip().lower().replace("-", "_")
        missing = self._missing_capability(
            request,
            OperatorActionCapability.RELEASE_GATE,
        )
        if missing is not None:
            return OperatorActionResult(
                action=action,
                status="denied",
                proof_level="contract_proof",
                fact_state="denied",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=missing,
            )
        if self._release_evidence_candidate_handler is None:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=f"{action} requires a release evidence candidate handler",
            )
        try:
            candidates = self._release_evidence_candidate_handler(request)
        except OperatorActionBlockedError as exc:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level=exc.proof_level,
                fact_state=exc.fact_state,
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=exc.summary,
                payload=exc.payload,
            )
        except Exception as exc:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=f"release evidence candidate inspection failed: {exc}",
            )
        return OperatorActionResult(
            action=action,
            status="ok",
            proof_level="contract_proof",
            fact_state="release_evidence_candidates_inspected",
            actor_id=request.actor_id,
            audit_id=audit_id,
            summary="Inspected release evidence candidates.",
            payload={
                "candidates": candidates,
                "source_authority": "operator_action_contract",
            },
        )

    def _handle_export_release_evidence(
        self,
        request: OperatorActionRequest,
        *,
        audit_id: str,
    ) -> OperatorActionResult:
        action = request.action.strip().lower().replace("-", "_")
        missing = self._missing_capability(
            request,
            OperatorActionCapability.RELEASE_GATE,
        )
        if missing is not None:
            return OperatorActionResult(
                action=action,
                status="denied",
                proof_level="contract_proof",
                fact_state="denied",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=missing,
            )
        if self._release_evidence_export_handler is None:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=f"{action} requires a release evidence export handler",
            )
        try:
            exported = self._release_evidence_export_handler(request)
        except OperatorActionBlockedError as exc:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level=exc.proof_level,
                fact_state=exc.fact_state,
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=exc.summary,
                payload=exc.payload,
            )
        except Exception as exc:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=f"release evidence export failed: {exc}",
            )
        kind = _text(exported.get("kind")) or action
        artifact = exported.get("artifact")
        gate = exported.get("gate")
        artifact_proof = (
            _text(artifact.get("proof_level")) if isinstance(artifact, dict) else None
        )
        gate_status = _text(gate.get("status")) if isinstance(gate, dict) else None
        gate_proof = _text(gate.get("proof_level")) if isinstance(gate, dict) else None
        detail = []
        if artifact_proof:
            detail.append(f"artifact_proof={artifact_proof}")
        if gate_status:
            suffix = f"/{gate_proof}" if gate_proof else ""
            detail.append(f"gate={gate_status}{suffix}")
        summary = f"Exported {kind} release evidence"
        if detail:
            summary = f"{summary} {' '.join(detail)}."
        else:
            summary = f"{summary}."
        return OperatorActionResult(
            action=action,
            status="ok",
            proof_level="contract_proof",
            fact_state="release_evidence_exported",
            actor_id=request.actor_id,
            audit_id=audit_id,
            summary=summary,
            payload={
                "export": exported,
                "source_authority": "operator_action_contract",
            },
        )

    def _handle_attempt_release_evidence(
        self,
        request: OperatorActionRequest,
        *,
        audit_id: str,
    ) -> OperatorActionResult:
        action = request.action.strip().lower().replace("-", "_")
        missing = self._missing_capability(
            request,
            OperatorActionCapability.RELEASE_GATE,
        )
        if missing is not None:
            return OperatorActionResult(
                action=action,
                status="denied",
                proof_level="contract_proof",
                fact_state="denied",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=missing,
            )
        if self._release_evidence_attempt_handler is None:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=f"{action} requires a release evidence attempt handler",
            )
        try:
            attempt = self._release_evidence_attempt_handler(request)
        except OperatorActionBlockedError as exc:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level=exc.proof_level,
                fact_state=exc.fact_state,
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=exc.summary,
                payload=exc.payload,
            )
        except Exception as exc:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=f"release evidence attempt failed: {exc}",
            )
        return OperatorActionResult(
            action=action,
            status="ok",
            proof_level="contract_proof",
            fact_state="release_evidence_attempted",
            actor_id=request.actor_id,
            audit_id=audit_id,
            summary="Attempted configured release evidence.",
            payload={
                "attempt": attempt,
                "source_authority": "operator_action_contract",
            },
        )

    def _handle_capture_release_evidence_pack(
        self,
        request: OperatorActionRequest,
        *,
        audit_id: str,
    ) -> OperatorActionResult:
        action = "capture_release_evidence_pack"
        missing = self._missing_capability(
            request,
            OperatorActionCapability.RELEASE_GATE,
        )
        if missing is not None:
            return OperatorActionResult(
                action=action,
                status="denied",
                proof_level="contract_proof",
                fact_state="denied",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=missing,
            )
        try:
            artifacts_dir = self._release_path(
                request.payload.get("artifacts_dir"),
                default=self._release_readiness_dir / "artifacts",
            )
            output_path = self._release_path(
                request.payload.get("output_path"),
                default=self._release_readiness_dir / "evidence-pack.json",
            )
            readiness_output = self._release_optional_path(
                request.payload.get("readiness_output")
            )
            audit_output = self._release_optional_path(request.payload.get("audit_output"))
            github_server_truth = self._release_optional_path(
                request.payload.get("github_server_truth")
            )
            internal_review_artifact = self._release_optional_path(
                request.payload.get("internal_review_artifact")
            )
            production_baseline = self._release_optional_path(
                request.payload.get("production_baseline")
            )
            goal_stage_result = self._release_optional_path(
                request.payload.get("goal_stage_result")
            )
            god_room_participants = self._release_optional_path(
                request.payload.get("god_room_participants")
            )
            god_room_events = self._release_optional_path(
                request.payload.get("god_room_events")
            )
            god_room_blueprint_freeze = self._release_optional_path(
                request.payload.get("god_room_blueprint_freeze")
            )
            god_room_lane_dag = self._release_optional_path(
                request.payload.get("god_room_lane_dag")
            )
            god_room_memory_trace = self._release_optional_path(
                request.payload.get("god_room_memory_trace")
            )
            god_room_tui_projection = self._release_optional_path(
                request.payload.get("god_room_tui_projection")
            )
            god_room_speaker_attempt = self._release_optional_path(
                request.payload.get("god_room_speaker_attempt")
            )
            god_room_runtime_closure_evidence_output = self._release_optional_path(
                request.payload.get("god_room_runtime_closure_evidence_output")
            )
        except ValueError as exc:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="contract_proof",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=str(exc),
            )
        try:
            pack = capture_release_evidence_pack(
                artifacts_dir=artifacts_dir,
                output_path=output_path,
                readiness_output=readiness_output,
                audit_output=audit_output,
                github_server_truth=github_server_truth,
                github_base_branch=_text(request.payload.get("github_base_branch"))
                or "main",
                github_expected_head_sha=_text(
                    request.payload.get("github_expected_head_sha")
                ),
                internal_review_artifact=internal_review_artifact,
                internal_review_expected_head_sha=_text(
                    request.payload.get("internal_review_expected_head_sha")
                ),
                production_baseline=production_baseline,
                goal_stage_results=(
                    (goal_stage_result,) if goal_stage_result is not None else ()
                ),
                god_room_participants=god_room_participants,
                god_room_events=god_room_events,
                god_room_blueprint_freeze=god_room_blueprint_freeze,
                god_room_lane_dag=god_room_lane_dag,
                god_room_memory_trace=god_room_memory_trace,
                god_room_tui_projection=god_room_tui_projection,
                god_room_speaker_attempt=god_room_speaker_attempt,
                god_room_runtime_closure_evidence_output=(
                    god_room_runtime_closure_evidence_output
                ),
            )
        except Exception as exc:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=f"release evidence pack capture failed: {exc}",
            )
        return OperatorActionResult(
            action=action,
            status="ok",
            proof_level="contract_proof",
            fact_state="release_evidence_pack_captured",
            actor_id=request.actor_id,
            audit_id=audit_id,
            summary=(
                "Captured release evidence pack: "
                f"decision={pack['decision']} "
                f"blockers={pack['blocker_count']} "
                f"findings={pack['finding_count']}."
            ),
            payload={
                "evidence_pack": pack,
                "artifacts_dir": str(artifacts_dir),
                "output_path": str(output_path),
                "readiness_output": str(
                    readiness_output
                    or Path(pack["source_reports"]["release_readiness"])
                ),
                "audit_output": str(
                    audit_output
                    or Path(pack["source_reports"]["proof_contamination_audit"])
                ),
            },
        )

    def _handle_refresh_live_gate_status(
        self,
        request: OperatorActionRequest,
        *,
        audit_id: str,
    ) -> OperatorActionResult:
        action = "refresh_live_gate_status"
        missing = self._missing_capability(
            request,
            OperatorActionCapability.RELEASE_GATE,
        )
        if missing is not None:
            return OperatorActionResult(
                action=action,
                status="denied",
                proof_level="contract_proof",
                fact_state="denied",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=missing,
            )
        try:
            output_dir = self._release_path(
                request.payload.get("output_dir"),
                default=self._release_readiness_dir / "artifacts" / "live_gate_status",
            )
        except ValueError as exc:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="contract_proof",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=str(exc),
            )
        try:
            summary = capture_live_gate_status(
                output_dir=output_dir,
                env=self._live_gate_env,
                command_runner=self._live_gate_command_runner,
            )
            gate_summary = _live_gate_refresh_summary(output_dir)
        except Exception as exc:
            return OperatorActionResult(
                action=action,
                status="blocked",
                proof_level="manual_gap",
                fact_state="blocked",
                actor_id=request.actor_id,
                audit_id=audit_id,
                summary=f"live gate status refresh failed: {exc}",
            )
        return OperatorActionResult(
            action=action,
            status="ok",
            proof_level="contract_proof",
            fact_state="live_gate_status_refreshed",
            actor_id=request.actor_id,
            audit_id=audit_id,
            summary=(
                "Refreshed live gate status artifacts: "
                f"artifact_count={summary['artifact_count']}."
            ),
            payload={
                "live_gate_status": summary,
                "output_dir": str(output_dir),
                "artifact_count": summary["artifact_count"],
                **gate_summary,
            },
        )

    def _missing_capability(
        self,
        request: OperatorActionRequest,
        capability: OperatorActionCapability,
    ) -> str | None:
        granted = {
            item.value if isinstance(item, OperatorActionCapability) else str(item)
            for item in request.capabilities
        }
        if capability.value in granted:
            return None
        return f"missing capability {capability.value}"

    def _effective_god_cli_registry(self) -> GodCliRegistry:
        if self._registration_store is None:
            return self._god_cli_registry
        return GodCliRegistry(
            [
                *self._god_cli_registry.list_registrations(),
                *self._registration_store.list_registrations(),
            ]
        )

    def _release_optional_path(self, value: Any) -> Path | None:
        text = _text(value)
        if text is None:
            return None
        return self._release_path(text, default=self._release_readiness_dir)

    def _release_path(self, value: Any, *, default: Path) -> Path:
        text = _text(value)
        path = default if text is None else Path(text)
        if not path.is_absolute():
            path = self._release_readiness_dir / path
        release_root = self._release_readiness_dir.resolve(strict=False)
        resolved = path.resolve(strict=False)
        if resolved != release_root and release_root not in resolved.parents:
            raise ValueError(
                f"release evidence path {path} must stay under release readiness root "
                f"{self._release_readiness_dir}"
            )
        return resolved

    def _audit(
        self,
        request: OperatorActionRequest,
        result: OperatorActionResult,
        *,
        audit_id: str,
    ) -> OperatorActionResult:
        audited = OperatorActionResult(
            action=result.action,
            status=result.status,
            proof_level=result.proof_level,
            fact_state=result.fact_state,
            actor_id=result.actor_id,
            audit_id=audit_id,
            summary=result.summary,
            payload=result.payload,
            timestamp_utc=result.timestamp_utc,
        )
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        audit_path = self._audit_dir / "operator-actions.jsonl"
        audit_row = {
            "schema_version": "xmuse.operator_action_audit.v1",
            "audit_id": audit_id,
            "action": audited.action,
            "status": audited.status,
            "fact_state": audited.fact_state,
            "actor_id": request.actor_id,
            "source": request.source,
            "idempotency_key": request.idempotency_key,
            "capabilities": [
                item.value if isinstance(item, OperatorActionCapability) else str(item)
                for item in request.capabilities
            ],
            "payload": request.payload,
            "result_payload": audited.payload,
            "timestamp_utc": _utcnow(),
        }
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(audit_row, ensure_ascii=False) + "\n")
        return audited


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _blocked_missing_lane_field(
    *,
    action: str,
    actor_id: str,
    audit_id: str,
    field_name: str,
) -> OperatorActionResult:
    return OperatorActionResult(
        action=action,
        status="blocked",
        proof_level="manual_gap",
        fact_state="blocked",
        actor_id=actor_id,
        audit_id=audit_id,
        summary=f"{action} requires {field_name}",
    )


def _status_guard(expected_status: str, *, action: str):
    def guard(lane: dict[str, Any], _data: dict[str, Any]) -> None:
        actual = str(lane.get("status") or "pending")
        if actual != expected_status:
            raise ValueError(
                f"state guard mismatch for {action}: expected status {expected_status}"
            )

    return guard


def _live_gate_refresh_summary(output_dir: Path) -> dict[str, Any]:
    gates = load_release_gate_artifacts(output_dir)
    readiness = evaluate_release_readiness(gates)
    gate_statuses = [
        {
            "gate_id": gate.gate_id,
            "kind": gate.kind.value,
            "configured": gate.configured,
            "status": gate.status,
            "proof_level": gate.proof_level,
            "summary": gate.summary,
        }
        for gate in gates
    ]
    status_by_gate = {gate["gate_id"]: gate for gate in gate_statuses}
    blockers = []
    for blocker in readiness.blockers:
        gate_status = status_by_gate.get(str(blocker.get("gate_id")))
        enriched = dict(blocker)
        if gate_status is not None:
            enriched["status"] = gate_status["status"]
            enriched["proof_level"] = gate_status["proof_level"]
        blockers.append(enriched)
    return {
        "gate_statuses": gate_statuses,
        "blockers": blockers,
        "release_decision": readiness.decision,
    }


def _registration_from_payload(payload: dict[str, Any]) -> GodCliRegistration:
    cli_id = _required_text(payload.get("cli_id"), "payload.cli_id")
    capabilities = tuple(
        GodCliCapability(item)
        for item in _string_values(payload.get("capabilities"))
    )
    allowed_speech_acts = tuple(_string_values(payload.get("allowed_speech_acts")))
    if not allowed_speech_acts and GodCliCapability.PEER_GOD in capabilities:
        allowed_speech_acts = PEER_GOD_SPEECH_ACTS
    return GodCliRegistration(
        cli_id=cli_id,
        display_name=_text(payload.get("display_name")) or cli_id,
        command_family=_required_text(
            payload.get("command_family"),
            "payload.command_family",
        ),
        provider_profile_ref=_required_text(
            payload.get("provider_profile_ref"),
            "payload.provider_profile_ref",
        ),
        capabilities=capabilities,
        allowed_speech_acts=allowed_speech_acts,
        supports_persistent_sessions=_bool_payload(
            payload.get("supports_persistent_sessions")
        ),
        supports_mcp_writeback=_bool_payload(payload.get("supports_mcp_writeback")),
        state_write_allowed=_bool_payload(payload.get("state_write_allowed")),
        proof_level=_god_cli_proof_level(payload.get("proof_level")),
        proof_refs=tuple(_string_values(payload.get("proof_refs"))),
        registration_kind="manual",
        source_authority="operator_action_contract",
    )


def _required_text(value: Any, field_name: str) -> str:
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            return cleaned
    raise ValueError(f"{field_name} must be non-empty")


def _god_cli_proof_level(value: Any) -> GodCliProofLevel:
    proof_level = _required_text(value, "payload.proof_level")
    allowed = {
        "contract_proof",
        "fake_runtime_proof",
        "live_service_proof",
        "server_side_enforcement_proof",
        "server_side_merge_proof",
        "real_provider_proof",
        "internal_review_proof",
        "manual_gap",
    }
    if proof_level not in allowed:
        raise ValueError("payload.proof_level must be an xmuse proof level")
    return cast(GodCliProofLevel, proof_level)


def _string_values(value: Any) -> list[str]:
    if isinstance(value, list | tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _bool_payload(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
