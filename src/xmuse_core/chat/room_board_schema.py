"""Pure SQLite schema for the Room coordination board.

The board lets long-lived owner agents coordinate through module charters,
versioned interface contracts, progress reports, and peer questions.  Every
board write appends at least one ``board.`` activity to ``room_activities``
and updates these tables in the same transaction; ``chat.db`` stays the only
authority.
"""

from __future__ import annotations

import sqlite3


def create_room_board_schema(conn: sqlite3.Connection) -> None:
    """Create the additive board tables in the caller transaction."""

    conn.execute(
        """create table if not exists room_board_splits (
               split_id text primary key,
               conversation_id text not null references conversations(id),
               proposed_by_participant_id text not null
                   references participants(participant_id),
               status text not null check (
                   status in ('proposed','approved','rejected','superseded')
               ),
               split_json text not null,
               activity_id text references room_activities(activity_id),
               approved_by text,
               decided_at text,
               created_at text not null
           )"""
    )
    conn.execute(
        """create table if not exists room_board_charters (
               conversation_id text not null references conversations(id),
               module_id text not null,
               version integer not null check (version > 0),
               split_id text not null references room_board_splits(split_id),
               owner_participant_id text not null references participants(participant_id),
               status text not null check (status in ('active','done','retired')),
               charter_json text not null,
               claimed_at text,
               created_at text not null,
               primary key (conversation_id, module_id, version)
           )"""
    )
    conn.execute(
        """create table if not exists room_board_contracts (
               conversation_id text not null references conversations(id),
               contract_id text not null,
               version integer not null check (version > 0),
               provider_module_id text not null,
               kind text not null check (kind in ('api_schema','types','protocol','text')),
               content text not null,
               digest text not null,
               author_participant_id text not null references participants(participant_id),
               rationale text,
               activity_id text references room_activities(activity_id),
               created_at text not null,
               primary key (conversation_id, contract_id, version)
           )"""
    )
    conn.execute(
        """create table if not exists room_board_progress (
               progress_id text primary key,
               conversation_id text not null references conversations(id),
               module_id text not null,
               participant_id text not null references participants(participant_id),
               status text not null check (
                   status in ('working','blocked','ready_for_review','done')),
               summary text not null,
               claims_json text not null,
               activity_id text references room_activities(activity_id),
               created_at text not null
           )"""
    )
    conn.execute(
        """create table if not exists room_board_cursors (
               conversation_id text not null references conversations(id),
               participant_id text not null references participants(participant_id),
               last_seen_seq integer not null default 0 check (last_seen_seq >= 0),
               updated_at text not null,
               primary key (conversation_id, participant_id)
           )"""
    )
    conn.execute(
        "create index if not exists idx_room_board_splits_conversation "
        "on room_board_splits(conversation_id, status)"
    )
    conn.execute(
        "create index if not exists idx_room_board_charters_owner "
        "on room_board_charters(conversation_id, owner_participant_id, status)"
    )
    conn.execute(
        "create index if not exists idx_room_board_contracts_provider "
        "on room_board_contracts(conversation_id, provider_module_id, version)"
    )
    conn.execute(
        "create index if not exists idx_room_board_progress_module "
        "on room_board_progress(conversation_id, module_id, created_at)"
    )
    conn.execute(
        """create table if not exists room_board_verifications (
               verification_id text primary key,
               conversation_id text not null references conversations(id),
               module_id text not null,
               participant_id text not null references participants(participant_id),
               progress_id text not null references room_board_progress(progress_id),
               status text not null check (
                   status in ('pending','running','passed','failed','superseded','error')
               ),
               attempt_count integer not null default 0 check (attempt_count >= 0),
               lease_owner text,
               lease_token text,
               lease_expires_at text,
               head_commit text,
               patch_digest text,
               changed_paths_json text not null default '[]',
               patch_text text,
               not_before text,
               result_json text,
               activity_id text references room_activities(activity_id),
               created_at text not null,
               updated_at text not null
           )"""
    )
    conn.execute(
        "create index if not exists idx_room_board_verifications_module "
        "on room_board_verifications(conversation_id, module_id, created_at)"
    )
