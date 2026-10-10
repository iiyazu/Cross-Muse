# xmuse hub

Hub and CLI for xmuse 2 (see the design notes for the architecture). This file only documents setup that is not
obvious from `xmuse --help`.

## Claude desktop app

Run a Claude agent from the Claude desktop app (Windows) against a workspace in WSL.

1. `xmuse init <workspace>` (once), then `xmuse agent add <id> --vendor claude --desktop`. This writes a
   project `.mcp.json` and `.claude/settings.json` whose commands go through `wsl.exe -d <distro> -- ...`
   (distro from `WSL_DISTRO_NAME`, default `Ubuntu-24.04`). No channel is configured.
2. `xmuse hub start`.
3. In the desktop app open the workspace (`\\wsl.localhost\<distro>\...`, `xmuse attach <id>` prints the exact
   path), trust it, and enable the project MCP server `xmuse`.
4. Start a new session and call `xmuse_whoami` to verify.
5. Optional: if the session has a Monitor tool, run the command that `xmuse attach <id>` prints on its second line
   (`wsl.exe -d <distro> -- <python> -m xmuse --ws <workspace> watch --agent <id>`); it prints a line whenever
   new messages arrive for the agent, without marking anything read.

Limits:

- No push. The hub never wakes a desktop agent in the background (messages queue and count in the inbox). The
  `UserPromptSubmit` hook prints a reminder when messages are pending; the agent must start every turn with
  `xmuse_inbox` and call `xmuse_ack` when done. `xmuse watch` adds near-real-time notices where a Monitor exists.
- Desktop sessions live on the Windows side, so the hub cannot `--resume` them; a desktop session cannot continue
  in the background.
- One interactive Claude identity per workspace: adding a desktop agent replaces the CLI-mode config (a note is
  printed).
- The desktop app must trust the workspace and enable the project MCP server; if it ignores the project hooks or
  `.mcp.json`, the agent simply works without the reminder or the tools.
- `xmuse hub status` shows `"desktop": true` and `"pending": n` for these agents.
