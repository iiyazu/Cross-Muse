# Development Goal Worker Delegation Policy

更新日期: 2026-06-13

本文档是 Codex 开发 xmuse 时使用 `/goal` 的固定行为规范。它约束的是
**开发过程中的 worker 委派方式**，不是 xmuse 产品运行时的 provider 权限模型。
产品内 Codex/OpenCode/GOD 权限仍以 `provider-matrix.md`、`mainline-contracts.md`
和具体实现合同为准。

后续 `/goal` prompt 应引用本文档，不需要重复展开本文件的行为规范；只有改变
委派策略时才更新本文档。

## Roles

- Codex 是 outer controller、planner、reviewer、verifier、committer 和最终事实判断者。
- OpenCode 是 bounded worker，只提交候选 patch、候选 artifact 或候选审计摘要。
- OpenCode 不能作为架构裁决者、状态权威、release truth、merge truth 或最终 reviewer。
- OpenCode 的自报完成不构成证据；必须由 Codex 独立审查和验证。

## Repeated Failure And Demo-Grade Refactor Rule

反复失败和 demo 级实现不是继续叠补丁的信号，而是重构边界的信号。

- 同一功能、stage、测试簇或 runtime path 出现两次同类失败后，Codex 必须先做
  root-cause 记录，停止继续叠加局部 patch。
- 若需要第三次重试，或 goal-stage / supervisor 已标记 `refactor_required`，
  必须先重构或替换失败边界，再允许继续执行。
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
Read and follow docs/xmuse/development-goal-worker-delegation-policy.md for
OpenCode worker delegation. Do not repeat the policy unless changing it.
```

如果某轮 `/goal` 需要偏离本文档，必须在 prompt 中明确说明偏离点、原因和人工授权。
