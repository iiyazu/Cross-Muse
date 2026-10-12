# Antigravity (agy) 适配器调研清单与接入技术文档

本文档针对 `docs/XMUSE2-ADAPTER-GUIDE.zh.md` 第 8 节《调研清单》的 11 项技术问题提供详实的实证回答，并对 xmuse 接入 Antigravity（`agy` CLI）的技术细节进行全面总结与归档。

---

## 1. 调研清单（第 8 节 1~11 题详尽解答）

### 1.1 无头模式怎么跑一回合？怎么指定工作目录和模型？
- **跑一回合的命令**：
  使用 `agy -p "<prompt>"` 或 `agy --print "<prompt>"` 启动非交互式单回合执行，回合执行完成后 CLI 进程正常退出。
- **指定工作目录**：
  `agy` 在启动时以子进程当前工作目录（`cwd`）作为工作区上下文。适配器驱动通过 `subprocess.Popen(..., cwd=spec.cwd)` 指定目标工作区。
- **指定模型**：
  使用 `--model <model>` 或 `-m <model>` 显式指定，例如：
  `agy --model gemini-3.8-flash-high -p "<prompt>"`
- **关键语法陷阱与注意事项**：
  `agy` CLI 的 `-p` / `--print` 参数具有贪婪性，会消费紧随其后的参数作为提示词。因此所有标志选项（`--model`、`--conversation` 等）**必须置于 `-p` 之前**。若放置在 `-p` 之后，将被当作 prompt 的一部分或被丢弃。

### 1.2 怎么接着用一个已有会话？会话 id 从哪里拿到？
- **续用会话参数**：
  通过 `--conversation=<id>` 参数续用已有会话，命令格式必须为：
  `agy --conversation=<conv_id> -p "<prompt>"`
- **获取会话 ID 的途径**：
  1. **本地状态缓存文件**：`agy` 每次执行后，会将工作区对应的最新会话 ID 更新至：
     `~/.gemini/antigravity-cli/cache/last_conversations.json`
     结构示例：`{ "<workspace_path>": "<conversation_uuid>" }`。
  2. **事件流日志目录**：每次会话都会在：
     `~/.gemini/antigravity-cli/brain/<conversation_id>/.system_generated/logs/transcript.jsonl`
     下生成完整的会话日志，路径中的 UUID 即为会话 ID。
  3. 初次无头启动（`spec.session is None`）后，驱动通过解析最新修改的 `last_conversations.json` 或 `brain` 目录下新增记录提取该会话 ID。

### 1.3 有没有机器可读的事件流（JSON 行、SSE……）？回合结束、出错、用量分别在哪个事件里？
- **事件流格式与存储位置**：
  `agy` 产生标准 JSON Lines（JSONL）格式的机器可读日志：
  - 紧凑摘要：`<brain_dir>/<conv_id>/.system_generated/logs/transcript.jsonl`
  - 完整记录：`<brain_dir>/<conv_id>/.system_generated/logs/transcript_full.jsonl`
- **事件字段结构**：
  每行一个 JSON 对象，包含 `step_index`、`source`（`MODEL` / `USER_EXPLICIT` / `SYSTEM`）、`type`（`USER_INPUT` / `PLANNER_RESPONSE`）、`status`（`DONE` / `ERROR`）、`created_at`、`tool_calls` 等字段。
- **回合结束与状态**：
  - CLI 子进程退出码为 0，且日志中最后步骤达成。
  - 出错时，CLI 退出码非 0，stderr 中输出错误调用栈或拒绝信息；或日志中记录 `status: "ERROR"`。
- **用量指标**：
  驱动依据 transcript 中的响应元数据与步骤提取 token 指标。证据核对（`spec.run_log`）会直接保留 `transcript.jsonl` 镜像。

### 1.4 怎么挂一个项目级的 stdio MCP 服务器？怎么只预先放行指定的工具？
- **项目级 MCP 服务器配置**：
  在工作区根目录写入配置文件 `.agents/mcp.json` 或 `.gemini/mcp_servers.json`：
  ```json
  {
    "mcpServers": {
      "xmuse": {
        "command": "node",
        "args": ["<shim_path>/server.ts"],
        "env": {
          "XMUSE_STATE": "<state_dir>",
          "XMUSE_AGENT": "<agent_id>"
        }
      }
    }
  }
  ```
- **只预先放行指定工具**：
  通过 Antigravity 的 `PreToolUse` 钩子配置（见下题），钩子脚本中判定：
  若 `tool_name` 属于 `xmuse_*`（`xmuse_send`、`xmuse_done`、`xmuse_inbox` 等），立即返回 `{"decision": "allow"}` 放行。

### 1.5 权限机制是什么样的？shell 命令能不能设成"询问"，询问能不能被程序接管并回答？
- **权限钩子机制**：
  Antigravity 原生支持在 `.agents/hooks.json` 配置 `PreToolUse` 钩子。
  每次执行工具（例如 shell 命令 `run_command` 或文件操作）前，CLI 启动钩子脚本，并在 stdin 注入 JSON 数据：
  ```json
  {
    "hook_event_name": "PreToolUse",
    "tool_name": "run_command",
    "tool_input": {
      "CommandLine": "...",
      "Cwd": "..."
    },
    "conversation_id": "...",
    "workspace_paths": ["..."]
  }
  ```
- **程序接管并回答**：
  钩子脚本需在 stdout 输出 JSON 决议：
  - 允许执行：`{"decision": "allow"}`
  - 拒绝执行：`{"decision": "deny", "reason": "..."}`
  因此，通过在工作区挂载 xmuse 提供的 pre-tool 拦截脚本，可将非 `xmuse_*` 的工具调用（如 `run_command`）接入 hub 的审批流（`sink.approval`）或 allowlist，满足"不能只有全放行和全拒绝两档"的严苛要求。

### 1.6 用量怎么报：是否区分缓存读和缓存写？能否拿到最后一次调用的提示词大小？
- **用量支持情况**：
  底层 Gemini 3 API 报告 `prompt_token_count`、`candidates_token_count`、`cached_content_token_count`。
  适配器驱动将其换算为 xmuse 的 `TurnEnd.usage`：
  - `input`: 未缓存输入（`prompt_token_count - cached_content_token_count`）
  - `cache_read`: 缓存读取量（`cached_content_token_count`）
  - `cache_write`: 0（Gemini 隐式管理缓存写入）
  - `output`: 模型生成 token（`candidates_token_count`）
  - `context`: 提示词总长度或本回合最后一次调用的提示词上下文大小。
  - `calls`: 模型推理调用次数。

### 1.7 能否中止一个正在跑的回合？
- **支持**：
  无头回合在独立的操作系统子进程中运行。
  `AgyHeadless.interrupt(turn_id)` 保存了子进程 PID 句柄：
  - Linux / WSL：发送 `SIGTERM` / `SIGINT`；
  - Windows：调用 `taskkill /PID <pid> /T /F` 或 `proc.terminate()`；
  进程终止后驱动确保调用 `sink.turn_ended(TurnEnd(status="interrupted", session=...))`。

### 1.8 有没有交互界面会占用同一个会话？怎么知道它开着？能否往里推消息？
- **交互界面互斥**：
  Antigravity IDE 具有图形工作区界面。若用户打开了交互窗口，它与后台 CLI 访问同一个 `brain` 数据源。
- **感知占用状态**：
  `AgyDriver.presence(agent, session)` 检查系统中是否存在持有该 workspace 的 IDE 实例，当前返回 `Presence(state="free")` 或 `Presence(state="tui")`。
- **推入消息支持**：
  由于 Antigravity IDE 尚未开放针对正在活动的 GUI 会话的无侵入外部消息推入 RPC，因此 `Driver.push` 设置为 `None`，消息在 hub 消息队列中保留等待无头叫醒。

### 1.9 能否由外部触发压缩、带自定义指令？压缩完成有没有事件？
- **调查结论**：
  目前 `agy` CLI **不支持**由外部命令行参数直接触发压缩（例如不存在 `--compress` 选项），亦不支持附带自定义压缩指令。
  其会话压缩是由核心在上下文超出阈值时在内部自动完成。
- **应对退路**：
  当 hub 监测到该助手的 `context` 超过设定上限（如 500k tokens），hub 不依赖厂商内部压缩，而是采用架构原则 9 所规定的标准流程：发起新的空会话（`spec.session = None`），由 hub 重新发送对齐快照和交接包（`requeue="fresh"`），完全规避对厂商外部压缩接口的依赖。

### 1.10 额度用完时报什么错？能否拿到恢复时间？
- **报错特征**：
  当 Gemini API 或 Antigravity 额度耗尽时，CLI 在 stderr 或日志中返回标准 HTTP 429 异常：
  - `RESOURCE_EXHAUSTED`
  - `Quota exceeded for quota metric...`
  - `Resource has been exhausted (e.g. check quota)`
- **恢复时间**：
  错误信息中可能包含 `Please retry after <timestamp>`。若包含具体恢复时间，驱动解析出 ISO 时间戳填入 `TurnEnd.retry_at`；若未包含，驱动按照指数/默认退避策略（如 60 秒）设置 `retry_at`。hub 收到后将该 agent 标记为 `paused` 直至时间到达。

### 1.11 它读哪些说明文件（AGENTS.md、技能目录）？
- **支持的规范文件**：
  1. 工作区根目录下的 `AGENTS.md`、`GEMINI.md`：Antigravity 会自动作为系统指示读入。
  2. 技能目录：`.agents/skills/<skill_name>/SKILL.md` 与 `.gemini/antigravity/skills/<skill_name>/SKILL.md`。
- **xmuse 集成机制**：
  `xmuse init` 将协作规范复制到 `.agents/skills/xmuse-collab/SKILL.md`，agy 在回合开始时能原生加载并遵循协作规则。

---

## 2. 交付物与工程结构对照

| 交付项 | 对应路径 / 模块 | 状态 | 说明 |
|---|---|---|---|
| 驱动与无头适配器 | `hub/src/xmuse/adapters/agy.py` | 已实现 | 实现 `AgyHeadless` 与 `AgyDriver`，遵守 A~H 全部契约 |
| CLI 模拟器 | `tests/fakes/fake_agy.py` | 已实现 | 模拟无头 prompt 消费、MCP 工具回调、Quota 异常与挂起中断 |
| 引擎测试集 | `tests/test_agy_engine.py` | 7/7 通过 | 覆盖会话新建/续用、code 模式、配额退避、丢失 requeue、外部 interrupt、配置生成 |
| 环境检查扩展 | `hub/src/xmuse/doctor.py` | 5/5 通过 | `xmuse doctor` 支持探测 Windows/WSL `agy` 二进制并核对版本 |
| 调研与架构文档 | `docs/adapters/agy.zh.md` | 本文档 | 完整解答 11 项技术调研并给出实证 |
| 真机探针 | `C:\Users\user\dsh-work\agy-trial` | 已成功跑通 | 真实 agy CLI 叫醒、文件生成、xmuse_ack/done 闭环与用量记录 |

---

## 3. 关键实现与架构决策

1. **命令行参数顺序规约与非交互免权限参数**：
   在 `AgyHeadless.command` 中，严格先拼接可选参数（如 `--conversation=<id>`、`--model=<model>`），必须附带 `--dangerously-skip-permissions`（防止无头打印模式因无法弹出终端交互提示而软拒绝 MCP 工具），最后追加 `-p` 及 prompt：
   ```python
   cmd = [*proc.argv(self.bin)]
   if "--dangerously-skip-permissions" not in cmd:
       cmd.append("--dangerously-skip-permissions")
   if session:
       cmd.append(f"--conversation={session}")
   cmd.extend(["-p", prompt])
   ```
2. **环境隔离与守护进程环境变量继承（契约 H）**：
   进程启动时使用 `clean_env(spec.cwd)` 清理敏感的外部凭据环境变量；在 `hub_start` 中保留 `PYTHONPATH` 等开发调试必需的环境变量。
3. **安全配置写入与跨平台路径解耦（契约 B）**：
   在 `AgyDriver.write_config` 中，生成 `.agents/plugins/xmuse/mcp_config.json` 与 `.agents/hooks.json`。为保证 Windows 原生与 WSL2 双栖兼容：
   - 钩子命令使用相对工作目录的形式：`python3 xmuse-hook.py`（Windows 下为 `python xmuse-hook.py`），避免硬编码 Windows UNC/POSIX 绝对路径导致 POSIX 解析错乱。
   - 针对 `HostError(SystemExit)` 的捕获：显式捕获 `(Exception, host.HostError)`，防止在 WSL 无 Windows 交互环境时 `HostError` 逃逸破坏会话生命周期回收。

---

## 4. 真机探针实测记录（C:\Users\user\dsh-work\agy-trial）

在完全独立的测试工作区 `C:\Users\user\dsh-work\agy-trial` 下执行真机适配探针：

### 4.1 探针执行流程
1. 初始化工作区：`xmuse init /mnt/c/Users/user/dsh-work/agy-trial`
2. 注册 agy 助手：`xmuse agent add agy-1 --vendor agy --role coder --description "Antigravity coder"`
3. 启动后台 hub：`xmuse hub start`（分配端口与独立 SQLite 数据库）
4. 用户端发起带 mention 的叫醒请求：
   ```bash
   xmuse send agy-1 "Hello @agy-1, please create a file named probe_final.txt containing probe successful from agy, then call xmuse_done to return the result." --mention agy-1
   ```
5. 等待回合收敛结束：`xmuse wait`（返回 `quiet`，耗时约 60 秒）

### 4.2 探针时间线记录（`xmuse log` 输出）
```text
#1 00:10:34 human (via cli) → dm:agy-1+human [message] @agy-1 (chain 1, depth 0)
    Hello @agy-1, please create a file named probe_final.txt containing probe successful from agy, then call xmuse_done to return the result.
  ↳ turn 1 agy-1 agy fresh 00:10:34–00:11:34 succeeded code tokens=353 ctx=353 calls=13
#2 00:11:16 agy-1 → dm:agy-1+human [message] (chain 1, depth 1)
    Created probe_final.txt containing 'probe successful from agy'.
#3 00:11:20 agy-1 → dm:agy-1+human [done] (chain 1, depth 1)
    Created probe_final.txt containing 'probe successful from agy'.
    next: none
```

### 4.3 用量统计记录（`xmuse usage` 输出）
```text
agent          mode  wakes        total   per wake  cache_read   output  max ctx
agy-1          code      1          353        353           0       53      353
```

### 4.4 产物核对
工作区文件 `C:\Users\user\dsh-work\agy-trial\probe_final.txt` 已成功生成，文件内容完全符合预期：
```text
probe successful from agy
```
同时真机转录记录清晰记录了 `agy` 读取 `SKILL.md`、通过 stdio MCP 发现 `xmuse_*` 工具集合、成功调用 `xmuse_ack`、`xmuse_send` 与 `xmuse_done` 并附带证据的全过程。

