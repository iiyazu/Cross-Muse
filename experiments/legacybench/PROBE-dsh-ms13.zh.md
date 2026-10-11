# T11a 探针预注册：Legacy-Bench 上 dsh 单 agent（opencode-go/muse-spark-1.3-contributor）

> 先写死再开跑。这是探针，样本小，只作描述，不下结论。

## 题目（代号 tNN，工作区和 prompt 里只用代号）

- t01 = tasks/1907c2-c-debug-legacy-buddy-fix（C）
- t02 = tasks/2831b5-java7-rating-engine-repair（Java 7）
- t03 = tasks/505812-java7-inventory-cost-fix（Java 7）
- t04 = tasks/6fe1ab-java7-mtom-attachment-corruption-fix（Java 7）

题库：base 本机 `BENCH_DIR/legacy-bench`，`git clone --depth 1 https://github.com/factory-ai/legacy-bench`，
提交号 `12fa7cf`，与 r7 用的版本一致（Apache-2.0）。

## 阵容

- dsh 单 agent，模型 `opencode-go/muse-spark-1.3-contributor`，单次运行，无人值守。
- 每道题跑 3 次（全新工作区和容器），共 12 个 run；每个 run 时限 60 分钟；同时最多跑 2 个 run。
- 时限偏离声明：官方给 agent 的时限是 300 秒，这里放宽到 60 分钟，所有组以后都用同一个时限。
- 调用方式（base 预检通过）：`dsh.cmd --profile headless --patch <overlay> --json -`，
  task 走 stdin，cwd 即该题工作区；overlay 含 `llm-pi-ai` 行（opencode-go 取 `OPENCODE_GO_API_KEY`）
  和 `agent-default-model` 行，并禁用 web/子 agent 等原生工具；模型名已在会话记录里核对生效。
- 审批：shell 命令按 dsh 自动模式放行；出现等待人工审批的记为卡住，不替它批准。
- 不用 Claude 跑任何题；不读、不打印任何密钥。

## 主指标

- (a) 整题通过率：`test_outputs.py` 全部通过才算通过，与官方口径一致；
- (b) 部分得分：每题通过的测试数 / 测试总数，并给出 4 道题的平均值。

## 次指标（每个 run 记入 meta.json）

- "自称完成但没通过"的比例（agent 最后总结说已完成/已修好，而整题实际没通过）；
- 每个 run 的 token（输入、输出、缓存分开记）、墙钟时间、回合数或工具调用数；
- 编译警告（题面要求无警告的题）。

## 防作弊与执行（做法以任务书 T11a §2–§6 为准）

- 镜像 `docker build -t lb-tNN environment/`；参考解校验（solve.sh + tests/test.sh）先行，全过才开跑。
- 工作区 `D:\lb\ws\tNN-rK\`：从镜像导出整个 `/app`（含构建产物），不含 tests/solution/instruction.md；
  干净 git 单提交 `base`；长期容器 `lb-tNN-rK` 挂载工作区到 /app，cpus=1、内存 2GB。
- 包装命令 `D:\lb\bin\tNN-rK.cmd`（工作区之外），容器内 /app 执行，原样返回输出（截断 400 行）和退出码。
- 评测：tests/ 拷进容器跑 `pytest /tests/test_outputs.py -v -rA`，记 passed/total；对照总结判"自称完成"；
  统计 diff（文件数、行数、CRLF）；会话记录作弊扫描（legacy-bench、factory-ai、solve.sh、
  github.com、git clone、curl/wget 指代码托管站），命中照样计分、不剔除。
- 跑完删容器、保留镜像。