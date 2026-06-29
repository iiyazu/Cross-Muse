from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse_core.chat.groupchat_worklist import (
    GroupchatWorklistScheduler,
    GroupchatWorklistStore,
    GroupchatWorklistTickOutcome,
)
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.models import GroupchatChain
from xmuse_core.chat.peer_scheduler import PeerChatScheduler, PeerChatSchedulerOutcome

_AUTHORITY_WAIT_REASONS = {"dispatch_acknowledgement_not_execution_proof"}


@dataclass(frozen=True)
class GroupchatPeerRuntimeTickOutcome:
    worklist: GroupchatWorklistTickOutcome
    peer: PeerChatSchedulerOutcome | None = None


@dataclass(frozen=True)
class GroupchatPeerRuntimeRunOutcome:
    ticks: int
    stop_reason: str
    chain_status: str
    chain_status_reason: str | None
    tick_outcomes: tuple[GroupchatPeerRuntimeTickOutcome, ...]


@dataclass(frozen=True)
class GroupchatPeerRuntimeRootRunOutcome:
    chain_id: str
    created_chain: bool
    run: GroupchatPeerRuntimeRunOutcome


class GroupchatPeerRuntime:
    """Bridge groupchat worklist routing into the existing peer scheduler."""

    def __init__(
        self,
        *,
        db_path: Path | str,
        god_layer: Any,
        worktree: Path | str,
        scheduler_id: str,
        claim_ttl_s: int = 240,
        response_wait_s: float = 180.0,
        post_writeback_grace_s: float = 8.0,
        degraded_fallback_enabled: bool = False,
        provider_service: Any | None = None,
        memoryos_client: Any | None = None,
        memoryos_timeout_s: float = 1.0,
    ) -> None:
        self._db_path = Path(db_path)
        self._worktree = Path(worktree)
        self._god_layer = god_layer
        self._scheduler_id = scheduler_id
        self._claim_ttl_s = claim_ttl_s
        self._response_wait_s = response_wait_s
        self._post_writeback_grace_s = post_writeback_grace_s
        self._degraded_fallback_enabled = degraded_fallback_enabled
        self._provider_service = provider_service
        self._memoryos_client = memoryos_client
        self._memoryos_timeout_s = memoryos_timeout_s
        self._worklist = GroupchatWorklistScheduler(
            db_path=self._db_path,
            scheduler_id=scheduler_id,
        )
        self._store = GroupchatWorklistStore(self._db_path)
        self._inbox = ChatInboxStore(self._db_path)

    async def tick_once(self, *, chain_id: str) -> GroupchatPeerRuntimeTickOutcome:
        scanned = self._worklist.scan_routes_once(chain_id=chain_id)
        claimed = self._worklist.claim_and_link_one(chain_id=chain_id)
        if claimed is None:
            return GroupchatPeerRuntimeTickOutcome(
                worklist=GroupchatWorklistTickOutcome(
                    scanned=len(scanned),
                    **_terminal_scan_outcome_fields(scanned),
                ),
            )
        if claimed.inbox_item_id is None:
            failed = self._store.fail_item(
                claimed.item_id,
                reason="inbox_delivery_failed",
            )
            return GroupchatPeerRuntimeTickOutcome(
                worklist=GroupchatWorklistTickOutcome(
                    scanned=len(scanned),
                    claimed_item_id=claimed.item_id,
                    failed_item_id=failed.item_id,
                    failure_reason="inbox_delivery_failed",
                ),
            )

        try:
            peer = await self._peer_scheduler_for(claimed.inbox_item_id).tick_once()
        except Exception:
            failed = self._store.fail_item(
                claimed.item_id,
                reason="provider_delivery_failed",
            )
            return GroupchatPeerRuntimeTickOutcome(
                worklist=GroupchatWorklistTickOutcome(
                    scanned=len(scanned),
                    claimed_item_id=claimed.item_id,
                    linked_inbox_item_id=claimed.inbox_item_id,
                    failed_item_id=failed.item_id,
                    failure_reason="provider_delivery_failed",
                ),
            )

        inbox_item = self._inbox.get(claimed.inbox_item_id)
        if inbox_item.status != "read" or inbox_item.responded_message_id is None:
            failed = self._worklist.fail_missing_callback(claimed.item_id)
            return GroupchatPeerRuntimeTickOutcome(
                worklist=GroupchatWorklistTickOutcome(
                    scanned=len(scanned),
                    claimed_item_id=claimed.item_id,
                    linked_inbox_item_id=claimed.inbox_item_id,
                    failed_item_id=failed.item_id,
                    failure_reason="callback_missing",
                ),
                peer=peer,
            )

        try:
            completed = self._worklist.complete_from_writeback(
                claimed.item_id,
                completed_message_id=inbox_item.responded_message_id,
            )
        except ValueError:
            failed = self._worklist.fail_missing_callback(claimed.item_id)
            return GroupchatPeerRuntimeTickOutcome(
                worklist=GroupchatWorklistTickOutcome(
                    scanned=len(scanned),
                    claimed_item_id=claimed.item_id,
                    linked_inbox_item_id=claimed.inbox_item_id,
                    failed_item_id=failed.item_id,
                    failure_reason="callback_missing",
                ),
                peer=peer,
            )

        followup = self._worklist.scan_routes_once(chain_id=chain_id)
        return GroupchatPeerRuntimeTickOutcome(
            worklist=GroupchatWorklistTickOutcome(
                scanned=len(scanned),
                claimed_item_id=completed.item_id,
                linked_inbox_item_id=completed.inbox_item_id,
                completed_message_id=completed.completed_message_id,
                followup_scanned=len(followup),
                **_terminal_scan_outcome_fields(followup),
            ),
            peer=peer,
        )

    async def run_until_idle(
        self,
        *,
        chain_id: str,
        max_ticks: int,
    ) -> GroupchatPeerRuntimeRunOutcome:
        if max_ticks <= 0:
            raise ValueError("max_ticks must be positive")

        outcomes: list[GroupchatPeerRuntimeTickOutcome] = []
        stop_reason = "max_ticks"
        for _ in range(max_ticks):
            outcome = await self.tick_once(chain_id=chain_id)
            outcomes.append(outcome)
            chain = self._store.get_chain(chain_id)
            if chain.status != "open":
                stop_reason = f"chain_{chain.status}"
                break
            if outcome.worklist.claimed_item_id is None:
                if self._store.has_unscanned_messages(chain_id=chain_id):
                    continue
                if _is_authority_wait(outcome.worklist.terminal_reason):
                    stop_reason = f"waiting_for_authority:{outcome.worklist.terminal_reason}"
                    break
                stop_reason = "idle"
                break
        chain = self._store.get_chain(chain_id)
        return GroupchatPeerRuntimeRunOutcome(
            ticks=len(outcomes),
            stop_reason=stop_reason,
            chain_status=chain.status,
            chain_status_reason=chain.status_reason,
            tick_outcomes=tuple(outcomes),
        )

    async def run_from_root_message(
        self,
        *,
        conversation_id: str,
        root_message_id: str,
        max_ticks: int,
        policy_id: str = "default-natural-groupchat",
        max_depth: int = 3,
        human_max_targets: int = 2,
        agent_max_targets: int = 1,
        pingpong_warn_after: int = 2,
        pingpong_block_after: int = 4,
    ) -> GroupchatPeerRuntimeRootRunOutcome:
        chain = self._chain_for_root(
            conversation_id=conversation_id,
            root_message_id=root_message_id,
            policy_id=policy_id,
        )
        created_chain = False
        if chain is None:
            chain = self._store.create_chain(
                conversation_id=conversation_id,
                root_message_id=root_message_id,
                policy_id=policy_id,
                max_depth=max_depth,
                human_max_targets=human_max_targets,
                agent_max_targets=agent_max_targets,
                pingpong_warn_after=pingpong_warn_after,
                pingpong_block_after=pingpong_block_after,
            )
            created_chain = True

        if chain.status != "open":
            return GroupchatPeerRuntimeRootRunOutcome(
                chain_id=chain.chain_id,
                created_chain=created_chain,
                run=GroupchatPeerRuntimeRunOutcome(
                    ticks=0,
                    stop_reason=f"chain_{chain.status}",
                    chain_status=chain.status,
                    chain_status_reason=chain.status_reason,
                    tick_outcomes=(),
                ),
            )

        return GroupchatPeerRuntimeRootRunOutcome(
            chain_id=chain.chain_id,
            created_chain=created_chain,
            run=await self.run_until_idle(
                chain_id=chain.chain_id,
                max_ticks=max_ticks,
            ),
        )

    def _peer_scheduler_for(self, inbox_item_id: str) -> PeerChatScheduler:
        return PeerChatScheduler(
            db_path=self._db_path,
            god_layer=self._god_layer,
            worktree=self._worktree,
            scheduler_id=f"{self._scheduler_id}:peer",
            claim_ttl_s=self._claim_ttl_s,
            response_wait_s=self._response_wait_s,
            post_writeback_grace_s=self._post_writeback_grace_s,
            degraded_fallback_enabled=self._degraded_fallback_enabled,
            only_inbox_item_id=inbox_item_id,
            provider_service=self._provider_service,
            memoryos_client=self._memoryos_client,
            memoryos_timeout_s=self._memoryos_timeout_s,
        )

    def _chain_for_root(
        self,
        *,
        conversation_id: str,
        root_message_id: str,
        policy_id: str,
    ) -> GroupchatChain | None:
        for chain in self._store.list_chains(conversation_id):
            if chain.root_message_id == root_message_id and chain.policy_id == policy_id:
                return chain
        return None


def _terminal_scan_outcome_fields(items: list[Any]) -> dict[str, str | None]:
    for item in items:
        if getattr(item, "status", None) not in {"blocked", "failed", "canceled"}:
            continue
        return {
            "terminal_item_id": getattr(item, "item_id", None),
            "terminal_reason": getattr(item, "terminal_reason", None),
            "terminal_source_message_id": getattr(item, "source_message_id", None),
        }
    return {
        "terminal_item_id": None,
        "terminal_reason": None,
        "terminal_source_message_id": None,
    }


def _is_authority_wait(reason: str | None) -> bool:
    return reason in _AUTHORITY_WAIT_REASONS
