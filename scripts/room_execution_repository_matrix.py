#!/usr/bin/env python3
"""Run the fixed G2 exact-patch matrix against frozen repository objects."""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from scripts import room_execution_profile_acceptance as acceptance
from xmuse_core.chat.room_execution_profiles import get_execution_gate_profile
from xmuse_core.chat.room_execution_repository_matrix import (
    RESULT_SCHEMA,
    build_repository_matrix_result,
    evaluate_repository_matrix_result,
)
from xmuse_core.chat.room_execution_sandbox import (
    GateResourceMonitor,
    build_repository_manifest_digest,
    build_toolchain_capability_digest,
    discover_sandbox_layout,
    probe_sandbox_capability,
    run_gate,
)

FAILURE_SCHEMA = "room_execution_repository_matrix_failure/v1"


@dataclass(frozen=True)
class FrozenRepository:
    scenario_id: str
    commit: str
    tree: str
    profile_id: str
    expected_status: Literal["passed", "blocked"]
    expected_reason: str
    paths: tuple[str, ...] = ()
    fixture_name: str | None = None
    fixture_sha256: str | None = None


REPOSITORIES = (
    FrozenRepository(
        "memu-python",
        "707b80e5f4394b8e4aafff1ef23fd331a8b557f8",
        "95e53c4303d67513e0a25a544a18e4b29303dbdd",
        "python-uv/v1",
        "passed",
        "accepted",
        ("tests/test_references.py",),
        "memu-python-uv-707b80e.patch",
        "sha256:9f10ef3b5e301e4a166ac10ddab9fe0c3aacdde22365c97e0d01401aa0feb732",
    ),
    FrozenRepository(
        "clowder-docs",
        "88c5836a54d02ffa3843f60a416c660804b272de",
        "cfe9e5602ef3e6791d7d0ee60101325f3f8e349b",
        "docs/v1",
        "passed",
        "accepted",
        ("docs/features/F151-xiaoyi-channel-gateway.md",),
        "clowder-docs-88c5836.patch",
        "sha256:85ae679fed2e1e519633cc403d36b3c34c64b9e138e89063532b6b9c86bcd25a",
    ),
    FrozenRepository(
        "memoryos-control",
        "da17322d03fc5496e8e670f48e3637546da5daaa",
        "ede499017d5a25de5b25925f18886646f8091cab",
        "python-uv/v1",
        "passed",
        "accepted",
        ("tests/test_budget.py",),
        "memoryos-python-uv-da17322d.patch",
        "sha256:e074ab996329dfaab4379fa480a5b88dacbc89eea4a00e0d7b2ac61c0f1c8128",
    ),
    FrozenRepository(
        "letta-blocked",
        "1131535716e8a31c9a437f8695e25ac98f203a24",
        "8d53781fa7c433a2071b578fcbae67b68063fa10",
        "python-uv/v1",
        "blocked",
        "execution_backend_dependencies_unavailable",
    ),
    FrozenRepository(
        "mem0-blocked",
        "74d043731b9f3ef5d89dcbd435e359b885be5add",
        "f1d1e6c0f56dc7de24502a6ba78a6b2ab133deb7",
        "python-uv/v1",
        "blocked",
        "execution_gate_profile_marker_missing",
    ),
)

_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"


class RepositoryMatrixAcceptanceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fixed_python_baseline(repository: Path) -> str:
    """Run the immutable python-uv gates in the same networkless sandbox."""

    profile = get_execution_gate_profile("python-uv/v1")
    manifest_digest = build_repository_manifest_digest(repository, profile)
    capability_digest = build_toolchain_capability_digest(
        repository, profile, gate_ids=profile.gate_ids
    )
    resource_monitor = GateResourceMonitor(repository)
    evidence: list[str] = []
    with discover_sandbox_layout(
        stage=repository,
        execution_root=repository,
        gate_ids=profile.gate_ids,
        profile=profile,
        expected_toolchain_capability_digest=capability_digest,
    ) as layout:
        evidence.append(probe_sandbox_capability(layout, resource_sampler=resource_monitor))
        for gate_id in profile.gate_ids:
            result = run_gate(layout, gate_id, resource_sampler=resource_monitor)
            evidence.append(result.evidence_digest)
            if result.status != "passed":
                raise RepositoryMatrixAcceptanceError("repository_matrix_python_baseline_failed")
    return acceptance._digest(
        json.dumps(
            {
                "manifest_digest": manifest_digest,
                "capability_digest": capability_digest,
                "evidence": evidence,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _fixture(spec: FrozenRepository) -> str:
    if spec.fixture_name is None or spec.fixture_sha256 is None:
        raise RepositoryMatrixAcceptanceError("repository_matrix_fixture_missing")
    raw = (_FIXTURE_ROOT / spec.fixture_name).read_bytes()
    if acceptance._digest(raw) != spec.fixture_sha256:
        raise RepositoryMatrixAcceptanceError("repository_matrix_fixture_drift")
    return raw.decode("utf-8", errors="strict")


def _safe_scenario(
    spec: FrozenRepository,
    observed: dict[str, Any],
    *,
    source_guard_unchanged: bool,
    baseline_digest: str | None = None,
) -> dict[str, Any]:
    evidence = str(observed["evidence_digest"])
    if baseline_digest is not None:
        evidence = acceptance._digest(f"{baseline_digest}:{evidence}".encode("ascii"))
    status = "passed" if observed["status"] == "passed" else "blocked"
    return {
        "scenario_id": spec.scenario_id,
        "profile_id": spec.profile_id,
        "frozen_commit_digest": acceptance._digest(spec.commit.encode("ascii")),
        "frozen_tree_digest": acceptance._digest(spec.tree.encode("ascii")),
        "expected_status": spec.expected_status,
        "observed_status": status,
        "reason_code": ("accepted" if status == "passed" else str(observed["reason_code"])),
        "gate_count": int(observed["gate_count"]),
        "changed_file_count": int(observed["changed_file_count"]),
        "execution_started": bool(observed["execution_started"]),
        "source_guard_unchanged": source_guard_unchanged,
        "promotion_applied": bool(observed["promotion_applied"]),
        "target_bytes_exact": bool(observed["target_bytes_exact"]),
        "sandbox_boundary_preserved": bool(observed["sandbox_boundary_preserved"]),
        "evidence_digest": evidence,
    }


def run_matrix(args: argparse.Namespace) -> dict[str, Any]:
    sources = {
        "memu-python": Path(args.memu_repo).resolve(strict=True),
        "clowder-docs": Path(args.clowder_repo).resolve(strict=True),
        "memoryos-control": Path(args.memoryos_repo).resolve(strict=True),
        "letta-blocked": Path(args.letta_repo).resolve(strict=True),
        "mem0-blocked": Path(args.mem0_repo).resolve(strict=True),
    }
    dependency_sources = {
        "memu-python": Path(args.memu_dependency_repo).resolve(strict=True),
        "memoryos-control": Path(args.memoryos_dependency_repo).resolve(strict=True),
    }
    guards = {name: acceptance._source_guard(path) for name, path in sources.items()}
    dependency_guards = {
        name: acceptance._source_guard(path) for name, path in dependency_sources.items()
    }
    memu_spec = REPOSITORIES[0]
    dependency_head = (
        acceptance._git(dependency_sources["memu-python"], "rev-parse", "HEAD")
        .decode("ascii")
        .strip()
    )
    dependency_tree = (
        acceptance._git(dependency_sources["memu-python"], "rev-parse", "HEAD^{tree}")
        .decode("ascii")
        .strip()
    )
    if dependency_head != memu_spec.commit or dependency_tree != memu_spec.tree:
        raise RepositoryMatrixAcceptanceError("repository_matrix_dependency_source_mismatch")
    if acceptance._git(
        dependency_sources["memu-python"],
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=normal",
    ):
        raise RepositoryMatrixAcceptanceError("repository_matrix_dependency_source_dirty")
    scenarios: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="xmuse-repository-matrix-") as raw:
        temporary = Path(raw)
        baseline_repository = temporary / "memu-baseline"
        acceptance._clone_frozen_commit(
            dependency_sources["memu-python"],
            baseline_repository,
            frozen_commit=memu_spec.commit,
            frozen_tree=memu_spec.tree,
        )
        acceptance._link_dependencies(
            baseline_repository,
            dependency_sources["memu-python"],
            frontend=False,
        )
        baseline_digest = _fixed_python_baseline(baseline_repository)
        for index, spec in enumerate(REPOSITORIES):
            source = sources[spec.scenario_id]
            repository = temporary / f"repository-{index}"
            acceptance._clone_frozen_commit(
                source,
                repository,
                frozen_commit=spec.commit,
                frozen_tree=spec.tree,
            )
            if spec.expected_status == "passed":
                dependency_source = dependency_sources.get(spec.scenario_id, repository)
                observed = acceptance._run_scenario(
                    name=spec.scenario_id,
                    repository=repository,
                    dependency_source=dependency_source,
                    runtime=temporary / f"runtime-{index}",
                    profile_id=spec.profile_id,
                    paths=spec.paths,
                    fixture_patch=_fixture(spec),
                    link_dependencies=spec.profile_id != "docs/v1",
                )
            else:
                observed = acceptance._run_expected_blocked_scenario(
                    repository,
                    name=spec.scenario_id,
                    profile_id=spec.profile_id,
                    expected_reason=spec.expected_reason,
                )
            acceptance._require_source_guard(source, guards[spec.scenario_id])
            scenarios.append(
                _safe_scenario(
                    spec,
                    observed,
                    source_guard_unchanged=True,
                    baseline_digest=(
                        baseline_digest if spec.scenario_id == "memu-python" else None
                    ),
                )
            )
    for name, source in sources.items():
        acceptance._require_source_guard(source, guards[name])
    for name, source in dependency_sources.items():
        acceptance._require_source_guard(source, dependency_guards[name])
    result = build_repository_matrix_result(scenarios=scenarios)
    if result.get("schema_version") != RESULT_SCHEMA:
        raise RepositoryMatrixAcceptanceError("repository_matrix_result_schema_invalid")
    passed, _failed = evaluate_repository_matrix_result(result)
    if not passed:
        raise RepositoryMatrixAcceptanceError("repository_matrix_policy_failed")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memu-repo", required=True)
    parser.add_argument("--memu-dependency-repo", required=True)
    parser.add_argument("--clowder-repo", required=True)
    parser.add_argument("--memoryos-repo", required=True)
    parser.add_argument("--memoryos-dependency-repo", required=True)
    parser.add_argument("--letta-repo", required=True)
    parser.add_argument("--mem0-repo", required=True)
    parser.add_argument("--result", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = run_matrix(args)
        code = 0
    except (acceptance.AcceptanceError, RepositoryMatrixAcceptanceError) as exc:
        result = {
            "schema_version": FAILURE_SCHEMA,
            "status": "failed",
            "reason_code": exc.code,
        }
        code = 1
    except Exception:
        result = {
            "schema_version": FAILURE_SCHEMA,
            "status": "failed",
            "reason_code": "repository_matrix_internal_error",
        }
        code = 1
    payload = json.dumps(result, sort_keys=True, separators=(",", ":"))
    destination = Path(args.result)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
