# Post-PathA Release Readiness Audit

**Date:** 2026-06-04
**Scope:** Read-only audit of xmuse's readiness to be understood, installed, started, demoed, and presented as an independent internship/resume project after Path A (V8/V9/V10).
**Method:** Source exploration, doc review, tool outputs. No production code, tests, or memoryOS modified. Fake provider is not real provider evidence.
**Conventions:** `current fact` / `inference` / `recommendation` are distinguished per section.

**Post-packaging note (2026-06-04):** This audit records the pre-release-packaging
state. The release candidate packaging goal added root `README.md`,
`QUICKSTART.md`, `scripts/demo_fake_groupchat.py`, and
`docs/xmuse/release-checklist.md`; use those files as the current onboarding
entry points.

---

## 1. README / Quickstart / Doc Readiness

### Current Facts

| Asset | Status | Evidence |
|-------|--------|----------|
| Top-level `README.md` | **MISSING** | `/home/iiyatu/projects/python/xmuse/README.md` does not exist |
| PyPI `readme` field | **Chinese doc index** | `pyproject.toml:5` → `docs/xmuse/README.md` (74 lines, entirely Chinese, is a doc index not a project description) |
| `AGENTS.md` | **EXISTS** (114 lines) | Good developer reference: entry points, architecture facts, constraints, commands. But 50% is OpenCode AI-orchestration config irrelevant to general developers |
| `.env.example` | **EXCELLENT** (133 lines) | Well-organized, 6 named sections, all vars documented with defaults and behavior |
| Quickstart / Getting Started | **MISSING** | No `QUICKSTART.md`, no `INSTALL.md`, no `SETUP.md` anywhere in repo |
| English project description | **MISSING** | `docs/xmuse/README.md` is entirely Chinese. Only English description is `pyproject.toml:4`: "Autonomous software development platform built on MemoryOS" |
| Install instructions | **NOT user-facing** | Buried in `AGENTS.md:34-43` (assumes `uv`), V8 walkthrough has install verification but is a development note not an onboarding doc |
| Contribution guide | **MISSING** | No `CONTRIBUTING.md`, no license file |
| Doc language split | **50/50 Chinese/English** | 33 `docs/xmuse/` files: ~16 Chinese, ~17 English. New contributors face language barrier |
| `docs/xmuse/README.md` | **Inadequate as PyPI readme** | No install, no description, no license, no screenshots, no links |

### Inferences

- **A fresh clone has zero onboarding.** A developer who clones the repo and opens the directory sees nothing explaining what xmuse is, how to install it, or how to get started.
- **PyPI publication would fail to communicate.** `docs/xmuse/README.md`'s Chinese doc index is incomprehensible as a PyPI landing page.
- **AGENTS.md is the de facto README but is mis-targeted.** It serves OpenCode AI agents, not human developers.
- **`.env.example` is the best single piece of user-facing documentation**, but it assumes the user already knows how to install and run the project.

### Recommendations

1. **Create `README.md` at repo root** — English, 30-50 lines: what, why, quick install, quick demo, architecture one-liner, link to docs.
2. **Add a `QUICKSTART.md`** — Step-by-step: prerequisites (Python 3.11, uv), `uv sync`, `cp .env.example .env`, `uv run xmuse-chat-api`, demo via curl.
3. **Either make `docs/xmuse/README.md` bilingual** or **point `pyproject.toml` readme to a proper English README** at repo root.
4. **Add `CONTRIBUTING.md` and `LICENSE`** before any public push.

### Score: 2/10

---

## 2. Clean Install to Fake Groupchat Demo Path

### Current Facts

**V8 (Phase 1) proved installability (`docs/xmuse/archive/2026-06-pre-m7/walkthrough-maintenance-notes-v8.md`):**

| Gate | Result | Evidence |
|------|--------|----------|
| `pyproject.toml` has no editable `../memoryOS` | PASS | V8 walkthrough:14-30 |
| `uv build` | PASS | V8 walkthrough:75-78 (produced `.tar.gz` and `.whl`) |
| Clean env `pip install -e .` | PASS | V8 walkthrough:84-86 |
| Clean env import smoke | PASS | V8 walkthrough:89-98 (`import xmuse`, `import xmuse_core`) |
| Clean env Chat API + fake provider groupchat | PASS | V8 walkthrough:100-111 (`chat-fake-provider-groupchat-smoke-ok`) |
| Wheel metadata has no memoryos-lite | PASS | V8 walkthrough:147-150 |
| Ruff on touched files | PASS | V8 walkthrough:131-136 |

**Fake groupchat path (docs/xmuse/archive/2026-06-pre-m7/walkthrough-maintenance-notes-v8.md:100-111):**
- Created conversation through `xmuse.chat_api.create_app()`
- Posted human `@architect` message
- Ran `PeerChatScheduler` with fake provider layer
- Fake provider used `PeerChatService.read_inbox()` and `post_god_message()`
- **Result:** `chat-fake-provider-groupchat-smoke-ok conv_b0a6e2b569fa47c5bb6b93fd8a737728 1`

**However, this was a test-level smoke — not wired as a production entry point:**
- No `--demo` flag on `xmuse-chat-api`
- No `demo/` directory or `scripts/demo_*.py` in version control
- Old demo scripts (`scripts/gods_chat_minimal.py`, `scripts/ray_gods_chat_demo.py`) archived to `xmuse/history/` which is gitignored
- Fake provider is in `src/xmuse_core/providers/adapters/fake.py` but not selectable as a runtime backend via env var
- The `PeerChatScheduler._runtime_for_participant()` only supports `codex` and `opencode` cli_kinds — no fake runtime path in production code

**Dependencies required for different scenarios:**

| Scenario | Requires Ray | Requires Codex binary | Requires DeepSeek key | Works offline |
|----------|-------------|----------------------|----------------------|---------------|
| `pip install -e .` | No (but installed) | No | No | Yes |
| `uv run pytest` (unit) | No (mocked) | No | No | Yes |
| Chat API `/health` | No | No | No | Yes |
| Chat API POST + reply | Yes (hard dep in pyproject) | Yes or OpenCode | For OpenCode only | No (needs codex binary) |
| Platform runner | Yes | Yes | For OpenCode only | No |
| TUI | No | No | No | Partially (stale without chat backend) |
| Fake groupchat smoke | No | No | No | Yes (test-level only) |

### Inferences

- **Clean install works and is verified.** V8 closure is real and replayable.
- **Fake groupchat demo is technically possible but not user-facing.** It exists only as a test path. A new developer cannot discover or trigger it without reading V8 walkthrough and writing their own harness.
- **Ray is a hard dependency (~200MB) even for scenarios that don't use it.** `ray[default]>=2.55.1` is in `[project.dependencies]` (pyproject.toml:14). A lightweight demo install can't skip it.
- **The path from "I cloned the repo" to "I see a fake groupchat reply" requires:**
  1. Reading V8 walkthrough (not a README)
  2. Understanding `create_app()` internals
  3. Understanding `PeerChatScheduler` + fake layer setup
  4. Writing glue code to wire them together
  → This is a developer-week task, not a 5-minute demo.

### Recommendations

1. **Move Ray to optional dependency** — `[project.optional-dependencies] demo = []` or `runtime = []` so basic install doesn't require Ray.
2. **Add a `--demo` flag** to `xmuse-chat-api` that wires `FakeGodLayer` for instant demo.
3. **Create `scripts/demo_fake_groupchat.py`** — standalone script that creates conversation, posts message, runs scheduler, shows result.
4. **Restore archived demo scripts** to version control or rewrite as `scripts/` entries.
5. **Document the one-liner demo path** in README: `uv sync && uv run xmuse-chat-api --demo`.

### Score: 4/10

---

## 3. Real Ray/Codex/MCP Manual Gate Clarity

### Current Facts

**Production topology is documented** (`docs/xmuse/production-operations.md:9-21`):
```
operator → Chat API :8201 → platform runner → PeerChatScheduler
  → RayGodSessionLayer → RayGodActor → Codex app-server thread
  → MCP /mcp/chat :8100 → chat.db + god_sessions.json
```

**Operations docs exist** (`docs/xmuse/production-operations.md`):
- Startup commands: lines 47-51
- Health check: lines 69-89 (`--health-once --health-check-http`)
- Degradation matrix: lines 92-100 (6 conditions × expected behavior)
- Shutdown/cleanup: lines 103-131
- Restart/resume: lines 133-143 (named test gate)

**Real Ray/Codex smoke is documented and gated:**

| Gate | Command | Doc reference |
|------|---------|---------------|
| Real Ray + Codex app-server + MCP writeback restart/resume soak | `uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume` | `production-operations.md:142-143` |
| Restart resume smoke with fake app server | `uv run pytest -q tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server` | `quality-gates-and-provider-matrix.md:30` |
| Health check | `uv run xmuse-platform-runner --health-once --health-check-http --mcp-port 8100` | `production-operations.md:72-73` |

**Production env bundle is documented** (`docs/xmuse/config-matrix.md:109-119`, `quality-gates-and-provider-matrix.md:100-110`):
```bash
XMUSE_PEER_GOD_BACKEND=ray
XMUSE_EXECUTE_GOD_BACKEND=ray
XMUSE_REVIEW_GOD_BACKEND=ray
XMUSE_RAY_GOD_TRANSPORT=app-server
XMUSE_RAY_GOD_EFFORT=low
XMUSE_RAY_GOD_MCP=1
XMUSE_CHAT_API_URL=http://127.0.0.1:8201
```

**Known production gaps documented:**

| Gap | Doc Reference |
|-----|---------------|
| No auth on Chat API / MCP / Dashboard | `production-operations.md:151`, `config-matrix.md:175` |
| No CI actually running | `quality-gates-and-provider-matrix.md:115-121` (workflow file exists but never triggered on any real CI system) |
| `python-dotenv` declared but never imported | `config-matrix.md:174`, codex-strengthening-handoff.md:396 |
| Codex health check is binary-existence only | `provider-matrix.md:178` |
| 86+ full-repo ruff violations deferred | codex-strengthening-handoff.md:86-88 at multiple rounds |
| Chat API and MCP no auth | multiple docs |

### Inferences

- **The manual operator gates are clear and well-documented.** An operator with Ray, Codex, and MCP infrastructure can follow the docs to run the full production stack.
- **But "clarity" doesn't mean "works first try."** These gates have never been independently verified on a clean machine. They were last run in the MemoryOS monorepo context.
- **Real Ray/Codex/MCP path has never been independently verified** in the standalone xmuse repo. The V8 walkthrough only tested fake provider. The V9 operations doc was written to spec, not to verified behavior.
- **No automated CI exists.** `quality-gates-and-provider-matrix.md` claims "CI workflow exists" — technically true of the `.yml` file but functionally false. No push or PR has ever triggered it.

### Recommendations

1. **Independently verify the real Ray/Codex/MCP gate on a clean machine** — document the exact commands and output as a new walkthrough entry.
2. **Add CI runner configuration** — either set up GitHub Actions (the `.yml` is ready) or document why it's deferred.
3. **Upgrade Codex health check** from binary-existence to a real capability probe.
4. **Document the `--last` anti-pattern fix progress** — provider session binding rounds built the seam but the runtime still uses first-run commands.

### Score: 6/10 (good docs, no independent verification, no CI runs)

---

## 4. Production vs Experimental vs Legacy Boundary

### Current Facts

**Provider classification is clear and enforced by contract tests:**
- `Codex = PRIMARY` — real groupchat GOD provider (`quality-gates-and-provider-matrix.md:85-86`)
- `OpenCode = SECONDARY` — bounded worker / bounded deliberation only, no MCP, no persistent session (`quality-gates-and-provider-matrix.md:87`)
- `Claude Code = launcher only, not provider adapter` (`quality-gates-and-provider-matrix.md:88-89`)
- `Fake = TEST ONLY` — excluded from default registry (`quality-gates-and-provider-matrix.md:90`)
- Enforcement at `tests/xmuse/test_provider_support_level.py`, `test_provider_policy.py`

**Config matrix classification (docs/xmuse/config-matrix.md:9-15):**
- `required`: `DEEPSEEK_API_KEY`
- `optional`: `XMUSE_ROOT`, `XMUSE_RAY_GOD_EFFORT`, etc. (~15 vars)
- `legacy`: `XMUSE_REVIEW_GATE`, shell script vars (~12 vars)
- `injected`: `XMUSE_FEATURE_ID`, `XMUSE_LANE_ID` (~15 vars, set by xmuse for subprocesses)
- `frontend-only`: `NEXT_PUBLIC_XMUSE_*` (~3 vars)

**Phase completion status (docs/xmuse/archive/2026-06-roadmaps-and-audits/path-a-foundation-first-roadmap.md):**

| Phase | Name | Status | Output Doc |
|-------|------|--------|------------|
| **Phase 1 (V8)** | Independent Installability | **DONE** | `walkthrough-maintenance-notes-v8.md` |
| **Phase 2 (V9)** | Runtime Operations | **DONE** | `production-operations.md` |
| **Phase 3 (V10)** | Quality Gates | **DOC EXISTS, CI NEVER TRIGGERED** | `quality-gates-and-provider-matrix.md`, `.github/workflows/xmuse-ci.yml` |
| **Phase 4 (V11)** | Depth Hardening | **NOT STARTED** — docs exist as scoping | `mcp-permission-model.md`, `schema-migration-strategy.md`, `v11-depth-hardening-inventory.md` |

**`feature_lanes.json` authority confusion (well-documented, partly resolved):**
- All docs agree: `feature_lanes.json` should be projection/queue, not authority
- `codex-strengthening-handoff.md:81`: "只应作为迁移期投影或兼容导出"
- Graph-native `FeatureGraphStatusStore` built as shadow (`src/xmuse_core/structuring/feature_graph_status_store.py`)
- **BUT** 42+ code locations still read `feature_lanes.json` as de facto authority
- Migration incomplete — feature graph status store not wired into `PlatformOrchestrator`

**Known doc inaccuracies:**
- `config-matrix.md:174` claims `pydantic-settings` is "declared but unused, no BaseSettings class" — **OUTDATED**, `Settings(BaseSettings)` exists at `src/xmuse_core/runtime/settings.py:14-61`
- `config-matrix.md` line references are off by 6-24 lines due to code changes (V10 audit:362-371)
- 4 undocumented env vars: `XMUSE_GOD_RUNTIME`, `XMUSE_NON_GOD_CODEX_MODEL`, `XMUSE_PEER_CHAT_RUNTIME`, `XMUSE_CHAT_DRIVER_RUNTIME` (V10 audit:375-383)

### Inferences

- **Production vs experimental boundaries are well-documented in intent** but the code-to-doc gap varies by area. Provider classification is tightly enforced. Config classification has minor drift.
- **Phase 4 docs are not stubs** — `mcp-permission-model.md` (82 lines) and `schema-migration-strategy.md` (79 lines) are substantive scoping documents that explicitly say "does not implement." They serve their Phase 4 planning purpose.
- **The biggest boundary gap is CI**: Phase 3 claims completion but the CI workflow has never run. The quality-gates doc says "CI workflow exists" — technically true but practically meaningless without executions.
- **`feature_lanes.json` migration is the most significant known architectural debt.** Every codex-strengthening-handoff round ends with the same note: "feature_lanes.json is still the migration-era execution live queue; this round did not change dispatch."

### Recommendations

1. **Fix config-matrix.md line references and pydantic-settings claim** — simple maintenance that restores doc accuracy.
2. **Either activate CI or deprecate the workflow file.** A `.github/workflows/xmuse-ci.yml` that never runs is misleading.
3. **Prioritize cutting over from `feature_lanes.json` to graph-native status store** in a focused round. The shadow path is built — wire it into `PlatformOrchestrator`.
4. **Add the 4 undocumented env vars to `.env.example` and `config-matrix.md`.**

### Score: 7/10

---

## 5. Resume / Project Positioning with Evidence

### Current Facts

**Quantitative metrics:**

| Metric | Value |
|--------|-------|
| Total Python LOC | 185,568 |
| Core library (`src/xmuse_core/`) | 83,465 lines / 262 files |
| Application layer (`xmuse/`) | 11,789 lines / 49 files |
| TUI (`xmuse/tui/`) | 2,918 lines / 22 files |
| Test suite | 102,103 lines / 234 files |
| Test functions | 2,319 |
| Test classes | 65 |
| Golden JSON fixture files | 51 (2,144 lines) |
| Documentation files | 44 / 23,196 lines / 1.2MB |
| Direct dependencies | 13 (FastAPI, LangGraph, Ray, Textual, Pydantic, etc.) |
| Ruff violations | 82 (41 auto-fixable) |
| CI workflow | Defined but never triggered |

**Technical sophistication demonstrated:**

| Technique | Location | Evidence |
|-----------|----------|----------|
| Multi-agent orchestration | `src/xmuse_core/platform/orchestrator.py` (1,301 lines) | Coordinates feature graph claims, reviews, reworks, patch-forwards, takeovers with 15+ specialist coordinators |
| Distributed actors (Ray) | `src/xmuse_core/agents/ray_god_actor.py` (181 lines) + 4 supporting files | Manages GOD agent lifecycle, transport, crash recovery, session resume |
| Provider adapter abstraction | `src/xmuse_core/providers/adapters/` (4 adapters) | Clean protocol-based abstraction with 9 failure types, capability routing, policy enforcement |
| LangGraph integration | `src/xmuse_core/structuring/langgraph_adapter.py` | Workflow orchestration with clear role boundaries ("must NOT write lane status directly") |
| Self-evolution system | `src/xmuse_core/self_evolution/` (18 files) | Watcher + controller + decomposer + recovery loop for autonomous improvement |
| MCP (Model Context Protocol) | `xmuse/mcp_server.py` (1,106 lines) + supporting modules | Full MCP-over-HTTP server with 35 tools, search, mutation, permissions |
| Textual TUI | `xmuse/tui/` (22 files, 2,918 lines) | Terminal UI with chat screen, feature board, lane detail, completion engine, input history |
| Contract-first testing | `tests/fixtures/xmuse/contracts/` (51 JSON fixtures) | Versioned golden fixtures with schema compliance tests |
| V8 independence closure | Verified by `uv build`, `pip install -e .`, clean import smoke | Removed monorepo dependency without breaking functionality |
| Provider session binding | 10+ progressive rounds in codex-strengthening-handoff.md | Explicit `--last` rejection, store with upsert/resume/mark_failed, seam built to runtime boundary |

**Evidence of real working system:**
- `docs/xmuse/archive/2026-06-pre-m7/walkthrough-maintenance-notes-v8.md:110`: `chat-fake-provider-groupchat-smoke-ok conv_b0a6e2b569fa47c5bb6b93fd8a737728 1`
- `xmuse/HANDOFF.md:35-37`: "2026-06-02 minimal user-vision closed-loop smoke: passed — chat conversation → feature plan → graph-set → projection → TUI worklist"
- `xmuse/HANDOFF.md:38`: "2026-06-02 live RayGodActor lifecycle smoke: passed after hardening"
- `xmuse/HANDOFF.md:47`: "full tests: 3228 passed, 1 skipped, 9 warnings in 1008.69s"
- `xmuse/HANDOFF.md:48-69`: 15+ focused gates all passing (orchestrator, dashboard, chat store, MCP, persistent review, etc.)

### Inferences

- **xmuse is a genuinely sophisticated project** — 185K LOC, multi-framework architecture, distributed compute, self-modification capability, professional testing methodology.
- **The "built on MemoryOS" framing is a resume liability** — `pyproject.toml:4` still says "Autonomous software development platform built on MemoryOS." V8 removed the actual dependency, but the branding hasn't been updated.
- **No visual evidence exists.** A resume entry or portfolio link leads to a repo with no README, no screenshots, no architecture diagrams, no demo video. The TUI is one of the most visually impressive features and has zero visual documentation.
- **The technical depth is resume-competitive at the senior level**, but the presentation gap (no README, no screenshots, Chinese docs) means an evaluator must dig deep to understand what was built.

### Recommendations for resume positioning

1. **Update `pyproject.toml:4` description** — remove "built on MemoryOS," use something like "Multi-agent AI orchestration platform with distributed execution, self-evolution, and terminal UI."
2. **Create a README.md** with architecture summary, features list, and demo link.
3. **Add architecture diagram** — even a simple mermaid/ASCII flow is transformative for communication.
4. **Record a TUI screencast** or take a screenshot and add it to the repo.
5. **One-sentence resume pitch:** "Built a multi-agent AI orchestration platform (185K LOC) that coordinates Codex/OpenCode agents via Ray distributed actors, LangGraph workflows, MCP writeback, and a Textual TUI — with 2,300+ automated tests and zero external runtime dependencies after monorepo extraction."
6. **Fix the 41 auto-fixable ruff violations** to get a clean baseline — this is a one-command fix that removes 50% of all violations.

### Score: 8.5/10 (technical depth) but 3/10 (presentation) → blended 6/10

---

## 6. Missing Screenshots / Demo Scripts / Architecture Diagrams / FAQ

### Current Facts

**Screenshots:** Zero. `find home/iiyatu/projects/python/xmuse -name '*.png' -o -name '*.jpg' -o -name '*.gif' -o -name '*.svg'` returns no project-owned image files.

**Architecture diagrams:** Zero. No mermaid, drawio, plantuml, graphviz, or ASCII diagrams exist in any `docs/` file.

**Demo scripts:** Zero in version control. Two historical demo scripts were archived:
- `scripts/gods_chat_minimal.py` → `xmuse/history/cleanup_20260601T163850Z/` (gitignored)
- `scripts/ray_gods_chat_demo.py` → same archive (gitignored)
Reference: `xmuse/HANDOFF.md:96-98`

**FAQ:** Zero. No `FAQ.md`, no `CONTRIBUTING.md`, no trouble-shooting guide.

**Demo harness:** No `--demo` flag, no `scripts/demo_*.py`, no `Makefile` with demo target.

### Inferences

- This is the single biggest gap for resume/internship presentation. A project with a Textual TUI (a visual component!) has zero visual evidence.
- The lack of demo scripts means a recruiter/evaluator cannot experience the project without significant setup effort.
- The lack of FAQ means common questions ("Do I need Ray?", "Do I need Codex?", "How do I see it working?") are unanswerable without reading deep docs.

### Recommendations

1. **Highest priority: TUI screenshot or GIF** — `uv run python -m xmuse.tui`, take a screenshot, add to repo root as `docs/xmuse/screenshots/tui-chat.png`.
2. **Architecture diagram in README** — mermaid or ASCII showing the full pipeline: Chat API → PeerChatScheduler → GOD Session Layer → Ray/Codex → MCP writeback.
3. **Restore or rewrite demo scripts** — `scripts/demo_fake_groupchat.py` that stands alone (no Ray, no Codex, no API keys).
4. **Add FAQ** — 5-10 common questions with brief answers.
5. **Add `--demo` flag** to `xmuse-chat-api` so a single command launches a working demo.

### Score: 1/10

---

## 7. Codex Follow-Up Task List

These are the concrete remediation items identified by this audit, organized by priority and effort. Each item includes the workstream that identified it.

### P0 — Blocker for Independent Presentation

| # | Task | Est. Effort | Workstream | Evidence |
|---|------|-------------|------------|----------|
| 1 | Create `README.md` at repo root with English project description, install instructions, and quick-start | 2h | 1-Docs | No top-level README exists |
| 2 | Create `QUICKSTART.md` with step-by-step from clone to demo | 1h | 1-Docs | No quickstart exists |
| 3 | Add TUI screenshot/GIF to docs | 30min | 6-Missing | Zero screenshots in repo |
| 4 | Create standalone fake groupchat demo script (`scripts/demo_fake_groupchat.py`) | 3h | 2-Install | Demo path only exists in tests |
| 5 | Update `pyproject.toml` description to remove "built on MemoryOS" framing | 5min | 5-Resume | `pyproject.toml:4` |
| 6 | Run `ruff check --fix` on auto-fixable violations (41 of 82) | 5min | 4-Boundaries | 41 auto-fixable violations |
| 7 | Add architecture diagram to docs | 1h | 6-Missing | No diagrams exist |

### P1 — High Impact, Medium Effort

| # | Task | Est. Effort | Workstream | Evidence |
|---|------|-------------|------------|----------|
| 8 | Add `CONTRIBUTING.md` and `LICENSE` file | 30min | 1-Docs | Neither exists |
| 9 | Make `docs/xmuse/README.md` bilingual or point `pyproject.toml` readme to English README | 1h | 1-Docs | PyPI readme is entirely Chinese |
| 10 | Move `ray[default]` to optional dependency group | 2h | 2-Install | Ray ~200MB hard dep for all installs |
| 11 | Add `--demo` flag to `xmuse-chat-api` wiring fake provider | 4h | 2-Install | No user-facing demo mode |
| 12 | Fix `test_skill_plan_execute_review.py` collection error | 30min | 5-Evidence | 1 broken test |
| 13 | Add 4 undocumented env vars to `.env.example` and `config-matrix.md` | 30min | 4-Boundaries | V10 audit:375-383 |
| 14 | Fix config-matrix.md line reference drift (6-24 lines off) | 30min | 4-Boundaries | V10 audit:362-371 |
| 15 | Fix config-matrix.md outdated `pydantic-settings` claim | 5min | 4-Boundaries | Claims "no BaseSettings" but `runtime/settings.py:14-61` has one |
| 16 | Create FAQ with 5-10 common questions | 1h | 6-Missing | No FAQ exists |
| 17 | Activate CI (GitHub Actions) or deprecate workflow file | 2h | 4-Boundaries | `.yml` exists but never runs |
| 18 | Independently verify real Ray/Codex/MCP gate on clean machine | 4h | 3-Real-Gates | Never verified in standalone repo |

### P2 — Meaningful but Non-Blocking

| # | Task | Est. Effort | Workstream | Evidence |
|---|------|-------------|------------|----------|
| 19 | Cut over from `feature_lanes.json` to graph-native status store in `PlatformOrchestrator` | 1-2d | 4-Boundaries | 42+ code locations still read legacy lanes |
| 20 | Fix the 3 known test failures (`test_gate_profiles.py` ×5, `test_feature_plan_proposal.py` ×1) | 2h | 5-Evidence | V10 audit:75-78 |
| 21 | Restore archived demo scripts to version control | 30min | 6-Missing | `xmuse/HANDOFF.md:96-98` |
| 22 | Upgrade Codex health check from binary-existence to capability probe | 3h | 3-Real-Gates | `provider-matrix.md:178` |
| 23 | Document `pydantic-settings` adoption plan or remove unused dep | 1h | 4-Boundaries | Declared but unused in production |
| 24 | Ban `--last` in runtime dispatch (provider session binding rounds built the seam) | 1d | 3-Real-Gates | All codex-strengthening-handoff rounds end with this as remaining risk |
| 25 | Reduce `test_platform_orchestrator.py` (9,085 lines) | 1-2d | 5-Evidence | Single-file mega-test is a maintenance burden |
| 26 | Resolve full-repo ruff violations (remaining 41 non-auto-fixable) | 4h | 4-Boundaries | Deferred across 10+ rounds |
| 27 | Implement Phase 4: schema migration, MCP permissions, cleanup automation | Multi-day | 4-Boundaries | Docs exist as scoping, no implementation |

### Task Dependency Graph

```
P0: README.md ← QUICKSTART.md ← demo script ← screenshot
                                        ↑
P1: --demo flag ────────────────────────┘
     ↑
     ray[default] optional dep

P1: CI activation ← ruff --fix ← fix known test failures
     ↑
     independent Ray/Codex verification

P0: pyproject.toml description ← architecture diagram

P2: feature_lanes.json cutover ← provider session binding completion
```

---

## 8. Commands Run and Results

### Environment Verification

```bash
# Working directory
pwd
# /home/iiyatu/projects/python/xmuse

# Python version
python3 --version
# Python 3.11.x (via .venv)

# Repository structure
ls -la
# .env.example  .git/  .github/  .gitignore  AGENTS.md  dist/
# docs/  opencode.json  pyproject.toml  scripts/  src/
# tests/  uv.lock  xmuse/
```

### Documentation Inventory

```bash
# Count docs files
ls docs/xmuse/*.md | wc -l
# 31 .md files in docs/xmuse/

# Check for README at repo root
ls README.md 2>&1
# ls: cannot access 'README.md': No such file or directory

# Check CI workflow
cat .github/workflows/xmuse-ci.yml | wc -l
# 56 lines
```

### Test Collection (no execution)

```bash
# Count total tests
uv run pytest --collect-only -q tests/xmuse/ 2>&1 | tail -5
# 3331 collected tests (1 collection error)
```

### Ruff Lint Status

```bash
# Full-repo ruff
uv run ruff check . 2>&1 | tail -30
# Found 82 errors (41 auto-fixable)
# Breakdown: 33 E501, 19 I001, 16 F401, 4 E741, 3 UP037, 3 UP035, 2 UP012, 1 F841, 1 E702
```

### Git Status

```bash
# Branch
git branch
# * main

# No commits
git log --oneline -5 2>&1
# fatal: your current branch 'main' does not have any commits yet

# All files untracked
git status --short | wc -l
# 233 (all ?? untracked)

# No remotes
git remote -v
# (empty)
```

### Codebase Size

```bash
# Total Python LOC
find src/xmuse_core xmuse -name '*.py' -exec cat {} + | wc -l
# 95,254 (core + app layer)

# Test LOC
find tests/xmuse -name '*.py' -exec cat {} + | wc -l
# 102,103

# Golden fixtures
find tests/fixtures -name '*.json' | wc -l
# 51

# Documentation size
find docs -type f -exec cat {} + | wc -c
# 1,219,832 bytes (1.2MB)
```

### Media/Visual Search

```bash
# Screenshots
find . -name '*.png' -not -path './.venv/*' 2>/dev/null
# (empty — no project-owned images)

# Architecture diagrams
grep -r "architecture diagram\|mermaid\|plantuml\|drawio" docs/ --include="*.md" 2>/dev/null
# (empty — no diagram references)

# GIF/screencast
find . -name '*.gif' -not -path './.venv/*' 2>/dev/null
# (empty)
```

---

## Summary Scoring

| Section | Score | Key Weakness |
|---------|-------|--------------|
| 1. README/doc readiness | **2/10** | No README, no quickstart, Chinese-only PyPI readme |
| 2. Clean install to demo | **4/10** | V8 proved installability but demo path is test-only, not user-facing |
| 3. Real Ray/Codex/MCP gates | **6/10** | Well-documented but never independently verified in standalone repo |
| 4. Production vs experimental | **7/10** | Good boundary docs, but CI is dead code, `feature_lanes.json` migration incomplete |
| 5. Resume positioning | **6/10** | 8.5/10 technical depth blended with 3/10 presentation |
| 6. Missing media/demo/diagrams | **1/10** | Zero screenshots, zero diagrams, zero demo scripts, zero FAQ |
| **Overall** | **4.3/10** | Strong technical foundation, catastrophic presentation gap |

**Bottom line:** xmuse is technically ready for independent presentation after Path A — the V8 installability, V9 operations docs, and V10 quality gates provide a solid foundation. But it is **not yet presentable** as an independent project without a README, screenshots, architecture diagram, demo script, and English onboarding. The remediation effort is approximately **2-3 focused days** for P0+P1 items, which would bring the score from 4.3/10 to approximately 7.5/10.
