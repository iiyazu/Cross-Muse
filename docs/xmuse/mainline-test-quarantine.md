# Mainline Test Quarantine

Updated: 2026-06-21

The default xmuse test run is a current-mainline signal. Historical and
compatibility contracts that no longer describe the active xmuse path are kept
in the repository, but they are isolated behind the `legacy_compat` quarantine.

## Why

xmuse currently treats the mainline as:

```text
GOD groupchat decision
-> durable blueprint / proposal / lane graph authority
-> runner projection
-> execution/review plane
-> final-action / GitHub gate
```

Older compatibility surfaces are still useful for archaeology and migration
work, but they should not make the current mainline look broken. They also
should not be deleted until a replacement or explicit archival decision exists.

## Default Behavior

`tests/xmuse/conftest.py` marks the current quarantined nodeids as
`legacy_compat` and skips them by default.

Default mainline check:

```bash
uv run pytest -q
```

Run a focused mainline subset:

```bash
uv run pytest tests/xmuse/test_grok_persistent.py tests/xmuse/test_platform_runner.py -q
```

## Running Quarantined Tests

Run quarantined historical/compatibility tests explicitly:

```bash
uv run pytest -q --include-legacy-compat -m legacy_compat
```

Run the full repository including quarantined tests:

```bash
uv run pytest -q --include-legacy-compat
```

These commands are expected to expose known historical/compatibility failures
until the corresponding debt item is fixed, rewritten as a current contract, or
archived.

## Current Quarantine Clusters

- legacy chat API conversation scoping, compact cards, fork contracts, and
  proposal approval compatibility;
- legacy `claude` CLI-kind participant/template compatibility;
- legacy launcher command shape;
- MCP permission metadata and documentation coverage;
- legacy feature-plan proposal and V14 closure approval compatibility;
- real Ray/Codex runtime evidence and soak tests that require explicit runtime
  evidence;
- legacy gate profile and master-loop contracts;
- legacy peer-chat proposal flow contracts;
- split-export entrypoint compatibility around `xmuse-tui-terminal-demo`;
- legacy Ray optional dependency expectations.

## Closure Rule

A quarantined test may leave the quarantine only when one of these is true:

1. The current mainline behavior is intentionally restored and the test passes
   without weakening authority/evidence boundaries.
2. The old expectation is rewritten as a current-mainline contract test.
3. The old surface is archived with a short rationale and no active mainline
   importer.

