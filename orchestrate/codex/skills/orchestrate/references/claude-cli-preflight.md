# Claude CLI Review Preflight

Use this contract for every authorized Claude plan critique or final review. The review packet leaves
the machine, but Claude receives no tools and cannot edit the repository.

The mandatory path is:

```bash
python3 ~/.codex/skills/orchestrate/scripts/claude_review.py preflight --review-tier <important|security|exceptional>
python3 ~/.codex/skills/orchestrate/scripts/claude_review.py run-review \
  --review-tier <important|security|exceptional> \
  --input "$REVIEW_PACKET" --output "$REVIEW_OUTPUT" --approved-outbound
```

Do not hand-build the subprocess or hand-parse Claude JSON. The shared runner owns binary resolution,
authentication classification, safe flags, timeout, structured output, result bounds, model evidence,
error classification, and the exceptional Fable fallback.

## Authorization And Deduplication

Explicit `$orchestrate` grants the bounded goal policy in [review-policy.md](review-policy.md). Before
dispatch, require an eligible review tier, remaining goal budget, an `unused` per-PR allowance, and no
receipt for `<repo identity>|<PR number>|<head SHA>|<policy version>`. Then atomically consume the allowance
and increment the budget immediately before `run-review`. Invoke it in the same turn; do not ask for a
redundant approval.

Run preflight first. Its `command` field must be an array of strings. Print those exact elements, in
order and shell-escaped, as informational underlying Claude argv. It is not the shared `run-review` wrapper,
must not be executed directly, and is not another approval gate.

A failed preflight sends no packet and leaves the allowance unused. Any dispatch attempt consumes it,
including provider failure, timeout, malformed output, missing model metadata, data-policy rejection,
or exceptional fallback. Implicit pipeline routing has no standing outbound authorization. `DRY_RUN`,
internal-only, and no-external instructions override all standing authorization.

## Resolve One Binary

Resolve the CLI once and use the same absolute path for `--help`, auth status, preflight, and review.
Prefer `ORCH_CLAUDE_BIN`, then `~/.local/bin/claude`, `command -v claude`, and known native install
paths. Require `--safe-mode`, `--permission-mode`, `--tools`, `--no-session-persistence`, `--model`,
`--fallback-model`, `--effort`, `--output-format`, `--json-schema`, and `--max-budget-usd`.

Do not use `--bare` with subscription auth: current Claude CLI bare mode deliberately skips Keychain
and OAuth. Do not run preflight with one PATH and execute with another.

## Keychain-Aware Authentication

On macOS, a sandboxed `loggedIn=false` is not authoritative because subscription credentials may be
in macOS Keychain. Run the local-only preflight once with `sandbox_permissions=require_escalated`
before classifying auth. It sends no review packet and reports no account identifier.

Do not start `claude auth login` after only a sandboxed false negative. Ask the user to authenticate
only if the same native binary fails in the normal user context. Never read or expose credentials.

Classify `subscription` only when auth JSON has `loggedIn=true`, `authMethod=claude.ai`,
`apiProvider=firstParty`, a non-empty `subscriptionType`, and no API-key, bearer-token, Bedrock,
Vertex, or Foundry environment override. Subscription calls omit a USD cap by default but still
consume plan quota. Metered or provider auth uses a positive cap, default `$2`.

## Review Tiers And Command

- `important`: `--model sonnet`; no direct retry.
- `security`: `--model opus`; no direct retry.
- `exceptional`: `--model fable --fallback-model opus`; one direct Opus attempt only when the Fable
  envelope proves model-specific unavailability before a model starts.

Every tier also uses `--safe-mode`, `--permission-mode plan`, `--tools ""`,
`--no-session-persistence`, `--effort max`, `--output-format json`, and the runner-owned
`--json-schema`. The live CLI has no `--max-turns` flag, so do not invent it; no-tools print mode and a
single stdin packet bound the call.

The schema requires `PASS|CHANGES_REQUIRED`, a summary, and up to 20 findings with severity, file,
optional line, rationale, and recommendation. Missing or invalid `structured_output` is a failed
review, not text to salvage.

## Failure Disposition

Use only bounded, content-free classes: `preflight-auth`, `model-specific-quota`, `global-quota`,
`model-unavailable`, `timeout`, `malformed-output`, `data-policy`, `command-start`, or `model-error`.
Do not print raw stderr, prompts, output, account data, or logs.

- Zero retry: global quota, timeout/stall, malformed output, data policy, auth failure, and generic
  provider errors.
- One retry: only the exceptional Fable-specific fallback above.
- Optional external lane: immediately use the corresponding internal critic/reviewer and label it.
- Required external lane: pause once and request a concrete decision. Do not poll a baton or output.

If the execution environment rejects outbound data, keep the consumed allowance, record
`EXTERNAL_REVIEW_BLOCKED:data-policy`, and use zero Claude retries. Do not switch transports or
re-encode the packet to bypass policy. Do not relabel it as a Claude authentication or model failure.

Decision options for a required lane:

A. Accept the internal reviewer
B. Complete one local Claude baton
C. Pause or abort

## Data Boundary

Classify the packet as public, anonymized, or private. Send only the smallest approved diff and
context. Never send secrets, customer data, raw transcripts, full logs, hidden reasoning, unrelated
repository content, or machine/account identifiers. Standing review authorization never grants push,
PR creation, merge, deploy, install, migration, destructive action, or tenant/live access.
