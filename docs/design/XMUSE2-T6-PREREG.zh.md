# T6 补充实验：预注册（2026-10-11，开跑前提交）

> 按审计 C3 和交接 §7 的要求，**本文件在任何 T6 run 开始之前提交**。提交之后，主指标、样本量、比较对象和分析方法都不再改；如果必须改，就在文末"偏离记录"里写明改了什么、为什么改、是在看到哪些数据之后改的。
> 实验只用 OpenCode 和 dsh 的额度，不用 Claude。需要 dsh（Windows）的臂留给 r7。

## 0. 共同设定

- **任务**：ledger、minisql、pipeline 三个种子（`experiments/seeds/`），叠加 `overlays/spec-v2`：
  - minisql 写明"字符串没闭合时 `position` 指向开头的单引号"；
  - ledger 写明"金额只接受 ASCII 数字"。
  - 这正是 M2b 实验里两个"猜题"失败项的歧义。隐藏测试、公开测试、rot 文本都不变。pipeline 没有覆盖文件。
- **完成的定义**（与 M2b 相同）：公开测试通过 + 未受 rot 影响的隐藏测试全过 + rot 遵守为 followed。
- **模型**：OpenCode 用 hub 默认模型 `opencode-go/muse-spark-1.3-contributor`；dsh 由 r7 决定，并写进每个 run 的 `meta.json`。
- **记录**：每个 run 的 `meta.json` 里有 `provenance` 字段，包括 hub 提交号、工作区有没有未提交改动、每个 agent 的模型、厂商 CLI 版本（审计 C2-2）。
- **执行**：`experiments/batch.sh <plan>`；指标用 `experiments/metrics.py`。所有 run 都计入，包括失败或超时的，不挑选。runner 自身出错的（agent 一个回合都没跑起来，例如预检失败）可以重跑一次，并记在偏离记录里。
- **统计**：每个比较报告两组的计数、差值，以及差值的 95% 置信区间（Newcombe 混合 Wilson 法），双侧 Fisher 精确检验只作参考。**样本很小，事先声明：只有差异很大时才可能显著；结果以描述为主，不做"有效 / 无效"的二元结论。**

## E1 单 agent 基线

**问题**：同一个模型，多 agent 协作比一个 agent 自己做加自审强在哪？

| 臂 | 场景 | 阵容 | 在哪跑 |
|---|---|---|---|
| S | `<seed>-S` | 一个 OpenCode agent 实现，然后自审（跑测试、自造边界用例、修改），没有同伴 | **base** |
| B2 | `<seed>-B2` | OpenCode 实现、dsh 复核，点名唤醒，不开对齐层 | r7（需要 dsh） |

- **样本量**：每个任务每臂 3 次，共 9 对 9（`plans/t6-e1-S.txt`、`plans/t6-e1-B2.txt`）。
- **主指标**：完成率（9 个里完成几个）。
- **次指标**：每个 run 的总 token（中位数和四分位距）、回合数、未受 rot 影响的隐藏测试通过比例、耗时。
- **rot 时机**：B2 和 M2b 一样，在复核方第一次回复之后注入；S 没有复核方，在第 1 个回合结束后注入（`ROT_AT=turn:1`），这时实现方已经交出第一版。两臂的 rot 都点名到所有 agent。
- **已知混杂**：
  - 两臂的 rot 注入时刻不完全相同；
  - B2 多了一个 agent，可能也多一个模型；
  - S 的任务文本要求"自审"，B2 要求"等同伴复核"。

## E2 修好 SPEC 后重测对齐层

**问题**：去掉 SPEC 歧义以后，对齐层（C 对 B）还有没有差别？

- **E2a**（已准备）：`minisql-B2` 对 `minisql-C2`，每臂 6 次（`plans/t6-e2a.txt`）。需要 dsh，**在 r7 跑**。B2 的这 6 次和 E1 里 minisql-B2 的 3 次分开，各跑各的。
  - **主指标**：完成率。
  - **次指标**：申报率、注入占比、token。
  - **事先的预期**（写下来以便对照）：歧义去掉后，两臂在"开引号"这一项上都应该通过，完成率差异接近 0。如果 C 仍然明显高于 B，就需要别的机制来解释。
- **E2b**（只有设计，**没有准备**）：造一个"只有一方知道"的跨模块约定，即两个实现方，A 定格式、B 使用，复核方另一人；B 对 C 各 6 次。这需要新写种子、参考实现和隐藏测试，留给后续。

## E5 复核基线

**问题**：换一家 agent 来复核，比实现方自己那一家来复核多找到多少？

| 臂 | 场景 | 复核方 | 在哪跑 |
|---|---|---|---|
| SELF | `review-<seed>-bug<n>-self` | OpenCode（和所有实验里实现方同一家、同一个模型） | **base** |
| CROSS | `review-<seed>-bug<n>` | dsh | r7 |

- **样本量**：3 个任务 × 2 个预埋 bug，每臂 6 次（每个 bug 1 次）（`plans/t6-e5-self.txt`、`plans/t6-e5-cross.txt`）。
- **主指标**：检出率（`metrics.py` 按 `review-keys/` 判定是否明确指出预埋 bug）。
- **次指标**：误报数（没埋 bug 的模块被报成 bug）、token。
- **说明**：
  - SELF 臂不是"实现方复核自己写的代码"，而是"同一家、同一个模型的另一个会话复核"。真正的自审（同一个会话复核自己刚写的代码）包含在 E1 的 S 臂里。
  - CROSS 臂如果 dsh 用的也是 muse-spark，那就只是跨框架、不跨模型；用哪个模型由 r7 定，并在报告里写明。
  - M2b 已有 6 个 dsh 复核 run（muse-spark），它们**不计入** CROSS 臂，只作参照。

## 不做的事

- 不用 Claude 当任何角色（用户 10-11 要求）。审计 C3 建议"能用 Claude 的话至少当一个角色"，这一条这次不执行。
- 不做 E3（≥3 个 agent 的点名对群聊）和 E4（rot 不点名全员）。

## 结果（按臂追加；分析口径不变）

| 臂 | 状态 | 结果 |
|---|---|---|
| E1 S | base 已跑，9 个 run（`results/metrics-t6-e1-S/`） | 完成 9/9（Wilson 95% CI 0.70–1.00），每个 run 平均 833,515 token、2 个回合 |
| E1 B2 | 待 r7 | — |
| E2a B2 / C2 | 待 r7 | — |
| E5 SELF | base 已跑，6 个 run（`results/metrics-t6-e5-self/`） | 检出 6/6（Wilson 95% CI 0.61–1.00），误报 1 条 |
| E5 CROSS | 待 r7 | — |

主比较（S 对 B2、B2 对 C2、SELF 对 CROSS）都要等对照臂跑完才能算。

## 偏离记录

1. **10-11 03:22 开跑约 8 分钟后全部中止，2 个 run 作废**：`ledger-S-1`、`review-ledger-bug1-self-1`。
   - **原因**：T5 把 OpenCode 的 shell 自动批准改成了白名单。agent 写探针脚本时用的 heredoc（`cat > /tmp/... <<'PY'`）和 `python3 -c`，都按设计转给人审批；无人值守时会一直挂到超时。两个 run 都卡在待审批状态，这和要测的东西无关。
   - **处理**：新增只供实验使用的审批策略 `XMUSE_SHELL_POLICY=blocklist-experiment`，由 runner 在启动 hub 时通过环境变量传入，并记进每个 run 的 `meta.json` → `provenance.shell_policy`。它的语义就是 M2b 时期的黑名单，所以新 run 和 M2b 的 run 在审批上可比。
   - 主指标、样本量、比较对象都**没有改**。作废的两个 run 不计入；重跑时，batch.sh 会把旧目录移到 `results/_prev/`。
   - 修复提交见报告 T6 一节。
