# Architecture dependency report

`python -m xmuse.architecture_dependency_report --project-root .` emits the internal
`xmuse_architecture_dependency_report/v1` JSON evidence used by the architecture boundary
tests. It parses source only; it does not import xmuse modules or initialise a runtime.

The hard gate reports import cycles, `xmuse_core` dependencies on the application layer or
`memoryos_lite`, and read-model dependencies on supervisors, CLIs, or operator mutation
stores. It also reports cross-layer edges and fan-out as review evidence, not thresholds.

`capability_debts` intentionally exposes narrow adapters that construct a wider Store or
Ledger implementation. It has no file-specific suppression mechanism. Execution's public
`RoomExecutionStore` remains only as a stateless in-process compatibility composition;
Operator, Controller, Runtime, Review, and Read stores own their respective SQL seams directly.
