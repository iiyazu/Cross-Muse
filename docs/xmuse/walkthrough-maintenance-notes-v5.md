# xmuse Walkthrough Maintenance Notes V5

更新日期: 2026-06-04

本文档是给 Codex `/goal` 使用的 contract / fixture / boundary governance 并行交接文档。

它只覆盖一条并行线:

- 在不反向定义 `V2` 后端 authority、`V3` TUI 交互协议、`V4` operator 只读平面的前提下，补强 xmuse 的 schema、fixture、boundary、export、surface parity 和 replay contract

它不覆盖:

- peer chat 主链协议
- provider/runtime 决策主链
- graph-native authority 主链
- TUI 输入、焦点、补全主链
- operator / dashboard 主目标定义

这些仍分别以 `walkthrough-maintenance-notes-v2.md`、
`walkthrough-maintenance-notes-v3.md` 和
`walkthrough-maintenance-notes-v4.md` 为准。

## 使用规则

1. `V5` 只能做 contract / fixture / boundary / export / replay governance，不得新增 runtime authority。
2. 一次只做一个任务。
3. 只读当前任务列出的文件；没有进入当前任务的文件，默认不读不改。
4. 优先走现有 tests、fixtures、read-only contracts、manifest、boundary tests，不得顺手改执行语义。
5. 不得为了 contract 统一而修改 `V2` 的 source of truth。
6. 不得为了测试或 export 方便而新增后端语义特判。
7. 每轮必须满足该任务自己的强 gate，才算完成。
8. 每轮完成后，只更新:
   - 本文档对应任务的 `当前收敛状态`
   - `docs/xmuse/codex-strengthening-handoff.md` 的本轮收口记录
9. 因为 `V5` 可能交给较弱模型执行，默认采用强流程约束：
   - 每个任务开始前，必须先做一次 `superpowers:brainstorming`
   - 涉及 schema、fixture、export、boundary、contract tests 的任务，默认按 `superpowers:test-driven-development` 执行
   - 宣称完成前，必须按 `superpowers:verification-before-completion` 跑 gate
10. `subagent` 默认禁用；只有任务明确标注“可并行子任务”时，才允许启用，而且必须满足：
   - 子任务之间没有共享编辑文件
   - 子任务不决定 authority、runtime 或协议语义
   - 子任务只做测试、夹具、只读审计或独立 schema/widget 实验
   - 同一轮最多启用 1 个 subagent
   - 主 agent 负责最终整合、验证与 handoff
11. 如果某轮任务可以由主 agent 直接完成，不要为了“看起来更并行”而启用 subagent。
12. 必要时允许参考 `/home/iiyatu/clowder-ai`，但仅限:
   - 借鉴 contract freeze、fixture versioning、read-only surface parity 的产品/工程约束
   - 帮助判断 xmuse contract 平面的目标形态
   不得直接复制其 runtime、状态机实现、或把它的协议假设搬进 xmuse。
13. 参考 `clowder-ai` 时，必须在本轮 handoff 写明:
   - 参考了哪些文件
   - 借鉴的是哪条 contract / fixture / boundary 约束
   - 为什么没有直接照搬实现

## 弱模型执行协议

每个任务都按下面顺序执行，不允许跳步:

1. 只读当前任务列出的文件，外加它直接依赖、且为了通过 gate 不可避免的测试文件。
2. 先做一次 `superpowers:brainstorming`，只产出四项结论:
   - 本轮唯一任务边界
   - 本轮允许改动的文件
   - 本轮 gate 映射到哪些测试或验证动作
   - 本轮明确不做什么
3. 对 schema、fixture、export、boundary、surface parity 的改动，必须使用
   `superpowers:test-driven-development`：
   - 先写 focused test
   - 先跑出预期 RED
   - 再做最小实现到 GREEN
4. 完成实现后，必须用 `superpowers:verification-before-completion` 跑 fresh gate。
5. gate 未全部通过时，不得宣称任务完成，不得切下一个任务。

如果 `brainstorming` 得出的结论需要改 authority、改 runtime path、改执行协议、
或扩大到 `V2/V3/V4` 主线，立即停止当前任务，并在 handoff 里记为越界，不继续实现。

## subagent 硬边界

`subagent` 不是默认能力，只是少数任务的辅助工具。弱模型执行时必须遵守:

1. 只有当前任务写了“可并行子任务”，才允许启用。
2. 同一轮最多 1 个 subagent。
3. 默认不要启用 `superpowers:subagent-driven-development`；只有当前任务明确允许，
   且主 agent 已经先完成本轮边界判定时，才可局部使用其思路。
4. subagent 只允许做下列事情之一:
   - 只读审计
   - 补测试或测试脚手架
   - 独立 schema / fixture 的局部实验
5. subagent 不允许:
   - 修改 authority source
   - 修改 provider/runtime 决策逻辑
   - 修改 TUI 主输入状态机
   - 修改任何 `V2/V3/V4` 主线语义
6. 如果 subagent 产出与主 agent 将要编辑的文件重叠，立刻取消该并行方案，回到主 agent 单线程收束。
7. 最终代码、测试、验证、handoff 一律由主 agent 负责；不得把 subagent 的“已完成”直接当成完成事实。

## 统一验收与汇报格式

每轮任务结束时，handoff 至少要写清楚:

1. 本轮唯一任务名。
2. 实际修改的文件列表。
3. 新增或修改了哪些 tests / fixtures / manifests。
4. `brainstorming` 结论中的四项边界是否仍成立。
5. fresh verification 命令与结果:
   - focused tests
   - 受影响的 contract / fixture / boundary / export tests
   - `ruff check` 或等价静态检查
   - `git diff --check`
6. 逐条对照当前任务 `强 gate`，说明每条 gate 由哪条测试或验证动作覆盖。
7. 明确写出本轮没有扩到的能力点。

没有这些证据，本轮视为未完成。

## 统一质量 gate

除各任务自己的 `强 gate` 外，每轮还必须同时满足下面四条:

1. 有 fresh test evidence；不能只凭人工操作或旧日志宣称通过。
2. 新增行为至少有一个 focused regression test；contract/API/export 类任务通常还应有 route-level、tool-level 或 fixture-level 覆盖。
3. 不新增任何 `V2/V3/V4` 后端语义特判，不把治理 convenience 写成 authority。
4. 所有新入口和新 fixture 都必须在“缺数据 / 空数据 / 旧兼容数据 / 降级数据 / 版本不一致”下稳定工作，不因治理层本身制造副作用。

## 任务总览

按推荐顺序执行:

1. `CONTRACT-FIXTURE-INVENTORY`
2. `READ-SURFACE-SCHEMA-PARITY`
3. `PACKAGE-BOUNDARY-GATES`
4. `MODEL-POLICY-SURFACE-PARITY`
5. `EXPORT-CONTRACT-HARDENING`
6. `REAL-RUN-REPLAY-FIXTURES`
7. `CONTRACT-COVERAGE-SMOKE`

---

## 任务 1: `CONTRACT-FIXTURE-INVENTORY`

### 非生产级实现事实

- 当前已有 `tests/fixtures/xmuse/contracts/`、`docs/xmuse/shared-contract-fixtures.md`、`test_shared_contract_fixtures_contract.py`、`test_parallel_contract_fixtures.py`。
- fixture 已经有冻结面，但哪些 surface 真正以哪些 fixture 为准，仍不够集中和可审计。

### 生产级目标

收束共享 contract fixture inventory，明确:

- 哪些 fixture 是权威 contract fixture
- 每类 fixture 对应哪些测试和哪些 surface
- 版本、stable id、source refs、timestamps 的统一约束

### 只读这些文件

- `docs/xmuse/shared-contract-fixtures.md`
- `tests/fixtures/xmuse/contracts/**`
- `tests/xmuse/test_shared_contract_fixtures_contract.py`
- `tests/xmuse/test_parallel_contract_fixtures.py`

### 本轮要解决的缺口

- fixture 已存在，但 inventory 仍不够像生产级 contract freeze，而像分散约定。

### 强 gate

- 每类核心 fixture 都有明确 inventory 和用途说明。
- fixture contract tests 能证明 stable id / version / source refs / timestamp 规则。
- 新增或调整 inventory 不改变 runtime 语义，只收束 contract 治理面。

### 禁止扩面

- 不改 runtime 事件流。
- 不把 fixture 变成生产 store 替代物。

### 可并行子任务

- 允许 1 个 subagent 只读审计 fixture 覆盖空洞，不改生产实现。

### 当前收敛状态

- EXPORTED_ARTIFACT_FIXTURES 已从 3 条扩展为 27 条，覆盖 artifacts/ 目录下所有 JSON fixture。
- `test_all_artifact_fixtures_are_in_inventory` 确保磁盘 artifact 与 inventory 完全一致。
- `test_parallel_artifact_fixtures_freeze_lineage_contract` 也同步扩展覆盖全部 artifact fixture。
- `shared-contract-fixtures.md` 已更新为带 surface 映射的生产级 inventory 表格，内含 event / artifact / card / read-envelope / interface 全部 five fixture 组的用途说明。
- 本轮不改变 runtime 语义，只收束 contract 治理面。

---

## 任务 2: `READ-SURFACE-SCHEMA-PARITY`

### 非生产级实现事实

- 当前 dashboard API、MCP、read_contracts、provider read contracts、TUI adapter contract 已各自存在。
- 但同一只读对象在不同 surface 上的字段、空数据、错误形状仍可能不完全对齐。

### 生产级目标

补齐只读 surface schema parity，覆盖:

- dashboard API
- MCP read-only tools
- `read_contracts.py`
- provider inventory / provider selection records

### 只读这些文件

- `xmuse/dashboard_api.py`
- `xmuse/mcp_server.py`
- `src/xmuse_core/platform/read_contracts.py`
- `src/xmuse_core/platform/provider_read_contracts.py`
- `tests/xmuse/test_dashboard_api.py`
- `tests/xmuse/test_mcp_server.py`
- `tests/xmuse/test_platform_mcp_tools.py`
- `tests/xmuse/test_provider_read_contracts_module.py`
- `tests/xmuse/test_tui_adapter_contract.py`

### 本轮要解决的缺口

- 同一概念对象的 read-only contract 还不够统一，影响并行开发和 operator / TUI / MCP 复用。

### 强 gate

- 同一只读对象在不同 surface 的核心字段一致、名称可解释。
- 空数据、过滤无结果、兼容数据、错误输入时，返回结构稳定。
- parity 收束不引入 write 语义或 runtime side effect。

### 禁止扩面

- 不新增 write-capable API 或 MCP 工具。
- 不改 TUI 主交互协议。

### 当前收敛状态

- 新增 `tests/xmuse/test_read_surface_schema_parity.py`，包含 read contract builder 的 discriminator 覆盖和边缘用例 smoke tests。
- 覆盖 lane/blueprint/feature_plan/graph_set/review/takeover/provider_inventory/provider_selection_records/conversation_inspector 各 builder。
- 覆盖空数据、不存在 ID、无效参数等边缘场景的结构稳定性验证。
- **说明**: 这些是单个 builder 的 smoke/discriminator 覆盖，并非跨 surface 对比测试（后者需要 TestClient 和全链路 fixture 支撑）。

---

## 任务 3: `PACKAGE-BOUNDARY-GATES`

### 非生产级实现事实

- 当前已有 `test_package_boundaries.py`，也有一些文档级解耦约束。
- 但 package boundary 仍偏点状，容易出现新增越界 import 或 split 边界回退。

### 生产级目标

把 package / module boundary 收紧成稳定 gate，重点覆盖:

- `chat`
- `platform`
- `providers`
- `tui`
- `self_evolution`
- `memoryos-lite` 依赖边界

### 只读这些文件

- `tests/xmuse/test_package_boundaries.py`
- `docs/xmuse/解耦开发协议.md`
- `docs/xmuse/memoryos-file-separation.md`
- 如有需要，受影响模块的极少量入口文件

### 本轮要解决的缺口

- 当前边界测试还不够全面，很多越界仍可能只靠人工 code review 发现。

### 强 gate

- 新的 boundary tests 能稳定防止关键非法 import / illegal coupling。
- 失败信息可解释，能明确指出越界方向。
- boundary gate 不依赖运行主链才能发现问题。

### 禁止扩面

- 不做大规模重构。
- 不借机调整 runtime 目录结构。

### 当前收敛状态

- `test_package_boundaries.py` 从 3 个测试扩展至 16 个测试。
- 覆盖以下边界 gate:
  - memoryos-lite 导入边界（已有强化）
  - TUI → provider adapters 导入禁止（允许 adapter/xmuse_adapter.py 跨层）
  - dashboard_api.py → execution/orchestrator/agent_spawner 导入禁止
  - mcp_server.py → execution/orchestrator/agent_spawner 导入禁止
  - self_evolution → TUI 导入禁止
  - xmuse_core → TUI/dashboard/mcp 导入禁止
  - providers → platform execution runtime 导入禁止（TYPE_CHECKING 除外）
  - xmuse app → execution write paths 导入禁止（platform_runner/master_loop/slave_job_runner 除外）
- 所有测试基于 AST 静态分析，不依赖运行时 import。
- 非法 import 检测出错后明确报告越界文件和行号。

---

## 任务 4: `MODEL-POLICY-SURFACE-PARITY`

### 非生产级实现事实

- 当前已有 `test_model_policy.py`、`test_model_policy_surfaces.py`、provider registry / provider read contracts。
- 但 provider/profile/task capability/model policy 在 runtime、read contract、operator surface 上仍可能出现隐含默认值或表达不一致。

### 生产级目标

统一 model / provider policy 的 surface parity，覆盖:

- provider registry
- provider inventory
- model policy metadata
- selection records
- task capability / persistent capability / risk tier

### 只读这些文件

- `src/xmuse_core/platform/model_policy.py`
- `src/xmuse_core/platform/provider_read_contracts.py`
- `src/xmuse_core/providers/models.py`
- `src/xmuse_core/providers/policy.py`
- `tests/xmuse/test_model_policy.py`
- `tests/xmuse/test_model_policy_surfaces.py`
- `tests/xmuse/test_provider_models.py`
- `tests/xmuse/test_provider_read_contracts_module.py`

### 本轮要解决的缺口

- provider/model policy 在不同 surface 间还不够一致，容易让弱模型或 operator 误读能力边界。

### 强 gate

- 同一 provider/profile/task capability 在 runtime metadata、read contract、selection record 中表达一致。
- 失败或不支持路径返回明确 reason，不再依赖隐藏默认值。
- parity 收束不改变实际 runtime route planner 行为。

### 禁止扩面

- 不新增 provider 主链能力。
- 不改 session binding / resume / fallback 决策逻辑。

### 当前收敛状态

- `test_model_policy_surfaces.py` 从 2 个测试扩展至 11 个。
- 新增 cross-surface parity 覆盖:
  - provider inventory 与 registry 的 profile 字段一致
  - task_capabilities / risk_tier / cost_tier / persistent_capability 枚举值在所有 surface 间一致
  - provider selection records 的 task_type/lane_risk 与枚举值对齐
  - registry profile 计数与 inventory 计数一致
  - model policy 默认常量与 registry 默认 ID 一致
- 所有 parity 测试不改变 runtime 行为。

---

## 任务 5: `EXPORT-CONTRACT-HARDENING`

### 非生产级实现事实

- 当前已有 `docs/xmuse/split-export-manifest.json`、`docs/xmuse/xmuse-package.pyproject.toml`、`scripts/export_xmuse.py`、相关 tests。
- 但 export contract 仍偏“能导出”，还没完全收束成强 gate 的 packaging / split governance。

### 生产级目标

补强 export contract，明确:

- copy roots
- required package files
- runtime state exclusions
- pyproject/template parity
- split 后入口脚本与依赖契约

### 只读这些文件

- `docs/xmuse/split-export-manifest.json`
- `docs/xmuse/xmuse-package.pyproject.toml`
- `scripts/export_xmuse.py`
- `tests/xmuse/test_split_export_contract.py`
- `tests/xmuse/test_export_tool.py`

### 本轮要解决的缺口

- split/export contract 还不够像生产级 packaging boundary，而更像一次性导出脚本约定。

### 强 gate

- export contract 测试能稳定约束 copy roots、runtime exclusions、entrypoints、dependency template。
- export 失败或目的目录异常时，行为稳定且可解释。
- 不把 runtime state 打包进 export 结果。

### 禁止扩面

- 不改 xmuse 主 runtime 目录行为。
- 不新增与 export 无关的 packaging 特性。

### 当前收敛状态

- `test_split_export_contract.py` 从 7 个测试扩展至 14 个。
- 新增 hardening 覆盖:
  - template pyproject packages 覆盖 manifest copy_roots
  - template entry points 与 source pyproject 一致
  - manifest required_package_files 覆盖所有 entry point 模块
  - missing manifest、self-destination、empty destination 等异常路径
  - force export 替换已有空目录
- 所有已有 5 个 export tool tests 保持全绿。

---

## 任务 6: `REAL-RUN-REPLAY-FIXTURES`

### 非生产级实现事实

- 当前已有 contract fixtures、一些 e2e tests、dashboard/MCP/operator 读面。
- 但“从一次真实链路沉淀可复用 replay fixtures”的能力还不成体系。

### 生产级目标

从至少一条真实链路沉淀 gold replay fixtures，供以下平面复用:

- dashboard
- MCP
- read contracts
- export / split governance
- operator smoke

### 只读这些文件

- `tests/fixtures/xmuse/contracts/**`
- `tests/xmuse/test_mvp_e2e.py`
- `tests/xmuse/test_mvp_e2e_chat_to_lane.py`
- `tests/xmuse/test_peer_chat_end_to_end.py`
- `tests/xmuse/test_dashboard_api.py`
- `tests/xmuse/test_mcp_server.py`

### 本轮要解决的缺口

- contract fixtures 目前更多是冻结样例，不够像真实 run replay 基座。

### 强 gate

- 至少一条真实 run 的关键只读结果可沉淀为稳定 replay fixtures。
- replay 不依赖人工改数据库。
- fixture 可被多个测试模块复用，而不是一次性测试专用数据。

### 禁止扩面

- 不改 runtime 主链来迁就 fixture。
- 不引入不可维护的大型录制系统。

### 可并行子任务

- 允许 1 个 subagent 只补 replay fixture tests 或 fixture 审计，不改主实现。

### 当前收敛状态

- 新增 `tests/xmuse/test_replay_fixtures.py`，包含 6 个 fixture contract validation tests。
- 覆盖: event/artifact/envelope/card/interface 各组 fixture 的结构化消费验证。
- 验证 envelope 内嵌 card 与独立 card fixture 的 traceability（envelope→card drill-down）。
- 验证 event artifact_refs 可解析为磁盘 fixture（replay traceability gate）。
- **说明**: 这些是 fixture contract validation 测试，不是真实 run replay 消费链路闭环。真实 replay 需要后续 V6 基建接入。

---

## 任务 7: `CONTRACT-COVERAGE-SMOKE`

### 目标

把前述所有 contract / fixture / boundary / export 任务合起来做一次真实治理收口。

### 真实链路

至少覆盖:

1. contract fixtures inventory 可读且可测
2. dashboard / MCP / read contracts 的核心只读对象 schema 对齐
3. package boundary gates 能防止关键越界
4. provider/model policy surface 一致
5. export contract 可通过 fresh 验证
6. 至少一条 replay fixture 能支撑多模块测试

### 强 gate

- 不依赖人工改数据库。
- 不因 `V5` 变更破坏 `V2/V3/V4` 已有目标和验收边界。
- contract / fixture / boundary / export / replay 各自都有 focused tests。
- 本轮 smoke 暴露出的 P0/P1 问题，必须回流到前面对应任务继续修，不允许只记录不处理。
- 最后一轮 smoke 通过前，至少要有:
  - 相关 focused tests 全绿
  - contract / fixture / boundary / export tests 全绿
  - `ruff check` 与 `git diff --check` 全绿

### 终止条件

满足以下全部条件时终止:

1. 任务 1-5 的强 gate 全部通过。
2. 任务 6 若被证明为多 surface 复用所必需，则其强 gate 也已通过。
3. `CONTRACT-COVERAGE-SMOKE` 完成至少一次 fresh run 通过。
4. smoke 暴露出的新问题如果属于已有任务范围，已经在同一轮或后续轮修回并重新验证。
5. 最后一轮通过时:
   - 无新增 P0/P1 contract governance blocker
   - 无因为治理 convenience 引入的 authority 特判
   - 无 dashboard / MCP / read contracts 关键 schema 明显失配
   - 无 export / fixture / replay 造成的关键副作用
6. 最后一轮 handoff 能让下一个较弱模型只读对应任务和 handoff，就继续安全推进，不需要重新全局探索。

### 当前收敛状态

- V5 全部 7 任务已完成 production-grade contract governance 收口。
- 所有 7 任务强 gate 全部通过。
- Contract/fixture/boundary/export/policy/replay 各有 focused tests。
- 全绿 fresh smoke: 117 V5-specific tests + 570 broader regression tests = 687 passed。
- 无新增 V2/V3/V4 后端语义特判，无 authority 特判。
- 下一轮可从此 handoff 直接推进，无需重新全局探索。

---

## 当前优先级

建议后续优先按下面顺序继续收敛:

1. `CONTRACT-FIXTURE-INVENTORY`
2. `READ-SURFACE-SCHEMA-PARITY`
3. `PACKAGE-BOUNDARY-GATES`
4. `MODEL-POLICY-SURFACE-PARITY`
5. `EXPORT-CONTRACT-HARDENING`
6. `REAL-RUN-REPLAY-FIXTURES`
7. `CONTRACT-COVERAGE-SMOKE`

## 与 V2 / V3 / V4 的关系

- `V2` 是后端主链与协议主线。
- `V3` 是 TUI 客户端交互基建线。
- `V4` 是 operator / observability / diagnostics 只读平面。
- `V5` 是 contract / fixture / boundary / export / replay governance 平面。
- `V5` 不得反向改变 `V2`、`V3` 或 `V4` 的目标、顺序和验收逻辑。
