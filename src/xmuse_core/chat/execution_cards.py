from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, field_validator

from xmuse_core.chat.envelopes import normalize_envelope
from xmuse_core.chat.models import ChatCard
from xmuse_core.platform.run_health import (
    DEFAULT_STALE_AFTER_S,
    build_run_health_model_from_lanes,
    build_run_health_scope,
)
from xmuse_core.platform.state_normalizer import summarize_lane_states

if TYPE_CHECKING:
    from xmuse_core.structuring.models import FeatureGraphSet

ExecutionCardType = Literal[
    "blueprint_execution_started",
    "feature_plan_ready",
    "lane_graph_ready",
    "run_progress",
    "run_takeover",
    "run_terminal",
]
RiskLevel = Literal["low", "medium", "high"]


def _require_text(value: str, field_name: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{field_name} must be non-empty")
    return clean


def _clean_counts(counts: dict[str, Any] | None) -> dict[str, int]:
    cleaned: dict[str, int] = {}
    for raw_key, raw_value in (counts or {}).items():
        key = str(raw_key).strip()
        if not key or isinstance(raw_value, bool) or not isinstance(raw_value, int):
            continue
        cleaned[key] = max(raw_value, 0)
    return cleaned


def _intent_id(dedupe_key: str) -> str:
    digest = sha256(dedupe_key.encode("utf-8")).hexdigest()[:12]
    prefix = dedupe_key.split(":", 3)[2] if dedupe_key.count(":") >= 2 else "execution"
    safe_prefix = prefix.replace("_", "-")
    return f"{safe_prefix}-{digest}"


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _optional_text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _mapping_payload(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="python")
        if isinstance(payload, Mapping):
            return payload
    return {}


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _materialization_time(planning_run: Mapping[str, Any]) -> str:
    for key in ("updated_at", "created_at"):
        value = _optional_text(planning_run.get(key))
        if value is not None:
            return value
    raise ValueError("planning_run must include updated_at or created_at")


def _lane_failed_count(summary: Mapping[str, int]) -> int:
    return sum(
        int(summary.get(key) or 0)
        for key in ("terminated", "exec_failed", "gate_failed")
    )


def _warning_codes(run_health: Mapping[str, Any]) -> list[str]:
    warnings = run_health.get("warnings")
    if not isinstance(warnings, list):
        return []
    return [
        str(item["code"])
        for item in warnings
        if isinstance(item, Mapping) and _optional_text(item.get("code")) is not None
    ]


def _degraded_flag(run_health: Mapping[str, Any]) -> bool:
    counts = run_health.get("counts")
    if not isinstance(counts, Mapping):
        return False
    if any(int(counts.get(key) or 0) > 0 for key in ("degraded_fallback", "infra_failed")):
        return True
    return bool(_warning_codes(run_health))


def _stale_flag(run_health: Mapping[str, Any]) -> bool:
    counts = run_health.get("counts")
    if not isinstance(counts, Mapping):
        return False
    return int(counts.get("stale") or 0) > 0


def _terminal_lane_breakdown(
    terminal_aggregation: Mapping[str, Any],
) -> tuple[int, int]:
    lane_statuses = terminal_aggregation.get("lane_statuses")
    if not isinstance(lane_statuses, list):
        return 0, 0

    merged = 0
    failed = 0
    for item in lane_statuses:
        if not isinstance(item, Mapping):
            continue
        normalized_status = str(item.get("normalized_status") or "").strip().lower()
        is_terminal = item.get("terminal") is True
        if normalized_status == "merged":
            merged += 1
        elif is_terminal:
            failed += 1
    return merged, failed


class CardDrilldownRef(BaseModel):
    ref_type: str
    ref_id: str
    label: str
    href: str
    api_href: str

    @field_validator("ref_type", "ref_id", "label", "href", "api_href")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)


class CardIntent(BaseModel):
    intent_id: str
    dedupe_key: str
    conversation_id: str
    planning_run_id: str
    card_type: ExecutionCardType
    source_id: str
    title: str
    status: str
    summary: str
    href: str
    api_href: str
    created_at: str
    counts: dict[str, int] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    drilldown_refs: list[CardDrilldownRef] = Field(default_factory=list)
    risk_level: RiskLevel | None = None
    fallback_used: bool = False
    takeover_active: bool = False

    @field_validator(
        "intent_id",
        "dedupe_key",
        "conversation_id",
        "planning_run_id",
        "source_id",
        "title",
        "status",
        "summary",
        "href",
        "api_href",
        "created_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("counts", mode="before")
    @classmethod
    def _validate_counts(cls, value: Any) -> dict[str, int]:
        if isinstance(value, dict):
            return _clean_counts(value)
        return {}

    @field_validator("drilldown_refs")
    @classmethod
    def _validate_drilldown_refs(
        cls,
        value: list[CardDrilldownRef],
    ) -> list[CardDrilldownRef]:
        if not value:
            raise ValueError("drilldown_refs must contain at least one item")
        return value

    def to_chat_card(self) -> ChatCard:
        metadata: dict[str, Any] = {
            "planning_run_id": self.planning_run_id,
            "payload": dict(self.payload),
            "dedupe_key": self.dedupe_key,
            "drilldown_refs": [
                ref.model_dump(mode="json") for ref in self.drilldown_refs
            ],
        }
        if self.risk_level is not None:
            metadata["risk_level"] = self.risk_level
        if self.fallback_used:
            metadata["fallback_used"] = True
        if self.takeover_active:
            metadata["takeover_active"] = True
        return ChatCard(
            id=f"card_execution_{self.intent_id}",
            conversation_id=self.conversation_id,
            card_type=self.card_type,
            source_id=self.source_id,
            title=self.title,
            summary=self.summary,
            status=self.status,
            href=self.href,
            api_href=self.api_href,
            created_at=self.created_at,
            counts=self.counts,
            metadata=metadata,
        )


def build_execution_card_envelope(intent: CardIntent) -> dict[str, Any]:
    return normalize_envelope(
        {
            "type": "message",
            "cards": [intent.to_chat_card().model_dump(mode="json")],
        }
    )


class CardIntentStore:
    def __init__(self, base_dir: Path | str) -> None:
        self._path = Path(base_dir) / "read_models" / "execution_card_intents.json"

    def save(self, intent: CardIntent) -> CardIntent:
        intents = self.list_all()
        for index, existing in enumerate(intents):
            if existing.dedupe_key == intent.dedupe_key:
                intents[index] = intent
                self._write(intents)
                return intent
        intents.append(intent)
        self._write(intents)
        return intent

    def list_all(self) -> list[CardIntent]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw_intents = data.get("intents", []) if isinstance(data, dict) else []
        if not isinstance(raw_intents, list):
            return []
        intents: list[CardIntent] = []
        for raw in raw_intents:
            if not isinstance(raw, dict):
                continue
            intents.append(CardIntent.model_validate(raw))
        intents.sort(key=lambda item: (item.created_at, item.card_type, item.intent_id))
        return intents

    def list_for_conversation(self, conversation_id: str) -> list[CardIntent]:
        return [
            intent
            for intent in self.list_all()
            if intent.conversation_id == conversation_id
        ]

    def get(self, conversation_id: str, intent_id: str) -> CardIntent:
        for intent in self.list_for_conversation(conversation_id):
            if intent.intent_id == intent_id:
                return intent
        raise KeyError(f"execution card intent not found: {intent_id}")

    def _write(self, intents: list[CardIntent]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "intents": [intent.model_dump(mode="json") for intent in intents],
        }
        self._path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


class ChatExecutionCardEmitter:
    def __init__(self, base_dir: Path | str) -> None:
        self._base_dir = Path(base_dir)
        self._store = CardIntentStore(self._base_dir)

    def list_intents(self, conversation_id: str) -> list[CardIntent]:
        return self._store.list_for_conversation(conversation_id)

    def list_cards(self, conversation_id: str) -> list[ChatCard]:
        return [intent.to_chat_card() for intent in self.list_intents(conversation_id)]

    def get_intent(self, conversation_id: str, intent_id: str) -> CardIntent:
        return self._store.get(conversation_id, intent_id)

    def materialize_planning_run_cards(
        self,
        *,
        planning_run: Mapping[str, Any],
        terminal_aggregation: Mapping[str, Any] | BaseModel | None = None,
        live_pids: set[int] | None = None,
        runner_pids: list[int] | None = None,
        mcp_pids: list[int] | None = None,
        now: float | None = None,
        stale_after_s: float = DEFAULT_STALE_AFTER_S,
    ) -> list[CardIntent]:
        conversation_id = _require_text(
            str(planning_run.get("conversation_id") or ""),
            "conversation_id",
        )
        planning_run_id = _require_text(
            str(planning_run.get("planning_run_id") or planning_run.get("id") or ""),
            "planning_run_id",
        )
        created_at = _materialization_time(planning_run)
        graph_set = self._load_graph_set(conversation_id, planning_run)
        graph_set_id = (
            graph_set.id
            if graph_set is not None
            else _optional_text(planning_run.get("graph_set_id"))
        )
        if graph_set_id is None:
            return []

        lanes = self._planning_run_lanes(planning_run=planning_run, graph_set=graph_set)
        run_health = build_run_health_model_from_lanes(
            lanes,
            now=now,
            stale_after_s=stale_after_s,
            live_pids=live_pids,
            runner_pids=runner_pids,
            mcp_pids=mcp_pids,
            xmuse_root=self._base_dir,
            scope=build_run_health_scope(
                conversation_id=conversation_id,
                workspace_id=conversation_id,
            ),
        )
        progress_counts = self._progress_counts(
            graph_set=graph_set,
            lanes=lanes,
            run_health=run_health,
        )
        progress_payload = self._progress_payload(
            planning_run=planning_run,
            graph_set=graph_set,
            graph_set_id=graph_set_id,
            run_health=run_health,
        )
        cards = [
            self.emit_run_progress(
                conversation_id=conversation_id,
                planning_run_id=planning_run_id,
                graph_set_id=graph_set_id,
                counts=progress_counts,
                fallback_used=bool(progress_payload["fallback_used"]),
                created_at=created_at,
                status=(
                    "degraded"
                    if progress_payload["stale"] or progress_payload["degraded"]
                    else "active"
                ),
                extra_payload=progress_payload,
                summary=self._progress_summary(progress_counts, progress_payload),
            )
        ]

        if terminal_aggregation is not None:
            terminal_payload = _mapping_payload(terminal_aggregation)
            terminal_status = _optional_text(terminal_payload.get("status"))
            if terminal_status in {"merged", "terminated", "blocked_for_input"}:
                terminal_counts = self._terminal_counts(
                    progress_counts=progress_counts,
                    terminal_aggregation=terminal_payload,
                )
                terminal_card_payload = self._terminal_payload(
                    planning_run=planning_run,
                    graph_set=graph_set,
                    graph_set_id=graph_set_id,
                    run_health=run_health,
                    terminal_aggregation=terminal_payload,
                )
                cards.append(
                    self.emit_run_terminal(
                        conversation_id=conversation_id,
                        planning_run_id=planning_run_id,
                        terminal_status=terminal_status,
                        counts=terminal_counts,
                        created_at=created_at,
                        extra_payload=terminal_card_payload,
                        summary=self._terminal_summary(
                            terminal_status=terminal_status,
                            terminal_payload=terminal_card_payload,
                            terminal_counts=terminal_counts,
                        ),
                    )
                )

        return cards

    def emit_blueprint_execution_started(
        self,
        *,
        conversation_id: str,
        planning_run_id: str,
        resolution_id: str,
        blueprint_ref: str,
        created_at: str,
        summary: str,
    ) -> CardIntent:
        payload = {
            "resolution_id": _require_text(resolution_id, "resolution_id"),
            "blueprint_ref": _require_text(blueprint_ref, "blueprint_ref"),
        }
        return self._emit(
            conversation_id=conversation_id,
            planning_run_id=planning_run_id,
            card_type="blueprint_execution_started",
            status="active",
            created_at=created_at,
            summary=summary,
            title="Blueprint execution started",
            counts={},
            payload=payload,
            drilldown_refs=[
                CardDrilldownRef(
                    ref_type="resolution",
                    ref_id=payload["resolution_id"],
                    label="Approved blueprint",
                    href=(
                        f"/dashboard/peer-chat/conversations/{conversation_id}"
                        f"#resolution-{payload['resolution_id']}"
                    ),
                    api_href=f"/api/chat/resolutions/{payload['resolution_id']}",
                )
            ],
            dedupe_suffix=payload["resolution_id"],
        )

    def emit_feature_plan_ready(
        self,
        *,
        conversation_id: str,
        planning_run_id: str,
        feature_plan_id: str,
        feature_count: int,
        risk_level: RiskLevel | None,
        created_at: str,
        summary: str,
    ) -> CardIntent:
        feature_plan_id = _require_text(feature_plan_id, "feature_plan_id")
        return self._emit(
            conversation_id=conversation_id,
            planning_run_id=planning_run_id,
            card_type="feature_plan_ready",
            status="ready",
            created_at=created_at,
            summary=summary,
            title="Feature plan ready",
            counts={"features": feature_count},
            payload={"feature_plan_id": feature_plan_id},
            risk_level=risk_level,
            drilldown_refs=[
                CardDrilldownRef(
                    ref_type="feature_plan",
                    ref_id=feature_plan_id,
                    label="Feature plan",
                    href=f"/dashboard/feature-plans/{feature_plan_id}",
                    api_href=f"/api/feature-plans/{feature_plan_id}",
                )
            ],
            dedupe_suffix=feature_plan_id,
        )

    def emit_lane_graph_ready(
        self,
        *,
        conversation_id: str,
        planning_run_id: str,
        graph_set_id: str,
        lane_graph_count: int,
        lane_count: int,
        risk_level: RiskLevel | None,
        created_at: str,
        summary: str,
    ) -> CardIntent:
        graph_set_id = _require_text(graph_set_id, "graph_set_id")
        return self._emit(
            conversation_id=conversation_id,
            planning_run_id=planning_run_id,
            card_type="lane_graph_ready",
            status="ready",
            created_at=created_at,
            summary=summary,
            title="Lane graph ready",
            counts={
                "lane_graphs": lane_graph_count,
                "lanes": lane_count,
            },
            payload={"graph_set_id": graph_set_id},
            risk_level=risk_level,
            drilldown_refs=[
                CardDrilldownRef(
                    ref_type="graph_set",
                    ref_id=graph_set_id,
                    label="Lane graph set",
                    href=f"/dashboard/feature-graph-sets/{graph_set_id}",
                    api_href=f"/api/feature-graph-sets/{graph_set_id}",
                )
            ],
            dedupe_suffix=graph_set_id,
        )

    def emit_run_progress(
        self,
        *,
        conversation_id: str,
        planning_run_id: str,
        graph_set_id: str,
        counts: dict[str, int],
        fallback_used: bool,
        created_at: str,
        summary: str,
        status: str = "active",
        extra_payload: dict[str, Any] | None = None,
    ) -> CardIntent:
        graph_set_id = _require_text(graph_set_id, "graph_set_id")
        clean_counts = _clean_counts(counts)
        payload = {
            "graph_set_id": graph_set_id,
            "fallback_used": bool(fallback_used),
        }
        if extra_payload:
            payload.update(dict(extra_payload))
        return self._emit(
            conversation_id=conversation_id,
            planning_run_id=planning_run_id,
            card_type="run_progress",
            status=status,
            created_at=created_at,
            summary=summary,
            title="Run progress",
            counts=clean_counts,
            payload=payload,
            fallback_used=fallback_used,
            drilldown_refs=[
                CardDrilldownRef(
                    ref_type="graph_set",
                    ref_id=graph_set_id,
                    label="Run graph set",
                    href=f"/dashboard/feature-graph-sets/{graph_set_id}",
                    api_href=f"/api/feature-graph-sets/{graph_set_id}",
                )
            ],
            dedupe_suffix=_stable_json(
                {
                    "graph_set_id": graph_set_id,
                    "counts": clean_counts,
                    "payload": payload,
                    "status": status,
                }
            ),
        )

    def emit_run_takeover(
        self,
        *,
        conversation_id: str,
        planning_run_id: str,
        lane_id: str,
        takeover_reason: str,
        created_at: str,
        summary: str,
        payload: dict[str, Any] | None = None,
        status: str = "needs_attention",
        title: str = "Run takeover",
        counts: dict[str, int] | None = None,
        dedupe_suffix: str | None = None,
        takeover_active: bool = True,
    ) -> CardIntent:
        lane_id = _require_text(lane_id, "lane_id")
        takeover_reason = _require_text(takeover_reason, "takeover_reason")
        final_payload = {
            "lane_id": lane_id,
            "takeover_reason": takeover_reason,
        }
        if isinstance(payload, dict):
            final_payload.update(payload)
        return self._emit(
            conversation_id=conversation_id,
            planning_run_id=planning_run_id,
            card_type="run_takeover",
            status=status,
            created_at=created_at,
            summary=summary,
            title=title,
            counts=_clean_counts(counts) or {"takeover_lanes": 1},
            payload=final_payload,
            takeover_active=takeover_active,
            drilldown_refs=[
                CardDrilldownRef(
                    ref_type="lane",
                    ref_id=lane_id,
                    label="Lane",
                    href=f"/dashboard/lanes/{lane_id}#takeover",
                    api_href=f"/api/lanes/{lane_id}",
                )
            ],
            dedupe_suffix=dedupe_suffix or f"{lane_id}:{takeover_reason}",
        )

    def emit_run_terminal(
        self,
        *,
        conversation_id: str,
        planning_run_id: str,
        terminal_status: str,
        counts: dict[str, int],
        created_at: str,
        summary: str,
        extra_payload: dict[str, Any] | None = None,
    ) -> CardIntent:
        terminal_status = _require_text(terminal_status, "terminal_status")
        clean_counts = _clean_counts(counts)
        payload = {"terminal_status": terminal_status}
        if extra_payload:
            payload.update(dict(extra_payload))
        dedupe_basis = {"terminal_status": terminal_status}
        dedupe_basis["graph_set_id"] = _optional_text(payload.get("graph_set_id")) or ""
        return self._emit(
            conversation_id=conversation_id,
            planning_run_id=planning_run_id,
            card_type="run_terminal",
            status=terminal_status,
            created_at=created_at,
            summary=summary,
            title="Run terminal",
            counts=clean_counts,
            payload=payload,
            drilldown_refs=[
                CardDrilldownRef(
                    ref_type="run_health",
                    ref_id=planning_run_id,
                    label="Run health",
                    href=(
                        f"/dashboard/peer-chat/conversations/{conversation_id}"
                        "#run-health"
                    ),
                    api_href=(
                        f"/api/dashboard/peer-chat/conversations/{conversation_id}"
                        "/run-health"
                    ),
                )
            ],
            dedupe_suffix=_stable_json(dedupe_basis),
        )

    def _load_graph_set(
        self,
        conversation_id: str,
        planning_run: Mapping[str, Any],
    ) -> FeatureGraphSet | None:
        graph_set_id = _optional_text(planning_run.get("graph_set_id"))
        if graph_set_id is None:
            return None
        try:
            from xmuse_core.structuring.feature_plan_store import FeatureGraphSetStore

            return FeatureGraphSetStore(self._base_dir / "lane_graphs").load(
                graph_set_id,
                conversation_id=conversation_id,
            )
        except (KeyError, ValueError):
            return None

    def _planning_run_lanes(
        self,
        *,
        planning_run: Mapping[str, Any],
        graph_set: FeatureGraphSet | None,
    ) -> list[dict[str, Any]]:
        lane_payload = _read_json(self._base_dir / "feature_lanes.json")
        if not isinstance(lane_payload, Mapping):
            return []
        raw_lanes = lane_payload.get("lanes")
        if not isinstance(raw_lanes, list):
            return []

        conversation_id = _optional_text(planning_run.get("conversation_id"))
        graph_set_id = _optional_text(planning_run.get("graph_set_id"))
        graph_ids = {graph.id for graph in graph_set.graphs} if graph_set is not None else set()
        feature_plan_id = graph_set.feature_plan.id if graph_set is not None else None
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()

        for lane in raw_lanes:
            if not isinstance(lane, dict):
                continue
            explicit_conversation_id = _optional_text(lane.get("conversation_id"))
            if (
                conversation_id is not None
                and explicit_conversation_id is not None
                and explicit_conversation_id != conversation_id
            ):
                continue
            matches_graph = _optional_text(lane.get("graph_id")) in graph_ids
            matches_plan = (
                feature_plan_id is not None
                and _optional_text(lane.get("feature_plan_id")) == feature_plan_id
            )
            matches_graph_set = (
                graph_set_id is not None
                and _optional_text(lane.get("graph_set_id")) == graph_set_id
            )
            if not (matches_graph or matches_plan or matches_graph_set):
                continue
            lane_id = _optional_text(lane.get("lane_id")) or _optional_text(lane.get("feature_id"))
            if lane_id is None or lane_id in seen:
                continue
            selected.append(lane)
            seen.add(lane_id)

        return selected

    def _progress_counts(
        self,
        *,
        graph_set: FeatureGraphSet | None,
        lanes: list[dict[str, Any]],
        run_health: Mapping[str, Any],
    ) -> dict[str, int]:
        feature_counts = {
            "features": 0,
            "lane_graphs": 0,
            "planned_features": 0,
            "ready_features": 0,
            "active_features": 0,
            "terminal_features": 0,
            "blocked_features": 0,
            "unsafe_features": 0,
        }
        if graph_set is not None:
            from xmuse_core.structuring.feature_summary import summarize_feature_graph_set

            progress = summarize_feature_graph_set(
                graph_set,
                terminal_success_feature_ids=set(),
                live_lanes=lanes,
            )
            feature_counts.update(
                {
                    "features": len(graph_set.feature_plan.features),
                    "lane_graphs": len(graph_set.graphs),
                    "planned_features": progress.counts["planned"],
                    "ready_features": progress.counts["ready"],
                    "active_features": progress.counts["active"],
                    "terminal_features": progress.counts["terminal"],
                    "blocked_features": progress.counts["blocked"],
                    "unsafe_features": progress.counts["unsafe"],
                }
            )

        lane_counts = summarize_lane_states(lanes)
        health_counts = run_health.get("counts")
        if not isinstance(health_counts, Mapping):
            health_counts = {}
        return {
            **feature_counts,
            "total_lanes": int(lane_counts.get("total") or 0),
            "active_lanes": int(health_counts.get("live") or 0),
            "stale_lanes": int(health_counts.get("stale") or 0),
            "blocked_lanes": int(health_counts.get("blocked") or 0),
            "failed_lanes": _lane_failed_count(lane_counts),
            "terminal_lanes": int(health_counts.get("terminal") or 0),
            "retrying_lanes": int(health_counts.get("retrying") or 0),
            "takeover_lanes": int(health_counts.get("takeover_context_needed") or 0),
            "degraded_lanes": int(health_counts.get("degraded_fallback") or 0),
        }

    def _progress_payload(
        self,
        *,
        planning_run: Mapping[str, Any],
        graph_set: FeatureGraphSet | None,
        graph_set_id: str,
        run_health: Mapping[str, Any],
    ) -> dict[str, Any]:
        warning_codes = _warning_codes(run_health)
        degraded = _degraded_flag(run_health)
        stale = _stale_flag(run_health)
        return {
            "graph_set_id": graph_set_id,
            "graph_set_version": (
                graph_set.feature_plan.version
                if graph_set is not None
                else int(planning_run.get("graph_set_version") or 0)
            ),
            "feature_plan_id": (
                graph_set.feature_plan.id
                if graph_set is not None
                else _optional_text(planning_run.get("feature_plan_id")) or ""
            ),
            "planning_status": _optional_text(planning_run.get("status")) or "unknown",
            "stale": stale,
            "degraded": degraded,
            "fallback_used": (
                int(
                    (run_health.get("counts") or {}).get("degraded_fallback")
                    or 0
                )
                > 0
            ),
            "warning_codes": warning_codes,
        }

    def _progress_summary(
        self,
        counts: Mapping[str, int],
        payload: Mapping[str, Any],
    ) -> str:
        summary = (
            f"{counts['terminal_features']}/{counts['features']} features terminal, "
            f"{counts['active_lanes']} active lanes, "
            f"{counts['stale_lanes']} stale, "
            f"{counts['failed_lanes']} failed."
        )
        if payload.get("degraded") is True:
            return summary + " Runner health is degraded."
        return summary

    def _terminal_counts(
        self,
        *,
        progress_counts: Mapping[str, int],
        terminal_aggregation: Mapping[str, Any],
    ) -> dict[str, int]:
        merged_lanes, failed_lanes = _terminal_lane_breakdown(terminal_aggregation)
        return {
            "features": progress_counts.get("features", 0),
            "lane_graphs": progress_counts.get("lane_graphs", 0),
            "terminal_features": progress_counts.get("terminal_features", 0),
            "blocked_features": progress_counts.get("blocked_features", 0),
            "unsafe_features": progress_counts.get("unsafe_features", 0),
            "merged_lanes": merged_lanes,
            "failed_lanes": failed_lanes,
            "open_lineages": len(list(terminal_aggregation.get("open_lineages") or [])),
            "blocked_objects": len(list(terminal_aggregation.get("blocked_objects") or [])),
            "final_action_holds": len(list(terminal_aggregation.get("final_action_holds") or [])),
        }

    def _terminal_payload(
        self,
        *,
        planning_run: Mapping[str, Any],
        graph_set: FeatureGraphSet | None,
        graph_set_id: str,
        run_health: Mapping[str, Any],
        terminal_aggregation: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = self._progress_payload(
            planning_run=planning_run,
            graph_set=graph_set,
            graph_set_id=graph_set_id,
            run_health=run_health,
        )
        payload.update(
            {
                "terminal_reason": _optional_text(terminal_aggregation.get("reason")) or "",
                "terminal_aggregation_id": _optional_text(
                    terminal_aggregation.get("aggregation_id")
                )
                or "",
            }
        )
        return payload

    def _terminal_summary(
        self,
        *,
        terminal_status: str,
        terminal_payload: Mapping[str, Any],
        terminal_counts: Mapping[str, int],
    ) -> str:
        reason = (
            _optional_text(terminal_payload.get("terminal_reason"))
            or "terminal aggregation recorded"
        )
        return (
            f"Run {terminal_status}. "
            f"{terminal_counts['merged_lanes']} merged lanes, "
            f"{terminal_counts['failed_lanes']} failed lanes. "
            f"{reason}."
        )

    def _emit(
        self,
        *,
        conversation_id: str,
        planning_run_id: str,
        card_type: ExecutionCardType,
        status: str,
        created_at: str,
        summary: str,
        title: str,
        counts: dict[str, int],
        payload: dict[str, Any],
        drilldown_refs: list[CardDrilldownRef],
        dedupe_suffix: str,
        risk_level: RiskLevel | None = None,
        fallback_used: bool = False,
        takeover_active: bool = False,
    ) -> CardIntent:
        conversation_id = _require_text(conversation_id, "conversation_id")
        planning_run_id = _require_text(planning_run_id, "planning_run_id")
        dedupe_key = (
            f"{conversation_id}:{planning_run_id}:{card_type}:{dedupe_suffix}"
        )
        intent_id = _intent_id(dedupe_key)
        intent = CardIntent(
            intent_id=intent_id,
            dedupe_key=dedupe_key,
            conversation_id=conversation_id,
            planning_run_id=planning_run_id,
            card_type=card_type,
            source_id=intent_id,
            title=title,
            status=_require_text(status, "status"),
            summary=_require_text(summary, "summary"),
            href=(
                f"/dashboard/peer-chat/conversations/{conversation_id}"
                f"#execution-card-{intent_id}"
            ),
            api_href=(
                f"/api/dashboard/peer-chat/conversations/{conversation_id}"
                f"/execution-cards/{intent_id}"
            ),
            created_at=_require_text(created_at, "created_at"),
            counts=counts,
            payload=payload,
            drilldown_refs=drilldown_refs,
            risk_level=risk_level,
            fallback_used=fallback_used,
            takeover_active=takeover_active,
        )
        return self._store.save(intent)
