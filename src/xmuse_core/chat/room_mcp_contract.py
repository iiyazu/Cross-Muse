"""The single capability contract exposed to default Room Agents."""

from __future__ import annotations

import copy
from typing import Any

ROOM_OUTCOME_TOOL_NAME = "chat_room_submit_outcome"
ROOM_OUTCOME_TOOL_SCHEMA: dict[str, Any] = {
    "name": ROOM_OUTCOME_TOOL_NAME,
    "description": (
        "Submit the verified participant durable outcome for one leased room "
        "observation. Provider final text is not room truth; observer rooms "
        "use this instead of legacy chat_post_message."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "conversation_id": {"type": "string"},
            "participant_id": {"type": "string"},
            "god_session_id": {"type": "string"},
            "observation_id": {"type": "string"},
            "observation_batch_id": {"type": "string"},
            "reply_to_activity_id": {"type": "string"},
            "lease_token": {"type": "string"},
            "client_request_id": {"type": "string"},
            "outcome_type": {
                "type": "string",
                "enum": ["respond", "handoff", "propose", "defer", "noop"],
            },
            "outcome_payload": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "mentioned_participant_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "target_participant_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "proposal_type": {"type": "string"},
                    "references": {"type": "array", "items": {"type": "string"}},
                    "execution_patch": {
                        "type": "object",
                        "properties": {
                            "schema_version": {
                                "type": "string",
                                "const": "room_execution_patch/v1",
                            },
                            "base_head": {
                                "type": "string",
                                "pattern": "^(?:[0-9a-f]{40}|[0-9a-f]{64})$",
                            },
                            "summary": {"type": "string", "maxLength": 4096},
                            "unified_diff": {"type": "string", "maxLength": 204800},
                            "allowed_files": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 32,
                                "uniqueItems": True,
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "schema_version",
                            "base_head",
                            "summary",
                            "unified_diff",
                            "allowed_files",
                        ],
                        "additionalProperties": False,
                    },
                    "wake_condition": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "proposal_assessments": {
                "type": "array",
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "properties": {
                        "proposal_id": {"type": "string"},
                        "candidate_digest": {
                            "type": "string",
                            "pattern": "^sha256:[0-9a-f]{64}$",
                        },
                        "assessment": {
                            "type": "string",
                            "enum": ["endorse", "object", "abstain"],
                        },
                        "rationale": {"type": "string", "maxLength": 2048},
                    },
                    "required": [
                        "proposal_id",
                        "candidate_digest",
                        "assessment",
                        "rationale",
                    ],
                    "additionalProperties": False,
                },
            },
            "memory_candidates": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [
                                "room_fact",
                                "room_decision",
                                "user_preference",
                                "project_rule",
                            ],
                        },
                        "content": {"type": "string", "maxLength": 4096},
                        "source_activity_ids": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 8,
                            "uniqueItems": True,
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["kind", "content", "source_activity_ids"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "conversation_id",
            "participant_id",
            "god_session_id",
            "observation_id",
            "lease_token",
            "client_request_id",
            "outcome_type",
        ],
        "additionalProperties": False,
    },
}


def room_tool_schemas() -> list[dict[str, Any]]:
    return [copy.deepcopy(ROOM_OUTCOME_TOOL_SCHEMA)]
