from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

ProofLevel = Literal["contract_proof"]
SourceAuthority = Literal["operator_action_contract"]

SCHEMA_VERSION = "xmuse.god_cli_selection_store.v1"


@dataclass(frozen=True)
class GodCliSelectionRecord:
    conversation_id: str
    cli_id: str
    selected_by: str
    audit_id: str
    idempotency_key: str
    selected_at_utc: str
    source_authority: SourceAuthority = "operator_action_contract"
    proof_level: ProofLevel = "contract_proof"

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


class GodCliSelectionStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def record_selection(
        self,
        *,
        conversation_id: str,
        cli_id: str,
        selected_by: str,
        audit_id: str,
        idempotency_key: str,
        selected_at_utc: str | None = None,
    ) -> GodCliSelectionRecord:
        record = GodCliSelectionRecord(
            conversation_id=_required_text(conversation_id, "conversation_id"),
            cli_id=_required_text(cli_id, "cli_id"),
            selected_by=_required_text(selected_by, "selected_by"),
            audit_id=_required_text(audit_id, "audit_id"),
            idempotency_key=_required_text(idempotency_key, "idempotency_key"),
            selected_at_utc=selected_at_utc or _utcnow(),
        )
        payload = self._read_payload()
        selections = _selection_dict(payload)
        selections[record.conversation_id] = record.model_dump()
        self._write_payload(
            {
                "schema_version": SCHEMA_VERSION,
                "selections": selections,
            }
        )
        return record

    def get(self, conversation_id: str) -> GodCliSelectionRecord | None:
        key = conversation_id.strip()
        if not key:
            return None
        raw = _selection_dict(self._read_payload()).get(key)
        if not isinstance(raw, dict):
            return None
        try:
            return GodCliSelectionRecord(**raw)
        except TypeError:
            return None

    def list_records(self) -> list[GodCliSelectionRecord]:
        records: list[GodCliSelectionRecord] = []
        for raw in _selection_dict(self._read_payload()).values():
            if not isinstance(raw, dict):
                continue
            try:
                records.append(GodCliSelectionRecord(**raw))
            except TypeError:
                continue
        return sorted(records, key=lambda item: item.conversation_id)

    def _read_payload(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": SCHEMA_VERSION, "selections": {}}
        if not isinstance(payload, dict):
            return {"schema_version": SCHEMA_VERSION, "selections": {}}
        return payload

    def _write_payload(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self._path)


def _selection_dict(payload: dict[str, Any]) -> dict[str, Any]:
    selections = payload.get("selections")
    if not isinstance(selections, dict):
        return {}
    return dict(selections)


def _required_text(value: str, field_name: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ValueError(f"{field_name} must not be blank")
    return cleaned


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
