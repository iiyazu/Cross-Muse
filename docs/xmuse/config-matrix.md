# xmuse Config Matrix

更新日期: 2026-06-04

## 范围与分类

本矩阵枚举 xmuse 代码库中**所有已实现的配置入口**。按其用途分为 5 类:

| 分类 | 说明 | 示例 |
|------|------|------|
| **required** | 运行时必需。缺失导致功能不可用 | `DEEPSEEK_API_KEY` |
| **optional** | 有默认值，可按需覆盖 | `XMUSE_ROOT`, `XMUSE_RAY_GOD_EFFORT` |
| **legacy** | 旧流程或已降级路径，非当前主链 | `XMUSE_REVIEW_GATE`, `XMUSE_REVIEW_CODEX_CMD` |
| **injected** | xmuse 运行时设给子进程，不从外层 env 读取 | `XMUSE_FEATURE_ID`, `XMUSE_LANE_ID` |
| **frontend-only** | 仅供旧 browser frontend 引用，不在 Python 代码中读取 | `NEXT_PUBLIC_XMUSE_*` |

## 环境变量

### Runtime Root (required at runtime)

| 变量 | 分类 | 默认 | 读取位置 | 缺失行为 |
|------|------|------|----------|----------|
| `XMUSE_ROOT` | optional | 各入口调用 `default_xmuse_root()` | `src/xmuse_core/runtime/paths.py:17` | 各入口以 `./xmuse` 为 fallback |

### Provider / Model (required at runtime)

| 变量 | 分类 | 默认 | 读取位置 | 缺失行为 |
|------|------|------|----------|----------|
| `XMUSE_CODEX_MODEL` | optional | `"gpt-5.4"` | `chat/driver.py:101`, `platform/execution/executor.py:748`, `platform/execution/review_god.py:1165`, `platform/agent_spawner.py:118-120` | 使用默认 |
| `DEEPSEEK_API_KEY` | **required** | — | `providers/registry.py:25`, `providers/adapters/opencode.py:218,231-234,368` | 健康检查报 `CONFIG_ERROR`，adapter 返回 `UNAVAILABLE` |
| `DEEPSEEK_MODEL` | optional | `"deepseek-v4-flash"` | `providers/registry.py:23` | 使用默认 |
| `DEEPSEEK_BASE_URL` | optional | None | `providers/registry.py:24` | 不使用 |

### Runtime Backend / GOD (required for groupchat)

| 变量 | 分类 | 默认 | 读取位置 | 缺失行为 |
|------|------|------|----------|----------|
| `XMUSE_RUNTIME_BACKEND` | optional | `"ray"` | `platform/read_envelopes.py:206` | fallback "ray" |
| `XMUSE_REVIEW_GOD_BACKEND` | optional | `"ray"` | `xmuse/platform_runner.py:142` | fallback "ray" |
| `XMUSE_EXECUTE_GOD_BACKEND` | optional | `"ray"` | `xmuse/platform_runner.py:161` | fallback "ray" |
| `XMUSE_PEER_GOD_BACKEND` | optional | `"ray"` | `xmuse/platform_runner.py:210` | fallback "ray" |
| `XMUSE_DEGRADED_LOCAL_GOD_MODE` | optional | disabled | `xmuse/platform_runner.py:832` | 禁用 |
| `XMUSE_RAY_GOD_TRANSPORT` | optional | `"app-server"` | `src/xmuse_core/agents/ray_session_layer.py:377` | fallback "app-server" |
| `XMUSE_RAY_GOD_EFFORT` | optional | `"low"` | `src/xmuse_core/agents/ray_session_layer.py:387` | fallback "low" |
| `XMUSE_RAY_GOD_MCP` | optional | `"0"` (off) | `src/xmuse_core/agents/ray_session_layer.py:395` | 关闭 |

### Orchestrator Control (optional)

| 变量 | 分类 | 默认 | 读取位置 | 缺失行为 |
|------|------|------|----------|----------|
| `XMUSE_RECONCILE_GATE_REVIEW_CONCURRENCY` | optional | unlimited | `platform/orchestrator.py:165,216` | 无效值回退到 16 |
| `XMUSE_RECOVERY` | optional | (空=默认) | `platform/orchestrator.py:198` | 使用 `RecoveryConfig` 默认值 |

### TUI / Dashboard (optional)

| 变量 | 分类 | 默认 | 读取位置 | 缺失行为 |
|------|------|------|----------|----------|
| `XMUSE_CHAT_API_URL` | optional | `"http://127.0.0.1:8201"` | `xmuse/tui/adapter/xmuse_adapter.py:32-33` | 硬编码 fallback |
| `XMUSE_SUPERPOWERS` | optional | disabled | `src/xmuse_core/skills/superpowers_bridge.py:17` | 禁用 |

### Legacy — master_loop + hermes_reporter + scripts (非当前主链)

这些变量是旧 master_loop、hermes_reporter 和 shell 脚本的配置。当前群聊主链不依赖它们。

| 变量 | 默认 | 读取位置 |
|------|------|----------|
| `XMUSE_REVIEW_GATE` | `"1"` (enabled) | `xmuse/master_loop.py:273` |
| `XMUSE_REVIEW_CODEX_CMD` | `"codex"` | `xmuse/master_loop.py:279` |
| `XMUSE_REVIEW_MODEL` | `"gpt-5.5"` | `xmuse/master_loop.py:280` |
| `XMUSE_REVIEW_TIMEOUT_S` | `"300"` | `xmuse/master_loop.py:281` |
| `XMUSE_LOOP_ROOT` | `hermes_reporter.py` 父目录 | `xmuse/hermes_reporter.py:12` |
| `XMUSE_REPORT_ONLY` | `""` (full mode) | `xmuse/hermes_reporter.py:281` |
| `XMUSE_MAX_HOURS` | `"10"` | `xmuse/overnight_runner.sh:9` |
| `XMUSE_MONITOR_INTERVAL_SECONDS` | `"600"` | `xmuse/scheduler_monitor.sh:7` |
| `XMUSE_MONITOR_LOG_FILE` | `"/tmp/xmuse_scheduler_monitor.log"` | `xmuse/scheduler_monitor.sh:8` |
| `XMUSE_MONITOR_PID_FILE` | `"/tmp/xmuse_scheduler_monitor.pid"` | `xmuse/scheduler_monitor.sh:9` |
| `XMUSE_MONITOR_LOCK_FILE` | `"/tmp/xmuse_scheduler_monitor.lock"` | `xmuse/scheduler_monitor.sh:10` |

### Frontend-only — NEXT_PUBLIC_XMUSE_* (Python 代码不读取)

仅在 `xmuse/FRONTEND_API.md` 和 `xmuse/FRONTEND_IMPLEMENTATION_GUIDE.md` 中作为前端配置说明出现。

| 变量 | 值 |
|------|-----|
| `NEXT_PUBLIC_XMUSE_CHAT_API_BASE_URL` | `http://localhost:8201/api/chat` |
| `NEXT_PUBLIC_XMUSE_API_BASE_URL` | `http://localhost:8200/api` |
| `NEXT_PUBLIC_XMUSE_MCP_ENDPOINT` | `http://localhost:8100/mcp` |

### 运行时注入（xmuse 设给子进程）

| 变量 | 设置位置 |
|------|----------|
| `XMUSE_FEATURE_ID` | `providers/adapters/codex.py:248`, `providers/service.py:199`, `agents/launchers/claude_code.py:26` |
| `XMUSE_GOD_NAME` | `platform/agent_spawner.py:160` |
| `XMUSE_LANE_ID` | `platform/agent_spawner.py:161` |
| `XMUSE_MCP_URL` | `platform/agent_spawner.py:162` |
| `XMUSE_GOD_MODEL` | `platform/agent_spawner.py:164` |
| `XMUSE_WORKER_MODEL` | `platform/agent_spawner.py:166` |
| `XMUSE_DELEGATION_MODE` | `platform/agent_spawner.py:168` |
| `XMUSE_TRACE_ID` | `platform/agent_spawner.py:171` |
| `XMUSE_REQUEST_ID` | `platform/agent_spawner.py:173` |
| `XMUSE_GRAPH_ID` | `platform/agent_spawner.py:177` |
| `OPENCODE_CONFIG_CONTENT` | `providers/adapters/opencode.py:96` |

## Production 群聊最小 env bundle

V7 真实 groupchat MCP writeback 主链必须设置以下变量。这是当前权威生产配置模板:

```bash
# runtime backend
XMUSE_PEER_GOD_BACKEND=ray
XMUSE_EXECUTE_GOD_BACKEND=ray
XMUSE_REVIEW_GOD_BACKEND=ray
# Ray GOD session transport
XMUSE_RAY_GOD_TRANSPORT=app-server
XMUSE_RAY_GOD_EFFORT=low
XMUSE_RAY_GOD_MCP=1
# optional: TUI endpoint
XMUSE_CHAT_API_URL=http://127.0.0.1:8201
```

此 bundle 的目的是确保:
- Ray 作为 GOD 持久 session backend
- Codex app-server 作为 transport（非 process-json batch）
- MCP writeback 开启（`XMUSE_RAY_GOD_MCP=1` — 这是真实 MCP writeback gate；默认 off 避免普通 Ray session 意外暴露 MCP）
- 其余使用各自默认值

## CLI 参数（platform_runner）

| 参数 | 类型 | 默认 |
|------|------|------|
| `--xmuse-root` | Path | `$XMUSE_ROOT` 或 `./xmuse` |
| `--lanes` | Path | `<xmuse-root>/feature_lanes.json` |
| `--mcp-port` | int | `8100` |
| `--max-hours` | float | `8.0` |
| `--max-concurrent` | int | `4` |
| `--god-runtime` | str | `"codex"` |
| `--chat-driver-model` | str | `"gpt-5.4"` |
| `--health-once` | flag | false |
| `--health-check-http` | flag | false |
| `--stale-after-s` | float | `1800.0` |

完整列表参见 `xmuse/platform_runner.py:924-1071`。

## 端口绑定

| 端口 | 服务 | 默认 | 是否可配 |
|------|------|------|----------|
| 8100 | MCP Server | 8100 | `--mcp-port` (6 处) |
| 8200 | Dashboard API | 8200 | 否（硬编码常量） |
| 8201 | Chat API | 8201 | 否（硬编码常量） |
| 3000 | CORS allow origin | 3000 | 否（3 处硬编码） |

## 硬编码常量

| 常量 | 值 | 位置 |
|------|-----|------|
| `WORKTREE_BASE` | `~/.config/superpowers/worktrees/memoryOS` | `src/xmuse_core/platform/orchestrator.py:164` |
| `DEFAULT_STALE_AFTER_S` | `1800.0` | `src/xmuse_core/platform/run_health.py:64` |
| `WRITER_LEASE_TTL_S` | `60.0` | `xmuse/platform_runner.py:53` |
| `SAFE_RECONCILE_GATE_REVIEW_CONCURRENCY` | `16` | `src/xmuse_core/platform/orchestrator.py:166` |

## 凭证/密钥

| 密钥 | 类型 | 来源 | 处理方式 |
|------|------|------|----------|
| `DEEPSEEK_API_KEY` | API key | 环境变量 | OpenCode adapter 必填；缺失报 `CONFIG_ERROR` |
| MemoryOS `X-API-Key` | API key | `MemoryOSClient.api_key` 参数（Optional） | 无人传入，当前实际不使用 |
| `CallbackCredentials` token | UUID | 内存生成 | 进程重启后失效 |

## 关键发现

1. **中央配置尚未接管全部调用点** — `src/xmuse_core/runtime/settings.py` 已提供
   `Settings(BaseSettings)` 和 `.env` 加载，但配置仍分散在 20+ 文件和 4 个 shell
   脚本，许多入口继续直接读取 `os.environ`。
2. **`python-dotenv` 仍无直接 import** — `.env` 加载当前通过 `pydantic-settings`
   overlay 完成；本矩阵不声明所有 runtime 已迁入该 overlay。
3. **所有 API 无认证** — Chat API / MCP / Dashboard 无 auth 中间件，CORS 是唯一保护
4. **只有 `DEEPSEEK_API_KEY` 是真正的"密钥"** — Codex 不需要 env（只要求 binary 在 PATH）
5. **多路径模型选择** — env var + CLI args + profile ref 三套机制，优先级未显式文档化
6. **端口分散** — 8100 作为默认值出现在 6+ 个独立位置
7. **shell 脚本配置未纳入统一管理** — `scheduler_monitor.sh` 和 `overnight_runner.sh` 有自己的 `XMUSE_MONITOR_*` 和 `XMUSE_MAX_HOURS` 体系

## Path A 使用说明

- 本矩阵支撑 Path A **Phase 2（Runtime 可运营）** 和 **Phase 3（质量门禁）**
- 不作为 Phase 1（独立安装验证）的 gate — Path A Phase 1 默认只需要 `$XMUSE_ROOT`；`$DEEPSEEK_API_KEY` 仅用于 OpenCode/provider smoke
- Phase 2 runtime operations 使用 `uv run xmuse-platform-runner --health-once --health-check-http --mcp-port 8100` 输出 `operations` health block，检查 Chat API、MCP、runner、Ray GOD layer、Codex app-server、durable state、scheduler progress 和 cleanup leftovers。
- Phase 2 不启动 CI/type gate，不强制 provider matrix enforcement。
