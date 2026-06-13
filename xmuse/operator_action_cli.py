from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from xmuse_core.platform.operator_actions import (
    OperatorActionRequest,
    OperatorActionService,
)
from xmuse_core.platform.release_evidence_attempts import (
    run_release_evidence_attempt_action,
)
from xmuse_core.platform.release_evidence_candidates import (
    build_release_evidence_candidate_report,
)
from xmuse_core.platform.release_evidence_export_actions import (
    run_release_evidence_export_action,
)
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.providers.god_cli_registration_store import GodCliRegistrationStore
from xmuse_core.providers.god_cli_registry import build_default_god_cli_registry
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionStore
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xmuse-operator-action",
        description="Run an audited xmuse operator action against durable stores.",
    )
    parser.add_argument("--xmuse-root", type=Path, default=DEFAULT_XMUSE_ROOT)
    parser.add_argument("--action", required=True)
    parser.add_argument("--conversation-id")
    parser.add_argument("--actor-id", default=os.environ.get("XMUSE_OPERATOR_ID", "operator"))
    parser.add_argument("--capability", action="append", default=[])
    parser.add_argument("--idempotency-key")
    parser.add_argument("--payload-json")
    parser.add_argument(
        "--payload",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Additional operator action payload field. May be repeated.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Path for the OperatorActionResult JSON envelope.",
    )
    args = parser.parse_args(argv)

    root = args.xmuse_root
    action = args.action.strip().lower().replace("-", "_")
    payload = _payload(args.payload_json, args.payload)
    if args.conversation_id and "conversation_id" not in payload:
        payload["conversation_id"] = args.conversation_id.strip()
    idempotency_key = args.idempotency_key or f"operator-cli:{action}:{uuid4().hex}"
    request = OperatorActionRequest(
        action=action,
        actor_id=args.actor_id.strip() or "operator",
        capabilities=tuple(_capabilities(args.capability, os.environ)),
        idempotency_key=idempotency_key,
        payload=payload,
        source="operator_cli",
    )
    result = _service(root, os.environ).handle(request).model_dump()
    output = args.output or root / "work" / "operator_actions" / "latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "action": result["action"],
                "status": result["status"],
                "proof_level": result["proof_level"],
                "fact_state": result["fact_state"],
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0 if result["status"] == "ok" else 2


def _service(root: Path, env: Mapping[str, str]) -> OperatorActionService:
    release_root = root / "work" / "release_readiness"
    return OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(
            extra_registrations=GodCliRegistrationStore(
                root / "god_cli_registrations.json"
            ).list_registrations()
        ),
        audit_dir=root / "work" / "operator_actions",
        registration_store=GodCliRegistrationStore(root / "god_cli_registrations.json"),
        selection_store=GodCliSelectionStore(root / "god_cli_selections.json"),
        lane_state_machine=LaneStateMachine(
            root / "feature_lanes.json",
            history_path=root / "state_history.json",
        ),
        release_evidence_export_handler=lambda request: run_release_evidence_export_action(
            request,
            xmuse_root=root,
            release_readiness_dir=release_root,
        ),
        release_evidence_candidate_handler=lambda request: build_release_evidence_candidate_report(
            root,
            conversation_id=_text(request.payload.get("conversation_id")),
            env=env,
            memoryos_payload=request.payload,
            trace_limit=_int_payload(request.payload.get("trace_limit"), default=20),
        ),
        release_evidence_attempt_handler=lambda request: run_release_evidence_attempt_action(
            request,
            xmuse_root=root,
            release_readiness_dir=release_root,
            env=env,
        ),
    )


def _payload(payload_json: str | None, entries: Sequence[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if payload_json:
        loaded = json.loads(payload_json)
        if not isinstance(loaded, dict):
            raise SystemExit("--payload-json must decode to a JSON object")
        payload.update(loaded)
    for entry in entries:
        key, separator, raw_value = entry.partition("=")
        clean_key = key.strip()
        if not separator or not clean_key:
            raise SystemExit("--payload entries must use KEY=VALUE")
        payload[clean_key] = _coerce_payload_value(raw_value.strip())
    return payload


def _coerce_payload_value(value: str) -> Any:
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "null":
        return None
    if "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


def _capabilities(explicit: Sequence[str], env: Mapping[str, str]) -> list[str]:
    values: list[str] = []
    values.extend(_split_values(env.get("XMUSE_OPERATOR_CAPABILITIES")))
    values.extend(_split_values(env.get("XMUSE_TUI_OPERATOR_CAPABILITIES")))
    values.extend(explicit)
    return _ordered_unique(item.strip() for item in values if item.strip())


def _split_values(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _ordered_unique(values: Sequence[str] | Any) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _int_payload(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


if __name__ == "__main__":
    raise SystemExit(main())
