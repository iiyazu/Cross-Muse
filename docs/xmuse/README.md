# xmuse 文档入口

更新日期: 2026-06-28

本目录现在按“当前 goal 入口、当前产品合同、CI/兼容合同、历史档案”分层。下一轮
自然 agents 群聊 `/goal` 不再默认读取旧的 closure ledger、walkthrough、runtime
operation record 或巨大 handoff 文档。

## 当前 Goal 文档包

下一轮 `/goal` 只需要默认读取这些文档：

| 文档 | 用途 |
|---|---|
| `docs/xmuse/natural-groupchat-a2a-goal.md` | 当前愿景、最新状态、A2A/Ray/Clowder-AI 取舍和 forbidden claims |
| `docs/xmuse/natural-groupchat-a2a-behavior.md` | authority-first 行为规范、TDD/superpowers/GitHub 约束、patch/refactor 阈值 |
| `docs/xmuse/natural-groupchat-a2a-task-plan.md` | Phase 0-7 的实施任务、验收和停止条件 |
| `docs/xmuse/natural-groupchat-a2a-goal-prompt.md` | 可直接贴入 `/goal` 的简洁 prompt |
| `/home/iiyatu/projects/python/xmuse-m7-natural-groupchat-goal-design/docs/superpowers/specs/2026-06-26-natural-groupchat-a2a-production-goal-design.md` | 详细设计来源 |
| `/home/iiyatu/clowder-ai` | 自然群聊实现参考，不是 xmuse authority |

当前校准：

- `origin/main` 当前校准在 merge commit
  `8ae7600991371783658829900cda59ecdbed7a57`，对应 PR #273
  `docs: record sentinel backend alignment merge`。
- PR #242、#244、#245、#246、#247、#248、#249、#250、#251、#252、#253、#254、#255、#257、#258、#259、#260、#261、#262、#263、#264、#265、#266、#267、#268、#269、#270 均已合并，
  #271、#272、#273 均已合并，且各自 merge commit 的 main push CI 均为 success。
- PR #248 与 #250 是当前 goal 文档校准；PR #249 加固了 GitHub server
  truth exact-head check-run evidence；PR #251 暴露 MemoryOS sidecar 支撑上下文
  的只读 UX projection；PR #252 明确 A2A review verdict 后仍需 proposal
  approval authority 才能进入 dispatch；PR #254 让 proposal approval 响应只在
  durable dispatch queue entry 存在时暴露下一跳；PR #255 将 dispatch gate refs
  持久化给 MemoryOS/frontend/copilot 等只读消费者；PR #257 让 dispatch bridge
  把同一组 authority source refs 写入 execute-peer context/prompt/envelope，并让
  frontend/copilot 保持 execution evidence 与 authority refs 分离；PR #258 刷新当前
  goal 文档；PR #259 把 dispatch ack/evidence 留在 `chat_dispatch_queue`，避免提升为
  acceptance spine 的 lane execution proof；PR #260 刷新执行 proof 边界文档；
  PR #261 把 approved dispatch authority refs 写入 saved lane graph、
  `feature_lanes.json` projection、lane context bundle、normal execution prompt
  和 persistent execute context，并明确这些 refs 不是 lane execution proof；PR #262
  刷新当前 goal docs；PR #263 在可选 MemoryOS sidecar 中记录 approved dispatch
  handoff continuity，保留 queue/proposal/review/resolution/artifact refs，并在
  sidecar degraded 时继续以 `chat.db` dispatch queue 为 authority；PR #264 刷新当前
  goal docs；PR #265 让 frontend read-only UX projection 在
  `dispatch_queue.entries[]` 暴露 authority refs、authority boundary 和
  projection-only sidecar continuity contract；PR #266 让 copilot intake 接受
  `review_trigger_verdict:*` 作为 durable review verdict authority，同时保持
  `mcp_writeback:*` 和 legacy `chat_dispatch_queue#entry=*` 为 candidate input；
  PR #267 刷新当前 goal docs；PR #268 让 acceptance-gated short run 在
  final-action GitHub gate resolution 后把 `feature_lanes.json` 更新为终态
  read projection：accepted 显示为 `merged`，manual-gap blocked 显示为
  `blocked_for_input` + `blocked_reason`，并保留 durable authority refs；
  PR #269 刷新当前 goal docs；PR #270 将 synthetic acceptance-gated short-run
  lane projection 标记为 `integration_mode: noop`，避免 health 将其误报为
  普通 feature lane 的 dependent release 风险；PR #271 刷新当前 goal docs；
  PR #272 对齐 fullchain docs sentinel 的 peer/review/execute GOD backend；
  PR #273 记录 #272 的 merge/main-CI 事实。这些都是支撑链路，不是
  production-ready natural groupchat 证明。
- PR #243 (`codex/natural-groupchat-overnight-goal-docs`) 是较早的宽文档包，
  当前 `BEHIND` main；可作参考，但不是最新 current-goal 状态入口。
- Dirty historical worktree 和 archive 文档只能作为参考，不是 main capability。

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
```

This archive contains the old `codex-strengthening-handoff.md`,
`fullchain-runtime-*`, `production-closure-gap-ledger.md`,
`real-provider-soak-evidence-2026-06-21.md`, and
`walkthrough-maintenance-notes*.md` files.

Rules:

1. Do not treat archived evidence as proof for a new PR head.
2. Do not restart old L8-L11, overnight-readiness, or closure-ledger framing
   from the archive.
3. If an archived implementation detail is reused, cite it as reference and
   re-verify the current code path.

Old `docs/superpowers/specs/` and `docs/superpowers/plans/` remain historical
implementation records because tests and lane history may reference their
paths. They are not the current entrypoint.
