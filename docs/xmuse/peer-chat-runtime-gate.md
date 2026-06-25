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
protection required checks. As of the 2026-06-25 live evidence capture,
`peer-chat-runtime-gate` is promoted from default PR visibility to a required
server-side check for `main`.

The promotion is recorded in
`docs/xmuse/github-server-side-gate-live-evidence-2026-06-25.md`. A passing
`peer-chat-runtime-gate` on a PR is CI evidence; branch-protection truth comes
from the GitHub server-side required-check setting for the exact repository
state.
