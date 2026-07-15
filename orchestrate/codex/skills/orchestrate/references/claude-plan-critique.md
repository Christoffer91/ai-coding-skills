# Claude Plan Critique Gate

Use this only for a bounded, secret-free `FULL_SPEC` after outbound authorization is established. An explicit user invocation of `$orchestrate` supplies invocation-scoped `external_review_allowance: unused` for the workflow's single selected external review pass; implicit routing or a request without explicit `$orchestrate` still requires separate explicit approval. Internal `orchestrate_plan_critic` remains the default and the fallback when authorization, authentication, entitlement, or model verification is absent.

## Safe command

Follow [claude-cli-preflight.md](claude-cli-preflight.md) through the shared runner, including absolute binary resolution, authentication classification, outbound-data review, and the one-attempt direct Opus fallback. After `preflight`, print exactly its JSON `command` array as shell-escaped informational argv; it is the underlying Claude command, not the `run-review` wrapper or an approval gate. When standing authorization came from explicit `$orchestrate`, atomically change the allowance from `unused` to `consumed` immediately before invoking the shared runner with the known packet/output paths and `--approved-outbound` in the same turn. Refuse standing-authorized dispatch when the allowance is not `unused`; do not ask for a redundant second approval after the transition. For implicit routing, wait for separate explicit outbound approval before invoking it. Never hand-build or hand-parse the Claude call.

Any runner dispatch consumes the allowance regardless of success, failure, timeout, malformed or missing metadata, tool/data-policy rejection, or eligible Opus fallback. A failed preflight sends no packet and leaves it `unused`. After a standing-authorized plan critique dispatch, final external review requires separate explicit outbound approval or a new explicit `$orchestrate` invocation.

Do not enter this lane for `DRY_RUN` or an explicit internal-only/no-external request. Standing authorization covers only this selected review pass and does not approve another paid comparison, repository external action, or any other hard gate.

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

Send the review prompt and bounded plan through stdin; do not place plan content, repository excerpts, customer data, or secrets in process arguments. Never include `.env` values, credentials, private keys, raw logs, transcript bodies, or unreviewed repository content.

The resolved Claude Code CLI must support `--model fable`, `--fallback-model`, `--effort max`, `--safe-mode`, and `--no-session-persistence`. Do not use `dangerously-skip-permissions`, auto mode, tools, MCP servers, Chrome, plugins, or ultrareview for this gate.

## Model policy

- Primary request: the Claude Code `fable` alias. Its exact resolved model is unknown until result metadata verifies it; do not claim Fable 5 from the alias alone.
- Fallback request: the Claude Code `opus` alias when `fable` is strictly unavailable. One direct Opus call is allowed for structured 404/429 unavailability or the exact Fable-specific subscription-limit envelope before model execution. Generic usage or billing limits do not qualify. Its exact resolved family and version are unknown until result metadata verifies them; never assume the alias means Opus 4.8.
- Inspect the JSON result metadata when present. If the fallback resolves to a different family/version or cannot be verified, report that fact and use the internal critic instead of claiming an Opus 4.8 review.
- Do not invent or hard-code an unverified full model ID.

## Prompt contract

Ask Claude to follow the `critique` discipline: steelman the spec, identify only evidence-backed blockers or important gaps, name real tradeoffs, map each accepted concern to an exact plan change and verification check, and return `solid`, `solid-with-caveats`, `needs-rework`, or `stop-and-rethink`.

Claude does not approve execution. Codex validates the critique, records accepted/rejected findings in `Critique disposition`, reruns affected risk/coverage checks, and requests human approval when the plan materially changes.

If outbound data policy rejects the call before Claude starts, record `EXTERNAL_REVIEW_BLOCKED:data-policy` and follow [claude-cli-preflight.md](claude-cli-preflight.md) with zero Claude retries. Optional external critique falls back immediately to `orchestrate_plan_critic`. If Claude critique is an explicit success criterion, pause at the single A/B/C decision instead; do not poll a baton or review file.
