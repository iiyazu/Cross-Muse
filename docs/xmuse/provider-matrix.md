# xmuse Provider Matrix

更新日期: 2026-06-04

## 概述

xmuse 有两个独立的 provider plane，对应不同的运行时路径:

| Plane | 职责 | 代码路径 | 调用链 |
|-------|------|----------|--------|
| **Execution/Review** | lane 执行、review、coordinator | `src/xmuse_core/providers/*` | `RunnerProviderService → ProviderAdapter.invoke() → CLI subprocess` |
| **Groupchat GOD Session** | 群聊 GOD 持久 session、Ray actor、MCP writeback | `src/xmuse_core/agents/ray_session_layer.py` | `RayGodSessionLayer → Codex app-server → MCP writeback` |

两者当前都指向 Codex CLI，但抽象层级和持久化语义不同。下面分别展开。

---

## Plane 1: Execution / Review Provider

`src/xmuse_core/providers/` — 将 AI CLI（Codex, OpenCode）通过统一接口接入执行/审查流程。

```
executor → RunnerProviderService → ProviderAdapter.invoke() → CLI subprocess
             ↓
        ProviderPolicyService.select_worker()
             ↓
        LanePolicySignals (lane risk/capability)
```

### Provider 一览

| Provider | Adapter | 支持级别 | Profiles | MCP | 持久化 | 健康检查 |
|----------|---------|----------|----------|-----|--------|----------|
| Codex CLI | `CodexProviderAdapter` | **PRIMARY** | 5 | Yes | provider-native resume | binary 存在性 |
| OpenCode CLI | `OpenCodeProviderAdapter` | **SECONDARY** (worker only) | 1 | No | N/A | 实际 smoke run |
| Claude Code | `launchers/claude_code.py` | **Launcher only** — 不是 provider adapter | 0 | — | — | — |
| Fake (test) | `FakeProviderAdapter` | **TEST ONLY** | 任意 mock | N/A | N/A | 模拟状态 |

**Claude Code 说明**: `src/xmuse_core/agents/launchers/claude_code.py` 是一个独立的 agent launcher（类似于 `codex_persistent.py`），它不经过 `providers/` 抽象层。没有对应的 `ProviderProfile` 或 `ProviderAdapter`。后续如需纳入统一调度，需要新增 `ClaudeCodeProviderAdapter`。

### Codex 持久化 — 两种语义

| 类型 | 机制 | 用途 | 代码 |
|------|------|------|------|
| **provider-native resume** | `provider_session_id` 传回 Codex CLI resume 命令 | 中断后恢复同一 session | `providers/adapters/codex.py:build_resume_command()`, `providers/session_binding.py` |
| **Ray GOD app-server** | Ray actor 保持 app-server 长连接，MCP writeback | 群聊 GOD 持久 session | `agents/ray_session_layer.py`, `agents/ray_god_actor.py` |

两者互不替代：provider-native resume 是单次 CLI 调用的恢复；Ray GOD app-server 是跨多次 CLI 调用的持久 session 连接。

### Profile 矩阵

| Profile Ref | Provider | 模型 | 成本 | 风险 | 能力 |
|-------------|----------|------|------|------|------|
| `codex.default` | CODEX | gpt-5.4 | HIGH | HIGH | write, review, coord, plan, takeover |
| `codex.worker` | CODEX | gpt-5.4-mini | LOW | LOW | bounded_code_writing |
| `codex.review` | CODEX | gpt-5.4 | HIGH | HIGH | review |
| `codex.god` | CODEX | gpt-5.4 | MEDIUM | HIGH | coord, plan, takeover |
| `codex.final_quality` | CODEX | gpt-5.5 | HIGH | HIGH | merge_final_review |
| `opencode.deepseek_flash_worker` | OPENCODE | deepseek-v4-flash | LOW | LOW | bounded_code_writing |

### 配置要求

| Profile | 必需 | 可选 | 其他 |
|---------|------|------|------|
| 所有 codex.* | (无) | `XMUSE_CODEX_MODEL` | `codex` binary 在 PATH |
| opencode.deepseek_flash_worker | `DEEPSEEK_API_KEY` | `DEEPSEEK_MODEL`, `DEEPSEEK_BASE_URL` | `opencode` binary 在 PATH |

### Provider 选择策略

`providers/policy.py` — `ProviderPolicyService` 的 worker 选择逻辑:

1. lane 有升级信号（反复失败/模糊 review/高风险文件）→ `codex.god`
2. 低风险边界任务且 `opencode.deepseek_flash_worker` 健康 → 选 OpenCode
3. OpenCode 不健康 → fallback 到 `codex.worker`
4. 默认 → `codex.worker`

God / review / coordinator 固定使用对应的 codex.* profile。

### 关键文件

| 文件 | 核心职责 |
|------|----------|
| `providers/adapters/codex.py` | Codex CLI 适配器（主执行器） |
| `providers/adapters/opencode.py` | OpenCode CLI 适配器（低成本 worker） |
| `providers/adapters/fake.py` | 测试用 fake adapter |
| `providers/models.py` | ProviderProfile / 枚举定义 |
| `providers/registry.py` | 6 个默认 profile 注册 |
| `providers/policy.py` | 智能 provider 选择逻辑 |
| `providers/service.py` | RunnerProviderService（编排器接入点） |
| `providers/health.py` | ProviderHealthSnapshot 模型 |
| `providers/goal_contract.py` | WorkerGoalContract + 校验 |
| `providers/selection_record.py` | 选择审计记录 |
| `providers/session_binding.py` | provider-native session 恢复绑定 |

### 测试覆盖

以下测试文件覆盖 Execution/Review provider plane。**数字为撰写时的快照，随时间变化。**

推荐验证命令（比数字更有用）:

```bash
# Execution/Review provider 全量门禁
uv run pytest tests/xmuse/test_provider_models.py \
  tests/xmuse/test_provider_adapters.py \
  tests/xmuse/test_provider_policy.py \
  tests/xmuse/test_provider_opencode.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_provider_read_contracts_module.py \
  -q
```

```bash
# 包边界验证（xmuse_core 不直接 import memoryos_lite）
uv run pytest tests/xmuse/test_package_boundaries.py -q
```

---

## Plane 2: Groupchat GOD Session

`src/xmuse_core/agents/ray_session_layer.py` — 群聊 GOD 持久 session 路径。

```
RayGodSessionLayer
  → RayGodActor (Ray remote actor)
    → Codex app-server (长连接 thread)
      → MCP writeback → chat_api / mcp_server
```

| 组件 | 路径 | 持久化方式 |
|------|------|-----------|
| `RayGodSessionLayer` | `agents/ray_session_layer.py:29` | Ray actor 保持，非 durable store 权威 |
| `RayGodActor` | `agents/ray_god_actor.py:29` | 子进程 + Codex app-server thread |
| `CodexAppServerTransport` | `agents/codex_app_server_transport.py:108` | SSE 长连接 |

**关键约束**: Ray actor 内存不是权威状态。崩溃恢复必须走 durable store（`chat.db`、`god_sessions.json`）。

**Groupchat GOD plane 验证**（不是默认 CI gate — 涉及真实 Ray/Codex 环境）:
```bash
uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume
```

V9 runtime operations health gate:

```bash
uv run xmuse-platform-runner --health-once --health-check-http --mcp-port 8100
```

The `operations.readiness` block must show Ray backend configuration,
Codex app-server observation/orphan status, MCP enablement, and scheduler
progress. Degraded local fallback is explicit and must not be treated as the
MCP writeback happy path.

**生产 bundle**（见 `config-matrix.md` Production 群聊最小 env bundle）:

```
XMUSE_PEER_GOD_BACKEND=ray
XMUSE_RAY_GOD_TRANSPORT=app-server
XMUSE_RAY_GOD_MCP=1
XMUSE_RAY_GOD_EFFORT=low
```

### 与 Execution/Review plane 的关系

| 维度 | Execution/Review Plane | Groupchat GOD Plane |
|------|----------------------|---------------------|
| 调用入口 | `RunnerProviderService` | `RayGodSessionLayer` |
| 子进程 | `codex exec` (单次任务) | `codex app-server / thread` (长连接) |
| session 管理 | `provider_session_id` resume | Ray actor lease + MCP writeback |
| 当前生产者 | Codex (primary) | Codex (唯一) |
| OpenCode | 支持 (worker only) | 不支持 |

---

## 已知问题

1. **Codex 健康检查过于薄弱** — 只检查 binary 是否存在，不验证实际可用性
2. **无 Claude Code adapter** — `agents/launchers/claude_code.py` 是 launcher，不是 `ProviderAdapter`。无法通过 provider policy 选择
3. **OpenCode 只支持 bounded_code_writing** — 不能用于 review/coord/plan/takeover
4. **Provider 选择优先级多路径** — env var / CLI arg / profile ref 三套，无显式优先级文档
5. **Settings overlay 仍是 additive** — `src/xmuse_core/runtime/settings.py` 已提供
   `Settings(BaseSettings)` 和 `.env` 加载，但当前代码仍保留大量直接
   `os.environ.get()` 读取；后续如需中央配置，需要逐步迁移调用点。
6. **Groupchat GOD plane fallback 是显式 degraded contract** — `XMUSE_DEGRADED_LOCAL_GOD_MODE` 和 prewarm fallback 可用于本地降级，但 V9 health/readiness 必须显示 degraded 状态；fake/stdout fallback 不能替代真实 MCP writeback happy path

## Path A 使用说明

- 本矩阵支撑 Path A **Phase 3（质量门禁 + Provider 矩阵显式化）**
- 不作为 Phase 1 installability gate
- Phase 3 应以此矩阵为基础：显式化 Codex=primary for real groupchat，OpenCode=secondary bounded worker，Claude Code=launcher only not provider adapter
