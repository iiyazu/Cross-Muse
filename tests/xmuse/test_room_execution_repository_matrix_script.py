from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import room_execution_repository_matrix as matrix


def test_fixed_matrix_pins_expected_repositories_profiles_and_blockers() -> None:
    assert tuple(item.scenario_id for item in matrix.REPOSITORIES) == (
        "memu-python",
        "clowder-docs",
        "memoryos-control",
        "letta-blocked",
        "mem0-blocked",
    )
    assert tuple(item.profile_id for item in matrix.REPOSITORIES) == (
        "python-uv/v1",
        "docs/v1",
        "python-uv/v1",
        "python-uv/v1",
        "python-uv/v1",
    )
    assert matrix.REPOSITORIES[3].expected_reason == ("execution_backend_dependencies_unavailable")
    assert matrix.REPOSITORIES[4].expected_reason == ("execution_gate_profile_marker_missing")
    assert all(len(item.commit) == 40 and len(item.tree) == 40 for item in matrix.REPOSITORIES)


def test_fixtures_are_digest_pinned_and_apply_to_only_allowed_paths() -> None:
    for spec in matrix.REPOSITORIES[:3]:
        fixture = matrix._fixture(spec)
        assert fixture.startswith("diff --git ")
        assert all(f" b/{path}" in fixture for path in spec.paths)


def test_fixed_python_baseline_uses_only_server_owned_commands(tmp_path: Path, monkeypatch) -> None:
    observed: list[str] = []

    class Layout:
        def __enter__(self):
            observed.append("layout-enter")
            return self

        def __exit__(self, *_args):
            observed.append("layout-close")

    profile = SimpleNamespace(gate_ids=("patch_diff_check", "python_uv_pytest"))
    monkeypatch.setattr(matrix, "get_execution_gate_profile", lambda _profile: profile)
    monkeypatch.setattr(
        matrix, "build_repository_manifest_digest", lambda *_args: "sha256:" + "a" * 64
    )
    monkeypatch.setattr(
        matrix, "build_toolchain_capability_digest", lambda *_args, **_kwargs: "sha256:" + "b" * 64
    )
    monkeypatch.setattr(matrix, "GateResourceMonitor", lambda _root: object())
    monkeypatch.setattr(matrix, "discover_sandbox_layout", lambda **_kwargs: Layout())
    monkeypatch.setattr(
        matrix,
        "probe_sandbox_capability",
        lambda *_args, **_kwargs: "sha256:" + "c" * 64,
    )

    def run_gate(_layout, gate_id, **_kwargs):
        observed.append(gate_id)
        return SimpleNamespace(status="passed", evidence_digest="sha256:" + "d" * 64)

    monkeypatch.setattr(matrix, "run_gate", run_gate)

    digest = matrix._fixed_python_baseline(tmp_path)

    assert digest.startswith("sha256:")
    assert observed == [
        "layout-enter",
        "patch_diff_check",
        "python_uv_pytest",
        "layout-close",
    ]


def test_safe_scenario_uses_opaque_frozen_refs() -> None:
    spec = matrix.REPOSITORIES[0]
    scenario = matrix._safe_scenario(
        spec,
        {
            "status": "passed",
            "gate_count": 4,
            "changed_file_count": 1,
            "execution_started": True,
            "promotion_applied": True,
            "target_bytes_exact": True,
            "sandbox_boundary_preserved": True,
            "evidence_digest": "sha256:" + "a" * 64,
        },
        source_guard_unchanged=True,
        baseline_digest="sha256:" + "b" * 64,
    )

    encoded = json.dumps(scenario)
    assert spec.commit not in encoded
    assert spec.tree not in encoded
    assert scenario["observed_status"] == "passed"
    assert scenario["reason_code"] == "accepted"


def test_main_fails_closed_without_exception_text(tmp_path: Path, monkeypatch, capsys) -> None:
    result = tmp_path / "result.json"

    class Parser:
        @staticmethod
        def parse_args():
            return SimpleNamespace(result=str(result))

    monkeypatch.setattr(matrix, "_parser", lambda: Parser())
    monkeypatch.setattr(
        matrix,
        "run_matrix",
        lambda _args: (_ for _ in ()).throw(RuntimeError("/secret token-value")),
    )

    assert matrix.main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "reason_code": "repository_matrix_internal_error",
        "schema_version": matrix.FAILURE_SCHEMA,
        "status": "failed",
    }
    assert json.loads(result.read_text(encoding="utf-8")) == payload


def test_main_returns_success_and_writes_canonical_result(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    destination = tmp_path / "result.json"
    payload = {"schema_version": matrix.RESULT_SCHEMA, "matrix_digest": "safe"}

    class Parser:
        @staticmethod
        def parse_args():
            return SimpleNamespace(result=str(destination))

    monkeypatch.setattr(matrix, "_parser", lambda: Parser())
    monkeypatch.setattr(matrix, "run_matrix", lambda _args: payload)

    assert matrix.main() == 0
    assert json.loads(capsys.readouterr().out) == payload
    assert json.loads(destination.read_text(encoding="utf-8")) == payload
