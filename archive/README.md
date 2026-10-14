# archive

Historical artifacts, moved here on 2026-10-11 (T7) with `git mv`, so `git log --follow` still shows their history. Nothing here is maintained, imported by the hub, or run by the tests.

| Path | What it was |
|---|---|
| `spikes/` | M0/M1 probes: vendor wake paths (Claude channel and `-p --resume`, OpenCode serve + SSE, dsh headless), cost and usage scripts. Removed from the public history (recorded runs and machine-specific scripts); `cc-tree.py` and `cc-usage.py` were ported into `hub/src/xmuse/adapters/claude.py`. |
| `e2e/` | The M1 end-to-end harness (shell scenarios, seeds, hidden tests), replaced by `experiments/`. Its recorded results were removed from the public history. Its `check.py` is still used, as `experiments/check.py`. |
| `claude-mod-t0/`, `opencode-plugin-t0/` | The per-vendor sidebars of 10-11 (T0: a Claude Code mod and an OpenCode TUI plugin on the view API). Moved here on 2026-10-13: on 10-12 the direction changed to one Claude session as coordinator with the panel in `integrations/xmuse-panel/`, the other agents as assistants. Their own tests still run against `tools/mock-hub` (same relative path). The dsh drawer of the same plan (`integrations/dsh-bundle/sidebar-host.js`, `client.js`, `SIDEBAR.zh.md`) is woven into the dsh bundle and stays there. |

Paths inside these files (for example `/home/<user>/dev/...` in recordings) are left as recorded.
