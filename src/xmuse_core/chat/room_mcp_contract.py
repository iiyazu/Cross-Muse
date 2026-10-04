"""The capability contract exposed to Room Agents: one outcome tool plus board tools."""

from __future__ import annotations

import copy
from typing import Any

ROOM_OUTCOME_TOOL_NAME = "chat_room_submit_outcome"
ROOM_BOARD_READ_TOOL_NAME = "chat_room_board_read"
ROOM_BOARD_PROPOSE_SPLIT_TOOL_NAME = "chat_room_board_propose_split"
ROOM_BOARD_CLAIM_TOOL_NAME = "chat_room_board_claim"
ROOM_BOARD_PUBLISH_CONTRACT_TOOL_NAME = "chat_room_board_publish_contract"
ROOM_BOARD_REPORT_PROGRESS_TOOL_NAME = "chat_room_board_report_progress"
ROOM_BOARD_ASK_TOOL_NAME = "chat_room_board_ask"
ROOM_BOARD_TOOL_NAMES: tuple[str, ...] = (
    ROOM_BOARD_READ_TOOL_NAME,
    ROOM_BOARD_PROPOSE_SPLIT_TOOL_NAME,
    ROOM_BOARD_CLAIM_TOOL_NAME,
    ROOM_BOARD_PUBLISH_CONTRACT_TOOL_NAME,
    ROOM_BOARD_REPORT_PROGRESS_TOOL_NAME,
    ROOM_BOARD_ASK_TOOL_NAME,
)
ROOM_TOOL_NAMES: tuple[str, ...] = (ROOM_OUTCOME_TOOL_NAME, *ROOM_BOARD_TOOL_NAMES)
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
                    "handoff_note": {
                        "type": "object",
                        "properties": {
                            "what": {"type": "string", "maxLength": 2000},
                            "why": {"type": "string", "maxLength": 2000},
                            "tradeoffs": {"type": "string", "maxLength": 2000},
                            "open_questions": {
                                "type": "array",
                                "maxItems": 16,
                                "items": {"type": "string", "maxLength": 2000},
                            },
                            "next_action": {"type": "string", "maxLength": 2000},
                        },
                        "additionalProperties": False,
                    },
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


_LEASE_PROPERTIES: dict[str, Any] = {
    "conversation_id": {"type": "string"},
    "participant_id": {"type": "string"},
    "god_session_id": {"type": "string"},
    "observation_id": {"type": "string"},
    "lease_token": {"type": "string"},
    "client_request_id": {"type": "string"},
}
_LEASE_REQUIRED = list(_LEASE_PROPERTIES)
_ID_LIST = {"type": "array", "maxItems": 16, "items": {"type": "string"}}
_CHARTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "module_id": {"type": "string"},
        "title": {"type": "string", "maxLength": 200},
        "paths": {"type": "array", "minItems": 1, "maxItems": 32, "items": {"type": "string"}},
        "provides": _ID_LIST,
        "depends": _ID_LIST,
        "acceptance": {
            "type": "array",
            "maxItems": 16,
            "items": {"type": "string", "maxLength": 500},
        },
        "report_to": {"type": ["string", "null"]},
    },
    "required": ["module_id", "title", "paths"],
    "additionalProperties": False,
}
_CONTRACT_KINDS = ["api_schema", "types", "protocol", "text"]


def _board_tool(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {**_LEASE_PROPERTIES, **properties},
            "required": [*_LEASE_REQUIRED, *required],
            "additionalProperties": False,
        },
    }


ROOM_BOARD_TOOL_SCHEMAS: tuple[dict[str, Any], ...] = (
    _board_tool(
        ROOM_BOARD_READ_TOOL_NAME,
        "Read the Room board: module charters, the contract index, and your board inbox "
        "(new board events addressed to you; reading advances your cursor). Pass "
        "contract_ref ('id' for the latest or 'id@version') to get one contract's full text. "
        "Use the identifiers of your current delivery.",
        {"contract_ref": {"type": "string"}},
        [],
    ),
    _board_tool(
        ROOM_BOARD_PROPOSE_SPLIT_TOOL_NAME,
        "Room lead only: propose splitting the work into modules. Each module gets a charter "
        "(paths it owns, contracts it provides and depends on, acceptance checks), an owner "
        "from the Room participants, and initial contracts for everything it provides. "
        "Nothing takes effect until the operator approves the split.",
        {
            "modules": {"type": "array", "minItems": 1, "maxItems": 16, "items": _CHARTER_SCHEMA},
            "assignments": {
                "type": "object",
                "description": "module_id -> participant_id",
                "additionalProperties": {"type": "string"},
            },
            "contracts": {
                "type": "array",
                "maxItems": 32,
                "items": {
                    "type": "object",
                    "properties": {
                        "contract_id": {"type": "string"},
                        "provider_module_id": {"type": "string"},
                        "kind": {"type": "string", "enum": _CONTRACT_KINDS},
                        "content": {"type": "string", "maxLength": 65536},
                        "rationale": {"type": "string", "maxLength": 4000},
                    },
                    "required": ["contract_id", "provider_module_id", "kind", "content"],
                    "additionalProperties": False,
                },
            },
        },
        ["modules", "assignments", "contracts"],
    ),
    _board_tool(
        ROOM_BOARD_CLAIM_TOOL_NAME,
        "Take ownership of a module whose approved charter assigns it to you.",
        {"module_id": {"type": "string"}},
        ["module_id"],
    ),
    _board_tool(
        ROOM_BOARD_PUBLISH_CONTRACT_TOOL_NAME,
        "Publish a new interface contract (base_version omitted) or revise one "
        "(base_version = the version you read). Allowed for the owner of the providing "
        "module or the lead. A revision notifies every owner that depends on the contract. "
        "A stale base_version fails with the latest version; read it and retry.",
        {
            "contract_id": {"type": "string"},
            "kind": {"type": "string", "enum": _CONTRACT_KINDS},
            "content": {"type": "string", "maxLength": 65536},
            "base_version": {"type": ["integer", "null"], "minimum": 1},
            "rationale": {"type": "string", "maxLength": 4000},
            "provider_module_id": {"type": "string"},
        },
        ["contract_id", "kind", "content"],
    ),
    _board_tool(
        ROOM_BOARD_REPORT_PROGRESS_TOOL_NAME,
        "Report progress on a module you own. claims are short, checkable statements "
        "(for example 'pnpm --filter api test passes'); only claim what you verified. "
        "blocked and ready_for_review notify your report target.",
        {
            "module_id": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["working", "blocked", "ready_for_review", "done"],
            },
            "summary": {"type": "string", "maxLength": 4000},
            "claims": {
                "type": "array",
                "maxItems": 32,
                "items": {"type": "string", "maxLength": 500},
            },
        },
        ["module_id", "status", "summary"],
    ),
    _board_tool(
        ROOM_BOARD_ASK_TOOL_NAME,
        "Ask one other participant a question; they are woken and answer in the Room.",
        {
            "target_participant_id": {"type": "string"},
            "question": {"type": "string", "maxLength": 4000},
            "references": _ID_LIST,
        },
        ["target_participant_id", "question"],
    ),
)


def room_tool_schemas() -> list[dict[str, Any]]:
    return [copy.deepcopy(ROOM_OUTCOME_TOOL_SCHEMA), *copy.deepcopy(ROOM_BOARD_TOOL_SCHEMAS)]


def room_tool_schema(name: str) -> dict[str, Any] | None:
    for schema in room_tool_schemas():
        if schema["name"] == name:
            return schema
    return None
