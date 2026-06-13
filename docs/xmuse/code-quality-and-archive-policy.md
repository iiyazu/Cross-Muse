# xmuse 代码质量与归档策略

更新日期: 2026-06-13

## 目标

本策略约束并行 Codex sessions 的代码质量。核心目标是保持 xmuse 主库干净、模块边界清楚、
测试可独立运行，并避免为了短期跑通而堆叠历史实现。

## 复用优先级

实现新能力前必须按顺序检查:

1. 是否已有 service/model/store 可复用。
2. 是否已有测试覆盖同类行为。
3. 是否已有 helper 可以扩展。
4. 是否旧代码与新协议冲突。

复用优先，但不是无条件复用。

### 应复用

- Pydantic/domain models。
- Store 和 artifact writer。
- `LaneProjectionSyncer`、`LaneStateMachine`、state guard。
- `ProviderPolicyService` 和 provider adapter 抽象。
- Chat store、inbox、participant store。
- Dashboard/read model helper。
- 已有 prompt builder 和 evidence bundle helper。

### 可重写

满足任一条件时可以果断新实现:

- 旧代码职责混杂，无法按协议层独立测试。
- 旧代码把 dashboard/TUI/workflow/runner 硬耦合。
- 旧代码直接手写 `feature_lanes.json`，绕过 state machine。
- 旧代码依赖已废弃的 browser frontend 或 master_loop 路径。
- 旧代码行为不可复现、无测试、无清晰调用者。
- 同一功能或 runtime path 已经两次同类失败，继续 patch 只会扩大耦合。
- 当前生产主线依赖 demo 级实现，且 demo path 无法满足合同、权限、证据或测试边界。

重写必须给出理由，并保留必要迁移证据。

### 直接重构触发条件

以下情况不再继续做局部补丁，应直接重构或替换失败边界:

- 同一测试簇、stage、功能或 runtime path 两次出现同类失败；下一步必须是有边界的
  root-cause/refactor 或 replacement work，而不是第三次同路径 patch。
- goal-stage harness 或 overnight supervisor 标记 `refactor_required`。
- demo/local/fake 实现被生产路径依赖，且无法通过小改动满足 production contract。
- 为了修一个问题需要同时改动多个无关层，说明当前边界已经失效。
- 修复需要 TUI/dashboard/read model 直接写内部状态、直接写 `feature_lanes.json`
  或绕过 durable contract。

直接重构要求:

- 先写明失败边界、替代边界、迁移方式和保留的兼容面。
- 第三次同边界执行必须等上述重构/替换说明和 focused tests 就绪后再开始。
- 只重构与失败边界直接相关的文件；无关清理另开任务。
- 用 focused tests 证明新边界行为，再删除或隔离 demo/legacy path。
- 若旧 path 仍有调用者，放入 adapter/legacy 过渡并写清删除条件。
- 不允许通过改 proof label、UI 文案或 release evidence 解释来掩盖 demo 级实现。

## 隔离规则

不再作为当前主路径的内容应隔离，而不是散落在主目录。

| 类型 | 处理 |
|---|---|
| runtime logs/db/state | 移到 `xmuse/history/cleanup_*` 或保持 ignored |
| browser frontend 历史实现 | `xmuse/archive/frontend_*` |
| demo script | `xmuse/archive/demo_*` 或 `docs/xmuse/archive/` |
| 仍被测试引用的历史 spec/plan | 保留原路径，只在索引中标为历史 |
| 旧代码仍有调用者 | 移到 `xmuse/legacy/` 或保留原路径并包 adapter，直到替换完成 |
| 旧代码无调用者但有参考价值 | 移到 `xmuse/archive/` 或 `docs/xmuse/archive/` |

路径原则:

- `xmuse/history/cleanup_*`: 只用于 runtime 快照、logs、db、一次性清理记录，不作为代码组织路径。
- `xmuse/archive/`: 用于无调用者、非当前主路径的代码、脚本、旧前端实现。
- `xmuse/legacy/`: 用于仍有调用者但已有替代方案的过渡代码，必须有 adapter 和删除条件。
- `docs/xmuse/archive/`: 用于历史 spec、plan、prompt、运行记录。

禁止:

- 直接删除不确定用途的文件。
- 使用 `git reset --hard` 清理。
- 把运行态 telemetry 写回 tracked design/source。
- 在新主路径旁边保留两个同名 competing implementation。

## 模块化要求

每个新模块必须回答:

```text
它做什么？
谁调用它？
它读哪些 artifact/event？
它写哪些 artifact/event？
如何 fake/stub 测试？
它不能做什么？
```

文件组织要求:

- 跨层契约放在 models/contracts/schema 层。
- 运行 orchestration 放 coordinator/service 层。
- I/O 与 store 单独封装。
- Prompt builder 与业务状态机分开。
- Dashboard/TUI 只读转换逻辑不要反向依赖 runner。

## 测试要求

每个 session 至少需要一种验证:

- unit test: 模块纯逻辑。
- contract test: schema/event/artifact/read envelope。
- fake integration test: fake store / fake CLI / fake reviewer。
- smoke test: 真实 CLI/Ray/LangGraph 只在必要时运行。

测试命名建议:

```text
tests/test_xmuse_<module>_contract.py
tests/test_xmuse_<module>_service.py
tests/test_xmuse_<module>_integration.py
```

## 状态写入规则

当前 Stage 0:

- `feature_lanes.json` 是执行事实源。
- 状态写入必须通过 `LaneStateMachine` 或明确封装的 state-machine service。
- `LaneProjectionSyncer` 负责投影读写和 sanitization。
- subagent、dashboard、TUI、LangGraph node、Ray child actor 不直接写 lane status。

## Provider / CLI 规则

- CLI worker 是受控工具，不是独立自治 GOD。
- coordinator 给 CLI worker 提供完整 context bundle。
- worker 输出必须是结构化结果: summary、files changed、tests、blocker、evidence refs。
- worker 失败必须返回 failure class，而不是静默重试。
- 模型和 provider 选择走 provider policy，不硬编码在业务逻辑里。

## 越界升级规则

若 session 无法在 allowed files 内完成任务:

1. 不自行扩大修改范围。
2. 优先使用本模块 fake/stub 或 optional adapter 继续推进可验证部分。
3. 在输出中写明 `boundary-escalation`，包含缺失接口、被阻塞原因、建议 owner。
4. 同时标记 `needs-S0-contract-review`，由 S0 决定 contract 或模块边界是否调整。
5. 不允许为了绕过边界把跨层逻辑临时堆进当前文件。

## 合并前检查

每个 session 合并前必须检查:

```bash
git status --short
rg -n "TODO|TBD|pass #|NotImplemented" <touched files>
```

并按改动范围运行 focused tests。没有运行的测试不能在汇报中声称通过。
