---
name: start
description: Entry point for multi-agent orchestrated development. Use when starting any non-trivial task that benefits from structured planning, multi-step execution, and quality gates.
auto_activate: true
triggers:
  - "start task"
  - "use orchestrated execution"
  - "multi-step task"
  - "long running task"
  - "complex feature"
---

# Multi-Agent Orchestration

Use this when a task requires multiple steps, files, or verification gates.

---

## Quick Start

For complex tasks, the flow is:

```
1. LOAD orchestrated-execution skill  → 了解 4 阶段循环
2. INVOKE @planner                  → 产出实现计划（含 WU、DoD、文件范围）
3. INVOKE @orchestrator             → 执行 4 阶段循环
4. REPORT result                    → 汇总完成情况
```

## When to Use Which

| Task Size | Approach | Agents Involved |
|-----------|----------|-----------------|
| 1 file, 1 step | Direct prompting | (none needed) |
| 2-5 files, multiple steps | @orchestrator | orchestrator → coder → adversarial-reviewer |
| Complex feature, many files | @planner → @orchestrator | planner → orchestrator → coder + adversarial-reviewer |
| Multiple independent features | @swarm-coordinator | swarm-coordinator → orchestrator(s) |

## Agent Roster

| Agent | Role |
|-------|------|
| @orchestrator | Main coordinator for a task. Decomposes, delegates, validates |
| @planner | Creates implementation plans with WU/DoD/deps |
| @coder | Implements code following TDD |
| @adversarial-reviewer | Finds failures against spec. Binary PASS/FAIL |
| @swarm-coordinator | Coordinates multiple parallel workstreams |

## Skills

| Skill | When |
|-------|------|
| orchestrated-execution | Running the 4-phase loop |
| plan-review-gate | Adversarial review of implementation plans |
