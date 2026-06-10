from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from xmuse_core.chat.protocol_v2 import (
    GodSpeechAct,
    GodSpeechActMessageV1,
    derive_unanswered_reply_blockers,
    sort_god_speech_act_messages,
)
from xmuse_core.integrations.memoryos_client import (
    MemoryOSClientProtocol,
    MemoryOSIngestResult,
)
from xmuse_core.integrations.memoryos_events import (
    MemoryOSWritebackEvent,
    write_memory_event,
)
from xmuse_core.integrations.memoryos_namespace import task_namespace
from xmuse_core.platform.execution.github_ops import (
    CheckStatus,
    DraftPRRecord,
    FakeGitHubOps,
    FeatureDraftPRRequest,
    MergeReadiness,
    ReviewOutcome,
    evaluate_merge_readiness,
)
from xmuse_core.platform.execution.subagent_runtime import SubagentRuntimeContract
from xmuse_core.structuring.blueprint_execution.lane_dag_service import (
    BlueprintFeatureSpec,
    BlueprintLaneDagPlan,
    BlueprintLaneDagRequest,
    BlueprintLaneDagService,
    BlueprintLaneSpec,
    LaneDependencyEdge,
    LaneDependencyType,
    LaneDispatchDecision,
    LaneExecutionStatus,
)
from xmuse_core.structuring.mission_blueprint_v1 import (
    MissionBlueprintDecisionLogEntry,
    MissionBlueprintStatus,
    MissionBlueprintV1,
)

REQUIRED_GITHUB_CHECKS = [
    "quality-gates",
    "contract-smoke-gates",
    "real-runtime-integration-gate",
]

SELF_ITERATION_BLUEPRINT_ID = "bp-self-iteration-runtime-closure"
SELF_ITERATION_CONVERSATION_ID = "conv-self-iteration-runtime-closure"
SELF_ITERATION_THREAD_ID = "thread-self-iteration-runtime-closure"


class ProofLevel(StrEnum):
    CONTRACT = "contract_proof"
    FAKE_RUNTIME = "fake_runtime_proof"
    LIVE_RUNTIME = "live_runtime_proof"
    LIVE_SERVICE = "live_service_proof"
    SERVER_SIDE_ENFORCEMENT = "server_side_enforcement_proof"
    REAL_PROVIDER = "real_provider_proof"
    MANUAL_GAP = "manual_gap"


class GitHubTruthEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_path: str
    required_checks: list[str]
    workflow_jobs: list[str]
    missing_required_checks: list[str] = Field(default_factory=list)
    codeowners_path: str
    codeowners_covers_mainline: bool
    pr_template_path: str
    pr_template_fields: list[str]
    branch_protection_verified: bool = False
    ci_visibility: str
    proof_level: ProofLevel = ProofLevel.CONTRACT


class SelfIterationEvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "self_iteration_evidence_bundle.v1"
    evidence_id: str
    blueprint_id: str
    feature_id: str
    lane_id: str
    changed_files: list[str]
    commands_run: list[str]
    test_results: list[str]
    source_refs: list[str]
    memory_refs: list[str] = Field(default_factory=list)
    risk_notes: list[str]
    rollback_notes: list[str]
    proof_level: ProofLevel

    @field_validator(
        "changed_files",
        "commands_run",
        "test_results",
        "source_refs",
        "risk_notes",
        "rollback_notes",
    )
    @classmethod
    def _validate_non_empty_list(cls, values: list[str]) -> list[str]:
        cleaned = [_require_non_empty(value) for value in values]
        if not cleaned:
            raise ValueError("list must contain at least one item")
        return cleaned

    @property
    def ref(self) -> str:
        return f"evidence:{self.evidence_id}"


class SelfIterationClosureArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    human_request: str
    transcript: list[GodSpeechActMessageV1]
    blueprint: MissionBlueprintV1
    lane_dag_request: BlueprintLaneDagRequest
    lane_dag_plan: BlueprintLaneDagPlan
    dispatch_decisions: list[LaneDispatchDecision]
    runtime_contract: SubagentRuntimeContract
    evidence_bundle: SelfIterationEvidenceBundle
    review_pass: ReviewOutcome
    review_fail: ReviewOutcome
    patch_forward_plan: BlueprintLaneDagPlan
    github_evidence: GitHubTruthEvidence
    draft_pr: DraftPRRecord
    merge_readiness: MergeReadiness


class GodDeliberationReplayExport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "god_deliberation_replay_export.v1"
    export_id: str
    transcript_source: str
    proof_level: ProofLevel
    natural_deliberation: bool
    speech_acts: list[str]
    source_refs: list[str]
    blueprint: MissionBlueprintV1

    @field_validator("export_id", "transcript_source")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _require_non_empty(value)


def build_self_iteration_replay_fixture() -> list[GodSpeechActMessageV1]:
    """Deterministic GOD groupchat fixture for the runtime closure sample."""

    return sort_god_speech_act_messages(
        [
            _gsa(
                message_id="gsa-001-propose",
                sender_god="god-planner",
                targets=["god-review", "god-memory"],
                speech_act=GodSpeechAct.PROPOSE,
                references=["human:self-iteration-runtime-closure"],
                memory_refs=["memory://global/repo/iiyazu/Cross-Muse"],
                payload={
                    "proposal": "Close one replayable xmuse self-iteration loop.",
                    "assumptions": [
                        "Default proof remains fake/local unless live gates are run."
                    ],
                    "scope": [
                        "speech acts",
                        "frozen blueprint",
                        "laneDAG",
                        "runtime contract",
                        "review",
                        "MemoryOS writeback",
                    ],
                },
            ),
            _gsa(
                message_id="gsa-002-ask-memory",
                sender_god="god-planner",
                targets=["god-memory"],
                speech_act=GodSpeechAct.ASK,
                causal_parent_id="gsa-001-propose",
                references=["message:gsa-001-propose"],
                requires_reply_by=8,
                payload={"question": "Which MemoryOS namespace proves the writeback?"},
            ),
            _gsa(
                message_id="gsa-003-challenge-proof",
                sender_god="god-review",
                targets=["god-planner"],
                speech_act=GodSpeechAct.CHALLENGE,
                causal_parent_id="gsa-001-propose",
                references=["message:gsa-001-propose"],
                requires_reply_by=8,
                payload={
                    "challenge": "Separate contract proof from live runtime proof.",
                    "blocks_freeze": True,
                },
            ),
            _gsa(
                message_id="gsa-004-object-live-claim",
                sender_god="god-review",
                targets=["god-planner"],
                speech_act=GodSpeechAct.OBJECT,
                causal_parent_id="gsa-001-propose",
                references=["message:gsa-001-propose"],
                payload={
                    "objection": "Do not claim branch protection or live services "
                    "without server evidence.",
                    "blocks_freeze": True,
                },
            ),
            _gsa(
                message_id="gsa-005-evidence-memory",
                sender_god="god-memory",
                targets=["god-planner", "god-review"],
                speech_act=GodSpeechAct.EVIDENCE,
                causal_parent_id="gsa-002-ask-memory",
                references=["message:gsa-002-ask-memory"],
                memory_refs=[
                    "memory://repo/iiyazu/Cross-Muse/workspace/xmuse/"
                    "conversation/conv-self-iteration-runtime-closure/"
                    "thread/thread-self-iteration-runtime-closure/god/god-execute/"
                    "blueprint/bp-self-iteration-runtime-closure/feature/"
                    "feature-runtime-evidence/lane/lane-runtime-evidence"
                ],
                payload={"answer": "Use task namespace and REST-first fake client in CI."},
            ),
            _gsa(
                message_id="gsa-006-evidence-proof-boundary",
                sender_god="god-planner",
                targets=["god-review"],
                speech_act=GodSpeechAct.EVIDENCE,
                causal_parent_id="gsa-003-challenge-proof",
                references=[
                    "message:gsa-003-challenge-proof",
                    "message:gsa-004-object-live-claim",
                    "docs/xmuse/self-iteration-runtime-closure-plan.md",
                ],
                payload={
                    "evidence": "Default CI exercises contract and fake runtime proof; "
                    "live proof remains opt-in debt.",
                    "resolves": [
                        "gsa-003-challenge-proof",
                        "gsa-004-object-live-claim",
                    ],
                },
            ),
            _gsa(
                message_id="gsa-007-vote-freeze",
                sender_god="god-review",
                targets=["god-convenor"],
                speech_act=GodSpeechAct.VOTE,
                causal_parent_id="gsa-006-evidence-proof-boundary",
                references=["message:gsa-006-evidence-proof-boundary"],
                payload={"vote": "approve", "reason": "Proof boundaries are explicit."},
            ),
            _gsa(
                message_id="gsa-008-decide-freeze",
                sender_god="god-convenor",
                targets=["god-planner", "god-execute", "god-memory"],
                speech_act=GodSpeechAct.DECIDE,
                causal_parent_id="gsa-007-vote-freeze",
                references=["message:gsa-007-vote-freeze"],
                payload={"decision": "Freeze blueprint and dispatch laneDAG sample."},
            ),
            _gsa(
                message_id="gsa-009-handoff-execute",
                sender_god="god-convenor",
                targets=["god-execute"],
                speech_act=GodSpeechAct.HANDOFF,
                causal_parent_id="gsa-008-decide-freeze",
                references=["message:gsa-008-decide-freeze"],
                payload={"handoff": "Build bounded runtime contract and evidence bundle."},
            ),
        ]
    )


def derive_frozen_self_iteration_blueprint(
    messages: list[GodSpeechActMessageV1],
) -> MissionBlueprintV1:
    ordered = sort_god_speech_act_messages(messages)
    _validate_required_speech_acts(ordered)
    blockers = derive_unanswered_reply_blockers(ordered, current_lamport=99)
    if blockers:
        blocker_ids = ", ".join(blocker.blocker_id for blocker in blockers)
        raise ValueError(f"cannot freeze blueprint with unanswered replies: {blocker_ids}")
    unresolved = _unresolved_blocking_messages(ordered)
    if unresolved:
        raise ValueError(
            "cannot freeze blueprint with unresolved blockers: " + ", ".join(unresolved)
        )
    return MissionBlueprintV1(
        blueprint_id=SELF_ITERATION_BLUEPRINT_ID,
        conversation_id=SELF_ITERATION_CONVERSATION_ID,
        revision=1,
        goal="Produce one replayable, auditable xmuse self-iteration loop.",
        scope=[
            "GOD speech-act replay",
            "frozen blueprint",
            "feature/lane/laneDAG authority sample",
            "subagent runtime contract and evidence bundle",
            "review pass/fail with patch-forward",
            "GitHub gate evidence",
            "REST-first MemoryOS writeback",
            "replay documentation",
        ],
        constraints=[
            "Default CI is no-secrets and no-live-service.",
            "feature_lanes.json remains projection only.",
            "Fake proof is not described as live runtime proof.",
            "MemoryOS writes remain REST-first.",
        ],
        non_goals=[
            "Full production autonomy",
            "Unverified GitHub branch protection enforcement",
            "Live Ray/Codex/MemoryOS proof in default CI",
        ],
        acceptance_contracts=[
            "Replay derives a frozen MissionBlueprintV1 from structured speech acts.",
            "Blueprint converts to typed laneDAG and scheduler dispatch decisions.",
            "SubagentRuntimeContract serializes execution authority and scope.",
            "Evidence bundle drives review approval and patch-forward rejection paths.",
            "MemoryOS fake writeback preserves actor, namespace, source refs, and layer.",
            "Documentation states proof level for every claim.",
        ],
        repo_areas=[
            "src/xmuse_core/chat/",
            "src/xmuse_core/structuring/",
            "src/xmuse_core/platform/execution/",
            "src/xmuse_core/integrations/",
            "src/xmuse_core/self_iteration/",
            "tests/xmuse/",
            "docs/xmuse/",
        ],
        open_questions=[
            "GitHub branch protection and live Actions run visibility require server evidence.",
            "Live MemoryOS Lite proof remains opt-in outside default CI.",
        ],
        decision_log=[
            MissionBlueprintDecisionLogEntry(
                decision="Proof boundaries resolved review challenge before freeze.",
                source_refs=[
                    "message:gsa-003-challenge-proof",
                    "message:gsa-006-evidence-proof-boundary",
                ],
            ),
            MissionBlueprintDecisionLogEntry(
                decision="Freeze blueprint for centralized laneDAG execution.",
                source_refs=[
                    "message:gsa-007-vote-freeze",
                    "message:gsa-008-decide-freeze",
                ],
            ),
        ],
        source_refs=[f"message:{message.message_id}" for message in ordered],
        status=MissionBlueprintStatus.FROZEN,
        approved_by=["god-review", "god-convenor"],
    )


def export_god_deliberation_replay(
    messages: list[GodSpeechActMessageV1],
    *,
    export_id: str,
    transcript_source: str,
    proof_level: ProofLevel,
    natural_deliberation: bool,
) -> GodDeliberationReplayExport:
    if natural_deliberation and proof_level not in {
        ProofLevel.LIVE_SERVICE,
        ProofLevel.REAL_PROVIDER,
    }:
        raise ValueError("natural deliberation evidence requires live/real proof level")
    if not natural_deliberation and proof_level in {
        ProofLevel.LIVE_SERVICE,
        ProofLevel.REAL_PROVIDER,
    }:
        raise ValueError("contract exports must not claim live/real deliberation proof")
    ordered = sort_god_speech_act_messages(messages)
    blueprint = derive_frozen_self_iteration_blueprint(ordered)
    return GodDeliberationReplayExport(
        export_id=export_id,
        transcript_source=transcript_source,
        proof_level=proof_level,
        natural_deliberation=natural_deliberation,
        speech_acts=[message.speech_act.value for message in ordered],
        source_refs=[f"message:{message.message_id}" for message in ordered],
        blueprint=blueprint,
    )


def build_self_iteration_lane_dag_request(
    blueprint: MissionBlueprintV1,
) -> BlueprintLaneDagRequest:
    blueprint_ref = f"blueprint:{blueprint.blueprint_id}:{blueprint.revision}"
    return BlueprintLaneDagRequest(
        graph_id="graph-self-iteration-runtime-closure",
        resolution_id="resolution-self-iteration-runtime-closure",
        graph_version=1,
        blueprint=blueprint,
        features=[
            BlueprintFeatureSpec(
                feature_id="feature-github-truth",
                title="GitHub truth alignment evidence",
                goal="Record workflow, CODEOWNERS, PR template, and settings gaps.",
                acceptance_criteria=["Required check names match workflow job names."],
                blueprint_refs=[blueprint_ref],
                expected_touched_areas=[".github/", "docs/xmuse/"],
            ),
            BlueprintFeatureSpec(
                feature_id="feature-replay-lanedag",
                title="Self-iteration replay and laneDAG sample",
                goal="Convert the frozen blueprint to a deterministic typed laneDAG.",
                acceptance_criteria=["Replay fixture drives laneDAG authority data."],
                blueprint_refs=[blueprint_ref],
                depends_on_features=["feature-github-truth"],
                expected_touched_areas=[
                    "src/xmuse_core/chat/",
                    "src/xmuse_core/structuring/",
                ],
            ),
            BlueprintFeatureSpec(
                feature_id="feature-runtime-evidence",
                title="Runtime contract and evidence bundle",
                goal="Bound local fake subagent execution with auditable evidence.",
                acceptance_criteria=["Runtime contract and evidence bundle serialize."],
                blueprint_refs=[blueprint_ref],
                depends_on_features=["feature-replay-lanedag"],
                expected_touched_areas=["src/xmuse_core/platform/execution/"],
                memory_refs=["memory://conversation/conv-self-iteration-runtime-closure"],
            ),
            BlueprintFeatureSpec(
                feature_id="feature-review-writeback-docs",
                title="Review, writeback, and replay documentation",
                goal="Prove review pass/fail, MemoryOS writeback, and replay artifact.",
                acceptance_criteria=["Patch-forward and REST-first writeback are covered."],
                blueprint_refs=[blueprint_ref],
                depends_on_features=["feature-runtime-evidence"],
                expected_touched_areas=["src/xmuse_core/integrations/", "docs/xmuse/"],
            ),
        ],
        lanes=[
            BlueprintLaneSpec(
                lane_id="lane-github-truth",
                feature_id="feature-github-truth",
                title="Align GitHub truth evidence",
                prompt="Inspect local workflow, CODEOWNERS, and PR template evidence.",
                acceptance_criteria=["GitHub evidence records unverified server gaps."],
                blueprint_refs=[blueprint_ref],
                gate_profiles=["ruff", "pytest"],
            ),
            BlueprintLaneSpec(
                lane_id="lane-replay-lanedag",
                feature_id="feature-replay-lanedag",
                title="Replay blueprint to laneDAG",
                prompt="Build deterministic speech-act replay and laneDAG authority sample.",
                acceptance_criteria=["Typed laneDAG includes hard, soft, review, artifact edges."],
                blueprint_refs=[blueprint_ref],
                dependency_edges=[
                    LaneDependencyEdge(
                        source_lane_id="lane-github-truth",
                        target_lane_id="lane-replay-lanedag",
                        edge_type=LaneDependencyType.SOFT_DEP,
                        rationale="GitHub proof boundaries inform replay documentation.",
                        source_refs=["message:gsa-006-evidence-proof-boundary"],
                    )
                ],
                gate_profiles=["ruff", "pytest"],
            ),
            BlueprintLaneSpec(
                lane_id="lane-runtime-evidence",
                feature_id="feature-runtime-evidence",
                title="Runtime contract and evidence bundle",
                prompt="Create bounded subagent contract and fake/local evidence bundle.",
                acceptance_criteria=[
                    "Worker evidence has files, commands, tests, risks, rollback."
                ],
                blueprint_refs=[blueprint_ref],
                gate_profiles=["ruff", "pytest", "mypy"],
                memory_refs=["memory://conversation/conv-self-iteration-runtime-closure"],
            ),
            BlueprintLaneSpec(
                lane_id="lane-review-writeback-docs",
                feature_id="feature-review-writeback-docs",
                title="Review, writeback, and replay docs",
                prompt="Route evidence through review, MemoryOS fake writeback, and docs.",
                acceptance_criteria=["Review failure appends patch-forward lane."],
                blueprint_refs=[blueprint_ref],
                dependency_edges=[
                    LaneDependencyEdge(
                        source_lane_id="lane-runtime-evidence",
                        target_lane_id="lane-review-writeback-docs",
                        edge_type=LaneDependencyType.REVIEW_DEP,
                        rationale="Writeback and docs require review evidence.",
                        source_refs=["evidence:self-iteration-lane-runtime-evidence"],
                    ),
                    LaneDependencyEdge(
                        source_lane_id="lane-replay-lanedag",
                        target_lane_id="lane-review-writeback-docs",
                        edge_type=LaneDependencyType.ARTIFACT_DEP,
                        rationale="Replay artifact must include laneDAG output.",
                        source_refs=["graph:graph-self-iteration-runtime-closure"],
                    ),
                ],
                gate_profiles=["ruff", "pytest", "mypy"],
            ),
        ],
        source_refs=["message:gsa-008-decide-freeze", "message:gsa-009-handoff-execute"],
    )


def build_self_iteration_runtime_contract(
    plan: BlueprintLaneDagPlan,
    *,
    worktree_path: Path,
    lane_id: str = "lane-runtime-evidence",
) -> SubagentRuntimeContract:
    lane = _find_lane(plan, lane_id)
    depends_on = [
        edge.source_lane_id
        for edge in plan.dependency_edges
        if edge.target_lane_id == lane_id and edge.dispatch_blocking
    ]
    memory_context_ref = _task_memory_ref(plan.blueprint_id, lane_id)
    return SubagentRuntimeContract(
        blueprint_id=plan.blueprint_id,
        feature_id="feature-runtime-evidence",
        lane_id=lane_id,
        depends_on=depends_on,
        worktree_path=worktree_path,
        allowed_files=[
            "src/xmuse_core/self_iteration/",
            "src/xmuse_core/platform/execution/subagent_runtime.py",
            "tests/xmuse/test_self_iteration_runtime_closure.py",
            "docs/xmuse/",
        ],
        allowed_tools=["read", "edit", "uv_run", "git"],
        write_scope=[
            "src/xmuse_core/self_iteration/",
            "src/xmuse_core/platform/execution/subagent_runtime.py",
            "tests/xmuse/",
            "docs/xmuse/",
        ],
        acceptance_criteria=list(lane.acceptance_criteria),
        required_checks=list(REQUIRED_GITHUB_CHECKS),
        gate_profiles=list(lane.gate_profiles),
        base_branch="main",
        source_context_refs=[
            plan.blueprint_ref,
            "lane:lane-runtime-evidence",
            "message:gsa-009-handoff-execute",
        ],
        memory_context_ref=memory_context_ref,
        memory_context={"namespace": memory_context_ref, "proof_level": ProofLevel.CONTRACT},
        rollback_plan=(
            "Revert the self-iteration closure commit or create a patch-forward lane "
            "linked to the failed review evidence."
        ),
        review_profile="self-iteration-contract",
    )


def build_self_iteration_evidence_bundle(
    contract: SubagentRuntimeContract,
) -> SelfIterationEvidenceBundle:
    changed_files = contract.validate_write_paths(
        [
            "src/xmuse_core/self_iteration/runtime_closure.py",
            "tests/xmuse/test_self_iteration_runtime_closure.py",
            "docs/xmuse/self-iteration-runtime-closure.md",
        ]
    )
    return SelfIterationEvidenceBundle(
        evidence_id="self-iteration-lane-runtime-evidence",
        blueprint_id=contract.blueprint_id or SELF_ITERATION_BLUEPRINT_ID,
        feature_id=contract.feature_id,
        lane_id=contract.lane_id,
        changed_files=changed_files,
        commands_run=[
            "uv run ruff check .",
            "uv run pytest -q tests/xmuse/test_self_iteration_runtime_closure.py",
            "uv run mypy src/xmuse_core/self_iteration/runtime_closure.py "
            "src/xmuse_core/platform/execution/subagent_runtime.py",
        ],
        test_results=["focused self-iteration contract tests pass in fake/local mode"],
        source_refs=list(contract.source_context_refs),
        memory_refs=[contract.memory_context_ref] if contract.memory_context_ref else [],
        risk_notes=[
            "GitHub branch protection requires server-side evidence before live claim.",
            "Live MemoryOS Lite remains opt-in outside default CI.",
        ],
        rollback_notes=[contract.rollback_plan],
        proof_level=ProofLevel.FAKE_RUNTIME,
    )


def review_self_iteration_evidence(
    evidence: SelfIterationEvidenceBundle,
    *,
    approve: bool,
) -> ReviewOutcome:
    if approve:
        return ReviewOutcome(
            verdict="approved",
            summary="Evidence bundle satisfies self-iteration contract proof.",
            evidence_refs=[evidence.ref],
        )
    return ReviewOutcome(
        verdict="changes_requested",
        summary="Patch-forward required to address missing runtime evidence.",
        evidence_refs=[evidence.ref, "review:self-iteration:changes-requested"],
    )


def read_github_truth_evidence(repo_root: Path) -> GitHubTruthEvidence:
    workflow_path = repo_root / ".github" / "workflows" / "xmuse-ci.yml"
    codeowners_path = repo_root / "CODEOWNERS"
    pr_template_path = repo_root / ".github" / "pull_request_template.md"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    codeowners_text = codeowners_path.read_text(encoding="utf-8")
    pr_template_text = pr_template_path.read_text(encoding="utf-8")
    jobs = _extract_workflow_jobs(workflow_text)
    template_fields = _extract_pr_template_fields(pr_template_text)
    return GitHubTruthEvidence(
        workflow_path=workflow_path.relative_to(repo_root).as_posix(),
        required_checks=list(REQUIRED_GITHUB_CHECKS),
        workflow_jobs=jobs,
        missing_required_checks=[
            check for check in REQUIRED_GITHUB_CHECKS if check not in jobs
        ],
        codeowners_path=codeowners_path.relative_to(repo_root).as_posix(),
        codeowners_covers_mainline=all(
            area in codeowners_text
            for area in [
                "/src/xmuse_core/chat/",
                "/src/xmuse_core/structuring/",
                "/src/xmuse_core/platform/",
                "/src/xmuse_core/integrations/",
                "/.github/",
                "/docs/xmuse/",
            ]
        ),
        pr_template_path=pr_template_path.relative_to(repo_root).as_posix(),
        pr_template_fields=template_fields,
        branch_protection_verified=False,
        ci_visibility=(
            "local workflow contract only; server-side branch protection and latest "
            "Actions run require GitHub evidence"
        ),
    )


def build_self_iteration_closure_artifacts(
    *,
    repo_root: Path,
    worktree_path: Path,
) -> SelfIterationClosureArtifacts:
    transcript = build_self_iteration_replay_fixture()
    blueprint = derive_frozen_self_iteration_blueprint(transcript)
    request = build_self_iteration_lane_dag_request(blueprint)
    service = BlueprintLaneDagService()
    plan = service.build_plan(request)
    dispatch = service.evaluate_dispatch(
        plan,
        lane_statuses={
            "lane-github-truth": LaneExecutionStatus.APPROVED,
            "lane-replay-lanedag": LaneExecutionStatus.APPROVED,
        },
    )
    contract = build_self_iteration_runtime_contract(plan, worktree_path=worktree_path)
    evidence = build_self_iteration_evidence_bundle(contract)
    review_pass = review_self_iteration_evidence(evidence, approve=True)
    review_fail = review_self_iteration_evidence(evidence, approve=False)
    patch_plan = service.append_patch_forward_lane(
        plan,
        failed_lane_id=contract.lane_id,
        patch_lane_id="lane-runtime-evidence-patch-1",
        prompt="Patch missing runtime evidence without overwriting failed lane state.",
        acceptance_criteria=["Patch-forward evidence resolves review finding."],
        verdict_ref="review:self-iteration:changes-requested",
        evidence_refs=list(review_fail.evidence_refs),
    )
    github_evidence = read_github_truth_evidence(repo_root)
    draft_pr = FakeGitHubOps().create_or_update_feature_draft_pr(
        FeatureDraftPRRequest(
            feature_id=contract.feature_id,
            feature_ids=list(plan.feature_ids),
            title="Self-iteration runtime closure",
            base_branch=contract.base_branch,
            head_branch="self-iteration-runtime-closure",
            blueprint_refs=[plan.blueprint_ref],
            lane_refs=[lane.feature_id for lane in plan.lane_graph.lanes],
            depends_on_lanes=list(contract.depends_on),
            acceptance_criteria=list(contract.acceptance_criteria),
            evidence_bundle_refs=[evidence.ref],
            review_evidence_bundle=list(review_pass.evidence_refs),
            memory_refs=list(evidence.memory_refs),
            memory_impact="task_state writeback through REST-first MemoryOS contract",
            new_artifacts=["docs/xmuse/self-iteration-runtime-closure.md"],
            provider_changes=["none; default proof is fake/local"],
            gate_profile=",".join(contract.required_checks),
            rollback_plan=contract.rollback_plan,
            privacy_impact="no transcript export beyond deterministic fixture refs",
        )
    )
    merge_readiness = evaluate_merge_readiness(
        [
            CheckStatus(name="quality-gates", status="success"),
            CheckStatus(name="contract-smoke-gates", status="success"),
            CheckStatus(name="real-runtime-integration-gate", status="success"),
        ],
        review_evidence_refs=list(review_pass.evidence_refs),
        required_check_names=list(REQUIRED_GITHUB_CHECKS),
    )
    return SelfIterationClosureArtifacts(
        human_request=(
            "Execute the xmuse Self-Iteration Runtime Closure plan and produce one "
            "auditable replay loop."
        ),
        transcript=transcript,
        blueprint=blueprint,
        lane_dag_request=request,
        lane_dag_plan=plan,
        dispatch_decisions=dispatch,
        runtime_contract=contract,
        evidence_bundle=evidence,
        review_pass=review_pass,
        review_fail=review_fail,
        patch_forward_plan=patch_plan,
        github_evidence=github_evidence,
        draft_pr=draft_pr,
        merge_readiness=merge_readiness,
    )


async def write_self_iteration_memory_evidence(
    client: MemoryOSClientProtocol,
    artifacts: SelfIterationClosureArtifacts,
    *,
    commit_sha: str | None = None,
) -> list[MemoryOSIngestResult]:
    namespace = task_namespace(
        repo_id="iiyazu/Cross-Muse",
        workspace_id="xmuse",
        god_id="god-execute",
        conversation_id=artifacts.blueprint.conversation_id,
        thread_id=SELF_ITERATION_THREAD_ID,
        blueprint_id=artifacts.blueprint.blueprint_id,
        feature_id=artifacts.runtime_contract.feature_id,
        lane_id=artifacts.runtime_contract.lane_id,
    )
    events = [
        MemoryOSWritebackEvent(
            kind="blueprint_frozen",
            namespace=namespace,
            actor_id="god-convenor",
            event_id=artifacts.blueprint.blueprint_id,
            summary="Self-iteration runtime closure blueprint frozen.",
            source_refs=artifacts.blueprint.source_refs[:4],
            commit_sha=commit_sha,
            metadata={"memory_layer": "task_state", "proof_level": ProofLevel.CONTRACT},
        ),
        MemoryOSWritebackEvent(
            kind="feature_reworked",
            namespace=namespace,
            actor_id="god-execute",
            event_id=artifacts.evidence_bundle.evidence_id,
            summary="Lane runtime evidence bundle produced in fake/local mode.",
            source_refs=[artifacts.evidence_bundle.ref, *artifacts.evidence_bundle.source_refs],
            commit_sha=commit_sha,
            metadata={"memory_layer": "task_state", "proof_level": ProofLevel.FAKE_RUNTIME},
        ),
        MemoryOSWritebackEvent(
            kind="review_verdict_finalized",
            namespace=namespace,
            actor_id="god-review",
            event_id="self-iteration-review-approved",
            summary=artifacts.review_pass.summary,
            source_refs=list(artifacts.review_pass.evidence_refs),
            commit_sha=commit_sha,
            metadata={"memory_layer": "task_state", "proof_level": ProofLevel.CONTRACT},
        ),
        MemoryOSWritebackEvent(
            kind="merge_readiness_evaluated",
            namespace=namespace,
            actor_id="god-github",
            event_id="self-iteration-gate-outcome",
            summary=artifacts.merge_readiness.reason,
            source_refs=[
                f"draft-pr:{artifacts.draft_pr.number}",
                *artifacts.review_pass.evidence_refs,
            ],
            commit_sha=commit_sha,
            metadata={
                "memory_layer": "task_state",
                "proof_level": ProofLevel.CONTRACT,
                "real_merge_event": False,
            },
        ),
    ]
    results: list[MemoryOSIngestResult] = []
    for event in events:
        results.append(await write_memory_event(client, event))
    return results


def _validate_required_speech_acts(messages: list[GodSpeechActMessageV1]) -> None:
    observed = {message.speech_act for message in messages}
    required = {
        GodSpeechAct.PROPOSE,
        GodSpeechAct.ASK,
        GodSpeechAct.CHALLENGE,
        GodSpeechAct.OBJECT,
        GodSpeechAct.VOTE,
        GodSpeechAct.DECIDE,
        GodSpeechAct.EVIDENCE,
        GodSpeechAct.HANDOFF,
    }
    missing = sorted(speech_act.value for speech_act in required - observed)
    if missing:
        raise ValueError("missing required speech acts: " + ", ".join(missing))


def _gsa(
    *,
    message_id: str,
    sender_god: str,
    targets: list[str],
    speech_act: GodSpeechAct,
    payload: dict[str, Any],
    references: list[str] | None = None,
    causal_parent_id: str | None = None,
    memory_refs: list[str] | None = None,
    requires_reply_by: int | None = None,
) -> GodSpeechActMessageV1:
    return GodSpeechActMessageV1(
        message_id=message_id,
        conversation_id=SELF_ITERATION_CONVERSATION_ID,
        thread_id=SELF_ITERATION_THREAD_ID,
        sender_god=sender_god,
        targets=targets,
        speech_act=speech_act,
        references=references or [],
        causal_parent_id=causal_parent_id,
        confidence=0.92,
        memory_refs=memory_refs or [],
        requires_reply_by=requires_reply_by,
        payload=payload,
    )


def _unresolved_blocking_messages(messages: list[GodSpeechActMessageV1]) -> list[str]:
    resolving_refs: set[str] = set()
    for message in messages:
        if message.speech_act not in {GodSpeechAct.EVIDENCE, GodSpeechAct.DECIDE}:
            continue
        resolving_refs.update(message.references)
        resolved = message.payload.get("resolves")
        if isinstance(resolved, list):
            resolving_refs.update(f"message:{item}" for item in resolved if isinstance(item, str))
    unresolved: list[str] = []
    for message in messages:
        if message.speech_act not in {GodSpeechAct.CHALLENGE, GodSpeechAct.OBJECT}:
            continue
        if message.payload.get("blocks_freeze") is not True:
            continue
        if f"message:{message.message_id}" not in resolving_refs:
            unresolved.append(message.message_id)
    return unresolved


def _extract_workflow_jobs(workflow_text: str) -> list[str]:
    jobs: list[str] = []
    in_jobs = False
    for line in workflow_text.splitlines():
        if line == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if line.startswith("  ") and not line.startswith("    ") and line.rstrip().endswith(":"):
            jobs.append(line.strip().removesuffix(":"))
    return jobs


def _extract_pr_template_fields(template_text: str) -> list[str]:
    fields: list[str] = []
    for line in template_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") and stripped.endswith(":"):
            fields.append(stripped.removeprefix("- ").removesuffix(":"))
    return fields


def _find_lane(plan: BlueprintLaneDagPlan, lane_id: str):
    for lane in plan.lane_graph.lanes:
        if lane.feature_id == lane_id:
            return lane
    raise ValueError(f"unknown lane: {lane_id}")


def _task_memory_ref(blueprint_id: str, lane_id: str) -> str:
    return task_namespace(
        repo_id="iiyazu/Cross-Muse",
        workspace_id="xmuse",
        god_id="god-execute",
        conversation_id=SELF_ITERATION_CONVERSATION_ID,
        thread_id=SELF_ITERATION_THREAD_ID,
        blueprint_id=blueprint_id,
        feature_id="feature-runtime-evidence",
        lane_id=lane_id,
    ).uri


def _require_non_empty(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("value must be non-empty")
    return value
