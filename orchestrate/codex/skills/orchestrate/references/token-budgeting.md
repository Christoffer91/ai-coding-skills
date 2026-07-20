# Token Observability And Budgets

Token telemetry is an operational signal, not a billing ledger. Public pricing is not available for
Sol or Terra, and subscription execution may have zero marginal API charge while still consuming
plan quota. Never report an API-equivalent estimate as a billed cost.

## Measurement Contract

- Increment `tokens.coverage.calls.v1` before every model process starts. Its value is
  `<calls with parseable usage>/<model calls started>`.
- Add every parseable result to the role, dashboard step, and `tokens.total` counters. Include
  retries, failed calls, and repair calls when they expose valid usage.
- A dashboard step is not a coverage unit: one step may contain several calls, and a driver-only
  step may contain none.
- Label totals as **measured tokens**. Legacy records without the versioned call metric have
  `coverage unknown`; do not infer completeness from populated steps.
- Missing telemetry never fails the underlying task and never becomes zero usage.
- Codex usage is extracted only from exactly one structured JSONL `turn.completed.usage` event per
  completed process. It is per-turn: measured tokens are `input_tokens + output_tokens`; cached and
  reasoning fields are subsets/informational and are not added again. Missing, malformed, duplicate,
  killed, or non-completing telemetry remains uncovered rather than becoming zero usage.

## Provisional Next-Spawn Thresholds

| Profile | Observe threshold |
|---|---:|
| `DIRECT` | 100,000 |
| `FAST` | 250,000 |
| `STANDARD` | 600,000 |
| `DEEP` | 1,200,000 |

These initial thresholds are planning guardrails, not hard caps. The default policy is `observe`:
record that the threshold was reached, then continue required work. `enforce` may stop only before
another model call; it must not cancel a running call or skip deterministic verification. Required
review or remediation that cannot legally start becomes a visible replan/blocker, never a silent
completion.

Promote a profile to default enforcement only after at least 20 comparable runs have at least 90%
call coverage and their median/P75/P90 distributions have been reviewed. Keep an `observe` rollback.
Do not change model routing merely to improve an incomplete metric.

## Context Control

Send each role only its contract slice and fresh evidence. Reuse an unchanged approved spec, avoid
dual internal/external critiques unless requested, and use diff-only review packets after the first
review round. Token thresholds do not override risk, security, scope, or verification gates.

## Review Call Budget

- Count review processes, not headings or dashboard steps.
- `DETERMINISTIC`: zero reviewer-model calls.
- `FAST`: at most one local autoreview pass.
- `STANDARD`: one fresh internal reviewer; no autoreview duplicate and no external review by default.
- `IMPORTANT`: one internal or one Claude Sonnet review, not both by default.
- `SECURITY`: one Codex Security diff scan plus at most one Claude Opus second opinion when authorized.
- `EXCEPTIONAL`: Fable only by explicit selection; its eligible Opus fallback is the same pass.
- An explicit `$orchestrate` goal permits at most three eligible external PR reviews. Do not call an
  external reviewer on every push. Re-review only after an accepted blocking security finding changes
  the risky surface, and only once.

Subscription calls may have no incremental API invoice but still consume plan quota. Use recorded
token metadata and call coverage for capacity decisions; do not translate it into a claimed billed
cost without authoritative pricing and metered usage evidence.
