# Shared Run Status for Codex-Primary Runs

Use this protocol from the Codex conductor and from `pipeline` intake (step B.8). Emit for any
non-trivial run: every `EXECUTE`, and any `PLAN_ONLY` above `FAST`. `DIRECT` and a bare `FAST` plan need
not emit, but a `FAST` `EXECUTE` that mutates files still should, so the goal is visible while it runs.
Status is observational: a missing or broken emitter must never fail, approve, reject, or otherwise change
the run. Emit at run start, not only when a pipeline routes into `orchestrate`.

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

## Optional Codex rollout liveness (strict binding only)

The dashboard can consume an isolated Codex liveness lease, but it is **not** a substitute for
explicit `step`, `handoff`, `fail`, or `done` emissions. Use it only when this host exposes both:

1. the absolute rollout JSONL path for this exact session; and
2. the active Codex `turn_id` when this goal is bound.

Never discover a "latest" rollout or infer completion from `task_complete` / turn markers. If
either value is unavailable, record `codex sidecar: NOT_BOUND`
in the local report and **SKIP silently**. The Phase 1 `quiet` state is intentional in that case.

When both values are available at intake, include them in the initial start emission:

```bash
orch_emit start --id "$RUN_ID" --repo "$REPO" --topic "$TOPIC" \
  --title "$TITLE" --branch "$BRANCH" \
  --codex-session "$ROLLOUT" --codex-turn "$TURN_ID"
```

`orchestrate-status` stores only opaque hashes and a fresh run generation — never the rollout path
or raw turn id. The binding is immutable: a later `step` may repeat the exact pair for verification,
but cannot replace it. Resolve the optional sidecar like the emitter and launch it only after that
successful binding:

```bash
if command -v orchestrate-codex-sidecar >/dev/null 2>&1; then
  ORCH_SIDECAR="$(command -v orchestrate-codex-sidecar)"
elif [ -x "$HOME/.claude/skills/orchestrate/dashboard/orchestrate-codex-sidecar" ]; then
  ORCH_SIDECAR="$HOME/.claude/skills/orchestrate/dashboard/orchestrate-codex-sidecar"
else
  ORCH_SIDECAR=""
fi
[ -z "$ORCH_SIDECAR" ] || nohup "$ORCH_SIDECAR" --id "$RUN_ID" --session "$ROLLOUT" --turn "$TURN_ID" \
  >/dev/null 2>&1 &
```

The sidecar reads bounded new JSONL bytes from EOF and writes a separate generation-bound lease.
The initial turn remains immutable binding metadata, while every recognized event in that bound
session counts as activity across later turns, including turnless `response_item` events. It never
calls `heartbeat`, edits run JSON, changes a step, or emits a terminal status. It exits on idle,
SIGTERM, an inactive/removed/rebound run, or a missing/replaced/truncated rollout; a duplicate
instance exits without taking over. `await`, `handoff`, `paused`, `rejected`,
`failed`, and `done` are authoritative inactive states. This is optional, best-effort telemetry —
not proof of semantic completion.

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

An inactive run never resumes through an incidental `step`. After a new user message explicitly
resumes a `paused` run or accepts a `handoff`, emit the lifecycle transition first:

```bash
orchestrate-status resume --id "$RUN_ID" --reason "explicit user resume"
```

This preserves PR/review metadata, rotates the liveness generation, and clears stale
`needsRestart`/watchdog evidence. `await`, `done`, `failed`, and `rejected` cannot be resumed this
way. Answer an `await` gate through its recorded option; create a fresh run after a terminal result.

For recoverable `needs-rework`, `ESCALATE/BLOCKED`, or no-progress stops, keep the run non-terminal: emit the current step as `pending` with a short reason and then `pause`. Reserve `fail --id "$RUN_ID"` for an actual terminal failure. On successful local completion use `done --id "$RUN_ID"`; a `PR_READY` review handoff uses the handoff sequence below instead.

## Timeouts and lifecycle closure

A tool or agent timeout is not proof of terminal failure and must not leave a run in `running`.
Capture the bounded failure evidence, diagnose it, and continue only when the next legal action can
start immediately. Otherwise update the resume command, return the active step to `pending` with a
short factual note, and emit `pause`. Do not relabel a timeout as progress or keep retrying merely to
refresh the dashboard.

Before returning control to the user, close every successfully started status run with exactly one
honest lifecycle outcome: `pause` for resumable blocked or timed-out work, `handoff` for a registered
review baton, `done` for completed work, `fail` for terminal failure, or `cancel` for an explicit
abort/rejection. A final response is not a lifecycle outcome; never leave the record in `running`,
`review`, or a partially active step after the work has stopped. Emitter failure remains non-fatal to
the underlying task, but record `shared status: EMIT_FAILED` in the local report.

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

Automatic goal continuation is not user input. After emitting the terminal question, do not poll
the PR, gate, answer file, or external review output; do not repeat the same question in automatic
continuation turns; and do not count those turns as failed human responses. Preserve `await` or
`paused`, return control once, and resume only after a new user message or a valid bounded dashboard
answer supplies the decision.

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
