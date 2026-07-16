"""Deliver durable bindings and outboxes to MemoryOS through narrow ports."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from typing import Any, Literal, Protocol

from xmuse.memoryos_evidence import canonical_digest
from xmuse.memoryos_http_client import MemoryOSAdapterError, required_id
from xmuse_core.chat.room_memory_ports import (
    RoomMemoryBindingSessionAttachmentPort,
    RoomMemoryDocumentOutboxPort,
    RoomMemoryMessageOutboxPort,
)


class MemoryOSDeliveryClient(Protocol):
    @property
    def profile(self) -> Literal["archive-only", "full-local"]: ...

    def health(self, *, timeout_s: float = 0.5) -> Mapping[str, Any]: ...

    def create_session(self, *, title: str) -> str: ...

    def attach_archive(
        self,
        *,
        archive_id: str,
        session_id: str,
        source_refs: tuple[Mapping[str, Any], ...],
        metadata: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...

    def ingest_message(
        self,
        *,
        session_id: str,
        external_id: str,
        role: Literal["user", "assistant"],
        content: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...

    def ingest_document(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class MemoryOSDeliveryPump:
    """Advance at most one binding, message, or document ledger operation."""

    def __init__(
        self,
        *,
        binding_store: RoomMemoryBindingSessionAttachmentPort,
        message_store: RoomMemoryMessageOutboxPort,
        document_store: RoomMemoryDocumentOutboxPort,
        client: MemoryOSDeliveryClient,
        worker_id: str,
    ) -> None:
        self._binding_store = binding_store
        self._message_store = message_store
        self._document_store = document_store
        self._client = client
        self._worker_id = worker_id

    async def pump_once(self) -> bool:
        if await self._pump_binding_once():
            return True
        if self._client.profile == "full-local" and await self._pump_message_once():
            return True
        await asyncio.to_thread(self._client.health, timeout_s=0.5)
        if self._document_store.requeue_retryable_failed_outbox(limit=1):
            return True
        claim = self._document_store.claim_next_outbox(worker_id=self._worker_id)
        if claim is None:
            return False
        outbox = _mapping(claim, "outbox")
        delivery = _mapping(claim, "delivery")
        request = _mapping(claim, "document_request")
        outbox_id = required_id(outbox, "outbox_id", "room_memory_outbox_invalid")
        delivery_id = required_id(delivery, "delivery_id", "room_memory_outbox_invalid")
        lease_token = required_id(delivery, "lease_token", "room_memory_outbox_invalid")
        _attempt_number(delivery)
        request_digest = canonical_digest(request)
        try:
            response = await asyncio.to_thread(self._client.ingest_document, request)
            self._document_store.complete_delivery(
                outbox_id=outbox_id,
                delivery_id=delivery_id,
                lease_token=lease_token,
                status="delivered",
                request_digest=request_digest,
                response_digest=canonical_digest(response),
                reason_code=None,
            )
        except MemoryOSAdapterError as exc:
            if exc.code == "memoryos_document_conflict":
                self._document_store.complete_delivery(
                    outbox_id=outbox_id,
                    delivery_id=delivery_id,
                    lease_token=lease_token,
                    status="conflict",
                    request_digest=request_digest,
                    reason_code="room_memory_document_conflict",
                )
            else:
                self._document_store.complete_delivery(
                    outbox_id=outbox_id,
                    delivery_id=delivery_id,
                    lease_token=lease_token,
                    status="failed",
                    request_digest=request_digest,
                    reason_code=exc.code,
                )
                raise
        return True

    async def _pump_message_once(self) -> bool:
        if self._message_store.requeue_retryable_failed_message_outbox(limit=1):
            return True
        claim = self._message_store.claim_next_message_outbox(worker_id=self._worker_id)
        if claim is None:
            return False
        outbox = _mapping(claim, "outbox")
        delivery = _mapping(claim, "delivery")
        request = _mapping(claim, "message_request")
        outbox_id = required_id(outbox, "message_outbox_id", "room_memory_outbox_invalid")
        delivery_id = required_id(delivery, "delivery_id", "room_memory_outbox_invalid")
        lease_token = required_id(delivery, "lease_token", "room_memory_outbox_invalid")
        _attempt_number(delivery)
        request_digest = canonical_digest(request)
        session_id = request.get("session_id")
        external_id = request.get("external_id")
        role = request.get("role")
        content = request.get("content")
        metadata = request.get("metadata")
        if (
            not isinstance(session_id, str)
            or not isinstance(external_id, str)
            or role not in {"user", "assistant"}
            or not isinstance(content, str)
            or not isinstance(metadata, Mapping)
        ):
            raise MemoryOSAdapterError("room_memory_outbox_invalid")
        clean_role: Literal["user", "assistant"] = role
        try:
            response = await asyncio.to_thread(
                self._client.ingest_message,
                session_id=session_id,
                external_id=external_id,
                role=clean_role,
                content=content,
                metadata=metadata,
            )
            message = response.get("message")
            message_payload = message if isinstance(message, Mapping) else response
            memoryos_message_id = message_payload.get("id")
            if not isinstance(memoryos_message_id, str) or not memoryos_message_id:
                raise MemoryOSAdapterError("memoryos_message_response_invalid")
            self._message_store.complete_message_delivery(
                message_outbox_id=outbox_id,
                delivery_id=delivery_id,
                lease_token=lease_token,
                status="delivered",
                request_digest=request_digest,
                response_digest=canonical_digest(response),
                memoryos_message_id=memoryos_message_id,
                memoryos_session_id=session_id,
                reason_code=None,
            )
        except MemoryOSAdapterError as exc:
            status: Literal["conflict", "failed"] = (
                "conflict" if exc.code == "memoryos_message_conflict" else "failed"
            )
            self._message_store.complete_message_delivery(
                message_outbox_id=outbox_id,
                delivery_id=delivery_id,
                lease_token=lease_token,
                status=status,
                request_digest=request_digest,
                reason_code=("room_memory_message_conflict" if status == "conflict" else exc.code),
            )
            raise
        return True

    async def _pump_binding_once(self) -> bool:
        for raw in self._binding_store.list_pending_bindings(limit=20):
            binding = dict(raw)
            binding_id = required_id(binding, "binding_id", "room_memory_binding_invalid")
            conversation_id = required_id(binding, "conversation_id", "room_memory_binding_invalid")
            revision = _revision(binding)
            session_state = binding.get("session_state")
            if session_state == "uncertain":
                if self._reopen(binding_id, revision):
                    return True
                continue
            if session_state == "creating":
                self._binding_store.complete_session_create(
                    binding_id=binding_id,
                    client_request_id=_binding_request_id("session", binding_id, revision - 1),
                    expected_revision=revision,
                    session_id=None,
                    uncertain=True,
                )
                return True
            if session_state == "unbound" and binding.get("scope_type") == "room":
                request_id = _binding_request_id("session", binding_id, revision)
                reserved = self._binding_store.reserve_session_create(
                    binding_id=binding_id,
                    client_request_id=request_id,
                    expected_revision=revision,
                )
                reserved_revision = _revision(reserved)
                try:
                    session_id = await asyncio.to_thread(
                        self._client.create_session,
                        title=f"xmuse Room archive {conversation_id}",
                    )
                except Exception as exc:
                    self._binding_store.complete_session_create(
                        binding_id=binding_id,
                        client_request_id=request_id,
                        expected_revision=reserved_revision,
                        session_id=None,
                        uncertain=True,
                    )
                    raise MemoryOSAdapterError("room_memory_session_uncertain") from exc
                self._binding_store.complete_session_create(
                    binding_id=binding_id,
                    client_request_id=request_id,
                    expected_revision=reserved_revision,
                    session_id=session_id,
                    uncertain=False,
                )
                return True
            if session_state != "bound":
                continue
            attachment_state = binding.get("attachment_state")
            if attachment_state == "uncertain":
                if self._reopen(binding_id, revision):
                    return True
                continue
            if attachment_state == "attaching":
                self._binding_store.complete_attachment(
                    binding_id=binding_id,
                    client_request_id=_binding_request_id("attachment", binding_id, revision - 1),
                    expected_revision=revision,
                    attachment_id=None,
                    uncertain=True,
                )
                return True
            if attachment_state != "pending":
                continue
            session_id = required_id(binding, "session_id", "room_memory_binding_invalid")
            archive_id = required_id(binding, "archive_id", "room_memory_binding_invalid")
            request_id = _binding_request_id("attachment", binding_id, revision)
            reserved = self._binding_store.reserve_attachment(
                binding_id=binding_id,
                client_request_id=request_id,
                expected_revision=revision,
            )
            reserved_revision = _revision(reserved)
            try:
                response = await asyncio.to_thread(
                    self._client.attach_archive,
                    archive_id=archive_id,
                    session_id=session_id,
                    source_refs=(
                        {
                            "source_type": "document",
                            "source_id": f"xmuse-room-binding-{conversation_id}",
                            "session_id": session_id,
                            "metadata": {"scope_type": binding.get("scope_type")},
                        },
                    ),
                    metadata={"producer": "xmuse_room_archive_adapter/v1"},
                )
                attachment_id = required_id(
                    response, "attachment_id", "memoryos_attachment_response_invalid"
                )
            except Exception as exc:
                self._binding_store.complete_attachment(
                    binding_id=binding_id,
                    client_request_id=request_id,
                    expected_revision=reserved_revision,
                    attachment_id=None,
                    uncertain=True,
                )
                raise MemoryOSAdapterError("room_memory_attachment_uncertain") from exc
            self._binding_store.complete_attachment(
                binding_id=binding_id,
                client_request_id=request_id,
                expected_revision=reserved_revision,
                attachment_id=attachment_id,
                uncertain=False,
            )
            return True
        return False

    def _reopen(self, binding_id: str, revision: int) -> bool:
        try:
            self._binding_store.reopen_uncertain_binding(
                binding_id=binding_id,
                expected_revision=revision,
            )
        except Exception as exc:
            if getattr(exc, "code", None) == "room_memory_binding_retry_not_ready":
                return False
            raise
        return True


def _mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise MemoryOSAdapterError("room_memory_outbox_invalid")
    return value


def _attempt_number(payload: Mapping[str, Any]) -> int:
    value = payload.get("attempt_number")
    if isinstance(value, bool) or not isinstance(value, int):
        raise MemoryOSAdapterError("room_memory_outbox_invalid")
    return value


def _revision(payload: Mapping[str, Any]) -> int:
    value = payload.get("revision")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MemoryOSAdapterError("room_memory_binding_invalid")
    return value


def _binding_request_id(kind: str, binding_id: str, revision: int) -> str:
    if revision < 0:
        raise MemoryOSAdapterError("room_memory_binding_invalid")
    digest = hashlib.sha256(f"{kind}:{binding_id}:{revision}".encode()).hexdigest()[:32]
    return f"memory-{kind}-{digest}"


__all__ = ["MemoryOSDeliveryClient", "MemoryOSDeliveryPump"]
