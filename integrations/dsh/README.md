# xmuse board — dsh 包

只读查看 xmuse 协作看板。Decisions stay in the Web：审批、复核结论等所有写操作都在浏览器 UI 里完成，这里只能看。

dsh（`@deepseek-ai/dsh`）目前是 developer preview：可能有 breaking changes，接入前请对照当前 dsh 文档核实技能目录和钩子桥的用法。

## 安装技能

把 `skills/xmuse-board` 复制到任一技能目录：

```sh
cp -r integrations/dsh/skills/xmuse-board <project>/.agents/skills/
# 或 ~/.agents/skills/，或 <project>/.dsh/skills/
```

当用户问起看板状态、模块状态、待审批或待复核事项时调用。技能只运行 `xmuse-ctl status` / `board` / `watch --once` 等只读命令，原样报告清洗后的数据。

## 要求

- `xmuse-ctl` 必须在 PATH 上（从本仓库安装，例如 `uv tool install ./integrations/xmuse-ctl` 或 `pipx install ./integrations/xmuse-ctl`）。
- 环境变量：`XMUSE_API_BASE`（默认 `http://127.0.0.1:8201`，仅回环地址），`XMUSE_WEB_BASE`（默认 `http://127.0.0.1:3000`，用于拼接 Web 链接）。
- 在项目目录里运行 `xmuse-ctl attach` 绑定房间（先 `xmuse-ctl rooms` 查看也行）。

## 可选的钩子（默认关闭）

用 `@deepseek-ai/dsh-hooks-claude-code` 桥挂载 `hooks.claude.json`，示例见 `cordis.example.yml`（opt-in：不挂载就没有钩子）。桥会在 `UserPromptSubmit` 和 `SessionStart` 时运行 `xmuse-ctl hook --host dsh --event <Event>`：只有当有待你处理的事项、且事项集合自上次提醒变化超过 30 秒时，才返回一行 `[xmuse] …` 状态（`status` 一行文本加最多 3 个待办标签，总长 ≤ 300 字符）作为 `additionalContext`。注入的是计数、状态码和固定标签，never agent text：模块标题、复核意见等一律不会进入模型上下文。其他情况钩子输出 `{}`，什么都不注入。

## 只读和无 agent 文本保证

- 本包只调用 `xmuse-ctl` 的只读命令（loopback `GET`，无 token、无请求体）。
- Decisions stay in the Web：需要决定的事项请打开 `board` 输出的 Web 链接处理。

## 以后可能：Claude Code mod 桥

dsh 还有一个实验性的 Claude Code mods 桥，将来它稳定后可以直接跑本仓库现有的 Claude Code mod，在提示词上方得到一条真正的 band（本包不做、也不测试）。目前先用上面的技能加可选钩子。
