"""Offline tests for the brownfield board evaluation script (no providers)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import board_brownfield_eval as brownfield
from xmuse_core.chat.room_board import normalize_charter
from xmuse_core.chat.room_board_integration import INTEGRATION_REF_PREFIX
from xmuse_core.chat.room_database import RoomDatabase


def _plan(**overrides: object) -> dict[str, object]:
    plan: dict[str, object] = {
        "title": "demo",
        "modules": [
            {
                "module_id": "a",
                "title": "tar-parser",
                "paths": ["packages/tar-parser/**"],
                "task": "Do A " * 400,
            },
            {
                "module_id": "b",
                "title": "headers",
                "paths": ["packages/headers/**", "packages/cookie/**"],
                "task": "Do B",
            },
        ],
    }
    plan.update(overrides)
    return plan


def test_load_plan_validates_modules(tmp_path: Path) -> None:
    good = tmp_path / "plan.json"
    good.write_text(json.dumps(_plan()), encoding="utf-8")
    assert [m["module_id"] for m in brownfield.load_plan(good)["modules"]] == ["a", "b"]

    for broken in (
        _plan(modules=[]),
        _plan(modules=[{"module_id": "a", "paths": ["x/**"], "task": ""}]),
        _plan(modules=[{"module_id": "a", "paths": [], "task": "t"}]),
        _plan(
            modules=[
                {"module_id": "a", "paths": ["x/**"], "task": "t"},
                {"module_id": "a", "paths": ["y/**"], "task": "t"},
            ]
        ),
        _plan(modules=[{"module_id": "a", "paths": ["x/**"], "task": "t", "owner_cli": "codex"}]),
    ):
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(ValueError):
            brownfield.load_plan(path)


def test_split_spec_is_a_valid_board_split_without_the_task_text() -> None:
    plan = _plan()
    spec = brownfield.build_split_spec(plan, {"a": "owner-a", "b": "owner-b"})

    assert spec["assignments"] == {"a": "owner-a", "b": "owner-b"}
    assert spec["contracts"] == []
    for module in spec["modules"]:
        # The board accepts every charter as is ...
        assert normalize_charter(module)["paths"] == module["paths"]
        assert module["provides"] == [] and module["depends"] == []
        # ... and the long requirements never travel through the lead.
        assert "Do A" not in json.dumps(module)
    message = brownfield.build_split_message(spec)
    assert "chat_room_board_propose_split" in message
    assert json.loads(message.split(":\n", 1)[1].rsplit("\n", 1)[0]) == spec


def test_task_message_carries_the_full_requirements() -> None:
    module = _plan()["modules"][0]  # type: ignore[index]
    message = brownfield.build_task_message(module)

    assert message.startswith("Requirements for your module `a` (tar-parser):")
    assert message.count("Do A") == 400


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout.strip()


def test_export_green_head_writes_a_plain_repository_at_the_integration_ref(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    assert brownfield.export_green_head(root, "conv_1")["reason"] == "no_mirror"

    mirror = root / "runtime" / "owner-clones" / ".mirror.git"
    mirror.parent.mkdir(parents=True)
    _git(tmp_path, "init", "-q", "--bare", str(mirror))
    assert brownfield.export_green_head(root, "conv_1")["reason"] == "no_integration_branch"

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "config", "user.email", "t@example.invalid")
    _git(work, "config", "user.name", "T")
    (work / "a.txt").write_text("integrated\n", encoding="utf-8")
    _git(work, "add", "a.txt")
    _git(work, "commit", "-qm", "green")
    green = _git(work, "rev-parse", "HEAD")
    _git(work, "push", "-q", str(mirror), f"HEAD:{INTEGRATION_REF_PREFIX}conv_1")

    exported = brownfield.export_green_head(root, "conv_1")

    assert exported["green_head"] == green
    result = Path(str(exported["result_repo"]))
    assert _git(result, "rev-parse", "HEAD") == green
    assert (result / "a.txt").read_text(encoding="utf-8") == "integrated\n"


def test_collect_board_rows_reads_the_real_schema(tmp_path: Path) -> None:
    RoomDatabase(tmp_path / "chat.db").initialize()

    assert brownfield.collect_board_rows(tmp_path, "conv_missing") == {
        "verifications": [],
        "reviews": [],
    }


@pytest.mark.parametrize("reviewer", ["claude", "antigravity"])
def test_reviewer_participant_passes_room_setup(tmp_path: Path, reviewer: str) -> None:
    RoomDatabase(tmp_path / "chat.db").initialize()
    lead = brownfield.ParticipantInit(
        role="lead", display_name="Lead", cli_kind="opencode", model="opencode-go/m"
    )
    setup = brownfield.RoomSetupService(tmp_path).create_conversation(
        brownfield.RoomConversationCreate(
            title="reviewer",
            client_request_id=f"reviewer-{reviewer}",
            collaboration=brownfield.RoomCollaborationInit(
                mode="addressed", lead_role="lead", review_policy="cross_family"
            ),
            initial_participants=[
                lead,
                brownfield.reviewer_participant(reviewer, "gemini-3.8-flash-high"),
            ],
        )
    )

    assert setup["id"]


def test_a_module_owner_cli_overrides_the_run_default() -> None:
    plan = _plan()
    plan["modules"][1]["owner_cli"] = "antigravity"  # type: ignore[index]

    assert brownfield.module_owner_clis(plan, "opencode") == {"a": "opencode", "b": "antigravity"}
    assert brownfield.module_owner_clis(_plan(), "antigravity") == {
        "a": "antigravity",
        "b": "antigravity",
    }


def test_a_reviewer_of_an_owner_family_is_refused(tmp_path: Path) -> None:
    plan = _plan()
    plan["modules"][0]["owner_cli"] = "antigravity"  # type: ignore[index]
    path = tmp_path / "mixed.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    common = ["--seed", str(tmp_path), "--plan", str(path), "--root", str(tmp_path / "root")]

    assert brownfield.main([*common, "--result", "r.json", "--reviewer", "antigravity"]) == 2
    assert not (tmp_path / "root").exists()


def _history() -> list[dict[str, object]]:
    return [
        {"act": "ACT01", "kind": "message", "text": "act-one"},
        {"act": "ACT02", "kind": "gate", "text": "red-flag"},
        {"act": "ACT03", "kind": "message", "text": "act-three"},
    ]


def test_probe_context_is_empty_without_flags() -> None:
    assert (
        brownfield.build_probe_context(history=_history(), max_history=None, preload_memory="")
        == ""
    )


def test_probe_context_takes_the_recent_k_acts() -> None:
    context = brownfield.build_probe_context(history=_history(), max_history=2, preload_memory="")

    assert "act-one" not in context
    assert "[gate] red-flag" in context
    assert "act-three" in context


def test_probe_context_appends_preloaded_memory_verbatim() -> None:
    context = brownfield.build_probe_context(
        history=_history(), max_history=None, preload_memory="# Module memory: x"
    )

    assert "act-one" not in context
    assert "# Module memory: x" in context


def test_load_probe_history_rejects_non_lists(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"acts": []}), encoding="utf-8")

    with pytest.raises(ValueError):
        brownfield.load_probe_history(path)


def test_max_history_needs_a_history_file(tmp_path: Path) -> None:
    plan = _plan()
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    common = ["--seed", str(tmp_path), "--plan", str(path), "--root", str(tmp_path / "root")]

    assert brownfield.main([*common, "--result", "r.json", "--max-history", "8"]) == 2
