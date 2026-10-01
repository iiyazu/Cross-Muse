"""Unit tests for the offline eval harness (scripts/eval). No network is touched."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.eval import judge, metrics, report, run_eval, tasks

CORRELATION = "corr_1"


def _participant(pid: str, role: str, name: str) -> dict[str, Any]:
    return {
        "participant_id": pid,
        "role": role,
        "display_name": name,
        "mention_handle": f"@{role}",
        "status": "active",
    }


def _human_item(content: str = "task prompt", *, seq: int = 0) -> dict[str, Any]:
    return {
        "kind": "message",
        "room_seq": seq,
        "activity_id": "act_root",
        "correlation_id": CORRELATION,
        "causal_depth": 0,
        "actor": {
            "kind": "human",
            "participant_id": None,
            "role": "human",
            "display_name": "Human",
        },
        "content": content,
        "handoff_targets": [],
        "context_only_tail": False,
    }


def _agent_item(
    seq: int,
    pid: str,
    role: str,
    name: str,
    content: str,
    *,
    kind: str = "message",
    depth: int = 1,
    targets: list[str] | None = None,
    context_only: bool = False,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "room_seq": seq,
        "activity_id": f"act_{seq}",
        "correlation_id": CORRELATION,
        "causal_depth": depth,
        "actor": {"kind": "participant", "participant_id": pid, "role": role, "display_name": name},
        "content": content,
        "handoff_targets": targets or [],
        "context_only_tail": context_only,
    }


def make_transcript(
    items: list[dict[str, Any]],
    participants: list[dict[str, Any]],
    *,
    turns: list[dict[str, Any]] | None = None,
    mode: str = "broadcast",
    task_id: str = "T1",
    wall_s: float = 12.0,
    mention_prefix: str | None = None,
) -> dict[str, Any]:
    if turns is None:
        turns = [
            {
                "correlation_id": CORRELATION,
                "root_activity_id": "act_root",
                "participants": [
                    {
                        "participant_id": participant["participant_id"],
                        "observation_count": 1,
                        "unresolved_count": 0,
                    }
                    for participant in participants
                ],
            }
        ]
    return {
        "schema_version": "eval_transcript/v1",
        "transcript_id": f"{task_id}_{mode}_r1",
        "task_id": task_id,
        "mode": mode,
        "run": 1,
        "conversation_id": "conv_x",
        "room_title": f"eval-{task_id}-{mode}",
        "mention_prefix": mention_prefix,
        "root_correlation_id": CORRELATION,
        "timing": {"wall_s": wall_s, "timed_out": False, "abort_reason": None},
        "projection": {
            "participants": participants,
            "turns": turns,
            "timeline_items": [_human_item(), *items],
        },
    }


def two_agent_transcript(
    left_content: str, right_content: str, *, mode: str = "broadcast"
) -> dict[str, Any]:
    participants = [
        _participant("part_a", "architect", "Claude Lead"),
        _participant("part_b", "research", "Gemini Researcher"),
    ]
    items = [
        _agent_item(1, "part_a", "architect", "Claude Lead", left_content),
        _agent_item(2, "part_b", "research", "Gemini Researcher", right_content),
    ]
    return make_transcript(items, participants, mode=mode)


# --- metrics -------------------------------------------------------------------


def test_agent_turns_counts_terminal_observations() -> None:
    transcript = make_transcript(
        [_agent_item(1, "part_a", "architect", "A", "hello")],
        [_participant("part_a", "architect", "A")],
        turns=[
            {
                "correlation_id": CORRELATION,
                "root_activity_id": "act_root",
                "participants": [
                    {"participant_id": "part_a", "observation_count": 3, "unresolved_count": 1},
                    {"participant_id": "part_b", "observation_count": 2, "unresolved_count": 2},
                ],
            }
        ],
    )
    assert metrics.agent_turns(transcript) == 2


def test_agent_turns_falls_back_to_timeline_items() -> None:
    transcript = two_agent_transcript("one two three", "four five six")
    transcript["projection"]["turns"] = []
    assert metrics.agent_turns(transcript) == 2


def test_visible_messages_excludes_human_and_counts_handoffs() -> None:
    participants = [_participant("part_a", "architect", "A"), _participant("part_b", "review", "B")]
    items = [
        _agent_item(1, "part_a", "architect", "A", "first"),
        _agent_item(2, "part_a", "architect", "A", "second", kind="handoff", targets=["B"]),
    ]
    transcript = make_transcript(items, participants)
    assert metrics.visible_messages(transcript) == 2


def test_echo_pairs_thresholds_and_message_count() -> None:
    base = "one two three four five six seven eight nine ten"
    extended = base + " eleven twelve thirteen fourteen"
    # trigram shingles: base has 8, extended has 12, 8 shared -> jaccard 8/12 = 0.667
    assert metrics.shingle_jaccard(base, extended) == pytest.approx(0.6667, abs=0.001)

    participants = [
        _participant("part_a", "architect", "A"),
        _participant("part_b", "research", "B"),
    ]
    cross = make_transcript(
        [
            _agent_item(1, "part_a", "architect", "A", base),
            _agent_item(2, "part_b", "research", "B", extended),
        ],
        participants,
    )
    assert metrics.echo_message_count(cross) == 2

    same_agent = make_transcript(
        [
            _agent_item(1, "part_a", "architect", "A", base),
            _agent_item(2, "part_a", "architect", "A", extended),
        ],
        participants,
    )
    assert metrics.echo_message_count(same_agent) == 0

    unrelated = two_agent_transcript("alpha beta gamma", "money rounding defect fix")
    assert metrics.echo_pairs(unrelated) == []


def test_echo_counts_distinct_messages() -> None:
    base = "one two three four five six seven eight nine ten"
    participants = [
        _participant("part_a", "architect", "A"),
        _participant("part_b", "research", "B"),
    ]
    transcript = make_transcript(
        [
            _agent_item(1, "part_a", "architect", "A", base),
            _agent_item(2, "part_b", "research", "B", base),
            _agent_item(3, "part_a", "architect", "A", base),
        ],
        participants,
    )
    assert metrics.echo_message_count(transcript) == 3


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("Agreed, no objections.", True),
        ("Sounds good - ship it.", True),
        ("Agreed. But the retry must honor Retry-After, see line 42.", False),
        ("Confirmed: the plan misses clock skew. Resync NTP before retrying.", False),
        ("```\nagreed\n```", False),
        ("agreed " + "and now a much longer sentence " * 20, False),
        ("Agreed on the diagnosis, but the contrast ratio fails WCAG AA.", False),
    ],
)
def test_pure_ack_heuristic(content: str, expected: bool) -> None:
    assert metrics.is_pure_ack(content) is expected


def test_pure_ack_messages_counts_only_agents() -> None:
    participants = [_participant("part_a", "architect", "A"), _participant("part_b", "review", "B")]
    items = [
        _agent_item(1, "part_a", "architect", "A", "Agreed."),
        _agent_item(2, "part_b", "review", "B", "Here are three ranked risks with fixes."),
        _agent_item(3, "part_a", "architect", "A", "Sounds good."),
    ]
    transcript = make_transcript(items, participants)
    assert metrics.pure_ack_messages(transcript) == 2


def test_wall_time_and_token_estimate() -> None:
    transcript = two_agent_transcript("abcd" * 25, "efgh" * 25)
    assert metrics.wall_time_s(transcript) == 12.0
    assert metrics.token_estimate(transcript) == (100 + 100) // 4


def test_causal_depth_handoff_summary_and_context_only() -> None:
    participants = [_participant("part_a", "architect", "A"), _participant("part_b", "review", "B")]
    items = [
        _agent_item(1, "part_a", "architect", "A", "plan", depth=1),
        _agent_item(
            2, "part_b", "review", "B", "gaps", kind="handoff", depth=3, targets=["A", "C"]
        ),
        _agent_item(3, "part_a", "architect", "A", "context", depth=2, context_only=True),
    ]
    transcript = make_transcript(items, participants)
    assert metrics.max_causal_depth(transcript) == 3
    assert metrics.handoff_summary(transcript) == {"count": 1, "targets": ["A", "C"]}
    assert metrics.context_only_messages(transcript) == 1


def test_specialist_status_single_role_and_any() -> None:
    participants = [
        _participant("part_a", "architect", "Lead"),
        _participant("part_b", "research", "Res"),
    ]
    items = [
        _agent_item(1, "part_b", "research", "Res", "Research summary with evidence."),
        _agent_item(2, "part_a", "architect", "Lead", "Agreed."),
    ]
    transcript = make_transcript(items, participants)
    assert metrics.specialist_status(transcript, ("research",))["ok"] is True
    assert metrics.specialist_status(transcript, ("architect",))["ok"] is False
    assert metrics.specialist_status(transcript, ())["ok"] is True


def test_specialist_status_ordered_chain() -> None:
    participants = [
        _participant("part_r", "research", "R"),
        _participant("part_a", "architect", "A"),
        _participant("part_v", "review", "V"),
    ]
    ordered_items = [
        _agent_item(1, "part_r", "research", "R", "four retry-worthy modes"),
        _agent_item(2, "part_a", "architect", "A", "ten step retry plan"),
        _agent_item(3, "part_v", "review", "V", "gap: duplicates on partial writes"),
    ]
    transcript = make_transcript(ordered_items, participants)
    assert metrics.specialist_status(transcript, ("research", "architect", "review"), ordered=True)[
        "ok"
    ]

    scrambled = make_transcript(
        [
            _agent_item(1, "part_v", "review", "V", "gap: duplicates on partial writes"),
            _agent_item(2, "part_r", "research", "R", "four retry-worthy modes"),
            _agent_item(3, "part_a", "architect", "A", "ten step retry plan"),
        ],
        participants,
    )
    result = metrics.specialist_status(scrambled, ("research", "architect", "review"), ordered=True)
    assert result["ok"] is False
    assert result["detail"]["sequence_ok"] is False


def test_compute_metrics_keys_cover_csv_columns() -> None:
    transcript = two_agent_transcript("shared text body", "shared text body")
    computed = metrics.compute_metrics(transcript, tasks.tasks_by_id()["T1"])
    for key in (
        "agent_turns",
        "visible_msgs",
        "echo_msgs",
        "pure_ack_msgs",
        "wall_s",
        "max_causal_depth",
        "handoffs",
        "specialist_ok",
        "tokens_est",
        "notes",
    ):
        assert key in computed


# --- tasks ----------------------------------------------------------------------


def test_task_prompts_embed_appendices() -> None:
    known = tasks.tasks_by_id()
    assert "Residual risk (verbatim" in known["T3"].prompt
    assert "300-word" not in known["T3"].prompt
    assert "X-Tool-Timestamp" in known["T5"].prompt
    assert len(known["T3"].prompt) < 40_000


def test_select_tasks_rejects_unknown_ids() -> None:
    with pytest.raises(ValueError):
        tasks.select_tasks("T1,T9")


# --- judge ----------------------------------------------------------------------


def test_blind_transcript_strips_identity_and_mode() -> None:
    transcript = two_agent_transcript(
        "Claude Lead should note the contrast issue.", "Per @architect, agreed."
    )
    transcript["prompt_posted"] = "@architect Critique this login screen."
    transcript["mention_prefix"] = "@architect"
    transcript["projection"]["timeline_items"][0]["content"] = transcript["prompt_posted"]

    blinded = judge.blind_transcript(transcript, seed=3)
    assert "Claude Lead" not in blinded.rendered
    assert "Gemini Researcher" not in blinded.rendered
    assert "broadcast" not in blinded.rendered
    assert "eval-T1-broadcast" not in blinded.rendered
    assert "@architect" not in blinded.rendered
    assert "part_a" not in blinded.rendered
    assert "Critique this login screen." in blinded.rendered
    assert "Agent A" in blinded.rendered
    assert set(blinded.letters.values()) == {"A", "B"}

    again = judge.blind_transcript(transcript, seed=3)
    assert again.letters == blinded.letters
    assert again.rendered == blinded.rendered


def test_build_judge_prompt_contains_rubric_but_no_mode() -> None:
    task = tasks.tasks_by_id()["T4"]
    transcript = two_agent_transcript("SQLite WAL recommendation.", "Two tradeoffs listed.")
    transcript["task_id"] = "T4"
    transcript["transcript_id"] = "T4_addressed_r1"
    transcript["mode"] = "addressed"
    blinded = judge.blind_transcript(transcript, seed=1)
    prompt = judge.build_judge_prompt(task, blinded)
    assert "clear recommendation" in prompt
    assert "fully correct and complete with no fabrication" in prompt
    assert "STRICT JSON" in prompt
    assert "broadcast" not in prompt
    assert "addressed" not in prompt
    assert "Claude Lead" not in prompt


def test_parse_judge_output_validates_strict_json() -> None:
    payload = {"score": 2, "rationale": "correct core, one omission", "must_hits": {"a": True}}
    assert judge.parse_judge_output(json.dumps(payload))["score"] == 2
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    assert judge.parse_judge_output(fenced)["must_hits"] == {"a": True}
    for bad in (
        "no json here",
        json.dumps({"score": 4, "rationale": "x", "must_hits": {}}),
        json.dumps({"score": 1, "rationale": "", "must_hits": {}}),
        json.dumps({"score": 1, "rationale": "x", "must_hits": {"a": "yes"}}),
    ):
        with pytest.raises(judge.JudgeOutputError):
            judge.parse_judge_output(bad)


def test_cohen_kappa_known_values() -> None:
    assert judge.cohen_kappa([2, 3, 1], [2, 3, 1]) == 1.0
    assert judge.cohen_kappa([1, 1, 0, 0], [1, 0, 1, 0]) == pytest.approx(0.0)
    assert judge.cohen_kappa([], []) is None


def test_manual_sheet_writes_blinded_prompt(tmp_path: Path) -> None:
    transcript = two_agent_transcript("Claude Lead: risk one is contrast.", "Confirmed.")
    error_transcript = {
        "transcript_id": "T2_broadcast_r1",
        "task_id": "T2",
        "mode": "broadcast",
        "run": 1,
        "error": "boom",
    }
    md_path, csv_path = judge.write_manual_sheet(
        [transcript, error_transcript], tasks.tasks_by_id(), seed=5, out_dir=tmp_path
    )
    sheet = md_path.read_text(encoding="utf-8")
    assert "## T1_broadcast_r1" in sheet
    assert "Claude Lead" not in sheet
    assert "Agent A" in sheet
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [
        {
            "transcript_id": "T1_broadcast_r1",
            "task_id": "T1",
            "score": "",
            "rationale": "",
            "must_hits_json": "",
        }
    ]


def test_command_backend_with_monkeypatched_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    transcript = two_agent_transcript("Risk one is error placement.", "Fix: inline errors.")

    def fake_run(cmd: str, prompt: str, *, timeout_s: float = 300.0) -> str:
        assert "STRICT JSON" in prompt
        return json.dumps({"score": 3, "rationale": "complete", "must_hits": {"risk": True}})

    monkeypatch.setattr(judge, "run_judge_command", fake_run)
    payload = judge.command_backend(
        [transcript], tasks.tasks_by_id(), cmd="fake-judge", passes=2, seed=0, timeout_s=5.0
    )
    entry = payload["entries"][0]
    assert entry["agree"] is True
    assert entry["score_mean"] == 3.0
    assert payload["agreement"] == 1.0
    assert payload["cohen_kappa"] == 1.0


# --- report ---------------------------------------------------------------------


def _row(
    task_id: str,
    mode: str,
    *,
    rubric: str = "",
    judge_a: str = "",
    judge_b: str = "",
    agent_turns: str = "2",
    visible_msgs: str = "3",
    echo_msgs: str = "0",
    pure_ack_msgs: str = "0",
    wall_s: str = "10.0",
    specialist_ok: str = "True",
) -> dict[str, str]:
    return {
        "task_id": task_id,
        "mode": mode,
        "run": "1",
        "rubric_score": rubric,
        "judge_a": judge_a,
        "judge_b": judge_b,
        "agree": "",
        "agent_turns": agent_turns,
        "visible_msgs": visible_msgs,
        "echo_msgs": echo_msgs,
        "pure_ack_msgs": pure_ack_msgs,
        "wall_s": wall_s,
        "max_causal_depth": "2",
        "handoffs": "0",
        "specialist_ok": specialist_ok,
        "tokens_est": "100",
        "notes": "",
    }


def test_merge_judgments_and_effective_scores() -> None:
    rows: list[dict[str, Any]] = [
        _row("T1", "broadcast"),
        _row("T1", "addressed", rubric="2"),
    ]
    judgments = {
        "entries": [
            {
                "transcript_id": "T1_broadcast_r1",
                "task_id": "T1",
                "mode": "broadcast",
                "run": 1,
                "passes": [{"score": 3}, {"score": 3}],
                "agree": True,
            }
        ]
    }
    assert report.merge_judgments(rows, judgments) == 1
    assert report.effective_scores(rows[0]) == [3.0, 3.0]
    assert report.effective_scores(rows[1]) == [2.0]


def test_aggregate_and_table_format() -> None:
    rows = [
        _row("T1", "broadcast", judge_a="3", judge_b="3", agent_turns="4", pure_ack_msgs="2"),
        _row("T2", "broadcast", judge_a="2", judge_b="2", agent_turns="6", pure_ack_msgs="1"),
        _row("T1", "addressed", judge_a="3", judge_b="3", agent_turns="2", pure_ack_msgs="0"),
        _row("T2", "addressed", judge_a="2", judge_b="3", agent_turns="2", pure_ack_msgs="0"),
    ]
    aggregated = report.aggregate(rows, ["broadcast", "addressed"])
    assert aggregated["broadcast"]["rubric_mean"] == pytest.approx(2.5)
    assert aggregated["broadcast"]["turns_total"] == 10
    assert aggregated["addressed"]["turns_total"] == 4
    assert aggregated["broadcast"]["pure_ack_mean"] == pytest.approx(1.5)

    table = report.render_table(aggregated, ["broadcast", "addressed"])
    lines = table.split("\n")
    assert lines[0] == "| | broadcast | addressed |"
    assert "| Rubric mean (0–3) | 2.5 | 2.8 |" in lines
    assert "| Agent turns (total) | 10 | 4 |" in lines
    assert "| Wall time (median) | 10.0 s | 10.0 s |" in lines
    assert "| Right specialist answered | 2/2 | 2/2 |" in lines


def test_takeaway_reflects_direction_and_critique_note() -> None:
    rows = [
        _row("T1", "broadcast", judge_a="3", judge_b="3", agent_turns="6", pure_ack_msgs="2"),
        _row("T2", "broadcast", judge_a="1", judge_b="1", agent_turns="6"),
        _row("T1", "addressed", judge_a="2", judge_b="2", agent_turns="3", pure_ack_msgs="0"),
        _row("T2", "addressed", judge_a="3", judge_b="3", agent_turns="3"),
    ]
    aggregated = report.aggregate(rows, ["broadcast", "addressed"])
    takeaway = report.render_takeaway(aggregated, rows, ["broadcast", "addressed"])
    assert "fewer agent turns" in takeaway
    assert "cutting pure-ack noise from" in takeaway
    assert "T1 3.0 vs 2.0" in takeaway
    # The takeaway reports measurements only; it never asserts a cause or decision.
    assert "chose the default" not in takeaway


def test_takeaway_does_not_claim_a_reduction_when_noise_is_equal() -> None:
    rows = [
        _row("T2", "broadcast", judge_a="3", judge_b="3", agent_turns="4", pure_ack_msgs="0"),
        _row("T2", "addressed", judge_a="1", judge_b="1", agent_turns="1", pure_ack_msgs="0"),
    ]
    aggregated = report.aggregate(rows, ["broadcast", "addressed"])
    takeaway = report.render_takeaway(aggregated, rows, ["broadcast", "addressed"])
    assert "cutting" not in takeaway
    assert "addressed scored 2.0 below broadcast" in takeaway


def test_build_markdown_includes_judging_stats_and_header() -> None:
    rows = [
        _row("T1", "broadcast", judge_a="3", judge_b="3"),
        _row("T1", "addressed", judge_a="3", judge_b="3"),
    ]
    markdown = report.build_markdown(
        rows, {"agreement": 1.0, "cohen_kappa": 1.0}, ["broadcast", "addressed"]
    )
    assert "| | broadcast | addressed |" in markdown
    assert "agreement 100%" in markdown
    assert "Cohen's kappa 1.000" in markdown


def test_single_mode_takeaway() -> None:
    rows = [_row("T1", "broadcast", judge_a="3", judge_b="3")]
    aggregated = report.aggregate(rows, ["broadcast"])
    takeaway = report.render_takeaway(aggregated, rows, ["broadcast"])
    assert "single mode present" in takeaway


def test_results_csv_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "results.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(report.RESULTS_COLUMNS))
        writer.writeheader()
        writer.writerow(_row("T1", "broadcast"))
    loaded = report.read_results(path)
    assert loaded[0]["task_id"] == "T1"
    assert report._num(loaded[0]["wall_s"]) == 10.0
    assert report._num("") is None


# --- run_eval pure helpers --------------------------------------------------------


def test_planned_cells_alternates_mode_order_per_block() -> None:
    selected = [tasks.tasks_by_id()[task_id] for task_id in ("T1", "T2", "T3")]
    plan = run_eval.planned_cells(selected, ["broadcast", "addressed"], seed=7)
    by_task: dict[str, list[str]] = {}
    for task_id, mode in plan:
        by_task.setdefault(task_id, []).append(mode)
    assert all(len(modes) == 2 for modes in by_task.values())
    orderings = [tuple(modes) for modes in by_task.values()]
    assert orderings.count(("broadcast", "addressed")) == 2
    assert orderings.count(("addressed", "broadcast")) == 1
    assert run_eval.planned_cells(selected, ["broadcast", "addressed"], seed=7) == plan


def test_error_transcript_row_has_blank_metrics() -> None:
    task = tasks.tasks_by_id()["T2"]
    transcript = run_eval.error_transcript(
        task, "addressed", run=1, seed=0, message="boom", conversation_id="conv_err"
    )
    row = run_eval.csv_row(transcript, task)
    assert row["agent_turns"] == ""
    assert row["notes"].startswith("error:boom")
    assert transcript["conversation_id"] == "conv_err"


def test_csv_row_matches_design_columns() -> None:
    transcript = two_agent_transcript("Agreed.", "Risk one is error placement; fix it.")
    row = run_eval.csv_row(transcript, tasks.tasks_by_id()["T1"])
    assert set(row) == set(run_eval.RESULTS_COLUMNS)
