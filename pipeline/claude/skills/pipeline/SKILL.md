---
name: pipeline
description: "Use when starting a multi-step code or config change that needs gating and verification before completion, when asked to handle work end-to-end, or when a task needs a 'full workflow' with checkpoints. Delegates to single-purpose skills for continuity tracking, security/risk gates, peer + domain reviews, verification, and PR-ready output. Not for trivial Q&A or when one narrow skill suffices. Keywords: pipeline, orchestrate change, security and risk gate, coverage matrix, verification before completion."
allowed-tools: Read, Glob, Grep, Edit, Write, Bash
---

# Pipeline

## Purpose
One entrypoint skill to enforce a standard pipeline: continuity tracking, security gates, relevant reviews, verification, and PR-ready output.

## When to Use
- At the start of any non-trivial task (code/config changes, behavior changes)
- When asked for a "full workflow" or end-to-end handling
- When work is long-running and needs checkpoints

## When NOT to Use
- Trivial Q&A that won't lead to changes
- Single narrow skill is clearly sufficient

## Steps

### 1. Context Setup
1. Establish a continuity track: `.claude/continuity/<project>--<topic>.md`
2. Update track with: Goal, Constraints, State

### 2. Coverage Matrix
Determine which checks apply (REQUIRED / OPTIONAL / NOT_APPLICABLE):
- Security (REQUIRED for code/config changes)
- Risk (REQUIRED for code/config changes)
- Codex Peer Review (REQUIRED for code changes)
- Architecture (REQUIRED for structural or multi-domain changes)
- Performance (if perf-sensitive)
- UX (if UI changes)
- Tests/Verification (REQUIRED for behavior changes)
- Docs (if user-visible changes)

**Implementation route:** for non-trivial implementation, hand execution to `/orchestrate` (dual-brain loop: Codex critiques + implements + opens the PR behind an independent verify gate; Claude reviews). **Always spec-first:** produce/validate `PLAN-<topic>.md` per the orchestrate spec template before routing — Fable 5 plans when available, else draft with gpt-5.6-sol at ultra and validate in-session. The coverage matrix above decides which review lenses that loop's review step must apply. Stay in-session only for small, judgment-heavy edits.

### 3. Execute Reviews
For each REQUIRED domain, run the corresponding skill:
- Security: `/security-first`, `/security-audit`
- Risk: `/risk-assess`
- Codex Peer Review (always for code changes): invoke the `/codex` skill to run `codex review --uncommitted` (or `--base main` for branch-wide). Apply the council protocol from `/codex`: auto-decide on non-critical changes, stop and ask on critical changes. Record outcome in the step 4 verification log.
- Architecture: `/architecture-review`
- Performance: `/performance-audit`
- UX: `/ux-review`
- Tests: `/test-coverage`, `/verify`
- Docs: `/update-docs`, `/prepare-pr`

### 4. Verification Gate
Before marking complete:
1. List commands to run (tests/lint/typecheck/build)
2. Get approval before running
3. Record outcomes as `command -> PASS/FAIL`

### 5. Final Output
Produce a summary with files changed, coverage matrix, commands run, risk summary, PR readiness.

## Output Format
```
## Pipeline Report
- Goal: ...
- Coverage: Security [X] | Risk [X] | Tests [X] | Docs [X]
- Changes: [file list]
- Verification: `npm test` -> PASS
- Status: Ready for PR / Needs attention
```

## Example
Input: "Add an optional `?status=` query param to an existing Azure Function HTTP endpoint."

Coverage matrix:
- Security: REQUIRED | Risk: REQUIRED | Codex Peer Review: REQUIRED
- Architecture: NOT_APPLICABLE | Performance: OPTIONAL | UX: NOT_APPLICABLE
- Tests/Verification: REQUIRED | Docs: REQUIRED

Pipeline Report:
- Goal: Add optional `status` filter to the orders endpoint
- Coverage: Security [REQUIRED] | Risk [REQUIRED] | Tests [REQUIRED] | Docs [REQUIRED]
- Changes: `function_app.py`, `tests/test_orders.py`, `README.md`
- Verification: `pytest -q` -> PASS
- Status: Ready for PR

## Safety Notes
- Never run destructive commands without approval
- If ESCALATE/BLOCKED on risk, stop and request approval

## Related Skills
- `/orchestrate` - dual-brain execution route (Codex implements, Claude reviews)
- `/continuity` - context management
- `/architecture-review` - design review
- `/verify` - pre-completion verification
- `/risk-assess` - risk assessment
- `/prepare-pr` - PR description
