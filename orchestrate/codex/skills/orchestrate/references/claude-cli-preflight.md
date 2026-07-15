# Claude CLI Review Preflight

Use this contract for every authorized Claude plan critique or final review. The review packet leaves the machine, but Claude receives no tools and cannot edit the repository.

The mandatory automated path is `python3 ~/.codex/skills/orchestrate/scripts/claude_review.py preflight`, followed after standing or separate outbound authorization by `run-review --input <packet> --output <review> --approved-outbound`. Do not hand-build the subprocess or hand-parse Claude JSON; the shared runner is the single owner of binary resolution, authentication classification, timeout, output bounds, model evidence, and fallback counters.

## Authorization source and same-turn execution

An explicit user invocation of `$orchestrate` initializes invocation-scoped canonical state `external_review_allowance: unused`; `unused|consumed` are the only valid states. This is standing outbound authorization for one selected bounded, secret-free plan critique or final review.

Run the local Keychain-aware preflight and parse its JSON result. Require `command` to be an array of strings. Render exactly those elements, without adding, removing, or reordering argv, using shell escaping, and print the rendered argv as an informational progress update. The `command` array is the resolved underlying Claude CLI invocation; it is not the shared `run-review` wrapper, must not be executed directly, and printing it is not an approval gate.

Immediately before invoking `python3 ~/.codex/skills/orchestrate/scripts/claude_review.py run-review --input <packet> --output <review> --approved-outbound` under standing authorization, atomically compare and set the canonical allowance from `unused` to `consumed`. Refuse standing-authorized dispatch unless the compare-and-set succeeds. Then invoke the shared runner with the known packet/output paths in the same turn; do not request a redundant second approval.

The allowance remains `consumed` after every runner dispatch attempt, including Claude success or failure, timeout, malformed output, missing model metadata, tool/data-policy rejection, and the one eligible direct Opus fallback. Fable plus that fallback is one runner pass and consumes only the already-consumed allowance. A later external plan critique or final review requires separate explicit outbound approval, or a new explicit `$orchestrate` invocation that creates a new `unused` allowance.

If local preflight fails before runner dispatch, no review packet or repository data is sent. Record `EXTERNAL_REVIEW_BLOCKED:preflight`; the failure leaves the allowance `unused`. Use the matching internal reviewer unless external Claude review is an explicit success criterion; in that case request one decision using the same optional-versus-required disposition below.

Implicit `pipeline` routing and requests that did not explicitly invoke `$orchestrate` have no standing authorization. Preflight may run because it sends no packet; after printing the preflight `command` argv, request explicit outbound approval before `run-review`.

`DRY_RUN` and explicit internal-only or no-external instructions override standing authorization. Standing authorization does not cover extra or comparative paid calls, secrets, customer data, raw transcripts, policy bypass, push, PR creation, merge, deploy, install, migration, destructive action, tenant/live calls, or any other hard gate. Subscription/metered handling, the default `$2` metered cap, the one eligible direct Opus fallback, and zero retries after data-policy rejection remain unchanged.

## Outbound data-policy rejection

A local repository plan, diff, log excerpt, or review packet is private by default even when it contains no secrets. Standing or separate user authorization is required but does not override an execution environment or tenant data-export policy.

If the tool layer rejects the command before Claude starts:

- Treat the runner dispatch as attempted and keep `external_review_allowance: consumed` when standing authorization was used, even if the tool layer sent no packet.
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

## Keychain-aware execution context

On macOS, Claude Code subscription credentials may be stored in macOS Keychain. A sandboxed
`loggedIn=false` result is not authoritative because the same native binary can be authenticated in
the normal user execution context while Keychain access is denied inside the sandbox.

Run the local-only preflight through the trusted canonical runner with `sandbox_permissions` set to
`require_escalated`. Preflight sends no review packet and invokes only CLI help plus sanitized auth
status. If an earlier sandboxed preflight reported unauthenticated, rerun this exact preflight once
outside the sandbox before classifying auth or asking the user to intervene. Use the same resolved
absolute binary for `run-review` after outbound approval.

Do not start `claude auth login` from a sandboxed false negative. Only after the Keychain-aware
preflight also reports unauthenticated may the user be asked to complete the interactive login; Codex
must never enter, read, or expose credentials.

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

For metered auth, add `--max-budget-usd 2`. Print the preflight JSON `command` array exactly as shell-escaped argv; do not label it a `run-review` command. After the required atomic allowance transition, invoke the shared runner immediately when explicit `$orchestrate` standing authorization applies; otherwise obtain explicit outbound approval before runner dispatch.

## Result and fallback

Parse the JSON envelope even when the CLI exits nonzero. A model statement is not model evidence: inspect `modelUsage` before naming a resolved version. Treat `total_cost_usd` as estimated model cost, not proof of a billed charge.

`--fallback-model opus` covers overload behavior, not every subscription quota failure. The shared runner retries directly with `--model opus` exactly once only when Fable returns structured 404/429 unavailability or the exact Fable-specific subscription-limit envelope before any model starts. Generic usage, quota, billing, or entitlement prose is not retryable. The second call omits `--fallback-model` and is accepted only when `modelUsage` verifies the Opus family. It remains inside the already-consumed review pass and requires no new allowance. Any timeout, second failure, malformed envelope, missing model metadata, auth change, or other error stops the external lane, leaves the allowance consumed, and returns to the internal critic/reviewer.

Classify outbound content as public, anonymized, or private before approval. Prefer an architecture-only anonymized packet. Never send secrets, customer data, raw transcripts, full logs, hidden reasoning, or repository content outside the approved review working set.
