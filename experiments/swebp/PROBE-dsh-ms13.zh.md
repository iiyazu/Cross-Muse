# T10c 探针预注册：dsh 单 agent（opencode-go/muse-spark-1.3-contributor）在 SWE-Bench Pro Verified 试点题上的解决率

> 先写死再开跑。10 道题误差很大，这一步只是探针，不下结论。

## 选题

从 `experiments/swebp/ids-24-20261011.txt`（24 道，文件顺序）用 `random.Random(20261011).sample(ids, 10)` 取 10 道：

1. `instance_internetarchive__openlibrary-3c48b4bb782189e0858e6c3fc7956046cf3e1cfb-v2d9a6c849c60ed19fd0858ce9e40b7cc8e097e59`
2. `instance_future-architect__vuls-407407d306e9431d6aa0ab566baa6e44e5ba2904`
3. `instance_tutao__tutanota-fb32e5f9d9fc152a00144d56dd0af01760a2d4dc-vc4e41fd0029957297843cb9dec4a25c7c756f029`
4. `instance_future-architect__vuls-fd18df1dd4e4360f8932bc4b894bd8b40d654e7c`
5. `instance_flipt-io__flipt-518ec324b66a07fdd95464a5e9ca5fe7681ad8f9`
6. `instance_NodeBB__NodeBB-18c45b44613aecd53e9f60457b9812049ab2998d-v0495b863a912fbff5749c67e860612b91825407c`
7. `instance_navidrome__navidrome-29bc17acd71596ae92131aca728716baf5af9906`
8. `instance_qutebrowser__qutebrowser-8cd06741bb56cdca49f5cdc0542da97681154315-v5149fcda2a9a6fe1d35dfed1bade1444a11ef271`
9. `instance_qutebrowser__qutebrowser-f91ace96223cac8161c16dd061907e138fe85111-v059c6fdc75567943479b23ebca7c07b5e9a7f34c`
10. `instance_NodeBB__NodeBB-0f788b8eaa4bba3c142d171fd941d015c53b65fc-v0ec6d6c2baf3cb4797482ce4829bc25cd5716649`

工作区目录只用 `t01`…`t10` 编号（按上表顺序），不出现 instance_id、仓库名或提交号。

## 阵容

- dsh 单 agent，模型 `opencode-go/muse-spark-1.3-contributor`，单次运行，无人值守。
- 每题上限 60 分钟；同时最多跑 2 道题。
- 审批：shell 命令按 dsh 自动模式放行；出现等待人工审批的记为卡住，不替它批准。
- 工作目录为该题工作区；不用用户主目录或 C:\ 根目录；不改 dsh 全局配置，需要配置只用单次运行的 overlay。
- 不用 Claude 跑任何题；不读、不打印任何密钥。

## 主指标

解决率 = 官方评测（`swe_bench_pro_eval.py`，`--use_local_docker --dockerhub_username=jefzda`）中 FAIL_TO_PASS 和 PASS_TO_PASS 都通过的题数 / 10。

## 判定规则（事先写死）

- 解决率 ≤ 7/10 → 题目集可用；
- 解决率 = 8/10 → 灰区，扩大到 24 道题再判；
- 解决率 ≥ 9/10 → 题目集偏容易，换更难的一层。
- 每个 run 都算，不挑题、不重跑刷分。

## 次指标（每题记入 meta.json）

模型、dsh 版本、开始/结束时间、墙钟时间、token（输入、输出、缓存分开）、回合数或工具调用数、退出状态、patch 改动行数和文件数、CRLF 检查结果、作弊扫描命中情况。

## 防作弊与包装（做法在任务书 T10c §2–§3， Discipline 不变）

- 容器 `swebp-tNN`（`docker run -d --name swebp-tNN <镜像> sleep infinity`，不加 `--rm`），`/app` 复位到 `base_commit`（`git reset -q --hard`，不 `git clean`）。
- 工作区只取 `git archive <base_commit>` 的被跟踪源码，放 `D:\swebp\ws\tNN\`；干净 git 单提交 `base`；不给 agent 上游地址和 instance_id。
- 包装命令 `D:\swebp\bin\tNN-test.cmd`（工作区之外）：WSL 生成 patch → 容器撤旧 patch → 套新 patch → 容器内执行（先 export Dockerfile ENV，照抄 harness 的提取方法）→ 返回输出（截断 400 行）和退出码。先用参考答案 patch 自测通过再给 agent 用。
- 评测输出到 `BENCH_DIR/pilot/probe-dsh-ms13/`；跑完删容器、保留镜像。