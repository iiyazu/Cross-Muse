"""Budget-window lifecycle extracted from SelfEvolutionController.

A budget window bounds how much self-evolution work a run-chain may spawn
within a rolling 10-hour period. Functions take the SelfEvolutionStore
explicitly so they stay free of controller state.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from xmuse_core.self_evolution.models import (
    EvolutionBudgetStatus,
    EvolutionBudgetWindow,
)
from xmuse_core.self_evolution.store import SelfEvolutionStore

_BUDGET_WINDOW_HOURS = 10


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _matches_source(window: EvolutionBudgetWindow, source_run_id: str) -> bool:
    return window.origin_run_id == source_run_id or source_run_id in window.consumed_run_ids


def budget_window_for(
    source_run_id: str,
    now: str,
    *,
    store: SelfEvolutionStore,
) -> tuple[EvolutionBudgetWindow, bool]:
    """Return the active budget window for a run-chain, creating one if needed.

    Expires any stale matching windows, reuses the most recent active window,
    or opens a fresh 10-hour window. The bool is whether the returned window is
    currently active.
    """
    windows = store.list_budget_windows()
    for window in windows:
        if (
            _matches_source(window, source_run_id)
            and _parse_utc(now) >= _parse_utc(window.expires_at)
            and window.status != EvolutionBudgetStatus.EXPIRED
        ):
            window.status = EvolutionBudgetStatus.EXPIRED
            store.save_budget_window(window)
    matching_active = [
        window
        for window in windows
        if _matches_source(window, source_run_id)
        and _parse_utc(now) < _parse_utc(window.expires_at)
    ]
    window = matching_active[-1] if matching_active else None
    if window is None:
        started = _parse_utc(now)
        window = EvolutionBudgetWindow(
            window_id=_new_id("evbudget"),
            origin_run_id=source_run_id,
            started_at=now,
            expires_at=(started + timedelta(hours=_BUDGET_WINDOW_HOURS))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            status=EvolutionBudgetStatus.ACTIVE,
            consumed_run_ids=[],
        )
        store.save_budget_window(window)

    active = _parse_utc(now) < _parse_utc(window.expires_at)
    next_status = (
        EvolutionBudgetStatus.ACTIVE if active else EvolutionBudgetStatus.EXPIRED
    )
    if window.status != next_status:
        window.status = next_status
        store.save_budget_window(window)
    return window, active


def consume_budget_window(
    budget_window: EvolutionBudgetWindow,
    source_run_id: str,
    *,
    store: SelfEvolutionStore,
) -> None:
    """Record a run-id against a budget window's consumed list (idempotent)."""
    if source_run_id not in budget_window.consumed_run_ids:
        budget_window.consumed_run_ids.append(source_run_id)
        store.save_budget_window(budget_window)


def get_budget_window(
    window_id: str,
    *,
    store: SelfEvolutionStore,
) -> EvolutionBudgetWindow:
    """Fetch a budget window by id, raising KeyError if absent."""
    for window in store.list_budget_windows():
        if window.window_id == window_id:
            return window
    raise KeyError(f"unknown self-evolution budget window: {window_id}")


class BudgetWindow:
    """Small controller-facing budget-window service."""

    def __init__(self, *, store: SelfEvolutionStore) -> None:
        self._store = store

    def for_track(self, track: str) -> EvolutionBudgetWindow:
        window, _active = budget_window_for(track, _utc_now(), store=self._store)
        return window

    def consume(self, window_id: str, lanes_count: int) -> EvolutionBudgetWindow:
        window = self.get(window_id)
        for index in range(max(0, lanes_count)):
            suffix = "" if index == 0 else f"#{index + 1}"
            consume_budget_window(window, f"{window.origin_run_id}{suffix}", store=self._store)
        return window

    def get(self, window_id: str) -> EvolutionBudgetWindow:
        return get_budget_window(window_id, store=self._store)
