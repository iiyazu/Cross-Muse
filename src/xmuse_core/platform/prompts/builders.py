"""Pure-function prompt builders extracted from PlatformOrchestrator.

Each function takes a lane dict and the xmuse root path, returning the
assembled prompt string or structured verdict object.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xmuse_core.platform.lane_context import (
    build_lane_context_bundle,
    should_include_retry_context,
)
from xmuse_core.providers.goal_contract import WorkerGoalContract
from xmuse_core.structuring.models import ReviewDecision, ReviewVerdict

_MAX_BLUEPRINT_REFS = 4
_MAX_BLUEPRINT_CHARS = 2400
_MAX_ACCEPTANCE_CRITERIA = 12
_MAX_ACCEPTANCE_CRITERION_CHARS = 500
_CHILD_WORKER_AUTOMATION_OVERRIDE = """## Xmuse Child Worker Automation Override

This is a noninteractive xmuse child-worker invocation owned by the platform
runner. If any local, project, user, plugin, or skill instruction asks you to
brainstorm before acting, wait for human approval, write a design document,
start a visual companion, offer browser mockups, or pause for clarification,
skip that instruction for this child-worker invocation.

Do not ask the human user for approval, confirmation, or clarification.
Do not start or offer a browser, visual companion, mockup companion, preview server, or
interactive design loop. Either complete the bounded lane using the task and
repository context already provided, or report a blocker through the lane
contract. If the lane is too vague to implement safely, exit non-zero and mark
the lane as blocked/failed instead of continuing an open-ended discussion.
"""


def build_worker_goal_prompt(
    contract: WorkerGoalContract,
    *,
    task_context: str = "",
) -> str:
    """Build the bounded CLI worker prompt for a coordinator-owned lane."""

    sections = [
        "## CLI Worker Goal Contract",
        "",
        "You are a bounded CLI worker called by the xmuse coordinator.",
        "You are a controlled tool, not an autonomous GOD.",
        "",
        "## Invocation",
        "",
        f"- request_id: {contract.request_id}",
        f"- lane_id: {contract.lane_id}",
        f"- provider_profile_ref: {contract.provider_profile_ref}",
        f"- output_schema_version: {contract.output_schema_version}",
    ]

    sections.extend(_prompt_list_section("Skill contracts", contract.skill_contract_refs))
    sections.extend(["## Goal", "", contract.goal])
    sections.extend(
        _prompt_list_section("Acceptance criteria", contract.acceptance_criteria)
    )
    sections.extend(_prompt_list_section("Blueprint refs", contract.blueprint_refs))
    sections.extend(_prompt_list_section("Dependencies", contract.dependencies))
    sections.extend(
        _prompt_list_section("Expected touched areas", contract.expected_touched_areas)
    )
    sections.extend(
        _prompt_list_section(
            "Required verification commands",
            contract.required_verification_commands,
        )
    )
    sections.extend(
        _prompt_list_section("Prior failure context", contract.prior_failure_context)
    )
    sections.extend(_prompt_list_section("Forbidden actions", contract.forbidden_actions))
    if task_context.strip():
        sections.extend(["## Task Context", "", task_context.strip()])
    sections.extend(
        [
            "## Required Output",
            "",
            "Return structured `worker_result` JSON that validates as "
            f"`{contract.output_schema_version}`.",
            "Required top-level fields include: request_id, provider_id, "
            "provider_profile_id, status, changed_files, tests_run, evidence_refs, "
            "evidence, verification, blockers, blocker_details, confidence, "
            "touched_areas, and summary.",
            "Use status `blocked` with blocker_details when work cannot proceed.",
            "Do not write durable stores.",
            "Do not update lane status.",
            "Do not create autonomous GOD chains.",
        ]
    )
    return "\n".join(sections).strip() + "\n"


def _prompt_list_section(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    return [f"## {title}", "", *[f"- {item}" for item in items]]


def build_execution_prompt(
    lane: dict[str, Any],
    *,
    xmuse_root: Path,
    skill_prompt_path: str,
    all_lanes: list[dict[str, Any]] | None = None,
) -> str:
    """Build the full execution-god prompt for *lane*."""
    skill = _read_prompt_skill(skill_prompt_path, xmuse_root=xmuse_root)
    task = lane.get("prompt", "")
    lid = lane.get("feature_id", "")
    prompt = (
        f"{_CHILD_WORKER_AUTOMATION_OVERRIDE}\n\n"
        f"{skill}\n\n## Task\n\nLane ID: {lid}\n\n{task}"
    )
    model_policy_context = _model_policy_context(lane)
    if model_policy_context:
        prompt = f"{prompt}\n\n{model_policy_context}"
    blueprint_context = _blueprint_context(lane, xmuse_root=xmuse_root)
    if blueprint_context:
        prompt = f"{prompt}\n\n{blueprint_context}"
    context = _prior_attempt_context(lane, xmuse_root=xmuse_root, all_lanes=all_lanes)
    if context:
        prompt = f"{prompt}\n\n{context}"
    return prompt


def _model_policy_context(lane: dict[str, Any]) -> str:
    if lane.get("model_policy_enabled") is not True:
        return ""
    lines = ["## Model Policy", ""]
    for key in (
        "model_policy_runtime",
        "review_model",
        "coordinator_model",
        "worker_model",
        "delegation_mode",
        "delegation_contract",
    ):
        value = lane.get(key)
        if isinstance(value, str) and value.strip():
            lines.append(f"- {key}: {value.strip()}")
    if len(lines) <= 2:
        return ""
    bounded_contract = _bounded_worker_delegation_contract(lane)
    if bounded_contract:
        return "\n".join(lines) + "\n\n" + bounded_contract
    return "\n".join(lines)


def _bounded_worker_delegation_contract(lane: dict[str, Any]) -> str:
    delegation_mode = lane.get("delegation_mode")
    if delegation_mode != "bounded_worker":
        return ""
    worker_model = _clean_prompt_value(lane.get("worker_model")) or "unset"
    return "\n".join(
        [
            "## Bounded Worker Delegation Contract",
            "",
            (
                "- Coordinator layer: plan the lane, delegate bounded "
                "code-writing work, collect diffs, changed files, tests run, "
                "and summaries, then perform first-pass integration."
            ),
            (
                "- Worker layer: use a temporary_child_worker with configured "
                f"worker_model {worker_model}."
            ),
            (
                "- Runtime constraint: codex-only; do not choose other runtimes "
                "or autonomously optimize model/cost choices."
            ),
        ]
    )


def _clean_prompt_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def build_review_prompt(
    lane: dict[str, Any],
    *,
    xmuse_root: Path,
    skill_prompt_path: str,
    all_lanes: list[dict[str, Any]] | None = None,
) -> str:
    """Build the full review-god prompt for *lane*."""
    skill = _read_prompt_skill(skill_prompt_path, xmuse_root=xmuse_root)
    lid = lane.get("feature_id", "")
    prompt = (
        f"{_CHILD_WORKER_AUTOMATION_OVERRIDE}\n\n"
        f"{skill}\n\n## Task\n\nReview lane: {lid}"
    )
    task = str(lane.get("prompt", "")).strip()
    if task:
        prompt = f"{prompt}\n\n## Lane Task\n\n{task}"
    blueprint_context = _blueprint_context(lane, xmuse_root=xmuse_root)
    if blueprint_context:
        prompt = f"{prompt}\n\n{blueprint_context}"
    context = _prior_attempt_context(lane, xmuse_root=xmuse_root, all_lanes=all_lanes)
    if context:
        prompt = f"{prompt}\n\n{context}"
    return prompt


def _blueprint_context(lane: dict[str, Any], *, xmuse_root: Path) -> str:
    sections = [
        section
        for section in (
            _blueprint_refs_for_prompt(lane.get("blueprint_refs"), xmuse_root=xmuse_root),
            _acceptance_criteria_for_prompt(lane.get("acceptance_criteria")),
        )
        if section
    ]
    return "\n\n".join(sections)


def _read_prompt_skill(skill_prompt_path: str, *, xmuse_root: Path) -> str:
    path = Path(skill_prompt_path)
    candidates = [path] if path.is_absolute() else [
        root / path for root in _prompt_skill_roots(xmuse_root)
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return ""


def _blueprint_refs_for_prompt(value: Any, *, xmuse_root: Path) -> str:
    refs = _coerce_text_items(value)
    if not refs:
        return ""

    lines = ["## Mission Blueprint References", ""]
    for ref in refs[:_MAX_BLUEPRINT_REFS]:
        lines.extend(_blueprint_ref_lines(ref, xmuse_root=xmuse_root))
    if len(refs) > _MAX_BLUEPRINT_REFS:
        omitted = len(refs) - _MAX_BLUEPRINT_REFS
        lines.append(f"- Omitted {omitted} additional blueprint ref(s) for prompt bounds.")
    return "\n".join(lines)


def _blueprint_ref_lines(ref: str, *, xmuse_root: Path) -> list[str]:
    roots = _blueprint_roots(xmuse_root)
    path = Path(ref)
    candidate = path if path.is_absolute() else roots[0] / path
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        return [f"### {ref}", "", f"- unavailable: unresolvable ({type(exc).__name__})", ""]
    if not path.is_absolute() and not resolved.exists() and len(roots) > 1:
        for root_candidate in roots[1:]:
            alternate = root_candidate / path
            try:
                alternate_resolved = alternate.resolve()
            except (OSError, RuntimeError, ValueError):
                continue
            if alternate_resolved.exists():
                resolved = alternate_resolved
                break
    display_root = _display_root_for(resolved, roots)
    if display_root is None:
        return [f"### {ref}", "", "- unavailable: outside xmuse root", ""]
    display = str(resolved.relative_to(display_root))
    if not resolved.exists():
        return [f"### {display}", "", "- unavailable: missing file", ""]

    try:
        text = _read_text_bounded(resolved, max_chars=_MAX_BLUEPRINT_CHARS)
    except (OSError, UnicodeDecodeError) as exc:
        return [f"### {display}", "", f"- unavailable: unreadable ({type(exc).__name__})", ""]

    return [f"### {display}", "", _compact_prompt_text(text), ""]


def _blueprint_roots(xmuse_root: Path) -> list[Path]:
    roots = [xmuse_root.resolve()]
    parent = xmuse_root.resolve().parent
    if parent != roots[0]:
        roots.append(parent)
    return roots


def _prompt_skill_roots(xmuse_root: Path) -> list[Path]:
    roots = _blueprint_roots(xmuse_root)
    for root in (Path.cwd(), Path(__file__).resolve().parents[4]):
        try:
            resolved = root.resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _display_root_for(path: Path, roots: list[Path]) -> Path | None:
    for root in roots:
        if _is_relative_to(path, root):
            return root
    return None


def _read_text_bounded(path: Path, *, max_chars: int) -> str:
    with path.open("r", encoding="utf-8") as handle:
        return handle.read(max_chars + 1)


def _acceptance_criteria_for_prompt(value: Any) -> str:
    criteria = _coerce_text_items(value)
    if not criteria:
        return ""

    lines = ["## Feature Acceptance Criteria", ""]
    for criterion in criteria[:_MAX_ACCEPTANCE_CRITERIA]:
        compacted = _compact_prompt_text(
            criterion,
            max_chars=_MAX_ACCEPTANCE_CRITERION_CHARS,
        )
        lines.append(f"- {compacted}")
    if len(criteria) > _MAX_ACCEPTANCE_CRITERIA:
        omitted = len(criteria) - _MAX_ACCEPTANCE_CRITERIA
        lines.append(
            f"- Omitted {omitted} additional acceptance criterion/criteria "
            "for prompt bounds."
        )
    return "\n".join(lines)


def _coerce_text_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        text = str(item).strip()
        if text:
            items.append(text)
    return items


def _compact_prompt_text(value: str, *, max_chars: int = _MAX_BLUEPRINT_CHARS) -> str:
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 14].rstrip() + "...<truncated>"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _prior_attempt_context(
    lane: dict[str, Any],
    *,
    xmuse_root: Path,
    all_lanes: list[dict[str, Any]] | None = None,
) -> str:
    if not should_include_retry_context(lane):
        return ""
    return str(
        build_lane_context_bundle(
            lane,
            xmuse_root=xmuse_root,
            all_lanes=all_lanes,
        )["retry_context"]
    )


def build_review_verdict(lane: dict[str, Any]) -> ReviewVerdict:
    """Construct a ReviewVerdict from lane metadata."""
    raw_decision = lane.get("review_decision", ReviewDecision.MERGE.value)
    try:
        decision = ReviewDecision(str(raw_decision))
    except ValueError:
        decision = ReviewDecision.MERGE

    evidence_refs = lane.get("review_evidence_refs", [])
    if not isinstance(evidence_refs, list):
        evidence_refs = []

    return ReviewVerdict(
        id=str(lane.get("review_verdict_id", f"verdict-{lane.get('feature_id', 'lane')}")),
        lane_id=str(lane.get("feature_id", "")),
        decision=decision,
        summary=str(lane.get("review_summary", lane.get("decision_reason", "reviewed"))),
        evidence_refs=[str(item) for item in evidence_refs],
        patch_instructions=(
            str(lane["patch_instructions"])
            if lane.get("patch_instructions") is not None
            else None
        ),
        terminate_reason=(
            str(lane["terminate_reason"]) if lane.get("terminate_reason") is not None else None
        ),
    )
