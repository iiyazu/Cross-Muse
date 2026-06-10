from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from xmuse_core.chat.execution_cards import ChatExecutionCardEmitter
from xmuse_core.platform.event_bus import EventBus
from xmuse_core.structuring.models import PlanningEvent
from xmuse_core.structuring.planning_event_store import PlanningEventStore
from xmuse_core.structuring.planning_run_store import PlanningRunStore


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text


def _event_ref(event_id: str) -> str:
    return f"planning_events.sqlite3#{event_id}"


def _audit_ref(event_id: str) -> str:
    return f"audit_events.json#{event_id}"


def _audit_event_id(event_type: str, dedupe_key: str) -> str:
    digest = sha256(f"{event_type}:{dedupe_key}".encode("utf-8")).hexdigest()[:12]
    return f"evt-{digest}"


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(default)
    return data if isinstance(data, dict) else dict(default)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class BlueprintAutomationResult:
    claimed_event_id: str
    planning_run_id: str
    next_event_id: str
    audit_ref: str
    chat_card_ref: str


class BlueprintAutomationService:
    def __init__(
        self,
        *,
        base_dir: Path | str,
        now: Callable[[], str] = _utc_now_iso,
        event_store: PlanningEventStore | None = None,
        run_store: PlanningRunStore | None = None,
        card_emitter: ChatExecutionCardEmitter | None = None,
        event_bus: EventBus | None = None,
        lease_ttl_seconds: int = 60,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._now = now
        self._event_store = event_store or PlanningEventStore(
            self._base_dir / "planning_events.sqlite3"
        )
        self._run_store = run_store or PlanningRunStore(self._base_dir / "planning_runs.sqlite3")
        self._card_emitter = card_emitter or ChatExecutionCardEmitter(self._base_dir)
        self._event_bus = event_bus or EventBus(
            audit_log_path=self._base_dir / "audit_events.json"
        )
        self._lease_ttl_seconds = lease_ttl_seconds

    def tick(self, *, worker_id: str) -> BlueprintAutomationResult | None:
        claimed = self._event_store.claim_next(
            worker_id=worker_id,
            lease_ttl=self._lease_ttl_seconds,
            event_type="blueprint.approved",
        )
        if claimed is None:
            return None
        return self._process_claimed_event(claimed)

    def _process_claimed_event(self, event: PlanningEvent) -> BlueprintAutomationResult:
        resolution_id = _require_text(event.payload.get("resolution_id"), "resolution_id")
        blueprint_artifact_id = _require_text(
            event.payload.get("blueprint_artifact_id"),
            "blueprint_artifact_id",
        )
        created_at = self._now()
        planning_run = self._resolve_planning_run(event)
        if event.planning_run_id != planning_run.planning_run_id:
            event = self._event_store.attach_planning_run(
                event.event_id,
                planning_run.planning_run_id,
            )

        started_event = self._event_store.enqueue(
            PlanningEvent(
                event_id=f"pevt_{planning_run.planning_run_id}_planning_started",
                event_type="planning.started",
                planning_run_id=planning_run.planning_run_id,
                conversation_id=event.conversation_id,
                blueprint_ref=event.blueprint_ref,
                dedupe_key=event.dedupe_key,
                idempotency_key=f"planning.started:{planning_run.planning_run_id}",
                payload={
                    **event.payload,
                    "source_event_id": event.event_id,
                },
                created_at=created_at,
                updated_at=created_at,
            )
        )
        intent = self._card_emitter.emit_blueprint_execution_started(
            conversation_id=event.conversation_id,
            planning_run_id=planning_run.planning_run_id,
            resolution_id=resolution_id,
            blueprint_ref=event.blueprint_ref,
            created_at=created_at,
            summary="Blueprint execution started.",
        )
        audit_ref = self._upsert_started_audit_event(
            event=event,
            planning_run_id=planning_run.planning_run_id,
            blueprint_artifact_id=blueprint_artifact_id,
            next_event_id=started_event.event_id,
            chat_card_ref=intent.intent_id,
            created_at=created_at,
        )
        self._run_store.append_artifact_refs(
            planning_run.planning_run_id,
            audit_refs=[audit_ref],
            chat_card_refs=[intent.intent_id],
            human_trigger_enabled=bool(event.payload.get("human_trigger_enabled")),
            updated_at=created_at,
        )
        self._event_store.ack(event.event_id)
        return BlueprintAutomationResult(
            claimed_event_id=event.event_id,
            planning_run_id=planning_run.planning_run_id,
            next_event_id=started_event.event_id,
            audit_ref=audit_ref,
            chat_card_ref=intent.intent_id,
        )

    def _resolve_planning_run(self, event: PlanningEvent):
        if event.planning_run_id is not None:
            try:
                return self._run_store.get(event.planning_run_id)
            except KeyError:
                pass
        blueprint_version = int(event.payload.get("resolution_version") or 1)
        return self._run_store.create_or_get_initial(
            conversation_id=event.conversation_id,
            blueprint_ref=event.blueprint_ref,
            blueprint_version=blueprint_version,
            dedupe_key=event.dedupe_key,
            planning_run_id=event.planning_run_id,
            created_by="blueprint_automation_service",
        )

    def _upsert_started_audit_event(
        self,
        *,
        event: PlanningEvent,
        planning_run_id: str,
        blueprint_artifact_id: str,
        next_event_id: str,
        chat_card_ref: str,
        created_at: str,
    ) -> str:
        path = getattr(self._event_bus, "_audit_log_path", None)
        if path is None:
            raise ValueError("event_bus must be configured with an audit_log_path")
        audit_path = Path(path)
        event_type = "blueprint.execution.started"
        dedupe_key = f"{event_type}:{planning_run_id}"
        payload = {
            "event_id": _audit_event_id(event_type, dedupe_key),
            "event_type": event_type,
            "created_at": created_at,
            "dedupe_key": dedupe_key,
            "actor": "blueprint_automation_service",
            "conversation_id": event.conversation_id,
            "planning_run_id": planning_run_id,
            "blueprint_ref": event.blueprint_ref,
            "resolution_id": event.payload.get("resolution_id"),
            "resolution_version": event.payload.get("resolution_version"),
            "blueprint_artifact_id": blueprint_artifact_id,
            "approved_by": list(event.payload.get("approved_by") or []),
            "approval_mode": event.payload.get("approval_mode"),
            "human_trigger_enabled": bool(event.payload.get("human_trigger_enabled")),
            "source_event_ref": _event_ref(event.event_id),
            "next_event_ref": _event_ref(next_event_id),
            "chat_card_ref": chat_card_ref,
        }

        data = _read_json(audit_path, {"events": []})
        events = data.setdefault("events", [])
        for existing in events:
            if not isinstance(existing, dict):
                continue
            metadata = existing.get("metadata")
            if (
                existing.get("event_type") == event_type
                and isinstance(metadata, dict)
                and metadata.get("dedupe_key") == dedupe_key
            ):
                metadata.update(payload)
                _write_json(audit_path, data)
                return _audit_ref(str(existing["event_id"]))

        audit_event = {
            "event_id": payload["event_id"],
            "event_type": event_type,
            "timestamp": created_at,
            "metadata": payload,
        }
        events.append(audit_event)
        _write_json(audit_path, data)
        return _audit_ref(str(audit_event["event_id"]))
