"""Pure gate-report signal formatting extracted from SelfEvolutionController.

These shape already-loaded gate-report payloads (dicts read from
``logs/gates/**/report.json``) into bounded evidence-signal summaries. They
are pure: file IO and ref resolution stay in the controller, which passes the
parsed payloads in. They build on the text-compaction primitives in
:mod:`evidence.text`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from xmuse_core.self_evolution.evidence.text import (
    compact_middle_text,
    compact_signal_text,
)


def is_generated_signal_ref(signal: str) -> bool:
    """True if a signal ref was synthesized by the summary machinery."""
    return (
        signal.startswith("lane_counts:")
        or signal.startswith("lane_signal:")
        or signal.startswith("gate_report:")
        or signal.startswith("gate_report_resolution:")
        or signal.startswith("gate_report_diagnostic:")
        or signal.startswith("gate_report_result:")
    )


def report_message_from_mapping(item: dict[str, Any]) -> str:
    for key in ("message", "summary", "reason", "error"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)


def compact_report_messages(value: Any) -> list[str]:
    """Compact up to 2 message strings from a list of warnings/failures."""
    if not isinstance(value, list):
        return []
    messages: list[str] = []
    for item in value:
        if isinstance(item, str):
            message = item
        elif isinstance(item, dict):
            message = report_message_from_mapping(item)
        else:
            continue
        message = compact_signal_text(message, 160)
        if message:
            messages.append(message)
        if len(messages) >= 2:
            break
    return messages


def compact_gate_report_ref_for_diagnostic(report_ref: str) -> str:
    """Middle-truncate a report ref, preserving the lane-id and filename."""
    if len(report_ref) <= 84:
        return report_ref

    path_parts = Path(report_ref).parts
    if len(path_parts) >= 4:
        lane_id = path_parts[-2]
        compact_lane_id = compact_middle_text(lane_id, 44)
        candidate = "/".join([*path_parts[:-2], compact_lane_id, path_parts[-1]])
        if len(candidate) <= 84:
            return candidate
    return compact_middle_text(report_ref, 84)


def gate_report_resolution_summary(payload: dict[str, Any]) -> str:
    report_ref = str(payload.get("report_ref") or "unknown")
    profile_reasons = payload.get("profile_reasons")
    parts = [f"gate_scope={report_ref}"]
    if isinstance(profile_reasons, list) and profile_reasons:
        first = profile_reasons[0]
        if isinstance(first, dict):
            profile_id = str(first.get("profile_id") or "unknown")
            reasons = first.get("reasons")
            parts.append(f"profile={profile_id}")
            if isinstance(reasons, list) and reasons:
                parts.append(f"reason={compact_signal_text(str(reasons[0]), 80)}")
                if len(reasons) > 1:
                    parts.append(f"+{len(reasons) - 1} reasons")
        if len(profile_reasons) > 1:
            parts.append(f"+{len(profile_reasons) - 1} profiles")

    summary = " ".join(parts)
    if len(summary) > 220:
        parts[0] = f"gate_scope={compact_gate_report_ref_for_diagnostic(report_ref)}"
        summary = " ".join(parts)
    return compact_signal_text(summary, 240)


def gate_report_diagnostic_summary(payload: dict[str, Any]) -> str:
    report_ref = str(payload.get("report_ref") or "unknown")
    parts = [f"gate_diagnostic={report_ref}"]
    warnings = payload.get("warnings")
    if isinstance(warnings, list) and warnings:
        parts.append(f"warning={compact_signal_text(str(warnings[0]), 120)}")
        if len(warnings) > 1:
            parts.append(f"+{len(warnings) - 1} warnings")
    nonblocking_failures = payload.get("nonblocking_failures")
    if isinstance(nonblocking_failures, list) and nonblocking_failures:
        parts.append(
            f"nonblocking={compact_signal_text(str(nonblocking_failures[0]), 120)}"
        )
        if len(nonblocking_failures) > 1:
            parts.append(f"+{len(nonblocking_failures) - 1} nonblocking")
    summary = " ".join(parts)
    if len(summary) > 220:
        parts[0] = f"gate_diagnostic={compact_gate_report_ref_for_diagnostic(report_ref)}"
        summary = " ".join(parts)
    return compact_signal_text(summary, 260)


def gate_report_command_summary(payload: dict[str, Any]) -> str:
    argv = payload.get("argv")
    if isinstance(argv, list) and argv:
        return argv_command_summary([str(part) for part in argv])
    return str(payload.get("command") or payload.get("command_id") or "command")


def argv_command_summary(argv: list[str]) -> str:
    pytest_index = pytest_argv_index(argv)
    if pytest_index is None:
        return " ".join(argv)

    targets = [part for part in argv[pytest_index + 1 :] if is_pytest_target(part)]
    if len(targets) <= 4:
        return " ".join(argv)

    first_target_index = next(
        (
            index
            for index in range(pytest_index + 1, len(argv))
            if is_pytest_target(argv[index])
        ),
        len(argv),
    )
    shown_targets = targets[:2]
    hidden_count = len(targets) - len(shown_targets)
    return " ".join(
        [
            *argv[:first_target_index],
            *shown_targets,
            f"+{hidden_count} test files",
        ]
    )


def pytest_argv_index(argv: list[str]) -> int | None:
    for index, part in enumerate(argv):
        if Path(part).name == "pytest":
            return index
    return None


def is_pytest_target(value: str) -> bool:
    return (
        value.startswith("tests/")
        or value.startswith("test/")
        or value.endswith(".py")
        or "::" in value
    )


def legacy_gate_command_payload(
    *,
    report_ref: str,
    command_entry: Any,
    index: int,
    report_outcome: str | None,
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {
        "report_ref": report_ref,
        "command_id": f"command_{index}",
        "profile_id": "unknown",
        "outcome": report_outcome or "unknown",
    }
    if isinstance(command_entry, str) and command_entry.strip():
        payload["command"] = compact_signal_text(command_entry, 240)
        return payload
    if not isinstance(command_entry, dict):
        return None

    command = command_entry.get("command")
    if isinstance(command, str) and command.strip():
        payload["command"] = compact_signal_text(command, 240)
    argv = command_entry.get("argv")
    if isinstance(argv, list) and argv:
        payload["argv"] = [str(part) for part in argv]
    if not payload.get("command") and not payload.get("argv"):
        return None

    command_id = command_entry.get("command_id")
    if isinstance(command_id, str) and command_id:
        payload["command_id"] = command_id
    profile_id = command_entry.get("profile_id")
    if isinstance(profile_id, str) and profile_id:
        payload["profile_id"] = profile_id
    returncode = command_entry.get("returncode")
    if isinstance(returncode, int):
        payload["returncode"] = returncode
        payload["outcome"] = "passed" if returncode == 0 else "failed"
    return payload


def gate_report_outcome(report: dict[str, Any]) -> str | None:
    passed = report.get("passed")
    if isinstance(passed, bool):
        return "passed" if passed else "failed"
    status = report.get("status")
    if isinstance(status, str):
        normalized = status.strip().lower().replace("_", "-")
        if normalized in {"passed", "pass", "success", "succeeded"}:
            return "passed"
        if normalized in {"failed", "fail", "failure", "error", "errored"}:
            return "failed"
        if normalized:
            return normalized
    return None


def lane_counts_summary(signal: str) -> str:
    try:
        counts = json.loads(signal.removeprefix("lane_counts:"))
    except json.JSONDecodeError:
        return signal
    if not isinstance(counts, dict):
        return signal

    ordered_keys = [
        key
        for key in ("total", "terminal", "merged", "terminated", "running")
        if key in counts
    ]
    ordered_keys.extend(
        sorted(key for key in counts if isinstance(key, str) and key not in ordered_keys)
    )
    parts = [
        f"{key}={counts[key]}"
        for key in ordered_keys
        if isinstance(counts.get(key), int)
    ]
    return f"lane_counts {' '.join(parts)}" if parts else signal
