"""God-picker logic extracted from PlatformOrchestrator.

xmuse is currently Codex-only. The picker preserves the historical public
shape used by orchestrator tests, but it no longer round-robins into other
runtimes or honors legacy lane metadata that names a non-Codex runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from xmuse_core.platform.agent_spawner import GodConfig


class GodPicker:
    """Selects execution/review god configs.

    Parameters
    ----------
    runtime_mode:
        Historical runtime label retained for observability.
    execution_gods:
        Ordered list of execution god configs. The first Codex config is used.
    review_gods:
        Ordered list of review god configs. The first Codex config is used.
    lane_reader:
        Callable that returns a lane dict given a lane_id, or raises KeyError.
    """

    def __init__(
        self,
        *,
        runtime_mode: str,
        execution_gods: list[GodConfig],
        review_gods: list[GodConfig],
        lane_reader: Callable[[str], dict[str, Any]],
    ) -> None:
        self._runtime_mode = runtime_mode
        self._execution_gods = execution_gods
        self._review_gods = review_gods
        self._lane_reader = lane_reader

    @property
    def runtime_mode(self) -> str:
        return self._runtime_mode

    @property
    def execution_gods(self) -> list[GodConfig]:
        return list(self._execution_gods)

    @property
    def review_gods(self) -> list[GodConfig]:
        return list(self._review_gods)

    def pick_execution(self, lane_id: str) -> GodConfig:
        """Choose the execute-god runtime for *lane_id*.

        Legacy ``god_runtime`` metadata is ignored so old lanes cannot switch
        the codex-only runtime back to Claude.
        """
        return self._first_codex(self._execution_gods)

    def pick_review(self, lane_id: str) -> GodConfig:
        """Choose the review-god runtime for *lane_id*."""
        return self._first_codex(self._review_gods)

    def _first_codex(self, gods: list[GodConfig]) -> GodConfig:
        for god in gods:
            if god.runtime == "codex":
                return god
        raise ValueError("GodPicker requires at least one codex god")
