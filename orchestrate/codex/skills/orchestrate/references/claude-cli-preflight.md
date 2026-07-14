# Claude CLI Review Preflight

Use this contract for every approved Claude plan critique or final review. The review packet leaves the machine, but Claude receives no tools and cannot edit the repository.

The mandatory automated path is `python3 ~/.codex/skills/orchestrate/scripts/claude_review.py preflight`, followed after approval by `run-review --input <packet> --output <review> --approved-outbound`. Do not hand-build the subprocess or hand-parse Claude JSON; the shared runner is the single owner of binary resolution, authentication classification, timeout, output bounds, model evidence, and fallback counters.

## Outbound data-policy rejection

A local repository plan, diff, log excerpt, or review packet is private by default even when it contains no secrets. User approval is required but does not override an execution environment or tenant data-export policy.

If the tool layer rejects the command before Claude starts:

- Record `EXTERNAL_REVIEW_BLOCKED:data-policy`; this is policy evidence, not a Claude result.
- Use zero Claude retries. Do not repeat authentication checks, switch Fable/Opus, move or re-encode the packet, invoke another external transport, or otherwise work around the rejection.
- Do not relabel it as a Claude, authentication, Fable, or Opus failure.
- Do not poll for a local review output or baton file. A baton is a one-time handoff and resumes only after a new user message confirms completion.
- When external review was optional, run the corresponding internal `orchestrate_plan_critic` or `orchestrate_reviewer` immediately and label it accurately.
- When the user made Claude review an explicit success criterion, do not silently substitute another model. Create at most one local baton, pause the run, and request exactly one decision:

A. Accept the internal reviewer
B. Complete one local Claude baton
C. Pause or abort

The decision request must state that option B is manual, that Codex will not poll it, and that the user must explicitly resume after the output exists.

## Resolve one binary

Resolve the Claude Code CLI once and use the same absolute path for `--version`, `--help`, `auth status`, and the review call. Prefer an explicit `ORCH_CLAUDE_BIN`; otherwise prefer `~/.local/bin/claude`, then inspect `command -v claude` and known native install paths. Reject candidates that do not support `--safe-mode`, `--permission-mode`, `--tools`, `--no-session-persistence`, `--model`, `--fallback-model`, `--effort`, `--output-format`, and `--max-budget-usd`.

Do not run preflight with one PATH and execute with another. A shell alias, wrapper, or older Homebrew binary may expose a different flag surface.

## Confirm authentication

Run `<absolute-claude> auth status --json` locally and parse it as JSON. Report only `loggedIn`, `authMethod`, `apiProvider`, and `subscriptionType`; never print account identifiers or credentials.

Classify as `subscription` only when all are true:

- `loggedIn` is `true`;
- `authMethod` is `claude.ai`;
- `apiProvider` is `firstParty`;
- `subscriptionType` is non-empty;
- no API-key, bearer-token, Bedrock, Vertex, or Foundry environment setting can take precedence.

For verified subscription auth, omit `--max-budget-usd` by default. An explicit `ORCH_CLAUDE_MAX_BUDGET_USD` may still cap estimated usage. For API, cloud-provider, or unknown authenticated modes, include a positive cap, default `$2`. Block when authentication cannot be verified.

Subscription use is not unbounded: `claude -p` consumes the plan's monthly Agent SDK allowance. Keep the one-review, one-fallback, no-tool, and timeout limits even when no USD cap is present.

## Review command

Send the approved packet through stdin:

```bash
"$CLAUDE_BIN" -p \
  --safe-mode \
  --model fable \
  --fallback-model opus \
  --permission-mode plan \
  --tools "" \
  --no-session-persistence \
  --effort max \
  --output-format json \
  < "$REVIEW_PACKET"
```

For metered auth, add `--max-budget-usd 2`. Print the exact post-preflight command and obtain explicit approval before sending the packet.

## Result and fallback

Parse the JSON envelope even when the CLI exits nonzero. A model statement is not model evidence: inspect `modelUsage` before naming a resolved version. Treat `total_cost_usd` as estimated model cost, not proof of a billed charge.

`--fallback-model opus` covers overload behavior, not every subscription quota failure. The shared runner retries directly with `--model opus` exactly once only when Fable returns structured 404/429 unavailability or the exact Fable-specific subscription-limit envelope before any model starts. Generic usage, quota, billing, or entitlement prose is not retryable. The second call omits `--fallback-model` and is accepted only when `modelUsage` verifies the Opus family. Any second failure, malformed envelope, missing model metadata, auth change, or other error stops the external lane and returns to the internal critic/reviewer.

Classify outbound content as public, anonymized, or private before approval. Prefer an architecture-only anonymized packet. Never send secrets, customer data, raw transcripts, full logs, hidden reasoning, or repository content outside the approved review working set.
