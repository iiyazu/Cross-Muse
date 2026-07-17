"""Strict authority-free contracts for source-backed Room memory."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Literal, cast

MAX_MEMORY_CANDIDATES_PER_OUTCOME = 3
MAX_MEMORY_CANDIDATE_BYTES = 4096
MAX_MEMORY_CANDIDATE_SOURCES = 8
MAX_MEMORY_RECEIPT_ITEMS = 8
MEMORY_CANDIDATE_KINDS = frozenset(
    {"room_fact", "room_decision", "user_preference", "project_rule"}
)
MEMORY_RECEIPT_STATUSES = frozenset(
    {
        "disabled",
        "ok",
        "empty",
        "timeout",
        "unavailable",
        "schema_rejected",
        "source_rejected",
        "oversize",
        "error",
    }
)
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}")


MemoryCandidateKind = Literal["room_fact", "room_decision", "user_preference", "project_rule"]


class RoomMemoryContractError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class MemoryCandidateInput:
    kind: MemoryCandidateKind
    content: str
    source_activity_ids: tuple[str, ...]


@dataclass(frozen=True)
class MemoryReceiptItem:
    item_id: str
    document_id: str
    source_activity_ids: tuple[str, ...]
    content_sha256: str
    text: str
    layer: Literal["recall", "page", "core", "archival"] = "archival"
    derived: bool = False
    proof_source_type: Literal["document", "message"] = "document"
    proof_session_id: str | None = None
    proof_source_ids: tuple[str, ...] = ()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()}"


def require_digest(value: object, code: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise RoomMemoryContractError(code)
    return value


def _identifier(value: object, code: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise RoomMemoryContractError(code)
    return value


def _content(value: object) -> str:
    if not isinstance(value, str):
        raise RoomMemoryContractError("room_memory_candidate_content_invalid")
    result = value.strip()
    try:
        encoded = result.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise RoomMemoryContractError("room_memory_candidate_content_invalid") from exc
    if not result or len(encoded) > MAX_MEMORY_CANDIDATE_BYTES or "\x00" in result:
        raise RoomMemoryContractError("room_memory_candidate_content_invalid")
    return result


def _source_ids(value: object, *, code: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or len(value) > MAX_MEMORY_CANDIDATE_SOURCES:
        raise RoomMemoryContractError(code)
    result = tuple(_identifier(item, code) for item in value)
    if len(set(result)) != len(result):
        raise RoomMemoryContractError(code)
    return result


def normalize_memory_candidates(value: object) -> tuple[MemoryCandidateInput, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_MEMORY_CANDIDATES_PER_OUTCOME:
        raise RoomMemoryContractError("room_memory_candidates_invalid")
    result: list[MemoryCandidateInput] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {
            "kind",
            "content",
            "source_activity_ids",
        }:
            raise RoomMemoryContractError("room_memory_candidate_invalid")
        kind = raw["kind"]
        if kind not in MEMORY_CANDIDATE_KINDS:
            raise RoomMemoryContractError("room_memory_candidate_kind_invalid")
        content = _content(raw["content"])
        source_ids = _source_ids(
            raw["source_activity_ids"], code="room_memory_candidate_sources_invalid"
        )
        identity = (str(kind), content, source_ids)
        if identity in seen:
            raise RoomMemoryContractError("room_memory_candidate_duplicate")
        seen.add(identity)
        result.append(MemoryCandidateInput(cast(MemoryCandidateKind, kind), content, source_ids))
    return tuple(result)


def normalize_receipt_items(value: object) -> tuple[MemoryReceiptItem, ...]:
    if not isinstance(value, list) or len(value) > MAX_MEMORY_RECEIPT_ITEMS:
        raise RoomMemoryContractError("room_memory_receipt_items_invalid")
    result: list[MemoryReceiptItem] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) not in {
            frozenset(
                {
                    "item_id",
                    "document_id",
                    "source_activity_ids",
                    "content_sha256",
                    "text",
                }
            ),
            frozenset(
                {
                    "item_id",
                    "document_id",
                    "source_activity_ids",
                    "content_sha256",
                    "text",
                    "layer",
                    "derived",
                }
            ),
            frozenset(
                {
                    "item_id",
                    "document_id",
                    "source_activity_ids",
                    "content_sha256",
                    "text",
                    "layer",
                    "derived",
                    "proof_source_type",
                    "proof_session_id",
                    "proof_source_ids",
                }
            ),
        }:
            raise RoomMemoryContractError("room_memory_receipt_item_invalid")
        layer = raw.get("layer", "archival")
        derived = raw.get("derived", False)
        if layer not in {"recall", "page", "core", "archival"} or not isinstance(derived, bool):
            raise RoomMemoryContractError("room_memory_receipt_item_invalid")
        if derived != (layer in {"recall", "page"}):
            raise RoomMemoryContractError("room_memory_receipt_item_invalid")
        proof_source_type = raw.get("proof_source_type", "document")
        proof_session_id = raw.get("proof_session_id")
        proof_source_ids = raw.get("proof_source_ids", [])
        if proof_source_type not in {"document", "message"} or not isinstance(
            proof_source_ids, list
        ):
            raise RoomMemoryContractError("room_memory_receipt_item_invalid")
        clean_proof_source_ids = tuple(
            _identifier(value, "room_memory_receipt_item_invalid") for value in proof_source_ids
        )
        if len(set(clean_proof_source_ids)) != len(clean_proof_source_ids):
            raise RoomMemoryContractError("room_memory_receipt_item_invalid")
        if proof_source_type == "message":
            if not isinstance(proof_session_id, str) or not clean_proof_source_ids:
                raise RoomMemoryContractError("room_memory_receipt_item_invalid")
            proof_session_id = _identifier(proof_session_id, "room_memory_receipt_item_invalid")
        elif proof_session_id is not None or clean_proof_source_ids:
            raise RoomMemoryContractError("room_memory_receipt_item_invalid")
        item_id = _identifier(raw["item_id"], "room_memory_receipt_item_invalid")
        if item_id in seen:
            raise RoomMemoryContractError("room_memory_receipt_item_duplicate")
        seen.add(item_id)
        text = raw["text"]
        if not isinstance(text, str) or not text or "\x00" in text:
            raise RoomMemoryContractError("room_memory_receipt_item_text_invalid")
        try:
            text_bytes = text.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise RoomMemoryContractError("room_memory_receipt_item_text_invalid") from exc
        if len(text_bytes) > 8192:
            raise RoomMemoryContractError("room_memory_receipt_item_text_invalid")
        content_sha256 = require_digest(
            raw["content_sha256"], "room_memory_receipt_item_digest_invalid"
        )
        if content_sha256 != f"sha256:{hashlib.sha256(text_bytes).hexdigest()}":
            raise RoomMemoryContractError("room_memory_receipt_item_digest_invalid")
        result.append(
            MemoryReceiptItem(
                item_id=item_id,
                document_id=_identifier(raw["document_id"], "room_memory_receipt_document_invalid"),
                source_activity_ids=_source_ids(
                    raw["source_activity_ids"],
                    code="room_memory_receipt_sources_invalid",
                ),
                content_sha256=content_sha256,
                text=text,
                layer=cast(Literal["recall", "page", "core", "archival"], layer),
                derived=derived,
                proof_source_type=cast(Literal["document", "message"], proof_source_type),
                proof_session_id=proof_session_id,
                proof_source_ids=clean_proof_source_ids,
            )
        )
    return tuple(result)
