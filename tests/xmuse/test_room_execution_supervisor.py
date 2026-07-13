from __future__ import annotations

from pathlib import Path

from xmuse_core.chat import room_execution_supervisor as supervisor


class _Store:
    def __init__(self, rows):
        self.rows = rows

    def list_controller_recovery(self, *, limit: int = 100):
        return self.rows[:limit]


class _Process:
    pid = 123

    def poll(self):
        return None


def _config(tmp_path: Path) -> supervisor.ExecutionControllerSupervisorConfig:
    return supervisor.ExecutionControllerSupervisorConfig(
        repo_root=tmp_path / "repo",
        xmuse_root=tmp_path / "runtime",
        execution_worktree=tmp_path / "worktree",
        generation="generation-1",
    )


def test_command_has_only_fixed_root_worktree_and_run_id(tmp_path: Path) -> None:
    command = supervisor.execution_controller_command(_config(tmp_path), run_id="run-1")
    assert command[1:3] == ["-m", "xmuse.room_execution_controller"]
    assert command.count("--run-id") == 1
    assert "--command" not in command
    assert "--patch" not in command
    assert "--candidate-id" not in command


def test_live_identity_is_not_duplicated(tmp_path: Path, monkeypatch) -> None:
    store = _Store(
        [
            {
                "run_id": "run-1",
                "controller_pid": 55,
                "controller_start_identity": "identity-55",
            }
        ]
    )
    monkeypatch.setattr(supervisor, "read_process_start_identity", lambda pid: f"identity-{pid}")

    result = supervisor.ensure_execution_controller(
        store,
        _config(tmp_path),
        run_id="run-1",
        popen=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not spawn")),
    )

    assert result is None


def test_dead_binding_spawns_without_forwarding_parent_secrets(tmp_path: Path, monkeypatch) -> None:
    store = _Store(
        [
            {
                "run_id": "run-1",
                "controller_pid": 55,
                "controller_start_identity": "old",
            }
        ]
    )
    monkeypatch.setenv("XMUSE_OPERATOR_TOKEN", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr(
        supervisor,
        "read_process_start_identity",
        lambda pid: None if pid == 55 else "new-identity",
    )
    captured = {}

    def popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return _Process()

    result = supervisor.ensure_execution_controller(
        store, _config(tmp_path), run_id="run-1", popen=popen
    )

    assert result is not None
    assert result.start_identity == "new-identity"
    assert "XMUSE_OPERATOR_TOKEN" not in captured["env"]
    assert "OPENAI_API_KEY" not in captured["env"]
    assert captured["env"]["XMUSE_WORKROOM_SERVICE"] == "execution_controller"
    assert captured["start_new_session"] is False
    assert "PYTHONPATH" not in captured["env"]


def test_unbound_run_is_spawnable(tmp_path: Path, monkeypatch) -> None:
    store = _Store([{"run_id": "run-1", "controller_pid": None, "controller_start_identity": None}])
    monkeypatch.setattr(supervisor, "read_process_start_identity", lambda _pid: "new")

    result = supervisor.ensure_execution_controller(
        store, _config(tmp_path), run_id="run-1", popen=lambda *_a, **_k: _Process()
    )

    assert result is not None
