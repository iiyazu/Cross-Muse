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

Codex model fallback 默认启用：当 runner 通过 `codex exec -m gpt-5.5`
执行阶段且输出匹配 quota/usage/weekly limit 等额度耗尽信号时，会自动用
`gpt-5.3-codex-spark` 重跑同一阶段 prompt。无需在常规 stage 命令中重复传
fallback 参数。

如需显式覆盖或关闭:

```bash
uv run python scripts/goal_stage_runner.py \
  --stage-manifest /abs/path/to/stage-manifest.json \
  --engine codex \
  --fallback-model gpt-5.3-codex-spark \
  --fallback-on quota_exhausted \
  --repo-root /home/iiyatu/projects/python/xmuse \
  --output /tmp/goal-runs/<stage-id>/result.json
```

关闭 fallback 时使用 `--fallback-on none`。注意：fallback 只作用于通过
`scripts/goal_stage_runner.py` 启动的阶段子进程；当前外层 `/goal` 会话如果耗尽，
仍需要人工在 Codex UI/CLI 中选择可用模型后继续。

- 规则：未生成 `result.json` 不得进入下一阶段。
- 规则：`--dry-run` 只用于预览 prompt/command，生成的 `result.json` 不得作为阶段通过证据。
- `status` 约束：
  - `ok`：可推进下一阶段。
  - `retry`：先由同一阶段做有限收敛重试（同一脚本再次运行），次数受 manifest `max_retries` 限制。
  - `blocked`：阻塞并上报，等待人工处理。
- 阶段执行必须遵循 RIGR-V：Read → Invariant → Green-by-fix →
  Refactor → Verify。阶段 prompt/result 应能追溯 task understanding、相关
  code path、已有覆盖、风险面、不变量、验证命令和剩余风险。
- 阶段执行还必须遵循 `docs/xmuse/goal-behavior-contract.md` 的 dependency-first
  closure 流程。每个 stage 必须先声明 target L 层、upstream blockers、authority
  owner、proof level、manual gaps 和 forbidden claims，再允许编码。
- 测试不是架构来源。stage 不得通过 broad speculative tests、fixture-only
  artifacts、TUI/read model 扩展或 release-pack 字段来声称 upstream closure。
- 如果 stage 只产生 `contract_proof` 或 `manual_gap`，result 必须明确保留对应
  forbidden claims；不得把它过读为 live/provider/server proof。
- Targeted tests 只在 bug fix、public/API contract、可判定行为变更、
  parser/serializer 等场景强制。docs/config/pure refactor/performance/
  architecture migration 不得为了满足 red-first 形式而添加低价值测试。
- 新 failing test 只有在测试外部行为、public contract、真实 bug 或低层库契约时
  才能作为 stage evidence；不得断言临时变量、特判样例、mock 掉真实业务路径或只
  证明“不会抛异常”。
- 单 writer，多 verifier：主 Codex 是最终 production-code writer；explorer、
  test-designer、reviewer、docs/api subagent 默认只读或 tests-only。worker 自报
  passing 不构成 stage 通过证据，必须由 Codex 独立审查 diff 和风险面。
- 当 goal-stage `retry` 结果被导入 overnight supervisor 时，重复导入同一阶段的
  `retry` 结果会进入 supervisor 的 repeated-failure policy；第三次同类 retry
  import 会标记 `refactor_required`，要求先重构失败边界再重试。
- 同一功能、stage、测试簇或 runtime path 出现两次同类失败后，后续 manifest
  必须把下一步声明为 root-cause/refactor 或 replacement work，而不是继续同路径
  修补。第三次同边界执行只有在重构/替换 artifact 已产生后才允许。
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
- 触发 Codex model fallback 时，脚本还会输出：
  - `<output-path>.evidence/engine_output.primary.txt`
  - `<output-path>.evidence/engine_output.fallback.txt`
  - `result.json` 中的 `primary_model`、`fallback_model`、
    `fallback_triggered`、`fallback_reason`、`primary_returncode` 和
    `fallback_returncode`
- Codex model fallback 只解决执行连续性。它不升级 `proof_level`，不改变
  forbidden claims，不允许提交/推送/改 PR，也不把 fallback 输出变成 review truth。
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
  "objective": "Add durable selected-GOD binding resolver and fail-closed evidence",
  "scope": ["tests/xmuse/test_god_binding_resolver.py", "src/xmuse_core/providers/"],
  "acceptance_contracts": ["contract A", "contract B"],
  "owner": "cross-muse",
  "max_retries": 2,
  "risk": "medium",
  "constraints": ["do-not-write-runtime-state"],
  "closure": {
    "target_layers": ["L2"],
    "upstream_dependencies": ["L1"],
    "authority_owner": ["ProviderAccount", "GodProfile", "RoomSelectedGodBinding"],
    "allowed_writers": ["explicit registry/operator contract"],
    "forbidden_authorities": ["provider inventory", "env scan", "TUI temporary selection", "raw CLI string"],
    "proof_level": "contract_proof",
    "manual_gaps": [],
    "forbidden_claims": ["peer_god_live_proof", "provider_invocation_live_proof"]
  },
  "task_understanding": {
    "user_visible_behavior": "Operator-selected GOD bindings become durable speaker identity authority",
    "existing_code_path": ["src/xmuse_core/providers/"],
    "existing_tests": ["tests/xmuse/test_provider_inventory.py"],
    "risk_surface": ["provider inventory could be overread as peer-GOD identity"]
  },
  "invariants": {
    "behavior": ["existing valid behavior remains unchanged"],
    "architecture": ["do not bypass contract boundaries"]
  },
  "verification": {
    "targeted_tests_required": true,
    "red_required": true,
    "red_evidence": "behavior/API/bug contract proven when red-first is appropriate",
    "commands": ["uv run pytest tests/xmuse/test_foo.py -q"],
    "review_questions": [
      "What real requirement did any new failing test prove, if red-first was appropriate?",
      "Could the implementation be fitting only the test example?",
      "Were any tests modified, deleted, weakened, skipped, or xfailed?",
      "Was the real path under test mocked away?",
      "What evidence besides green tests shows the behavior is correct?",
      "Did this change close upstream authority or only downstream projection?",
      "Did any proof-level claim exceed the available durable/runtime/server evidence?"
    ]
  },
  "evidence_summary": {
    "target_layers": ["L2"],
    "proof_level": "contract_proof",
    "authority_objects": ["ProviderAccount", "GodProfile", "RoomSelectedGodBinding"],
    "runtime_path_touched": true,
    "projection_only": false,
    "manual_gaps": [],
    "forbidden_claims": ["peer_god_live_proof"]
  },
  "escalation_triggers": ["provider unavailable", "policy miss"],
  "prompt": "Optional additional task-specific prompt fragment.",
  "engine": "opencode"
}
```

`engine`、`closure`、`task_understanding`、`invariants`、`verification` 和
`evidence_summary` 是可选字段；缺省时执行器仍必须在 prompt/result 中记录同等
信息。未提供 `engine` 时使用 `/goal` 默认 `codex`。

## 为什么要这样约束

- 防止阶段内只靠自然语言承诺，而无可回放证据。
- 避免重复触发相同阶段时缺少统一入口。
- 让 `/goal` 和 `goal` 路径有一致的失败分类和复用回放行为。
