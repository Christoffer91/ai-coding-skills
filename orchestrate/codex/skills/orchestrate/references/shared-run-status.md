# Shared Run Status for Codex-Primary Runs

Use this protocol from the Codex conductor for `STANDARD` and `DEEP` runs. `FAST` and `DIRECT` do not emit. Status is observational: a missing or broken emitter must never fail, approve, reject, or otherwise change the orchestration run.

When the emitter is absent (skill-only install), tell the user ONCE — in the first status line of
the first run only — that an optional live dashboard layer exists (the orchestrate package's
`install.sh` / README "What do you actually need?"), then proceed without it. Never re-mention it
after a decline.

## Resolve once, fail open

Resolve the emitter at run start:

```bash
if command -v orchestrate-status >/dev/null 2>&1; then
  ORCH_STATUS="$(command -v orchestrate-status)"
elif [ -x "$HOME/.claude/skills/orchestrate/dashboard/orchestrate-status" ]; then
  ORCH_STATUS="$HOME/.claude/skills/orchestrate/dashboard/orchestrate-status"
else
  ORCH_STATUS=""
fi
```

If neither path exists, record `shared status: NOT_AVAILABLE` in the conductor's local report and **SKIP silently** at the command boundary. Do not print an emitter error. Wrap ordinary emissions so a non-zero exit is non-fatal, for example:

```bash
orch_emit() {
  [ -n "${ORCH_STATUS:-}" ] || return 0
  "$ORCH_STATUS" "$@" >/dev/null 2>&1 || true
}
```

Do not send secrets, credentials, customer data, raw logs, or transcript content in status arguments.

## Register a unique run

Build a filesystem-safe ID from the repository, topic, branch slug, UTC timestamp, and conductor PID:

```text
<repo>-<topic>-<branch-slug>-<YYYYMMDDTHHMMSSZ>-<pid>
```

The branch, timestamp, and PID are required; `<repo>-<topic>` alone can collide across worktrees and concurrent runs. Keep the resulting ID as the canonical run ID for every later emission.

On `STANDARD` or `DEEP` start:

```bash
RESUME_COMMAND="\$pipeline resume $TOPIC"
orch_emit start --id "$RUN_ID" --repo "$REPO" --topic "$TOPIC" \
  --title "$TITLE" --branch "$BRANCH" --planner "Sol Ultra" \
  --executor "Terra · medium" --cwd "$PWD" \
  --resume-command "$RESUME_COMMAND"
```

`RESUME_COMMAND` is a secret-free, single-line command or prompt that an operator
can copy to resume this exact run; the dashboard never executes it. It is limited
to 1000 characters and must not contain control characters. Update or clear it
when the continuation changes:

```bash
orch_emit resume-command --id "$RUN_ID" --command "$RESUME_COMMAND"
orch_emit resume-command --id "$RUN_ID" --clear
```

## Seven-step relay

Emit both state and actor so Codex-primary runs do not inherit Claude-centric defaults. Mark a step `active` before work and `done` only after its evidence is recorded.

| Step | Work | Actor | Notes |
|---|---|---|---|
| 1 | Planner `FULL_SPEC` | `Sol Ultra` | STANDARD/DEEP only |
| 2 | Plan critique | `Sol high` | Internal critic or the verified external actor |
| 3 | Executor `EXECUTE` states | `Terra · medium` | `--note` is the current smallest approved step |
| 4 | PR packaging | `Codex` | Use `PR_READY`; otherwise leave pending |
| 5 | Fresh final review | `Sol Ultra` | Use the verified external actor when that lane is approved |
| 6 | Review-fix rounds | `Terra · medium` | At most three rounds |
| 7 | Gated end | `gated` | Completion, handoff, rejection, or terminal failure |

Example transition:

```bash
orch_emit step --id "$RUN_ID" --n 3 --state active \
  --actor "Terra · medium" --note "$SMALLEST_STEP"
orch_emit step --id "$RUN_ID" --n 3 --state done --actor "Terra · medium"
```

For recoverable `needs-rework`, `ESCALATE/BLOCKED`, or no-progress stops, keep the run non-terminal: emit the current step as `pending` with a short reason and then `pause`. Reserve `fail --id "$RUN_ID"` for an actual terminal failure. On successful local completion use `done --id "$RUN_ID"`; a `PR_READY` review handoff uses the handoff sequence below instead.

## Best-effort token metrics

When the conductor can see an integer token count reported for a managed Codex
agent, emit it under `tokens.codex.<agent>` and update the conductor-local running
total under `tokens.total`:

```bash
orch_emit metric --id "$RUN_ID" --key "tokens.codex.$AGENT" --value "$AGENT_TOKENS"
orch_emit metric --id "$RUN_ID" --key tokens.total --value "$TOKENS_TOTAL"
```

Use stable agent names such as `planner`, `critic`, `executor`, and `reviewer`.
If usage is unavailable or is not an integer, skip silently; token telemetry must
never fail or change the orchestration run.

## Human gates

For a human gate in `SUPERVISED` or `DEEP`, keep the normal terminal approval request and additionally emit:

```bash
orch_emit gate --id "$RUN_ID" --question "$GATE_QUESTION" \
  --option "Approve:primary" --option "Reject"
```

If the emitter is available, poll it once with a bounded timeout. `wait` is the exception to the fire-and-forget wrapper because its stdout is the decision:

```bash
if DASHBOARD_CHOICE=$("$ORCH_STATUS" wait --id "$RUN_ID" --timeout "$GATE_TIMEOUT" 2>/dev/null); then
  # Accept only the exact emitted labels: Approve or Reject.
  :
else
  # Timeout or emitter failure: keep the terminal gate; never auto-approve.
  DASHBOARD_CHOICE=""
fi
```

The dashboard window and terminal decision are sequential, not concurrent: while the bounded `wait` is active, a valid dashboard answer is the decision. After timeout, do not call `wait` again for that gate; use the terminal decision and ignore any late dashboard answer. The next `gate` call clears stale answer data. `handoff`, `cancel`, `fail`, and `done` clear the displayed gate when they become the next terminal state.

The dashboard binds to localhost and is not itself phone-accessible. Gate notifications reach a phone only when `ORCH_NOTIFY_CMD` or repo-local `notify_cmd` is configured to use a phone-capable hook; the macOS Notification Center fallback is desktop-only.

## PR review handoff

After a `PR_READY` PR exists, write `$PWD/HANDOFF-CLAUDE-review-<topic>.md`. It must include the topic, run ID, PR number and URL, head branch, base branch, exact implementation session ID, `/orchestrate review <topic>` command, and focused items to scrutinize. Verify that the baton path is absolute and readable, then emit:

```bash
orch_emit pr --id "$RUN_ID" --number "$PR_NUMBER" --url "$PR_URL"
orch_emit metric --id "$RUN_ID" --key session --value "$IMPLEMENTATION_SESSION_ID"
orch_emit handoff --id "$RUN_ID" \
  --baton "$PWD/HANDOFF-CLAUDE-review-$TOPIC.md" \
  --review-command "/orchestrate review $TOPIC"
```

The metric key is exactly `session`; Claude review entry validates that key together with `status=handoff`, PR metadata, and the readable absolute baton path.
