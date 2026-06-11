# `/goal` Prompt: xmuse Production-Grade Strengthening

将下面内容作为 `/goal` 命令的目标 prompt 使用。

```text
你正在 /home/iiyatu/projects/python/xmuse 中强化 xmuse。自主执行，不要等待用户确认，除非遇到会破坏数据、跨仓库修改或需求矛盾的阻塞。

目标:
把 xmuse 往生产级但不冗余的多 coding-agent 编排平台推进。xmuse 的核心不是多开几个 CLI，而是把 Codex、Claude Code、OpenCode 等独立 coding agents 编排成可审计、可恢复、可并行、中心化执行的工程系统。

启动前必须阅读:
1. docs/xmuse/codex-strengthening-handoff.md
2. docs/xmuse/walkthrough-maintenance-notes.md
3. docs/xmuse/解耦开发协议.md
4. xmuse/HANDOFF.md
5. 当前任务相关源码和 tests/xmuse focused tests

必须先做的事实核对:
- 确认当前源码在 src/xmuse_core/、xmuse/、tests/xmuse/。
- 确认 pyproject.toml 的 pytest/ruff 配置。
- 用 rg 定位当前 feature graph、projection、orchestrator、review、Ray session、provider adapter 相关实现。
- 不要依据 MemoryOS 仓库中的旧 src/xmuse_core 进行实现判断。

架构硬约束:
- xmuse coordinator/state machine 是状态权威。
- Ray actor、LangGraph、A2A、Codex/Claude/OpenCode CLI 都不是状态权威。
- worker/reviewer 不直接写 durable execution state；它们返回 artifact/verdict/evidence，由 coordinator 转成状态转换。
- graph-set / feature graph / graph-native status store 是目标执行权威；feature_lanes.json 只能作为迁移期投影或兼容导出。
- peer agents、planner、reviewer、feature worker 必须按长 session 设计。
- oneshot CLI 只用于 lint/test/health check/小诊断/低风险可重试工具任务。
- 默认执行粒度要升到 feature graph: 一个 feature worker 长 session 推进一个 feature graph，lane DAG 是 worker 内部计划。
- reviewer 可判定 merge/rework/patch_forward/takeover/blocked，但 patch_forward 必须有强 gate。
- MemoryOS/xmuse memory 不替代 provider 原生 session resume。
- 不使用 codex --last 或等价 last-session 机制作为生产绑定策略；必须保存显式 provider session id。
- native runtime 不得直接删除；先降为 fallback，Ray parity gates 通过后再归档。
- 不把当前 Codex-first 能力描述成完整多 provider runtime。

优先实现方向:
1. 优先补稳定契约，而不是先改 runtime 大结构:
   - FeatureEvidenceBundle
   - ReviewVerdict
   - ReworkPacket
   - provider session binding record
   - feature graph ready/status identity
2. 为契约增加 Pydantic schema、golden fixtures、focused tests。
3. 将 reviewer/worker 的自然语言交接逐步收束为 structured evidence/artifact/verdict。
4. 若触及 runtime，抽象 LongSessionManager / AgentRuntimeAdapter，保持 Ray 默认、native fallback。
5. 若触及 execution，避免继续扩大 feature_lanes.json 权威；新增能力应朝 graph-native ready-set/status store 迁移。

阶段执行约束（硬规则）:
- 每个阶段必须使用统一脚本:
  ```bash
  uv run python scripts/goal_stage_runner.py \
    --stage-manifest /abs/path/to/stage-manifest.json \
    --engine <codex|opencode|auto> \
    --repo-root /home/iiyatu/projects/python/xmuse \
    --output .goal-runs/<stage_id>/result.json
  ```
- 每阶段必须先等待 result 文件写出，且 `status` 为 `ok` 才能进入下一阶段。
- `retry`: 同阶段重试一次执行，使用同一 manifest。
- `blocked`: 立即停止并上报阻塞原因与 owner。
- `--dry-run`: 只允许预览 prompt/command，不得作为阶段通过证据。
- 阶段必须产出至少:
  - `result.json`
  - `result.json.prompt.txt`
  - `result.json.manifest.jsonl`
  - `result.json.evidence/engine_output.txt`（执行器原始输出）

Reviewer 行为 gate:
- merge: 必须有 acceptance coverage、diff scope、verification、merge guard 证据。
- rework: 必须生成结构化 ReworkPacket，发回同一个 feature worker session 或可恢复 session。
- patch_forward: 仅允许边缘、小范围、低风险问题；必须限制 scope，记录为什么不打回 worker，重跑 focused gates。
- takeover: 仅在 worker 不可恢复、反复失败、上下文丢失或风险升级时触发。
- blocked: 必须记录缺失输入、阻塞原因和下一步 owner。

A2A 约束:
- A2A 可以作为 xmuse 与独立 agent runtime 的边界协议候选。
- A2A task/artifact/contextId 可映射 feature graph、evidence bundle、review verdict。
- A2A 不拥有 graph-set、ready-set、merge guard、worktree 写入、状态转换或 provider session binding。
- 只有 schema 和 runtime 边界稳定后才实现 A2A adapter；先做低风险 external reviewer/worker pilot。

实现方法:
- 小步提交，不做无关重构。
- 每个改动先写或更新 focused tests。
- 保持现有 API/fixtures 兼容，除非当前任务明确要求迁移。
- 遇到 dirty worktree 时只处理与本任务相关文件，不 revert 用户或其他 agent 的变更。
- 所有运行态文件、日志、数据库、历史快照不得作为稳定 API 扩张。

验收 gate:
- uv run ruff check .
- uv run pytest -q <focused tests>
- 如果改动影响平台核心，再运行 uv run pytest -q tests/xmuse 中相关目录或全量 tests/xmuse。
- 新增/修改的 schema 必须有 fixture/golden test。
- 新增/修改的状态转换必须有 guard/idempotency test。
- 新增/修改的 Ray/provider session 行为必须有恢复/失败测试。
- 新增/修改的 reviewer 行为必须覆盖 merge/rework/patch_forward 至少相关路径。
- 若仍依赖 feature_lanes.json，必须证明兼容投影不回归。

交付要求:
- 修改代码和测试。
- 更新 docs/xmuse/codex-strengthening-handoff.md 或 xmuse/HANDOFF.md，记录完成项、验证命令、剩余风险。
- 最终回答只汇报: 做了什么、验证了什么、未完成/风险是什么、下一步建议。
```
