# Claude Plan Critique Gate

Use this only for a bounded, secret-free `FULL_SPEC` after explicit approval for an external/paid Claude Code call. Internal `orchestrate_plan_critic` remains the default and the fallback when approval, authentication, entitlement, or model verification is absent.

## Safe command

Print this exact command and wait for explicit approval before running it:

```bash
claude -p \
  --safe-mode \
  --permission-mode plan \
  --tools "" \
  --no-session-persistence \
  --model fable \
  --fallback-model opus \
  --effort max \
  --max-budget-usd 2 \
  --output-format json
```

Send the review prompt and bounded plan through stdin; do not place plan content, repository excerpts, customer data, or secrets in process arguments. Never include `.env` values, credentials, private keys, raw logs, transcript bodies, or unreviewed repository content.

The installed Claude Code CLI must support `--model fable`, `--fallback-model`, `--effort max`, `--safe-mode`, and `--no-session-persistence`. Do not use `dangerously-skip-permissions`, auto mode, tools, MCP servers, Chrome, plugins, or ultrareview for this gate.

## Model policy

- Primary request: the Claude Code `fable` alias. Its exact resolved model is unknown until result metadata verifies it; do not claim Fable 5 from the alias alone.
- Fallback request: the Claude Code `opus` alias when `fable` is unavailable. Its exact resolved family and version are unknown until result metadata verifies them; never assume the alias means Opus 4.8.
- Inspect the JSON result metadata when present. If the fallback resolves to a different family/version or cannot be verified, report that fact and use the internal critic instead of claiming an Opus 4.8 review.
- Do not invent or hard-code an unverified full model ID.

## Prompt contract

Ask Claude to follow the `critique` discipline: steelman the spec, identify only evidence-backed blockers or important gaps, name real tradeoffs, map each accepted concern to an exact plan change and verification check, and return `solid`, `solid-with-caveats`, `needs-rework`, or `stop-and-rethink`.

Claude does not approve execution. Codex validates the critique, records accepted/rejected findings in `Critique disposition`, reruns affected risk/coverage checks, and requests human approval when the plan materially changes.
