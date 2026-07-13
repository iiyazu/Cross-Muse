from __future__ import annotations

from hashlib import sha256

from xmuse_core.chat.participant_store import Participant


def participant_session_prompt_fingerprint(participant: Participant) -> str:
    """Return v2 identity; mutable native model/effort are deliberately excluded."""

    fields = [
        "xmuse-room-session-v2",
        f"role={participant.role}",
        f"display_name={participant.display_name}",
        f"cli_kind={participant.cli_kind}",
    ]
    if participant.persona_snapshot_sha256 is not None:
        fields.append(f"persona_snapshot_sha256={participant.persona_snapshot_sha256}")
    prompt = "\n".join(fields)
    return f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}"


def legacy_participant_session_prompt_fingerprint(participant: Participant) -> str:
    """Return the immutable v1 fingerprint used only to prove legacy resume behavior."""

    fields = [
        "xmuse-room-session-v1",
        f"role={participant.role}",
        f"display_name={participant.display_name}",
        f"cli_kind={participant.cli_kind}",
        f"model={participant.model}",
    ]
    if participant.persona_snapshot_sha256 is not None:
        fields.append(f"persona_snapshot_sha256={participant.persona_snapshot_sha256}")
    return f"sha256:{sha256(chr(10).join(fields).encode('utf-8')).hexdigest()}"
