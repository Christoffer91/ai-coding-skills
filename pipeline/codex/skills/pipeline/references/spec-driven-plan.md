# Spec-Driven Plan Contract

Use this full contract for `STANDARD` and `DEEP` work. `FAST` work uses only the micro-spec defined in `pipeline`; do not inflate a mechanical edit into this document.

## Problem and outcome
- Current behavior or constraint.
- Intended user or system outcome.
- Evidence that the problem is real.

## Scope and non-goals
- In-scope behavior, components, and repositories.
- Explicit non-goals and do-not-touch boundaries.
- Allowed and prohibited files.

## Acceptance scenarios
- Numbered, observable scenarios using Given/When/Then where useful.
- Expected failure and edge-case behavior.
- Each scenario maps to deterministic evidence or an explicitly manual check.

## Interfaces and invariants
- APIs, schemas, data flow, state transitions, compatibility, and ownership boundaries.
- Security, privacy, cost, accessibility, and operational invariants.
- Dependencies and external actions that require approval.

## Implementation slices
- Small ordered slices with one objective and reversible boundary each.
- Exact proposed files and commands per slice.
- No unrelated cleanup.

## Verification map
- Acceptance scenario -> check -> expected signal.
- Focused check first, adjacent regression check second, broader suite only when justified.
- Mark unavailable checks and remaining risk explicitly.

## Rollback and recovery
- Reversal or disable path.
- State/data compatibility during rollback.
- Human gates for migration, publish, deploy, push, or destructive action.

## Open decisions
- Only decisions that materially change scope, risk, interfaces, or acceptance criteria.
- Recommended option and the evidence needed to decide.

## Critique disposition
- Critique verdict and reviewer/model.
- Accepted findings and exact plan changes.
- Rejected concerns with concise evidence.
- Remaining caveats or approval gates.

The approved full spec becomes the implementation contract. `orchestrate` and `loop-controller` may update it only through an explicit replan transition; they must not silently reinterpret success criteria or scope.
