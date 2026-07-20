# Claude Final Review Gate

Use this only for a bounded, secret-free final review after outbound authorization is established. An
explicit user invocation of `$orchestrate` supplies the goal-scoped budget in
[review-policy.md](review-policy.md). Under a valid `PR_READY` action grant, select the review tier,
create one per-PR `external_review_allowance: unused` only for an eligible external lane, and dispatch
without another approval prompt.
Implicit routing or a request without explicit `$orchestrate` still requires separate explicit
approval. Internal `orchestrate_reviewer` remains the fallback when authorization, authentication,
entitlement, input bounds, output validity, or model verification is absent.

## Precedence

For one review pass, the approved external lane replaces the internal reviewer; it is not an automatic
second opinion. Running both reviewers for comparison is an additional paid call and requires separate explicit approval.
A review-triggered fix uses deterministic checks and the internal reviewer. Do not automatically call
Claude again; only an accepted blocking security finding that changed the risky surface permits the
single exceptional re-review described by the policy.

## Safe command

Follow [claude-cli-preflight.md](claude-cli-preflight.md) through the shared runner. `IMPORTANT` maps to
`--review-tier important` (Sonnet), `SECURITY` maps to `--review-tier security` (Opus), and only an
explicit `EXCEPTIONAL` decision maps to `--review-tier exceptional` (Fable with eligible Opus
fallback). After `preflight`,
print exactly its JSON `command` array as shell-escaped informational argv. Verify the idempotency key,
then atomically consume the allowance immediately before invoking the runner. For implicit routing,
wait for separate explicit outbound approval. Never hand-build or hand-parse the Claude call.

Any runner dispatch consumes the allowance regardless of outcome. A failed preflight sends no packet
and leaves it unused. A matching idempotency receipt reuses the prior result with zero model calls.

Do not enter this lane for `DRY_RUN` or an explicit internal-only/no-external request. Standing authorization covers only this selected review pass and does not approve another paid comparison, repository external action, or any other hard gate.

```bash
"$CLAUDE_BIN" -p \
  --safe-mode \
  --permission-mode plan \
  --tools "" \
  --no-session-persistence \
  --model <sonnet|opus|fable> \
  --effort max \
  --output-format json \
  --json-schema "$REVIEW_SCHEMA"
```

Omit `--max-budget-usd` for verified Claude.ai subscription auth. Add `--max-budget-usd 2` for API, cloud-provider, or unknown authenticated modes, or when the user explicitly requests a subscription usage cap.

Send the bounded review packet through stdin. Do not place the spec, diff, check output, repository excerpts, customer data, or secrets in process arguments. Do not enable tools, MCP servers, Chrome, plugins, auto mode, or ultrareview for this gate.

## Fresh bounded inputs

Construct the packet immediately before the call from the same three inputs required by workflow step 9:

1. The approved spec and its recorded critique disposition, at most 100 KiB.
2. The current textual diff for only the approved working set, with binary/generated content omitted, at most 200 KiB.
3. Check outcomes as exact command, exit status, and a short relevant failure excerpt when needed, at most 20 KiB.

Do not substitute planner rationale, hidden reasoning, earlier diffs, full raw logs, or unreviewed repository content. If any input cannot be made complete inside these limits, report the bound and use the internal reviewer instead of truncating away relevant evidence.

## Model policy and fallback

- Important non-security work uses the Claude Code `sonnet` alias.
- Security-critical work uses `opus` directly so security review does not depend on Fable routing.
- Fable is exceptional, not default. Only that tier has `--fallback-model opus` and one direct Opus
  attempt for proven Fable-specific unavailability before model execution.
- Inspect the JSON result metadata when present. If the resolved model cannot be verified, report that fact and rerun the pass with the internal reviewer.
- Authentication, entitlement, command, timeout, malformed-output, or metadata-verification failure is non-fatal to orchestration: the internal `orchestrate_reviewer` is the fallback.
- Do not invent or hard-code an unverified full model ID.

## Prompt and verdict contract

The runner enforces structured output. Claude reviews only the approved spec and fresh evidence,
categorizes findings as `blocking`, `notable`, or `nit`, cites file and optional line, explains the
failure mode and recommendation, and returns `PASS` or `CHANGES_REQUIRED`.

Codex validates the findings before workflow step 10. Only validated blocking findings return to the
executor; notable and nit findings remain recorded evidence unless they expose a spec or risk change.
Codex fixes accepted in-scope blockers, rejects false findings with concrete code evidence, and reruns
affected verification. The user is not a mandatory review runner. Claude does not approve execution,
merging, or deployment.

If outbound data policy rejects the call before Claude starts, record `EXTERNAL_REVIEW_BLOCKED:data-policy` and follow [claude-cli-preflight.md](claude-cli-preflight.md) with zero Claude retries. Optional external review falls back immediately to `orchestrate_reviewer`. If Claude review is an explicit success criterion, pause at the single A/B/C decision instead; do not poll a baton or review file.
