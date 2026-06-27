from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import metadata
from typing import Any

from a2a import types as a2a_types
from google.protobuf.json_format import MessageToDict, ParseDict


@dataclass(frozen=True)
class A2ASDKBoundary:
    protocol: str = "a2a-sdk"
    authority: str = "xmuse-chat-db"
    supported_now: tuple[str, ...] = (
        "agent_card_model",
        "send_message_request_model",
        "artifact_parts_model",
        "task_result_normalization",
        "jsonrpc_http_boundary",
        "xmuse_authority_normalization",
    )
    deferred: tuple[str, ...] = (
        "streaming",
        "push_notifications",
        "direct_review_or_dispatch_authority",
    )


class A2ASDKBoundaryError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class NormalizedA2ATaskSend:
    task_id: str
    context_id: str
    sender_agent_id: str
    content: str
    target_address: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    input_parts: tuple[dict[str, Any], ...] = ()
    sdk_request: dict[str, Any] = field(default_factory=dict)
    jsonrpc_id: str | int | None = None
    method: str = "tasks/send"


@dataclass(frozen=True)
class NormalizedA2ATaskResult:
    task_id: str
    context_id: str
    state: str
    disposition: str
    terminal: bool
    content: str
    artifacts: tuple[dict[str, Any], ...] = ()
    history: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    source_refs: tuple[str, ...] = ()
    sdk_task: dict[str, Any] = field(default_factory=dict)
    jsonrpc_id: str | int | None = None


def a2a_sdk_dependency_status() -> dict[str, object]:
    return {
        "available": True,
        "import_name": "a2a",
        "version": metadata.version("a2a-sdk"),
        "models": _sdk_model_names(),
    }


def _sdk_model_names() -> tuple[str, ...]:
    return (
        a2a_types.AgentCard.__name__,
        a2a_types.AgentCapabilities.__name__,
        a2a_types.AgentSkill.__name__,
        a2a_types.Task.__name__,
        a2a_types.Artifact.__name__,
    )


def build_sdk_agent_card_payload(
    *,
    name: str,
    description: str,
    url: str,
    version: str,
    streaming: bool = False,
    push_notifications: bool = False,
    skills: tuple[Mapping[str, Any], ...] = (),
) -> dict[str, Any]:
    """Build an official a2a-sdk AgentCard payload.

    xmuse still returns its compatibility Agent Card fields for current clients,
    but this SDK payload is the public protocol boundary used to prevent drift
    between hand-written dicts and the installed SDK model.
    """

    card = a2a_types.AgentCard(
        name=name,
        description=description,
        version=version,
    )
    interface = card.supported_interfaces.add()
    interface.url = url
    interface.protocol_binding = "JSONRPC"
    interface.protocol_version = "1.0"
    card.capabilities.streaming = streaming
    card.capabilities.push_notifications = push_notifications
    for item in skills:
        skill = card.skills.add()
        skill.id = _required_text(item.get("id"), "skill.id")
        skill.name = _required_text(item.get("name"), "skill.name")
        skill.description = _required_text(item.get("description"), "skill.description")
        for tag in item.get("tags", ()):
            if isinstance(tag, str) and tag:
                skill.tags.append(tag)
    return MessageToDict(card, preserving_proto_field_name=True)


def normalize_task_send_payload(payload: Mapping[str, Any]) -> NormalizedA2ATaskSend:
    """Normalize legacy, JSON-RPC, or SDK SendMessageRequest payloads.

    The returned object is safe to pass into xmuse's durable chat/inbox bridge.
    A2A SDK state remains an interop envelope and never becomes proposal,
    review, dispatch, or merge authority by itself.
    """

    if not isinstance(payload, Mapping):
        raise A2ASDKBoundaryError("invalid_a2a_payload", "object payload required")

    jsonrpc_id: str | int | None = None
    method = "tasks/send"
    params: Mapping[str, Any] = payload
    if "jsonrpc" in payload or "method" in payload or "params" in payload:
        if payload.get("jsonrpc") != "2.0":
            raise A2ASDKBoundaryError("invalid_jsonrpc", "jsonrpc must be 2.0")
        method = _required_text(payload.get("method"), "method")
        if method not in {"tasks/send", "message/send", "SendMessage"}:
            raise A2ASDKBoundaryError("unsupported_a2a_method", method)
        request_id = payload.get("id")
        if request_id is not None and not isinstance(request_id, str | int):
            raise A2ASDKBoundaryError("invalid_jsonrpc_id", "id")
        jsonrpc_id = request_id
        raw_params = payload.get("params")
        if not isinstance(raw_params, Mapping):
            raise A2ASDKBoundaryError("invalid_jsonrpc_params", "params object required")
        params = raw_params

    if "message" in params:
        normalized = _normalize_sdk_send_message(params)
    else:
        normalized = _normalize_legacy_task_send(params)
    return NormalizedA2ATaskSend(
        task_id=normalized.task_id,
        context_id=normalized.context_id,
        sender_agent_id=normalized.sender_agent_id,
        content=normalized.content,
        target_address=normalized.target_address,
        metadata=normalized.metadata,
        input_parts=normalized.input_parts,
        sdk_request=normalized.sdk_request,
        jsonrpc_id=jsonrpc_id,
        method=method,
    )


def jsonrpc_task_send_response(
    *,
    request_id: str | int | None,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": dict(result),
    }


def jsonrpc_error_response(
    *,
    request_id: str | int | None,
    code: int,
    message: str,
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
    if data is not None:
        payload["error"]["data"] = dict(data)
    return payload


def normalize_task_result_payload(payload: Mapping[str, Any]) -> NormalizedA2ATaskResult:
    """Normalize A2A SDK Task output into an xmuse-safe provider result.

    This does not approve proposals, produce review truth, dispatch execution,
    or mutate final-action state. It only turns a remote/provider A2A task into
    a structured payload that a future writeback reconciler can persist into
    xmuse authority stores.
    """

    if not isinstance(payload, Mapping):
        raise A2ASDKBoundaryError("invalid_a2a_task_result", "object payload required")
    jsonrpc_id: str | int | None = None
    result: Mapping[str, Any] = payload
    if "jsonrpc" in payload or "result" in payload or "error" in payload:
        if payload.get("jsonrpc") != "2.0":
            raise A2ASDKBoundaryError("invalid_jsonrpc", "jsonrpc must be 2.0")
        request_id = payload.get("id")
        if request_id is not None and not isinstance(request_id, str | int):
            raise A2ASDKBoundaryError("invalid_jsonrpc_id", "id")
        jsonrpc_id = request_id
        if "error" in payload:
            return _normalize_jsonrpc_error(payload, jsonrpc_id=jsonrpc_id)
        raw_result = payload.get("result")
        if not isinstance(raw_result, Mapping):
            raise A2ASDKBoundaryError("invalid_jsonrpc_result", "result object required")
        result = raw_result
    try:
        task = ParseDict(dict(result), a2a_types.Task())
    except Exception as exc:  # noqa: BLE001 - protobuf raises several parse exception types.
        raise A2ASDKBoundaryError("invalid_sdk_task", str(exc)) from exc
    task_id = _required_text(task.id, "task_id")
    context_id = _optional_text(task.context_id, "context_id") or ""
    state = _task_state_name(task.status.state)
    disposition = _task_disposition(state)
    artifacts = tuple(_artifact_to_payload(artifact) for artifact in task.artifacts)
    history = tuple(_message_to_payload(message) for message in task.history)
    content = _task_content(artifacts=artifacts, history=history, status=task.status)
    source_refs = (f"a2a_task:{task_id}",) + (
        (f"a2a_context:{context_id}",) if context_id else ()
    )
    return NormalizedA2ATaskResult(
        task_id=task_id,
        context_id=context_id,
        state=state,
        disposition=disposition,
        terminal=_task_terminal(state),
        content=content,
        artifacts=artifacts,
        history=history,
        metadata=_metadata(MessageToDict(task.metadata, preserving_proto_field_name=True)),
        source_refs=source_refs,
        sdk_task=MessageToDict(task, preserving_proto_field_name=True),
        jsonrpc_id=jsonrpc_id,
    )


def _normalize_legacy_task_send(params: Mapping[str, Any]) -> NormalizedA2ATaskSend:
    task_id = _required_text(params.get("task_id"), "task_id")
    context_id = _required_text(params.get("context_id"), "context_id")
    sender_agent_id = _required_text(params.get("sender_agent_id"), "sender_agent_id")
    content = _required_text(params.get("content"), "content")
    target_address = _optional_text(params.get("target_address"), "target_address")
    metadata = _metadata(params.get("metadata"))
    request = a2a_types.SendMessageRequest(tenant="xmuse")
    request.message.message_id = task_id
    request.message.task_id = task_id
    request.message.context_id = context_id
    request.message.role = a2a_types.Role.ROLE_USER
    request.message.parts.add(text=content)
    _append_legacy_input_parts(request.message.parts, params.get("input_parts"))
    request.message.metadata.update(
        {
            "sender_agent_id": sender_agent_id,
            "target_address": target_address or "",
            "metadata": metadata,
            **metadata,
        }
    )
    return NormalizedA2ATaskSend(
        task_id=task_id,
        context_id=context_id,
        sender_agent_id=sender_agent_id,
        content=content,
        target_address=target_address,
        metadata=metadata,
        input_parts=_parts_to_payload(request.message.parts),
        sdk_request=MessageToDict(request, preserving_proto_field_name=True),
    )


def _normalize_sdk_send_message(params: Mapping[str, Any]) -> NormalizedA2ATaskSend:
    try:
        request = ParseDict(dict(params), a2a_types.SendMessageRequest())
    except Exception as exc:  # noqa: BLE001 - protobuf raises several parse exception types.
        raise A2ASDKBoundaryError("invalid_sdk_send_message", str(exc)) from exc
    message = request.message
    task_id = _required_text(message.task_id or message.message_id, "task_id")
    context_id = _required_text(message.context_id, "context_id")
    metadata_payload = MessageToDict(message.metadata, preserving_proto_field_name=True)
    metadata = _message_metadata(metadata_payload)
    sender_agent_id = _required_text(
        metadata_payload.get("sender_agent_id") or request.tenant,
        "sender_agent_id",
    )
    target_address = _optional_text(metadata_payload.get("target_address"), "target_address")
    content = _content_from_parts(message.parts)
    if not content:
        raise A2ASDKBoundaryError("missing_content", "message.parts text/data/url/raw required")
    return NormalizedA2ATaskSend(
        task_id=task_id,
        context_id=context_id,
        sender_agent_id=sender_agent_id,
        content=content,
        target_address=target_address,
        metadata=metadata,
        input_parts=_parts_to_payload(message.parts),
        sdk_request=MessageToDict(request, preserving_proto_field_name=True),
    )


def _message_metadata(metadata_payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = {
        key: value
        for key, value in metadata_payload.items()
        if key not in {"sender_agent_id", "target_address", "metadata"}
    }
    nested = _metadata(metadata_payload.get("metadata"))
    metadata.update(nested)
    return _metadata(metadata)


def _content_from_parts(parts: Any) -> str:
    chunks: list[str] = []
    for part in parts:
        kind = part.WhichOneof("content")
        if kind == "text":
            chunks.append(part.text)
        elif kind == "url":
            chunks.append(f"[a2a-url:{part.url}]")
        elif kind == "raw":
            chunks.append("[a2a-raw-bytes]")
        elif kind == "data":
            chunks.append(
                json.dumps(
                    MessageToDict(part.data, preserving_proto_field_name=True),
                    sort_keys=True,
                )
            )
    return "\n".join(chunk for chunk in chunks if chunk)


def _parts_to_payload(parts: Any) -> tuple[dict[str, Any], ...]:
    payload: list[dict[str, Any]] = []
    for part in parts:
        data = MessageToDict(part, preserving_proto_field_name=True)
        data["kind"] = part.WhichOneof("content")
        payload.append(data)
    return tuple(payload)


def _append_legacy_input_parts(parts: Any, value: object) -> None:
    if value is None:
        return
    if not isinstance(value, list | tuple):
        raise A2ASDKBoundaryError("invalid_input_parts", "input_parts list required")
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise A2ASDKBoundaryError(
                "invalid_input_part",
                f"input_parts[{index}] object required",
            )
        part = parts.add()
        kind = _input_part_kind(item)
        if kind == "text":
            part.text = _required_text(
                item.get("text") or item.get("content"),
                f"input_parts[{index}].text",
            )
        elif kind == "data":
            ParseDict(
                _json_value(item.get("data"), f"input_parts[{index}].data"),
                part.data,
            )
        elif kind in {"url", "file"}:
            part.url = _required_text(
                item.get("url") or item.get("uri") or item.get("file_id"),
                f"input_parts[{index}].url",
            )
        elif kind == "raw":
            part.raw = _raw_bytes(item.get("raw"), f"input_parts[{index}].raw")
        else:
            raise A2ASDKBoundaryError(
                "unsupported_input_part_kind",
                f"input_parts[{index}].kind={kind}",
            )
        metadata = _input_part_metadata(item)
        if metadata:
            ParseDict(metadata, part.metadata)
        filename = _optional_text(item.get("filename"), f"input_parts[{index}].filename")
        if filename is not None:
            part.filename = filename
        media_type = _optional_text(
            item.get("media_type") or item.get("mediaType"),
            f"input_parts[{index}].media_type",
        )
        if media_type is not None:
            part.media_type = media_type


def _input_part_kind(item: Mapping[str, Any]) -> str:
    explicit = _optional_text(item.get("kind"), "input_part.kind")
    if explicit:
        return explicit.lower()
    if item.get("text") is not None or item.get("content") is not None:
        return "text"
    if item.get("data") is not None:
        return "data"
    if item.get("url") is not None or item.get("uri") is not None:
        return "url"
    if item.get("file_id") is not None:
        return "file"
    if item.get("raw") is not None:
        return "raw"
    return "unknown"


def _json_value(value: object, field_name: str) -> Any:
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError) as exc:
        raise A2ASDKBoundaryError("invalid_json_value", field_name) from exc


def _raw_bytes(value: object, field_name: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise A2ASDKBoundaryError("invalid_raw_part", field_name)


def _input_part_metadata(item: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _metadata(item.get("metadata"))
    for key in ("artifact_id", "file_id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            metadata.setdefault(key, value.strip())
    return metadata


def _artifact_to_payload(artifact: Any) -> dict[str, Any]:
    parts = _parts_to_payload(artifact.parts)
    payload = MessageToDict(artifact, preserving_proto_field_name=True)
    return {
        "artifact_id": artifact.artifact_id,
        "name": artifact.name,
        "description": artifact.description,
        "parts": list(parts),
        "text": _content_from_parts(artifact.parts),
        "sdk_artifact": payload,
    }


def _message_to_payload(message: Any) -> dict[str, Any]:
    parts = _parts_to_payload(message.parts)
    return {
        "message_id": message.message_id,
        "context_id": message.context_id,
        "task_id": message.task_id,
        "role": a2a_types.Role.Name(message.role),
        "parts": list(parts),
        "text": _content_from_parts(message.parts),
        "metadata": MessageToDict(message.metadata, preserving_proto_field_name=True),
    }


def _task_content(
    *,
    artifacts: tuple[dict[str, Any], ...],
    history: tuple[dict[str, Any], ...],
    status: Any,
) -> str:
    artifact_text = "\n".join(
        str(item.get("text", "")) for item in artifacts if item.get("text")
    )
    if artifact_text:
        return artifact_text
    for message in reversed(history):
        if message.get("text"):
            return str(message["text"])
    if status.HasField("message"):
        return _content_from_parts(status.message.parts)
    return ""


def _task_state_name(value: int) -> str:
    try:
        return a2a_types.TaskState.Name(value)
    except ValueError:
        return "TASK_STATE_UNSPECIFIED"


def _task_disposition(state: str) -> str:
    if state == "TASK_STATE_COMPLETED":
        return "completed"
    if state in {"TASK_STATE_INPUT_REQUIRED", "TASK_STATE_AUTH_REQUIRED"}:
        return "blocked"
    if state in {
        "TASK_STATE_FAILED",
        "TASK_STATE_CANCELED",
        "TASK_STATE_REJECTED",
        "TASK_STATE_UNSPECIFIED",
    }:
        return "failed"
    return "in_progress"


def _task_terminal(state: str) -> bool:
    return state in {
        "TASK_STATE_COMPLETED",
        "TASK_STATE_FAILED",
        "TASK_STATE_CANCELED",
        "TASK_STATE_INPUT_REQUIRED",
        "TASK_STATE_REJECTED",
        "TASK_STATE_AUTH_REQUIRED",
    }


def _normalize_jsonrpc_error(
    payload: Mapping[str, Any],
    *,
    jsonrpc_id: str | int | None,
) -> NormalizedA2ATaskResult:
    error = payload.get("error")
    if not isinstance(error, Mapping):
        raise A2ASDKBoundaryError("invalid_jsonrpc_error", "error object required")
    message = str(error.get("message") or "A2A JSON-RPC error")
    task_id = str(jsonrpc_id or "unknown")
    return NormalizedA2ATaskResult(
        task_id=task_id,
        context_id="",
        state="TASK_STATE_FAILED",
        disposition="failed",
        terminal=True,
        content=message,
        metadata={"jsonrpc_error": dict(error)},
        source_refs=(f"a2a_jsonrpc_error:{task_id}",),
        sdk_task={},
        jsonrpc_id=jsonrpc_id,
    )


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise A2ASDKBoundaryError(f"invalid_{field_name}", field_name)
    text = value.strip()
    if not text:
        raise A2ASDKBoundaryError(f"missing_{field_name}", field_name)
    return text


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise A2ASDKBoundaryError(f"invalid_{field_name}", field_name)
    return value.strip() or None


def _metadata(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise A2ASDKBoundaryError("invalid_metadata", "metadata")
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError) as exc:
        raise A2ASDKBoundaryError("invalid_metadata_json", "metadata") from exc
