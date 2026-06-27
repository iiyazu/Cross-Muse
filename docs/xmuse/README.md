# xmuse 文档入口

更新日期: 2026-06-27

本目录现在按“当前 goal 入口、当前产品合同、CI/兼容合同、历史档案”分层。下一轮
自然 agents 群聊 `/goal` 不再默认读取旧的 closure ledger、walkthrough、runtime
operation record 或巨大 handoff 文档。

## 当前 Goal 文档包

下一轮 `/goal` 只需要默认读取这些文档：

| 文档 | 用途 |
|---|---|
| `docs/xmuse/document-status.md` | 当前文档状态索引：标记 default-read、current-contract、retained-by-test、reference-only 和 archived，避免新会话误读旧 goal |
| `docs/xmuse/natural-groupchat-a2a-goal.md` | 当前愿景、最新状态、A2A/Ray/Clowder-AI 取舍和 forbidden claims |
| `docs/xmuse/natural-groupchat-a2a-behavior.md` | authority-first 行为规范、TDD/superpowers/GitHub 约束、patch/refactor 阈值 |
| `docs/xmuse/natural-groupchat-a2a-task-plan.md` | Phase 0-7 的实施任务、验收和停止条件 |
| `docs/xmuse/natural-groupchat-a2a-goal-prompt.md` | 可直接贴入 `/goal` 的简洁 prompt |
| `/home/iiyatu/projects/python/xmuse-m7-natural-groupchat-goal-design/docs/superpowers/specs/2026-06-26-natural-groupchat-a2a-production-goal-design.md` | 详细设计来源 |
| `/home/iiyatu/clowder-ai` | 自然群聊实现参考，不是 xmuse authority |

当前校准：

- `origin/main` 当前按 PR #242 / `c1d19ad2ae9bd8b22742376c98968073a508329c`
  校准。
- PR #193 (`codex/a2a-sdk-foundation`) 和 A2A hardening PR #234-#242
  已合并。
- PR #242 (`codex/a2a-natural-real-chain`) 将 peer chat 主路径默认切到
  native GOD session，并保留 Ray 作为 optional legacy backend。
- 最新已观察 main CI run `28292323481` 在 merge commit `c1d19ad...`
  上成功。
- Dirty historical worktree 和 archive 文档只能作为参考，不是 main capability。

下一轮长 `/goal` 是无人值守吞吐型 goal：时间只表示可承载的任务量级，不
按小时切死阶段。推荐采用三写轨加一只读副驾轨：

```text
Track A: natural groupchat real chain / PR / CI / merge
Track B: MemoryOS sidecar and context continuity
Track C: frontend API / UX read projection
Track D: read-only copilot audit
```

Track A 是主链路和合并协调者。Track B/C 只能消费已存在 authority，
不能替代 `chat.db / inbox / proposal / review verdict / dispatch queue /
GitHub server facts`。Track D 只能写共享审计记录，不能写代码或创建 PR。

## 当前产品主线

`docs/xmuse/mainline-contracts.md` 是产品主线合同入口。它保留这条 north-star：

```text
GOD groupchat deliberation
-> frozen blueprint
-> feature/lane/laneDAG
-> centralized execution/review
-> GitHub merge gate
-> REST-first MemoryOS
```

`blueprint freeze 是去中心化 GOD deliberation 与中心化 execution/review 的边界`。
`feature_lanes.json` 仍是兼容投影和 live queue，不是 authority。

下一轮 natural groupchat A2A goal 会把主线前半段改成更实际的运行路线：

```text
natural groupchat
-> official a2a-sdk provider / handoff / artifact envelope
-> xmuse chat.db / inbox / proposal / review / dispatch authority
-> provider-native execution
-> PR / CI / operator merge
```

A2A SDK 是 interop boundary，不是 proposal、review、dispatch 或 merge authority。
Ray 是 optional legacy adapter，不是默认自然群聊 kernel。

## CI 和合同文档

这些文档仍是当前 CI、合同测试或 release 判断的一部分，保留在顶层：

| 文档 | 用途 |
|---|---|
| `docs/xmuse/contract-smoke-gates.md` | no-secrets contract smoke CI gate |
| `docs/xmuse/peer-chat-runtime-gate.md` | no-secrets peer-chat runtime focused gate |
| `docs/xmuse/deep-research-03-next-goal.md` | historical contract-vs-runtime proof split used by CI docs tests |
| `docs/xmuse/real-runtime-integration-gate.md` | no-secrets real runtime integration gate contract |
| `docs/xmuse/broad-suite-baseline-debt.md` | known broad-suite baseline gaps |
| `docs/xmuse/memoryos-lite-runtime-compatibility.md` | MemoryOS Lite public compatibility contract |
| `docs/xmuse/vision-runtime-evidence-closure-plan.md` | older proof-level boundary plan kept for tests |
| `docs/xmuse/vision-runtime-evidence-closure-goal-prompt.md` | older prompt kept for tests |
| `docs/xmuse/github-server-side-gate-live-evidence-2026-06-25.md` | latest committed GitHub server-side evidence snapshot |
| `docs/xmuse/github-server-side-gate.md` | GitHub server-side gate contract |
| `docs/xmuse/github-review-merge-contract.md` | PR template, CODEOWNERS and merge-ready contract |
| `docs/xmuse/release-checklist.md` | current release claim boundary |

Do not use these older CI docs as the active natural groupchat goal plan unless
the task explicitly targets their contract surface.

## Implementation Policies Still In Force

| 文档 | 用途 |
|---|---|
| `docs/xmuse/code-quality-and-archive-policy.md` | reuse, refactor, archive and state-write quality rules |
| `docs/xmuse/parallel-development-runbook.md` | parallel session coordination, useful only after interfaces are frozen |
| `docs/xmuse/goal-copilot-behavior-policy.md` | optional read-only copilot behavior |
| `docs/xmuse/goal-stage-harness.md` | standard stage/evidence vocabulary |
| `docs/xmuse/production-operations.md` | operational commands and expectations |
| `docs/xmuse/provider-matrix.md` | provider support matrix |
| `docs/xmuse/config-matrix.md` | configuration surface |
| `docs/xmuse/解耦开发协议.md` | layer and event boundary protocol |

## Historical Archive

Moved historical material:

```text
docs/xmuse/archive/2026-06-pre-m7/
docs/xmuse/archive/2026-06-pre-overnight-goal/
```

`2026-06-pre-m7/` contains the old `codex-strengthening-handoff.md`,
`fullchain-runtime-*`, `production-closure-gap-ledger.md`,
`real-provider-soak-evidence-2026-06-21.md`, and
`walkthrough-maintenance-notes*.md` files.

`2026-06-pre-overnight-goal/` contains superseded deep-research, Path/V-series,
closure, self-iteration, OpenCode-in, and production-strengthening prompts or
roadmaps that are no longer default entrypoints.

Rules:

1. Do not treat archived evidence as proof for a new PR head.
2. Do not restart old L8-L11, overnight-readiness, or closure-ledger framing
   from the archive.
3. If an archived implementation detail is reused, cite it as reference and
   re-verify the current code path.

Old `docs/superpowers/specs/` and `docs/superpowers/plans/` remain historical
implementation records because tests and lane history may reference their
paths. They are not the current entrypoint.
