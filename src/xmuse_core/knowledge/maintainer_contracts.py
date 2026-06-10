"""Contracts and low-level helpers for Xmuse error-knowledge maintenance."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any

FEATURE_ID = "xmuse-error-knowledge"
SCHEMA_VERSION = "1.0"
EXTRACTOR_VERSION = "xmuse-error-knowledge-2026-05-25"

DEFAULT_ALLOWED_WRITES = [
    "xmuse/knowledge/**",
    f"xmuse/work/features/{FEATURE_ID}/result.md",
    f"xmuse/work/features/{FEATURE_ID}/review_verdict.json",
    f"xmuse/work/features/{FEATURE_ID}/ack.json",
    f"xmuse/work/features/{FEATURE_ID}/slave_state.json",
]
BOOTSTRAP_WRITES = [
    f"xmuse/work/features/{FEATURE_ID}/ack.json",
    f"xmuse/work/features/{FEATURE_ID}/result.md",
]
REQUIRED_INPUTS = [
    "xmuse/master_state.json",
    "xmuse/master_status.json",
    "xmuse/contracts/master_dispatch_template.json",
    "xmuse/contracts/slave_dispatch_template.json",
    "xmuse/contracts/knowledge_maintainer_template.json",
]
OPTIONAL_INPUTS = [
    "xmuse/reports/latest.json",
    "xmuse/reports/latest.md",
]
SCAN_GLOBS = [
    "xmuse/work/features/*/ack.json",
    "xmuse/work/features/*/result.md",
    "xmuse/work/features/*/review_verdict.json",
    "xmuse/work/features/*/execute_review.md",
    "xmuse/work/features/*/slave_state.json",
    "xmuse/work/features/*/plan_final.md",
    "xmuse/master/features/*/master_review.json",
    "xmuse/master/features/*/integrated_tests.json",
    "xmuse/approvals/*/merge_approval_request.json",
    "xmuse/approvals/*/merge_approval.json",
    "xmuse/approvals/*/merge_decision.json",
    "xmuse/approvals/*/post_merge_verification.json",
]
FINAL_WORK_ARTIFACTS = ["ack.json", "result.md", "review_verdict.json"]
DETERMINISTIC_INVARIANTS = {
    "missing_required_artifact",
    "invalid_json_artifact",
    "ack_non_usable",
    "review_verdict_not_pass",
    "integrated_tests_missing",
    "integrated_tests_not_passed",
    "merge_requested_without_approval",
    "approval_artifact_digest_mismatch",
    "stale_target_head",
    "write_boundary_violation",
}
NON_PROMOTABLE_PREFIXES = (
    "environment:",
    "transient:",
    "baseline_drift:",
    "dirty_worktree:",
    "missing_optional:",
)


class SimulatedWriteFailure(RuntimeError):
    """Raised by tests to stop after a bounded number of object writes."""


@dataclass(frozen=True)
class Finding:
    feature_id: str
    artifact_path: Path
    artifact_type: str
    fingerprint: str
    summary: str
    evidence: str
    root_cause_status: str
    deterministic_invariant: str | None = None
    verification_evidence: bool = False
    source_run_id: str | None = None
    promotion_suppressed: bool = False


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def stable_id(prefix: str, *parts: str, length: int = 16) -> str:
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:length]
    return f"{prefix}-{digest}"


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def normalize_command(command: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", command.strip().lower()).strip("-")
    return value[:80] or "unknown"


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _path_matches(pattern: str, rel_path: str) -> bool:
    pattern = pattern.strip("/")
    rel_path = rel_path.strip("/")
    if pattern.endswith("/**"):
        base = pattern[:-3].rstrip("/")
        return rel_path == base or rel_path.startswith(base + "/")
    return rel_path == pattern


def _safe_relative(root: Path, path: Path) -> str:
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    return resolved_path.relative_to(resolved_root).as_posix()


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _atomic_write_json(path: Path, payload: Any) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def artifact_type_for(path: Path) -> str:
    name = path.name
    if name == "ack.json":
        return "ack"
    if name == "review_verdict.json":
        return "review_verdict"
    if name == "result.md":
        return "result"
    if name == "execute_review.md":
        return "execute_review"
    if name == "slave_state.json":
        return "slave_state"
    if name == "plan_final.md":
        return "plan_final"
    if name == "master_review.json":
        return "master_review"
    if name == "integrated_tests.json":
        return "integrated_tests"
    if name.startswith("merge_approval_request"):
        return "merge_approval_request"
    if name.startswith("merge_approval"):
        return "merge_approval"
    if name.startswith("merge_decision"):
        return "merge_decision"
    if name.startswith("post_merge_verification"):
        return "post_merge_verification"
    return path.suffix.lstrip(".") or "artifact"


def feature_id_for(root: Path, path: Path) -> str:
    rel = _safe_relative(root, path)
    parts = rel.split("/")
    if len(parts) >= 4 and parts[:3] == ["xmuse", "work", "features"]:
        return parts[3]
    if len(parts) >= 4 and parts[:3] == ["xmuse", "master", "features"]:
        return parts[3]
    if len(parts) >= 3 and parts[:2] == ["xmuse", "approvals"]:
        return parts[2]
    return "global"


def source_ref(
    root: Path,
    path: Path,
    *,
    artifact_type: str,
    feature_id: str,
    digest: str,
    source_run_id: str | None = None,
) -> dict[str, Any]:
    ref = {
        "path": _safe_relative(root, path),
        "digest": digest,
        "artifact_type": artifact_type,
        "feature_id": feature_id,
    }
    if source_run_id:
        ref["source_run_id"] = source_run_id
    return ref


def source_digest_for_refs(refs: list[dict[str, Any]]) -> str:
    return sha256_text(canonical_json(refs))


def unique_source_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for ref in refs:
        unique[(str(ref.get("path")), str(ref.get("digest")))] = ref
    return [unique[key] for key in sorted(unique)]


def validate_contract(root: str | Path) -> dict[str, Any]:
    root = Path(root)
    contract_path = root / "xmuse/contracts/knowledge_maintainer_template.json"
    if not contract_path.exists():
        return {
            "valid": False,
            "bootstrap": True,
            "contract": None,
            "blockers": ["knowledge_maintainer_template.json missing"],
        }
    try:
        contract = _read_json(contract_path)
    except JSONDecodeError as exc:
        return {
            "valid": False,
            "bootstrap": True,
            "contract": None,
            "blockers": [f"knowledge_maintainer_template.json invalid JSON: {exc.msg}"],
        }

    blockers: list[str] = []
    if contract.get("role") != "knowledge_maintainer":
        blockers.append("knowledge_maintainer_template.json role must be knowledge_maintainer")
    allowed = contract.get("allowed_writes")
    if not isinstance(allowed, list) or sorted(allowed) != sorted(DEFAULT_ALLOWED_WRITES):
        blockers.append(
            "allowed_writes must exactly match the knowledge maintainer contract"
        )
    bootstrap = contract.get("bootstrap_failure_writes")
    if not isinstance(bootstrap, list) or sorted(bootstrap) != sorted(BOOTSTRAP_WRITES):
        blockers.append(
            "knowledge_maintainer_template.json bootstrap writes must be ack/result only"
        )
    required_inputs = contract.get("required_inputs")
    if not isinstance(required_inputs, list) or sorted(required_inputs) != sorted(REQUIRED_INPUTS):
        blockers.append(
            "knowledge_maintainer_template.json required_inputs must match contract"
        )
    return {
        "valid": not blockers,
        "bootstrap": bool(blockers),
        "contract": contract,
        "blockers": blockers,
    }


def write_bootstrap_blocked(root: Path, blockers: list[str], *, run_id: str, now: str) -> dict:
    feature_dir = root / f"xmuse/work/features/{FEATURE_ID}"
    feature_dir.mkdir(parents=True, exist_ok=True)
    ack = {
        "feature_id": FEATURE_ID,
        "ack_level": "blocked",
        "mode": "bootstrap_no_op",
        "knowledge_run_id": run_id,
        "recorded_at": now,
        "blockers": blockers,
        "allowed_writes_used": BOOTSTRAP_WRITES,
        "knowledge_files_written": False,
    }
    result = "\n".join(
        [
            f"# feature: {FEATURE_ID}",
            "",
            "## Bootstrap No-Op",
            "",
            "The knowledge maintainer did not enter normal authorized mode.",
            "",
            "Blockers:",
            *[f"- {blocker}" for blocker in blockers],
            "",
            "Writes performed: `ack.json` and `result.md` only.",
            "",
        ]
    )
    _atomic_write_json(feature_dir / "ack.json", ack)
    _atomic_write_text(feature_dir / "result.md", result)
    return {"status": "blocked", "blockers": blockers, "knowledge_run_id": run_id}


_write_bootstrap_blocked = write_bootstrap_blocked
