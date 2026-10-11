# T15 团队实验预注册：prizehub 猎场上的 T-plain 对 T-xmuse（2026-10-11，base 起草，用户定）

> 先写死再开跑。每组只有 3 次，样本很小，结果只用来描述，不做显著性结论。

## 1. 判定口径（先看单干）
单干：dsh-ms13，挂 `run_tests`，题面用新版 README。按单干修好的比例决定后续做法：

| 单干修好数 / 总数 | 做法 | 主要指标 |
|---|---|---|
| 超过 50% | **不再调整难度**，直接用当前猎场跑团队实验（备用方案） | 协作质量（第 4.1 节） |
| 10%–50% | 按原计划走 | 修好数 / 总数；第 4.1 节的协作指标照样记录 |
| 低于 10% | 停下，等 r7 调整 | — |

不管走哪种做法，T-plain 和 T-xmuse 都各跑 3 次，见第 3 节。

## 2. 阵容与条件（两组完全相同，只差信息层开关）
- **角色**：
  - 规划者 P：`dsh-ms13`（dsh，`opencode-go/muse-spark-1.3-contributor`），**不写功能代码**，只负责合并冲突和接线；
  - 执行者 E1：`oc-ms13`（opencode，同一模型）；
  - 执行者 E2：`dsh-fl`（dsh，`opencode-go/deepseek-v4.1-flash`）。
- **编排**：hub 预设 `plan-split-integrate`。每个执行者在 P 的工作区下有自己的 worktree（`.xmuse-wt/<id>`），P 负责整合出最终工作区。
- **信息层**：T-plain 设 `info_layer=off`，T-xmuse 设 `info_layer=on`。除此之外，配置、题面、时限、模型、护栏完全相同。
- **时限**：总墙钟 7200 秒。各阶段：P0 1200、P1 3000、P2 1200、P3 960 × 2 轮（秒）；先到总时限就直接收尾。
- **护栏**（两组相同，写进 meta）：`turn_timeout` 7200、`max_chain_wakes` 60；`max_chain_tokens` 和 `agent_hourly_tokens` 调高到不会触发。
- **题面**：猎场 `README.md` 原文，中途不补任何提示。
- **测试入口**：
  - dsh 成员（P、E2）用 MCP 工具 `run_tests(test?)`。工具由 hub 的 `extra_mcp` 挂载，工作区路径和 compose 项目名都固定写死，不执行工作区里的任何脚本；
  - E1 也挂同一个 bench-tests MCP（opencode 的 MCP 配置），shell 用默认的白名单策略，不开无人值守的宽松 shell；
  - 如果 opencode 挂不上：E1 改用 `docs/dev-ops/bench/run-tests.sh`，为此只能开宽松 shell 策略（`blocklist-experiment`）。这时 E1 的 shell 权限明显比 dsh 成员宽，结果里要标明。
  - 两种入口执行的是同一条命令：`mvn -B test -Dspring.profiles.active=bench -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false [-Dtest=…]`。
  - 已知差异：`run-tests.sh` 直接在 `/mnt/c` 上编译，比 MCP 入口慢。
- **隔离**：每个 run 都用全新的工作区（从同一个猎场提交克隆）、全新的 hub 状态目录。每个 agent 各用一套 compose（项目名带 run 编号）。每个 run 结束后执行 `compose down -v`，清掉这些环境。

## 3. 次数与顺序
- T-plain 和 T-xmuse 各 3 次，**交替进行**：plain → xmuse → plain → xmuse → plain → xmuse。
- 每次都算，不挑、不重跑刷分。
- 因为环境故障（hub 崩溃、Docker 起不来、模型渠道整体不可用）而作废的 run，在报告里列出原因，并按原来的顺序位置补跑一次。agent 自己的失败（超时、跑偏、交白卷）不算环境故障。

## 4. 指标
所有判分都用 `BENCH_DIR/grade.py`：修好的 bug、判不了的 bug（判定测试编译不过）、回归、能否编译。

### 4.1 协作质量（备用方案下是主要指标，原计划下照样记录）
| 指标 | 口径 |
|---|---|
| 重复修同一个 bug 的次数 | E1、E2 的 worktree 最终状态各自单独判分，两边都判为修好的 bug 数 |
| 整合时丢掉的修复数 | 在 E1 或 E2 的 worktree 里修好了，但在最终工作区里没修好的 bug 数 |
| 合并冲突次数 | 预设事件里，hub 合并某个执行者分支时发生冲突、交给 P 手动处理的次数（P3 每一轮都算） |
| 跨层 bug 两侧改法不一致的次数 | 只看跨层 bug。如果 E1、E2 的分支都改了这个 bug 涉及的文件，而两边单独判分的结果不同，或者合并后判定测试失败，就记一次。每一次都附上两边的 diff，并人工复核：只改了一侧、但另一侧没被碰过的，不算 |
| 总 token | hub `usage` 里三个 agent 的合计（输入 + 缓存读 + 输出），同时分角色列出 |
| 墙钟 | 从预设开始到收尾快照 F 的时间；分阶段的时间也列出来 |

### 4.2 结果
- 最终工作区的修好数 / 总数、跨层修好数 / 跨层总数、回归数、能否编译、判不了的数量；
- E1、E2 的 worktree 也按同样的口径各判一次分；
- 快照 S-E1、S-E2、S-int、S-fix-k、F 都要判分，用来看每个阶段的净变化。

### 4.3 其它记录
- 每个 agent 的 token 和用时；
- hub 消息总数（按 kind 分）；
- 对齐层各类条目的数量：decision、assumption、question、assignment。T-plain 下这些应当全是 0；
- 越界修改的次数；
- 崩溃重试和降级的次数；
- 每个 agent 调用 `run_tests` 的次数。

## 5. 报告格式
1. **逐次列出**：6 个 run，每个 run 一行，列出第 4 节的全部指标。
2. **两组均值**：T-plain、T-xmuse 各自的均值，以及最小值和最大值。只做描述，不写"显著"。
3. **逐 bug 对照**：每个 bug 一行，列单干 / T-plain 第 1–3 次 / T-xmuse 第 1–3 次，每格标"修好、未修好、判不了"。另外给出每组 3 次里修好的次数。
4. 原始 json（grade、usage、log、run-status、align 列表）推到 prizehub-bench 的 `results/`；REPORT 里给出路径。

## 5a. 修订（2026-10-11，开跑前；用户定）
- **墙钟改为 30 分钟**（第 2 节的 7200 秒作废）。单干和团队都是 1800 秒。团队各阶段按 hub 默认时限减半：P0 300、P1 750、P2 300、P3 240 × 2 轮（秒），总计 1800；`turn_timeout` 1800。单干每 600 秒存一次快照。
- **E1 的测试入口**：第 2 节的"如果 opencode 挂不上"没有发生。hub 的 `extra_mcp` 已扩展到 headless opencode（服务器写进实例配置，并给这个服务器的工具加 allow 规则）。r7 上用真实的 oc-ms13、默认白名单 shell 验证过：它能看到 `bench-tests.run_tests`，调用 `run_tests(SchemeDrawTest)` 返回 `tests=6 failures=0`，没有停下等人工审批。所以三个成员用的是同一种入口，shell 策略也都是默认白名单。
- **猎场**：换成合并了 r7 新 bug 后的版本，bug 数和 `HEAD^{tree}` 以 REPORT 中的记录为准。第 1 节的判定口径不变。
- **run_tests 调用次数**：从 `bench_tests.py` 写的调用日志（`logs/bt-calls.jsonl`，按 compose 项目区分 agent）统计。（已被 5b 取代）

## 5b. 修订（2026-10-11，开跑前；用户定）：只推理、可编译、不能运行测试
- **实验条件**：所有 agent 都只能推理和编译，不能运行测试。理由（用户）：能跑测试，就能靠反复试错修 bug；这里要测的是推理和协作。第一次单干（32/44）一次测试都没跑，正好可以作为同条件的基线。
- **猎场**：删掉 `docs/dev-ops/bench/` 下的运行脚本和 compose。判分器只用 kit 里 `harness/` 那份，不受影响。README 改两处：
  - "本地环境"一节改为"本环境不能运行测试，可以调用 compile 工具检查能否编译"；
  - "任务"一节的"可见测试和构建必须通过"改为"构建必须通过（判分时会运行全部测试）"，"不准削弱、跳过或删除测试"保留。
- **工具**：bench-tests MCP 只提供 `compile()`，没有参数，删掉 `run_tests`。它在固定的 scratch 副本上执行 `mvn -q -o test-compile`，容器无网络，用离线 Maven 缓存；返回成功或失败，以及报错原文（前 200 行）。P、E1、E2 和单干都挂这一个工具。
- **shell**：oc-ms13 用默认白名单。白名单里没有 docker、java、mvn、gradle。剩下一条间接途径：白名单会自动批准 `python3 <工作区或 /tmp 里的 .py>`，这样的脚本可以调用 docker。所以每个 run 结束后，在 transcript 和 turn 日志里搜 mvn、gradle、java、docker 的调用，命中就记为违规并逐条列出，不做事后剔除。
- **记录**：每个 agent 调用 `compile` 的次数，取自 `logs/bt-calls.jsonl`。第 4.3 节里"每个 agent 调用 `run_tests` 的次数"换成这一项。
- **其余不变**：第 1 节判定口径、30 分钟墙钟（5a）、3 + 3 次交替、指标、报告格式都不变。

## 5c. 修订（2026-10-12 00:20，系列中途；用户定）：不再挂起等人工审批
- **原因**：默认白名单不含 `git branch`。r1-plain、r2-xmuse 里 oc-ms13 在 P1 的第一条 shell（`git branch --show-current` 等）被挂起等人工审批，无人值守，E1 整个 P1 没有产出（S-E1 = 基线）。r2 的 P3 又因 `mvn -q -o test-compile` 挂起一次。
- **新策略**：hub 的 `XMUSE_SHELL_POLICY=open-experiment`（xmuse2 `34cf280` 里的 hub 提交）。所有权限请求由 hub 自己答复，不会挂起：命令行里任何一个词是构建/测试运行器（docker、podman、java、javac、mvn、mvnw、mvn.cmd、gradle、gradlew、wsl、wsl.exe、cmd.exe、powershell、pwsh）就立即拒绝，其余一律批准。"只推理、可编译"的条件（5b）不变。脚本间接调用运行器仍拦不住，照旧事后搜索，命中记违规。
- **run 的取舍**：
  - r1-plain、r2-xmuse 作废（条件不同：E1 在 P1 被挂起），移到 `runs/team-pilot`，只作试跑记录，不进入两组统计。
  - r3-plain 保留：整次 0 个挂起，所有请求都被白名单自动批准，新策略下 agent 看到的结果完全相同。
  - r4-xmuse 刚开始就被中止（移到 `runs/team-aborted`），按新策略从头跑。
  - 新顺序：r4-xmuse → r5-plain → r6-xmuse → r7-plain → r8-xmuse。T-plain = r3、r5、r7，T-xmuse = r4、r6、r8，仍是交替。
- **新增记录**：每个 run 的审批记录（agent、命令、批准还是拒绝），以及被拒绝的次数。

## 6. 现状（预注册提交时）
- 当前猎场：44 个 bug，r7 上的猎场 `HEAD^{tree}` = `859b69f51ac5b2288e31c130e41b4c741b417434`。
- 上一次单干（旧 README、挂了 `run_tests` 但一次都没调用）：32/44。
- r7 要求的加难度改写（convention 型 bug 扩到 65–75 个、加诱饵、README 写明两个测试入口），正在等决定怎么做。如果最后不改难度，就按第 1 节第一行（备用方案），直接用当前猎场跑。
