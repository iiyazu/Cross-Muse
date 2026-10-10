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

## dsh desktop (foreground) mode

Lets the user see and steer dsh's work: the dsh agent lives in a dsh desktop session that the hub never runs. (The hub's
background dsh runner cannot continue sessions created in the desktop app, and headless sessions never show in the
desktop sidebar.)

1. Put the workspace under `/mnt/<drive>/`, then `xmuse init <workspace>` and
   `xmuse agent add dsh-1 --vendor dsh --desktop` (stores `{"foreground": true}`; running it again updates the settings
   and re-renders files, the token stays). `--desktop` on dsh means foreground; on claude it still means the coordinator.
2. `xmuse hub start`, then open the workspace in the dsh desktop app and start a session. The generated `AGENTS.md`
   section (`<!-- xmuse:fg dsh-1 ... -->`) holds the exact commands, with this machine's python and workspace paths baked in.
3. The loop the agent follows: start `xmuse watch --agent dsh-1 --once` as a background task (its completion wakes the
   session); when woken, run `xmuse tool --agent dsh-1 inbox`, do the work, reply with
   `xmuse tool --agent dsh-1 send --args-file .xmuse-tmp/send.json`, `ack`, and start the watch again.

Details:

- `watch --once` prints deliveries that are already unread and unacked right away and exits 0; otherwise it blocks for
  the first new delivery. It exits 1 ("hub stopped") if the hub goes away. It is read-only.
- `xmuse tool --agent <id> <name> [--args-file PATH]` calls `/v1/tools/xmuse_<name>` with that agent's token and prints
  the JSON result (non-zero exit with the error otherwise). Arguments come from the file or piped stdin, as UTF-8 (BOM or
  not) or BOM-marked UTF-16 (Windows PowerShell). Message text goes through the file, never the wsl.exe command line.
- The engine never wakes a foreground agent, and `hub status` shows `"foreground": true` and `"pending": n`. The
  coordinator-only behaviors (hub notices cc'd, `on_behalf_of`, prompt injection) do not apply to it.
- No dsh presence hooks are written for a foreground agent (they would register the desktop session as the agent's
  current session for the hub to continue); stale ones are removed. `.xmuse-tmp/` is git-excluded.
