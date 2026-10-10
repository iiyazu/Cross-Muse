# archive

Historical artifacts, moved here on 2026-10-11 (T7) with `git mv`, so `git log --follow` still shows their history. Nothing here is maintained, imported by the hub, or run by the tests.

| Path | What it was |
|---|---|
| `spikes/` | M0/M1 probes: vendor wake paths (Claude channel and `-p --resume`, OpenCode serve + SSE, dsh headless), cost and usage scripts, recorded runs (`runs/`) and notes. `cc-tree.py` and `cc-usage.py` were ported into `hub/src/xmuse/adapters/claude.py`. |
| `e2e/` | The M1 end-to-end harness (shell scenarios, seeds, hidden tests) and its recorded results, replaced by `experiments/`. Its `check.py` is still used, as `experiments/check.py`. |

Paths inside these files (for example `/home/<user>/dev/...` in recordings) are left as recorded.
