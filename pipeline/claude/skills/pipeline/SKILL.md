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
3. **Bootstrap the live dashboard** (same as `/orchestrate` precondition 6 — a pipeline that routes to
   orchestration must surface on localhost:4600 too). If `~/.claude/skills/orchestrate/dashboard/` exists:
   symlink the emitter onto PATH if missing (`ln -sf …/dashboard/orchestrate-status ~/.local/bin/`),
   and if `curl -s -o /dev/null -w '%{http_code}' localhost:4600` isn't `200`, start the server
   (`nohup ~/.claude/skills/orchestrate/dashboard/orchestrate-dashboard >/tmp/orch-dashboard.log 2>&1 &`;
   both tools resolve PATH symlinks safely). Then `orchestrate-status start --id <repo>-<topic> …
   --log ~/.orchestrate/artifacts/<id>/run.log` (create the dir; tee the round's codex/tool output into
   that file — the console viewer shows only the run's own recorded log, no fallback) so the run appears
   immediately, and emit `step`/`pr`/`gate` as the pipeline progresses. Do this at pipeline
   start, not reactively when the user notices an empty page.
   **Emit discipline:** use a FRESH id per topic/round — never reuse a prior round's id (suffix a round
   number if the topic repeats); emit `step --n N --state active|done` at each real transition; and
   ALWAYS end the round with a terminal `orchestrate-status done --id <id>` (or a fail state), including
   handoffs. The dashboard infers "stalled" from time-since-last-emit; a completed round MUST emit
   done/fail, and a new round MUST start a new id, or the card will misreport. For backgrounded legs
   expected to run long, wrap them with an `orchestrate-status heartbeat` loop per the orchestrate
   skill's emit discipline.

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
