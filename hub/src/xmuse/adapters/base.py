"""Wake adapter interface. One `Driver` per vendor; the engine never branches on vendor.

Mapping to the dsh contract A–H (XMUSE2-M0-DSH-PROMPT):
  A  headless.start / Sink.turn_ended         send into an existing session; turn-end + failure events
  B  Driver.write_config                       project-level MCP config, only xmuse tools pre-approved
  C  Driver.presence().holder                  single writer: host serializes ('free') or a lease says who holds it
  D  Driver.push                               push into a live interactive session (optional)
  E  TurnEnd.usage                             per-turn usage, never cumulative
  F  Presence.human_turn + Driver.on_hook      tell human input from hub input
  G  Driver.on_hook                            turn-boundary hooks (optional)
  H  agent["model"] + env.clean_env()          explicit model, clean environment
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class Usage:
    input: int = 0        # uncached input
    cache_read: int = 0
    cache_write: int = 0
    output: int = 0       # incl. reasoning
    context: int = 0      # prompt size of the turn's last model call = what the next wake re-reads
    calls: int = 0        # model calls in the turn
    mode: str = "chat"    # "code" when the turn edited files or ran commands
    model: str = ""

    @property
    def total(self) -> int:
        return self.input + self.cache_read + self.cache_write + self.output


@dataclass
class TurnSpec:
    turn_id: int
    agent: dict            # agents row (id, vendor, model, settings, ...)
    session: str | None    # vendor session id to continue; None = start a fresh session
    prompt: str
    cwd: Path
    run_log: Path          # where the adapter keeps the raw vendor stream for this turn


@dataclass
class TurnEnd:
    turn_id: int
    status: str            # succeeded | failed | interrupted
    session: str | None    # vendor session id the turn ran in (new id for fresh sessions)
    usage: Usage = field(default_factory=Usage)
    error: str | None = None
    note: str | None = None  # e.g. fork_detected
    retry_at: float | None = None  # vendor refused the turn for quota: requeue and pause the agent until then
    requeue: str | None = None     # messages were not handled: 'fresh' = vendor lost the session, retry in a new
                                   # one; 'hold' = session stays busy (lease refused), pause the agent for the human


@dataclass
class Presence:
    holder: str = "free"     # free | tui (an interactive process holds the session) | hub
    human_turn: bool = False  # a human input is being processed: admission waits
    push: bool = False       # the interactive holder accepts pushed messages (Driver.push)


class Sink(Protocol):
    """Implemented by the engine. Adapters call it from their own threads."""
    def turn_ended(self, end: TurnEnd) -> None: ...
    def kick(self) -> None: ...
    def approval(self, agent_id: str, session: str, request: dict) -> None: ...


class Adapter(Protocol):
    name: str

    def start(self, spec: TurnSpec) -> dict:
        """Begin the turn without blocking; return {"pid"?: int, "handle"?: str}.
        Must later call sink.turn_ended exactly once for spec.turn_id."""

    def interrupt(self, turn_id: int) -> None: ...


class Driver(Protocol):
    vendor: str
    headless: Adapter            # autonomous path (user absent)
    push: Adapter | None         # human-present path into a live interactive session

    def presence(self, agent: dict, session: str | None) -> Presence: ...

    def on_hook(self, agent: dict, event: str, payload: dict) -> bool:
        """Vendor hook/event report; returns True when admission should be re-checked."""

    def write_config(self, ws: Path, agent: dict, state: Path) -> list[Path]:
        """Project-level config that mounts the shim and pre-approves only xmuse tools."""

    def attach_command(self, agent: dict, session: str | None) -> str:
        """How the human opens the agent's current session in its native UI."""

    def close(self) -> None: ...
