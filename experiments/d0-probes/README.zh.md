# D0 探针（xmuse 侧栏方案可行性实测）

只用于验证可行性，**不是产品代码**。

| 目录/文件 | 对应报告 | 内容 |
|---|---|---|
| `claude-probe/` | A | Claude Code mod 探针：`$.http.fetch`、`$.clock.every`、`$.prompt.submit`、`$.session.id`、`/xmuse` 命令、Pane/AbovePrompt（Input/Select/Button/Markdown）、`probe.test.ts`（`claude plugin test`） |
| `opencode-probe/` | B | OpenCode 2.x TUI 插件探针（`@opencode/plugin/tui`）：sidebar.content 插槽、`/xmuse` 斜杠命令带参数、toast、定时器、HTTP |
| `dsh-drawer-probe/` | C | dsh 插件探针：宿主侧路由 `/xmuse-probe/*` 转发到回环 hub，浏览器侧可收起抽屉；`test/host-proxy.mjs` 是假宿主测试 |
| `http-echo-server.js` | A/C | 最小 HTTP 回显服务（记录每个请求），`node http-echo-server.js <port> <host> <logfile>` |
| `pty-run.py` | A/B | 在伪终端里驱动交互式 TUI（claude / opencode）并截屏成文本 |
| （未公开） | 全部 | 实测时用的 shell 脚本路径写死为作者机器，没有公开 |

注意：

- `claude-probe` 把日志写到 `<插件根>/../out/claude-probe.log`，配置读 `<插件根>/../out/config.json`（不在仓库里，运行前自建，格式见 `claude-probe/hooks/register.tsx` 开头注释）。
- 探针不含任何令牌；OpenCode 实测用的是临时 XDG 目录和随机密码（不在仓库）。
- 不要把这些目录装进用户的正式插件目录；用法见报告末尾的"用户手动核对清单"。
