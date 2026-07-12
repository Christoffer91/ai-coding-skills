# Spec template — every orchestrate run starts from one of these

Spec-driven development is mandatory in this loop: no implementation without a
`PLAN-<topic>.md` containing all sections below. The executor is only as good as
the spec — numbered items with file paths and acceptance criteria are what make
hands-off execution reliable.

## Who writes the spec
- **Fable 5 (medium)** — the default planner, in-session.
- **Fallback when Fable is unavailable** (session limits, outage, non-Fable session):
  draft with **gpt-5.6-sol at ultra**, read-only, then the session validates and owns it:
  ```bash
  codex exec -s read-only -c model_reasoning_effort=ultra -o /tmp/spec-draft.md - < spec-request.md
  ```
  The spec-request states the goal, constraints, and this template. A drafted spec is
  never executed unvalidated — the session (any Claude) reviews it against the template
  and the repo before step 2.

## Template

```markdown
# Plan: <topic> — <one-line goal>

## Context
Why this change exists; what prompted it; the state today. 2–5 sentences.

## Files in scope
Explicit list of files/dirs to touch. Out-of-scope files are off-limits.

## Fixes / Features (numbered)
### 1 — <name>
What to change, in which file, with expected behavior. Concrete enough that a
mechanical executor cannot misread it. Include exact flags/keys/schemas.
### 2 — …

## Acceptance
Commands that must pass (tests, lint, build, greps that prove the change),
plus behavior assertions. These become the verify gate's contract.

## Out of scope
What NOT to do — deferred items, tempting adjacent refactors, forbidden paths.

## Commit
The exact commit subject (+ optional body outline).
```

## Quality bar (planner self-check before step 2)
- Every numbered item names its file(s) and observable outcome.
- Acceptance is runnable, not aspirational ("all tests green" + which suites).
- Out-of-scope explicitly fences the executor.
- A stranger (or a medium-effort executor) could implement it without asking questions.
