from __future__ import annotations

from hashlib import sha256

from xmuse_core.chat.participant_store import Participant


def participant_session_prompt_fingerprint(participant: Participant) -> str:
    """Return the durable participant-bound Room session prompt identity."""

    fields = [
        "xmuse-room-session-v1",
        f"role={participant.role}",
        f"display_name={participant.display_name}",
        f"cli_kind={participant.cli_kind}",
        f"model={participant.model}",
    ]
    # Keep the pre-persona fingerprint byte-for-byte stable for existing Rooms so
    # their durable provider binding can resume. New bundled personas deliberately
    # create a distinct session identity.
    if participant.persona_snapshot_sha256 is not None:
        fields.append(f"persona_snapshot_sha256={participant.persona_snapshot_sha256}")
    prompt = "\n".join(fields)
    return f"sha256:{sha256(prompt.encode('utf-8')).hexdigest()}"
