# xmuse

[![xmuse CI](https://github.com/iiyazu/Cross-Muse/actions/workflows/xmuse-ci.yml/badge.svg)](https://github.com/iiyazu/Cross-Muse/actions/workflows/xmuse-ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

xmuse is a local runtime for natural, logically decentralized Agent group conversations.
Its Room Collaboration Protocol lets persistent Agents observe the same durable Room
activity and independently choose whether to `respond`, `handoff`, `propose`, `defer`, or
`noop`. Infrastructure owns
delivery, identity, causality, attempts, safety, and recovery; it never speaks as an Agent.

## Current product loop

```text
Browser
  -> fixed same-origin Next routes
  -> Room-only Chat API
  -> RoomDatabase / RoomKernel
  -> isolated Room Runner
  -> participant-bound read-only Codex session
  -> bundled Skill decision and context evidence
  -> Room-only MCP chat_room_submit_outcome
  -> durable outcome
  -> Room projection / Operations Inspector

execution proposal
  -> immutable exact-patch candidate in chat.db
  -> manual confirmation (default), or startup-enabled unanimous Room consensus
  -> one-shot networkless Bubblewrap controller in a detached worktree
  -> fixed path-selected gates
  -> guarded promotion of the same patch + execution infrastructure activity

optional source-backed memory
  -> visible Room activity / approved Agent candidate memory outbox in chat.db
  -> full-local MemoryOS hybrid index (rebuildable, loopback, offline BM25 + FastEmbed + RRF)
  -> bounded source-validated memory_evidence in the next Agent context
```

- `chat.db` is authority for Room activity, observations, attempts, controls, messages,
  proposals, cursors, leases, Skill evidence, accepted outcomes, exact-patch candidates,
  assessments, authorizations, execution attempts, gate evidence, and promotion journals.
  It also owns memory outbox rows, candidate approvals, delivery evidence, and recall
  receipts; the MemoryOS database is a disposable index, never Room authority.
- `god_sessions.json` records durable participant/provider bindings. Provider stdout,
  browser state, screenshots, and telemetry are not authority.
- Human speech atomically creates one root observation for every active participant. After
  that root phase terminates, peer activities for the same participant and correlation are
  claimed as one immutable batch (at most 16 items), with one attempt, Skill decision, and
  durable outcome. Mentions and handoffs change attention priority, never eligibility or the
  per-turn response budget.
- Only the identity-, attempt-, and lease-bound MCP outcome becomes Agent speech. Provider
  final text is diagnostic.
- Room Codex sessions use a config-isolated home, read-only filesystem policy, no network,
  and exactly one pre-approved MCP outcome tool.
- Agents can author or assess an exact unified diff through that same durable outcome tool;
  they never receive a writable workspace or arbitrary command surface. Execution is manual
  by default. Consensus execution additionally requires the startup kill-switch, a Room
  policy opt-in, a frozen unanimous peer snapshot, complete patch-review receipts, and the
  server-only low-risk policy.
- The one-shot Harness applies only the authorized bytes in a detached worktree. Bubblewrap
  removes network and ambient credentials. A server-owned, versioned gate profile freezes
  repository markers, the complete local toolchain capability, and the path-selected gate
  order into the authorization. Frontend gates invoke fixed read-only dependency entrypoints,
  never candidate-controlled package scripts. Promotion rechecks policy, clean HEAD, profile
  evidence, and file digests. Pre-promotion failure leaves target bytes unchanged; an
  ambiguous promotion image is blocked for human repair.
- Confirmed-dead Runner attempts are fenced and reopened only after provider cleanup.
  Cancel/retry and guarded Runtime recovery use durable, idempotent control ledgers.
- The browser consumes bounded `room_list_projection/v1`,
  `room_chat_projection/v3`, `room_operations_projection/v2`, and the non-authoritative
  `room_codex_projection/v1` used by the per-participant Agent Console. Console controls are
  rendered only from native capability descriptors; their slash aliases do not add xmuse
  semantics or enter the shared Room composer.
- While a Room turn is active, `room_agent_stream_projection/v1` may expose a sanitized,
  disposable provider preview over SSE. The wire value remains bounded plain text; the browser
  renders only closed Markdown blocks and keeps the unfinished tail lightweight. It is stored
  outside `chat.db`, fenced to
  the exact attempt, and disappears when the durable Room outcome is projected; it is never
  speech, memory, execution evidence, or a fallback outcome. Visible outcomes emit the answer
  itself before the MCP commit so the preview advances with native Codex deltas; noop/defer
  decisions submit directly without manufacturing preview text.
- Provider context uses `room_context_envelope/v2`: the Human root, primary source, causal
  ancestry, batch members, bounded recent burst, active roster, and frozen role persona are
  retained under a 64 KiB limit. A peer follow-up may create visible speech once; its tail is
  context-only and cannot start a third provider wave.
- Optional MemoryOS recall accepts only bounded `metadata.v3_context.items[]` archival
  evidence whose document and activity sources can be re-proved from `chat.db`. Timeouts,
  malformed data, and sidecar failure degrade memory only; the Room attempt still completes
  from its causal context. Agents may propose source-backed memory candidates, but only
  Room facts/decisions auto-publish to that Room. User preferences and project rules require
  an explicit operator approval before shared-archive recall.
- This remains a loopback-only, single-user application. Managed writes use a server-only
  `XMUSE_OPERATOR_TOKEN`; fixed Next routes never expose it to the browser.

## v0.4.0 release qualification

`v0.4.0` keeps the Room-first authority model while closing four production-facing seams:
an optional but trusted full-local MemoryOS companion can be selected automatically; the
Harness has additional closed, server-owned Python and pnpm profiles; Execution no longer
hides a broad Store behind narrow capability adapters; and the Workbench adds progressive
disclosure and first-use guidance without recreating Codex state machines.

The release-candidate qualification ran a 45+ minute, three-Room/four-Agent/six-wave soak:
18/18 correlations settled in 159 attempts while provider, Runner, MemoryOS, and stream-cache
faults were recovered. The browser reported zero console errors. The accompanying memory
diversity run settled 48 correlations with six non-empty source-backed recall receipts, 19
re-proved source references, and 16 derived items. The Harness matrix promoted fixed patches
in memU, MemoryOS, and twg while Clowder, Letta, and mem0 failed closed where their fixed
profile capability was not satisfied. Release notes retain only safe aggregate evidence and
SHA-256 digests; Room text, provider output, internal IDs, runtime paths, and traces remain
outside the release. See `docs/releases/v0.4.0.md`.

The optional companion is built from `memoryos-lite 0.2.1` at clean source SHA
`26a77ece3bfe865169890a7dd49b5076c13ab723`. Installation stays optional; when its
installer-owned manifest and payload digests verify, the default `--memory-mode auto` starts
the full-local companion. It never searches PATH or arbitrary configuration.

## v0.3.1 release

The `v0.3.1` release adds production evidence for the existing Room-first product. A
source-backed MemoryOS run proved non-recent, cross-Room recall with an approved project
source re-proved from `chat.db`; the Exact-patch Harness promoted fixed patches in memU,
Clowder, and MemoryOS while fail-closing incompatible Letta and mem0 inputs. Memory runtime
consumers now receive only their recall, context-receipt, or delivery-pump capability.

A 120-minute full-local endurance run settled 40/40 Human correlations across eight Rooms in
172 attempts. It recovered identity-fenced Codex, Runner, MemoryOS, and stream-cache faults
with no duplicate outcome, cross-Room identity/causality leak, provider orphan, or runtime
residue. Safe aggregate evidence and digests are recorded in
`docs/releases/v0.3.1.md`; raw Room/provider artifacts remain outside the release.

## v0.3.0 release

The `v0.3.0` release makes the local Workroom installable outside a source checkout and
closes the first installed, full-local MemoryOS dogfood cycle. The browser state and
components are split by Room, Codex, execution, memory, and runtime domains; the Linux
x86_64 bundle verifies its platform, Python ABI, manifest, and every payload digest before
atomically activating an isolated version.

Installed four-Agent dogfood proved that Room Codex can inspect the configured workspace
through network-disabled, read-only tools while the only durable Room write remains
`chat_room_submit_outcome`. A provider turn which ends without that outcome now rotates only
its exactly bound delivery session before a bounded retry; an unproven cleanup keeps the old
lease fenced. The final run settled root and peer phases in exactly eight attempts with no
exhausted observation or runtime residue.

## v0.1.0 release baseline

The `v0.1.0` release closed the fixed production soak with 16/16 correlations settled across
four Rooms and eight persistent Agents. It recorded 69 provider attempts, 64 durable outcomes,
zero duplicate outcomes, cross-Room identity/causality leaks, provider orphans, recovery
residue, or browser-console errors. The run exercised Codex, Runner, MemoryOS, and projection
cache failures while preserving the workspace and restoring a single runtime topology.

The default startup has no platform runner, central speaker queue, fixed role sequence,
Dashboard, broad MCP root, self-evolution control plane, enabled MemoryOS sidecar, or Google
A2A transport. The Room Collaboration Protocol is xmuse's own durable collaboration model,
not an implementation of Google A2A; a future Google A2A adapter could only be an opt-in
remote participant transport.
MemoryOS remains optional at installation time. Workroom's default `--memory-mode auto`
selects only an installer-owned, digest-verified full-local companion; `--memory` is the
explicit `--memory-mode on` compatibility alias and `--no-memory` disables it. The companion
is never discovered through PATH or arbitrary configuration. Memory does not expand the Room
Agent's single MCP tool or filesystem/network permissions. Retired implementations live only
in Git history.

## Install a release bundle

Release assets for Linux x86_64 / WSL contain a small standard-library bootstrap, the base
application bundle, and an optional MemoryOS companion bundle. Use CPython 3.11 matching the
bundle ABI; installation is offline and verifies every payload digest before activation.

```bash
python3.11 xmuse-setup.pyz install \
  --bundle xmuse-0.4.0-linux-x86_64.tar.gz
python3.11 xmuse-setup.pyz install-memory \
  --bundle xmuse-memoryos-companion-0.4.0-linux-x86_64.tar.gz   # optional

export PATH="$HOME/.local/share/xmuse/active/.venv/bin:$PATH"
xmuse-setup verify
xmuse-workroom launch --no-open
```

`launch` starts the existing Workroom supervisor in a detached process, waits for its real
readiness receipt, and opens `http://127.0.0.1:3000` unless `--no-open` is supplied. It does
not introduce a second supervisor. With the companion installed, plain `launch` discovers the
bundled executable and stages the verified FastEmbed cache into the private runtime root. Use
`launch --no-memory` to opt out, or `launch --memory` when explicitly selecting a source/
development executable.

Install a newer base bundle to create and atomically activate a separate version. Roll back
or remove an inactive version explicitly:

```bash
xmuse-setup activate 0.3.0  # roll back
xmuse-setup activate 0.4.0
xmuse-setup uninstall 0.3.0
```

The active version cannot be uninstalled. Native Windows and macOS bundles are not provided;
unknown archive members, symlinks, path traversal, digest mismatch, wrong CPU/OS, and wrong
Python ABI fail closed.

## Run locally

Requirements: Linux or WSL, Python 3.11+, `uv`, Git, Bubblewrap, Node.js 20.9+, npm,
and an authenticated Codex CLI on `PATH`.

```bash
uv sync --frozen --all-groups
cd frontend
npm ci
NEXT_PUBLIC_XMUSE_CHAT_API_BASE_URL=http://127.0.0.1:8201/api/chat npm run build
cd ..
export XMUSE_ROOT=/tmp/xmuse-local
uv run xmuse-workroom doctor
uv run xmuse-workroom start
```

Open `http://127.0.0.1:3000`. From another terminal:

```bash
uv run xmuse-workroom status
uv run xmuse-workroom stop
```

The default execution workspace is this xmuse checkout with
`xmuse-monorepo/v2`. To use another clean Git workspace, choose its fixed profile
explicitly; the same path is mounted read-only for Room Agents and used as the exact-patch
promotion target:

```bash
uv run xmuse-workroom start \
  --workspace /absolute/path/to/python-project \
  --execution-profile python-uv/v1
```

The fixed profiles are `docs/v1` (documentation plus diff-check), `python-uv/v1`
(`ruff`, `mypy src`, and `pytest`), `xmuse-monorepo/v2` (backend plus direct TypeScript,
ESLint, Vitest, and Next build gates), `python-uv-ty/v1` (Ruff, ty, and pytest),
`node-pnpm-library/v1` (Prettier, TypeScript, Jest, and tsup), and
`node-pnpm-next-workspace/v1` (Biome, workspace TypeScript, Vitest, and Next build).
Only `docs/v1` can run diff-check alone. Missing markers, preinstalled dependencies,
Bubblewrap, or fixed tool entrypoints block both manual and consensus execution. xmuse never
runs repository package scripts, accepts candidate-controlled argv, or installs dependencies
from the network to accommodate a workspace. Python gates are supervised at 2 GiB aggregate
RSS, 64 processes, and 1 GiB scratch; frontend gates use 4 GiB, 128 processes, and 2 GiB
scratch. Neither the workspace path nor internal profile/toolchain digests enter browser
projections.

To explicitly enable source-backed memory from a checkout, point Workroom at a real MemoryOS
executable. Full-local is the default memory profile; archive-only remains an explicit
compatibility profile. Without an executable, `auto` leaves the Room available and reports
that the companion is not installed:

```bash
uv run xmuse-workroom start --memory-mode on \
  --memoryos-executable /absolute/path/to/memoryos
```

The equivalent `--memory` flag is retained for compatibility. `--memory-mode auto` is the
default and only trusts the verified companion manifest created by the installer; it never
searches PATH. Use `--no-memory` or `--memory-mode off` to disable the optional sidecar.

Workroom fixes the sidecar to loopback, creates a private derived data directory and random
server-only API key, and keeps external memory governance in `chat.db`. Full-local enables
offline BM25, FastEmbed and RRF hybrid retrieval without granting Room Agents network or a
second memory-writing tool. MemoryOS health is reported separately and never changes Room
Runtime readiness. A confirmed-dead owned sidecar is restarted with bounded
`1/2/4/8/16/30s` backoff while the same Workroom generation retains its private endpoint,
key, and data directory; a live-but-unhealthy, identity-mismatched, or unknown port owner is
reported as degraded and is never killed speculatively. Crash-loop or explicit derived-cache
blockers can be rebuilt from the Inspector through a guarded, durable operator action. The
manager first proves and stops the sidecar, deletes only the fixed derived directory, resets
bindings/outbox from `chat.db`, restarts the same capability, and waits for replay evidence.

The six supported commands are `xmuse-chat-api`, `xmuse-mcp-server`,
`xmuse-room-runner`, `xmuse-workroom`, `xmuse-data`, and `xmuse-setup`.

## Data maintenance

```bash
uv run xmuse-data doctor --root "$XMUSE_ROOT"
uv run xmuse-data backup /path/to/new-backup --root "$XMUSE_ROOT"
uv run xmuse-workroom stop --root "$XMUSE_ROOT"
uv run xmuse-data restore /path/to/backup --root "$XMUSE_ROOT" --replace
uv run xmuse-data compact --root "$XMUSE_ROOT"
```

`xmuse-data` recognizes current `xmuse.room_db/v1` and old
`xmuse.chat_db/v1` database variants for offline doctor/backup/restore/compact only. It
preserves schema markers and durable identities without initializing or running retired
product surfaces. Backups contain `chat.db` and the fenced participant binding snapshot, not
the MemoryOS cache. Restore clears only the fixed derived MemoryOS directory, forgets old
session/attachment bindings, and reopens visible activities plus approved candidates for
rebuild.

## Verify

```bash
PYTHONWARNINGS=error TMPDIR=/tmp uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy --explicit-package-bases xmuse src/xmuse_core scripts
uv build
cd frontend
npm ci && npm run typecheck && npm test && npm run lint && npm run build && npm run test:e2e
```

The independent multi-Room lab exercises the same production Kernel/Host path without
adding a telemetry API or Dashboard. `ci-sim` is deterministic and suitable for ordinary
CI; live profiles require a clean HEAD, free fixed ports, authenticated Codex, and a result
path outside the workspace:

```bash
uv run python scripts/room_soak_chaos.py ci-sim --result /tmp/xmuse-ci-soak.json
uv run python scripts/room_soak_chaos.py live-short --result /tmp/xmuse-live-short.json
uv run python scripts/room_soak_chaos.py memory-recovery \
  --memoryos-executable /absolute/path/to/memoryos \
  --result /tmp/xmuse-memory-recovery.json
uv run python scripts/room_soak_chaos.py live-soak \
  --confirm-provider-cost \
  --result /tmp/xmuse-live-soak.json
```

`memory-recovery` uses two phases: nine warm-up turns and one post-recovery turn per Room.
This deliberately moves the recall anchor beyond the default eight-activity recent burst,
so a passing receipt proves archival MemoryOS evidence instead of duplicating Room context.
`live-soak` distributes four provider waves across at least 60 minutes; the confirmation
flag is mandatory. Results use `room_soak_chaos_result/v1` and contain only aggregate
counts, percentiles, stable reason codes, resource totals, and digests. Room/provider text,
tokens, process identities, bindings, and local paths are rejected by the result contract.

Release maintainers additionally use the fixed `live-goal-memory-soak` profile. Its
`room_goal_memory_soak_result/v1` evidence combines multi-Room provider recovery, MemoryOS
recall, guarded native Codex actions, three browser viewports, and workspace-integrity proof;
it is intentionally not part of ordinary CI.

For v0.4.0 release qualification, the installed 45-minute soak and the separate three-Room
memory-diversity dogfood emit safe aggregate result contracts only. The latter uses
`room_memory_diversity_result/v1` to prove source-backed project-rule, user-preference,
non-recent decision, lexical, semantic, and derived recall paths without publishing dialogue,
MemoryOS IDs, paths, or traces.

Implementation and fresh tests are evidence. See [QUICKSTART.md](QUICKSTART.md) and the
[implementation map](docs/xmuse/README.md).
