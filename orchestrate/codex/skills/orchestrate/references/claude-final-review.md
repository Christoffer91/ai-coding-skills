# Claude Final Review Gate

Use this only for a bounded, secret-free final review after explicit approval for an external/paid Claude Code call. Internal `orchestrate_reviewer` remains the default and the fallback when approval, authentication, entitlement, input bounds, or model verification is absent.

## Precedence

For one review pass, the approved external lane replaces the internal reviewer; it is not an automatic second opinion. Running both reviewers for comparison is an additional paid call and requires separate explicit approval. Any later material diff requires a fresh review decision and fresh inputs.

## Safe command

Follow [claude-cli-preflight.md](claude-cli-preflight.md) through the shared runner, including absolute binary resolution, authentication classification, outbound-data review, and the one-attempt direct Opus fallback. After `preflight`, print the exact command and wait for explicit approval before invoking `run-review`; never hand-build or hand-parse the Claude call.

```bash
"$CLAUDE_BIN" -p \
  --safe-mode \
  --permission-mode plan \
  --tools "" \
  --no-session-persistence \
  --model fable \
  --fallback-model opus \
  --effort max \
  --output-format json
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

- Primary request: the Claude Code `fable` alias. Its exact resolved model is unknown until result metadata verifies it; do not claim Fable 5 from the alias alone.
- Fallback request: the Claude Code `opus` alias when `fable` is strictly unavailable. One direct Opus call is allowed for structured 404/429 unavailability or the exact Fable-specific subscription-limit envelope before model execution. Generic usage or billing limits do not qualify. Its exact resolved family and version are unknown until result metadata verifies them; never assume the alias means Opus 4.8.
- Inspect the JSON result metadata when present. If the resolved model cannot be verified, report that fact and rerun the pass with the internal reviewer.
- Authentication, entitlement, command, timeout, malformed-output, or metadata-verification failure is non-fatal to orchestration: the internal `orchestrate_reviewer` is the fallback.
- Do not invent or hard-code an unverified full model ID.

## Prompt and verdict contract

Ask Claude to review only against the approved spec and fresh evidence. It must categorize findings as `blocking`, `notable`, or `nit`, cite the affected file/behavior, explain the concrete failure mode, and return an overall `PASS` or `CHANGES_REQUIRED` verdict.

Codex validates the findings before workflow step 10. Only validated blocking findings return to the executor; notable and nit findings remain recorded evidence unless they expose a spec or risk change. Claude does not approve execution, merging, or deployment.

If outbound data policy rejects the call before Claude starts, record `EXTERNAL_REVIEW_BLOCKED:data-policy` and follow [claude-cli-preflight.md](claude-cli-preflight.md) with zero Claude retries. Optional external review falls back immediately to `orchestrate_reviewer`. If Claude review is an explicit success criterion, pause at the single A/B/C decision instead; do not poll a baton or review file.
