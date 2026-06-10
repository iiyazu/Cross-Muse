---
name: orchestrated-execution
description: 4-phase execution loop for work units - IMPLEMENT, VALIDATE, ADVERSARIAL REVIEW, COMMIT. Trust nothing, verify everything, review adversarially.
---

# Orchestrated Execution Skill

**Core principle**: Trust nothing. Verify everything. Review adversarially.

Use this when a task has been decomposed into work units with DoD items.

---

## The 4-Phase Execution Loop

For each work unit, execute these four phases in sequence:

```text
┌──────────┐    ┌──────────┐    ┌──────────────┐    ┌──────┐
│ IMPLEMENT│───→│ VALIDATE │───→│  ADVERSARIAL │───→│COMMIT│
│          │    │          │    │    REVIEW     │    │      │
└──────────┘    └──────────┘    └──────┬───────┘    └──────┘
     ▲                                 │
     │              FAIL               │
     └─────────────────────────────────┘
```

### Phase 1: IMPLEMENT

Spawn a coding subagent with:
- The spec section for this work unit
- The DoD items
- The file scope (exact files it may touch)
- Project context (completed work units, patterns)

### Phase 2: VALIDATE (Orchestrator runs directly)

Run these yourself — do NOT ask the coder:
```bash
# Type checking
pytest --no-header -q  # or your test runner

# Lint
ruff check .

# Verify file scope
git diff --name-only
```

**Phase 2 outcomes:**
- All pass → proceed to Phase 3
- Any fail → return to Phase 1

### Phase 3: ADVERSARIAL REVIEW

Spawn the `adversarial-reviewer` subagent as a **fresh instance** with:
- The spec
- The DoD items
- The diff (`git diff`)

**Phase 3 outcomes:**
- PASS → proceed to Phase 4
- FAIL → return to Phase 1, spawn **new** reviewer

### Phase 4: COMMIT

```bash
git add <file-scope-files>
git commit -m "feat(wu-{n}): {title}

DoD items verified:
- [x] {item-1}
- [x] {item-2}
"
```

---

## Critical Rules (MUST FOLLOW)

1. **Never trust subagent self-reports** — run validation yourself
2. **Fresh reviewer on re-review** — always spawn new instance with no prior context
3. **Max 3 retries per work unit** — then escalate to user
4. **File scope enforcement** — verify with `git diff --name-only`
5. **Quality gates are BLOCKING** — no skip, no advisory

---

## Escalation Protocol

After 3 failed attempts per work unit:

```markdown
## Escalation: WU-{n} Failed After 3 Attempts

### Failure History
| Attempt | Phase | Error | Fix Tried |
|---------|-------|-------|-----------|
| 1 | {phase} | {error} | {fix} |
| 2 | {phase} | {error} | {fix} |
| 3 | {phase} | {error} | {fix} |

### Options
1. Skip this work unit
2. Manual intervention
3. Restructure approach
```
