# xmuse 收束审计与下一轮长目标研究

## 研究边界

这次审计必须把“公开可验证事实”和“你提供的本地未推送事实”分开。公开层面可以确认的是：`iiyazu/Cross-Muse` 是公开仓库，当前仍有一个开放的 Draft PR #43；该仓库的公开文档已经把 xmuse 的收束主线明确为一个狭窄的 closure controller 路径，而不是同时追求所有 L1-L11 的展示面；`iiyazu/MemryOS-lite` 也是公开仓库，定位是长期 Agent 的上下文窗口记忆中间件与 traceability surface。citeturn2view0turn3view1turn14view0turn11view0turn12view0

按你提供的本地报告，上一轮长 goal 后你还有 5 个未 push 的本地提交，核心是继续复用 shared handoff evaluator，并增加 object/condition 级别的 `observed_generation` freshness guard。这些本地提交目前不能被当作 GitHub、CI、review、merge truth；它们只能被当作“候选本地实现事实”，需要以后续 push、CI、review 或更强的 durable artifact 来升级其证明等级。这个边界也符合仓库自己写下的规则：proof level 只能从更强的上游 producer 或 server API 证明升级，CI 成功、PR body、worker output 都不能替代 GitHub review truth 或 merge truth。citeturn14view2turn18view1turn19view0turn9view1turn9view2

## 上一轮长 goal 的审计结论

如果按第一性原理看，上一轮长 goal 并没有“失败”，而是做了一个更正确的收束：它没有继续试图宣称 “L1-L11 全闭环”，而是把收束点放回了一个更底层、更可验证的控制面——也就是 `Recovery -> ExecutionCandidate -> ReviewClosure -> ReleaseHandoff` 这条窄链。这个方向与仓库公开的 `goal-behavior-contract`、`AGENTS.md`、`next-production-closure-long-goal.md` 完全同向：这些文档都把 closure controller 的默认路径固定在这四段上，并要求每个生产切片明确 `spec`、`status`、`conditions`、`owner_refs`、`source_refs`、`target_refs`，缺失上游 producer 时必须 fail closed 到 `manual_gap` 或 `refactor_required`。citeturn14view0turn14view1turn14view2turn23view0turn20view0

公开可见的开发轨迹也支持这一点。`b050d53` 这个大提交已经把工作重心压在 Wave D / L8-L10 的 recovery、review handoff、runtime closure、release evidence 等边界上；`4465686` 则继续对 `closure_objects.py`、`closure_reconciler.py`、`god_room_review_handoff.py`、`god_room_runtime_closure_evidence_capture.py`、`release_evidence_candidates.py`、`release_evidence_pack.py` 这些“闭环控制器边界文件”动刀，同时补强 `AGENTS.md`、`anti-tdd-abuse-policy.md`、`goal-behavior-contract.md`、`github-git-behavior-policy.md` 等治理文档。换句话说，公开分支已经把“先统一控制面，再谈投影面”的路线写进了代码与文档。citeturn6view1turn4view0turn7view0turn7view1

从奥卡姆剃刀角度，这条路线是对的，因为它拒绝继续扩 TUI、dashboard、release-pack 字段和各种“看起来更完整”的 surface，而是把注意力放在“谁在写 truth、谁只是在读 projection、谁只能产出 candidate evidence”这三个最少问题上。Kubernetes API conventions 也给出同样的设计启发：`spec` 是 desired state，`status` 是实际观察，conditions 是显式状态，而不是让客户从若干零散症状去推断系统是否准备好。特别是 `observedGeneration` 的实践，正对应你本地本轮新增的 freshness guard 思路。citeturn10view0turn10view1turn10view3turn10view4

所以，上一轮长 goal 的核心成绩不是“闭环完成”，而是**把 xmuse 的 L8-L10 闭环从扩展 surface，重新拉回到单一控制面和显式 freshness / admission 规则**。这一步是正确的，而且是之后所有“可用状态”工作的必要前提。citeturn14view0turn14view2turn23view2

## 当前真正的痛点

当前最大的痛点不是“还缺一个功能”，而是**闭环判断仍然过度分散**。你报告中的 5 个本地提交已经暴露了这一点：有两个提交在“复用 review-chain handoff admission”，还有两个提交在“补 object 与 condition 的 observed_generation 守卫”。这类补法本身没错，但它同时说明 handoff evaluation 和 freshness validation 还不是一个真正单一、统一、不可绕过的边界；否则不会反复以“把另一处也接上共享 evaluator”“再给另一层 condition 补 observed_generation”的形式出现。Kubernetes 官方条件设计明确建议，把 conditions 当作显式 API，用统一 schema 和 `observedGeneration` 表示 freshness，而不是由多个 consumer 各自暗含自己的 freshness 与 readiness 逻辑。citeturn10view1turn10view3turn10view4

第二个痛点是**Surface 仍然多于 Producer**。公开文档已经反复强调：release evidence、runtime closure replay、TUI、dashboard、MemoryOS provenance hints 都只能读上游证据，不能自己生产 truth。`goal-behavior-contract.md` 甚至把 MemoryOS Lite 明确限定为 L10 provenance/trace consumer，不得拥有 recovery 决策、execution-candidate validity、independent review verdict、release handoff truth、GitHub review/merge truth。MemryOS-lite 仓库自己的 README 和设计文档也把它定义为“context-window memory middleware”“source traceability”“trace endpoint”，而不是审查真值的 authority plane。citeturn14view1turn14view2turn14view5turn11view0turn12view0

第三个痛点是**PR #43 已经成为结构性噪音源**。公开 PR 页面显示 #43 仍然是 Draft，而且已经积累到非常大的提交量；仓库自己的 Git/GitHub policy 进一步把 PR #43 定义为“too heavy”，要求把它当作 frozen umbrella / historical integration PR，只允许修冲突、补说明、准备拆分，而默认禁止再把新生产功能堆进去。GitHub 官方文档也说明 draft pull request 本身不可 merge，而 required review 与 merge truth 需要服务端的审批状态，不是 CI 绿就能替代。citeturn3view1turn19view0turn9view1turn9view2turn9view3

第四个痛点是**superpowers 技能和多 agent 编排很容易替代思考，而不是减少复杂度**。仓库公开 `AGENTS.md` 已经给出非常务实的分流：简单 1-2 文件任务直接 prompt，不要 orchestration；3+ 文件的多步任务才用 `@orchestrator`；复杂 feature 先 `@planner` 再 orchestrator；而且 orchestrator 必须独立验证，不能信任 subagent 自报。worker delegation policy 也把 OpenCode 限定为 bounded worker，不得做架构裁决、truth 判断、提交、推送、PR 更新。换句话说，superpowers 不是默认入口，它只能在 scope、acceptance gate、forbidden actions 都已经清楚时，承担低智能重复劳动。citeturn23view0turn23view1turn16view2turn16view3

第五个痛点是**TDD 仍然会天然诱导“状态先于 producer”**。仓库公开的 anti-TDD policy 写得非常直白：tests 是 verification，不是 architecture authority；如果 tests 先于 authority/proof path 出现，或 tests 构造了运行时本该产生的 artifacts，或 mocks 绕开 selected GOD binding / provider invocation / recovery enforcement / independent review / GitHub truth / MemoryOS truth，就构成 TDD abuse。更重要的是，文档已经给了非常硬的纠正动作：一旦检测到 abuse，先停止加测试，先找缺失的 authority 或 producer，必要时把 speculative tests 降成 `manual_gap` 文档或删掉；而如果重复失败或 handoff parsing 复制扩散，就要直接进入 bounded refactor，而不是继续 patch stacking。citeturn13view0turn14view4turn23view2

## 依照第一性原理与奥卡姆剃刀的收束方案

如果把 xmuse 当作一个控制系统，而不是一个“功能集合”，那么它要进入“可用状态”，真正只需要满足四个最小命题。

第一，**系统只能有一条主 closure 链**。公开文档已经把这条链定义为 `Recovery -> ExecutionCandidate -> ReviewClosure -> ReleaseHandoff`。这意味着下一步不应该再追求新的 closure surface，而应该让所有现有 surface 都退回到读这条链的产物和条件。citeturn14view0turn20view0turn21view5

第二，**系统只能有一个共享的 admission/freshness 规则源**。Kubernetes API conventions 把 `spec/status/conditions/observedGeneration` 视为通用控制面语言；xmuse 文档也已经要求 closure writer 在写 status 前通过 admission-style checks，并携带 `generation`、`observed_generation`、`evaluator_version`。因此，接下来最符合奥卡姆剃刀的工作，不是再给 release pack、runtime closure、MemoryOS candidate 各补一层校验，而是把 handoff 与 freshness 的“单一真正规则”抽出来，让所有 consumer 复用。citeturn10view0turn10view1turn10view3turn14view0turn14view2

第三，**投影永远不能高于 authority**。GitHub review/merge truth 只能来自服务端；draft PR 不能 merge；Approvals 与 merge blockers 必须由 GitHub 服务端状态认定。MemoryOS 也只能做 provenance/trace surface。由此推导，下一轮长任务不应再增加任何“看起来接近 ready”的 projection；它应该只做 authority path consolidation。citeturn9view1turn9view2turn9view3turn14view1turn14view5

第四，**开发过程也必须服从同样的控制面约束**。也就是：/goal 相当于 desired state；durable artifacts/status/server API 才是 observed state；Codex 是唯一 writer + 最终 verifier；OpenCode/subagents 只是 bounded worker；PR 是 review/integration unit 不是 proof authority；出现两次同边界失败后，第三次之前必须先有 refactor artifact。这一点在仓库的 AGENTS、worker policy、stage harness、GitHub behavior policy 中都已经写明。citeturn23view0turn23view1turn23view2turn19view0

这四条一旦成立，xmuse 的“可用状态”就不再等于“所有层都很花哨”，而是等于：**对一个 bounded 的 L8→L10 闭环，系统能够明白地说出 desired state、current observed state、哪些条件满足、哪些条件因为 stale lineage / missing upstream producer / server truth missing 而 fail closed。**这比把更多面板点亮更接近真正可用。citeturn14view0turn10view4

## 建议的唯一下一轮长任务

最符合第一性原理和奥卡姆剃刀的下一轮长任务，不是再扩 TUI、不是再碰 MemoryOS live、也不是追加 GitHub truth surface，而是：

**抽取并强制落地一个单一的 L9→L10 release-handoff admission / freshness boundary，然后删除剩余重复消费者。** citeturn4view0turn20view0turn21view5

为什么是它。因为你这轮本地 5 个提交，已经很清楚地表明真正的摩擦不在“有没有更多 evidence 字段”，而在“handoff evaluation 和 freshness rejection 还没成为唯一控制面”。公开历史也支持这个判断：`b050d53` 和 `4465686` 都集中修改了 `god_room_review_handoff.py`、`god_room_runtime_closure_evidence_capture.py`、`release_evidence_candidates.py`、`release_evidence_pack.py`、`closure_objects.py`、`closure_reconciler.py` 这些 handoff/aggregation/controller 边界文件；仓库的下一轮长 goal 文档也把 “L9 chain 先于 L10 aggregation” 和 “release evidence 只能聚合 upstream artifacts” 作为主原则。citeturn6view1turn4view0turn20view0turn21view5

这轮长任务的目标不应该写成“闭环完成”，而应该写成：

> 把所有 L10 读者改成只消费一个共享的 `review-closure -> release-handoff` admission 结果；  
> 把 stale generation / stale head / mismatched graph-lane scope / deleted forbidden claims / proof inflation 统一收口到一个 shared freshness+admission evaluator；  
> 删除或重定向原先各 consumer 内部重复的 handoff parsing 和 freshness special-case。 citeturn14view0turn14view2turn10view3turn10view4

最小作用域应当只覆盖这些边界文件：

- `src/xmuse_core/platform/god_room_review_handoff.py`
- `src/xmuse_core/platform/god_room_runtime_closure_evidence_capture.py`
- `src/xmuse_core/platform/release_evidence_candidates.py`
- `src/xmuse_core/platform/release_evidence_pack.py`
- `src/xmuse_core/platform/closure_objects.py`
- `src/xmuse_core/platform/closure_reconciler.py`

如果确实还存在分散的 freshness 校验，再增加一个极小的新共享模块，比如 `closure_admission.py` 或 `closure_freshness.py`。不要再扩 TUI、不要新增 release-pack 表面字段、不要再让另一个 consumer 私自复制 handoff rule。这个文件范围的合理性，既来自最近公开大提交的 file tree，也来自当前长 goal 文档对 L9/L10 handoff aggregation 的定义。citeturn4view0turn20view0turn21view5

验收标准也必须极窄、极硬：

- L10 consumer 不能再各自决定 `chain_ready`、`handoff ready` 或 freshness；
- stale `generation` / `observed_generation` / `head_sha` / graph-lane scope 不匹配时，所有相关 consumer 都一致 fail closed；
- inherited `manual_gaps` 与 `forbidden_claims` 不允许在某个 consumer 里“顺手消失”；
- release evidence 仍然只是 aggregation，不升级为 review truth、GitHub truth、merge truth；
- MemoryOS 仍只接 provenance hints，不接 authority path；
- focused tests 证明的是共享 evaluator 的输入输出与 fail-closed 行为，而不是更多高层 “ready/closed/passed” 布尔值。citeturn14view0turn14view2turn14view5turn21view5turn9view1turn9view2

同样重要的是，这项长任务**不该继续默认落在 PR #43**。公开 Git policy 已经明确要求：PR #43 是过重 umbrella，未来 work 应尽量拆成小 PR；推荐顺序里，closure controller shell、L8 recovery consolidation、L9 execution-candidate consolidation、L9→L10 release handoff aggregation、L10 projection 是分步推进的。所以下一轮应优先开一个新的 scoped branch / stacked PR，必要时注明 stacked on #43，但默认不要继续往 #43 里堆。citeturn19view0turn18view1turn23view0

可以把下一轮 `/goal` 写成下面这个样子：

```text
/goal

Implement one shared L9->L10 release-handoff admission and freshness boundary for xmuse.

Purpose:
Collapse duplicated review-handoff parsing and stale-state rejection into a single
authority-owned boundary so that all L10 consumers read one handoff result instead
of each consumer inventing its own readiness/freshness logic.

Desired state:
- One shared evaluator owns:
  - stable source/target ref validation
  - owner lineage validation
  - inherited manual_gap / forbidden_claim preservation
  - proof inflation rejection
  - stale generation / stale observed_generation / stale head rejection
  - graph/lane/review scope matching
- Runtime closure capture, release evidence candidates, release evidence pack,
  and closure reconciler consume this shared result.
- Existing duplicated consumer-local handoff/freshness logic is removed or routed
  through the shared evaluator.
- MemoryOS remains provenance-only.
- GitHub review/merge truth remains server-side only.

In scope:
- src/xmuse_core/platform/god_room_review_handoff.py
- src/xmuse_core/platform/god_room_runtime_closure_evidence_capture.py
- src/xmuse_core/platform/release_evidence_candidates.py
- src/xmuse_core/platform/release_evidence_pack.py
- src/xmuse_core/platform/closure_objects.py
- src/xmuse_core/platform/closure_reconciler.py
- focused tests for the shared boundary

Out of scope:
- no new TUI/cockpit surface
- no new release-readiness claims
- no live MemoryOS proof
- no GitHub review truth / merge truth / ready_to_merge / pr_merged
- no new PR #43 feature accumulation unless explicitly instructed

Implementation rules:
1. Use the narrow closure chain only:
   Recovery -> ExecutionCandidate -> ReviewClosure -> ReleaseHandoff
2. Introduce or finish one shared admission/freshness evaluator.
3. Delete or redirect duplicate per-consumer handoff parsing.
4. Fail closed on stale or mismatched lineage.
5. Preserve inherited manual_gaps and forbidden_claims.
6. Add targeted regression tests only for the shared boundary and its consumers.
7. Update ledger and docs with honest proof boundaries.

Validation:
- uv run pytest <focused handoff/freshness tests> -q
- uv run ruff check .
- git diff --check
- test ! -e xmuse/__init__.py
- if package boundary changed:
  uv run pytest tests/xmuse/test_package_boundaries.py -q
```

这项任务天然会超过 8 小时，因为它不是机械改字段，而是一次“删掉重复规则、留下唯一控制面”的 bounded refactor + migration slice；但它又足够窄，不会把目标重新膨胀到 “全闭环” 幻觉。citeturn14view0turn19view0turn23view0turn23view2

## Codex 的行为规范

Codex 的首要规范应该是：**先判定 authority，再写 producer，再补 verification；永远不要先写“闭环看起来成立”的 tests、TUI、release surface。** 仓库的 anti-TDD 文档已经把这一点写得很清楚：tests 只能验证真实生产路径；不能定义架构、不能替代 runtime producer、不能伪造 authority，也不能把 fixture 小世界当作生产闭环。citeturn13view0

第二条规范是：**默认使用最小执行模式，而不是默认使用 superpowers。** 1-2 个文件、明显局部的工作，直接 prompt；3+ 文件且需要多步协调，才用 `@orchestrator`；确实是复杂 feature，才先用 `@planner` 再 orchestrator；除非任务真的是多个独立子问题，否则不要默认 `@swarm-coordinator`。任何 skill、subagent、OpenCode 输出，都只是 candidate，不是事实。这个规范直接来自仓库现有 `AGENTS.md`、worker delegation policy 与 stage harness。citeturn23view0turn23view1turn23view2

第三条规范是：**两次同边界失败后，第三次之前必须先重构或删除。** 仓库现有规则已经明确：如果同一 feature / stage / 测试簇 / runtime path 连续两次同类失败，下一步必须声明为 root-cause / refactor / replacement work，而不是继续沿原路径补 patch；`refactor_required` 后不得发起第四次同类重试。把这条提升成 Codex 的硬行为规则，会比“尽量重构”有效得多。citeturn14view4turn16view2turn16view3turn23view0

第四条规范是：**永远只维护一条 closure 主链。** 新 surface、TUI 字段、release-pack 字段、worker report，只有在它们来自 `Recovery -> ExecutionCandidate -> ReviewClosure -> ReleaseHandoff` 这条链，或明确标成 projection/manual gap 时，才能存在。否则默认视为噪音或 false closure 候选。citeturn7view0turn14view0turn14view1

第五条规范是：**把 freshness 当一等公民，而不是收尾补丁。** Kubernetes 的 conditions 设计把 `observedGeneration` 视为条件 freshness 的标准字段；xmuse 的 goal contract 也已经要求 closure objects 至少包含 `generation`、`observed_generation`、`evaluator_version`，并在 stale head / stale generation / wrong scope 时 fail closed。Codex 以后看到 stale-state 问题，不应再“顺手在另一个 consumer 里补个 guard”，而应先问：是不是应该抽出 shared freshness boundary。citeturn10view3turn10view4turn14view0turn14view2

第六条规范是：**PR 与 proof 严格分离。** PR 是 review/integration unit，不是 proof authority；PR #43 默认不能再当新 scope 汇集器；draft PR 不可 merge；CI green 也不等于 review truth 或 merge truth。Codex 必须把“当前本地候选事实”“当前 head 的 CI 事实”“GitHub 服务端 review/merge truth”三者分开陈述。citeturn19view0turn3view1turn9view1turn9view2turn9view3

第七条规范是：**MemoryOS 永远不进 xmuse authority write path。** 这不只是仓库偏好，而是架构边界：Cross-Muse 的公开文档已经禁止把 L8/L9 recovery、candidate、review、handoff truth 路由进 MemoryOS；MemryOS-lite 自己的公开定位也只是 memory middleware、traceability、trace endpoint。Codex 如在 goal 中碰到 MemoryOS，默认只当 provenance/trace sink 处理。citeturn14view1turn14view5turn11view0turn12view0

把这些规则压缩成一句最重要的话，就是：

> **Codex 的默认动作不是“让更多东西变绿”，而是“让唯一正确的 producer path 更短、更单一、更不可绕过；如果做不到，就诚实保留 manual_gap”。** citeturn13view0turn14view0turn23view2