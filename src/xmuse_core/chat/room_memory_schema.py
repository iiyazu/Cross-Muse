"""SQLite schema and additive migrations for source-backed Room memory."""

from __future__ import annotations

import sqlite3

from xmuse_core.chat.room_memory_binding_conn import ensure_room_memory_bindings_conn


def _execute_schema(conn: sqlite3.Connection, script: str) -> None:
    for statement in script.split(";"):
        if cleaned := statement.strip():
            conn.execute(cleaned)


def create_room_memory_schema(conn: sqlite3.Connection) -> None:
    """Create memory authority and deterministic reference-only backfills."""

    _execute_schema(
        conn,
        """
        create table if not exists room_memory_bindings (
            binding_id text primary key,
            conversation_id text not null references conversations(id),
            scope_type text not null check (scope_type in ('room','local_user','project')),
            scope_key text not null,
            archive_id text not null,
            session_id text,
            session_state text not null check (
                session_state in ('unbound','creating','bound','uncertain')
            ),
            session_request_id text,
            session_retry_count integer not null default 0 check (session_retry_count >= 0),
            session_retry_not_before text,
            attachment_id text,
            attachment_state text not null check (
                attachment_state in ('pending','attaching','attached','uncertain')
            ),
            attachment_request_id text,
            attachment_retry_count integer not null default 0
                check (attachment_retry_count >= 0),
            attachment_retry_not_before text,
            revision integer not null check (revision >= 0),
            created_at text not null,
            updated_at text not null,
            unique(conversation_id, scope_type),
            check ((session_state = 'bound' and session_id is not null)
                   or session_state <> 'bound'),
            check ((attachment_state = 'attached' and attachment_id is not null)
                   or attachment_state <> 'attached')
        );

        create table if not exists room_memory_candidates (
            candidate_id text primary key,
            conversation_id text not null references conversations(id),
            author_participant_id text not null references participants(participant_id),
            source_observation_id text not null references room_observations(observation_id),
            source_batch_id text not null references room_observation_batches(batch_id),
            source_attempt_id text not null references room_observation_attempts(attempt_id),
            kind text not null check (
                kind in ('room_fact','room_decision','user_preference','project_rule')
            ),
            content text not null,
            content_sha256 text not null,
            source_activity_ids_json text not null,
            candidate_digest text not null,
            approval_state text not null check (
                approval_state in ('pending','approved','rejected')
            ),
            approval_mode text not null check (approval_mode in ('automatic','operator')),
            publish_state text not null check (
                publish_state in ('not_queued','queued','delivered','failed','conflict')
            ),
            target_scope text not null check (target_scope in ('room','local_user','project')),
            revision integer not null check (revision >= 0),
            reason_code text,
            resolved_by text,
            resolution_client_action_id text unique,
            resolution_request_fingerprint text,
            created_at text not null,
            resolved_at text,
            updated_at text not null
        );

        create table if not exists room_memory_candidate_actions (
            action_id text primary key,
            candidate_id text not null references room_memory_candidates(candidate_id),
            conversation_id text not null references conversations(id),
            client_action_id text not null,
            operator_identity text not null,
            request_fingerprint text not null,
            decision text not null check (decision in ('approve','reject')),
            status text not null check (status in ('applied','rejected')),
            reason_code text,
            result_json text not null,
            created_at text not null,
            unique(operator_identity, client_action_id)
        );

        create table if not exists room_memory_outbox (
            outbox_id text primary key,
            conversation_id text not null references conversations(id),
            activity_id text unique references room_activities(activity_id),
            candidate_id text unique references room_memory_candidates(candidate_id),
            document_id text not null unique,
            target_scope text not null check (target_scope in ('room','local_user','project')),
            state text not null check (
                state in ('pending','claimed','delivered','failed','conflict')
            ),
            attempt_count integer not null check (attempt_count >= 0),
            lease_owner text,
            lease_token text,
            acquired_at text,
            expires_at text,
            current_delivery_id text,
            reason_code text,
            next_attempt_at text,
            created_at text not null,
            updated_at text not null,
            delivered_at text,
            check ((activity_id is not null) <> (candidate_id is not null))
        );

        -- Message delivery is deliberately a separate ledger from the existing
        -- archival document outbox.  The two MemoryOS APIs have different
        -- idempotency contracts, and keeping them separate means a failed
        -- message ingest can never mark an archival source as delivered.
        create table if not exists room_memory_message_outbox (
            message_outbox_id text primary key,
            conversation_id text not null references conversations(id),
            activity_id text not null unique references room_activities(activity_id),
            external_id text not null unique,
            state text not null check (
                state in ('pending','claimed','delivered','failed','conflict')
            ),
            attempt_count integer not null check (attempt_count >= 0),
            lease_owner text,
            lease_token text,
            acquired_at text,
            expires_at text,
            current_delivery_id text,
            reason_code text,
            next_attempt_at text,
            created_at text not null,
            updated_at text not null,
            delivered_at text
        );

        create table if not exists room_memory_message_deliveries (
            delivery_id text primary key,
            message_outbox_id text not null
                references room_memory_message_outbox(message_outbox_id),
            attempt_number integer not null check (attempt_number > 0),
            worker_id text not null,
            lease_token_sha256 text not null,
            state text not null check (state in ('claimed','delivered','failed','conflict')),
            request_digest text,
            response_digest text,
            -- MemoryOS message identity is retained only for source proof.  It
            -- never crosses the Room/browser projection boundary.
            memoryos_message_id text,
            memoryos_session_id text,
            reason_code text,
            claimed_at text not null,
            finished_at text,
            updated_at text not null,
            unique(message_outbox_id, attempt_number)
        );

        create table if not exists room_memory_deliveries (
            delivery_id text primary key,
            outbox_id text not null references room_memory_outbox(outbox_id),
            attempt_number integer not null check (attempt_number > 0),
            worker_id text not null,
            lease_token_sha256 text not null,
            state text not null check (state in ('claimed','delivered','failed','conflict')),
            request_digest text,
            response_digest text,
            reason_code text,
            claimed_at text not null,
            finished_at text,
            updated_at text not null,
            unique(outbox_id, attempt_number)
        );

        create table if not exists room_memory_attempt_receipts (
            receipt_id text primary key,
            attempt_id text not null unique references room_observation_attempts(attempt_id),
            conversation_id text not null references conversations(id),
            participant_id text not null references participants(participant_id),
            correlation_id text not null,
            status text not null check (status in (
                'disabled','ok','empty','timeout','unavailable','schema_rejected',
                'source_rejected','oversize','error'
            )),
            schema_version text,
            latency_ms integer not null check (latency_ms >= 0 and latency_ms <= 60000),
            item_count integer not null check (item_count >= 0 and item_count <= 8),
            item_refs_json text not null,
            source_activity_ids_json text not null,
            evidence_sha256 text not null,
            context_payload_sha256 text,
            context_submitted_at text,
            request_fingerprint text not null,
            created_at text not null,
            updated_at text not null,
            check ((context_payload_sha256 is null and context_submitted_at is null)
                   or (context_payload_sha256 is not null and context_submitted_at is not null))
        );

        -- External MemoryOS kernel suggestions are advisory input, not Room
        -- outcomes.  Keep a bounded receipt even when source proof or
        -- candidate governance rejects one so recall cannot look healthy
        -- while silently dropping the governance handoff.
        create table if not exists room_memory_advisory_receipts (
            receipt_id text primary key,
            conversation_id text not null references conversations(id),
            attempt_id text not null references room_observation_attempts(attempt_id),
            advisory_id text not null,
            advisory_fingerprint text not null,
            status text not null check (status in ('accepted','duplicate','rejected')),
            reason_code text not null,
            candidate_digest text,
            source_activity_ids_json text not null,
            created_at text not null,
            updated_at text not null,
            unique(attempt_id, advisory_id)
        );

        create table if not exists room_memory_rebuild_actions (
            action_id text primary key,
            client_action_id text not null unique,
            operator_identity text not null,
            request_fingerprint text not null,
            incident_guard text not null,
            runtime_generation text,
            status text not null check (
                status in ('requested','applied','rejected','failed')
            ),
            phase text not null check (
                phase in ('requested','stopping','stopped','cache_cleared',
                          'authority_reset','restarting','replaying','complete')
            ),
            revision integer not null check (revision >= 0),
            before_state text not null,
            before_code text not null,
            after_state text,
            after_code text,
            reason_code text,
            result_json text,
            requested_at text not null,
            applied_at text,
            updated_at text not null
        );
        """,
    )

    rebuild_columns = {
        str(row[1]) for row in conn.execute("pragma table_info(room_memory_rebuild_actions)")
    }
    if "runtime_generation" not in rebuild_columns:
        conn.execute("alter table room_memory_rebuild_actions add column runtime_generation text")

    binding_columns = {
        str(row[1]) for row in conn.execute("pragma table_info(room_memory_bindings)")
    }
    for name, definition in (
        ("session_retry_count", "integer not null default 0"),
        ("session_retry_not_before", "text"),
        ("attachment_retry_count", "integer not null default 0"),
        ("attachment_retry_not_before", "text"),
    ):
        if name not in binding_columns:
            conn.execute(f"alter table room_memory_bindings add column {name} {definition}")
    outbox_columns = {str(row[1]) for row in conn.execute("pragma table_info(room_memory_outbox)")}
    if "next_attempt_at" not in outbox_columns:
        conn.execute("alter table room_memory_outbox add column next_attempt_at text")
    message_delivery_columns = {
        str(row[1]) for row in conn.execute("pragma table_info(room_memory_message_deliveries)")
    }
    if "memoryos_message_id" not in message_delivery_columns:
        conn.execute(
            "alter table room_memory_message_deliveries add column memoryos_message_id text"
        )
    if "memoryos_session_id" not in message_delivery_columns:
        conn.execute(
            "alter table room_memory_message_deliveries add column memoryos_session_id text"
        )
    conn.execute(
        "create index if not exists idx_room_memory_outbox_dispatch "
        "on room_memory_outbox(state, created_at, outbox_id)"
    )
    conn.execute(
        "create index if not exists idx_room_memory_message_outbox_dispatch "
        "on room_memory_message_outbox(state, created_at, message_outbox_id)"
    )
    conn.execute(
        "create unique index if not exists idx_room_memory_message_source "
        "on room_memory_message_deliveries(memoryos_session_id, memoryos_message_id) "
        "where memoryos_session_id is not null and memoryos_message_id is not null"
    )
    conn.execute(
        "create index if not exists idx_room_memory_candidates_projection "
        "on room_memory_candidates(conversation_id, approval_state, created_at desc)"
    )
    conn.execute(
        "create unique index if not exists idx_room_memory_rebuild_one_requested "
        "on room_memory_rebuild_actions(status) where status = 'requested'"
    )
    conn.execute(
        """create trigger if not exists trg_room_memory_activity_outbox
           after insert on room_activities
           when new.visibility = 'room'
           begin
             insert or ignore into room_memory_outbox
               (outbox_id, conversation_id, activity_id, candidate_id, document_id,
                target_scope, state, attempt_count, created_at, updated_at)
             values ('memory_outbox_activity_' || new.activity_id, new.conversation_id,
                     new.activity_id, null, 'xmuse-room-activity-' || new.activity_id,
                     'room', 'pending', 0, new.created_at, new.created_at);
           end"""
    )
    conn.execute(
        """insert or ignore into room_memory_outbox
           (outbox_id, conversation_id, activity_id, candidate_id, document_id,
            target_scope, state, attempt_count, created_at, updated_at)
           select 'memory_outbox_activity_' || activity_id, conversation_id, activity_id,
                  null, 'xmuse-room-activity-' || activity_id, 'room', 'pending', 0,
                  created_at, created_at
           from room_activities where visibility = 'room'"""
    )

    # A message is a visible speech event, not a preview, noop, defer, provider
    # final or infrastructure diagnostic.  Proposals have no materialized
    # message but remain durable Agent speech and are represented by their
    # authoritative proposal content in the delivery adapter.
    conn.execute(
        """create trigger if not exists trg_room_memory_message_outbox
           after insert on room_activities
           when new.visibility = 'room'
            and new.delivery_mode = 'active'
            and ((new.actor_kind = 'human' and new.activity_type = 'message.posted')
                 or (new.actor_kind = 'participant' and new.activity_type in
                     ('message.responded','room.handoff','proposal.created')))
           begin
             insert or ignore into room_memory_message_outbox
               (message_outbox_id, conversation_id, activity_id, external_id,
                state, attempt_count, created_at, updated_at)
             values ('memory_message_outbox_' || new.activity_id,
                     new.conversation_id, new.activity_id,
                     'xmuse-room-message-' || new.activity_id,
                     'pending', 0, new.created_at, new.created_at);
           end"""
    )
    conn.execute(
        """insert or ignore into room_memory_message_outbox
           (message_outbox_id, conversation_id, activity_id, external_id,
            state, attempt_count, created_at, updated_at)
           select 'memory_message_outbox_' || activity_id, conversation_id,
                  activity_id, 'xmuse-room-message-' || activity_id,
                  'pending', 0, created_at, created_at
           from room_activities
           where visibility = 'room' and delivery_mode = 'active'
             and ((actor_kind = 'human' and activity_type = 'message.posted')
                  or (actor_kind = 'participant' and activity_type in
                      ('message.responded','room.handoff','proposal.created')))"""
    )

    conversations = conn.execute(
        """select c.id, c.created_at from conversations c
           where (select count(*) from room_memory_bindings b
                  where b.conversation_id = c.id) < 3
           order by c.created_at, c.id"""
    ).fetchall()
    for conversation in conversations:
        ensure_room_memory_bindings_conn(
            conn,
            conversation_id=str(conversation["id"]),
            stamp=str(conversation["created_at"]),
        )
