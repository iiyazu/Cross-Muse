# MemoryOS Lite Runtime Compatibility

Updated: 2026-06-10

This document closes the Deep Research 04 MemoryOS Lite compatibility gap. xmuse
keeps MemoryOS REST-first and does not import `memoryos_lite`.

## Public API Payload Contract

xmuse only relies on the public session-centric REST surface:

| Operation | Endpoint | Default xmuse payload |
| --- | --- | --- |
| create session | `POST /sessions` | `{ "title": "xmuse:{kind}:{digest}" }` |
| ingest | `POST /sessions/{id}/ingest` | `role`, `content`, `metadata` |
| build context | `POST /sessions/{id}/build-context` | `task`, `budget`, `retrieval_query` |
| search | `POST /memory/search` | `query`, `top_k`, `session_id` |

The default adapter does not send `include_global_core` or `limit`. Those fields
may exist in some MemoryOS Lite builds, but xmuse must not require the service to
accept extra fields for default compatibility.

## ContextPackage Compatibility

xmuse parses the current public `ContextPackage` shape:

- `pinned_core`
- `active_task_pages`
- `recent_messages`
- `retrieved_pages`
- `dropped_pages`
- `metadata`

`retrieved_evidence` is parsed when present, but it is an optional compatibility
enhancement. Live compatibility must not depend on `retrieved_evidence` being
returned by the service.

Source-ref extraction order:

1. top-level `metadata.xmuse_source_refs`;
2. `retrieved_evidence[].metadata.xmuse_source_refs`, when present;
3. `recent_messages[].metadata.xmuse_source_refs`;
4. synthetic `memoryos-lite-message:{id}` refs for auditable message links.

## Durable Namespace Binding

xmuse persists:

```text
MemoryOSNamespace.uri -> MemoryOS Lite session_id
```

The default store path is:

```text
${XMUSE_ROOT:-xmuse}/memoryos_lite_sessions.json
```

This is runtime state. It is ignored by repository rules and must not be
committed. Tests inject a temporary store path.

On process restart, a new adapter with the same binding store reuses the active
session id and does not create a new session. If MemoryOS Lite returns `404` for
an active session, xmuse marks that binding `stale`, creates a fresh session,
and retries the operation once.

## Proof Levels

| Proof | Evidence | Default CI |
| --- | --- | --- |
| fake contract | payload, ContextPackage, binding, stale retry tests | yes |
| live smoke | opt-in live service health/ingest/context test | no |
| restart/resume continuity | temp-store fake restart test; opt-in live restart test | fake yes, live no |
| provider/Ray/Codex runtime | credentialed runtime gate | no |

Default CI remains no-secrets and no-live-service. Live MemoryOS Lite runtime
proof requires:

```bash
XMUSE_LIVE_MEMORYOS_LITE=1 \
XMUSE_MEMORYOS_LITE_URL=http://127.0.0.1:8000 \
uv run pytest -q tests/xmuse/test_memoryos_lite_interop.py
```
