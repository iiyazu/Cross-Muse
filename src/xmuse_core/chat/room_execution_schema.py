"""Pure SQLite schema and additive migrations for Room execution authority."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


def _schema_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _execute_schema(conn: sqlite3.Connection, script: str) -> None:
    for statement in script.split(";"):
        if cleaned := statement.strip():
            conn.execute(cleaned)


def create_room_execution_schema(conn: sqlite3.Connection) -> None:
    """Create the additive exact execution authority ledger."""

    _execute_schema(
        conn,
        """
        create table if not exists room_execution_policies (
            conversation_id text primary key references conversations(id),
            mode text not null check (mode in ('manual','consensus')),
            revision integer not null check (revision >= 0),
            risk_policy_revision text not null,
            created_at text not null,
            updated_at text not null
        );

        create table if not exists room_execution_candidates (
            candidate_id text primary key,
            proposal_id text not null unique references proposals(id),
            conversation_id text not null references conversations(id),
            author_participant_id text not null references participants(participant_id),
            author_identity_fingerprint text not null,
            source_observation_id text not null references room_observations(observation_id),
            source_batch_id text references room_observation_batches(batch_id),
            source_attempt_id text not null references room_observation_attempts(attempt_id),
            source_activity_id text not null unique references room_activities(activity_id),
            source_correlation_id text not null,
            base_head text not null,
            summary text not null,
            unified_diff text not null,
            allowed_files_json text not null,
            files_json text not null,
            candidate_digest text not null,
            patch_sha256 text not null,
            review_material_digest text not null,
            patch_bytes integer not null check (patch_bytes > 0 and patch_bytes <= 204800),
            file_count integer not null check (file_count between 1 and 32),
            modify_only integer not null check (modify_only in (0,1)),
            context_fit_eligible integer not null check (context_fit_eligible in (0,1)),
            direct_human_root integer not null check (direct_human_root in (0,1)),
            peer_snapshot_digest text not null,
            policy_mode_snapshot text not null check (
                policy_mode_snapshot in ('manual','consensus')
            ),
            policy_revision_snapshot integer not null,
            risk_policy_revision_snapshot text not null,
            state text not null check (state in ('open','authorized','rejected')),
            consensus_state text not null check (
                consensus_state in ('collecting','endorsed','objected','abstained','invalidated')
            ),
            revision integer not null check (revision >= 0),
            reason_code text,
            created_at text not null,
            updated_at text not null,
            authorized_at text,
            rejected_at text
        );

        create table if not exists room_execution_candidate_members (
            candidate_id text not null references room_execution_candidates(candidate_id)
                on delete cascade,
            participant_id text not null references participants(participant_id),
            identity_fingerprint text not null,
            ordinal integer not null check (ordinal >= 0),
            status_snapshot text not null,
            review_attempt_id text references room_observation_attempts(attempt_id),
            review_batch_id text references room_observation_batches(batch_id),
            review_activity_id text references room_activities(activity_id),
            review_material_digest text,
            review_context_payload_sha256 text,
            full_material_available integer not null default 0 check (
                full_material_available in (0,1)
            ),
            review_bound_at text,
            primary key(candidate_id, participant_id),
            unique(candidate_id, ordinal),
            check (
              (full_material_available = 0 and review_attempt_id is null
               and review_batch_id is null and review_activity_id is null
               and review_material_digest is null and review_context_payload_sha256 is null
               and review_bound_at is null)
              or
              (full_material_available = 1 and review_attempt_id is not null
               and review_batch_id is not null and review_activity_id is not null
               and review_material_digest is not null
               and review_context_payload_sha256 is not null and review_bound_at is not null)
            )
        );

        create table if not exists room_execution_assessments (
            assessment_id text primary key,
            candidate_id text not null references room_execution_candidates(candidate_id),
            assessor_participant_id text not null references participants(participant_id),
            assessor_identity_fingerprint text not null,
            assessment text not null check (assessment in ('endorse','object','abstain')),
            rationale text not null,
            candidate_digest text not null,
            review_material_digest text not null,
            source_attempt_id text not null references room_observation_attempts(attempt_id),
            source_batch_id text not null references room_observation_batches(batch_id),
            source_activity_id text not null references room_activities(activity_id),
            created_at text not null,
            unique(candidate_id, assessor_participant_id)
        );

        create table if not exists room_execution_operator_actions (
            action_id text primary key,
            conversation_id text not null references conversations(id),
            candidate_id text references room_execution_candidates(candidate_id),
            run_id text references room_execution_runs(run_id),
            action_type text not null check (
                action_type in ('policy_update','candidate_execute','candidate_reject','run_cancel')
            ),
            client_action_id text not null,
            operator_identity text not null,
            request_fingerprint text not null,
            expected_candidate_digest text,
            expected_candidate_revision integer,
            expected_policy_revision integer,
            expected_run_state text,
            expected_run_revision integer,
            status text not null check (status in ('requested','applied','rejected','failed')),
            result_json text not null,
            reason_code text,
            requested_at text not null,
            applied_at text,
            updated_at text not null,
            unique(operator_identity, client_action_id)
        );

        create table if not exists room_execution_authorizations (
            authorization_id text primary key,
            candidate_id text not null unique references room_execution_candidates(candidate_id),
            conversation_id text not null references conversations(id),
            authorization_mode text not null check (authorization_mode in ('manual','consensus')),
            candidate_digest text not null,
            candidate_revision integer not null,
            policy_revision integer not null,
            risk_policy_revision text not null,
            peer_snapshot_digest text not null,
            workspace_guard_digest text not null,
            risk_evidence_digest text,
            status text not null check (status in ('active','consumed','invalidated')),
            reason_code text,
            created_at text not null,
            consumed_at text,
            invalidated_at text
        );

        create table if not exists room_execution_runs (
            run_id text primary key,
            authorization_id text not null unique
                references room_execution_authorizations(authorization_id),
            candidate_id text not null unique references room_execution_candidates(candidate_id),
            conversation_id text not null references conversations(id),
            state text not null check (state in (
                'requested','preparing','staging','verifying','ready_to_promote','promoting',
                'cancel_requested','cancel_pending','cancelled','succeeded','failed','blocked'
            )),
            revision integer not null check (revision >= 0),
            control_seq integer not null check (control_seq >= 0),
            execution_generation integer not null check (execution_generation >= 0),
            controller_id text,
            controller_generation text,
            controller_pid integer check (controller_pid is null or controller_pid > 0),
            controller_start_identity text,
            reason_code text,
            changed_files_json text not null,
            gate_ids_json text not null,
            evidence_digest text,
            requested_at text not null,
            started_at text,
            finished_at text,
            updated_at text not null
        );

        create table if not exists room_execution_gate_plan_bindings (
            binding_id text primary key,
            authorization_id text not null unique
                references room_execution_authorizations(authorization_id),
            run_id text not null unique references room_execution_runs(run_id),
            schema_version text not null check (
                schema_version = 'room_execution_gate_profile/v1'
            ),
            profile_id text not null,
            profile_revision integer not null check (profile_revision > 0),
            profile_digest text not null,
            gate_ids_json text not null,
            repository_manifest_digest text not null,
            toolchain_capability_digest text not null,
            gate_plan_digest text not null,
            created_at text not null
        );

        create table if not exists room_execution_gate_evidence (
            evidence_id text primary key,
            run_id text not null references room_execution_runs(run_id) on delete cascade,
            execution_generation integer not null,
            gate_id text not null,
            status text not null check (status in ('running','passed','failed','cancelled')),
            evidence_digest text not null,
            reason_code text,
            started_at text not null,
            finished_at text,
            created_at text not null,
            updated_at text not null,
            unique(run_id, execution_generation, gate_id)
        );

        create table if not exists room_execution_promotion_journal (
            journal_id text primary key,
            run_id text not null unique references room_execution_runs(run_id),
            execution_generation integer not null,
            target_head text not null,
            pre_manifest_digest text not null,
            post_manifest_digest text not null,
            file_entries_json text not null,
            status text not null check (status in ('prepared','applying','applied','ambiguous')),
            observed_manifest_digest text,
            prepared_at text not null,
            applied_at text,
            updated_at text not null
        );
        """,
    )
    conn.execute(
        "create index if not exists idx_room_execution_candidates_room_created "
        "on room_execution_candidates(conversation_id, created_at desc, candidate_id)"
    )
    conn.execute(
        "create index if not exists idx_room_execution_runs_room_requested "
        "on room_execution_runs(conversation_id, requested_at desc, run_id)"
    )
    conn.execute(
        "create index if not exists idx_room_execution_runs_dispatch "
        "on room_execution_runs(state, requested_at, run_id)"
    )
    stamp = _schema_timestamp()
    unbound_states = (
        "requested",
        "preparing",
        "staging",
        "verifying",
        "ready_to_promote",
        "promoting",
        "cancel_requested",
        "cancel_pending",
    )
    placeholders = ",".join("?" for _ in unbound_states)
    unbound = (
        f"select r.run_id from room_execution_runs r "
        "left join room_execution_gate_plan_bindings b on b.run_id = r.run_id "
        f"where b.run_id is null and r.state in ({placeholders})"
    )
    conn.execute(
        "update room_execution_authorizations set status = 'invalidated', "
        "reason_code = 'execution_gate_plan_missing', invalidated_at = ? "
        "where authorization_id in "
        "(select authorization_id from room_execution_runs "
        f"where run_id in ({unbound}))",
        (stamp, *unbound_states),
    )
    conn.execute(
        "update room_execution_runs set state = 'blocked', revision = revision + 1, "
        "reason_code = 'execution_gate_plan_missing', controller_id = null, "
        "controller_generation = null, controller_pid = null, "
        "controller_start_identity = null, finished_at = coalesce(finished_at, ?), "
        f"updated_at = ? where run_id in ({unbound})",
        (stamp, stamp, *unbound_states),
    )
