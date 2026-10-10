# xmuse dsh bundle（冒烟版 0.0.1）

dsh 桌面端原生插件（Host 插件，纯 ESM，不需要构建），只为回答几个"能不能"的问题，不是正式集成。

## 它做什么

- 斜杠命令 `/xmuse`：
  - `ping`：用 dsh-schedule 同样的路径往**当前会话**投递一条 follow-up 用户消息
    （`sessionController.resolveAgent` → `agent.followup(createUserMessage({source:{kind:'xmuse'}}))` → `sessions.flush`），
    内容 `[xmuse] smoke delivery <ISO 时间>: reply "pong" in one line.`
  - `bind <agent-id>`：把当前会话绑定到 hub 里的 agent（内存 + 同目录 `bindings.json`）。
  - `status`：显示启动自检（`sessionController` / `sessions` / `commands` 是否存在、hub 状态目录是否可读）和绑定表。
- 模型工具 `xmuse_whoami`：每个会话在 `agent/created` 注册；调用时才查绑定，已绑定则用该 agent 的 token 调 hub
  `POST /v1/tools/xmuse_whoami`，未绑定则提示先 `/xmuse bind <agent>`。
- 所有回调都有 try/catch，不会抛出未处理的 Promise rejection。
- 配置只有一个 `state`（hub 状态目录，默认 `\\wsl.localhost\Ubuntu-24.04\home\user\.local\state\xmuse\xmuse-desk-c9ddc1e5`，
  在 `cordis.patch.yml` 里）。插件只读 `hub.json`（端口）和 `tokens/<agent>`，token 不进配置也不进日志。

## 安装（用户自己操作）

1. 源码在 WSL：`~/dev/xmuse2-dshb/integrations/dsh-bundle/`。运行 `bash sync.sh` 把它同步到
   `C:\Users\user\dsh-work\xmuse-bundle`（不含 test、node_modules；已有的 `bindings.json` 会保留）。
2. dsh 桌面端：**插件 → 添加插件**，路径填 `C:\Users\user\dsh-work\xmuse-bundle`。
3. 在 `C:\Users\user\xmuse-desk` 打开一个会话来测（hub 要在运行：`hub.json` 里的端口可连）。

## 冒烟清单

在上述工作区的 dsh 桌面会话里依次执行，并记录现象：

1. `/xmuse status`：命令在 `/` 弹出菜单里有吗？自检里 `sessionController`、`sessions.flush` 是 yes 吗？`hub state` 是 `ok (port …)` 吗？`bindings file` 是否 ok？
2. `/xmuse ping`：会话被唤醒并回复 `pong` 吗？这条消息在 UI 里怎么渲染（预期：可折叠的"收到执行请求"触发卡，而不是用户气泡）？会话正在跑时再 ping 一次，会排队吗？
3. `/xmuse bind dsh-1`：返回确认；再 `/xmuse status` 能看到绑定；检查 `C:\Users\user\dsh-work\xmuse-bundle\bindings.json` 是否生成。
4. 对模型说"调用 xmuse_whoami 工具并把结果原样告诉我"：应返回 `{"id":"dsh-1",...}`。绑定前（新会话）调用应得到"先运行 /xmuse bind"的提示。这也验证了绑定发生在 `agent/created` 之后仍然生效。
5. 日志（dsh 的插件/应用日志）里查 `xmuse: self-check ...` 那一行。

## 这次冒烟要回答的问题

1. 本地绝对路径（`C:\...`）安装能成功吗？`pnpm add` 用的是链接（`link:`）还是拷贝？
2. 改了源码、重新 `sync.sh` 之后，需要重启 dsh 吗（官方说替换已装包要重启）？链接方式 + HMR 能否免重启？
3. 不声明 `Config` 时，`cordis.patch.yml` 里的 `config.state` 会不会原样传给 `apply(ctx, config)`？（`status` 里显示的 `state dir` 可以看出来；若是默认值则说明没传到。）
4. 自定义 `source.kind: 'xmuse'` 的 follow-up：UI 渲染成什么？冷会话（已关闭的会话）能被 `resolveAgent` 恢复并唤醒吗？
5. 原生工具在桌面 `standard` 预设会话里对模型可见吗？
6. Windows 进程能读 `\\wsl.localhost\...` 下的 hub 状态并连上 `127.0.0.1:<port>` 的 hub 吗？有没有被代理拦截？
7. `/xmuse` 命令会不会出现在 `/` 菜单里？

## 开发

```
cd integrations/dsh-bundle
node --check index.js
npm test        # = node --import ./test/register.mjs --test test/bundle.test.mjs
```

测试用 fake ctx、fake hub（本地 HTTP 服务），并通过 `test/hooks.mjs` 把 `@deepseek-ai/*` 三个导入指向 `test/stubs/`。

## 已知不确定项

- 没有 `.d.ts`，API 形状（`resolveAgent` 返回 `{agent}`/`{error}`、`ctx.effect` 接受返回清理函数的回调、`ctx.logger.info/warn`、命令 handler 返回 `{kind,text}`）来自 dsh 0.2.0-rc.2 的编译产物和官方指南，未在真实 dsh 里验证。
- `@deepseek-ai/dsh-commands/brand`、`dsh-llm`、`dsh-tools` 靠 dsh 运行时解析（与官方插件同样的做法），bundle 不声明依赖和 peerDependencies。
