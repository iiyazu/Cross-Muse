from __future__ import annotations

from dataclasses import replace

import pytest

from xmuse_core.chat.room_execution_profiles import (
    EXECUTION_GATE_PROFILE_SCHEMA,
    RoomExecutionProfileError,
    build_execution_gate_plan,
    execution_gate_plan_from_mapping,
    gate_ids_for_profile_paths,
    get_execution_gate_profile,
)

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def test_fixed_profiles_are_server_owned_and_contain_no_command_text() -> None:
    docs = get_execution_gate_profile("docs/v1")
    python = get_execution_gate_profile("python-uv/v1")
    xmuse = get_execution_gate_profile("xmuse-monorepo/v2")

    assert docs.schema_version == EXECUTION_GATE_PROFILE_SCHEMA
    assert docs.gate_ids == ("patch_diff_check",)
    assert python.gate_ids == (
        "patch_diff_check",
        "python_uv_ruff",
        "python_uv_mypy",
        "python_uv_pytest",
    )
    assert xmuse.gate_ids[-1] == "frontend_build"
    assert all(profile.profile_digest.startswith("sha256:") for profile in (docs, python, xmuse))
    assert set(xmuse.safe_reference()) == {
        "schema_version",
        "profile_id",
        "revision",
        "gate_ids",
    }


@pytest.mark.parametrize(
    ("profile_id", "paths", "expected"),
    [
        ("docs/v1", ("README.md",), ("patch_diff_check",)),
        (
            "python-uv/v1",
            ("README.md",),
            ("patch_diff_check", "python_uv_ruff", "python_uv_mypy", "python_uv_pytest"),
        ),
        (
            "python-uv/v1",
            ("src/example.py", "docs/design.md"),
            ("patch_diff_check", "python_uv_ruff", "python_uv_mypy", "python_uv_pytest"),
        ),
        (
            "xmuse-monorepo/v2",
            ("src/xmuse_core/example.py",),
            ("patch_diff_check", "backend_ruff", "backend_mypy", "backend_pytest"),
        ),
        (
            "xmuse-monorepo/v2",
            ("src/runtime.md", "tests/fixtures/README.txt"),
            ("patch_diff_check", "backend_ruff", "backend_mypy", "backend_pytest"),
        ),
        (
            "xmuse-monorepo/v2",
            ("frontend/app/page.tsx",),
            (
                "patch_diff_check",
                "frontend_typecheck",
                "frontend_lint",
                "frontend_vitest",
                "frontend_build",
            ),
        ),
        (
            "xmuse-monorepo/v2",
            ("frontend/README.md",),
            (
                "patch_diff_check",
                "frontend_typecheck",
                "frontend_lint",
                "frontend_vitest",
                "frontend_build",
            ),
        ),
        (
            "xmuse-monorepo/v2",
            ("README.md",),
            (
                "patch_diff_check",
                "backend_ruff",
                "backend_mypy",
                "backend_pytest",
                "frontend_typecheck",
                "frontend_lint",
                "frontend_vitest",
                "frontend_build",
            ),
        ),
    ],
)
def test_profile_paths_resolve_only_ordered_fixed_gates(profile_id, paths, expected) -> None:
    assert gate_ids_for_profile_paths(profile_id, paths) == expected


@pytest.mark.parametrize(
    ("profile_id", "paths", "code"),
    [
        ("unknown/v1", ("README.md",), "room_execution_gate_profile_unknown"),
        ("docs/v1", ("src/example.py",), "room_execution_gate_path_uncovered"),
        ("python-uv/v1", ("package-lock.json",), "room_execution_gate_path_uncovered"),
        ("xmuse-monorepo/v2", ("deploy/prod.yml",), "room_execution_gate_path_uncovered"),
        ("docs/v1", ("prompts/system.txt",), "room_execution_gate_path_uncovered"),
        ("docs/v1", ("secrets.txt",), "room_execution_gate_path_uncovered"),
        ("docs/v1", ("NOTES.md",), "room_execution_gate_path_uncovered"),
        ("docs/v1", ("docs/build.js",), "room_execution_gate_path_uncovered"),
        ("xmuse-monorepo/v2", (), "room_execution_gate_paths_empty"),
    ],
)
def test_unknown_profiles_and_uncovered_paths_fail_closed(profile_id, paths, code) -> None:
    with pytest.raises(RoomExecutionProfileError) as raised:
        gate_ids_for_profile_paths(profile_id, paths)
    assert raised.value.code == code


def test_private_plan_round_trip_is_strict_and_safe_reference_hides_digests() -> None:
    plan = build_execution_gate_plan(
        profile_id="python-uv/v1",
        changed_paths=("src/example.py",),
        repository_manifest_digest=DIGEST_A,
        toolchain_capability_digest=DIGEST_B,
    )

    assert (
        execution_gate_plan_from_mapping(plan.internal_mapping(), changed_paths=("src/example.py",))
        == plan
    )
    assert set(plan.safe_reference()) == {
        "schema_version",
        "profile_id",
        "revision",
        "gate_ids",
    }
    assert not any("digest" in key for key in plan.safe_reference())

    tampered = plan.internal_mapping()
    tampered["gate_ids"] = ["patch_diff_check"]
    with pytest.raises(RoomExecutionProfileError) as raised:
        execution_gate_plan_from_mapping(tampered, changed_paths=("src/example.py",))
    assert raised.value.code == "room_execution_gate_plan_invalid"

    with pytest.raises(RoomExecutionProfileError) as raised:
        execution_gate_plan_from_mapping(
            replace(plan, profile_digest=DIGEST_B).internal_mapping(),
            changed_paths=("src/example.py",),
        )
    assert raised.value.code == "room_execution_gate_plan_invalid"
