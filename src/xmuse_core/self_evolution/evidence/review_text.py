"""Review-summary text parsing extracted from SelfEvolutionController.

Parses free-form reviewer prose (markdown-ish) into bounded structured
signals: scope refs, findings, verification confirmations, residual risks,
and recovery reasons. All functions are pure; they build on the bounded
text-compaction primitives in :mod:`evidence.text`.
"""

from __future__ import annotations

import re
from typing import Any

from xmuse_core.self_evolution.evidence.text import (
    compact_confirmation_text,
    compact_risk_text,
    compact_signal_text,
)


def review_scope_refs(value: Any) -> list[str]:
    """Extract up to 3 file refs from the scope/summary section of a review."""
    if not isinstance(value, str) or not value.strip():
        return []

    refs: list[str] = []
    seen: set[str] = set()
    for raw_line in value.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        normalized = _normalized_review_section_name(line)
        if normalized.startswith(("verification", "residual risk")):
            break
        if normalized in {"findings", "finding"}:
            continue
        for ref in _review_scope_refs_from_line(line):
            if ref in seen:
                continue
            refs.append(ref)
            seen.add(ref)
            if len(refs) >= 3:
                return refs
    return refs


def _review_scope_refs_from_line(line: str) -> list[str]:
    candidates = re.findall(r"\]\(([^)]+)\)", line)
    candidates.extend(re.findall(r"`([^`]*(?:src|tests|xmuse|docs)/[^`]*)`", line))
    candidates.extend(
        re.findall(
            r"(?<![\w./-])(?:src|tests|xmuse|docs)/[^\s),;`]+"
            r"\.(?:py|md|json|toml|yaml|yml|ts|tsx|js|css)(?::\d+)?",
            line,
        )
    )
    refs: list[str] = []
    for candidate in candidates:
        ref = _normalize_review_scope_ref(candidate)
        if ref:
            refs.append(ref)
    return refs


def _normalized_review_section_name(line: str) -> str:
    normalized = re.sub(r"^#+\s*", "", line).strip()
    normalized = normalized.replace("**", "").replace("__", "").replace("`", "")
    return normalized.strip().lower().rstrip(":")


def _normalize_review_scope_ref(value: str) -> str | None:
    ref = value.strip().strip("<>()[]`'\".,;")
    if not ref:
        return None
    ref = ref.replace("\\", "/").split("#", 1)[0].split("?", 1)[0]
    ref = re.sub(r":\d+(?::\d+)?$", "", ref)

    for marker in ("src/", "tests/", "xmuse/", "docs/"):
        index = ref.find(marker)
        if index >= 0:
            ref = ref[index:]
            break
    else:
        return None

    if not re.search(r"\.(?:py|md|json|toml|yaml|yml|ts|tsx|js|css)$", ref):
        return None
    return ref


def review_finding_summaries(value: Any) -> list[str]:
    """Extract up to 2 severity-prefixed finding lines from a review."""
    if not isinstance(value, str) or not value.strip():
        return []

    findings: list[str] = []
    for raw_line in value.splitlines():
        line = compact_signal_text(raw_line, 220)
        if not line:
            continue
        line = re.sub(r"^(?:[-*]\s+|\d+[.)]\s*)", "", line).strip()
        line = line.replace("**", "").replace("__", "")
        if line.lower() in {"findings", "finding", "findings:"}:
            continue
        if not _is_review_finding_line(line):
            continue
        findings.append(line)
        if len(findings) >= 2:
            break
    return findings


def review_confirmation_summaries(value: Any) -> list[str]:
    """Extract up to 2 verification confirmations from a review summary."""
    if not isinstance(value, str) or not value.strip():
        return []

    verification_confirmations: list[str] = []
    general_confirmations: list[str] = []
    in_verification_block = False
    pending_verification_command: str | None = None
    for raw_line in value.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        line = re.sub(r"^(?:[-*]\s+|\d+[.)]\s*)", "", line).strip()
        line = line.replace("**", "").replace("__", "").replace("`", "")
        lowered = line.lower().rstrip(":")
        if lowered.startswith("verification"):
            in_verification_block = True
            pending_verification_command = None
            continue
        if lowered in {"findings", "finding"}:
            in_verification_block = False
            pending_verification_command = None
            continue

        if lowered.startswith(("no blocking findings", "no findings")):
            confirmation_line = _confirmation_evidence_text(line)
            if confirmation_line:
                general_confirmations.append(
                    compact_confirmation_text(confirmation_line, 220)
                )
        elif in_verification_block and _verification_confirmation_passed(
            _confirmation_evidence_lowered(line)
        ):
            confirmation_line = _confirmation_evidence_text(line)
            if pending_verification_command and _is_result_confirmation(
                confirmation_line.lower().rstrip(":")
            ):
                result_text = _result_confirmation_text(confirmation_line)
                confirmation_line = f"{pending_verification_command} -> {result_text}"
            pending_verification_command = None
            verification_confirmations.append(
                compact_confirmation_text(confirmation_line, 220)
            )
        elif in_verification_block and _looks_like_verification_command(line):
            pending_verification_command = compact_confirmation_text(line, 220)
        elif lowered.startswith("gate report") and "passing" in lowered:
            pending_verification_command = None
            confirmation_line = _confirmation_evidence_text(line)
            if confirmation_line:
                verification_confirmations.append(
                    compact_confirmation_text(confirmation_line, 220)
                )

    max_confirmations = 2
    confirmations = _select_review_confirmations(
        verification_confirmations,
        max_confirmations=max_confirmations,
    )
    if len(confirmations) < max_confirmations and general_confirmations:
        confirmations.append(general_confirmations[0])
    return confirmations


def review_risk_summaries(value: Any) -> list[str]:
    """Extract up to 2 residual-risk lines from a review summary."""
    if not isinstance(value, str) or not value.strip():
        return []

    risks: list[str] = []
    in_residual_risk_block = False
    in_findings_block = False
    for raw_line in value.splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        line = re.sub(r"^(?:[-*]\s+|\d+[.)]\s*)", "", line).strip()
        line = line.replace("**", "").replace("__", "").replace("`", "")
        lowered = line.lower().rstrip(":")
        inline_risk = _inline_residual_risk_text(line)
        starts_residual_risk = _starts_residual_risk_block(line)
        if starts_residual_risk or lowered == "residual risk":
            in_findings_block = False
            in_residual_risk_block = True
            if inline_risk:
                risks.append(compact_risk_text(inline_risk, 220))
            if len(risks) >= 2:
                break
            continue
        if _is_review_section_heading(line):
            in_residual_risk_block = False
            in_findings_block = lowered in {"findings", "finding"}
            continue
        if _is_review_finding_line(line):
            in_findings_block = True
        if in_findings_block:
            continue
        if inline_risk:
            risks.append(compact_risk_text(inline_risk, 220))
            in_residual_risk_block = starts_residual_risk
        elif in_residual_risk_block:
            risks.append(compact_risk_text(line, 220))

        if len(risks) >= 2:
            break
    return risks


def review_recovery_reason(lane: dict[str, Any]) -> str | None:
    """Derive a normalized recovery reason from a lane's review fields."""
    if lane.get("review_recovery_reason"):
        return compact_signal_text(str(lane["review_recovery_reason"]), 80)
    if lane.get("review_fallback_reason"):
        return None

    text_parts = [
        str(lane.get("manual_recovery") or ""),
        str(lane.get("review_summary") or ""),
        str(lane.get("failure_reason") or ""),
    ]
    normalized = " ".join(text_parts).lower()
    if not normalized.strip():
        return None

    has_review_fallback_context = bool(lane.get("review_fallback")) or (
        "review fallback" in normalized
        or "stdout fallback" in normalized
        or "false-positive merge" in normalized
        or "false positive merge" in normalized
        or "misclassified" in normalized
    )
    if not has_review_fallback_context:
        return None

    reproduced = "reproduc" in normalized
    false_positive_merge = (
        "false-positive merge" in normalized
        or "false positive merge" in normalized
        or ("misclassified" in normalized and "merge" in normalized)
    )
    if reproduced and false_positive_merge:
        return "reproduced_finding_false_positive_merge"
    if reproduced:
        return "reproduced_finding_recovery"
    return None


def _is_review_finding_line(line: str) -> bool:
    return re.match(r"(?i)^(critical|high|medium|low)\b[: -]", line) is not None


def _inline_residual_risk_text(line: str) -> str | None:
    match = re.search(
        r"(?i)\b(?:the\s+)?(?:main\s+)?residual[-\s]+risk(?:\s+is|:)\s+(.+)",
        line,
    )
    if match is None:
        return None
    risk = match.group(1).strip()
    return risk or None


def _starts_residual_risk_block(line: str) -> bool:
    return re.match(r"(?i)^\s*residual[-\s]+risk\s*:", line) is not None


def _is_review_section_heading(line: str) -> bool:
    normalized = re.sub(r"^#+\s*", "", line).strip().lower().rstrip(":")
    return normalized in {
        "assumptions",
        "change summary",
        "findings",
        "finding",
        "open questions",
        "questions",
        "summary",
        "verification",
        "verification run",
    }


def _select_review_confirmations(
    confirmations: list[str],
    *,
    max_confirmations: int,
) -> list[str]:
    if len(confirmations) <= max_confirmations:
        return confirmations

    broader_confirmations = [
        confirmation
        for confirmation in confirmations
        if not _is_targeted_pytest_confirmation(confirmation)
    ]
    if len(broader_confirmations) >= max_confirmations:
        return broader_confirmations[:max_confirmations]
    return confirmations[:max_confirmations]


def _is_targeted_pytest_confirmation(confirmation: str) -> bool:
    lowered = confirmation.lower()
    return "pytest" in lowered and "::" in confirmation


def _verification_confirmation_passed(lowered: str) -> bool:
    if not lowered:
        return False
    if re.search(
        r"\b(?:failed|failures?|errors?|errored|non[-_ ]?zero|"
        r"traceback|exception|timeout|timed out)\b",
        lowered,
    ):
        return False
    if re.search(r"\bexit(?:ed)?[-_ ]?code\s*[:=]?\s*[1-9]\d*\b", lowered):
        return False
    return bool(
        lowered == "passed"
        or lowered.endswith("-> passed")
        or lowered.endswith(": passed")
        or "all checks passed" in lowered
        or re.search(r"\bpassed(?:\s*:\s*\d+\s+tests?)?\.?$", lowered)
        or re.search(r"\b\d+\s+passed\b", lowered)
        or re.search(
            r"\b(?:tests?|checks?|verification|suite|command)\s+passed\b",
            lowered,
        )
    )


def _confirmation_evidence_lowered(line: str) -> str:
    return _confirmation_evidence_text(line).lower().rstrip(":")


def _confirmation_evidence_text(line: str) -> str:
    parts = re.split(
        r"(?i)\s+(?:the\s+)?(?:main\s+)?residual[-\s]+risk(?:\s+is\b|:)",
        line,
        maxsplit=1,
    )
    if len(parts) == 1:
        return line.strip()
    confirmation = parts[0].strip()
    return confirmation.rstrip(" .") + "." if confirmation else ""


def _looks_like_verification_command(line: str) -> bool:
    lowered = line.lower()
    return (
        lowered.startswith(("uv run ", "pytest ", "ruff ", "python "))
        or " uv run " in lowered
        or " pytest " in lowered
        or " ruff " in lowered
    )


def _is_result_confirmation(lowered: str) -> bool:
    return lowered.startswith(("result:", "result ", "outcome:", "outcome "))


def _result_confirmation_text(line: str) -> str:
    return re.sub(r"(?i)^(?:result|outcome)\s*:?\s*", "", line).strip()
