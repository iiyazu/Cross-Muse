# Peer Chat Runtime Gate

Updated: 2026-06-25

The `peer-chat-runtime-gate` job is the no-secrets default PR gate for the
durable GOD groupchat runtime contracts. It runs on pull requests, pushes to
`main`, and manual `workflow_dispatch` runs through `.github/workflows/xmuse-ci.yml`.

## Default Job

The job installs the project with `uv sync --frozen --all-groups`, then runs
focused lint and pytest targets for:

- peer scheduler routing and bounded fan-out;
- peer service durable inbox/message behavior;
- mention parsing and natural handoff contracts;
- prompt/context assembly contracts;
- collaboration runtime contracts;
- peer chat API contracts;
- package boundary protection.

It intentionally excludes provider credentials, real Ray/Codex app-server writeback,
long-running soak tests, and live MemoryOS service checks.

## Proof Boundary

This job provides contract proof and fake/local runtime proof for no-secrets
peer-chat paths. It does not prove production-ready groupchat, live provider
stability, live MemoryOS behavior, GitHub review truth, merge truth, full L8-L10
closure, or full L1-L11 closure.

## Server-Side Enforcement

`docs/xmuse/github-server-side-gate.md` remains the authority for branch
protection required checks. Promoting `peer-chat-runtime-gate` from default PR
visibility to a required server-side check is a separate GitHub settings change
and must be recorded with server-side evidence for the exact repository state.

Until that promotion is completed, a passing `peer-chat-runtime-gate` is useful
CI evidence but is not itself branch-protection truth.
