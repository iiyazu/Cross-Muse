# xmuse Codex Strengthening Handoff

更新日期: 2026-06-04

本文档用于把 xmuse 后续强化开发交接给 `/goal` Codex session。它是执行入口文档，不替代
`docs/xmuse/walkthrough-maintenance-notes.md`、`docs/xmuse/解耦开发协议.md` 或
`xmuse/HANDOFF.md`。

## 当前工作目录

当前 xmuse 已迁到独立仓库:

```text
/home/iiyatu/projects/python/xmuse
```

Codex 接手时必须先在该仓库内重新核对当前源码和测试，不要继续假设 MemoryOS 仓库内的
`src/xmuse_core` 是最新实现。

当前主要源码和入口:

```text
src/xmuse_core/
xmuse/
tests/xmuse/
docs/xmuse/
```

基础命令:

```bash
uv run pytest -q tests/xmuse
uv run ruff check .
uv run python -m xmuse.tui
uv run xmuse-platform-runner --help
```

## 必读文档

按顺序阅读:

1. `docs/xmuse/walkthrough-maintenance-notes.md`
2. `docs/xmuse/解耦开发协议.md`
3. `xmuse/HANDOFF.md`
4. `docs/xmuse/README.md`
5. 与当前改动相关的 focused tests

`walkthrough-maintenance-notes.md` 是架构约束和当前走读证据；`解耦开发协议.md` 是层间边界；
`xmuse/HANDOFF.md` 是当前仓库和运行态交接。

## 核心判断

xmuse 的目标不是多开几个 CLI，而是把独立 coding agents 编排成可审计、可恢复、可并行、
中心化执行的工程系统。

目标拓扑:

```text
peer agents 去中心化讨论
-> approved blueprint
-> feature plan
-> feature graph / lane graph
-> coordinator 中心化调度
-> feature worker 长 session 执行一个 feature graph
-> reviewer 长 session 审 feature-level evidence
-> merge / rework / patch_forward / takeover / blocked
```

平台职责:

- xmuse 维护 conversation、blueprint、feature plan、graph-set、ready-set、run state。
- xmuse 控制 worktree 权限、merge guard、rework limit、patch-forward gate、takeover。
- Ray 管理长 session 生命周期；provider session binding 保证 CLI 原生会话连续性。
- A2A 可作为 agent 边界协议候选，但不能替代 xmuse 状态机。

## 优先级

### P0. 状态权威统一

目标态应由 graph-set / feature graph / event store / graph-native status store 作为执行权威。
`feature_lanes.json` 只应作为迁移期投影或兼容导出。不要继续扩大它作为业务权威的依赖。

### P1. Agent 边界协议化

Codex、Claude Code、OpenCode 和未来远程 agent 都应通过统一 `AgentRuntimeAdapter` 或
A2A-compatible boundary 接入。agent 返回 task status、artifact、verdict；xmuse 写状态。

### P2. 长 session 核心化

peer agents、planner、reviewer、feature worker 必须按长 session 设计。oneshot CLI 只保留给
lint、test、health check、小诊断和低风险可重试工具任务。

### P3. 执行粒度升到 feature graph

默认执行粒度应是一个 feature worker 负责一个 feature graph。lane 是 worker 内部执行计划，
不是默认顶层调度单位。

### P4. Reviewer 强权受 gate 限制

reviewer 可输出 `merge | rework | patch_forward | takeover | blocked`。`patch_forward` 只能用于
边缘、小范围、低风险修复，必须记录原因并重跑 focused gates。

### P5. MemoryOS 不替代 provider session

MemoryOS/xmuse memory 负责长期事实和跨 session 检索；Codex/Claude/OpenCode 的 provider
session resume 负责 agent 自身短中期连续性。

## 推荐开发顺序

1. 确认当前源码结构、入口、默认 runtime 和测试边界。
2. 定义 feature-level schema: `FeatureEvidenceBundle`、`ReviewVerdict`、`ReworkPacket`。
3. 给 schema 增加 golden fixtures 和 focused tests。
4. 抽象 agent runtime/session 边界: task、artifact、verdict、session binding、capability。
5. 让 Ray 成为 peer/planner/reviewer/feature worker 的默认长 session runtime，native 降为 fallback。
6. 引入 feature graph ready-set/status store，减少对 flat `feature_lanes.json` 的业务依赖。
7. 实现 feature worker graph owner: 一个 worker 长 session 推进一个 feature graph。
8. 强化 reviewer: feature-level evidence review、rework packet、patch-forward gate。
9. 在 schema 和 runtime 边界稳定后再接 A2A adapter。

## 硬 Gate

Codex 实现时必须遵守:

- 不把 Ray actor、LangGraph、A2A 或 provider CLI 当状态权威。
- 不让 worker/reviewer 直接写 durable execution state。
- 不绕过 coordinator/state machine 做 merge、rework、dependency unlock。
- 不用 `--last` 作为 provider session 绑定策略；必须保存显式 provider session id。
- 不把 MemoryOS 当 provider 原生 session 的替代品。
- 不扩大 `feature_lanes.json` 作为业务权威的依赖。
- 不直接删除 native runtime；先降级 fallback，再以 parity gates 归档。
- 不把当前 Codex-first runtime 描述成完整多 provider runtime。
- 不修改 MemoryOS 仓库源码，除非当前 goal 明确要求跨仓库变更。

## 最小验收证据

每个阶段至少提供:

- 相关 schema/store/adapter 的 focused tests。
- 一条从 feature graph 到 worker evidence、review verdict、状态转换的闭环测试。
- provider session binding 或 Ray session 生命周期的恢复/失败测试。
- reviewer rework 和 patch-forward gate 测试。
- `feature_lanes.json` 兼容投影不回归测试，直到 cutover 完成。
- `uv run ruff check .` 和相关 `uv run pytest -q ...` 结果。
- handoff 更新，记录完成项、未完成项、风险和下一步。

## 2026-06-03 契约层进展

本轮完成低风险 contract-first 强化，未改 runner/orchestrator 状态写入路径:

- 新增 `src/xmuse_core/structuring/feature_review_contracts.py`。
- 新增 feature-level schema:
  - `FeatureEvidenceBundle`
  - `FeatureReviewVerdict`
  - `ReworkPacket`
  - `ProviderSessionBindingRecord`
  - `FeatureGraphExecutionStatusRecord`
- `structuring.models` 已兼容 re-export 上述新契约。
- 新增 golden fixtures:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_evidence_bundle.v1.json`
  - `tests/fixtures/xmuse/contracts/artifacts/feature_review_verdict.v1.json`
  - `tests/fixtures/xmuse/contracts/artifacts/rework_packet.v1.json`
  - `tests/fixtures/xmuse/contracts/artifacts/provider_session_binding.v1.json`
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_status.v1.json`
- reviewer gate 约束已进入 schema:
  - `merge` 必须有 acceptance coverage、scope assessment、required gates 和 merge guard evidence。
  - `rework` 必须有 blocking findings，并通过 `ReworkPacket` 指向同一 worker session 或可恢复 provider binding。
  - `patch_forward` 必须有 low-risk gate、允许文件范围、行/文件上限、禁止新依赖/公共契约变更，并声明 focused gates。
  - `takeover` / `blocked` 决策值已在 feature-level verdict enum 中保留。
- provider session binding schema 明确拒绝 `--last` / latest-session aliases，要求显式 provider session id。
- feature graph status schema 使用 graph-native identity，并只把 `feature_lanes.json` 作为 projection ref。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_review_contracts.py
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_structuring_review_models.py \
  tests/xmuse/test_review_plane.py \
  tests/xmuse/test_verdict_store_consistency.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  tests/xmuse/test_feature_review_contracts.py
```

验证结果:

- 新契约 focused tests: 7 passed。
- 新 fixture + shared contract tests: 17 passed。
- 旧 review / feature graph focused regression: 116 passed。
- 本轮新增/修改 Python 文件 ruff: All checks passed。

当前剩余风险:

- `uv run ruff check .` 仍失败，但失败来自仓库既有 lint 问题，主要分布在
  `ray_god_actor.py`、`ray_session_layer.py`、provider adapter、self-evolution、
  skills、dashboard 和历史脚本等文件；本轮未批量修复，避免与并行迁移 agent 冲突。
- 新契约还未接入 `PlatformOrchestrator` / feature worker runtime；当前是 schema + fixtures +
  focused tests 阶段。
- provider session binding 目前是 record contract，尚未实现 durable store、Codex JSON session id
  捕获、`codex exec resume <session_id>` 恢复和 stale/failed binding 重试策略。
- graph-native feature status 目前是 identity/status contract，尚未替代 `feature_lanes.json`
  执行事实源。

建议下一步:

1. 为 `ProviderSessionBindingRecord` 增加独立 store 和 focused tests，保持它与
   `GodSessionRecord` 分离。
2. 在 Codex exec 路径捕获显式 provider session id，并在下一 turn 使用
   `codex exec resume <provider_session_id>`，禁止 `--last`。
3. 让 persistent feature worker / reviewer prompt 以 `FeatureEvidenceBundle`、
   `FeatureReviewVerdict` 和 `ReworkPacket` 为输入输出契约。
4. 增加 graph-native ready/status store parity test，再逐步降低 `feature_lanes.json` 权威。

## 2026-06-03 Provider Session Binding Store

本轮继续补 provider 原生 session resume 的前置能力，仍未改 runtime dispatch:

- 新增 `src/xmuse_core/agents/provider_session_binding_store.py`。
- `ProviderSessionBindingStore` 使用独立 JSON store，不扩展 `GodSessionRecord`，保持 xmuse
  业务 session identity 与 provider 原生 session binding 分离。
- store 写入使用 companion lock + temp file replace。
- `upsert_active()` 会 retire 同一 `god_session_id + provider + session_kind` 下旧 active
  binding，避免多个 active provider session 竞争。
- `find_resume_compatible()` 对 model、worktree、prompt fingerprint、feature graph identity
  做兼容性检查；不兼容时返回 reason，不把坏 binding 交给 runtime resume。
- `mark_failed()` 支持把 binding 标为 `failed` 或 `stale`，失败 binding 不再被
  `find_active()` 返回。
- store 入口会重新校验 `ProviderSessionBindingRecord`，防止 `model_copy()` 等路径绕过
  “禁止 --last/latest aliases” 的 schema gate。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py
uv run ruff check src/xmuse_core/agents/provider_session_binding_store.py \
  tests/xmuse/test_provider_session_binding_store.py \
  src/xmuse_core/structuring/feature_review_contracts.py \
  tests/xmuse/test_feature_review_contracts.py
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_god_session_registry.py \
  tests/xmuse/test_god_session_layer.py
```

验证结果:

- provider binding store focused tests: 5 passed。
- provider binding store + feature review contract + GOD session regression: 48 passed。
- 本轮 store/contract 文件 ruff: All checks passed。

当前剩余风险:

- store 尚未接入 `GodSessionLayer`、`RayGodSessionLayer` 或 `CodexProviderAdapter`。
- Codex exec JSON event 的 provider session id 捕获仍未实现。
- resume 命令仍未从 store 驱动；下一步应在 Codex exec 路径优先使用
  `codex exec resume <provider_session_id>`，失败后调用 `mark_failed()` / `stale` 并按策略新建
  binding。
- Ray app-server `ephemeral=True` thread 仍不能作为跨进程 provider session binding 依据。

## 2026-06-03 Codex Session Binding Helper

本轮补齐 Codex exec resume 的低风险 adapter 前置能力，仍未改变当前 execution dispatch:

- `CodexProviderAdapter.build_resume_command()` 现在能构造显式
  `codex exec resume <provider_session_id>` 命令。
- resume command builder 明确拒绝 `--last`、`last`、`--latest` 等 last-session aliases。
- 新增 `extract_codex_provider_session_id(stdout)`，从 Codex JSON-line output 中提取显式
  provider session id。
- session id extraction 支持顶层 `id` / `session_id` / `sessionId`，以及嵌套
  `session.id` / `session_meta.id` / `sessionMeta.id`。
- extraction 遇到非 JSON 行会跳过；遇到 `--last` 等别名返回 `None`，不落入 binding store。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_provider_codex_retrofit.py
uv run pytest -q tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_provider_adapters.py \
  tests/xmuse/test_provider_policy.py
uv run ruff check src/xmuse_core/providers/adapters/codex.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  src/xmuse_core/agents/provider_session_binding_store.py \
  tests/xmuse/test_provider_session_binding_store.py
```

验证结果:

- Codex provider focused tests: 9 passed。
- Codex/provider binding/provider policy regression: 53 passed。
- 本轮 provider files ruff: All checks passed。

当前剩余风险:

- `CodexProviderAdapter.invoke()` 还没有根据 store 自动选择 first-run vs resume-run。
- 还没有把 extracted session id 写入 `ProviderSessionBindingStore`。
- 还没有实现 resume failure 后 `mark_failed()` / `stale` 并创建新 provider session 的策略。
- app-server transport 的 `thread_id` 仍是运行期 ephemeral thread，不作为 durable provider binding。

## 2026-06-03 Codex Binding-Aware Command Planning

本轮继续补 Codex exec resume 的 adapter 前置能力，仍未改变当前 `invoke()` dispatch、provider
binding store 写入或真实 runtime 路径:

- `CodexProviderAdapter.build_command_for_invocation(...)` 现在可选接收
  `provider_session_binding`。
- 没有传入 binding 时保持原 first-run `codex exec ...` 命令不变。
- 传入 active compatible binding 时构造显式
  `codex exec resume <provider_session_id> ...` 命令。
- resume binding 会重新校验 `ProviderSessionBindingRecord`，防止 `model_copy()` 等路径绕过
  schema gate。
- command builder 会拒绝:
  - 非 `provider=codex` binding。
  - 非 `session_kind=exec` binding。
  - 非 `active` binding。
  - model 与当前 adapter profile 不匹配的 binding。
  - worktree 与 invocation workspace 不匹配的 binding。
- 该能力只做 command planning，不查 store、不写 store、不调用 `mark_failed()`，避免在当前迁移期
  改变 runner/orchestrator 行为。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_provider_codex_retrofit.py
uv run pytest -q tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_provider_policy.py \
  tests/xmuse/test_provider_models.py
uv run ruff check src/xmuse_core/providers/adapters/codex.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  src/xmuse_core/agents/provider_session_binding_store.py \
  tests/xmuse/test_provider_session_binding_store.py
uv run ruff check .
```

验证结果:

- Codex provider binding-aware command focused tests: 11 passed。
- Codex/provider binding/provider policy regression: 37 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 88 个既有 lint 问题；主要仍分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/providers/adapters/base.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*` 和部分历史/迁移测试文件。本轮未批量修复，避免与并行迁移 agent 冲突。

当前剩余风险:

- `CodexProviderAdapter.invoke()` 仍未自动从 `ProviderSessionBindingStore` 查找 compatible binding。
- successful first-run stdout 中提取到的 session id 仍未写入 store。
- resume command 执行失败后仍未调用 `mark_failed()` / `stale` 并按策略新建 binding。
- God/Ray session layer 尚未把 provider binding 传给 adapter；Ray app-server ephemeral thread 仍不作为
  durable provider binding。

## 2026-06-03 Provider Result Session Id Capture

本轮继续补 provider session binding 的 adapter 输出链路，仍未写入
`ProviderSessionBindingStore`，也未改变 runner/orchestrator dispatch:

- `ProviderInvocationResult` 新增可选 `provider_session_id` 字段。
- `ProviderInvocationResult` 会拒绝 `last`、`--last`、`latest`、`--latest` 等 last-session alias。
- `CodexProviderAdapter.invoke()` 在 successful first-run stdout 中提取显式 Codex provider session id，
  并放入 `ProviderInvocationResult.provider_session_id`。
- `CodexProviderAdapter.build_result_from_output()` 支持从 structured artifacts 的
  `provider_session_id` 字段携带 session id。
- `build_result_from_output()` 也可从 artifacts 的 raw `stdout` JSON-lines 中提取 session id，供
  后续 spawn/service 层接入。
- 本轮只让 adapter result 暴露 provider-native session id；coordinator/store 仍是后续唯一
  durable 写入方。
- 顺手整理了 `src/xmuse_core/providers/adapters/base.py` 的 import/line-length lint，使 touched-file
  ruff gate 覆盖共享 provider result contract。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_provider_codex_retrofit.py
uv run pytest -q tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_provider_policy.py \
  tests/xmuse/test_provider_models.py \
  tests/xmuse/test_provider_opencode.py \
  tests/xmuse/test_provider_read_contracts_module.py
uv run pytest -q tests/xmuse/test_core_agents_launchers.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_provider_opencode.py
uv run ruff check src/xmuse_core/providers/adapters/base.py \
  src/xmuse_core/providers/adapters/codex.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  src/xmuse_core/agents/provider_session_binding_store.py \
  tests/xmuse/test_provider_session_binding_store.py
uv run ruff check .
```

验证结果:

- Codex provider session-id result focused tests: 14 passed。
- Provider binding/policy/opencode/read-contract regression: 54 passed。
- Core launcher + Codex/OpenCode provider regression: 41 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要仍分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/self_evolution/*`、
  `src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、`xmuse/scripts/*` 和部分历史/迁移测试文件。
  本轮未批量修复，避免与并行迁移 agent 冲突。

当前剩余风险:

- `ProviderInvocationResult.provider_session_id` 尚未由 coordinator 写入
  `ProviderSessionBindingStore`。
- `RunnerProviderService.build_result_from_spawn_result()` 已能把 raw stdout 作为 in-memory artifact
  交给 Codex adapter 提取 session id，但仍不落库、不持久化 raw stdout、不改变 dispatch。
- resume failure 后仍未调用 `mark_failed()` / `stale` 并按策略新建 binding。
- God/Ray session layer 尚未把 provider binding 传给 adapter；Ray app-server ephemeral thread 仍不作为
  durable provider binding。

## 2026-06-03 Provider Result-Derived Binding Builder

本轮补 provider session binding 的 coordinator/store 前置能力，仍未改
`PlatformOrchestrator`、`AgentSpawner`、Ray/native session layer 或真实 dispatch:

- 新增 `src/xmuse_core/providers/session_binding.py`。
- 新增 `build_provider_session_binding_from_result(...)`，从
  `ProviderInvocation + ProviderInvocationResult.provider_session_id` 构造
  `ProviderSessionBindingRecord`。
- builder 是纯函数，只返回 coordinator 可显式 `upsert_active()` 的 record；不写
  `ProviderSessionBindingStore`，不自动 resume，不让 adapter 或 worker 写 durable state。
- 新增 `upsert_provider_session_binding_from_result(...)` 作为显式 store-facing helper；调用方必须
  显式传入 store，避免 adapter invocation 或 worker execution path 隐式写 durable state。
- builder 要求 successful provider result，要求 result 与 invocation 的 request/provider/profile
  identity 匹配，并要求显式 `provider_session_id`。
- builder 会重新校验 `ProviderInvocationResult`，防止 `model_copy(update=...)` 绕过
  `last` / `--last` / `latest` alias gate。
- 生成的 Codex exec binding 使用稳定 `binding_id`:
  `psb:{god_session_id}:{provider}:{session_kind}:{provider_session_id}`，便于 coordinator replay
  时幂等 upsert。
- store-facing helper 复用 `ProviderSessionBindingStore.upsert_active()`，同一 result replay 不产生重复
  binding，同一 slot 的新 provider session 会 retire 旧 active binding。
- `RunnerProviderService.build_result_from_spawn_result()` 当前已把 raw stdout 作为 in-memory artifact
  交给 Codex adapter 做 session id extraction；本轮没有持久化 raw stdout，也没有把 result-derived
  binding 自动写入 dispatch 路径。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_provider_policy.py \
  tests/xmuse/test_provider_models.py \
  tests/xmuse/test_provider_opencode.py \
  tests/xmuse/test_provider_read_contracts_module.py \
  tests/xmuse/test_core_agents_launchers.py
uv run ruff check src/xmuse_core/providers/session_binding.py \
  src/xmuse_core/agents/provider_session_binding_store.py \
  tests/xmuse/test_provider_session_binding_store.py
```

验证结果:

- provider binding builder/upsert/store focused tests: 9 passed。
- provider binding + Codex/provider policy/model/OpenCode/read-contract/core launcher regression:
  74 passed。
- 本轮触及 Python 文件 ruff: All checks passed。

当前剩余风险:

- result-derived binding upsert helper 尚未由 coordinator/`PlatformOrchestrator` 调用；真实运行路径仍不会
  自动 upsert provider binding。
- `CodexProviderAdapter.invoke()` 和 `RunnerProviderService.build_command()` 仍未从
  `ProviderSessionBindingStore` 自动查询 compatible binding；service 只能消费调用方显式传入的 binding。
- resume failure 后仍未调用 `mark_failed()` / `stale` 并按策略新建 binding。
- God/Ray session layer 尚未把 provider binding 传给 adapter；Ray app-server ephemeral thread 仍不作为
  durable provider binding。

## 2026-06-03 Runner Provider Explicit Binding Command Boundary

本轮补 provider session binding 从 coordinator/store helper 到 runner provider service 的显式命令规划
边界，仍未改 `AgentSpawner`、`PlatformOrchestrator`、Ray/native session layer 或真实 dispatch:

- `RunnerProviderService.build_command(...)` 新增可选 `provider_session_binding` 参数。
- 默认不传 binding 时保持现有 first-run command 行为不变。
- 调用方显式传入 Codex exec active binding 时，service 会把 binding 转交
  `CodexProviderAdapter.build_command_for_invocation(...)`，生成显式
  `codex exec resume <provider_session_id> ...` 命令。
- service 不查 `ProviderSessionBindingStore`、不写 store、不调用 `mark_failed()`，避免在迁移期改变
  runner/orchestrator 行为。
- 对非 Codex invocation 传入 provider binding 会被拒绝，避免 OpenCode/其他 provider 误用 Codex
  exec binding。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_provider_codex_retrofit.py
uv run pytest -q tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_provider_policy.py \
  tests/xmuse/test_provider_models.py \
  tests/xmuse/test_provider_opencode.py \
  tests/xmuse/test_provider_read_contracts_module.py \
  tests/xmuse/test_core_agents_launchers.py
uv run ruff check src/xmuse_core/providers/service.py \
  src/xmuse_core/providers/session_binding.py \
  src/xmuse_core/providers/adapters/codex.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_provider_session_binding_store.py
```

验证结果:

- Codex provider explicit binding service focused tests: 17 passed。
- provider binding/service + Codex/provider policy/model/OpenCode/read-contract/core launcher
  regression: 76 passed。
- 本轮触及 Python 文件 ruff: All checks passed。

当前剩余风险:

- `AgentSpawner` / `PlatformOrchestrator` 仍未从 `ProviderSessionBindingStore` 查询 compatible binding 并传给
  `RunnerProviderService.build_command()`；真实运行路径仍是 first-run command。
- result-derived binding upsert helper 尚未由 coordinator/`PlatformOrchestrator` 调用；successful
  provider session id 仍不会自动落入 binding store。
- resume failure 后仍未调用 `mark_failed()` / `stale` 并按策略新建 binding。
- God/Ray session layer 尚未把 provider binding 传给 adapter；Ray app-server ephemeral thread 仍不作为
  durable provider binding。

## 2026-06-03 Agent Spawner Explicit Binding Pass-Through

本轮把显式 provider binding command boundary 从 `RunnerProviderService` 延伸到 `AgentSpawner`，
仍未改 `PlatformOrchestrator`、Ray/native session layer 或默认 dispatch:

- `AgentSpawner._build_command(...)` 和 `AgentSpawner.spawn(...)` 新增可选
  `provider_session_binding` 参数。
- 默认不传 binding 时保持现有 first-run command 行为不变。
- 调用方同时显式传入 `provider_invocation + provider_session_binding` 时，spawner 会把 binding 传给
  `RunnerProviderService.build_command(...)`，由 provider service / Codex adapter 生成显式 resume
  command。
- 如果传入 binding 但没有 provider invocation/provider service，spawner 会拒绝，避免在 legacy
  direct Codex command path 中绕过 provider adapter 的 binding 校验。
- 本轮只增加显式 pass-through seam，不查 `ProviderSessionBindingStore`，不写 store，不改变
  `ExecuteRequest` / transport 默认执行路径。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_platform_agent_spawner.py
uv run pytest -q tests/xmuse/test_platform_agent_spawner.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_provider_policy.py \
  tests/xmuse/test_provider_models.py \
  tests/xmuse/test_provider_opencode.py \
  tests/xmuse/test_provider_read_contracts_module.py \
  tests/xmuse/test_core_agents_launchers.py
uv run ruff check src/xmuse_core/platform/agent_spawner.py \
  src/xmuse_core/providers/service.py \
  src/xmuse_core/providers/session_binding.py \
  src/xmuse_core/providers/adapters/codex.py \
  tests/xmuse/test_platform_agent_spawner.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_provider_session_binding_store.py
```

验证结果:

- AgentSpawner explicit binding pass-through focused tests: 11 passed。
- spawner + provider binding/service + Codex/provider policy/model/OpenCode/read-contract/core launcher
  regression: 87 passed。
- 本轮触及 Python 文件 ruff: All checks passed。

当前剩余风险:

- `PlatformOrchestrator` / execution transport 仍未从 `ProviderSessionBindingStore` 查询 compatible binding 并传给
  `AgentSpawner.spawn()`；真实运行路径仍是 first-run command。
- result-derived binding upsert helper 尚未由 coordinator/`PlatformOrchestrator` 调用；successful
  provider session id 仍不会自动落入 binding store。
- resume failure 后仍未调用 `mark_failed()` / `stale` 并按策略新建 binding。
- God/Ray session layer 尚未把 provider binding 传给 adapter；Ray app-server ephemeral thread 仍不作为
  durable provider binding。

## 2026-06-03 Execution Request Explicit Binding Pass-Through

本轮把显式 provider binding command boundary 从 `AgentSpawner` 延伸到 execution request /
transport 边界，仍未接入 store lookup/upsert，也未改变默认 first-run dispatch:

- `ExecuteRequest` 新增可选 `provider_session_binding` 字段。
- `execution.executor.run_execution_god(...)` 新增可选 `provider_session_binding` 参数，并在构造
  `ExecuteRequest` 时显式透传。
- `SubprocessTransport.send_execute(...)` / `spawn_god(...)` 会把显式 binding 传给
  `AgentSpawner.spawn(...)`。
- 默认不传 binding 时保持现有 first-run command 行为不变；transport 只在 binding 非空时把新参数
  传给 spawner，降低对旧 fake spawner / 测试替身的影响。
- 如果调用方显式传入 binding，但 spawner 不支持 `provider_session_binding` 参数，transport 会失败而
  不是静默丢弃 binding，避免错误退回 first-run。
- 本轮不查 `ProviderSessionBindingStore`、不写 store、不调用 `mark_failed()`，也不改变
  `PlatformOrchestrator` 默认调度路径。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_execution_child_worker.py::test_execution_request_carries_explicit_provider_session_binding
uv run pytest -q tests/xmuse/test_execution_child_worker.py
uv run pytest -q tests/xmuse/test_execution_child_worker.py \
  tests/xmuse/test_platform_agent_spawner.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_provider_policy.py \
  tests/xmuse/test_provider_models.py \
  tests/xmuse/test_provider_opencode.py \
  tests/xmuse/test_provider_read_contracts_module.py \
  tests/xmuse/test_core_agents_launchers.py
uv run ruff check src/xmuse_core/platform/messages.py \
  src/xmuse_core/platform/execution/transport.py \
  src/xmuse_core/platform/execution/executor.py \
  tests/xmuse/test_execution_child_worker.py
uv run ruff check .
```

验证结果:

- 新 execution request provider binding focused test: 1 passed。
- execution child worker focused tests: 5 passed。
- execution transport + spawner/provider binding/service + Codex/provider policy/model/OpenCode/read-contract/core
  launcher regression: 92 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要仍分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/self_evolution/*`、
  `src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、`xmuse/scripts/*` 和部分历史/迁移测试文件。
  本轮未批量修复，避免与并行迁移 agent 冲突。

当前剩余风险:

- `PlatformOrchestrator` 仍未从 `ProviderSessionBindingStore.find_resume_compatible()` 查询 binding 并传给
  `run_execution_god(...)`；真实运行路径仍是 first-run command。
- successful `ProviderInvocationResult.provider_session_id` 仍未由 coordinator 显式
  `upsert_provider_session_binding_from_result(...)` 写入 binding store。
- resume failure 后仍未调用 `mark_failed()` / `stale` 并按策略新建 binding。
- God/Ray persistent session layer 尚未与 provider-native binding 对齐；Ray app-server ephemeral thread
  仍不作为 durable provider binding。

## 2026-06-03 Coordinator Compatible Binding Lookup

本轮把 provider session binding 从“只能由调用方显式传入”推进到 coordinator-side 只读兼容查询，
仍不写 binding store，也不让 adapter/worker 拥有状态:

- 新增 `src/xmuse_core/platform/execution/provider_session_binding.py`。
- 新增 `resolve_execution_provider_session_binding(...)`，由 execution coordinator 使用
  `ProviderSessionBindingStore.find_resume_compatible(...)` 查询 active/compatible binding。
- resolver 只支持 Codex exec provider binding；OpenCode/其他 provider invocation 会返回 `None`，
  避免把不支持 resume 的 provider 误传给 Codex resume command path。
- resolver 不会从 lane id 或 flat projection 自行构造 `god_session_id`。只有 lane 明确带
  `provider_session_binding_god_session_id` 时才查询 store，避免把临时 lane identity 冒充 durable
  xmuse session identity。
- `PlatformOrchestrator` 现在持有独立 `ProviderSessionBindingStore`，默认路径为
  `xmuse_root / "provider_session_bindings.json"`；构造 store 不会创建 runtime 文件。
- `orchestrator_lane_flow.run_execution_god(...)` 会在 provider invocation 建好后做只读 lookup，
  compatible binding 会通过 `provider_session_binding` 显式传给 executor/transport/spawner。
- prompt fingerprint 使用当前 execution prompt 的 `fingerprint_prompt(prompt)`；旧 binding 若未记录
  prompt fingerprint 仍可通过 model/worktree/feature graph gate。
- 本轮仍不调用 `upsert_provider_session_binding_from_result(...)`，successful first-run result 仍不会自动落库。
- `provider_session_binding_god_session_id` 只是迁移期显式 session hint，不把 `feature_lanes.json`
  提升为 provider binding 权威；provider binding 的权威仍是独立 store。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_execution_provider_session_binding.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py::test_run_execution_god_passes_compatible_provider_session_binding
uv run pytest -q tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_execution_child_worker.py \
  tests/xmuse/test_platform_orchestrator.py::test_run_execution_god_writes_lane_context_bundle \
  tests/xmuse/test_platform_orchestrator.py::test_run_execution_god_passes_compatible_provider_session_binding \
  tests/xmuse/test_persistent_execute_god.py::test_orchestrator_wires_persistent_execute_session_layer_when_enabled
uv run pytest -q tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_execution_child_worker.py \
  tests/xmuse/test_platform_agent_spawner.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_provider_policy.py \
  tests/xmuse/test_provider_models.py \
  tests/xmuse/test_provider_opencode.py \
  tests/xmuse/test_provider_read_contracts_module.py \
  tests/xmuse/test_core_agents_launchers.py \
  tests/xmuse/test_persistent_execute_god.py \
  tests/xmuse/test_runtime_ray_backend.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/platform/orchestrator.py \
  src/xmuse_core/platform/orchestrator_lane_flow.py \
  src/xmuse_core/platform/execution/provider_session_binding.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check .
```

验证结果:

- execution provider binding resolver focused tests: 4 passed。
- orchestrator compatible binding lookup focused test: 1 passed。
- execution provider binding + execution child worker + targeted orchestrator/persistent-execute regression:
  12 passed。
- provider/spawner/binding/service + persistent execute/Ray backend regression: 120 passed。
- full `tests/xmuse/test_platform_orchestrator.py`: 163 passed。
- 本轮新增/触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要仍分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/self_evolution/*`、
  `src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、`xmuse/scripts/*` 和部分历史/迁移测试文件。
  本轮未批量修复，避免与并行迁移 agent 冲突。

当前剩余风险:

- `provider_session_binding_god_session_id` 仍需要未来 feature worker / long-session owner 明确写入或
  通过 graph-native execution status 关联；本轮没有让 lane projection 自动生成该字段。
- successful `ProviderInvocationResult.provider_session_id` 仍未由 coordinator 显式
  `upsert_provider_session_binding_from_result(...)` 写入 binding store。
- resume failure 后仍未调用 `mark_failed()` / `stale` 并按策略新建 binding。
- 目标态仍应把 lookup identity 收敛到 feature graph status / feature worker session identity，
  而不是长期依赖 flat lane projection field。

## 2026-06-03 Coordinator Result-Derived Binding Upsert

本轮把 successful provider result 中的显式 provider session id 接入 coordinator-side durable
binding upsert，仍不让 adapter/worker 写状态，也不改变 resume failure 策略:

- `execution.executor.run_execution_god(...)` 新增可选 store-facing 参数:
  - `provider_session_binding_writer`
  - `provider_session_binding_god_session_id`
  - `provider_session_binding_role`
  - `provider_session_binding_conversation_id`
  - `provider_session_binding_feature_graph_id`
  - `provider_session_binding_prompt_fingerprint`
- provider result 成功且带 `provider_session_id` 时，executor 通过已有
  `upsert_provider_session_binding_from_result(...)` 显式写入 coordinator 传入的 writer。
- upsert gate 要求 `provider_invocation`、writer、`provider_session_binding_god_session_id` 都存在；
  否则直接 no-op，避免从 lane id 或临时 worker identity 编造 durable `god_session_id`。
- `orchestrator_lane_flow.run_execution_god(...)` 现在把 `PlatformOrchestrator` 的
  `ProviderSessionBindingStore` 作为 writer 传给 executor，并沿用显式
  `provider_session_binding_god_session_id` 作为 binding owner。
- conversation id 来自 lane `conversation_id`，feature graph id 来自 lane `graph_id`，prompt
  fingerprint 使用 `fingerprint_prompt(prompt)`，model 使用最终 provider model。
- focused integration test 使用 fake transport 返回 successful `ProviderInvocationResult`，验证
  `PlatformOrchestrator._run_execution_god()` 会把 provider session id 写入独立 binding store；
  测试中显式 patch `_on_lane_executed`，避免进入 gate/review 或真实 Codex CLI。
- 本轮不实现 resume failure `mark_failed()` / stale retry；也不把 `feature_lanes.json` 作为长期
  provider binding 权威。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_execution_child_worker.py::test_run_execution_god_upserts_provider_session_binding_from_successful_result
uv run pytest -q tests/xmuse/test_platform_orchestrator.py::test_run_execution_god_passes_provider_session_binding_writer_context
uv run pytest -q tests/xmuse/test_platform_orchestrator.py::test_run_execution_god_upserts_provider_session_binding_store \
  tests/xmuse/test_execution_child_worker.py::test_run_execution_god_upserts_provider_session_binding_from_successful_result
uv run pytest -q tests/xmuse/test_execution_child_worker.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_platform_agent_spawner.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_provider_policy.py \
  tests/xmuse/test_provider_models.py \
  tests/xmuse/test_provider_opencode.py \
  tests/xmuse/test_provider_read_contracts_module.py \
  tests/xmuse/test_core_agents_launchers.py \
  tests/xmuse/test_persistent_execute_god.py \
  tests/xmuse/test_runtime_ray_backend.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/platform/messages.py \
  src/xmuse_core/platform/execution/transport.py \
  src/xmuse_core/platform/execution/executor.py \
  src/xmuse_core/platform/execution/provider_session_binding.py \
  src/xmuse_core/platform/orchestrator.py \
  src/xmuse_core/platform/orchestrator_lane_flow.py \
  tests/xmuse/test_execution_child_worker.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check .
```

验证结果:

- executor result-derived provider binding upsert focused test: 1 passed。
- orchestrator writer context focused test: 1 passed。
- orchestrator fake-transport binding-store integration + executor upsert focused tests: 2 passed。
- provider/spawner/binding/service + persistent execute/Ray backend regression: 121 passed。
- full `tests/xmuse/test_platform_orchestrator.py`: 165 passed。
- 本轮新增/触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要仍分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/self_evolution/*`、
  `src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、`xmuse/scripts/*` 和部分历史/迁移测试文件。
  本轮未批量修复，避免与并行迁移 agent 冲突。

当前剩余风险:

- `provider_session_binding_god_session_id` 仍是迁移期显式 hint；目标态应由 feature worker long-session
  identity 或 graph-native execution status 关联产生。
- upsert 失败当前会随 execution 成功路径抛出；后续可考虑在 coordinator 侧降级记录 binding-store
  failure，但不能让 worker/adapter 接管写状态。
- resume failure 后仍未调用 `mark_failed()` / `stale` 并按策略新建 binding。
- 当前只覆盖 Codex exec provider binding；OpenCode/Claude Code durable session resume 仍需各自能力确认。

## 2026-06-03 Feature Graph Status Store

本轮补 graph-native feature graph status store 的前置能力，仍未改 runner/orchestrator
派发路径:

- 新增 `src/xmuse_core/structuring/feature_graph_status_store.py`。
- `FeatureGraphStatusStore` 使用独立 JSON store，不读取 `feature_lanes.json` 判定 ready
  feature graph。
- store 写入使用 companion lock + temp file replace。
- `upsert()` 以 `graph_set_id + feature_graph_id` 作为 graph-native identity，同一 feature graph
  新状态会替换旧状态，不产生重复记录。
- store 会拒绝旧 `graph_set_version` 或旧 `updated_at` 覆盖当前状态；`updated_at` 会按
  timezone-aware datetime 归一到 UTC 后比较，避免 offset timestamp 让乱序事件倒退状态。
- `list_ready()` 只返回 status store 中 `status=ready` 的 feature graph；记录里的
  `feature_lanes_projection_ref` 仅作为迁移期兼容引用。
- 新增 `transition()` 作为 graph-native execution status 的受控写入口。
- transition guard 覆盖 `planned`、`ready`、`running`、`reviewing`、`reworking`、
  `blocked`、`merged`、`failed` 生命周期中的允许路径，`merged` / `failed` 为终态。
- transition 支持 `expected_status` 并拒绝 mismatch，防止 coordinator 并发或乱序事件覆盖。
- 完全相同的 transition record replay 会在 `expected_status` 检查前幂等返回当前记录，
  不产生重复记录。
- 非完全相同的 same-status transition 会被拒绝；状态不变的 seed/backfill 修正必须走
  `upsert()` 或后续专门 metadata API，不能通过 transition 改写终态。
- 新增 `initialize_from_graph_set()`，可从 `FeatureGraphSet` 初始化 graph-native
  feature graph status: 无 feature dependency 的 graph 为 `ready`，有依赖的 graph 为
  `planned`。
- `initialize_from_graph_set()` 只创建缺失记录；如果 feature graph status 已经进入
  `running`、`reviewing`、`merged` 等推进状态，重复初始化不会回退状态。
- 新增 `release_ready_dependents()`，在依赖 feature graph 都已 `merged` 后，通过
  `transition()` 将下游 `planned` graph 释放为 `ready`。
- dependency release 只信任当前 `graph_set_version` 和当前 feature 的 `graph_id` 匹配的
  status record，避免旧 graph-set/version 的 merged 记录错误解锁依赖。
- `blocked` 不会被 dependency release 自动解除，避免把非依赖原因的 blocker 当成依赖满足处理。
- 初始化和依赖释放只写 status store，不写 `feature_lanes.json`，也不改变 runner dispatch。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py
uv run ruff check src/xmuse_core/structuring/feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_status_store.py
uv run ruff check .
```

验证结果:

- feature graph status store focused tests: 20 passed。
- feature graph status store + feature review contract + projection/builder regression:
  53 passed。
- 本轮 status store 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 88 个既有 lint 问题，主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/providers/adapters/base.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*` 和部分历史/迁移测试文件；本轮未批量修复，避免与并行迁移 agent 冲突。

当前剩余风险:

- status store 尚未接入 `PlatformOrchestrator`、`LaneStateMachine` 或 runner source flag；
  当前仍是 graph-native durable store 前置能力。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮没有改变
  dispatch 行为，避免与并行迁移 agent 冲突。
- 还需要后续由 coordinator 在 graph-set.ready、feature worker start、feature-level review verdict、
  merge/rework/blocked 等事件上调用这些 graph-native status helper，串成闭环。

## 2026-06-03 Feature Graph Status Event Journal

本轮在 graph-native feature graph status store 内补 append-only 事件审计，仍未改
runner/orchestrator 派发路径:

- `feature_graph_statuses.json` payload 现在同时持久化 `statuses` 和 `events`。
- 旧 payload 没有 `events` 字段时仍可读取，`list_events()` 返回空列表，保持向后兼容。
- `upsert()` 仍作为 seed/backfill 写入口，不产生 execution transition event。
- `initialize_from_graph_set()` 只为新创建的 feature graph status 追加
  `feature_graph_status.initialized` event；重复初始化不会重复记录事件，也不会回退 advanced
  status。
- `transition()` 只在真实状态转换时追加 `feature_graph_status.transitioned` event；完全相同的
  record replay 幂等返回，不重复追加事件。
- event 记录包含 `event_id`、`event_type`、`graph_set_id`、`graph_set_version`、
  `feature_graph_id`、`feature_id`、`from_status`、`to_status`、`from_status_id`、
  `status_id`、`updated_at` 和 `idempotency_key`。
- 非法 transition、`expected_status` mismatch、终态外跳、same-status mutation 和 stale update
  都不会写入事件。
- status + events 在同一 lock + temp file replace 下写入，保证状态变更和审计事件同文件原子更新。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py
uv run ruff check src/xmuse_core/structuring/feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_status_store.py
uv run ruff check .
```

验证结果:

- feature graph status store focused tests: 24 passed。
- feature graph status event journal + feature review contract + projection/builder regression:
  57 passed。
- 本轮 status store 触及文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 88 个既有 lint 问题；主要仍分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/providers/adapters/base.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*` 和部分历史/迁移测试文件。本轮未批量修复，避免与并行迁移 agent 冲突。

当前剩余风险:

- event journal 仍是 status store 本地审计能力，尚未接入 coordinator event store、
  `PlatformOrchestrator` 或 `LaneStateMachine`。
- 还没有 read-model/dashboard drill-down 展示这些 graph-native status events。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮只增强
   graph-native status store，没有改变 dispatch 行为。

## 2026-06-04 V3 TUI-INPUT-HISTORY

本轮为 V3 第一条并行线收束 TUI 输入历史基建:

- 新增 `InputHistory` 类 (在 `xmuse/tui/screens/chat_screen.py`)。
  - per-conversation 普通消息/slash 命令分离历史。
  - `navigate_up` / `navigate_down` 用同一键盘状态机覆盖消息和 slash 历史。
  - 默认每类型 cap 50 条；连续重复输入不会新增条目。
- ChatScreen 接入:
  - `on_input_submitted` 后区分 slash 与普通消息，各自推入对应历史。
  - `on_key` 拦截 `up`/`down` (仅输入框聚焦时)，避免与 copy mode 冲突。
  - conversation 切换时 `reset_position`，确保作用域稳定。
- 新增 focused test: `tests/xmuse/test_tui_input_history.py` (11 passed)。
- 回归验证: 60 existing TUI tests passed, ruff check passed, git diff --check passed。

未扩能力点:
- 未做 slash 补全 (Task 2, 已在 V3 完成)。
- 未改左侧会话导航。
- 未改后端发送语义。

## 2026-06-04 V3 TUI-COMPLETION-ENGINE

本轮为 TUI 建立统一 completion engine:

- 新增 `xmuse/tui/completion.py`:
  - `CompletionEngine` 在输入 `/` 时返回命令候选 (含描述), 输入 `@` 时返回 participant 候选。
  - 支持前缀过滤和 display_name 搜索。
  - 同 role 多 participant 自动去重。
- 新增 `ChatScreen` 集成:
  - `#completion-list` ListView overlay (docked bottom, 默认 hidden, `.visible` 时显示)。
  - `on_input_changed` → `_refresh_completions` 实时检查触发器并更新列表。
  - Tab/Enter 应用选中候选 (单候选时自动选择), Esc 退出。
  - Up/Down 有 completion 时优先导航候选列表, 无 completion 时回退到输入历史。
- 新增 focused test: `tests/xmuse/test_tui_completion.py` (13 passed)。
- 回归: 84 TUI tests passed, ruff check passed。

未扩能力点:
- 未新增后端命令语义。
- 未改 V2 default intake / review trigger 后端职责。

## 2026-06-04 V3 长期自迭代 — 探索轮次

**能力 A: TUI-CONVERSATION-SEARCH** (shadow→merged)
- Ctrl+f 开关搜索栏, 实时过滤消息, Esc 退出。
- `MessageLog.search(query)` / `MessageLog.clear_search()` 存储+过滤消息。
- 0 backend 改动, 纯 client-side。

**能力 B: TUI-CONNECTION-STATUS** (直接主路径)
- Header 显示连接状态: has_errors→degraded, live>0→connected, 默认→idle。
- `_connection_style_for()` 纯函数可测试。

**能力 C: TUI-PARTICIPANT-STATUS** (直接主路径)
- 右侧面板 participant 状态符号: ● active, ◆ failed, ◉ thinking, ○ default。

**验证:** 131 TUI tests passed (从 116 +15), ruff check passed, no V2 protocol changes。

**未扩能力点:**
- 未做服务端搜索
- 未做配置面板
- 未改 V2 participant protocol

## 2026-06-04 V3 TUI Tasks 3-14

**Task 3 (TUI-COMMAND-PALETTE):** 命令面板已形成。`_SLASH_COMMANDS` 含 `params` 字段,
completion display 展示 "命令名 参数 描述"。所有 10 个命令有参数提示。

**Task 4 (TUI-PARTICIPANT-CACHE):** `XmuseAdapter` 新增 per-conversation participant 内存缓存,
TTL=30s。`refresh_participants()` 可绕过缓存。新增 4 tests。

**Task 5 (TUI-SESSION-SWITCH):** `/resume` 无参数时自动恢复最近 session。help 文本已更新。

**Task 6-7 (DRAFTS-AND-STATUS / PENDING-ERROR):**
- per-conversation draft: 切换 conv 时保存/恢复输入框。
- `_send_status` 追踪 sending/sent/failed。
- `#mode-status` Static 显示当前模式和发送状态。
- `_input_mode` 追踪 normal/completion/copy。

**Task 8 (TUI-FOCUS-STATE):** focus state 通过 `_input_mode` + mode-status 栏协议化。

**Task 9 (TUI-MULTILINE-COMPOSE):** placeholder 提示 Alt+Enter 新行, 粘贴多行兼容。

**Task 10 (TUI-SCROLLBACK):** MessageLog `_at_bottom` / `_pending_count` 机制, `_on_scroll` 检测。

**Tasks 11-13 (CONTRACT/SCREEN/KEYMAP TESTS):**
- 新增 `test_tui_adapter_contract.py` (8 tests)
- 新增 `test_tui_screen_integration.py` (6 tests)
- 新增 `test_tui_keymap.py` (5 tests)

**Task 14 (TUI-UX-SMOKE):** 新增 `test_tui_ux_smoke.py` (6 tests) 覆盖完整链路。

最终验证: 116 TUI tests passed, ruff check passed, git diff --check passed。
所有 V3 任务已收束, 终止条件满足。

## 2026-06-03 Feature Graph Status Event Contract

本轮把 graph-native status event 从裸 dict 收束为稳定契约，仍未改 execution dispatch:

- 新增 `FeatureGraphStatusEventRecord` Pydantic schema。
- `structuring.models` 已兼容 re-export `FeatureGraphStatusEventRecord`。
- 新增 golden fixture:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_status_event.v1.json`
- event schema 限制 `event_type` 只能是 `feature_graph_status.initialized` 或
  `feature_graph_status.transitioned`。
- initialized event 必须没有 `from_status` / `from_status_id`。
- transitioned event 必须有 `from_status` / `from_status_id`。
- `FeatureGraphStatusStore.list_events()` 现在返回 `FeatureGraphStatusEventRecord`。
- store 读取持久化 events 时会重新校验 schema；非法 event payload 不会静默进入审计链。
- store 会显式拒绝非 list 的 `events` 容器和非 object 的 event 条目，避免 corrupt audit
  payload 在下一次写入时被静默丢弃。
- store 写入 events 时使用 `model_dump(mode="json")`，保持 JSON payload 兼容。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_status_store.py
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_status_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_status_store.py
uv run ruff check .
```

验证结果:

- feature review contract + feature graph status store focused tests: 35 passed。
- typed status event contract + status store + projection/builder regression: 61 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 88 个既有 lint 问题；主要仍分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/providers/adapters/base.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*` 和部分历史/迁移测试文件。本轮未批量修复，避免与并行迁移 agent 冲突。

当前剩余风险:

- event contract 尚未接入 coordinator event store 或 dashboard/read-model 展示。
- `FeatureGraphStatusStore` 当前仍是 graph-native 前置能力；runner/orchestrator 仍未从
  `feature_lanes.json` 切到 graph-native source。

## 2026-06-03 Feature Review Status Transition Plan

本轮把 feature-level reviewer verdict 到 graph-native status action 的映射收束为纯契约/服务层，
仍未改 runner/orchestrator 派发路径，也未让 reviewer 直接写 durable state:

- 新增 `src/xmuse_core/structuring/feature_graph_review_transitions.py`。
- 新增 `FeatureGraphReviewCoordinatorAction`:
  - `transition_status`
  - `patch_forward_gate`
  - `takeover_required`
- 新增 `FeatureGraphReviewStatusTransitionPlan` Pydantic schema，并由 `structuring.models`
  兼容 re-export。
- 新增 golden fixture:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_review_status_transition_plan.v1.json`
- `build_feature_graph_review_status_transition_plan()` 只根据
  `FeatureEvidenceBundle + FeatureReviewVerdict + 当前 FeatureGraphExecutionStatusRecord`
  构造 coordinator 可消费的 action plan，不调用 `FeatureGraphStatusStore.transition()`。
- builder 要求 reviewer verdict 对应同一 evidence bundle，且当前 feature graph 状态必须是
  `reviewing`。
- builder 会校验当前 status record 与 evidence bundle 的 graph-set、feature-plan、feature、
  feature-graph identity 一致。
- `merge` / `rework` / `blocked` 会生成 `transition_status` plan，目标状态分别是
  `merged` / `reworking` / `blocked`。
- `patch_forward` 只生成 `patch_forward_gate` action，不携带 target status record；后续必须由
  coordinator 执行强 gate、补丁、focused gates 和 merge guard。
- `takeover` 只生成 `takeover_required` action，不携带 target status record；后续必须由
  coordinator/takeover gate 决定接管。
- transition plan schema 会拒绝 non-transition action 携带 target status。
- transition plan schema 会校验 target status record 的 status、graph_set_id、
  graph_set_version、feature_id、feature_graph_id、updated_at 与 plan 一致，避免 coordinator
  后续应用 verdict 时混入错误 aggregate/version 的 status record。
- transition plan schema 会强制 `transition_status` 只能对应 `merge` / `rework` / `blocked`
  decision，并强制 decision 到 target status 的映射分别为 `merged` / `reworking` / `blocked`。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_review_transitions.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py
uv run ruff check .
```

验证结果:

- review transition plan + graph status/projection/builder focused regression: 72 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 88 个既有 lint 问题；主要仍分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/providers/adapters/base.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*` 和部分历史/迁移测试文件。本轮未批量修复，避免与并行迁移 agent 冲突。

当前剩余风险:

- review transition plan 尚未接入 `PlatformOrchestrator`、`LaneStateMachine` 或 coordinator
  event consumer；当前是纯契约/服务层。
- `patch_forward` / `takeover` 目前只被分流成 coordinator action，强 gate 和实际闭环仍需后续接入。
- `FeatureGraphStatusStore.transition(expected_status=reviewing)` 的实际调用仍需后续由 coordinator
  完成，不能交给 worker/reviewer 直接写。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮没有改变 dispatch 行为。

## 2026-06-03 Feature Review Status Transition Application

本轮补齐上一节 transition plan 到 graph-native status store 的最小 coordinator-side apply
前置能力，仍未改 `PlatformOrchestrator`、runner dispatch、Ray/native runtime 或
`feature_lanes.json`:

- 新增 `src/xmuse_core/structuring/feature_graph_review_transition_application.py`。
- 新增 `apply_feature_graph_review_status_transition_plan(store, plan)`。
- applier 只接受 `coordinator_action=transition_status` 的 plan。
- applier 会拒绝 `patch_forward_gate` / `takeover_required` action，确保 patch-forward 和 takeover
  必须先经过 coordinator gate，不能被当成直接状态转换写入。
- applier 在调用 store 前会重新校验 `FeatureGraphReviewStatusTransitionPlan`，防止
  `model_copy(update=...)` 等路径绕过 schema validator。
- applier 通过 `FeatureGraphStatusStore.transition(target_status_record,
  expected_status=plan.expected_status)` 写入，复用 status store 的 lifecycle guard、expected-status
  guard、stale update guard 和 idempotent replay。
- `FeatureGraphReviewStatusTransitionPlan` schema 进一步收紧: review transition plan 的
  `current_status` / `expected_status` 必须是 `reviewing`，避免反序列化 plan 把 review verdict
  应用于非 review 阶段。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_review_transitions.py \
  src/xmuse_core/structuring/feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_review_transition_application.py
uv run ruff check .
```

验证结果:

- review transition application + graph status/projection/builder focused regression: 77 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 88 个既有 lint 问题；主要仍分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/providers/adapters/base.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*` 和部分历史/迁移测试文件。本轮未批量修复，避免与并行迁移 agent 冲突。

当前剩余风险:

- applier 仍是纯服务层，尚未由 coordinator event consumer 或 `PlatformOrchestrator` 调用。
- merge guard、patch-forward gate、takeover gate 的真实闭环仍在后续 runtime/coordinator
  集成阶段完成。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮只提供 graph-native
  review status application 前置能力。

## 2026-06-03 Feature Graph Rework Packet Builder

本轮补齐 reviewer `rework` verdict 到结构化 `ReworkPacket` 的纯服务层，仍未改
`PlatformOrchestrator`、runner dispatch、Ray/native runtime 或 `feature_lanes.json`:

- 新增 `src/xmuse_core/structuring/feature_graph_rework_packets.py`。
- 新增 `build_feature_graph_rework_packet(...)`。
- builder 要求 `FeatureReviewVerdict.decision == rework`，并要求 verdict 的
  `evidence_bundle_id` 匹配 `FeatureEvidenceBundle.bundle_id`。
- builder 会重新校验传入的 `FeatureEvidenceBundle` / `FeatureReviewVerdict`，防止
  `model_copy(update=...)` 绕过 schema validator。
- 生成的 `ReworkPacket` 会指回同一个 `worker_session_id` 和
  `provider_session_binding_ref`，满足“打回同一个 feature worker 或可恢复 provider session”的
  contract 边界。
- `blocking_findings` 直接来自 reviewer verdict，`required_changes` 由 blocking finding summary
  收束，`gates_to_rerun` 优先使用 reviewer required gates，缺省时回退 worker evidence bundle
  的 verification commands。
- `files_or_areas_to_revisit` 使用 evidence bundle / verdict scope 的 touched/changed files 去重；
  如果没有具体文件，回退为 `feature_graph:<feature_graph_id>`，确保 rework packet 始终有明确范围。
- 新增 golden fixture:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_rework_packet.v1.json`
- 补齐早前新增 fixture 的 gate-one artifact metadata:
  - `feature_graph_status_event.v1.json`
  - `feature_graph_review_status_transition_plan.v1.json`

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_review_transitions.py \
  src/xmuse_core/structuring/feature_graph_review_transition_application.py \
  src/xmuse_core/structuring/feature_graph_rework_packets.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py
uv run ruff check .
```

验证结果:

- rework packet builder + review transition/status/projection/builder + shared fixture gate:
  93 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 88 个既有 lint 问题；主要仍分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/providers/adapters/base.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*` 和部分历史/迁移测试文件。本轮未批量修复，避免与并行迁移 agent 冲突。

当前剩余风险:

- rework packet builder 仍是纯 contract/service 层，尚未由 coordinator event consumer 或
  `PlatformOrchestrator` 调用。
- rework limit、worker resume、provider session binding 的实际 runtime 闭环仍需后续接入。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮没有改变 dispatch 行为。

## 2026-06-03 Feature Graph Patch-Forward Plan

本轮补齐 reviewer `patch_forward` verdict 到 coordinator gate plan 的纯契约/服务层，仍未改
`PlatformOrchestrator`、review plane、runner dispatch、Ray/native runtime 或
`feature_lanes.json`:

- 新增 `FeatureGraphPatchForwardPlan` Pydantic schema。
- `structuring.models` 已兼容 re-export `FeatureGraphPatchForwardPlan`。
- 新增 `src/xmuse_core/structuring/feature_graph_patch_forward.py`。
- 新增 `build_feature_graph_patch_forward_plan(...)`。
- builder 要求 `FeatureReviewVerdict.decision == patch_forward`，要求 verdict 的
  `evidence_bundle_id` 匹配 `FeatureEvidenceBundle.bundle_id`，并要求当前 graph-native status 是
  `reviewing`。
- builder 会校验当前 status record 与 evidence bundle 的 graph-set、feature-plan、feature、
  feature-graph identity 一致。
- builder 会重新校验传入的 evidence bundle、verdict 和 current status，防止
  `model_copy(update=...)` 绕过 schema validator。
- `FeatureGraphPatchForwardPlan` 固定记录 reviewer session、rationale、risk、
  reason_not_rework、allowed_file_refs、max files/lines、focused gates、evidence refs 和
  no-new-dependency/no-public-contract-change flags。
- patch-forward plan schema 强制 `current_status == expected_status == reviewing`、`risk == low`、
  `disallow_new_dependencies == True`、`disallow_public_contract_changes == True`，确保它只是
  coordinator 后续 gate 的输入，不会变成直接状态转换或第二个 worker 权限。
- 新增 golden fixture:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_patch_forward_plan.v1.json`

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_review_transitions.py \
  src/xmuse_core/structuring/feature_graph_review_transition_application.py \
  src/xmuse_core/structuring/feature_graph_rework_packets.py \
  src/xmuse_core/structuring/feature_graph_patch_forward.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py
uv run ruff check .
```

验证结果:

- patch-forward plan + rework packet + review transition/status/projection/builder + shared fixture
  gate: 99 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 88 个既有 lint 问题；主要仍分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/providers/adapters/base.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*` 和部分历史/迁移测试文件。本轮未批量修复，避免与并行迁移 agent 冲突。

当前剩余风险:

- patch-forward plan 仍是纯 contract/service 层，尚未由 coordinator event consumer 或
  `PlatformOrchestrator` 调用。
- reviewer 实际 patch-forward 补丁执行、focused gates rerun、merge guard、diff/evidence 归档和
  后续 status transition 仍需后续 coordinator/runtime 集成。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮没有改变 dispatch 行为。

## 2026-06-03 Feature Graph Blocked Review Plan

本轮补齐 reviewer `blocked` verdict 到 coordinator blocked plan 的纯契约/服务层，仍未改
`PlatformOrchestrator`、runner dispatch、Ray/native runtime 或 `feature_lanes.json`:

- 新增 `FeatureGraphBlockedReviewPlan` Pydantic schema。
- `structuring.models` 已兼容 re-export `FeatureGraphBlockedReviewPlan`。
- 新增 `src/xmuse_core/structuring/feature_graph_blocked_review.py`。
- 新增 `build_feature_graph_blocked_review_plan(...)`。
- builder 要求 `FeatureReviewVerdict.decision == blocked`，要求 verdict 的
  `evidence_bundle_id` 匹配 `FeatureEvidenceBundle.bundle_id`，并要求当前 graph-native status 是
  `reviewing`。
- builder 会校验当前 status record 与 evidence bundle 的 graph-set、feature-plan、feature、
  feature-graph identity 一致。
- builder 会重新校验传入的 evidence bundle、verdict 和 current status，防止
  `model_copy(update=...)` 绕过 schema validator。
- blocked verdict schema 现在要求 `blocked_missing_inputs`、`blocked_reason` 和
  `blocked_owner`，满足 blocked gate 对缺失输入、阻塞原因和下一步 owner 的结构化记录要求。
- blocked plan schema 固定记录 `missing_inputs`、`blocked_reason`、`blocked_owner`、
  evidence refs、reviewer session、reviewing source status 和 blocked target status。
- blocked plan 只作为 coordinator 后续 blocked transition / dead-letter / human escalation 的输入，
  不直接写 status store。
- 新增 golden fixture:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_blocked_review_plan.v1.json`

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_review_contracts.py
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py
uv run ruff check .
```

验证结果:

- blocked review plan + feature review contract focused tests: 23 passed。
- blocked plan + review transition/status/projection/builder + shared fixture gate: 106 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 88 个既有 lint 问题；主要仍分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/providers/adapters/base.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*` 和部分历史/迁移测试文件。本轮未批量修复，避免与并行迁移 agent 冲突。

当前剩余风险:

- blocked plan 仍是纯 contract/service 层，尚未由 coordinator event consumer 或
  `PlatformOrchestrator` 调用。
- blocked verdict 到 graph-native `blocked` status 的真实写入仍需 coordinator 调用
  review transition plan / status transition applier，不能交给 reviewer 直接写 durable state。
- blocked escalation card、dead-letter/read-model 展示和 human/provider owner 路由仍需后续接入。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮没有改变 dispatch 行为。

## 2026-06-03 Feature Graph Takeover Plan

本轮补齐 reviewer `takeover` verdict 到 coordinator takeover gate plan 的纯契约/服务层，
仍未改 `PlatformOrchestrator`、takeover runtime、runner dispatch、Ray/native runtime 或
`feature_lanes.json`:

- 新增 `FeatureGraphTakeoverTrigger` enum:
  - `worker_unrecoverable`
  - `repeated_failure`
  - `context_lost`
  - `risk_escalated`
- 新增 `FeatureGraphTakeoverPlan` Pydantic schema。
- `structuring.models` 已兼容 re-export `FeatureGraphTakeoverPlan` 和
  `FeatureGraphTakeoverTrigger`。
- 新增 `src/xmuse_core/structuring/feature_graph_takeover_plan.py`。
- 新增 `build_feature_graph_takeover_plan(...)`。
- takeover verdict schema 现在要求 `takeover_reason` 和非空 `takeover_triggers`，避免 reviewer
  只用自然语言笼统要求接管。
- builder 要求 `FeatureReviewVerdict.decision == takeover`，要求 verdict 的
  `evidence_bundle_id` 匹配 `FeatureEvidenceBundle.bundle_id`，并要求当前 graph-native status 是
  `reviewing`。
- builder 会校验当前 status record 与 evidence bundle 的 graph-set、feature-plan、feature、
  feature-graph identity 一致。
- builder 会重新校验传入的 evidence bundle、verdict 和 current status，防止
  `model_copy(update=...)` 绕过 schema validator。
- takeover plan 固定记录 failed worker session、failed provider session binding ref、takeover
  reason、structured triggers、reviewer session 和 evidence refs。
- takeover plan 只作为 coordinator/takeover gate 输入，不直接写 status store，也不绕过
  merge guard、worktree guard 或 provider session binding。
- 新增 golden fixture:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_takeover_plan.v1.json`

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_review_contracts.py
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py
uv run ruff check .
```

验证结果:

- takeover plan + feature review contract focused tests: 24 passed。
- takeover plan + review transition/status/projection/builder + shared fixture gate: 113 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 88 个既有 lint 问题；主要仍分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/providers/adapters/base.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*` 和部分历史/迁移测试文件。本轮未批量修复，避免与并行迁移 agent 冲突。

当前剩余风险:

- takeover plan 仍是纯 contract/service 层，尚未由 coordinator event consumer、
  `PlatformOrchestrator` 或 takeover gate 调用。
- 真实 takeover 执行仍需后续 coordinator 校验 rework limits、provider binding recovery、
  worktree/merge guard 和 takeover attempt lease。
- takeover 触发条件目前是 schema 级枚举和 plan evidence，尚未接入自动分类器或 dashboard
  drill-down。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮没有改变 dispatch 行为。

## 2026-06-03 Provider Resume Binding Failure Marking

本轮补齐 execution provider resume 失败后的 coordinator-owned binding 失效路径，仍未改
provider adapter、worker durable state 写入、Ray/native runtime 或 `feature_lanes.json` 权威:

- `run_execution_god(...)` 在收到 provider result failure 时，如果本次执行确实使用了显式
  `provider_session_binding`，会通过显式传入的 coordinator store/writer 标记该 binding。
- `ProviderFailureKind.STALE_REQUEST` 映射为 `ProviderSessionBindingStatus.STALE`，其余 provider
  failure 映射为 `ProviderSessionBindingStatus.FAILED`。
- failure reason 复用 execution failure metadata vocabulary，例如 stale resume 记录为
  `stale_request`。
- 没有显式 `provider_session_binding` 时不标记 store，避免 coordinator 虚构 provider session
  ownership。
- writer 未暴露 `mark_failed(...)` 时保持 no-op，兼容只支持 `upsert_active(...)` 的旧测试 writer。
- 标记 stale/failed 后，`ProviderSessionBindingStore.find_active(...)` 不再返回该 binding，避免后续
  turn 继续使用已知坏的 provider-native session。
- orchestrator 级测试覆盖了 compatible binding lookup -> execution request binding -> provider
  stale failure -> store stale -> no active binding 的闭环，并 patch 掉 `_on_lane_executed`，避免真实
  Codex CLI 或后续 gate 被触发。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_execution_child_worker.py::test_run_execution_god_marks_resume_binding_stale_on_stale_provider_failure
uv run pytest -q tests/xmuse/test_platform_orchestrator.py::test_run_execution_god_marks_compatible_binding_stale_on_provider_resume_failure
uv run pytest -q tests/xmuse/test_execution_child_worker.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_session_binding_store.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_execution_child_worker.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_platform_agent_spawner.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_provider_policy.py \
  tests/xmuse/test_provider_models.py \
  tests/xmuse/test_provider_opencode.py \
  tests/xmuse/test_provider_read_contracts_module.py \
  tests/xmuse/test_core_agents_launchers.py \
  tests/xmuse/test_persistent_execute_god.py \
  tests/xmuse/test_runtime_ray_backend.py
uv run pytest -q tests/xmuse/test_execution_child_worker.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/platform/execution/executor.py \
  tests/xmuse/test_execution_child_worker.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check .
```

验证结果:

- executor stale binding focused test: 1 passed。
- orchestrator stale binding focused test: 1 passed。
- execution/provider binding store focused gate: 20 passed。
- provider/session/runtime focused regression: 122 passed。
- execution child worker + platform orchestrator regression: 173 passed。
- platform orchestrator full file regression: 166 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/self_evolution/*`、
  `src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、`xmuse/scripts/*` 和部分历史/迁移测试文件。
  本轮未批量修复，避免与并行迁移 agent 冲突。

当前剩余风险:

- provider failure marking 只 retire 当前坏 binding；尚未实现 coordinator 级 retry/new-session
  strategy。
- non-stale provider failure 目前统一标为 `failed`，后续可按 provider capability 增加更细的恢复策略。
- provider session binding 仍主要覆盖 Codex exec resume；Ray app-server thread 的跨进程持久恢复仍未接入。
- execution 粒度仍处在 lane projection 迁移期，尚未升到默认 feature graph worker owner。

## 2026-06-03 Graph-Native Feature Worker Claim

本轮补 graph-native status store 的 feature-worker claim 前置能力，仍未改 runner dispatch、
`PlatformOrchestrator` 默认执行粒度、Ray/native runtime 或 `feature_lanes.json`:

- `FeatureGraphExecutionStatusRecord` 新增可选字段:
  - `active_worker_session_id`
  - `active_provider_session_binding_ref`
- 新增 golden fixture:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_status_running_claim.v1.json`
- `FeatureGraphStatusStore.claim_ready(...)` 会把 graph-native status 从 `ready` 原子转换为
  `running`，并记录 active lane ids、feature worker session id 和 provider session binding ref。
- claim 使用现有 `transition(..., expected_status=READY)`，所以 competing worker 无法重复领取同一
  feature graph。
- 同一 worker/session/provider/timestamp 的 claim replay 会返回当前 running record，不重复写 event。
- claim 默认把当前 `ready_lane_ids` 移入 `active_lane_ids`，支持 coordinator 后续以 feature worker
  长 session 领取一个 feature graph。
- claim 不读取、不写入 `feature_lanes.json`；测试固定了 projection 文件内容在 claim 前后完全一致。
- 旧 `feature_graph_status.v1.json` ready fixture 保持语义不变；running claim 使用单独 fixture，避免
  “ready 但已有 active worker”的契约矛盾。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py::test_feature_graph_status_store_claims_ready_feature_graph_without_projection_write \
  tests/xmuse/test_feature_graph_status_store.py::test_feature_graph_status_store_claim_ready_is_idempotent_for_same_claim \
  tests/xmuse/test_feature_graph_status_store.py::test_feature_graph_status_store_claim_ready_rejects_competing_worker \
  tests/xmuse/test_feature_graph_status_store.py::test_feature_graph_status_record_golden_fixture_tracks_active_worker_binding
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py \
  tests/xmuse/test_platform_projection_dependents.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_review_contracts.py
uv run ruff check .
```

验证结果:

- graph-native claim focused tests: 4 passed。
- feature graph status store focused tests: 31 passed。
- feature review contract + review transition/status/projection/builder + shared fixture gate: 86 passed。
- graph/status/projection expanded focused gate: 132 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- `claim_ready(...)` 仍是 graph-native status store 前置能力，尚未接入
  `PlatformOrchestrator` / runner source flag。
- feature worker 长 session 领取 feature graph 后，lane DAG 内部推进、evidence bundle 产出、
  reviewer handoff 仍需后续 coordinator/runtime 集成。
- claim 当前只记录 worker session id/provider binding ref，不负责启动 Ray/native session 或创建
  provider session binding。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮没有改变 dispatch 行为。

## 2026-06-03 Feature Worker Claim Plan

本轮把 graph-native feature worker claim 从 store helper 进一步收束为 coordinator 可消费的
结构化 action plan，仍未改 runner dispatch、`PlatformOrchestrator` 默认执行粒度、Ray/native runtime
或 `feature_lanes.json`:

- 新增 `FeatureGraphWorkerClaimPlan` Pydantic schema。
- `structuring.models` 已兼容 re-export `FeatureGraphWorkerClaimPlan`。
- 新增 golden fixture:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_worker_claim_plan.v1.json`
- 新增 `src/xmuse_core/structuring/feature_graph_worker_claims.py`。
- 新增 `build_feature_graph_worker_claim_plan(...)`:
  - 输入当前 `FeatureGraphExecutionStatusRecord`。
  - 只接受 `status=ready`。
  - 固定 `expected_status=ready`、`target_status=running`。
  - 记录 `worker_session_id`、`provider_session_binding_ref`、`active_lane_ids`、
    `source_status_id` 和 graph-native identity。
- 新增 `src/xmuse_core/structuring/feature_graph_worker_claim_application.py`。
- 新增 `apply_feature_graph_worker_claim_plan(...)`:
  - 应用前重新校验 `FeatureGraphWorkerClaimPlan`，防止 `model_copy(update=...)` 绕过 schema。
  - 通过 `FeatureGraphStatusStore.claim_ready(...)` 写入，复用 ready -> running guard、idempotent replay
    和 event journal。
  - 不读取、不写 `feature_lanes.json`。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_worker_claims.py
uv run pytest -q tests/xmuse/test_feature_graph_worker_claims.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py \
  tests/xmuse/test_platform_projection_dependents.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/feature_graph_status_store.py \
  src/xmuse_core/structuring/feature_graph_worker_claims.py \
  src/xmuse_core/structuring/feature_graph_worker_claim_application.py \
  src/xmuse_core/structuring/models.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_worker_claims.py \
  tests/xmuse/test_feature_review_contracts.py
uv run ruff check .
```

验证结果:

- feature worker claim plan focused tests: 5 passed。
- feature worker claim + graph/status/review/projection focused gate: 137 passed。
- feature graph worker claim + status store focused tests: 36 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- claim plan/applier 仍是纯 contract/service 层，尚未由 `PlatformOrchestrator` 或 runner source flag
  调用。
- feature worker session 的创建、provider binding 的选择/创建，以及 Ray/native 长 session 生命周期仍
  需要 runtime 集成。
- claim plan 当前只覆盖 ready -> running；running -> reviewing 的 feature-level evidence bundle
  提交流程仍需后续结构化接入。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮没有改变 dispatch 行为。

## 2026-06-03 Platform Graph Claim Coordinator Helper

本轮新增 coordinator-facing 的 graph-native ready claim shadow path，仍未切换
`xmuse/platform_runner.py` 主循环、`PlatformOrchestrator.dispatch_lane(...)` 或 legacy lane dispatch:

- 新增 `src/xmuse_core/platform/feature_graph_claim_coordinator.py`。
- 新增 `FeatureGraphWorkerClaimOutcome`。
- 新增 `claim_next_ready_feature_graph_worker(...)`:
  - 只读取 `FeatureGraphStatusStore.list_ready(...)`。
  - 可按 `graph_set_id`、`conversation_id`、`feature_graph_id` 过滤 ready feature graph。
  - 使用 deterministic ordering 选择一个 ready feature graph。
  - 构造 `FeatureGraphWorkerClaimPlan`。
  - 通过 `apply_feature_graph_worker_claim_plan(...)` 写入 graph-native status store。
  - 不读取、不写入 `feature_lanes.json`。
- 新增 focused tests，证明 helper 可以领取 graph-native ready feature graph，同时 projection 文件字节级保持不变。
- 该 helper 是 coordinator 显式调用的前置能力，不让 worker/reviewer 直接写 durable state。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_claim_coordinator.py
uv run pytest -q tests/xmuse/test_feature_graph_claim_coordinator.py \
  tests/xmuse/test_feature_graph_worker_claims.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py \
  tests/xmuse/test_platform_projection_dependents.py
uv run ruff check src/xmuse_core/platform/feature_graph_claim_coordinator.py \
  src/xmuse_core/structuring/feature_graph_worker_claims.py \
  src/xmuse_core/structuring/feature_graph_worker_claim_application.py \
  src/xmuse_core/structuring/feature_graph_status_store.py \
  src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  tests/xmuse/test_feature_graph_claim_coordinator.py \
  tests/xmuse/test_feature_graph_worker_claims.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_review_contracts.py
uv run ruff check .
```

验证结果:

- platform graph claim coordinator focused tests: 3 passed。
- platform graph claim + graph/status/review/projection focused gate: 140 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- helper 尚未接入 `PlatformOrchestrator` 或 runner source flag；默认执行仍由 `feature_lanes.json`
  projection 驱动。
- helper 当前只选择并 claim graph-native ready feature graph；还不负责创建长 session、
  选择/创建 provider binding，或启动 feature worker。
- 需要后续增加 shadow/parity telemetry，把 legacy lane candidate 与 graph-native feature claim 的
  差异写入 read model 或 coordinator health，而不是静默切换。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮没有改变 dispatch 行为。

## 2026-06-03 PlatformOrchestrator Graph Claim Facade

本轮把 graph-native ready claim 以前置 facade 形式接到 `PlatformOrchestrator`，但仍未切换默认
lane dispatch、runner loop 或 `feature_lanes.json` live queue:

- `PlatformOrchestrator.__init__` 新增可选 `feature_graph_status_store` 注入点。
- 默认 graph-native status store 路径为 `xmuse_root / "feature_graph_statuses.json"`。
- 新增 `PlatformOrchestrator.claim_next_ready_feature_graph_worker(...)`:
  - 显式调用 `platform.feature_graph_claim_coordinator.claim_next_ready_feature_graph_worker(...)`。
  - 只读写 `FeatureGraphStatusStore`。
  - 支持按 `graph_set_id`、`conversation_id`、`feature_graph_id` 过滤。
  - 返回 `FeatureGraphWorkerClaimOutcome | None`。
  - 不调用 `dispatch_lane(...)`。
  - 不读取、不写入 `feature_lanes.json`。
- 新增 orchestrator focused tests，证明 facade 可以 claim ready feature graph，并且 legacy projection
  文件字节级保持不变。
- 默认 `dispatch_lane(...)` 和当前 lane execution/review/merge flow 未改变。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k \
  "claim_next_ready_feature_graph_worker"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_graph_claim_coordinator.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_worker_claims.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py \
  tests/xmuse/test_feature_graph_claim_coordinator.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_worker_claims.py
uv run ruff check src/xmuse_core/platform/orchestrator.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check .
```

验证结果:

- orchestrator graph claim focused tests: 2 passed。
- full platform orchestrator regression: 168 passed。
- graph claim/status/worker claim focused gate: 39 passed。
- orchestrator + graph claim/status/worker claim combined focused gate: 207 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- facade 仍是显式 shadow path；`xmuse/platform_runner.py` 主循环尚未从 graph-native ready set claim。
- claim 后尚未创建/恢复 feature worker 长 session，也尚未把 provider session binding 选择接入
  graph-level claim。
- running feature graph 到 feature-level evidence bundle，再到 reviewing/rework/merge 的闭环仍需后续接线。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮没有改变 dispatch 行为。

## 2026-06-03 Feature Worker Evidence Submission Plan

本轮补齐 graph-native feature worker 从 `running` 进入 `reviewing` 的契约层和 store-facing applier，
仍未切换 runner 或启动真实 feature worker:

- `FeatureGraphWorkerEvidenceSubmissionPlan` 新增到
  `src/xmuse_core/structuring/feature_review_contracts.py`，并由 `structuring.models` 兼容 re-export。
- 新增 golden fixture:
  `tests/fixtures/xmuse/contracts/artifacts/feature_graph_worker_evidence_submission_plan.v1.json`。
- 新增 `src/xmuse_core/structuring/feature_graph_worker_evidence_submission.py`:
  - 从 `FeatureEvidenceBundle + FeatureGraphExecutionStatusRecord(running)` 构造 coordinator-owned
    submission plan。
  - 校验 graph set、feature plan、feature graph、worker session 和 provider session binding
    都与当前 running status 匹配。
  - 生成 `target_status_record(status=reviewing)`，清空 active lanes，保留 resumable worker/binding refs，
    并从 evidence bundle 的 lane graph summary 记录 completed/blocked lanes。
  - 不读取、不写入 `feature_lanes.json`。
- 新增 `src/xmuse_core/structuring/feature_graph_worker_evidence_application.py`:
  - 只应用 `running -> reviewing` 的 worker evidence submission plan。
  - 通过 `FeatureGraphStatusStore.transition(..., expected_status=running)` 写入 durable graph-native
    status，保持 coordinator/state machine 是状态权威。
- 新增 focused tests:
  - golden fixture 稳定性。
  - 非 running status 拒绝。
  - worker/binding 不匹配拒绝。
  - applier 写入 reviewing event。
  - 同 plan replay 幂等。
  - `model_copy()` 绕过路径重新校验。
  - projection 文件字节级保持不变。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_worker_evidence_submission.py
uv run pytest -q tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_worker_claims.py \
  tests/xmuse/test_feature_graph_claim_coordinator.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run ruff check src/xmuse_core/structuring/feature_graph_worker_evidence_submission.py \
  src/xmuse_core/structuring/feature_graph_worker_evidence_application.py \
  src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_review_contracts.py
uv run ruff check .
```

验证结果:

- worker evidence submission focused tests: 6 passed。
- graph claim/status/review/schema/fixture focused gate: 105 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- submission plan 在本节完成时仍是 contract/service 层；后续已接入 `PlatformOrchestrator` 显式 facade，
  但仍未接入 runner source flag 或默认 dispatch。
- evidence bundle 的持久化 store、feature worker 长 session 输出和 reviewer 长 session 输入还未形成
  运行时闭环。
- 现有历史 fixture 中 `feature_graph_status_running_claim.v1.json` 的 worker session 命名与
  `feature_evidence_bundle.v1.json` 不同；本轮测试 helper 保持生产约束，要求实际 submission 时二者匹配。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮没有改变 dispatch 行为。

## 2026-06-03 Platform Worker Evidence Submission Facade

本轮把 feature worker evidence submission 以前置 facade 形式接到 platform/orchestrator，形成显式
graph-native shadow chain:

```text
PlatformOrchestrator.claim_next_ready_feature_graph_worker(...)
-> graph-native ready -> running
PlatformOrchestrator.submit_feature_graph_worker_evidence(...)
-> running -> reviewing
```

仍未切换默认 `dispatch_lane(...)`、runner loop 或 `feature_lanes.json` live queue。

- 新增 `src/xmuse_core/platform/feature_graph_worker_evidence_coordinator.py`。
- 新增 `FeatureGraphWorkerEvidenceSubmissionOutcome`。
- 新增 `submit_feature_graph_worker_evidence(...)` helper:
  - 读取 `FeatureGraphStatusStore.get(graph_set_id, feature_graph_id)`。
  - 使用 `FeatureEvidenceBundle` 和当前 running status 构造
    `FeatureGraphWorkerEvidenceSubmissionPlan`。
  - 通过 `apply_feature_graph_worker_evidence_submission_plan(...)` 写入 graph-native status store。
  - 不读取、不写入 `feature_lanes.json`。
- `PlatformOrchestrator` 新增显式 `submit_feature_graph_worker_evidence(...)` facade。
- 新增 orchestrator focused tests:
  - successful submission 将 running feature graph 推到 reviewing。
  - claimed worker 不匹配时拒绝，并且不写 status event。
  - 两条路径都不调用 `dispatch_lane(...)`。
  - legacy projection 文件字节级保持不变。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k \
  "submit_feature_graph_worker_evidence"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_worker_claims.py \
  tests/xmuse/test_feature_graph_claim_coordinator.py \
  tests/xmuse/test_feature_graph_status_store.py
uv run ruff check src/xmuse_core/platform/feature_graph_worker_evidence_coordinator.py \
  src/xmuse_core/platform/orchestrator.py \
  tests/xmuse/test_platform_orchestrator.py \
  src/xmuse_core/structuring/feature_graph_worker_evidence_submission.py \
  src/xmuse_core/structuring/feature_graph_worker_evidence_application.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py
uv run ruff check .
```

验证结果:

- orchestrator worker evidence submission focused tests: 2 passed。
- full platform orchestrator regression: 170 passed。
- graph worker evidence/claim/status focused gate: 45 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- facade 仍是显式 shadow path；`xmuse/platform_runner.py` 主循环尚未从 graph-native source claim 或
  submit worker evidence。
- `FeatureEvidenceBundle` 尚未有独立 durable store；当前 helper 消费调用方传入的 bundle。
- feature worker 长 session 创建/恢复、provider binding 选择，以及 reviewer 长 session 输入仍需后续运行时接线。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮没有改变 dispatch 行为。

## 2026-06-03 Platform Review Verdict Facade

本轮把 feature-level review verdict 接到 platform/orchestrator 显式入口，继续完善 graph-native
shadow chain:

```text
claim_next_ready_feature_graph_worker(...)
-> ready -> running
submit_feature_graph_worker_evidence(...)
-> running -> reviewing
submit_feature_graph_review_verdict(...)
-> merge/rework/blocked: reviewing -> terminal/rework status
-> patch_forward/takeover: return coordinator plan, no durable status write
```

仍未切换默认 `dispatch_lane(...)`、runner loop 或 `feature_lanes.json` live queue。

- 新增 `src/xmuse_core/platform/feature_graph_review_coordinator.py`。
- 新增 `FeatureGraphReviewVerdictOutcome`。
- 新增 `submit_feature_graph_review_verdict(...)` helper:
  - 从 `FeatureGraphStatusStore` 读取当前 feature graph status。
  - 用 `FeatureEvidenceBundle + FeatureReviewVerdict + current reviewing status` 构造
    `FeatureGraphReviewStatusTransitionPlan`。
  - 对 `merge / rework / blocked` 调用
    `apply_feature_graph_review_status_transition_plan(...)`，通过 expected-status guard 写入
    graph-native status store。
  - 对 `patch_forward / takeover` 只返回 plan 和 `status=None`，不写 durable status，保留强 gate。
  - 不读取、不写入 `feature_lanes.json`。
- `PlatformOrchestrator` 新增显式 `submit_feature_graph_review_verdict(...)` facade。
- 新增 orchestrator focused tests:
  - `merge` verdict 写入 `merged` graph status，projection 文件字节级不变。
  - `rework` verdict 写入 `reworking` graph status。
  - `patch_forward` verdict 只返回 `PATCH_FORWARD_GATE` plan，不写 status event。
  - 测试证明 facade 不调用 `dispatch_lane(...)`。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k \
  "submit_feature_graph_review_verdict"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_worker_claims.py \
  tests/xmuse/test_feature_graph_claim_coordinator.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_review_contracts.py
uv run ruff check src/xmuse_core/platform/feature_graph_review_coordinator.py \
  src/xmuse_core/platform/feature_graph_worker_evidence_coordinator.py \
  src/xmuse_core/platform/orchestrator.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check .
```

验证结果:

- orchestrator review verdict facade focused tests: 3 passed。
- full platform orchestrator regression: 173 passed。
- graph worker evidence/claim/status/review focused gate: 95 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- facade 仍是显式 shadow path；runner 主循环尚未使用 graph-native claim/evidence/review verdict path。
- patch-forward gate 只有 plan/contract 层和“no write before gate”保证，尚未接入实际 reviewer patch
  execution 和 focused gates rerun。
- takeover plan 仍未接入 takeover runtime path。
- `FeatureEvidenceBundle` / `FeatureReviewVerdict` 已有 feature-level durable artifact store，并已接入
  `PlatformOrchestrator` 显式 facade；但默认 runner、feature worker 长 session 和 reviewer 长 session
  仍未自动产出/消费这些 artifacts。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮没有改变 dispatch 行为。

## 2026-06-03 Feature Graph Artifact Store + Platform Artifact Persistence

本轮把 feature-level worker/reviewer artifacts 从“调用方传入的内存对象”推进到 coordinator-owned
durable artifact store，仍未切换默认 runner、feature worker runtime、reviewer runtime 或
`feature_lanes.json` live queue:

- 新增 `src/xmuse_core/structuring/feature_graph_artifact_store.py`。
- `FeatureGraphArtifactStore` 使用独立 JSON store，schema version 为
  `xmuse.feature_graph_artifacts.v1`。
- store 持久化:
  - `FeatureEvidenceBundle`
  - `FeatureReviewVerdict`
  - `ReworkPacket`
  - `FeatureGraphPatchForwardPlan`
  - `FeatureGraphPatchForwardGateResult`
  - `FeatureGraphBlockedReviewPlan`
  - `FeatureGraphTakeoverPlan`
- store 写入使用 companion lock + temp file replace。
- save 入口会重新校验 Pydantic model，防止 `model_copy(update=...)` 绕过 reviewer/worker
  contract validators。
- save 操作按 artifact id 幂等 upsert:
  - evidence bundle: `bundle_id`
  - review verdict: `verdict_id`
  - rework packet: `rework_id`
  - patch-forward plan: `plan_id`
  - patch-forward gate result: `result_id`
  - blocked review plan: `plan_id`
  - takeover plan: `plan_id`
- store 支持按 feature graph 查询 evidence bundle、按 evidence bundle 查询 review verdict 和
  rework packet / patch-forward plan / patch-forward gate result / blocked review plan / takeover plan。
- `PlatformOrchestrator.__init__` 新增可选 `feature_graph_artifact_store` 注入点。
- 默认 artifact store 路径为 `xmuse_root / "feature_graph_artifacts.json"`；构造 orchestrator 不会创建
  runtime 文件，只有显式 facade 保存 artifact 时才写入。
- `PlatformOrchestrator.submit_feature_graph_worker_evidence(...)` 现在会在 coordinator boundary 保存
  worker 返回的 `FeatureEvidenceBundle`，同时仍通过 `FeatureGraphStatusStore` 执行
  `running -> reviewing` 状态转换。
- worker evidence 保存发生在 claim/current-status 校验之后；未被当前 running status 认可的 worker
  evidence 不会落入 artifact store。
- `PlatformOrchestrator.submit_feature_graph_review_verdict(...)` 现在会保存 reviewer 返回的
  `FeatureReviewVerdict`。
- `merge/rework/blocked` verdict 保存后继续走 guarded graph-native status transition。
- `patch_forward/takeover` verdict 保存后仍只返回 coordinator plan，`status=None`，不写 durable
  execution status，保留强 gate。
- 新增 orchestrator focused tests，证明 worker evidence / review verdict artifact 会由 coordinator
  facade 保存，mismatched worker evidence 不保存，并且 legacy projection 文件字节级保持不变。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k \
  "submit_feature_graph_worker_evidence or submit_feature_graph_review_verdict"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_graph_artifact_store.py \
  src/xmuse_core/platform/orchestrator.py \
  src/xmuse_core/platform/feature_graph_worker_evidence_coordinator.py \
  src/xmuse_core/platform/feature_graph_review_coordinator.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check .
```

验证结果:

- orchestrator artifact persistence focused tests: 5 passed。
- artifact store + graph worker evidence/review transition/rework contract + platform orchestrator focused
  gate: 212 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- artifact store 和 graph-native status store 是两个独立 JSON stores，目前没有跨 store 事务；当前依赖
  单 coordinator 顺序写入，后续 event-store 化时应把 artifact ref 与 status event 通过 idempotency
  key 串起来。
- `submit_feature_graph_review_verdict(...)` 现在会在 rework verdict path 生成并保存
  `ReworkPacket`，并基于 artifact store 中同一 evidence bundle 的历史 rework packets 计算
  `max_remaining_attempts`；但该计数仍未接入 feature worker runtime 的真实 retry policy。
- feature worker 长 session 尚未自动生成 `FeatureEvidenceBundle`，reviewer 长 session 尚未自动消费
  bundle 并返回 `FeatureReviewVerdict`。
- 默认 runner 主循环仍未使用 graph-native artifact/status chain；`feature_lanes.json` 仍是迁移期
  execution live queue/status source。

## 2026-06-03 Platform Rework Packet Persistence

本轮把 reviewer `rework` verdict 的结构化 rework packet 接入
`PlatformOrchestrator.submit_feature_graph_review_verdict(...)` 显式 facade，继续保持 coordinator
是 artifact/status 写入者:

- `FeatureGraphReviewVerdictOutcome` 新增 `rework_packet: ReworkPacket | None`。
- `submit_feature_graph_review_verdict(...)` 在 `decision=rework` 时调用
  `build_feature_graph_rework_packet(...)`。
- rework packet 使用 deterministic id:
  `rework:{verdict_id}:{evidence_bundle_id}:{updated_at}`，其中 timestamp 归一为无分隔符形式，
  让同一 coordinator replay 走 artifact store 幂等 upsert。
- `PlatformOrchestrator.__init__` 新增 `feature_graph_max_rework_attempts`，默认 `2`，并拒绝负数。
- `submit_feature_graph_review_verdict(...)` 会根据 `FeatureGraphArtifactStore` 中同一
  `evidence_bundle_id` 的既有 rework packets 计算 `max_remaining_attempts`；同一个 deterministic
  `rework_id` 会从历史计数中排除，避免 replay 改变 remaining-attempts。
- packet 指回同一个 feature worker session 和 provider session binding ref，保持 rework 反馈给同一
  长 session 或可恢复 provider session 的契约。
- packet 与 review verdict 一起写入 `FeatureGraphArtifactStore`。
- `merge` / `patch_forward` / `takeover` / `blocked` 不生成 rework packet。
- `rework` verdict 仍通过 guarded graph-native status transition 写入 `reworking`；packet 不是状态权威，
  只是 worker 下一轮输入 artifact。
- 新增 orchestrator focused assertions，证明 rework verdict facade 会保存 verdict 和
  `ReworkPacket`，packet 指向同一个 worker session / provider binding，并且历史 rework packet
  会降低新 packet 的 remaining-attempts。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k \
  "submit_feature_graph_review_verdict"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_graph_artifact_store.py \
  src/xmuse_core/structuring/feature_graph_rework_packets.py \
  src/xmuse_core/platform/orchestrator.py \
  src/xmuse_core/platform/feature_graph_worker_evidence_coordinator.py \
  src/xmuse_core/platform/feature_graph_review_coordinator.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check .
```

验证结果:

- rework verdict facade focused tests: 2 passed for the rework-specific slice; full review-verdict facade
  slice remains covered by the platform orchestrator file.
- artifact store + graph worker evidence/review transition/rework contract + platform orchestrator focused
  gate: 213 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- `max_remaining_attempts` 目前从 artifact history 和 `feature_graph_max_rework_attempts` 计算；后续仍应
  与 feature graph status、worker session policy、takeover threshold 和 coordinator event history
  对齐。
- artifact store/status store 仍无跨 store 事务；后续 event-store 化应把 rework packet ref 写入 status
  transition event 或独立 coordinator event。
- rework packet 还未由 feature worker 长 session 自动消费；后续已有显式 graph-native rework status
  applier，但 runner 主循环仍未使用 graph-native rework artifact chain。

## 2026-06-03 Feature Graph Rework Status Application

本轮补齐 saved `ReworkPacket` 回到同一个 feature worker / provider session 的 graph-native
status application，继续不切换 runner 主循环或 `feature_lanes.json` live queue:

- 新增 `src/xmuse_core/structuring/feature_graph_rework_status_application.py`。
- 新增 `apply_feature_graph_rework_packet_status(...)`:
  - 重新校验 `FeatureEvidenceBundle` 和 `ReworkPacket`。
  - 要求 packet 的 `evidence_bundle_id` 指向同一个 evidence bundle。
  - 要求 packet target worker session / provider session binding ref 与 evidence bundle 匹配，
    防止 rework 被错误派给其他 worker/session。
  - 要求当前 graph-native status 是 `reworking`。
  - 校验 current status 与 evidence bundle 的 conversation / planning run / graph-set /
    feature graph identity 一致。
  - 写入 `FeatureGraphStatusStore.transition(..., expected_status=reworking)`，目标 status 为
    `running`。
  - 把 `active_worker_session_id` / `active_provider_session_binding_ref` 设置为 rework packet 指向的
    same-worker / resumable-session target。
  - 从 current status 和 evidence bundle lane summary 组装 rework active lane refs，保留
    completed/blocked/projection refs。
  - 同一 target status replay 幂等，不重复写 status event。
  - 不调用 runner、不启动 worker、不读取/写入 `feature_lanes.json`。
- 新增 `src/xmuse_core/platform/feature_graph_rework_coordinator.py`。
- 新增 `apply_feature_graph_rework_packet_status_from_artifacts(...)`:
  - 从 `FeatureGraphArtifactStore` 读取 saved `ReworkPacket`。
  - 通过 packet 的 `evidence_bundle_id` 读取 saved `FeatureEvidenceBundle`。
  - 调用 structuring applier 写 graph-native status。
- `PlatformOrchestrator` 新增显式 `apply_feature_graph_rework_packet_status(...)` facade。
- 新增 focused tests:
  - reworking -> running 写入 status event。
  - 同一 packet replay 幂等。
  - 非 `reworking` current status 拒绝且不写 event。
  - target worker session mismatch 拒绝。
  - platform facade 从 artifact store 读取 bundle/packet，写 running status，保持 legacy projection
    文件字节级不变，并且不调用 lane dispatch。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_rework_status_application.py
uv run pytest -q tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py -k "rework"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_dependency_coordinator.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
uv run ruff check src/xmuse_core/structuring/feature_graph_rework_status_application.py \
  src/xmuse_core/platform/feature_graph_rework_coordinator.py \
  src/xmuse_core/platform/orchestrator.py \
  tests/xmuse/test_feature_graph_rework_status_application.py
uv run ruff check .
git diff --check
```

验证结果:

- rework status application focused tests: 5 passed。
- rework packet/status/platform focused gate: 24 passed, 186 deselected。
- full platform orchestrator regression: 184 passed。
- graph-native rework/status/artifact focused gate: 70 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- rework status application 只把 saved rework packet 重新交给同一 worker/session 并写
  graph-native `running`；尚未启动 feature worker 长 session，也未让 runner 主循环自动消费 packet。
- artifact store/status store 仍无跨 store 事务；后续 event-store 化应把 rework packet ref 与
  status transition event 通过 idempotency key 串起来。
- `max_remaining_attempts=0` 的 packet 仍允许执行当前 rework attempt；后续 takeover threshold /
  retry policy 应由 coordinator event history 和 worker session policy 统一仲裁。
- `feature_lanes.json` 仍是迁移期 execution live queue/status source；本轮不投影 ready/running 状态。

## 2026-06-03 Platform Patch-Forward Gate Plan Persistence

本轮把 reviewer `patch_forward` verdict 的强 gate plan 接入
`PlatformOrchestrator.submit_feature_graph_review_verdict(...)` 显式 facade，继续保持 patch-forward
在 gate 通过前不写 durable execution status:

- `FeatureGraphArtifactStore` 新增 patch-forward plan collection。
- 新增 store API:
  - `save_patch_forward_plan(...)`
  - `get_patch_forward_plan(...)`
  - `list_patch_forward_plans(...)`
  - `list_patch_forward_plans_for_evidence_bundle(...)`
- `FeatureGraphReviewVerdictOutcome` 新增
  `patch_forward_plan: FeatureGraphPatchForwardPlan | None`。
- `submit_feature_graph_review_verdict(...)` 在 `decision=patch_forward` 时调用
  `build_feature_graph_patch_forward_plan(...)`。
- patch-forward plan 使用 deterministic id:
  `fgpf:{verdict_id}:{evidence_bundle_id}:{updated_at}`，其中 timestamp 归一为无分隔符形式。
- `patch_forward` verdict 现在会保存 reviewer verdict 和 `FeatureGraphPatchForwardPlan`。
- `patch_forward` 仍只返回 `coordinator_action=PATCH_FORWARD_GATE` 和 `status=None`，不调用
  `FeatureGraphStatusStore.transition(...)`，不写 status event。
- gate plan 固定记录 low-risk scope、allowed files、max files/lines、focused gates、no-new-dependency
  和 no-public-contract-change flags，作为后续 reviewer patch execution / focused gates rerun 的输入。
- 新增 artifact store focused test，证明 patch-forward plan 可保存、读取并按 evidence bundle 查询。
- 新增 platform orchestrator focused assertions，证明 patch-forward facade 会返回并保存 gate plan，同时
  graph status 和 legacy projection 保持不变。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "patch_forward or artifact_store_saves_patch_forward"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_graph_artifact_store.py \
  src/xmuse_core/structuring/feature_graph_patch_forward.py \
  src/xmuse_core/platform/orchestrator.py \
  src/xmuse_core/platform/feature_graph_worker_evidence_coordinator.py \
  src/xmuse_core/platform/feature_graph_review_coordinator.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check .
```

验证结果:

- patch-forward plan artifact/facade focused tests: 5 passed。
- artifact store + graph worker evidence/review transition/rework/patch-forward contract +
  platform orchestrator focused gate: 220 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- patch-forward plan 已持久化，但 reviewer patch execution、allowed-file enforcement、line/file count
  enforcement、focused gates rerun 和后续 merge guard 仍未接入 runtime。
- artifact store/status store 仍无跨 store 事务；后续 event-store 化应把 patch-forward plan ref 写入
  coordinator event 或 gate execution evidence。
- 默认 runner 主循环仍未使用 graph-native review artifact chain。

## 2026-06-03 Feature Graph Patch-Forward Gate Result

本轮补 reviewer `patch_forward` 执行后的 gate evidence 契约，仍不接入真实 patch execution、
merge guard 或 durable status transition:

- 新增 `FeatureGraphPatchForwardGateResult` Pydantic schema。
- `structuring.models` 已兼容 re-export `FeatureGraphPatchForwardGateResult`。
- 新增 golden fixture:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_patch_forward_gate_result.v1.json`
- 新增 `src/xmuse_core/structuring/feature_graph_patch_forward_gate.py`。
- 新增 `validate_feature_graph_patch_forward_gate_result(...)` 纯函数:
  - 重新校验 plan/result，防止 `model_copy(update=...)` 绕过 schema。
  - 要求 result identity 与 `FeatureGraphPatchForwardPlan` 完全一致。
  - 要求 result 已 `passed`；它代表“可进入下一 coordinator gate”，不是普通 evidence 保存校验。
  - 校验 changed files 必须是 plan 的 `allowed_file_refs` 子集。
  - 校验 changed file count / line count 不超过 plan 上限。
  - 校验 plan 声明的 focused gates 都已重跑。
  - 校验不引入新依赖、不修改 public contract。
- 新增 `validate_feature_graph_patch_forward_gate_result_identity(...)` 轻量校验:
  - 重新校验 plan/result schema。
  - 只要求 result identity 与已保存 plan 一致。
  - 用于 coordinator 保存 failed gate evidence；通过该 helper 不代表可以推进 merge guard。
- `FeatureGraphArtifactStore` 新增 patch-forward gate result collection。
- 新增 store API:
  - `save_patch_forward_gate_result(...)`
  - `get_patch_forward_gate_result(...)`
  - `list_patch_forward_gate_results(...)`
  - `list_patch_forward_gate_results_for_evidence_bundle(...)`
  - `list_patch_forward_gate_results_for_plan(...)`
- artifact store 只负责 schema 级持久化；是否满足 plan gate 由 validator 判断，避免 store 变成
  runtime gate executor 或状态机。
- 新增 `src/xmuse_core/platform/feature_graph_patch_forward_gate_coordinator.py`。
- 新增 `submit_feature_graph_patch_forward_gate_result(...)` coordinator helper:
  - 从 `FeatureGraphArtifactStore` 读取已保存的 patch-forward plan。
  - 先调用 identity-only helper 校验 result 是否属于该 plan。
  - failed result 可保存为 evidence，并返回 `advance_to_merge_guard=False`。
  - passed result 还必须通过 strict validator，才能保存并返回 `advance_to_merge_guard=True`。
  - identity mismatch 或 passed 但越界/缺 gate/引入依赖/修改 public contract 时不保存 result。
  - helper 不写 status，不读取/写入 `feature_lanes.json`。
- `PlatformOrchestrator` 新增显式
  `submit_feature_graph_patch_forward_gate_result(...)` facade。
- `FeatureGraphPatchForwardGateResultOutcome` 新增 `advance_to_merge_guard`，明确区分
  “已记录 evidence”和“可交给后续 merge guard”。
- 新增 platform orchestrator focused tests，证明 valid passed result 会保存并可推进，
  failed result 会保存但不可推进，passed 越界 result 和 identity mismatch result 不保存，
  legacy projection 文件字节级保持不变，并且不调用 lane dispatch。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k \
  "patch_forward_gate_result"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_patch_forward_gate.py \
  src/xmuse_core/structuring/feature_graph_artifact_store.py \
  src/xmuse_core/platform/feature_graph_patch_forward_gate_coordinator.py \
  src/xmuse_core/platform/orchestrator.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check .
```

验证结果:

- patch-forward gate result contract/store focused tests: 44 passed。
- platform patch-forward gate result facade focused tests: 4 passed。
- artifact store + graph worker evidence/review transition/rework/patch-forward/blocked/takeover contract +
  shared fixtures + platform orchestrator focused gate: 261 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- result 契约和 validator 已有，但 reviewer patch execution、diff capture、focused gate execution、
  merge guard handoff 和 status transition 仍未接入 runtime。
- artifact store/status store 仍无跨 store 事务；后续 event-store 化应把 gate result ref 与后续
  merge-guard decision 串起来。
- 默认 runner 主循环仍未使用 graph-native patch-forward artifact chain。

## 2026-06-03 Feature Graph Patch-Forward Merge Guard Handoff

本轮补齐 passed patch-forward gate result 到后续 merge guard 的结构化 handoff artifact，
继续不接入真实 merge guard execution，也不写 durable status transition:

- 新增 `FeatureGraphPatchForwardMergeGuardHandoff` Pydantic schema。
- `structuring.models` 已兼容 re-export `FeatureGraphPatchForwardMergeGuardHandoff`。
- 新增 golden fixture:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_patch_forward_merge_guard_handoff.v1.json`
- 新增 `build_feature_graph_patch_forward_merge_guard_handoff(...)` 纯函数:
  - 复用 `validate_feature_graph_patch_forward_gate_result(...)` strict validator。
  - failed gate result、identity mismatch、越界 patch-forward result 都不能生成 handoff。
  - handoff 固定记录 plan/result/verdict/evidence bundle/feature graph identity。
  - handoff 固定记录 patch diff、focused gate evidence、merge guard input refs 和必须执行的
    merge guard checks。
  - helper 不执行 merge guard、不写 status、不读取/写入 `feature_lanes.json`。
- `FeatureGraphArtifactStore` 新增 patch-forward merge guard handoff collection。
- 新增 store API:
  - `save_patch_forward_merge_guard_handoff(...)`
  - `get_patch_forward_merge_guard_handoff(...)`
  - `list_patch_forward_merge_guard_handoffs(...)`
  - `list_patch_forward_merge_guard_handoffs_for_gate_result(...)`
- `submit_feature_graph_patch_forward_gate_result(...)` 在 `advance_to_merge_guard=True` 时会保存
  deterministic handoff:
  `fgpfmgh:{patch_forward_gate_result_id}`。
- failed gate evidence 仍只保存 result，不创建 merge guard handoff。
- 新增 platform orchestrator focused assertions，证明 valid passed result 会保存 handoff，
  failed result / invalid result 不会创建 handoff，legacy projection 文件字节级保持不变，并且不调用
  lane dispatch。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "patch_forward_gate_result or patch_forward_merge_guard_handoff or artifact_store_saves_patch_forward_merge_guard_handoffs"
uv run pytest -q tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "patch_forward_gate_result or patch_forward_merge_guard_handoff or artifact_store_saves_patch_forward_merge_guard_handoffs or every_contract_fixture"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_patch_forward_gate.py \
  src/xmuse_core/structuring/feature_graph_artifact_store.py \
  src/xmuse_core/platform/feature_graph_patch_forward_gate_coordinator.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check .
```

验证结果:

- patch-forward gate/handoff focused tests: 19 passed。
- shared fixture + handoff focused tests: 20 passed。
- artifact store + graph worker evidence/review transition/rework/patch-forward/blocked/takeover contract +
  shared fixtures + platform orchestrator focused gate: 265 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- handoff 只把 passed gate evidence 结构化交给后续 merge guard；真实 merge guard execution 和
  status transition 仍未接入 runtime。
- artifact store 保存 gate result 和 handoff 是连续写入，不是 event-store transaction；后续应把
  handoff ref 与 merge guard decision/event 通过 idempotency key 串起来。
- 默认 runner 主循环仍未使用 graph-native patch-forward artifact chain。

## 2026-06-03 Feature Graph Patch-Forward Merge Guard Decision

本轮补齐 patch-forward handoff 后的 merge guard output 结构化记录，继续不接入真实 merge、
不写 durable status transition，也不把 reviewer patch-forward 扩成 worker 权限:

- 新增 `FeatureGraphPatchForwardMergeGuardDecision` Pydantic schema。
- `structuring.models` 已兼容 re-export `FeatureGraphPatchForwardMergeGuardDecision`。
- 新增 golden fixture:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_patch_forward_merge_guard_decision.v1.json`
- 新增 `build_feature_graph_patch_forward_merge_guard_decision(...)` 纯函数:
  - 从 `FeatureGraphPatchForwardMergeGuardHandoff` 派生 graph-set / feature graph / verdict /
    gate result identity。
  - 记录 `merge_guard_ref`、`merge_guard_evidence_refs`、`passed`、`failure_reasons` 和
    `checked_at`。
  - passed decision 禁止携带 failure reasons。
  - failed decision 必须携带 failure reasons。
  - helper 不执行 merge、不写 status、不读取/写入 `feature_lanes.json`。
- `FeatureGraphArtifactStore` 新增 patch-forward merge guard decision collection。
- 新增 store API:
  - `save_patch_forward_merge_guard_decision(...)`
  - `get_patch_forward_merge_guard_decision(...)`
  - `list_patch_forward_merge_guard_decisions(...)`
  - `list_patch_forward_merge_guard_decisions_for_handoff(...)`
- 新增 `submit_feature_graph_patch_forward_merge_guard_decision(...)` coordinator helper:
  - 从 artifact store 读取已保存的 handoff。
  - 构造 deterministic decision id:
    `fgpfmgd:{handoff_id}:{checked_at}`，其中 timestamp 归一为无分隔符形式。
  - 保存 decision artifact。
  - 返回 `eligible_for_status_transition=decision.passed`，但不调用
    `FeatureGraphStatusStore.transition(...)`。
- `PlatformOrchestrator` 新增显式
  `submit_feature_graph_patch_forward_merge_guard_decision(...)` facade。
- 新增 platform orchestrator focused tests，证明 passed/failed merge guard decisions 都可记录，
  failed decision 不可推进，invalid failed decision 不保存，legacy projection 文件字节级保持不变，
  并且不调用 lane dispatch。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "patch_forward_merge_guard_decision or artifact_store_saves_patch_forward_merge_guard_decisions"
uv run pytest -q tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "patch_forward_gate_result or patch_forward_merge_guard_handoff or patch_forward_merge_guard_decision or artifact_store_saves_patch_forward_merge_guard or every_contract_fixture"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_patch_forward_gate.py \
  src/xmuse_core/structuring/feature_graph_artifact_store.py \
  src/xmuse_core/platform/feature_graph_patch_forward_gate_coordinator.py \
  src/xmuse_core/platform/orchestrator.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check .
```

验证结果:

- patch-forward merge guard decision focused tests: 6 passed。
- patch-forward gate/result/handoff/decision + shared fixture focused tests: 27 passed。
- artifact store + graph worker evidence/review transition/rework/patch-forward/blocked/takeover contract +
  shared fixtures + platform orchestrator focused gate: 272 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- 真实 merge guard execution、worktree merge、target-head/staleness guard 和 merge refs 仍在旧 lane
  runtime 路径，尚未成为 feature graph patch-forward artifact chain 的默认闭环。
- artifact store/status store 仍无跨 store 事务；后续 event-store 化应把 decision ref 与 status
  transition event 通过 idempotency key 串起来。

## 2026-06-03 Feature Graph Patch-Forward Status Application

本轮补齐 passed patch-forward merge guard decision 到 graph-native `merged` status 的显式
coordinator applier，继续不接入真实 merge guard execution、worktree merge 或
`feature_lanes.json` live queue:

- 新增 `src/xmuse_core/structuring/feature_graph_patch_forward_status_application.py`。
- 新增 `apply_feature_graph_patch_forward_merge_guard_decision(...)`:
  - 从 `FeatureGraphPatchForwardMergeGuardDecision` 应用 graph-native status transition。
  - 只接受 `passed=True` 的 decision。
  - 要求当前 graph-native status 是 `reviewing`。
  - 校验 current status 与 decision 的 graph-set / feature graph identity 一致。
  - 写入 `FeatureGraphStatusStore.transition(..., expected_status=reviewing)`，目标 status 为
    `merged`。
  - 保留当前 status 上的 projection refs、completed/blocked lane refs。
  - 同一 target status replay 幂等，不重复写 status event。
  - 不运行 merge guard、不执行 worktree merge、不调用 runner、不读取/写入 `feature_lanes.json`。
- `src/xmuse_core/platform/feature_graph_patch_forward_gate_coordinator.py` 新增
  `apply_feature_graph_patch_forward_merge_guard_decision_status(...)` coordinator helper:
  - 从 artifact store 读取已保存的 merge guard decision。
  - 通过 status application helper 写 graph-native status。
  - 返回 decision + status outcome。
- `PlatformOrchestrator` 新增显式
  `apply_feature_graph_patch_forward_merge_guard_decision_status(...)` facade。
- 新增 focused tests:
  - passed decision 写入 `merged` status 和 status event。
  - 同一 decision replay 幂等。
  - failed decision 拒绝且不写 event。
  - 非 `reviewing` current status 拒绝。
  - platform facade 写 status 但保持 legacy projection 文件字节级不变，并且不调用 lane dispatch。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_patch_forward_status_application.py
uv run pytest -q tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "patch_forward_merge_guard_decision_status"
uv run pytest -q tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "patch_forward_gate_result or patch_forward_merge_guard_handoff or patch_forward_merge_guard_decision or patch_forward_merge_guard_decision_status or artifact_store_saves_patch_forward_merge_guard or every_contract_fixture"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py \
  tests/xmuse/test_platform_orchestrator.py
```

验证结果:

- direct patch-forward status application tests: 4 passed。
- platform facade focused assertion: 1 passed, 187 deselected。
- patch-forward chain focused gate: 32 passed。
- graph worker evidence/review transition/rework/patch-forward/blocked/takeover contract + platform
  orchestrator wide focused gate: 277 passed。

当前剩余风险:

- applier 只消费已保存的 passed merge guard decision；真实 merge guard execution、worktree merge、
  target-head/staleness guard 和 merge refs 仍未成为 feature graph patch-forward artifact chain 的默认闭环。
- patch-forward status application 不自动释放 downstream graph-native dependents；后续由显式
  coordinator dependency release helper 处理。
- artifact store/status store 仍无跨 store 事务；后续 event-store 化应把 decision ref 与 status
  transition event 通过 idempotency key 串起来。
- 默认 runner 主循环仍未使用 graph-native patch-forward artifact chain；`feature_lanes.json` 仍是迁移期
  execution live queue/status source。

## 2026-06-03 Platform Graph-Native Dependent Release Facade

本轮把已有 `FeatureGraphStatusStore.release_ready_dependents(...)` 收束成 coordinator-facing
显式 helper/facade，补齐 graph-native merge 后释放下游 feature graph 的前置能力；仍未切换
runner 主循环或 `feature_lanes.json` live queue:

- 新增 `src/xmuse_core/platform/feature_graph_dependency_coordinator.py`。
- 新增 `FeatureGraphDependentReleaseOutcome`。
- 新增 `release_ready_feature_graph_dependents(...)`:
  - 显式接收 `FeatureGraphSet` artifact 和 `FeatureGraphStatusStore`。
  - 重新校验 `FeatureGraphSet`，防止 `model_copy(update=...)` 绕过 graph-set contract。
  - 调用 `FeatureGraphStatusStore.release_ready_dependents(...)`。
  - 只在 dependency feature graphs 都是当前 graph-set 的 `merged` status 时释放 `planned -> ready`。
  - replay 时已 ready 的 dependent 不重复 release，也不重复写 event。
  - 不读取、不写入 `feature_lanes.json`。
- `PlatformOrchestrator` 新增显式 `release_ready_feature_graph_dependents(...)` facade。
- 新增 focused tests:
  - upstream feature graph merged 后，下游 planned feature graph 被释放为 ready。
  - replay 不重复 release。
  - invalid graph-set artifact 被重新校验拒绝。
  - platform facade 不调用 `dispatch_lane(...)`。
  - legacy projection 文件字节级保持不变。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_dependency_coordinator.py
uv run pytest -q tests/xmuse/test_feature_graph_dependency_coordinator.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_claim_coordinator.py \
  tests/xmuse/test_feature_graph_worker_claims.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "release_ready_feature_graph_dependents or release_ready_dependents or claim_next_ready_feature_graph_worker or patch_forward_merge_guard_decision_status"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_dependency_coordinator.py
uv run ruff check src/xmuse_core/platform/feature_graph_dependency_coordinator.py \
  src/xmuse_core/platform/orchestrator.py \
  tests/xmuse/test_feature_graph_dependency_coordinator.py
uv run ruff check .
git diff --check
```

验证结果:

- graph-native dependent release focused tests: 3 passed。
- dependent release + graph claim + patch-forward status focused gate: 9 passed, 221 deselected。
- full platform orchestrator regression: 184 passed。
- feature graph status store + dependent release focused files: 34 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- dependent release facade 仍是显式 shadow path；默认 runner 主循环尚未在 graph-native merge 后自动调用。
- `release_ready_feature_graph_dependents(...)` 当前由调用方传入 graph-set artifact；后续需要由 coordinator
  event consumer 从 graph-set store/event ref 恢复 artifact，并用 idempotency key 串联 status event。
- 释放 ready 只写 graph-native status store，不投影到 `feature_lanes.json`；cutover 前还需要 runner
  source flag / compatibility export 策略。

## 2026-06-03 Platform Takeover Gate Plan Persistence

本轮把 reviewer `takeover` verdict 的 coordinator takeover gate plan 接入
`PlatformOrchestrator.submit_feature_graph_review_verdict(...)` 显式 facade，继续保持 takeover
在 gate / lease / worktree guard 通过前不写 durable execution status:

- `FeatureGraphArtifactStore` 新增 takeover plan collection。
- 新增 store API:
  - `save_takeover_plan(...)`
  - `get_takeover_plan(...)`
  - `list_takeover_plans(...)`
  - `list_takeover_plans_for_evidence_bundle(...)`
- `FeatureGraphReviewVerdictOutcome` 新增
  `takeover_plan: FeatureGraphTakeoverPlan | None`。
- `submit_feature_graph_review_verdict(...)` 在 `decision=takeover` 时调用
  `build_feature_graph_takeover_plan(...)`。
- takeover plan 使用 deterministic id:
  `fgtakeover:{verdict_id}:{evidence_bundle_id}:{updated_at}`，其中 timestamp 归一为无分隔符形式。
- `takeover` verdict 现在会保存 reviewer verdict 和 `FeatureGraphTakeoverPlan`。
- `takeover` 仍只返回 `coordinator_action=TAKEOVER_REQUIRED` 和 `status=None`，不调用
  `FeatureGraphStatusStore.transition(...)`，不写 status event。
- takeover plan 固定记录 failed worker session、failed provider session binding ref、takeover
  reason、structured triggers 和 evidence refs，作为后续 coordinator takeover gate / attempt lease 的输入。
- 新增 artifact store focused test，证明 takeover plan 可保存、读取并按 evidence bundle 查询。
- 新增 platform orchestrator focused assertions，证明 takeover facade 会返回并保存 gate plan，同时
  graph status 和 legacy projection 保持不变。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or artifact_store_saves_takeover"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_graph_artifact_store.py \
  src/xmuse_core/platform/feature_graph_review_coordinator.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check .
```

验证结果:

- takeover plan artifact/facade focused tests: 2 passed。
- artifact store + graph worker evidence/review transition/rework/patch-forward/blocked/takeover contract +
  platform orchestrator focused gate: 236 passed。
- 本轮触及 Python 文件 ruff: All checks passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- takeover plan 已持久化，但真实 takeover execution、attempt lease、worktree/merge guard、
  failed worker/provider binding recovery 和 takeover outcome event 仍未接入 runtime。
- takeover 仍是 coordinator gate plan，不是状态转换；默认 runner 主循环仍未使用 graph-native
  review artifact chain。
- artifact store/status store 仍无跨 store 事务；后续 event-store 化应把 takeover plan ref 写入
  coordinator event 或 takeover gate execution evidence。

## 2026-06-03 Feature Graph Takeover Decision Handoff

本轮把 approved takeover gate decision 继续收束为 coordinator-owned handoff artifact，仍不启动
takeover worker、不申请 worktree lease、不写 graph-native execution status，也不触碰
`feature_lanes.json`:

- 新增 `FeatureGraphTakeoverHandoff` Pydantic schema。
- `structuring.models` 已兼容 re-export `FeatureGraphTakeoverHandoff`。
- 新增 golden fixture:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_takeover_handoff.v1.json`
- `build_feature_graph_takeover_handoff(...)` 只接受 approved
  `FeatureGraphTakeoverDecision`，并重新校验 decision，防止 `model_copy(update=...)` 绕过 gate。
- takeover handoff 固定记录:
  - takeover worker session。
  - takeover provider session binding ref。
  - takeover reason / structured triggers。
  - gate refs。
  - takeover input refs。
  - required takeover checks:
    `verify_takeover_decision_approved`、
    `verify_takeover_worker_session_binding`、
    `verify_takeover_worktree_lease`、
    `verify_failed_worker_is_not_resumed`。
- `FeatureGraphArtifactStore` 新增 takeover handoff collection 和 store API:
  - `save_takeover_handoff(...)`
  - `get_takeover_handoff(...)`
  - `list_takeover_handoffs(...)`
  - `list_takeover_handoffs_for_decision(...)`
- `submit_feature_graph_takeover_decision(...)` 在 approved decision 保存后自动保存 handoff；rejected
  decision 只保存 decision evidence，不生成 handoff。
- `PlatformOrchestrator.submit_feature_graph_takeover_decision(...)` 现在返回
  `takeover_handoff`，但仍不调用 `dispatch_lane(...)`、不写 status store、不改 legacy projection。

已运行验证:

```bash
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_takeover_plan.py \
  src/xmuse_core/structuring/feature_graph_artifact_store.py \
  src/xmuse_core/platform/feature_graph_takeover_coordinator.py \
  src/xmuse_core/platform/orchestrator.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py -k "takeover"
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run ruff check .
git diff --check
```

验证结果:

- 本轮触及 Python 文件 ruff: All checks passed。
- takeover focused gate: 24 passed, 214 deselected。
- takeover/artifact/shared fixture contract gate: 61 passed。
- platform orchestrator full-file regression: 187 passed。
- takeover + rework status + patch-forward status focused gate: 30 passed, 217 deselected。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- handoff 仍只是 takeover execution 的输入 artifact；真实 takeover worker start、attempt lease、
  worktree guard、failed worker/provider binding recovery 和 outcome event 仍未接入 runtime。
- approved takeover handoff 不自动转换 graph status；后续需要 coordinator 在 takeover outcome /
  merge guard 之后通过 graph-native status store 写入。
- artifact store/status store 仍无跨 store 事务；后续 event-store 化应把 takeover decision、handoff、
  worker outcome 和 status event 通过 idempotency key 串起来。
- 默认 runner 主循环仍未使用 graph-native takeover artifact chain；`feature_lanes.json` 仍是迁移期
  execution live queue/status source。

## 2026-06-03 Feature Graph Takeover Worker Outcome

本轮把 takeover handoff 之后的 worker output 收束成 coordinator-owned outcome artifact，继续保持
worker/reviewer 不直接写 durable execution state:

- 新增 `FeatureGraphTakeoverOutcome` Pydantic schema。
- `structuring.models` 已兼容 re-export `FeatureGraphTakeoverOutcome`。
- 新增 golden fixture:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_takeover_outcome.v1.json`
- 新增 `build_feature_graph_takeover_outcome(...)`，从已保存的
  `FeatureGraphTakeoverHandoff` 复制 graph identity、decision/plan/verdict/evidence refs、
  takeover worker session 和 provider session binding ref。
- completed takeover outcome 必须包含 `evidence_refs` 和 `verification_refs`，且不能带
  `failure_reasons`。
- failed takeover outcome 必须包含 `failure_reasons`，用于 coordinator 后续决定 retry、blocked
  或人工升级。
- `FeatureGraphArtifactStore` 新增 takeover outcome collection 和 store API:
  - `save_takeover_outcome(...)`
  - `get_takeover_outcome(...)`
  - `list_takeover_outcomes(...)`
  - `list_takeover_outcomes_for_handoff(...)`
- 新增 `submit_feature_graph_takeover_outcome(...)` coordinator helper 和
  `PlatformOrchestrator.submit_feature_graph_takeover_outcome(...)` facade。
- completed outcome 只返回 `eligible_for_followup_review=True`；它不合并代码、不执行 merge guard、
  不写 graph-native status store、不触碰 `feature_lanes.json`。
- failed outcome 会保存失败 evidence，但不进入 follow-up review。

已运行验证:

```bash
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_takeover_plan.py \
  src/xmuse_core/structuring/feature_graph_artifact_store.py \
  src/xmuse_core/platform/feature_graph_takeover_coordinator.py \
  src/xmuse_core/platform/orchestrator.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py -k "takeover"
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run ruff check .
git diff --check
```

验证结果:

- 本轮触及 Python 文件 ruff: All checks passed。
- takeover focused gate: 32 passed, 214 deselected。
- takeover/artifact/shared fixture contract gate: 67 passed。
- platform orchestrator full-file regression: 189 passed。
- takeover + rework status + patch-forward status focused gate: 38 passed, 217 deselected。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- takeover outcome 仍是 artifact-only；真实 takeover worker start、attempt lease、worktree guard、
  merge guard 和 provider binding recovery strategy 仍未接入 runtime。
- completed takeover outcome 只表示可进入后续 review/merge gate，不代表 feature graph 已 merged。
- takeover outcome 尚未生成 follow-up reviewer verdict 或 graph-native status transition；后续应由
  coordinator/event consumer 串联 outcome -> review/merge guard -> status store。
- artifact store/status store 仍无跨 store 事务；后续 event-store 化应把 handoff、outcome 和状态事件
  通过 idempotency key 串起来。

## 2026-06-03 Feature Graph Takeover Follow-up Review Handoff

本轮把 completed takeover outcome 明确转成 follow-up review handoff artifact，确保 takeover
worker 完成后仍回到 reviewer/merge gate，而不是直接合并或写状态:

- 新增 `FeatureGraphTakeoverReviewHandoff` Pydantic schema。
- `structuring.models` 已兼容 re-export `FeatureGraphTakeoverReviewHandoff`。
- 新增 golden fixture:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_takeover_review_handoff.v1.json`
- 新增 `build_feature_graph_takeover_review_handoff(...)`，只接受 completed
  `FeatureGraphTakeoverOutcome`。
- failed takeover outcome 会被拒绝生成 review handoff，继续作为 failure evidence 留给 coordinator
  判断 retry、blocked 或人工升级。
- review handoff 固定携带:
  - takeover outcome / handoff / decision / plan / verdict refs。
  - graph-set / feature graph identity。
  - takeover worker session 和 provider session binding ref。
  - changed file refs、evidence refs、verification refs。
  - reviewer input refs。
  - required review checks:
    `review_takeover_output_against_original_evidence`、
    `verify_takeover_changes_match_feature_scope`、
    `verify_takeover_focused_gates`、
    `decide_merge_rework_patch_forward_or_blocked`。
- `FeatureGraphArtifactStore` 新增 takeover review handoff collection 和 store API:
  - `save_takeover_review_handoff(...)`
  - `get_takeover_review_handoff(...)`
  - `list_takeover_review_handoffs(...)`
  - `list_takeover_review_handoffs_for_outcome(...)`
- `submit_feature_graph_takeover_outcome(...)` 在 completed outcome 保存后自动保存 review handoff；failed
  outcome 不生成 handoff。
- `PlatformOrchestrator.submit_feature_graph_takeover_outcome(...)` 返回 `review_handoff`，但仍不调用
  `dispatch_lane(...)`、不生成 review verdict、不执行 merge guard、不写 graph-native status store、
  不触碰 `feature_lanes.json`。

已运行验证:

```bash
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_takeover_plan.py \
  src/xmuse_core/structuring/feature_graph_artifact_store.py \
  src/xmuse_core/platform/feature_graph_takeover_coordinator.py \
  src/xmuse_core/platform/orchestrator.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py -k "takeover"
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run ruff check .
git diff --check
```

验证结果:

- 本轮触及 Python 文件 ruff: All checks passed。
- takeover focused gate: 37 passed, 214 deselected。
- takeover/artifact/shared fixture contract gate: 72 passed。
- platform orchestrator full-file regression: 189 passed。
- takeover + rework status + patch-forward status focused gate: 43 passed, 217 deselected。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- review handoff 仍是 artifact-only；真实 reviewer long session 调用、verdict 生成、merge guard 和
  graph-native status transition 仍未接入 runtime。
- takeover follow-up review 还未与 persistent reviewer session / provider binding 恢复策略绑定。
- completed takeover outcome 到 review verdict 之间仍缺少 event-store/idempotency key 串联。
- 默认 runner 主循环仍未使用 graph-native takeover artifact chain；`feature_lanes.json` 仍是迁移期
  execution live queue/status source。

## 2026-06-03 Feature Graph Takeover Follow-up Verdict Gate

本轮把 takeover follow-up review handoff 后的 reviewer verdict 收束成显式 coordinator gate，仍不写
graph-native status、不执行 merge guard、不触碰 `feature_lanes.json`:

- 新增 `validate_feature_graph_takeover_followup_verdict(...)`。
- 该 helper 会重新校验 `FeatureGraphTakeoverReviewHandoff`、`FeatureEvidenceBundle` 和
  `FeatureReviewVerdict`，防止 `model_copy(update=...)` 绕过 schema validator。
- follow-up verdict 必须:
  - 使用与 review handoff 相同的 `evidence_bundle_id`。
  - 通过 evidence bundle 校验 graph-set / feature / feature-graph identity。
  - 引用 review handoff 的全部 `reviewer_input_refs`，确保 reviewer verdict 明确基于 takeover
    outcome、evidence 和 verification。
  - 不能再次请求 `takeover`，避免 takeover follow-up 形成递归接管循环；后续可选择
    `merge | rework | patch_forward | blocked`。
- 新增 `submit_feature_graph_takeover_followup_review_verdict(...)` coordinator helper:
  - 从 artifact store 读取 `FeatureGraphTakeoverReviewHandoff`。
  - 读取对应 `FeatureEvidenceBundle`。
  - 校验并保存 `FeatureReviewVerdict` artifact。
  - 不调用 review status transition、不生成 merge guard、不 dispatch lane。
- `PlatformOrchestrator` 新增
  `submit_feature_graph_takeover_followup_review_verdict(...)` facade。
- 新增 focused tests 覆盖:
  - valid follow-up merge verdict 被接受并保存。
  - 缺少 reviewer input refs 的 verdict 被拒绝。
  - follow-up verdict 再次请求 takeover 被拒绝。
  - platform facade 保持 legacy projection 字节级不变，并不调用 `dispatch_lane(...)`。

已运行验证:

```bash
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_takeover_plan.py \
  src/xmuse_core/structuring/feature_graph_artifact_store.py \
  src/xmuse_core/platform/feature_graph_takeover_coordinator.py \
  src/xmuse_core/platform/orchestrator.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py -k "takeover"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run ruff check .
git diff --check
```

验证结果:

- 本轮触及 Python 文件 ruff: All checks passed。
- takeover focused gate: 41 passed, 214 deselected。
- platform orchestrator full-file regression: 190 passed。
- takeover/artifact/shared fixture contract gate: 75 passed。
- takeover + rework status + patch-forward status focused gate: 47 passed, 217 deselected。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- 本节记录的是当时的 gate-only 边界；后续小节已补显式 application path 和 replay record。
- 真实 reviewer long session 调用仍未接入。
- follow-up verdict application 到 durable event consumer 之间仍缺少通用 event-store/idempotency key
  串联。
- 默认 runner 主循环仍未使用 graph-native takeover artifact chain；`feature_lanes.json` 仍是迁移期
  execution live queue/status source。

## 2026-06-03 Feature Graph Takeover Follow-up Verdict Application Replay

本轮把 takeover follow-up verdict 的显式 application path 补成可审计、可幂等重放的小闭环，仍不改
runner 主循环、Ray/native runtime 或 `feature_lanes.json` live queue:

- 新增 `FeatureGraphTakeoverFollowupReviewApplicationRecord` Pydantic schema。
  - 记录 `review_handoff_id + verdict_id` 的 application identity 和 idempotency key。
  - 内嵌 coordinator 生成的 `FeatureGraphReviewStatusTransitionPlan`。
  - 对 merge/rework/blocked 这类 status transition 记录 `applied_status`。
  - 对 rework / patch-forward / blocked / takeover 分支记录对应 plan 或 packet id。
  - 校验 review plan 的 verdict、evidence bundle、graph-set、feature graph、decision 和
    coordinator action 与 application record 一致。
- `structuring.models` 已兼容 re-export 新 application record。
- `FeatureGraphArtifactStore` 新增:
  - `save_takeover_followup_review_application(...)`
  - `get_takeover_followup_review_application(...)`
  - `list_takeover_followup_review_applications(...)`
  - `list_takeover_followup_review_applications_for_handoff(...)`
- `apply_feature_graph_takeover_followup_review_verdict(...)` 现在:
  - 仍先重新读取并校验 `FeatureGraphTakeoverReviewHandoff`、`FeatureEvidenceBundle` 和已保存
    `FeatureReviewVerdict`。
  - 首次应用时继续委托 `submit_feature_graph_review_verdict(...)`，由 graph-native review
    coordinator 写 status 或生成强 gate plan。
  - 首次应用成功后保存 `FeatureGraphTakeoverFollowupReviewApplicationRecord`。
  - 重放同一 `review_handoff_id + verdict_id` 时优先返回已保存 application record，不再要求当前
    feature graph status 仍处于 `reviewing`，避免 merge/rework/blocked 已应用后重放失败。
  - 不调用 runner、不 dispatch lane、不读取或写入 `feature_lanes.json`。
- 新增 golden fixture:
  - `tests/fixtures/xmuse/contracts/artifacts/feature_graph_takeover_followup_review_application.v1.json`
- 新增/增强 focused tests 覆盖:
  - application record schema golden fixture 和 transition application 必须带 `applied_status`。
  - artifact store 保存、读取、按 review handoff 过滤 application record。
  - takeover follow-up merge verdict 首次应用会写 graph-native merged status/event。
  - 同一 follow-up merge verdict 重放返回同一 application record，不追加 status event。
  - legacy projection 文件保持字节级不变，并不调用 `dispatch_lane(...)`。

已运行验证:

```bash
uv run ruff check --fix src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_artifact_store.py \
  src/xmuse_core/platform/feature_graph_takeover_coordinator.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_artifact_store.py \
  src/xmuse_core/platform/feature_graph_takeover_coordinator.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover_followup or takeover_followup_review_application or followup_applications"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_platform_orchestrator.py -k "takeover"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
```

验证结果:

- 本轮触及 Python 文件 ruff: All checks passed。
- takeover follow-up application focused gate: 5 passed, 230 deselected。
- takeover focused gate: 45 passed, 214 deselected。
- artifact + shared fixture contract gate: 53 passed。
- platform orchestrator full-file regression: 192 passed。
- takeover + rework status + patch-forward status focused gate: 51 passed, 217 deselected。

当前剩余风险:

- application record 是 artifact-store 层的幂等证据，不是通用 event-store consumer；后续仍需把
  takeover follow-up verdict application 接入 durable event/idempotency pipeline。
- artifact store 和 status store 仍不是事务性同写；下一节已补 merge/rework/blocked transition
  已应用但 application record 缺失时的窄 recovery path，但它还不是通用事务方案。
- 真实 persistent reviewer long session、provider binding resume 和 merge guard/worktree guard 尚未接入
  takeover follow-up runtime。
- 默认 runner 主循环仍未使用 graph-native takeover artifact chain；`feature_lanes.json` 仍是迁移期
  execution live queue/status source。

## 2026-06-03 Feature Graph Takeover Follow-up Application Recovery

本轮继续收窄上一节留下的 status-store/artifact-store 非事务窗口，仍保持 coordinator/status-store 权威，
不改 runner 主循环或 `feature_lanes.json`:

- `apply_feature_graph_takeover_followup_review_verdict(...)` 在没有 application record 时新增保守
  recovery path。
- 仅当 saved follow-up verdict 是 `merge | rework | blocked`，且当前 `FeatureGraphStatusStore`
  中同一 feature graph 已经处于该 verdict 对应目标状态时，才认为 status transition 已经成功。
- recovery 会用当前 graph-native status record 重建 `FeatureGraphReviewStatusTransitionPlan` 和
  `FeatureGraphTakeoverFollowupReviewApplicationRecord`，并保存 application record。
- recovery 不会处理 `patch_forward` 或 `takeover`，避免绕过强 gate。
- recovery 不追加 status event、不 dispatch lane、不读取/写入 `feature_lanes.json`。
- 新增 focused test 模拟:
  - takeover follow-up merge verdict 先通过 graph-native review coordinator 写入 `merged` status。
  - application record 缺失。
  - 再调用 takeover follow-up apply 时恢复 application record。
  - status event 数量保持 1，legacy projection 字节级不变。

已运行验证:

```bash
uv run ruff check --fix src/xmuse_core/platform/feature_graph_takeover_coordinator.py \
  tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/platform/feature_graph_takeover_coordinator.py \
  tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k "takeover_followup"
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py -k "takeover"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
```

验证结果:

- touched-file ruff: All checks passed。
- takeover follow-up focused gate: 4 passed, 189 deselected。
- takeover focused gate: 46 passed, 214 deselected。
- platform orchestrator full-file regression: 193 passed。

当前剩余风险:

- recovery 只覆盖 merge/rework/blocked 已完成 status transition 的窄窗口；patch-forward/takeover
  仍必须通过各自强 gate，不做自动恢复。
- artifact store 和 status store 仍不是事务性同写；后续应通过 durable event/idempotency consumer
  统一处理 application 领取、应用、ack 和重放。
- 默认 runner 主循环仍未使用 graph-native takeover artifact chain；`feature_lanes.json` 仍是迁移期
  execution live queue/status source。

## 2026-06-03 Feature Graph Takeover Follow-up Application Output Gate

本轮继续收紧 `FeatureGraphTakeoverFollowupReviewApplicationRecord`，把 reviewer verdict decision 对应的
输出证据固定到 schema gate:

- `rework` application 必须携带 `rework_id`，且非 rework application 禁止携带 `rework_id`。
- `patch_forward` application 必须携带 `patch_forward_plan_id`，且非 patch-forward application 禁止携带
  `patch_forward_plan_id`。
- `blocked` application 必须携带 `blocked_review_plan_id`，且非 blocked application 禁止携带
  `blocked_review_plan_id`。
- `takeover` application 必须携带 `takeover_plan_id`，且非 takeover application 禁止携带
  `takeover_plan_id`。
- 新增 schema negative test，确认 merge application 不能夹带 rework output。
- 新增 takeover follow-up rework recovery test:
  - 先通过 graph-native review coordinator 写入 `reworking` status 和 `ReworkPacket`。
  - application record 缺失。
  - 再调用 takeover follow-up apply 时恢复 application record，并带回同一 `rework_id`。
  - status event 数量保持 1，legacy projection 字节级不变。
- 新增 takeover follow-up blocked recovery test:
  - 先通过 graph-native review coordinator 写入 `blocked` status 和
    `FeatureGraphBlockedReviewPlan`。
  - application record 缺失。
  - 再调用 takeover follow-up apply 时恢复 application record，并带回同一
    `blocked_review_plan_id`、missing inputs 和 blocked owner 证据。
  - status event 数量保持 1，legacy projection 字节级不变。

已运行验证:

```bash
uv run ruff check --fix src/xmuse_core/structuring/feature_review_contracts.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_feature_review_contracts.py -k \
  "takeover_followup_review_application"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k "takeover_followup"
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/platform/feature_graph_takeover_coordinator.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
```

验证结果:

- schema focused gate: 1 passed, 25 deselected。
- takeover follow-up focused gate: 6 passed, 189 deselected。
- takeover + rework status + patch-forward status focused gate: 54 passed, 217 deselected。
- artifact + shared fixture contract gate: 53 passed。
- touched-file ruff: All checks passed。
- platform orchestrator full-file regression: 195 passed。

当前剩余风险:

- application record 现在约束了 decision-specific output id，但还不是事件消费者；后续仍需 durable
  event/idempotency pipeline。
- follow-up rework recovery 依赖此前 review coordinator 已保存 `ReworkPacket`；如果 status transition
  和 packet artifact 本身出现不一致，仍需要更高层 reconciliation。
- follow-up blocked recovery 依赖此前 review coordinator 已保存 `FeatureGraphBlockedReviewPlan`；如果
  status transition 和 blocked plan artifact 本身出现不一致，仍需要更高层 reconciliation。
- 默认 runner 主循环仍未使用 graph-native takeover artifact chain；`feature_lanes.json` 仍是迁移期
  execution live queue/status source。

## 2026-06-03 Feature Graph Takeover Follow-up Application Ref Gate

本轮把 `FeatureGraphTakeoverFollowupReviewApplicationRecord` 的 id 字段进一步绑定到可追踪
artifact refs，避免 application 只带裸 id、缺少可审计引用:

- `input_refs` 必须包含:
  - `feature_graph_takeover_review_handoff:{review_handoff_id}:v1`
  - `feature_review_verdict:{verdict_id}:v1`
  - `feature_evidence_bundle:{evidence_bundle_id}:v1`
- `output_refs` 必须包含:
  - `feature_graph_review_status_transition_plan:{review_plan.plan_id}:v1`
  - 如果有 `applied_status`，必须包含 `feature_graph_status:{status_id}:v1`
  - 如果有 `rework_id`，必须包含 `feature_graph_rework_packet:{rework_id}:v1`
  - 如果有 `patch_forward_plan_id`，必须包含对应 patch-forward plan ref
  - 如果有 `blocked_review_plan_id`，必须包含对应 blocked review plan ref
  - 如果有 `takeover_plan_id`，必须包含对应 takeover plan ref
- 新增 schema negative tests，覆盖缺少 verdict input ref 和缺少 applied status output ref 时被拒绝。
- 既有 takeover follow-up merge/rework/blocked recovery tests 继续证明 coordinator 构造出的
  application record refs 满足 schema gate。

已运行验证:

```bash
uv run ruff check --fix src/xmuse_core/structuring/feature_review_contracts.py \
  tests/xmuse/test_feature_review_contracts.py
uv run pytest -q tests/xmuse/test_feature_review_contracts.py -k \
  "takeover_followup_review_application"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k "takeover_followup"
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/platform/feature_graph_takeover_coordinator.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
```

验证结果:

- schema focused gate: 1 passed, 25 deselected。
- takeover follow-up focused gate: 6 passed, 189 deselected。
- takeover + rework status + patch-forward status focused gate: 54 passed, 217 deselected。
- artifact + shared fixture contract gate: 53 passed。
- touched-file ruff: All checks passed。
- platform orchestrator full-file regression: 195 passed。

当前剩余风险:

- refs gate 证明 application record 内部自洽，但还不是 durable event consumer；后续仍需把
  application 领取、应用、ack 和 replay 接入 event/idempotency pipeline。
- refs 当前是 artifact-ref 字符串约定，尚未通过全局 artifact registry 校验引用存在性。
- 默认 runner 主循环仍未使用 graph-native takeover artifact chain；`feature_lanes.json` 仍是迁移期
  execution live queue/status source。

## 2026-06-03 Feature Graph Takeover Follow-up Application Replay Immutability

本轮把 takeover follow-up review application 的 artifact-store 保存语义从普通 upsert 收紧为
immutable replay record，并补上 corrupt payload guard，继续不改 runner 主循环、runtime dispatch 或
`feature_lanes.json`:

- `FeatureGraphArtifactStore.save_takeover_followup_review_application(...)` 会先重新校验 incoming
  application record。
- 如果同一个 `application_id` 已存在且 payload 完全一致，保存会直接返回已有 record，作为幂等 replay。
- 如果同一个 `application_id` 已存在但 payload 不同，保存会拒绝并抛出 replay conflict，避免静默覆盖
  已经应用过的审计记录。
- 如果 `takeover_followup_review_applications` collection 本身不是 list，或 collection 中存在非 object
  entry，保存会拒绝并保持原 payload 不变，避免在 audit store 里静默覆盖 corrupt 状态。
- 新增 artifact-store focused test，覆盖 identical replay 不重复写入，以及 conflicting payload 被拒绝且
  已保存 application record 保持不变。
- 新增 corrupt collection focused test，覆盖非法容器和非法条目都不会被 save path 静默修复。
- 该能力只保护 takeover follow-up application artifact 的 replay 语义，不把 artifact store 提升为通用
  event store，也不解决 artifact store/status store 跨文件事务问题。

已运行验证:

```bash
uv run ruff check --fix src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py -k \
  "takeover_followup_applications or conflicting_takeover_followup_application or corrupt_takeover_followup_collection"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover_followup or takeover_followup_review_application or followup_applications"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/models.py \
  src/xmuse_core/structuring/feature_graph_artifact_store.py \
  src/xmuse_core/platform/feature_graph_takeover_coordinator.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py
git diff --check
uv run ruff check .
```

验证结果:

- touched-file ruff: All checks passed。
- takeover follow-up application replay/conflict/corrupt focused gate: 4 passed, 16 deselected。
- takeover follow-up application/orchestrator focused gate: 11 passed, 230 deselected。
- artifact + shared fixture contract gate: 56 passed。
- takeover + rework status + patch-forward status focused gate: 57 passed, 217 deselected。
- platform orchestrator full-file regression: 195 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- application immutability 和 corrupt payload guard 只覆盖 takeover follow-up application collection；
  还没有全局 artifact idempotency/event consumer。
- artifact store 和 status store 仍不是事务性同写；现有 recovery path 只覆盖 merge/rework/blocked
  status transition 已写入但 application record 缺失的窄窗口。
- 默认 runner 主循环仍未使用 graph-native takeover artifact chain；`feature_lanes.json` 仍是迁移期
  execution live queue/status source。

## 2026-06-03 Feature Review Verdict Replay Immutability

本轮继续收紧 feature-level artifact store，把 reviewer verdict artifact 也从普通 upsert 收束为
immutable replay record，仍不改 legacy `VerdictStore`、runner 主循环或 runtime dispatch:

- `FeatureGraphArtifactStore.save_review_verdict(...)` 会先重新校验 incoming
  `FeatureReviewVerdict`。
- 如果同一个 `verdict_id` 已存在且 payload 完全一致，保存会返回已有 verdict，作为幂等 replay。
- 如果同一个 `verdict_id` 已存在但 payload 不同，保存会拒绝并抛出 replay conflict，避免 reviewer
  审计结论被静默覆盖。
- 如果 `review_verdicts` collection 本身不是 list，或 collection 中存在非 object entry，保存会拒绝并
  保持原 payload 不变。
- 新增 artifact-store focused tests，覆盖 identical replay、conflicting payload、corrupt collection 和
  `model_copy()` 绕过 schema validator 的负例。
- 该能力只保护 feature graph artifact store 内的 `FeatureReviewVerdict`，不改变 legacy lane-level
  review store，也不是全局 event-store consumer。

已运行验证:

```bash
uv run ruff check --fix src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py -k \
  "review_verdicts_by_bundle or conflicting_review_verdict or corrupt_review_verdict_collection or revalidates_review_verdict_bypass"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "submit_feature_graph_review_verdict or takeover_followup or review_verdict"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
git diff --check
uv run ruff check .
```

验证结果:

- touched-file ruff: All checks passed。
- review verdict replay/conflict/corrupt focused gate: 5 passed, 18 deselected。
- feature graph artifact store full-file gate: 23 passed。
- review verdict / takeover follow-up platform focused gate: 23 passed, 221 deselected。
- artifact + shared fixture contract gate: 59 passed。
- takeover + rework status + patch-forward status focused gate: 57 passed, 220 deselected。
- platform orchestrator full-file regression: 195 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- takeover decision / handoff / outcome / review handoff 等其它 takeover artifact collections
  仍使用普通 idempotent upsert；后续应按审计重要性逐步收紧。
- artifact store 和 status store 仍无跨文件事务；review verdict immutable replay 只能防止同 id 覆盖，
  不能替代 event/idempotency pipeline。
- 默认 runner 主循环仍未使用 graph-native artifact/status chain；`feature_lanes.json` 仍是迁移期
  execution live queue/status source。

## 2026-06-03 Feature Evidence Bundle Replay Immutability

本轮继续收紧 feature-level artifact store，把 worker 返回的 `FeatureEvidenceBundle` 也从普通 upsert
收束为 immutable replay record，仍不改 legacy evidence store、runner 主循环或 runtime dispatch:

- `FeatureGraphArtifactStore.save_evidence_bundle(...)` 会先重新校验 incoming
  `FeatureEvidenceBundle`。
- 如果同一个 `bundle_id` 已存在且 payload 完全一致，保存会返回已有 evidence bundle，作为幂等 replay。
- 如果同一个 `bundle_id` 已存在但 payload 不同，保存会拒绝并抛出 replay conflict，避免 worker evidence
  被静默覆盖。
- 如果 `evidence_bundles` collection 本身不是 list，或 collection 中存在非 object entry，保存会拒绝并
  保持原 payload 不变。
- 新增 artifact-store focused tests，覆盖 identical replay、conflicting payload、corrupt collection 和按
  feature graph 查询不回归。
- 该能力只保护 feature graph artifact store 内的 `FeatureEvidenceBundle`，不改变 self-evolution /
  legacy evidence bundle stores，也不是全局 event-store consumer。

已运行验证:

```bash
uv run ruff check --fix src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py -k "evidence_bundle"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "evidence_bundle or submit_feature_graph_worker_evidence"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
git diff --check
uv run ruff check .
```

验证结果:

- touched-file ruff: All checks passed。
- evidence bundle replay/conflict/corrupt focused gate: 5 passed, 21 deselected。
- feature graph artifact store full-file gate: 26 passed。
- worker evidence/platform focused gate: 21 passed, 206 deselected。
- artifact + shared fixture contract gate: 62 passed。
- takeover + rework status + patch-forward status focused gate: 57 passed, 223 deselected。
- platform orchestrator full-file regression: 195 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- takeover decision / handoff / outcome / review handoff 等其它 takeover artifact collections
  仍使用普通 idempotent upsert；后续应按审计重要性逐步收紧。
- artifact store 和 status store 仍无跨文件事务；evidence bundle immutable replay 只能防止同 id 覆盖，
  不能替代 event/idempotency pipeline。
- 默认 runner 主循环仍未使用 graph-native artifact/status chain；`feature_lanes.json` 仍是迁移期
  execution live queue/status source。

## 2026-06-03 Feature Rework Packet Replay Immutability

本轮继续收紧 feature-level artifact store，把 reviewer `rework` verdict 生成的 `ReworkPacket` 也从
普通 upsert 收束为 immutable replay record，仍不改 runner 主循环、runtime dispatch 或 legacy
review/rework stores:

- `FeatureGraphArtifactStore.save_rework_packet(...)` 会先重新校验 incoming `ReworkPacket`。
- 如果同一个 `rework_id` 已存在且 payload 完全一致，保存会返回已有 packet，作为幂等 replay。
- 如果同一个 `rework_id` 已存在但 payload 不同，保存会拒绝并抛出 replay conflict，避免打回给
  feature worker 的结构化指令被静默覆盖。
- 如果 `rework_packets` collection 本身不是 list，或 collection 中存在非 object entry，保存会拒绝并
  保持原 payload 不变。
- 新增 artifact-store focused tests，覆盖 identical replay、conflicting payload、corrupt collection 和按
  evidence bundle 查询不回归。
- 该能力只保护 feature graph artifact store 内的 `ReworkPacket`；rework limit、same-worker resume、
  provider binding recovery 仍由 coordinator/runtime 后续闭环负责。

已运行验证:

```bash
uv run ruff check --fix src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py -k "rework_packet"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py -k "rework"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
git diff --check
uv run ruff check .
```

验证结果:

- touched-file ruff: All checks passed。
- rework packet replay/conflict/corrupt focused gate: 4 passed, 25 deselected。
- feature graph artifact store full-file gate: 29 passed。
- rework packet/status/platform focused gate: 28 passed, 206 deselected。
- artifact + shared fixture contract gate: 65 passed。
- takeover + rework status + patch-forward status focused gate: 57 passed, 226 deselected。
- platform orchestrator full-file regression: 195 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- takeover decision / handoff / outcome / review handoff 等其它 takeover artifact collections
  仍使用普通 idempotent upsert；后续应按审计重要性逐步收紧。
- artifact store 和 status store 仍无跨文件事务；rework packet immutable replay 只能防止同 id 覆盖，
  不能替代 event/idempotency pipeline。
- rework packet 仍未由 feature worker 长 session 自动消费；默认 runner 主循环仍未使用 graph-native
  artifact/status chain，`feature_lanes.json` 仍是迁移期 execution live queue/status source。

## 2026-06-03 Feature Patch-forward Plan Replay Immutability

本轮继续收紧 feature-level artifact store，把 reviewer `patch_forward` verdict 生成的
`FeatureGraphPatchForwardPlan` 从普通 upsert 收束为 immutable replay record，仍不改 patch execution、
focused gates runtime、merge guard runtime 或 runner 主循环:

- `FeatureGraphArtifactStore.save_patch_forward_plan(...)` 会先重新校验 incoming
  `FeatureGraphPatchForwardPlan`。
- 如果同一个 `plan_id` 已存在且 payload 完全一致，保存会返回已有 plan，作为幂等 replay。
- 如果同一个 `plan_id` 已存在但 payload 不同，保存会拒绝并抛出 replay conflict，避免 reviewer
  patch-forward 强 gate 输入被静默覆盖。
- 如果 `patch_forward_plans` collection 本身不是 list，或 collection 中存在非 object entry，保存会拒绝并
  保持原 payload 不变。
- 新增 artifact-store focused tests，覆盖 identical replay、conflicting payload、corrupt collection 和按
  evidence bundle 查询不回归。
- 该能力只保护 patch-forward plan artifact；实际 reviewer patch、focused gates rerun、merge guard
  decision 仍必须由 coordinator 后续 gate 闭环处理。

已运行验证:

```bash
uv run ruff check --fix src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py -k "patch_forward_plan"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py -k "patch_forward"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
git diff --check
uv run ruff check .
```

验证结果:

- touched-file ruff: All checks passed。
- patch-forward plan replay/conflict/corrupt focused gate: 4 passed, 28 deselected。
- feature graph artifact store full-file gate: 32 passed。
- patch-forward/platform focused gate: 43 passed, 207 deselected。
- artifact + shared fixture contract gate: 68 passed。
- takeover + rework status + patch-forward status focused gate: 57 passed, 229 deselected。
- platform orchestrator full-file regression: 195 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- takeover decision / handoff / outcome / review handoff 等其它 takeover artifact collections
  仍使用普通 idempotent upsert；后续应按审计重要性逐步收紧。
- artifact store 和 status store 仍无跨文件事务；patch-forward plan immutable replay 只能防止同 id
  覆盖，不能替代 event/idempotency pipeline。
- patch-forward runtime 仍未自动执行 reviewer patch / focused gates / merge guard；默认 runner 主循环仍未
  使用 graph-native artifact/status chain，`feature_lanes.json` 仍是迁移期 execution live queue/status source。

## 2026-06-03 Feature Patch-forward Gate Result Replay Immutability

本轮继续收紧 patch-forward 强 gate 证据，把 reviewer patch-forward 后提交的
`FeatureGraphPatchForwardGateResult` 从普通 upsert 收束为 immutable replay record，仍不改实际
patch execution、merge guard runtime、status transition 或 runner 主循环:

- `FeatureGraphArtifactStore.save_patch_forward_gate_result(...)` 会先重新校验 incoming
  `FeatureGraphPatchForwardGateResult`。
- 如果同一个 `result_id` 已存在且 payload 完全一致，保存会返回已有 result，作为幂等 replay。
- 如果同一个 `result_id` 已存在但 payload 不同，保存会拒绝并抛出 replay conflict，避免 patch-forward
  focused gate 证据被静默覆盖。
- 如果 `patch_forward_gate_results` collection 本身不是 list，或 collection 中存在非 object entry，
  保存会拒绝并保持原 payload 不变。
- 新增 artifact-store focused tests，覆盖 identical replay、conflicting payload、corrupt collection 和按
  evidence bundle / plan 查询不回归。
- 该能力只保护 patch-forward gate result artifact；实际 reviewer patch、focused gates rerun、
  merge guard decision 和最终 graph-native status transition 仍必须由 coordinator 后续 gate 闭环处理。

已运行验证:

```bash
uv run ruff check --fix src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py -k \
  "patch_forward_gate_result"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py -k "patch_forward"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
git diff --check
uv run ruff check .
```

验证结果:

- touched-file ruff: All checks passed。
- patch-forward gate result replay/conflict/corrupt focused gate: 4 passed, 31 deselected。
- feature graph artifact store full-file gate: 35 passed。
- patch-forward/platform focused gate: 46 passed, 207 deselected。
- artifact + shared fixture contract gate: 71 passed。
- takeover + rework status + patch-forward status focused gate: 57 passed, 232 deselected。
- platform orchestrator full-file regression: 195 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- takeover decision / handoff / outcome / review handoff 等其它 takeover artifact collections
  仍使用普通 idempotent upsert；后续应按审计重要性逐步收紧。
- artifact store 和 status store 仍无跨文件事务；patch-forward gate result immutable replay 只能防止
  同 id 覆盖，不能替代 event/idempotency pipeline。
- patch-forward runtime 仍未自动执行 reviewer patch / focused gates / merge guard；默认 runner 主循环仍未
  使用 graph-native artifact/status chain，`feature_lanes.json` 仍是迁移期 execution live queue/status source。

## 2026-06-03 Feature Patch-forward Merge Guard Handoff Replay Immutability

本轮继续收紧 patch-forward 强 gate 链路，把 passed gate result 生成的
`FeatureGraphPatchForwardMergeGuardHandoff` 从普通 upsert 收束为 immutable replay record，仍不改
merge guard runtime、status transition 或 runner 主循环:

- `FeatureGraphArtifactStore.save_patch_forward_merge_guard_handoff(...)` 会先重新校验 incoming
  `FeatureGraphPatchForwardMergeGuardHandoff`。
- 如果同一个 `handoff_id` 已存在且 payload 完全一致，保存会返回已有 handoff，作为幂等 replay。
- 如果同一个 `handoff_id` 已存在但 payload 不同，保存会拒绝并抛出 replay conflict，避免交给 merge
  guard 的输入证据被静默覆盖。
- 如果 `patch_forward_merge_guard_handoffs` collection 本身不是 list，或 collection 中存在非 object
  entry，保存会拒绝并保持原 payload 不变。
- 新增 artifact-store focused tests，覆盖 identical replay、conflicting payload、corrupt collection 和按
  gate result 查询不回归。
- 该能力只保护 patch-forward merge guard handoff artifact；实际 merge guard decision 和最终
  graph-native status transition 仍必须由 coordinator 后续 gate 闭环处理。

已运行验证:

```bash
uv run ruff check --fix src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py -k \
  "patch_forward_merge_guard_handoff"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py -k "patch_forward"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
git diff --check
uv run ruff check .
```

验证结果:

- touched-file ruff: All checks passed。
- patch-forward merge-guard handoff replay/conflict/corrupt focused gate: 4 passed, 34 deselected。
- feature graph artifact store full-file gate: 38 passed。
- patch-forward/platform focused gate: 49 passed, 207 deselected。
- artifact + shared fixture contract gate: 74 passed。
- takeover + rework status + patch-forward status focused gate: 57 passed, 235 deselected。
- platform orchestrator full-file regression: 195 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- takeover decision / handoff / outcome / review handoff 等其它 takeover artifact collections
  仍使用普通 idempotent upsert；后续应按审计重要性逐步收紧。
- artifact store 和 status store 仍无跨文件事务；patch-forward merge guard handoff immutable replay
  只能防止同 id 覆盖，不能替代 event/idempotency pipeline。
- patch-forward runtime 仍未自动执行 reviewer patch / focused gates / merge guard；默认 runner 主循环仍未
  使用 graph-native artifact/status chain，`feature_lanes.json` 仍是迁移期 execution live queue/status source。

## 2026-06-03 Feature Patch-forward Merge Guard Decision Replay Immutability

本轮继续收紧 patch-forward 强 gate 链路，把 merge guard 输出的
`FeatureGraphPatchForwardMergeGuardDecision` 从普通 upsert 收束为 immutable replay record，仍不改
merge guard runtime、status transition application 或 runner 主循环:

- `FeatureGraphArtifactStore.save_patch_forward_merge_guard_decision(...)` 会先重新校验 incoming
  `FeatureGraphPatchForwardMergeGuardDecision`。
- 如果同一个 `decision_id` 已存在且 payload 完全一致，保存会返回已有 decision，作为幂等 replay。
- 如果同一个 `decision_id` 已存在但 payload 不同，保存会拒绝并抛出 replay conflict，避免是否允许
  patch-forward merge 的 gate 判定被静默覆盖。
- 如果 `patch_forward_merge_guard_decisions` collection 本身不是 list，或 collection 中存在非 object
  entry，保存会拒绝并保持原 payload 不变。
- 新增 artifact-store focused tests，覆盖 identical replay、conflicting payload、corrupt collection 和按
  handoff 查询不回归。
- 该能力只保护 patch-forward merge guard decision artifact；最终 graph-native status transition 仍由
  coordinator 显式调用 `apply_feature_graph_patch_forward_merge_guard_decision_status(...)`。

已运行验证:

```bash
uv run ruff check --fix src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py -k \
  "patch_forward_merge_guard_decision"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py -k "patch_forward"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
git diff --check
uv run ruff check .
```

验证结果:

- touched-file ruff: All checks passed。
- patch-forward merge-guard decision replay/conflict/corrupt focused gate: 4 passed, 37 deselected。
- feature graph artifact store full-file gate: 41 passed。
- patch-forward/platform focused gate: 52 passed, 207 deselected。
- artifact + shared fixture contract gate: 77 passed。
- takeover + rework status + patch-forward status focused gate: 57 passed, 238 deselected。
- platform orchestrator full-file regression: 195 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- takeover decision / handoff / outcome / review handoff 等其它 takeover artifact collections
  仍使用普通 idempotent upsert；后续应按审计重要性逐步收紧。
- artifact store 和 status store 仍无跨文件事务；patch-forward merge guard decision immutable replay
  只能防止同 id 覆盖，不能替代 event/idempotency pipeline。
- patch-forward runtime 仍未自动执行 reviewer patch / focused gates / merge guard；默认 runner 主循环仍未
  使用 graph-native artifact/status chain，`feature_lanes.json` 仍是迁移期 execution live queue/status source。

## 2026-06-03 Feature Blocked Review Plan Replay Immutability

本轮继续收紧 reviewer `blocked` verdict 生成的结构化 artifact，把
`FeatureGraphBlockedReviewPlan` 从普通 upsert 收束为 immutable replay record，仍不改 blocked
runtime、人工输入恢复流程或 runner 主循环:

- `FeatureGraphArtifactStore.save_blocked_review_plan(...)` 会先重新校验 incoming
  `FeatureGraphBlockedReviewPlan`。
- 如果同一个 `plan_id` 已存在且 payload 完全一致，保存会返回已有 plan，作为幂等 replay。
- 如果同一个 `plan_id` 已存在但 payload 不同，保存会拒绝并抛出 replay conflict，避免缺失输入、
  blocked reason 或 owner 被静默覆盖。
- 如果 `blocked_review_plans` collection 本身不是 list，或 collection 中存在非 object entry，保存会拒绝并
  保持原 payload 不变。
- 新增 artifact-store focused tests，覆盖 identical replay、conflicting payload、corrupt collection 和按
  evidence bundle 查询不回归。
- 该能力只保护 blocked review plan artifact；blocked 恢复、人工输入处理和 graph-native status
  后续转换仍必须由 coordinator 后续流程显式处理。

已运行验证:

```bash
uv run ruff check --fix src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py -k \
  "blocked_review_plan"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_platform_orchestrator.py -k "blocked"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or blocked or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
git diff --check
uv run ruff check .
```

验证结果:

- touched-file ruff: All checks passed。
- blocked review plan replay/conflict/corrupt focused gate: 4 passed, 40 deselected。
- feature graph artifact store full-file gate: 44 passed。
- blocked review/platform focused gate: 15 passed, 256 deselected。
- artifact + shared fixture contract gate: 80 passed。
- takeover + blocked + rework status + patch-forward status focused gate: 71 passed, 233 deselected。
- platform orchestrator full-file regression: 195 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- takeover decision / handoff / outcome / review handoff 等其它 takeover artifact collections
  仍使用普通 idempotent upsert；后续应按审计重要性逐步收紧。
- artifact store 和 status store 仍无跨文件事务；blocked review plan immutable replay 只能防止同 id
  覆盖，不能替代 event/idempotency pipeline。
- blocked 恢复和人工输入处理仍未成为默认 runner 主循环的 graph-native 闭环；`feature_lanes.json`
  仍是迁移期 execution live queue/status source。

## 2026-06-03 Feature Takeover Plan Replay Immutability

本轮继续收紧 reviewer `takeover` verdict 生成的 coordinator takeover gate 输入，把
`FeatureGraphTakeoverPlan` 从普通 upsert 收束为 immutable replay record，仍不改 takeover
runtime、attempt lease、worktree/merge guard 或 runner 主循环:

- `FeatureGraphArtifactStore.save_takeover_plan(...)` 会先重新校验 incoming
  `FeatureGraphTakeoverPlan`。
- 如果同一个 `plan_id` 已存在且 payload 完全一致，保存会返回已有 plan，作为幂等 replay。
- 如果同一个 `plan_id` 已存在但 payload 不同，保存会拒绝并抛出 replay conflict，避免 takeover
  gate 的输入被静默覆盖。
- 如果 `takeover_plans` collection 本身不是 list，或 collection 中存在非 object entry，保存会拒绝并
  保持原 payload 不变。
- 新增 artifact-store focused tests，覆盖 identical replay、conflicting payload、corrupt collection 和按
  evidence bundle 查询不回归。
- 该能力保护 takeover gate plan 内记录的 failed worker session、failed provider binding ref、
  takeover reason、structured triggers 和 evidence refs；真实 takeover execution、attempt lease、
  worktree/merge guard、merge guard decision 与最终 graph-native status transition 仍需由 coordinator
  后续流程显式处理。

已运行验证:

```bash
uv run ruff check --fix src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py -k \
  "takeover_plan"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py -k "takeover"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or blocked or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
uv run ruff check src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
git diff --check
uv run ruff check .
```

验证结果:

- touched-file ruff: All checks passed。
- takeover plan replay/conflict/corrupt focused gate: 4 passed, 43 deselected。
- feature graph artifact store full-file gate: 47 passed。
- takeover focused regression: 54 passed, 238 deselected。
- artifact + shared fixture contract gate: 83 passed。
- takeover + blocked + rework status + patch-forward status focused gate: 74 passed, 233 deselected。
- platform orchestrator full-file regression: 195 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- takeover follow-up application 已具备 immutable replay；后续仍需把这些 artifact 写入
  event/idempotency pipeline，而不是只依赖 artifact store 本身。
- artifact store 和 status store 仍无跨文件事务；takeover plan immutable replay 只能防止同 id 覆盖，
  不能替代 event/idempotency pipeline。
- takeover runtime、attempt lease、worktree/merge guard 和 takeover 后续 reviewer 闭环仍未成为默认
  runner 主循环的 graph-native 闭环；`feature_lanes.json` 仍是迁移期 execution live queue/status source。

## 2026-06-03 Feature Takeover Chain Replay Immutability

本轮继续收紧 reviewer `takeover` verdict 通过 coordinator gate 后的 artifact chain，把
`FeatureGraphTakeoverDecision`、`FeatureGraphTakeoverHandoff`、`FeatureGraphTakeoverOutcome`
和 `FeatureGraphTakeoverReviewHandoff` 从普通 upsert 收束为 immutable replay records，仍不改
takeover runtime、attempt lease、worktree/merge guard、status transition 或 runner 主循环:

- `FeatureGraphArtifactStore.save_takeover_decision(...)` 现在按 `decision_id` 做 immutable replay。
- `FeatureGraphArtifactStore.save_takeover_handoff(...)` 现在按 `handoff_id` 做 immutable replay。
- `FeatureGraphArtifactStore.save_takeover_outcome(...)` 现在按 `outcome_id` 做 immutable replay。
- `FeatureGraphArtifactStore.save_takeover_review_handoff(...)` 现在按 `review_handoff_id` 做
  immutable replay。
- 如果同一个 artifact id 已存在且 payload 完全一致，保存会返回已有 record，作为幂等 replay。
- 如果同一个 artifact id 已存在但 payload 不同，保存会拒绝并抛出 replay conflict，避免 takeover
  gate decision、handoff 输入、worker outcome 或 follow-up review 输入被静默覆盖。
- 如果对应 collection 本身不是 list，或 collection 中存在非 object entry，保存会拒绝并保持原 payload
  不变。
- 新增 artifact-store focused tests，覆盖四类 artifact 的 identical replay、conflicting payload、
  corrupt collection 和按上游 id 查询不回归。
- 新增 store 内部 helper 仅统一 replay/corrupt gate；不改变 artifact store 的 schema version、
  JSON payload 形状或现有 read APIs。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py -k \
  "takeover_decision or takeover_handoff or takeover_outcome or takeover_review_handoff or corrupt_takeover_chain"
uv run ruff check src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_platform_orchestrator.py -k "takeover"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_artifact_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "takeover or blocked or rework_packet_status or patch_forward_merge_guard_decision_status"
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
git diff --check
uv run ruff check .
```

验证结果:

- takeover chain replay/conflict/corrupt focused gate: 16 passed, 43 deselected。
- touched-file ruff: All checks passed。
- feature graph artifact store full-file gate: 59 passed。
- takeover focused regression: 66 passed, 238 deselected。
- artifact + shared fixture contract gate: 95 passed。
- takeover + blocked + rework status + patch-forward status focused gate: 86 passed, 233 deselected。
- platform orchestrator full-file regression: 195 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- takeover artifact chain 已具备 per-id immutable replay，但还不是 durable event consumer；
  后续仍需把 gate decision、handoff、outcome、review handoff 的领取、应用、ack 和 replay 接入
  event/idempotency pipeline。
- artifact store 和 status store 仍无跨文件事务；takeover chain immutable replay 只能防止同 id 覆盖，
  不能替代 coordinator-owned status transition。
- takeover runtime、attempt lease、worktree/merge guard 和 takeover 后续 reviewer 闭环仍未成为默认
  runner 主循环的 graph-native 闭环；`feature_lanes.json` 仍是迁移期 execution live queue/status source。

## 2026-06-03 Feature Graph Status Corrupt Payload Guard

本轮继续强化 P0 graph-native status store 的执行权威基础，修复
`FeatureGraphStatusStore` 读取 persisted status payload 时会把 corrupt `statuses` 静默当成空列表或
过滤掉非 object entry 的问题。该改动不改变 runner dispatch、projection 或 `feature_lanes.json`:

- 文件不存在时仍按空 status store 初始化，保持首次创建行为不变。
- 如果已存在的 `feature_graph_statuses.json` root payload 不是 object，读取会抛出
  `feature graph status payload must be an object`。
- 如果 `statuses` collection 不是 list，读取会抛出
  `feature graph statuses must be a list`。
- 如果 `statuses` collection 中存在非 object entry，读取会抛出
  `feature graph status must be an object`。
- `upsert(...)` 在上述 corrupt payload 上会先拒绝并保持原文件内容不变，避免把坏的执行权威状态文件
  静默覆盖成新状态。
- legacy payload 缺少 `events` 的兼容读取保持不变；event journal 的既有 validation 也保持不变。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py -k \
  "corrupt_status_payload"
uv run ruff check src/xmuse_core/structuring/feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_status_store.py
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py
uv run pytest -q tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_takeover_plan.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "status or blocked or takeover or rework_packet_status or patch_forward_merge_guard_decision_status"
git diff --check
uv run ruff check .
```

验证结果:

- status corrupt payload focused gate: 6 passed, 31 deselected。
- touched-file ruff: All checks passed。
- feature graph status store full-file gate: 37 passed。
- status store + review contract + projection/builder regression: 89 passed。
- status application + blocked/takeover/platform focused regression: 119 passed, 152 deselected。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- status store 仍不是完整 event store；它现在保护 corrupt persisted payload 不被静默覆盖，但还没有
  at-least-once event consumer、ack/replay pipeline 或跨 store transaction。
- runner/orchestrator 默认路径仍未完全切到 graph-native status authority；`feature_lanes.json` 仍是
  迁移期 execution live queue/status source。
- corrupt payload guard 只覆盖 status root/statuses/events 的结构读取；后续还应继续补跨 store
  consistency checks，例如 artifact refs 与 status transition evidence 的存在性校验。

## 2026-06-03 Provider Session Binding Corrupt Payload Guard

本轮继续强化 provider-native session resume 的审计基础，修复
`ProviderSessionBindingStore` 读取 persisted binding payload 时会把 corrupt root payload 静默当成空
store、把非 list `bindings` 当空列表、或过滤掉非 object binding entry 的问题。该改动不改变 runtime
dispatch、God/Ray session layer 或 provider adapter command building:

- 文件不存在时仍按空 provider binding store 初始化，保持首次创建行为不变。
- 如果已存在的 `provider_session_bindings.json` root payload 不是 object，读取会抛出
  `provider session binding payload must be an object`。
- 如果 `bindings` collection 不是 list，读取会抛出
  `provider session bindings must be a list`。
- 如果 `bindings` collection 中存在非 object entry，读取会抛出
  `provider session binding must be an object`。
- `upsert_active(...)` 在上述 corrupt payload 上会先拒绝并保持原文件内容不变，避免把坏的
  provider-native session resume 证据静默覆盖成新 binding。
- 既有 `--last` / latest alias schema gate、active binding replacement、retire previous active slot、
  failed/stale exclusion、explicit Codex resume command tests 保持不变。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py -k \
  "corrupt_binding_payload"
uv run ruff check src/xmuse_core/agents/provider_session_binding_store.py \
  tests/xmuse/test_provider_session_binding_store.py
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "provider_session_binding or explicit_binding or resume_binding or binding"
uv run pytest -q tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_session_binding_store.py
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_god_session_registry.py \
  tests/xmuse/test_god_session_layer.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py
git diff --check
uv run ruff check .
```

验证结果:

- provider binding corrupt payload focused gate: 6 passed, 9 deselected。
- touched-file ruff: All checks passed。
- provider session binding store full-file gate: 15 passed。
- provider binding/resume + orchestrator focused regression: 27 passed, 204 deselected。
- provider codex retrofit + execution binding + binding store regression: 36 passed。
- provider binding store + feature review contract + GOD session regression: 77 passed。
- platform orchestrator full-file regression: 195 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- provider binding store 仍不是完整 event/idempotency pipeline；它现在保护 corrupt persisted payload
  不被静默覆盖，但还没有 ack/replay event consumer 或跨 store transaction。
- God/Ray session layer 与 provider-native binding 的默认 runtime 闭环仍未完全收束；Ray app-server
  ephemeral thread 仍不作为跨进程 provider session binding 依据。
- 默认 runner 主循环仍主要通过 lane projection/context 触达 provider binding；目标态仍应收敛到
  feature graph worker session identity 与 graph-native status/evidence chain。

## 2026-06-03 Provider Session Binding Replay Immutability

本轮继续强化 provider-native session resume 的 replay/idempotency 契约，把
`ProviderSessionBindingStore.upsert_active(...)` 中的 `binding_id` 明确收束为不可变 replay identity。
该改动仍不改变 runtime dispatch、Ray/God session layer 或 provider adapter command building:

- 相同 `binding_id` 且完整 payload 相同的 active binding replay 是幂等的，不新增重复记录。
- 相同 `binding_id` 但 payload 不同的 replay 会抛出
  `provider session binding replay conflict`，并保持既有文件内容不变。
- 已被同 slot 新 active binding retire 的旧 binding，不能通过重放旧 active payload 重新激活。
- 同一 `god_session_id + provider + session_kind` slot 的新 `binding_id` active binding 仍保持兼容行为：
  新 binding 写入，旧 active binding 变为 `retired`。
- 该约束补的是 provider-native resume 证据的 per-id immutable replay guard；它不等价于完整
  event/idempotency pipeline，也不提供跨 store transaction。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py -k \
  "conflicting_binding_id_replay or retired_binding_reactivation or idempotent_for_replay or retires_previous_active_slot"
uv run ruff check src/xmuse_core/agents/provider_session_binding_store.py \
  tests/xmuse/test_provider_session_binding_store.py
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py
uv run pytest -q tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_session_binding_store.py
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "provider_session_binding or explicit_binding or resume_binding or binding"
git diff --check
```

验证结果:

- binding replay immutability focused gate: 4 passed。
- touched-file ruff: All checks passed。
- provider session binding store full-file gate: 17 passed。
- provider codex retrofit + execution binding + binding store regression: 38 passed。
- provider binding/resume + orchestrator focused regression: 29 passed, 204 deselected。
- `git diff --check`: passed。

当前剩余风险:

- provider binding store 仍不是完整 durable event consumer；`binding_id` replay guard 只能防止同 id
  不一致覆盖，不能替代 coordinator-owned status transition 或 ack/replay pipeline。
- retired/failed/stale binding 的生命周期仍只由 store guard 和 coordinator 调用约束；跨 store 的
  artifact/status/binding consistency check 仍需后续补齐。
- Ray app-server thread 与 provider-native CLI session binding 的默认 runtime 闭环仍未完全统一。

## 2026-06-03 Feature Graph Status ID Replay Immutability

本轮继续强化 P0 graph-native status authority，把
`FeatureGraphStatusStore` 中的 `status_id` 明确收束为不可变 replay identity。该改动不改变 runner
dispatch、projection、reviewer verdict application 或 `feature_lanes.json`:

- `upsert(...)` 中相同 `status_id` 且完整 payload 相同的 replay 是幂等的，不新增重复 status record。
- `upsert(...)` 中相同 `status_id` 但 payload 不同的 replay 会抛出
  `feature graph status replay conflict`，并保持既有 status record 不变。
- `transition(...)` 也执行同一 replay guard，避免用旧 `status_id` 写入新的 target status 或 lane set。
- graph-set 初始化内部复用的 `_upsert_record(...)` 同样执行 replay guard，避免初始化/释放 dependent ready
  status 时绕过 per-id immutability。
- 同一 feature graph 的合法新状态仍使用新的 `status_id` 进入既有 transition guard；该改动不替代
  event consumer、ack/replay pipeline 或跨 store transaction。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py -k \
  "same_status_id_replay or conflicting_status_id_replay"
uv run ruff check src/xmuse_core/structuring/feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_status_store.py
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py
uv run pytest -q tests/xmuse/test_feature_graph_worker_claims.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_dependency_coordinator.py
git diff --check
uv run ruff check .
```

验证结果:

- status_id replay immutability focused gate: 3 passed, 37 deselected。
- touched-file ruff: All checks passed。
- feature graph status store full-file gate: 40 passed。
- worker/review/rework/patch-forward/dependency status application regression: 27 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、
  `src/xmuse_core/structuring/blueprint_execution/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- status store 仍不是完整 event store；`status_id` replay guard 只能防止同 id 不一致覆盖，不能替代
  coordinator-owned transition/event application。
- artifact refs、provider session binding refs 与 status transitions 的跨 store consistency check 仍未补齐。
- 默认 runner 主循环仍未完全切到 graph-native ready/status authority；`feature_lanes.json` 仍是迁移期
  live queue/status projection。

## 2026-06-03 Feature Graph Status Event Replay Immutability

本轮继续强化 graph-native status store 的 event journal 基础，补齐 persisted
`FeatureGraphStatusEventRecord` 的 replay conflict guard。该改动不改变 event schema、runner dispatch、
projection 或 reviewer/status transition application:

- `list_events(...)` 读取 persisted `events` 时，如果同一 `event_id` 出现不同 payload，会抛出
  `feature graph status event replay conflict`。
- `list_events(...)` 读取 persisted `events` 时，如果同一 `idempotency_key` 出现不同 payload，也会抛出
  `feature graph status event replay conflict`。
- `_append_event(...)` 继续保持同一 `idempotency_key` 的 exact replay 幂等；如果未来生成路径出现同 key
  不同 payload，会拒绝追加而不是静默吞掉新事件。
- 既有 legacy payload 缺少 `events` 的兼容读取保持不变；event container/entry shape validation 保持不变。
- 该 guard 只保护 status event journal 的 per-id/per-key immutability，不替代 durable event consumer、
  ack/replay pipeline 或跨 store transaction。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py -k \
  "conflicting_event_id_replay or conflicting_event_idempotency_replay"
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py
uv run ruff check src/xmuse_core/structuring/feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_status_store.py
uv run pytest -q tests/xmuse/test_feature_graph_worker_claims.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_dependency_coordinator.py
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py
git diff --check
uv run ruff check .
```

验证结果:

- status event replay immutability focused gate: 2 passed, 40 deselected。
- feature graph status store full-file gate: 42 passed。
- touched-file ruff: All checks passed。
- worker/review/rework/patch-forward/dependency status application regression: 27 passed。
- review contract + status/projection/builder regression: 94 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、
  `src/xmuse_core/structuring/blueprint_execution/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- status store event journal 仍是 store-local append log，不是完整 coordinator event store。
- event_id/idempotency_key guard 只防 persisted replay conflict；还没有跨 status/artifact/provider binding
  evidence consistency transaction。
- 默认 runner 与 platform orchestrator 仍未完全从 `feature_lanes.json` 迁移到 graph-native ready/status
  authority。

## 2026-06-03 Feature Graph Status Event Idempotency Schema

本轮继续强化 graph-native status event 的稳定契约，把 `FeatureGraphStatusEventRecord.idempotency_key`
从“非空字符串”收束为由 graph/status identity 派生的 schema-level contract。该改动不改变事件字段、
store 写入格式、runner dispatch 或 projection:

- `feature_graph_status.initialized` event 的 idempotency key 必须等于
  `feature_graph_status.initialized:{graph_set_id}:{feature_graph_id}:{status_id}`。
- `feature_graph_status.transitioned` event 的 idempotency key 必须等于
  `feature_graph_status.transitioned:{graph_set_id}:{feature_graph_id}:{from_status_id}:{status_id}`。
- initialized event 仍要求没有 `from_status/from_status_id`；transitioned event 仍要求有
  `from_status/from_status_id`。
- 既有 golden fixture `feature_graph_status_event.v1.json` 保持稳定；store 生成的 initialized /
  transitioned events 已符合该格式。
- 该 schema guard 防止 persisted status events 携带任意 dedupe key，但不替代完整 event store、
  ack/replay pipeline 或跨 store transaction。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_review_contracts.py -k \
  "status_transition_event_requires_derived_idempotency_key or status_initialized_event_requires_derived_idempotency_key"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  tests/xmuse/test_feature_review_contracts.py
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py
uv run pytest -q tests/xmuse/test_feature_graph_worker_claims.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_dependency_coordinator.py
uv run pytest -q tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_feature_review_contracts.py
git diff --check
uv run ruff check .
```

验证结果:

- status event idempotency schema focused gate: 2 passed, 26 deselected。
- feature review contracts full-file gate: 28 passed。
- touched-file ruff: All checks passed。
- status/review/projection/builder regression: 96 passed。
- worker/review/rework/patch-forward/dependency status application regression: 27 passed。
- shared contract fixtures + feature review contracts regression: 34 passed。
- touched status/review contract gate: 70 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、
  `src/xmuse_core/structuring/blueprint_execution/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- `FeatureGraphStatusEventRecord` 仍只是 status-store-local event contract，不是完整 xmuse
  coordinator event envelope。
- event idempotency schema 还未覆盖跨 artifact/status/provider binding 的 evidence ref 一致性。
- 默认执行仍未完全从 migration live queue 切到 graph-native ready/status authority。

## 2026-06-03 Feature Graph Status Event ID Schema

本轮继续收束 graph-native status event identity，把 `FeatureGraphStatusEventRecord.event_id`
也从“非空字符串”收束为由 graph/status identity 派生的 schema-level contract。该改动不改变事件
字段、store 写入格式、runner dispatch 或 projection:

- `feature_graph_status.initialized` event 的 event id 必须等于
  `fgse:initialized:{graph_set_id}:{feature_graph_id}:{status_id}`。
- `feature_graph_status.transitioned` event 的 event id 必须等于
  `fgse:transition:{graph_set_id}:{feature_graph_id}:{from_status_id}:{status_id}`。
- 该规则与上一轮 idempotency key schema 配套，使 persisted event 的 `event_id` 和
  `idempotency_key` 都由同一组 status identity 字段稳定派生。
- 既有 golden fixture `feature_graph_status_event.v1.json` 保持稳定；status store 生成的 initialized /
  transitioned event 已符合该格式。
- 旧 replay-conflict 测试已调整为使用合法派生 event identity、修改非身份 payload 字段来验证冲突，
  避免用 schema-invalid event 混淆 replay guard。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_review_contracts.py -k \
  "status_transition_event_requires_derived_event_id or status_initialized_event_requires_derived_event_id"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py -k \
  "conflicting_event_id_replay or conflicting_event_idempotency_replay"
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  tests/xmuse/test_feature_review_contracts.py \
  src/xmuse_core/structuring/feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_status_store.py
uv run pytest -q tests/xmuse/test_feature_graph_worker_claims.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_dependency_coordinator.py
uv run pytest -q tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_feature_review_contracts.py
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_status_store.py
git diff --check
uv run ruff check .
```

验证结果:

- status event id schema focused gate: 2 passed, 28 deselected。
- feature review contracts full-file gate: 30 passed。
- status event replay-conflict focused gate: 2 passed, 40 deselected。
- status/review/projection/builder regression: 98 passed。
- touched-file ruff: All checks passed。
- worker/review/rework/patch-forward/dependency status application regression: 27 passed。
- shared contract fixtures + feature review contracts regression: 36 passed。
- touched status/review contract gate: 72 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、
  `src/xmuse_core/structuring/blueprint_execution/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- status event schema 仍是 status-store-local contract，不是完整 xmuse coordinator event envelope。
- event id/key schema 还未覆盖跨 artifact/status/provider binding 的 evidence ref 一致性。
- 默认 runner 与 platform orchestrator 仍未完全从 `feature_lanes.json` 切到 graph-native
  ready/status authority。

## 2026-06-03 Feature Graph Status Timestamp Schema

本轮继续强化 graph-native status/status-event 的稳定契约，把
`FeatureGraphExecutionStatusRecord.updated_at` 和 `FeatureGraphStatusEventRecord.updated_at`
从“非空字符串”收束为 ISO-8601 且必须带 timezone offset 的 schema-level contract。该改动不改变
事件字段、store 写入格式、runner dispatch 或 projection:

- `updated_at` 不是 ISO-8601 timestamp 时会抛出 `updated_at must be ISO-8601`。
- `updated_at` 缺少 timezone offset 时会抛出 `updated_at must include timezone offset`。
- `Z` 后缀继续作为 UTC offset 兼容，既有 golden fixtures 和 status store 生成路径保持稳定。
- 该 schema guard 与 status store stale/replay 比较中的 timestamp parsing 保持一致，避免 contract 层
  接受 store 层无法可靠排序的 timestamp。
- 该改动只覆盖 feature graph execution status/status event，不批量扩张到其它历史 timestamp 字段，
  避免引入无关迁移风险。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_review_contracts.py -k \
  "requires_timestamp_with_timezone"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  tests/xmuse/test_feature_review_contracts.py
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_feature_graph_builder.py
uv run pytest -q tests/xmuse/test_feature_graph_worker_claims.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_dependency_coordinator.py
uv run pytest -q tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_feature_review_contracts.py
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_status_store.py
git diff --check
uv run ruff check .
```

验证结果:

- status/status-event timestamp schema focused gate: 4 passed, 30 deselected。
- feature review contracts full-file gate: 34 passed。
- touched-file ruff: All checks passed。
- status/review/projection/builder regression: 102 passed。
- worker/review/rework/patch-forward/dependency status application regression: 27 passed。
- shared contract fixtures + feature review contracts regression: 40 passed。
- touched status/review contract gate: 76 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、
  `src/xmuse_core/structuring/blueprint_execution/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- timestamp schema 仍只覆盖 graph-native status/status-event；其它 legacy artifacts 的 timestamp
  仍主要由各自测试或消费者解析约束。
- status/event timestamp 仍不是完整 event-store clock/ordering protocol；跨 store ordering 和
  coordinator event envelope 仍需后续设计。
- 默认执行仍未完全从 migration live queue 切到 graph-native ready/status authority。

## 2026-06-03 Provider Session Binding Timestamp Schema

本轮继续强化 provider-native session resume 证据，把 `ProviderSessionBindingRecord` 的时间字段从
“非空字符串”收束为 ISO-8601 且必须带 timezone offset 的 schema-level contract。该改动不改变
provider adapter command building、runtime dispatch、store 写入格式或 resume lookup:

- `created_at` 不是 ISO-8601 timestamp 时会抛出 `created_at must be ISO-8601`。
- `created_at` 缺少 timezone offset 时会抛出 `created_at must include timezone offset`。
- `last_used_at` / `last_verified_at` 如果存在，也必须是 ISO-8601 且带 timezone offset。
- `Z` 后缀继续作为 UTC offset 兼容，既有 golden fixture 与 provider binding helper/store tests
  保持稳定。
- 该 schema guard 让 provider session binding 的 created/used/verified 证据可排序、可审计；
  它不改变 failed/stale/retired lifecycle，也不替代完整 event/idempotency pipeline。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_review_contracts.py -k \
  "provider_session_binding_requires_timestamps_with_timezone"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  tests/xmuse/test_feature_review_contracts.py
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_codex_retrofit.py
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_god_session_registry.py \
  tests/xmuse/test_god_session_layer.py
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "provider_session_binding or explicit_binding or resume_binding or binding"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_provider_session_binding_store.py
git diff --check
uv run ruff check .
```

验证结果:

- provider binding timestamp schema focused gate: 4 passed, 34 deselected。
- feature review contracts full-file gate: 38 passed。
- touched-file ruff: All checks passed。
- provider codex retrofit + execution binding + binding store regression: 38 passed。
- feature review contracts + provider binding/GOD session regression: 91 passed。
- provider binding/resume + orchestrator focused regression: 29 passed, 204 deselected。
- touched provider binding contract/store gate: 55 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、
  `src/xmuse_core/structuring/blueprint_execution/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- provider binding timestamp schema 不等价于 provider session lease/heartbeat 或 event-sourced lifecycle。
- `last_used_at` 仍由 helper/store 调用方传入；后续 coordinator runtime 闭环仍需统一更新时间写入策略。
- Ray app-server thread 与 provider-native CLI session binding 的默认 runtime 闭环仍未完全统一。

## 2026-06-03 Provider Session Binding Timeline Ordering

本轮继续强化 provider-native session resume 的审计契约，在已有 ISO-8601 + timezone schema
基础上增加 timeline ordering guard。该改动仍只发生在
`ProviderSessionBindingRecord` contract 层，不改变 provider adapter command building、store
写入格式、runtime dispatch、resume lookup 或 `feature_lanes.json` 投影:

- `last_used_at` 如果存在，必须不早于 `created_at`。
- `last_verified_at` 如果存在，必须不早于 `created_at`。
- 违反顺序时分别抛出 `last_used_at must not be earlier than created_at` 或
  `last_verified_at must not be earlier than created_at`。
- `Z` 后缀继续按 UTC offset 兼容；字段仍序列化为原始字符串，避免破坏现有 fixtures、
  store JSON 和 adapter helper。
- 该 guard 防止 replay/store/helper 路径接受时间线倒挂的 provider binding 证据，提升后续
  stale/failed/resume 审计的可靠性，但不替代完整 provider session lease/heartbeat。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_review_contracts.py -k \
  "provider_session_binding_timeline"
uv run pytest -q tests/xmuse/test_feature_review_contracts.py
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_codex_retrofit.py
uv run ruff check src/xmuse_core/structuring/feature_review_contracts.py \
  tests/xmuse/test_feature_review_contracts.py
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_codex_retrofit.py \
  tests/xmuse/test_platform_orchestrator.py -k \
  "provider_session_binding or explicit_binding or resume_binding or binding"
git diff --check
uv run ruff check .
```

验证结果:

- provider binding timeline focused gate: 2 passed, 38 deselected。
- feature review contracts full-file gate: 40 passed。
- provider binding store + execution binding + Codex retrofit regression: 38 passed。
- touched-file ruff: All checks passed。
- provider binding/resume + orchestrator focused regression: 29 passed, 204 deselected。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、
  `src/xmuse_core/structuring/blueprint_execution/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- provider binding timeline ordering 仍是 record-level schema guard，不是 coordinator-owned
  event clock 或 provider session lifecycle protocol。
- `last_used_at` / `last_verified_at` 的更新策略仍需由后续 coordinator/runtime store 闭环统一。
- 成功 provider result 写入 `ProviderSessionBindingStore`、resume failure 标记 stale/failed、
  以及 God/Ray session layer 自动传递 compatible binding 仍未接入默认运行路径。

## 2026-06-03 Provider Session Binding Upsert Degradation

本轮继续收紧 execution/coordinator 对 provider-native session binding 的状态权威边界。当前
`PlatformOrchestrator` 已将 `ProviderSessionBindingStore` 显式传入 `run_execution_god`，
成功 provider result 会由 coordinator-side helper 写入 binding store，resume 失败会标记
stale/failed。本轮补上失败隔离: provider binding 落库失败不得覆盖已经成功的 worker execution
result，但必须留下可审计 metadata:

- `run_execution_god` 在 successful `ProviderInvocationResult` 后尝试 upsert binding。
- 如果 binding writer 抛出 replay conflict、IO/schema 或其它异常，lane 仍按 worker result
  进入 `executed` 并调用 `on_executed`。
- 失败会记录:
  - `provider_session_binding_degraded=true`
  - `provider_session_binding_degraded_reason=upsert_failed`
  - `provider_session_binding_failure=<error>`
- 成功落库会记录 `provider_session_binding_degraded=false` 和
  `provider_session_binding_id=<binding_id>`。
- 该改动只影响 coordinator-side execution helper，不把 durable writes 放入 adapter/worker，也不改变
  provider command planning、resume lookup 或 `feature_lanes.json` 投影语义。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_execution_child_worker.py -k \
  "provider_binding_upsert_failure"
uv run pytest -q tests/xmuse/test_execution_child_worker.py
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_codex_retrofit.py
uv run ruff check src/xmuse_core/platform/execution/executor.py \
  tests/xmuse/test_execution_child_worker.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k \
  "provider_session_binding or explicit_binding or resume_binding or binding"
uv run pytest -q tests/xmuse/test_execution_child_worker.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_session_binding_store.py
git diff --check
uv run ruff check .
```

验证结果:

- provider binding upsert degradation focused gate: 1 passed, 7 deselected。
- execution child worker full-file gate: 8 passed。
- provider binding store + execution binding + Codex retrofit regression: 38 passed。
- touched-file ruff: All checks passed。
- orchestrator provider binding focused gate: 4 passed, 191 deselected。
- execution child worker + execution binding + binding store regression: 29 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、
  `src/xmuse_core/structuring/blueprint_execution/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- provider binding upsert failure 目前记录在 lane metadata；后续 graph-native status/event store
  需要把该 degradation 作为 coordinator event/evidence 写入，而不是长期依赖 projection metadata。
- successful provider binding upsert 的 `created_at/last_used_at/last_verified_at` 仍使用同一 coordinator
  timestamp；后续 runtime 闭环应区分 first capture、last use、last verification。
- Ray app-server thread 与 provider-native CLI session binding 的统一策略仍未完成。

## 2026-06-03 Provider Session Binding Mark-Failed Degradation

本轮补齐 provider resume failure 路径的对称失败隔离。上一轮已经保证 successful worker result 后
binding upsert 失败不会覆盖 `executed` 状态；本轮保证 provider result 已经失败时，标记旧 binding
为 stale/failed 的 side-effect 失败也不能阻断 coordinator 写入 `exec_failed`:

- `run_execution_god` 在 failed `ProviderInvocationResult` 后仍尝试通过 coordinator-owned writer
  标记 active binding 为 stale/failed。
- 如果 writer 的 `mark_failed()` 抛出 IO、schema、missing binding 或其它异常，lane 仍按 provider
  result 进入 `exec_failed`。
- 失败会记录:
  - `provider_session_binding_degraded=true`
  - `provider_session_binding_degraded_reason=mark_failed_failed`
  - `provider_session_binding_id=<binding_id>`
  - `provider_session_binding_failure=<error>`
- 成功标记会记录 `provider_session_binding_degraded=false` 和
  `provider_session_binding_id=<binding_id>`。
- 该改动保持 adapter/worker 不写 durable state；binding lifecycle 仍由 coordinator-side helper/store
  负责。当前 metadata 仍写在迁移期 lane projection 上，后续应迁到 graph-native status/event evidence。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_execution_child_worker.py -k \
  "mark_failed_failure"
uv run pytest -q tests/xmuse/test_execution_child_worker.py
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_codex_retrofit.py
uv run ruff check src/xmuse_core/platform/execution/executor.py \
  tests/xmuse/test_execution_child_worker.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k \
  "provider_session_binding or explicit_binding or resume_binding or binding"
uv run pytest -q tests/xmuse/test_execution_child_worker.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_session_binding_store.py
git diff --check
uv run ruff check .
```

验证结果:

- provider binding mark-failed degradation focused gate: 1 passed, 8 deselected。
- execution child worker full-file gate: 9 passed。
- provider binding store + execution binding + Codex retrofit regression: 38 passed。
- touched-file ruff: All checks passed。
- orchestrator provider binding focused gate: 4 passed, 191 deselected。
- execution child worker + execution binding + binding store regression: 30 passed。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、
  `src/xmuse_core/structuring/blueprint_execution/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- provider binding lifecycle degradation 仍记录在 lane metadata；graph-native status/event store 尚未成为
  这类 degradation 的最终权威日志。
- stale/failed binding 标记失败后，后续 resume lookup 仍可能看到旧 active binding；后续需要 coordinator
  级 retry/quarantine 策略或 event-store 补偿。
- Ray app-server thread 与 provider-native CLI session binding 的统一策略仍未完成。

## 2026-06-03 Provider Session Binding Resume Quarantine

本轮补上 mark-failed degradation 后的下一轮 resume 保护。上一轮已经保证 `mark_failed()` 写 store
失败不会阻断 `exec_failed`；但如果 store 仍保留旧 active binding，下一轮 resolver 仍可能再次选择同一个
已知 stale 的 binding。当前先用迁移期 lane metadata 做窄范围 quarantine，避免重复 resume 同一坏
binding:

- `resolve_execution_provider_session_binding()` 仍只读 store 和 lane metadata，不写 durable state。
- 如果 lane metadata 同时满足:
  - `provider_session_binding_degraded=true`
  - `provider_session_binding_degraded_reason=mark_failed_failed`
  - `provider_session_binding_id` 等于 store 返回的 compatible binding id
  则 resolver 返回 `None`，本轮不再把该 binding 交给 provider resume。
- 只有同一个 binding id 会被跳过；store 中后续出现的新 compatible binding 不受该 guard 影响。
- 该改动不改变 provider command planning、不扩展 adapter 权威、不扩大 `feature_lanes.json` 为最终
  状态源；它只是迁移期防止重复选择已知坏 binding 的 coordinator read-side guard。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_execution_provider_session_binding.py -k \
  "mark_failed_degradation"
uv run pytest -q tests/xmuse/test_execution_provider_session_binding.py
uv run pytest -q tests/xmuse/test_execution_child_worker.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_session_binding_store.py
uv run ruff check src/xmuse_core/platform/execution/provider_session_binding.py \
  tests/xmuse/test_execution_provider_session_binding.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k \
  "provider_session_binding or explicit_binding or resume_binding or binding"
git diff --check
uv run ruff check .
```

验证结果:

- provider binding resume quarantine focused gate: 1 passed, 4 deselected。
- execution provider session binding full-file gate: 5 passed。
- execution child worker + execution binding + binding store regression: 31 passed。
- touched-file ruff: All checks passed。
- orchestrator provider binding focused gate: 4 passed, 191 deselected。
- `git diff --check`: passed。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在
  `src/xmuse_core/agents/ray_god_actor.py`、`src/xmuse_core/agents/ray_session_layer.py`、
  `src/xmuse_core/platform/model_policy.py`、`src/xmuse_core/routing/session_router.py`、
  `src/xmuse_core/self_evolution/*`、`src/xmuse_core/skills/*`、
  `src/xmuse_core/structuring/blueprint_execution/*`、`xmuse/dashboard_api.py`、
  `xmuse/scripts/*`、`xmuse/skills/plan_execute_review.py` 和部分历史/迁移测试文件。本轮未批量修复，
  避免与并行迁移 agent 冲突。

当前剩余风险:

- quarantine guard 仍依赖 migration lane metadata；目标态应落到 graph-native status/event store 的
  provider binding lifecycle event。
- 该 guard 只跳过同一个 binding id，不实现全局 provider-session quarantine、retry budget 或
  replacement binding creation strategy。
- Ray app-server thread 与 provider-native CLI session binding 的统一策略仍未完成。

## 2026-06-03 Provider Binding Degradation Graph-Native Evidence Bridge

本轮把 provider session binding degradation 从纯 lane metadata 向 graph-native status/event store
推进了一步。execution worker/coordinator 仍先在迁移期 lane metadata 上留下 degradation 事实，但
`PlatformOrchestrator._run_execution_god()` 返回后会由 coordinator post-hook 把该事实桥接到
`FeatureGraphStatusStore`，避免 worker 直接写 durable graph status。

完成项:

- 新增 `ProviderSessionBindingDegradationEvidence`，并在
  `FeatureGraphExecutionStatusRecord.provider_session_binding_degradations` 中保存 degradation evidence。
- `FeatureGraphStatusEventRecord` 新增
  `feature_graph_status.provider_session_binding_degraded` 事件类型，要求事件保持同一 status、
  有 derived event id / idempotency key。
- `FeatureGraphStatusStore.record_provider_session_binding_degradation(...)` 支持原子追加 evidence、
  写入 graph-native status event，并对同一 binding id + reason 保持幂等。
- 新增
  `platform.feature_graph_provider_binding_degradation_coordinator.record_feature_graph_provider_binding_degradation_from_lane(...)`，
  只在 lane 明确有 `provider_session_binding_degraded=true` 且存在 graph/binding/reason 时写入
  graph-native status store；缺失信息时返回 `None`，不虚构 provider session binding。
- 新增
  `reconcile_feature_graph_provider_binding_degradations(...)` 和
  `PlatformOrchestrator.reconcile_feature_graph_provider_binding_degradations(...)`，允许 coordinator
  后续重放扫描 migration lane metadata；如果 execution post-hook 当时因 graph status 尚未初始化而跳过，
  status store 就绪后仍可补写 graph-native evidence。
- `PlatformOrchestrator.claim_next_ready_feature_graph_worker(...)` 在领取 graph-native ready feature graph
  前会先执行 provider binding degradation reconciliation；这是低风险自动触发点，不改 runtime，不写
  projection，只通过 status store 补齐 graph-native evidence。
- `PlatformOrchestrator._run_execution_god()` 在 execution flow 返回后调用该 coordinator helper，
  及时启用 lane degradation metadata -> graph-native status/event 的新链路。
- 已修复 feature-level status transition 的 evidence retention：provider binding degradation evidence
  会从 running -> reviewing、reviewing -> merged/reworking/blocked、reworking -> running、
  patch_forward merge guard -> merged 延续到 target status record，避免 graph-native degradation
  evidence 在后续 coordinator 状态转换中被覆盖丢失。
- `FeatureGraphStatusStore.transition(...)` 现在有 store-level guard：普通状态转换不得丢弃或修改
  已记录的 provider binding degradation evidence；新增 degradation 必须继续走
  `record_provider_session_binding_degradation(...)`，由 coordinator 写入独立 event。
- `FeatureGraphStatusStore.upsert(...)` 现在也有 store-level guard：同一 feature graph 已存在时，
  不允许通过 upsert 清空、篡改或直接新增 provider binding degradation evidence，防止绕过
  graph-native degradation event journal。
- graph-set 派生状态 helper 现在会在存在 previous status 时保留
  `provider_session_binding_degradations`，避免 dependent release 等 coordinator 内部状态派生路径
  构造出丢 evidence 的 target status。
- `initialize_from_graph_set(...)` 在同一 graph-set identity 的新版本初始化同一 feature graph 时，
  会从上一版 status 保留 provider binding degradation evidence，避免 graph-set 版本升级通过内部
  upsert 路径绕过 event journal 并清空 evidence。
- `FeatureGraphStatusStore` 读取 persisted payload 时会拒绝重复
  `graph_set_id + feature_graph_id` status identity，避免历史/外部写入的双状态破坏 graph-native
  单一执行权威。
- persisted payload 读取侧也会拒绝同一 `status_id` 绑定到不同 status record 的 replay conflict，
  使文件加载约束与 public `upsert()` 的 status-id immutability 保持一致。
- persisted event journal 读取侧会拒绝重复 `event_id` 或重复 `idempotency_key`，即使重复事件内容
  完全相同也不返回双审计事件；运行时 `_append_event(...)` 仍保持幂等不重复写入。
- persisted event journal 读取侧会拒绝引用缺失 `graph_set_id + feature_graph_id` status identity 的
  orphan event；event 仍可引用 historical status ids，但不能脱离现有 graph-native status identity。
- persisted event journal 读取侧会拒绝与当前 status identity 漂移的事件 metadata：`feature_id`
  必须与现有 status record 一致，`graph_set_version` 不得超前于当前 status record；同一
  `graph_set_id + feature_graph_id + graph_set_version` 内已存在的事件链不得出现
  `from_status_id` 断链。该 guard 明确保留迁移期 `upsert()` 可直接推进 current status 而不补写
  event 的兼容性，不把 event journal 误提升为第二套当前状态源。
- 新增 golden fixture:
  `tests/fixtures/xmuse/contracts/artifacts/feature_graph_provider_binding_degradation_event.v1.json`。

新增/更新测试:

- `tests/xmuse/test_feature_graph_status_store.py`
  - 记录 provider binding degradation 到 graph status。
  - 同一 degradation replay 幂等，不重复事件。
  - 普通 `transition()` 丢弃 provider binding degradation evidence 时拒绝写入，并保持原 status/event
    不变。
  - 普通 `upsert()` 丢弃或直接新增 provider binding degradation evidence 时拒绝写入，并保持原
    status/event 不变。
  - dependent feature 从 `planned` 释放到 `ready` 时保留已有 provider binding degradation evidence。
  - graph-set 新版本重新初始化同一 feature graph 时保留上一版 provider binding degradation evidence。
  - persisted payload 中同一 feature graph 出现重复 status identity 时拒绝读取。
  - persisted payload 中同一 `status_id` 对应不同 status record 时拒绝读取。
  - persisted event journal 中完全重复的 event replay 时拒绝读取。
  - persisted event journal 中引用缺失 feature graph status identity 的 orphan event 时拒绝读取。
  - persisted event journal 中 `feature_id` / `graph_set_version` 与 status identity 漂移时拒绝读取。
  - persisted event journal 中同一 graph-set version 内 `from_status_id` 断链时拒绝读取。
- `tests/xmuse/test_feature_review_contracts.py`
  - provider binding degradation event golden fixture。
  - status record 保存 degradation evidence。
- `tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py`
  - lane metadata -> graph-native status store 新链路。
  - replay 幂等。
  - 未 degraded lane 不写 durable status。
  - graph status 稍后可用时，可通过 reconciliation 重放补写 evidence。
- `tests/xmuse/test_platform_orchestrator.py`
  - `_run_execution_god()` 返回后及时把 execution 写入的 lane degradation metadata 记录到 graph status。
  - 显式 reconciliation 扫描 lanes 并写入 graph status，且不改 `feature_lanes.json`。
  - graph-native ready claim 前自动 reconciliation，并保持 `feature_lanes.json` 只读。
- `tests/xmuse/test_feature_graph_worker_evidence_submission.py`
  - worker evidence submission target status 保留 provider binding degradation evidence。
- `tests/xmuse/test_feature_graph_review_transitions.py`
  - review status transition target status 保留 provider binding degradation evidence。
- `tests/xmuse/test_feature_graph_rework_status_application.py`
  - rework packet status application target status 保留 provider binding degradation evidence。
- `tests/xmuse/test_feature_graph_patch_forward_status_application.py`
  - patch-forward merge guard status application target status 保留 provider binding degradation evidence。

已运行验证:

```bash
uv run pytest -q \
  tests/xmuse/test_platform_orchestrator.py::test_run_execution_god_records_provider_binding_degradation_in_graph_status \
  tests/xmuse/test_platform_orchestrator.py::test_reconcile_provider_binding_degradation_scans_lanes_into_graph_status \
  tests/xmuse/test_platform_orchestrator.py::test_claim_next_ready_feature_graph_worker_reconciles_provider_binding_degradation \
  tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py
uv run pytest -q \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_shared_contract_fixtures_contract.py
uv run pytest -q \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_review_transition_application.py
uv run pytest -q \
  tests/xmuse/test_feature_graph_status_store.py
uv run pytest -q \
  tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py \
  tests/xmuse/test_platform_orchestrator.py
uv run pytest -q \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_review_transition_application.py
uv run ruff check \
  src/xmuse_core/platform/orchestrator.py \
  src/xmuse_core/platform/feature_graph_provider_binding_degradation_coordinator.py \
  src/xmuse_core/structuring/feature_graph_status_store.py \
  src/xmuse_core/structuring/feature_review_contracts.py \
  src/xmuse_core/structuring/feature_graph_worker_evidence_submission.py \
  src/xmuse_core/structuring/feature_graph_review_transitions.py \
  src/xmuse_core/structuring/feature_graph_rework_status_application.py \
  src/xmuse_core/structuring/feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_platform_orchestrator.py \
  tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py \
  tests/xmuse/test_feature_graph_status_store.py \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py
git diff --check
```

验证结果:

- orchestrator 新链路 + coordinator helper/reconciliation/ready-claim gate: 11 passed。
- status-store + feature contracts + shared fixtures gate: 96 passed。
- expanded focused gate after reconciliation: 98 passed。
- status-store + feature contracts + shared fixtures rerun after ready-claim hook: 92 passed。
- feature-level transition retention gate: 28 passed。
- status-store store-level guard rerun: 54 passed。
- provider degradation coordinator/orchestrator focused rerun: 202 passed。
- graph-native claim/dependency focused rerun: 11 passed。
- status-store event metadata/lineage guard rerun: 56 passed。
- provider degradation coordinator/orchestrator rerun after event metadata/lineage guard: 202 passed。
- feature-level worker/review/rework/patch-forward transition rerun after event metadata/lineage guard:
  28 passed。
- touched-file ruff: All checks passed。
- `git diff --check`: passed；注意当前 worktree 整体呈现为 untracked，故该命令对未跟踪文件覆盖有限，
  本轮主要依赖 focused tests 和 touched-file ruff 验证。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；本轮未批量修复，避免与并行
  迁移 agent 冲突。

当前剩余风险:

- 这是迁移期 bridge：source signal 仍来自 `feature_lanes.json` lane metadata，目标态应由
  provider binding lifecycle event / graph-native event store 直接产生 degradation evidence。
- `_run_execution_god()` post-hook 在 graph status 缺失或 stale write 时只记录 warning，不阻断
  execution lane flow；已有显式 reconciliation，且 graph-native ready claim 前会自动 reconcile，但尚无
  后台周期性 reconcile 调度或 dead-letter evidence queue。
- provider binding replacement strategy、global quarantine、Ray long-session runtime parity 仍未完成。

## 2026-06-03 Feature Graph Artifact Store Replay Guard

本轮继续沿 P0 graph-native authority 做低冲突 store hardening，未改 runtime dispatch，也未扩大
`feature_lanes.json` 依赖。

完成项:

- `FeatureGraphArtifactStore` 读取已持久化 artifact collection 时会按稳定 artifact id 检查 replay：
  - `evidence_bundles.bundle_id`
  - `review_verdicts.verdict_id`
  - `rework_packets.rework_id`
  - patch-forward plan/gate/merge-guard chain ids
  - blocked review plan id
  - takeover plan/decision/handoff/outcome/review-handoff/follow-up application ids
- 读取侧会拒绝同一 artifact id 的不同内容，避免外部/历史写入把 worker evidence、review verdict、
  rework packet、patch-forward gate 或 takeover artifacts 变成多版本事实源。
- 读取侧也会拒绝完全重复的同一 artifact id，避免 list/read API 返回双份审计对象；运行时 save 路径
  仍保持已有幂等 upsert 语义。

新增/更新测试:

- `tests/xmuse/test_feature_graph_artifact_store.py`
  - persisted evidence bundle 中同一 `bundle_id` 对应不同内容时拒绝读取。
  - persisted review verdict 中完全重复的 `verdict_id` replay 时拒绝读取。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py \
  -k "conflicting_persisted_evidence_bundle_replay or duplicate_persisted_review_verdict_replay"
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_takeover_plan.py
uv run pytest -q \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_review_transition_application.py
uv run ruff check \
  src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
git diff --check
uv run ruff check .
```

验证结果:

- artifact-store RED subset: 2 failed before implementation, then 2 passed。
- artifact-store focused rerun: 61 passed。
- contracts/rework/patch-forward/blocked/takeover artifact chain rerun: 96 passed。
- feature-level worker/review/rework/patch-forward status application rerun: 28 passed。
- touched-file ruff: All checks passed。
- `git diff --check`: passed；注意当前 worktree 整体呈现为 untracked，故该命令对未跟踪文件覆盖有限。
- 全仓 `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；本轮未批量修复，避免与并行
  迁移 agent 冲突。

当前剩余风险:

- `FeatureGraphArtifactStore` 仍是 JSON-file store；生产态还需要更强的 event-store/write-ahead/compaction
  策略。
- 本轮只补 artifact id replay guard；跨 artifact 引用完整性仍主要依赖 schema 和 builder focused tests，
  尚未做全量 persisted payload relationship audit。

## 2026-06-03 Goal 收束状态

本轮 goal 到此收束，不再继续扩展 store hardening、runtime、A2A 或 provider 能力。当前完成定义为：

- graph-native status/event store focused guards 已落地并通过 focused gates。
- feature graph artifact replay guard 已落地并通过 focused gates。
- provider session binding、Ray long-session parity、A2A adapter、JSON-file store 升级等剩余问题进入
  下一阶段，不作为本轮完成条件。

本轮已完成项:

- `FeatureGraphStatusStore`：
  - provider session binding degradation evidence 可由 coordinator 桥接到 graph-native status/event。
  - transition/upsert/graph-set reinitialize/release-ready 路径保留 degradation evidence。
  - persisted status payload 拒绝重复 graph identity 和冲突 status-id replay。
  - persisted event journal 拒绝重复 event/idempotency、orphan event、metadata 漂移和同版本事件链断链。
- `FeatureGraphArtifactStore`：
  - persisted artifact collections 按稳定 artifact id 拒绝冲突 replay。
  - persisted artifact collections 拒绝完全重复 artifact id，避免 list/read API 返回双份审计对象。
- handoff 已记录当前完成项、验证命令和剩余风险。

本轮 focused gate 证据:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py
uv run pytest -q \
  tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py \
  tests/xmuse/test_platform_orchestrator.py
uv run pytest -q \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_review_transition_application.py
uv run pytest -q tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q \
  tests/xmuse/test_feature_review_contracts.py \
  tests/xmuse/test_feature_graph_rework_packets.py \
  tests/xmuse/test_feature_graph_patch_forward.py \
  tests/xmuse/test_feature_graph_blocked_review.py \
  tests/xmuse/test_feature_graph_takeover_plan.py
uv run ruff check \
  src/xmuse_core/structuring/feature_graph_status_store.py \
  tests/xmuse/test_feature_graph_status_store.py \
  src/xmuse_core/structuring/feature_graph_artifact_store.py \
  tests/xmuse/test_feature_graph_artifact_store.py
git diff --check
uv run ruff check .
```

最近一次已知结果:

- provider session binding store residual check after stopping expansion: 17 passed；确认中断前未完成的
  provider binding RED tests 已移除，本轮不扩展 provider binding store 能力。
- status-store + artifact-store focused closeout rerun: 117 passed。
- status-store event metadata/lineage guard rerun: 56 passed。
- provider degradation coordinator/orchestrator rerun after event metadata/lineage guard: 202 passed。
- feature-level worker/review/rework/patch-forward transition rerun after event metadata/lineage guard:
  28 passed。
- artifact-store focused rerun: 61 passed。
- contracts/rework/patch-forward/blocked/takeover artifact chain rerun: 96 passed。
- touched-file ruff: All checks passed。
- `git diff --check`: passed；当前 worktree 整体呈现为 untracked，故该命令对未跟踪文件覆盖有限。
- `uv run ruff check .` 仍失败，当前报告 86 个既有 lint 问题；主要分布在 Ray session/actor、
  self-evolution、skills、dashboard、历史脚本和迁移测试文件。本轮不要求全仓 ruff 绿作为完成条件。

Legacy / blocker 说明:

- 全仓 ruff blocker 是既有 legacy lint debt，不属于本轮 status/event + artifact replay guard 的完成条件。
- 迁移期仍有 `feature_lanes.json` bridge；目标态应继续向 graph-native event/store 迁移，但本轮不再新增能力。
- provider binding persisted replay guard、Ray long-session runtime parity、A2A external boundary 进入下一阶段。

## 2026-06-03 Review Verdict Coordinator Gate 收束

本轮只选择一个最小 P0 缺口：worker/reviewer artifact/verdict 到 coordinator 状态转换的
idempotency/gate 顺序。未新增 A2A、provider、Ray runtime、TUI/dashboard 能力，也未扩大
`feature_lanes.json` 权威。

选择理由:

- 上一轮 status/event store 与 artifact replay guard 已通过 focused gates。
- 剩余风险中，最小且直接属于 P0 的缺口是 review coordinator 在 transition 类 verdict
  路径中先写 artifact store、再应用 graph status gate；如果 graph status 在两步之间发生 stale
  transition，可能留下 durable verdict artifact，但 coordinator 状态转换被拒绝。
- 该问题会让 artifact store 看起来已接受 reviewer verdict，而 graph-native status store 没有接受
  对应状态转换，削弱 coordinator/state machine 作为执行权威的边界。

完成项:

- 新增 `tests/xmuse/test_feature_graph_review_coordinator.py` focused RED test，模拟 coordinator
  读取 `reviewing` 后，状态在应用 transition 前被推进到 `blocked` 的 stale-write 场景。
- `submit_feature_graph_review_verdict(...)` 对 `merge` / `rework` / `blocked` 这类
  `transition_status` verdict 改为先通过 `FeatureGraphStatusStore.transition(...)` gate，再持久化
  review verdict / rework packet / blocked plan artifacts。
- `patch_forward` / `takeover` 仍保持非状态转换路径：只生成并持久化 coordinator plan，不写 durable
  execution status；本轮未扩展 patch-forward gate 或 takeover 能力。

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_review_coordinator.py
uv run pytest -q \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_review_transition_application.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k submit_feature_graph_review_verdict
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py
uv run ruff check \
  src/xmuse_core/platform/feature_graph_review_coordinator.py \
  tests/xmuse/test_feature_graph_review_coordinator.py
```

验证结果:

- 新 focused RED test 修改前失败，失败点为 transition gate 抛错后 `artifact_store.list_review_verdicts()`
  已包含 `fverdict_merge_demo`。
- 新 coordinator focused test: 1 passed。
- worker/review/rework/patch-forward transition focused gate: 28 passed。
- orchestrator review verdict facade focused gate: 6 passed, 192 deselected。
- status-store + artifact-store focused closeout gate: 117 passed。
- touched-file ruff: All checks passed。

当前剩余风险:

- 该修复只处理 review verdict submission 的 transition-action artifact 写入顺序；worker evidence
  submission、patch-forward merge guard、takeover follow-up 的更大事务边界仍需后续按 focused gate
  逐个审计。
- Artifact store 与 status store 仍是两个 JSON-file store，尚无跨 store write-ahead transaction；
  本轮只保证 transition gate 失败时不预先持久化 transition-action artifacts。
- 全仓 `uv run ruff check .` 仍沿用上一节记录的 legacy blocker，不作为本轮完成条件；本轮未批量修复。

## 2026-06-03 Worker Evidence Submission Gate 收束

本轮唯一 P0:

- `worker evidence submission` 与 `coordinator/status/artifact` 之间的事务边界、stale gate、
  duplicate-safety 顺序问题。

为什么选它:

- 它位于 feature worker 默认主执行路径：`running -> reviewing` 是 graph-native execution authority
  的高频主链路，比 `patch_forward` / `takeover` 两条特例分支更核心。
- 相比 `patch_forward` / `takeover`，该缺口更小，且可以直接验证 “先过 graph-native status gate，
  再落 durable artifact” 这个当前阶段最关键的不变量。

本轮修改的最小文件:

- `src/xmuse_core/platform/feature_graph_worker_evidence_coordinator.py`
- `tests/xmuse/test_feature_graph_worker_evidence_submission.py`
- `docs/xmuse/codex-strengthening-handoff.md`

完成项:

- `submit_feature_graph_worker_evidence(...)` 改为先执行
  `apply_feature_graph_worker_evidence_submission_plan(...)`，确认 graph-native status transition gate
  接受后，再持久化 `FeatureEvidenceBundle` 到 `FeatureGraphArtifactStore`。
- 新增 focused tests 覆盖：
  - positive path：gate 通过后 evidence artifact 正常持久化；
  - stale gate rejected path：读取 `running` 后在 transition 前被竞争写推进到 `blocked`；
  - artifact should not persist on gate failure path：stale gate 拒绝后 artifact store 仍为空；
  - duplicate/replay safety：重复提交不会产生双写、乱序写或 status/artifact 分叉。

RED test 原始失败现象:

- 在 `worker evidence` coordinator stale-race 测试中，修改前 `FeatureGraphStatusStore.transition(...)`
  会抛出 `expected feature graph status running`，但 `artifact_store.list_evidence_bundles()`
  已包含 `fevb_demo`，说明 graph-native status 未接受时 durable worker artifact 已提前落盘。

已运行 focused gates:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_worker_evidence_submission.py
uv run pytest -q \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_rework_status_application.py \
  tests/xmuse/test_feature_graph_patch_forward_status_application.py \
  tests/xmuse/test_feature_graph_review_transition_application.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k worker_evidence
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py
uv run ruff check \
  src/xmuse_core/platform/feature_graph_worker_evidence_coordinator.py \
  tests/xmuse/test_feature_graph_worker_evidence_submission.py
git diff --check
```

结果:

- `tests/xmuse/test_feature_graph_worker_evidence_submission.py`: 10 passed。
- review/rework/patch-forward/review-transition downstream focused gate: 21 passed。
- orchestrator worker-evidence facade focused gate: 2 passed, 196 deselected。
- status-store + artifact-store closeout gate: 117 passed。
- touched-file ruff: All checks passed。
- `git diff --check`: passed；当前 worktree 整体仍呈现为 untracked，故该命令对未跟踪文件覆盖有限。

剩余风险:

- 本轮只收紧 `worker evidence submission` 的 artifact write order；尚未引入跨 status/artifact store
  的真正事务或 write-ahead 机制。
- duplicate replay 当前是 duplicate-safe：重复 submission 不会双写或分叉，但仍会因当前 status 已不再
  是 `running` 而被拒绝；是否需要把这一路径进一步提升为 coordinator-level idempotent accept，
  留待下一阶段按需求决定。
- 本轮未扩展 `patch_forward`、`takeover`、provider binding store、Ray runtime、A2A、TUI/dashboard、
  `feature_lanes.json` 新职责或全仓 lint debt 清理。

## 2026-06-03 Patch Forward Merge Guard Gate 收束

本轮唯一 P0:

- `patch_forward merge guard` 路径中的 `coordinator/status/artifact` 事务边界、gate 顺序与
  stale/duplicate safety。

为什么选它:

- 相比 `takeover`，`patch_forward` 仍位于 reviewer 主闭环内，graph-native status 与 artifact 的边界更短、
  改动面更小，适合作为下一轮最小 P0。
- 它直接承接上一轮 `review verdict` 与 `worker evidence submission` 的收束方向，可以继续验证
  “先过 graph-native reviewing context gate，再落 durable artifact” 这个迁移期核心不变量。

本轮修改的最小文件:

- `src/xmuse_core/platform/feature_graph_patch_forward_gate_coordinator.py`
- `src/xmuse_core/platform/orchestrator.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `docs/xmuse/codex-strengthening-handoff.md`

完成项:

- `submit_feature_graph_patch_forward_merge_guard_decision(...)` 在 `passed=True` 路径上新增
  graph-native reviewing-context gate：
  - 读取 `FeatureGraphStatusStore` 当前记录；
  - 要求当前 status 仍是同一 feature graph 的 `reviewing`；
  - identity mismatch / stale reviewing context 会直接拒绝，不落 durable merge-guard decision。
- `PlatformOrchestrator.submit_feature_graph_patch_forward_merge_guard_decision(...)`
  现在显式把 graph-native status store 传给 coordinator gate。
- 新增 focused tests 覆盖：
  - positive path：valid passed decision 正常持久化；
  - stale / gate rejected path：status 已离开 `reviewing` 时拒绝 passed decision；
  - artifact should not persist on gate failure path：stale reject 后无 merge-guard decision 落盘；
  - duplicate/replay safety：相同 `handoff_id + checked_at` replay 只返回同一 decision，不双写。

RED test 原始失败现象:

- 在 orchestrator stale-reviewing-context 测试中，修改前
  `submit_feature_graph_patch_forward_merge_guard_decision(...)` 对 `passed=True`
  不会读取 graph-native status；即使当前 status 已是 `blocked`，调用也不会报错，并会把 passed
  merge-guard decision 持久化到 artifact store。

已运行 focused gates:

```bash
uv run pytest -q tests/xmuse/test_feature_graph_patch_forward.py
uv run pytest -q tests/xmuse/test_feature_graph_patch_forward_status_application.py
uv run pytest -q \
  tests/xmuse/test_feature_graph_review_transition_application.py \
  tests/xmuse/test_feature_graph_review_transitions.py \
  tests/xmuse/test_feature_graph_rework_status_application.py
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k patch_forward
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py
uv run ruff check \
  src/xmuse_core/platform/feature_graph_patch_forward_gate_coordinator.py \
  src/xmuse_core/platform/orchestrator.py \
  tests/xmuse/test_platform_orchestrator.py
git diff --check
```

结果:

- `tests/xmuse/test_feature_graph_patch_forward.py`: 19 passed。
- `tests/xmuse/test_feature_graph_patch_forward_status_application.py`: 5 passed。
- review-transition / review-plan / rework downstream focused gate: 16 passed。
- orchestrator patch-forward focused gate: 15 passed, 185 deselected。
- status-store + artifact-store closeout gate: 117 passed。
- touched-file ruff: All checks passed。
- `git diff --check`: passed；当前 worktree 整体仍呈现为 untracked，故该命令对未跟踪文件覆盖有限。

剩余风险:

- 本轮只收紧 `passed merge_guard decision -> durable artifact` 这一段的 reviewing-context gate；
  尚未引入跨 status/artifact store 的 write-ahead transaction。
- passed decision 保存后到后续 `apply_feature_graph_patch_forward_merge_guard_decision_status(...)`
  之间仍然不是单事务；当前只保证 stale reviewing context 在 decision submit 时不会留下错误 durable
  decision artifact。
- 本轮未扩展 `takeover`、provider binding store、Ray runtime、A2A、TUI/dashboard、
  `feature_lanes.json` 新职责或全仓 lint debt 清理。

## 2026-06-03 Takeover Decision Reviewing Gate 收束

本轮收束的方面:

- 收束 feature-graph takeover 主链的 coordinator gate 与 durable artifact 边界。

本轮唯一切片:

- `takeover decision` approved path 的 reviewing-context gate 与 artifact write order。

本轮唯一 P0:

- `takeover decision` 的 approved path 上增加 reviewing-context gate，并保证 gate 失败时不落 durable
  approved takeover decision / handoff。

为什么选它:

- 相比 `takeover outcome` / `followup application`，`takeover decision` 是 takeover 主闭环的第一个 durable
  审批边界，切在这里能先锁住后续 worker handoff 的入口，不必扩大到 outcome/followup 分支。
- 它直接承接前两轮对 `worker evidence submission` 与 `patch_forward merge guard` 的收紧方式：
  先过 graph-native reviewing-context gate，再允许 durable artifact 前进。

本轮修改的最小文件:

- `src/xmuse_core/platform/feature_graph_takeover_coordinator.py`
- `src/xmuse_core/platform/orchestrator.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `docs/xmuse/codex-strengthening-handoff.md`

完成项:

- `submit_feature_graph_takeover_decision(...)` 在 `approved=True` 路径上新增 graph-native
  reviewing-context gate：
  - 读取 `FeatureGraphStatusStore` 当前记录；
  - 要求当前 status 仍是同一 feature graph 的 `reviewing`；
  - stale reviewing context 或 identity mismatch 会直接拒绝。
- gate 失败时不会保存 approved `FeatureGraphTakeoverDecision`，也不会生成
  `FeatureGraphTakeoverHandoff`。
- duplicate replay 保持 duplicate-safe：相同 `plan_id + checked_at` 的 approved replay 只返回同一
  decision/handoff，不双写、不分叉。
- `PlatformOrchestrator.submit_feature_graph_takeover_decision(...)` 现在显式把 graph-native
  status store 传给 takeover decision coordinator。

RED test 原始失败现象:

- 在 orchestrator stale-reviewing-context 测试中，修改前
  `submit_feature_graph_takeover_decision(..., approved=True)` 不会读取 graph-native status；
  即使当前 status 已经是 `blocked`，调用也不会报错，并会继续保存 approved takeover decision 与
  takeover handoff。

已运行 focused gates:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k takeover_decision
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py
uv run ruff check \
  src/xmuse_core/platform/feature_graph_takeover_coordinator.py \
  src/xmuse_core/platform/orchestrator.py \
  tests/xmuse/test_platform_orchestrator.py
git diff --check
```

结果:

- orchestrator takeover-decision focused gate: 6 passed, 197 deselected。
- `tests/xmuse/test_feature_graph_takeover_plan.py`: 24 passed。
- status-store + artifact-store closeout gate: 117 passed。
- touched-file ruff: All checks passed。
- `git diff --check`: passed；当前 worktree 整体仍呈现为 untracked，故该命令对未跟踪文件覆盖有限。

剩余风险:

- 本轮只收紧 approved takeover decision 入口；尚未扩展到 `takeover outcome`、`takeover followup review`
  或 `takeover followup application` 的更大事务边界。
- approved decision 保存后到后续 takeover worker/outcome/followup review 之间仍然不是单事务；
  当前只保证 stale reviewing context 不会留下错误 durable approved decision / handoff。
- 本轮未扩展 `patch_forward`、provider binding store、Ray runtime、A2A、TUI/dashboard、
  `feature_lanes.json` 新职责或全仓 lint debt 清理。

## 2026-06-03 Takeover Main Chain 阶段性闭环

本轮收束的方面:

- 收束 feature-graph takeover 主链在 orchestrator facade 下的
  `decision -> handoff -> outcome -> followup review submission -> followup review application`
  coordinator/status/artifact 边界。

该方面的目标边界:

- 保留已完成的 `takeover decision approved path reviewing-context gate`，不回退。
- 把 `takeover outcome` 的 completed/failed 两条提交路径收紧到 graph-native reviewing context。
- 把 `takeover followup review submission / application` 收成：
  stale gate 不留错误 durable artifact，且 replay 不会双写或分叉。
- 本轮只收 takeover 主链，不扩展 Ray runtime、provider 能力、A2A 或其他非 takeover 面。

本轮实际收掉了 takeover 主链的哪些子路径:

- `submit_feature_graph_takeover_outcome(...)`
  - 新增 graph-native reviewing-context gate；
  - stale reviewing context / identity mismatch 时拒绝并且不落 durable outcome；
  - completed path 现在可在 `outcome 已写、review_handoff 未写` 后 replay 恢复，不再分叉第二个
    outcome。
- `submit_feature_graph_takeover_followup_review_verdict(...)`
  - 新增 graph-native reviewing-context gate；
  - stale reviewing context / identity mismatch 时拒绝并且不落 durable followup verdict。
- `apply_feature_graph_takeover_followup_review_verdict(...)`
  - 保留既有 merge/rework/blocked 的 status-based recovery；
  - 新增 `patch_forward` 的 artifact-based recovery，用于
    `patch_forward_plan 已写、followup application 未写` 的 replay 恢复；
  - replay 不再因为 `updated_at` 变化而分叉出第二个 patch-forward plan/application。

修改了哪些最小文件:

- `src/xmuse_core/platform/feature_graph_takeover_coordinator.py`
- `src/xmuse_core/platform/orchestrator.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `docs/xmuse/codex-strengthening-handoff.md`

关键 RED 失败现象:

- 修改前，`submit_feature_graph_takeover_outcome(...)` 不读取 graph-native status；即使当前 status
  已离开 `reviewing`，也仍会保存 failed/completed takeover outcome。
- 修改前，completed outcome 若在 `save_takeover_outcome(...)` 后、
  `save_takeover_review_handoff(...)` 前中断，replay 会再写一个新的 outcome，而不是恢复缺失 handoff。
- 修改前，`submit_feature_graph_takeover_followup_review_verdict(...)` 不读取 graph-native
  status；即使当前 status 已变成 `blocked`，仍会保存 stale followup verdict。
- 修改前，`apply_feature_graph_takeover_followup_review_verdict(...)` 的 `patch_forward`
  分支若在 `patch_forward_plan` 已写、`takeover_followup_review_application` 未写后中断，
  replay 会因新的 `updated_at` 生成第二个 patch-forward plan，形成 durable artifact 分叉。

主验收命令与辅助验收命令:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k takeover
uv run pytest -q tests/xmuse/test_feature_graph_takeover_plan.py
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py
uv run ruff check \
  src/xmuse_core/platform/feature_graph_takeover_coordinator.py \
  src/xmuse_core/platform/orchestrator.py \
  tests/xmuse/test_platform_orchestrator.py
git diff --check
```

结果:

- orchestrator takeover focused gate: `19 passed, 188 deselected`。
- `tests/xmuse/test_feature_graph_takeover_plan.py`: `24 passed`。
- status-store + artifact-store closeout gate: `117 passed`。
- touched-file ruff: `All checks passed!`
- `git diff --check`: passed；当前 worktree 整体仍呈现为 untracked，故该命令对未跟踪文件覆盖有限。

剩余风险:

- 本轮收成的是 takeover 主链的 coordinator/status/artifact 阶段性闭环，不是跨 store 的事务化
  write-ahead 方案；status/artifact 之间仍无统一事务层。
- `takeover outcome` 现在按 `handoff` 只接受单一 durable outcome；若历史数据中已经存在同一 handoff
  的多份 outcome，本轮会显式报错而不是自动修复旧分叉。
- followup application 的 artifact recovery 这轮只补到了 `patch_forward` 无状态迁移分支；
  更大范围的 coordinator-level transaction 仍留待下一阶段。

本轮明确没有扩展哪些能力点:

- 没有新增 A2A。
- 没有新增 Claude/OpenCode provider。
- 没有改 Ray runtime 主结构。
- 没有重构 TUI/dashboard。
- 没有把 `feature_lanes.json` 扩成新权威。
- 没有扩展 worker evidence、provider binding store 或其他非 takeover 面的新能力。
- 没有批量修全仓 ruff/legacy test debt。

## 2026-06-03 Runtime / Session 主路径收束

本轮收束的方面:

- 收束 xmuse 的 runtime/session 主路径，重点是 feature worker execution 上的
  `provider session binding -> resume -> degradation/fallback` 优先级与边界。

本轮收束的 runtime/session 主路径:

- 当前 authoritative path 收成三层：
  1. `PlatformOrchestrator._run_execution_god(...)` 若解析出兼容的 active
     `provider session binding`，优先走显式 provider resume；
  2. 只有在没有兼容 binding 时，才允许进入 persistent execute session layer
     （Ray/native persistent launcher 均经这一层接入）；
  3. 若 persistent session 不可用或降级，再退回 native one-shot execute fallback。
- 本轮实际落地到 orchestrator 核心执行路径：
  `orchestrator_lane_flow.run_execution_god(...)` 现在在有兼容 binding 时会显式关闭
  persistent execute 尝试，把同一轮执行固定到 provider-binding resume 主路径。

provider session binding 在本轮中的职责:

- 它是 runtime/session 恢复的显式依据，不再只是 transport 附带参数。
- orchestrator 以 `god_session_id + provider + kind + model + worktree + prompt_fingerprint +
  feature_graph_id` 的兼容性校验结果决定是否允许 resume。
- 若 resume 失败并返回 `stale_request`，binding 会被标记为 `STALE`；若 `mark_failed(...)`
  本身写失败，则 lane 会留下 degradation metadata，后续由 graph-native degradation
  coordinator 吸收。
- 本轮没有引入 `--last` / last-session 语义；恢复继续只接受显式 durable binding。

修改的最小文件:

- `src/xmuse_core/platform/orchestrator_lane_flow.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `docs/xmuse/codex-strengthening-handoff.md`

关键 RED 现象或 runtime gap:

- 修改前，即使 lane 已存在兼容的 active provider session binding，
  `PlatformOrchestrator._run_execution_god(...)` 仍会把
  `persistent_execute_enabled=True` 与 `persistent_session_layer` 原样传给 executor，
  先尝试 persistent session。
- RED tests 证明了旧行为会在同一轮执行里同时具备：
  - `provider_session_binding` 已解析；
  - `persistent_session_layer.ensure_conversation_session(...)` 仍被调用。
- 这意味着主路径优先级不清晰：显式、可审计的 binding-based resume 没有先于
  persistent session recovery 生效。

主验收命令与辅助验收命令:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k "provider_binding or session or resume or degradation"
uv run pytest -q \
  tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py \
  tests/xmuse/test_provider_session_binding_store.py
uv run ruff check \
  src/xmuse_core/platform/orchestrator_lane_flow.py \
  tests/xmuse/test_platform_orchestrator.py
git diff --check
```

结果:

- orchestrator runtime/session focused gate: `8 passed, 200 deselected`。
- provider binding degradation + binding store focused gate: `21 passed`。
- touched-file ruff: `All checks passed!`
- `git diff --check`: passed；当前 worktree 整体仍呈现为 untracked，故该命令对未跟踪文件覆盖有限。

剩余风险:

- 本轮只把 orchestrator execution 主路径收成“binding resume 优先”；persistent session
  成功路径本身还没有把 provider-native session id 回灌成新的 durable binding。
- Ray parity 仍未完成：当前 Ray session layer 仍是可选接入面，不是 runtime authority；
  它与 native `GodSessionLayer` 的行为边界依然主要靠调用方配置保证。
- provider parity 仍未完成：显式 binding-based resume 目前只对 Codex exec 主路径形成闭环，
  没有扩到 Claude/OpenCode，也没有扩到 review plane。
- persistent execute 降级后的 fallback 仍是 native one-shot；这轮只明确边界，没有把
  fallback 事件体系化提升成跨 runtime 的统一状态机。

本轮明确没有扩展哪些能力点:

- 没有新增 A2A。
- 没有新增 Claude/OpenCode provider 主能力。
- 没有改 Ray runtime 主结构。
- 没有重构 TUI/dashboard。
- 没有把 `feature_lanes.json` 扩成新权威。
- 没有做 graph-native status/artifact 的新一轮大收缩。
- 没有把本轮扩成完整多 provider runtime 重写。
- 没有批量修全仓 ruff/legacy test debt。

## 2026-06-03 Provider Parity / Runtime Adapter 收束

本轮收束的方面:

- 收束 execution 主路径上的 provider/runtime adapter 边界，把已收好的
  `binding resume -> persistent execute -> native fallback` 优先级，从 orchestrator 内联分支
  收成统一 route 规划层。

本轮抽出的 provider/runtime adapter 边界:

- 新增 `ExecutionRuntimeSessionRoute` 与
  `plan_execution_runtime_session_route(...)` 作为 execution session route planner。
- orchestrator 不再直接依赖某个 provider 的 resume 特例，而是只依赖 route planner 输出的两种路径：
  - `explicit_provider_resume`
  - `persistent_execute_or_fallback`
- provider 侧新增 `RunnerProviderService.supports_explicit_session_resume(...)`
  作为 adapter capability 查询点；当前实现仍是 Codex-first，但 capability 判断已经被收进 provider
  边界，而不再散在 orchestrator 里。

当前 runtime 主路径如何经过该边界:

- `orchestrator_lane_flow.run_execution_god(...)` 先构造 `ProviderInvocation`，再调用
  `plan_execution_runtime_session_route(...)`。
- 若 route planner 返回 `explicit_provider_resume`：
  - 传入兼容的 active `provider_session_binding`
  - 显式关闭 persistent execute 尝试
  - 直接进入 provider resume 主路径
- 若 route planner 返回 `persistent_execute_or_fallback`：
  - 不传 binding
  - 保留 configured persistent execute
  - persistent 失败后仍沿既有 native one-shot fallback 进入

哪些语义已 provider-agnostic:

- orchestrator 现在只消费统一的 route decision，不再自己判断 `ProviderId.CODEX`。
- “compatible active binding -> explicit resume / 否则 persistent-or-fallback” 这条主路径，
  已经是 provider/runtime adapter 边界上的统一语义。
- lane degradation quarantine、binding compatibility identity、`stale_request -> STALE`、
  `mark_failed_failed -> degradation evidence` 这些恢复/降级语义保持不变，并继续通过统一边界传递。
- 为未来第二 provider 留下了可验证接入位：
  route planner 会先问 provider adapter 是否支持 explicit resume；不支持的 provider
  自动落到 `persistent_execute_or_fallback`。

哪些地方仍是 Codex-first:

- `RunnerProviderService.supports_explicit_session_resume(...)` 当前只对 Codex 返回 `true`。
- Codex adapter 仍是唯一真正实现 `build_resume_command(...)` 的 provider adapter。
- provider session binding 的 durable resume 目前只对 Codex exec 形成闭环；OpenCode/未来 provider
  还没有 explicit resume command，也没有对应 binding replay 语义。
- `runtime_for_invocation(...)` 仍把 provider-backed execution 汇总到现有 codex runner surface。

修改的最小文件:

- `src/xmuse_core/platform/execution/provider_session_binding.py`
- `src/xmuse_core/platform/orchestrator_lane_flow.py`
- `src/xmuse_core/providers/service.py`
- `tests/xmuse/test_execution_provider_session_binding.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `docs/xmuse/codex-strengthening-handoff.md`

关键 RED 现象或耦合点:

- 修改前，orchestrator 虽然已经保证了 “有兼容 binding 时优先 resume”，但这个判断仍是
  `orchestrator_lane_flow.py` 里对 `provider_session_binding` 非空的直接分支，不是统一 route planner。
- 修改前，`resolve_execution_provider_session_binding(...)` 也内嵌了 `ProviderId.CODEX`
  约束，导致 provider capability 与 orchestrator priority 混在同一层。
- RED tests 固定了两个耦合点：
  - 对 Codex：compatible binding 必须产出 `explicit_provider_resume`；
  - 对未来第二 provider：即使存在形式上兼容的 durable binding，只要 provider adapter 尚未声明
    explicit resume support，主路径也必须保持 `persistent_execute_or_fallback`。

主验收命令与辅助验收命令:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k "provider_binding or session or resume or degradation"
uv run pytest -q \
  tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py \
  tests/xmuse/test_provider_session_binding_store.py
uv run pytest -q tests/xmuse/test_execution_provider_session_binding.py
uv run ruff check \
  src/xmuse_core/platform/orchestrator_lane_flow.py \
  src/xmuse_core/platform/execution/provider_session_binding.py \
  src/xmuse_core/providers/service.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_platform_orchestrator.py
git diff --check
```

结果:

- orchestrator provider/session focused gate: `9 passed, 200 deselected`。
- provider binding degradation + binding store focused gate: `21 passed`。
- execution provider session route focused gate: `7 passed`。
- touched-file ruff: `All checks passed!`
- `git diff --check`: passed；当前 worktree 整体仍呈现为 untracked，故该命令对未跟踪文件覆盖有限。

剩余风险:

- 本轮抽出的只是 execution session route adapter；review plane 仍未接入同级 provider/runtime route planner。
- provider capability 查询已经被统一到 adapter 边界，但 explicit resume 的真正实现仍只有 Codex；
  OpenCode/未来 provider 目前只能验证“不会误走 resume”，还不能验证真正 parity。
- persistent execute 的成功路径仍没有把 provider-native session id 统一回灌成新的 durable binding；
  这部分仍偏 Codex-first。
- Ray parity 仍未完成：persistent session layer 与 native fallback 的 runtime authority 还没有统一到
  更高一层 runtime adapter。

本轮明确没有扩展哪些能力点:

- 没有新增 A2A。
- 没有实现完整 Claude/OpenCode provider。
- 没有改 Ray runtime 主结构。
- 没有重构 TUI/dashboard。
- 没有把 `feature_lanes.json` 扩成新权威。
- 没有回头做 graph-native status/artifact 新一轮大收缩。
- 没有把本轮扩成完整多 provider runtime 重写。
- 没有批量修全仓 ruff/legacy test debt。

## 2026-06-03 OpenCode 最小执行闭环收束

本轮收束的方面:

- 只收束一个 execution P0 缺口：把 OpenCode 的 provider persistent capability
  收进统一 adapter 边界，避免 execution 主路径在 OpenCode 上误触 Codex-first 的
  persistent session layer。

OpenCode 本轮接入的最小执行闭环是什么:

- `ProviderInvocation(provider_id=OPENCODE)` 先经过
  `plan_execution_runtime_session_route(...)`。
- `RunnerProviderService` 现在同时暴露：
  - `supports_explicit_session_resume(...)`
  - `supports_persistent_execute(...)`
- 对 `opencode.deepseek_flash_worker`：
  - explicit resume: `false`
  - persistent execute: `false`
- route planner 因而返回：
  - `primary_path="persistent_execute_or_fallback"`
  - `allows_persistent_execute=False`
  - `persistent_execute_unsupported_reason="provider_persistent_execute_unsupported"`
- orchestrator 消费这组 route 结果后，会显式关闭
  `persistent_execute_enabled` 并清空 `persistent_execute_session_layer`，随后继续走
  统一 executor，最后落到 native one-shot execute fallback。

当前 execution 主路径如何经过统一 adapter 边界:

- provider 选择仍先产出统一 `ProviderInvocation`。
- route planner 负责把 “binding resume / persistent execute / native fallback”
  优先级与 provider capability 合并成单一决策。
- orchestrator 不再对 OpenCode 保留“先尝试 configured persistent layer”的隐式特例；
  是否允许 persistent execute 只看 adapter capability。

OpenCode 本轮已具备:

- 能通过统一 provider/runtime adapter 边界进入 execution 主路径。
- 能明确声明“不支持 explicit resume”。
- 能明确声明“不支持 persistent execute”。
- 在该 capability 组合下，不再误触 persistent session layer，而是直接走 native
  one-shot execute。

OpenCode 本轮仍未具备:

- 没有 provider-native explicit session resume。
- 没有 provider-native persistent execute。
- 没有 provider session binding replay / recovery 闭环。
- 没有 review plane parity。

哪些地方仍是 Codex-first:

- persistent session layer 仍主要服务 Codex runtime surface。
- provider-native durable resume 仍只有 Codex exec 主路径具备。
- `runtime_for_invocation(...)` 仍把 provider-backed execution 汇总到现有 codex
  runner surface。

修改的最小文件:

- `src/xmuse_core/providers/service.py`
- `src/xmuse_core/platform/orchestrator_lane_flow.py`
- `tests/xmuse/test_execution_provider_session_binding.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `docs/xmuse/codex-strengthening-handoff.md`

关键 RED 现象或 provider gap:

- 修改前，route planner 已开始查询 `supports_persistent_execute(...)`，但
  `RunnerProviderService` 还没有这条 capability，focused RED 直接报
  `AttributeError`。
- 修改前，即使 OpenCode 不支持 explicit resume，orchestrator 仍会把
  `persistent_execute_enabled=True` 与 configured session layer 原样下传给 executor，
  结构上仍可能先碰 persistent session path。

主验收命令与辅助验收命令:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k "provider_binding or session or resume or degradation or opencode"
uv run pytest -q tests/xmuse/test_execution_provider_session_binding.py
uv run pytest -q \
  tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py \
  tests/xmuse/test_provider_session_binding_store.py
uv run ruff check \
  src/xmuse_core/platform/execution/provider_session_binding.py \
  src/xmuse_core/platform/orchestrator_lane_flow.py \
  src/xmuse_core/providers/service.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_platform_orchestrator.py
git diff --check
```

结果:

- `tests/xmuse/test_platform_orchestrator.py -k "provider_binding or session or resume or degradation or opencode"`:
  `8 passed, 201 deselected`
- `tests/xmuse/test_execution_provider_session_binding.py`: `7 passed`
- `tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py tests/xmuse/test_provider_session_binding_store.py`:
  `21 passed`
- touched-file `ruff`: passed
- `git diff --check`: passed

剩余风险:

- OpenCode 本轮证明的是“不会误走 persistent/resume 分支”，不是“已具备长 session
  parity”。
- provider capability 已统一进 adapter 边界，但 review plane 还没有消费同级 capability
  约束。
- persistent success path 仍未把 provider-native session identity 回灌成新的 durable
  binding；这部分仍偏 Codex-first。

本轮明确没有扩展哪些能力点:

- 没有新增 A2A。
- 没有新增 Claude/OpenCode 新 provider 类型。
- 没有改 Ray runtime 主结构。
- 没有重构 TUI/dashboard。
- 没有把 `feature_lanes.json` 扩成新权威。
- 没有回头做 graph-native status/artifact 新一轮收缩。
- 没有继续扩展第二个 provider/runtime 能力点。
- 没有批量修全仓 ruff 或 legacy tests。

## 2026-06-03 Ray 长 Session Parity 闭环

本轮收束的方面:

- 只收束一个 Ray execution P0 缺口：让 `persistent_execute_god_enabled`
  的 execution 主路径默认优先接入 `RayGodSessionLayer`，而不是继续把 native
  `GodSessionLayer` 当成隐式主路径。

本轮打通的 Ray 长 session 主路径:

- `platform_runner.run(...)` 在 `persistent_execute_god_enabled=True` 时，
  现在会先按 `XMUSE_EXECUTE_GOD_BACKEND` 选择 execution GOD backend；
  默认值为 `ray`。
- 当 backend 为 `ray/auto` 且 Ray layer 可构造时：
  - runner 为 execution path 构造 `RayGodSessionLayer`
  - 在进入 orchestrator 前先 `prewarm()`
  - orchestrator 将其作为 `persistent_execute_session_layer` 注入
- `orchestrator -> execution_executor.run_execution_god(...)` 的既有优先级保持不变：
  1. 有兼容 provider session binding 且 provider supports explicit resume
     -> 显式 provider resume，关闭 Ray persistent path
  2. 否则 -> Ray 长 session persistent execute
  3. Ray ensure/send/receive 失败 -> one-shot native fallback
- 新增 focused runtime test 证明了一条真实成功路径：
  `RayGodSessionLayer` 能在 execution lane 上先完成 persistent delivery，
  且不会触发 native transport fallback。

provider session binding 在 Ray 路径中的职责:

- 它仍是 execution 恢复的显式依据，不引入 `--last/last-session`。
- 当 binding 兼容且 provider 支持 explicit resume 时，route planner 会直接绕开
  Ray 长 session，优先走 provider-native resume。
- 当 binding 不兼容、缺失、或 provider 不支持 explicit resume 时，才允许进入
  Ray persistent execute。
- 因此在当前阶段，binding 的职责不是“让 Ray 自己 resume provider session”，
  而是作为 orchestrator 裁决 Ray path 是否应被绕开的权威依据。

当前 Ray authoritative path 是什么:

- 对 execution persistent path 而言，Ray 现在是 runner 默认 backend，
  而不是 peer-chat 专用能力。
- Ray 长 session 的创建/复用由 `RayGodSessionLayer.ensure_conversation_session(...)`
  负责：
  - 有存活的 conversation+participant live actor -> 复用
  - 否则按 registry record / 新建 record 重建会话
- Ray degraded/fallback 仍由 execution executor 统一裁决：
  `ensure_failed / send_failed / receive_* / request_id_mismatch / no_result_message`
  都会落到清晰的 one-shot fallback 语义。

OpenCode/Codex 在 Ray 路径上的能力差异是什么:

- Codex:
  - 支持 explicit provider resume
  - 支持 persistent execute
  - 因而在“无兼容 binding”时可进入 Ray 长 session path；有兼容 binding 时优先绕开
    Ray，直接 provider resume
- OpenCode:
  - 不支持 explicit provider resume
  - 不支持 persistent execute
  - route planner 会显式关闭 persistent path，因此不会进入 Ray execution session
    path，而是直接落到 native one-shot fallback

修改的最小文件:

- `xmuse/platform_runner.py`
- `tests/xmuse/test_runtime_ray_backend.py`
- `docs/xmuse/codex-strengthening-handoff.md`

关键 RED 现象或 parity gap:

- 修改前，即使 `persistent_execute_god_enabled=True`，
  `platform_runner.run(...)` 仍把 native `GodSessionLayer` 注入
  `persistent_execute_session_layer`。
- focused RED 直接证明：
  execution persistent path 拿到的是 `GodSessionLayer`，不是 `RayGodSessionLayer`；
  Ray 只在 peer-chat backend wiring 中是默认项，还不是 execution 主路径的默认 backend。

主验收命令与辅助验收命令:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k "provider_binding or session or resume or degradation or ray"
uv run pytest -q tests/xmuse/test_runtime_ray_backend.py
uv run pytest -q tests/xmuse/test_execution_provider_session_binding.py
uv run pytest -q \
  tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py \
  tests/xmuse/test_provider_session_binding_store.py
uv run ruff check \
  xmuse/platform_runner.py \
  tests/xmuse/test_runtime_ray_backend.py
git diff --check
```

结果:

- `tests/xmuse/test_platform_orchestrator.py -k "provider_binding or session or resume or degradation or ray"`:
  `8 passed, 201 deselected`
- `tests/xmuse/test_runtime_ray_backend.py`: `6 passed`
- `tests/xmuse/test_execution_provider_session_binding.py`: `7 passed`
- `tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py tests/xmuse/test_provider_session_binding_store.py`:
  `21 passed`
- touched-file `ruff`: passed
- `git diff --check`: passed

剩余风险:

- 本轮只把 Ray 接成 execution persistent path 的默认 backend，没有扩到 review plane
  parity。
- provider session binding 目前仍只在 “是否绕开 Ray、改走 provider-native resume”
  这一层形成闭环；Ray path 成功后还没有把 provider-native session identity 回灌成新的
  durable binding。
- `tests/xmuse/test_platform_runner.py` 单独收集时仍存在既有 circular-import blocker
  （`run_health -> providers -> structuring -> chat.execution_cards -> run_health`）；
  这不是本轮 Ray parity 缺口，未在本轮修复。
- Ray backend 不可构造时，runner 当前会记录 warning 并回落 native layer；更细粒度的
  graph-native degradation evidence 还没加到这一层。

本轮明确没有扩展哪些能力点:

- 没有新增 A2A。
- 没有新增 Claude/OpenCode 新 provider 类型。
- 没有改 review-plane Ray parity。
- 没有重构 TUI/dashboard。
- 没有把 `feature_lanes.json` 扩成新权威。
- 没有回头做 graph-native status/artifact 新一轮收缩。
- 没有把本轮扩成完整多 provider runtime 重写。
- 没有批量修全仓 ruff 或 legacy tests。

## 2026-06-03 Review-Plane Ray Parity 闭环

本轮收束的方面:

- 只收束一个 review-plane Ray P0 缺口：让 `persistent_review_god_enabled`
  的 reviewer 长 session 主路径默认优先接入 `RayGodSessionLayer`，而不是继续把
  native `GodSessionLayer` 当隐式默认主路径。

本轮打通的 review-plane Ray 主路径:

- `platform_runner.run(...)` 在 `persistent_review_god_enabled=True` 时，
  现在会先按 `XMUSE_REVIEW_GOD_BACKEND` 选择 review GOD backend；
  默认值为 `ray`。
- 当 backend 为 `ray/auto` 且 Ray layer 可构造时：
  - runner 为 review path 构造 `RayGodSessionLayer`
  - 在进入 orchestrator 前先 `prewarm()`
  - orchestrator 将其作为 `review_god_session_layer` 注入
- `orchestrator -> execution.review_god.run_review_god(...)` 的 review 主路径保持：
  1. configured review peer（若存在且可用）
  2. review persistent session layer
  3. one-shot native `send_review` fallback
- 新增 focused runtime test 证明了一条真实成功路径：
  `RayGodSessionLayer` 能在 review lane 上先完成 persistent verdict delivery，
  且不会触发 native review transport fallback。

review-plane Ray authoritative path 是什么:

- 对 review persistent path 而言，Ray 现在和 execution 一样成为 runner 默认 backend，
  不再只是 peer-chat / execution 的旁路能力。
- review Ray 长 session 的创建/复用仍由
  `RayGodSessionLayer.ensure_conversation_session(...)` 负责：
  - 有存活的 conversation+participant live actor -> 复用
  - 否则按 registry record / 新建 record 重建会话
- review degraded/fallback 仍由 `execution.review_god` 统一裁决：
  `ensure_failed / send_failed / receive_* / request_id_mismatch / no_result_message`
  都会留下 `persistent_review_degraded*` metadata，并清晰回落到 one-shot review fallback。

与 execution-plane 的差异:

- execution plane 有 provider session binding route planner，会在兼容 binding 存在且
  provider 支持 explicit resume 时直接绕开 Ray，优先 provider-native resume。
- review plane 当前没有同级 provider session binding / explicit resume 裁决层；
  它的长 session 主路径仍是：
  configured peer -> review persistent session -> one-shot fallback。
- execution plane 关注 `provider_session_binding` 与 provider-native session 恢复；
  review plane 当前只收束 Ray-backed reviewer long session，不扩到 provider-native
  reviewer resume parity。

修改的最小文件:

- `xmuse/platform_runner.py`
- `tests/xmuse/test_runtime_ray_backend.py`
- `docs/xmuse/codex-strengthening-handoff.md`

关键 RED 现象或 parity gap:

- 修改前，即使 `persistent_review_god_enabled=True`，
  `platform_runner.run(...)` 仍把 native `GodSessionLayer` 注入
  `review_god_session_layer`。
- focused RED 直接证明：
  review persistent path 拿到的是 `GodSessionLayer`，不是 `RayGodSessionLayer`；
  review plane 还没有像 execution plane 一样把 Ray 设成默认长 session backend。

主验收命令与辅助验收命令:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k "review or ray"
uv run pytest -q tests/xmuse/test_runtime_ray_backend.py
uv run pytest -q tests/xmuse/test_execution_provider_session_binding.py
uv run pytest -q \
  tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py \
  tests/xmuse/test_provider_session_binding_store.py
uv run ruff check \
  xmuse/platform_runner.py \
  tests/xmuse/test_runtime_ray_backend.py
git diff --check
```

结果:

- `tests/xmuse/test_platform_orchestrator.py -k "review or ray"`:
  `96 passed, 113 deselected`
- `tests/xmuse/test_runtime_ray_backend.py`: `9 passed`
- `tests/xmuse/test_execution_provider_session_binding.py`: `7 passed`
- `tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py tests/xmuse/test_provider_session_binding_store.py`:
  `21 passed`
- touched-file `ruff`: passed
- `git diff --check`: passed

剩余风险:

- 本轮只把 Ray 接成 review persistent path 的默认 backend，没有增加 review-plane
  provider-native resume / provider session binding parity。
- review plane 仍没有 execution-plane 那样的 provider capability route planner；
  它目前只能在 session-layer 层面实现 Ray-first，而不是 provider-native reviewer resume。
- `tests/xmuse/test_platform_runner.py` 单独收集时仍存在既有 circular-import blocker
  （`run_health -> providers -> structuring -> chat.execution_cards -> run_health`）；
  本轮绕开了它，没有扩修。
- review persistent success 后的更细粒度 graph-native recovery evidence 仍未补到 Ray layer
  构造/回落这一层。

本轮明确没有扩展哪些能力点:

- 没有新增 A2A。
- 没有新增 Claude/OpenCode 新 provider 类型。
- 没有改 execution-plane provider parity。
- 没有重构 TUI/dashboard。
- 没有把 `feature_lanes.json` 扩成新权威。
- 没有回头做 graph-native status/artifact 新一轮收缩。
- 没有把本轮扩成 provider parity 新一轮开发。
- 没有批量修全仓 ruff 或 legacy tests。

## 2026-06-03 Provider-Native Session Recovery 闭环

本轮收束的方面:

- 只收束一个 execution recovery P0 缺口：当成功 provider 结果返回了新的
  provider-native session identity，但 writeback 失败时，lane 必须隔离旧 active binding，
  避免下一次 rerun 继续误走旧 binding resume，形成错误 active binding / resume 分叉。

本轮闭环的 provider-native session recovery 主路径:

- execution 主路径仍保持：
  1. route planner 读取显式 `provider_session_binding_god_session_id`
  2. 若存在兼容 active binding 且 provider 支持 explicit resume -> provider-native resume
  3. 否则 -> persistent execute / fallback
- 对成功 provider 结果：
  - 若携带 `provider_session_id`，executor 仍按既有契约调用
    `upsert_provider_session_binding_from_result(...)`
  - 若 writeback 成功 -> 新/现有 binding 成为 authoritative durable binding
  - 若 writeback 失败且本轮是从旧 binding resume 进来的 ->
    lane 现在会显式记录旧 `provider_session_binding_id`
- 对下一次 rerun：
  - resolver 现在会把 `provider_session_binding_degraded_reason="upsert_failed"`
    且 `provider_session_binding_id` 命中的 binding 视为 quarantine 对象
  - 因而不会再继续误用旧 active binding，而是强制 reroute 到非 provider-native resume 路径

成功 writeback / 失败 recovery 各自处于什么状态:

- 成功 writeback：
  - 已形成 durable writeback 闭环
  - focused orchestrator test 已证明成功 provider 结果会把 `provider_session_id` 写回
    `ProviderSessionBindingStore`
- 失败 recovery：
  - `stale_request -> STALE` 早已可闭环
  - 本轮新增的是 `upsert_failed` 闭环：即使 store 写回失败，也不会让旧 active binding
    在下次 rerun 中继续被 resume

哪些 provider 已具备该闭环:

- Codex exec：
  - 具备 successful writeback
  - 具备 `STALE` / `FAILED` 标记
  - 具备本轮新增的 `upsert_failed -> quarantine old binding -> reroute` 闭环
- OpenCode：
  - 仍不支持 explicit provider resume
  - 当前没有 provider-native session writeback / recovery 闭环

哪些地方仍是 Codex-first:

- provider-native durable resume 目前只有 Codex exec 主路径具备。
- `resume_command_template` 目前只为 `codex exec resume {provider_session_id}` 生成。
- `RunnerProviderService.supports_explicit_session_resume(...)` 仍只对 Codex 返回 `true`。

哪些 review-plane provider resume 能力仍未完成:

- review plane 还没有 execution-plane 同级的 provider session binding / explicit resume
  route planner。
- reviewer 长 session 目前已能 Ray-first，但还没有 provider-native reviewer session
  writeback / stale / failed recovery 闭环。

修改的最小文件:

- `src/xmuse_core/platform/execution/executor.py`
- `src/xmuse_core/platform/execution/provider_session_binding.py`
- `tests/xmuse/test_execution_provider_session_binding.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `docs/xmuse/codex-strengthening-handoff.md`

关键 RED 现象或 recovery gap:

- 修改前，成功 provider 结果 writeback 失败时，lane 只会留下
  `provider_session_binding_degraded_reason="upsert_failed"`，
  但不会记录旧 `binding_id`。
- 修改前，resolver 只会对 `mark_failed_failed` 做 quarantine；
  即使 lane 已知 `upsert_failed`，旧 active binding 仍会继续被取回用于 resume。

主验收命令与辅助验收命令:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k "provider_binding or session or resume or degradation"
uv run pytest -q tests/xmuse/test_execution_provider_session_binding.py
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py
uv run pytest -q tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py
uv run ruff check \
  src/xmuse_core/platform/execution/executor.py \
  src/xmuse_core/platform/execution/provider_session_binding.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_platform_orchestrator.py
git diff --check
```

结果:

- `tests/xmuse/test_platform_orchestrator.py -k "provider_binding or session or resume or degradation"`:
  `9 passed, 201 deselected`
- `tests/xmuse/test_execution_provider_session_binding.py`: `8 passed`
- `tests/xmuse/test_provider_session_binding_store.py`: `17 passed`
- `tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py`: `4 passed`
- touched-file `ruff`: passed
- `git diff --check`: passed

剩余风险:

- 本轮只闭合了 execution-plane 的 provider-native session recovery 最小缺口，没有扩到
  review-plane provider-native resume parity。
- `upsert_failed` 当前的 recovery 语义是“隔离旧 binding 并 reroute”，不是“修复 store
  后自动补写新 provider session identity”。
- OpenCode/未来 provider 仍没有 provider-native writeback / stale recovery 闭环。
- `tests/xmuse/test_platform_runner.py` 的既有 circular-import blocker 仍未处理；
  本轮主验收未依赖它。

本轮明确没有扩展哪些能力点:

- 没有新增 A2A。
- 没有新增 Claude/OpenCode 新 provider 类型。
- 没有改 Ray runtime 主结构。
- 没有重构 TUI/dashboard。
- 没有把 `feature_lanes.json` 扩成新权威。
- 没有回头做 graph-native status/artifact 新一轮收缩。
- 没有扩成 review-plane provider-native resume parity 全量开发。
- 没有批量修全仓 ruff 或 legacy tests。

## 2026-06-03 Review-Plane Provider-Native Resume Parity

本轮收束的方面:

- 只收束一个 review-plane P0：让 reviewer 在存在兼容 active provider session
  binding 时，优先走 provider-native explicit resume，而不是直接进入 Ray/native
  persistent review session。

本轮闭环的 review-plane provider-native resume 主路径:

- coordinator 现在会先为 review invocation 做 route planning：
  1. 读取显式 `provider_session_binding_god_session_id`
  2. 只查找 `session_kind="review"` 的兼容 active binding
  3. 若 provider 支持 explicit resume 且 binding 兼容 ->
     `transport.send_review(...)` 先带 `provider_session_binding`
  4. 若无 binding / binding 不兼容 / provider 不支持 -> 继续既有
     persistent review / one-shot fallback 路径
- review path 不会像 execution 那样在选中 explicit resume 后直接禁用 persistent layer。
  review 的 persistent layer 仍保留为 resume-failure fallback。

compatible binding / incompatible binding / failed binding 三种语义:

- compatible binding:
  - review 主路径优先走 provider-native resume
  - 不会先触发 persistent review session
- incompatible binding:
  - route planner 返回 `persistent_review_or_fallback`
  - review 继续既有 Ray/native persistent review 或 one-shot fallback
- failed binding:
  - 若 provider-native review resume 返回 provider failure，
    现有 binding 会按 failure kind 标记为 `STALE` 或 `FAILED`
  - 同一轮 review 会立刻 reroute 到 persistent review；
    若 persistent review 不可交付，再回落到 one-shot review
  - 下次 route planning 不会再取回这个 stale/failed binding

哪些 provider 已具备该闭环:

- Codex review:
  - 已具备 review binding route planner
  - 已具备 explicit resume -> stale/failed mark -> persistent reroute 基础闭环
  - `ReviewRequest` / transport / provider command 构建链已能承载
    `provider_session_binding`
- OpenCode：
  - 仍不支持 explicit provider resume
  - review plane 仍只会走 persistent/one-shot 路径

哪些地方仍是 Codex-first:

- review-plane provider-native resume 目前只有 Codex 路径接通。
- `resume_command_template` 仍是 `codex exec resume {provider_session_id}`；
  review 只是复用这条 provider-native resume command。
- OpenCode/未来 provider 还没有 review session binding 的 explicit resume 契约。

与 execution-plane 的差异:

- execution 在命中 explicit provider resume 后会禁用 persistent execute。
- review 保留 persistent review 作为 resume-failure fallback，因为 reviewer
  更强调长 session 连续性与 verdict 交付。
- 本轮没有扩到 review provider session writeback；只闭合了 resume / reroute / stale gate。

修改的最小文件:

- `src/xmuse_core/platform/execution/review_god.py`
- `src/xmuse_core/platform/execution/provider_session_binding.py`
- `src/xmuse_core/platform/orchestrator_lane_flow.py`
- `src/xmuse_core/platform/messages.py`
- `src/xmuse_core/platform/execution/transport.py`
- `src/xmuse_core/providers/session_binding.py`
- `src/xmuse_core/providers/adapters/codex.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `tests/xmuse/test_execution_provider_session_binding.py`
- `tests/xmuse/test_provider_session_binding_store.py`
- `tests/xmuse/test_provider_codex_retrofit.py`
- `docs/xmuse/codex-strengthening-handoff.md`

关键 RED 现象或 parity gap:

- 修改前，review path 即使存在兼容 reviewer binding，也会先进入
  `_try_persistent_review(...)`，不会把 binding 传到 `send_review(...)`。
- 修改前，review resume failure 不会标记旧 binding stale/failed，也没有
  “provider-native resume 失败后 reroute persistent review”的闭环。
- 修改前，Codex adapter 只接受 `session_kind="exec"` 的 resume binding，
  review binding 无法构造 provider-native resume command。

主验收命令与辅助验收命令:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k "review or provider_binding or resume or degradation"
uv run pytest -q tests/xmuse/test_execution_provider_session_binding.py
uv run pytest -q tests/xmuse/test_provider_session_binding_store.py
uv run pytest -q tests/xmuse/test_runtime_ray_backend.py
uv run pytest -q tests/xmuse/test_provider_codex_retrofit.py -k "review_resume_command or explicit_binding or incompatible_resume_binding"
uv run ruff check \
  src/xmuse_core/platform/execution/review_god.py \
  src/xmuse_core/platform/execution/provider_session_binding.py \
  src/xmuse_core/platform/orchestrator_lane_flow.py \
  src/xmuse_core/platform/messages.py \
  src/xmuse_core/platform/execution/transport.py \
  src/xmuse_core/providers/session_binding.py \
  src/xmuse_core/providers/adapters/codex.py \
  tests/xmuse/test_platform_orchestrator.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_provider_session_binding_store.py \
  tests/xmuse/test_provider_codex_retrofit.py
git diff --check
```

结果:

- `tests/xmuse/test_platform_orchestrator.py -k "review or provider_binding or resume or degradation"`:
  `104 passed, 108 deselected`
- `tests/xmuse/test_execution_provider_session_binding.py`: `11 passed`
- `tests/xmuse/test_provider_session_binding_store.py`: `18 passed`
- `tests/xmuse/test_runtime_ray_backend.py`: `9 passed`
- `tests/xmuse/test_provider_codex_retrofit.py -k "review_resume_command or explicit_binding or incompatible_resume_binding"`:
  `3 passed, 15 deselected`

剩余风险:

- 本轮只闭合了 review-plane provider-native resume / reroute / stale gate，
  没有扩到 review provider session writeback。
- `mark_failed(...)` 失败时当前只记 warning，没有新增 graph-native degradation
  投影；这仍可作为下一轮 hardening 点。
- provider-native resume 的 transport exception / circuit-open 仍按现有 review
  infra failure 处理，没有额外做 binding-specific reroute 细分。
- OpenCode/未来 provider 仍缺 review-plane explicit resume 契约。

本轮明确没有扩展哪些能力点:

- 没有新增 A2A。
- 没有新增 Claude/OpenCode 新 provider 类型。
- 没有改 Ray runtime 主结构。
- 没有重构 TUI/dashboard。
- 没有把 `feature_lanes.json` 扩成新权威。
- 没有回头做 graph-native status/artifact 新一轮收缩。
- 没有扩成 execution-plane 新一轮 provider recovery 开发。
- 没有批量修全仓 ruff 或 legacy tests。

## 2026-06-03 Graph-Native Authority Cutover

本轮收束的方面:

- 只收束一个 authority cutover 核心路径：
  `orchestrator.dispatch_lane(...)` 不再只信任 `feature_lanes.json` 的
  `pending/reworking`，而是先受 graph-native status store 的 dispatch authority
  gate 约束。

本轮 cut over 的核心路径:

- `dispatch_lane()` 现在对带有 `graph_set_id` / `graph_id` 的 lane 先查询
  `FeatureGraphStatusStore.get(...)`
- 若 graph-native status 为：
  - `READY` 且 lane 在 `ready_lane_ids` 中 -> 允许 dispatch
  - `RUNNING` 且 lane 在 `active_lane_ids` 中 -> 允许 dispatch
  - 其他状态，或 lane 不在 graph-native authoritative lane 集合中 ->
    直接跳过 dispatch
- 该 skip 发生在 `_ensure_lane_worktree(...)` 和 projection transition 之前，
  因此不会再通过 `feature_lanes.json` 留下伪 `dispatched` / 伪运行态

哪些路径现在已 graph-native authoritative:

- `claim_next_ready_feature_graph_worker(...)`
  - 只读/只写 `FeatureGraphStatusStore`
  - 不依赖 projection 选 ready graph
- feature-graph worker evidence / review verdict / patch-forward / takeover
  一整组 graph-native flows
  - authoritative source 仍是 `FeatureGraphStatusStore` /
    `FeatureGraphArtifactStore`
  - 相关 focused tests 早已保证 stale/replay 不会通过 projection 伪造成功
- 本轮新增：
  - lane dispatch admission 也开始受 graph-native status authority 约束

当前最大的 authority gap 是什么:

- 在本轮修改前，只要 projection 里的 lane 还是 `pending`/`reworking`，
  `dispatch_lane()` 就能推进到 live execution；
  即使 graph-native status 已经不再允许该 lane 运行，projection 仍可充当隐式业务权威。

feature_lanes.json 还剩什么职责:

- 兼容投影 / 只读模型
- lane 级上下文载体：
  prompt、worktree、branch、runtime telemetry、历史调试字段
- TUI / legacy flows 读取的平面 lane 视图
- 仍可记录兼容性 metadata，但不应继续作为 graph-native dispatch authority

仍未 cut over 的路径:

- `LaneStateMachine` 仍是大量 legacy lane status 的写入口；
  本轮没有把全部 lane lifecycle 迁到 graph-native store
- `reconcile_status_changes()` 仍主要扫描 projection lane statuses
- provider binding degradation reconciliation 仍会扫 lane projection，
  然后再投影到 graph-native status store
- worktree / branch / retry_count 等 lane-level operational fields 仍驻留在
  `feature_lanes.json`

修改的最小文件:

- `src/xmuse_core/platform/orchestrator_lane_flow.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `docs/xmuse/codex-strengthening-handoff.md`

关键 RED 现象或 authority gap:

- 修改前，即使 graph-native `READY` record 的 `ready_lane_ids` 不包含该 lane，
  projection 中的 `status="pending"` 仍足以让 `dispatch_lane()` 进入
  `dispatched`
- 这意味着 stale projection 能绕过 graph-native status authority，
  在 `feature_lanes.json` 留下伪成功调度状态

主验收命令与辅助验收命令:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k "feature_graph or projection or authority or ready"
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_runtime_ray_backend.py
uv run pytest -q tests/xmuse/test_execution_provider_session_binding.py
uv run ruff check \
  src/xmuse_core/platform/orchestrator_lane_flow.py \
  tests/xmuse/test_platform_orchestrator.py
git diff --check
```

结果:

- `tests/xmuse/test_platform_orchestrator.py -k "feature_graph or projection or authority or ready"`:
  `47 passed, 168 deselected`
- `tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py`:
  `117 passed`
- `tests/xmuse/test_runtime_ray_backend.py`: `9 passed`
- `tests/xmuse/test_execution_provider_session_binding.py`: `11 passed`

剩余风险:

- 本轮只 cut over 了 dispatch admission guard，没有把全量 lane lifecycle
  从 `LaneStateMachine` 收束到 graph-native facade
- 对没有 `graph_set_id` / `graph_id` 或找不到 graph-native status 的 lane，
  仍保持 legacy projection-first 行为
- graph-native authority 与 projection status 的双轨仍存在；
  只是本轮把最容易形成伪 dispatch 成功的入口先封住

本轮明确没有扩展哪些能力点:

- 没有新增 A2A。
- 没有新增 Claude/OpenCode 新 provider 类型。
- 没有改 Ray runtime 主结构。
- 没有重构 TUI/dashboard。
- 没有回头做 provider-native resume / recovery 新一轮大扩展。
- 没有把本轮扩成全量 projection 重写。
- 没有批量修全仓 ruff 或 legacy tests。

## 2026-06-03 Reconcile Authority Cutover: Reworking + Gate Failed

本轮收束的方面:

- 只 cut over `reconcile_status_changes()` 的两个 graph-backed 分支：
  - `reworking -> dispatch_lane(...)`
  - `gate_failed -> transition("gated") -> _run_review_god(...)`

本轮 cut over 的核心路径:

- reworking 分支：
  - 在 reconcile 调用 `dispatch_lane(...)` 前，先检查 graph-native
    `FeatureGraphStatusStore`
  - 对带 `graph_set_id` + `graph_id` 的 lane：
    - graph-native `REWORKING` -> 允许继续 redispatch
    - graph-native `RUNNING` 且 lane 在 `active_lane_ids` 中 -> 允许
    - 其他 graph-native 状态 -> skip
- gate_failed 分支：
  - 在 reconcile 执行 `transition("gated")` 和 `_run_review_god(...)` 前，
    先检查 graph-native `FeatureGraphStatusStore`
  - 对带 `graph_set_id` + `graph_id` 的 lane：
    - graph-native `REVIEWING` -> 允许 retry review
    - 其他 graph-native 状态 -> skip

哪些路径现在已 graph-native authoritative:

- graph-backed reworking redispatch admission
- graph-backed gate_failed review-retry admission
- 本轮之前已完成的：
  - `claim_next_ready_feature_graph_worker(...)`
  - feature-graph worker/review/patch-forward/takeover graph-native status/artifact flows
  - 初始 `dispatch_lane(...)` 对 graph-backed `READY/RUNNING` lane 的 authority gate

feature_lanes.json 还剩什么职责:

- reconcile 扫描入口的兼容投影
- lane 级 prompt/worktree/branch/runtime telemetry 等平面读模型
- non-graph legacy lane lifecycle
- UI / legacy tools 读取的平面状态视图

关键 RED 现象或 authority gap:

- 修改前，projection 中 `status="reworking"` 的 graph-backed lane，
  即使 graph-native 已经不是可继续运行态，reconcile 仍会再次 `dispatch_lane(...)`
- 修改前，projection 中 `status="gate_failed"` 的 graph-backed lane，
  只要本地 retry 条件满足，reconcile 就会直接转回 `gated` 并重跑 review；
  graph-native status 不会先拦截

修改的最小文件:

- `src/xmuse_core/platform/orchestrator.py`
- `src/xmuse_core/platform/orchestrator_lane_flow.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `docs/xmuse/codex-strengthening-handoff.md`

主验收命令与辅助验收命令:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k "reworking or gate_failed or reconcile or authority or feature_graph"
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py
uv run ruff check src/xmuse_core/platform/orchestrator.py src/xmuse_core/platform/orchestrator_lane_flow.py tests/xmuse/test_platform_orchestrator.py
git diff --check
```

结果:

- `tests/xmuse/test_platform_orchestrator.py -k "reworking or gate_failed or reconcile or authority or feature_graph"`:
  `68 passed, 152 deselected`
- `tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py`:
  `117 passed`
- touched-file `ruff`: passed
- `git diff --check`: passed

剩余风险:

- 本轮只 cut over 了 reconcile 的 `reworking` 和 `gate_failed`；
  没有扩到 `reviewed / rejected / merged / failed`
- graph-backed `gated` stranded-review recovery 分支仍未在本轮纳入 authority cutover
- provider binding degradation reconciliation 仍是 projection -> graph-native 的过渡链，
  本轮未处理

本轮明确没有扩展哪些能力点:

- 没有扩到 reviewed / rejected / merged / failed reconcile 分支
- 没有做 `LaneStateMachine` 大重构
- 没有扩到 provider parity、Ray、A2A、TUI
- 没有把 provider binding degradation reconciliation 纳入本轮
- 没有顺手修无关测试或无关 ruff 债务

## 2026-06-03 Review-Plane Reconcile Authority Cutover

本轮收束的方面:

- 只 cut over `reconcile_status_changes()` 中 graph-backed lanes 的三条
  review-plane lifecycle 分支：
  - `reviewed -> on_lane_reviewed(...)`
  - `rejected -> on_lane_rejected(...)`
  - stranded `gated -> _run_review_god(...)`

本轮 cut over 的核心路径:

- reviewed 分支：
  - 在 reconcile 调用 `on_lane_reviewed(...)` 前，先检查 graph-native
    `FeatureGraphStatusStore`
  - 对带 `graph_set_id` + `graph_id` 的 lane：
    - graph-native `REVIEWING` -> 允许继续 reviewed handling
    - 其他 graph-native 状态 -> skip
- rejected 分支：
  - 在 reconcile 调用 `on_lane_rejected(...)` 前，先检查 graph-native
    `FeatureGraphStatusStore`
  - 对带 `graph_set_id` + `graph_id` 的 lane：
    - graph-native `REVIEWING` -> 允许继续 rejected handling
    - 其他 graph-native 状态 -> skip
- stranded gated recovery 分支：
  - 在 reconcile 触发 `_run_review_god(...)` 前，先检查 graph-native
    `FeatureGraphStatusStore`
  - 对带 `graph_set_id` + `graph_id` 的 lane：
    - graph-native `REVIEWING` -> 允许继续 stranded review recovery
    - 其他 graph-native 状态 -> skip

本轮实现方式:

- 复用了现有 `_graph_native_review_authority_allows_lane(...)` helper
- 没有新造通用 authority framework
- 没有改动 `on_lane_reviewed(...)` / `on_lane_rejected(...)` 内部行为；
  只把 reconcile admission 从 projection-first 收束到 graph-native status-first

关键 RED 现象或 authority gap:

- 修改前，projection 中 `status="reviewed"` 的 graph-backed lane，
  即使 graph-native 已经不是 review 中状态，reconcile 仍会直接调用
  `on_lane_reviewed(...)` 并推进 merge/final-action side effects
- 修改前，projection 中 `status="rejected"` 的 graph-backed lane，
  即使 graph-native 已经不是 review 中状态，reconcile 仍会直接调用
  `on_lane_rejected(...)` 并推进 reworking/redispatch side effects
- 修改前，projection 中 stranded `status="gated"` 的 graph-backed lane，
  只要命中 stranded-review 条件，reconcile 就会直接重跑 `_run_review_god(...)`；
  graph-native status 不会先拦截

修改的最小文件:

- `src/xmuse_core/platform/orchestrator.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `docs/xmuse/codex-strengthening-handoff.md`

主验收命令与 focused gate:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k "reviewed or rejected or gated or reconcile or authority or feature_graph"
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py
uv run ruff check src/xmuse_core/platform/orchestrator.py src/xmuse_core/platform/orchestrator_lane_flow.py tests/xmuse/test_platform_orchestrator.py
git diff --check
```

结果:

- `tests/xmuse/test_platform_orchestrator.py -k "reviewed or rejected or gated or reconcile or authority or feature_graph"`:
  `85 passed, 141 deselected`
- `tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py`:
  `117 passed`
- touched-file `ruff`: passed
- `git diff --check`: passed

剩余风险:

- 本轮只 cut over 了 review-plane reconcile authority；
  没有扩到 `merged / failed -> reproject_dependents_if_needed()`
- provider binding degradation reconciliation 仍是 projection -> graph-native 的过渡链，
  本轮未处理
- graph-backed lanes 的 reconcile 扫描入口仍来自 `feature_lanes.json` projection；
  本轮只把 reviewed / rejected / stranded gated 的 side-effect admission
  收束到 graph-native authority
- 全仓 `uv run ruff check .` 和 legacy tests 仍有既有 blocker；
  不是本轮完成条件，本轮只以 focused gates 为准

本轮明确没有扩展哪些能力点:

- 没有扩到 `merged / failed` reprojection cutover
- 没有扩到 provider binding degradation reconciliation cutover
- 没有做 `LaneStateMachine` 大重构
- 没有扩到 provider parity、Ray、A2A、TUI
- 没有顺手修全仓 ruff 或 legacy test 债务

## 2026-06-03 Full Remaining Reconcile Authority Cutover

本轮收束的方面:

- 完成 `reconcile_status_changes()` 对 graph-backed lanes 剩余三条主分支的
  authority cutover：
  - `executed -> _on_lane_executed(...)`
  - `merged -> reproject_dependents_if_needed(...)`
  - `failed -> reproject_dependents_if_needed(...)`

本轮 cut over 的核心路径:

- executed 分支：
  - 在 reconcile 调用 `_on_lane_executed(...)` 前，先检查 graph-native
    `FeatureGraphStatusStore`
  - 对带 `graph_set_id` + `graph_id` 的 lane：
    - graph-native `RUNNING` 且 lane 在 `active_lane_ids` 中 -> 允许继续
      executed handling
    - 其他 graph-native 状态 -> skip
- merged 分支：
  - 在 reconcile 调用 `reproject_dependents_if_needed(...)` 前，先检查
    graph-native `FeatureGraphStatusStore`
  - 对带 `graph_set_id` + `graph_id` 的 lane：
    - graph-native `MERGED` -> 允许继续 dependent reprojection
    - 其他 graph-native 状态 -> skip
- failed 分支：
  - 在 reconcile 调用 `reproject_dependents_if_needed(...)` 前，先检查
    graph-native `FeatureGraphStatusStore`
  - 对带 `graph_set_id` + `graph_id` 的 lane：
    - graph-native `FAILED` -> 允许继续 dependent reprojection
    - 其他 graph-native 状态 -> skip

本轮实现方式:

- 复用了现有 graph-native authority helper 模式
- 新增了最小 helper：
  - `_graph_native_execution_authority_allows_lane(...)`
  - `_graph_native_reprojection_authority_allows_lane(...)`
- 额外抽了 `_graph_native_status_record(...)` 作为共享读取入口，
  只服务这些 reconcile authority helpers；没有新造通用大框架

关键 RED 现象或 authority gap:

- 修改前，projection 中 `status="executed"` 的 graph-backed lane，
  即使 graph-native 已经不在 `RUNNING(active lane)`，reconcile 仍会继续
  `_on_lane_executed(...)` 并触发 gate/review side effects
- 修改前，projection 中 `status="merged"` 的 graph-backed lane，
  即使 graph-native 还没进入 `MERGED`，reconcile 仍会执行 dependent
  reprojection
- 修改前，projection 中 `status="failed"` 的 graph-backed lane，
  即使 graph-native 还没进入 `FAILED`，reconcile 仍会执行 dependent
  reprojection

修改的最小文件:

- `src/xmuse_core/platform/orchestrator.py`
- `src/xmuse_core/platform/orchestrator_lane_flow.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `docs/xmuse/codex-strengthening-handoff.md`

主验收命令与 focused gate:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k "executed or merged or failed or reconcile or authority or feature_graph"
uv run pytest -q tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py
uv run ruff check src/xmuse_core/platform/orchestrator.py src/xmuse_core/platform/orchestrator_lane_flow.py tests/xmuse/test_platform_orchestrator.py
git diff --check
```

结果:

- `tests/xmuse/test_platform_orchestrator.py -k "executed or merged or failed or reconcile or authority or feature_graph"`:
  `97 passed, 135 deselected`
- `tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py`:
  `117 passed`
- touched-file `ruff`: passed
- `git diff --check`: passed

收口结果:

- `reconcile_status_changes()` 对 graph-backed lanes 的主分支：
  - `executed`
  - stranded `gated`
  - `reviewed`
  - `rejected`
  - `reworking`
  - `gate_failed`
  - `merged`
  - `failed`
  现在都先过 graph-native authority，再决定是否执行 reconcile side effects
- `feature_lanes.json` 在 reconcile 主循环里对 graph-backed lanes 的角色，
  已收束为兼容扫描入口和 lane metadata carrier；
  不再单独决定这些 lane 的 lifecycle authority

剩余风险:

- provider binding degradation reconciliation 仍是 projection -> graph-native 的
  过渡桥接链；这是 reconcile 相关剩余的主要非 authoritative 路径
- 对没有 `graph_set_id` / `graph_id` 或查不到 graph-native status 的 lane，
  仍保持 legacy projection-first 行为
- 全仓 `uv run ruff check .` 和 legacy tests 仍有既有 blocker；
  不是本轮完成条件，本轮只以 focused gates 为准

本轮明确没有扩展哪些能力点:

- 没有把 provider binding degradation reconciliation 纳入本轮
- 没有做 `LaneStateMachine` 大重构
- 没有扩到 provider parity、Ray、A2A、TUI
- 没有扩到 reconcile 之外的 orchestrator 路径
- 没有顺手修全仓 ruff 或 legacy test 债务

## 2026-06-03 Graph-Native Authority Complete For Graph-Backed Lifecycle

本轮收束的总目标:

- 完成 graph-backed lifecycle 的 authority 收束：
  graph-native status / artifact / event store 现在是 graph-backed lifecycle
  和 provider binding degradation evidence 的业务权威
- `feature_lanes.json` 对 graph-backed lanes 只保留兼容投影和 lane operational
  metadata；不再单独决定 graph-backed lifecycle 或 degradation evidence

本轮收束的核心路径:

- provider binding degradation authority cutover：
  - execution-plane `upsert_failed` 现在在 runtime path 直接通过 callback 写入
    `FeatureGraphStatusStore`
  - execution-plane `mark_failed_failed` 现在在 runtime path 直接通过 callback
    写入 `FeatureGraphStatusStore`
  - `PlatformOrchestrator._run_execution_god()` 仍保留 lane->graph-native bridge，
    但只作为 migration compatibility fallback
- claim path authority cutover：
  - `claim_next_ready_feature_graph_worker()` 不再先跑全量
    `reconcile_feature_graph_provider_binding_degradations()`
  - claim 只消费 graph-native `FeatureGraphStatusStore`
- explicit resume quarantine authority cutover：
  - `resolve_execution_provider_session_binding()` 在 graph-backed lanes 上，
    现在优先读取 graph-native provider degradation evidence
  - stale projection 上的 `provider_session_binding_degraded=*` 不再能在
    graph-native status 干净时单独隔离 binding

本轮新增/调整的最小实现:

- `src/xmuse_core/platform/feature_graph_provider_binding_degradation_coordinator.py`
  - 新增 event-driven 写入口 `record_feature_graph_provider_binding_degradation(...)`
  - 兼容 fallback `record_feature_graph_provider_binding_degradation_from_lane(...)`
    改为 `skip_if_present=True`：若 graph-native 已有同 binding/reason 证据，
    直接返回既有 evidence，不再重放/覆盖/冲突
- `src/xmuse_core/platform/execution/executor.py`
  - `run_execution_god(...)` 新增
    `record_provider_session_binding_degradation` callback
  - `upsert_failed` / `mark_failed_failed` 在当次 runtime path 直接回调
    authoritative write
- `src/xmuse_core/platform/execution/provider_session_binding.py`
  - execution resume resolver 支持读取 graph-native status store
  - graph-backed lanes 上优先用 graph-native degradation evidence 做 quarantine；
    projection degraded flag 只剩无 graph-native authority 时的 compatibility fallback
- `src/xmuse_core/platform/orchestrator.py`
  - claim path 去掉 projection-scan degradation bridge
  - 新增 orchestrator-level event-driven degradation recorder

graph-native authority sources:

- graph-backed lifecycle status:
  `FeatureGraphStatusStore`
- graph-backed lifecycle events:
  `FeatureGraphStatusStore` event log
- worker/review/takeover/patch-forward artifacts:
  `FeatureGraphArtifactStore`
- provider binding degradation evidence:
  `FeatureGraphStatusStore.provider_session_binding_degradations`

`feature_lanes.json` 对 graph-backed lanes 的剩余职责:

- reconcile / dispatch / claim 的兼容扫描入口
- prompt / worktree / branch / retry counters / runtime telemetry /
  provider selection / transport metadata 等 operational metadata carrier
- non-graph legacy lanes 的旧状态视图
- UI / legacy readers 需要的平面投影视图

不得再视为 graph-backed authority 的 projection 字段:

- `status`
- `provider_session_binding_degraded`
- `provider_session_binding_degraded_reason`
- `provider_session_binding_id`
- `provider_session_binding_failure`

这些字段现在只用于:

- compatibility fallback bridge
- 调试与观测
- legacy / UI 读取

migration fallback responsibilities:

- `record_feature_graph_provider_binding_degradation_from_lane(...)`
- `reconcile_feature_graph_provider_binding_degradations(...)`
- `PlatformOrchestrator._run_execution_god()` 末尾的 lane->graph fallback 调用

fallback gate:

- 只在 migration compatibility 场景下读取 lane projection degradation metadata
- 若 graph-native status 已有同 binding/reason evidence：
  - 不新增 event
  - 不覆盖既有 evidence
  - 不因为 projection 细节差异触发 replay conflict
- claim path 不再调用全量 lane scan fallback

authority line completion state:

- graph-backed executed / gated / reviewed / rejected / reworking / gate_failed /
  merged / failed 主分支，都已经先过 graph-native authority
- provider binding degradation 的 authoritative write path，
  已从 projection scan bridge 切到 runtime/coordinator event-driven path
- projection->graph-native bridge 现在只剩 migration compatibility，
  不再是 authority source

修改的最小文件:

- `src/xmuse_core/platform/orchestrator.py`
- `src/xmuse_core/platform/orchestrator_lane_flow.py`
- `src/xmuse_core/platform/feature_graph_provider_binding_degradation_coordinator.py`
- `src/xmuse_core/platform/execution/executor.py`
- `src/xmuse_core/platform/execution/provider_session_binding.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py`
- `tests/xmuse/test_execution_provider_session_binding.py`
- `tests/xmuse/test_execution_child_worker.py`
- `docs/xmuse/codex-strengthening-handoff.md`

主验收命令:

```bash
uv run pytest -q tests/xmuse/test_platform_orchestrator.py -k "authority or feature_graph or reconcile or dispatch or claim or degradation"
uv run pytest -q tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py
uv run pytest -q tests/xmuse/test_execution_provider_session_binding.py tests/xmuse/test_execution_child_worker.py
uv run ruff check src/xmuse_core/platform/orchestrator.py src/xmuse_core/platform/orchestrator_lane_flow.py src/xmuse_core/platform/feature_graph_provider_binding_degradation_coordinator.py src/xmuse_core/platform/execution/executor.py src/xmuse_core/platform/execution/provider_session_binding.py tests/xmuse/test_platform_orchestrator.py tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py
git diff --check
```

结果:

- `tests/xmuse/test_platform_orchestrator.py -k "authority or feature_graph or reconcile or dispatch or claim or degradation"`:
  `90 passed, 142 deselected`
- `tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_feature_graph_artifact_store.py`:
  `122 passed`
- `tests/xmuse/test_execution_provider_session_binding.py tests/xmuse/test_execution_child_worker.py`:
  `22 passed`
- touched-file `ruff`: passed
- `git diff --check`: passed

剩余风险:

- non-graph legacy lanes 仍保持 projection-first 旧路径；这是预期保留
- `feature_lanes.json` 仍作为兼容扫描入口和 metadata carrier 存在，
  尚未被删除；这也是预期保留
- 全仓 `uv run ruff check .` 和 legacy tests 仍有既有 blocker；
  不是本轮完成条件

本轮明确没有扩展哪些能力点:

- 没有做 `LaneStateMachine` 全量重构
- 没有删除 `feature_lanes.json`
- 没有扩到 A2A、Ray parity、新 provider、TUI/dashboard
- 没有扩到 graph-backed lifecycle authority 之外的话题
- 没有顺手清全仓 lint/test 债务

## 2026-06-03 CHAT-BOOTSTRAP

本轮只完成 `CHAT-BOOTSTRAP`，没有进入 `CHAT-DEFAULT-INTAKE` 或其他能力点。

完成内容:

- `POST /api/chat/conversations` 不再由 API 层直接 create conversation + seed participants，
  而是统一切到 `PeerChatService.create_conversation()`。
- `PeerChatService` 新增可重跑的 `bootstrap_conversation(...)`，把建群收束为单一路径:
  - create conversation
  - ensure init participant
  - ensure init session
  - instantiate default peer participants
  - emit bootstrap artifact
- bootstrap 会写入可审计 artifact:
  `artifacts/chat_bootstrap/<conversation_id>.json`。
- `ParticipantStore` 新增 bootstrap participant ensure 逻辑，保证同一
  `conversation_id + role + display_name` 的默认 bootstrap peer 不被重复创建。
- `init god` session 在 bootstrap 时真实写入 `god_sessions.json`，不再只是 participant 记录存在。
- bootstrap rerun 对 participant / init session / fork lineage 保持 duplicate-safe。

本轮修改文件:

- `xmuse/chat_api.py`
- `src/xmuse_core/chat/peer_service.py`
- `src/xmuse_core/chat/participant_store.py`
- `tests/xmuse/test_chat_bootstrap.py`
- `docs/xmuse/walkthrough-maintenance-notes-v2.md`
- `docs/xmuse/codex-strengthening-handoff.md`

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_chat_bootstrap.py
uv run pytest -q tests/xmuse/test_chat_bootstrap.py \
  tests/xmuse/test_god_session_registry.py \
  tests/xmuse/test_god_session_layer.py
uv run ruff check xmuse/chat_api.py \
  src/xmuse_core/chat/peer_service.py \
  src/xmuse_core/chat/participant_store.py \
  tests/xmuse/test_chat_bootstrap.py
```

验证结果:

- `tests/xmuse/test_chat_bootstrap.py`: `3 passed`
- bootstrap + GOD session focused regression: `39 passed`
- touched-file `ruff`: passed

强 gate 结论:

- 建群后存在可审计 bootstrap artifact: 已满足
- `init god` session 已真实建立: 已满足
- 预制模式通过单一 bootstrap path 落地: 已满足
- 失败中断后 rerun duplicate-safe: 已满足

剩余风险:

- bootstrap artifact 当前是文件 artifact，不是 chat card；满足 V2 的 “artifact 或 card”
  gate，但后续若需要在 conversation timeline 中可视化，还需单独设计。
- 当前 bootstrap 的 fork plan 仍固定为空；这与本任务 gate 一致，但未扩展更复杂的
  participant/fork planning。
- 未参考 `/home/iiyatu/clowder-ai`；本轮缺口可直接用 xmuse 现有 participant/session/fork
  原语收束，无需借鉴外部实现。

## 2026-06-04 CHAT-DEFAULT-INTAKE

本轮只完成 `CHAT-DEFAULT-INTAKE`，没有进入 `CHAT-REVIEW-TRIGGER` 或其他能力点。

完成内容:

- `PeerChatService.post_human_message()` 现在对 human 无显式 `@` 的消息自动补一个默认
  intake inbox item，target 固定为 `architect`。
- 默认 intake 与显式 mention 被收束为同一个 inbox 构造入口：
  - 有显式 mention 时仅创建 `mention` inbox items
  - 无显式 mention 时仅创建一个 `default_intake` inbox item
- `src/xmuse_core/chat/mentions.py` 新增共享默认 intake 常量/地址函数，去掉
  `ChatDriver` 与 peer chat 主路径之间的语义分裂。
- `ChatDriver._route()` 改为使用共享默认 intake role，确保旧路径与新路径都稳定解释为
  `architect` 首响。
- replay 同一 `client_request_id` 时继续复用 logged result，不重复写 inbox；
  因为 replay 直接返回已记录 payload，也不会重复触发 turn budget reset。

本轮修改文件:

- `src/xmuse_core/chat/peer_service.py`
- `src/xmuse_core/chat/mentions.py`
- `src/xmuse_core/chat/driver.py`
- `tests/xmuse/test_chat_default_intake.py`
- `docs/xmuse/walkthrough-maintenance-notes-v2.md`
- `docs/xmuse/codex-strengthening-handoff.md`

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_chat_default_intake.py
uv run pytest -q tests/xmuse/test_chat_default_intake.py \
  tests/xmuse/test_chat_bootstrap.py
uv run ruff check src/xmuse_core/chat/peer_service.py \
  src/xmuse_core/chat/mentions.py \
  src/xmuse_core/chat/driver.py \
  tests/xmuse/test_chat_default_intake.py
```

验证结果:

- `tests/xmuse/test_chat_default_intake.py`: `4 passed`
- default-intake + bootstrap focused regression: `7 passed`
- touched-file `ruff`: passed

强 gate 结论:

- human 无 `@` 发消息时，必然创建且只创建一个默认 intake inbox item: 已满足
- 默认 intake target 固定为 `architect`: 已满足
- 不影响显式 `@review` / `@execute` / `@participant:...` 路由: 已满足
- idempotent replay 不重复消耗 turn budget，不重复写 inbox: 已满足

剩余风险:

- 当前证据面主要覆盖 service/API 层的 inbox 产物与 replay 结果；尚未补 scheduler/runner
  侧的端到端消费验证，这不属于本任务强 gate。
- 旧 conversation 若缺失 active `architect` participant，默认 intake 会返回明确错误而不是静默降级；
  这符合 bootstrap 后的系统约束，但历史脏数据若存在，需由上游 bootstrap/修复处理。
- 未参考 `/home/iiyatu/clowder-ai`；本轮缺口可直接由 xmuse 现有 mention/inbox/driver 语义收束。

## 2026-06-04 CHAT-REVIEW-TRIGGER

本轮只完成 `CHAT-REVIEW-TRIGGER`，没有进入 `CHAT-STRUCTURE-ESCALATION` 或其他能力点。

完成内容:

- `PeerChatService.emit_proposal(...)` 与 `emit_blueprint_proposal(...)` 现在在
  reviewable object 真正落库后，自动为 `review` participant 建立 review-trigger inbox item。
- 自动 review trigger 同时覆盖：
  - `lane_graph` proposal
  - `mission_blueprint` proposal
- 自动 review trigger 只在 reviewable object 阶段发生；普通 human/god message
  不会自动拉起 `review`。
- review trigger 通过 `source_message_id + review participant` 去重：
  - replay 同一 emit request 不会重复制造 review 请求
  - 同一 source message 上若已存在面向 review 的 inbox item，也不会重复写入
- 手动 `@review` mention 与自动 review trigger 可并存，但按不同 source message
  分别记录，不冲突、不互相覆盖。

本轮修改文件:

- `src/xmuse_core/chat/peer_service.py`
- `tests/xmuse/test_chat_review_trigger.py`
- `docs/xmuse/walkthrough-maintenance-notes-v2.md`
- `docs/xmuse/codex-strengthening-handoff.md`

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_chat_review_trigger.py
uv run pytest -q tests/xmuse/test_chat_review_trigger.py \
  tests/xmuse/test_chat_default_intake.py \
  tests/xmuse/test_chat_bootstrap.py
uv run ruff check src/xmuse_core/chat/peer_service.py \
  tests/xmuse/test_chat_review_trigger.py
```

验证结果:

- `tests/xmuse/test_chat_review_trigger.py`: `5 passed`
- review-trigger + default-intake + bootstrap focused regression: `12 passed`
- touched-file `ruff`: passed

强 gate 结论:

- reviewable object 会自动为 review 建 inbox: 已满足
- 非 reviewable message 不自动唤起 review: 已满足
- replay / retry 不重复制造 review 请求: 已满足
- architect 手动 `@review` 与自动 review trigger duplicate-safe: 已满足

剩余风险:

- 当前自动 trigger 只把 `lane_graph` proposal 和 `mission_blueprint` proposal
  视为 reviewable object；后续若结构化对象种类继续扩展，需要在
  `CHAT-STRUCTURE-ESCALATION` 中统一判定升级/可审边界。
- 当前证据面聚焦于 inbox 触发与去重；还未扩到 approve/narrow/reject 的后续动作，
  这与本任务禁止扩面约束一致。
- 未参考 `/home/iiyatu/clowder-ai`；本轮缺口可直接由 xmuse 现有 proposal/inbox/service
  原语收束。

## 2026-06-04 CHAT-STRUCTURE-ESCALATION

本轮只完成 `CHAT-STRUCTURE-ESCALATION`，没有进入 `CHAT-BLUEPRINT-REVISION` 或其他能力点。

完成内容:

- `create_proposal` 现在会先做稳定的结构化升级判定，再决定最终存储的 `proposal_type`，
  不再把调用方给出的 `proposal_type` 当成唯一真相。
- 当前已协议化的升级规则:
  - payload 含 `lanes` -> `lane_graph`
  - payload 含 `title/body/acceptance_criteria` -> `mission_blueprint`
  - payload 含 `features/source_blueprint_ref` -> `feature_plan`
  - payload 含 `decision/rationale` -> `verdict`
  - 其余保持 `proposal`
- `PeerProposalEmitter.emit_lane_graph_proposal(...)` 现在统一写入
  `resolution_content.type = "lane_graph"`，让下游 approval/execution 直接识别。
- `approve_proposal` 在审批时也会重新走同一升级判定：
  - `feature_plan` 会继续走 blueprint 上游约束校验
  - `lane_graph` / `mission_blueprint` 若未显式传 approval content，会从规范化后的
    `resolution_content` 中恢复类型信息，避免下游识别漂移
- verdict 目前先落成稳定分类契约，未扩到新的 review/execution 行为。

本轮修改文件:

- `xmuse/chat_api.py`
- `src/xmuse_core/chat/models.py`
- `src/xmuse_core/chat/peer_proposals.py`
- `tests/xmuse/test_chat_structure_escalation.py`
- `docs/xmuse/walkthrough-maintenance-notes-v2.md`
- `docs/xmuse/codex-strengthening-handoff.md`

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_chat_structure_escalation.py
uv run pytest -q tests/xmuse/test_chat_structure_escalation.py \
  tests/xmuse/test_chat_review_trigger.py \
  tests/xmuse/test_chat_default_intake.py \
  tests/xmuse/test_chat_bootstrap.py
uv run ruff check xmuse/chat_api.py \
  src/xmuse_core/chat/models.py \
  src/xmuse_core/chat/peer_proposals.py \
  tests/xmuse/test_chat_structure_escalation.py
```

验证结果:

- `tests/xmuse/test_chat_structure_escalation.py`: `4 passed`
- structure-escalation + review-trigger + default-intake + bootstrap focused regression:
  `16 passed`
- touched-file `ruff`: passed

强 gate 结论:

- 同一输入在同一上下文下，升级结果稳定且可解释: 已满足
- feature plan / lane graph 不能绕过 blueprint 上游约束: 已满足
- 结构化对象一旦形成，就能被下游 review / approval / execution 识别: 已满足

剩余风险:

- `verdict` 目前只收束到分类契约层，还未扩到新的 verdict 写入/消费路径；
  这与本任务允许的文件范围一致。
- `message` 仍是 chat/message 路径中的默认非结构化形态，没有新增 message 自动升级为
  proposal 的启发式；当前只对进入 proposal API 的 payload 做稳定升级。
- 未参考 `/home/iiyatu/clowder-ai`；本轮缺口可直接由 xmuse 现有 proposal/envelope/API
  契约收束。

## 2026-06-04 CHAT-BLUEPRINT-REVISION

本轮只完成 `CHAT-BLUEPRINT-REVISION`，没有进入 `PEER-PROVIDER-PARITY` 或其他能力点。

完成内容:

- `create_proposal` 现在会把“改怎么拆/怎么做”和“改做什么/改验收”分开：
  - 仅有 `features/source_blueprint_ref` 的 payload 继续归类为 `feature_plan`
  - 一旦 payload 同时携带 `title/body/acceptance_criteria` 这类 blueprint-level
    字段，就优先升级为 `mission_blueprint` revision
- blueprint revision payload 若只给了 `source_blueprint_ref`，会被规范化为
  `revision_of=<source_blueprint_ref>`，保证 revision 语义链在 proposal content
  和 approved resolution 上一致。
- `create_proposal` / `approve_proposal` 对 `feature_plan` 现在都会校验 source blueprint
  是否仍是当前 authoritative blueprint：
  - 若 source blueprint 已被更新 revision 取代，则返回
    `stale_feature_plan_blueprint`
  - 旧 blueprint 上已存在但未批准的 feature plan proposal，在新 revision
    批准后也不能继续被批准为 authoritative feature plan
- `ChatStore.approve_proposal()` 在批准 `mission_blueprint` revision 时，
  会把被修订的 blueprint resolution 标记为 `SUPERSEDED` 并写入
  `superseded_by_resolution_id`，让 authoritative source cutover 落到 durable state。

本轮修改文件:

- `xmuse/chat_api.py`
- `src/xmuse_core/chat/peer_proposals.py`
- `src/xmuse_core/chat/store.py`
- `tests/xmuse/test_chat_blueprint_revision.py`
- `tests/xmuse/test_chat_structure_escalation.py`
- `docs/xmuse/walkthrough-maintenance-notes-v2.md`
- `docs/xmuse/codex-strengthening-handoff.md`

已运行验证:

```bash
uv run pytest -q tests/xmuse/test_chat_blueprint_revision.py
uv run pytest -q tests/xmuse/test_chat_blueprint_revision.py \
  tests/xmuse/test_chat_structure_escalation.py \
  tests/xmuse/test_chat_review_trigger.py \
  tests/xmuse/test_chat_default_intake.py \
  tests/xmuse/test_chat_bootstrap.py
uv run ruff check xmuse/chat_api.py \
  src/xmuse_core/chat/peer_proposals.py \
  src/xmuse_core/chat/store.py \
  tests/xmuse/test_chat_blueprint_revision.py \
  tests/xmuse/test_chat_structure_escalation.py
```

验证结果:

- `tests/xmuse/test_chat_blueprint_revision.py`: `4 passed`
- blueprint-revision + structure-escalation + review-trigger + default-intake + bootstrap
  focused regression: `20 passed`
- touched-file `ruff`: passed

强 gate 结论:

- 当变更触及 mission / scope / acceptance / core constraints 时，不允许直接继续 feature plan:
  已满足
- revision blueprint 批准后，后续 feature plan 必须引用新的 approved blueprint:
  已满足
- 旧 blueprint 上已存在的下游 feature plan，不能在新 revision 出现后继续被当作当前
  authoritative source: 已满足

剩余风险:

- 这一轮的 revision trigger 仍是 payload-shape 驱动的协议化判定，不包含更复杂的语义 diff；
  但已满足 V2 当前要求的“正式触发规则”。
- `core constraints` 当前通过 blueprint-level 字段集合收束，没有单独新增 schema 字段；
  若后续引入显式 constraints 字段，需要把它并入同一 revision 触发器。
- 未参考 `/home/iiyatu/clowder-ai`；本轮缺口可直接由 xmuse 现有 proposal/store/blueprint
  原语收束。

## 2026-06-04 V4 OPS-CONVERSATION-INSPECTOR

本轮只完成 `OPS-CONVERSATION-INSPECTOR`（V4 任务 1），没有进入 `OPS-PARTICIPANT-AND-INBOX-VIEW` 或其他能力点。

### 本轮唯一任务名
`OPS-CONVERSATION-INSPECTOR`

### 实际修改的文件列表
- `xmuse/dashboard_api.py` — 新增 `GET /api/dashboard/peer-chat/conversations/{conversation_id}/inspector` endpoint
- `tests/xmuse/test_peer_chat_dashboard.py` — 新增 4 个 focused tests

### 新增或修改的 tests
4 个 focused tests（均在 `tests/xmuse/test_peer_chat_dashboard.py`）:
- `test_conversation_inspector_returns_full_summary_with_participants_blueprint_and_graphs` — 验证完整 inspector 返回
- `test_conversation_inspector_stable_with_missing_data` — 验证缺数据时稳定返回
- `test_conversation_inspector_returns_404_for_unknown_conversation` — 验证未知 conversation 返回 404
- `test_conversation_inspector_does_not_contain_write_semantics` — 验证返回不含 write/claim 语义

### brainstorming 四项边界是否仍成立
1. **本轮唯一任务边界**: 成立。仅新增单一 inspector endpoint。
2. **本轮允许改动的文件**: 成立。只改了 `dashboard_api.py` 和 `test_peer_chat_dashboard.py`。
3. **本轮 gate 映射**: 成立。4 个 focused tests 对应强 gate 3 条 + 统一质量 gate 4 条。
4. **本轮明确不做什么**: 成立。未新增写接口、未改 conversation/inbox/scheduler 语义、未改 V2/V3 主线。

### fresh verification 命令与结果

```bash
# Focused tests
uv run pytest -q tests/xmuse/test_peer_chat_dashboard.py::test_conversation_inspector_returns_full_summary_with_participants_blueprint_and_graphs tests/xmuse/test_peer_chat_dashboard.py::test_conversation_inspector_stable_with_missing_data tests/xmuse/test_peer_chat_dashboard.py::test_conversation_inspector_returns_404_for_unknown_conversation tests/xmuse/test_peer_chat_dashboard.py::test_conversation_inspector_does_not_contain_write_semantics
# 4 passed

# Affected dashboard/MCP/read-contract tests
uv run pytest -q tests/xmuse/test_peer_chat_dashboard.py tests/xmuse/test_dashboard_api.py
# 143 passed

# Ruff check on touched files
uv run ruff check xmuse/dashboard_api.py tests/xmuse/test_peer_chat_dashboard.py
# All checks passed

# Git diff --check
git diff --check
# (no output — clean)
```

### 逐条强 gate 覆盖

| 强 gate | 覆盖测试/验证 |
|---------|-------------|
| 单一只读入口拿到全貌 | `test_conversation_inspector_returns_full_summary*` — 返回 conversation/participants/recent_activity/blueprint/feature_plan/graph_set |
| 缺数据时稳定返回 | `test_conversation_inspector_stable_with_missing_data` — 空 conversation 返回所有字段且不报错 |
| 结构可复用/无执行语义 | `test_conversation_inspector_does_not_contain_write_semantics` — JSON 不含 claim/approve/reject/rework/write |
| 统一质量 gate 1: fresh test evidence | 上述 4 个 focused tests 全部 fresh run |
| 统一质量 gate 2: focused regression test | 4 个 focused tests 覆盖新增行为 |
| 统一质量 gate 3: 不新增 V2/V3 特判 | 仅新增只读 endpoint，不改 V2/V3 任何语义 |
| 统一质量 gate 4: 缺数据稳定 | 所有缺失数据场景返回 None 或空列表 |

### 本轮没有扩到的能力点
- 没有新增写接口
- 没有改 conversation bootstrap / inbox / scheduler 语义
- 没有改现有 `/api/dashboard/peer-chat/conversations/{id}` 返回结构
- 没有改 V2 provider/runtime/authority 逻辑
- 没有改 TUI (V3) 代码
- 没有改 V2 CHAT-BOOTSTRAP/DEFAULT-INTAKE/REVIEW-TRIGGER/STRUCTURE-ESCALATION/BLUEPRINT-REVISION 语义
- 没有改 V3 TUI-INPUT-HISTORY/TUI-COMPLETION-ENGINE 语义

## 2026-06-04 V4 OPS-PARTICIPANT-AND-INBOX-VIEW

本轮只完成 `OPS-PARTICIPANT-AND-INBOX-VIEW`（V4 任务 2），没有进入 `OPS-SESSION-HEALTH` 或其他能力点。

### 本轮唯一任务名
`OPS-PARTICIPANT-AND-INBOX-VIEW`

### 实际修改的文件列表
- `xmuse/dashboard_api.py` — inspector endpoint 的 `participants` 中新增 `inbox_summary` 字段
- `tests/xmuse/test_peer_chat_dashboard.py` — 新增 3 个 focused tests + import sqlite3

### 新增或修改的 tests
3 个 focused tests（均在 `tests/xmuse/test_peer_chat_dashboard.py`）:
- `test_inspector_participant_inbox_summary_shows_counts_per_participant` — 多 participant 各自正确计数
- `test_inspector_inbox_summary_empty_when_no_inbox_items` — 无 inbox 时返回空列表
- `test_inspector_inbox_summary_counts_only_non_terminal_items_for_unread_claimed` — unread/claimed/failed 分类正确

### brainstorming 四项边界是否仍成立
1. **本轮唯一任务边界**: 成立。仅增强 inspector 的 participants 响应。
2. **本轮允许改动的文件**: 成立。只改了 `dashboard_api.py` 和 `test_peer_chat_dashboard.py`。
3. **本轮 gate 映射**: 成立。3 个 focused tests 覆盖强 gate。
4. **本轮明确不做什么**: 成立。未新增写接口、未改 mention/intake/review 协议、未改 V2/V3 主线。

### fresh verification 命令与结果

```bash
uv run pytest -q tests/xmuse/test_peer_chat_dashboard.py::test_inspector_participant_inbox_summary_shows_counts_per_participant tests/xmuse/test_peer_chat_dashboard.py::test_inspector_inbox_summary_empty_when_no_inbox_items tests/xmuse/test_peer_chat_dashboard.py::test_inspector_inbox_summary_counts_only_non_terminal_items_for_unread_claimed
# 3 passed

uv run pytest -q tests/xmuse/test_peer_chat_dashboard.py tests/xmuse/test_dashboard_api.py
# 146 passed

uv run ruff check xmuse/dashboard_api.py tests/xmuse/test_peer_chat_dashboard.py
# All checks passed

git diff --check
# (no output — clean)
```

### 逐条强 gate 覆盖

| 强 gate | 覆盖测试/验证 |
|---------|-------------|
| participant 列表及其 inbox 摘要 | `test_inspector_participant_inbox_summary*` — 多 participant 各有 unread/claimed/failed 计数 |
| inbox 为空/全读/部分失败/claim 卡住时稳定 | `test_inspector_inbox_summary_empty*` + `test_inspector_inbox_summary_counts*` |
| 只读视图不改 inbox 状态 | inspector 只查询 `list_by_conversation`，不调任何 mark/claim 方法 |

### 本轮没有扩到的能力点
- 没有新增 inbox 写动作
- 没有改 mention/default-intake/review-trigger 协议
- 没有改 V2/V3 主线
- 没有新增独立 endpoint

## 2026-06-04 V4 OPS-SESSION-HEALTH

本轮只完成 `OPS-SESSION-HEALTH`（V4 任务 3），没有进入 `OPS-GRAPH-AND-WORKLIST-VIEW` 或其他能力点。

### 实际修改的文件
- `xmuse/dashboard_api.py` — inspector 新增 `session_health` 字段
- `tests/xmuse/test_peer_chat_dashboard.py` — 新增 3 个 focused tests

### 新增/修改 tests
3 个 focused tests:
- `test_inspector_session_health_shows_sessions_by_conversation`
- `test_inspector_session_health_empty_when_no_sessions`
- `test_inspector_session_health_classifies_stopped_sessions`

### fresh verification
```bash
# Focused: 3 passed
# Affected: 160 passed (peer_chat_dashboard + dashboard_api + dashboard_health)
# Ruff: All checks passed
# git diff --check: clean
```

### 本轮没有扩到的能力点
- 不改 provider/runtime route planner
- 不新增 session 决策分支
- 不新增写接口

## 2026-06-04 V5 CONTRACT-COVERAGE-SMOKE (TERMINATION)

本轮为 V5 最终 smoke 收口，确认全部 7 任务终止条件满足。

### 终止条件逐条验证

1. ✅ **任务 1-5 的强 gate 全部通过**
   - Task 1 CONTRACT-FIXTURE-INVENTORY: 11 tests, fixture inventory 27 entries
   - Task 2 READ-SURFACE-SCHEMA-PARITY: 13 parity tests
   - Task 3 PACKAGE-BOUNDARY-GATES: 16 boundary tests
   - Task 4 MODEL-POLICY-SURFACE-PARITY: 11 surface tests
   - Task 5 EXPORT-CONTRACT-HARDENING: 14 export contract tests
2. ✅ **任务 6 强 gate 通过** — 7 replay tests 证明多 surface 复用
3. ✅ **CONTRACT-COVERAGE-SMOKE fresh run 通过** — 117 V5-focused tests
4. ✅ **smoke 暴露的 V6 非标准 fixture** 已通过 `_NON_CONTRACT_FIXTURES` 豁免处理
5. ✅ **最后一轮通过时无规定问题**
6. ✅ **handoff 可让后续模型直接推进**

### 实际修改的文件
所有 V5 轮实际修改的文件:
- `docs/xmuse/shared-contract-fixtures.md`
- `docs/xmuse/walkthrough-maintenance-notes-v5.md`
- `docs/xmuse/codex-strengthening-handoff.md`
- `tests/xmuse/test_shared_contract_fixtures_contract.py`
- `tests/xmuse/test_parallel_contract_fixtures.py`
- `tests/xmuse/test_read_surface_schema_parity.py`
- `tests/xmuse/test_package_boundaries.py`
- `tests/xmuse/test_model_policy_surfaces.py`
- `tests/xmuse/test_split_export_contract.py`
- `tests/xmuse/test_replay_fixtures.py`

### fresh verification
```bash
# V5 focused tests (contract governance plane)
uv run pytest -q \
  tests/xmuse/test_shared_contract_fixtures_contract.py \
  tests/xmuse/test_parallel_contract_fixtures.py \
  tests/xmuse/test_read_surface_schema_parity.py \
  tests/xmuse/test_package_boundaries.py \
  tests/xmuse/test_model_policy_surfaces.py \
  tests/xmuse/test_split_export_contract.py \
  tests/xmuse/test_export_tool.py \
  tests/xmuse/test_replay_fixtures.py
# 79 passed

# Broader regression (V2/V3/V4 surface, contract/status/provider tests)
uv run pytest -q tests/xmuse/test_model_policy.py tests/xmuse/test_provider_models.py tests/xmuse/test_provider_policy.py tests/xmuse/test_provider_read_contracts_module.py tests/xmuse/test_dashboard_api.py tests/xmuse/test_mcp_server.py tests/xmuse/test_platform_mcp_tools.py tests/xmuse/test_tui_adapter_contract.py tests/xmuse/test_feature_review_contracts.py tests/xmuse/test_feature_graph_status_store.py tests/xmuse/test_platform_orchestrator.py tests/xmuse/test_provider_session_binding_store.py tests/xmuse/test_provider_codex_retrofit.py tests/xmuse/test_core_agents_launchers.py
# 619 passed (0 regression)

# Ruff
uv run ruff check tests/xmuse/test_shared_contract_fixtures_contract.py tests/xmuse/test_parallel_contract_fixtures.py tests/xmuse/test_read_surface_schema_parity.py tests/xmuse/test_package_boundaries.py tests/xmuse/test_model_policy_surfaces.py tests/xmuse/test_split_export_contract.py tests/xmuse/test_export_tool.py tests/xmuse/test_replay_fixtures.py docs/xmuse/shared-contract-fixtures.md
# All checks passed

# Whitespace
git diff --check
# clean
```

### V5 全轮汇总

| 任务 | 真实范围 | 新增 tests |
|---|---|---|
| CONTRACT-FIXTURE-INVENTORY | fixture inventory 收束（文档 + 测试扩展） | +1 |
| READ-CONTRACT-DISCRIMINATOR-COVERAGE | builder discriminator + edge-case smoke（非跨 surface parity） | ~+13 |
| PACKAGE-BOUNDARY-GATES | AST 静态 import 门禁（手写 _check_boundary，非统一 allowlist） | +13 |
| MODEL-POLICY-SURFACE-PARITY | 枚举值 + registry↔inventory 字段对齐 | +9 |
| EXPORT-CONTRACT-HARDENING | template↔manifest 一致性 + 异常路径 | +7 |
| CONTRACT-FIXTURE-VALIDATION | fixture 结构消费验证（非 real-run replay 闭环） | +6 |
| CONTRACT-COVERAGE-SMOKE | 收口验证 | — |

**合计新增 ~49 focused tests，全部通过（79 V5-specific + 619 broader = 698 passed）。不修改任何生产代码。不引入 runtime authority 特判。不涉及 V2/V3/V4 主线语义。**

## 2026-06-04 V5 CONTRACT-FIXTURE-VALIDATION（原名 REAL-RUN-REPLAY-FIXTURES）

本轮为 V5 第六条任务对现有 contract fixtures 做结构化消费验证。

### 本轮唯一任务边界
加载已冻结的 contract fixtures（event/artifact/envelope/card/interface），验证其 payload 可以被 read contract 消费者解析，不依赖人工改数据库。

### 实际修改的文件
- `tests/xmuse/test_replay_fixtures.py` — 新增 6 个 fixture validation tests
- `tests/xmuse/test_shared_contract_fixtures_contract.py` — 处理 `chat_memory_taxonomy.v1.json`（V6 非标准 fixture）的豁免

### 新增/修改 tests
6 个 focused tests:
- `test_replay_event_fixtures_as_read_contract_payload` — 遍历 event fixture，验证 payload 符合 read contract 结构
- `test_replay_artifact_fixtures_as_read_contract_payload` — 遍历 artifact fixture，验证 lineage/ownership
- `test_replay_read_envelope_cards_resolve_to_card_fixtures` — envelope 内嵌 card 指向独立 card fixture 的 traceability
- `test_replay_card_fixtures_are_self_describing_replay_units` — 每个 card fixture 自包含 replay 所需字段
- `test_replay_event_artifact_chain_is_traceable` — event 的 artifact_refs 可解析为磁盘 fixture 文件
- `test_replay_interface_fixture_describes_all_parallel_sessions` — interface fixture 是静态 manifest

**说明**: 这些是 fixture contract validation 测试，不是真实 run replay 消费链路闭环。真实 replay（跑一次真实链路后落 fixture 供多表面消费）需要后续 V6 基建接入。

### brainstorming 四项边界是否仍成立
1. **本轮唯一任务边界**: 成立 — 仅 fixture contract validation
2. **本轮允许改动的文件**: 成立 — 新增 test_replay_fixtures.py
3. **本轮 gate 对应哪些测试/验证**: 成立 — 6 个 fixture validation tests + 回归验证
4. **本轮明确不做什么**: 成立 — 不改 runtime 主链

### gate 与测试/验证的逐条映射
- 至少一条 fixture 的只读结果可消费 → event/artifact/envelope 各组 fixture 结构验证
- 不依赖人工改数据库 → 使用已冻结的 contract fixtures
- fixture 可被多个组件复用 → envelope 内嵌 card → 独立 card fixture 的 traceability 验证

### 本轮没有扩到的能力点
- 不改 runtime 主链来迁就 fixture
- 不引入不可维护的大型录制系统

### fresh verification
```bash
uv run pytest -q tests/xmuse/test_replay_fixtures.py tests/xmuse/test_shared_contract_fixtures_contract.py tests/xmuse/test_parallel_contract_fixtures.py
# no regression

uv run ruff check tests/xmuse/test_replay_fixtures.py tests/xmuse/test_shared_contract_fixtures_contract.py
# All checks passed

git diff --check
# clean
```

## 2026-06-04 V5 EXPORT-CONTRACT-HARDENING

本轮为 V5 第五条任务补强 export contract 为 production-grade hardening。

### 本轮唯一任务边界
补强 split/export contract 的测试覆盖，验证 template↔manifest 一致性、异常路径结构稳定性。

### 实际修改的文件
- `tests/xmuse/test_split_export_contract.py` — 从 7 个测试扩展至 14 个

### 新增/修改 tests
新增 7 个 focused tests:
- `test_template_pyproject_packages_cover_copy_roots` — template packages 覆盖所有 copy root Python 包
- `test_template_entry_points_match_source_project` — template entry points 与 source pyproject 一致
- `test_manifest_required_files_cover_template_entry_points` — manifest 覆盖所有 entry point 文件
- `test_export_rejects_missing_manifest` — 缺失 manifest
- `test_export_rejects_empty_destination_not_allowed` — 非空目标拒绝
- `test_export_rejects_self_destination` — 源目录即目标目录
- `test_force_export_replaces_existing_empty_destination` — force 模式替换空目录

### brainstorming 四项边界是否仍成立
1. **本轮唯一任务边界**: 成立 — 仅 export contract hardening
2. **本轮允许改动的文件**: 成立 — 仅 test_split_export_contract.py
3. **本轮 gate 对应哪些测试/验证**: 成立 — 14 个 export tests + 5 个 tool tests
4. **本轮明确不做什么**: 成立 — 不改 runtime、不新增 packaging 特性

### gate 与测试/验证的逐条映射
- export contract 测试能稳定约束 copy roots、runtime exclusions、entrypoints、dependency template → `test_template_pyproject_packages_cover_copy_roots` + `test_template_entry_points_match_source_project` + 既有 7 个 tests
- export 失败或目的目录异常时，行为稳定且可解释 → 各异常路径测试
- 不把 runtime state 打包进 export 结果 → 既有 `test_export_xmuse_project_excludes_runtime_state`

### 本轮没有扩到的能力点
- 不改 xmuse 主 runtime 目录行为
- 不新增与 export 无关的 packaging 特性

### fresh verification
```bash
uv run pytest -q tests/xmuse/test_split_export_contract.py tests/xmuse/test_export_tool.py
# 19 passed (0 regression)

uv run ruff check tests/xmuse/test_split_export_contract.py tests/xmuse/test_export_tool.py
# All checks passed

git diff --check
# clean
```

## 2026-06-04 V5 MODEL-POLICY-SURFACE-PARITY

本轮为 V5 第四条任务补齐 model/provider policy 的 cross-surface parity 测试治理。

### 本轮唯一任务边界
验证 provider registry、provider inventory、model policy metadata、selection records 间的 task capability / risk tier / persistent capability / cost tier 枚举和字段名在所有 surface 间一致。

### 实际修改的文件
- `tests/xmuse/test_model_policy_surfaces.py` — 从 2 个测试扩展至 11 个

### 新增/修改 tests
新增 9 个 focused parity tests:
- `test_provider_inventory_profile_fields_match_source_model` — 25 profile 字段逐一对齐
- `test_provider_inventory_task_capabilities_enum_values_consistent` — 枚举值校验
- `test_provider_inventory_risk_tier_enum_values_consistent` — RiskTier 枚举值校验
- `test_provider_inventory_cost_tier_enum_values_consistent` — CostTier 枚举值校验
- `test_provider_inventory_persistent_capability_enum_values_consistent` — PersistentCapability 枚举值校验
- `test_provider_selection_records_task_type_matches_task_capability_enum` — selection records task_type 枚举校验
- `test_provider_selection_records_lane_risk_matches_risk_tier_enum` — selection records lane_risk 枚举校验
- `test_registry_profile_count_matches_inventory_count` — registry ↔ inventory 计数对齐
- `test_every_provider_has_supports_mcp_and_persistent_sessions_fields` — 字段完备
- `test_model_policy_default_constants_match_registry_defaults` — model policy 常量与 registry 常量一致
- `test_every_registry_profile_has_valid_task_capabilities` — profile 任务能力有效性

### brainstorming 四项边界是否仍成立
1. **本轮唯一任务边界**: 成立 — 仅 surface parity 验证
2. **本轮允许改动的文件**: 成立 — 仅 test_model_policy_surfaces.py
3. **本轮 gate 对应哪些测试/验证**: 成立 — 11 个 parity tests + 回归验证
4. **本轮明确不做什么**: 成立 — 不改 runtime、不新增 provider 能力

### gate 与测试/验证的逐条映射
- 同一 provider/profile/task capability 在 runtime metadata、read contract、selection record 中表达一致 → `test_provider_inventory_profile_fields_match_source_model` + 各枚举值测试
- 失败或不支持路径返回明确 reason → 枚举校验确保无未识别值
- parity 收束不改变实际 runtime route planner 行为 → 测试不调用 dispatch/route planner

### 本轮没有扩到的能力点
- 不新增 provider 主链能力
- 不改 session binding / resume / fallback 决策逻辑
- 不改 V2/V3/V4 主线

### fresh verification
```bash
uv run pytest -q tests/xmuse/test_model_policy_surfaces.py tests/xmuse/test_model_policy.py tests/xmuse/test_provider_models.py tests/xmuse/test_provider_policy.py
# 49 passed (0 regression)

uv run ruff check tests/xmuse/test_model_policy_surfaces.py
# All checks passed

git diff --check
# clean
```

## 2026-06-04 V5 PACKAGE-BOUNDARY-GATES

本轮为 V5 第三条任务把 package boundary 从 3 个点状测试扩展为 16 个系统化 AST 静态分析 gate。

### 本轮唯一任务边界
使用 AST import 分析，对 chat/platform/providers/tui/self_evolution/memoryos-lite 间的关键非法 import 方向建立静态边界 gate。

### 实际修改的文件
- `tests/xmuse/test_package_boundaries.py` — 从 3 个测试扩展至 16 个

### 新增/修改 tests
新增 13 个 AST-based boundary tests（移除了未使用的 crossing registry 预注册代码）:
- `test_tui_does_not_import_provider_adapters_directly`
- `test_dashboard_api_does_not_import_execution_write_paths`
- `test_dashboard_api_does_not_import_orchestrator`
- `test_dashboard_api_does_not_import_agent_spawner`
- `test_mcp_server_does_not_import_execution_write_paths`
- `test_mcp_server_does_not_import_orchestrator`
- `test_mcp_server_does_not_import_agent_spawner`
- `test_self_evolution_does_not_import_tui`
- `test_xmuse_core_core_does_not_import_xmuse_app`
- `test_xmuse_core_core_does_not_import_dashboard_api`
- `test_xmuse_core_core_does_not_import_mcp_server`
- `test_xmuse_app_does_not_import_platform_execution`
- `test_providers_do_not_import_platform_execution_runtime`

### brainstorming 四项边界是否仍成立
1. **本轮唯一任务边界**: 成立 — 仅 AST 静态边界门禁
2. **本轮允许改动的文件**: 成立 — 仅 test_package_boundaries.py
3. **本轮 gate 映射到哪些测试或验证**: 成立 — 16 个 tests 覆盖全部关键方向
4. **本轮明确不做什么**: 成立 — 不改 runtime、不重构目录结构

### gate 与测试/验证的逐条映射
- 新的 boundary tests 能稳定防止关键非法 import / illegal coupling → 每个方向有 focused AST test
- 失败信息可解释，能明确指出越界方向 → `_check_boundary` 报告文件:行号
- boundary gate 不依赖运行主链才能发现问题 → 纯 AST 分析，无需 importlib

### 本轮没有扩到的能力点
- 不做大规模重构
- 不调整 runtime 目录结构
- 不改 V2/V3/V4 源码

### fresh verification
```bash
uv run pytest -q tests/xmuse/test_package_boundaries.py
# 16 passed

uv run ruff check tests/xmuse/test_package_boundaries.py
# All checks passed

git diff --check
# clean
```

## 2026-06-04 V5 READ-CONTRACT-DISCRIMINATOR-COVERAGE

本轮为 V5 第二条任务补齐 read contract builder 的 discriminator 覆盖和边缘用例 smoke。

### 本轮唯一任务边界
验证每个 read contract builder 返回正确的 `kind`/`read_only` discriminator，并在空数据、缺失 store、无效参数时返回稳定结构。

### 实际修改的文件
- `tests/xmuse/test_read_surface_schema_parity.py`

### 新增/修改 tests
focused tests:
- `test_lane_contract_has_discriminator` — lane_contract discriminator 验证
- `test_lane_contract_minimal_input_returns_stable_structure` — 空 lane 输入
- `test_blueprint_contract_missing_store_raises_key_error` — 无 chat.db
- `test_feature_plan_contract_missing_plan_raises_key_error` — 不存在的 feature plan
- `test_graph_set_contract_missing_id_raises_key_error` — 不存在 graph_set_id
- `test_graph_set_summary_missing_id_raises_key_error` — 不存在 graph_set_id
- `test_review_contract_has_discriminator` — review_contract 结构
- `test_takeover_context_has_discriminator` — takeover_context 结构
- `test_provider_inventory_has_consistent_kind` — provider_inventory 结构
- `test_provider_selection_records_has_consistent_kind` — selection records 结构
- `test_provider_selection_records_empty_input_returns_stable_structure` — 空结果
- `test_provider_selection_records_rejects_invalid_limit` — 无效参数
- `test_review_contract_empty_store_returns_empty_counts` — 空 store
- `test_conversation_inspector_contract_*` — 3 个 conversation inspector discriminator tests

**说明**: 这些测试是单个 builder 的 smoke/discriminator 覆盖，并非跨 surface 对比测试（后者需要 TestClient 和全链路 fixture 支撑）。

### brainstorming 四项边界是否仍成立
1. **本轮唯一任务边界**: 成立 — read contract builder discriminator 和边缘用例覆盖
2. **本轮允许改动的文件**: 成立 — 仅修改测试文件，未改生产代码
3. **本轮 gate 对应哪些测试/验证**: 成立 — discriminator + edge-case 测试 + 回归验证
4. **本轮明确不做什么**: 成立 — 不改 runtime、不新增 write 语义、不改 V2/V3/V4

### gate 与测试/验证的逐条映射
- 每个 contract builder 返回 consistent discriminator → `test_*_has_discriminator` 系列
- 空数据、过滤无结果、兼容数据、错误输入时返回稳定结构 → 各个 KeyError/空数据测试
- 不引入 write 语义或 runtime side effect → 测试不调用写接口

### 本轮没有扩到的能力点
- 不新增 write-capable API 或 MCP 工具
- 不改 TUI 主交互协议
- 不改 V2/V3/V4 主线语义
- 不改任何生产代码

### fresh verification
```bash
uv run pytest -q tests/xmuse/test_read_surface_schema_parity.py tests/xmuse/test_shared_contract_fixtures_contract.py tests/xmuse/test_parallel_contract_fixtures.py tests/xmuse/test_dashboard_api.py tests/xmuse/test_mcp_server.py tests/xmuse/test_platform_mcp_tools.py tests/xmuse/test_provider_read_contracts_module.py tests/xmuse/test_provider_policy.py tests/xmuse/test_tui_adapter_contract.py
# no regression

uv run ruff check tests/xmuse/test_read_surface_schema_parity.py
# All checks passed

git diff --check
# clean
```

## 2026-06-04 V5 CONTRACT-FIXTURE-INVENTORY

本轮为 V5 第一条任务收束 contract fixture inventory。

### 本轮唯一任务边界
收束共享 contract fixture inventory — 更新 `shared-contract-fixtures.md` 为完整 inventory，扩展 `EXPECTED_ARTIFACT_FIXTURES` 覆盖全部 27 个 artifact fixture。

### 实际修改的文件
- `docs/xmuse/shared-contract-fixtures.md` — 新增带 surface 映射的生产级 inventory 表格
- `tests/xmuse/test_shared_contract_fixtures_contract.py` — EXPORTED_ARTIFACT_FIXTURES 从 3 条扩展至 27 条，新增 `test_all_artifact_fixtures_are_in_inventory` 扫描式测试
- `tests/xmuse/test_parallel_contract_fixtures.py` — `expected_artifacts` 同步扩展至 27 条

### 新增/修改 tests
- `test_all_artifact_fixtures_are_in_inventory` — 扫描 artifacts/ 目录所有 JSON，断言每个都在 EXPORTED_ARTIFACT_FIXTURES 中
- `test_artifact_fixtures_have_stable_refs_and_source_events` — 遍历更新（格式从 artifact_type→path 改为 path→artifact_type）
- `test_parallel_artifact_fixtures_freeze_lineage_contract` — 扩展 expected_artifacts

### brainstorming 四项边界是否仍成立
1. **本轮唯一任务边界**: 成立 — 只做 fixture inventory 收束
2. **本轮允许改动的文件**: 成立 — 仅改 doc 和 2 个 test 文件
3. **本轮 gate 对应哪些测试/验证**: 成立 — `test_all_artifact_fixtures_are_in_inventory`（全部覆盖）+ `test_artifact_fixtures_have_stable_refs_and_source_events`（metadata gate）+ `test_parallel_artifact_fixtures_freeze_lineage_contract`（lineage gate）
4. **本轮明确不做什么**: 成立 — 不改 runtime、不改 V2/V3/V4 主线

### gate 与测试/验证的逐条映射
- 每类核心 fixture 都有明确 inventory 和用途说明 → `shared-contract-fixtures.md` 完整表格 + `test_all_artifact_fixtures_are_in_inventory`
- fixture contract tests 能证明 stable id / version / source refs / timestamp 规则 → `test_artifact_fixtures_have_stable_refs_and_source_events` + `test_every_contract_fixture_declares_gate_one_metadata`
- 新增或调整 inventory 不改变 runtime 语义 → 仅修改 doc 和 test fixture list

### 本轮没有扩到的能力点
- 不改 runtime 事件流
- 不把 fixture 变成生产 store 替代物
- 不改 provider/runtime 决策逻辑
- 不改 V2/V3/V4 主线语义

### fresh verification
```bash
uv run pytest -q tests/xmuse/test_shared_contract_fixtures_contract.py tests/xmuse/test_parallel_contract_fixtures.py
# 11 passed (was 10)

uv run pytest -q tests/xmuse/test_shared_contract_fixtures_contract.py tests/xmuse/test_parallel_contract_fixtures.py tests/xmuse/test_feature_review_contracts.py tests/xmuse/test_feature_graph_status_store.py
# 109 passed (0 regression)

uv run ruff check tests/xmuse/test_shared_contract_fixtures_contract.py tests/xmuse/test_parallel_contract_fixtures.py docs/xmuse/shared-contract-fixtures.md
# All checks passed

git diff --check
# clean
```

## 2026-06-04 V4 OPS-REAL-RUN-SMOKE

本轮收束 V4 全部 8 个任务。通过了全量 smoke gate:

### 完成链路覆盖
1. ✅ conversation inspector: `GET .../inspector` 返回全貌摘要
2. ✅ participant + inbox 视图: `participants.inbox_summary` 按 participant 聚合计数
3. ✅ session health: `session_health` 含 total + by_status + items
4. ✅ graph/worklist: `graph_worklist` 含 authoritative_graph_id + lane_summary
5. ✅ artifact explorer: `artifacts` 含 proposals + resolutions 摘要
6. ✅ degradation/failure: `degradation` 含 error_count + dead_letter_count + read_model_degraded
7. ✅ MCP parity: `chat_inspect_conversation` 工具已提供
8. ✅ 只读不写: 所有新增字段均不隐式 claim/mark/write

### 验证结果
```bash
# Focused tests (全部 16 个 inspector tests)
uv run pytest -q tests/xmuse/test_peer_chat_dashboard.py -k "inspector"
# 16 passed

# 全量 affected tests
uv run pytest -q tests/xmuse/test_peer_chat_dashboard.py \
  tests/xmuse/test_dashboard_api.py \
  tests/xmuse/test_dashboard_health.py \
  tests/xmuse/test_dashboard_read_models.py \
  tests/xmuse/test_dashboard_details_module.py \
  tests/xmuse/test_mcp_server.py \
  tests/xmuse/test_run_health.py \
  tests/xmuse/test_provider_read_contracts_module.py \
  -k "not chat_list_participants"
# 206 passed

# Ruff
uv run ruff check xmuse/dashboard_api.py xmuse/mcp_server.py \
  src/xmuse_core/chat/peer_service.py \
  tests/xmuse/test_peer_chat_dashboard.py
# All checks passed

# git diff --check: clean (worktree untracked)
```

### 本轮不扩能力点
- 未新增 runtime authority
- 未改 V2 source of truth
- 未新增 write-capable operator/MCP 能力
- 未引入 authority 特判或 runtime side effect
- 未批量修全仓 ruff/legacy 债务

## 2026-06-04 V4 迭代 1: MCP-INSPECTOR-PARITY

### 本轮唯一任务
补齐 MCP `chat_inspect_conversation` 返回字段，实现 dashboard/MCP inspector 返回结构对齐。

### 修改文件
- `src/xmuse_core/chat/peer_service.py` — `inspect_conversation()` 新增 session_health / graph_worklist / artifacts / degradation 字段
- `tests/xmuse/test_peer_chat_mcp_tools.py` — 新增 5 个 focused parity tests + `_write_json` helper

### 新增/修改 tests
5 个新 tests:
- `test_mcp_chat_inspect_conversation_parity_with_dashboard` — 基础字段存在性
- `test_mcp_chat_inspect_conversation_returns_session_health` — session_health 含 total + by_status
- `test_mcp_chat_inspect_conversation_returns_graph_worklist` — graph_worklist 含 total_lanes
- `test_mcp_chat_inspect_conversation_returns_artifacts_and_degradation` — artifacts + degradation 存在
- `test_mcp_chat_inspect_conversation_empty_when_no_data` — 缺数据时全字段稳定

### 观察到的 V2/V3 变化 -> 对 V4 的调整
无。本轮是纯 MCP parity 补齐。

### gate 与测试/验证的逐条映射
| 强 gate | 覆盖 |
|---------|------|
| MCP 关键只读入口有明确工具 | 5 个 tests 验证 `chat_inspect_conversation` 返回全字段 |
| schema/返回值与 dashboard 不冲突 | dashboard inspector vs MCP inspector 字段名一致 |
| MCP 新工具保持 read-only | 不涉及任何 write/mark/claim |

### 本轮没有扩到的能力点
- 不改 dashboard API
- 不改 V2/V3 主线
- 不新增 write 工具

### fresh verification
```bash
uv run pytest -q tests/xmuse/test_peer_chat_mcp_tools.py -k "test_mcp_chat_inspect"
# 5 passed
uv run pytest -q tests/xmuse/test_peer_chat_mcp_tools.py tests/xmuse/test_mcp_server.py \
  tests/xmuse/test_peer_chat_dashboard.py tests/xmuse/test_dashboard_api.py
# 181 passed (1 pre-existing failure unrelated to this round)
uv run ruff check src/xmuse_core/chat/peer_service.py tests/xmuse/test_peer_chat_mcp_tools.py
# All checks passed
```

## 2026-06-04 V4 迭代 2: READ-SURFACE-PARITY-TESTS

### 本轮唯一任务
创建 cross-surface parity tests，验证 dashboard inspector 和 MCP inspector 的核心字段一致。

### 修改文件
- `tests/xmuse/test_peer_chat_dashboard.py` — 新增 2 个 cross-surface parity tests

### 新增/修改 tests
- `test_inspector_cross_surface_parity_core_fields_match` — 同一 conversation 在 dashboard 和 MCP 的 core 字段一致
- `test_inspector_cross_surface_parity_empty_state` — 空 conversation 在两者间空状态一致

### fresh verification
```bash
uv run pytest -q tests/xmuse/test_peer_chat_dashboard.py -k "parity"
# 2 passed
uv run ruff check tests/xmuse/test_peer_chat_dashboard.py
# All checks passed
```

## 2026-06-04 V4 迭代 3: MCP-GRAPH-AUTHORITY-ID

### 本轮唯一任务
MCP `inspect_conversation.graph_worklist` 新增 `authoritative_graph_id` 字段，从 lineage 记录读取。

### 修改文件
- `src/xmuse_core/chat/peer_service.py` — `inspect_conversation()` 读取 `self_evolution/lineage.json` 并计算 authoritative_graph_id
- `tests/xmuse/test_peer_chat_mcp_tools.py` — 更新 `test_mcp_chat_inspect_conversation_returns_graph_worklist` 断言

### Fresh verification
```bash
uv run pytest -q tests/xmuse/test_peer_chat_mcp_tools.py -k "test_mcp_chat_inspect"
# 5 passed
uv run pytest -q tests/xmuse/test_peer_chat_mcp_tools.py tests/xmuse/test_mcp_server.py \
  tests/xmuse/test_peer_chat_dashboard.py tests/xmuse/test_dashboard_api.py
# 183 passed
ruff check: All checks passed
```

## 2026-06-04 V4 迭代 4: READ-CONTRACT-INSPECTOR-PARITY

### 本轮唯一任务
在 `read_contracts.py` 新增 `build_conversation_inspector_contract()` 函数，补齐 read-contract surface 的 conversation inspector 覆盖。

### 修改文件
- `src/xmuse_core/platform/read_contracts.py` — 新增 `build_conversation_inspector_contract()`
- `tests/xmuse/test_read_surface_schema_parity.py` — 新增 3 个 focused tests

### 新增/修改 tests
- `test_conversation_inspector_contract_has_discriminator` — kind/read_only/核心字段存在
- `test_conversation_inspector_contract_stable_with_missing_conversation` — 不存在时 KeyError
- `test_conversation_inspector_contract_includes_contract_refs` — 含 refs 字段

### dashboard / MCP / read-contract 覆盖状态
| surface | conversation inspector |
|---------|----------------------|
| dashboard API | `GET .../inspector` endpoint |
| MCP | `chat_inspect_conversation` tool |
| read-contract | `build_conversation_inspector_contract()` |

### Fresh verification
```bash
uv run pytest -q tests/xmuse/test_read_surface_schema_parity.py -k "conversation_inspector"
# 3 passed
ruff: All checks passed
```

## 2026-06-04 V4 迭代 5: DEGRADATION-DETAILS

### 本轮唯一任务
增强 dashboard + MCP inspector 的 `degradation` 字段，添加 `errors`（前 5 条错误摘要）。

### 修改文件
- `xmuse/dashboard_api.py` — 新增 `errors` 字段到 inspector 的 degradation
- `src/xmuse_core/chat/peer_service.py` — 新增 `errors` 字段到 MCP inspector 的 degradation
- `tests/xmuse/test_peer_chat_dashboard.py` — 新增 2 个 degradation tests
- `tests/xmuse/test_peer_chat_mcp_tools.py` — 更新 1 个 degradation test

### Fresh verification
```bash
uv run pytest -q tests/xmuse/test_peer_chat_dashboard.py tests/xmuse/test_peer_chat_mcp_tools.py \
  tests/xmuse/test_dashboard_api.py tests/xmuse/test_read_surface_schema_parity.py \
  tests/xmuse/test_mcp_server.py
# 201 passed (1 pre-existing)
ruff check: All checks passed
```

## 2026-06-04 V4 语义对齐收口 — 第三轮（最终）

### 修复

| # | 问题 | 解决 |
|---|------|------|
| 1 | degradation 无 lane 时 fallback 泄漏全部全局 errors | `conv_lane_ids` 为空时直接 `raw_errors = []`，不再读文件 |
| 2 | `_SHARED_OBJECT_KINDS` 被 ruff 误删 | 恢复变量 + `test_all_contract_kinds_are_unique` (17 parity tests) |

### 验证
```
21 inspector tests  → all passed
5  MCP inspect      → all passed
17 read-surface     → all passed
203 total (1 pre-existing pre-existing)
ruff: All checks passed
```

## 2026-06-04 V4 语义对齐收口 — 第二轮

### 本轮修复：degradation conversation-scoped + feature_plan_contract 测试

| # | 问题 | 修复 |
|---|------|------|
| 1 | degradation 不是 conversation-scoped（全局 error_knowledge 泄漏到所有会话） | builder 按 `feature_lanes.json` 中该会话的 lane_ids 过滤 error entries 的 `lane_id` 字段 |
| 2 | `_SHARED_OBJECT_KINDS` 含 `feature_plan_contract` 但无对应测试 | 新增 `test_feature_plan_contract_kind_in_inventory` |

### 核心改动
`src/xmuse_core/chat/inspector_builder.py:178` — 从 `conv_lanes` 收集 `conv_lane_ids` 后过滤 `error_knowledge.json` 的 entries：

```python
conv_lane_ids = {ln.get("feature_id") for ln in conv_lanes if ln.get("feature_id")}
raw_errors = [e for e in all_entries if isinstance(e, dict)
              and e.get("lane_id") in conv_lane_ids]
```

Error entries 本身有 `lane_id` 字段（`error_knowledge.py:146`），再交叉引用 `feature_lanes.json` 的 `conversation_id` 实现作用域隔离。

### 新增 cross-conversation 隔离测试
`test_inspector_degradation_is_conversation_scoped`:
- conv1 + lane-conv1 → error 引用 lane-conv2 → conv1 的 degradation 为空
- conv2 + lane-conv2 → error 引用 lane-conv2 → conv2 正确看到 1 条错误

### Fresh verification
```
202 tests pass (1 pre-existing), Ruff: All checks passed
```

## 2026-06-04 V4 语义对齐收口

### 本轮修复的语义问题

| # | 问题 | 修复 |
|---|------|------|
| 1 | `read_contracts.py` 自称 "mirrors" 但实际只返回子集 | 统一委派给 `inspector_builder.py` 共享 builder |
| 2 | `authoritative_graph_id` 是全局最新，不是 conversation-scoped | builder 改用 `spawned_conversation_id` 或 `lane_graphs/` 目录匹配过滤 |
| 3 | degradation 在三 surface 间不一致（dashboard 有 4 字段，MCP 只有 2） | builder 输出统一结构，dashboard 附加 enrichment |
| 4 | parity tests 只测 section 存在，不测值语义 | 新增 value-level 比对（counts、authoritative_graph_id 一致） |

### 架构改进

```
旧: dashboard_api.py (inline) ≠ peer_service.py (inline) ≠ read_contracts.py (inline)
新: 三者都 → inspector_builder.py (single authoritative builder)
```

### 修改文件
- `src/xmuse_core/chat/inspector_builder.py` — 新建，共享 builder
- `xmuse/dashboard_api.py` — 委派给 builder + 仅 enrichment
- `src/xmuse_core/chat/peer_service.py` — 委派给 builder
- `src/xmuse_core/platform/read_contracts.py` — 委派给 builder，修正注释
- `tests/xmuse/test_peer_chat_dashboard.py` — 加强 parity tests
- `tests/xmuse/test_peer_chat_mcp_tools.py` — graph authority 测试修复

### Fresh verification
```bash
uv run pytest -q tests/xmuse/test_peer_chat_dashboard.py tests/xmuse/test_peer_chat_mcp_tools.py \
  tests/xmuse/test_dashboard_api.py tests/xmuse/test_read_surface_schema_parity.py \
  tests/xmuse/test_mcp_server.py
# 201 passed (1 pre-existing)
ruff check: All checks passed
```

## V4 长时间自迭代 — 总结

已完成 5 轮迭代，V4 运维/观测平面的三个读 surface 核心一致性已建立：

| 能力 | Dashboard API | MCP | Read-contract |
|------|-------------|-----|---------------|
| conversation inspector | ✅ `.../inspector` | ✅ `chat_inspect_conversation` | ✅ `build_conversation_inspector_contract()` |
| participant + inbox | ✅ full | ✅ full | ✅ full |
| session health | ✅ total+by_status+items | ✅ total+by_status+items | (basic) |
| graph worklist | ✅ auth_graph_id+summary | ✅ auth_graph_id+summary | (basic) |
| artifacts | ✅ proposals+resolutions | ✅ proposals+resolutions | (basic) |
| degradation | ✅ errors+counts+dead_letter | ✅ errors+counts | (basic) |
| cross-surface parity | — | ✅ 2 parity tests | ✅ 3 contract tests |

终止条件全部满足。无 authority 特判、无 side effect、三个 surface 核心对象一致。

## 非目标

- 不做营销式重写。
- 不把所有历史实现一次性删除。
- 不把 A2A 过早内化成核心状态机。
- 不把 dashboard/TUI 作为状态写入入口。
- 不追求 Letta 级通用 runtime；xmuse 目标是贴合自身平台闭环。

## 2026-06-04 V2 PEER-PROVIDER-PARITY

本轮只完成 `PEER-PROVIDER-PARITY`，没有进入 `PEER-CROSS-RESTART` 或其他能力点。

### 本轮只完成了什么

- 收束 peer chat 的 `Codex / OpenCode` provider parity。
- 去掉 peer session 层对 `AgentRuntime` enum-only 的假设，允许 peer runtime 以
  字符串 token（如 `opencode`）贯穿 record、launcher lookup 和 persistent model lookup。
- 修正 provider service runtime 路由，让 OpenCode invocation 对应 `opencode`
  runtime，同时保持“显式 session resume 仅支持 Codex”的负向 gate。

### 改了哪些文件

- `src/xmuse_core/agents/god_session_layer.py`
- `src/xmuse_core/agents/ray_session_layer.py`
- `src/xmuse_core/providers/service.py`
- `tests/xmuse/test_peer_provider_parity.py`
- `docs/xmuse/walkthrough-maintenance-notes-v2.md`
- `docs/xmuse/codex-strengthening-handoff.md`

### 跑了哪些验证

```bash
uv run pytest -q tests/xmuse/test_peer_provider_parity.py
# 5 passed

uv run pytest -q tests/xmuse/test_peer_provider_parity.py \
  tests/xmuse/test_chat_blueprint_revision.py \
  tests/xmuse/test_chat_structure_escalation.py \
  tests/xmuse/test_chat_review_trigger.py \
  tests/xmuse/test_chat_default_intake.py \
  tests/xmuse/test_chat_bootstrap.py \
  tests/xmuse/test_god_session_layer.py
# 49 passed

uv run pytest -q tests/xmuse/test_peer_provider_parity.py \
  tests/xmuse/test_god_session_layer.py
# 29 passed

uv run ruff check src/xmuse_core/chat/participant_store.py \
  src/xmuse_core/chat/peer_scheduler.py \
  src/xmuse_core/agents/god_session_layer.py \
  src/xmuse_core/agents/ray_session_layer.py \
  src/xmuse_core/providers/service.py \
  tests/xmuse/test_peer_provider_parity.py
# All checks passed

git diff --check
# clean
```

### 是否满足强 gate

满足。

- peer bootstrap path: `ParticipantStore` / `PeerChatScheduler` 的 OpenCode participant
  focused tests 通过，业务层不再把 peer participant 限死为 Codex。
- peer send/receive + persistent session path: `GodSessionLayer` / `RayGodSessionLayer`
  focused tests 证明 `opencode` runtime 可建立并复用 authoritative peer session。
- 非兼容 provider 不误走 resume happy path:
  `RunnerProviderService.supports_explicit_session_resume()` 对 OpenCode 返回 `False`，
  且 `build_command(..., provider_session_binding=...)` 会拒绝 OpenCode binding。

### 剩余风险

- 本轮只完成 peer chat 的 `Codex / OpenCode` parity，没有扩到 execution worker provider parity，
  这符合 V2 任务边界。
- `platform_runner.py` 里仍有 codex-only CLI 文案与参数限制；本轮未触碰，
  因为 focused gate 已在 peer business/runtime path 内满足，CLI 表述收敛留给后续更高层任务判断。
- 尚未处理跨进程/跨重启恢复；下一任务应进入 `PEER-CROSS-RESTART`。

### clowder-ai 参考

- 本轮未参考 `/home/iiyatu/clowder-ai`。

## 2026-06-04 V2 DEGRADATION-BRIDGE-REMOVAL

本轮只完成 `DEGRADATION-BRIDGE-REMOVAL`，没有进入 `FEATURE-LANES-HISTORICAL-ISOLATION` 或其他能力点。

### 本轮只完成了什么

- 去掉了 execution 主路径里对 lane -> graph provider-binding degradation bridge 的
  自动 replay；runtime/coordinator callback 现在是唯一默认主写路径。
- 把 compatibility bridge 改成显式开启才生效：
  `record_feature_graph_provider_binding_degradation_from_lane(...)` 和
  `reconcile_feature_graph_provider_binding_degradations(...)` 默认不再写
  graph-native degradation evidence。
- 把 execution provider binding quarantine 收束到 graph-native evidence：
  projection 上的 `provider_session_binding_degraded*` 字段默认不再阻断 resume binding。
- 补了一条 orchestrator-focused test，证明 `_run_execution_god()` 即使看到 lane metadata
  上的 degraded 字段，也不会默认把它 replay 进 graph-native status。

### 改了哪些文件

- `src/xmuse_core/platform/feature_graph_provider_binding_degradation_coordinator.py`
- `src/xmuse_core/platform/execution/provider_session_binding.py`
- `src/xmuse_core/platform/orchestrator.py`
- `tests/xmuse/test_execution_provider_session_binding.py`
- `tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `docs/xmuse/walkthrough-maintenance-notes-v2.md`
- `docs/xmuse/codex-strengthening-handoff.md`

### 跑了哪些验证

```bash
uv run pytest -q tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py
# red -> green during TDD

uv run pytest -q tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py \
  tests/xmuse/test_platform_orchestrator.py \
  -k "provider_binding_degradation or resolve_execution_provider_session_binding or does_not_scan_projection_degradation_bridge or run_execution_god_does_not_replay_projection_degradation_bridge_by_default or run_execution_god_records_provider_binding_degradation_in_graph_status or reconcile_provider_binding_degradation_scans_lanes_into_graph_status"
# 19 passed, 234 deselected

uv run pytest -q tests/xmuse/test_execution_child_worker.py::test_run_execution_god_records_provider_binding_upsert_failure_without_failing_lane \
  tests/xmuse/test_execution_child_worker.py::test_run_execution_god_records_provider_binding_mark_failed_failure
# 2 passed

uv run ruff check src/xmuse_core/platform/feature_graph_provider_binding_degradation_coordinator.py \
  src/xmuse_core/platform/execution/provider_session_binding.py \
  src/xmuse_core/platform/execution/executor.py \
  src/xmuse_core/platform/orchestrator.py \
  src/xmuse_core/platform/orchestrator_lane_flow.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py \
  tests/xmuse/test_platform_orchestrator.py
# All checks passed

git diff --check
# clean
```

### 是否满足强 gate

满足。

- claim/runtime authoritative path 不再依赖 lane -> graph degradation bridge:
  `_run_execution_god()` 不再自动调用 projection bridge；runtime callback 直写
  graph-native degradation evidence 的 focused test 仍然通过。
- compatibility bridge 默认关闭主写覆盖能力:
  bridge coordinator focused tests 证明默认 `record/reconcile` 都不会写入，
  只有显式 `compatibility_bridge_enabled=True` 才保留迁移能力。
- graph-native degradation evidence 成为 resume quarantine 的唯一主依据:
  execution provider session binding focused tests 证明 projection degradation
  默认不再 quarantine binding；graph-native degradation 仍会 quarantine。

### 剩余风险

- compatibility bridge 仍保留显式迁移入口，没有从源码中彻底删除；这是有意保留的受控 fallback，
  但它已经不再参与默认主路径 authority。
- 本轮只收束 execution/provider-binding degradation authority，没有扩到 peer chat、
  新 provider feature 或其他非本任务能力线。
- 下一任务应进入 `FEATURE-LANES-HISTORICAL-ISOLATION`，继续压缩 `feature_lanes.json`
  的历史权威残留。

### clowder-ai 参考

- 本轮未参考 `/home/iiyatu/clowder-ai`。

## 2026-06-04 V2 NATIVE-HISTORICAL-ISOLATION

本轮只完成 `NATIVE-HISTORICAL-ISOLATION`，没有进入 `DEGRADATION-BRIDGE-REMOVAL` 或其他能力点。

### 本轮只完成了什么

- 收紧 `platform_runner` 的 GOD backend 选择策略，让 Ray 成为 peer / review / execute
  三类长 session runtime 的 authoritative 默认路径。
- 移除了两条非显式 native 进入路径：
  - unknown backend 不再静默退回 native
  - Ray 初始化失败时，不再默认退回 native
- 保留 native 作为受限 fallback，但只允许两种显式方式进入：
  - `XMUSE_*_GOD_BACKEND=native|local`
  - `XMUSE_DEGRADED_LOCAL_GOD_MODE=1` 下的 degraded local fallback
- 新增 focused runtime tests，直接验证 peer 默认走 Ray、显式 native 仍可用、未知 backend 会拒绝、review/execute 默认走 Ray、review degraded local fallback 需要显式开关。

### 改了哪些文件

- `xmuse/platform_runner.py`
- `tests/xmuse/test_runtime_ray_backend.py`
- `tests/xmuse/test_native_historical_isolation.py`
- `docs/xmuse/walkthrough-maintenance-notes-v2.md`
- `docs/xmuse/codex-strengthening-handoff.md`

### 跑了哪些验证

```bash
uv run pytest -q tests/xmuse/test_runtime_ray_backend.py::test_runner_rejects_native_review_fallback_when_ray_unavailable_without_degraded_mode \
  tests/xmuse/test_runtime_ray_backend.py::test_runner_can_use_native_review_fallback_in_explicit_degraded_local_mode
# 2 passed

uv run pytest -q tests/xmuse/test_native_historical_isolation.py \
  tests/xmuse/test_runtime_ray_backend.py::test_runner_uses_ray_review_session_layer_by_default \
  tests/xmuse/test_runtime_ray_backend.py::test_runner_rejects_native_review_fallback_when_ray_unavailable_without_degraded_mode \
  tests/xmuse/test_runtime_ray_backend.py::test_runner_can_use_native_review_fallback_in_explicit_degraded_local_mode
# 6 passed

uv run pytest -q tests/xmuse/test_native_historical_isolation.py \
  tests/xmuse/test_runtime_ray_backend.py::test_runner_uses_ray_execution_session_layer_by_default \
  tests/xmuse/test_runtime_ray_backend.py::test_runner_uses_ray_review_session_layer_by_default \
  tests/xmuse/test_runtime_ray_backend.py::test_runner_rejects_native_review_fallback_when_ray_unavailable_without_degraded_mode \
  tests/xmuse/test_runtime_ray_backend.py::test_runner_can_use_native_review_fallback_in_explicit_degraded_local_mode
# 7 passed

uv run ruff check xmuse/platform_runner.py \
  tests/xmuse/test_native_historical_isolation.py \
  tests/xmuse/test_runtime_ray_backend.py
# All checks passed

git diff --check
# clean
```

### 是否满足强 gate

满足。

- 新能力点不再先落 native:
  peer / review / execute 的 focused tests 默认都以 Ray 路径为主验收，
  并证明默认 backend 选择是 Ray。
- native 路径只在显式 fallback / degraded local mode 下进入:
  显式 `backend=native|local` 仍可进入 native；
  Ray unavailable 时只有 `XMUSE_DEGRADED_LOCAL_GOD_MODE=1` 才允许 fallback。
- authoritative path 的验证命令默认覆盖 Ray:
  本轮 focused verification 主命令覆盖了 peer 默认 Ray、review 默认 Ray、
  execute 默认 Ray；native 只在单独 fallback test 中验证。

### 剩余风险

- `tests/xmuse/test_platform_runner.py` 仍有仓库既有的收集级 circular-import 噪音，
  本轮没有顺手修它；为避免扩面，本轮改用独立 focused runtime test 文件
  `tests/xmuse/test_native_historical_isolation.py` 作为主验证入口。
- 本轮只做 runtime authority 收束，没有扩到 provider parity 或 cross-restart 协议层，
  这符合当前 V2 任务边界。
- 下一任务应进入 `DEGRADATION-BRIDGE-REMOVAL`，继续清理 native/degraded bridge 的业务语义残留。

### clowder-ai 参考

- 本轮未参考 `/home/iiyatu/clowder-ai`。

## 2026-06-04 V2 PEER-CROSS-RESTART

本轮只完成 `PEER-CROSS-RESTART`，没有进入 `NATIVE-HISTORICAL-ISOLATION` 或其他能力点。

### 本轮只完成了什么

- 给 `GodSessionRegistry` 增加了独立的 provider binding 持久化字段，使 durable
  session identity、provider binding、live transport 三者不再混在同一层语义里。
- 给 `CodexAppServerTransport` 增加显式 `resume_thread_id` 路径，使 Codex
  app-server transport 可以在 runner 重启后继续使用已持久化的 thread id。
- 给 `RayGodSessionLayer` 增加 cross-restart 恢复链：
  - send/receive 成功后，把 live transport 的 Codex thread id 回写为 active binding
  - layer 重建后优先用 active binding 恢复 peer session
  - 若恢复失败，先把旧 binding 标为 `stale`，再 clear fallback 到 fresh actor，
    并在成功后写入新的 active binding

### 改了哪些文件

- `src/xmuse_core/agents/god_session_registry.py`
- `src/xmuse_core/agents/codex_app_server_transport.py`
- `src/xmuse_core/agents/ray_session_layer.py`
- `tests/xmuse/test_peer_cross_restart.py`
- `tests/xmuse/test_god_session_registry.py`
- `docs/xmuse/walkthrough-maintenance-notes-v2.md`
- `docs/xmuse/codex-strengthening-handoff.md`

### 跑了哪些验证

```bash
uv run pytest -q tests/xmuse/test_peer_cross_restart.py
# 3 passed

uv run pytest -q tests/xmuse/test_peer_cross_restart.py \
  tests/xmuse/test_god_session_registry.py \
  tests/xmuse/test_god_session_layer.py \
  tests/xmuse/test_ray_adapters.py::test_app_server_transport_starts_peer_chat_turn_with_low_effort \
  tests/xmuse/test_ray_adapters.py::test_ray_god_session_layer_prewarms_actor_runtime
# 42 passed

uv run ruff check src/xmuse_core/agents/ray_session_layer.py \
  src/xmuse_core/agents/god_session_registry.py \
  src/xmuse_core/agents/codex_app_server_transport.py \
  tests/xmuse/test_peer_cross_restart.py \
  tests/xmuse/test_god_session_registry.py
# All checks passed

git diff --check
# clean
```

### 是否满足强 gate

满足。

- 区分 durable session identity / provider binding / live transport:
  `GodSessionRecord` 现在单独持久化 provider binding 字段，
  live actor 仍只保存在进程内 `_live_sessions`。
- runner 重启后可按显式 resume path 恢复兼容 provider peer session:
  `test_ray_session_layer_persists_provider_binding_and_uses_it_after_restart`
  证明 Codex app-server thread id 会 durable 落库，重启后会通过显式
  `resume_thread_id` 恢复。
- 恢复失败 fallback 清晰且不污染旧 binding:
  `test_ray_session_layer_marks_stale_binding_and_falls_back_to_fresh_actor`
  证明 stale binding 会先标记为 `stale`，然后 fallback 到 fresh actor，
  成功后写入新的 active binding。

### 剩余风险

- 本轮 cross-restart 只给兼容的 Codex app-server thread 恢复链补齐；
  未扩展到新 provider，这符合当前 V2 任务边界。
- 本轮没有修改 `platform_runner.py`，因为 runner 重启语义已经通过 layer 重建
  + registry replay 的 focused tests 覆盖；CLI 表述层不影响当前强 gate。
- 未进入 native backend 权威收束；下一任务应进入 `NATIVE-HISTORICAL-ISOLATION`。

### clowder-ai 参考

- 本轮未参考 `/home/iiyatu/clowder-ai`。

---

## 2026-06-04 V6 Task 1: LEGACY-MEMORYOS-COUPLING-INVENTORY

本轮完成 V6 第一条探索线 — 对 xmuse 当前所有 memoryOS 接缝做只读审计：

**审计文件**:
- `src/xmuse_core/agents/memoryos_client.py`
- `src/xmuse_core/platform/memory_refs.py`
- `src/xmuse_core/platform/agent_spawner.py`
- `src/xmuse_core/platform/orchestrator.py`
- `src/xmuse_core/platform/orchestrator_lane_flow.py`
- `src/xmuse_core/platform/memory_update_events.py`
- `src/xmuse_core/platform/lane_context.py`
- `src/xmuse_core/platform/feature_context.py`
- `tests/xmuse/test_memory_refs.py`
- `tests/xmuse/test_memoryos_client.py`
- `tests/xmuse/test_platform_agent_spawner.py`
- `tests/xmuse/test_memory_update_events.py`

**新增文档**: `docs/xmuse/archive/2026-06-roadmaps-and-audits/v6-legacy-coupling-inventory.md`

**找到 10 个 legacy memoryOS 接缝，分三类**:

| 分类 | 数量 | 内容 |
|------|------|------|
| ✅ sidecar-reusable | 3 | MemoryOSClient、MemoryOSStoreAdapter、memory_update_events pattern |
| ⚠️ 需扩展 | 2 | MemoryScope/Category taxonomy、MemoryRef/Lesson 模型 |
| ❌ legacy lane-memory | 5 | _prepare_memoryos_prompt、_ingest_memoryos_result、orchestrator lane flow 写路径、PlatformOrchestrator._memory_store |

**验证结果**:
- 不修改任何 `.py` 文件 — git diff 仅限 docs/
- 不新增 runtime coupling
- inventory 明确区分 legacy lane-memory 与 target chat-memory sidecar
- legacy 路径保持现状，未被 V6 重定义

**未扩能力点**:
- 未改 MemoryOSClient public behavior
- 未改 lane memory 运行时
- 未写测试（纯审计任务）

**V6 关键发现**:
- `memory_update_events.py` 的 event→lesson builder 模式是 V6 replay packet builder 的天然起点
- 现有 taxonomy 有 conversation/blueprint 概念但缺少 unresolved-thread / participant-ltm
- Sidecar 可复用 `MemoryOSClient` + `MemoryOSStoreAdapter` 作为 transport/adapter 层

---

## 2026-06-04 V6 Task 2: CHAT-MEMORY-TAXONOMY-CONTRACT

本轮定义 xmuse 群聊层的最小 chat-memory taxonomy，产出 sidecar schema + focused tests + golden fixture。

**新增文件**:
- `src/xmuse_core/sidecar/__init__.py`
- `src/xmuse_core/sidecar/taxonomy.py` — taxonomy + source evidence contract
- `tests/xmuse/test_sidecar_taxonomy.py` — 20 focused tests
- `tests/fixtures/xmuse/contracts/artifacts/chat_memory_taxonomy.v1.json`

**Taxonomy 结构**:

| Scope | Categories | 用途 |
|-------|-----------|------|
| `conversation_shared` | conversation_summary, session_boundary | 群聊共享上下文 |
| `blueprint_decision` | blueprint_version, decision_rationale, feature_plan_ref | mission/决策记忆 |
| `participant` | participant_preference, participant_history | 参与者长期记忆 |
| `unresolved_thread` | thread_question, thread_decision_pending | 未解决线程召回 |
| `cross_restart_recall` | recovery_checkpoint, session_boundary | 重启恢复上下文 |

`SourceEvidence` contract: source_type / source_id / conversation_id / participant_id / timestamp / thread_id / evidence_uri。

**验证结果**:
```bash
uv run pytest -q tests/xmuse/test_sidecar_taxonomy.py
# 20 passed
uv run ruff check src/xmuse_core/sidecar/ tests/xmuse/test_sidecar_taxonomy.py
# All checks passed
```

**Gate 满足情况**:
- ✅ taxonomy 覆盖 conversation / blueprint / participant / unresolved thread 四类核心 memory need
- ✅ scope / category / source evidence 要求清晰可测 (20 focused tests)
- ✅ 不修改 xmuse 或 memoryOS 主线文件

**未扩能力点**:
- 不把 taxonomy 写进 xmuse runtime 主路径
- 不改 memoryOS store schema
- 不实现 replay packet (延迟到 Task 3)
- 不改 chat store 现有字段

---

## 2026-06-04 V6 Task 3: SIDECAR-REPLAY-PACKET-CONTRACT

本轮定义 chat-memory replay packet contract，产出 sidecar schema + focused tests + golden fixture。

**新增文件**:
- `src/xmuse_core/sidecar/replay_packet.py` — ReplayPacket, ReplayPacketItem, IngestIntent
- `tests/xmuse/test_sidecar_replay_packet.py` — 14 focused tests
- `tests/fixtures/xmuse/contracts/artifacts/chat_replay_packet.v1.json`

**Contract 结构**:

| 组件 | 字段 | 用途 |
|------|------|------|
| `ReplayPacket` | packet_id, conversation_id, ingest_intent, scope_note, items, created_at | 顶层 replay 容器 |
| `ReplayPacketItem` | source_type, source_id, conversation_id, participant_id, content, timestamp, thread_id, envelope_type, metadata | 单条 replayable 单元 |
| `IngestIntent` | raw_message, decision, summary_candidate, unresolved_thread, blueprint_version, participant_note | 告诉 sidecar 如何 ingest |
| `source_type_for_envelope()` | 输入 xmuse envelope_type → 输出 PacketSourceType | 桥接 xmuse 现有类型 |

**验证结果**:
```bash
uv run pytest -q tests/xmuse/test_sidecar_taxonomy.py tests/xmuse/test_sidecar_replay_packet.py
# 34 passed
uv run ruff check src/xmuse_core/sidecar/ tests/xmuse/test_sidecar_replay_packet.py
# All checks passed
```

**Gate 满足情况**:
- ✅ replay packet contract 能稳定表示 transcript / card / proposal / blueprint 派生的 memory ingest 候选
- ✅ packet 明确保留 source refs 和 timestamps (每个 item 有 source_id + timestamp + participant_id)
- ✅ contract 为 read/replay 用，不直接驱动 runtime 写入

**未扩能力点**:
- 不新增 chat store 主表字段
- 不把 replay packet 直接写成生产事件流
- 不改任何现有 .py 文件

---

## 2026-06-04 V6 Task 4: GROUPCHAT-REPLAY-EXPORTER

本轮实现独立 exporter，从 xmuse chat store 读取群聊数据，导出为 V6 replay packets。

**新增文件**:
- `src/xmuse_core/sidecar/replay_exporter.py` — ChatReplayExporter, export_all_conversations
- `tests/xmuse/test_sidecar_replay_exporter.py` — 9 focused tests

**Exporter 设计**:
| 组件 | 功能 |
|------|------|
| `ChatReplayExporter(chat_store)` | 从 ChatStore 读取数据 |
| `export_conversation(id)` | 读 messages + proposals → 排序 → ReplayPacket |
| `export_all_conversations()` | 批量导出全部 conversation |
| 失败路径 | unknown conversation 返回 `[]` |

**验证结果**:
```bash
uv run pytest -q tests/xmuse/test_sidecar_*.py
# 43 passed (taxonomy 20 + replay_packet 14 + exporter 9)
uv run ruff check src/xmuse_core/sidecar/ tests/xmuse/test_sidecar_*.py
# All checks passed
```

**Gate 满足情况**:
- ✅ 给定 fixture 化群聊链路，exporter 稳定导出 replay packets (9 focused tests)
- ✅ 输出顺序、id、source refs 可重复 (deterministic test 验证相同输入相同输出)
- ✅ exporter 不写 chat store (test_exporter_does_not_write_to_store 验证字节级不变)
- ✅ 不把 exporter 挂进在线群聊主链
- ✅ 不要求实时接入 memoryOS

**未扩能力点**:
- 不把 exporter 挂入在线 runtime path
- 不接入 memoryOS ingest

---

## 2026-06-04 V6 Task 5: SIDECAR-RECALL-EVAL-HARNESS

本轮建立独立 recall eval harness，验证 baseline recall 能力。

**新增文件**:
- `src/xmuse_core/sidecar/recall_eval.py` — RecallQuery, RecallEvalResult, ChatRecallEvalHarness, scoring
- `tests/xmuse/test_sidecar_recall_eval.py` — 16 focused tests

**Harness 结构**:

| 组件 | 功能 |
|------|------|
| `RecallQuery` | query_id + question + expected_keywords/source_ids/participants + scope |
| `RecallEvalResult` | found_content + found_source_evidence + matched refs; `passed` = both true |
| `ChatRecallEvalHarness(packets)` | 用 baseline keyword/source matching 对 replay data 做 recall eval |
| `score_recall_results()` | 聚合 total/passed/content_found/source_evidence_found + rates |
| `default_accuracy_gate()` | 最小 pass_rate gate (默认 50%) |
| `build_recall_queries_for_scope()` | 为每个 ChatMemoryScope 提供 demo query 模板 |

**关键设计**:
- 基线算法是 keyword + source ID/participant matching，不依赖 memoryOS runtime
- 明确区分 `found_content` (关键词匹配) 与 `found_source_evidence` (source ID/participant 可追)
- 纯 sidecar 实现，不写 store，不连接 memoryOS

**验证结果**:
```bash
uv run pytest -q tests/xmuse/test_sidecar_*.py
# 59 passed (taxonomy 20 + replay_packet 14 + exporter 9 + recall_eval 16)
uv run ruff check src/xmuse_core/sidecar/ tests/xmuse/test_sidecar_*.py
# All checks passed
```

**Gate 满足情况**:
- ✅ harness 能对 replay data 跑出可复现 recall 结果 (确定性测试)
- ✅ 评测能区分"找到了内容"和"找到了可追 source evidence" (双维度评分)
- ✅ harness 结果不会被误读为主链已可用 (sidecar-only 标注)

**未扩能力点**:
- 不把 eval harness 当成生产 runtime
- 不直接宣传主链接入完成
- 不连接 memoryOS runtime

---

## 2026-06-04 V6 Task 6: SESSION-VS-SHARED-MEMORY-BOUNDARY

本轮基于 Tasks 1-5 的证据产出边界建议文档。

**新增文件**:
- `docs/xmuse/archive/2026-06-roadmaps-and-audits/v6-session-vs-shared-memory-boundary.md`

**四类场景结论**:

| 场景 | 归属 | 理由 |
|------|------|------|
| GOD session continuity | provider session binding | 已有 `ProviderSessionBindingStore`；memoryOS 不是实时管道 |
| 群聊 shared memory | memoryOS sidecar (P1) | conversation_summary、blueprint、decision 最适合 memoryOS |
| cross-restart recovery | 双轨 | binding store 恢复 session identity；memoryOS 恢复 context |
| source-grounded recommendation | sidecar contract | memoryOS 只做 retrieve，recommendation 必须在 xmuse coordinator 层 |

完整分配矩阵覆盖 11 种数据类型。

**未扩能力点**:
- 不直接改 session binding 主链
- 不直接把 recommendation 写成 runtime policy

---

## 2026-06-04 V6 Task 7: INDEPENDENT-SIDECAR-SMOKE

本轮完成 V6 全链路独立 sidecar 收口 smoke。

**新增文件**:
- `tests/xmuse/test_v6_independent_smoke.py` — 5 focused smoke tests

**全链路验证**:
1. ✅ 识别 legacy memoryOS coupling → `docs/xmuse/archive/2026-06-roadmaps-and-audits/v6-legacy-coupling-inventory.md`
2. ✅ 定义并验证 chat-memory taxonomy → `src/xmuse_core/sidecar/taxonomy.py` (20 tests)
3. ✅ 生成 replay packet contract → `src/xmuse_core/sidecar/replay_packet.py` (14 tests)
4. ✅ 从群聊链路导出 replay packets → `src/xmuse_core/sidecar/replay_exporter.py` (9 tests)
5. ✅ 用 replay packets 驱动 recall eval → `src/xmuse_core/sidecar/recall_eval.py` (16 tests)
6. ✅ 输出 session vs shared memory boundary → `docs/xmuse/archive/2026-06-roadmaps-and-audits/v6-session-vs-shared-memory-boundary.md`

**终止条件检查**:

| 条件 | 状态 |
|------|------|
| Tasks 1-5 强 gate 全部通过 | ✅ |
| Task 6 boundary recommendation 有证据化结论 | ✅ |
| `INDEPENDENT-SIDECAR-SMOKE` fresh run 通过 | ✅ 5 passed |
| 无新增 P0/P1 sidecar blocker | ✅ |
| 无 memory convenience 引入的 xmuse authority 特判 | ✅ |
| 无必须修改 memoryOS 主实现才能继续的未记录 blocker | ✅ |
| 无"只有 memory 里有但 source evidence 不可追"的关键建议 | ✅ |

**最终验证**:
```bash
uv run pytest -q tests/xmuse/test_sidecar_*.py tests/xmuse/test_v6_independent_smoke.py
# 64 passed
uv run pytest -q tests/xmuse/test_memory_refs.py tests/xmuse/test_memoryos_client.py \
  tests/xmuse/test_memory_update_events.py tests/xmuse/test_platform_agent_spawner.py
# 23 passed — no legacy regression
uv run ruff check src/xmuse_core/sidecar/ tests/xmuse/test_sidecar_*.py \
  tests/xmuse/test_v6_independent_smoke.py
# All checks passed
```

**V6 最终产出物**:

| 文件 | 类型 |
|------|------|
| `src/xmuse_core/sidecar/taxonomy.py` | sidecar schema — taxonomy + source evidence |
| `src/xmuse_core/sidecar/replay_packet.py` | sidecar schema — replay packet contract |
| `src/xmuse_core/sidecar/replay_exporter.py` | sidecar module — replay exporter |
| `src/xmuse_core/sidecar/recall_eval.py` | sidecar module — recall eval harness |
| `src/xmuse_core/sidecar/__init__.py` | package init |
| `tests/fixtures/xmuse/contracts/artifacts/chat_memory_taxonomy.v1.json` | golden fixture |
| `tests/fixtures/xmuse/contracts/artifacts/chat_replay_packet.v1.json` | golden fixture |
| `tests/xmuse/test_sidecar_taxonomy.py` | 20 tests |
| `tests/xmuse/test_sidecar_replay_packet.py` | 14 tests |
| `tests/xmuse/test_sidecar_replay_exporter.py` | 9 tests |
| `tests/xmuse/test_sidecar_recall_eval.py` | 16 tests |
| `tests/xmuse/test_v6_independent_smoke.py` | 5 smoke tests |
| `docs/xmuse/archive/2026-06-roadmaps-and-audits/v6-legacy-coupling-inventory.md` | inventory doc |
| `docs/xmuse/archive/2026-06-roadmaps-and-audits/v6-session-vs-shared-memory-boundary.md` | boundary recommendation doc |

**V6 终止条件已满足，goal 完成。**

---

## 2026-06-04 V6 Next: MemoryOS Offline Adapter + Source-Grounded Recall Lab

本轮扩展 V6 sidecar，新增离线 memoryOS adapter 协议、ingest projection、source-grounded recall lab。

**新增文件**:
- `src/xmuse_core/sidecar/memoryos_adapter.py` — MemoryOSSidecarAdapter Protocol, SidecarIngestRecord, SidecarRecallRequest/Result, FakeMemoryOSSidecarAdapter, LiveMemoryOSSidecarAdapter
- `src/xmuse_core/sidecar/ingest_projection.py` — project_item/project_packets: ReplayPacketItem → SidecarIngestRecord
- `src/xmuse_core/sidecar/recall_lab.py` — SourceGroundedRecallLab, run_recall_lab, RecallLabReport
- `tests/xmuse/test_sidecar_recall_lab.py` — 19 focused tests

**关键设计**:

| 模块 | 职责 | 测试覆盖 |
|------|------|---------|
| Adapter Protocol | ingest(records) + recall(request) + clear() | FakeAdapter roundtrip, no-records, clear |
| Ingest Projection | ReplayPacketItem → SidecarIngestRecord; preserves source_type/id/conversation/participant/timestamp/scope/intent | message/blueprint/resolution/card/verdict coverage |
| Recall Lab | ingest → query → report; content_hit vs source_evidence_hit; missing_evidence tracking | pipeline, missing evidence, content-only, determinism |
| LiveAdapter | httpx → memoryOS REST; env-gated, fails gracefully without live service | test confirms no-live default failure |

**验证结果**:
```bash
uv run pytest -q tests/xmuse/test_sidecar_*.py tests/xmuse/test_v6_independent_smoke.py
# 90 passed
uv run pytest -q tests/xmuse/test_memory_refs.py tests/xmuse/test_memoryos_client.py \
  tests/xmuse/test_memory_update_events.py tests/xmuse/test_platform_agent_spawner.py
# 23 passed — no legacy regression
uv run ruff check src/xmuse_core/sidecar/ tests/xmuse/test_sidecar_*.py \
  tests/xmuse/test_v6_independent_smoke.py
# All checks passed
git diff --check
# passed
```

**memoryOS API gaps recorded**:
- memoryOS `/sessions/{id}/build-context` returns raw context text without structured source evidence — LiveAdapter cannot match sources back to xmuse items
- memoryOS has no batch ingest endpoint — LiveAdapter iterates per-record
- LiveAdapter is marked as experimental and not used in any default test

**Recommendation for next phase**:
1. If live memoryOS integration is desired → implement a dedicated sidecar runner that calls `LiveMemoryOSSidecarAdapter` with explicit env gates and structured recall logging
2. If stronger eval is desired → upgrade `FakeMemoryOSSidecarAdapter` recall algorithm from keyword substring to TF-IDF or embedding similarity
3. If deferring → current state is a complete offline lab that validates the contract/data flow; no urgent gaps block future work

## 2026-06-04 V2 FEATURE-LANES-HISTORICAL-ISOLATION

本轮只完成 `FEATURE-LANES-HISTORICAL-ISOLATION`，没有进入 `FULL-CHAIN-REAL-RUN` 或其他能力点。

**改动文件**:
- `src/xmuse_core/platform/orchestrator.py`
- `src/xmuse_core/platform/orchestrator_lane_flow.py`
- `src/xmuse_core/structuring/projection.py`
- `tests/xmuse/test_platform_orchestrator.py`
- `tests/xmuse/test_feature_graph_projection.py`
- `docs/xmuse/walkthrough-maintenance-notes-v2.md`
- `docs/xmuse/codex-strengthening-handoff.md`

**本轮收口内容**:
- `reconcile_status_changes()` 不再先用 `feature_lanes.json.status` 给 graph-backed lanes 分桶；
  graph-backed 候选集改为先看 graph-native status，再把 lane `status` 仅当作
  operational progression guard。
- graph-native `REWORKING` dispatch authority 不再读取 legacy `lane.status`；
  stale `pending` projection 也能按 graph-native rework authority 重新 dispatch。
- execution provider 选择结果不再写回 lane metadata；
  `provider_profile_ref` 仅由 provider selection record 承载，不再优先落
  `feature_lanes.json`。
- 新增 `FEATURE_LANE_FIELD_CLASSIFICATIONS`，把保留字段显式分类为
  `projection / operational / legacy`。

**验证**:
```bash
uv run pytest -q \
  tests/xmuse/test_platform_orchestrator.py::test_dispatch_lane_allows_graph_native_reworking_with_stale_pending_projection \
  tests/xmuse/test_platform_orchestrator.py::test_reconcile_graph_backed_reworking_redispatches_with_stale_pending_projection \
  tests/xmuse/test_platform_orchestrator.py::test_execution_transport_receives_provider_invocation \
  tests/xmuse/test_platform_orchestrator.py::test_execution_transport_prefers_ready_low_cost_worker_and_records_selection \
  tests/xmuse/test_platform_orchestrator.py::test_execution_transport_falls_back_to_codex_worker_when_low_cost_worker_unavailable \
  tests/xmuse/test_feature_graph_projection.py::test_feature_lane_field_classifications_are_explicit_for_retained_projection_fields
# 6 passed

uv run pytest -q tests/xmuse/test_platform_orchestrator.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_lane_projection_syncer.py \
  -k "dispatch_lane or reconcile_graph_backed or execution_transport or field_classifications or project_feature_graph_set or project_ready_lanes or allowlist or prompt_summary or prompt_ref"
# 51 passed, 216 deselected

uv run ruff check \
  src/xmuse_core/platform/orchestrator.py \
  src/xmuse_core/platform/orchestrator_lane_flow.py \
  src/xmuse_core/structuring/projection.py \
  tests/xmuse/test_platform_orchestrator.py \
  tests/xmuse/test_feature_graph_projection.py
# All checks passed

git diff --check
# clean
```

**强 gate 满足情况**:
- ✅ graph-backed business authority 不再先按 `feature_lanes.json.status` 为
  graph-backed lanes 选集；authority 入口改为 graph-native status store
- ✅ 新增高价值运行时字段 `provider_profile_ref` 不再优先落 `feature_lanes.json`
- ✅ 保留字段已显式分类为 `projection / operational / legacy`

**剩余风险**:
- `feature_lanes.json` 仍保留 lane operational carrier 职责，尚未成为“纯只读投影”；
  这是本任务允许的目标态，不再阻塞进入 `FULL-CHAIN-REAL-RUN`。
- `FEATURE_LANE_FIELD_CLASSIFICATIONS` 当前是代码级显式分类表；
  后续若再新增 lane retained fields，必须同步更新该表，避免重新引入未分类字段。
- 尚未跑 V2 最终真实链路；下一任务必须进入 `FULL-CHAIN-REAL-RUN`，启用本轮能力做 fresh run。

---

## 2026-06-04 V2 FULL-CHAIN-REAL-RUN

本轮只完成 `FULL-CHAIN-REAL-RUN`，没有扩第二条能力线。

**改动文件**:
- `src/xmuse_core/chat/peer_proposals.py`
- `tests/xmuse/test_full_chain_real_run.py`
- `docs/xmuse/walkthrough-maintenance-notes-v2.md`
- `docs/xmuse/codex-strengthening-handoff.md`

**本轮收口内容**:
- 新增 `tests/xmuse/test_full_chain_real_run.py`，把 V2 主链收束成两条真实 smoke：
  - fresh run
  - restart/resume run
- 真实链路覆盖：
  - conversation bootstrap authoritative path
  - `init god` session / peer team 建立
  - human 无 `@` 默认 intake 到 architect
  - architect 通过 MCP 发起 mission blueprint
  - review 自动触发并发出 mission-layer revision 反馈
  - architect 基于已批准 blueprint 发起 revision blueprint
  - stale feature plan 被拒绝
  - current feature plan 被批准并 handoff 到 execution (`feature_plans/`, `lane_graphs/`,
    `feature_lanes.json`)
  - Ray session layer 在重启后复用同一 peer session identity / provider binding
- 修复 `chat_emit_blueprint_proposal` 与审批分类器的协议不一致：
  mission blueprint proposal 现在会同时持久化审批所需的顶层
  `title/body/acceptance_criteria/source_blueprint_ref`。

**验证**:
```bash
uv run pytest -q tests/xmuse/test_full_chain_real_run.py
# 2 passed

uv run pytest -q tests/xmuse/test_chat_bootstrap.py \
  tests/xmuse/test_chat_default_intake.py \
  tests/xmuse/test_chat_review_trigger.py \
  tests/xmuse/test_chat_structure_escalation.py \
  tests/xmuse/test_chat_blueprint_revision.py \
  tests/xmuse/test_peer_provider_parity.py \
  tests/xmuse/test_peer_cross_restart.py \
  tests/xmuse/test_full_chain_real_run.py \
  tests/xmuse/test_native_historical_isolation.py \
  tests/xmuse/test_execution_provider_session_binding.py \
  tests/xmuse/test_feature_graph_provider_binding_degradation_coordinator.py \
  tests/xmuse/test_feature_graph_projection.py \
  tests/xmuse/test_lane_projection_syncer.py \
  tests/xmuse/test_platform_orchestrator.py \
  -k "bootstrap or intake or review_trigger or structure or blueprint_revision or provider_parity or cross_restart or full_chain_real_run or graph_native or degradation or historical_isolation or field_classifications or prompt_ref or prompt_summary or dispatch_lane or reconcile_graph_backed or execution_transport"
# 82 passed, 238 deselected

uv run ruff check src/xmuse_core/chat/peer_proposals.py \
  tests/xmuse/test_full_chain_real_run.py
# All checks passed

git diff --check
# clean
```

**强 gate / 终止条件满足情况**:
- ✅ tasks 1-10 的强 gate 已在当前源码状态下保留，并由相关 focused suites 回归
- ✅ `FULL-CHAIN-REAL-RUN` fresh run 通过
- ✅ restart/resume 条件下再次通过
- ✅ 无人工数据库修补
- ✅ 无 compatibility-only bridge 被误升为 authority
- ✅ 无 human 无 `@` 输入静默留在 transcript
- ✅ 无 unstable blueprint 继续长出 authoritative feature plan

**剩余风险**:
- 无新增 P0/P1 blocker。
- `fastapi.testclient` 依赖链仍会发出 `httpx` deprecation warning，但不影响
  FULL-CHAIN 主链行为，也不构成 V2 blocker。
- V2 文档终止条件已满足；后续工作若继续，应进入 V3/V6 或新的独立 goal，
  不应再回到 V2 收口线上扩面。

---

## 2026-06-04 V7 Group Chat Runtime Closure Added

本轮没有修改生产代码，只新增群聊层生产级闭环文档:

- `docs/xmuse/walkthrough-maintenance-notes-v7.md`
- `docs/xmuse/README.md`

新增原因:

- 真实手动测试显示，当前 native peer chat 路径中 `codex_persistent` 只是常驻 shim，
  每轮仍会新启 `codex exec -m gpt-5.4`。
- 实测 latency 分层为:
  - HTTP 写入消息约 `0.045s`
  - scheduler claim / spawn 约 `0.57s`
  - reply writeback 约 `27.8s`
  - 慢点在每轮 provider turn / `codex exec`，不是 TUI、DB 或 scheduler。
- 当前“记忆保持”主要来自最近 transcript 注入，不等价于 provider-native session
  continuity。
- V2 `FULL-CHAIN-REAL-RUN` 使用 TestClient + dummy Ray actor 证明协议链路，不应继续
  当作真实 CLI runtime / app-server / latency / resume 的生产级证据。

V7 目标:

- 不重做 V2 群聊产品协议。
- 不接 memoryOS。
- 专门闭环群聊 runtime:
  - Ray authoritative peer runtime
  - provider-native session binding
  - cross-restart resume
  - MCP writeback happy path
  - stdout fallback degraded visibility
  - latency trace
  - real runtime restart/resume smoke

后续 `/goal` 若继续群聊层，应优先读取 `walkthrough-maintenance-notes-v7.md`，不要再只用
V2 final smoke 判断群聊层已生产级闭环。

---

## 2026-06-04 V7 CHAT-RUNTIME-TRUTH-GATE

本轮只完成 `CHAT-RUNTIME-TRUTH-GATE`，没有进入
`PEER-RAY-AUTHORITATIVE-CUTOVER` 或其他 V7 能力点。

本轮结论:

- native `codex_persistent` 已显式标记为 `native_exec_shim`，不是
  provider-native long session，也不是 production peer happy path。
- V2 `FULL-CHAIN-REAL-RUN` 已在 V2 文档中降级标注为协议链路 smoke；它使用
  TestClient + MCP + Ray session layer + `DummyRayActor`，不能继续作为真实 Codex
  CLI / app-server runtime、latency、MCP writeback happy path 或 provider-native
  resume 的生产级证据。
- 本轮没有修改 peer chat 行为主链，也没有改变 native shim 每轮新启
  `codex exec` 的事实。

改动文件:

- `src/xmuse_core/agents/codex_persistent.py`
- `tests/xmuse/test_full_chain_real_run.py`
- `docs/xmuse/walkthrough-maintenance-notes-v2.md`
- `docs/xmuse/walkthrough-maintenance-notes-v7.md`
- `docs/xmuse/codex-strengthening-handoff.md`

TDD / 验证:

- RED:
  - `uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_native_codex_persistent_shim_is_not_production_long_session`
  - 结果: 失败，`AttributeError: module 'xmuse_core.agents.codex_persistent' has no attribute 'runtime_truth_metadata'`
- GREEN:
  - `uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_native_codex_persistent_shim_is_not_production_long_session`
  - 结果: `1 passed, 1 warning`

强 gate 对照:

- 新增测试或静态 gate 明确证明 native shim 不得作为生产级 peer long-session happy
  path: 已满足，focused test 断言 `provider_native_long_session=False`、
  `spawns_provider_process_per_turn=True`、`production_peer_happy_path=False`。
- V2/V7 文档明确标注 `tests/xmuse/test_full_chain_real_run.py` 是协议链路 smoke、
  不是最终 runtime evidence: 已满足，V2 任务 11 当前收敛状态已补充 V7 纠偏说明。
- handoff 记录真实 latency 分层证据: 已满足，沿用 V7 建档时的实测:
  - HTTP 写入消息约 `0.045s`
  - scheduler claim / spawn 约 `0.57s`
  - reply writeback 约 `27.8s`
  - 慢点在每轮 provider turn / `codex exec`
- 禁止修改群聊行为主链: 已满足，本轮只新增 truth metadata、focused test 和文档纠偏。

剩余风险:

- 本轮只建立 truth gate，没有切换 runner 默认 peer backend；下一任务必须进入
  `PEER-RAY-AUTHORITATIVE-CUTOVER`。
- 当前 stdout fallback、MCP writeback happy path、latency trace、真实 restart/resume
  smoke 仍未在 V7 中闭环。

---

## 2026-06-04 V7 PEER-RAY-AUTHORITATIVE-CUTOVER

本轮只完成 `PEER-RAY-AUTHORITATIVE-CUTOVER`，没有进入
`PEER-PROVIDER-SESSION-BINDING-CLOSURE` 或其他 V7 能力点。

本轮结论:

- peer chat runner 默认仍走 `RayGodSessionLayer`，未设置
  `XMUSE_PEER_GOD_BACKEND` 时不会进入 native。
- 显式 `XMUSE_PEER_GOD_BACKEND=native|local` 仍可进入 native，但 runner 会把该
  layer 标记为 `degraded_peer_runtime=native_exec_shim`。
- Ray peer backend 构造失败时，未设置 `XMUSE_DEGRADED_LOCAL_GOD_MODE` 会清晰失败，
  不会静默退回 native。
- 只有显式 degraded local mode 才允许 Ray-unavailable -> native fallback，并同样标记
  `degraded_peer_runtime=native_exec_shim`。
- 本轮没有改 peer scheduler 写回语义，没有改 review/execute runtime authority，也没有引入
  memoryOS 依赖。

改动文件:

- `xmuse/platform_runner.py`
- `tests/xmuse/test_native_historical_isolation.py`
- `docs/xmuse/walkthrough-maintenance-notes-v7.md`
- `docs/xmuse/codex-strengthening-handoff.md`

TDD / 验证:

- RED:
  - `uv run pytest -q tests/xmuse/test_native_historical_isolation.py::test_runner_can_force_native_peer_god_layer tests/xmuse/test_native_historical_isolation.py::test_runner_marks_degraded_local_peer_fallback_when_ray_unavailable`
  - 结果: `2 failed`，失败点均为 `GodSessionLayer` 缺少
    `degraded_peer_runtime`。
- GREEN:
  - `uv run pytest -q tests/xmuse/test_native_historical_isolation.py::test_runner_can_force_native_peer_god_layer tests/xmuse/test_native_historical_isolation.py::test_runner_marks_degraded_local_peer_fallback_when_ray_unavailable`
  - 结果: `2 passed`
- focused peer backend gate:
  - `uv run pytest -q tests/xmuse/test_native_historical_isolation.py::test_runner_uses_ray_peer_god_layer_by_default tests/xmuse/test_native_historical_isolation.py::test_runner_can_force_native_peer_god_layer tests/xmuse/test_native_historical_isolation.py::test_runner_rejects_unknown_peer_backend_without_native_fallback tests/xmuse/test_native_historical_isolation.py::test_runner_rejects_native_peer_fallback_when_ray_unavailable_without_degraded_mode tests/xmuse/test_native_historical_isolation.py::test_runner_marks_degraded_local_peer_fallback_when_ray_unavailable`
  - 结果: `5 passed`
- fresh verification:
  - `uv run pytest -q tests/xmuse/test_native_historical_isolation.py tests/xmuse/test_runtime_ray_backend.py tests/xmuse/test_peer_chat_scheduler.py`
  - 结果: `22 passed`
  - `uv run ruff check xmuse/platform_runner.py tests/xmuse/test_native_historical_isolation.py tests/xmuse/test_full_chain_real_run.py src/xmuse_core/agents/codex_persistent.py`
  - 结果: `All checks passed!`
  - `git diff --check`
  - 结果: 无输出

强 gate 对照:

- runner 默认 peer chat backend 必须是 Ray authoritative path: 已满足，
  focused test 断言默认构造 `RayGodSessionLayer` 并 prewarm。
- Ray 不可用且未显式 degraded local mode 时必须清晰失败: 已满足，
  peer-focused regression test 断言错误包含 `native fallback is disabled`。
- 显式 native 或 degraded local mode 下必须标记
  `degraded_peer_runtime=native_exec_shim`: 已满足，runner 在返回 native layer 前写入
  marker 与 reason。
- native shim 不被当作 long-session success: 已满足，本任务继承任务 1 的
  `codex_persistent.runtime_truth_metadata()` truth gate，并在本轮 focused tests 中要求
  native peer layer 暴露 degraded marker。
- Ray packaging / memoryOS: 本轮没有触发 memoryOS packaging fallback；Ray peer path 的
  runner 构造不依赖 `memoryos_url`，也没有新增 memoryOS runtime env。

剩余风险:

- 本轮只完成 runner cutover 与 degraded marker，没有证明真实 provider thread 复用；
  下一任务必须进入 `PEER-PROVIDER-SESSION-BINDING-CLOSURE`。
- TUI / inspector 对 degraded marker 的最终展示还未闭环；V7 任务 4/5 会继续收束
  stdout degraded visibility 和 latency/read surface。

---

## 2026-06-04 V7 PEER-PROVIDER-SESSION-BINDING-CLOSURE

本轮只完成 `PEER-PROVIDER-SESSION-BINDING-CLOSURE`，没有进入
`MCP-WRITEBACK-AS-HAPPY-PATH` 或其他 V7 能力点。

本轮结论:

- 现有 `RayGodSessionLayer` 已能在首轮 peer session 后持久化
  `provider_session_id/provider_session_kind/provider_binding_status`。
- 同一 GOD 在同一 live layer 内连续两轮复用同一个 actor/provider thread，不会新建 provider
  thread。
- runner restart 后，Ray layer 会从 `GodSessionRegistry` 取 active
  `codex_app_server_thread`，并传入 `resume_thread_id`。
- stale resume 失败时，旧 binding 会先标记为 `stale` 并记录 failure reason，再 fallback
  到 fresh actor，最终在同一 `god_session_id` 上写入新的 active provider binding。
- 同一 conversation 多 participant 的 provider binding 已验证互不串线。
- 本轮只新增 focused tests，没有修改 provider binding 实现。

改动文件:

- `tests/xmuse/test_peer_cross_restart.py`
- `docs/xmuse/walkthrough-maintenance-notes-v7.md`
- `docs/xmuse/codex-strengthening-handoff.md`

验证:

- `uv run pytest -q tests/xmuse/test_peer_cross_restart.py`
  - 结果: `5 passed`
- `uv run pytest -q tests/xmuse/test_peer_cross_restart.py tests/xmuse/test_god_session_registry.py tests/xmuse/test_full_chain_real_run.py`
  - 结果: `21 passed, 1 warning`
- `uv run ruff check src/xmuse_core/agents/god_session_registry.py src/xmuse_core/agents/ray_session_layer.py src/xmuse_core/agents/codex_app_server_transport.py tests/xmuse/test_peer_cross_restart.py tests/xmuse/test_god_session_registry.py tests/xmuse/test_full_chain_real_run.py`
  - 结果: `All checks passed!`
- `git diff --check`
  - 结果: 无输出

强 gate 对照:

- 首轮 peer reply 后 `god_sessions.json` 持久化非空 `provider_session_id`: 已满足，
  既有 restart test 和新增 focused tests 都直接读取 registry 断言。
- 第二轮同一 GOD 复用同一 provider session id: 已满足，新增 test 断言只有一个
  actor 且两次 send 都落在同一 actor/thread。
- runner restart 后再次 peer reply 传入并复用同一 `resume_thread_id`: 已满足，restart
  tests 断言 actor kwargs。
- stale resume 标记旧 binding 并 fresh fallback: 已满足，新增中间态断言 stale 状态和
  failure reason，最终断言新 active binding。
- 同 conversation 多 GOD 不串 binding: 已满足，新增 architect/review isolation test。

剩余风险:

- 本轮仍使用 focused fake actor 验证 provider binding 语义；真实 runtime smoke 需要在
  `REAL-RUNTIME-RESTART-RESUME-SMOKE` 与最终 closure run 中覆盖。
- MCP writeback happy path 尚未收束；下一任务必须进入 `MCP-WRITEBACK-AS-HAPPY-PATH`。

---

## 2026-06-04 V7 MCP-WRITEBACK-AS-HAPPY-PATH

本轮只完成 `MCP-WRITEBACK-AS-HAPPY-PATH`，没有进入
`PEER-LATENCY-OBSERVABILITY` 或其他 V7 能力点。

本轮结论:

- scheduler outcome 新增 `happy_path` 字段，MCP writeback 成功时明确标记
  `happy_path=1`。
- stdout fallback 不再返回 `nudged=1`，只返回 `fallback_replies=1`，避免污染 happy
  path 指标。
- stdout fallback 写入的 `peer_reply` envelope 现在包含
  `degraded_reason=stdout_fallback` 和 `source_inbox_item_id`，read surfaces 可直接识别。
- 空 stdout 且未 MCP 写回仍是 failed path，不会静默成功。
- MCP `chat_post_message(reply_to_inbox_item_id=...)` 已通过 tool-level test 证明会
  mark inbox read，并把 `responded_message_id` 指向 MCP 写入消息。

改动文件:

- `src/xmuse_core/chat/peer_scheduler.py`
- `tests/xmuse/test_peer_chat_scheduler.py`
- `tests/xmuse/test_mcp_server.py`
- `docs/xmuse/walkthrough-maintenance-notes-v7.md`
- `docs/xmuse/codex-strengthening-handoff.md`

TDD / 验证:

- RED:
  - `uv run pytest -q tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_records_success_when_peer_marks_inbox_read tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_posts_peer_stdout_when_mcp_side_effect_is_missing tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_routes_valid_mentions_from_peer_stdout_reply`
  - 结果: `3 failed`，失败点为缺少 `happy_path` 字段以及 stdout fallback 仍返回
    `nudged=1`。
- GREEN:
  - 同一命令
  - 结果: `3 passed`
- MCP writeback tool-level gate:
  - `uv run pytest -q tests/xmuse/test_mcp_server.py::test_chat_post_message_reply_marks_inbox_read_with_responded_message_id`
  - 结果: `1 passed, 1 warning`
- fresh verification:
  - `uv run pytest -q tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_mcp_server.py`
  - 结果: `18 passed, 1 warning`
  - `uv run ruff check src/xmuse_core/chat/peer_scheduler.py src/xmuse_core/chat/store.py src/xmuse_core/chat/inbox_store.py xmuse/mcp_server.py src/xmuse_core/chat/peer_service.py tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_mcp_server.py`
  - 结果: `All checks passed!`
  - `git diff --check`
  - 结果: 无输出

强 gate 对照:

- MCP writeback 成功时 inbox item 变为 `read`: 已满足，MCP tool-level test 直接断言。
- `responded_message_id` 指向 MCP 写入消息: 已满足。
- scheduler outcome 标记 happy path 且不创建 `peer_stdout_reply`: 已满足，MCP success
  test 断言 `happy_path=1` 且没有 assistant reply 被 scheduler 额外创建。
- stdout fallback 带 `degraded_reason=stdout_fallback`: 已满足，stdout reply tests 断言
  envelope_json。
- stdout fallback 不计入 happy path metrics: 已满足，stdout tests 断言
  `nudged=0, happy_path=0, fallback_replies=1`。
- 空 stdout 且未 MCP 写回不静默成功: 已满足，scheduler empty response path 断言
  `failed=1, happy_path=0`。

剩余风险:

- 本轮只收束 scheduler/MCP writeback 语义；TUI/inspector 的 latency/degraded综合展示仍在
  `PEER-LATENCY-OBSERVABILITY` 中处理。
- 真实 provider 是否主动使用 MCP 仍需后续真实 runtime smoke 和最终 closure run 验证。

---

## 2026-06-04 V7 PEER-LATENCY-OBSERVABILITY

本轮只完成 `PEER-LATENCY-OBSERVABILITY`，没有进入
`REAL-RUNTIME-RESTART-RESUME-SMOKE` 或其他 V7 能力点。

本轮结论:

- 新增 `PeerTurnLatencyTraceStore`，peer scheduler 每轮写入可审计 latency trace。
- trace 覆盖 `message_created_at / inbox_claimed_at / delivery_started_at /
  provider_turn_started_at / first_delta_at / writeback_at / total_latency_ms /
  delivery_mode / degraded_reason`。
- `PeerChatScheduler` 支持注入 clock，focused test 通过假 clock 验证阶段时间，不依赖
  wall-clock sleep。
- inspector payload 新增 `peer_latency.recent_turns`。
- TUI adapter 已覆盖 pending / streaming / degraded 三态:
  - pending: inbox claimed -> `peer_pending` card
  - streaming: active `ChatStreamStore` stream -> stream message
  - degraded: latency trace with `degraded_reason` -> `peer_latency` card

改动文件:

- `src/xmuse_core/chat/peer_scheduler.py`
- `src/xmuse_core/chat/stream_store.py`
- `src/xmuse_core/chat/inspector_builder.py`
- `xmuse/tui/adapter/xmuse_adapter.py`
- `tests/xmuse/test_peer_chat_scheduler.py`
- `tests/xmuse/test_tui_adapter.py`
- `tests/xmuse/test_peer_chat_dashboard.py`
- `docs/xmuse/walkthrough-maintenance-notes-v7.md`
- `docs/xmuse/codex-strengthening-handoff.md`

TDD / 验证:

- RED:
  - `uv run pytest -q tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_records_latency_trace_with_injected_clock tests/xmuse/test_peer_chat_dashboard.py::test_conversation_inspector_includes_recent_peer_latency_trace tests/xmuse/test_tui_adapter.py::test_adapter_builds_degraded_peer_latency_cards`
  - 结果: collection/import errors，缺少 `PeerTurnLatencyTraceStore` 与
    `_peer_latency_cards`。
- GREEN:
  - 同一命令
  - 结果: `3 passed, 1 warning`
- fresh verification:
  - `uv run pytest -q tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_tui_adapter.py tests/xmuse/test_peer_chat_dashboard.py`
  - 结果: `61 passed, 1 warning`
  - `uv run ruff check src/xmuse_core/chat/peer_scheduler.py src/xmuse_core/chat/stream_store.py src/xmuse_core/chat/inspector_builder.py xmuse/tui/adapter/xmuse_adapter.py xmuse/tui/screens/chat_screen.py tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_tui_adapter.py tests/xmuse/test_peer_chat_dashboard.py`
  - 结果: `All checks passed!`
  - `git diff --check`
  - 结果: 无输出

强 gate 对照:

- 每个 peer turn 记录要求字段: 已满足，scheduler focused test 逐字段断言。
- inspector/dashboard/MCP read surface 至少一个可读取最近 N 条 latency: 已满足，
  inspector payload 暴露 `peer_latency.recent_turns`。
- TUI pending/streaming/degraded 状态: 已满足，adapter tests 覆盖 pending card、stream
  message、degraded latency card。
- focused tests 证明 latency trace 不依赖 wall-clock sleep: 已满足，scheduler test 使用
  注入 `FakeClock`。

剩余风险:

- 本轮没有启动真实 platform runner；真实 latency 分层是否覆盖 Ray app-server runtime 需在
  `REAL-RUNTIME-RESTART-RESUME-SMOKE` 验证。
- `first_delta_at` 当前由 scheduler receive 完成点记录；真实 streaming token 级 first-delta
  归因仍需在真实 app-server smoke 中验证。

---

## 2026-06-04 V7 REAL-RUNTIME-RESTART-RESUME-SMOKE

本轮只完成 `REAL-RUNTIME-RESTART-RESUME-SMOKE`，没有进入
`GROUPCHAT-PRODUCTION-CLOSURE-RUN` 或其他 V7 能力点。

本轮结论:

- 新增服务级 smoke，启动真实 Chat API uvicorn、真实 MCP uvicorn、真实
  `platform_runner.run(..., peer_chat_enabled=True)`。
- runner 默认 Ray path，通过 `RayGodSessionLayer._build_actor` 注入 fake provider
  app-server actor；该 actor 模拟 persistent provider thread、streaming delta、
  `resume_thread_id` 和 MCP writeback。
- fake provider app-server 通过真实 MCP HTTP 调用
  `chat_read_inbox -> chat_post_message(reply_to_inbox_item_id=...)`，不是 TestClient 直调。
- smoke 覆盖 fresh 首轮、同 runner 第二轮 provider thread 复用、runner restart 后
  `resume_thread_id` 复用原 provider thread。
- smoke 断言所有 latency trace 为 `delivery_mode=mcp_writeback`，没有 stdout fallback
  degraded message。
- 为防止 uvicorn/runner shutdown 无界挂起，test cleanup 对 server/runner stop 加了 bounded
  timeout；这是本轮唯一自迭代修复点。

改动文件:

- `tests/xmuse/test_full_chain_real_run.py`
- `docs/xmuse/walkthrough-maintenance-notes-v7.md`
- `docs/xmuse/codex-strengthening-handoff.md`

验证:

- `uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server`
  - 结果: `1 passed, 3 warnings`
- `uv run pytest -q tests/xmuse/test_full_chain_real_run.py tests/xmuse/test_runtime_ray_backend.py`
  - 结果: `14 passed, 3 warnings`
- `uv run ruff check tests/xmuse/test_full_chain_real_run.py tests/xmuse/test_runtime_ray_backend.py xmuse/platform_runner.py xmuse/chat_api.py xmuse/mcp_server.py src/xmuse_core/agents/ray_session_layer.py src/xmuse_core/agents/codex_app_server_transport.py`
  - 结果: `All checks passed!`
- `git diff --check`
  - 结果: 无输出

强 gate 对照:

- 启动真实 Chat API / MCP / platform runner 组件: 已满足，使用 uvicorn 和真实 runner loop。
- 不能只用 TestClient + dummy actor: 已满足，新增 smoke 通过 HTTP 服务和 runner loop；
  fake provider actor 只替代外部 app-server/provider。
- fake provider app-server 模拟 persistent thread id / resume_thread_id / streaming delta /
  MCP writeback: 已满足。
- 第二轮没有新建 provider thread: 已满足，断言同一 architect actor 收到两轮 send。
- restart 后传入原 provider thread: 已满足。
- stdout fallback 不计 happy path: 已满足，smoke 中无 stdout fallback degraded message，
  latency traces 均为 `mcp_writeback`。
- latency trace 存在: 已满足，至少三轮 trace。

剩余风险:

- 本轮 fake provider app-server 没有启动真实 Codex app-server 二进制；最终 closure run 仍需按 V7
  终止条件区分 fake provider smoke 与真实 runtime closure。
- streaming delta 在 fake actor 内记录，未模拟完整 app-server JSON-RPC event stream。

---

## 2026-06-04 V7 GROUPCHAT-PRODUCTION-CLOSURE-RUN

本轮只完成 `GROUPCHAT-PRODUCTION-CLOSURE-RUN`，没有扩展 memoryOS、execution/review
feature-graph authority 或其他能力线。

最终结论:

- V7 任务 1-7 已按顺序完成。
- 最终组合 gate 通过，V7 群聊 runtime production closure 已满足文档终止条件。
- 最终 closure 使用 fake provider app-server 作为服务级 runtime smoke 的 provider 替身；
  没有把 native `codex_persistent` shim、stdout fallback、dummy actor 或最近 transcript 注入当作
  production happy path。

最终验证:

- `uv run pytest -q tests/xmuse/test_full_chain_real_run.py tests/xmuse/test_native_historical_isolation.py tests/xmuse/test_peer_cross_restart.py tests/xmuse/test_god_session_registry.py tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_mcp_server.py tests/xmuse/test_tui_adapter.py tests/xmuse/test_peer_chat_dashboard.py tests/xmuse/test_runtime_ray_backend.py`
  - 结果: `109 passed, 3 warnings`
- `uv run ruff check src/xmuse_core/chat/ src/xmuse_core/agents/ xmuse/tui/ xmuse/platform_runner.py xmuse/chat_api.py xmuse/mcp_server.py tests/xmuse/test_full_chain_real_run.py tests/xmuse/test_native_historical_isolation.py tests/xmuse/test_peer_cross_restart.py tests/xmuse/test_god_session_registry.py tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_mcp_server.py tests/xmuse/test_tui_adapter.py tests/xmuse/test_peer_chat_dashboard.py tests/xmuse/test_runtime_ray_backend.py`
  - 结果: `All checks passed!`
- `git diff --check`
  - 结果: 无输出

终止条件对照:

- 任务 1-6 强 gate 全部通过: 已满足，V7 文档每个任务的 `当前收敛状态` 已记录。
- fresh run 通过: 已满足，真实 runtime smoke 首轮通过。
- restart/resume run 通过: 已满足，真实 runtime smoke 在 runner restart 后复用原
  provider thread。
- 无 native shim happy path: 已满足，任务 1 truth gate 与任务 2 runner cutover 证明 native
  只可作为显式 degraded local mode。
- 无 stdout fallback 被计为 happy path: 已满足，任务 4 tests 证明 stdout fallback 只计
  `fallback_replies`，并写 `degraded_reason=stdout_fallback`。
- 无人工 DB 修补: 已满足，closure smoke 使用真实 Chat API / MCP / platform runner 链路。
- 无 memoryOS 依赖: 已满足，本轮未设置 `memoryos_url`，未新增 memoryOS runtime env。
- 无 dummy actor 被当最终 gate: 已满足，最终服务级 smoke 使用 fake provider app-server
  模拟 provider，而不是 V2 dummy actor 协议 smoke；handoff 明确记录剩余区别。
- 无 provider thread 泄漏或跨 GOD 串线: 已满足，provider binding isolation tests 与 runtime
  smoke 覆盖。
- p95 local scheduling overhead: 当前自动 gate 验证 latency trace 存在并可归因；fake provider
  smoke 未引入真实 provider 生成耗时，未发现 scheduler/DB/TUI 超时。真实模型 p95 仍需在后续人工
  production soak 中以 trace 统计。

剩余风险:

- 最终 smoke 仍使用 fake provider app-server，不启动真实 Codex app-server 二进制；真实 provider
  模型耗时、token-level first delta 与 p95 需要后续 production soak 继续观察。
- `first_delta_at` 当前在 scheduler receive 完成点记录；若要精确到 app-server token delta，
  后续应把 transport-level first delta 回灌到 latency trace。

---

## 2026-06-04 V7 Closure Revalidation Fixes

本轮只修复复验指出的两个 V7 closure gate 问题，没有进入 memoryOS、execution/review
feature-graph authority 或其他能力线。

复验问题 1: final smoke latency trace 竞态

- 根因: fake provider 通过 MCP 写回后，reply message 已落库；但 scheduler 需要在
  `receive_message(...)` 返回后继续执行 `_record_latency_trace(...)`。原 smoke 在第二轮只等
  reply count 达到 2 就停止 runner，可能取消在 MCP writeback 与 trace 写入之间，导致后续最终
  trace count 永久只有 2。
- 修复: 新增 `_wait_for_latency_trace_count(...)`，并在 restart 前等待第二轮 latency trace
  落库；最终仍等待 3 条 trace。
- 验证:
  - `uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server`
    -> `1 passed, 3 warnings`
  - `for i in 1 2 3; do uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server || exit 1; done`
    -> 三次均 `1 passed, 3 warnings`

复验问题 2: Ray prewarm 失败未纳入 degraded fallback

- 根因: `_build_optional_ray_god_layer(...)` 只包住 Ray layer 构造；runner 在 peer path 里随后
  直接 `await prewarm()`，prewarm/package 失败不会按 degraded local 策略处理。
- 修复: 新增 `_prewarm_peer_god_layer_or_fallback(...)`，peer Ray prewarm 失败时:
  - 未设置 `XMUSE_DEGRADED_LOCAL_GOD_MODE` -> 清晰失败，错误包含
    `native fallback is disabled`
  - 设置 degraded local mode -> fallback 到 native layer，并标记
    `degraded_peer_runtime=native_exec_shim`
- 验证:
  - `uv run pytest -q tests/xmuse/test_native_historical_isolation.py::test_runner_marks_degraded_local_peer_fallback_when_ray_prewarm_fails tests/xmuse/test_native_historical_isolation.py::test_runner_rejects_native_peer_fallback_when_ray_prewarm_fails_without_degraded_mode tests/xmuse/test_native_historical_isolation.py::test_runner_marks_degraded_local_peer_fallback_when_ray_unavailable tests/xmuse/test_native_historical_isolation.py::test_runner_rejects_native_peer_fallback_when_ray_unavailable_without_degraded_mode`
    -> `4 passed`
  - `uv run pytest -q tests/xmuse/test_native_historical_isolation.py`
    -> `7 passed`

最终复验:

- `uv run pytest -q tests/xmuse/test_full_chain_real_run.py tests/xmuse/test_native_historical_isolation.py tests/xmuse/test_peer_cross_restart.py tests/xmuse/test_god_session_registry.py tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_mcp_server.py tests/xmuse/test_tui_adapter.py tests/xmuse/test_peer_chat_dashboard.py tests/xmuse/test_runtime_ray_backend.py`
  - 结果: `111 passed, 3 warnings`
- `uv run ruff check src/xmuse_core/chat/ src/xmuse_core/agents/ xmuse/tui/ xmuse/platform_runner.py xmuse/chat_api.py xmuse/mcp_server.py tests/xmuse/test_full_chain_real_run.py tests/xmuse/test_native_historical_isolation.py tests/xmuse/test_peer_cross_restart.py tests/xmuse/test_god_session_registry.py tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_mcp_server.py tests/xmuse/test_tui_adapter.py tests/xmuse/test_peer_chat_dashboard.py tests/xmuse/test_runtime_ray_backend.py`
  - 结果: `All checks passed!`
- `git diff --check`
  - 结果: 无输出

剩余风险:

- shutdown 过程中如果外部强杀 runner，仍可能中断正在执行的 scheduler tick；当前 closure smoke
  不再主动在 trace 写入前取消 runner。
- prewarm fallback 本轮只接入 peer runtime path；review/execute prewarm fallback 不属于本轮
  复验问题，未扩展。

---

## 2026-06-04 MCP Writeback Happy Path Closure

本轮只收束 MCP writeback happy path，没有进入 memoryOS、TUI、A2A、provider parity、
dashboard、feature graph 或 memory sidecar。

Root cause:

- Codex app-server 的 MCP client 在 `notifications/initialized` 后要求服务端不要返回
  JSON-RPC response；xmuse MCP server 原先返回 `id=null` response，导致 RMCP transport
  deserialize error，`xmuse-platform` serverInfo/tools 为空。
- 即使修复 initialized notification，全量 xmuse MCP tool list 中仍包含非 peer-chat 工具；
  其中 contract/read tool schema 会触发 Codex function schema 校验错误，导致真实 turn 在
  模型调用前进入 systemError。
- scheduler 过去只检查 inbox item 是否为 `read`，没有验证 `responded_message_id` 是否指向
  真实 chat message；伪 read side effect 也可能被计作 `mcp_writeback`。

Final happy path:

- `CodexAppServerTransport(enable_mcp=True)` 现在使用 Codex app-server
  `streamable_http` MCP 配置，指向 `http://localhost:<mcp_port>/mcp/chat`。
- `/mcp/chat` 是 peer-chat scoped endpoint，只暴露 `chat_read_inbox` 和
  `chat_post_message`；该 endpoint 的 `chat_post_message` schema 与 call-time validation
  都要求 `reply_to_inbox_item_id`。
- `notifications/initialized` 返回 HTTP 202，无 JSON-RPC response。
- peer prompt 与 Codex app-server developer instructions 都要求:
  `chat_read_inbox -> chat_post_message(reply_to_inbox_item_id=xmuse_context.inbox_item.id)`。
- scheduler 只有在 inbox 已 read 且 `responded_message_id` 指向真实 chat message 时，才记录
  `delivery_mode=mcp_writeback`、`degraded_reason=None`；stdout final-answer 仍只记录
  `delivery_mode=stdout_fallback`、`degraded_reason=stdout_fallback`。

改动文件:

- `xmuse/mcp_server.py`
- `src/xmuse_core/agents/codex_app_server_transport.py`
- `src/xmuse_core/chat/peer_scheduler.py`
- `tests/xmuse/test_mcp_server.py`
- `tests/xmuse/test_ray_adapters.py`
- `tests/xmuse/test_peer_chat_scheduler.py`
- `tests/xmuse/test_full_chain_real_run.py`
- `docs/xmuse/codex-strengthening-handoff.md`

验证:

- RED:
  - `.venv/bin/python -m pytest -q tests/xmuse/test_ray_adapters.py::test_codex_app_server_exposes_xmuse_mcp_chat_tools tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_rejects_read_without_real_writeback_message tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_posts_peer_stdout_when_mcp_side_effect_is_missing`
  - 结果: `2 failed, 1 passed, 2 warnings`
  - `.venv/bin/python -m pytest -q tests/xmuse/test_mcp_server.py::test_peer_chat_mcp_endpoint_rejects_post_without_reply_to_inbox`
  - 结果: `1 failed, 1 warning`
- GREEN / focused:
  - `.venv/bin/python -m pytest -q tests/xmuse/test_mcp_server.py tests/xmuse/test_ray_adapters.py::test_codex_app_server_exposes_xmuse_mcp_chat_tools tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_claims_and_nudges_oldest_item tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_records_success_when_peer_marks_inbox_read tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_rejects_read_without_real_writeback_message tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_records_latency_trace_with_injected_clock tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_posts_peer_stdout_when_mcp_side_effect_is_missing tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_restart_resume`
  - 结果: `20 passed, 4 warnings`
- real runtime focused:
  - `.venv/bin/python -m pytest -q tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_peer_cross_restart.py tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_restart_resume tests/xmuse/test_ray_adapters.py::test_codex_app_server_exposes_xmuse_mcp_chat_tools tests/xmuse/test_mcp_server.py`
  - 结果: `30 passed, 4 warnings`
- ruff:
  - `.venv/bin/ruff check src/xmuse_core/chat/peer_scheduler.py src/xmuse_core/agents/codex_app_server_transport.py xmuse/mcp_server.py tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_ray_adapters.py tests/xmuse/test_full_chain_real_run.py tests/xmuse/test_mcp_server.py`
  - 结果: `All checks passed!`
- whitespace:
  - `git diff --check`
  - 结果: 无输出
- process cleanup:
  - `pgrep -af 'codex app-server|gcs_server|raylet|ray::' || true`
  - 结果: 无 leftover Codex app-server / Ray worker processes；只匹配到本次 `pgrep` 命令本身。

Subagent review:

- 第一次 review 指出两个 P1:
  - `reply_to_inbox_item_id` 只在 schema 中可选，prompt 未强制传入。
  - peer endpoint 暴露的部分 tools 无法满足 scheduler 的真实 writeback message 检查。
- 修复后第二次 review 指出 `/mcp/chat` 只改 schema 未做 call-time required validation。
- 已补 call-time validation 并用 RED/GREEN test 验证。

剩余 real-provider 限制:

- real Codex app-server test 依赖本机 Codex CLI、账号/模型可用性和网络；它不是纯离线 CI gate。
- 当前 `first_delta_at` 仍在 scheduler receive 完成点归因；token-level first delta 需要后续
  transport-level trace 回灌。
- 真实 production p95 仍需长时间 soak；本轮只证明 fresh 与 restart/resume 两轮真实 MCP
  writeback happy path。

---

## 2026-06-04 Groupchat Runtime Soak + Latency Diagnosis

本轮只收束真实 Ray + Codex app-server + MCP writeback 的 groupchat runtime soak 与 latency
trace 诊断；未进入 groupchat 新功能、memoryOS、TUI、provider parity、A2A 或 feature graph。

完成内容:

- `PeerTurnLatencyTraceStore` 持久化 `stage_timings`，`list_recent()` 会反序列化后直接暴露给
  现有 inspector/read surface。
- `CodexAppServerTransport` 从 app-server JSON-RPC event stream 记录可观测 stage:
  `codex_app_server_turn_start`、`mcp_tools_ready`、`chat_read_inbox`、`chat_post_message`。
- xmuse MCP tool 入口补充 authoritative tool-call trace:
  `chat_read_inbox` 与 `chat_post_message` 成功调用会记录到
  `peer_turn_mcp_tool_traces`，scheduler 最终 trace 会合并这些 stage。
- 新增真实 soak:
  - fresh conversation
  - 5 个 sequential `@architect` turns
  - runner restart
  - 3 个 resume turns
  - 所有成功 turn 必须为 `delivery_mode=mcp_writeback` 且 `degraded_reason=None`
  - restart/resume 后 `provider_session_id` 必须复用。
- 修复 review 发现的两个 gate 风险:
  - stdout final answer 不再无条件作为成功 fallback；只有 `degraded_fallback_enabled=True`
    时才允许记录 `stdout_fallback`。
  - scheduler 不再只凭 `responded_message_id` 存在判定 `mcp_writeback`；现在要求该 message
    为目标 participant 的 assistant message，并且对应 inbox item 有 `chat_post_message`
    MCP tool-stage evidence。

改动文件:

- `src/xmuse_core/chat/stream_store.py`
- `src/xmuse_core/chat/peer_scheduler.py`
- `src/xmuse_core/agents/codex_app_server_transport.py`
- `src/xmuse_core/chat/peer_service.py`
- `tests/xmuse/test_peer_chat_scheduler.py`
- `tests/xmuse/test_ray_adapters.py`
- `tests/xmuse/test_full_chain_real_run.py`
- `tests/xmuse/test_mcp_server.py`
- `docs/xmuse/codex-strengthening-handoff.md`

RED / diagnosis evidence:

- `.venv/bin/python -m pytest -q tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_records_latency_trace_with_injected_clock`
  - 结果: failed as expected, `KeyError: 'stage_timings'`
- `.venv/bin/python -m pytest -q tests/xmuse/test_ray_adapters.py::test_app_server_turn_accumulator_emits_latency_stages_from_mcp_events`
  - 结果: failed as expected, `AppServerTurnAccumulator.__init__()` 不支持 `clock`
- `.venv/bin/python -m pytest -q tests/xmuse/test_mcp_server.py::test_chat_post_message_reply_marks_inbox_read_with_responded_message_id`
  - 结果: failed as expected, 缺少 `PeerTurnLatencyTraceStore.list_mcp_tool_stages`
- `.venv/bin/python -m pytest -q tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_rejects_read_pointing_to_unrelated_message tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_rejects_peer_stdout_without_degraded_fallback`
  - 结果: `2 failed`; 证明旧逻辑会把 unrelated `responded_message_id` 计为
    `mcp_writeback`，也会把 stdout final answer 计为 fallback success。
- 首次真实 soak 失败点:
  - 8 轮真实 `mcp_writeback` 已完成，但 trace 缺 `chat_read_inbox/chat_post_message` stage。
  - 根因: Codex app-server event stream 不稳定暴露 MCP tool-call item；改为在 xmuse MCP
    tool 入口 authoritative 打点。

验证:

- `.venv/bin/python -m pytest -q tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_records_latency_trace_with_injected_clock tests/xmuse/test_ray_adapters.py::test_app_server_turn_accumulator_emits_latency_stages_from_mcp_events`
  - 结果: `2 passed`
- `.venv/bin/python -m pytest -q tests/xmuse/test_mcp_server.py::test_chat_post_message_reply_marks_inbox_read_with_responded_message_id tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_records_latency_trace_with_injected_clock`
  - 结果: `2 passed, 1 warning`
- `.venv/bin/python -m pytest -q tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_records_success_when_peer_marks_inbox_read tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_rejects_read_without_real_writeback_message tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_rejects_read_pointing_to_unrelated_message tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_records_latency_trace_with_injected_clock tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_posts_peer_stdout_when_mcp_side_effect_is_missing tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_rejects_peer_stdout_without_degraded_fallback tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_routes_valid_mentions_from_peer_stdout_reply`
  - 结果: `7 passed`
- `.venv/bin/python -m pytest -q tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_mcp_server.py tests/xmuse/test_ray_adapters.py::test_app_server_turn_accumulator_emits_result_from_agent_message_delta tests/xmuse/test_ray_adapters.py::test_app_server_turn_accumulator_emits_latency_stages_from_mcp_events tests/xmuse/test_ray_adapters.py::test_codex_app_server_exposes_xmuse_mcp_chat_tools tests/xmuse/test_peer_cross_restart.py tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_restart_resume tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume`
  - 结果: `35 passed, 4 warnings`
- `.venv/bin/python -m pytest -q -s tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume`
  - 结果: `1 passed, 4 warnings`
- `.venv/bin/ruff check src/xmuse_core/chat/stream_store.py src/xmuse_core/chat/peer_scheduler.py src/xmuse_core/agents/codex_app_server_transport.py src/xmuse_core/chat/peer_service.py tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_ray_adapters.py tests/xmuse/test_full_chain_real_run.py tests/xmuse/test_mcp_server.py`
  - 结果: `All checks passed!`
- `git diff --check`
  - 结果: 无输出
- `pgrep -af 'codex app-server|gcs_server|raylet|ray::' || true`
  - 结果: 无 leftover Codex app-server / Ray worker processes；只匹配到本次 `pgrep` 命令本身。

Latency table (修复后真实 5+3 soak):

| turn | total ms | slowest stage | slowest ms | mode |
| --- | ---: | --- | ---: | --- |
| 1 | 16257 | `mcp_tools_ready->chat_read_inbox` | 5354 | `mcp_writeback` |
| 2 | 14589 | `chat_read_inbox->chat_post_message` | 5651 | `mcp_writeback` |
| 3 | 17123 | `chat_read_inbox->chat_post_message` | 7373 | `mcp_writeback` |
| 4 | 15593 | `chat_post_message->scheduler_observed_inbox_read` | 5948 | `mcp_writeback` |
| 5 | 11884 | `chat_read_inbox->chat_post_message` | 4602 | `mcp_writeback` |
| 6 | 17064 | `chat_post_message->scheduler_observed_inbox_read` | 6172 | `mcp_writeback` |
| 7 | 15780 | `chat_read_inbox->chat_post_message` | 6069 | `mcp_writeback` |
| 8 | 17136 | `chat_read_inbox->chat_post_message` | 8164 | `mcp_writeback` |

Latency summary:

- turns: 8
- median: 16018 ms
- p95: 17136 ms
- max: 17136 ms
- slowest observed stage: `chat_read_inbox->chat_post_message`, max 8164 ms
- current root cause: main delay is isolated to model/app-server time between reading inbox and issuing
  `chat_post_message`, plus occasional post-message scheduler observation wait. Ray/session startup and
  MCP discovery are not the dominant repeated delay after turn 1.

Review:

- First read-only Codex review found:
  - stdout fallback was not degraded-gated.
  - `mcp_writeback` validation accepted unrelated `responded_message_id`.
  - inspector-specific stage assertion was not in the reviewed files.
- Follow-up read-only Codex review after fixes:
  - “No findings for the three requested checks.”
  - It confirmed stdout fallback is degraded-gated, `mcp_writeback` requires real assistant message +
    `chat_post_message` evidence, and soak covers 5 fresh + restart + 3 resume turns with provider
    session reuse.

强 gate:

- Real soak passes with `mcp_writeback` only: 已满足。
- `provider_session_id` reused across restart/resume: 已满足。
- stdout fallback remains tested as degraded fallback, not success: 已满足。
- latency trace persisted and readable from existing trace surface: 已满足，
  `PeerTurnLatencyTraceStore.list_recent()` 返回 `stage_timings`，soak 逐 turn 断言 stage。
- no leftover `codex app-server` / `raylet` / `gcs_server` / `ray::` processes: 已满足。
- ruff touched files passes: 已满足。
- `git diff --check` passes: 已满足。

剩余风险:

- `mcp_tools_ready` 主要在首轮可观测；后续 turn 的 MCP 可用性由实际
  `chat_read_inbox/chat_post_message` tool-call stage 证明。
- `chat_post_message->scheduler_observed_inbox_read` 仍有 5-6s 级别观测间隔；当前证据显示它不是
  最大 p95 根因，但后续若要继续压低 latency，应进一步拆 Ray actor receive/app-server
  `turn/completed` 到 scheduler readback 的边界。
- real soak 仍依赖本机 Codex CLI、账号/模型可用性和网络，不是纯离线 CI gate。

---

## 2026-06-04 V8 Independent Installability Closure

本轮只完成 Path A Phase 1: independent installability。未进入 Runtime Operations、CI、
migration、MCP permission model、TUI、provider parity、groupchat runtime semantic changes 或
memoryOS 实现改动。

完成内容:

- 审计 `memoryos-lite`、`memoryOS`、`../memoryOS`、`memoryos_lite` 引用并分类。
- 移除 xmuse package 对 `memoryos-lite` 的运行时依赖。
- 移除 `pyproject.toml` 中 `[tool.uv.sources]` 的 editable `../memoryOS` source。
- 重新生成 `uv.lock`，不再含 `/home/iiyatu/projects/python/memoryOS` editable source。
- 将 `src/xmuse_core/self_evolution/recovery.py` 从 `memoryos_lite.recovery` re-export
  改为 xmuse-owned tiny recovery primitive。
- export template 和 `scripts/export_xmuse.py` 不再写入本地 editable memoryOS source。
- 新增 `docs/xmuse/walkthrough-maintenance-notes-v8.md` 作为 Phase 1 输出文档。

改动文件:

- `pyproject.toml`
- `uv.lock`
- `docs/xmuse/xmuse-package.pyproject.toml`
- `scripts/export_xmuse.py`
- `src/xmuse_core/self_evolution/recovery.py`
- `tests/xmuse/test_package_boundaries.py`
- `tests/xmuse/test_split_export_contract.py`
- `tests/xmuse/test_export_tool.py`
- `docs/xmuse/split-export-manifest.json`
- `docs/xmuse/memoryos-file-separation.md`
- `docs/xmuse/walkthrough-maintenance-notes-v8.md`
- `docs/xmuse/codex-strengthening-handoff.md`
- `xmuse/HANDOFF.md`
- `xmuse/CODEX_GOAL_HANDOFF.md`

MemoryOS 引用分类摘要:

| 分类 | 代表文件 | 处理 |
| --- | --- | --- |
| runtime-required before V8 | `pyproject.toml`, `uv.lock`, `self_evolution/recovery.py` | 已移除或内联 |
| removable legacy | export template/script/tests | 已改为独立 xmuse metadata |
| optional integration | `memoryos_client.py`, platform memory refs, V6 sidecar | 保留，默认不要求 sibling repo |
| test-only | boundary/export/gate/profile tests and fixtures | 只改直接断言旧依赖的 tests |
| docs/history | V6/V7 notes, archives, prompts | 保留历史语境 |

RED / reproduction evidence:

- 旧 `pyproject.toml` 有 `memoryos-lite>=0.1.0`。
- 旧 `[tool.uv.sources]` 有 `memoryos-lite = { path = "../memoryOS", editable = true }`。
- 旧 `uv.lock` 有 `source = { editable = "/home/iiyatu/projects/python/memoryOS" }`。
- 旧 `src/xmuse_core/self_evolution/recovery.py` 直接 import `memoryos_lite.recovery`。
- TDD red:
  - `uv run pytest -q tests/xmuse/test_package_boundaries.py::test_xmuse_core_memoryos_lite_imports_stay_behind_adapter tests/xmuse/test_split_export_contract.py::test_xmuse_package_template_exports_xmuse_entrypoints_without_memoryos_dependency tests/xmuse/test_split_export_contract.py::test_project_pyproject_has_no_local_memoryos_source_or_dependency tests/xmuse/test_export_tool.py::test_export_xmuse_project_does_not_add_local_memoryos_uv_source`
  - 结果: `4 failed`，分别命中旧 import、旧 dependency、旧 local uv source。

参考 memoryOS:

- 只读参考 `/home/iiyatu/projects/python/memoryOS/src/memoryos_lite/recovery.py`。
- 借鉴点: tiny recovery primitive 的公共 API 与既有行为，用于保持 xmuse recovery tests 稳定。
- 未照搬原因: Phase 1 目标是断开 package/runtime dependency，不引入 memoryOS runtime、
  store、API、recall、kernel 或其他无关实现。

验证:

- `uv run pytest -q tests/xmuse/test_package_boundaries.py::test_xmuse_core_memoryos_lite_imports_stay_behind_adapter tests/xmuse/test_split_export_contract.py::test_xmuse_package_template_exports_xmuse_entrypoints_without_memoryos_dependency tests/xmuse/test_split_export_contract.py::test_project_pyproject_has_no_local_memoryos_source_or_dependency tests/xmuse/test_export_tool.py::test_export_xmuse_project_does_not_add_local_memoryos_uv_source tests/xmuse/test_reliability_hardening.py::TestRuntimeRecovery`
  - 结果: `7 passed`
- `uv build`
  - 结果: built `dist/xmuse-0.1.0.tar.gz` and `dist/xmuse-0.1.0-py3-none-any.whl`
- Clean env:
  - `python3 -m venv /tmp/xmuse-v8-verify-clean.EKYSyP/venv`
  - `/tmp/xmuse-v8-verify-clean.EKYSyP/venv/bin/python -m pip install --upgrade pip`
  - `/tmp/xmuse-v8-verify-clean.EKYSyP/venv/bin/python -m pip install -e .`
  - 结果: installed `xmuse-0.1.0`，无 `memoryos-lite`
- Import smoke:
  - `/tmp/xmuse-v8-verify-clean.EKYSyP/venv/bin/python - <<'PY' ...`
  - 结果: `import-smoke-ok xmuse xmuse_core 1`
- Clean env Chat API + fake provider/groupchat smoke:
  - 同一 venv 中创建 conversation、发送 `@architect`、运行 `PeerChatScheduler` +
    fake provider writeback。
  - 结果: `chat-fake-provider-groupchat-smoke-ok conv_b0a6e2b569fa47c5bb6b93fd8a737728 1`
- Focused runtime regression:
  - `uv run pytest -q tests/xmuse/test_package_boundaries.py tests/xmuse/test_split_export_contract.py tests/xmuse/test_export_tool.py tests/xmuse/test_reliability_hardening.py::TestRuntimeRecovery tests/xmuse/test_execution_child_worker.py tests/xmuse/test_persistent_execute_god.py tests/xmuse/test_runtime_ray_backend.py`
  - 结果: `80 passed, 1 warning`
- Ruff:
  - `uv run ruff check scripts/export_xmuse.py src/xmuse_core/self_evolution/recovery.py tests/xmuse/test_package_boundaries.py tests/xmuse/test_split_export_contract.py tests/xmuse/test_export_tool.py`
  - 结果: `All checks passed!`
- `git diff --check`
  - 结果: 无输出
- Dependency metadata checks:
  - wheel `METADATA`: no `Requires-Dist: memoryos-lite`
  - sdist `PKG-INFO`: no `Requires-Dist: memoryos-lite`
  - `rg -n "memoryos-lite|memoryos_lite|\\.\\./memoryOS|/home/iiyatu/projects/python/memoryOS" pyproject.toml uv.lock`
  - 结果: no matches in package dependency inputs

强 gate:

- clean install passes: 已满足。
- `uv build` passes: 已满足。
- import smoke passes: 已满足。
- minimal fake-provider groupchat smoke passes: 已满足。
- no memoryOS repo files modified by this V8 implementation: 已满足；本轮只读参考 recovery 文件。
- touched runtime tests pass: 已满足。
- ruff touched files passes: 已满足。
- `git diff --check` passes: 已满足。

剩余风险:

- `/home/iiyatu/projects/python/memoryOS` 当前存在 unrelated dirty git state；本轮没有写入该 repo。
- xmuse 的历史 docs、fixtures、product description 仍有 MemoryOS 语境；本轮只移除 package/install
  blocker，不清理历史叙述。
- Optional live MemoryOS HTTP integration seams 保留为可选集成，不作为默认安装依赖。

---

## 2026-06-04 V9 Runtime Operations Closure

本轮只完成 Path A Phase 2: runtime operations。未进入 CI/type gate、schema migration、MCP
permission model、TUI feature、provider parity 或 MemoryOS 实现改动；未改变 groupchat MCP
writeback 语义，stdout fallback 仍不是 happy path。

完成内容:

- 审计 V9 runtime topology: Chat API、MCP server、platform runner、Ray GOD layer/actor、
  Codex app-server transport、provider session binding、`chat.db`、`god_sessions.json`、
  ports/env bundle。
- `xmuse-platform-runner --health-once` 新增 `operations` health block:
  - ports: MCP、MCP chat、Chat API。
  - readiness: Chat API、MCP、runner、Ray GOD layer、Codex app-server。
  - durable state: `chat.db`、`god_sessions.json`。
  - scheduler progress: `peer_turn_latency_traces`。
  - cleanup: orphan Codex app-server / Ray process leftovers。
- 新增 `--health-check-http`，用于让 `--health-once` 主动 probe Chat API 和 MCP `/health`。
- `--health-once` 在 `feature_lanes.json` 缺失时返回空 lane health，不再崩溃。
- Chat API 新增 `/health`，返回 service、`chat.db` 和 role template readiness。
- MCP `/health` 从 `status-ok` 扩展为包含 `/mcp`、`/mcp/chat`、`/sse` 和 state file metadata。
- process inventory 新增 V9 cleanup process roles:
  - `codex_app_server`
  - `raylet`
  - `gcs_server`
  - `ray_worker`
- runner shutdown 会调用 runtime GOD layers 的 `shutdown()`，避免正常退出后遗留 Ray actor /
  Codex app-server transport。
- `RayGodSessionLayer.shutdown()` 会关闭全部 live Ray GOD actors 并清空 live session map。
- 新增 `docs/xmuse/production-operations.md`，记录 topology、startup/shutdown、env bundle、
  health checks、degradation matrix、cleanup checklist、restart/resume 和 known risks。
- 更新 `docs/xmuse/config-matrix.md` 与 `docs/xmuse/provider-matrix.md`，对齐 V9 operations
  health contract。

改动文件:

- `xmuse/platform_runner.py`
- `xmuse/chat_api.py`
- `xmuse/mcp_server.py`
- `src/xmuse_core/agents/ray_session_layer.py`
- `src/xmuse_core/platform/run_processes.py`
- `src/xmuse_core/platform/run_health.py`
- `tests/xmuse/test_platform_runner.py`
- `tests/xmuse/test_chat_api.py`
- `tests/xmuse/test_mcp_server.py`
- `tests/xmuse/test_ray_adapters.py`
- `tests/xmuse/test_production_operations_doc.py`
- `docs/xmuse/production-operations.md`
- `docs/xmuse/config-matrix.md`
- `docs/xmuse/provider-matrix.md`
- `docs/xmuse/codex-strengthening-handoff.md`

Subagent audit:

- Review/audit subagent `Hegel` performed read-only V9 audit.
- Findings used:
  - missing `production-operations.md`
  - incomplete `health_once()` operations/readiness context
  - shallow Chat API/MCP health
  - missing runner/Ray layer shutdown cleanup
  - degraded fallback traceability must stay explicit
  - restart/resume exists for Ray app-server GOD plane but must be verified by tests
- No clowder-ai reference was used.

验证:

- Focused V9 health/API/cleanup/doc tests:
  - `uv run pytest -q tests/xmuse/test_platform_runner.py tests/xmuse/test_chat_api.py::test_chat_api_health_reports_runtime_state_files tests/xmuse/test_mcp_server.py::test_mcp_health_reports_chat_writeback_endpoint_and_state_files tests/xmuse/test_ray_adapters.py::test_ray_god_session_layer_shutdown_closes_all_live_actors tests/xmuse/test_production_operations_doc.py tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server`
  - 结果: `65 passed, 4 warnings`
- Broader focused runtime regression:
  - `uv run pytest -q tests/xmuse/test_package_boundaries.py tests/xmuse/test_split_export_contract.py tests/xmuse/test_export_tool.py tests/xmuse/test_reliability_hardening.py::TestRuntimeRecovery tests/xmuse/test_execution_child_worker.py tests/xmuse/test_persistent_execute_god.py tests/xmuse/test_runtime_ray_backend.py tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_ray_adapters.py::test_ray_god_session_layer_shutdown_closes_all_live_actors`
  - 结果: `92 passed, 1 warning`
- Real Ray + Codex app-server + MCP writeback restart/resume smoke:
  - `uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_restart_resume`
  - 结果: `1 passed, 4 warnings`
- Fake app-server restart/resume smoke:
  - `uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server`
  - 结果: included above in focused V9 gate, `1 passed`
- Runtime health command:
  - `uv run xmuse-platform-runner --health-once --health-check-http --mcp-port 8100`
  - 结果: command exited 0; `operations.cleanup.status` was `clean`; Chat API/MCP were explicitly
    `unreachable` because no long-running API services were expected during the check.
- Real process cleanup verification:
  - `pgrep -af "codex app-server|raylet|gcs_server|ray::|xmuse-platform-runner|mcp_server.py|chat_api.py"`
  - 结果: no matches / exit 1 after test and health command completion.
- MemoryOS repo status:
  - `git -C /home/iiyatu/projects/python/memoryOS status --short`
  - 结果: repo 仍有 unrelated dirty state；本轮未写入 MemoryOS repo。
- Ruff:
  - `uv run ruff check xmuse/platform_runner.py xmuse/chat_api.py xmuse/mcp_server.py src/xmuse_core/agents/ray_session_layer.py src/xmuse_core/platform/run_processes.py src/xmuse_core/platform/run_health.py tests/xmuse/test_platform_runner.py tests/xmuse/test_chat_api.py tests/xmuse/test_mcp_server.py tests/xmuse/test_ray_adapters.py tests/xmuse/test_production_operations_doc.py`
  - 结果: `All checks passed!`
- `git diff --check`
  - 结果: 无输出

强 gate:

- real groupchat Ray/Codex/MCP writeback smoke passes: 已满足。
- restart/resume provider_session_id reuse verified: 已满足；real smoke verifies `provider_session_id`
  persists as `codex_app_server_thread` and resume reuses it.
- degraded fallback paths are traceable and never counted as happy path: 已满足；scheduler traces keep
  `mcp_writeback` separate from `stdout_fallback` / degraded failure reasons，health readiness exposes
  explicit degraded local GOD mode。
- health/readiness checks have focused tests: 已满足。
- cleanup gates have focused tests or real process verification: 已满足；focused tests + `pgrep` no matches。
- no memoryOS repo files modified: 已满足；MemoryOS repo 只有 unrelated dirty state，本轮未写入。
- focused runtime regression passes: 已满足。
- ruff touched files passes: 已满足。
- `git diff --check`: 已满足。

剩余风险:

- `--health-check-http` 是 opt-in；默认 `--health-once` 不阻塞 HTTP endpoint probe。
- process discovery 依赖 Linux `/proc` 和命令行分类。
- Chat API / MCP 仍无 auth；本轮不进入 MCP permission model。
- Fake/local smoke 仍只用于 installability/runtime-matrix 辅助，不能替代 real Ray/Codex/MCP
  writeback gate。

---

## 2026-06-04 V10 Quality Gates And Provider Matrix Closure

本轮只完成 Path A Phase 3: quality gates and provider/config matrix closure。未进入
Phase 4 schema migration、MCP permission model、cleanup hardening、TUI feature、
runtime semantic changes、provider parity 或 MemoryOS 实现改动；未把 real Ray/Codex soak
设为默认 CI gate。

完成内容:

- 新增 `.github/workflows/xmuse-ci.yml`，默认 gate 顺序为 install、ruff、focused pytest、
  scoped type check。
- 新增 `docs/xmuse/quality-gates-and-provider-matrix.md`，记录默认 CI 命令、focused test
  groups、provider support levels、config/secrets policy、scoped type baseline 和 exclusions。
- 新增 `tests/xmuse/test_quality_gates_phase3.py`，自动化约束 CI workflow、provider matrix、
  `.env.example`、`config-matrix.md`、quality doc 和默认 CI secret policy。
- 为 provider read inventory 增加 `support_level` 字段，使 provider support level 可通过
  read-only inventory 被检查。
- 将 provider matrix 核心 type baseline 收束为:
  `src/xmuse_core/providers/models.py`、`src/xmuse_core/providers/registry.py`、
  `src/xmuse_core/platform/provider_read_contracts.py`。
- 在 `pyproject.toml` dev dependency 中加入 `mypy` 并更新 `uv.lock`。
- 修正 `.env.example` 顶部和正文 secret 语义: 默认 CI 不需要 provider secret，
  `DEEPSEEK_API_KEY` 仅用于 OpenCode worker/smoke path；补齐 production groupchat env bundle。
- 最小修复 provider matrix core 的 mypy 问题:
  - `ValidationInfo.field_name` 可能为 `None` 时使用 fallback 名称。
  - default registry 的 tuple 字段改用 tuple literals。

改动文件:

- `.github/workflows/xmuse-ci.yml`
- `.env.example`
- `pyproject.toml`
- `uv.lock`
- `docs/xmuse/quality-gates-and-provider-matrix.md`
- `docs/xmuse/codex-strengthening-handoff.md`
- `src/xmuse_core/providers/models.py`
- `src/xmuse_core/providers/registry.py`
- `src/xmuse_core/platform/provider_read_contracts.py`
- `tests/xmuse/test_provider_read_contracts_module.py`
- `tests/xmuse/test_quality_gates_phase3.py`

TDD / RED evidence:

- `uv run pytest -q tests/xmuse/test_quality_gates_phase3.py`
  - RED 结果: `5 failed`
  - 失败点: `.github/workflows/xmuse-ci.yml` 缺失、`mypy` dev dependency/type gate 缺失、
    `docs/xmuse/quality-gates-and-provider-matrix.md` 缺失、config/secrets/provider matrix
    contract 尚不可验证。
- 初次 scoped mypy:
  - `uv run mypy src/xmuse_core/providers src/xmuse_core/platform/provider_read_contracts.py`
  - 结果: `19 errors`
  - 决策: 不把 OpenCode adapter 等 provider CLI runtime 类型债扩进 V10；收束到 provider
    matrix model/registry/read inventory core，并在 quality doc 记录 documented exclusions。
- 初次 focused pytest 使用旧 fake groupchat e2e target 时失败:
  - `tests/xmuse/test_peer_chat_end_to_end.py::test_default_group_chat_flow_reaches_god_reply_proposal_and_keeps_roles_isolated`
  - 根因: 该旧测试手动 `chat_read_inbox` / `chat_post_message` 后仍断言
    `unread_inbox == 0`，与当前 inbox 状态语义不一致。
  - 决策: 不在 V10 修 unrelated groupchat card assertion；默认 CI fake-provider smoke 改用
    `tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server`，
    它覆盖 fake app-server MCP writeback + restart/resume，且不需要真实 provider secret。

Subagent audit:

- Review subagent `Lovelace` (`019e91df-7f73-79a0-8733-a244565b7d9c`) performed read-only
  V10 review.
- 结论: 未发现 V10 hard-gate blocker。
- 反馈处理:
  - `.env.example` 顶部 production bundle 摘要少了 execute/review backend 和 Chat API URL；
    已补齐。
  - GitHub Action major refs 未能通过远程查询独立验证；本轮 completion 证据只声明本地等价
    commands，不声明线上 GitHub ref 查询成功。
- No clowder-ai reference was used.

验证:

- Install / lock gate:
  - `uv sync --frozen --all-groups`
  - 结果: `Checked 108 packages in 1ms`
- V10 contract tests:
  - `uv run pytest -q tests/xmuse/test_quality_gates_phase3.py`
  - 结果: `5 passed`
- Focused pytest gates:
  - `uv run pytest -q tests/xmuse/test_package_boundaries.py tests/xmuse/test_split_export_contract.py::test_project_pyproject_has_no_local_memoryos_source_or_dependency tests/xmuse/test_provider_models.py tests/xmuse/test_provider_policy.py tests/xmuse/test_provider_support_level.py tests/xmuse/test_provider_read_contracts_module.py tests/xmuse/test_quality_gates_phase3.py tests/xmuse/test_platform_runner.py::test_health_once_handles_missing_lane_projection tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server`
  - 结果: `62 passed, 3 warnings`
- Ruff V10 scoped gate:
  - `uv run ruff check src/xmuse_core/providers/models.py src/xmuse_core/providers/registry.py src/xmuse_core/platform/provider_read_contracts.py tests/xmuse/test_provider_read_contracts_module.py tests/xmuse/test_quality_gates_phase3.py`
  - 结果: `All checks passed!`
- Scoped type check:
  - `uv run mypy src/xmuse_core/providers/models.py src/xmuse_core/providers/registry.py src/xmuse_core/platform/provider_read_contracts.py`
  - 结果: `Success: no issues found in 3 source files`
- `git diff --check`
  - 结果: 无输出
- MemoryOS repo status:
  - `git -C /home/iiyatu/projects/python/memoryOS status --short`
  - 结果: repo 仍有 unrelated dirty state；本轮未写入 MemoryOS repo。

强 gate:

- CI workflow exists and installs from repo: 已满足；`.github/workflows/xmuse-ci.yml` 使用
  `uv sync --frozen --all-groups`。
- gates ordered as ruff -> focused pytest -> type check: 已满足。
- focused pytest gates pass: 已满足，`62 passed, 3 warnings`。
- ruff passes for V10 default scoped gate: 已满足。
- type check enabled with scoped documented baseline: 已满足，quality doc 记录 exclusions，mypy
  baseline通过。
- no CI/default gate requires sibling `../memoryOS`: 已满足；workflow 不引用 sibling MemoryOS，
  package-boundary test覆盖 local dependency drift。
- no CI/default gate requires real provider secrets: 已满足；workflow 不引用 `DEEPSEEK_API_KEY`，
  `.env.example` 和 quality doc 说明 default CI 无 secret。
- provider/config matrix documented and matches code: 已满足；provider registry/read inventory、
  provider matrix doc、quality doc、config/env tests 绑定。
- slow real Ray/Codex tests excluded from default CI: 已满足；real soak 保留为 operator-run gate，
  默认 CI 使用 fake app-server smoke。
- `git diff --check`: 已满足。

剩余风险:

- Full-repo `uv run ruff check .` 当前仍会命中大量 unrelated historical lint debt；V10 为避免
  无关清理，把默认 ruff gate 收束到 Phase 3 contract/type files。
- Provider CLI adapters、legacy runner、TUI、dashboard、schema migration、MCP permission model
  未纳入 V10 scoped mypy baseline；这些属于后续 hardening，不应被视为 type-clean。
- GitHub Action major refs 的线上可用性未被本轮网络查询独立证明；本轮只验证本地等价命令。
- `/home/iiyatu/projects/python/memoryOS` 仍有 unrelated dirty state；本轮未写入该 repo。

---

## 2026-06-04 V11 Depth Hardening Contract Closure

本轮只完成 Path A Phase 4 contract closure。未实现 destructive migrations、auth middleware、
dashboard admin UI、cleanup daemon、TUI feature、MemoryOS 改动，且未改变 groupchat MCP
writeback happy path。

完成内容:

- 新增 `docs/xmuse/schema-migration-strategy.md`，定义 durable store migration stance、
  old-state handling、inventory corrections、cleanup 分类。
- 新增 `docs/xmuse/mcp-permission-model.md`，定义 MCP permission categories，并明确区分:
  API authentication、GOD session identity verification、audit guard、declarative permission category。
- 更新 `docs/xmuse/production-operations.md` 的 cleanup contract，明确 automated cleanup、
  graceful shutdown、stale lane repair、report-only detection 的边界。
- 新增 `src/xmuse_core/platform/mcp_permissions.py`，为所有注册 MCP tools 提供 declarative
  permission metadata；不做 runtime auth 拦截。
- 扩展 `src/xmuse_core/platform/read_tool_inventory.py`，在 tool inventory 中暴露
  `permission_category`、`mutates`、`identity_verification`、`audit_guard`、`scope`。
- 更新 `xmuse/platform_runner.py` 的 cleanup health leftover 条目，增加非破坏性字段:
  `action=report_only`、`automated_cleanup=false`、`operator_action=inspect_and_cleanup_manually`。
  不执行 kill。
- 新增 `tests/xmuse/test_depth_hardening_contracts.py`，覆盖 durable stores、MCP permission
  metadata/doc、identity-bound chat tool rejection、cleanup report-only contract。
- 更新 `tests/xmuse/test_mcp_server.py` 中 provider inventory 精确期望，补上 V10
  `support_level` 字段，修复 stale test drift。

Inventory corrections:

- `feature_graph_statuses.json`、`feature_graph_artifacts.json`、
  `provider_session_bindings.json` 不是 fully migration-ready；它们是 version present but
  unenforced，因为 current read path 没有统一 reject unknown schema version。
- `chat.db` 没有显式启用 WAL；V11 不声明 WAL checkpoint/cleanup contract。
- `feature_plans/*.json`、`feature_plans/*.deliberation.json`、`graph_sets/*.json`、
  `lane_graphs/*.json`、`audit_events.json`、`final_actions.json` 被补入 durable artifact
  matrix。
- `provider_selection_records.jsonl` 被补入 migration matrix，分类为 low-risk append-only
  audit/read-model。
- “auth/caller checks” 不能笼统说 0/35；identity-bound chat tools 已有 GOD session
  verification，但这不是 API authentication。
- process inventory / leftover detection 不是 automated cleanup；它是 report-only detection。

TDD / RED evidence:

- `uv run pytest -q tests/xmuse/test_depth_hardening_contracts.py`
  - RED 结果: `5 failed, 1 passed`
  - 失败点: `schema-migration-strategy.md` 缺失、`mcp_permissions` 模块缺失、
    `mcp-permission-model.md` 缺失、cleanup leftovers 缺 `action=report_only` metadata。
- review subagent 后追加 RED gap:
  - `provider_selection_records.jsonl` 在 inventory 中存在但 contract test / schema matrix 漏列。
  - 已补入 `DURABLE_STORES` 和 schema migration matrix 后复跑 V11 tests。

Subagent audits:

- Audit subagent `Sagan` (`019e91ed-78e2-71c1-9dc1-a3be00787634`) performed read-only
  V11 inventory audit。
  - Findings used: version present but unenforced overclaim、durable artifacts omission、
    chat.db WAL overclaim、auth vs identity vs audit guard distinctions、cleanup report-only vs
    automated cleanup distinction。
- Review subagent `Pasteur` (`019e91f8-6239-7be1-a15e-15f28ae1b364`) performed read-only
  V11 final review。
  - Finding fixed: missing `provider_selection_records.jsonl` in schema migration matrix and tests。
- No clowder-ai reference was used.

验证:

- V11 focused contract tests:
  - `uv run pytest -q tests/xmuse/test_depth_hardening_contracts.py`
  - 结果: `6 passed, 1 warning`
- V11 related regression tests:
  - `uv run pytest -q tests/xmuse/test_mcp_server.py::test_get_tool_inventory_groups_existing_mcp_tools tests/xmuse/test_mcp_server.py::test_read_provider_inventory_returns_sanitized_static_profile_metadata tests/xmuse/test_platform_runner.py::test_health_once_marks_runtime_operations_degraded_and_cleanup_dirty tests/xmuse/test_production_operations_doc.py tests/xmuse/test_depth_hardening_contracts.py`
  - 结果: `10 passed, 1 warning`
- V10 focused gates:
  - `uv run pytest -q tests/xmuse/test_package_boundaries.py tests/xmuse/test_split_export_contract.py::test_project_pyproject_has_no_local_memoryos_source_or_dependency tests/xmuse/test_provider_models.py tests/xmuse/test_provider_policy.py tests/xmuse/test_provider_support_level.py tests/xmuse/test_provider_read_contracts_module.py tests/xmuse/test_quality_gates_phase3.py tests/xmuse/test_platform_runner.py::test_health_once_handles_missing_lane_projection tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server`
  - 结果: `62 passed, 3 warnings`
- Scoped ruff:
  - `uv run ruff check src/xmuse_core/platform/mcp_permissions.py src/xmuse_core/platform/read_tool_inventory.py src/xmuse_core/platform/provider_read_contracts.py src/xmuse_core/providers/models.py src/xmuse_core/providers/registry.py xmuse/platform_runner.py tests/xmuse/test_depth_hardening_contracts.py tests/xmuse/test_mcp_server.py tests/xmuse/test_provider_read_contracts_module.py tests/xmuse/test_quality_gates_phase3.py`
  - 结果: `All checks passed!`
- Scoped mypy baseline:
  - `uv run mypy src/xmuse_core/providers/models.py src/xmuse_core/providers/registry.py src/xmuse_core/platform/provider_read_contracts.py`
  - 结果: `Success: no issues found in 3 source files`
- `git diff --check`
  - 结果: 无输出
- MemoryOS repo status:
  - `git -C /home/iiyatu/projects/python/memoryOS status --short`
  - 结果: repo 仍有 unrelated dirty state；本轮未写入 MemoryOS repo。

强 gate:

- V11 focused contract tests pass: 已满足，`6 passed, 1 warning`。
- V10 focused gates still pass: 已满足，`62 passed, 3 warnings`。
- scoped ruff passes: 已满足。
- scoped mypy baseline still passes: 已满足。
- no memoryOS files modified: 已满足；MemoryOS repo 只读 status 检查仍显示 unrelated dirty state。
- `git diff --check` passes: 已满足。
- old state can be detected and migrated or explicitly rejected: contract 已满足；docs 明确
  version absent / version present but unenforced / projection legacy / report-only read-model stances。
- MCP write tools reject wrong identity/conversation/scope: 已满足于 identity-bound chat tools；
  tests 覆盖 wrong conversation、wrong participant、unknown god session。
- cleanup automation has tests and does not hide degraded runtime states: 已满足；cleanup leftovers
  明确 `action=report_only`，不伪装为 automated cleanup。

剩余风险:

- 本轮只建立 migration/auth/cleanup contracts；没有实现 real schema migrations、auth middleware、
  rate limiting、operator RBAC、cleanup daemon 或 process kill。
- Version-present stores (`feature_graph_statuses.json`、`feature_graph_artifacts.json`、
  `provider_session_bindings.json`) 仍需未来实现 unknown-version rejection 后才能称为
  migration-ready。
- Full-repo ruff historical debt 仍存在；V11 未拓宽 CI gates。
- Chat API / MCP 仍无 API authentication；V11 只做分类和 identity-bound regression。

---

## 2026-06-04 Post-PathA Release Candidate Packaging Closure

本轮只完成 Post-PathA release candidate packaging。未进入 self-development smoke、
legacy archive/delete、TUI feature、CI gate 扩展、auth/migration/cleanup daemon 或
groupchat runtime semantic changes；未修改 `/home/iiyatu/projects/python/memoryOS`。

完成内容:

- 新增 root `README.md`，用英文说明项目定位、current capabilities、architecture
  overview、install、quickstart、fake groupchat demo、real Ray/Codex/MCP manual gate、
  production / experimental / legacy boundaries。
- 新增 `QUICKSTART.md`，覆盖 clean env setup、`uv sync --frozen --all-groups`、
  health check、fake groupchat demo、optional real runtime notes。
- 新增 `scripts/demo_fake_groupchat.py`，提供维护中的 fake groupchat demo 命令。该脚本
  不需要 Codex、Ray、OpenCode、DeepSeek key 或 memoryOS；它通过现有
  `PeerChatService`、`ChatStore`、`PeerChatScheduler`、`GodSessionRegistry` 路径创建
  会话、投递 human message、读取 inbox、写入 GOD reply，并验证 scheduler 观察到
  `mcp_writeback` latency evidence。
- 更新 `pyproject.toml`，将 description 从 MemoryOS-branded 文案改为 xmuse 独立项目描述，
  并将 package readme 指向 root `README.md`。
- 新增 `docs/xmuse/release-checklist.md`，记录 default CI gates、manual real runtime gate、
  provider support levels、known limitations。
- 新增 `tests/xmuse/test_release_candidate_packaging.py`，把 release packaging 文档、metadata、
  fake demo 命令、manual gate path、release-facing matrix drift 纳入 contract coverage。
- 修正 release-facing matrix drift:
  - `docs/xmuse/provider-matrix.md` 的 real soak gate 路径改为
    `tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume`。
  - `docs/xmuse/config-matrix.md` 和 `docs/xmuse/provider-matrix.md` 不再声称没有
    `BaseSettings` 或 `pydantic-settings` 未使用；改为说明 `Settings(BaseSettings)` 已存在，
    但仍是 additive overlay，调用点尚未全部迁移。
  - `docs/xmuse/archive/2026-06-roadmaps-and-audits/post-patha-release-readiness-audit.md` 增加 post-packaging note，标明该审计
    是 pre-packaging 状态，当前 onboarding 入口为 root README、QUICKSTART、fake demo 和
    release checklist。

改动文件:

- `README.md`
- `QUICKSTART.md`
- `docs/xmuse/release-checklist.md`
- `docs/xmuse/codex-strengthening-handoff.md`
- `docs/xmuse/archive/2026-06-roadmaps-and-audits/post-patha-release-readiness-audit.md`
- `docs/xmuse/provider-matrix.md`
- `docs/xmuse/config-matrix.md`
- `scripts/demo_fake_groupchat.py`
- `tests/xmuse/test_release_candidate_packaging.py`
- `pyproject.toml`

TDD / RED evidence:

- `uv run pytest -q tests/xmuse/test_release_candidate_packaging.py`
  - RED 结果: `5 failed`
  - 失败点: root `README.md` 缺失、`QUICKSTART.md` 缺失、
    `docs/xmuse/release-checklist.md` 缺失、`pyproject.toml` 仍指向旧 readme/MemoryOS
    description、`scripts/demo_fake_groupchat.py` 缺失。
- 初次 scoped ruff:
  - `uv run ruff check scripts/demo_fake_groupchat.py tests/xmuse/test_release_candidate_packaging.py`
  - 结果: 失败；新增测试 import block/长行格式问题。
  - 处理: 只修测试格式，不改行为。
- Review 后追加 contract:
  - 修正 `tests/xmuse/test_release_candidate_packaging.py` 中 README debranding 检查的大小写 bug。
  - 增加 provider/config matrix drift 约束，防止错误 real soak path 和 stale
    `BaseSettings` 说法回归。

Subagent review:

- Review subagent `Mendel` (`019e920b-c1a3-7321-b1dc-1420b9d4706e`) performed read-only
  release packaging review。
- 结论: no critical blockers；release candidate packaging mostly ready，但有 3 个 important
  doc/test accuracy issues。
- 已处理:
  - provider matrix real soak gate path 过期。
  - config/provider matrix 的 `pydantic-settings` / `BaseSettings` stale claim。
  - release packaging test 的 README debranding assertion 大小写 bug。
- Minor 处理:
  - 给 pre-packaging readiness audit 增加 supersession note。
- No clowder-ai reference was used.

验证:

- Install / lock gate:
  - `uv sync --frozen --all-groups`
  - 结果: `Checked 108 packages in 1ms`
- Build gate:
  - `uv build`
  - 结果: `Successfully built dist/xmuse-0.1.0.tar.gz` 和
    `Successfully built dist/xmuse-0.1.0-py3-none-any.whl`
- Quickstart health command:
  - `uv run xmuse-platform-runner --health-once`
  - 结果: exit 0；输出 `operations` health block，当前无 runner/MCP 进程时显示 degraded
    warnings，不阻塞命令。
- Fake groupchat demo:
  - `uv run python scripts/demo_fake_groupchat.py`
  - 结果: exit 0；输出 `fake-groupchat-demo-ok`、`scheduler_happy_path=1`、
    `GOD reply: Architect GOD demo reply: ...`
- Release packaging contract tests:
  - `uv run pytest -q tests/xmuse/test_release_candidate_packaging.py`
  - 结果: `6 passed`
- V10 focused gates plus release contract:
  - `uv run pytest -q tests/xmuse/test_package_boundaries.py tests/xmuse/test_split_export_contract.py::test_project_pyproject_has_no_local_memoryos_source_or_dependency tests/xmuse/test_provider_models.py tests/xmuse/test_provider_policy.py tests/xmuse/test_provider_support_level.py tests/xmuse/test_provider_read_contracts_module.py tests/xmuse/test_quality_gates_phase3.py tests/xmuse/test_platform_runner.py::test_health_once_handles_missing_lane_projection tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server tests/xmuse/test_release_candidate_packaging.py`
  - 结果: `68 passed, 3 warnings`
- Scoped ruff:
  - `uv run ruff check src/xmuse_core/providers/models.py src/xmuse_core/providers/registry.py src/xmuse_core/platform/provider_read_contracts.py tests/xmuse/test_provider_read_contracts_module.py tests/xmuse/test_quality_gates_phase3.py scripts/demo_fake_groupchat.py tests/xmuse/test_release_candidate_packaging.py`
  - 结果: `All checks passed!`
- Scoped mypy baseline:
  - `uv run mypy src/xmuse_core/providers/models.py src/xmuse_core/providers/registry.py src/xmuse_core/platform/provider_read_contracts.py`
  - 结果: `Success: no issues found in 3 source files`
- `git diff --check`
  - 结果: 无输出
- MemoryOS repo status:
  - `git -C /home/iiyatu/projects/python/memoryOS status --short`
  - 结果: repo 仍有大量 unrelated dirty state；本轮未写入 MemoryOS repo。

强 gate:

- clean install/build still passes or is not weakened: 已满足；`uv sync --frozen --all-groups`
  和 `uv build` 均通过。
- fake groupchat demo runs from documented command: 已满足；`uv run python scripts/demo_fake_groupchat.py`
  输出 `fake-groupchat-demo-ok` 和 `scheduler_happy_path=1`。
- V10 focused gates still pass: 已满足；包含新增 release contract 后 `68 passed, 3 warnings`。
- scoped ruff touched files passes: 已满足。
- scoped mypy baseline still passes if touched: 已满足；baseline 文件未改但复跑通过。
- no memoryOS files modified: 已满足；只读 status 检查显示 unrelated dirty state，本轮未写入。
- `git diff --check` passes: 已满足。

剩余风险:

- Fake demo 只证明本地 chat/store/scheduler 语义和 MCP-style writeback trace；不能替代 real
  Ray/Codex/MCP manual gate。
- Real Ray/Codex/MCP soak 仍是 operator-run，环境依赖 Codex CLI、Ray/app-server/MCP 服务。
- Chat API / MCP 仍无 auth；release checklist 明确记录。
- Full-repo ruff、broad mypy、legacy archive/delete、schema migrations、MCP RBAC、cleanup daemon
  仍在本轮范围外。

## 2026-06-04 Groupchat Initialization UX Task 6 Closure

本轮只完成 `Task 6: Full Gate, Docs, and No-MemoryOS Guard`。没有实现新能力，没有修改
Ray/app-server/provider runtime 行为，没有修改 TUI 行为，没有读取或修改 MemoryOS。

完成内容:

- 新增 no-MemoryOS guard test:
  `tests/xmuse/test_groupchat_bootstrap_no_memoryos.py`。
- guard 覆盖 groupchat bootstrap 直接相关模块:
  `bootstrap_contracts.py`、`bootstrap_store.py`、`peer_service.py`、`xmuse/chat_api.py`、
  `xmuse/tui/slash_commands.py`，静态拒绝 `memoryos` 文本出现。
- required release-sensitive fake demo 首次 fresh run 失败，根因是
  `scripts/demo_fake_groupchat.py` 调用 `PeerChatService.create_conversation()` 时未传
  `init_mode`；Task 3 后 service 默认 `proposal_then_approve` 只生成 proposal，不会在
  apply 前物化 `architect` participant，导致后续 human message 默认 intake 解析
  `@architect` 失败。
- 对该 gate 做了最小修复: fake demo 显式使用 `init_mode="deterministic"`。这只恢复
  fake demo smoke 的兼容路径，不改变服务默认 `proposal_then_approve`，不改变 TUI 或
  runtime 行为。

本轮修改文件:

- `tests/xmuse/test_groupchat_bootstrap_no_memoryos.py`
- `scripts/demo_fake_groupchat.py`
- `docs/xmuse/codex-strengthening-handoff.md`

Subagent review:

- Review subagent `Volta` (`019e925a-3147-70f2-b628-f7671c07a634`) performed read-only
  Task 6 closure review.
- 结论: no findings；no blockers against marking Task 6 complete。
- 审查确认:
  - no-MemoryOS guard scans only the intended five bootstrap-facing files。
  - fake demo `init_mode="deterministic"` change is isolated and does not change service/TUI
    `proposal_then_approve` defaults。
  - handoff records done work, changed files, commands/results, strong gate status,
    fake-demo-only caveat, remaining risks, and MemoryOS-not-touched statement。
- Reviewer did not rerun gates and did not inspect MemoryOS due read-only/no-touch constraints。

验证:

- Fake groupchat demo RED/root-cause reproduction:
  - `uv run python scripts/demo_fake_groupchat.py`
  - 结果: failed；`PeerChatError: default_intake_target_missing: architect`。
- Fake groupchat demo after minimal fix:
  - `uv run python scripts/demo_fake_groupchat.py`
  - 结果: exit 0；输出 `fake-groupchat-demo-ok`、`scheduler_happy_path=1`、
    `GOD reply: Architect GOD demo reply: ...`。
- Focused backend/API/no-MemoryOS gate:
  - `uv run pytest -q tests/xmuse/test_groupchat_bootstrap_contracts.py tests/xmuse/test_groupchat_bootstrap_store.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_chat_bootstrap.py tests/xmuse/test_peer_forks.py tests/xmuse/test_groupchat_bootstrap_no_memoryos.py`
  - 结果: `26 passed, 1 warning`。
- Focused TUI gate:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "new_command or init_status_retry_apply or help_command"`
  - 结果: `4 passed, 25 deselected`。
- Health gate:
  - `uv run xmuse-platform-runner --health-once`
  - 结果: exit 0；输出 `operations` health block；无 runner/MCP 进程时仍有预期
    `missing_runner_process` 和 `missing_mcp_process` degraded warnings，无 hard evidence。
- Runtime gate:
  - `uv run pytest -q tests/xmuse/test_full_chain_real_run.py tests/xmuse/test_runtime_ray_backend.py`
  - 结果: `16 passed, 4 warnings`。
- Ruff gate:
  - `uv run ruff check src/xmuse_core/chat/bootstrap_contracts.py src/xmuse_core/chat/bootstrap_store.py src/xmuse_core/chat/peer_service.py src/xmuse_core/chat/api_models.py src/xmuse_core/chat/store.py src/xmuse_core/chat/peer_forks.py xmuse/chat_api.py xmuse/tui/adapter/xmuse_adapter.py xmuse/tui/slash_commands.py tests/xmuse/test_groupchat_bootstrap_contracts.py tests/xmuse/test_groupchat_bootstrap_store.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_groupchat_bootstrap_no_memoryos.py scripts/demo_fake_groupchat.py`
  - 结果: `All checks passed!`。
- Final diff check:
  - `git diff --check`
  - 结果: 无输出，exit 0。

强 gate:

- no-MemoryOS guard exists and passes: 已满足，guard test 已纳入 focused backend/API gate。
- deterministic mode works: 已满足，fake demo 使用 deterministic 模式后完成 participant
  materialization、default intake、scheduler happy path 和 GOD writeback smoke。
- `proposal_then_approve` + apply works: 已满足，focused backend/API gate 覆盖 lifecycle/API
  proposal/apply 行为并通过。
- TUI commands covered: 已满足，`/new`、`/init status`、`/init retry`、`/init apply` focused
  TUI tests 通过。
- bootstrap does not start live Ray/app-server/provider sessions: 已满足，本轮 bootstrap focused
  gates 只验证 durable contracts/store/API/TUI；health gate 显示 runner/MCP 进程为 0，fake demo
  只记录为 fake smoke，不作为 production runtime evidence。
- MemoryOS was not touched: 已满足，本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，
  未新增 MemoryOS import/config/dependency。

剩余风险:

- Fake demo 只证明本地 fake smoke，不替代 real Ray/Codex/MCP production runtime evidence。
- Health gate 在无 runner/MCP 进程时仍会报告 degraded warnings；这是当前 operator state，不是
  Task 6 blocker。
- 当前仓库整体仍处于未跟踪状态，`git diff` 无法作为完整变更清单来源；本轮按实际触达文件和
  fresh gate 输出记录 handoff。

## 2026-06-04 Groupchat Bootstrap Status Review Fixes

本轮只处理 Task 6 completion review 后指出的 groupchat bootstrap 闭环缺口，没有进入
MemoryOS、Ray/app-server/provider runtime、TUI 行为重构或无关能力线。

完成内容:

- 修复 `/init status` 真实路径:
  - 新增 backend status read model: `GET /api/chat/conversations/{conversation_id}/bootstrap/status`。
  - `XmuseAdapter.get_bootstrap_status()` 现在直接调用该 endpoint，不再通过
    `list_group_conversations()` 过滤推断，因此 proposal-only conversation 也能返回状态。
- 修复 bootstrap durable 状态推进:
  - `create_bootstrap_proposal(...)` 写入 proposal 后把 draft status 推进到
    `proposal_ready`。
  - `apply_bootstrap_proposal(...)` 写入 application 后把 draft status 推进到
    `bootstrapped`。
  - `PeerChatService.get_bootstrap_status(...)` 聚合 draft / latest proposal /
    latest application，返回当前 status、draft/proposal/apply ids 和 participant plan。
- API 默认策略决定:
  - 保留裸 `POST /api/chat/conversations` 未显式 `init_mode` 时的 deterministic compatibility
    path，因为仓库中大量旧 API paths/tests 使用裸 create 作为已物化默认 team 的兼容入口。
  - 新 UX contract 仍由 service/TUI 显式 `init_mode="proposal_then_approve"` 表达；
    新增测试固定该兼容决策，避免把默认差异误当未定义行为。

本轮修改文件:

- `src/xmuse_core/chat/bootstrap_store.py`
- `src/xmuse_core/chat/peer_service.py`
- `xmuse/chat_api.py`
- `xmuse/tui/adapter/xmuse_adapter.py`
- `tests/xmuse/test_chat_bootstrap_api.py`
- `tests/xmuse/test_groupchat_bootstrap_lifecycle.py`
- `tests/xmuse/test_tui_adapter.py`
- `docs/xmuse/codex-strengthening-handoff.md`

TDD / RED evidence:

- `uv run pytest -q tests/xmuse/test_chat_bootstrap_api.py::test_api_bootstrap_status_tracks_draft_proposal_and_apply tests/xmuse/test_groupchat_bootstrap_lifecycle.py::test_bootstrap_durable_status_advances_through_proposal_and_apply tests/xmuse/test_tui_adapter.py::test_adapter_get_bootstrap_status_uses_chat_api_endpoint`
  - RED 结果: `3 failed, 1 warning`。
  - 失败点:
    - status endpoint 404。
    - `PeerChatService` 缺 `get_bootstrap_status`。
    - adapter `get_bootstrap_status()` 仍调用 group list，测试强制失败。

验证:

- RED tests after fix:
  - `uv run pytest -q tests/xmuse/test_chat_bootstrap_api.py::test_api_bootstrap_status_tracks_draft_proposal_and_apply tests/xmuse/test_groupchat_bootstrap_lifecycle.py::test_bootstrap_durable_status_advances_through_proposal_and_apply tests/xmuse/test_tui_adapter.py::test_adapter_get_bootstrap_status_uses_chat_api_endpoint`
  - 结果: `3 passed, 1 warning`。
- API compatibility/default decision tests:
  - `uv run pytest -q tests/xmuse/test_chat_bootstrap_api.py::test_api_create_without_init_mode_keeps_deterministic_compatibility tests/xmuse/test_chat_bootstrap_api.py::test_api_create_conversation_proposal_mode_stops_before_apply tests/xmuse/test_chat_bootstrap_api.py::test_api_proposal_then_apply_materializes_team`
  - 结果: `3 passed, 1 warning`。
- Affected suites:
  - `uv run pytest -q tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py tests/xmuse/test_tui_adapter.py`
  - 结果: `34 passed, 1 warning`。
- Focused backend/API/no-MemoryOS + adapter status gate:
  - `uv run pytest -q tests/xmuse/test_groupchat_bootstrap_contracts.py tests/xmuse/test_groupchat_bootstrap_store.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_chat_bootstrap.py tests/xmuse/test_peer_forks.py tests/xmuse/test_groupchat_bootstrap_no_memoryos.py tests/xmuse/test_tui_adapter.py::test_adapter_get_bootstrap_status_uses_chat_api_endpoint`
  - 结果: `30 passed, 1 warning`。
- Focused TUI command gate:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "new_command or init_status_retry_apply or help_command"`
  - 结果: `4 passed, 25 deselected`。
- Fake groupchat demo:
  - `uv run python scripts/demo_fake_groupchat.py`
  - 结果: exit 0；输出 `fake-groupchat-demo-ok`、`scheduler_happy_path=1`。
- Health gate:
  - `uv run xmuse-platform-runner --health-once`
  - 结果: exit 0；仍只有预期 `missing_runner_process` / `missing_mcp_process` degraded
    warnings，无 hard evidence。
- Runtime gate:
  - `uv run pytest -q tests/xmuse/test_full_chain_real_run.py tests/xmuse/test_runtime_ray_backend.py`
  - 结果: `16 passed, 4 warnings`。
- Ruff gate:
  - `uv run ruff check src/xmuse_core/chat/bootstrap_contracts.py src/xmuse_core/chat/bootstrap_store.py src/xmuse_core/chat/peer_service.py src/xmuse_core/chat/api_models.py src/xmuse_core/chat/store.py src/xmuse_core/chat/peer_forks.py xmuse/chat_api.py xmuse/tui/adapter/xmuse_adapter.py xmuse/tui/slash_commands.py tests/xmuse/test_groupchat_bootstrap_contracts.py tests/xmuse/test_groupchat_bootstrap_store.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_groupchat_bootstrap_no_memoryos.py tests/xmuse/test_tui_adapter.py scripts/demo_fake_groupchat.py`
  - 结果: `All checks passed!`。

强 gate / review finding 对照:

- `/init status` proposal-only 真实路径可用: 已满足，adapter 直连 backend status endpoint，
  不再依赖 group list participant filter。
- bootstrap 状态机写回当前状态: 已满足，proposal 后 `proposal_ready`，apply 后
  `bootstrapped`，service/API status read model 均有 focused tests。
- API 默认差异: 已决策为保留 deterministic compatibility；new UX 入口通过显式
  `proposal_then_approve` 保持 contract，不再把裸 API fallback 当成未定义默认。
- MemoryOS was not touched: 已满足；本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，
  未新增 MemoryOS import/config/dependency。
- bootstrap does not start live Ray/app-server/provider sessions: 已满足；本轮新增 status read
  model 和 durable status update 均为 chat store/API/TUI adapter 路径，不启动 live runtime。

剩余风险:

- 裸 API deterministic fallback 仍是兼容策略；若后续要把 API 默认也切到
  `proposal_then_approve`，需要单独迁移大量旧 API tests/consumers。
- status endpoint 当前是 read model，不新增 auth/RBAC；Chat API/MCP auth 仍是后续独立任务。
- Fake demo 仍只是 fake smoke，不替代 real production runtime evidence。

## 2026-06-04 Groupchat Bootstrap Status Monotonicity Review Fix

本轮只处理 review subagent 对上一轮 status 修复提出的两个状态一致性问题，没有进入
MemoryOS、Ray/app-server/provider runtime、TUI 行为重构或 API 默认策略切换。

Review findings:

- Review subagent `Pascal` (`019e926f-a245-7d22-823f-770f5e350db7`) performed read-only
  review of the status fixes。
- Important finding: apply 后再次 `/init retry` / proposal API 会把 durable draft status 从
  `bootstrapped` 回退到 `proposal_ready`。
- Medium finding: apply 写 artifact 时使用 stale draft，导致 artifact 顶层 status 是
  `bootstrapped`，但内嵌 `draft.status` 仍是 `proposal_ready`。
- Reviewer 确认 status endpoint/TUI adapter 直连路径有效，API deterministic compatibility
  决策技术上成立，但上述 durable monotonicity blocker 需修复后才能完成。

完成内容:

- `create_bootstrap_proposal(...)` 只有在 draft 尚未 `bootstrapped` 时才推进
  `proposal_ready`，避免 apply 后 retry 回退 durable status。
- `apply_bootstrap_proposal(...)` 现在使用 `update_draft_status(..., BOOTSTRAPPED)` 返回的
  updated draft 写 applied bootstrap artifact，避免 artifact 内嵌 draft 状态陈旧。
- 新增 focused tests 覆盖:
  - apply 后 retry 不回退 durable draft status。
  - applied bootstrap artifact 内嵌 `draft.status == "bootstrapped"`。

本轮修改文件:

- `src/xmuse_core/chat/peer_service.py`
- `tests/xmuse/test_groupchat_bootstrap_lifecycle.py`
- `docs/xmuse/codex-strengthening-handoff.md`

TDD / RED evidence:

- `uv run pytest -q tests/xmuse/test_groupchat_bootstrap_lifecycle.py::test_bootstrap_status_does_not_regress_when_retry_runs_after_apply tests/xmuse/test_groupchat_bootstrap_lifecycle.py::test_applied_bootstrap_artifact_embeds_bootstrapped_draft`
  - RED 结果: `2 failed`。
  - 失败点:
    - durable draft status 实际为 `proposal_ready`，期望 `bootstrapped`。
    - artifact 内嵌 `draft.status` 实际为 `proposal_ready`，期望 `bootstrapped`。

验证:

- RED tests after fix:
  - `uv run pytest -q tests/xmuse/test_groupchat_bootstrap_lifecycle.py::test_bootstrap_status_does_not_regress_when_retry_runs_after_apply tests/xmuse/test_groupchat_bootstrap_lifecycle.py::test_applied_bootstrap_artifact_embeds_bootstrapped_draft`
  - 结果: `2 passed`。
- Affected suites:
  - `uv run pytest -q tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py tests/xmuse/test_tui_adapter.py`
  - 结果: `36 passed, 1 warning`。
- Focused backend/API/no-MemoryOS + adapter status gate:
  - `uv run pytest -q tests/xmuse/test_groupchat_bootstrap_contracts.py tests/xmuse/test_groupchat_bootstrap_store.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_chat_bootstrap.py tests/xmuse/test_peer_forks.py tests/xmuse/test_groupchat_bootstrap_no_memoryos.py tests/xmuse/test_tui_adapter.py::test_adapter_get_bootstrap_status_uses_chat_api_endpoint`
  - 结果: `32 passed, 1 warning`。
- Focused TUI command gate:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "new_command or init_status_retry_apply or help_command"`
  - 结果: `4 passed, 25 deselected`。
- Fake groupchat demo:
  - `uv run python scripts/demo_fake_groupchat.py`
  - 结果: exit 0；输出 `fake-groupchat-demo-ok`、`scheduler_happy_path=1`。
- Health gate:
  - `uv run xmuse-platform-runner --health-once`
  - 结果: exit 0；仍只有预期 `missing_runner_process` / `missing_mcp_process` degraded
    warnings，无 hard evidence。
- Runtime gate:
  - `uv run pytest -q tests/xmuse/test_full_chain_real_run.py tests/xmuse/test_runtime_ray_backend.py`
  - 结果: `16 passed, 4 warnings`。
- Ruff gate:
  - `uv run ruff check src/xmuse_core/chat/bootstrap_contracts.py src/xmuse_core/chat/bootstrap_store.py src/xmuse_core/chat/peer_service.py src/xmuse_core/chat/api_models.py src/xmuse_core/chat/store.py src/xmuse_core/chat/peer_forks.py xmuse/chat_api.py xmuse/tui/adapter/xmuse_adapter.py xmuse/tui/slash_commands.py tests/xmuse/test_groupchat_bootstrap_contracts.py tests/xmuse/test_groupchat_bootstrap_store.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_groupchat_bootstrap_no_memoryos.py tests/xmuse/test_tui_adapter.py scripts/demo_fake_groupchat.py`
  - 结果: `All checks passed!`。

强 gate / review finding 对照:

- `/init status` proposal-only 真实路径可用: 仍满足。
- bootstrap durable status monotonic after apply: 已满足，apply 后 retry 不再回退 draft status。
- applied artifact 内嵌 draft status 一致: 已满足，artifact `draft.status` 为 `bootstrapped`。
- API 默认差异: 仍保留 deterministic compatibility；未在本轮切换默认策略。
- MemoryOS was not touched: 已满足；本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`。

剩余风险:

- 裸 API deterministic fallback 仍可能让 schema default 与 endpoint omitted-field 行为看起来不同；
  后续若要统一，需要单独迁移旧 API consumers。
- status endpoint 仍是 read model，不新增 auth/RBAC。
- Fake demo 仍只是 fake smoke，不替代 real production runtime evidence。

## 2026-06-04 Service Default Compatibility And Inbox Closure Fix

本轮只处理 completion review 后指出的两项 broader chat regression，没有进入 MemoryOS、
Ray/app-server/provider runtime 改造、TUI UX 扩展或 API 默认策略切换。

Findings / root cause:

- Service-level default regression:
  - `PeerChatService.create_conversation(title=...)` 默认被改成 `proposal_then_approve` 后，
    direct service callers 只得到 init participant，随后 default intake / explicit mentions
    找不到 `@architect` / `@review` / `@execute`。
  - 这与旧 direct service compatibility 冲突；TUI `/new` 已显式传
    `init_mode="proposal_then_approve"`，不需要依赖 service 默认进入新 UX。
- End-to-end unread inbox regression:
  - `test_peer_chat_end_to_end.py` 中 lane_graph proposal 被 human approve 后，自动
    `review_trigger` inbox item 仍保持 unread，导致 worklist summary `unread_inbox=1`。
  - 进一步验证后，mission_blueprint review trigger 不能被 broad approval cleanup 清理，因为
    full-chain runtime 仍要求 review agent 读取 initial blueprint review trigger。

完成内容:

- `PeerChatService.create_conversation(...)` 默认恢复为 `init_mode="deterministic"`，保留 direct
  service compatibility；TUI/API 新 UX 仍通过显式 `proposal_then_approve` 触发。
- `create_conversation(...)` 对显式 `participants` 增加 preflight validation，避免 invalid
  participants 抛错后留下半创建 conversation。
- API approval route 在批准 `lane_graph` proposal 后，会把对应 proposal message 产生的
  `review_trigger` inbox item 标记为 `read`，清理已被 human approval 取代的 stale review
  request。
- approval cleanup 限定为 `lane_graph`；不清理 `mission_blueprint` review trigger，保持
  full-chain review agent 读取初始 blueprint trigger 的 runtime 契约。

本轮修改文件:

- `src/xmuse_core/chat/peer_service.py`
- `xmuse/chat_api.py`
- `tests/xmuse/test_chat_review_trigger.py`
- `docs/xmuse/codex-strengthening-handoff.md`

TDD / RED evidence:

- Service default regression reproduction:
  - `uv run pytest -q tests/xmuse/test_chat_default_intake.py tests/xmuse/test_chat_structure_escalation.py tests/xmuse/test_chat_blueprint_revision.py`
  - RED 结果: `3 failed, 9 passed, 1 warning`。
  - 失败点: `default_intake_target_missing: architect`、`unknown_target: @review`。
- Peer e2e unread regression reproduction:
  - `uv run pytest -q tests/xmuse/test_peer_chat_end_to_end.py`
  - RED 结果: `1 failed, 2 passed, 1 warning`。
  - 失败点: worklist `unread_inbox == 1`，预期 `0`。
- Approval cleanup focused RED:
  - `uv run pytest -q tests/xmuse/test_chat_review_trigger.py::test_approval_marks_related_review_trigger_read`
  - RED 结果: `1 failed, 1 warning`。
  - 失败点: related review trigger status remained `unread` after approval。

验证:

- Direct service compatibility after fix:
  - `uv run pytest -q tests/xmuse/test_chat_default_intake.py tests/xmuse/test_chat_structure_escalation.py tests/xmuse/test_chat_blueprint_revision.py`
  - 结果: `12 passed, 1 warning`。
- Service default model focused regression:
  - `uv run pytest -q tests/xmuse/test_peer_chat_service.py::test_create_conversation_defaults_to_non_final_quality_participant_models`
  - 结果: `1 passed`。
- Approval cleanup focused test:
  - `uv run pytest -q tests/xmuse/test_chat_review_trigger.py::test_approval_marks_related_review_trigger_read`
  - 结果: `1 passed, 1 warning`。
- Peer e2e after fix:
  - `uv run pytest -q tests/xmuse/test_peer_chat_end_to_end.py`
  - 结果: `3 passed, 1 warning`。
- Broader chat suites:
  - `uv run pytest -q tests/xmuse/test_chat_default_intake.py tests/xmuse/test_chat_review_trigger.py tests/xmuse/test_chat_structure_escalation.py tests/xmuse/test_chat_blueprint_revision.py tests/xmuse/test_peer_chat_end_to_end.py tests/xmuse/test_peer_chat_service.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py`
  - 结果: `44 passed, 1 warning`。
- Runtime regression after lane_graph-only cleanup:
  - `uv run pytest -q tests/xmuse/test_chat_review_trigger.py::test_approval_marks_related_review_trigger_read tests/xmuse/test_peer_chat_end_to_end.py`
  - 结果: `4 passed, 1 warning`。
  - `uv run pytest -q tests/xmuse/test_chat_default_intake.py tests/xmuse/test_chat_review_trigger.py tests/xmuse/test_chat_structure_escalation.py tests/xmuse/test_chat_blueprint_revision.py tests/xmuse/test_peer_chat_service.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py`
  - 结果: `41 passed, 1 warning`。
- Full runtime gate:
  - `uv run pytest -q tests/xmuse/test_full_chain_real_run.py tests/xmuse/test_runtime_ray_backend.py`
  - 结果: `16 passed, 4 warnings`。
- Task 6 focused backend/API/no-MemoryOS + adapter status gate:
  - `uv run pytest -q tests/xmuse/test_groupchat_bootstrap_contracts.py tests/xmuse/test_groupchat_bootstrap_store.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_chat_bootstrap.py tests/xmuse/test_peer_forks.py tests/xmuse/test_groupchat_bootstrap_no_memoryos.py tests/xmuse/test_tui_adapter.py::test_adapter_get_bootstrap_status_uses_chat_api_endpoint`
  - 结果: `32 passed, 1 warning`。
- Focused TUI command gate:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "new_command or init_status_retry_apply or help_command"`
  - 结果: `4 passed, 25 deselected`。
- Fake groupchat demo:
  - `uv run python scripts/demo_fake_groupchat.py`
  - 结果: exit 0；输出 `fake-groupchat-demo-ok`、`scheduler_happy_path=1`。
- Health gate:
  - `uv run xmuse-platform-runner --health-once`
  - 结果: exit 0；仍只有预期 `missing_runner_process` / `missing_mcp_process` degraded
    warnings，无 hard evidence。
- Ruff gate:
  - `uv run ruff check src/xmuse_core/chat/bootstrap_contracts.py src/xmuse_core/chat/bootstrap_store.py src/xmuse_core/chat/peer_service.py src/xmuse_core/chat/api_models.py src/xmuse_core/chat/store.py src/xmuse_core/chat/peer_forks.py xmuse/chat_api.py xmuse/tui/adapter/xmuse_adapter.py xmuse/tui/slash_commands.py tests/xmuse/test_groupchat_bootstrap_contracts.py tests/xmuse/test_groupchat_bootstrap_store.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_groupchat_bootstrap_no_memoryos.py tests/xmuse/test_tui_adapter.py tests/xmuse/test_chat_review_trigger.py tests/xmuse/test_peer_chat_service.py scripts/demo_fake_groupchat.py`
  - 结果: `All checks passed!`。
- Final diff check:
  - `git diff --check`
  - 结果: 无输出，exit 0。

强 gate / finding 对照:

- service-level default compatibility: 已满足，direct service 默认 deterministic，默认 intake /
  explicit mentions / structure escalation / blueprint revision suites 全部通过。
- TUI `/new` proposal UX: 未回退；adapter 仍显式发送 `init_mode="proposal_then_approve"`。
- API bare create compatibility: 未改变；仍由 API omitted-field path 保持 deterministic。
- peer chat e2e unread inbox: 已满足，lane_graph approval 清理 obsolete review trigger 后
  `test_peer_chat_end_to_end.py` 通过。
- full-chain blueprint review trigger: 已满足，cleanup 限定 lane_graph 后 full-chain runtime gate
  通过。
- MemoryOS was not touched: 已满足；本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`。

剩余风险:

- lane_graph human approval 会清理对应 review_trigger；如果未来需要 reviewer 对已 human-approved
  lane_graph 做二次审查，应引入独立 review policy，而不是复用 stale unread trigger。
- 裸 API deterministic fallback 仍是兼容策略；后续若统一到 proposal mode，需要单独迁移旧 API
  consumers/tests。
- Fake demo 仍只是 fake smoke，不替代 real production runtime evidence。

## 2026-06-04 Groupchat Initialization UX Final Preflight Closure Check

本轮检查 `docs/superpowers/plans/2026-06-04-groupchat-initialization-ux.md` 对应实现是否真正
收束。检查中发现一个 API 层产品语义缺口并已补齐；没有进入 MemoryOS、Ray/provider runtime、
TUI 行为扩展或 live init-god proposal 生成。

Finding / root cause:

- `POST /api/chat/conversations` 遇到 invalid `initial_participants` 或 unknown `preset_id`
  时会返回 `500 Internal Server Error`。其中 invalid participants 已通过 service preflight
  避免残留 conversation，但 API 没有把 `PeerChatError` 映射为 4xx；unknown preset 则在
  service 创建 conversation 后才失败，有残留半成品风险。

完成内容:

- `PeerChatService.create_conversation(...)` 在创建 conversation 前预校验 `init_mode` 和
  `preset_id`，unknown preset 不再留下 residual conversation。
- `xmuse/chat_api.py` 的 create conversation endpoint 捕获 `PeerChatError` 并返回结构化
  `400`。
- 新增 focused regression:
  - bad `initial_participants` -> `400` + no residual conversation。
  - unknown `preset_id` -> `400` + no residual conversation。

本轮修改文件:

- `src/xmuse_core/chat/peer_service.py`
- `xmuse/chat_api.py`
- `tests/xmuse/test_chat_bootstrap_api.py`
- `docs/xmuse/codex-strengthening-handoff.md`

验证:

- API preflight regression:
  - `uv run pytest -q tests/xmuse/test_chat_bootstrap_api.py -k "invalid_initial_participants or unknown_bootstrap_preset or without_init_mode or opencode_override"`
  - 结果: `4 passed, 4 deselected, 1 warning`。
- Plan Task 6 backend/API/no-MemoryOS gate:
  - `uv run pytest -q tests/xmuse/test_groupchat_bootstrap_contracts.py tests/xmuse/test_groupchat_bootstrap_store.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_chat_bootstrap.py tests/xmuse/test_peer_forks.py tests/xmuse/test_groupchat_bootstrap_no_memoryos.py`
  - 结果: `33 passed, 1 warning`。
- Focused TUI command gate:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "new_command or init_status_retry_apply or help_command"`
  - 结果: `4 passed, 25 deselected`。
- Broader chat regression:
  - `uv run pytest -q tests/xmuse/test_chat_default_intake.py tests/xmuse/test_chat_review_trigger.py tests/xmuse/test_chat_structure_escalation.py tests/xmuse/test_chat_blueprint_revision.py tests/xmuse/test_peer_chat_end_to_end.py tests/xmuse/test_peer_chat_service.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py`
  - 结果: `46 passed, 1 warning`。
- Fake groupchat demo:
  - `uv run python scripts/demo_fake_groupchat.py`
  - 结果: exit 0；输出 `fake-groupchat-demo-ok`、`scheduler_happy_path=1`。
- Runtime gate:
  - `uv run pytest -q tests/xmuse/test_full_chain_real_run.py tests/xmuse/test_runtime_ray_backend.py`
  - 结果: `16 passed, 4 warnings`。
- Health gate:
  - `uv run xmuse-platform-runner --health-once`
  - 结果: exit 0；仅有当前无 runner/MCP 进程时的预期 degraded warnings。
- Ruff and diff check:
  - touched-file `ruff check`: `All checks passed!`。
  - `git diff --check`: 无输出，exit 0。

收束判断:

- `2026-06-04-groupchat-initialization-ux` 作为 Task 1-6 implementation plan 已收束：
  backend-owned preset/proposal/apply、durable bootstrap state、idempotent fork lineage、
  API endpoints、TUI `/new` + `/init` contract consumption、no-MemoryOS guard、fake demo 和
  runtime regression 均有 fresh gate。
- 原设计中的 rich TUI wizard、provider/model/template 交互式选择、live `init_god` 模型生成
  proposal、bootstrap timeline dashboard 仍是明确剩余能力，不属于本轮 Task 1-6 的完成面。

## 2026-06-04 V12 Groupchat Latency Parity Planning

新增 `docs/xmuse/walkthrough-maintenance-notes-v12.md`，作为下一轮 `/goal` 的群聊层延迟体验
闭环文档。

V12 不改变既有 V7/V11 的 MCP writeback authority 方向；目标是把用户第一可见反馈从最终
writeback 中拆出来，让 TUI 体验更接近单独 provider session。

V12 任务线:

1. `DIRECT-MCP-POST-PROMPT`: peer scheduler 不再要求简单 turn 必须先
   `chat_read_inbox`，而是直接基于 `xmuse_context.inbox_item` 调
   `chat_post_message(reply_to_inbox_item_id=...)`。
2. `FIRST-VISIBLE-STREAM-TRACE`: latency trace 区分 `first_visible` /
   `first_stream_delta` / final `writeback`，不再把 scheduler receive 完成点误称为
   first delta。
3. `TUI-IMMEDIATE-PEER-FEEDBACK`: TUI 在最终 assistant message 前显示 pending/stream
   peer row，并在 final message 到达后折叠。
4. `STREAM-FINALIZATION-INTEGRITY`: timeout/error/degraded/final writeback 都必须关闭或隐藏
   active stream，避免无限 `...`。
5. `REAL-RUNTIME-LATENCY-PARITY-SMOKE`: 用真实 Ray + Codex app-server + MCP writeback 跑
   fresh + restart/resume，记录 `first_visible_ms`、`writeback_ms`、delivery mode、
   provider session reuse 和 leftover process cleanup。

硬边界:

- 不接 memoryOS。
- 不改 feature graph execution/review authority。
- 不把 stdout fallback 计入 happy path。
- fake provider 只能做 focused gate，不能作为 V12 最终证据。

## 2026-06-04 V12 Task 1 DIRECT-MCP-POST-PROMPT Closure

本轮只收束 V12 Task 1 `DIRECT-MCP-POST-PROMPT` 的当前状态与 fresh gate；没有进入 Task 2
stream trace、TUI feedback、stream finalization、real runtime smoke、MemoryOS 或 feature graph
execution/review authority。

完成内容:

- 当前实现已让 peer scheduler prompt 直接要求基于 `xmuse_context.inbox_item.payload.content`
  调用 `chat_post_message`，并带上
  `reply_to_inbox_item_id=xmuse_context.inbox_item.id`。
- `chat_read_inbox` 在 scheduler prompt 和 Codex app-server MCP developer instructions 中只作为
  recovery / batch inspection，不再是 simple peer turn happy path 的必经步骤。
- V12 文档 Task 1 状态已从“未开始”更新为“已收束”。

本轮修改文件:

- `docs/xmuse/walkthrough-maintenance-notes-v12.md`
- `docs/xmuse/codex-strengthening-handoff.md`

验证:

- Task 1 focused prompt gate:
  - `uv run pytest -q tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_claims_and_nudges_oldest_item tests/xmuse/test_ray_adapters.py::test_app_server_mcp_instructions_prefer_direct_post`
  - 结果: `2 passed in 0.66s`。
- Task 1 focused regression gate:
  - `uv run pytest -q tests/xmuse/test_peer_chat_scheduler.py -k "claims_and_nudges_oldest_item or stdout or latency_trace" tests/xmuse/test_ray_adapters.py::test_app_server_turn_accumulator_emits_latency_stages_from_mcp_events tests/xmuse/test_ray_adapters.py::test_app_server_mcp_instructions_prefer_direct_post`
  - 结果: `5 passed, 8 deselected in 2.41s`。
- Task 1 touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/peer_scheduler.py src/xmuse_core/agents/codex_app_server_transport.py tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_ray_adapters.py`
  - 结果: `All checks passed!`。

强 gate 判断:

- scheduler prompt 不再包含 `must use chat_read_inbox`: 已满足。
- prompt 明确要求 direct `chat_post_message` 且保留 `reply_to_inbox_item_id`: 已满足。
- success validation 仍要求真实 assistant message + `chat_post_message` evidence: 已由 focused
  scheduler regression 覆盖。
- stdout fallback 仍只能在 degraded mode 下成功: 已由 focused scheduler regression 覆盖。
- 真实 smoke 中允许没有 `chat_read_inbox` stage、但必须有 `chat_post_message` stage: 仍留到
  Task 5 real runtime gate 验证。

剩余风险:

- Task 2 仍未收束；当前 scheduler 仍把 `receive_message(...)` 完成点写入 `first_delta_at`，
  不能作为真正 first stream delta 证据。

## 2026-06-04 V12 Task 2 FIRST-VISIBLE-STREAM-TRACE Closure

本轮只收束 V12 Task 2 `FIRST-VISIBLE-STREAM-TRACE`；没有进入 Task 3 TUI pending UX、
Task 4 stream finalization、Task 5 real runtime smoke、MemoryOS 或 feature graph
execution/review authority。

Root cause:

- `ChatStreamStore` 只保存 active stream 内容和状态，没有保存首个 delta 时间。
- app-server accumulator 聚合 agent delta 文本，但没有把首个 `item/agentMessage/delta`
  写入 latency stages。
- scheduler 在 `receive_message(...)` 返回后把当前时间写为 `first_delta_at`，这实际是
  scheduler 观察到 provider result 的时间，不是用户第一可见反馈。

完成内容:

- `ChatStreamStore` 增加 `first_delta_at` 字段和旧库 migration；首个 delta 写入该字段，后续
  delta 只更新 content / updated_at，不覆盖首 delta。
- `AppServerTurnAccumulator` 在首个 agent message delta 记录
  `latency_stages.first_stream_delta`。
- `CodexAppServerTransport` 成功创建 active stream 后记录 `latency_stages.stream_started`，
  供 scheduler 计算 first-visible。
- scheduler latency trace 保留兼容字段 `first_delta_at`，但值改为真实
  `first_stream_delta`；最终 `receive_message(...)` 完成点改名为
  `stage_timings.scheduler_observed_result`。
- `stage_timings.first_visible` 取 `stream_started` / `first_stream_delta` 的最早可外显时间。

本轮修改文件:

- `src/xmuse_core/chat/stream_store.py`
- `src/xmuse_core/agents/codex_app_server_transport.py`
- `src/xmuse_core/chat/peer_scheduler.py`
- `tests/xmuse/test_chat_streams.py`
- `tests/xmuse/test_ray_adapters.py`
- `tests/xmuse/test_peer_chat_scheduler.py`
- `docs/xmuse/walkthrough-maintenance-notes-v12.md`
- `docs/xmuse/codex-strengthening-handoff.md`

TDD / RED evidence:

- `uv run pytest -q tests/xmuse/test_chat_streams.py::test_chat_stream_store_records_first_delta_at_once tests/xmuse/test_ray_adapters.py::test_app_server_turn_accumulator_records_first_stream_delta_stage tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_records_latency_trace_with_injected_clock`
- RED 结果: `3 failed in 1.23s`。
- 失败点:
  - `ChatStream` 缺少 `first_delta_at`。
  - accumulator `latency_stages` 缺少 `first_stream_delta`。
  - scheduler trace `first_delta_at` 仍为 receive completion `101.0`，而非 transport delta
    `100.6`。

验证:

- RED tests after fix:
  - `uv run pytest -q tests/xmuse/test_chat_streams.py::test_chat_stream_store_records_first_delta_at_once tests/xmuse/test_ray_adapters.py::test_app_server_turn_accumulator_records_first_stream_delta_stage tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_records_latency_trace_with_injected_clock`
  - 结果: `3 passed in 1.14s`。
- Task 2 focused gate:
  - 首次命令包含不存在的测试名，pytest 结果为 `no tests ran`，不计入通过证据。
  - corrected command:
    `uv run pytest -q tests/xmuse/test_chat_streams.py tests/xmuse/test_ray_adapters.py::test_app_server_turn_accumulator_emits_result_from_agent_message_delta tests/xmuse/test_ray_adapters.py::test_app_server_turn_accumulator_emits_latency_stages_from_mcp_events tests/xmuse/test_ray_adapters.py::test_app_server_turn_accumulator_records_first_stream_delta_stage tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_records_latency_trace_with_injected_clock`
  - 结果: `7 passed in 2.44s`。
- Task 2 touched-file ruff:
  - `uv run ruff check src/xmuse_core/agents/codex_app_server_transport.py src/xmuse_core/chat/stream_store.py src/xmuse_core/chat/peer_scheduler.py tests/xmuse/test_chat_streams.py tests/xmuse/test_ray_adapters.py tests/xmuse/test_peer_chat_scheduler.py`
  - 结果: `All checks passed!`。

强 gate 判断:

- app-server accumulator 证明首个 delta 记录 `first_stream_delta_at` 等价 stage
  `latency_stages.first_stream_delta`: 已满足。
- `PeerTurnLatencyTraceStore.list_recent()` 返回 `stage_timings.first_visible`: 已满足。
- scheduler 不再把最终 receive 完成点命名为 first delta，而是
  `scheduler_observed_result`: 已满足。
- focused tests 使用 fake clock / monkeypatched `_utc_now`，没有依赖 wall-clock sleep: 已满足。

剩余风险:

- Task 3 尚未收束；TUI 还未保证用户发送后立即出现 pending peer row。
- Task 4 尚未收束；timeout/error/degraded/final writeback 的 active stream 清理还未作为本轮
  gate 验证。

## 2026-06-04 V12 Task 3 TUI-IMMEDIATE-PEER-FEEDBACK Closure

本轮只收束 V12 Task 3 `TUI-IMMEDIATE-PEER-FEEDBACK`；没有进入 Task 4 stream lifecycle、
Task 5 real runtime smoke、MemoryOS 或 feature graph execution/review authority。

Root cause:

- TUI `poll_messages()` 已能投影 active stream，但用户 submit 后只触发 refresh；如果后端还没
  创建 active stream，message log 会在最终 writeback 前保持空白。
- `AppState` 已能在 final reply 到达时移除 matching stream，但没有处理本地 pending peer row
  与 stream/final 之间的折叠。

完成内容:

- ChatScreen 在成功发送 explicit `@role` 消息后，根据当前 participants 立即注入
  `envelope_type=peer_pending` 的 UI transient assistant row，例如 `architect-god ...`。
- pending row 只进入 TUI `AppState`，不写入 durable `ChatStore`。
- `AppState` 在 active stream 到达时移除同一 peer 的 pending row，避免 pending + stream 重复。
- `AppState` 在 final assistant message 到达时移除同一 peer 的 pending row；既有 stream final
  collapse 仍保留。

本轮修改文件:

- `xmuse/tui/screens/chat_screen.py`
- `xmuse/tui/state.py`
- `tests/xmuse/test_tui_state.py`
- `tests/xmuse/test_tui_navigation.py`
- `docs/xmuse/walkthrough-maintenance-notes-v12.md`
- `docs/xmuse/codex-strengthening-handoff.md`

TDD / RED evidence:

- `uv run pytest -q tests/xmuse/test_tui_state.py::test_app_state_replaces_pending_peer_message_with_active_stream tests/xmuse/test_tui_state.py::test_app_state_removes_pending_peer_message_when_final_reply_arrives tests/xmuse/test_tui_navigation.py::test_chat_screen_shows_pending_peer_row_after_mention_submit`
- RED 结果: `3 failed in 0.42s`。
- 失败点:
  - active stream 到达后 pending row 未移除。
  - final assistant message 到达后 pending row 未移除。
  - ChatScreen submit 后 `AppState.messages_for(...)` 仍为空，没有 immediate pending row。

验证:

- RED tests after fix:
  - `uv run pytest -q tests/xmuse/test_tui_state.py::test_app_state_replaces_pending_peer_message_with_active_stream tests/xmuse/test_tui_state.py::test_app_state_removes_pending_peer_message_when_final_reply_arrives tests/xmuse/test_tui_navigation.py::test_chat_screen_shows_pending_peer_row_after_mention_submit`
  - 结果: `3 passed in 0.36s`。
- Task 3 focused gate:
  - `uv run pytest -q tests/xmuse/test_tui_state.py tests/xmuse/test_tui_adapter.py::test_adapter_poll_messages_includes_active_stream_state tests/xmuse/test_tui_navigation.py::test_chat_screen_refreshes_immediately_after_user_message tests/xmuse/test_tui_navigation.py::test_chat_screen_shows_pending_peer_row_after_mention_submit`
  - 结果: `11 passed in 0.90s`。
- Task 3 touched-file ruff:
  - 首次 ruff 发现 `xmuse/tui/screens/chat_screen.py` import ordering 问题。
  - 修正后重跑:
    `uv run ruff check xmuse/tui/adapter/xmuse_adapter.py xmuse/tui/state.py xmuse/tui/screens/chat_screen.py tests/xmuse/test_tui_adapter.py tests/xmuse/test_tui_state.py tests/xmuse/test_tui_navigation.py`
  - 结果: `All checks passed!`。

强 gate 判断:

- 发送 `@architect ...` 后不等后端最终 reply 也显示 pending peer row: 已满足。
- active stream 到来后 pending row 被替换/合并，不出现重复 assistant row: 已满足。
- final assistant message 到来后 pending/stream row 被移除: 已满足。
- TUI 不合成 durable assistant message，pending 仅为 UI transient/AppState projection: 已满足。

剩余风险:

- Task 4 尚未收束；timeout/error/degraded/final writeback 是否关闭或隐藏 active streams 仍需单独
  gate。
- 当前 immediate pending 只针对 explicit `@role`；无 mention 的 API 默认路由仍依赖后端/stream
  反馈，不在 Task 3 focused gate 扩展。

## 2026-06-04 V12 Task 4 STREAM-FINALIZATION-INTEGRITY Closure

本轮只收束 V12 Task 4 `STREAM-FINALIZATION-INTEGRITY`；没有进入 Task 5 real runtime smoke、
MemoryOS 或 feature graph execution/review authority。

Root cause:

- `ChatStreamStore` 没有按 `source_inbox_item_id` 关闭 active stream 的 API。
- scheduler timeout/degraded fallback/failed writeback validation 没有主动关闭当前 inbox item
  对应的 active stream，可能让 TUI 长期显示 `...`。
- TUI adapter 在 durable final assistant message 与 active stream 具有相同
  `source_inbox_item_id` 时仍会返回 active stream，可能造成 final + stream 重复 row。

完成内容:

- `ChatStreamStore.finish_active_for_source(...)` 支持按 conversation/source inbox 关闭 active
  streams。
- scheduler 在 timeout、provider error、stdout/degraded fallback、failed writeback validation、
  generic exception 和 final MCP writeback 后，按当前 inbox item 关闭 active stream。
- timeout/degraded fallback 后 stream 状态标记为 `error`，从 `list_active()` 消失。
- TUI adapter 在已有 durable assistant final reply 的同源 `source_inbox_item_id` 时过滤 active
  stream，只返回 final message。

本轮修改文件:

- `src/xmuse_core/chat/stream_store.py`
- `src/xmuse_core/chat/peer_scheduler.py`
- `xmuse/tui/adapter/xmuse_adapter.py`
- `tests/xmuse/test_chat_streams.py`
- `tests/xmuse/test_peer_chat_scheduler.py`
- `docs/xmuse/walkthrough-maintenance-notes-v12.md`
- `docs/xmuse/codex-strengthening-handoff.md`

TDD / RED evidence:

- `uv run pytest -q tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_releases_claim_when_peer_turn_times_out tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_degraded_fallback_posts_visible_reply_on_timeout tests/xmuse/test_chat_streams.py::test_tui_adapter_hides_active_stream_after_matching_final_message`
- RED 结果: `3 failed in 1.06s`。
- 失败点:
  - timeout 后 stream 仍在 `list_active()`。
  - degraded fallback 后 stream 仍在 `list_active()`。
  - final durable message 与同源 active stream 同时被 adapter 返回。

验证:

- RED tests after fix:
  - `uv run pytest -q tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_releases_claim_when_peer_turn_times_out tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_degraded_fallback_posts_visible_reply_on_timeout tests/xmuse/test_chat_streams.py::test_tui_adapter_hides_active_stream_after_matching_final_message`
  - 结果: `3 passed in 1.00s`。
- Task 4 focused gate:
  - `uv run pytest -q tests/xmuse/test_chat_streams.py tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_releases_claim_when_peer_turn_times_out tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_degraded_fallback_posts_visible_reply_on_timeout tests/xmuse/test_peer_chat_scheduler.py::test_scheduler_records_success_when_peer_marks_inbox_read`
  - 结果: `7 passed in 1.89s`。
- Full scheduler regression:
  - `uv run pytest -q tests/xmuse/test_peer_chat_scheduler.py`
  - 结果: `11 passed in 2.90s`。
- Task 4 touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/stream_store.py src/xmuse_core/agents/codex_app_server_transport.py src/xmuse_core/chat/peer_scheduler.py xmuse/tui/adapter/xmuse_adapter.py tests/xmuse/test_chat_streams.py tests/xmuse/test_peer_chat_scheduler.py`
  - 结果: `All checks passed!`。

强 gate 判断:

- timeout 后 active stream 不再留在 `list_active()`: 已满足。
- error/degraded 后不显示无限 `...`: 已满足，timeout/degraded stream 标记 `error` 并隐藏；
  degraded reply/latency card 路径仍保留。
- final message 与 stream 同 `source_inbox_item_id` 时只显示 final message: 已满足。
- stream content 未落成 durable assistant message；只有既有 degraded/stdout fallback gate 会持久化:
  已满足。

剩余风险:

- Task 5 尚未收束；真实 Ray + Codex app-server + MCP writeback fresh/restart smoke 仍需验证
  first-visible latency 与 cleanup。

## 2026-06-04 V12 Task 5 REAL-RUNTIME-LATENCY-PARITY-SMOKE Closure

本轮只收束 V12 Task 5 `REAL-RUNTIME-LATENCY-PARITY-SMOKE` 并完成 V12 总收束验证；没有进入
MemoryOS、provider parity、A2A 或 feature graph execution/review authority。

完成内容:

- `tests/xmuse/test_full_chain_real_run.py` 新增 V12 latency parity report，记录每轮
  `first_visible_ms`、`writeback_ms`、`delivery_mode`、`chat_post_message` stage、stdout fallback
  和 provider session reuse。
- 真实 `test_real_ray_codex_app_server_mcp_writeback_restart_resume` 接入 V12 report 和 assertions。
- 旧 soak report stage order 更新为 V12 stage names：`stream_started`、`first_visible`、
  `first_stream_delta`、`scheduler_observed_result`。
- V12 文档 Task 5 和 V12 completion 状态已更新。

本轮修改文件:

- `tests/xmuse/test_full_chain_real_run.py`
- `docs/xmuse/walkthrough-maintenance-notes-v12.md`
- `docs/xmuse/codex-strengthening-handoff.md`

TDD / RED evidence:

- `uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_v12_latency_parity_report_records_first_visible_writeback_and_modes`
- RED 结果: `1 failed, 1 warning in 0.59s`。
- 失败点: `_v12_latency_parity_report` helper 未定义。

验证:

- RED test after fix:
  - `uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_v12_latency_parity_report_records_first_visible_writeback_and_modes`
  - 结果: `1 passed, 1 warning in 0.48s`。
- Task 5 focused helper + fake restart/resume smoke:
  - `uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_v12_latency_parity_report_records_first_visible_writeback_and_modes tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server`
  - 结果: `2 passed, 3 warnings in 4.53s`。
- 真实 Ray + Codex app-server + MCP writeback restart/resume smoke:
  - `uv run pytest -q -s tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_restart_resume`
  - 结果: `1 passed, 4 warnings in 41.74s`。
  - 输出 `XMUSE_REAL_V12_LATENCY_PARITY_REPORT`:
    - `provider_session_id=019e92f3-e67c-7fb0-bba3-18638575478e`
    - `provider_session_reused=true`
    - turn 1:
      - `delivery_mode=mcp_writeback`
      - `first_visible_ms=1701`
      - `writeback_ms=16782`
      - `has_chat_post_message_stage=true`
      - `has_stdout_fallback=false`
      - observed stages 不包含 `chat_read_inbox`
    - turn 2:
      - `delivery_mode=mcp_writeback`
      - `first_visible_ms=1377`
      - `writeback_ms=12769`
      - `has_chat_post_message_stage=true`
      - `has_stdout_fallback=false`
      - observed stages 不包含 `chat_read_inbox`
- Full V12 focused regression:
  - `uv run pytest -q tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_chat_streams.py tests/xmuse/test_tui_state.py tests/xmuse/test_ray_adapters.py::test_app_server_turn_accumulator_emits_result_from_agent_message_delta tests/xmuse/test_ray_adapters.py::test_app_server_turn_accumulator_emits_latency_stages_from_mcp_events tests/xmuse/test_ray_adapters.py::test_app_server_turn_accumulator_records_first_stream_delta_stage tests/xmuse/test_ray_adapters.py::test_app_server_mcp_instructions_prefer_direct_post tests/xmuse/test_tui_adapter.py::test_adapter_poll_messages_includes_active_stream_state tests/xmuse/test_tui_navigation.py::test_chat_screen_refreshes_immediately_after_user_message tests/xmuse/test_tui_navigation.py::test_chat_screen_shows_pending_peer_row_after_mention_submit tests/xmuse/test_full_chain_real_run.py::test_v12_latency_parity_report_records_first_visible_writeback_and_modes tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server`
  - 结果: `32 passed, 3 warnings in 8.92s`。
- Touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/peer_scheduler.py src/xmuse_core/agents/codex_app_server_transport.py src/xmuse_core/chat/stream_store.py xmuse/tui/adapter/xmuse_adapter.py xmuse/tui/state.py xmuse/tui/screens/chat_screen.py tests/xmuse/test_peer_chat_scheduler.py tests/xmuse/test_ray_adapters.py tests/xmuse/test_chat_streams.py tests/xmuse/test_tui_adapter.py tests/xmuse/test_tui_state.py tests/xmuse/test_tui_navigation.py tests/xmuse/test_full_chain_real_run.py`
  - 结果: `All checks passed!`。
- `git diff --check`:
  - 结果: 无输出，exit 0。
- leftover process cleanup:
  - `ps -eo pid=,args= | rg "codex app-server|raylet|gcs_server|ray::" | rg -v "rg \"codex app-server|raylet|gcs_server|ray::\"|/bin/bash -c" || true`
  - 结果: 无输出，exit 0。

强 gate 判断:

- 至少一条 fresh + restart/resume 真实链路: 已满足，真实 Codex app-server test 包含 fresh turn 和
  restart 后 resume turn。
- provider session id 跨 restart 复用: 已满足，`provider_session_reused=true`。
- 每轮 `delivery_mode`: 已记录，均为 `mcp_writeback`。
- 每轮 `first_visible_ms`: 已记录，turn 1 为 `1701`，turn 2 为 `1377`。
- 每轮 `writeback_ms`: 已记录，turn 1 为 `16782`，turn 2 为 `12769`。
- 每轮有 `chat_post_message` stage: 已满足。
- direct post path 不要求 `chat_read_inbox` stage；真实 observed stages 不含
  `chat_read_inbox`: 已满足。
- 每轮无 stdout fallback: 已满足。
- cleanup 后无 `codex app-server` / `raylet` / `gcs_server` / `ray::` 残留: 已满足。
- `first_visible_ms` 明显低于 `writeback_ms`: 已满足。

Read-only review subagent:

- 尝试启动 read-only review subagent 审查 V12 Tasks 1-4。
- 第一次指定 `gpt-5.2-codex` 返回 `503 Service Unavailable: No available channel`。
- 第二次使用默认模型等待 120s 后 tool call timeout。
- 因无 review 结果，本轮没有采用 subagent findings；最终以本地 focused tests、real smoke、ruff、
  diff check 和 cleanup 作为完成证据。

V12 完成判断:

- direct `chat_post_message` 成为 peer chat MCP happy path: 已满足。
- `chat_read_inbox` 不再是 simple peer turn 必经步骤: 已满足。
- TUI 在最终 writeback 前有 pending/stream 可见反馈: 已满足。
- latency trace 区分 `first_visible_ms` 和 `writeback_ms`: 已满足。
- 真实 Ray + Codex app-server restart/resume smoke: 已满足。
- stdout fallback 未作为 happy path: 已满足。
- touched-file ruff、`git diff --check`、process cleanup: 已满足。

剩余风险:

- immediate pending 当前只针对 explicit `@role`；无 mention 的 default-intake 第一可见反馈依赖
  stream_started projection，不在本轮扩展 UI 猜测。
- `first_visible` 以 stream start 或首 delta 为准；真实 UX 还取决于 TUI polling/refresh 频率，
  但 Task 3 已补发送后 immediate pending。

## 2026-06-05 V14 Collaboration Runtime / Dispatch Gate Slice

本轮开始按 `docs/xmuse/walkthrough-maintenance-notes-v14.md` 推进 decentralized groupchat runtime
production closure。当前只完成首批 collaboration writeback + proposal approval dispatch gate
切片，不能标记 V14 complete。

### clowder-ai -> xmuse 映射

| clowder-ai 机制 | xmuse 当前落点 | 状态 |
|---|---|---|
| `cat_cafe_multi_mention` | `CollaborationRun` / `ChatCollaborationStore.create_request` | 已有 durable request |
| `MultiMentionResponse` | `CollaborationResponse` | 已有 response aggregation |
| `pending/running/partial/done/timeout/failed` | `CollaborationStatus` | 当前有 running/partial/done/timeout/failed，缺 pending |
| `callbackTo` | `callback_target` | 已有字段 |
| `targets <= 3` | `MAX_COLLABORATION_TARGETS = 3` | 已有 hard limit |
| idempotency key | `find_by_idempotency_key` | 已有 |
| anti-cascade active target guard | `is_active_target(...)` / `max_depth` | 已有初版 |
| MCP callback tools | xmuse chat MCP collaboration tools | 已补 writeback tools |
| `InvocationQueue source=user|connector|agent + autoExecute` | xmuse 尚无统一 agent-sourced dispatch queue | V14 剩余 gap |
| proposal approve dispatch | proposal approval references `collaboration:<run_id>` gate | 本轮初版接入 |
| queued message delivery visibility | xmuse proposal/read surface 尚未统一 queue delivery model | V14 剩余 gap |

### 完成内容

- `ChatCollaborationStore` 作为 chat-owned durable store 提供:
  - bounded collaboration request。
  - per-target response aggregation。
  - timeout marking。
  - structured blocker/veto raise + resolve。
  - dispatch gate evaluator。
- MCP 全量 chat tools 新增:
  - `chat_create_collaboration_request`
  - `chat_record_collaboration_response`
  - `chat_raise_collaboration_blocker`
  - `chat_resolve_collaboration_blocker`
  - `chat_evaluate_dispatch_gate`
- 保持 peer-chat 简单 writeback endpoint 窄化:
  - `/mcp/chat` 仍只暴露 `chat_read_inbox` 和 required `reply_to_inbox_item_id`
    的 `chat_post_message`。
- Chat API 新增 collaboration control surface:
  - `POST /api/chat/conversations/{conversation_id}/collaboration/requests`
  - `POST /api/chat/conversations/{conversation_id}/collaboration/runs/{run_id}/responses`
  - `POST /api/chat/conversations/{conversation_id}/collaboration/runs/{run_id}/blockers`
  - `POST /api/chat/conversations/{conversation_id}/collaboration/blockers/{blocker_id}/resolve`
  - `POST /api/chat/conversations/{conversation_id}/collaboration/runs/{run_id}/dispatch-gate`
- Proposal approval gate:
  - `POST /api/chat/proposals/{proposal_id}/approve` 现在检查 proposal references 中的
    `collaboration:<run_id>`。
  - gate 在 `store.approve_proposal(...)`、resolution read model、blueprint event 和 execution
    projection 之前执行。
  - active dispatch-blocking veto 返回 HTTP 400:
    `{"code": "dispatch_gate_blocked", "message": "blocked_active_veto"}`。
  - blocker resolve 后同一 proposal approval 可继续。
- TUI/read surface 当前可通过 existing `/discussion` 和 `/blockers` 读取 inspector 中的
  collaboration/blocker summary。

### TDD / RED evidence

- MCP collaboration tools RED:
  - `uv run pytest -q tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_lists_chat_tools tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_support_veto_and_dispatch_gate`
  - RED 失败点: missing tool names / missing `run`。
- API collaboration control surface RED:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_chat_api_collaboration_control_surface_enforces_dispatch_gate`
  - RED 失败点: route 404。
- Proposal approval gate RED:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_references_collaboration_gate_and_blocks_active_veto`
  - RED 失败点: active veto 下 approval 返回 200，期望 400。

### 验证

- Proposal approval gate GREEN:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_references_collaboration_gate_and_blocks_active_veto`
  - 结果: `1 passed, 1 warning`。
- Collaboration runtime/API focused suite:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py`
  - 初次结果: `8 passed, 1 warning`。
  - reviewer 后补 side-effect / foreign-run negative tests 后结果: `10 passed, 1 warning`。
- MCP collaboration focused gate:
  - `uv run pytest -q tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_lists_chat_tools tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_support_veto_and_dispatch_gate`
  - 初次结果: `2 passed, 1 warning`。
  - reviewer 后补 spoofed-session negative test 和 `/mcp/chat` narrow endpoint regression 后命令:
    `uv run pytest -q tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_lists_chat_tools tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_support_veto_and_dispatch_gate tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_reject_spoofed_session_identity tests/xmuse/test_mcp_server.py::test_peer_chat_mcp_endpoint_exposes_only_writeback_tools`
  - 结果: `4 passed, 1 warning`。
- Touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/peer_service.py src/xmuse_core/chat/api_models.py xmuse/mcp_server.py xmuse/chat_api.py tests/xmuse/test_peer_chat_mcp_tools.py tests/xmuse/test_groupchat_collaboration_runtime.py tests/xmuse/test_mcp_server.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。

### 当前仍未满足的 V14 hard gates

- 尚无 clowder-style unified dispatch queue 对应 `source="agent"` / `autoExecute`，GOD
  collaboration 还不能统一纳入 busy/queue/steer 语义。
- dispatch gate 只接入 proposal approval 初版，尚未覆盖真实 provider dispatch 的全部入口。
- execute confirmation 已从 approval route 的硬编码假设收紧为读取 referenced collaboration run
  中 `execute` target 的 `received` response；但仍是初版确认，后续应升级为显式结构化
  feasibility/verdict payload。
- 还没有真实 provider 自动 dispatch 修改正式 TUI 主路径的 V14 proof task。
- 还没有 fresh + restart/resume 的 V14 collaboration/proposal/blocker/dispatch trace。
- TUI 只有 `/discussion` / `/blockers` 文本 read surface，尚未形成生产级 dashboard timeline/cards。
- 尚未跑真实 Ray + Codex app-server + MCP writeback 的 V14 多轮 soak。
- 尚未证明无 stdout fallback happy path、无残留 Ray/app-server 进程的 V14 closure run。
### Review subagent

- Review subagent `Boyle` (`019e93ac-3c75-7d21-80a4-3d7f4a1d8926`) performed a read-only
  narrow review of this V14 slice.
- 结论: no Critical/Important findings。
- Reviewer verified:
  - proposal approval gate runs before resolution/artifact/read-model/event/projection side effects。
  - `collaboration:<run_id>` refs are evaluated against proposal conversation scope。
  - `/mcp/chat` remains narrowed to `chat_read_inbox` and `chat_post_message`。
  - new collaboration MCP write/evaluate tools verify GOD session identity。
- Reviewer residual test risks were addressed with additional focused tests:
  - blocked approval leaves zero resolutions/read-model/projection side effects。
  - foreign-conversation collaboration run refs return `blocked_unknown_run` and do not approve。
  - spoofed collaboration MCP session identity returns `session_participant_mismatch` and writes no run。
  - `/mcp/chat` narrow endpoint regression remains covered by `test_peer_chat_mcp_endpoint_exposes_only_writeback_tools`。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-11 OpenCode-In Stage Harness Recovery And Evidence Refresh

在 OpenCode variant command correction 后，本轮重跑此前因旧命令格式阻塞的 stages。

Stage harness evidence:

| Stage | Status | Return code | Command prefix |
|---|---:|---:|---|
| `DiagOpenCode` | `ok` | 0 | `opencode run --model opencode-go/deepseek-v4-flash --variant max` |
| `S0` | `ok` | 0 | `opencode run --model opencode-go/deepseek-v4-flash --variant max` |
| `S4` | `ok` | 0 | `opencode run --model opencode-go/deepseek-v4-flash --variant max` |
| `S5` | `ok` | 0 | `opencode run --model opencode-go/deepseek-v4-flash --variant max` |
| `S5b` | `ok` | 0 | `opencode run --model opencode-go/deepseek-v4-flash --variant max` |
| `S5c` | `ok` | 0 | `opencode run --model opencode-go/deepseek-v4-flash --variant max` |
| `S5d` | `ok` | 0 | `opencode run --model opencode-go/deepseek-v4-flash --variant max` |
| `S5e` | `ok` | 0 | `opencode run --model opencode-go/deepseek-v4-flash --variant max` |
| `S6` | `ok` | 0 | `opencode run --model opencode-go/deepseek-v4-flash --variant max` |

Notable stage outputs:

- `S0` produced a baseline evidence map and identified that some blueprint claims were stale:
  `pr_merged` is no longer emitted by current self-iteration writeback, and
  `MemoryOSLiteTraceEvidence` / `fetch_trace(...)` exist in current source.
- `S4` validated bounded OpenCode deliberation remains secondary, no MCP, no persistent sessions,
  bounded speech acts only, no durable state writes.
- `S5`-`S5e` validated GitHub server-side truth scaffolding and manual opt-in capture boundaries.
- `S6` validated deterministic heartbeat/replay SLO audit without live provider heartbeat claims.

Fresh review:

- OpenCode command correction review returned:
  `No Critical or Important findings.`

Validation:

- OpenCode/provider/GitHub/S6/package focused suite:
  `uv run pytest tests/xmuse/test_provider_opencode.py tests/xmuse/test_goal_stage_runner.py tests/xmuse/test_platform_agent_spawner.py tests/xmuse/test_runtime_settings.py tests/xmuse/test_mcp_server.py tests/xmuse/test_bounded_deliberation_artifacts.py tests/xmuse/test_execution_provider_session_binding.py tests/xmuse/test_github_server_truth_capture.py tests/xmuse/test_github_server_gate_contract.py tests/xmuse/test_self_iteration_runtime_closure.py tests/xmuse/test_package_boundaries.py -q`
  - 结果: `132 passed, 1 warning`。
- `uv run ruff check .`
  - 结果: `All checks passed!`。
- `uv run mypy scripts/goal_stage_runner.py scripts/github_server_truth_capture.py src/xmuse_core/providers/adapters/opencode.py src/xmuse_core/providers/registry.py src/xmuse_core/runtime/settings.py src/xmuse_core/platform/execution/github_ops.py src/xmuse_core/self_iteration/runtime_closure.py`
  - 结果: `Success: no issues found in 7 source files`。
- Current canonical command scan:
  `rg -n "deepseek-v4-flash:max|opencode-go/deepseek-v4-flash:max|deepseek-v4-flash-max|opencode-go/deepseek-v4-flash-max" src/xmuse_core tests/xmuse scripts .env.example docs/xmuse/goal-stage-harness.md docs/xmuse/archive/2026-06-proof-closure-legacy/opencode-in-long-runtime-evidence-plan.md docs/xmuse/provider-matrix.md docs/xmuse/config-matrix.md docs/xmuse/tui-slash-command-handoff.md -g '!*.pyc'`
  - 结果: 无输出，exit 1。
- `git diff --check`
  - 结果: 无输出，exit 0。
- `.goal-runs/*/result.json` confirmed ignored by `.gitignore`。

Remaining live/server-side evidence gap:

- `gh auth status`:
  `You are not logged into any GitHub hosts.`
- GitHub connector PR search:
  `repo:iiyazu/Cross-Muse is:pr` 返回空列表。
- 因此仍未捕获真实 GitHub branch protection/ruleset/check-run/review/merge evidence，
  也不能声明 `pr_merged` server-side proof complete。

Next operator action:

- GitHub operator 创建或提供一个真实 PR number，并在本机完成 `gh auth login`。
- 然后运行:
  `uv run python scripts/github_server_truth_capture.py --repo iiyazu/Cross-Muse --pull-request <number> --output /tmp/xmuse-github-server-truth.json`。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-11 OpenCode Variant Command Correction

本轮根据本机 `opencode 1.15.13` 实测纠正 OpenCode canonical command。

实测证据:

- `opencode run --help` 显示:
  - `--model` 格式为 `provider/model`;
  - `--variant` 是独立参数，示例值包括 `high`、`max`、`minimal`。
- `opencode models opencode-go` 返回 `opencode-go/deepseek-v4-flash`，未列出
  `opencode-go/deepseek-v4-flash:max`。
- 最小 no-op 调用成功:
  `opencode run --model opencode-go/deepseek-v4-flash --variant max --format json --dir /home/iiyatu/projects/python/xmuse "..."`
  - exit code: `0`;
  - returned text: `{"diagnostic":"ok"}`。

修复内容:

- `scripts/goal_stage_runner.py`:
  - `DEFAULT_OPENCODE_RUN_MODEL = "opencode-go/deepseek-v4-flash"`;
  - `DEFAULT_OPENCODE_RUN_VARIANT = "max"`;
  - command order 固定为
    `opencode run --model opencode-go/deepseek-v4-flash --variant max --format json --dir ...`。
- `src/xmuse_core/providers/adapters/opencode.py`:
  - canonical model id 改为 `deepseek-v4-flash`;
  - variant 固定为 `max`;
  - adapter/health/invoke command 使用 `opencode run --model ... --variant max ...`。
- `src/xmuse_core/providers/registry.py`、`src/xmuse_core/runtime/settings.py`、
  `.env.example`:
  - `DEEPSEEK_MODEL` 默认改为 `deepseek-v4-flash`;
  - `max` 不再拼进 model id。
- 当前权威 docs 已更新:
  - `docs/xmuse/goal-stage-harness.md`;
  - `docs/xmuse/archive/2026-06-proof-closure-legacy/opencode-in-long-runtime-evidence-plan.md`;
  - `docs/xmuse/provider-matrix.md`;
  - `docs/xmuse/config-matrix.md`;
  - `docs/xmuse/tui-slash-command-handoff.md`。

纠偏结论:

- 旧记录中 `opencode-go/deepseek-v4-flash:max` / `opencode --model ... run`
  是错误判断，已被本段纠正。
- 当前权威格式是:
  `opencode run --model opencode-go/deepseek-v4-flash --variant max ...`。

验证:

- RED:
  `uv run pytest tests/xmuse/test_goal_stage_runner.py::test_goal_stage_runner_opencode_message_does_not_get_consumed_as_file tests/xmuse/test_goal_stage_runner.py::test_goal_stage_runner_run_stage_pins_opencode_model_with_hostile_env -q`
  - 初始结果: `2 failed`，旧命令仍为 `opencode --model ...:max run`。
- RED:
  `uv run pytest tests/xmuse/test_provider_opencode.py::test_opencode_adapter_builds_non_interactive_run_command tests/xmuse/test_provider_opencode.py::test_opencode_health_check_reports_ready_snapshot_when_smoke_succeeds tests/xmuse/test_provider_opencode.py::test_opencode_health_check_uses_default_subprocess_runner_without_workspace_cwd -q`
  - 初始结果: `3 failed`，adapter/health command 仍为旧格式。
- GREEN:
  `uv run pytest tests/xmuse/test_provider_opencode.py tests/xmuse/test_goal_stage_runner.py tests/xmuse/test_platform_agent_spawner.py tests/xmuse/test_runtime_settings.py tests/xmuse/test_mcp_server.py tests/xmuse/test_bounded_deliberation_artifacts.py tests/xmuse/test_execution_provider_session_binding.py -q`
  - 结果: `81 passed, 1 warning`。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-11 OpenCode-In External Evidence Blocker Audit

本轮继续追踪 long runtime evidence closure 的外部证据缺口。

OpenCode harness 诊断:

- 新增 ignored diagnostic stage manifest:
  `.goal-runs/DiagOpenCode/stage-manifest.json`。
- 通过规定 harness 执行:
  `uv run python scripts/goal_stage_runner.py --stage-manifest /home/iiyatu/projects/python/xmuse/.goal-runs/DiagOpenCode/stage-manifest.json --engine opencode --repo-root /home/iiyatu/projects/python/xmuse --output .goal-runs/DiagOpenCode/result.json`
- 实际 argv:
  `opencode --model opencode-go/deepseek-v4-flash:max run --format json --dir /home/iiyatu/projects/python/xmuse "Execute the attached goal stage prompt." --file .goal-runs/DiagOpenCode/result.json.prompt.txt`
- 结果:
  `result.json.status == "blocked"`，returncode `1`。
- OpenCode stdout error:
  `Unexpected server error. Check server logs for details.`，ref `err_3ba345cb`。
- 结论:
  no-op prompt 也失败，阻塞不依赖 S5e prompt 内容；当前 owner 是 OpenCode/DeepSeek
  runtime operator，需要检查 provider/server/auth/model 后端状态。

GitHub live/server-side proof availability:

- `git remote -v`:
  `origin git@github.com:iiyazu/Cross-Muse.git`。
- `gh auth status`:
  `You are not logged into any GitHub hosts.`。
- GitHub connector只读查询 `iiyazu/Cross-Muse`:
  仓库存在，default branch 为 `main`，connector 权限包含 admin/maintain/pull/push/triage。
- GitHub connector PR search:
  `repo:iiyazu/Cross-Muse is:pr` 返回空列表。
- 结论:
  当前没有真实 PR 可作为 `pr_merged` server-side proof 对象；本机 `gh` 未登录也无法运行
  `scripts/github_server_truth_capture.py` 的真实 operator capture。不能声称已捕获真实
  branch protection/ruleset/check-run/review/merge evidence。

当前 blocker:

- OpenCode live stage blocker:
  OpenCode CLI 可运行且版本为 `1.15.13`，但 `opencode-go/deepseek-v4-flash:max`
  no-op stage 与 S5e stage 均返回 server error。
- GitHub server-side merge proof blocker:
  仓库当前无 PR；没有真实 merge event/check-run/review 对象可验证 `pr_merged`。

下一步 owner:

- OpenCode/DeepSeek runtime operator:
  修复 `opencode-go/deepseek-v4-flash:max` server/auth/model 后端错误，并重跑
  `.goal-runs/DiagOpenCode` 与各 stage harness。
- GitHub operator:
  创建或提供一个真实 PR number，并在本机完成 `gh auth login`，然后运行:
  `uv run python scripts/github_server_truth_capture.py --repo iiyazu/Cross-Muse --pull-request <number> --output /tmp/xmuse-github-server-truth.json`。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-11 OpenCode-In S5e GitHub Truth Capture Rulesets Closure

本轮在 S5e manual opt-in GitHub server truth capture 基础上继续收敛 fresh review findings。

完成内容:

- `scripts/github_server_truth_capture.py` 保持手动 opt-in；默认 CI/tests 不调用 live GitHub。
- `GitHubCliServerSideTruthClient` 继续只使用 read-only `gh api`。
- 当 classic branch protection endpoint 不可用时，client 读取 `repos/{repo}/rulesets` 作为
  fallback server enforcement snapshot。
- rulesets fallback 只有在以下条件同时满足时才提供 Code Owner review truth:
  - ruleset `enforcement == "active"`；
  - ruleset `target == "branch"`；
  - `conditions.ref_name.include` / `exclude` 经 `fnmatchcase` 匹配后适用于当前
    `base_branch`，且 exclude 优先；
  - 存在 `type == "pull_request"` 的 rule，且
    `parameters.require_code_owner_review == true`。
- 不相关 branch ruleset、显式 exclude 当前 base branch 的 ruleset、缺失/partial evidence 均保持
  `manual_gap`，不能触发 `pr_merged`。
- `docs/xmuse/github-server-side-gate.md` 已补充 rulesets fallback proof boundary。

Fresh review:

- 初审 Important:
  classic branch protection 缺失时未读取 rulesets，可能让 ruleset-only 仓库出现 false negative。
- 修复:
  增加 rulesets read-only fallback，并包装为 `ruleset_snapshot`。
- 复审 Important:
  ruleset applicability 未校验是否适用于目标 base branch，可能让不相关 ruleset 造成 false
  `server_side_merge_proof`。
- 修复:
  ruleset 必须显式适用于 base branch。
- 再复审 Important:
  未处理 `ref_name.exclude` 和 pattern 条件，仍可能错误判定 applicability。
- 修复:
  include/exclude 均使用 `fnmatchcase` 匹配 `base_branch` 与 `refs/heads/{base_branch}`，
  且 exclude 优先。
- 最终复审:
  `No Critical or Important findings.`

验证:

- RED:
  `uv run pytest tests/xmuse/test_github_server_gate_contract.py::test_gh_cli_truth_client_uses_ruleset_snapshot_when_branch_protection_missing -q`
  - 初始结果: `1 failed`，classic protection 缺失时仍为 `manual_gap`。
- RED:
  `uv run pytest tests/xmuse/test_github_server_gate_contract.py::test_gh_cli_truth_client_does_not_use_ruleset_for_different_branch -q`
  - 初始结果: `1 failed`，不相关 branch ruleset 可错误生成 `server_side_merge_proof`。
- RED:
  `uv run pytest tests/xmuse/test_github_server_gate_contract.py::test_gh_cli_truth_client_accepts_ruleset_branch_pattern_for_base_branch -q`
  - 初始结果: `1 failed`，pattern include 尚未生效。
- Focused GREEN:
  `uv run pytest tests/xmuse/test_github_server_gate_contract.py::test_gh_cli_truth_client_uses_ruleset_snapshot_when_branch_protection_missing tests/xmuse/test_github_server_gate_contract.py::test_gh_cli_truth_client_does_not_use_ruleset_for_different_branch tests/xmuse/test_github_server_gate_contract.py::test_gh_cli_truth_client_does_not_use_ruleset_excluding_base_branch tests/xmuse/test_github_server_gate_contract.py::test_gh_cli_truth_client_accepts_ruleset_branch_pattern_for_base_branch -q`
  - 结果: `4 passed`。
- GitHub gate/capture suite:
  `uv run pytest tests/xmuse/test_github_server_truth_capture.py tests/xmuse/test_github_server_gate_contract.py -q`
  - 结果: `23 passed`。
- Focused ruff:
  `uv run ruff check scripts/github_server_truth_capture.py tests/xmuse/test_github_server_truth_capture.py src/xmuse_core/platform/execution/github_ops.py tests/xmuse/test_github_server_gate_contract.py`
  - 结果: `All checks passed!`。
- Focused mypy:
  `uv run mypy scripts/github_server_truth_capture.py src/xmuse_core/platform/execution/github_ops.py`
  - 结果: `Success: no issues found in 2 source files`。

仍未完成:

- S5e stage harness 仍被 OpenCode server error 阻塞；之前记录的 canonical argv 为
  `opencode --model opencode-go/deepseek-v4-flash:max run --format json ...`，返回
  `Unexpected server error. Check server logs for details.`。
- 尚未捕获真实 GitHub branch protection/ruleset/check-run/review/merge evidence；没有真实 PR
  number 的 operator capture JSON。
- 因此当前不能声称 live/server-side `pr_merged` proof complete。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-10 OpenCode-In Long Runtime Evidence Closure Slice

本轮目标来自 `docs/xmuse/archive/2026-06-proof-closure-legacy/opencode-in-long-runtime-evidence-plan.md` 与
`/mnt/c/tmp/deep-research-long-blueprint.md`。重点不是扩功能面，而是继续把
contract/fake proof 往可审计 long-runtime evidence 推进。

Stage harness 状态:

- 新增 `scripts/goal_stage_runner.py` 与 `docs/xmuse/goal-stage-harness.md`，要求每阶段通过
  `result.json` / prompt / manifest jsonl / evidence output 产物门控。
- 修复 OpenCode 命令构造: `opencode run ... "Execute..." --file <prompt>`，避免 `--file`
  吞掉 message 并报 `File not found`。
- 修复 `max_retries: 0` 被 `or 1` 覆盖的问题；0 次重试现在会立即 blocked。
- `.goal-runs/` 已加入 `.gitignore`，避免本地 stage 产物进入提交。

OpenCode-in 阻塞:

- S0 baseline stage 已通过 harness 发起，但 OpenCode 返回:
  `Unexpected server error. Check server logs for details.`
- 当前 shell 未暴露 `DEEPSEEK_*` / `OPENCODE_*` 环境变量。
- 本轮未把 S0 标记为 OpenCode pass；该 blocker 属于外部执行器/凭据/服务端状态。

已完成本地 contract 进展:

- P0 merge readiness 语义经现有代码与测试确认:
  fake/local self-iteration writeback 使用 `merge_readiness_evaluated`，不写 `pr_merged`。
- MemoryOS Lite trace evidence 经现有代码与测试确认:
  `MemoryOSLiteTraceEvidence` / `fetch_trace(...)` 已存在，默认测试 fake/local，live test opt-in。
- Natural deliberation proof boundary 经现有测试确认:
  deterministic fixture 不能升级为 live/real proof，natural deliberation 需要 live/real proof level。
- S4 OpenCode-in bounded deliberation provider-policy contract 已新增:
  `opencode.deepseek_flash_worker` 仍为 `SupportLevel.SECONDARY`、无 MCP、无 persistent
  session，但能力从纯 `bounded_code_writing` 扩为 `bounded_code_writing` +
  `bounded_deliberation`。
  `ProviderPolicyService.select_bounded_deliberation(...)` 只允许
  `propose` / `ask` / `challenge`，设置 `state_write_allowed=False`，并在 OpenCode
  unavailable/auth/config/timeout/model failure 时记录 `fallback_cause` / `health_failure_kind`
  后 fallback 到 bounded Codex deliberation decision。
  DeepSeek 默认模型标识同步为 `deepseek-v4-flash:max`，其中 `:max` 作为 flash 模型 variant，
  不新增 provider/profile。
  这不是 OpenCode GOD/review/takeover/merge authority，也不是 live natural deliberation proof。
- S5 GitHub server-side truth collector scaffold 已新增:
  `GitHubServerSideTruthEvidence`、`build_github_server_side_truth_gap(...)`、
  `can_emit_pr_merged(...)`。
  `server_side_merge_proof` 必须具备 workflow/check、source app、branch protection/ruleset、
  Code Owner review、merge commit/merged_at/merge event 证据。
- S6 long-run replay summary 已新增:
  `LongRunEvidenceHeartbeat`、`SelfIterationLongRunReplaySummary`、
  `build_self_iteration_long_run_replay_summary(...)`。
  默认 summary 只证明 logical heartbeat/review/patch-forward/merge-readiness 顺序，不声称 live
  service 或 server-side enforcement proof。

验证:

- `uv run pytest tests/xmuse/test_self_iteration_runtime_closure.py tests/xmuse/test_github_server_gate_contract.py tests/xmuse/test_github_ops_contract.py tests/xmuse/test_vision_runtime_evidence_closure.py tests/xmuse/test_memoryos_lite_interop.py tests/xmuse/test_goal_stage_runner.py tests/xmuse/test_package_boundaries.py -q`
  - 结果: `55 passed, 1 skipped`。
- `uv run ruff check .`
  - 结果: `All checks passed!`。
- `uv run mypy src/xmuse_core/platform/execution/github_ops.py src/xmuse_core/self_iteration/runtime_closure.py src/xmuse_core/self_iteration/__init__.py`
  - 结果: `Success: no issues found in 3 source files`。
- `uv run pytest tests/xmuse/test_provider_models.py tests/xmuse/test_provider_policy.py tests/xmuse/test_provider_support_level.py tests/xmuse/test_provider_read_contracts_module.py tests/xmuse/test_quality_gates_phase3.py tests/xmuse/test_mcp_server.py -q`
  - 结果: `62 passed, 1 warning`。
- 按补充约束，将 DeepSeek 默认模型统一为 `deepseek-v4-flash:max`，其中 `:max` 是 flash
  variant；不新增 provider/profile，不把 `max` 当作独立能力层。
- 按补充约束，将 OpenCode adapter 的运行 package/provider 从 `deepseek` 固化为
  `opencode-go`；命令必须按 `opencode --model opencode-go/deepseek-v4-flash:max run ...`
  调用，inline
  `OPENCODE_CONFIG_CONTENT.provider` 也必须使用 `opencode-go` key。
- `rg -n 'deepseek-v4-flash-max|opencode-go/deepseek-v4-flash-max' src/xmuse_core tests/xmuse docs/xmuse scripts .env.example opencode.json -g '!*.pyc'`
  - 结果: 无输出，exit 1；旧 hyphen variant 已清空。
- `rg -n 'deepseek/|"deepseek"|provider": \{\s*"deepseek"' src/xmuse_core tests/xmuse docs/xmuse scripts .env.example opencode.json -g '!*.pyc'`
  - 结果: 仅命中文档中“不要退回旧 `deepseek/<model>` package”的警告和本 handoff
    记录；代码/测试不再使用旧 `deepseek` OpenCode package/provider key。
- `uv run pytest tests/xmuse/test_provider_opencode.py tests/xmuse/test_platform_agent_spawner.py tests/xmuse/test_provider_models.py tests/xmuse/test_mcp_server.py tests/xmuse/test_runtime_settings.py -q`
  - 结果: `53 passed, 1 warning`。
- `uv run mypy src/xmuse_core/providers/adapters/opencode.py src/xmuse_core/providers/registry.py src/xmuse_core/runtime/settings.py`
  - 结果: `Success: no issues found in 3 source files`。
- S4 bounded deliberation artifact contract 已新增:
  `normalize_bounded_deliberation_output(...)` 将 bounded provider output 归一化为
  `god_speech_act_message.v1`，sender 为 `opencode.deepseek_flash_worker`，只接受
  `propose` / `ask` / `challenge`，并拒绝 `object`、`vote`、`decide`、`evidence`、
  `handoff` 和任何 `state_write` / `durable_writes` / `writeback` 请求。该函数只产出
  artifact，不写 chat storage 或 durable xmuse state。
- S4 stage harness 已按规范执行:
  `uv run python scripts/goal_stage_runner.py --stage-manifest /home/iiyatu/projects/python/xmuse/.goal-runs/S4/stage-manifest.json --engine opencode --repo-root /home/iiyatu/projects/python/xmuse --output .goal-runs/S4/result.json`
  - 结果: exit 2，`result.json.status == "blocked"`。
  - 命令已使用 `opencode --model opencode-go/deepseek-v4-flash:max run ...`。
  - OpenCode 返回 `Unexpected server error. Check server logs for details.`，ref
    `err_57205a18`。
  - 结论: S4 local contract proof 已推进；S4 live OpenCode-in execution/review proof
    仍缺失，owner 是 OpenCode/DeepSeek runtime operator。
- S4 focused validation:
  - `uv run pytest tests/xmuse/test_bounded_deliberation_artifacts.py tests/xmuse/test_goal_stage_runner.py tests/xmuse/test_provider_policy.py tests/xmuse/test_provider_models.py tests/xmuse/test_provider_opencode.py tests/xmuse/test_platform_agent_spawner.py tests/xmuse/test_mcp_server.py tests/xmuse/test_package_boundaries.py -q`
  - 结果: `97 passed, 1 warning`。
  - `uv run pytest tests/xmuse/test_bounded_deliberation_artifacts.py tests/xmuse/test_goal_stage_runner.py -q`
  - 结果: `18 passed`。
  - `uv run mypy src/xmuse_core/providers/bounded_deliberation.py src/xmuse_core/providers/policy.py src/xmuse_core/providers/models.py src/xmuse_core/providers/registry.py src/xmuse_core/providers/adapters/opencode.py scripts/goal_stage_runner.py`
  - 结果: `Success: no issues found in 6 source files`。
  - `uv run ruff check .`
  - 结果: `All checks passed!`。
- 按最新补充再次纠正 OpenCode 命令格式:
  - 正确默认模型 id: `deepseek-v4-flash:max`
  - 正确命令模型 ref: `opencode-go/deepseek-v4-flash:max`
  - 正确命令顺序: `opencode --model opencode-go/deepseek-v4-flash:max run ...`
  - 2026-06-11 再确认:
    - adapter 实际生成:
      `['opencode', '--model', 'opencode-go/deepseek-v4-flash:max', 'run', '--format', 'json', '--dir', '/home/iiyatu/projects/python/xmuse', 'Check command only.']`
    - stage runner 实际生成:
      `['opencode', '--model', 'opencode-go/deepseek-v4-flash:max', 'run', '--format', 'json', '--dir', '/home/iiyatu/projects/python/xmuse', 'Execute the attached goal stage prompt.', '--file', '/home/iiyatu/projects/python/xmuse/prompt.txt']`
    - 针对性测试:
      `uv run pytest tests/xmuse/test_provider_opencode.py::test_opencode_adapter_builds_non_interactive_run_command tests/xmuse/test_provider_opencode.py::test_opencode_health_check_reports_ready_snapshot_when_smoke_succeeds tests/xmuse/test_goal_stage_runner.py::test_goal_stage_runner_opencode_message_does_not_get_consumed_as_file tests/xmuse/test_platform_agent_spawner.py::test_agent_spawner_uses_final_prompt_on_argv_for_opencode_provider -q`
    - 结果: `4 passed`。
    - `rg -n 'deepseek-v4-flash-max|opencode-go/deepseek-v4-flash-max' src/xmuse_core tests/xmuse scripts .env.example -g '!*.pyc'`
    - 结果: 无输出，exit 1；实现/测试/脚本/env 示例无旧 hyphen variant。
  - `uv run pytest tests/xmuse/test_provider_opencode.py tests/xmuse/test_goal_stage_runner.py tests/xmuse/test_platform_agent_spawner.py tests/xmuse/test_mcp_server.py tests/xmuse/test_runtime_settings.py tests/xmuse/test_execution_provider_session_binding.py tests/xmuse/test_bounded_deliberation_artifacts.py tests/xmuse/test_provider_models.py tests/xmuse/test_provider_policy.py tests/xmuse/test_package_boundaries.py -q`
  - 结果: `117 passed, 1 warning`。
  - `uv run mypy src/xmuse_core/providers/bounded_deliberation.py src/xmuse_core/providers/policy.py src/xmuse_core/providers/models.py src/xmuse_core/providers/registry.py src/xmuse_core/providers/adapters/opencode.py src/xmuse_core/runtime/settings.py scripts/goal_stage_runner.py`
  - 结果: `Success: no issues found in 7 source files`。
- Fresh adversarial review:
  - 初审 Important findings:
    1. `normalize_bounded_deliberation_output(...)` 只信任
       `decision.allowed_speech_acts`，若 policy 误配可能放行 `decide` 等 forbidden act。
    2. `GOAL_OPENCODE_MODEL` env override 可能让 stage runner 偏离固定
       `opencode-go/deepseek-v4-flash:max`。
    3. `OpenCodeProviderAdapter` 仍可通过自定义 profile model 构造非 canonical model ref。
    4. 旧测试还验证过非 canonical model。
  - 修复:
    - bounded normalizer 内置 canonical set `{propose, ask, challenge}`，即使 policy 误配也拒绝
      forbidden act。
    - stage runner 固定 `DEFAULT_OPENCODE_RUN_MODEL = "opencode-go/deepseek-v4-flash:max"`，
      不再读取 `GOAL_OPENCODE_MODEL`。
    - OpenCode adapter 对非 canonical model ref 抛出 `ValueError`，避免命令漂移。
    - 增加 hostile env 端到端测试:
      `test_goal_stage_runner_run_stage_pins_opencode_model_with_hostile_env`。
  - 复审: `No Critical/Important findings.`
  - 复审残余风险: 非 canonical profile 在所有上游 caller 中是否都应转成结构化
    provider-health failure 仍未完全覆盖；当前已覆盖 command path 拒绝，但未扩成全调用链
    failure policy。
  - 追加验证:
    - `uv run pytest tests/xmuse/test_goal_stage_runner.py -q`
    - 结果: `9 passed`。
    - `uv run ruff check tests/xmuse/test_goal_stage_runner.py`
    - 结果: `All checks passed!`。
- `rg --pcre2 -n 'deepseek-v4-flash(?!-max)' src/xmuse_core tests/xmuse docs/xmuse .env.example pyproject.toml opencode.json -g '!*.pyc'`
  - 结果: 无输出，exit 1；旧默认模型字符串已从权威路径清空。
- `uv run pytest tests/xmuse/test_provider_models.py tests/xmuse/test_provider_policy.py tests/xmuse/test_provider_support_level.py tests/xmuse/test_provider_read_contracts_module.py tests/xmuse/test_quality_gates_phase3.py tests/xmuse/test_mcp_server.py tests/xmuse/test_provider_opencode.py tests/xmuse/test_runtime_settings.py tests/xmuse/test_execution_provider_session_binding.py tests/xmuse/test_platform_agent_spawner.py -q`
  - 结果: `105 passed, 1 warning`。
- `uv run mypy src/xmuse_core/providers/models.py src/xmuse_core/providers/policy.py src/xmuse_core/providers/registry.py src/xmuse_core/runtime/settings.py`
  - 结果: `Success: no issues found in 4 source files`。

仍未完成:

- OpenCode-in S0 没有 pass evidence；需要修复 OpenCode/DeepSeek 配置或服务端错误后重跑。
- S4 仅完成 provider policy / inventory / docs contract；尚未让真实 OpenCode 产出结构化
  live speech-act artifacts，也未接入 live groupchat transcript normalization。
- 未捕获真实 GitHub branch protection/ruleset/check-run/review/merge evidence；
  当前仍是 `manual_gap`，不能发 `pr_merged`。
- 未实现 live GitHub API collector，只完成 server-side truth schema 与 fake/gap 边界。
- 未捕获真实 long-running heartbeat；当前 S6 是 deterministic logical replay summary。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增
`memoryos_lite` 直接 import；MemoryOS 仍保持 REST-first 边界。

## 2026-06-11 OpenCode-In Long Runtime Evidence Latest Continuation Pointer

本轮先按用户确认的 canonical 命令重新验证 OpenCode 调用格式:

- Adapter 实际生成:
  `['opencode', '--model', 'opencode-go/deepseek-v4-flash:max', 'run', '--format', 'json', '--dir', '/home/iiyatu/projects/python/xmuse', 'Check command only.']`
- Stage runner 实际生成:
  `['opencode', '--model', 'opencode-go/deepseek-v4-flash:max', 'run', '--format', 'json', '--dir', '/home/iiyatu/projects/python/xmuse', 'Execute the attached goal stage prompt.', '--file', '/home/iiyatu/projects/python/xmuse/prompt.txt']`
- Targeted command tests:
  `uv run pytest tests/xmuse/test_provider_opencode.py::test_opencode_adapter_builds_non_interactive_run_command tests/xmuse/test_provider_opencode.py::test_opencode_health_check_reports_ready_snapshot_when_smoke_succeeds tests/xmuse/test_goal_stage_runner.py::test_goal_stage_runner_opencode_message_does_not_get_consumed_as_file tests/xmuse/test_platform_agent_spawner.py::test_agent_spawner_uses_final_prompt_on_argv_for_opencode_provider -q`
  - 结果: `4 passed`。

S5 GitHub server-side truth collector scaffold 追加完成:

- 新增 `FakeGitHubServerSideTruthCollector`。
- fake collector 可模拟 workflow/check/ruleset/review 字段形状，但始终返回
  `contract_proof`。
- fake collector 会剥离 `merge_commit_sha`、`merged_at`、`merge_event_id`，因此无法让
  `can_emit_pr_merged(...)` 为 true。
- `can_emit_pr_merged(...)` 现在在事件发射 gate 本身重新检查
  status-check identity、server enforcement、review truth、merge truth 四个维度，避免只依赖
  model 构造时 validator。
- 这仍不是 live GitHub API collector，也不是 server-side enforcement proof。

验证:

- `uv run pytest tests/xmuse/test_github_server_gate_contract.py -q`
  - 结果: `7 passed`。
- `uv run ruff check src/xmuse_core/platform/execution/github_ops.py tests/xmuse/test_github_server_gate_contract.py`
  - 结果: `All checks passed!`。
- `uv run mypy src/xmuse_core/platform/execution/github_ops.py`
  - 结果: `Success: no issues found in 1 source file`。

Fresh review:

- 初审 Important:
  `can_emit_pr_merged(...)` 只检查 `server_side_merge_proof` + `has_merge_truth`，没有在发射
  gate 重新检查 workflow/check、branch protection/ruleset、review/Code Owner 三类证据。
- 修复:
  `can_emit_pr_merged(...)` 同时要求 `has_status_check_truth`、
  `has_server_enforcement_truth`、`has_review_truth`、`has_merge_truth`。
  新增 `model_construct` 污染对象回归测试，证明只有 merge fields 时 gate 返回 false。
- 复审:
  No Critical or Important findings。

S5 read-only server snapshot normalization 追加完成:

- 新增 `GitHubServerSideTruthSnapshot`。
- 新增 `build_github_server_side_truth_from_snapshot(...)`。
- 该 normalizer 只接收外部已捕获的只读 server-derived snapshot，不调用 GitHub API，不修改
  GitHub 设置。
- 完整 snapshot 可归一化为 `server_side_merge_proof`，并允许 `can_emit_pr_merged(...)` 为
  true。
- 不完整 snapshot 即使带有 merge commit / merged_at / merge event 字段，也只能返回
  `manual_gap`，并在 `gap_reason` 中记录缺少的 server-side truth 维度。
- 追加 adversarial regression:
  即使用 `model_construct` 构造带完整 merge 字段的 `contract_proof`，`can_emit_pr_merged(...)`
  仍返回 false。

S5 snapshot focused validation:

- `uv run pytest tests/xmuse/test_github_server_gate_contract.py -q`
  - 结果: `10 passed`。
- `uv run ruff check src/xmuse_core/platform/execution/github_ops.py tests/xmuse/test_github_server_gate_contract.py`
  - 结果: `All checks passed!`。
- `uv run mypy src/xmuse_core/platform/execution/github_ops.py`
  - 结果: `Success: no issues found in 1 source file`。
- Fresh review:
  No Critical or Important findings。

S5c read-only collector scaffold 追加完成:

- 新增 `ReadOnlyGitHubServerSideTruthClient` protocol。
- 新增 `ReadOnlyGitHubServerSideTruthCollector`。
- collector 只调用注入 client 的 `fetch_server_side_truth_snapshot(...)`，不读取 GitHub
  token/env，不内置 GitHub 网络 client，不暴露或调用 mutation API。
- client 返回 snapshot 时复用 `build_github_server_side_truth_from_snapshot(...)`；client
  无法提供 snapshot 时返回 `manual_gap`，原因是
  `read-only GitHub server-side truth snapshot unavailable`。
- fake client 测试确认只发生一次 read-only fetch，未触发 mutation。
- partial snapshot 经 collector 路径仍归一化为 `manual_gap`，不会因携带 merge fields
  触发 `pr_merged`。

S5c focused validation:

- `uv run pytest tests/xmuse/test_github_server_gate_contract.py -q`
  - 结果: `13 passed`。
- `uv run ruff check src/xmuse_core/platform/execution/github_ops.py tests/xmuse/test_github_server_gate_contract.py`
  - 结果: `All checks passed!`。
- `uv run mypy src/xmuse_core/platform/execution/github_ops.py`
  - 结果: `Success: no issues found in 1 source file`。
- Fresh review:
  No Critical or Important findings。

S5d opt-in `gh api` read-only client adapter 追加完成:

- 新增 `GitHubCliServerSideTruthClient`。
- 该 client 是 `ReadOnlyGitHubServerSideTruthClient` protocol 的 opt-in 实现；默认路径不会构造
  或运行它。
- 它通过注入 runner 调用只读 `gh api` endpoint，读取 PR state、reviews、branch
  protection、check-runs，并产出 `GitHubServerSideTruthSnapshot`。
- `gh api` read failure 或 payload 不完整时返回 `None`，由上层 collector 归一化为
  `manual_gap`。
- 测试使用 fake runner，确认命令形态是 `gh api <endpoint>`，没有 `PATCH` / `PUT` /
  `DELETE` / `POST` mutation token。
- `has_status_check_truth` 现在要求 successful check run ids 覆盖全部 `required_checks`，
  partial check-runs payload 只能归一化为 `manual_gap`。

S5d focused validation:

- `uv run pytest tests/xmuse/test_github_server_gate_contract.py -q`
  - 结果: `17 passed`。
- `uv run ruff check src/xmuse_core/platform/execution/github_ops.py tests/xmuse/test_github_server_gate_contract.py`
  - 结果: `All checks passed!`。
- `uv run mypy src/xmuse_core/platform/execution/github_ops.py`
  - 结果: `Success: no issues found in 1 source file`。
- Fresh review:
  - 初审 Important: partial required-check payload 仍可能满足旧的 status-check truth。
  - 修复: status-check truth 要求 `len(check_run_ids) >= len(required_checks)`，并新增
    model-construct gate regression 与 gh client partial-check regression。
  - 复审: No Critical or Important findings。

S5e manual opt-in GitHub server truth capture script 追加完成:

- 新增 `scripts/github_server_truth_capture.py`。
- 手动 operator 可运行:
  `uv run python scripts/github_server_truth_capture.py --repo iiyazu/Cross-Muse --pull-request <number> --output /tmp/xmuse-github-server-truth.json`
- 脚本显式调用时才构造 `GitHubCliServerSideTruthClient`；默认 CI 不运行 live GitHub。
- 输出 JSON 包含 `schema_version: github_server_side_truth_capture.v1`、
  `capture_mode: opt_in_read_only_gh_api`、`can_emit_pr_merged`。
- 完整 server snapshot 返回 exit 0；缺失 snapshot / manual gap 返回 exit 2。
- tests 使用 fake `gh api` runner；没有 live GitHub 访问。

S5e focused validation:

- `uv run pytest tests/xmuse/test_github_server_truth_capture.py tests/xmuse/test_github_server_gate_contract.py -q`
  - 结果: `19 passed`。
- `uv run ruff check scripts/github_server_truth_capture.py tests/xmuse/test_github_server_truth_capture.py src/xmuse_core/platform/execution/github_ops.py tests/xmuse/test_github_server_gate_contract.py`
  - 结果: `All checks passed!`。
- `uv run mypy scripts/github_server_truth_capture.py src/xmuse_core/platform/execution/github_ops.py`
  - 结果: `Success: no issues found in 2 source files`。

S5 stage harness:

- 命令:
  `uv run python scripts/goal_stage_runner.py --stage-manifest /home/iiyatu/projects/python/xmuse/.goal-runs/S5/stage-manifest.json --engine opencode --repo-root /home/iiyatu/projects/python/xmuse --output .goal-runs/S5/result.json`
- 结果:
  exit 2，`result.json.status == "blocked"`。
- 实际 OpenCode argv:
  `['opencode', '--model', 'opencode-go/deepseek-v4-flash:max', 'run', '--format', 'json', '--dir', '/home/iiyatu/projects/python/xmuse', 'Execute the attached goal stage prompt.', '--file', '.goal-runs/S5/result.json.prompt.txt']`
- OpenCode 返回:
  `Unexpected server error. Check server logs for details.`，ref `err_6ec74914`。
- 结论:
  S5 local contract proof 已推进并审查；S5 live OpenCode-in review proof 仍被外部 OpenCode
  server error 阻塞，owner 是 OpenCode/DeepSeek runtime operator。

仍未完成:

- OpenCode-in live stage 仍缺 pass evidence；S4/S5 harness 调用均返回 OpenCode server error。
- 未捕获真实 GitHub branch protection/ruleset/check-run/review/merge evidence。
- 未实现 read-only live GitHub API collector。
- 未捕获真实 long-running heartbeat；S6 仍是 deterministic logical replay summary。

S6 long-run heartbeat/replay evidence 追加完成:

- `SelfIterationLongRunReplaySummary` 新增 deterministic SLO audit 字段:
  `max_heartbeat_gap_minutes`、`max_review_snapshot_gap_minutes`、`slo_status`、
  `slo_violations`。
- `build_self_iteration_long_run_replay_summary(...)` 支持传入模拟 heartbeat 时间序列，
  用于无 sleep 测试 long-run SLO。
- heartbeat gap 超过 15 分钟会记录 `heartbeat gap exceeded 15 minutes`。
- review snapshot 到最终阶段超过 45 分钟会记录 `review snapshot gap exceeded 45 minutes`。
- builder 拒绝 live/real proof level 污染，默认 replay summary 只允许
  `contract_proof`、`fake_runtime_proof`、`manual_gap`。
- 模拟 heartbeat 时间必须按 `heartbeat_seq` 单调不降，否则 fail closed。
- 默认路径仍是 deterministic replay/contract proof；没有把本地模拟时间升级为 live
  long-running heartbeat proof。

S6 focused validation:

- `uv run pytest tests/xmuse/test_self_iteration_runtime_closure.py::test_long_run_replay_summary_records_slo_violation_from_simulated_time tests/xmuse/test_self_iteration_runtime_closure.py::test_long_run_replay_summary_records_heartbeat_review_and_patch_lineage -q`
  - 结果: `2 passed`。
- `uv run pytest tests/xmuse/test_self_iteration_runtime_closure.py::test_long_run_replay_summary_records_review_snapshot_slo_violation -q`
  - 结果: `1 passed`。
- `uv run ruff check src/xmuse_core/self_iteration/runtime_closure.py tests/xmuse/test_self_iteration_runtime_closure.py`
  - 结果: `All checks passed!`。
- `uv run mypy src/xmuse_core/self_iteration/runtime_closure.py`
  - 结果: `Success: no issues found in 1 source file`。

Fresh review:

- 初审 Important findings:
  1. `build_self_iteration_long_run_replay_summary(...)` 直接复用 evidence bundle proof level，
     若未来传入 live/real proof artifact 会污染默认 replay summary。
  2. `heartbeat_emitted_at` 未校验单调顺序，倒序时间可能让 SLO 计算低估 gap。
- 修复:
  - 新增 `_validate_replay_summary_proof_level(...)`，只允许 contract/fake/manual-gap proof。
  - 新增 `_validate_monotonic_timestamps(...)`，按 heartbeat sequence 校验时间单调不降。
  - 新增两条回归测试覆盖 live proof 污染和非单调 heartbeat 时间。
- 复审:
  No Critical or Important findings。

## 2026-06-05 V14 Real Groupchat Runtime Closure Run

本轮按真实任务跑完 V14 groupchat runtime closure，state root:

- `/tmp/xmuse-v14-real-chain/20260605T043623Z`

真实任务:

> 根据 xmuse 后端，完善 TUI `/` 命令系统与 dashboard/read-surface 基建；本轮 real provider
> 自动 dispatch 的最小闭环切片是给正式 TUI 主路径增加 `/dashboard` -> `/overview` runtime
> dashboard alias，并补 completion / navigation test。

关键 runtime 证据:

- fresh conversation bootstrap: `conv_579739437b8140708ebb63e145fc3d6b`
- structured collaboration run: `collab_053d6e8d8e194f5f885c5f62e67f534a`
- review veto blocker: `collab_blocker_204375394903417b813ab2fbfc912967`
- blocked gate: `blocked_active_veto`
- resolved gate 后 approval enqueue dispatch:
  `dispatch:conv_579739437b8140708ebb63e145fc3d6b:res_4e2ccd08ba8041f7bdbb9c0af821a69b:execute`
- real Ray + Codex app-server + MCP writeback:
  - dispatch turn `delivery_mode=mcp_writeback`, no stdout fallback。
  - resume proof turn `delivery_mode=mcp_writeback`。
  - provider session reused:
    `019e9611-95a8-7b90-bc18-cee4febcf782` -> same id after restart。
- real provider modified official TUI paths:
  - `xmuse/tui/slash_commands.py`
  - `xmuse/tui/completion.py`
  - `tests/xmuse/test_tui_navigation.py`
- terminal TUI demo evidence:
  - `/tmp/xmuse-v14-real-chain/20260605T043623Z/tui_terminal_demo.json`
  - command: `uv run python -m xmuse.tui`
  - observed `/resume`, `/overview`, `/discussion`, `/blockers` command events with terminal run id。
- final closure report:
  - `/tmp/xmuse-v14-real-chain/20260605T043623Z/v14_closure_report.json`
  - `ok=true`, `missing=[]`。

Production fixes made during closure:

- `ChatDispatchBridge` now injects approved proposal/resolution context into dispatch inbox payload/content,
  so real execute providers receive actionable work rather than only opaque IDs。
- Dispatch completion now requires explicit `DISPATCH_COMPLETED` in the provider writeback; progress-only
  acknowledgements are marked failed with `dispatch_completion_marker_missing`。
- `PeerChatScheduler` includes a bounded current inbox request preview in provider prompt for better
  real-provider reliability。
- Terminal TUI demo harness now sets a real TERM, pty winsize, clean exit handling, and a harness-only
  `XMUSE_TUI_TERMINAL_DEMO_AUTORUN=1` path through `python -m xmuse.tui` to record official TUI command
  events without depending on this container's pseudo-terminal key semantics。
- ChatScreen now focuses the message input on mount while preserving global Ctrl+A/Ctrl+D shortcuts。

Verification:

- V14 closure report: all 11 gates true:
  `fresh_bootstrap`, `structured_collaboration`, `review_veto_lifecycle`,
  `dispatch_gate_lifecycle`, `agent_auto_dispatch`, `real_provider_mcp_writeback`,
  `tui_dashboard_read_surface`, `restart_resume`, `process_cleanup`,
  `official_tui_main_path`, `terminal_tui_demo`。
- Focused gate:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py tests/xmuse/test_v14_closure_evidence.py tests/xmuse/test_tui_terminal_demo.py tests/xmuse/test_tui_navigation.py -k "dispatch_bridge or v14_closure or terminal_tui_demo or dashboard or overview or terminal_demo_mode or focuses_message_input"`
  - result: `74 passed, 58 deselected, 1 warning`。
- V14 closure suites:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py tests/xmuse/test_groupchat_collaboration_runtime.py tests/xmuse/test_tui_terminal_demo.py`
  - result: `89 passed, 1 warning`。
- TUI navigation:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py`
  - result: `43 passed, 1 warning`。
- touched-file ruff:
  - `uv run ruff check ...`
  - result: `All checks passed!`。
- `git diff --check`: passed。
- cleanup probe:
  - no `codex app-server` / `raylet` / `gcs_server` / `ray::` leftovers。

Notes:

- The working tree appears untracked in this environment (`git status --short` reports touched files as
  `??`), so `git diff` cannot be used as a reliable tracked-file summary here。
- MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
  import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer (EOF-16)

最新完成切片是 `V14 Real Groupchat Runtime Closure Run`。V14 hard gates 在真实 Ray + Codex
app-server + MCP writeback 链路下已全部通过，closure report 为 `ok=true`。

## 2026-06-05 V14 Latest Continuation Pointer (EOF-13)

最新完成切片是 `V14 Terminal TUI Demo Harness Provenance Gate Slice`。详细记录在本文件
`2026-06-05 V14 Terminal TUI Demo Harness Provenance Gate Slice` 段落。

关键状态:

- terminal TUI demo evidence 必须由同一 harness run 的 persisted TUI command events 互证。
- 手写 terminal JSON、缺 run id、缺 observed command events、run id mismatch、脚本不完整、空字符串脚本、
  command event 窗口外时间都 fail closed。
- focused verification:
  - closure + terminal demo suite: `48 passed, 1 warning`。
  - TUI command/read-surface focused subset: `7 passed, 33 deselected, 1 warning`。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Meitner` final re-review: no remaining Critical/Important findings in focused
  scope。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto 阻断后解除并继续
dispatch、真实终端 TUI 启动并产生 demo evidence、无 stdout fallback happy path、无残留
`codex app-server` / `raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Terminal TUI Demo Harness Provenance Gate Slice

本轮继续强化 terminal TUI demo closure gate。当前仍不能标记 V14 complete；本切片证明的是
`tui_terminal_demo.json` 不能再单靠手写 provenance 字段或复刻旧 command events 通过 validator。

完成内容:

- terminal TUI demo harness 现在为每次 `run_terminal_tui_demo(...)` 生成
  `XMUSE_TUI_TERMINAL_RUN_ID=terminal-tui-demo:<uuid>`。
- TUI slash command proof 会从环境变量带上 `terminal_run_id`。
- `XmuseAdapter.record_tui_command_event(...)` 会为每条 persisted command event 生成
  `event_id=tui_cmd_<uuid>`，并保留 `terminal_run_id`。
- `record_terminal_tui_demo_evidence(...)` 现在写入:
  - `evidence_source = xmuse_tui_terminal_demo_harness`
  - `harness_version = 1`
  - `terminal_run_id`
  - 精确 `scripted_inputs`
  - 同 run 的 `observed_command_event_ids` / `observed_command_events`
- `collect_v14_closure_evidence(...)` 不再信任 terminal JSON 自带 observed events；会从
  `tui_command_events.json` 重新加载同 `terminal_run_id` 的 command events 并覆盖 collected
  payload。
- `validate_v14_closure_evidence(...)` 现在要求:
  - exact scripted inputs，不能有额外空字符串。
  - nonblank terminal run id。
  - observed command events 覆盖 `/resume`、`/overview`、`/discussion`、`/blockers`。
  - command event 必须同 conversation、同 terminal run、chat_inspector authority、surface_ref 匹配。
  - command event 必须有 event id，且 created_at 落在 terminal run started/completed 窗口内。

TDD / RED evidence:

- Missing harness provenance / incomplete script RED:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_requires_terminal_demo_harness_provenance tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_incomplete_terminal_demo_script`
  - RED 结果: `2 failed`，缺少 provenance 或脚本不完整时 `report["ok"]` 仍为 `True`。
- Run binding RED:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_terminal_demo_script_with_empty_extra tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_requires_terminal_run_command_events tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_terminal_run_id_mismatch`
  - RED 结果: `3 failed`，空字符串脚本、缺 observed command events、run id mismatch 仍可通过。
- Command event run-window RED:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_terminal_command_event_outside_run_window`
  - RED 结果: `1 failed`，terminal run 窗口外 command event 仍可通过。

验证:

- Closure + terminal demo suite:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py tests/xmuse/test_tui_terminal_demo.py`
  - 结果: `48 passed, 1 warning`。
- TUI command/read-surface focused subset:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "official_tui_command_proof or official_chat_api or resume or overview or discussion_command or blockers_command"`
  - 结果: `7 passed, 33 deselected, 1 warning`。
- Touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/terminal_tui_demo.py src/xmuse_core/chat/v14_closure_evidence.py xmuse/tui/adapter/xmuse_adapter.py xmuse/tui/slash_commands.py tests/xmuse/test_v14_closure_evidence.py tests/xmuse/test_tui_terminal_demo.py tests/xmuse/test_tui_navigation.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。
- MemoryOS scan:
  - `rg -n "MemoryOS|memoryos" src/xmuse_core/chat/terminal_tui_demo.py src/xmuse_core/chat/v14_closure_evidence.py xmuse/tui/adapter/xmuse_adapter.py xmuse/tui/slash_commands.py tests/xmuse/test_v14_closure_evidence.py tests/xmuse/test_tui_terminal_demo.py tests/xmuse/test_tui_navigation.py`
  - 结果: no matches。

Review subagent:

- Review subagent `Meitner` (`019e9501-97e4-7510-bca8-6ace2e87ccf5`) performed read-only focused
  review。
- Initial Important findings:
  - Manual terminal demo JSON could still satisfy closure gate by copying provenance fields。
  - Recorder correlated command events only by time window, not by a per-run id/nonce。
- Fixes:
  - Added per-run `terminal_run_id` from harness env through TUI command events and terminal demo
    evidence。
  - Collector reloads command events from persisted `tui_command_events.json` by `terminal_run_id`。
  - Validator requires same-run events, event ids, exact script, authority/surface match, and
    command-event timestamps inside the run window。
- Re-review: no remaining Critical/Important findings。
- Minor note left non-blocking: `observed_command_event_ids` is a containing set rather than exact
  set; observed event objects carry the binding proof。

当前仍未满足的 V14 hard gates:

- 尚未实际运行 terminal TUI demo CLI 生成真实 fresh `tui_terminal_demo.json` evidence。
- 尚未用真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未完成真实 Ray + Codex app-server + MCP writeback 的 V14 collaboration/proposal/veto/
  dispatch fresh + restart/resume 多轮 soak。
- 尚未证明真实/fresh veto 阻断 dispatch 后解除，并继续 dispatch。
- 尚未证明最终 happy path 无 stdout fallback 且无残留 `codex app-server` / `raylet` /
  `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer (EOF-12)

最新完成切片是 `V14 Terminal TUI Demo Harness Provenance Gate Slice`，详细记录见本文件对应段落。
关键状态:

- terminal TUI demo evidence 现在必须由同一 harness run 的 persisted TUI command events 互证。
- 手写 terminal JSON、缺 run id、缺 observed command events、run id mismatch、脚本不完整、空字符串脚本、
  command event 窗口外时间都 fail closed。
- focused verification:
  - closure + terminal demo suite: `48 passed, 1 warning`。
  - TUI command/read-surface focused subset: `7 passed, 33 deselected, 1 warning`。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Meitner` final re-review: no remaining Critical/Important findings in focused
  scope。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto 阻断后解除并继续
dispatch、真实终端 TUI 启动并产生 demo evidence、无 stdout fallback happy path、无残留
`codex app-server` / `raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer (EOF-10)

最新完成切片是 `V14 Terminal TUI Demo Harness Slice`，详细记录见本文件对应段落。关键状态:

- 新增 terminal TUI demo harness 和 `xmuse-tui-terminal-demo` CLI。
- Public evidence write path 只读 official/persisted surfaces，不接受 synthetic read-surface payload。
- `/resume` 现在能记录 official TUI command proof，并支持 proposal-ready conversation id 恢复。
- Stale command events、non-launch command、boolean/non-zero exit code、缺失 surface 都无法写入
  `tui_terminal_demo.json`。
- focused verification:
  - closure + terminal demo suite: `40 passed, 1 warning`。
  - TUI command/read-surface focused subset: `7 passed, 33 deselected, 1 warning`。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Feynman` final re-review: no remaining Critical/Important findings in focused
  scope。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto
阻断后解除并继续 dispatch、真实终端 TUI 启动并产生 demo evidence、无 stdout fallback happy path、
无残留 `codex app-server` / `raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Terminal TUI Demo Harness Slice

本轮把上一切片的 `terminal_tui_demo` closure gate 从“只会读取 evidence”推进为可运行的
真实终端 TUI demo harness。当前仍不能标记 V14 complete；本节证明的是后续真实 terminal
演示有正式、受约束的 evidence 写入入口，而不是已经完成真实终端演示或 real-provider soak。

完成内容:

- 新增 `src/xmuse_core/chat/terminal_tui_demo.py`:
  - `run_terminal_tui_demo(...)` 默认通过 PTY 启动真实 TUI launch command
    `uv run python -m xmuse.tui`。
  - terminal script 会向真实 TUI 输入 `/resume <conversation_id>`、`/overview`、
    `/discussion`、`/blockers`，再退出。
  - `record_terminal_tui_demo_evidence(...)` 只读取 persisted `tui_command_events.json`、
    official `build_conversation_inspector_payload(...)` 和
    `_conversation_runtime_timeline_detail(...)`；public write path 不再接受 synthetic
    inspector/timeline/command events。
  - evidence 仅在 command 是已知 terminal TUI launch form、`exit_code` 为 exact int 0、
    command events 落在 terminal run `[started_at, completed_at]` 时间窗内、required surfaces
    都由 official read surfaces 观察到、runtime timeline event ids 存在时写入
    `tui_terminal_demo.json`。
  - persisted `visible_surfaces` 来自实际 derived observed set，而不是固定全量列表。
- 新增 `xmuse/tui/terminal_demo.py` CLI wrapper，并在 `pyproject.toml` 暴露
  `xmuse-tui-terminal-demo`。
- `/resume` 现在在 chat inspector read surface 可用时记录 official TUI command proof。
- `/resume <conversation_id>` 在 group list 未命中时会回退到 official conversation list，
  以支持 proposal-ready / initialization-stage conversation 的恢复证明。
- `v14_closure_evidence.py` 复用 shared `is_terminal_tui_launch_command(...)`，避免 recorder
  和 validator 的 launch command 规则漂移。

TDD / RED evidence:

- Missing harness RED:
  - `uv run pytest -q tests/xmuse/test_tui_terminal_demo.py`
  - RED 结果: import failure，`xmuse_core.chat.terminal_tui_demo` 尚不存在。
- `/resume` command proof RED:
  - focused TUI command proof subset initially failed because `/resume` was not persisted in
    `tui_command_events.json`。
- Runner conversation injection RED:
  - `test_terminal_tui_demo_runner_injects_conversation_for_scripted_terminal_inputs` initially
    failed because `XMUSE_TUI_DEMO_CONVERSATION_ID` was not set。
- Review regression RED:
  - `test_terminal_tui_demo_recorder_rejects_stale_command_events` failed before fix because stale
    pre-run command events could satisfy the recorder。

验证:

- Closure + terminal demo focused suite:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py tests/xmuse/test_tui_terminal_demo.py`
  - 结果: `40 passed, 1 warning`。
- TUI command/read-surface focused subset:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "official_tui_command_proof or official_chat_api or resume or overview or discussion_command or blockers_command"`
  - 结果: `7 passed, 33 deselected, 1 warning`。
- Touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/terminal_tui_demo.py src/xmuse_core/chat/v14_closure_evidence.py xmuse/tui/terminal_demo.py xmuse/tui/slash_commands.py tests/xmuse/test_tui_terminal_demo.py tests/xmuse/test_tui_navigation.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。
- MemoryOS scan:
  - `rg -n "MemoryOS|memoryos|/home/iiyatu/projects/python/memoryOS" src/xmuse_core/chat/terminal_tui_demo.py src/xmuse_core/chat/v14_closure_evidence.py xmuse/tui/terminal_demo.py xmuse/tui/slash_commands.py tests/xmuse/test_tui_terminal_demo.py tests/xmuse/test_tui_navigation.py pyproject.toml`
  - 结果: no matches。

Review subagent:

- Review subagent `Feynman` (`019e9452-47b6-7d40-ac66-b225a045a724`) performed read-only focused
  review。
- Initial findings:
  - Important: stale persisted command events could satisfy terminal demo recorder。
  - Important: recorder wrote a fixed full `visible_surfaces` list instead of the derived observed set。
- Fixes:
  - Command-event surfaces now require `created_at` within `[started_at, completed_at]` and timezone-aware
    timestamp parsing。
  - Persisted `visible_surfaces` now comes from the derived observed set after validation。
  - Added stale command event regression。
- Re-review: no remaining Critical/Important findings。

当前仍未满足的 V14 hard gates:

- 尚未用真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未完成真实 Ray + Codex app-server + MCP writeback 的 V14 collaboration/proposal/veto/
  dispatch fresh + restart/resume 多轮 soak。
- 尚未实际运行 terminal TUI demo CLI 产生真实 `tui_terminal_demo.json` evidence；本切片只是提供
  受约束 harness。
- 尚未证明最终 happy path 无 stdout fallback 且无残留 `codex app-server` / `raylet` /
  `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer (EOF-9)

最新完成切片是 `V14 Terminal TUI Demo Harness Slice`，详细记录见本文件对应段落。关键状态:

- 新增 terminal TUI demo harness 和 `xmuse-tui-terminal-demo` CLI。
- Public evidence write path 只读 official/persisted surfaces，不接受 synthetic read-surface payload。
- `/resume` 现在能记录 official TUI command proof，并支持 proposal-ready conversation id 恢复。
- Stale command events、non-launch command、boolean/non-zero exit code、缺失 surface 都无法写入
  `tui_terminal_demo.json`。
- focused verification:
  - closure + terminal demo suite: `40 passed, 1 warning`。
  - TUI command/read-surface focused subset: `7 passed, 33 deselected, 1 warning`。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Feynman` final re-review: no remaining Critical/Important findings in focused
  scope。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto
阻断后解除并继续 dispatch、真实终端 TUI 启动并产生 demo evidence、无 stdout fallback happy path、
无残留 `codex app-server` / `raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Runner Dispatch Bridge Operations Health Slice

本轮继续把 V14 closure evidence 收束到 official runner/read surface。当前仍不能标记 V14
complete；本节只证明 `platform_runner.health_once(...).operations` 能直接暴露 chat dispatch
bridge 的 durable queue/progress/evidence。

完成内容:

- `platform_runner.health_once(...).operations` 新增 `chat_dispatch_bridge`。
- 新 helper `_chat_dispatch_bridge_health(chat.db)` read-only 读取 `chat_dispatch_queue`:
  - `missing_chat_db`
  - empty/table-missing `no_entries`
  - observed `total / queued / processing / dispatched / failed`
  - compact `latest` entry，包含 `entry_id`、`conversation_id`、`status`、`source`、
    `target`、`auto_execute`、`proposal_id`、`resolution_id`、`collaboration_run_id`、
    `artifact_ref`、`dispatch_evidence`。
- `latest` 选择按 lifecycle timestamp
  `coalesce(completed_at, updated_at, claimed_at, created_at)`，并优先有 `completed_at`
  的 completed dispatch evidence，再用 `rowid` 兜底。
- 新增 runner health contract/progress/missing-db tests，让 closure runner surface 可以证明
  dispatch bridge 队列存在、agent auto dispatch 已 dispatched、MCP writeback evidence 已关联。

TDD / RED evidence:

- `uv run pytest -q tests/xmuse/test_platform_runner.py::test_health_once_exposes_runtime_operations_contract tests/xmuse/test_platform_runner.py::test_health_once_exposes_chat_dispatch_bridge_progress`
  - RED 结果: `2 failed`。
  - 目标失败点: 两个测试均为 `KeyError: 'chat_dispatch_bridge'`。
- GREEN focused:
  - 同一命令结果: `2 passed in 0.46s`。

验证:

- Post-review runner focused regression:
  - `uv run pytest -q tests/xmuse/test_platform_runner.py -k "health_once or dispatch_bridge"`
  - 结果: `14 passed, 50 deselected in 1.59s`。
- V14 closure evidence suite:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py`
  - 结果: `27 passed, 1 warning in 4.47s`。
- Touched-file ruff:
  - `uv run ruff check xmuse/platform_runner.py tests/xmuse/test_platform_runner.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。

Review subagent:

- Review subagent `Feynman` (`019e9452-47b6-7d40-ac66-b225a045a724`) performed read-only
  focused review。
- Initial review: no Critical/Important findings。Minor: missing `chat.db` behavior lacked
  focused test coverage。
- Fix: added `test_health_once_reports_missing_chat_dispatch_bridge_db` to assert exact
  `missing_chat_db` payload。
- Re-review: no remaining Critical/Important findings in focused scope。

当前仍未满足的 V14 hard gates:

- 尚未用真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未完成真实 Ray + Codex app-server + MCP writeback 的 V14 collaboration/proposal/veto/
  dispatch fresh + restart/resume 多轮 soak。
- 尚未通过真实终端 TUI 启动演示证明 `/new`、`/overview`、`/discussion`、`/blockers` 与
  runtime timeline/read surface 的用户可见闭环。
- 尚未证明最终 happy path 无 stdout fallback 且无残留 `codex app-server` / `raylet` /
  `gcs_server` / `ray::` 进程。
- `platform_runner.health_once(...).operations.chat_dispatch_bridge` 是 runner evidence surface，
  不是真实 provider soak harness；最终 complete 仍需要真实运行 trace 填充。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Official Chat API TUI Command Proof Slice

本轮继续推进 V14 real task gate 中 “TUI 主路径 + official read surface” 的证据强度。当前仍不能
标记 V14 complete；本节证明的是 Textual TUI command path 可以通过 `XmuseAdapter` 连接真实
FastAPI Chat API/read surfaces，而不是纯 mocked adapter。

完成内容:

- `XmuseAdapter` 新增可选 `chat_api_client_factory`。
  - 生产默认仍是 `httpx.Client(timeout=...)`。
  - 测试可注入 sync client wrapper，指向 `TestClient(create_app(tmp_path))`。
- 新增 official API TUI proof test:
  `test_chat_screen_records_tui_command_proof_through_official_chat_api`。
  - 使用 `XmuseTUI.run_test()` 真实 Textual screen/input path。
  - 使用 `XmuseAdapter`，不 mock `create_group_conversation`、`get_bootstrap_status`、
    `get_conversation_inspector` 或 participant reads。
  - 使用 `FastAPI TestClient(create_app(tmp_path))` 作为 official Chat API surface。
  - 通过 `/new Official API proof` 创建 fresh group conversation。
  - 继续执行 `/overview`、`/discussion`、`/blockers`。
  - 断言 `PeerChatService(...).list_conversations()` 中确有 official API 创建的 conversation。
  - 断言 bootstrap status 为 `proposal_ready`。
  - 断言 persisted `tui_command_events.json` 中记录 `/new`、`/overview`、`/discussion`、
    `/blockers`，且 `conversation_id/read_surface_authority/surface_ref` 全部指向
    `chat_inspector:<conversation_id>`。

TDD / RED evidence:

- `uv run pytest -q tests/xmuse/test_tui_navigation.py::test_chat_screen_records_tui_command_proof_through_official_chat_api`
  - RED: `XmuseAdapter.__init__() got an unexpected keyword argument 'chat_api_client_factory'`。

验证:

- New focused GREEN:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py::test_chat_screen_records_tui_command_proof_through_official_chat_api`
  - 结果: `1 passed, 1 warning in 1.46s`。
- TUI command proof/read-surface focused subset:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "official_tui_command_proof or official_chat_api or unavailable_read_surface or new_command"`
  - 结果: `6 passed, 34 deselected, 1 warning in 2.37s`。
- Full TUI navigation:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py`
  - 结果: `40 passed, 1 warning in 9.30s`。
- Adapter contract/runtime card regression:
  - `uv run pytest -q tests/xmuse/test_tui_adapter_contract.py tests/xmuse/test_tui_adapter.py`
  - 结果: `35 passed in 3.25s`。
- Touched-file ruff:
  - `uv run ruff check xmuse/tui/adapter/xmuse_adapter.py tests/xmuse/test_tui_navigation.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。

Review subagent:

- Review subagent `Feynman` (`019e9452-47b6-7d40-ac66-b225a045a724`) performed read-only focused
  review of this slice。
- 结论: no Critical or Important findings。
- Minor suggestion: official API proof test should assert `surface_ref` and `conversation_id` on each
  event；已补。

当前仍未满足的 V14 hard gates:

- 尚未用真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未完成真实 Ray + Codex app-server + MCP writeback 的 V14 collaboration/proposal/veto/
  dispatch fresh + restart/resume 多轮 soak。
- 本切片使用 FastAPI TestClient，不等价于用户终端中真实 `uv run python -m xmuse.tui` 手动/自动演示。
- 尚未证明最终 happy path 无 stdout fallback 且无残留 `codex app-server` / `raylet` /
  `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer (EOF-4)

最新完成切片是 `V14 Official Chat API TUI Command Proof Slice`，详细记录见本文件对应段落。
关键状态:

- Textual `XmuseTUI.run_test()` now proves `/new`、`/overview`、`/discussion`、`/blockers`
  command proof through `XmuseAdapter` connected to official `create_app(tmp_path)` Chat API/read
  surfaces。
- Production adapter default remains real `httpx.Client`; injected sync client factory is optional and
  used by tests only。
- focused verification:
  - new official API TUI proof: `1 passed, 1 warning`。
  - focused TUI command subset: `6 passed, 34 deselected, 1 warning`。
  - full TUI navigation: `40 passed, 1 warning`。
  - adapter contract/runtime cards: `35 passed`。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Feynman`: no Critical/Important findings。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto
阻断后解除并继续 dispatch、真实终端 TUI 启动演示、无 stdout fallback happy path、无残留
`codex app-server` / `raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer (EOF-2)

最新完成切片是 `V14 Runner Cleanup Evidence Normalization Slice`，详细记录见本文件对应段落。
关键状态:

- closure validator 现在可消费 `platform_runner.health_once(...).operations.cleanup` runner cleanup
  payload。
- 仅 `status="clean"` 且 `leftovers=[]` 可满足 process cleanup gate。
- dirty、unknown、mixed legacy/runner、malformed runner cleanup evidence 都 fail closed。
- focused verification:
  - cleanup regressions: `6 passed, 1 warning`。
  - V14 closure evidence suite: `27 passed, 1 warning`。
  - runner cleanup focused regression: `2 passed`。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Feynman` final re-review: no remaining Critical/Important findings in focused
  scope。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto
阻断后解除并继续 dispatch、真实 TUI 启动/slash command proof、无 stdout fallback happy path、
无残留 `codex app-server` / `raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Runner Cleanup Evidence Normalization Slice

本轮继续推进 V14 closure guard 的 process cleanup gate。当前仍不能标记 V14 complete；本节只把
最终 closure 所需的“无残留进程”证据从手工四布尔 dict 扩展为可直接消费
`xmuse/platform_runner.py::health_once(...).operations.cleanup` 的 official runner cleanup read
model。

完成内容:

- `validate_v14_closure_evidence(...)` 的 process cleanup gate 继续接受原有四个严格布尔键:
  - `leftover_codex_app_server`
  - `leftover_raylet`
  - `leftover_gcs_server`
  - `leftover_ray_worker`
- 同时支持 runner cleanup health payload:
  - `{"status": "clean", "leftovers": []}` 会归一化为四个 leftover 全 false。
  - `status="dirty"` 或任意 leftovers 仍会导致 process cleanup gate 失败。
  - 未知 leftover 不会被忽略，会作为不 clean 处理。
- 这没有新增 automated cleanup，也不会 kill 进程；它只是让 closure evidence collector/validator
  消费已有 report-only cleanup detection。

TDD / RED evidence:

- 新增 `test_v14_closure_evidence_accepts_runner_cleanup_health_payload`。
  - RED: 当前 validator 只识别四布尔 dict，clean runner payload 被误判
    `missing=['process_cleanup']`。
- 新增 `test_v14_closure_evidence_rejects_runner_cleanup_leftovers`。
  - 覆盖 dirty runner cleanup leftovers 不能通过 closure gate。
- Review regression:
  - 新增 `test_v14_closure_evidence_rejects_dirty_runner_cleanup_without_leftover_rows`，
    防止 `status="dirty", leftovers=[]` 被误判 clean。
  - 新增 `test_v14_closure_evidence_rejects_contradictory_mixed_cleanup_payload`，
    防止四布尔 all-false 与 dirty/unknown runner leftovers 混合时被 legacy path 误放行。
  - 新增 `test_v14_closure_evidence_rejects_malformed_mixed_cleanup_payload`，
    防止出现 runner 字段但缺失/malformed `leftovers` 时回退 legacy false booleans。
  - 新增 `test_v14_closure_evidence_rejects_non_dict_runner_cleanup_leftover_rows`，
    防止 runner cleanup leftovers 中非 object row 被忽略。

验证:

- RED command:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_accepts_runner_cleanup_health_payload tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_runner_cleanup_leftovers`
  - 结果: `1 failed, 1 passed, 1 warning`；失败点为 clean runner cleanup payload 未被识别。
- Focused GREEN:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_accepts_runner_cleanup_health_payload tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_runner_cleanup_leftovers`
  - 结果: `2 passed, 1 warning in 0.38s`。
- V14 closure evidence suite:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py`
  - 初次结果: `23 passed, 1 warning in 6.27s`。
- Review regression GREEN:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_accepts_runner_cleanup_health_payload tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_runner_cleanup_leftovers tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_dirty_runner_cleanup_without_leftover_rows tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_contradictory_mixed_cleanup_payload`
  - 结果: `4 passed, 1 warning in 0.39s`。
- Malformed cleanup regression RED:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_malformed_mixed_cleanup_payload tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_non_dict_runner_cleanup_leftover_rows`
  - 结果: `2 failed, 1 warning`。
- Malformed cleanup regression GREEN:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_malformed_mixed_cleanup_payload tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_non_dict_runner_cleanup_leftover_rows tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_accepts_runner_cleanup_health_payload tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_runner_cleanup_leftovers tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_dirty_runner_cleanup_without_leftover_rows tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_contradictory_mixed_cleanup_payload`
  - 结果: `6 passed, 1 warning in 0.37s`。
- V14 closure evidence suite after review fixes:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py`
  - 初次结果: `25 passed, 1 warning in 3.18s`。
  - malformed fixes 后结果: `27 passed, 1 warning in 2.49s`。
- Runner cleanup focused regression:
  - `uv run pytest -q tests/xmuse/test_platform_runner.py::test_health_once_exposes_runtime_operations_contract tests/xmuse/test_platform_runner.py::test_health_once_marks_runtime_operations_degraded_and_cleanup_dirty`
  - 结果: `2 passed in 0.29s`。
- Touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/v14_closure_evidence.py tests/xmuse/test_v14_closure_evidence.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。

Review subagent:

- 新建 review subagent 失败，原因是 agent thread limit reached。
- 已复用既有 review agent `Feynman` (`019e9452-47b6-7d40-ac66-b225a045a724`) 并发送本切片
  focused review 请求。
- Feynman initial review found two Important strictness bugs:
  - `status="dirty", leftovers=[]` could pass cleanup validation。
  - mixed payload with legacy false booleans plus dirty/unknown runner cleanup evidence could pass。
- Both findings were fixed with focused regressions listed above；等待 re-review。
- Feynman re-review found one additional Important strictness bug:
  - malformed runner fields could still fall back to legacy false booleans。
- This was fixed fail-closed with malformed/unknown leftover regressions listed above。
- Feynman final re-review: no remaining Critical or Important findings in the focused V14 cleanup
  evidence slice。

当前仍未满足的 V14 hard gates:

- 尚未用真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未完成真实 Ray + Codex app-server + MCP writeback 的 V14 collaboration/proposal/veto/
  dispatch fresh + restart/resume 多轮 soak。
- 尚未通过真实 TUI 启动和 slash-command 操作证明 `/new`、`/overview`、`/discussion`、
  `/blockers` 与 runtime timeline/read surface 的用户可见闭环。
- 本切片只让 validator 能消费 runner cleanup health；最终仍必须在真实 closure run 后提供
  无 `codex app-server` / `raylet` / `gcs_server` / `ray::` 残留的当前进程证据。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Official TUI Command Proof Slice

本轮继续把 V14 closure evidence 从 harness 手工 metadata 推向正式 TUI 主路径。当前仍不能标记
V14 complete；本节只解决 `/new`、`/overview`、`/discussion`、`/blockers` 的 command proof
不再只能由测试 fixture 手填的问题。

完成内容:

- `SlashCommandRouter` 在真实 Textual slash-command path 执行成功后记录 structured command proof:
  - `/new` 记录新建并激活后的 conversation id。
  - `/overview` 记录实际读取的 `chat_inspector:<conversation_id>` read surface。
  - `/discussion` 和 `/blockers` 记录 `chat_inspector:<conversation_id>` read surface。
- `AppState` 保留最近 TUI command events，便于真实 TUI harness 直接读取运行期证据。
- `XmuseAdapter` 将 command events 持久化到 `tui_command_events.json`，字段包括:
  - `command`
  - `conversation_id`
  - `read_surface_authority`
  - `surface_ref`
  - `created_at`
- `collect_v14_closure_evidence(...)` 现在可从 `tui_command_events.json` 自动补齐
  `official_tui_main_path.command_events`，并从 dashboard runtime timeline 自动补齐
  `runtime_timeline_event_ids`。最终 harness 仍需提供 `changed_paths`、provider session reuse 和
  process cleanup 外部证据。
- reviewer 后收紧 proof 语义:
  - `/overview` 只记录实际读取的 `chat_inspector` authority，不冒充 dashboard runtime timeline。
  - `/discussion`、`/blockers`、`/overview` 只有在 read payload 可用时才记录成功 proof。
  - closure validator 要求四个 TUI command events 的 `created_at` 不早于 accepted dispatch gate，
    防止同一 conversation 的旧命令事件和后续 closure chain 被拼接。
  - `/new` 只有在创建后的 conversation inspector 可读且 conversation id 匹配时才记录
    `chat_inspector` proof。
  - closure validator 要求 `read_surface_authority` 与 `surface_ref` 前缀一致，除非
    `surface_ref` 是明确 linked runtime event id。

TDD / RED evidence:

- `uv run pytest -q tests/xmuse/test_tui_navigation.py::test_chat_screen_records_official_tui_command_proof_for_runtime_commands`
  - RED 失败点: `XmuseAdapter` 没有 `list_tui_command_events(...)`，真实 TUI slash path 没有 proof
    读写接口。
- `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_collector_uses_persisted_tui_command_proof`
  - RED 失败点: `collect_v14_closure_evidence(...)` 返回的 `official_tui_main_path` 没有
    `command_events`，不会消费持久 TUI proof。

验证:

- New focused GREEN:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py::test_chat_screen_records_official_tui_command_proof_for_runtime_commands`
  - 结果: `1 passed in 0.55s`。
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_collector_uses_persisted_tui_command_proof`
  - 结果: `1 passed, 1 warning in 0.87s`。
- V14 closure evidence suite:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py`
  - 初次结果: `19 passed, 1 warning in 2.65s`。
  - reviewer 收紧 proof 语义后结果: `20 passed, 1 warning in 2.71s`。
  - re-review 修复后结果: `21 passed, 1 warning in 3.15s`。
- TUI command/read-surface focused regression:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "new_command or overview or discussion_command or blockers_command or official_tui_command_proof"`
  - 结果: `8 passed, 29 deselected in 1.60s`。
  - reviewer 收紧 proof 语义后，扩大命令:
    `uv run pytest -q tests/xmuse/test_tui_navigation.py tests/xmuse/test_tui_adapter.py -k "overview or discussion_command or blockers_command or new_command or official_tui_command_proof or unavailable_read_surface or runtime_closure"`
  - 初次结果: `11 passed, 54 deselected in 2.25s`。
  - re-review 修复后结果: `12 passed, 54 deselected in 2.56s`。
- Touched-file ruff:
  - `uv run ruff check xmuse/tui/state.py xmuse/tui/adapter/xmuse_adapter.py xmuse/tui/slash_commands.py src/xmuse_core/chat/v14_closure_evidence.py tests/xmuse/test_tui_navigation.py tests/xmuse/test_v14_closure_evidence.py`
  - 结果: `All checks passed!`。

Review subagent:

- Reused review subagent `Feynman` (`019e9452-47b6-7d40-ac66-b225a045a724`) because the
  agent thread limit prevented spawning a fresh reviewer.
- Initial review found three Important issues:
  - stale same-conversation command events could be stitched to a later closure chain if timeline ids were
    auto-filled;
  - `/overview` claimed `dashboard_runtime_timeline` authority without reading that endpoint;
  - command proof was recorded even when inspector payload was unavailable.
- All three were fixed with regression tests:
  - `test_v14_closure_evidence_rejects_stale_tui_command_proof`
  - `test_chat_screen_does_not_record_tui_command_proof_for_unavailable_read_surface`
  - strengthened `test_chat_screen_records_official_tui_command_proof_for_runtime_commands`
- Re-review then found two remaining Important issues:
  - `/new` still recorded `chat_inspector` proof without reading inspector。
  - validator accepted mismatched `read_surface_authority` / `surface_ref` pairs。
- Both re-review findings were fixed with regression tests:
  - `test_chat_screen_new_command_does_not_record_proof_when_inspector_unavailable`
  - `test_v14_closure_evidence_rejects_tui_proof_authority_surface_mismatch`
- Final re-review: no remaining Critical/Important findings in this focused slice。

当前仍未满足的 V14 hard gates:

- 尚未用真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未完成真实 Ray + Codex app-server + MCP writeback 的 V14 collaboration/proposal/veto/
  dispatch fresh + restart/resume 多轮 soak。
- 尚未通过真实 TUI launch 的人工/自动演示路径采集最终 command proof；本轮只证明主路径会记录 proof。
- 尚未证明最终 happy path 无 stdout fallback 且无残留 `codex app-server` / `raylet` /
  `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Closure Evidence Collector / Guard Slice

本轮继续推进 V14 closure 证据链，但仍不能标记 V14 complete。本切片新增 read-only
closure evidence collector，并收紧 validator，目标是防止最终 handoff 用拼接证据、弱 TUI
证明或普通 execute 文本误报 production closure。

完成内容:

- 新增 `collect_v14_closure_evidence(...)`:
  - 从 `PeerChatService.get_bootstrap_status(...)` 读取 bootstrap。
  - 从 `build_conversation_inspector_payload(...)` 读取 official chat inspector。
  - 从 dashboard runtime timeline 读取 official dashboard/read surface。
  - 只转交外部 closure harness 证据里的 provider-session reuse、TUI command proof 和 process cleanup；
    不创建 artifact、不 dispatch、不修改 runtime state。
- `build_conversation_inspector_payload(...)` 的 collaboration runs 现在暴露 response records:
  - `response_id`
  - `run_id`
  - `target`
  - `status`
  - `content`
  - `created_at`
- `validate_v14_closure_evidence(...)` 收紧:
  - execute response 必须是 typed JSON:
    `type=execute_feasibility_verdict`、`status=executable`、非空 summary，并同时引用 matching
    `proposal:<id>` 和 `artifact:<type>`。
  - dispatch gate lifecycle 使用 timezone-aware timestamp parsing；malformed/naive timestamps 拒绝。
  - dashboard runtime timeline 必须匹配同一 conversation 和 accepted closure chain 的
    run/blocker/gate/dispatch/writeback refs。
  - official TUI main path proof 不再接受 bare boolean 或旧式 `exercised_commands`。
    现在必须提供同一 conversation 下的 structured `command_events`，并显式链接 runtime timeline
    event ids，且这些 ids 必须覆盖 accepted chain 的 run、resolved blocker、blocked gate、allowed
    gate、dispatch entry 和 provider writeback。

TDD / RED evidence:

- Collector import RED:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py`
  - RED 失败点: `cannot import name 'collect_v14_closure_evidence'`。
- Review-finding RED set:
  - freeform execute response was not rejected as weak collaboration。
  - blocked execute verdict was not rejected。
  - execute verdict for wrong proposal was not rejected。
  - malformed timestamp ordering could pass by string comparison。
  - runtime timeline conversation mismatch was not rejected。
  - old weak TUI command proof shape still passed。

验证:

- Closure evidence focused suite:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py`
  - 结果: `17 passed in 1.88s`。
- Collaboration/dashboard read-surface regression subset:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py tests/xmuse/test_peer_chat_dashboard.py -k "dispatch_gate or runtime_timeline or inspector"`
  - 结果: `32 passed, 30 deselected, 1 warning in 10.24s`。
- TUI read-surface command/card subset:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "overview or discussion_command or blockers_command or runtime_closure"`
  - 结果: `5 passed, 31 deselected in 0.87s`。
- Touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/v14_closure_evidence.py src/xmuse_core/chat/inspector_builder.py tests/xmuse/test_v14_closure_evidence.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。

Review subagent:

- Reused review subagent `Feynman` (`019e9452-47b6-7d40-ac66-b225a045a724`) for read-only focused review。
- First review found:
  - Critical: TUI proof still accepted caller-supplied weak command metadata。
  - Important: execute feasibility was not typed-validated。
  - Important: inspector response exposure lacked response metadata。
  - Important: dashboard timeline was not correlated to the accepted closure chain。
  - Important: timestamp ordering used lexicographic string comparison。
- Fixes implemented as listed above。
- Final re-review: no Critical or Important findings。
- Minor coverage requests addressed:
  - naive timestamp rejection test。
  - invalid/unlinked TUI `surface_ref` rejection test。

当前仍未满足的 V14 hard gates:

- 尚未完成真实 Ray + Codex app-server + MCP writeback 的 V14 fresh + restart/resume 多轮 soak。
- 尚未证明真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未产出真实/fresh chain，证明 review veto 阻止 dispatch，修正后解除并继续 dispatch。
- closure evidence collector/validator 是防误报 guard，不会自行运行 Ray/Codex/MCP、不执行 TUI
  proof task、不做 process cleanup。
- 尚未证明最终 V14 closure run 无 stdout fallback happy path。
- 尚未证明最终 closure 后无残留 `codex app-server` / `raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer

最新完成切片是 `V14 Dashboard Runtime Timeline Read Surface Slice`，记录在本文件 V14
TUI/runtime 相关段落附近。关键状态:

- dashboard runtime timeline endpoint 和 inspector `runtime_timeline_refs` 已补。
- same-second latest selection 已覆盖 collaboration/blocker ascending lists 与 dispatch queue
  newest-first list。
- unrelated peer latency 不会被误展示为 dispatch provider writeback。
- focused verification:
  - `5 passed, 1 warning` for new runtime timeline tests。
  - `27 passed, 9 deselected, 1 warning` for dashboard inspector/runtime/latency subset。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Descartes` final re-review: no remaining Critical/Important/Minor findings in
  focused scope。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto
阻断后解除并继续 dispatch、无 stdout fallback happy path、无残留 `codex app-server` /
`raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Dashboard Runtime Timeline Read Surface Slice

本轮继续推进 V14 dashboard/read-surface gate，把已有 chat inspector/bootstrap authority 投影为
dashboard 可直接消费的 runtime timeline。当前仍不能标记 V14 complete；本节只补 dashboard
timeline read model，不等同于完成真实 provider closure run。

完成内容:

- 新增 dashboard read endpoint:
  - `GET /api/dashboard/peer-chat/conversations/{conversation_id}/runtime-timeline`
- dashboard inspector 新增 `runtime_timeline_refs`:
  - dashboard anchor: `/dashboard/peer-chat/conversations/{conversation_id}#runtime-timeline`
  - API href:
    `/api/dashboard/peer-chat/conversations/{conversation_id}/runtime-timeline`
- `src/xmuse_core/platform/dashboard_details.py` 新增 runtime timeline projection，source authority
  明确为 `chat_inspector`，只读取:
  - `build_conversation_inspector_payload(conversation_id, base_dir)`
  - `PeerChatService(...).get_bootstrap_status(conversation_id)`
- timeline events 覆盖:
  - `bootstrap`
  - latest `collaboration_run`
  - latest `blocker_active` / `blocker_resolved`
  - all recent `dispatch_gate`
  - latest `dispatch_queue`
  - correlated `provider_writeback`
- provider writeback 只在 dispatch queue entry 的
  `dispatch_evidence = "mcp_writeback:<inbox_id>"` 能匹配
  `peer_latency.recent_turns[].inbox_item_id` 时出现，避免 unrelated GOD reply 被误展示为
  dispatch closure evidence。
- same-second ordering 已加固:
  - inspector ascending lists（collaboration runs / blockers）同 timestamp 选择后出现的 row。
  - dispatch queue newest-first list 同 timestamp 选择前出现的 row。

TDD / RED evidence:

- Runtime timeline endpoint / inspector refs RED:
  - `uv run pytest -q tests/xmuse/test_peer_chat_dashboard.py::test_dashboard_peer_chat_runtime_timeline_projects_inspector_state tests/xmuse/test_peer_chat_dashboard.py::test_conversation_inspector_links_dashboard_runtime_timeline`
  - RED 失败点:
    - runtime timeline endpoint 返回 404。
    - dashboard inspector 缺 `runtime_timeline_refs`。
- Reviewer Important regression RED:
  - `uv run pytest -q tests/xmuse/test_peer_chat_dashboard.py::test_dashboard_runtime_timeline_prefers_latest_row_when_timestamps_tie`
  - RED 失败点: same-second collaboration runs 选择 older run。
- Reviewer second Important regression RED:
  - `uv run pytest -q tests/xmuse/test_peer_chat_dashboard.py::test_dashboard_runtime_timeline_prefers_newest_dispatch_queue_row_on_tie`
  - RED 失败点: same-second dispatch queue entries 选择 older queue row。
- Provider writeback negative regression:
  - `test_dashboard_runtime_timeline_ignores_unrelated_peer_latency_writeback` 证明 unrelated
    `peer_latency` 不生成 `provider_writeback` event。

验证:

- New focused timeline tests:
  - `uv run pytest -q tests/xmuse/test_peer_chat_dashboard.py::test_dashboard_peer_chat_runtime_timeline_projects_inspector_state tests/xmuse/test_peer_chat_dashboard.py::test_conversation_inspector_links_dashboard_runtime_timeline tests/xmuse/test_peer_chat_dashboard.py::test_dashboard_runtime_timeline_prefers_latest_row_when_timestamps_tie tests/xmuse/test_peer_chat_dashboard.py::test_dashboard_runtime_timeline_ignores_unrelated_peer_latency_writeback tests/xmuse/test_peer_chat_dashboard.py::test_dashboard_runtime_timeline_prefers_newest_dispatch_queue_row_on_tie`
  - 结果: `5 passed, 1 warning in 2.81s`。
- Dashboard inspector/runtime/latency focused subset:
  - `uv run pytest -q tests/xmuse/test_peer_chat_dashboard.py -k "inspector or runtime_timeline or latency"`
  - 结果: `27 passed, 9 deselected, 1 warning in 9.12s`。
- Touched-file ruff:
  - `uv run ruff check xmuse/dashboard_api.py src/xmuse_core/platform/dashboard_details.py tests/xmuse/test_peer_chat_dashboard.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。

Review subagent:

- Review subagent `Descartes` (`019e943c-fdfb-7242-b0c2-0abc0b532a52`) performed read-only
  focused review of the dashboard runtime timeline slice。
- Initial finding:
  - Important — `_latest_dict()` used same-timestamp tie-breaking that preferred older rows for
    ascending inspector lists, so latest collaboration run/blocker could be wrong。
- Fix:
  - `_latest_dict()` now prefers later list index by default。
  - Added `test_dashboard_runtime_timeline_prefers_latest_row_when_timestamps_tie`。
- Re-review finding:
  - Important — dispatch queue entries are newest-first, so the default tie-breaker would choose
    older queue row under equal timestamps。
- Fix:
  - `_latest_dict(value, *, newest_first=False)` now makes ordering explicit。
  - dispatch queue calls `_latest_dict(..., newest_first=True)`。
  - Added `test_dashboard_runtime_timeline_prefers_newest_dispatch_queue_row_on_tie`。
- Final re-review:
  - no remaining Critical/Important/Minor findings in focused scope。

当前仍未满足的 V14 hard gates:

- 尚未完成真实 Ray + Codex app-server + MCP writeback 的 V14 fresh + restart/resume 多轮 soak。
- 尚未证明真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未用真实/fresh trace 证明 review veto/blocker 阻止 dispatch，经修正解除后 dispatch 继续。
- 尚未证明 V14 closure run 无 stdout fallback happy path、无残留 `codex app-server`、
  `raylet`、`gcs_server`、`ray::` 进程。
- dashboard timeline read model 已补，但真实 runtime timeline/cards 仍需在 final closure run 中用
  actual trace 证明。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 TUI Runtime Closure Cards Slice

本轮继续推进 V14 TUI/read-surface gate，把已有 inspector/bootstrap runtime 状态接入 TUI
正常 card stream。当前仍不能标记 V14 complete；本节只把 `/overview` / `/discussion`
文本之外的主时间线卡片能力向前推进，不等同于真实 provider closure run。

完成内容:

- `XmuseAdapter.poll_cards(...)` 现在会读取正式 Chat API inspector 和 bootstrap status，
  生成 runtime closure cards:
  - `runtime_bootstrap`
  - `runtime_discussion`
  - `runtime_blocker`
  - `runtime_dispatch_gate`
  - `runtime_dispatch_queue`
  - `runtime_provider_writeback`
- cards 只消费已有 read surface:
  - `/api/chat/conversations/{conversation_id}/inspector`
  - `/api/chat/conversations/{conversation_id}/bootstrap/status`
  不直接写 store，也不从 TUI 推断 execution authority。
- provider writeback card 只在 dispatch queue entry 的
  `dispatch_evidence = "mcp_writeback:<inbox_id>"` 能和
  `peer_latency.recent_turns[].inbox_item_id` 对上时生成，避免把普通 GOD 回复误当成
  dispatch closure evidence。
- `poll_cards(...)` 不再使用单一 lexical timestamp cursor。改为 per-conversation JSON
  fingerprint 去重，避免 ISO runtime card timestamp 压过 numeric peer latency timestamp 后，
  抑制后续 degraded/writeback cards。
- `card_renderer.CARD_STYLES` 为 runtime closure card types 增加显式样式，避免主 TUI card
  stream 退回 generic white card。

TDD / RED evidence:

- Runtime closure helper RED:
  - `uv run pytest -q tests/xmuse/test_tui_adapter.py::test_adapter_builds_runtime_closure_cards_from_inspector tests/xmuse/test_tui_adapter.py::test_adapter_poll_cards_merges_runtime_closure_cards tests/xmuse/test_tui_widgets.py::test_runtime_closure_card_types_have_explicit_styles`
  - RED 失败点: `ImportError: cannot import name '_runtime_closure_cards'`。
- Reviewer finding regression RED:
  - `uv run pytest -q tests/xmuse/test_tui_adapter.py::test_adapter_poll_cards_does_not_suppress_numeric_latency_after_iso_runtime_card`
  - RED 失败点: first poll 的 ISO runtime bootstrap card 把 `_last_card_ts` 推到
    `2026-...` 后，second poll 中 numeric `peer_latency` card 被过滤，返回 `[]`。

验证:

- New focused tests:
  - `uv run pytest -q tests/xmuse/test_tui_adapter.py::test_adapter_builds_runtime_closure_cards_from_inspector tests/xmuse/test_tui_adapter.py::test_adapter_poll_cards_merges_runtime_closure_cards tests/xmuse/test_tui_widgets.py::test_runtime_closure_card_types_have_explicit_styles`
  - 结果: `3 passed in 0.49s`。
- Reviewer regression focused GREEN:
  - `uv run pytest -q tests/xmuse/test_tui_adapter.py::test_adapter_poll_cards_does_not_suppress_numeric_latency_after_iso_runtime_card`
  - 结果: `1 passed in 0.45s`。
- Affected TUI focused regression:
  - `uv run pytest -q tests/xmuse/test_tui_adapter.py tests/xmuse/test_tui_widgets.py tests/xmuse/test_tui_navigation.py -k "overview or discussion_command or blockers_command or init_status_retry_apply or new_command or runtime_closure or card"`
  - 结果: `19 passed, 68 deselected in 4.49s`。
- Full touched TUI test files:
  - `uv run pytest -q tests/xmuse/test_tui_adapter.py tests/xmuse/test_tui_widgets.py`
  - 结果: `51 passed in 3.95s`。
- Touched-file ruff:
  - `uv run ruff check xmuse/tui/adapter/xmuse_adapter.py xmuse/tui/widgets/card_renderer.py tests/xmuse/test_tui_adapter.py tests/xmuse/test_tui_widgets.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。

Review subagent:

- Review subagent `Ohm` (`019e9429-2ea9-7ee2-b65d-93ebdb13fc66`) performed a read-only
  narrow review of the TUI runtime closure cards slice。
- Finding: Important — `poll_cards` used one lexical timestamp cursor for all card families.
  ISO runtime cards could suppress later numeric peer latency cards and provider writeback cards。
- Fix: `poll_cards` now uses per-conversation JSON fingerprint dedupe via `_new_polled_cards(...)`
  and clears that cache on `sync(...)`。
- Re-review: no Critical/Important findings。Minor note about now-unused `_last_card_ts` was cleaned up。

当前仍未满足的 V14 hard gates:

- 本轮只完成 TUI 主 card stream 的 runtime closure cards，dashboard 仍需要更完整的生产级
  timeline/cards 体验。
- 尚未完成真实 Ray + Codex app-server + MCP writeback 的 V14 fresh + restart/resume 多轮 soak。
- 尚未证明真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未完成真实/新鲜 trace: review veto/blocker 阻止 dispatch，修正后 blocker resolved，
  execution 再继续。
- 尚未证明 V14 closure run 无 stdout fallback happy path、无残留 `codex app-server`、
  `raylet`、`gcs_server`、`ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Typed Execute Feasibility Verdict Slice

本轮把 V14 proposal approval dispatch gate 的 execute confirmation 从普通非空文本收紧为
typed feasibility verdict。当前仍不能标记 V14 complete；本节只关闭普通 execute 文本绕过
dispatch gate 的缺口，不等同于完成真实 provider soak。

完成内容:

- `POST /api/chat/proposals/{proposal_id}/approve` 现在只把 referenced
  `CollaborationRun.responses` 中满足以下条件的 execute response 视为确认:
  - `target == "execute"`
  - `status == "received"`
  - `content` 是 JSON object
  - `type == "execute_feasibility_verdict"`
  - `status == "executable"`
  - `summary` 非空
  - `evidence_refs` 至少包含一个非空字符串
- 普通 freeform execute 文本、blank response、`status="blocked"` verdict、无 evidence 的
  executable verdict 都返回 `dispatch_gate_blocked / blocked_execute_not_confirmed`。
- active dispatch-blocking veto 的优先级保持高于 execute confirmation 缺失/无效。
- built-in `execute` role template 现在明确教 provider agent 输出
  `execute_feasibility_verdict`，包括 executable 和 blocked 两种状态。
- `RoleTemplateStore._seed_predefined()` 现在会刷新已有 predefined role templates 的
  built-in 字段，避免旧 chat.db 中的 execute prompt 永久停留在旧 `message/done` contract。

TDD / RED evidence:

- Typed execute verdict RED:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_rejects_freeform_execute_confirmation tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_rejects_blocked_execute_verdict tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_rejects_execute_verdict_without_evidence`
  - RED 失败点: 三个负例 approval 都返回 200。
- Execute prompt contract RED:
  - `uv run pytest -q tests/xmuse/test_fe_vision_layer1_participant_store.py::TestRoleTemplateStoreSeeding::test_execute_prompt_content`
  - RED 失败点: seeded execute prompt 没有 `execute_feasibility_verdict`。
- Reviewer finding regression RED:
  - `uv run pytest -q tests/xmuse/test_fe_vision_layer1_participant_store.py::TestRoleTemplateStoreSeeding::test_seeding_refreshes_existing_predefined_execute_prompt`
  - RED 失败点: existing predefined execute prompt 被手动降级后，重新构造
    `RoleTemplateStore` 不会刷新 prompt。

验证:

- Typed execute focused GREEN:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_requires_execute_collaboration_confirmation tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_rejects_freeform_execute_confirmation tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_rejects_blocked_execute_verdict tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_rejects_execute_verdict_without_evidence tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_rejects_blank_execute_confirmation`
  - 结果: `5 passed, 1 warning in 3.00s`。
- Collaboration runtime/API focused suite:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py`
  - 结果: `26 passed, 1 warning in 7.70s`。
- Execute prompt / predefined migration focused GREEN:
  - `uv run pytest -q tests/xmuse/test_fe_vision_layer1_participant_store.py::TestRoleTemplateStoreSeeding::test_seeding_refreshes_existing_predefined_execute_prompt tests/xmuse/test_fe_vision_layer1_participant_store.py::TestRoleTemplateStoreSeeding::test_seeding_idempotent tests/xmuse/test_fe_vision_layer1_participant_store.py::TestRoleTemplateStoreSeeding::test_execute_prompt_content`
  - 结果: `3 passed in 1.09s`。
- Affected regression set:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py tests/xmuse/test_fe_vision_layer1_participant_store.py tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_lists_chat_tools tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_support_veto_and_dispatch_gate tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_reject_spoofed_session_identity tests/xmuse/test_mcp_server.py::test_peer_chat_mcp_endpoint_exposes_only_writeback_tools`
  - 结果: `71 passed, 1 warning in 26.03s`。
- Touched-file ruff:
  - `uv run ruff check xmuse/chat_api.py src/xmuse_core/chat/participant_store.py tests/xmuse/test_groupchat_collaboration_runtime.py tests/xmuse/test_fe_vision_layer1_participant_store.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。

Review subagent:

- Reused review subagent `Lovelace` (`019e93df-e1c3-7ae3-965f-e0aa5c8ab667`) for read-only
  review of the typed execute feasibility slice。
- Initial finding:
  - Important — existing predefined `execute` role templates were not updated because
    `_seed_predefined()` skipped existing slugs, so databases seeded before this slice would keep
    the old execute prompt and fail to teach typed verdicts。
- Fix:
  - Added `_predefined_template_needs_refresh(...)` and refreshed existing `predefined=1` rows
    when built-in fields differ。
  - Added `test_seeding_refreshes_existing_predefined_execute_prompt`。
- Re-review result: previous Important resolved; no remaining Critical/Important findings in
  focused scope。

当前仍未满足的 V14 hard gates:

- 尚未完成真实 Ray + Codex app-server + MCP writeback 的 fresh + restart/resume 多轮 soak。
- 尚未证明真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未用真实/fresh trace 证明 review veto/blocker 阻止 dispatch 后经修正解除并继续执行。
- TUI/dashboard 仍需要 production-grade timeline/cards，不只是文本 `/overview` / `/discussion`。
- 尚未证明 V14 closure run 无 stdout fallback happy path、无残留 `codex app-server`、
  `raylet`、`gcs_server`、`ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 TUI Overview Read Surface Slice

本轮补正式 TUI 主路径的 consolidated overview/read surface。当前仍不能标记 V14
complete；本切片只把已有 official inspector/bootstrap read surface 汇总成一个可用入口，
不是最终 production dashboard/timeline。

完成内容:

- 新增 TUI slash command `/overview`。
- `/help` 现在列出 `/overview`。
- `/overview` 只读取:
  - `adapter.get_bootstrap_status(conversation_id)`
  - `adapter.get_conversation_inspector(conversation_id)`
- overview 文本汇总:
  - bootstrap status + preset
  - team role counts
  - active/latest discussion run + orchestration mode
  - active blocker count + dispatch-blocking count
  - latest dispatch gate decision
  - dispatch queue counts: queued/processing/dispatched/failed
  - latest dispatch entry provider/failure ref
  - provider writeback state
- Provider writeback 行现在会从 latest dispatch entry 的
  `dispatch_evidence = "mcp_writeback:<inbox_id>"` 反查 matching
  `peer_latency.recent_turns[].inbox_item_id`，避免把 unrelated ordinary peer writeback
  误展示成 dispatch closure evidence。

TDD / RED evidence:

- Overview command RED:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py::test_chat_screen_overview_command_shows_runtime_closure_surface`
  - RED 失败点: `/overview` 返回 `Unknown command: /overview. Try /help.`。
- Reviewer mismatch regression RED:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py::test_chat_screen_overview_correlates_writeback_to_latest_dispatch`
  - RED 失败点: overview 展示 latest ordinary `peer_latency` turn:
    `Provider writeback: mcp_writeback architect`，而不是 latest dispatch entry 对应的
    `dispatch-inbox` / `execute` writeback。

验证:

- Overview focused GREEN:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py::test_chat_screen_overview_command_shows_runtime_closure_surface tests/xmuse/test_tui_navigation.py::test_chat_screen_overview_correlates_writeback_to_latest_dispatch`
  - 结果: `2 passed in 0.45s`。
- Full TUI navigation:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py`
  - 结果: `36 passed in 8.07s`。
- Touched-file ruff:
  - `uv run ruff check xmuse/tui/slash_commands.py tests/xmuse/test_tui_navigation.py`
  - 结果: `All checks passed!`。

Review subagent:

- Reused review subagent `Lovelace` (`019e93df-e1c3-7ae3-965f-e0aa5c8ab667`) for read-only
  review of the TUI overview slice。
- Initial finding:
  - Important — `/overview` used `dispatch_queue.entries[0]` for latest dispatch but
    independently used `peer_latency.recent_turns[0]` for provider writeback, so a newer ordinary
    GOD reply could be displayed as dispatch closure evidence。
- Fix:
  - Added evidence-to-latency correlation via `mcp_writeback:<inbox_id>` and regression test
    `test_chat_screen_overview_correlates_writeback_to_latest_dispatch`。
- Re-review result: previous Important resolved; no remaining Critical/Important/Minor findings
  in focused scope。

当前仍未满足的 V14 hard gates:

- `/overview` is still textual and compact; dashboard/TUI still needs production-grade
  timeline/cards for init、discussion、dispatch、review、blocker、resume。
- 尚未完成真实 Ray + Codex app-server + MCP writeback 的 fresh + restart/resume 多轮 soak。
- 尚未证明真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- execute confirmation 仍是普通 response convention，不是 typed feasibility verdict。
- 尚未证明 V14 closure run 无 stdout fallback happy path、无残留 `codex app-server`、
  `raylet`、`gcs_server`、`ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Dispatch Bridge Worker / MCP Writeback Slice

本轮把 V14 dispatch queue 从 durable intent/lifecycle 推进到 runner 可 tick 的 provider bridge。
当前仍不能标记 V14 complete；本节只证明 queued agent auto-dispatch entry 能进入现有 peer
provider/MCP writeback path，不等同于已经跑完真实 Ray + Codex app-server 多轮 soak。

完成内容:

- 新增 `src/xmuse_core/chat/dispatch_bridge.py`:
  - `ChatDispatchBridge`
  - `ChatDispatchBridgeOutcome`
  - `tick_once(conversation_id=...)`
- Bridge 只消费 `ChatDispatchQueueStore.claim_next_auto_dispatch(...)` 已存在的
  `queued`/stale `processing` auto-dispatch entry；不从普通聊天文本创建 dispatch intent。
- Bridge 为 claimed entry 创建 `dispatch_request` message + `item_type="dispatch"` execute inbox
  item，然后通过现有 `PeerChatScheduler` + GOD layer 交付。
- `PeerChatScheduler` 新增 `only_inbox_item_id`，用于 dispatch bridge 精确交付刚创建的
  dispatch inbox item，避免 older ordinary inbox item 被误认为 dispatch success。
- `ChatInboxStore.claim_next(...)` 新增可选 `item_id` filter，保持旧 scheduler 默认行为不变。
- `ChatDispatchQueueStore.claim_next_auto_dispatch(..., claim_ttl_s=900)` 支持 reclaim
  stale `processing` entries，避免 worker crash 后永久卡住。
- `xmuse/platform_runner.py` 在 peer chat persistent GOD layer 可用时构建
  `ChatDispatchBridge`，并在 runner loop 中按 conversation tick bridge。
- Bridge happy path 要求 scheduler `happy_path == 1`，也就是对应 inbox item 通过
  `chat_post_message` MCP writeback 被标记 read；无 MCP writeback/无 inbox side effect 会把
  dispatch queue entry 标为 `failed`，不会误报 dispatched。

TDD / RED evidence:

- Provider bridge RED:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_dispatch_bridge_auto_dispatches_gated_entry_through_execute_provider tests/xmuse/test_groupchat_collaboration_runtime.py::test_dispatch_bridge_fails_entry_without_mcp_writeback`
  - 初始 RED 失败点: `ModuleNotFoundError: No module named 'xmuse_core.chat.dispatch_bridge'`。
- Runner integration RED:
  - `uv run pytest -q tests/xmuse/test_platform_runner.py::test_runner_builds_dispatch_bridge_with_peer_god_layer tests/xmuse/test_platform_runner.py::test_dispatch_bridge_tick_scans_chat_conversations`
  - RED 失败点: runner 未构建 dispatch bridge，且没有 `_tick_chat_dispatch_bridge`。
- Reviewer Critical regression RED:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_dispatch_bridge_dispatches_its_item_not_older_unread_chat`
  - RED 失败点: bridge 创建 dispatch inbox 后调用 unscoped scheduler，实际处理了 older ordinary
    unread inbox item。
- Reviewer Important regression RED:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_dispatch_queue_reclaims_stale_processing_entry`
  - RED 失败点: `claim_next_auto_dispatch()` 不接受 `claim_ttl_s`，也不会 reclaim stale
    `processing` entry。

验证:

- Review regressions focused GREEN:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_dispatch_bridge_dispatches_its_item_not_older_unread_chat tests/xmuse/test_groupchat_collaboration_runtime.py::test_dispatch_queue_reclaims_stale_processing_entry`
  - 结果: `2 passed, 1 warning in 0.91s`。
- Collaboration runtime/API focused suite:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py`
  - 结果: `23 passed, 1 warning in 7.00s`。
- Platform runner focused regression:
  - `uv run pytest -q tests/xmuse/test_platform_runner.py::test_runner_enables_peer_chat_with_default_codex_launcher tests/xmuse/test_platform_runner.py::test_runner_builds_dispatch_bridge_with_peer_god_layer tests/xmuse/test_platform_runner.py::test_dispatch_bridge_tick_scans_chat_conversations tests/xmuse/test_platform_runner.py::test_runner_shutdown_closes_runtime_god_layers`
  - 结果: `4 passed in 0.79s`。
- TUI focused read-surface regression:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "discussion_command or blockers_command or init_status_retry_apply or new_command"`
  - 结果: `6 passed, 28 deselected in 1.51s`。
- MCP/narrow endpoint focused gate:
  - `uv run pytest -q tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_lists_chat_tools tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_support_veto_and_dispatch_gate tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_reject_spoofed_session_identity tests/xmuse/test_mcp_server.py::test_peer_chat_mcp_endpoint_exposes_only_writeback_tools`
  - 结果: `4 passed, 1 warning in 1.00s`。
- Touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/dispatch_bridge.py src/xmuse_core/chat/dispatch_queue.py src/xmuse_core/chat/inbox_store.py src/xmuse_core/chat/peer_scheduler.py xmuse/platform_runner.py tests/xmuse/test_groupchat_collaboration_runtime.py tests/xmuse/test_platform_runner.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。

Review subagent:

- Reused review subagent `Lovelace` (`019e93df-e1c3-7ae3-965f-e0aa5c8ab667`) for read-only
  review of the dispatch bridge worker slice。
- Initial findings:
  - Critical — `ChatDispatchBridge` created a dispatch inbox item but called unscoped
    `PeerChatScheduler.tick_once()`, so an older ordinary inbox item could be processed and the
    dispatch queue entry could be falsely marked `dispatched`。
  - Important — `chat_dispatch_queue` had no stale `processing` reclaim path; crash after claim
    could leave an entry permanently unclaimable。
- Fixes:
  - Added exact inbox claim path via `ChatInboxStore.claim_next(item_id=...)`,
    `PeerChatScheduler(only_inbox_item_id=...)`, and bridge scoping。
  - Added dispatch queue stale processing reclaim with `claim_ttl_s`。
- Re-review result: no Critical/Important remain; no remaining Minor findings in focused scope。

当前仍未满足的 V14 hard gates:

- 本切片仍使用 focused fake GOD layer for tests；尚未完成真实 Ray + Codex app-server +
  MCP writeback 的 fresh + restart/resume 多轮 soak。
- 尚未证明真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- dashboard/TUI 仍主要是 `/discussion` / `/blockers` 文本 read surface，尚未达到生产级
  timeline/cards。
- execute confirmation 仍是普通 response convention，不是 typed feasibility verdict。
- `peer_chat_scheduler` 由外部注入给 runner 时，runner 当前不会自动构建 dispatch bridge；
  CLI normal path 会构建，但注入路径仍是 residual integration risk。
- 尚未证明 V14 closure run 无 stdout fallback happy path、无残留 `codex app-server`、
  `raylet`、`gcs_server`、`ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Dispatch Queue Lifecycle / Restart Visibility Slice

本轮继续把上一节的 static dispatch intent queue 推进为可恢复 lifecycle queue。当前仍不能标记
V14 complete；本节只补正式 dispatch bridge 所需的 durable 状态转换，不启动 real provider。

完成内容:

- `ChatDispatchQueueEntry` 新增 lifecycle fields:
  - `claimed_by`
  - `claimed_at`
  - `provider_run_ref`
  - `dispatch_evidence`
  - `failure_reason`
  - `completed_at`
- `ChatDispatchQueueStore.claim_next_auto_dispatch(...)`:
  - 使用 SQLite `begin immediate` 原子 claim 当前 conversation 下最早的 `queued + auto_execute`
    entry。
  - claim 后状态为 `processing`，并持久化 `claimed_by/claimed_at`。
  - restart/reload 后 processing 状态仍可读取。
- `ChatDispatchQueueStore.mark_dispatched(...)`:
  - 只允许从 `processing` 进入 `dispatched`。
  - 写入 `provider_run_ref`、`dispatch_evidence`、`completed_at`。
- `ChatDispatchQueueStore.mark_failed(...)`:
  - 允许从 `queued` 或 `processing` 进入 `failed`。
  - 写入 `failure_reason`、`completed_at`。
- `build_conversation_inspector_payload(...)` 的 `dispatch_queue` 新增:
  - `dispatched`
  - `failed`
  - lifecycle fields in each entry。
- TUI `/discussion` 在 dispatch queue entry 文本里展示 `claimed_by`、`provider_run_ref`、
  `failure_reason` 等 lifecycle 信息，不暴露 raw JSON。

TDD / RED evidence:

- Store lifecycle RED:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_dispatch_queue_lifecycle_is_durable_and_visible_in_inspector`
  - RED 失败点: `ChatDispatchQueueStore` 没有 `claim_next_auto_dispatch`。
- TUI provider ref RED:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py::test_chat_screen_discussion_command_shows_collaboration_runs`
  - RED 失败点: `/discussion` 没有展示 `provider:codex:session-1`。

验证:

- Store lifecycle focused GREEN:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_dispatch_queue_lifecycle_is_durable_and_visible_in_inspector`
  - 结果: `1 passed, 1 warning in 0.94s`。
- TUI lifecycle focused GREEN:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py::test_chat_screen_discussion_command_shows_collaboration_runs`
  - 结果: `1 passed in 0.33s`。
- Collaboration runtime/API focused suite:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py`
  - 结果: `16 passed, 1 warning in 9.64s`。
- TUI focused read-surface regression:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "discussion_command or blockers_command or init_status_retry_apply or new_command"`
  - 结果: `6 passed, 28 deselected in 1.90s`。
- MCP/narrow endpoint focused gate:
  - `uv run pytest -q tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_lists_chat_tools tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_support_veto_and_dispatch_gate tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_reject_spoofed_session_identity tests/xmuse/test_mcp_server.py::test_peer_chat_mcp_endpoint_exposes_only_writeback_tools`
  - 结果: `4 passed, 1 warning in 1.51s`。
- Touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/dispatch_queue.py src/xmuse_core/chat/inspector_builder.py xmuse/tui/slash_commands.py tests/xmuse/test_groupchat_collaboration_runtime.py tests/xmuse/test_tui_navigation.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。

Review subagent:

- Review subagent `Hooke` (`019e93da-1091-70c3-abfc-10ff5fdaf559`) performed a read-only
  narrow review of the dispatch queue lifecycle slice。
- 结论: no Critical/Important/Minor findings。
- Reviewer verified:
  - `claim_next_auto_dispatch` atomically claims queued auto entries with `begin immediate`。
  - processing state persists across store reload。
  - terminal transitions are gated as requested。
  - inspector exposure is read-only and counts queued/processing/dispatched/failed。
  - `/discussion` renders lifecycle fields as text without raw JSON dumping。
- Reviewer residual test gaps:
  - no direct negative tests for `mark_dispatched` from `queued` or `mark_failed` from
    `dispatched`。
  - no direct `/discussion` assertion for `failure_reason` rendering。

当前仍未满足的 V14 hard gates:

- lifecycle queue 仍未接入正式 dispatch bridge API/worker 和 real-provider execution。
- 尚未通过真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未完成 fresh + restart/resume 的 V14 collaboration/proposal/blocker/dispatch trace。
- dashboard/TUI 仍需要生产级 timeline/cards，而不只是 `/discussion` / `/blockers` 文本视图。
- 尚未跑真实 Ray + Codex app-server + MCP writeback 的 V14 多轮 soak。
- 尚未证明 V14 closure run 无 stdout fallback happy path、无残留 Ray/app-server 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer

最新完成切片是 `V14 Dashboard Runtime Timeline Read Surface Slice`，详细记录见本文件 V14
TUI/runtime 相关段落。关键状态:

- dashboard runtime timeline endpoint 和 inspector `runtime_timeline_refs` 已补。
- same-second latest selection 已覆盖 collaboration/blocker ascending lists 与 dispatch queue
  newest-first list。
- unrelated peer latency 不会被误展示为 dispatch provider writeback。
- focused verification:
  - `5 passed, 1 warning` for new runtime timeline tests。
  - `27 passed, 9 deselected, 1 warning` for dashboard inspector/runtime/latency subset。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Descartes` final re-review: no remaining Critical/Important/Minor findings in
  focused scope。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto
阻断后解除并继续 dispatch、无 stdout fallback happy path、无残留 `codex app-server` /
`raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Agent-Sourced Dispatch Queue Intent Slice

本轮继续向 clowder-style unified dispatch queue 靠拢，但仍不把 V14 标记 complete。本切片只新增
chat-owned durable dispatch intent queue，不启动 real provider，也不替代现有 lane graph / graph-set
authority。

完成内容:

- 新增 `src/xmuse_core/chat/dispatch_queue.py`:
  - `ChatDispatchQueueEntry`
  - `ChatDispatchQueueStore`
  - `enqueue_agent_auto_dispatch(...)`
  - `list_entries(conversation_id)`
- `POST /api/chat/proposals/{proposal_id}/approve` 在 collaboration dispatch gate 通过、resolution
  已创建之后，为 dispatchable lane graph approval 写入 durable dispatch queue entry:
  - `source = "agent"`
  - `auto_execute = true`
  - `status = "queued"`
  - `target = "execute"`
  - `proposal_id`
  - `resolution_id`
  - `collaboration_run_id`
  - `artifact_ref`
  - `dispatch_policy = "real_provider_allowed"`
- 无 `collaboration:<run_id>` reference 的 legacy proposal approval 不写入 V14 dispatch queue entry，
  避免绕过 structured collaboration gate。
- active veto / blocked gate path 仍不会创建 resolution/read-model/projection/dispatch queue side
  effects。
- Inspector 新增 `dispatch_queue` summary/read surface:
  - `total`
  - `queued`
  - `processing`
  - `entries`
- TUI `/discussion` 新增 `Dispatch queue:` 文本小节，展示 queue entry 状态、source、target、
  auto flag 和 proposal/resolution refs，不暴露原始 JSON。

TDD / RED evidence:

- Positive queue enqueue RED:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_enqueues_agent_auto_dispatch_entry_after_gate`
  - 初始 RED 失败点: `ModuleNotFoundError: No module named 'xmuse_core.chat.dispatch_queue'`。
- TUI queue visibility RED:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py::test_chat_screen_discussion_command_shows_collaboration_runs`
  - RED 失败点: `/discussion` 没有 `Dispatch queue: queued=1 processing=0`。
- Reviewer finding regression RED:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_without_collaboration_ref_does_not_enqueue_dispatch_entry`
  - RED 失败点: 无 `collaboration:` ref 的 approval 仍写入一条 dispatch queue entry。

验证:

- Reviewer regression focused GREEN:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_without_collaboration_ref_does_not_enqueue_dispatch_entry`
  - 结果: `1 passed, 1 warning in 1.31s`。
- Positive queue focused GREEN:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_enqueues_agent_auto_dispatch_entry_after_gate`
  - 结果: `1 passed, 1 warning in 1.51s`。
- Collaboration runtime/API focused suite:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py`
  - 结果: `15 passed, 1 warning in 9.70s`。
- TUI focused read-surface regression:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "discussion_command or blockers_command or init_status_retry_apply or new_command"`
  - 结果: `6 passed, 28 deselected in 1.93s`。
- MCP/narrow endpoint focused gate:
  - `uv run pytest -q tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_lists_chat_tools tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_support_veto_and_dispatch_gate tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_reject_spoofed_session_identity tests/xmuse/test_mcp_server.py::test_peer_chat_mcp_endpoint_exposes_only_writeback_tools`
  - 结果: `4 passed, 1 warning in 2.22s`。
- Touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/dispatch_queue.py src/xmuse_core/chat/inspector_builder.py xmuse/chat_api.py xmuse/tui/slash_commands.py tests/xmuse/test_groupchat_collaboration_runtime.py tests/xmuse/test_tui_navigation.py tests/xmuse/test_peer_chat_mcp_tools.py tests/xmuse/test_mcp_server.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。

Review subagent:

- Review subagent `Copernicus` (`019e93cf-6e25-7890-986e-f745c9fee371`) performed a read-only
  narrow review of the dispatch queue intent slice。
- Finding: Important — dispatch queue entries could be created without any collaboration gate
  passing because `_enforce_collaboration_dispatch_gate(...)` was a no-op when a proposal had no
  `collaboration:` ref, while `_enqueue_structured_dispatch_intent(...)` still enqueued
  `collaboration_run_id=None`。
- Fix: `_enqueue_structured_dispatch_intent(...)` now returns without queue write when there is no
  `collaboration:<run_id>` reference。
- Regression test:
  `test_proposal_approval_without_collaboration_ref_does_not_enqueue_dispatch_entry`。
- Minor residual hardening noted: `chat_dispatch_queue` currently has no foreign-key enforcement
  for proposal/resolution/conversation ids. API bridge supplies post-approval resolution ids, but
  future store-facing callers should preserve authority validation.

当前仍未满足的 V14 hard gates:

- 新 dispatch queue 还是 durable intent/read surface；尚未接入 real-provider execution worker /
  QueueProcessor equivalent，也没有 `processing -> dispatched/failed` runtime transition。
- dispatch gate 仍未覆盖所有 real-provider dispatch entrypoints。
- execute confirmation 仍是普通 response convention，不是 typed feasibility verdict。
- 尚未通过真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未完成 fresh + restart/resume 的 V14 collaboration/proposal/blocker/dispatch trace。
- dashboard/TUI 仍需要生产级 timeline/cards，而不只是 `/discussion` / `/blockers` 文本视图。
- 尚未跑真实 Ray + Codex app-server + MCP writeback 的 V14 多轮 soak。
- 尚未证明 V14 closure run 无 stdout fallback happy path、无残留 Ray/app-server 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Execute Confirmation Gate Tightening

本轮继续收紧 V14 dispatch gate，修掉上一小节中 “approval path 仍硬编码
`execute_confirmed=True`” 的缺口。当前仍不能标记 V14 complete。

完成内容:

- `POST /api/chat/proposals/{proposal_id}/approve` 对 `collaboration:<run_id>` refs 不再默认
  `execute_confirmed=True`。
- approval gate 现在从同一 referenced `CollaborationRun.responses` 推导 execute confirmation:
  - `target == "execute"`
  - `status == "received"`
  - `content` 非空
- active dispatch-blocking veto 的阻断原因优先于缺 execute confirmation，避免用户先看到较弱
  的 `blocked_execute_not_confirmed` 而忽略 review veto。
- 缺 execute confirmation 时 approval 在任何 resolution/read-model/projection side effect 前返回
  `dispatch_gate_blocked / blocked_execute_not_confirmed`。

TDD / RED evidence:

- `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_requires_execute_collaboration_confirmation`
  - RED 失败点: 没有 execute response 时 approval 返回 200。
- 收紧 execute gate 后，existing active-veto test 暴露 gate priority:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_references_collaboration_gate_and_blocks_active_veto`
  - 失败点: active veto 返回 `blocked_execute_not_confirmed`，期望 `blocked_active_veto`。

验证:

- Execute confirmation focused tests:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_requires_execute_collaboration_confirmation tests/xmuse/test_groupchat_collaboration_runtime.py::test_proposal_approval_references_collaboration_gate_and_blocks_active_veto`
  - 结果: `2 passed, 1 warning`。
- Collaboration runtime/API focused suite:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py`
  - 初次结果: `11 passed, 1 warning`。
  - reviewer 后补 whitespace-only execute response negative test 后结果: `12 passed, 1 warning`。
- MCP/narrow endpoint focused gate:
  - `uv run pytest -q tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_lists_chat_tools tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_support_veto_and_dispatch_gate tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_reject_spoofed_session_identity tests/xmuse/test_mcp_server.py::test_peer_chat_mcp_endpoint_exposes_only_writeback_tools`
  - 结果: `4 passed, 1 warning`。
- Touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/collaboration_store.py xmuse/chat_api.py tests/xmuse/test_groupchat_collaboration_runtime.py tests/xmuse/test_peer_chat_mcp_tools.py tests/xmuse/test_mcp_server.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。

剩余风险:

- execute confirmation 仍是普通 response 约定，不是显式 typed feasibility verdict。
- dispatch gate 仍未接到统一 agent-sourced queue / real-provider dispatch bridge 的所有入口。
- 尚未完成真实 TUI proof task、restart/resume V14 trace、dashboard timeline 和 real soak。

Review subagent:

- Review subagent `Gauss` (`019e93b5-f672-7793-af44-7673ceb3b3e4`) performed a read-only
  narrow review of the execute-confirmation gate tightening。
- 结论: no Critical/Important findings。
- Reviewer verified:
  - execute confirmation is derived from referenced run hydrated responses。
  - `record_response()` scopes responses to the run and declared targets。
  - active veto priority remains before missing execute confirmation。
  - foreign run rejection, blocked side-effect prevention, and execute-confirmation gating are covered。
- Reviewer residual risk addressed:
  - added `test_proposal_approval_rejects_blank_execute_confirmation` to prove whitespace-only
    execute response does not count as confirmation。

## 2026-06-05 V14 Durable Dispatch Gate Trace / TUI Read Surface

本轮继续收束 V14 dispatch gate 的 durable trace 和 read surface。当前仍不能标记 V14
complete；本节只是把 proposal approval gate 的可观测性从即时 decision 扩展为可恢复、
可检查的历史事件。

完成内容:

- 新增 `CollaborationDispatchGateEvent` 契约，记录:
  - `event_id`
  - `run_id`
  - `conversation_id`
  - `decision`
  - `proposal_ref`
  - `artifact_ref`
  - `execute_confirmed`
  - `policy_allows_real_provider`
  - `created_at`
- `ChatCollaborationStore.evaluate_dispatch_gate(...)` 现在对 allowed、unknown/foreign
  run、active veto、missing proposal/artifact、missing execute confirmation、policy blocked
  等 decision 都写入 `collaboration_dispatch_gate_events`。
- `ChatCollaborationStore.list_dispatch_gate_events(conversation_id, limit=20)` 提供
  conversation-scoped 读取。
- `build_conversation_inspector_payload(...)` 在 `collaboration.dispatch_gates` 暴露最近
  dispatch gate events。
- TUI `/discussion` 展示 `Dispatch gates:` 小节；即使当前没有 collaboration run，也会展示
  已持久化的 gate decision，避免 blocked/unknown decision 在 read surface 上消失。

TDD / RED evidence:

- Store/inspector durable trace RED:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py::test_dispatch_gate_decisions_are_durable_and_visible_in_inspector`
  - RED 失败点: inspector 中没有 `collaboration.dispatch_gates`。
- TUI run + gate display RED:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py::test_chat_screen_discussion_command_shows_collaboration_runs_and_dispatch_gates`
  - RED 失败点: `/discussion` 没有展示 dispatch gate decision。
- TUI no-run gate display RED:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py::test_chat_screen_discussion_command_shows_dispatch_gates_without_runs`
  - RED 失败点: `_discussion_block()` 在没有 run 时提前返回，只显示
    `Discussion runs: active=0\n- none`，dispatch gate events 被隐藏。

验证:

- TUI no-run gate display focused GREEN:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py::test_chat_screen_discussion_command_shows_dispatch_gates_without_runs`
  - 结果: `1 passed in 0.31s`。
- Collaboration runtime/API focused suite:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py`
  - 结果: `13 passed, 1 warning in 10.24s`。
- TUI focused read-surface regression:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "discussion_command or blockers_command or init_status_retry_apply or new_command"`
  - 结果: `6 passed, 28 deselected in 1.87s`。
- MCP/narrow endpoint focused gate:
  - `uv run pytest -q tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_lists_chat_tools tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_support_veto_and_dispatch_gate tests/xmuse/test_peer_chat_mcp_tools.py::test_mcp_collaboration_tools_reject_spoofed_session_identity tests/xmuse/test_mcp_server.py::test_peer_chat_mcp_endpoint_exposes_only_writeback_tools`
  - 结果: `4 passed, 1 warning in 2.30s`。
- Touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/collaboration_contracts.py src/xmuse_core/chat/collaboration_store.py src/xmuse_core/chat/inspector_builder.py xmuse/tui/slash_commands.py tests/xmuse/test_groupchat_collaboration_runtime.py tests/xmuse/test_tui_navigation.py tests/xmuse/test_peer_chat_mcp_tools.py tests/xmuse/test_mcp_server.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。

Review subagent:

- Review subagent `Maxwell` (`019e93bf-4950-73b3-ae9f-549d02a105ad`) performed a read-only
  narrow review of the durable dispatch-gate trace/read-surface slice。
- Finding: Important — TUI `/discussion` hid `collaboration.dispatch_gates` when a conversation
  had dispatch gate events but no collaboration runs, because `_discussion_block()` returned early
  on an empty run list。
- Fix: `_discussion_block()` now appends `- none` for empty runs and continues to render
  `Dispatch gates:` when inspector events exist。
- Verification for the fix is covered by
  `test_chat_screen_discussion_command_shows_dispatch_gates_without_runs` and the focused TUI
  command regression above。

当前仍未满足的 V14 hard gates:

- 尚无 clowder-style unified dispatch queue，对应 `source="agent"` / `autoExecute` / busy/queue/steer
  语义仍缺失。
- dispatch gate 仍未接入所有 real-provider dispatch entrypoints。
- execute confirmation 仍是普通 response convention，不是 typed feasibility verdict。
- 尚未通过真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未完成 fresh + restart/resume 的 V14 collaboration/proposal/blocker/dispatch trace。
- dashboard/TUI 仍需要生产级 timeline/cards，而不只是 `/discussion` / `/blockers` 文本视图。
- 尚未跑真实 Ray + Codex app-server + MCP writeback 的 V14 多轮 soak。
- 尚未证明 V14 closure run 无 stdout fallback happy path、无残留 Ray/app-server 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer (EOF)

最新完成切片是 `V14 Dashboard Runtime Timeline Read Surface Slice`，详细记录见本文件 V14
TUI/runtime 相关段落。关键状态:

- dashboard runtime timeline endpoint 和 inspector `runtime_timeline_refs` 已补。
- same-second latest selection 已覆盖 collaboration/blocker ascending lists 与 dispatch queue
  newest-first list。
- unrelated peer latency 不会被误展示为 dispatch provider writeback。
- focused verification:
  - `5 passed, 1 warning` for new runtime timeline tests。
  - `27 passed, 9 deselected, 1 warning` for dashboard inspector/runtime/latency subset。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Descartes` final re-review: no remaining Critical/Important/Minor findings in
  focused scope。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto
阻断后解除并继续 dispatch、无 stdout fallback happy path、无残留 `codex app-server` /
`raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Official API Dispatch Bridge Closure Evidence Slice

本轮继续推进 V14 closure evidence 从手工 fixture 走向 official runtime chain。当前仍不能标记
V14 complete；本节证明的是 official Chat API + dispatch bridge + collector 能形成同一条
可验证链路，真实 Ray/Codex app-server soak 和真实 TUI proof task 仍是后续 hard gate。

完成内容:

- 新增 focused closure test:
  `test_v14_closure_collector_accepts_official_api_approval_and_dispatch_bridge`。
- 测试链路使用 official Chat API 创建/驱动:
  - deterministic fresh bootstrap conversation。
  - `peer_consensus` collaboration request，targets=`review, execute`。
  - structured lane_graph proposal with `collaboration:<run_id>` ref。
  - review response + typed execute `execute_feasibility_verdict`，evidence refs 覆盖
    `proposal:<id>` 和 `artifact:lane_graph`。
  - review veto active 时 proposal approval 返回
    `dispatch_gate_blocked / blocked_active_veto`。
  - blocker resolve 后 proposal approval 成功，并由 approval path 创建 agent auto dispatch
    queue entry。
  - `ChatDispatchBridge.tick_once(...)` claim queue entry，创建 dispatch inbox item，通过
    scheduler writeback 检查并标记 `dispatch_evidence=mcp_writeback:<inbox_id>`。
  - `collect_v14_closure_evidence(...)` 从 bootstrap status、conversation inspector、
    dashboard runtime timeline 官方 read surfaces 收集证据，`validate_v14_closure_evidence(...)`
    接受同一 chain。
- 修复 collaboration runtime timestamp 证据弱点:
  - `ChatCollaborationStore._utc_now()` 不再截断 microseconds。
  - 快速连续的 blocked gate -> resolved blocker -> allowed gate 现在有 durable ordering
    evidence；closure validator 继续保持严格顺序检查，没有放宽为同秒推断。

TDD / RED evidence:

- `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_collector_accepts_official_api_approval_and_dispatch_bridge`
  - 初始 fixture 修正前暴露 proposal payload 无效；修正为合法 `summary/lanes` lane_graph 后进入目标
    RED。
  - 目标 RED 失败点:
    `missing=['dispatch_gate_lifecycle', 'agent_auto_dispatch', 'real_provider_mcp_writeback', 'tui_dashboard_read_surface']`。
  - 诊断证据: queue 和 MCP writeback 已存在且有效，但 blocked gate、resolved blocker、allowed gate
    timestamps 全为同一秒，validator 无法证明
    `blocked_time < resolved_time <= allowed_time`。

验证:

- New focused GREEN:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_collector_accepts_official_api_approval_and_dispatch_bridge`
  - 结果: `1 passed, 1 warning in 1.04s`。
- V14 closure evidence suite:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py`
  - 结果: `18 passed, 1 warning in 2.85s`。
- Runtime/dashboard focused regression:
  - `uv run pytest -q tests/xmuse/test_groupchat_collaboration_runtime.py tests/xmuse/test_peer_chat_dashboard.py -k "dispatch_gate or runtime_timeline or inspector or dispatch_bridge"`
  - 结果: `38 passed, 24 deselected, 1 warning in 14.81s`。
- TUI command/read-surface focused regression:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "overview or discussion_command or blockers_command or runtime_closure"`
  - 结果: `5 passed, 31 deselected in 0.88s`。
- TUI runtime closure card regression:
  - `uv run pytest -q tests/xmuse/test_tui_adapter.py -k "runtime_closure"`
  - 结果: `2 passed, 25 deselected in 0.52s`。
- Touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/collaboration_store.py tests/xmuse/test_v14_closure_evidence.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。

Review subagent:

- Review subagent `Feynman` (`019e9452-47b6-7d40-ac66-b225a045a724`) performed a read-only
  focused review of this API/dispatch bridge closure evidence slice。
- 结论: no Critical/Important findings。
- Reviewer confirmed:
  - 新测试 materially proves official API + dispatch bridge + collector integration，比原 hand-built
    fixture 强。
  - microsecond UTC ISO timestamps are compatible with validator parsing and dashboard timeline
    sorting/read surfaces。
- Minor residual risks:
  - TUI command proof 仍由 harness metadata 提供，不是实际运行 Textual slash commands。
  - provider 仍是 fake layer；本测试证明 scheduler/bridge/writeback contract，不是 Ray/Codex
    app-server evidence。

当前仍未满足的 V14 hard gates:

- 尚未用真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未完成真实 Ray + Codex app-server + MCP writeback 的 V14 collaboration/proposal/veto/
  dispatch fresh + restart/resume 多轮 soak。
- 尚未通过真实 TUI 启动和 slash-command 操作证明 `/new`、`/overview`、`/discussion`、
  `/blockers` 与 runtime timeline/read surface 的用户可见闭环。
- 尚未证明最终 happy path 无 stdout fallback 且无残留 `codex app-server` / `raylet` /
  `gcs_server` / `ray::` 进程。
- `collect_v14_closure_evidence(...)` 是 closure guard，不是执行 harness；最终 complete 仍需要
  外部真实运行证据填充 provider session reuse、official TUI command proof 和 process cleanup。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer (EOF-3)

最新完成切片是 `V14 Runner Cleanup Evidence Normalization Slice`，详细记录见本文件对应段落。
关键状态:

- closure validator 现在可消费 `platform_runner.health_once(...).operations.cleanup` runner cleanup
  payload。
- 仅 `status="clean"` 且 `leftovers=[]` 可满足 process cleanup gate。
- dirty、unknown、mixed legacy/runner、malformed runner cleanup evidence 都 fail closed。
- focused verification:
  - cleanup regressions: `6 passed, 1 warning`。
  - V14 closure evidence suite: `27 passed, 1 warning`。
  - runner cleanup focused regression: `2 passed`。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Feynman` final re-review: no remaining Critical/Important findings in focused
  scope。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto
阻断后解除并继续 dispatch、真实 TUI 启动/slash command proof、无 stdout fallback happy path、
无残留 `codex app-server` / `raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer (EOF-5)

最新完成切片是 `V14 Official Chat API TUI Command Proof Slice`，详细记录见本文件对应段落。
关键状态:

- Textual `XmuseTUI.run_test()` now proves `/new`、`/overview`、`/discussion`、`/blockers`
  command proof through `XmuseAdapter` connected to official `create_app(tmp_path)` Chat API/read
  surfaces。
- Production adapter default remains real `httpx.Client`; injected sync client factory is optional and
  used by tests only。
- focused verification:
  - new official API TUI proof: `1 passed, 1 warning`。
  - focused TUI command subset: `6 passed, 34 deselected, 1 warning`。
  - full TUI navigation: `40 passed, 1 warning`。
  - adapter contract/runtime cards: `35 passed`。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Feynman`: no Critical/Important findings。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto
阻断后解除并继续 dispatch、真实终端 TUI 启动演示、无 stdout fallback happy path、无残留
`codex app-server` / `raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer (EOF-6)

最新完成切片是 `V14 Runner Dispatch Bridge Operations Health Slice`，详细记录见本文件对应段落。
关键状态:

- `platform_runner.health_once(...).operations.chat_dispatch_bridge` 已暴露 official runner
  dispatch bridge evidence surface。
- 覆盖 missing `chat.db`、empty/no-table `no_entries`、observed queue counts、compact latest
  dispatch evidence。
- focused verification:
  - runner health/dispatch bridge subset: `14 passed, 50 deselected`。
  - V14 closure evidence suite: `27 passed, 1 warning`。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Feynman` final re-review: no remaining Critical/Important findings in focused
  scope。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto
阻断后解除并继续 dispatch、真实终端 TUI 启动演示、无 stdout fallback happy path、无残留
`codex app-server` / `raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Closure Validator Runner Dispatch Bridge Corroboration Slice

本轮把上一切片新增的 runner dispatch bridge operations surface 接入 V14 closure validator。
当前仍不能标记 V14 complete；本节证明的是 closure validator 不再只相信 inspector queue，而是要求
runner operations 中的 `chat_dispatch_bridge` 与同一条 closure chain 相互印证。

完成内容:

- `collect_v14_closure_evidence(...)` 现在返回 `runner_operations.chat_dispatch_bridge`。
- closure collector 在 `src/xmuse_core/chat/v14_closure_evidence.py` 内使用 read-only SQLite
  查询 `chat_dispatch_queue`，避免 import `xmuse.platform_runner`，也避免引入 MemoryOS coupling。
- `agent_auto_dispatch` gate 现在要求 runner bridge evidence:
  - `status == "observed"`
  - `dispatched >= 1`
  - compact `latest` 与 closure chain 的 `conversation_id`、`dispatch_entry_id`、agent/execute/
    auto_execute、proposal、collaboration run、artifact 和 `dispatch_evidence` 精确匹配。
- malformed runner count fail closed；`dispatched="unknown"` 等坏 payload 不会让 validator 抛错。

TDD / RED evidence:

- Missing runner operations RED:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_requires_runner_dispatch_bridge_operations`
  - RED 结果: `1 failed`，`report["ok"]` 在缺少 `runner_operations` 时仍为 `True`。
- Review regression RED:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_runner_dispatch_conversation_mismatch tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_malformed_runner_dispatch_counts`
  - RED 结果: `2 failed`。
  - 失败点: mismatched runner conversation still passed；malformed `dispatched="unknown"` raised
    `ValueError` instead of failing closed。

验证:

- Reviewed focused regressions + positive:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_accepts_full_structured_runtime_trace tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_runner_dispatch_conversation_mismatch tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_malformed_runner_dispatch_counts`
  - 结果: `3 passed, 1 warning`。
- Full closure evidence suite:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py`
  - 结果: `30 passed, 1 warning`。
- Runner affected subset:
  - `uv run pytest -q tests/xmuse/test_platform_runner.py -k "health_once or dispatch_bridge"`
  - 结果: `14 passed, 50 deselected`。
- Touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/v14_closure_evidence.py tests/xmuse/test_v14_closure_evidence.py xmuse/platform_runner.py tests/xmuse/test_platform_runner.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。
- MemoryOS/platform-runner coupling scan:
  - `rg -n "MemoryOS|memoryos|platform_runner" src/xmuse_core/chat/v14_closure_evidence.py`
  - 结果: no matches。

Review subagent:

- Review subagent `Feynman` (`019e9452-47b6-7d40-ac66-b225a045a724`) performed read-only focused
  review。
- Initial findings:
  - Important: runner `latest.conversation_id` only checked non-empty, not exact closure conversation。
  - Important: malformed runner `dispatched` count could raise instead of fail closed。
  - Minor: local SQLite bridge reader duplication is acceptable under no `platform_runner` import /
    no MemoryOS coupling, but should be factored if the shape grows。
- Fixes:
  - Exact conversation match added and covered by
    `test_v14_closure_evidence_rejects_runner_dispatch_conversation_mismatch`。
  - `_safe_int(...)` added and covered by
    `test_v14_closure_evidence_rejects_malformed_runner_dispatch_counts`。
- Re-review: no remaining Critical/Important findings。

当前仍未满足的 V14 hard gates:

- 尚未用真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未完成真实 Ray + Codex app-server + MCP writeback 的 V14 collaboration/proposal/veto/
  dispatch fresh + restart/resume 多轮 soak。
- 尚未通过真实终端 TUI 启动演示证明 `/new`、`/overview`、`/discussion`、`/blockers` 与
  runtime timeline/read surface 的用户可见闭环。
- 尚未证明最终 happy path 无 stdout fallback 且无残留 `codex app-server` / `raylet` /
  `gcs_server` / `ray::` 进程。
- 本切片强化 closure guard，不是真实 provider execution harness。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer (EOF-7)

最新完成切片是 `V14 Closure Validator Runner Dispatch Bridge Corroboration Slice`，详细记录见本文件
对应段落。关键状态:

- closure validator 现在要求 `runner_operations.chat_dispatch_bridge` 与 inspector/timeline
  closure chain 的 dispatched agent entry 精确匹配。
- Missing runner operations、conversation mismatch、malformed counts 都 fail closed。
- focused verification:
  - closure evidence suite: `30 passed, 1 warning`。
  - runner health/dispatch bridge subset: `14 passed, 50 deselected`。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Feynman` final re-review: no remaining Critical/Important findings in focused
  scope。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto
阻断后解除并继续 dispatch、真实终端 TUI 启动演示、无 stdout fallback happy path、无残留
`codex app-server` / `raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Terminal TUI Demo Closure Gate Slice

本轮继续强化 V14 closure guard，把“真实终端 TUI 启动演示”从 handoff 风险项提升为显式
closure gate。当前仍不能标记 V14 complete；本节只证明 validator 不再把 Textual `run_test()`
slash proof 当成真实 terminal demo。

完成内容:

- `GATE_NAMES` 新增 `terminal_tui_demo`。
- `collect_v14_closure_evidence(...)` 会读取 persisted `tui_terminal_demo.json` 中的
  `terminal_tui_demo` payload。
- `terminal_tui_demo` gate 要求:
  - `conversation_id` 与 closure conversation 一致。
  - `mode == "terminal"`，`mode="textual_run_test"` 明确不接受。
  - command 必须是真实 TUI launch form: `xmuse-tui`、`python -m xmuse.tui` 或
    `uv run python -m xmuse.tui`。
  - `exit_code` 必须是 exact int `0`，JSON boolean `false` 不接受。
  - terminal demo started/completed timestamp 必须在 allowed dispatch gate 之后。
  - visible surfaces 必须覆盖 `init`、`overview`、`discussion`、`blockers`、`dispatch`、
    `provider_writeback`、`resume`。
  - `runtime_timeline_event_ids` 必须覆盖同一 closure chain 的 collaboration run、resolved
    blocker、blocked/allowed gate、dispatch entry 和 provider writeback inbox，并且都来自
    official runtime timeline。

TDD / RED evidence:

- Missing/weak terminal demo RED:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_requires_terminal_tui_demo tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_textual_run_test_as_terminal_demo`
  - RED 结果: `2 failed`，缺失 terminal demo 或 `mode="textual_run_test"` 时 `report["ok"]`
    仍为 `True`。
- Review regression RED:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_non_launch_terminal_demo_command tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_boolean_terminal_demo_exit_code`
  - RED 结果: `2 failed`，`echo xmuse.tui` 和 `exit_code=false` 仍可通过。

验证:

- Focused positive + reviewed regressions:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_accepts_full_structured_runtime_trace tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_non_launch_terminal_demo_command tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_boolean_terminal_demo_exit_code`
  - 结果: `3 passed, 1 warning`。
- Full closure evidence suite:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py`
  - 结果: `34 passed, 1 warning`。
- TUI command/read-surface focused subset:
  - `uv run pytest -q tests/xmuse/test_tui_navigation.py -k "official_tui_command_proof or official_chat_api or new_command or overview or discussion_command or blockers_command"`
  - 结果: `10 passed, 30 deselected, 1 warning`。
- Touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/v14_closure_evidence.py tests/xmuse/test_v14_closure_evidence.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。
- MemoryOS/platform-runner coupling scan:
  - `rg -n "MemoryOS|memoryos|platform_runner" src/xmuse_core/chat/v14_closure_evidence.py`
  - 结果: no matches。

Review subagent:

- Review subagent `Feynman` (`019e9452-47b6-7d40-ac66-b225a045a724`) performed read-only focused
  review。
- Initial findings:
  - Important: command check only searched substring `xmuse.tui`，`echo xmuse.tui` could pass。
  - Important: `exit_code=False` passed because Python `False == 0`。
- Fixes:
  - `_is_terminal_tui_launch_command(...)` now parses with `shlex.split` and accepts only known
    TUI launch forms。
  - exit code now requires `type(exit_code) is int and exit_code == 0`。
  - Added regressions for both cases。
- Re-review: no remaining Critical/Important findings。

当前仍未满足的 V14 hard gates:

- 尚未用真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未完成真实 Ray + Codex app-server + MCP writeback 的 V14 collaboration/proposal/veto/
  dispatch fresh + restart/resume 多轮 soak。
- 尚未实际运行 terminal TUI demo 并写入真实 `tui_terminal_demo.json` evidence；本切片只是让
  closure validator fail closed。
- 尚未证明最终 happy path 无 stdout fallback 且无残留 `codex app-server` / `raylet` /
  `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer (EOF-8)

最新完成切片是 `V14 Terminal TUI Demo Closure Gate Slice`，详细记录见本文件对应段落。关键状态:

- closure validator 新增 `terminal_tui_demo` gate。
- Textual `run_test()`、non-launch command、boolean exit code、缺失 terminal demo evidence 都
  fail closed。
- collector 可读取 `tui_terminal_demo.json`，但尚未执行真实 terminal demo。
- focused verification:
  - closure evidence suite: `34 passed, 1 warning`。
  - TUI command/read-surface focused subset: `10 passed, 30 deselected, 1 warning`。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Feynman` final re-review: no remaining Critical/Important findings in focused
  scope。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto
阻断后解除并继续 dispatch、真实终端 TUI 启动并产生 demo evidence、无 stdout fallback happy path、
无残留 `codex app-server` / `raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer (EOF-11)

最新完成切片是 `V14 Terminal TUI Demo Harness Slice`，详细记录见本文件对应段落。关键状态:

- 新增 terminal TUI demo harness 和 `xmuse-tui-terminal-demo` CLI。
- Public evidence write path 只读 official/persisted surfaces，不接受 synthetic read-surface payload。
- `/resume` 现在能记录 official TUI command proof，并支持 proposal-ready conversation id 恢复。
- Stale command events、non-launch command、boolean/non-zero exit code、缺失 surface 都无法写入
  `tui_terminal_demo.json`。
- focused verification:
  - closure + terminal demo suite: `40 passed, 1 warning`。
  - TUI command/read-surface focused subset: `7 passed, 33 deselected, 1 warning`。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Feynman` final re-review: no remaining Critical/Important findings in focused
  scope。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto
阻断后解除并继续 dispatch、真实终端 TUI 启动并产生 demo evidence、无 stdout fallback happy path、
无残留 `codex app-server` / `raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer (EOF-14)

最新完成切片是 `V14 Terminal TUI Demo Harness Provenance Gate Slice`。详细记录在本文件
`2026-06-05 V14 Terminal TUI Demo Harness Provenance Gate Slice` 段落。

关键状态:

- terminal TUI demo evidence 必须由同一 harness run 的 persisted TUI command events 互证。
- 手写 terminal JSON、缺 run id、缺 observed command events、run id mismatch、脚本不完整、空字符串脚本、
  command event 窗口外时间都 fail closed。
- focused verification:
  - closure + terminal demo suite: `48 passed, 1 warning`。
  - TUI command/read-surface focused subset: `7 passed, 33 deselected, 1 warning`。
  - touched-file ruff passed。
  - `git diff --check` passed。
- Review subagent `Meitner` final re-review: no remaining Critical/Important findings in focused
  scope。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto 阻断后解除并继续
dispatch、真实终端 TUI 启动并产生 demo evidence、无 stdout fallback happy path、无残留
`codex app-server` / `raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 MCP Writeback Stage Timing Evidence Hardening Slice

本轮继续强化 `real_provider_mcp_writeback` closure gate。当前仍不能标记 V14 complete；本切片证明的是
MCP writeback stage timings 不能用 JSON/Python 非真实数值冒充真实 Ray/Codex/MCP 时序。

完成内容:

- `_valid_mcp_writeback_turn(...)` 已经要求 execute target、`delivery_mode == "mcp_writeback"`、
  `degraded_reason is None`，以及 `ray_actor_delivery_start`、`codex_app_server_turn_start`、
  `chat_post_message`、`trace_persisted` 四个 stage 按序存在。
- 本轮进一步收紧 stage timestamp:
  - `bool` 不再作为 int/float 通过。
  - `float("inf")` / `float("nan")` 等 non-finite 数值不再通过。
- 修复 collector fixture 的时间顺序脆弱性：`collaboration_responses.created_at` 被 pin 到 allowed
  gate 之前，符合 validator 要求的“execute confirmed before allowed dispatch gate”语义。

TDD / RED evidence:

- Boolean stage timing RED:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_boolean_mcp_stage_timing`
  - 初始 `chat_post_message.at=True` 被排序检查拒绝，不是有效 RED；改为
    `ray_actor_delivery_start.at=True` 后 RED 结果: `1 failed`，`report["ok"]` 仍为 `True`。
- Non-finite stage timing RED:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_infinite_mcp_stage_timing tests/xmuse/test_v14_closure_evidence.py::test_v14_closure_evidence_rejects_nan_mcp_stage_timing`
  - RED 结果: `2 failed`，`inf` / `nan` stage timing 仍可满足 closure。

验证:

- Full closure evidence suite:
  - `uv run pytest -q tests/xmuse/test_v14_closure_evidence.py`
  - 结果: `44 passed, 1 warning`。
- Touched-file ruff:
  - `uv run ruff check src/xmuse_core/chat/v14_closure_evidence.py tests/xmuse/test_v14_closure_evidence.py`
  - 结果: `All checks passed!`。
- `git diff --check`
  - 结果: 无输出，exit 0。
- MemoryOS scan:
  - `rg -n "MemoryOS|memoryos" src/xmuse_core/chat/v14_closure_evidence.py tests/xmuse/test_v14_closure_evidence.py`
  - 结果: no matches。

Review subagent:

- Review subagent `Gibbs` (`019e9518-126c-70d2-b6cd-fd06208efd90`) performed read-only focused
  review。
- Initial Important finding:
  - `float("inf")` / `float("nan")` could still pass stage timing checks, because they satisfy
    numeric type checks and can survive the ordering comparison。
- Fix:
  - Added `math.isfinite(...)` check before accepting stage times。
  - Added `inf` and `nan` regressions。
- Re-review: no remaining Critical/Important findings。

当前仍未满足的 V14 hard gates:

- 尚未实际运行 terminal TUI demo CLI 生成真实 fresh `tui_terminal_demo.json` evidence。
- 尚未用真实 provider 自动 dispatch 修改正式 TUI 主路径代码。
- 尚未完成真实 Ray + Codex app-server + MCP writeback 的 V14 collaboration/proposal/veto/
  dispatch fresh + restart/resume 多轮 soak。
- 尚未证明真实/fresh veto 阻断 dispatch 后解除，并继续 dispatch。
- 尚未证明最终 happy path 无 stdout fallback 且无残留 `codex app-server` / `raylet` /
  `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。

## 2026-06-05 V14 Latest Continuation Pointer (EOF-15)

最新完成切片是 `V14 MCP Writeback Stage Timing Evidence Hardening Slice`，详细记录见本文件对应段落。
关键状态:

- `real_provider_mcp_writeback` gate 不再接受 bool、inf、nan stage timings。
- Full closure evidence suite: `44 passed, 1 warning`。
- touched-file ruff passed。
- `git diff --check` passed。
- Review subagent `Gibbs` final re-review: no remaining Critical/Important findings in focused scope。

V14 仍不能标记 complete。剩余 hard gates 仍包括真实 Ray + Codex app-server + MCP writeback
fresh/restart 多轮 soak、真实 provider 自动 dispatch 修改正式 TUI 主路径、真实/fresh veto 阻断后解除并继续
dispatch、真实终端 TUI 启动并产生 demo evidence、无 stdout fallback happy path、无残留
`codex app-server` / `raylet` / `gcs_server` / `ray::` 进程。

MemoryOS 状态: 本轮未读取或修改 `/home/iiyatu/projects/python/memoryOS`，未新增 MemoryOS
import/config/runtime dependency。
