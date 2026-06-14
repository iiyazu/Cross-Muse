from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from xmuse_core.providers.god_cli_registry import (
    GodCliCapability,
    GodCliRegistration,
)

ProofLevel = Literal["contract_proof"]
SourceAuthority = Literal["operator_action_contract"]

SCHEMA_VERSION = "xmuse.god_cli_registration_store.v1"


@dataclass(frozen=True)
class GodCliRegistrationRecord:
    registration: GodCliRegistration
    registered_by: str
    audit_id: str
    idempotency_key: str
    registered_at_utc: str
    source_authority: SourceAuthority = "operator_action_contract"
    proof_level: ProofLevel = "contract_proof"

    def model_dump(self) -> dict[str, Any]:
        data = asdict(self)
        data["registration"] = self.registration.model_dump()
        return data


class GodCliRegistrationStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def record_registration(
        self,
        *,
        registration: GodCliRegistration,
        registered_by: str,
        audit_id: str,
        idempotency_key: str,
        registered_at_utc: str | None = None,
    ) -> GodCliRegistrationRecord:
        record = GodCliRegistrationRecord(
            registration=registration,
            registered_by=_required_text(registered_by, "registered_by"),
            audit_id=_required_text(audit_id, "audit_id"),
            idempotency_key=_required_text(idempotency_key, "idempotency_key"),
            registered_at_utc=registered_at_utc or _utcnow(),
        )
        payload = self._read_payload()
        registrations = _registration_dict(payload)
        registrations[record.registration.cli_id] = record.model_dump()
        self._write_payload(
            {
                "schema_version": SCHEMA_VERSION,
                "registrations": registrations,
            }
        )
        return record

    def get(self, cli_id: str) -> GodCliRegistrationRecord | None:
        key = cli_id.strip()
        if not key:
            return None
        raw = _registration_dict(self._read_payload()).get(key)
        if not isinstance(raw, dict):
            return None
        return _record_from_payload(raw)

    def list_records(self) -> list[GodCliRegistrationRecord]:
        records: list[GodCliRegistrationRecord] = []
        for raw in _registration_dict(self._read_payload()).values():
            if not isinstance(raw, dict):
                continue
            record = _record_from_payload(raw)
            if record is not None:
                records.append(record)
        return sorted(records, key=lambda item: item.registration.cli_id)

    def list_registrations(self) -> list[GodCliRegistration]:
        return [record.registration for record in self.list_records()]

    def _read_payload(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": SCHEMA_VERSION, "registrations": {}}
        if not isinstance(payload, dict):
            return {"schema_version": SCHEMA_VERSION, "registrations": {}}
        return payload

    def _write_payload(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self._path)


def _record_from_payload(payload: dict[str, Any]) -> GodCliRegistrationRecord | None:
    raw_registration = payload.get("registration")
    if not isinstance(raw_registration, dict):
        return None
    try:
        registration = _registration_from_payload(raw_registration)
        return GodCliRegistrationRecord(
            registration=registration,
            registered_by=str(payload["registered_by"]),
            audit_id=str(payload["audit_id"]),
            idempotency_key=str(payload["idempotency_key"]),
            registered_at_utc=str(payload["registered_at_utc"]),
            source_authority=payload.get(
                "source_authority",
                "operator_action_contract",
            ),
            proof_level=payload.get("proof_level", "contract_proof"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _registration_from_payload(payload: dict[str, Any]) -> GodCliRegistration:
    return GodCliRegistration(
        cli_id=str(payload["cli_id"]),
        display_name=str(payload["display_name"]),
        command_family=str(payload["command_family"]),
        provider_profile_ref=str(payload["provider_profile_ref"]),
        capabilities=tuple(
            GodCliCapability(str(item))
            for item in _string_list(payload.get("capabilities"))
        ),
        allowed_speech_acts=tuple(_string_list(payload.get("allowed_speech_acts"))),
        supports_persistent_sessions=bool(payload["supports_persistent_sessions"]),
        supports_mcp_writeback=bool(payload["supports_mcp_writeback"]),
        state_write_allowed=bool(payload["state_write_allowed"]),
        proof_level=payload["proof_level"],
        proof_refs=tuple(_string_list(payload.get("proof_refs"))),
        registration_kind=payload.get("registration_kind", "manual"),
        source_authority=payload.get("source_authority", "operator_action_contract"),
    )


def _registration_dict(payload: dict[str, Any]) -> dict[str, Any]:
    registrations = payload.get("registrations")
    if not isinstance(registrations, dict):
        return {}
    return dict(registrations)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _required_text(value: str, field_name: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned:
        raise ValueError(f"{field_name} must not be blank")
    return cleaned


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
