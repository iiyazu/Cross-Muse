from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from xmuse_core.agents.persistent_peer import PersistentCliPeerService
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.structuring.planning_contracts import (
    ArchitectGodRequest,
    ArchitectGodResponse,
    PlannerGodRequest,
    PlannerGodResponse,
    PlanningReviewRequest,
    PlanningReviewResponse,
)

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class PlanningGodAdapterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def build_planner_god_prompt(request: PlannerGodRequest) -> str:
    lines = [
        "You are the Planner GOD for xmuse autonomous blueprint execution.",
        (
            "Read the approved mission blueprint and return a medium-grained "
            "feature plan proposal."
        ),
        "",
        "Required response rules:",
        "- Output ONLY valid JSON, no markdown fence and no commentary.",
        "- Echo request_id and correlation_id exactly.",
        (
            "- Include feature_plan_id, feature_plan_version, "
            "source_blueprint_ref, artifact_refs, blueprint_refs, "
            "planning_rationale, and features."
        ),
        (
            "- Every feature must include feature_id, title, goal, "
            "acceptance_criteria, dependencies, graph_id, blueprint_refs, "
            "artifact_refs, risk_notes, planning_rationale, and "
            "dependency_rationale."
        ),
        "- Keep features medium-grained; do not decompose directly into tiny lanes.",
    ]
    if request.rework_context is not None:
        lines.extend(
            [
                "",
                "Rework context:",
                "- This is a revision request for a previously reviewed feature plan.",
                "- Address the review summary and findings in the revised output.",
                "- Keep the same feature_plan_id and increment feature_plan_version.",
            ]
        )
    lines.extend(
        [
            "",
            f"request_id: {request.request_id}",
            f"correlation_id: {request.correlation_id}",
        ]
    )
    return "\n".join(lines)


def build_architect_god_prompt(request: ArchitectGodRequest) -> str:
    return "\n".join(
        [
            "You are the Architect GOD for xmuse autonomous blueprint execution.",
            (
                "Read the approved feature plan and return a graph-set proposal "
                "with per-feature lane DAGs."
            ),
            "",
            "Required response rules:",
            "- Output ONLY valid JSON, no markdown fence and no commentary.",
            "- Echo request_id and correlation_id exactly.",
            (
                "- Include graph_set_id, graph_set_version, feature_plan_id, "
                "feature_plan_version, artifact_refs, blueprint_refs, "
                "feature_graphs, decomposition_review, and "
                "architect_self_check."
            ),
            (
                "- decomposition_review must include feature_packet and "
                "lane_packets aligned with the returned feature_graphs."
            ),
            (
                "- Every lane must include lane_id, local_lane_id, feature_id, "
                "title, prompt, acceptance_criteria, dependencies, "
                "capabilities, expected_touched_areas, artifact_refs, "
                "blueprint_refs, feature_refs, and dependency_rationale."
            ),
            (
                "- architect_self_check must include summary, "
                "dependency_shape, lane_size, risk_level, and "
                "readiness_warnings."
            ),
            "- Lane prompts must be self-contained enough for bounded workers.",
            "",
            f"request_id: {request.request_id}",
            f"correlation_id: {request.correlation_id}",
        ]
    )


def build_planning_review_prompt(request: PlanningReviewRequest) -> str:
    return "\n".join(
        [
            "You are the Review GOD for xmuse planning deliberation.",
            (
                "Review the supplied feature plan or graph-set proposal and "
                "return a structured verdict."
            ),
            "",
            "Required response rules:",
            "- Output ONLY valid JSON, no markdown fence and no commentary.",
            "- Echo request_id and correlation_id exactly.",
            (
                "- Include phase, artifact_id, artifact_version, verdict, "
                "summary, artifact_refs, blueprint_refs, feature_ids, "
                "lane_ids, dependency_rationale_notes, and findings."
            ),
            (
                "- Valid verdicts: approve, request_rework, "
                "reject_as_invalid, challenge_required, "
                "manual_review_required."
            ),
            "- manual_review_required is only valid for graph_set_review.",
            "- For graph_set_review, include architect_self_check in the response.",
            "",
            f"request_id: {request.request_id}",
            f"correlation_id: {request.correlation_id}",
        ]
    )


class _BasePlanningGodAdapter:
    def __init__(
        self,
        *,
        db_path: Path | str,
        session_layer: Any,
        participant_id: str,
        model: str,
        worktree: Path,
        timeout_s: float = 180.0,
    ) -> None:
        self._peer_service = PersistentCliPeerService(
            db_path=db_path,
            session_layer=session_layer,
        )
        self._participant_id = participant_id
        self._model = model
        self._worktree = worktree
        self._timeout_s = timeout_s

    async def _request_structured(
        self,
        *,
        conversation_id: str,
        feature_scope_id: str,
        request_id: str,
        correlation_id: str,
        message_type: str,
        prompt: str,
        context: str,
        response_model: type[ResponseT],
    ) -> ResponseT:
        result = await self._peer_service.request(
            conversation_id=conversation_id,
            participant_id=self._participant_id,
            model=self._model,
            prompt=prompt,
            session_prompt=prompt,
            worktree=self._worktree,
            request_id=request_id,
            message_type=message_type,
            context=context,
            feature_scope_id=feature_scope_id,
            timeout_s=self._timeout_s,
        )
        if not result.ok or result.message is None:
            raise PlanningGodAdapterError(result.status, result.reason or result.status)

        try:
            payload = _extract_payload(result.message)
            response = response_model.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            raise PlanningGodAdapterError("invalid_structured_output", str(exc)) from exc

        response_headers = response.model_dump(
            include={"request_id", "correlation_id", "conversation_id"}
        )
        if response_headers["request_id"] != request_id:
            raise PlanningGodAdapterError("request_id_mismatch", "response request_id mismatch")
        if response_headers["correlation_id"] != correlation_id:
            raise PlanningGodAdapterError(
                "correlation_id_mismatch",
                "response correlation_id mismatch",
            )
        if response_headers["conversation_id"] != conversation_id:
            raise PlanningGodAdapterError(
                "conversation_id_mismatch",
                "response conversation_id mismatch",
            )
        return response


class PlannerGodAdapter(_BasePlanningGodAdapter):
    async def request_plan(self, request: PlannerGodRequest) -> PlannerGodResponse:
        response = await self._request_structured(
            conversation_id=request.conversation_id,
            feature_scope_id=request.feature_plan_id,
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            message_type="planner",
            prompt=build_planner_god_prompt(request),
            context=request.model_dump_json(indent=2),
            response_model=PlannerGodResponse,
        )
        _ensure_equal(
            response.feature_plan_id,
            request.feature_plan_id,
            "feature_plan_id_mismatch",
            "response feature_plan_id mismatch",
        )
        _ensure_equal(
            response.feature_plan_version,
            request.feature_plan_version,
            "feature_plan_version_mismatch",
            "response feature_plan_version mismatch",
        )
        _ensure_equal(
            response.source_blueprint_ref,
            request.blueprint.blueprint_ref,
            "source_blueprint_ref_mismatch",
            "response source_blueprint_ref mismatch",
        )
        return response


class ArchitectGodAdapter(_BasePlanningGodAdapter):
    async def request_graph_set(self, request: ArchitectGodRequest) -> ArchitectGodResponse:
        return await self._request_structured(
            conversation_id=request.conversation_id,
            feature_scope_id=request.graph_set_id,
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            message_type="architect",
            prompt=build_architect_god_prompt(request),
            context=request.model_dump_json(indent=2),
            response_model=ArchitectGodResponse,
        )


class ReviewGodAdapter(_BasePlanningGodAdapter):
    async def request_review(self, request: PlanningReviewRequest) -> PlanningReviewResponse:
        response = await self._request_structured(
            conversation_id=request.conversation_id,
            feature_scope_id=request.artifact_id,
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            message_type="planning_review",
            prompt=build_planning_review_prompt(request),
            context=request.model_dump_json(indent=2),
            response_model=PlanningReviewResponse,
        )
        _ensure_equal(
            response.phase,
            request.phase,
            "review_phase_mismatch",
            "response review phase mismatch",
        )
        _ensure_equal(
            response.artifact_id,
            request.artifact_id,
            "artifact_id_mismatch",
            "response artifact_id mismatch",
        )
        _ensure_equal(
            response.artifact_version,
            request.artifact_version,
            "artifact_version_mismatch",
            "response artifact_version mismatch",
        )
        return response


def _ensure_equal(left: Any, right: Any, code: str, message: str) -> None:
    if left != right:
        raise PlanningGodAdapterError(code, message)


def _extract_payload(message: StdoutMessage) -> dict[str, Any]:
    candidates = [
        message.artifacts.get("stdout") if isinstance(message.artifacts, dict) else None,
        message.message,
    ]
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        text = candidate.strip()
        if not text:
            continue
        blob = _extract_json_blob(text)
        payload = json.loads(blob)
        if not isinstance(payload, dict):
            raise ValueError("structured output must be a JSON object")
        return payload
    raise ValueError("missing JSON object in persistent peer result")


def _extract_json_blob(text: str) -> str:
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fence is not None:
        return fence.group(1)
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1 or last <= first:
        raise ValueError("no JSON object found in structured output")
    return text[first : last + 1]


__all__ = [
    "ArchitectGodAdapter",
    "PlannerGodAdapter",
    "PlanningGodAdapterError",
    "build_architect_god_prompt",
    "build_planner_god_prompt",
    "build_planning_review_prompt",
]
