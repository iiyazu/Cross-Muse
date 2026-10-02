# Cross-Muse Evaluation: Broadcast vs. Addressed Collaboration

**Story:** the decentralized `broadcast` room was the original design; we measured it against a capability-`addressed` room on one machine, same roster, same prompts, and let the data drive the pivot.

**Roster (fixed, both modes):** Claude Code = lead/architect, Antigravity/Gemini = researcher, Codex = reviewer (if available; otherwise run with 2 agents and note it in threats). Same models/versions pinned for all runs; rooms created from one author-owned roster template with `collaboration: {"mode", "lead_role": "architect"}`.

**Budget:** 7 tasks × 2 modes. Estimated 3–7 agent turns/task in broadcast (root wave + one context-only peer round) and 2–4 in addressed → ~35–45 turns/mode, ~70–90 total, inside the ~60/mode cap. Abort a cell at 10 turns or 8 min; count it as a timeout, not a zero.

## 1. Tasks and rubrics (all read-only, self-contained, no internet/repo)

Each task is one Human message posted to a fresh room. Rubric scored 0–3: **3** fully correct + complete + no fabrication; **2** correct core, minor omission; **1** partially useful with a real error/fabrication; **0** wrong, refused, or empty. Task-specific "must-hit" items below.

| # | Exercises | Human prompt (verbatim) | Must-hit for 3 |
|---|---|---|---|
| T1 | Design critique | "Critique this login screen description; rank the top 3 usability risks with one concrete fix each. Screen: full-page centered card; email + password fields; 'Remember me' checked by default; no password visibility toggle; errors appear next to the submit button only after a 3-second spinner; 'Forgot password' is a 12px gray-on-white link." | 3 ranked risks; fixes actionable; ≥1 mentions error placement or contrast/visibility |
| T2 | Bug reasoning | "Find the root cause of this bug and give a minimal fix plus one regression test. Code: `def merge_sessions(a, b, meta={}): meta.update(a); meta.update(b); return meta` — called as `merge_sessions(x, y)` twice; the second caller sees keys from the first call. No other context exists." | mutable-default root cause; fix (e.g., `meta=None` or dict copy); a test that fails before/ passes after |
| T3 | Research/summarize | "Summarize the attached incident postmortem in 5 bullets, then state the single highest residual risk and one counter-argument to your own summary. Postmortem: see **Appendix A** (fixed ~600-word fictional postmortem, pre-written before runs)." | 5 faithful bullets (no invented facts); residual risk traceable to text; counter-argument present |
| T4 | Trade-off decision | "Decide for a single-user local desktop workroom on one machine: single SQLite WAL room store vs. a small Postgres service. Constraints: <5 concurrent rooms, durability matters, zero ops budget. Recommend one, give exactly 2 tradeoffs, and the trigger that would make you revisit." | clear recommendation; 2 real tradeoffs; revisit trigger specific |
| T5 | Handoff chain (research → plan → review) | "Sequential outputs, one each: 1) researcher: from the failure log summary below list the top 4 retry-worthy failure modes; 2) lead: a 10-step plan to add rate-limited retries to an MCP tool client covering those modes; 3) reviewer: audit the plan against each failure mode and list gaps. Log: see **Appendix B** (fixed ~300-word failure log)." | 4 modes; plan covers all 4; reviewer finds ≥1 real gap and does not rubber-stamp |
| T6 | Noise trap | "Acknowledgment checkpoint. Reply with exactly one line confirming you read this, then stop. No analysis, no questions, no suggestions." | ≤1 substantive message per agent; no analysis content |
| T7 | Cross-vendor patch review | "Review this diff (read-only). List defects ranked by severity with a fix each: `-def final_amount(cents: int) -> str: return f\"${cents/100:.2f}\"` `+def final_amount(amount: float) -> float: return amount * 1.0825` — used for money totals later summed and displayed." | float-money/rounding defect; type/regression vs. callers; ≥1 fix; no invented context |

The exact posted prompt is the instruction followed by the appendix text verbatim; `scripts/eval/tasks.py` freezes both and is the source of truth for every run.

T5 is the designed handoff task (in addressed mode expect A→B→A ≤ causal depth 4); T6 is the designed noise probe; T1/T7 reward cross-checking, T2/T3/T4 reward single-specialist answering.

## 2. Metrics (computed per task × mode from the exported transcript)

- **Rubric score** 0–3 per above.
- **Agent turns:** durable agent observations with terminal outcome in the task's correlation (projection `turns[]`/frontier counts), excluding the human message.
- **Visible messages:** timeline items authored by agents (`actor.kind != "human"`), including `kind=="handoff"`.
- **Redundant/echo messages (mechanical):** pair of agent messages in the same correlation with shingle-Jaccard ≥ 0.6 across agents (≥ 0.75 same agent), on normalized lowercase tokens; report **pure-ack rate** as a second signal — messages <30 tokens containing ack markers ("agreed", "confirmed", "no objections", "sounds good") and no digit, code fence, or new named entity.
- **Wall time:** seconds from `POST /messages` receipt to settle (defined in §4).
- **Handoff-chain length:** max `causal_depth` in the correlation; plus count of `kind=="handoff"` items and distinct `handoff_targets`.
- **Right specialist answered:** pre-registered expected specialist per task (T3→researcher, T2/T4→lead, T7→reviewer, T5→all three in order, T1→any); metric = that participant authored ≥1 message passing the content check (non-empty and not a pure acknowledgment); boolean.
- **Optional tokens:** provider usage if exposed; else report `content` chars ÷ 4 as a clearly-labeled estimate.

## 3. Protocol

1. **Pin environment:** one machine, same server build, models/versions logged; roster template frozen before the first run.
2. **Ordering:** seed-shuffle task order; alternate which mode runs first per task (block design) so latency/time-of-day drift hits both arms equally. Never run the two modes concurrently (shared compute would distort wall time).
3. **Repetitions:** 1 run per task per mode; spend remaining budget on a second run only for cells with anomalous settles (timeout, lease retry), not for cherry-picking.
4. **Judging:** export transcripts, then **blind**: replace display names with A/B/C, strip `collaboration.mode` and room title. A cheap model (Haiku/4o-mini class, temperature 0) is called twice per transcript with a fixed rubric prompt (task prompt + must-hit list + 0–3 anchors; output strict JSON `{score, rationale, must_hits}`); randomize the letter blocks per transcript. A human uninvolved in the runs spot-checks 2–3 tasks (all modes) and resolves judge disagreements. Report % agreement and Cohen's κ between the two judge passes.
5. **Avoid bias:** rubrics pre-registered before any run; identical prompts/roster/tool policy across modes; mechanical counts (turns, echo, wall time) never LLM-generated; judges never see mode labels or the hypothesis; T6's noise metric is purely mechanical.

## 4. Automation (Python stdlib `urllib`; loopback backend, no operator token needed for create/message reads)

Base `http://127.0.0.1:8201/api/chat`. Endpoints (verified in repo): `POST /conversations` and `GET /room-setup-options` (`xmuse/chat_api_room_setup.py`); `POST /threads/{cid}/messages` (`xmuse/chat_api_room_messages.py`); `GET /conversations/{cid}/room-projection?limit=100` and `GET /conversations/{cid}/events?after_seq=&limit=` and `GET /rooms` (`xmuse/chat_api_room_projection.py`); contract notes (40 KB message cap, limit ≤100, event vs. room seq are different domains) in `docs/xmuse/frontend/FRONTEND_API.md`.

```python
BASE = "http://127.0.0.1:8201/api/chat"
ROSTER = [...]  # initial_participants bound to provider profiles, or one roster_template_id

def post(path, body): return httpx.post(BASE + path, json=body, timeout=30).json()

def create_room(mode, task_id):
    return post("/conversations", {
        "title": f"eval-{task_id}-{mode}",
        "client_request_id": f"eval_{task_id}_{mode}_{uuid4().hex}",
        "initial_participants": ROSTER,
        "collaboration": {"mode": mode, "lead_role": "architect"}})

def run_cell(cid, prompt):
    t0 = time.time()
    post(f"/threads/{cid}/messages", {"message": prompt, "client_request_id": uuid4().hex})
    proj = settle(cid)
    return proj, time.time() - t0

def settle(cid, deadline_s=480):
    last_seq, stable = -1, 0
    while time.time() < start + deadline_s:
        ev = get(f"/conversations/{cid}/events?after_seq=0")
        proj = get(f"/conversations/{cid}/room-projection?limit=100")
        idle = proj["active_turn_count"] == 0 and proj["attention_turn_count"] == 0
        stable = stable + 1 if idle and ev["latest_seq"] == last_seq else 0
        last_seq = ev["latest_seq"]
        if idle and stable >= 2: return proj      # 2 consecutive 5 s polls cover the 15 s lease safety refresh
        time.sleep(5)
    raise TimeoutError(cid)
```

Implemented commands (`scripts/eval/`, no third-party imports):

```bash
uv run python scripts/eval/run_eval.py --base-url http://127.0.0.1:8201/api/chat \
    --modes broadcast,addressed --roster-template builtin.heterogeneous-duo \
    --tasks all --seed 7 --out eval_out
uv run python scripts/eval/judge.py --transcripts eval_out/transcripts --judge manual
uv run python scripts/eval/judge.py --transcripts eval_out/transcripts \
    --judge command --judge-cmd "<cheap-judge-cli>"
uv run python scripts/eval/report.py --results eval_out/results.csv
```

`run_eval.py` writes one transcript JSON per cell plus `results.csv` and
`run_manifest.json`; `judge.py` blinds the transcripts and writes `judging_sheet.md` /
`judging_sheet.csv` (manual) or `judgments.json` (command, two passes); `report.py`
merges the judgments and emits the README table. In addressed mode the Human message is
prefixed with the lead's real mention handle (`participants[].mention_handle` from the
room projection), so only the lead observes the root; in broadcast mode the prompt is
posted verbatim.

**Judge step:** `judge.py` loads transcripts, blinds/anonymizes, calls the cheap model twice with the fixed rubric prompt, writes `judgments.json`. **Results CSV** columns: `task_id, mode, run, rubric_score, judge_a, judge_b, agree, agent_turns, visible_msgs, echo_msgs, pure_ack_msgs, wall_s, max_causal_depth, handoffs, specialist_ok, tokens_est, notes`. A `report.py` aggregates per mode (mean/sum) and emits the README table.

## 5. README presentation

One table, aggregated per mode (per-task detail in `eval/results.csv`), plus a 2–3 sentence takeaway:

| | broadcast | addressed |
|---|---|---|
| Rubric mean (0–3) | … | … |
| Agent turns (total) | … | … |
| Visible messages | … | … |
| Echo + pure-ack msgs | … | … |
| Wall time (median) | … | … |
| Right specialist answered | …/7 | …/7 |

*Takeaway (template, filled from data):* "Same prompts, same roster: the addressed room matched broadcast's rubric mean (X.X vs X.X) while using ~N% fewer agent turns and cutting pure-ack noise from A to B messages per task; broadcast's edge showed up only in open critique tasks (T1/T7), where extra peer perspectives surfaced fixes addressed sometimes missed. We kept both modes — addressed as the default for directed work, broadcast as opt-in for open review — because the data, not the original design, chose the default."

## 6. Threats to validity

- **n=1 per cell**: provider nondeterminism dominates single runs; treat deltas <1 rubric point or <2 turns as noise; second runs only if budget allows.
- **Compute confound**: broadcast simply fires more turns, so any quality win may be "more tries," not "better coordination" — compare noise/turns per unit of rubric score, and state this.
- **Judge bias toward verbosity**: cheap LLM judges reward longer answers; mitigate with must-hit rubrics, blinded names, and the human spot-check; report κ.
- **Judge model family bias** (e.g., a Claude judge preferring Claude outputs): acceptable if the judge model differs from all roster models; else note it.
- **Roster asymmetry**: missing Codex makes addressed mode look leaner and removes the T7 reviewer; report the roster actually used with every result.
- **Prompt authoring bias**: tasks were written by the same person who hypothesized the pivot; T6's mechanical metric is the main guard — its result cannot be talked up by a persuasive agent.
- **Environment drift**: lease retries, cache warmth, and machine load affect wall time; block the mode order to spread drift, and treat wall time as directional only.

## Appendix A — Incident postmortem (fixed, fictional, ~600 words)

The posted T3 prompt appends this frozen text verbatim (same string as `tasks.POSTMORTEM_APPENDIX`).

```text
Appendix A - Incident postmortem (fixed, fictional)

Incident PM-2026-08: duplicate settlement emails after retry storm
Date: 2026-08-14, 02:04-03:41 UTC. Duration: 97 minutes. Severity: SEV-2.
Systems: billing-api (Go), notification-worker (Python), ledger db (Postgres 15).
Impact: 6,214 customers received a duplicate "payment settled" email; 412 of those
also saw a transient "payment failed" status that self-corrected. No money moved
twice; ledger balances verified correct within 11 minutes of recovery.

Detection: support ticket volume alert (Zendesk >40 tickets/10 min) fired at 02:19,
15 minutes after the first duplicate. The synthetic transaction monitor was green
throughout because it never asserts email uniqueness.

Timeline (UTC):
- 01:57 - Ledger primary fails over after a 4s network partition; writes queue on the
  billing-api side.
- 02:04 - notification-worker's settlement poller calls billing-api
  POST /settlements/notify; 43 requests time out at the 30s mark while the failover
  completes.
- 02:04-02:31 - Worker retries each timed-out request every 20s with no idempotency
  key. billing-api accepts the duplicates because the notify handler writes an
  "email queued" row and returns 202, then enqueues to SQS; queue dedup window is
  only 5 minutes.
- 02:19 - Support alert fires; on-call begins triage.
- 02:31 - First duplicate emails go out; poller is still retrying 61 in-flight
  requests.
- 02:47 - On-call pauses the notification-worker via feature flag
  notify_settlement_enabled=false.
- 03:12 - Root cause identified; ledger reconciliation confirms balances are correct;
  duplicate emails traced to missing idempotency keys.
- 03:41 - Retry backlog drained; duplicate volume reaches zero.

Root cause: the settlement poller was rewritten three weeks earlier (PR #4821) to
"retry aggressively on any 5xx or timeout." The rewrite dropped the X-Idempotency-Key
header that the legacy poller sent, and billing-api's notify handler never required
the key. The queue-level dedup window (5 minutes) is shorter than the retry window
(20s x 40 attempts, about 13 minutes), so late retries slipped past dedup.

Contributing factors:
1. No contract test asserted that the poller sends an idempotency key; PR #4821
   removed the header and CI stayed green.
2. billing-api's 202 response does not echo a dedup token, so the poller had no way
   to detect an accepted duplicate.
3. The synthetic monitor checks availability and latency only; email semantics are
   untested in staging.

What went well: failover itself completed in 4s; reconciliation tooling verified
ledger integrity in 11 minutes; the feature flag allowed a fast stop of outbound
email.

Action items:
- AI-1 (billing-api): require X-Idempotency-Key on POST /settlements/notify, reject
  missing keys with 400. Owner: Billing team. Status: shipped 2026-08-19.
- AI-2 (notification-worker): restore the idempotency key; persist per-event send
  state keyed by settlement id. Owner: Notifications team. Status: shipped
  2026-08-20.
- AI-3 (SRE): extend the synthetic monitor to assert exactly-one email per settlement
  via a test mailbox. Owner: SRE. Status: in progress, due 2026-09-05.
- AI-4 (both): add a contract test for the notify request schema. Owner: Billing +
  Notifications. Status: shipped 2026-08-21.
- AI-5 (data): backfill a reconciliation report of the 6,214 affected customers for
  support. Owner: Data. Status: done 2026-08-16.

Lessons: the missing contract test was the single highest-leverage gap; retries
without idempotency turned a 4s failover into 97 minutes of customer-visible noise.

Residual risk (verbatim from the postmortem document): "The dedup window and retry
policy are still configured independently in two repositories; the current values
happen to be compatible (400 attempts x 20s stays within the 30-minute queue dedup
window), but nothing enforces that relationship. The next tuning change to either
side can reintroduce duplicate sends, and the only current guard is the extended
synthetic monitor (AI-3), which is not yet shipped."
```

## Appendix B — MCP tool-client failure log (fixed, fictional, ~300 words)

The posted T5 prompt appends this frozen text verbatim (same string as `tasks.FAILURE_LOG_APPENDIX`).

```text
Appendix B - MCP tool-client failure log (fixed, fictional)

Observed 2026-08-02 through 2026-08-09; client mcp-client 0.9.3 calling three
upstream tool servers (registry, search, calc); about 12,400 calls.

1. Timeouts: 214 calls ended in "read timeout after 30s" to the search server under
   the 09:00-09:20 load burst; bursts lasted 6-18 minutes on 5 of 8 days. Of those,
   187 succeeded when manually retried after 1-2 minutes. Server logs show GC pauses
   of 12-22s, not crashes. The client has no automatic retry for reads; the runbook
   relies on manual operator retries.
2. HTTP 429 rate limiting: 391 calls to the registry server returned
   "429 Too Many Requests" with a Retry-After header present in 96% of cases
   (values 2-45s). Bursts reached 900+ calls/minute during CI fan-out on Aug 6. The
   client ignores Retry-After and backs off a flat 1s, so 38% of the immediate
   retries were rejected again.
3. Partial writes / lost responses: 27 POST /jobs calls to the calc server were
   durably accepted (each job appears in the job list) but the HTTP response never
   arrived (client saw "remote disconnected"). Blind manual resends created 9
   duplicate jobs before a human noticed.
4. Clock skew: 3 hosts ran 4-11 minutes ahead after the Aug 3 maintenance window
   left one rack's NTP client pointed at a decommissioned internal address; the
   other two drifted after a reboot. Their signed time-based credentials
   (X-Tool-Timestamp) were rejected by the search server with
   "401 timestamp_out_of_window" (113 calls), because the server accepts a
   +/-5 minute window.

Other noise, not retry-worthy: 41 "400 invalid_argument" responses from malformed
agent-supplied arguments; 12 "404 tool_not_found" after a registry rollout. These
should fail fast, not be retried.

Totals: 745 retry-worthy failures (214 + 391 + 27 + 113) out of about 12,400 calls;
53 fail-fast responses excluded.
