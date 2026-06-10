---
name: plan-review-gate
description: Adversarial plan review. Spawns 3 independent reviewers (Feasibility, Completeness, Scope) in parallel. All must PASS before presenting to user.
---

# Plan Review Gate

**Core principle**: No plan reaches the user without surviving independent adversarial scrutiny.

Spawn three reviewers in parallel as fresh subagent instances.

---

## The 3 Reviewers

### Reviewer 1: Feasibility
Can this plan actually be executed?

- File paths exist (verify with glob/grep)
- Dependency ordering is correct
- Technical approach matches codebase
- No unstated assumptions

### Reviewer 2: Completeness
Does the plan fully address the request?

- All requirements mapped to plan items
- Verification steps defined for each change
- Edge cases considered
- Cross-file integration points accounted for

### Reviewer 3: Scope & Alignment
Is the plan right-sized?

- Solves what was asked (no scope creep)
- No under-scoping
- Complexity proportional to problem

---

## Output

```markdown
## Plan Review Gate — APPROVED / REVISION NEEDED

| Reviewer | Verdict | Key Issues |
|----------|---------|------------|
| Feasibility | PASS/FAIL | {issues} |
| Completeness | PASS/FAIL | {issues} |
| Scope | PASS/FAIL | {issues} |

### Blocking Issues
{numbered list}
```
