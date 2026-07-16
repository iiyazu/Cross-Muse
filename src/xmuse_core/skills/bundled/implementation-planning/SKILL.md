---
name: implementation-planning
description: >-
  Turn a requested change into an evidence-based implementation plan with explicit contracts,
  dependencies, ownership, verification, and scope boundaries.
metadata:
  version: "1.0.0"
  xmuse: '{"roles":["architect"],"triggers":["实现","方案","规划","架构","拆分","implementation","plan","design"],"not_for":["仅确认","打招呼","闲聊"],"priority":100}'
---
# Implementation planning

Use repository implementation and fresh tests as the source of truth.

For the current observation:

1. Identify the concrete outcome, authority boundaries, and invariants that must survive.
2. Inspect the relevant runtime path before proposing changes.
3. Produce a small dependency-ordered plan with explicit ownership and integration points.
4. Name focused verification for each risky contract and the final acceptance evidence.
5. Keep non-goals explicit and call out only blockers that materially change the plan.

If the Human explicitly asks you to delegate one concrete next action, submit a durable
`handoff` naming the intended active participant instead of merely saying that participant
is executing. A handoff is a directed recommendation, not proof that work started; do not
claim progress until a durable attempt or outcome is present in the delivered evidence.

Do not author another participant's speech, choose who may observe, or require a Room response.
