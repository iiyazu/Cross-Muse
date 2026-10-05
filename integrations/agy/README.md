# xmuse board — agy 插件

只读查看 xmuse 协作看板。Decisions stay in the Web：审批、复核结论等所有写操作都在浏览器 UI 里完成，这里只能看。

## 安装

```sh
agy plugin install integrations/agy
```

或把 `integrations/agy` 复制到 agy 的插件目录下。

## 要求

- `xmuse-ctl` 必须在 PATH 上（从本仓库安装，例如 `uv tool install ./integrations/xmuse-ctl` 或 `pipx install ./integrations/xmuse-ctl`）。
- 环境变量：`XMUSE_API_BASE`（默认 `http://127.0.0.1:8201`，仅回环地址），`XMUSE_WEB_BASE`（默认 `http://127.0.0.1:3000`，用于拼接 Web 链接）。

## 绑定房间

在项目目录里运行一次：

```sh
xmuse-ctl attach
```

这会把当前目录绑定到最近的有模块的房间（或用 `xmuse-ctl rooms` 查看后 `xmuse-ctl attach <prefix>` 指定）。

## 技能

`skills/xmuse-board/SKILL.md`：当用户问起看板状态、模块状态、待审批或待复核事项时调用。技能只运行 `xmuse-ctl status` / `board` / `watch --once` 等只读命令，原样报告清洗后的数据。

## 可选的状态钩子（默认关闭）

`hooks.json` 里只有一个钩子 `xmuse-status`，`"enabled": false`。启用方式：把 `"enabled"` 设为 `true`，或在插件设置里打开。

启用后，每次调用前会运行 `xmuse-ctl hook --host agy`：只有当有待你处理的事项、且事项集合自上次提醒变化超过 30 秒时，才注入一行 `[xmuse] …` 状态（`status` 一行文本加最多 3 个待办标签，总长 ≤ 300 字符）。注入的是计数、状态码和固定标签，never agent text：模块标题、复核意见等一律不会进入模型上下文。其他情况钩子输出 `{}`，什么都不注入。

## 只读保证

- 插件只调用 `xmuse-ctl` 的只读命令（loopback `GET`，无 token、无请求体）。
- Decisions stay in the Web：需要决定的事项请打开 `board` 输出的 Web 链接处理。

## 验证

```sh
agy plugin validate integrations/agy
```
