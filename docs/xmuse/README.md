# xmuse 文档入口

更新日期: 2026-06-10

本目录是 xmuse 当前阶段的文档入口。旧的 `docs/superpowers/specs/` 和
`docs/superpowers/plans/` 仍保留原路径，因为测试、lane graph 和历史记录会引用
这些路径；它们现在视为实现历史和方案档案，不再作为唯一的当前权威入口。

## 当前方向

xmuse 的当前 north-star 是:

```text
GOD groupchat deliberation
-> frozen blueprint
-> feature/lane/laneDAG
-> centralized execution/review
-> GitHub merge gate
-> REST-first MemoryOS
```

`docs/xmuse/mainline-contracts.md` 是当前主线合同入口。它明确:

- demo/legacy 路径只能作为 smoke、历史兼容或参考，不能绕过主线合同；
- blueprint freeze 是去中心化 GOD deliberation 与中心化 execution/review 的边界；
- graph-set / lane graph / review plane / GitHub checks / MemoryOS refs 才是对应阶段的权威，
  `feature_lanes.json`、cards、dashboard/TUI 读模型是投影或视图。

## 当前权威文档

| 文档 | 用途 |
|---|---|
| `docs/xmuse/mainline-contracts.md` | 当前产品主线合同：GOD 群聊、blueprint freeze、laneDAG、review/GitHub gate、REST-first MemoryOS |
| `docs/xmuse/deep-research-02-next-goal.md` | 第二轮深度研究转化目标，定义 #13-#19 的下一阶段任务 |
| `docs/xmuse/contract-smoke-gates.md` | #19 合同 smoke CI：无 secrets 的 lint、format、typecheck、主线合约测试和 SLO smoke |
| `docs/xmuse/github-review-merge-contract.md` | GitHub PR template、CODEOWNERS、required checks 和 merge-ready 合同 |
| `docs/xmuse/memoryos-governance-contract.md` | MemoryOS namespace、actor identity、memory layer、redaction、tombstone 和 MCP 写入边界 |
| `docs/xmuse/解耦开发协议.md` | 四层解耦边界、事件契约、数据权威和开发规则 |
| `docs/xmuse/walkthrough-maintenance-notes.md` | 逐步走读 xmuse 时维护的当前实现事实、进度和非生产级记录 |
| `docs/xmuse/walkthrough-maintenance-notes-v7.md` | 群聊层 runtime 生产级闭环线：真实长 session、provider binding、MCP writeback、latency gate |
| `docs/xmuse/codex-strengthening-handoff.md` | 给 `/goal` Codex session 的强化开发交接文档、优先级和硬 gate |
| `docs/xmuse/xmuse-production-strengthening-goal-prompt.md` | 可直接用于 `/goal` 的生产级强化 prompt |
| `docs/xmuse/deep-research-conversion-roadmap.md` | 将深度研究报告转为 M1-M6 路线图和 GitHub issue 结构 |
| `docs/xmuse/deep-research-execution-tasks.md` | 深度研究转化的全量执行任务清单，供短 goal prompt 引用 |
| `docs/xmuse/parallel-development-runbook.md` | 多个 Codex session 并行开发的分工、批次、接口包和合并规则 |
| `docs/xmuse/code-quality-and-archive-policy.md` | 代码复用、重写、隔离、测试和状态写入质量规则 |
| `docs/xmuse/memoryos-file-separation.md` | xmuse 与 MemoryOS 的文件、依赖和迁出边界 |
| `docs/xmuse/split-export-manifest.json` | xmuse 迁出到独立仓库时要复制/排除的文件清单 |
| `docs/xmuse/xmuse-package.pyproject.toml` | 独立 xmuse package 的 pyproject 模板 |
| `docs/xmuse/session-prompts/` | 可直接用于启动各模块 Codex session 的初始化 prompt |
| `docs/xmuse/outer-god-integration-goal.md` | S0-S8 完成后由 Outer GOD 执行的生产级统合验收 goal |
| `xmuse/HANDOFF.md` | 当前仓库、运行态、开发方向和注意事项交接 |
| `xmuse/CODEX_GOAL_HANDOFF.md` | 给后续 outer GOD / Codex goal 的自动执行上下文 |
| `xmuse/FRONTEND_API.md` | 当前前端/TUI 可依赖的 API 摘要 |
| `xmuse/FRONTEND_CONTEXT.md` | 前端/TUI 开发背景和边界 |

## 历史档案

| 路径 | 状态 |
|---|---|
| `docs/superpowers/specs/` | 历史 spec 和已执行蓝图，保留原路径 |
| `docs/superpowers/plans/` | 历史 implementation plans，保留原路径 |
| `docs/xmuse/archive/plans/` | 未被当前代码引用的 xmuse plan 草案归档 |
| `xmuse/history/` | 运行快照、历史归档、隔离产物，默认不提交 |
| `xmuse/work/` | 过程记录和临时生成器，默认不作为稳定 API |

## 并行开发入口

若需要同时启动多个 Codex session，先读:

```text
docs/xmuse/parallel-development-runbook.md
docs/xmuse/code-quality-and-archive-policy.md
docs/xmuse/session-prompts/README.md
```

推荐先启动 `S0-integration-contract.md`，冻结事件、artifact、fixture 和 allowed files，
再并行启动 Batch 1 的 S1/S3/S4/S6/S7。S2/S5 触碰 runner/state-machine，建议等
contract 稳定后再启动。

## 清理规则

1. 当前方向文档放在 `docs/xmuse/` 或 `xmuse/*.md` 的明确入口中。
2. 仍被测试、graph snapshot、handoff 引用的历史文档不移动，只在入口中降级为历史。
3. 运行时产物、日志、数据库、旧前端构建目录移动到 `xmuse/history/` 隔离。
4. `feature_lanes.json` 是兼容投影和 live queue，不是权威设计文档。
5. Ray、LangGraph、TUI、dashboard 之间通过协议和事件对接，避免互相直接依赖实现细节。
