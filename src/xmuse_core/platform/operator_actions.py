from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from xmuse_core.platform.release_evidence_pack import capture_release_evidence_pack
from xmuse_core.providers.god_cli_registry import GodCliRegistry
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionStore

ActionStatus = Literal["ok", "denied", "blocked", "manual_gap"]
ProofLevel = Literal["contract_proof", "manual_gap"]


class OperatorActionCapability(StrEnum):
    REGISTER_GOD_CLI = "register_god_cli"
    SELECT_GOD_CLI = "select_god_cli"
    WORKFLOW_WRITE = "workflow_write"
    RELEASE_GATE = "release_gate"


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


class OperatorActionService:
    def __init__(
        self,
        *,
        god_cli_registry: GodCliRegistry,
        audit_dir: Path,
        selection_store: GodCliSelectionStore | None = None,
        release_readiness_dir: Path | None = None,
    ) -> None:
        self._god_cli_registry = god_cli_registry
        self._audit_dir = audit_dir
        self._selection_store = selection_store
        self._release_readiness_dir = release_readiness_dir or (
            audit_dir.parent / "release_readiness"
        )

    def handle(self, request: OperatorActionRequest) -> OperatorActionResult:
        action = request.action.strip().lower()
        audit_id = f"operator-action:{uuid4().hex}"
        if action == "select_god_cli":
            result = self._handle_select_god_cli(request, audit_id=audit_id)
        elif action in {
            "capture_release_evidence_pack",
            "release_evidence_pack",
            "capture_release_gate",
        }:
            result = self._handle_capture_release_evidence_pack(request, audit_id=audit_id)
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
        selection = self._god_cli_registry.select_for_god(cli_id)
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


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
