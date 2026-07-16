---
name: chief-of-staff
description: "Use when one chat should orchestrate a whole work session: decompose a broad goal into parallel workstreams, delegate to background subagents, track everything on the live dashboard, re-command workers mid-flight, and synthesize one answer. For multi-part or multi-repo work that would otherwise become serial rabbit-holing. Not for a single narrow task (just do it), not for shipping implementation (route to /orchestrate or /pipeline), and NOT a persistent cross-session conductor. Keywords: chief of staff, orchestrate everything, fan out, delegate, parallel workstreams, styr alt, deleger."
allowed-tools: Read, Glob, Grep, Bash, Agent, TaskCreate, TaskUpdate
---

# Chief of Staff — one chat runs the whole session

## Purpose
Turn this chat into the session's chief of staff: it decomposes the goal, delegates workstreams to
parallel background subagents, keeps live status on the dashboard, redirects workers as findings land,
and delivers ONE synthesized result. You talk to one brain; the brain runs the staff.

## Hard boundary — what this is NOT
Claude Code cannot create new top-level chats or command other human chat sessions (verified against
Anthropic docs). This skill orchestrates **within the current session**: subagents are ephemeral
workers that live and die with this chat. A *persistent* cross-session conductor is a separate,
deliberately deferred design (`PLAN-chief-of-staff.md` in dotfiles) — do not scope-creep into it here.

## When to use
- A broad goal with 2+ independent workstreams (audit these three repos; research X while fixing Y;
  triage everything on the board).
- Multi-repo or multi-domain work that would otherwise be done serially.
- The user says "styr alt", "ta det derfra", or hands over a messy pile.

## When NOT to use
- One narrow task — just do it (no council theater).
- Non-trivial implementation that should ship — route to `/orchestrate` (dual-brain loop) via
  `/pipeline`'s coverage matrix; this skill may *host* that routing but never replaces the loop.
- Work that needs a standing agent across sessions/nights — that's the deferred external conductor.

## Steps

### 1. Intake and decompose
1. Restate the goal in one line; list workstreams with an owner-shape each (recon / research /
   analysis / implementation-route). 2–5 workstreams is the sweet spot; cap 6.
2. Mark each workstream READ-ONLY (default) or WRITE. Write-work never runs as a parallel subagent
   against shared files — route it to `/orchestrate` (worktree isolation) or do it in-session after
   the reads land.
3. Track with TaskCreate/TaskUpdate so progress is visible in-chat too.

### 2. Dashboard telemetry (emit discipline)
Bootstrap per the orchestrate skill's precondition 6, then register the session:
```bash
ID="$(basename "$PWD")-cos-<slug>-$(date -u +%Y%m%dT%H%M%SZ)"   # FRESH id per session
LOG=~/.orchestrate/artifacts/$ID/run.log; mkdir -p "$(dirname "$LOG")"
orchestrate-status start --id "$ID" --repo <repo> --topic cos-<slug> \
  --title "<same name as this chat>" --branch main --planner "Claude (chief-of-staff)" \
  --executor "subagents" --log "$LOG"
```
Map workstreams onto step notes (`step --n 1 --state active --note "recon: <ws>"`), update at real
transitions, and ALWAYS end with `orchestrate-status done --id "$ID"` (or `fail`) — the full emit
discipline (fresh id, own log, terminal emit) applies.

### 3. Fan out — one message, parallel, background
- Dispatch ALL independent subagents in a single message so they run concurrently.
- Each brief is self-contained and bounded: goal, exact scope (paths/repos), what to return
  ("ranked findings + file:line pointers, ≤300 words, no file dumps"), and READ-ONLY unless
  explicitly write-tasked. Name agents (`name:` param) so they are addressable later.
- Agent types: `Explore` for repo recon; `general-purpose` for research/web/multi-step; a
  `codex exec -s read-only` leg (via Bash, stdin-redirected) when an independent second-model lens
  is worth it. Match effort to the workstream — cheap for recon, strong for judgment.
- Default 3–4 concurrent workers; more only when the workstreams are genuinely independent.

### 4. Monitor and re-command
- Completions arrive as notifications; fold each into the picture and update TaskUpdate + step notes.
- Course-correct a running/completed worker with `SendMessage` (by name) instead of spawning a new
  one — workers treat your messages as task direction.
- A worker that comes back thin: sharpen the brief and re-send once; after that, do it yourself or
  drop the workstream (say so).
- Long legs: wrap backgrounded processes with the heartbeat loop from the orchestrate emit
  discipline so the card stays live.

### 5. Route, don't absorb
- Findings that become non-trivial implementation → spec per the orchestrate template, then
  `/orchestrate` (its run appears on the dashboard beside this one).
- Security/risk/architecture judgment calls → the dedicated skills (`/risk-assess`,
  `/security-audit`, `/architecture-review`, `/critique`), not an overloaded worker brief.

### 6. Synthesize and close
- ONE report: per-workstream outcome, cross-cutting findings, what was routed onward (with run/PR
  links), what was dropped and why. Never paste raw worker output as the answer.
- Terminal emit (`done`/`fail`), TaskUpdate everything closed, and an Asks block with the decisions
  that belong to the user.

## Guardrails
- Read-only fan-out by default; parallel writes only in isolated worktrees via `/orchestrate`.
- No council theater: if one careful pass settles it, skip the staff.
- Token discipline: bounded briefs and answers; count workers in the final report; prefer
  falsifying a hypothesis in-session over spawning another worker.
- The dashboard is a projection of this session — never hand-edit run JSON to look better.
- Respect the hard boundary: never claim to be running other chats or promise cross-session
  persistence this skill does not have.

## Output Format
```
## Chief-of-Staff Report
- Goal: ...
- Workstreams: N dispatched (N read-only, N routed to /orchestrate)
- Findings: [per workstream, one line each + pointers]
- Routed onward: [runs/PRs opened]
- Dropped: [what + why]
- Workers used: N subagents, M codex legs
- Asks: ...
```

## Related Skills
- `/orchestrate` — shipping loop for implementation this skill routes out
- `/pipeline` — coverage matrix when a workstream is a full change
- `/critique` — pressure-test a decision before committing a workstream to it
- `/debug` — council-mode debugging when a workstream is a hard bug
