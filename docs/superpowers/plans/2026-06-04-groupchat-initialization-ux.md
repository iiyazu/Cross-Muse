# Groupchat Initialization UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build product-grade groupchat initialization with backend-owned preset/proposal/apply contracts, durable peer session records, idempotent fork lineage, and TUI `/new` + `/init` commands that consume the backend contract.

**Architecture:** Backend remains authoritative. `init god` or deterministic planning may produce a logical `TeamPlanProposal`, but only `PeerChatService` validates and applies it to `ParticipantStore`, `GodSessionRegistry`, and `PeerForkStore`. Bootstrap apply creates durable xmuse records only; live Ray/provider transport remains deferred until scheduled turns.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite, Textual TUI, pytest, ruff.

---

## Execution Notes

- Current xmuse worktree may show the whole repo as untracked. Do not run destructive git commands. Do not commit unless the repo is intentionally initialized and the user confirms.
- Do not edit MemoryOS. Do not add `memoryOS` imports/config dependencies.
- Keep fake-provider demos working, but do not count fake-only paths as production runtime evidence.
- Implement deterministic proposal/apply first. Add live init-god proposal only after the store, validator, API, and idempotency gates pass.

## File Structure

- Create `src/xmuse_core/chat/bootstrap_contracts.py`: Pydantic contracts, preset resolver, deterministic IDs, validators.
- Create `src/xmuse_core/chat/bootstrap_store.py`: SQLite-backed bootstrap draft/proposal/application state.
- Modify `src/xmuse_core/chat/store.py`: create bootstrap state tables during `ChatStore._init_db()`.
- Modify `src/xmuse_core/chat/peer_forks.py`: add deterministic bootstrap fork record helper.
- Modify `src/xmuse_core/chat/peer_service.py`: implement draft/proposal/apply lifecycle and keep legacy bootstrap as deterministic mode.
- Modify `src/xmuse_core/chat/api_models.py`: request models for presets/init mode/provider overrides/proposal/apply.
- Modify `xmuse/chat_api.py`: expose proposal/apply endpoints.
- Modify `xmuse/tui/adapter/xmuse_adapter.py`: call new backend endpoints.
- Modify `xmuse/tui/slash_commands.py`: `/new`, `/init status`, `/init retry`, `/init apply`.
- Modify tests under `tests/xmuse/`: add focused backend/API/TUI tests and update old bootstrap expectations.
- Update docs: this plan's implementation should update `docs/xmuse/codex-strengthening-handoff.md`.

---

### Task 1: Bootstrap Contracts and Presets

**Files:**
- Create: `src/xmuse_core/chat/bootstrap_contracts.py`
- Test: `tests/xmuse/test_groupchat_bootstrap_contracts.py`

- [ ] **Step 1: Write failing contract tests**

Create `tests/xmuse/test_groupchat_bootstrap_contracts.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from xmuse_core.chat.bootstrap_contracts import (
    BootstrapInitMode,
    LogicalPeerSpec,
    TeamPlanProposal,
    bootstrap_apply_id,
    bootstrap_fork_idempotency_key,
    resolve_groupchat_preset,
    validate_logical_proposal_payload,
)


def test_default_preset_resolves_logical_team() -> None:
    preset = resolve_groupchat_preset("architect-review-execute")

    assert preset.preset_id == "architect-review-execute"
    assert [role.role for role in preset.roles] == ["architect", "review", "execute"]
    assert [role.address_slug for role in preset.roles] == [
        "architect",
        "review",
        "execute",
    ]
    assert {role.provider_id for role in preset.roles} == {"codex"}


def test_logical_peer_allows_same_role_but_requires_unique_address_in_proposal() -> None:
    proposal = TeamPlanProposal(
        proposal_id="proposal-1",
        draft_id="draft-1",
        conversation_id="conv-1",
        source="deterministic",
        peers=[
            LogicalPeerSpec(
                role="review",
                address_slug="review-main",
                display_name="review-main",
                template_slug="review",
                provider_id="codex",
                profile_id="review",
                cli_kind="codex",
                model="gpt-5.5",
            ),
            LogicalPeerSpec(
                role="review",
                address_slug="review-security",
                display_name="review-security",
                template_slug="review",
                provider_id="codex",
                profile_id="review",
                cli_kind="codex",
                model="gpt-5.5",
            ),
        ],
        fork_plan=[],
        rationale="two independent reviewers",
        validation_status="pending",
    )

    assert [peer.address_slug for peer in proposal.peers] == [
        "review-main",
        "review-security",
    ]


def test_duplicate_address_slug_is_rejected() -> None:
    with pytest.raises(ValidationError, match="address_slug"):
        TeamPlanProposal(
            proposal_id="proposal-1",
            draft_id="draft-1",
            conversation_id="conv-1",
            source="deterministic",
            peers=[
                LogicalPeerSpec(
                    role="review",
                    address_slug="review",
                    display_name="review-a",
                    template_slug="review",
                    provider_id="codex",
                    profile_id="review",
                    cli_kind="codex",
                    model="gpt-5.5",
                ),
                LogicalPeerSpec(
                    role="execute",
                    address_slug="review",
                    display_name="execute-a",
                    template_slug="execute",
                    provider_id="codex",
                    profile_id="worker",
                    cli_kind="codex",
                    model="gpt-5.5",
                ),
            ],
            fork_plan=[],
            rationale="bad duplicate",
            validation_status="pending",
        )


def test_proposal_rejects_authority_ids() -> None:
    payload = {
        "proposal_id": "proposal-1",
        "draft_id": "draft-1",
        "conversation_id": "conv-1",
        "source": "init_god",
        "peers": [
            {
                "role": "architect",
                "address_slug": "architect",
                "display_name": "architect-god",
                "template_slug": "architect",
                "provider_id": "codex",
                "profile_id": "god",
                "cli_kind": "codex",
                "model": "gpt-5.5",
                "participant_id": "part-forged",
            }
        ],
        "fork_plan": [],
        "rationale": "forged ids",
        "validation_status": "pending",
    }

    with pytest.raises(ValueError, match="authority ids"):
        validate_logical_proposal_payload(payload)


def test_opencode_requires_explicit_model() -> None:
    with pytest.raises(ValidationError, match="explicit model"):
        LogicalPeerSpec(
            role="execute",
            address_slug="execute",
            display_name="execute-god",
            template_slug="execute",
            provider_id="opencode",
            profile_id="worker",
            cli_kind="opencode",
            model="",
        )


def test_deterministic_ids_are_stable() -> None:
    assert BootstrapInitMode.PROPOSAL_THEN_APPROVE.value == "proposal_then_approve"
    assert bootstrap_apply_id("conv-1", "proposal-1") == "bootstrap-apply:conv-1:proposal-1"
    assert bootstrap_fork_idempotency_key(
        "conv-1",
        "proposal-1",
        "part-init",
        "review",
    ) == "bootstrap-fork:conv-1:proposal-1:part-init:review"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest -q tests/xmuse/test_groupchat_bootstrap_contracts.py
```

Expected: fail because `xmuse_core.chat.bootstrap_contracts` does not exist.

- [ ] **Step 3: Implement contracts**

Create `src/xmuse_core/chat/bootstrap_contracts.py`:

```python
from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


CliKind = Literal["codex", "opencode"]
ProviderIdLiteral = Literal["codex", "opencode"]
ProposalSource = Literal["init_god", "deterministic"]


class BootstrapInitMode(StrEnum):
    DETERMINISTIC = "deterministic"
    PROPOSAL_THEN_APPROVE = "proposal_then_approve"


class BootstrapStatus(StrEnum):
    DRAFTING = "drafting"
    PROPOSAL_READY = "proposal_ready"
    PROPOSAL_FAILED = "proposal_failed"
    VALIDATION_FAILED = "validation_failed"
    APPLIED = "applied"
    BOOTSTRAPPED = "bootstrapped"
    DEGRADED = "degraded"


class LogicalPeerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1)
    address_slug: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    template_slug: str = Field(min_length=1)
    provider_id: ProviderIdLiteral
    profile_id: str = Field(min_length=1)
    cli_kind: CliKind
    model: str = Field(min_length=1)

    @field_validator("role", "address_slug", "display_name", "template_slug", "profile_id", "model", mode="before")
    @classmethod
    def _strip_required(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("explicit model is required" if value == "" else "must not be blank")
            return stripped
        return value

    @model_validator(mode="after")
    def _provider_matches_cli(self) -> "LogicalPeerSpec":
        if self.provider_id != self.cli_kind:
            raise ValueError("provider_id must match cli_kind for groupchat bootstrap")
        return self


class LogicalForkSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_role: Literal["init"] = "init"
    target_address_slug: str = Field(min_length=1)
    prompt_delta: str = Field(min_length=1)
    inherited_refs: list[str] = Field(default_factory=list)
    fork_reason: str = Field(min_length=1)


class PresetRoleSpec(LogicalPeerSpec):
    pass


class GroupchatPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset_id: str
    display_name: str
    description: str
    roles: list[PresetRoleSpec]
    allowed_overrides: list[Literal["provider", "model", "template", "display_name"]]


class BootstrapDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    conversation_id: str
    preset_id: str
    init_participant_id: str
    init_session_id: str
    requested_overrides: dict[str, Any] = Field(default_factory=dict)
    default_team: list[LogicalPeerSpec]
    status: BootstrapStatus
    created_at: str
    updated_at: str


class TeamPlanProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    draft_id: str
    conversation_id: str
    source: ProposalSource
    peers: list[LogicalPeerSpec]
    fork_plan: list[LogicalForkSpec] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    validation_status: Literal["pending", "accepted", "rejected"] = "pending"

    @model_validator(mode="after")
    def _unique_identity(self) -> "TeamPlanProposal":
        addresses = [peer.address_slug for peer in self.peers]
        names = [peer.display_name for peer in self.peers]
        if len(addresses) != len(set(addresses)):
            raise ValueError("address_slug must be unique within team proposal")
        if len(names) != len(set(names)):
            raise ValueError("display_name must be unique within team proposal")
        return self


class AppliedBootstrap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    apply_id: str
    draft_id: str
    proposal_id: str
    conversation_id: str
    participants: list[str]
    durable_god_sessions: list[str]
    fork_records: list[str]
    status: Literal["bootstrapped", "degraded"]
    created_at: str


_AUTHORITY_ID_KEYS = {
    "participant_id",
    "god_session_id",
    "fork_id",
    "provider_session_id",
    "provider_binding_id",
    "binding_id",
}


def validate_logical_proposal_payload(payload: dict[str, Any]) -> TeamPlanProposal:
    forbidden = _find_forbidden_keys(payload)
    if forbidden:
        raise ValueError(f"proposal payload contains authority ids: {sorted(forbidden)}")
    return TeamPlanProposal.model_validate(payload)


def _find_forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        found.update(key for key in value if key in _AUTHORITY_ID_KEYS)
        for child in value.values():
            found.update(_find_forbidden_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_find_forbidden_keys(child))
    return found


def bootstrap_apply_id(conversation_id: str, proposal_id: str) -> str:
    return f"bootstrap-apply:{conversation_id}:{proposal_id}"


def bootstrap_fork_idempotency_key(
    conversation_id: str,
    proposal_id: str,
    source_peer_id: str,
    target_address_slug: str,
) -> str:
    return f"bootstrap-fork:{conversation_id}:{proposal_id}:{source_peer_id}:{target_address_slug}"


def deterministic_draft_id(conversation_id: str) -> str:
    return f"bootstrap-draft:{conversation_id}"


def deterministic_proposal_id(conversation_id: str, preset_id: str) -> str:
    return f"bootstrap-proposal:{conversation_id}:{preset_id}"


def resolve_groupchat_preset(preset_id: str | None = None) -> GroupchatPreset:
    key = preset_id or "architect-review-execute"
    try:
        return _PRESETS[key]
    except KeyError as exc:
        raise ValueError(f"unknown groupchat preset: {key}") from exc


def preset_to_logical_team(preset: GroupchatPreset) -> list[LogicalPeerSpec]:
    return [LogicalPeerSpec.model_validate(role.model_dump()) for role in preset.roles]


_PRESETS: dict[str, GroupchatPreset] = {
    "architect-review-execute": GroupchatPreset(
        preset_id="architect-review-execute",
        display_name="Architect / Review / Execute",
        description="Default team for medium-to-large coding tasks.",
        allowed_overrides=["provider", "model", "template", "display_name"],
        roles=[
            PresetRoleSpec(role="architect", address_slug="architect", display_name="architect-god", template_slug="architect", provider_id="codex", profile_id="god", cli_kind="codex", model="gpt-5.5"),
            PresetRoleSpec(role="review", address_slug="review", display_name="review-god", template_slug="review", provider_id="codex", profile_id="review", cli_kind="codex", model="gpt-5.5"),
            PresetRoleSpec(role="execute", address_slug="execute", display_name="execute-god", template_slug="execute", provider_id="codex", profile_id="worker", cli_kind="codex", model="gpt-5.5"),
        ],
    ),
    "architect-review": GroupchatPreset(
        preset_id="architect-review",
        display_name="Architect / Review",
        description="Plan and review without executor.",
        allowed_overrides=["provider", "model", "template", "display_name"],
        roles=[
            PresetRoleSpec(role="architect", address_slug="architect", display_name="architect-god", template_slug="architect", provider_id="codex", profile_id="god", cli_kind="codex", model="gpt-5.5"),
            PresetRoleSpec(role="review", address_slug="review", display_name="review-god", template_slug="review", provider_id="codex", profile_id="review", cli_kind="codex", model="gpt-5.5"),
        ],
    ),
    "solo-architect": GroupchatPreset(
        preset_id="solo-architect",
        display_name="Solo Architect",
        description="Lightweight requirements clarification.",
        allowed_overrides=["provider", "model", "template", "display_name"],
        roles=[
            PresetRoleSpec(role="architect", address_slug="architect", display_name="architect-god", template_slug="architect", provider_id="codex", profile_id="god", cli_kind="codex", model="gpt-5.5"),
        ],
    ),
    "debug-light": GroupchatPreset(
        preset_id="debug-light",
        display_name="Debug Light",
        description="Low-cost bootstrap/runtime smoke team.",
        allowed_overrides=["provider", "model", "template", "display_name"],
        roles=[
            PresetRoleSpec(role="architect", address_slug="architect", display_name="architect-god", template_slug="architect", provider_id="codex", profile_id="god", cli_kind="codex", model="gpt-5.4-mini"),
            PresetRoleSpec(role="review", address_slug="review", display_name="review-god", template_slug="review", provider_id="codex", profile_id="review", cli_kind="codex", model="gpt-5.4-mini"),
        ],
    ),
}
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest -q tests/xmuse/test_groupchat_bootstrap_contracts.py
uv run ruff check src/xmuse_core/chat/bootstrap_contracts.py tests/xmuse/test_groupchat_bootstrap_contracts.py
```

Expected: all tests pass and ruff is clean.

---

### Task 2: Bootstrap State Store and Fork Idempotency

**Files:**
- Create: `src/xmuse_core/chat/bootstrap_store.py`
- Modify: `src/xmuse_core/chat/store.py`
- Modify: `src/xmuse_core/chat/peer_forks.py`
- Test: `tests/xmuse/test_groupchat_bootstrap_store.py`

- [ ] **Step 1: Write failing store tests**

Create `tests/xmuse/test_groupchat_bootstrap_store.py`:

```python
from __future__ import annotations

from xmuse_core.chat.bootstrap_contracts import (
    AppliedBootstrap,
    BootstrapDraft,
    BootstrapStatus,
    LogicalForkSpec,
    LogicalPeerSpec,
    TeamPlanProposal,
)
from xmuse_core.chat.bootstrap_store import BootstrapStateStore


def _peer(role: str) -> LogicalPeerSpec:
    return LogicalPeerSpec(
        role=role,
        address_slug=role,
        display_name=f"{role}-god",
        template_slug=role,
        provider_id="codex",
        profile_id="god" if role == "architect" else "review",
        cli_kind="codex",
        model="gpt-5.5",
    )


def test_draft_proposal_application_round_trip(tmp_path) -> None:
    store = BootstrapStateStore(tmp_path / "chat.db")
    draft = BootstrapDraft(
        draft_id="draft-1",
        conversation_id="conv-1",
        preset_id="architect-review",
        init_participant_id="part-init",
        init_session_id="god-init",
        requested_overrides={},
        default_team=[_peer("architect"), _peer("review")],
        status=BootstrapStatus.DRAFTING,
        created_at="2026-06-04T00:00:00Z",
        updated_at="2026-06-04T00:00:00Z",
    )
    proposal = TeamPlanProposal(
        proposal_id="proposal-1",
        draft_id=draft.draft_id,
        conversation_id=draft.conversation_id,
        source="deterministic",
        peers=draft.default_team,
        fork_plan=[
            LogicalForkSpec(
                target_address_slug="architect",
                prompt_delta="architect role",
                inherited_refs=[],
                fork_reason="bootstrap architect",
            )
        ],
        rationale="default team",
        validation_status="accepted",
    )
    applied = AppliedBootstrap(
        apply_id="apply-1",
        draft_id=draft.draft_id,
        proposal_id=proposal.proposal_id,
        conversation_id=draft.conversation_id,
        participants=["part-architect", "part-review"],
        durable_god_sessions=["god-architect", "god-review"],
        fork_records=["fork-1"],
        status="bootstrapped",
        created_at="2026-06-04T00:00:01Z",
    )

    store.upsert_draft(draft)
    store.upsert_proposal(proposal)
    store.upsert_application(applied)

    assert store.get_draft(draft.draft_id) == draft
    assert store.get_latest_draft_for_conversation("conv-1") == draft
    assert store.get_proposal(proposal.proposal_id) == proposal
    assert store.get_application(applied.apply_id) == applied


def test_upsert_is_duplicate_safe(tmp_path) -> None:
    store = BootstrapStateStore(tmp_path / "chat.db")
    draft = BootstrapDraft(
        draft_id="draft-1",
        conversation_id="conv-1",
        preset_id="solo-architect",
        init_participant_id="part-init",
        init_session_id="god-init",
        requested_overrides={},
        default_team=[_peer("architect")],
        status=BootstrapStatus.DRAFTING,
        created_at="2026-06-04T00:00:00Z",
        updated_at="2026-06-04T00:00:00Z",
    )

    store.upsert_draft(draft)
    store.upsert_draft(draft)

    assert len(store.list_drafts_for_conversation("conv-1")) == 1
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest -q tests/xmuse/test_groupchat_bootstrap_store.py
```

Expected: fail because `BootstrapStateStore` does not exist.

- [ ] **Step 3: Add SQLite tables**

Modify `src/xmuse_core/chat/store.py` inside `ChatStore._init_db()` to create three tables:

```python
                create table if not exists bootstrap_drafts (
                    draft_id text primary key,
                    conversation_id text not null,
                    payload_json text not null,
                    status text not null,
                    created_at text not null,
                    updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists bootstrap_proposals (
                    proposal_id text primary key,
                    draft_id text not null,
                    conversation_id text not null,
                    payload_json text not null,
                    validation_status text not null,
                    created_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists bootstrap_applications (
                    apply_id text primary key,
                    draft_id text not null,
                    proposal_id text not null,
                    conversation_id text not null,
                    payload_json text not null,
                    status text not null,
                    created_at text not null
                )
```

Place these alongside existing chat-owned tables. Do not create Alembic migrations unless xmuse already has a chat DB migration mechanism in this repo.

- [ ] **Step 4: Implement BootstrapStateStore**

Create `src/xmuse_core/chat/bootstrap_store.py`:

```python
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from xmuse_core.chat.bootstrap_contracts import (
    AppliedBootstrap,
    BootstrapDraft,
    TeamPlanProposal,
)
from xmuse_core.chat.store import ChatStore


class BootstrapStateStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        ChatStore(self._path)

    def upsert_draft(self, draft: BootstrapDraft) -> BootstrapDraft:
        with self._connect() as conn:
            conn.execute(
                """
                insert into bootstrap_drafts (
                    draft_id, conversation_id, payload_json, status, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?)
                on conflict(draft_id) do update set
                    payload_json = excluded.payload_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    draft.draft_id,
                    draft.conversation_id,
                    draft.model_dump_json(),
                    str(draft.status.value if hasattr(draft.status, "value") else draft.status),
                    draft.created_at,
                    draft.updated_at,
                ),
            )
        return draft

    def upsert_proposal(self, proposal: TeamPlanProposal) -> TeamPlanProposal:
        with self._connect() as conn:
            conn.execute(
                """
                insert into bootstrap_proposals (
                    proposal_id, draft_id, conversation_id, payload_json,
                    validation_status, created_at
                ) values (?, ?, ?, ?, ?, ?)
                on conflict(proposal_id) do update set
                    payload_json = excluded.payload_json,
                    validation_status = excluded.validation_status
                """,
                (
                    proposal.proposal_id,
                    proposal.draft_id,
                    proposal.conversation_id,
                    proposal.model_dump_json(),
                    proposal.validation_status,
                    _created_at_from_payload(proposal.model_dump(mode="json")),
                ),
            )
        return proposal

    def upsert_application(self, applied: AppliedBootstrap) -> AppliedBootstrap:
        with self._connect() as conn:
            conn.execute(
                """
                insert into bootstrap_applications (
                    apply_id, draft_id, proposal_id, conversation_id,
                    payload_json, status, created_at
                ) values (?, ?, ?, ?, ?, ?, ?)
                on conflict(apply_id) do nothing
                """,
                (
                    applied.apply_id,
                    applied.draft_id,
                    applied.proposal_id,
                    applied.conversation_id,
                    applied.model_dump_json(),
                    applied.status,
                    applied.created_at,
                ),
            )
        return self.get_application(applied.apply_id)

    def get_draft(self, draft_id: str) -> BootstrapDraft:
        row = self._one("select payload_json from bootstrap_drafts where draft_id = ?", draft_id)
        return BootstrapDraft.model_validate_json(row["payload_json"])

    def get_latest_draft_for_conversation(self, conversation_id: str) -> BootstrapDraft | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select payload_json from bootstrap_drafts
                where conversation_id = ?
                order by updated_at desc, rowid desc
                limit 1
                """,
                (conversation_id,),
            ).fetchone()
        return BootstrapDraft.model_validate_json(row["payload_json"]) if row else None

    def list_drafts_for_conversation(self, conversation_id: str) -> list[BootstrapDraft]:
        with self._connect() as conn:
            rows = conn.execute(
                "select payload_json from bootstrap_drafts where conversation_id = ? order by rowid asc",
                (conversation_id,),
            ).fetchall()
        return [BootstrapDraft.model_validate_json(row["payload_json"]) for row in rows]

    def get_proposal(self, proposal_id: str) -> TeamPlanProposal:
        row = self._one(
            "select payload_json from bootstrap_proposals where proposal_id = ?",
            proposal_id,
        )
        return TeamPlanProposal.model_validate_json(row["payload_json"])

    def get_application(self, apply_id: str) -> AppliedBootstrap:
        row = self._one(
            "select payload_json from bootstrap_applications where apply_id = ?",
            apply_id,
        )
        return AppliedBootstrap.model_validate_json(row["payload_json"])

    def _one(self, sql: str, value: str) -> sqlite3.Row:
        with self._connect() as conn:
            row = conn.execute(sql, (value,)).fetchone()
        if row is None:
            raise KeyError(value)
        return row

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn


def _created_at_from_payload(payload: dict) -> str:
    value = payload.get("created_at")
    return str(value) if value else "1970-01-01T00:00:00Z"
```

- [ ] **Step 5: Add fork idempotency helper**

Modify `src/xmuse_core/chat/peer_forks.py`:

```python
    def record_bootstrap_once(
        self,
        *,
        fork_id: str,
        conversation_id: str,
        source_peer_id: str,
        new_peer_id: str,
        prompt_delta: str,
        inherited_refs: list[str] | None,
        model_policy: dict[str, Any],
        feature_scope_id: str | None,
        fork_reason: str,
    ) -> PeerForkRecord:
        try:
            return self.get(fork_id)
        except KeyError:
            pass
        record = PeerForkRecord(
            fork_id=fork_id,
            conversation_id=conversation_id,
            source_peer_id=source_peer_id,
            new_peer_id=new_peer_id,
            prompt_delta=prompt_delta,
            inherited_refs=inherited_refs or [],
            model_policy=model_policy,
            feature_scope_id=feature_scope_id,
            fork_reason=fork_reason,
            created_at=_utc_now(),
        )
        self._validate_participant_lineage(record)
        with self._connect() as conn:
            conn.execute(
                """
                insert into peer_forks (
                    fork_id, conversation_id, source_peer_id, new_peer_id,
                    prompt_delta, inherited_refs_json, model_policy_json,
                    feature_scope_id, fork_reason, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(fork_id) do nothing
                """,
                (
                    record.fork_id,
                    record.conversation_id,
                    record.source_peer_id,
                    record.new_peer_id,
                    record.prompt_delta,
                    json.dumps(record.inherited_refs),
                    json.dumps(record.model_policy),
                    record.feature_scope_id,
                    record.fork_reason,
                    record.created_at,
                ),
            )
        return self.get(fork_id)
```

- [ ] **Step 6: Run tests**

Run:

```bash
uv run pytest -q tests/xmuse/test_groupchat_bootstrap_store.py tests/xmuse/test_peer_forks.py
uv run ruff check src/xmuse_core/chat/bootstrap_store.py src/xmuse_core/chat/store.py src/xmuse_core/chat/peer_forks.py tests/xmuse/test_groupchat_bootstrap_store.py
```

Expected: all tests pass and ruff is clean.

---

### Task 3: PeerChatService Draft / Proposal / Apply Lifecycle

**Files:**
- Modify: `src/xmuse_core/chat/peer_service.py`
- Test: `tests/xmuse/test_chat_bootstrap.py`
- Test: `tests/xmuse/test_groupchat_bootstrap_lifecycle.py`

- [ ] **Step 1: Add lifecycle tests**

Create `tests/xmuse/test_groupchat_bootstrap_lifecycle.py`:

```python
from __future__ import annotations

from xmuse_core.chat.peer_service import PeerChatService


def test_create_conversation_proposal_mode_stops_before_peer_materialization(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")

    payload = service.create_conversation(
        title="Bootstrap UX",
        preset_id="architect-review-execute",
        init_mode="proposal_then_approve",
    )

    assert payload["bootstrap"]["status"] in {"drafting", "proposal_ready"}
    assert payload["bootstrap"]["init_session"]["role"] == "init"
    assert payload["participants"] == []


def test_deterministic_bootstrap_applies_default_team(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")

    payload = service.create_conversation(
        title="Deterministic Bootstrap",
        preset_id="architect-review-execute",
        init_mode="deterministic",
    )

    assert payload["bootstrap"]["status"] == "bootstrapped"
    assert [participant["role"] for participant in payload["participants"]] == [
        "architect",
        "review",
        "execute",
    ]
    assert payload["bootstrap"]["fork_plan"] != []


def test_apply_bootstrap_is_duplicate_safe(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    payload = service.create_conversation(
        title="Apply Once",
        preset_id="architect-review-execute",
        init_mode="proposal_then_approve",
    )
    conv_id = payload["conversation"]["id"]

    proposal = service.create_bootstrap_proposal(
        conversation_id=conv_id,
        source="deterministic",
    )
    first = service.apply_bootstrap_proposal(
        conversation_id=conv_id,
        proposal_id=proposal["proposal"]["proposal_id"],
    )
    second = service.apply_bootstrap_proposal(
        conversation_id=conv_id,
        proposal_id=proposal["proposal"]["proposal_id"],
    )

    assert first["bootstrap"]["apply_id"] == second["bootstrap"]["apply_id"]
    assert first["bootstrap"]["fork_plan"] == second["bootstrap"]["fork_plan"]
    assert len(service.list_fork_lineage(conversation_id=conv_id, registry_path=tmp_path / "god_sessions.json")["lineage"]) == 3
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest -q tests/xmuse/test_groupchat_bootstrap_lifecycle.py
```

Expected: fail because new service parameters/methods do not exist.

- [ ] **Step 3: Extend PeerChatService signatures**

Modify `src/xmuse_core/chat/peer_service.py`:

```python
    def create_conversation(
        self,
        *,
        title: str,
        participants: list[dict[str, Any]] | None = None,
        preset_id: str | None = None,
        init_mode: str = "proposal_then_approve",
        provider_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
```

In the body, keep `participants` as legacy deterministic input:

```python
        conversation = self._chat.create_conversation(title)
        bootstrap = self.bootstrap_conversation(
            conversation_id=conversation.id,
            participants=participants,
            preset_id=preset_id,
            init_mode="deterministic" if participants is not None else init_mode,
            provider_overrides=provider_overrides,
        )
```

- [ ] **Step 4: Implement proposal/apply methods**

Add these methods to `PeerChatService`:

```python
    def create_bootstrap_proposal(
        self,
        *,
        conversation_id: str,
        source: str = "deterministic",
    ) -> dict[str, Any]:
        draft = self._bootstrap_state().get_latest_draft_for_conversation(conversation_id)
        if draft is None:
            raise PeerChatError("bootstrap_draft_not_found", conversation_id)
        proposal = self._deterministic_team_proposal(draft, source=source)
        self._bootstrap_state().upsert_proposal(proposal)
        return {
            "conversation_id": conversation_id,
            "proposal": proposal.model_dump(mode="json"),
            "status": "proposal_ready",
        }

    def apply_bootstrap_proposal(
        self,
        *,
        conversation_id: str,
        proposal_id: str,
        registry_path: Path | None = None,
    ) -> dict[str, Any]:
        proposal = self._bootstrap_state().get_proposal(proposal_id)
        if proposal.conversation_id != conversation_id:
            raise PeerChatError("bootstrap_proposal_conversation_mismatch", proposal_id)
        draft = self._bootstrap_state().get_draft(proposal.draft_id)
        init_participant = self._participants.get(draft.init_participant_id)
        registry = GodSessionRegistry(registry_path or self._base_dir / "god_sessions.json")
        participants: list[Participant] = []
        sessions = []
        forks = []
        role_templates = RoleTemplateStore(self._db_path)
        for peer in proposal.peers:
            template = role_templates.get_by_slug(peer.template_slug)
            if template is None:
                raise PeerChatError("unknown_role_template", peer.template_slug)
            participant = self._participants.ensure_bootstrap_participant(
                conversation_id=conversation_id,
                role=peer.role,
                display_name=peer.display_name,
                cli_kind=peer.cli_kind,
                model=peer.model,
                role_template_id=template.id,
            )
            participants.append(participant)
            session = self._ensure_peer_god_session(
                conversation_id=conversation_id,
                participant=participant,
                registry=registry,
            )
            sessions.append(session)
            forks.append(
                self._record_bootstrap_fork_once(
                    conversation_id=conversation_id,
                    proposal_id=proposal.proposal_id,
                    init_participant=init_participant,
                    participant=participant,
                    registry_path=registry.path,
                )
            )
        applied = self._applied_bootstrap(
            draft=draft,
            proposal=proposal,
            participants=participants,
            sessions=sessions,
            forks=forks,
        )
        self._bootstrap_state().upsert_application(applied)
        artifact = self._write_applied_bootstrap_artifact(
            conversation_id=conversation_id,
            draft=draft,
            proposal=proposal,
            applied=applied,
            participants=participants,
            init_participant=init_participant,
            init_session=registry.get(draft.init_session_id),
        )
        return {
            "conversation_id": conversation_id,
            "participants": [participant.model_dump(mode="json") for participant in participants],
            "bootstrap": {
                **applied.model_dump(mode="json"),
                "status": applied.status,
                "participant_plan": [peer.role for peer in proposal.peers],
                "fork_plan": [fork.fork_id for fork in forks],
                "artifact": artifact,
            },
        }
```

Use helper names exactly as shown; implement each helper in the same task.

- [ ] **Step 5: Implement service helpers**

Add helpers:

```python
    def _bootstrap_state(self) -> BootstrapStateStore:
        return BootstrapStateStore(self._db_path)

    def _ensure_peer_god_session(
        self,
        *,
        conversation_id: str,
        participant: Participant,
        registry: GodSessionRegistry,
    ) -> Any:
        session_address, session_inbox_id = build_conversation_session_identity(
            conversation_id=conversation_id,
            participant_id=participant.participant_id,
        )
        try:
            record = registry.find_by_conversation_participant(
                conversation_id,
                participant.participant_id,
            )
        except KeyError:
            return registry.create(
                role=participant.role,
                agent_name=participant.display_name,
                runtime=participant.cli_kind,
                session_address=session_address,
                session_inbox_id=session_inbox_id,
                conversation_id=conversation_id,
                participant_id=participant.participant_id,
                model=participant.model,
            )
        if (
            record.session_address != session_address
            or record.session_inbox_id != session_inbox_id
            or record.runtime != participant.cli_kind
        ):
            raise PeerChatError("bootstrap_session_conflict", participant.participant_id)
        return record
```

Also implement `_deterministic_team_proposal`, `_applied_bootstrap`, `_record_bootstrap_fork_once`, and `_write_applied_bootstrap_artifact` using contracts from Task 1 and `PeerForkStore.record_bootstrap_once()` from Task 2.

The fork helper must use:

```python
fork_id = bootstrap_fork_idempotency_key(
    conversation_id,
    proposal_id,
    init_participant.participant_id,
    participant.display_name.removesuffix("-god") or participant.role,
)
```

- [ ] **Step 6: Preserve legacy deterministic tests intentionally**

Update `tests/xmuse/test_chat_bootstrap.py` so existing direct create tests call:

```python
payload = service.create_conversation(
    title="Bootstrap Demo",
    init_mode="deterministic",
)
```

Keep old assertions that deterministic mode creates `architect / review / execute`.

- [ ] **Step 7: Run service tests**

Run:

```bash
uv run pytest -q tests/xmuse/test_chat_bootstrap.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py tests/xmuse/test_peer_forks.py
uv run ruff check src/xmuse_core/chat/peer_service.py tests/xmuse/test_chat_bootstrap.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py
```

Expected: all tests pass and ruff is clean.

---

### Task 4: API Models and Endpoints

**Files:**
- Modify: `src/xmuse_core/chat/api_models.py`
- Modify: `xmuse/chat_api.py`
- Test: `tests/xmuse/test_chat_bootstrap_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/xmuse/test_chat_bootstrap_api.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app


def test_api_create_conversation_proposal_mode_stops_before_apply(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/chat/conversations",
        json={
            "title": "API proposal",
            "preset_id": "architect-review-execute",
            "init_mode": "proposal_then_approve",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["bootstrap"]["status"] in {"drafting", "proposal_ready"}
    assert payload["participants"] == []


def test_api_proposal_then_apply_materializes_team(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    created = client.post(
        "/api/chat/conversations",
        json={"title": "API apply", "init_mode": "proposal_then_approve"},
    ).json()
    conv_id = created["id"]

    proposal_response = client.post(
        f"/api/chat/conversations/{conv_id}/bootstrap/proposals",
        json={"source": "deterministic"},
    )
    assert proposal_response.status_code == 201
    proposal = proposal_response.json()["proposal"]

    apply_response = client.post(
        f"/api/chat/conversations/{conv_id}/bootstrap/apply",
        json={"proposal_id": proposal["proposal_id"]},
    )

    assert apply_response.status_code == 200
    payload = apply_response.json()
    assert [participant["role"] for participant in payload["participants"]] == [
        "architect",
        "review",
        "execute",
    ]
    assert payload["bootstrap"]["fork_plan"] != []


def test_api_opencode_override_requires_explicit_model(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/chat/conversations",
        json={
            "title": "bad opencode",
            "provider_overrides": {
                "execute": {
                    "provider_id": "opencode",
                    "profile_id": "worker",
                    "cli_kind": "opencode",
                    "model": "",
                }
            },
        },
    )

    assert response.status_code == 422
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest -q tests/xmuse/test_chat_bootstrap_api.py
```

Expected: fail because request fields/endpoints do not exist.

- [ ] **Step 3: Extend API models**

Modify `src/xmuse_core/chat/api_models.py`:

```python
class ParticipantInit(BaseModel):
    role: str = Field(min_length=1)
    provider_id: ProviderId | None = None
    profile_id: ProviderProfileId | None = None
    cli_kind: Literal["codex", "opencode"] | None = None
    model: str | None = None
    role_template_id: str | None = None
    display_name: str | None = None


class ProviderOverride(BaseModel):
    provider_id: ProviderId
    profile_id: ProviderProfileId
    cli_kind: Literal["codex", "opencode"]
    model: str = Field(min_length=1)
    template_slug: str | None = None
    display_name: str | None = None


class ConversationCreate(BaseModel):
    title: str = Field(min_length=1)
    initial_participants: list[ParticipantInit] | None = None
    preset_id: str | None = None
    init_mode: Literal["deterministic", "proposal_then_approve"] = "proposal_then_approve"
    provider_overrides: dict[str, ProviderOverride] = Field(default_factory=dict)
```

Add:

```python
class BootstrapProposalCreate(BaseModel):
    source: Literal["deterministic", "init_god"] = "deterministic"


class BootstrapApplyCreate(BaseModel):
    proposal_id: str = Field(min_length=1)
```

- [ ] **Step 4: Wire chat API endpoints**

Modify imports in `xmuse/chat_api.py`:

```python
from xmuse_core.chat.api_models import BootstrapApplyCreate, BootstrapProposalCreate
```

If `xmuse/chat_api.py` already imports several names from `xmuse_core.chat.api_models`,
merge `BootstrapApplyCreate` and `BootstrapProposalCreate` into that existing import block
instead of creating a duplicate import.

Modify create endpoint to pass new fields:

```python
        result = _peer_service(root).create_conversation(
            title=request.title.strip(),
            participants=participants,
            preset_id=request.preset_id,
            init_mode=request.init_mode,
            provider_overrides={
                key: value.model_dump(mode="json")
                for key, value in request.provider_overrides.items()
            },
        )
```

Add endpoints:

```python
    @app.post(
        "/api/chat/conversations/{conversation_id}/bootstrap/proposals",
        status_code=status.HTTP_201_CREATED,
    )
    def create_bootstrap_proposal(
        conversation_id: str,
        request: BootstrapProposalCreate,
    ) -> dict[str, object]:
        try:
            return _peer_service(root).create_bootstrap_proposal(
                conversation_id=conversation_id,
                source=request.source,
            )
        except PeerChatError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from exc

    @app.post("/api/chat/conversations/{conversation_id}/bootstrap/apply")
    def apply_bootstrap_proposal(
        conversation_id: str,
        request: BootstrapApplyCreate,
    ) -> dict[str, object]:
        try:
            return _peer_service(root).apply_bootstrap_proposal(
                conversation_id=conversation_id,
                proposal_id=request.proposal_id,
                registry_path=root / "god_sessions.json",
            )
        except PeerChatError as exc:
            raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from exc
```

- [ ] **Step 5: Run API tests**

Run:

```bash
uv run pytest -q tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_fe_vision_layer1_api.py -k "conversation or participant"
uv run ruff check src/xmuse_core/chat/api_models.py xmuse/chat_api.py tests/xmuse/test_chat_bootstrap_api.py
```

Expected: all selected tests pass and ruff is clean.

---

### Task 5: TUI `/new` and `/init` Commands

**Files:**
- Modify: `xmuse/tui/adapter/xmuse_adapter.py`
- Modify: `xmuse/tui/slash_commands.py`
- Modify: `tests/xmuse/test_tui_navigation.py`

- [ ] **Step 1: Write failing TUI tests**

Append to `tests/xmuse/test_tui_navigation.py`:

```python
async def test_chat_screen_new_command_uses_bootstrap_contract(app: XmuseTUI) -> None:
    calls = []

    def _create_group(title: str, **kwargs):
        calls.append((title, kwargs))
        return {
            "id": "conv-created",
            "title": title,
            "created_at": "2026-06-04T00:00:00Z",
            "participants": [],
            "bootstrap": {"status": "proposal_ready"},
        }

    app.adapter.create_group_conversation = _create_group
    app.adapter.list_group_conversations = lambda: [
        {"id": "conv-created", "title": "Product planning", "created_at": "2026-06-04T00:00:00Z"}
    ]

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)
        input_widget = app.screen.query_one("#message-input")
        input_widget.value = "/new Product planning"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()

        assert calls == [
            (
                "Product planning",
                {"preset_id": "architect-review-execute", "init_mode": "proposal_then_approve"},
            )
        ]
        assert app.state.active_conversation_id == "conv-created"
        assert "proposal_ready" in appended[-1]["content"]


async def test_chat_screen_init_status_retry_apply_commands(app: XmuseTUI) -> None:
    app.state.active_conversation_id = "conv-1"
    app.adapter.get_bootstrap_status = lambda conv_id: {"status": "proposal_ready", "conversation_id": conv_id}
    app.adapter.create_bootstrap_proposal = lambda conv_id: {
        "proposal": {"proposal_id": "proposal-1"},
        "status": "proposal_ready",
    }
    app.adapter.apply_bootstrap_proposal = lambda conv_id, proposal_id: {
        "bootstrap": {"status": "bootstrapped", "proposal_id": proposal_id},
        "participants": [{"role": "architect"}],
    }

    async with app.run_test() as pilot:
        appended = []
        log = app.screen.query_one("#message-log")
        log.append_message = lambda **kwargs: appended.append(kwargs)
        input_widget = app.screen.query_one("#message-input")

        input_widget.value = "/init status"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()
        assert "proposal_ready" in appended[-1]["content"]

        input_widget.value = "/init retry"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()
        assert "proposal-1" in appended[-1]["content"]

        input_widget.value = "/init apply proposal-1"
        input_widget.post_message(input_widget.Submitted(input_widget, input_widget.value))
        await pilot.pause()
        assert "bootstrapped" in appended[-1]["content"]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest -q tests/xmuse/test_tui_navigation.py -k "new_command_uses_bootstrap_contract or init_status_retry_apply"
```

Expected: fail because adapter methods and `/init` route do not exist.

- [ ] **Step 3: Extend adapter**

Modify `xmuse/tui/adapter/xmuse_adapter.py`:

```python
    def create_group_conversation(
        self,
        title: str,
        *,
        preset_id: str = "architect-review-execute",
        init_mode: str = "proposal_then_approve",
    ) -> dict | None:
        clean_title = title.strip()
        if not clean_title:
            return None
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    f"{self._chat_api_base_url}/api/chat/conversations",
                    json={
                        "title": clean_title,
                        "preset_id": preset_id,
                        "init_mode": init_mode,
                    },
                )
                response.raise_for_status()
                data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None
```

Add:

```python
    def get_bootstrap_status(self, conv_id: str) -> dict | None:
        conversations = self.list_group_conversations()
        for conversation in conversations:
            if str(conversation.get("id") or conversation.get("conversation_id")) == conv_id:
                bootstrap = conversation.get("bootstrap")
                return bootstrap if isinstance(bootstrap, dict) else None
        return None

    def create_bootstrap_proposal(self, conv_id: str) -> dict | None:
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    f"{self._chat_api_base_url}/api/chat/conversations/{conv_id}/bootstrap/proposals",
                    json={"source": "deterministic"},
                )
                response.raise_for_status()
                data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def apply_bootstrap_proposal(self, conv_id: str, proposal_id: str) -> dict | None:
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    f"{self._chat_api_base_url}/api/chat/conversations/{conv_id}/bootstrap/apply",
                    json={"proposal_id": proposal_id},
                )
                response.raise_for_status()
                data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None
```

- [ ] **Step 4: Extend slash command router**

Modify `xmuse/tui/slash_commands.py`:

```python
        if command == "init":
            return self._init(rest, context)
```

Change `_new`:

```python
        created = context.app.adapter.create_group_conversation(
            title,
            preset_id="architect-review-execute",
            init_mode="proposal_then_approve",
        )
```

After refresh, include bootstrap status:

```python
        bootstrap = created.get("bootstrap") if isinstance(created, dict) else {}
        status = bootstrap.get("status") if isinstance(bootstrap, dict) else "unknown"
        return SlashCommandResult(
            True,
            refresh=True,
            message=f"Created group {_conversation_title(created)} ({conv_id}); bootstrap={status}",
        )
```

Add:

```python
    def _init(self, rest: str, context: SlashCommandContext) -> SlashCommandResult:
        conv_id = _active_conversation_id(context)
        if not conv_id:
            return SlashCommandResult(True, message="No active group.")
        parts = rest.split()
        action = parts[0] if parts else "status"
        if action == "status":
            status = context.app.adapter.get_bootstrap_status(conv_id)
            return SlashCommandResult(True, message=f"Bootstrap status: {status or 'unknown'}")
        if action == "retry":
            proposal = context.app.adapter.create_bootstrap_proposal(conv_id)
            if not proposal:
                return SlashCommandResult(True, message="Could not create bootstrap proposal.")
            proposal_id = str((proposal.get("proposal") or {}).get("proposal_id") or "")
            return SlashCommandResult(True, message=f"Bootstrap proposal ready: {proposal_id}")
        if action == "apply":
            if len(parts) < 2:
                return SlashCommandResult(True, message="Usage: /init apply <proposal_id>")
            applied = context.app.adapter.apply_bootstrap_proposal(conv_id, parts[1])
            if not applied:
                return SlashCommandResult(True, message=f"Could not apply bootstrap proposal: {parts[1]}")
            bootstrap = applied.get("bootstrap") if isinstance(applied, dict) else {}
            status = bootstrap.get("status") if isinstance(bootstrap, dict) else "unknown"
            _refresh_participants(context, conv_id)
            return SlashCommandResult(True, refresh=True, message=f"Bootstrap apply: {status}")
        return SlashCommandResult(True, message="Usage: /init status | /init retry | /init apply <proposal_id>")
```

Update `_help_text()` to include:

```python
        "/init status",
        "/init retry",
        "/init apply <proposal_id>",
```

- [ ] **Step 5: Run TUI tests**

Run:

```bash
uv run pytest -q tests/xmuse/test_tui_navigation.py -k "new_command or init_status_retry_apply or help_command"
uv run ruff check xmuse/tui/adapter/xmuse_adapter.py xmuse/tui/slash_commands.py tests/xmuse/test_tui_navigation.py
```

Expected: selected TUI tests pass and ruff is clean.

---

### Task 6: Full Gate, Docs, and No-MemoryOS Guard

**Files:**
- Modify: `docs/xmuse/codex-strengthening-handoff.md`
- Test: `tests/xmuse/test_groupchat_bootstrap_no_memoryos.py`

- [ ] **Step 1: Add no-MemoryOS guard**

Create `tests/xmuse/test_groupchat_bootstrap_no_memoryos.py`:

```python
from __future__ import annotations

from pathlib import Path


def test_groupchat_bootstrap_modules_do_not_import_memoryos() -> None:
    repo = Path(__file__).resolve().parents[2]
    files = [
        repo / "src/xmuse_core/chat/bootstrap_contracts.py",
        repo / "src/xmuse_core/chat/bootstrap_store.py",
        repo / "src/xmuse_core/chat/peer_service.py",
        repo / "xmuse/chat_api.py",
        repo / "xmuse/tui/slash_commands.py",
    ]
    offenders = [
        str(path.relative_to(repo))
        for path in files
        if "memoryos" in path.read_text(encoding="utf-8").lower()
    ]
    assert offenders == []
```

- [ ] **Step 2: Run focused backend/API/TUI gates**

Run:

```bash
uv run pytest -q \
  tests/xmuse/test_groupchat_bootstrap_contracts.py \
  tests/xmuse/test_groupchat_bootstrap_store.py \
  tests/xmuse/test_groupchat_bootstrap_lifecycle.py \
  tests/xmuse/test_chat_bootstrap_api.py \
  tests/xmuse/test_chat_bootstrap.py \
  tests/xmuse/test_peer_forks.py \
  tests/xmuse/test_groupchat_bootstrap_no_memoryos.py
```

Expected: all pass.

- [ ] **Step 3: Run focused TUI gate**

Run:

```bash
uv run pytest -q tests/xmuse/test_tui_navigation.py -k "new_command or init_status_retry_apply or help_command"
```

Expected: selected tests pass.

- [ ] **Step 4: Run broader release-sensitive gates**

Run:

```bash
uv run python scripts/demo_fake_groupchat.py
uv run xmuse-platform-runner --health-once
uv run pytest -q tests/xmuse/test_full_chain_real_run.py tests/xmuse/test_runtime_ray_backend.py
uv run ruff check \
  src/xmuse_core/chat/bootstrap_contracts.py \
  src/xmuse_core/chat/bootstrap_store.py \
  src/xmuse_core/chat/peer_service.py \
  src/xmuse_core/chat/api_models.py \
  src/xmuse_core/chat/store.py \
  src/xmuse_core/chat/peer_forks.py \
  xmuse/chat_api.py \
  xmuse/tui/adapter/xmuse_adapter.py \
  xmuse/tui/slash_commands.py \
  tests/xmuse/test_groupchat_bootstrap_contracts.py \
  tests/xmuse/test_groupchat_bootstrap_store.py \
  tests/xmuse/test_groupchat_bootstrap_lifecycle.py \
  tests/xmuse/test_chat_bootstrap_api.py \
  tests/xmuse/test_groupchat_bootstrap_no_memoryos.py
git diff --check
```

Expected: demo and health pass, tests pass, ruff clean, diff check clean.

- [ ] **Step 5: Update handoff**

Append a concise section to `docs/xmuse/codex-strengthening-handoff.md`:

```markdown
## Groupchat Initialization UX Closure

- Added backend-owned preset/proposal/apply bootstrap lifecycle.
- `proposal_then_approve` stops before peer materialization.
- deterministic mode can auto-apply for compatibility/demo paths.
- Bootstrap apply creates participants, durable `GodSessionRegistry` records, and idempotent fork lineage.
- Bootstrap apply does not start live Ray/app-server/provider-native sessions.
- TUI `/new` and `/init status|retry|apply` consume backend contracts.
- No MemoryOS dependency was introduced.

Verification:

- `uv run pytest -q tests/xmuse/test_groupchat_bootstrap_contracts.py tests/xmuse/test_groupchat_bootstrap_store.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_chat_bootstrap.py tests/xmuse/test_peer_forks.py tests/xmuse/test_groupchat_bootstrap_no_memoryos.py`: passed
- `uv run python scripts/demo_fake_groupchat.py`: passed
- `uv run xmuse-platform-runner --health-once`: passed
- `uv run ruff check src/xmuse_core/chat/bootstrap_contracts.py src/xmuse_core/chat/bootstrap_store.py src/xmuse_core/chat/peer_service.py src/xmuse_core/chat/api_models.py src/xmuse_core/chat/store.py src/xmuse_core/chat/peer_forks.py xmuse/chat_api.py xmuse/tui/adapter/xmuse_adapter.py xmuse/tui/slash_commands.py tests/xmuse/test_groupchat_bootstrap_contracts.py tests/xmuse/test_groupchat_bootstrap_store.py tests/xmuse/test_groupchat_bootstrap_lifecycle.py tests/xmuse/test_chat_bootstrap_api.py tests/xmuse/test_groupchat_bootstrap_no_memoryos.py`: passed
- `git diff --check`: passed

Remaining risk:

- Live init-god proposal generation is still optional and should be added only after deterministic proposal/apply is stable.
```

- [ ] **Step 6: Final report**

Final response must include:

- Files changed.
- Tests run and pass/fail status.
- Whether deterministic mode and proposal-then-approve mode both work.
- Whether live provider transport starts during bootstrap. Expected answer: no.
- Whether MemoryOS was touched. Expected answer: no.

---

## Scope Left for Later

- Live `init_god` model-generated proposal through MCP/writeback.
- Rich TUI wizard with selectable preset/provider/template controls.
- Dashboard read surface for bootstrap draft/proposal/apply timeline.
- Memory sidecar integration.
