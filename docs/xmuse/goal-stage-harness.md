# Goal Stage Harness

Purpose:

- 把每个 `/goal` 阶段任务从“口头约束”变成可执行的、有可追溯产物的流程。
- 强制通过脚本产出 `result.json` 和 `manifest.jsonl`，避免阶段越权越写。

## 固化规则

- 每个阶段必须有 stage manifest（JSON）。
- 阶段前置必须先调用脚本：

```bash
uv run python scripts/goal_stage_runner.py \
  --stage-manifest /abs/path/to/stage-manifest.json \
  --engine <codex|opencode|auto> \
  --repo-root /home/iiyatu/projects/python/xmuse \
  --output /tmp/goal-runs/<stage-id>/result.json
```

- 规则：未生成 `result.json` 不得进入下一阶段。
- 规则：`--dry-run` 只用于预览 prompt/command，生成的 `result.json` 不得作为阶段通过证据。
- `status` 约束：
  - `ok`：可推进下一阶段。
  - `retry`：先由同一阶段做有限收敛重试（同一脚本再次运行），次数受 manifest `max_retries` 限制。
  - `blocked`：阻塞并上报，等待人工处理。
- 当 goal-stage `retry` 结果被导入 overnight supervisor 时，重复导入同一阶段的
  `retry` 结果会进入 supervisor 的 repeated-failure policy；第三次同类 retry
  import 会标记 `refactor_required`，要求先重构失败边界再重试。
- 同一功能、stage、测试簇或 runtime path 出现两次同类失败后，后续 manifest
  必须把下一步声明为 root-cause/refactor work，而不是继续同路径修补。
- 一旦出现 `refactor_required`，不得发起第四次同类重试；必须先产出重构说明、
  失败边界、迁移策略和 focused validation。
- demo 级实现不得作为生产 stage 的通过证据。若 stage 发现生产主线依赖 demo
  path，结果应标记为 `retry` 或 `blocked`，并把 next_action 写成替换为
  contract-backed production path。
- 脚本会同时输出：
  - `result.json`（阶段产物）
  - `<output-path>.manifest.jsonl`（追加审计日志，例如 `result.json.manifest.jsonl`）
  - `<output-path>.prompt.txt`（本次给执行器的标准化提示，例如 `result.json.prompt.txt`）
  - `<output-path>.evidence/engine_output.txt`（引擎原始输出，例如 `result.json.evidence/engine_output.txt`）
- OpenCode engine 的默认模型 ref 必须是 `opencode-go/deepseek-v4-flash`，并且
  CLI 必须额外传 `--variant max`；不能把 `max` 拼进 model id，也不能退回旧
  `deepseek/<model>` package。
- Codex 开发 xmuse 时如何把低风险高工作量阶段委派给 OpenCode，统一遵循
  `docs/xmuse/development-goal-worker-delegation-policy.md`；后续 `/goal` prompt
  只需引用该文档，不需要重复展开行为规范。

## Manifest schema（最小字段）

```json
{
  "stage_id": "S1",
  "objective": "...",
  "scope": ["tests/xmuse/...", "src/..."],
  "acceptance_contracts": ["contract A", "contract B"],
  "owner": "cross-muse",
  "max_retries": 2,
  "risk": "medium",
  "constraints": ["do-not-write-runtime-state"],
  "escalation_triggers": ["provider unavailable", "policy miss"],
  "prompt": "Optional additional task-specific prompt fragment.",
  "engine": "opencode"
}
```

`engine` 是可选，未提供时使用 `/goal` 默认 `codex`。

## 为什么要这样约束

- 防止阶段内只靠自然语言承诺，而无可回放证据。
- 避免重复触发相同阶段时缺少统一入口。
- 让 `/goal` 和 `goal` 路径有一致的失败分类和复用回放行为。
