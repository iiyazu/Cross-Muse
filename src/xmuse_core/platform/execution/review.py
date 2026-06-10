from __future__ import annotations

import json
import re
from typing import Any

from xmuse_core.self_evolution.recovery import TransientRecoveryError


def is_spawn_transient(exc: BaseException) -> bool:
    return isinstance(exc, (TimeoutError, ConnectionError, OSError, TransientRecoveryError))


def review_infra_failure_reason(result: Any) -> str | None:
    if getattr(result, "exit_code", 1) == 0 and not getattr(result, "timed_out", False):
        return None
    output = f"{getattr(result, 'stderr', '')}\n{getattr(result, 'stdout', '')}".lower()
    infra_markers = {
        "usage_limit": (
            "usage limit",
            "try again later",
        ),
        "rate_limit": (
            "429 too many requests",
            "too many requests",
            "rate limit",
            "exceeded retry limit",
        ),
        "temporary_unavailable": (
            "temporarily unavailable",
            "service unavailable",
            "internal server error",
        ),
    }
    for reason, markers in infra_markers.items():
        if any(marker in output for marker in markers):
            return reason
    return None


def spawn_result_transient(result: Any) -> bool:
    if getattr(result, "timed_out", False):
        return True
    return review_infra_failure_reason(result) is not None


def review_infra_reason_from_exception(exc: BaseException) -> str:
    if isinstance(exc, TransientRecoveryError):
        reason = str(exc).split(":", 1)[0]
        if reason in {"usage_limit", "rate_limit", "temporary_unavailable"}:
            return reason
    return type(exc).__name__


def review_fallback_section_heading(value: str) -> bool:
    return value in {
        "assumptions",
        "change summary",
        "open questions",
        "questions",
        "summary",
        "verification",
        "verification run",
    }


def review_fallback_positive_line(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"(?:none|no findings|no blocking findings|no issues)"
            r"(?:\s+(?:found|detected|identified))?\s*[.!:]?",
            value,
        )
    )


def review_fallback_positive_text(value: str) -> bool:
    if value.startswith("findings:"):
        value = value.split(":", 1)[1].strip()
    if value.startswith("review decision:"):
        value = value.split(":", 1)[1].strip()
    if review_fallback_positive_line(value):
        return True
    positive_patterns = (
        r"^none[.!:]\s+i\s+did\s+not\s+find\s+"
        r"(?:(?:any\s+)?(?:findings|issues|bugs|failures)|a\s+blocking\s+issue)"
        r"(?:\s+in\s+the\s+current\s+lane\s+state)?[.!:]?",
        r"^none[.!:]\s+i\s+found\s+no\s+"
        r"(?:(?:blocking\s+)?(?:findings|issues|bugs|failures)|"
        r"a\s+blocking\s+issue)"
        r"(?:\s+in\s+.*)?[.!:]?",
        r"^none[.!:]\s+the\s+(?:prior|previous)\s+blocking\s+"
        r"(?:finding|issue|bug|failure|regression)\s+"
        r"(?:is|was)\s+(?:resolved|fixed|addressed)[.:]?.*",
        r"^no\s+blocking\s+findings\s+(?:in|for)\s+(?:the\s+)?"
        r"(?:current\s+lane\s+state|current\s+diff|current\s+changes|"
        r"lane\s+diff|lane|diff|changes)"
        r"(?:\s+i\s+reviewed)?[.!:]?",
        r"^no\s+(?:findings|issues|bugs|failures)\s+(?:were\s+)?"
        r"(?:found|detected|identified)[.!:]?",
    )
    return any(re.fullmatch(pattern, value) for pattern in positive_patterns)


def review_fallback_rework_reason(stdout: str) -> str | None:
    normalized = stdout.lower()
    reproduced_patterns = (
        r"\bstill\s+reproduc(?:e|es|ed|ible|ing)\b",
        r"\breproduc(?:ed|es|ing)\s+(?:finding|bug|issue|failure)\b",
        r"\b(?:finding|bug|issue|failure)\s+still\s+reproduc",
    )
    if any(re.search(pattern, normalized) for pattern in reproduced_patterns):
        return "reproduced_finding"
    if re.search(
        r"\b(?:not|cannot|can't|do\s+not|does\s+not|unable\s+to)\s+approve(?:d)?\b",
        normalized,
    ):
        return "explicit_rejection"
    if re.search(
        r"\b(?:do\s+not|don't|cannot|can't|must\s+not)\s+merge\b",
        normalized,
    ):
        return "explicit_rejection"
    if re.search(r"\b(?:would\s+not|should\s+not)\s+merge\b", normalized):
        return "explicit_rejection"
    if re.search(r"\bnot\s+ready\s+to\s+merge\b", normalized):
        return "explicit_rejection"
    if re.search(r"\bnot\s+acceptable\s+for\s+merge\b", normalized):
        return "explicit_rejection"
    if re.search(r"\bneeds?\s+rework\b", normalized):
        return "needs_rework"
    if re.search(r"\btests?\s+(?:are\s+)?absent\b", normalized):
        return "missing_tests"
    if re.search(r"\bvalidation\s+is\s+incomplete\b", normalized):
        return "incomplete_validation"
    if re.search(r"(?m)^\s*(?:[-*]\s+)?reject(?:ed|ion)?\b\s*:?", normalized):
        return "explicit_rejection"
    if re.search(r"\bdoes\s+not\s+(?:fix|resolve|address)\b", normalized):
        return "unresolved_finding"
    if re.search(
        r"\b(?:missing\s+)?(?:coverage|test|tests|failure|bug|issue|finding|regression)"
        r"\s+remains?\b",
        normalized,
    ):
        return "unresolved_finding"
    if re.search(r"\bmissing\s+(?:coverage|test|tests)\b", normalized):
        return "missing_coverage"
    if re.search(r"\bmust\s+fix\b", normalized):
        return "must_fix"
    negated_blocking_pattern = re.compile(
        r"\b(?:did\s+not|do\s+not|does\s+not|no|not)\s+"
        r"(?:find|see|identify|detect|have|found)?\s*"
        r"(?:a\s+)?blocking\s+(?:finding|issue|bug|failure|regression)\b"
    )
    in_findings_section = False
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        stripped = re.sub(r"^(?:[-*]\s+|\d+[.)]\s*)", "", line).strip()
        stripped = re.sub(r"^#{1,6}\s+", "", stripped).strip()
        stripped = stripped.replace("**", "").replace("__", "")
        lowered = stripped.lower()
        section_name = lowered.rstrip(":")
        if section_name in {"findings", "finding"}:
            in_findings_section = True
            continue
        if review_fallback_section_heading(section_name):
            in_findings_section = False
            continue
        if review_fallback_positive_text(lowered):
            if in_findings_section:
                in_findings_section = False
            continue
        if re.match(r"(?i)^(critical|important|high|medium|low)\b[: -]", stripped):
            return "severity_finding"
        if re.search(r"(?i)\bblocking\s+(?:finding|issue|bug|failure|regression)\b", stripped):
            if negated_blocking_pattern.search(lowered):
                continue
            if re.search(
                r"\b(?:prior|previous)\s+blocking\s+"
                r"(?:finding|issue|bug|failure|regression)\s+"
                r"(?:is|was)\s+(?:resolved|fixed|addressed)\b",
                lowered,
            ):
                continue
            return "blocking_finding"
        if in_findings_section:
            return "findings_section"
    return None


def review_fallback_positive_reason(stdout: str) -> str | None:
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        stripped = re.sub(r"^(?:[-*]\s+|\d+[.)]\s*)", "", line).strip()
        stripped = re.sub(r"^#{1,6}\s+", "", stripped).strip()
        stripped = stripped.replace("**", "").replace("__", "")
        lowered = stripped.lower()
        if lowered.startswith("findings:"):
            lowered = lowered.split(":", 1)[1].strip()
        if lowered.startswith("review decision:"):
            lowered = lowered.split(":", 1)[1].strip()
        if review_fallback_positive_line(lowered):
            token = lowered.split()[0].rstrip(".!:")
            if token == "no":
                return "positive_" + "_".join(lowered.rstrip(".!:").split()[:2])
            return f"positive_{token}"
        if not review_fallback_positive_text(lowered):
            continue
        token = lowered.split()[0].rstrip(".!:")
        if token == "no":
            return "positive_" + "_".join(lowered.rstrip(".!:").split()[:2])
        return f"positive_{token}"
    return None


def infer_review_fallback(stdout: str) -> tuple[str, str, str]:
    review_text = _extract_review_text(stdout)
    summary = review_text.strip()[-4000:] or "review completed without MCP status update"
    normalized = review_text.lower()
    verdict = _parse_verdict_line(review_text)
    if verdict == "merge":
        return "reviewed", summary, "verdict_merge"
    if verdict in {"rework", "terminate"}:
        return "rejected", summary, f"verdict_{verdict}"
    explicit_merge_reason = _explicit_merge_reason(review_text)
    if explicit_merge_reason:
        return "reviewed", summary, explicit_merge_reason
    approval_markers = (
        "approved",
        "approve",
    )
    negative_markers = (
        "high:",
        "medium:",
        "must fix",
        "still reproduces",
        "does not fix",
        "does not resolve",
    )
    rework_reason = review_fallback_rework_reason(review_text)
    if rework_reason:
        return "rejected", summary, rework_reason
    positive_reason = review_fallback_positive_reason(review_text)
    if positive_reason:
        return "reviewed", summary, positive_reason
    if any(marker in normalized for marker in approval_markers):
        return "reviewed", summary, "approval_marker"
    if any(marker in normalized for marker in negative_markers):
        return "rejected", summary, "negative_marker"
    # Fail-safe: unknown review text cannot be trusted as an approval.
    # Defaulting to merge on unrecognised output is a High-severity risk —
    # the review god may have produced a finding we cannot parse.
    return "rejected", summary, "unknown_review_text"


def _parse_verdict_line(stdout: str) -> str | None:
    for raw_line in stdout.splitlines():
        line = _normalize_review_marker_line(raw_line)
        match = re.fullmatch(r"(?i)verdict\s*:\s*(merge|rework|terminate)\s*\.?", line)
        if match:
            return match.group(1).lower()
    return None


def _extract_review_text(stdout: str) -> str:
    """Return human review text from known CLI JSON envelopes."""
    text = stdout.strip()
    if not text:
        return stdout
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return stdout
    if not isinstance(payload, dict):
        return stdout
    result = payload.get("result")
    if isinstance(result, str) and result.strip():
        return result
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message
    return stdout


def _explicit_merge_reason(stdout: str) -> str | None:
    for raw_line in stdout.splitlines():
        lowered = _normalize_review_marker_line(raw_line).lower().strip(" .:")
        if re.fullmatch(r"verdict\s*:?\s*merge", lowered):
            return "explicit_merge_verdict"
        if re.fullmatch(
            r"(?:review\s+)?decision\s*:?\s*(?:pass\s*/\s*)?merge",
            lowered,
        ):
            return "explicit_merge_decision"
        if re.fullmatch(r"(?:review\s+)?decision\s*:?\s*pass\s*/\s*merge", lowered):
            return "explicit_merge_decision"
    return None


def _normalize_review_marker_line(value: str) -> str:
    line = re.sub(r"^(?:[-*]\s+|\d+[.)]\s*)", "", value.strip()).strip()
    line = re.sub(r"^#{1,6}\s+", "", line).strip()
    return line.replace("**", "").replace("__", "").replace("`", "").strip()
