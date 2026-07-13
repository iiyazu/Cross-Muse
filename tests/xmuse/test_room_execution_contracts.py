from __future__ import annotations

import pytest

from xmuse_core.chat.room_execution_contracts import (
    RoomExecutionContractError,
    low_risk_patch_eligible,
    normalize_execution_patch,
    normalize_proposal_assessments,
)


def patch_payload(
    *,
    path: str = "src/xmuse_core/example.py",
    diff: str | None = None,
    allowed_files: list[str] | None = None,
) -> dict[str, object]:
    effective = diff or (
        f"diff --git a/{path} b/{path}\n"
        "index 1111111..2222222 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    return {
        "schema_version": "room_execution_patch/v1",
        "base_head": "a" * 40,
        "summary": "Change one line",
        "unified_diff": effective,
        "allowed_files": allowed_files or [path],
    }


def test_patch_normalizes_line_endings_and_has_distinct_stable_digests() -> None:
    first = normalize_execution_patch(patch_payload())
    second_payload = patch_payload()
    second_payload["unified_diff"] = str(second_payload["unified_diff"]).replace("\n", "\r\n")
    second = normalize_execution_patch(second_payload)

    assert first == second
    assert first.candidate_digest.startswith("sha256:")
    assert first.patch_sha256.startswith("sha256:")
    assert first.candidate_digest != first.patch_sha256
    assert first.allowed_files == ("src/xmuse_core/example.py",)
    assert first.modify_only is True
    assert low_risk_patch_eligible(first) is True


@pytest.mark.parametrize(
    ("diff", "allowed", "code"),
    [
        (
            "diff --git a/../escape.py b/../escape.py\n--- a/../escape.py\n"
            "+++ b/../escape.py\n@@ -1 +1 @@\n-a\n+b\n",
            ["../escape.py"],
            "room_execution_patch_path_invalid",
        ),
        (
            "diff --git a/.git/config b/.git/config\n--- a/.git/config\n"
            "+++ b/.git/config\n@@ -1 +1 @@\n-a\n+b\n",
            [".git/config"],
            "room_execution_patch_path_invalid",
        ),
        (
            "diff --git a/.gitmodules b/.gitmodules\n--- a/.gitmodules\n"
            "+++ b/.gitmodules\n@@ -1 +1 @@\n-a\n+b\n",
            [".gitmodules"],
            "room_execution_patch_submodule_forbidden",
        ),
        (
            "diff --git a/a.py b/b.py\nsimilarity index 100%\nrename from a.py\nrename to b.py\n",
            ["b.py"],
            "room_execution_patch_rename_forbidden",
        ),
        (
            "diff --git a/a.py b/a.py\nold mode 100644\nnew mode 100755\n",
            ["a.py"],
            "room_execution_patch_metadata_forbidden",
        ),
        (
            "diff --git a/a.bin b/a.bin\nnew file mode 100644\n"
            "index 0000000..1111111\nGIT binary patch\nliteral 1\nA\n",
            ["a.bin"],
            "room_execution_patch_binary_forbidden",
        ),
        (
            "diff --git a/vendor b/vendor\nindex 1111111..2222222 160000\n"
            "--- a/vendor\n+++ b/vendor\n@@ -1 +1 @@\n"
            "-Subproject commit 1111111\n+Subproject commit 2222222\n",
            ["vendor"],
            "room_execution_patch_submodule_forbidden",
        ),
    ],
)
def test_adversarial_patch_metadata_is_rejected(diff: str, allowed: list[str], code: str) -> None:
    with pytest.raises(RoomExecutionContractError) as exc_info:
        normalize_execution_patch(patch_payload(diff=diff, allowed_files=allowed))
    assert exc_info.value.code == code


def test_allowed_files_are_exact_and_unknown_assets_are_not_low_risk() -> None:
    with pytest.raises(RoomExecutionContractError) as exc_info:
        normalize_execution_patch(
            patch_payload(allowed_files=["src/xmuse_core/example.py", "extra.py"])
        )
    assert exc_info.value.code == "room_execution_patch_allowed_files_mismatch"

    asset = normalize_execution_patch(patch_payload(path="assets/logo.svg"))
    assert low_risk_patch_eligible(asset) is False


def test_add_delete_are_manual_valid_and_assessments_are_bounded() -> None:
    added = normalize_execution_patch(
        patch_payload(
            path="src/xmuse_core/new.py",
            diff=(
                "diff --git a/src/xmuse_core/new.py b/src/xmuse_core/new.py\n"
                "new file mode 100644\nindex 0000000..1111111\n--- /dev/null\n"
                "+++ b/src/xmuse_core/new.py\n@@ -0,0 +1 @@\n+new\n"
            ),
        )
    )
    deleted = normalize_execution_patch(
        patch_payload(
            path="src/xmuse_core/old.py",
            diff=(
                "diff --git a/src/xmuse_core/old.py b/src/xmuse_core/old.py\n"
                "deleted file mode 100644\nindex 1111111..0000000\n"
                "--- a/src/xmuse_core/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n"
            ),
        )
    )
    assert [item.change_type for item in added.files + deleted.files] == ["add", "delete"]
    assert not low_risk_patch_eligible(added)
    assert not low_risk_patch_eligible(deleted)

    value = [
        {
            "proposal_id": "prop_1",
            "candidate_digest": "sha256:" + "1" * 64,
            "assessment": "endorse",
            "rationale": "complete diff reviewed",
        }
    ]
    assert normalize_proposal_assessments(value)[0].assessment == "endorse"
    with pytest.raises(RoomExecutionContractError):
        normalize_proposal_assessments(value + value)
