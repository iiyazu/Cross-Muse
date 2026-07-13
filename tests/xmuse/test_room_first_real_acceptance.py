from __future__ import annotations

import json
import re
import signal
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.room_first_real_acceptance import (
    EXPECTED_BASELINE_HEAD,
    AcceptanceConfig,
    AcceptanceDependencies,
    CommandResult,
    run_acceptance,
)
from xmuse_core.skills.catalog import SkillCatalog


class _FakeProcess:
    def __init__(self) -> None:
        self.running = True
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return None if self.running else 0

    def terminate(self) -> None:
        self.terminated = True
        self.running = False

    def kill(self) -> None:
        self.killed = True
        self.running = False

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.running = False
        return 0


class _FakeAcceptanceSystem:
    def __init__(
        self,
        repo_root: Path,
        *,
        missing_command: str | None = None,
        fail_phase: str | None = None,
        interrupt_phase: str | None = None,
        leak_token: bool = False,
    ) -> None:
        self.repo_root = repo_root
        self.missing_command = missing_command
        self.fail_phase = fail_phase
        self.interrupt_phase = interrupt_phase
        self.leak_token = leak_token
        self.token = "acceptance-secret-sentinel"
        self.commands: list[tuple[str, ...]] = []
        self.signals: list[tuple[int, int]] = []
        self.process = _FakeProcess()
        self.spawned = False
        self.stopped = False
        self.runner_pid = 303
        self.runner_boot = "boot-before"
        self.mcp_pid = 404
        self.clock = 0.0

    def which(self, command: str) -> str | None:
        return None if command == self.missing_command else f"/fake/{command}"

    def monotonic(self) -> float:
        self.clock += 0.01
        return self.clock

    def sleep(self, seconds: float) -> None:
        self.clock += seconds

    def now(self) -> str:
        return "2026-07-12T00:00:00Z"

    def git_snapshot(self, _repo_root: Path) -> str:
        return "stable-worktree"

    def port_available(self, _host: str, _port: int) -> bool:
        return True

    def read_process_environment(self, pid: int) -> Mapping[str, str]:
        assert pid == 202
        return {"XMUSE_OPERATOR_TOKEN": self.token}

    def signal_pid(self, pid: int, signum: int) -> None:
        self.signals.append((pid, signum))

    def spawn(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
    ) -> _FakeProcess:
        del cwd, env
        self.commands.append(tuple(command))
        self.spawned = True
        return self.process

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_s: float,
    ) -> CommandResult:
        del timeout_s
        cmd = tuple(command)
        self.commands.append(cmd)
        if cmd[:3] == ("git", "rev-parse", "HEAD"):
            return CommandResult(0, EXPECTED_BASELINE_HEAD + "\n")
        if cmd[:3] == ("codex", "login", "status"):
            return CommandResult(0, "authenticated\n")
        if cmd[:3] == ("npm", "run", "build"):
            standalone = self.repo_root / "frontend" / ".next" / "standalone"
            static = self.repo_root / "frontend" / ".next" / "static"
            standalone.mkdir(parents=True, exist_ok=True)
            static.mkdir(parents=True, exist_ok=True)
            (standalone / "server.js").write_text("// fake\n", encoding="utf-8")
            return CommandResult(0)
        if "test:e2e:real" in cmd and "--list" in cmd:
            return CommandResult(0, "one real test\n")
        if "test:e2e:real" in cmd:
            phase = env["XMUSE_REAL_PHASE"]
            assert self.token not in env.values()
            assert env["XMUSE_REAL_OPERATOR_TOKEN_SHA256"] != self.token
            assert env["XMUSE_REAL_OPERATOR_TOKEN_LENGTH"] == str(len(self.token))
            if phase == self.interrupt_phase:
                raise KeyboardInterrupt
            if phase == self.fail_phase:
                return CommandResult(
                    1,
                    stderr=f"unsafe provider output {self.token}",
                )
            self._write_browser_artifacts(env, phase)
            if phase == "recover-runner":
                self.runner_pid += 1
                self.runner_boot = "boot-after"
            if phase == "recover-mcp":
                self.mcp_pid += 1
            if self.leak_token and phase == "verify":
                evidence_path = Path(env["XMUSE_REAL_EVIDENCE_PATH"])
                evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
                evidence["sentinel"] = self.token
                evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            return CommandResult(0)
        if "xmuse-workroom" in cmd and "status" in cmd:
            return CommandResult(1 if self.stopped else 0, json.dumps(self._status()))
        if "xmuse-workroom" in cmd and "stop" in cmd:
            self.stopped = True
            return CommandResult(0, json.dumps({"state": "stopped"}))
        return CommandResult(0)

    def _status(self) -> dict[str, Any]:
        ready = not self.stopped
        state = "ready" if ready else "stopped"
        return {
            "schema_version": "xmuse_workroom_status/v2",
            "state": state,
            "services": [
                {
                    "service": "frontend",
                    "ready": ready,
                    "live": ready,
                    "pid": 101,
                },
                {
                    "service": "chat_api",
                    "ready": ready,
                    "live": ready,
                    "pid": 202,
                },
                {
                    "service": "room_runner",
                    "ready": ready,
                    "live": ready,
                    "pid": self.runner_pid,
                    "boot_id": self.runner_boot,
                },
                {
                    "service": "room_mcp",
                    "ready": ready,
                    "live": ready,
                    "pid": self.mcp_pid,
                },
            ],
        }

    def _write_browser_artifacts(self, env: Mapping[str, str], phase: str) -> None:
        state_path = Path(env["XMUSE_REAL_STATE_PATH"])
        evidence_path = Path(env["XMUSE_REAL_EVIDENCE_PATH"])
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_payload = {
            "schema_version": "room_first_real_browser_state/v2",
            "conversation_id": "conv-real",
            "participant_ids": [
                "part-architect",
                "part-builder",
                "part-reviewer",
                "part-critic",
            ],
            "turns": [
                {
                    "kind": kind,
                    "correlation_id": f"corr-{kind}",
                    "root_activity_id": f"activity-{kind}",
                    "observation_count": 12,
                    "attempt_count": 8,
                    "skill_decision_count": 8,
                    "logical_batch_count": 8,
                    "infrastructure_retry_count": 0,
                    "expected_mention_handle": (None if kind == "normal" else f"@{kind}-target"),
                }
                for kind in ("normal", "mention", "handoff")
            ],
        }
        state_path.write_text(json.dumps(state_payload), encoding="utf-8")
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            evidence = {
                "schema_version": "room_first_real_browser_evidence/v2",
                "conversation_id": "conv-real",
                "participant_ids": state_payload["participant_ids"],
                "phases": {},
                "console_error_count": 0,
                "page_error_count": 0,
            }
        evidence["phases"][phase] = {
            "status": "passed",
            **(
                {
                    "room_status": "settled",
                    "participant_count": 4,
                    "turn_count": 3,
                    "durable_outcome_count": 12,
                    "skill_evidence_count": 24,
                    "batch_evidence_count": 12,
                    "near_duplicate_pair_count": 0,
                }
                if phase == "verify"
                else {}
            ),
        }
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        if phase == "verify":
            Path(env["XMUSE_REAL_SCREENSHOT_PATH"]).write_bytes(b"fake-png")

    def dependencies(self) -> AcceptanceDependencies:
        return AcceptanceDependencies(
            run=self.run,
            spawn=self.spawn,
            which=self.which,
            signal_pid=self.signal_pid,
            sleep=self.sleep,
            monotonic=self.monotonic,
            now=self.now,
            read_process_environment=self.read_process_environment,
            port_available=self.port_available,
            git_snapshot=self.git_snapshot,
        )


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "frontend").mkdir(parents=True)
    return root


def _config(tmp_path: Path, repo_root: Path) -> AcceptanceConfig:
    return AcceptanceConfig(
        repo_root=repo_root,
        runtime_root=tmp_path / "runtime",
        artifact_dir=tmp_path / "artifacts",
        readiness_timeout_s=2.0,
        phase_timeout_s=2.0,
    )


def test_fake_full_acceptance_is_phased_safe_and_cleans_up(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    system = _FakeAcceptanceSystem(repo)

    result = run_acceptance(_config(tmp_path, repo), dependencies=system.dependencies())

    assert result["status"] == "ok"
    assert result["worktree_unchanged"] is True
    assert result["room"] == {
        "conversation_id": "conv-real",
        "participant_ids": [
            "part-architect",
            "part-builder",
            "part-reviewer",
            "part-critic",
        ],
        "participant_count": 4,
        "root_correlation_id": "corr-handoff",
        "root_activity_id": "activity-handoff",
        "status": "settled",
        "turn_count": 3,
        "turns": [
            {
                "kind": kind,
                "correlation_id": f"corr-{kind}",
                "root_activity_id": f"activity-{kind}",
                "observation_count": 12,
                "attempt_count": 8,
                "skill_decision_count": 8,
                "logical_batch_count": 8,
                "infrastructure_retry_count": 0,
                "expected_mention_handle": (None if kind == "normal" else f"@{kind}-target"),
            }
            for kind in ("normal", "mention", "handoff")
        ],
    }
    assert result["counts"] == {
        "durable_outcomes": 12,
        "skill_evidence": 24,
        "console_errors": 0,
        "page_errors": 0,
    }
    assert system.signals == [
        (303, signal.SIGSTOP),
        (404, signal.SIGSTOP),
    ]
    assert system.stopped is True
    assert system.process.terminated is True
    assert (tmp_path / "runtime").is_dir()
    encoded = (tmp_path / "artifacts" / "result.json").read_text(encoding="utf-8")
    assert system.token not in encoded
    assert "unsafe provider output" not in encoded
    phases = [
        command
        for command in system.commands
        if "test:e2e:real" in command and "--list" not in command
    ]
    assert len(phases) == 4


def test_playwright_failure_is_bounded_and_always_stops_workroom(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    system = _FakeAcceptanceSystem(repo, fail_phase="conversation")

    result = run_acceptance(_config(tmp_path, repo), dependencies=system.dependencies())

    assert result["status"] == "failed"
    assert result["reason_code"] == "playwright_conversation_failed"
    assert system.stopped is True
    assert system.process.terminated is True
    assert system.token not in json.dumps(result)
    assert "unsafe provider output" not in json.dumps(result)


def test_keyboard_interrupt_still_stops_managed_processes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    system = _FakeAcceptanceSystem(repo, interrupt_phase="conversation")

    result = run_acceptance(_config(tmp_path, repo), dependencies=system.dependencies())

    assert result["status"] == "failed"
    assert result["reason_code"] == "acceptance_interrupted"
    assert system.stopped is True
    assert system.process.terminated is True


def test_preflight_blocker_does_not_start_runtime(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    system = _FakeAcceptanceSystem(repo, missing_command="codex")

    result = run_acceptance(
        _config(tmp_path, repo),
        dependencies=system.dependencies(),
    )

    assert result["status"] == "blocked"
    assert result["reason_code"] == "preflight_codex_not_found"
    assert system.spawned is False
    assert system.signals == []


def test_operator_token_leak_fails_closed_without_copying_secret(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    system = _FakeAcceptanceSystem(repo, leak_token=True)

    result = run_acceptance(_config(tmp_path, repo), dependencies=system.dependencies())

    assert result["status"] == "failed"
    assert result["reason_code"] == "operator_token_leaked"
    assert system.token not in json.dumps(result)
    assert system.stopped is True


def test_real_playwright_is_explicitly_isolated_from_normal_e2e() -> None:
    project = Path(__file__).resolve().parents[2]
    normal = (project / "frontend" / "playwright.config.ts").read_text(encoding="utf-8")
    real = (project / "frontend" / "playwright.real.config.ts").read_text(encoding="utf-8")
    package = json.loads((project / "frontend" / "package.json").read_text(encoding="utf-8"))

    assert "testIgnore:" in normal
    assert "testMatch:" in real
    for spec in ("room-first-real.spec.ts", "room-soak-real.spec.ts"):
        assert spec in normal
        assert spec in real
    assert "webServer" not in real
    assert package["scripts"]["test:e2e:real"] == (
        "playwright test --config playwright.real.config.ts"
    )


def test_real_acceptance_prompts_select_bundled_skills_for_supported_roles() -> None:
    project = Path(__file__).resolve().parents[2]
    spec = (project / "frontend" / "e2e" / "room-first-real.spec.ts").read_text(encoding="utf-8")
    prompts = re.findall(r'const (?:NORMAL|MENTION|HANDOFF)_PROMPT = "([^"\\]+)";', spec)
    assert len(prompts) == 3
    catalog = SkillCatalog.load_bundled()

    for prompt in prompts:
        decisions = {
            role: catalog.select(participant_role=role, source_text=prompt)
            for role in ("architect", "review")
        }
        assert decisions["architect"].skill_id == "implementation-planning"
        assert decisions["review"].skill_id == "evidence-review"
