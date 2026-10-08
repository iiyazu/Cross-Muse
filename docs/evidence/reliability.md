# 可靠性证据：并发与故障恢复

xmuse 把多个 agent 的协作做成一个**持久化协议**：每个房间以 `chat.db` 为唯一权威；agent 的每次发言都必须绑定身份、尝试次数和租约（lease），并带幂等键；平台负责投递、因果、恢复，永远不替 agent 发言。这一页给出这套协议在并发和故障下的实测结果。

## 1. 并发正确性：`ci-sim`（每个 PR 都会跑，约 2 分钟可复现）

**设置**：12 个房间 × 每房 4 个 agent × 每房 20 轮人类消息，走生产路径（真实的 Room Kernel、Host、MCP 结果工具和 SQLite），只把 agent 换成脚本化 transport，所以不需要任何 API key。并发投递上限为 4。

**结果**（2026-10-08 本地一次运行，原始结果：[`data/ci-sim-2026-10-08.json`](data/ci-sim-2026-10-08.json)，schema `room_soak_chaos_result/v1`）：

| 指标 | 结果 |
|---|---|
| 因果链（correlation） | 240/240 全部结清 |
| 投递尝试 / 结果 | 1680 / 1680，一一对应 |
| **重复结果** | **0** |
| **跨房间身份串号 / 因果串线** | **0 / 0** |
| 孤儿 provider 进程、残留租约、未完成尝试 | 0 / 0 / 0 |
| 并发度 | 12 个房间同时发消息，最多 4 个投递同时进行（上限生效） |
| SQLite 完整性检查 | `ok` |
| 门禁 | 41 项中 22 项适用且全部通过，其余 19 项只适用于 live 档位，记为 not_applicable |
| 耗时 | 123.9 秒 |

延迟只反映调度排队，不代表真实模型的耗时：240 条消息一开始就全部进队，而投递并发上限是 4。post→claim p50 39.1 s / p95 64.5 s，post→settled p50 90.2 s / p95 102.9 s；前后两半的结清延迟分别是 p95 89.6 s 和 103.5 s，在稳定性门禁（284.1 s）之内。

复现：

```bash
uv sync --frozen --all-groups
uv run python scripts/room_soak_chaos.py ci-sim \
  --root /tmp/xmuse-ci-sim --result /tmp/xmuse-ci-sim.json --no-build-frontend
```

CI 里的同名 job（`room-ci-sim`）每个 PR 都会跑，并校验结果契约。

## 2. 故障恢复：v0.4.0 发布前的 45 分钟 soak

**设置**：3 个房间、4 个常驻 agent（真实 provider）、6 波消息，持续 45 分钟以上；期间注入四类故障：provider 进程 SIGKILL、Room Runner SIGKILL、MemoryOS SIGKILL、流缓存故障。

**结果**（见 [`docs/releases/v0.4.0.md`](../releases/v0.4.0.md)）：18/18 条因果链全部结清，共 159 次尝试。**重复结果、跨房间泄漏、孤儿 provider、恢复残留、工作区改动、浏览器控制台错误全部为 0**。结果文件的 SHA-256 是 `3e37af5a4866663183ab6cc2c0625b38ad7fb57f87dadcf99904d373c7031553`。原始对话、数据库和日志按设计不作为发布物。

## 3. 背后的机制（面试深挖用）

| 问题 | 机制 | 代码 |
|---|---|---|
| 同一条消息被重复投递，agent 回答两次 | 结果必须绑定 observation + attempt + 当前 lease，并带幂等 `client_request_id`；同键重放返回原结果，指纹不同则拒绝 | `src/xmuse_core/chat/room_kernel.py`（`submit_participant_outcome`） |
| Runner 崩溃，正在进行的投递成了"僵尸" | 尝试记录 runner 的 generation 和 boot id；新 runner 启动后围栏（fence）旧代的尝试，只有证明 provider 已清理（`cleanup_succeeded`）才立即重开，否则等租约过期 | `src/xmuse_core/chat/room_controls.py`、`room_host.py` |
| 迟到的结果覆盖新结果 | 租约过期或被取代后提交的结果一律拒绝（`room_observation_lease_lost`）；有的 provider（Antigravity）没有取消 API，这是最后的强约束 | `room_kernel.py` |
| 长任务超过固定超时 | 写代码的 owner 改用"长回合"策略：心跳续租、停滞检测、循环检测，硬上限 4 小时 | `room_host.py`（`LongTurnPolicy`） |
| 一轮里同一个 agent 收到多条相关消息，回应重复或乱序 | 按人类消息的因果链（correlation）把同一 agent 的多条观察合成一个不可变批次：分 root 和 peer 两个阶段，一个批次只有一次尝试、一个结果，其余成员只是镜像 | `room_batches.py` |
| agent 越权写文件或执行命令 | OpenCode 和 agy 跑在 bubblewrap 只读沙箱里（临时目录也固定在沙箱内，#466）；写代码的 owner 只能写自己的克隆，产出以补丁形式过主机门禁 | `room_opencode_sandbox.py`、`room_workspace_sandbox.py` |

## 4. 工程基线

- 后端测试用例 2500+（pytest 收集数，含参数化；`PYTHONWARNINGS=error`，Python 3.11 和 3.13），ruff 与 `mypy --explicit-package-bases` 全部通过。
- CI 6 项：`backend-quality`、`backend-contracts`、`backend-contracts-py3.13`、`frontend-quality`、`frontend-e2e`、`room-ci-sim`，全绿才能合并，main 开了 strict 保护。
- 关键修复都附带突变验证：撤掉修复后，对应的测试必须失败。

## 局限

- `ci-sim` 用脚本化 agent，只证明协议在并发下的正确性，不证明真实模型的行为。
- 45 分钟 soak 只跑过一次，是发布前的资格测试，不是长期稳定性数据。
- 单机、回环、单用户；MCP 端点做的是能力和署名校验，不是远程认证。
