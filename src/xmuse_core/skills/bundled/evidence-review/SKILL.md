---
name: evidence-review
description: >-
  Ground claims in implementation and fresh tests. Use for review, audit, verification, and
  risk analysis.
metadata:
  version: "1.0.0"
  xmuse: '{"roles":["review"],"triggers":["审计","检查","验证","风险","review","verify","audit"],"not_for":["仅确认","打招呼","闲聊"],"priority":100}'
---
# Evidence review

Review the current observation against repository behavior and fresh executable evidence.

For each material finding:

1. State the violated contract or user-visible consequence.
2. Cite the smallest relevant implementation or test location.
3. Distinguish confirmed defects from risks and assumptions.
4. Recommend the smallest repair that preserves identity, causality, authority, and recovery.
5. Prioritize only findings that could change correctness or acceptance.

Do not treat documentation, provider output, or this guidance as durable Room authority. Do not
author another participant's speech or require a Room response.
