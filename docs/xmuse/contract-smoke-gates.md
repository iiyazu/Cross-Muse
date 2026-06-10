# Contract Smoke Gates

Updated: 2026-06-10

This gate keeps the deep-research-02 mainline contracts hard to bypass without
requiring provider credentials, GitHub secrets, live Ray actors, or a running
MemoryOS service.

## Default CI Job

`.github/workflows/xmuse-ci.yml` defines `contract-smoke-gates` for pull requests
and pushes to `main`.

The job runs:

```bash
uv run ruff check .
uv run ruff format --check src/xmuse_core/platform/production_readiness.py tests/xmuse/test_contract_smoke_gates.py
uv run pytest -q tests/xmuse/test_mainline_contract_docs.py tests/xmuse/test_deliberation_protocol_v2.py tests/xmuse/test_god_speech_act_contract.py tests/xmuse/test_deliberation_engine.py tests/xmuse/test_deliberation_chat_api.py tests/xmuse/test_mission_blueprint_v1.py tests/xmuse/test_lane_planner_v2.py tests/xmuse/test_blueprint_lane_dag_service.py tests/xmuse/test_feature_graph_patch_forward.py tests/xmuse/test_github_ops_contract.py tests/xmuse/test_memoryos_rest_integration.py tests/xmuse/test_memoryos_event_writeback.py tests/xmuse/test_production_hardening.py tests/xmuse/test_contract_smoke_gates.py tests/xmuse/test_package_boundaries.py
uv run mypy src/xmuse_core/platform/production_readiness.py
```

## Gate Layers

| Layer | Evidence |
|---|---|
| `lint+format+typecheck` | `uv run ruff check .`, scoped `uv run ruff format --check ...`, scoped `uv run mypy ...` |
| Protocol contracts | `test_deliberation_protocol_v2.py`, `test_god_speech_act_contract.py`, `test_deliberation_engine.py` |
| Blueprint and laneDAG contracts | `test_mission_blueprint_v1.py`, `test_lane_planner_v2.py`, `test_blueprint_lane_dag_service.py` |
| GitHub merge gate contracts | `test_github_ops_contract.py` |
| REST-first MemoryOS contracts | `test_memoryos_rest_integration.py`, `test_memoryos_event_writeback.py`, `test_production_hardening.py` |
| Integration smoke | `test_deliberation_chat_api.py`, `test_memoryos_rest_integration.py`, `test_feature_graph_patch_forward.py` |
| Performance smoke | `test_contract_smoke_gates.py` verifies `PRODUCTION_SLO_TARGETS` shape and positive thresholds |

## Known Baseline Exclusions

The contract smoke job is intentionally not the full test suite. It is a
no-secrets PR gate for the product mainline:

```text
GOD groupchat deliberation
-> frozen blueprint
-> feature/lane/laneDAG
-> centralized execution/review
-> GitHub merge gate
-> REST-first MemoryOS
```

Known broad-suite baseline gaps are not hidden:

- Full-repo `uv run ruff format --check .` currently reports historical format
  drift across many existing files, so CI only format-checks the contract smoke
  files added for this gate.
- Earlier broad `tests/xmuse/test_chat_api.py` runs exposed legacy chat API
  failures around default participants, fork lineage, and compact cards. Those
  paths are not used as evidence that the mainline contract is green.
- Real provider, real Ray/Codex, and live MemoryOS soak tests remain outside
  default CI because they require external services or credentials.

Any change that claims to complete a mainline contract must add or update a
focused test in this gate, then document any broader-suite issue separately.
