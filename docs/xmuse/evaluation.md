# Heterogeneous Room evaluation

This page reports what the evaluation harness measured on the heterogeneous Workroom
(Claude Code over ACP, Antigravity over the agy CLI, OpenCode over ACP in a read-only
bubblewrap sandbox), what the measurement exposed, and what it does not show. The design,
tasks, rubrics, controls, and validity threats were frozen before the first run in
[`eval-design.md`](eval-design.md). Raw transcripts and judgments are kept outside the
repository; the harness reproduces them.

## Method

- 7 read-only, self-contained tasks × 2 collaboration modes (`broadcast` vs `addressed`),
  same roster and frozen prompts, seed 7, n=1 per cell. A cell aborts at 10 turns or its
  deadline (15 minutes in run4) and counts as a timeout, not zero.
- Rubric 0–3 with must-hit items, judged on blinded transcripts by `claude -p --model
  sonnet`, two passes, with agreement and Cohen's κ reported.
- Turns, messages, echo/pure-ack noise, wall time, causal depth, handoffs, and turns per
  provider (`turns_by_cli`) are mechanical metrics computed from Room projections, never
  model-generated.
- Pipeline: `scripts/eval/run_eval.py` → `judge.py` → `report.py`.

## Broadcast vs addressed (run4, duo roster: Claude lead + Antigravity researcher)

| | broadcast | addressed |
| --- | --- | --- |
| Rubric mean (0–3) | 2.2 | 2.1 |
| Agent turns (total) | 28 | 8 |
| Visible messages | 2.1 | 1.0 |
| Echo + pure-ack msgs | 0.0 | 0.0 |
| Wall time (median) | 115.3 s | 40.1 s |
| Right specialist answered | 5/7 | 4/7 |

Two-pass agreement was 71%, κ 0.566, lower than run1 (0.757) and run2 (0.774), so the
result is stated as parity: addressed scored within 0.25 of broadcast while using about 71%
fewer agent turns. Per-task differences exist (T1 2.5 vs 3.0 addressed; T2 3.0 vs 2.5
broadcast; T7 2.0 both) but n=1 cannot rank them.

## What the measurement found and fixed

1. **The addressed lead never handed off.** In run1 the lead wrote "Researcher: / Lead: /
   Reviewer:" sections itself in all 7 addressed tasks. Addressed deliveries now carry
   `room_context.collaboration` (mode, lead, handoff guidance); broadcast envelopes are
   byte-identical. The T5 relay then scored 2.0 → 1.0 → 3.0 → 1.0 across run1–run4:
   guidance makes handoff possible, and compliance stays stochastic.
2. **Antigravity language-server discovery picked the wrong process.** It took the first
   loopback listener that answered HTTP 200; an unrelated local process answered and the Room
   stalled for 10 minutes. Discovery now matches listener socket inodes to the language
   server's own file descriptors and pairs the port with that process's CSRF token.
3. **The report template asserted conclusions regardless of data**, including "noise cut
   from 0.0 to 0.0". It now states measurements only.
4. **Blinding garbled ordinary words**: substring role replacement turned "architecturally"
   into "Agent Burally" and the judge penalized it. Whole-token blinding raised re-judged
   agreement from κ 0.62 to 0.76.
5. **MemoryOS BM25 negative IDF** (fixed in MemryOS-lite): in a small archive the question
   itself outranked the approved project rule. Before the fix the Agent answered "no
   evidence" instead of guessing.
6. **Delivery context cut the Human prompt and handed-off work at 4,000 characters.** A
   Verifier reported that the plan it was auditing stopped mid-Step 7, although the Room held
   all 6,402 characters. The 4,240-character T3 prompt had lost its closing residual-risk
   paragraph in every run, while the judge saw it whole. The Human root, primary source,
   batch members, and causal ancestry now use a 16,000-character bound; only the recent burst
   keeps 4,000, and the 64 KiB fitter shrinks batch/ancestry back to 4,000 first. A post-fix
   rerun showed the truncation explained only a small part of T3's low scores: 3 of 4 rerun
   T3 cells still scored 1 for numeric and timing errors.
7. **First-delivery memory recall raced the binding pump.** A new Room's first recall ran
   about 0.3 s before its MemoryOS binding attached, producing an `unavailable` receipt with
   no recall request. Recall now waits up to 2 s for bindings that are still being
   established; uncertain or mismatched bindings stay unavailable immediately.
8. **OpenCode answered in plain text and never submitted an outcome.** Its profile now gets
   one reminder inside the same lease; the platform still never writes an outcome for an
   Agent.
9. **OpenCode's paid models were not selectable over ACP** because the model was set before
   OpenCode finished loading them (about 1.5–2.5 s after start). Model selection now retries
   definite "not found" replies within a settle window, fails fast on transport errors, and
   never falls back to the agent's default model (#416).
10. **The `specialist_ok` metric was wrong for relays**: its ordered check counted the lead's
    first delegation message as the architect's output, so the pre-registered A→B→A relay
    could never pass. It now checks the expected roles as an ordered subsequence; old and new
    values were both reported, and only the two trio T5 cells changed.

## Capability routing: a low-cost Verifier

Roster `builtin.heterogeneous-trio-opencode`: Claude lead, Antigravity researcher, OpenCode
Verifier whose persona declares it the low-cost participant for routine checks. Routing stays
the addressed Agent's decision; the platform adds no router. Pre-registered: T5/T7 can now
reach a review role; the lead is not expected to self-delegate T3; no guidance tuning to
force delegation.

| Measurement | Result |
| --- | --- |
| T5 relay reaching the Verifier | 5/5 runs (4 free-model, 1 paid-model Verifier), Claude→Antigravity→Claude→Verifier, causal depth 4 |
| Claude turns in T5 | 2 per run, unchanged from the duo |
| T5 median wall time | 291 s over 5 runs, 231–391 s |
| T3/T7 delegated to the Verifier | 0/5; the lead answered alone |

The Verifier audits rather than rubber-stamps: in one run it found that a "max 3 attempts /
60 s" retry cap could not cover the log's 1–2 minute recoveries. Delegation happened when the
task named a review step; the lead never delegated fact-checking on its own, even with the
persona stating the Verifier is cheaper. With the paid model, one T5 run scored 3/3 from both
judges against a 2.0 mean over the four free-model runs; that single cell is a direction, not
an effect.

**Cross-family judge.** Re-judging run4 with OpenCode gave two self-consistent passes (κ 1.0)
but more lenient scores (broadcast 2.6 / addressed 2.4 vs 2.2 / 2.1); per-cell agreement
with the sonnet judge was 57%, κ 0.40. Both judges agree on direction (mode parity; T3 and T5
weakest), so it is directional evidence against the same-family threat, not a second verdict.

## Cross-Room memory

With full-local MemoryOS (BM25 + FastEmbed hybrid; ready only after the sidecar reports
`hybrid.semantic=true`), Claude proposes a `project_rule` in Room A, the operator approves
it, and Antigravity in Room B answers from recall alone with receipt `status=ok` and
`memoryos_source_evidence/v2` evidence. Run it with `scripts/heterogeneous_memory_smoke.py`.

## Limitations

- **Sample size**: n=1 per cell in the main comparison, n=2 for the pre-registered trio
  cells; reruns are separate cells. Tasks and guidance were developed by the author on these
  same 7 tasks, so this is a development set, not a held-out benchmark.
- **Judge bias**: the primary judge shares a model family with one participant; blinding and
  the lenient cross-family judge mitigate but do not remove it.
- **Handoff compliance is stochastic**: the same guidance gave T5 3.0 in run3 and 1.0 in run4;
  self-initiated verification delegation was 0/5.
- **Provider conditions**: most trio runs used a free OpenCode model (see fix 9); Codex was not
  logged in on the test machine, so the duo had no review role and T5/T7 could not pass
  `specialist_ok` there.
- **Confinement is not uniform**: Antigravity is instructed read-only; lease fencing rejects
  late outcomes, but nothing in the client stops a misbehaving model.
