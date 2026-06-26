import asyncio
from pathlib import Path

import pytest

from xmuse_core.platform.agent_spawner import AgentSpawner, GodConfig
from xmuse_core.providers.adapters.base import ProviderInvocation
from xmuse_core.providers.models import ProviderId, ProviderProfileId, RiskTier, TaskCapability
from xmuse_core.providers.service import RunnerProviderService
from xmuse_core.structuring.models import (
    ProviderSessionBindingRecord,
    ProviderSessionBindingStatus,
)


def test_agent_spawner_uses_configurable_codex_model(monkeypatch) -> None:
    monkeypatch.setenv("XMUSE_CODEX_MODEL", "gpt-5.4")
    spawner = AgentSpawner(repo_root=Path("/tmp/xmuse"), mcp_port=8100)

    command = spawner._build_command(
        GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="",
        ),
        Path("/tmp/worktree"),
    )

    assert command[:4] == ["codex", "exec", "-m", "gpt-5.4"]


def test_agent_spawner_normalizes_reserved_final_quality_model_env(monkeypatch) -> None:
    monkeypatch.setenv("XMUSE_CODEX_MODEL", "gpt-5.5")
    spawner = AgentSpawner(repo_root=Path("/tmp/xmuse"), mcp_port=8100)

    command = spawner._build_command(
        GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="",
        ),
        Path("/tmp/worktree"),
    )

    assert command[:4] == ["codex", "exec", "-m", "gpt-5.4"]


def test_agent_spawner_uses_explicit_model_and_worker_metadata(monkeypatch) -> None:
    monkeypatch.setenv("XMUSE_CODEX_MODEL", "gpt-5.4")
    spawner = AgentSpawner(repo_root=Path("/tmp/xmuse"), mcp_port=8100)
    god_config = GodConfig(
        name="execution-god",
        runtime="codex",
        timeout_s=60,
        skill_prompt_path="",
        model="gpt-5.4",
        worker_model="gpt-5.4-mini",
        delegation_mode="bounded_worker",
    )

    command = spawner._build_command(god_config, Path("/tmp/worktree"))
    env = spawner._build_env(god_config, "lane-tiered")

    assert command[:4] == ["codex", "exec", "-m", "gpt-5.4"]
    assert env["XMUSE_GOD_MODEL"] == "gpt-5.4"
    assert env["XMUSE_WORKER_MODEL"] == "gpt-5.4-mini"
    assert env["XMUSE_DELEGATION_MODE"] == "bounded_worker"


def test_agent_spawner_normalizes_windows_temp_env(monkeypatch) -> None:
    monkeypatch.setenv("TMPDIR", "/mnt/c/Users/iiyatu/AppData/Local/Temp")
    monkeypatch.setenv("TMP", "/mnt/c/Users/iiyatu/AppData/Local/Temp")
    monkeypatch.setenv("TEMP", "/mnt/c/Users/iiyatu/AppData/Local/Temp")
    spawner = AgentSpawner(repo_root=Path("/tmp/xmuse"), mcp_port=8100)

    env = spawner._build_env(
        GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="",
        ),
        "lane-tiered",
    )

    assert env["TMPDIR"] == "/tmp"
    assert env["TMP"] == "/tmp"
    assert env["TEMP"] == "/tmp"


def test_agent_spawner_build_command_passes_explicit_provider_binding_to_service(
    tmp_path: Path,
) -> None:
    provider_invocation = ProviderInvocation(
        request_id="lane-codex:execute",
        provider_id=ProviderId.CODEX,
        profile_id=ProviderProfileId.DEFAULT,
        task_type=TaskCapability.LANE_COORDINATION,
        risk_tier=RiskTier.MEDIUM,
        prompt="Continue the feature graph.",
        workspace=tmp_path,
        timeout_seconds=60,
    )
    binding = _provider_session_binding(worktree=str(tmp_path))
    spawner = AgentSpawner(
        repo_root=tmp_path / "xmuse",
        mcp_port=8123,
        provider_service=RunnerProviderService(mcp_port=8123),
    )

    command = spawner._build_command(
        GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="",
            model="gpt-5.4",
        ),
        tmp_path,
        provider_invocation=provider_invocation,
        provider_session_binding=binding,
    )

    assert command[:4] == [
        "codex",
        "exec",
        "resume",
        "codex-session-11111111-2222-3333-4444-555555555555",
    ]
    assert command[-2:] == ["-C", str(tmp_path)]


def test_agent_spawner_normalizes_reserved_final_quality_explicit_models() -> None:
    spawner = AgentSpawner(repo_root=Path("/tmp/xmuse"), mcp_port=8100)
    god_config = GodConfig(
        name="execution-god",
        runtime="codex",
        timeout_s=60,
        skill_prompt_path="",
        model="gpt-5.5",
        worker_model="gpt-5.5",
        delegation_mode="bounded_worker",
    )

    command = spawner._build_command(god_config, Path("/tmp/worktree"))
    env = spawner._build_env(god_config, "lane-tiered")

    assert command[:4] == ["codex", "exec", "-m", "gpt-5.4"]
    assert env["XMUSE_GOD_MODEL"] == "gpt-5.4"
    assert env["XMUSE_WORKER_MODEL"] == "gpt-5.4-mini"


def test_agent_spawner_defaults_to_local_codex_config_model(monkeypatch) -> None:
    monkeypatch.delenv("XMUSE_CODEX_MODEL", raising=False)
    spawner = AgentSpawner(repo_root=Path("/tmp/xmuse"), mcp_port=8100)

    command = spawner._build_command(
        GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="",
        ),
        Path("/tmp/worktree"),
    )

    assert command[:4] == ["codex", "exec", "-m", "gpt-5.4"]


def test_agent_spawner_rejects_claude_runtime() -> None:
    spawner = AgentSpawner(repo_root=Path("/tmp/xmuse"), mcp_port=9001)

    with pytest.raises(ValueError, match="codex-only"):
        spawner._build_command(
            GodConfig(
                name="execution-god",
                runtime="claude",
                timeout_s=60,
                skill_prompt_path="",
            ),
            Path("/tmp/worktree"),
        )


class _FakeMemoryOSClient:
    def __init__(self) -> None:
        self.created_titles: list[str] = []
        self.context_requests: list[tuple[str, str]] = []
        self.ingested: list[tuple[str, str, str]] = []

    async def create_session(self, title: str) -> str:
        self.created_titles.append(title)
        return "ses_lane_1"

    async def build_context(self, session_id: str, task: str, budget: int = 4096) -> str:
        self.context_requests.append((session_id, task))
        return "remember: prior lane evidence"

    async def ingest(self, session_id: str, role: str, content: str) -> None:
        self.ingested.append((session_id, role, content))


class _FakeProcess:
    pid = 4321
    returncode = 0
    killed = False
    waited = False

    async def communicate(self, input: bytes):
        self.prompt = input.decode()
        return b"lane stdout", b"lane stderr"

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.waited = True
        return self.returncode


@pytest.mark.asyncio
async def test_agent_spawner_attaches_memoryos_context_and_ingests_result(
    monkeypatch, tmp_path: Path
) -> None:
    fake_client = _FakeMemoryOSClient()
    fake_process = _FakeProcess()
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        captured["stdin"] = kwargs.get("stdin")
        return fake_process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    spawner = AgentSpawner(
        repo_root=tmp_path / "xmuse",
        mcp_port=8100,
        memoryos_client=fake_client,
    )
    result = await spawner.spawn(
        god_config=GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="",
        ),
        lane_id="lane-1",
        prompt="Implement the lane.",
        worktree=tmp_path,
    )

    assert fake_client.created_titles == ["xmuse:lane-1"]
    assert fake_client.context_requests == [("ses_lane_1", "Implement the lane.")]
    assert "<memoryos_context>" in fake_process.prompt
    assert "remember: prior lane evidence" in fake_process.prompt
    assert fake_process.prompt.endswith("Implement the lane.")
    assert fake_client.ingested[0] == ("ses_lane_1", "user", "Implement the lane.")
    assert fake_client.ingested[1] == ("ses_lane_1", "assistant", "lane stdout")
    assert result.memoryos_session_id == "ses_lane_1"
    assert result.memoryos_context_attached is True
    assert result.memoryos_ingested is True
    assert result.process_pid == 4321


def _provider_session_binding(*, worktree: str) -> ProviderSessionBindingRecord:
    return ProviderSessionBindingRecord(
        binding_id="psb-codex-demo",
        god_session_id="god-worker-demo",
        provider="codex",
        provider_session_id="codex-session-11111111-2222-3333-4444-555555555555",
        session_kind="exec",
        status=ProviderSessionBindingStatus.ACTIVE,
        conversation_id="conv-xmuse-hardening",
        feature_graph_id="graph-provider-session-binding",
        role="feature_worker",
        cwd="/repo",
        worktree=worktree,
        model="gpt-5.4",
        prompt_fingerprint="sha256:prompt-demo",
        created_at="2026-06-03T02:10:00Z",
        last_used_at="2026-06-03T02:11:00Z",
        last_verified_at="2026-06-03T02:11:30Z",
        resume_command_template="codex exec resume {provider_session_id}",
    )


@pytest.mark.asyncio
async def test_agent_spawner_uses_final_prompt_on_argv_for_opencode_provider(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    fake_client = _FakeMemoryOSClient()
    fake_process = _FakeProcess()
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        captured["stdin"] = kwargs.get("stdin")
        return fake_process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    provider_invocation = ProviderInvocation(
        request_id="lane-opencode:execute",
        provider_id=ProviderId.OPENCODE,
        profile_id=ProviderProfileId.DEEPSEEK_FLASH_WORKER,
        task_type=TaskCapability.BOUNDED_CODE_WRITING,
        risk_tier=RiskTier.LOW,
        prompt="Implement the lane.",
        workspace=tmp_path,
        timeout_seconds=60,
    )
    spawner = AgentSpawner(
        repo_root=tmp_path / "xmuse",
        mcp_port=8100,
        memoryos_client=fake_client,
        provider_service=RunnerProviderService(),
    )

    await spawner.spawn(
        god_config=GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="",
        ),
        lane_id="lane-opencode",
        prompt="Implement the lane.",
        worktree=tmp_path,
        provider_invocation=provider_invocation,
    )

    command = tuple(captured["cmd"])
    assert command[:10] == (
        "opencode",
        "run",
        "--model",
        "opencode-go/deepseek-v4-flash",
        "--variant",
        "max",
        "--format",
        "json",
        "--dir",
        str(tmp_path),
    )
    assert "<memoryos_context>" in command[-1]
    assert command[-1].endswith("Implement the lane.")
    assert fake_process.prompt == ""


@pytest.mark.asyncio
async def test_agent_spawner_reports_process_start_for_worker_lease(
    monkeypatch, tmp_path: Path
) -> None:
    fake_process = _FakeProcess()
    starts: list[tuple[str, int, list[str], Path]] = []

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return fake_process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    spawner = AgentSpawner(
        repo_root=tmp_path / "xmuse",
        mcp_port=8100,
        on_process_start=lambda lane_id, pid, command, worktree: starts.append(
            (lane_id, pid, command, worktree)
        ),
    )
    await spawner.spawn(
        god_config=GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="",
        ),
        lane_id="lane-lease",
        prompt="Implement the lane.",
        worktree=tmp_path,
    )

    assert starts == [
        (
            "lane-lease",
            4321,
            spawner._build_command(
                GodConfig(
                    name="execution-god",
                    runtime="codex",
                    timeout_s=60,
                    skill_prompt_path="",
                ),
                tmp_path,
            ),
            tmp_path,
        )
    ]


@pytest.mark.asyncio
async def test_agent_spawner_cleans_up_process_when_start_callback_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fake_process = _FakeProcess()

    async def fake_create_subprocess_exec(*cmd, **kwargs):
        return fake_process

    def fail_process_start(*args) -> None:
        raise RuntimeError("lease write failed")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    spawner = AgentSpawner(
        repo_root=tmp_path / "xmuse",
        mcp_port=8100,
        on_process_start=fail_process_start,
    )

    with pytest.raises(RuntimeError, match="lease write failed"):
        await spawner.spawn(
            god_config=GodConfig(
                name="execution-god",
                runtime="codex",
                timeout_s=60,
                skill_prompt_path="",
            ),
            lane_id="lane-lease",
            prompt="Implement the lane.",
            worktree=tmp_path,
        )

    assert fake_process.killed is True
    assert fake_process.waited is True
