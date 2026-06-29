# xmuse 并行 Codex Session Prompts

这些 prompt 用于启动多个 Codex session。每个 session 必须在独立 worktree 或明确的
文件边界中运行。

## 共享阅读列表

每个 session 启动前必须先阅读:

```text
docs/xmuse/README.md
docs/xmuse/document-status.md
docs/xmuse/解耦开发协议.md
docs/xmuse/parallel-development-runbook.md
docs/xmuse/code-quality-and-archive-policy.md
```

Archived handoff files under `docs/xmuse/archive/2026-06-runtime-root-legacy/`
are historical reference only.

各 session prompt 的“必须阅读”只列额外模块上下文。若本 README 与单个 prompt 冲突，
以本 README 和《解耦开发协议》为准。

## 通用越界规则

如果无法在 allowed files 内完成任务:

```text
boundary-escalation:
  blocked_by: <missing contract/module/file>
  needed_from: <session owner>
  local_stub: <fake/stub/adapter used, if any>
  needs-S0-contract-review: true
```

不要自行扩大修改范围，不要临时改对方模块。能用 fake/stub 独立验证的部分继续推进；
无法验证的部分停止并交给 S0 集成处理。

## 共享完成标志协议

为了支持一次性启动所有 Codex sessions，所有 session 使用同一个 canonical flag 目录同步依赖:

```text
/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/
```

即使 session 运行在独立 worktree，也必须读写上述绝对路径，而不是当前 worktree 下的相对路径。
每个 session 只写自己的 flag 文件，不编辑其他 session 的 flag。

### Flag 文件

| Session | 完成标志 |
|---|---|
| S0 | `S0.contract.ready.json` |
| S1 | `S1.chat_tui.ready.json` |
| S2 | `S2.coordinator.ready.json` |
| S3 | `S3.blueprint.ready.json` |
| S4 | `S4.graph.ready.json` |
| S5 | `S5.execution.ready.json` |
| S6 | `S6.subagent.ready.json` |
| S7 | `S7.dashboard.ready.json` |
| S8 | `S8.adapters.ready.json` |
| S0 final | `S0.integration.ready.json` |

### Flag 内容

```json
{
  "session": "S3",
  "status": "ready",
  "updated_at": "2026-06-02T00:00:00Z",
  "branch_or_worktree": "<name>",
  "touched_files": [],
  "verification": [
    {"command": "pytest tests/xmuse/test_feature_plan.py -q", "result": "passed"}
  ],
  "contracts_produced": [],
  "boundary_escalations": []
}
```

### 原子写入

写 flag 时先写临时文件，再 `mv` 到目标路径:

```bash
mkdir -p /home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags
tmp=/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/SX.name.ready.json.tmp
dst=/home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/SX.name.ready.json
# write JSON to "$tmp"
mv "$tmp" "$dst"
```

### 依赖轮询

有依赖的 session 启动后先进入准备阶段: 阅读文档、检查 allowed files、整理本地实现计划。
正式修改生产代码前，每 10 分钟检查一次所需 flag。依赖未满足时不要抢改对方模块。

轮询命令示例:

```bash
while [ ! -f /home/iiyatu/projects/python/memoryOS/xmuse/work/parallel_session_flags/S0.contract.ready.json ]; do
  date -u '+waiting for S0 contract at %Y-%m-%dT%H:%M:%SZ'
  sleep 600
done
```

### 默认依赖

| Session | 正式执行前必须等待 |
|---|---|
| S0 | 无 |
| S1 | `S0.contract.ready.json` |
| S2 | `S0.contract.ready.json` |
| S3 | `S0.contract.ready.json` |
| S4 | `S0.contract.ready.json` |
| S5 | `S0.contract.ready.json`, `S2.coordinator.ready.json`, `S4.graph.ready.json`, `S6.subagent.ready.json` |
| S6 | `S0.contract.ready.json` |
| S7 | `S0.contract.ready.json` |
| S8 | `S0.contract.ready.json`, `S2.coordinator.ready.json`, `S3.blueprint.ready.json` |
| S0 final integration | `S1.chat_tui.ready.json`, `S2.coordinator.ready.json`, `S3.blueprint.ready.json`, `S4.graph.ready.json`, `S5.execution.ready.json`, `S6.subagent.ready.json`, `S7.dashboard.ready.json`, `S8.adapters.ready.json` |

启动顺序建议:

1. `S0-integration-contract.md`
2. `S1-chat-tui-read-layer.md`
3. `S3-blueprint-decomposition.md`
4. `S4-lane-graph-generation.md`
5. `S6-cli-subagent-skills.md`
6. `S7-dashboard-drilldown.md`
7. `S2-coordinator-core.md`
8. `S5-execution-scheduling.md`
9. `S8-ray-langgraph-adapters.md`

先跑 S0，再跑 Batch 1。S2/S5 放到 contract 稳定后。
