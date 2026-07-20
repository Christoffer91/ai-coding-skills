# Orchestrate Model Routing

## Role Matrix

| Agent | Model | Effort | Sandbox | Delegation |
|---|---|---|---|---|
| `orchestrate_planner` | `gpt-5.6-sol` | `ultra` | read-only | Up to 3 evidence workers |
| `orchestrate_plan_critic` | `gpt-5.6-sol` | `high` | read-only | None |
| `orchestrate_explorer` | `gpt-5.6-sol` | `high` | read-only | None |
| `orchestrate_explorer_deep` | `gpt-5.6-sol` | `xhigh` | read-only | None |
| `orchestrate_executor` | `gpt-5.6-terra` | `medium` | workspace-write | None; single writer |
| `orchestrate_reviewer` | `gpt-5.6-sol` | `ultra` | read-only | Up to 3 evidence workers |

Do not leave model or effort implicit. The user's parent session may be Sol Ultra, and inherited defaults would defeat role-based routing.

## Adaptive Profiles

| Profile | Planning/spec | Critique | Execution | Final review |
|---|---|---|---|---|
| `DIRECT` | Parent produces no implementation spec | None | Parent; no delegated write | None |
| `FAST` | Pipeline `MICRO_SPEC`; no Sol Ultra | None unless escalated | `orchestrate_executor` Terra medium | Focused deterministic check only |
| `STANDARD` | `orchestrate_planner` Sol Ultra `FULL_SPEC` | `orchestrate_plan_critic` Sol high, or approved Claude lane | `orchestrate_executor` Terra medium | Fresh `orchestrate_reviewer` Sol Ultra; no autoreview duplicate |
| `DEEP` | Sol Ultra `FULL_SPEC` with high/xhigh evidence | Internal critic or approved Claude lane | Terra medium, one bounded slice at a time | One lane from `review-policy.md` plus required domain gates |

Risk and uncertainty override file count. FAST is allowed only when the solution, working set, invariant, success signal, and focused check are already concrete. Escalate `FAST -> STANDARD -> DEEP`; never downgrade within a run or reset by rephrasing.

Full spec planning is deliberately Sol Ultra. Small work saves cost by avoiding a full spec, critic, and final reviewer rather than by weakening a plan that actually carries architectural or behavioral decisions.

External model routing is risk-based, not prestige-based: Sonnet for important non-security review,
Opus for security-critical second opinion, and Fable only for explicit exceptional architecture work.

Use [token-budgeting.md](token-budgeting.md) for measured-call coverage, provisional profile
thresholds, and promotion to enforcement. Do not weaken required planning or review based on partial
telemetry; reduce duplicate packets and unnecessary model calls first.

## Evidence Selection

Use `orchestrate_explorer` for focused codebase tracing, history, test inventory, documentation checks, and ordinary review evidence.

Use `orchestrate_explorer_deep` only when one of these applies:

- security or permission assumptions;
- architecture, data-flow, or cross-module boundaries;
- contradictory evidence or an ambiguous failure;
- a high-impact claim whose false positive would materially alter the plan or review verdict.

The deep explorer must still receive one bounded question. Higher effort is not permission for broader scope.

## Context Contracts

Planner input:

- normalized user request;
- relevant repository instructions and memory pointer;
- known constraints and existing evidence.

Executor input:

- one approved objective;
- allowed and prohibited files;
- approved commands;
- invariant and success signal;
- relevant plan excerpt only.

Reviewer input:

- approved plan contract;
- current diff or exact review target;
- commands executed and PASS/FAIL/NOT_RUN outcomes;
- known pre-existing failures.

Do not give the reviewer planner rationale, rejected alternatives, or a request to confirm the implementation. The reviewer must be able to return `PASS` without inventing findings and `CHANGES_REQUIRED` without editing.

Plan critic input:

- normalized request and decision to be made;
- repository evidence packet;
- proposed `FULL_SPEC` without hidden planner reasoning.

The critic follows `critique`, steelmans first, cuts weak objections, and maps accepted concerns to exact spec and verification changes. It does not approve execution.

## Escalation

- Terra remains the writer for approved implementation and fixes.
- If two execution attempts produce no material evidence, enter `DIAGNOSE` or `REPLAN`; do not merely increase executor effort.
- Use Sol Ultra to revise the plan when scope, architecture, or acceptance criteria must change.
- An optional external-model review requires explicit approval and is reserved for high-risk or materially disputed decisions.
- The external plan-critique lane uses Claude Code print mode with `--model fable --fallback-model opus`; follow `claude-plan-critique.md`, keep tools disabled, send only reviewed plan text through stdin, and fall back to the internal critic when approval or model verification is absent.
- Luna is not part of v1. Add a mechanical worker only after representative evals show equal quality on deterministic edits.

## Budgets

- `DRY_RUN` spawns zero agents and runs zero commands.
- `FAST` spawns at most one Terra executor and no Sol planner, critic, explorer, or reviewer unless it escalates.
- Every STANDARD/DEEP `FULL_SPEC` has exactly one plan critique by default; do not run both internal and Claude critics unless the user explicitly requests comparative review.
- Maximum 3 parallel read-only evidence workers.
- Maximum 1 writer.
- Maximum 3 review/fix rounds.
- Keep agent nesting at 2 only for planner/reviewer evidence fan-out; leaf agents do not delegate.
- Apply `loop-controller` iteration, repeated-failure, no-progress, scope, command, and risk stops without reset-by-rephrasing.
- Token thresholds are next-spawn guards, not hard caps. They default to observation and never skip
  deterministic verification; see [token-budgeting.md](token-budgeting.md).
