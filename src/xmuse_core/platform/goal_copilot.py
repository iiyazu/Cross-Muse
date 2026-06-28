from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

REVIEW_BOARD_FILENAME = "production-goal-copilot-review-board.md"
INTAKE_SCHEMA_VERSION = "goal_copilot_intake/v1"
INTAKE_PROOF_BOUNDARY = (
    "advisory_intake_not_review_dispatch_github_gate_merge_or_execution_truth"
)
AUTHORITY_BOUNDARY = (
    "chat.db / inbox / proposal / review verdict / dispatch queue / "
    "final-action holds / GitHub server facts"
)
FORBIDDEN_TRUTH_SURFACES = [
    "provider stdout",
    "worker output",
    "local tests",
    "subagent output",
    "copilot output",
]

_DURABLE_AUTHORITY_PREFIXES = (
    "chat.db:",
    "inbox:",
    "proposal:",
    "review_verdict:",
    "review_trigger_verdict:",
    "chat_dispatch_queue:",
    "dispatch_queue:",
    "github:",
)
_FINAL_ACTION_HOLD_REF_PREFIX = "final_actions.json#hold="
_INTAKE_CLASSIFICATIONS = {
    "accepted",
    "rejected",
    "deferred",
    "requires_user_decision",
}


@dataclass(frozen=True, slots=True)
class GoalCopilotReviewEntry:
    reviewed_at: datetime
    scope: list[str]
    facts_inspected: list[str]
    observed: list[str]
    risks: list[str]
    recommendations: list[str]
    questions: list[str]
    claims_to_avoid: list[str]

    def to_markdown(self) -> str:
        return (
            "\n".join(
                [
                    f"## Review {_review_time(self.reviewed_at)}",
                    "",
                    _markdown_section("Scope", self.scope),
                    _markdown_section("Facts inspected", self.facts_inspected),
                    _markdown_section("Observed", self.observed),
                    _markdown_section("Risks", self.risks),
                    _markdown_section("Recommendations", self.recommendations),
                    _markdown_section("Questions", self.questions),
                    _markdown_section("Claims to avoid", self.claims_to_avoid),
                ]
            ).rstrip()
            + "\n"
        )


def default_goal_copilot_review_board_path(
    repo_root: Path,
    *,
    run_date: date | None = None,
) -> Path:
    resolved_date = run_date or datetime.now(tz=UTC).date()
    return repo_root / ".goal-runs" / resolved_date.isoformat() / REVIEW_BOARD_FILENAME


def append_goal_copilot_review_entry(
    *,
    repo_root: Path,
    board_path: Path,
    entry: GoalCopilotReviewEntry,
) -> Path:
    resolved_board_path = _validate_review_board_path(repo_root, board_path)
    resolved_board_path.parent.mkdir(parents=True, exist_ok=True)
    separator = "\n" if resolved_board_path.exists() and resolved_board_path.stat().st_size else ""
    with resolved_board_path.open("a", encoding="utf-8") as handle:
        handle.write(separator)
        handle.write(entry.to_markdown())
    return resolved_board_path


def build_goal_copilot_intake_decision(
    *,
    recommendation_id: str,
    classification: str,
    reason: str,
    verified_authority_refs: list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    normalized_classification = classification.strip()
    if normalized_classification not in _INTAKE_CLASSIFICATIONS:
        allowed = ", ".join(sorted(_INTAKE_CLASSIFICATIONS))
        raise ValueError(
            f"unsupported copilot intake classification: {classification!r}; {allowed}"
        )

    input_refs = [ref.strip() for ref in verified_authority_refs if ref.strip()]
    durable_refs = [ref for ref in input_refs if _is_durable_authority_ref(ref)]
    candidate_refs = [ref for ref in input_refs if not _is_durable_authority_ref(ref)]
    if normalized_classification == "accepted" and not durable_refs:
        raise ValueError("accepted copilot recommendations require durable authority refs")

    return {
        "schema_version": INTAKE_SCHEMA_VERSION,
        "advisory_only": True,
        "recommendation_id": recommendation_id,
        "classification": normalized_classification,
        "reason": reason,
        "authority_boundary": AUTHORITY_BOUNDARY,
        "intake_boundary": {
            "producer": "goal_copilot_review_board",
            "consumer": "main_goal_agent",
            "condition": "main_agent_verified_durable_authority_refs",
            "proof_boundary": INTAKE_PROOF_BOUNDARY,
            "failure_boundary": "accepted_without_durable_authority_refs_rejected",
        },
        "verified_authority_refs": durable_refs,
        "durable_authority_refs": durable_refs,
        "candidate_input_refs": candidate_refs,
        "forbidden_truth_surfaces": list(FORBIDDEN_TRUTH_SURFACES),
    }


def build_goal_copilot_launch_prompt(
    *,
    repo_path: Path,
    active_goal_prompt: str,
    review_board_path: Path,
) -> str:
    validated_board_path = _validate_review_board_path(repo_path, review_board_path)
    board_display = _display_path(repo_path, validated_board_path)
    return f"""You are the xmuse long-goal copilot.

Role:
- You are a read-only observer and correction reviewer.
- You are not the implementation agent.
- You are not proof truth, review truth, merge truth, or production truth.
- The main /goal Codex remains the only proof/phase/Git/merge coordinator.

Repository:
{repo_path}

Active goal:
{active_goal_prompt}

Authority:
{AUTHORITY_BOUNDARY}

Shared review board:
{board_display}

Hard rules:
- Do not edit source code.
- Do not edit main evidence docs or behavior/spec docs.
- Do not create branches, commits, pushes, PRs, or merges.
- Do not start xmuse services or write runtime state.
- Do not write to the main XMUSE_ROOT, chat.db, feature_lanes.json, or execution worktrees.
- Only append review entries to the shared review board.
- Treat your own output as candidate review input only, not proof truth.
- subagent output, worker output, and local tests are candidate input only.
- Verify accepted recommendations against {AUTHORITY_BOUNDARY}.

Output:
Append one concise entry to the shared review board using the template in
docs/xmuse/goal-copilot-behavior-policy.md.
"""


def _validate_review_board_path(repo_root: Path, board_path: Path) -> Path:
    root = repo_root.resolve()
    resolved = board_path.resolve(strict=False)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"copilot review board must be {REVIEW_BOARD_FILENAME} under .goal-runs/"
        ) from exc

    if relative.name != REVIEW_BOARD_FILENAME:
        raise ValueError(f"copilot review board must be named {REVIEW_BOARD_FILENAME}")
    if (
        len(relative.parts) != 3
        or relative.parts[0] != ".goal-runs"
        or not _is_iso_date(relative.parts[1])
    ):
        raise ValueError(f"copilot review board must be .goal-runs/<date>/{REVIEW_BOARD_FILENAME}")
    return resolved


def _display_path(repo_path: Path, path: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(repo_path.resolve()))
    except ValueError:
        return str(path)


def _is_durable_authority_ref(ref: str) -> bool:
    stripped_ref = ref.strip()
    if _is_final_action_hold_ref(stripped_ref):
        return True
    normalized = stripped_ref.lower()
    return any(normalized.startswith(prefix) for prefix in _DURABLE_AUTHORITY_PREFIXES)


def _is_final_action_hold_ref(ref: str) -> bool:
    if not ref.startswith(_FINAL_ACTION_HOLD_REF_PREFIX):
        return False
    hold_id = ref.removeprefix(_FINAL_ACTION_HOLD_REF_PREFIX).strip()
    return bool(hold_id)


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _review_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _markdown_section(title: str, values: list[str]) -> str:
    items = [_one_line(value) for value in values if _one_line(value)]
    if not items:
        items = ["None"]
    lines = [f"{title}:"]
    lines.extend(f"- {item}" for item in items)
    return "\n".join(lines) + "\n"


def _one_line(value: str) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").strip()
