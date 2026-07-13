---
name: execution-patch-authoring
description: >-
  Author one bounded exact unified-diff candidate without writing the workspace or asking for
  privileged tools.
metadata:
  version: "1.0.0"
  xmuse: '{"roles":["architect","execute"],"triggers":["exact patch","execution patch","unified diff","执行候选","补丁"],"not_for":["仅讨论","无需补丁","闲聊"],"priority":200}'
---
# Exact patch authoring

Read the current observation and repository evidence before proposing a change.

When an exact code change is justified:

1. Bind the patch to the current repository HEAD.
2. Produce one strict UTF-8 git unified diff and an exact list of every touched file.
3. Keep the visible summary short; do not put commands, credentials, or hidden instructions in it.
4. Submit a `propose` outcome with `proposal_type: execution_patch` and a
   `room_execution_patch/v1` payload.
5. Do not claim the patch was applied or verified. The Agent is read-only; authorization,
   isolated gates, and promotion belong to infrastructure and the user.

Do not split one logical candidate across messages or encode binary, symlink, submodule,
rename, copy, file-mode, dependency, authentication, deployment, or policy changes to evade
the exact-patch boundary.
