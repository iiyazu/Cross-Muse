# Development Goal Worker Delegation Policy

更新日期: 2026-06-13

本文档是 Codex 开发 xmuse 时使用 `/goal` 的 worker 委派规范。通用 goal 行为、
L1-L11 dependency-first closure、proof level、anti-false-closure 和 anti-TDD-abuse
规则以 `docs/xmuse/goal-behavior-contract.md` 为准。本文只补充 worker 委派边界。
它约束的是 **开发过程中的 worker 委派方式**，不是 xmuse 产品运行时的 provider
权限模型。
产品内 Codex/OpenCode/GOD 权限仍以 `provider-matrix.md`、`mainline-contracts.md`
和具体实现合同为准。

后续 `/goal` prompt 应同时引用
`docs/xmuse/goal-behavior-contract.md` 和本文档，不需要重复展开这两个文件的行为
规范；只有改变 goal 行为或委派策略时才更新对应文档。

## Roles

- Codex 是 outer controller、planner、reviewer、verifier、committer 和最终事实判断者。
- OpenCode 是 bounded worker，可以在明确 scope 内直接修改工作树生成候选 patch，
  也可以提交候选 artifact 或候选审计摘要。
- OpenCode 不能作为架构裁决者、状态权威、release truth、merge truth 或最终 reviewer。
- OpenCode 的自报完成不构成证据；必须由 Codex 独立审查和验证。

## Core Workflow: Dependency-First, Single Writer, Multiple Verifiers

长 `/goal` 的稳定组织原则是 **单 writer，多 verifier**。

主 Codex 必须先读 `production-closure-gap-ledger.md`，锁定目标 L 层、上游依赖、
authority owner、proof level 和 forbidden claims。Worker 不得把测试、TUI 投影、
provider inventory、release pack 字段、local CI 或自报完成当作 closure proof。

| Role | Permissions | Task |
|------|-------------|------|
| 主 Codex | 可写 | 最终设计、生产代码修改、最终 diff、提交、推送、PR 更新和最终事实判断 |
| explorer subagent | 只读 | 梳理相关调用链、现有测试、业务不变量和风险文件 |
| test-designer subagent | 只读或仅测试目录可写 | 设计行为级测试意图，指出过拟合风险，不碰生产实现 |
| reviewer subagent | 只读 | 审查最终 diff 的过拟合、特判、架构破坏、安全/并发风险和遗漏测试 |
| docs/api subagent | 只读 + 文档工具 | 核查框架/API 行为，防止凭记忆编码 |

不要让同一个 worker context 同时负责“定义测试世界、写实现、宣布通过”。主 Codex
可以添加测试，但测试只能验证已经明确的 authority/proof path。OpenCode 如被委派，
默认只产生 candidate patch/artifact/audit，不能自证完成。

## Dependency-First Closure Loop

默认流程是:

```text
Truth refresh
-> Layer targeting
-> Authority design
-> Production slice implementation
-> Targeted tests
-> Evidence export
-> Self-review / anti-false-closure audit
-> Ledger update and claim boundary
```

RIGR-V 仍可作为单个代码切片内部的工程节奏，但不得替代 L 层依赖、authority owner、
proof level 和 ledger boundary。Red-first 测试不是架构来源。

### Read

编码前必须明确:

- Task understanding:
  - User-visible behavior to change
  - Existing code path
  - Existing tests that already cover nearby behavior
  - Risk surface

禁止一上来写测试。先证明理解了目标 L 层、authority owner、现有生产路径和风险，
再决定是否需要 targeted tests。

### Invariant

每个任务至少声明两类不变量:

- Behavior invariants:
  - Existing valid behavior must remain unchanged.
  - Error handling, auth, persistence, compatibility, and contract semantics
    remain unchanged unless explicitly requested.
- Architecture invariants:
  - Do not change public API unless explicitly required.
  - Do not bypass existing abstraction or authority boundaries.
  - Do not add special cases for test fixtures.

### Tests When Appropriate

Targeted tests 只在行为可判定的场景强制使用:

| Task type | Test requirement | Correct evidence |
|-----------|-----------------|------------------|
| Bug fix | Required | Reproduce the bug first, then fix |
| Pure function / algorithm / parser | Required | Unit tests with boundaries; property/fuzz optional |
| API contract | Required | Contract or integration test |
| Refactor | Not normally required | Existing tests first; add characterization tests only when needed |
| UI bug | Semi-required | Steps, screenshots, browser evidence, and targeted tests where useful |
| Performance | Not ordinary TDD | Benchmark/profile/regression guard |
| Security / permissions | TDD is not enough | Negative/abuse tests plus review |
| Architecture migration | Not red-first by default | Plan, phased migration, compatibility tests |
| Docs/comments | Not needed | Lint/build docs if available |

A failing test is acceptable only if:

- It fails before implementation.
- It describes external behavior, public contract, reproduced bug, or a
  low-level library contract.
- It would remain valuable under a different correct implementation.
- It does not assert private implementation details unless the task is a
  low-level internal unit.
- It includes boundary or negative coverage when relevant.

### Green-By-Production-Slice

Green-by-production-slice 禁止:

- 修改测试预期来通过。
- 删除、skip、xfail、only 或放宽断言。
- 增加无意义 timeout。
- 特判测试 fixture、文件名、样例值或 test-only input。
- mock 掉真正该验证的业务路径。
- 用 mock 绕过 selected GOD binding、provider invocation、recovery enforcement
  或 review truth。
- 给 evidence pack 增加字段但没有上游 producer。
- 先扩展 TUI/dashboard/read model 再把它描述成 upstream closure。
- 吞异常或绕过 auth/persistence/validation。
- 改 public API 但不更新调用方和契约。

允许:

- 最小且诚实的生产代码改动，包括 contract/schema、store/resolver、runtime/API hook、
  fail-closed behavior、evidence artifact 和 ledger update。
- 清晰错误处理、真实边界修复、类型/校验补充。
- 复用已有项目模式或抽出已有模式中的局部复用逻辑。

### Refactor

Refactor 必须服务清晰性和边界收敛，不能借机改变语义。允许删除重复、收紧命名、
移动到合适模块、降低耦合、保持 public contract 不变。若 refactor 需要改变设计，
必须回到 plan/stage，不准混在 green 阶段里做。

### Verify

完成定义不能是 “tests pass”。Done when:

- 新 failing test 如果存在，确实先失败、后通过，并证明真实需求。
- Relevant existing tests pass.
- Lint/type/format/check commands pass where available.
- Diff review finds no test weakening, fixture special-casing, unrelated edits,
  public API breakage, excessive mocks, swallowed errors, or boundary violation.
- Final behavior matches the user request.
- Remaining risk is explicitly reported.

Codex 最终报告或 PR notes 需要回答:

1. 新测试失败时证明了什么真实需求？
2. 实现是否可能只是在拟合测试样例？
3. 有没有修改、删除、放宽、跳过测试？
4. 有没有 mock 掉真正该验证的路径？
5. 除了测试绿，还有什么证据表明行为正确？
6. 本轮 target layer、proof level、manual gaps 和 forbidden claims 是什么？

## Repeated Failure And Demo-Grade Refactor Rule

反复失败和 demo 级实现不是继续叠补丁的信号，而是重构边界的信号。

- 同一功能、stage、测试簇或 runtime path 出现两次同类失败后，Codex 必须停止继续
  叠加局部 patch，并把下一步改为有边界的 root-cause/refactor 或替换失败边界。
- 第三次同边界重试只允许在重构/替换 artifact 已存在后进行；该 artifact 必须写清
  失败边界、替代边界、迁移行为、focused tests 和回滚/兼容策略。
- goal-stage / supervisor 已标记 `refactor_required` 时，不得继续同路径修补；
  必须先重构或替换失败边界，再允许执行。
- 如果生产主线依赖 demo 级实现，不得通过包 adapter、UI 文案或 evidence 标签把
  demo 包装成生产能力。应隔离或归档 demo path，并以 contract-backed production
  path 替换。
- 重构必须有明确 owner、allowed files、迁移/兼容策略、focused tests 和回滚边界；
  不允许以“重构”为名扩大成无边界重写。
- OpenCode 只能在 Codex 已定义重构边界、验收合同和 gate 后承担机械子任务；
  OpenCode 不能决定是否接受架构重构，也不能自证完成。

## When To Delegate To OpenCode

只有同时满足以下条件时，Codex 才应把子任务委派给 OpenCode:

- 任务已经有详细计划、明确文件范围和明确 gate。
- 任务是繁重、重复、低智能需求或局部实现，不需要新的架构判断。
- 任务失败可以回滚，且结果可以通过 diff、测试、lint 或 artifact schema 验证。
- 任务不需要读取或写入 secrets、live credentials、外部生产配置或权威 runtime state。
- 任务不会直接改变 release/merge/GitHub/MemoryOS truth 语义。

适合委派的任务:

- 批量文档同步、引用修正、历史记录归类。
- 已有 plan 下的局部测试补齐、fixture 更新、机械重构。
- 大范围检索、证据包整理、非权威审计摘要。
- stage manifest 已定义且 gate 清晰的 bounded implementation stage。
- 明确要求“不扩大范围、不提交、不推送、不写 runtime state”的候选 patch。

OpenCode candidate patch 规则:

- Codex 必须先写清 allowed files、forbidden files、acceptance gate 和回滚边界。
- OpenCode 可以修改工作树，但不得提交、推送、更新 PR、改仓库设置或写 runtime
  state。
- OpenCode patch 默认未被接受；Codex 必须独立读 diff、运行 gate、审查 proof-level
  和 package/runtime boundary 后才可纳入最终 diff。
- 如果 OpenCode patch 触碰 authority、review truth、GitHub truth、MemoryOS live
  proof、peer-GOD 或 release readiness 语义，Codex 必须拒收或重写该部分。

不适合委派的任务:

- 架构、权限、安全、Auth/RBAC、durable authority 或 package boundary 决策。
- MemoryOS live proof、GitHub server-side truth、release readiness、`pr_merged`
  等事实分类。
- 没有明确验收 gate 的探索性实现。
- 用户需求澄清、产品最终形态判断和复杂 TUI/UX 取舍。
- 任何需要提交、推送、更新 PR、修改仓库设置或处理 secrets 的步骤。

## Invocation

优先通过 stage harness 调用 OpenCode:

```bash
uv run python scripts/goal_stage_runner.py \
  --stage-manifest /abs/path/to/stage-manifest.json \
  --engine opencode \
  --repo-root /home/iiyatu/projects/python/xmuse \
  --output .goal-runs/<stage_id>/result.json
```

OpenCode 的 DeepSeek 调用必须使用:

```bash
opencode run --model opencode-go/deepseek-v4-flash --variant max ...
```

禁止使用 `opencode-go/deepseek-v4-flash:max`、`deepseek-v4-flash:max`、
`deepseek-v4-flash-max` 或 `opencode-go/deepseek-v4-flash-max`。`max` 是
OpenCode CLI variant，不是 model id 的一部分。

如果 `opencode`、`opencode-go` 或 `DEEPSEEK_API_KEY` 不可用，记录 blocker 和
owner；不得把失败伪装成 OpenCode live proof。必要时由 Codex 接回任务。

## Codex Model Fallback Is Not Delegation

`scripts/goal_stage_runner.py` 默认使用
`--fallback-model gpt-5.3-codex-spark --fallback-on quota_exhausted` 的等价行为。
当 `codex exec -m gpt-5.5` 返回 quota/usage/weekly limit 等额度耗尽信号时，
runner 会自动用 `gpt-5.3-codex-spark` 重跑同一阶段 prompt。fallback 仍属于
Codex 执行上下文，只是为了解决 `gpt-5.5` 额度耗尽后的 stage 连续性。

边界:

- spark fallback 不是 OpenCode/DeepSeek worker 委派。
- spark fallback 输出仍必须按 Codex 输出审查：读取 diff、验证 gate、检查
  proof-level、manual gap 和 forbidden claims。
- fallback 成功不升级 `proof_level`，不构成 live proof、review truth、merge truth
  或 OpenCode peer-GOD 证明。
- fallback 不允许自动提交、推送、改 PR 或删除 manual gaps。
- fallback 只作用于 runner 启动的 stage 子进程；外层 `/goal` 会话耗尽时仍需要
  用户在 Codex UI/CLI 中选择可用模型后继续。

## Delegation Packet

委派给 OpenCode 的 prompt 或 stage manifest 必须包含:

- objective: 单一、可验收的目标。
- scope: 可修改的文件或目录范围。
- allowed actions: 允许的编辑、测试、检索或 artifact 生成动作。
- forbidden actions: 禁止提交、推送、写 runtime state、读写 secrets、创建
  `xmuse/__init__.py`、绕过合同或扩大范围。
- acceptance contracts: 必须满足的合同、schema、proof-level 或边界。
- validation commands: 需要 Codex 后续运行或复核的 gate。
- output requirements: 必须说明 changed files、reasoning、tests attempted、
  blockers 和 residual risk。

## Codex Review Duties

OpenCode 返回后，Codex 必须完成独立审查:

- 读取 `git status -sb` 和相关 `git diff`，确认没有越权文件或 runtime state。
- 检查是否触碰 `xmuse/__init__.py`、`feature_lanes.json`、`xmuse/work/`、
  `xmuse/history/`、`xmuse/logs/`、DB、sqlite 或 jsonl runtime state。
- 核对 package boundary: `xmuse_core` 不得直接依赖 runtime `xmuse/` 或
  `memoryos_lite`。
- 运行与任务匹配的 `uv run pytest ...`、`uv run ruff check ...`、
  `git diff --check` 或 schema/gate 命令。
- 对 OpenCode 声称的 proof-level、live evidence、review/merge truth 做事实复核。
- 只在 Codex 独立验证后接受 patch；必要时修改、回滚或重新委派。

拒收条件:

- 超出 scope、引入无关重构或隐藏状态写入。
- 把 fake/local/contract evidence 标成 live/server-side/real-provider proof。
- 跳过 gate、伪造测试结果或只给自然语言完成声明。
- 更改 authority 边界、provider 权限、release truth 或 merge truth 但没有明确授权。

## Evidence And Reporting

- `.goal-runs/`、`xmuse/work/` 和 runtime artifacts 默认不提交。
- OpenCode 产物应记录为候选 evidence 或候选 patch，不是最终事实。
- 最终报告由 Codex 汇总: 委派了什么、接受/拒收了什么、运行了哪些 gate、
  剩余 blocker 是什么。
- PR body 或 walkthrough 只记录经 Codex 复核后的结论。

## Prompt Minimization

后续长 `/goal` prompt 可只写:

```text
Read and follow docs/xmuse/goal-behavior-contract.md for dependency-first
closure behavior, proof levels, anti-false-closure review, and anti-TDD-abuse.
Read and follow docs/xmuse/development-goal-worker-delegation-policy.md for
OpenCode worker delegation. Do not repeat the policy unless changing it.
```

如果某轮 `/goal` 需要偏离本文档，必须在 prompt 中明确说明偏离点、原因和人工授权。
