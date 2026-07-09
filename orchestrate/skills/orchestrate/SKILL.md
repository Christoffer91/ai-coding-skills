---
name: orchestrate
description: "Run the dual-brain plan→execute→review→ship loop end-to-end: Fable/Claude plans and reviews PRs, Codex/gpt-5.6-sol critiques the plan, codes, opens the PR, and applies review edits. Use when asked to take a change from idea to merged/deployed autonomously, to 'ship it end-to-end', 'run the loop', 'hand this to Codex and drive it', or for a full autonomous agent-driven PR. Default hands-off; pass --supervised to gate each step. Not for trivial one-file edits (just do it) or plan-only work (stay in plan mode). Keywords: orchestrate, ship it, dual-brain, plan execute review loop, autonomous PR, hand to codex, relay."
allowed-tools: Read, Glob, Grep, Edit, Write, Bash
---

# Orchestrate — dual-brain shipping loop

## Purpose
Drive a change from plan to (optionally) deployed across two models, per the `## Model roles & orchestration` contract in `~/.claude/CLAUDE.md`:
**Claude (Fable 5 · medium / Opus 4.8 fallback)** plans + reviews PRs; **Codex / gpt-5.6-sol** critiques the plan, writes the code, opens the PR, and applies review edits. This skill is the conductor — it composes existing skills (`codex`, `handover`, `code-review`, `prepare-pr`, `verify`, `risk-assess`, `continuity`) plus raw `codex`/`gh`/`git`. It does not reimplement them.

## Modes
- **Hands-off (default):** run steps 2–6 without stopping; step 7 auto-deploys low-risk changes and stops for risky ones. This is the default because the user opted into full autonomy.
- **`--supervised`:** stop for the user at each handoff (plan-approval, execute, PR-review, edits, deploy). Use when the task is ambiguous, security-sensitive, or on a first run in a new repo.
- **`--dry-run`:** print the exact `codex`/`gh`/`git` commands the loop would run, execute nothing.

## Approvals, notifications & remote control
Make the loop drivable from the user's phone so a gate doesn't stall at a terminal they've walked away from.

- **Notify at every gate.** On each supervised handoff (plan-approval, execute, PR-review, edits, deploy) and on completion/failure of a long Codex run, call **`PushNotification`** with a one-line, actionable message. When the user has **Remote Control** connected (they pair their phone via the Claude app — *you cannot invoke it; there is no `/remote-control` skill*), the push reaches their phone. One push per real decision, not per step.
- **Ask with clickable approvals.** Present the decision as an interactive widget via **`mcp__visualize__show_widget`** (call `read_me` with `elicitation`/`interactive` first): Approve / Reject / Edit buttons wired to the global **`sendPrompt(text)`**, which sends the choice back to chat as if typed. Fall back to **`AskUserQuestion`** when a widget is overkill. A published **Artifact is read-only** — its CSP blocks any callback, so never rely on Artifact buttons for approval; use it only as an at-a-glance status board (phone-viewable via its URL).
- **Codex requests, never self-grants.** In the handoff, instruct Codex: for ANY gated action — package install, `git push`, network egress, tenant/live API call, migration, deploy — **stop and emit `⛔ APPROVAL-REQUEST: <action> — <why>`** in its output, and do not do it. Under `-s workspace-write` Codex has no network, so it *cannot* silently cross these gates. Claude scans the Codex output in-session and turns a request into a notification/approval decision. Driver-side marker scanning is future work.
- **Standing gates (always explicit approval):** installs, first `git push`/PR-open, anything touching a real tenant/production, secrets, deploy. Code + local mocked tests inside the sandbox need no gate.

## Preconditions (check first, once)
1. In a git repo with a clean-enough tree (stash or note pre-existing WIP). `git rev-parse --show-toplevel`.
2. `codex --version` ok and logged in; `gh auth status` ok. If either is missing, surface the setup message and stop (see `codex` skill). **Always run `codex exec … </dev/null`** (close stdin) — without it `codex exec` can block on *"Reading additional input from stdin…"* and hang indefinitely, worst of all when backgrounded (a silent multi-hour zombie). Codex spawns MCP servers on startup; a hung run leaves orphan `npm exec …mcp` processes — clean up with `pkill -f 'codex exec'; pkill -f 'npm exec.*mcp'`. Prefer foreground with a bounded timeout for long runs, or background + a `Monitor`/completion push.
3. Load repo memory: `python3 scripts/memctl.py locate --repo . --cwd "$PWD" --json` then read the resolved `.ai/MEMORY.md`.
4. Read the repo's `.ai/orchestrate.toml` if present (deploy target, ci_gate, max_iter, sandbox). Absent → deploy is human-gated (never guess a deploy mechanism). See `references/auto-deploy-safety.md`.

## The loop

`scripts/orchestrate.sh` automates only **steps 2–4 (the Codex leg)** and then records a `handoff` state. **Steps 5–7 run in a Claude session** so review judgment, fix-loop routing, and deploy approval stay with the planner/reviewer. The driver baton records the exact implementation session ID for step 6.

### 1 — Plan (Claude / Fable)
Produce a concrete spec at `PLAN-<topic>.md` (or reuse a plan-mode plan). Establish continuity: `/continuity` → `.claude/continuity/<repo>--<topic>.md`. Record loop state in memctl: `orchestrate.<topic> = {step:1, branch:"", pr:"", iter:0}`.

### 2 — Critique the plan (Codex / gpt-5.6-sol)
```bash
codex exec -s read-only -o /tmp/orch-critique.md \
  "You are an elite engineer. Critique this plan for a change in $(pwd): risks, wrong assumptions, missing edge cases, simpler approaches, and anything that would make a reviewer reject the PR. Be specific and terse. Plan follows:\n\n$(cat PLAN-<topic>.md)" </dev/null
```
Read `/tmp/orch-critique.md`. **Hands-off:** fold in valid points, revise `PLAN-<topic>.md`, proceed. **Supervised:** show the critique + your revisions, wait.

### 3 — Execute (Codex / gpt-5.6-sol)
Create the task branch, then hand off:
```bash
git switch -c orch/<topic>
```
Write `HANDOFF-CODEX-<topic>.md` via `/handover` (mission = implement the plan on this branch, run checks, commit). Then:
```bash
codex exec -s workspace-write -c approval_policy=never -c model_reasoning_effort=medium -o /tmp/orch-impl.md \
  "Read HANDOFF-CODEX-<topic>.md and PLAN-<topic>.md. Implement on the current branch (orch/<topic>). Run the project's tests/lint/build until green. Then git commit with a clear message. For any gated action (install, push, network, tenant/live call, deploy) STOP and emit '⛔ APPROVAL-REQUEST: <action> — <why>' instead of doing it. Do NOT push or open a PR (the sandbox has no network)." </dev/null
```
Notes: `codex exec` uses `-c approval_policy=never` (there is **no `-a` flag** on `exec`), and `workspace-write` **blocks network** — so Codex commits locally and *you* (or the driver) do the push + PR. Reserve `--dangerously-bypass-approvals-and-sandbox` for throwaway worktrees only.

**Driver worktree exception:** linked-worktree git metadata lives in the main repo's `.git`, outside the Codex sandbox. With `ORCH_WORKTREE=1`, the driver therefore asks Codex to implement and verify without staging/committing, then the driver stages everything except `PLAN-*.md` and creates the commit outside the sandbox.

**Reasoning effort per step:** executing a well-spec'd plan is mechanical, so the implement (step 3) and fix (step 6) steps run gpt-5.6-sol at **`model_reasoning_effort=medium`** — faster and lighter on your ChatGPT plan. The **critique (step 2)** and **PR review (step 5)** are judgment work and keep the config's `xhigh` default. Override the exec effort via `exec_effort` in `.ai/orchestrate.toml` or the `ORCH_EXEC_EFFORT` env var (driver).

### 4 — Open the PR (Claude / driver)
Codex committed locally but has no network from the sandbox, so you push and open the PR:
```bash
git push -u origin orch/<topic>
gh pr create --base main --head orch/<topic> --fill   # or --title/--body
```
Capture the PR number into memctl (`pr:<n>`, `step:5`). (In an in-session run where you gave Codex `--dangerously-bypass-approvals-and-sandbox` in a worktree, Codex can open the PR itself — then just confirm with `gh pr view <n>`.)

### 5 — Review the PR (Claude / Fable)
```bash
gh pr diff <n> > /tmp/orch-pr.diff
```
Run `/code-review` on the diff (this is Claude's taste/judgment pass). Optionally add an independent lens: `codex review --base main`. Categorize findings blocking / notable / nit (reuse the `codex` skill's protocol). No blocking findings → go to step 7. Blocking findings → step 6.

### 6 — Apply review edits (Codex / gpt-5.6-sol)
Resume the **specific** implement session — Codex prints `session id: <uuid>` in step 3; capture it. Do not use the most-recent-session shorthand: with several Codex runs going at once (common), it can hijack a concurrent session and apply the fix to the wrong work.
```bash
codex exec resume <session-id-from-step-3> -c model_reasoning_effort=medium \
  "Address this PR review and run the relevant checks (do not push). If this session uses a linked worktree, do not stage or commit; end with a one-line commit summary for Claude/the driver. Otherwise commit the fixes. Review: <blocking + notable findings>" \
  </dev/null > /tmp/orch-fix.md
# Linked worktree only: Claude/the driver stages and commits outside the Codex sandbox here.
git push   # you/driver push the new commits to the PR
```
`codex exec resume` inherits the original session's cwd and sandbox. It accepts `-c` configuration overrides, but not fresh `-o`, `-s`, or `-C` flags; capture its final stdout with shell redirection as shown.
Increment `iter`. **Cap at max_iter (default 3):** if still blocking after the cap, stop and escalate to the human with the outstanding findings. Otherwise loop back to step 5.

### 7 — Deploy (risk-gated)
Classify with `/risk-assess` + the hard exclusion list in `references/auto-deploy-safety.md`. Auto-deploy ONLY if **all** hold: **`deploy_authorized = true`** is set by the user in `.ai/orchestrate.toml` (never self-authorize) **AND** risk = low **AND** `gh pr checks <n>` all green **AND** PR mergeable **AND** a deploy mechanism (`deploy_cmd`/`deploy_skill`/`deploy_via`) is configured. Then merge + run it (or the repo's deploy skill, e.g. `/azf-deploy`). Any condition fails, or change is risky, or the target isn't user-authorized → **stop, summarize, hand deploy to the user.** Update memctl `step:done`. (A production self-merge without `deploy_authorized` will also be blocked by the harness — as it should be.)

## Live status (dashboard)
Emit status so this run shows on the shared dashboard — **`orchestrate-dashboard`** (→ http://localhost:4600) is one page for every run on this machine, with **click-to-answer gates**. The `orchestrate.sh` driver emits automatically; when driving **in-session**, call the emitter at each step (no-op if not installed):
```bash
ID="$(basename "$PWD")-<topic>"
orchestrate-status start --id "$ID" --repo <repo> --topic <topic> --title "<title>" --branch orch/<topic>
orchestrate-status step  --id "$ID" --n <1-7> --state active|done      # at each step
orchestrate-status pr    --id "$ID" --number <n> --url <url>           # after step 4
orchestrate-status gate  --id "$ID" --question "Deploy?" --option "Merge & deploy:primary" --option "Leave PR open"
choice=$(orchestrate-status wait --id "$ID" --timeout 0)               # blocks until you click in the dashboard
orchestrate-status done  --id "$ID"
```
For a gated decision, emit `gate` then `wait` — you answer from the dashboard's **Needs you** section. See `dashboard/README.md`.

## Guardrails
- Branch-per-task; PR always; never direct-push or force-push `main`.
- Default sandbox `workspace-write` (not `danger-full-access`) unless in a disposable worktree.
- Checkpoint every step to memctl so a killed/switched session resumes at the right step (Codex runs on ChatGPT-plan limits — resume, don't restart).
- Hard-gate deploy for any change touching auth, secrets, migrations, deletion/force-push, public API, prod/CI config, IaC, or diff > ~300 lines.
- Never store secrets in handover/plan/critique files.

## Resuming
Read `orchestrate.<topic>` from memctl + the latest `HANDOFF-*.md`; jump to the recorded step. Works across a killed CLI session or a switch between Claude Desktop and Claude Code. For a Codex thread continuation resume the **specific** `session id` (not `--last`, which can hijack a concurrent Codex run).

## Output format
```
## Orchestrate: <topic>
- Mode: hands-off | supervised | dry-run
- Step reached: 1..7 / done
- Branch: orch/<topic>   PR: #<n> (<url>)
- Plan critique: folded N points
- Review: blocking=N notable=N nit=N   iterations: k/max
- Risk: low|medium|high   Deploy: auto-deployed | gated-for-user | n/a
- Next: <one line>
```

## Related skills & references
- `codex` — the Codex CLI wrapper (delegation + `codex review`)
- `handover` — cross-tool batons (`HANDOFF-CODEX-*.md`, `HANDOFF-CLAUDE-review-*.md`)
- `code-review`, `prepare-pr`, `verify`, `risk-assess`, `continuity`, `git-autopush`, `deploy-functions`/`azf-deploy`
- `references/auto-deploy-safety.md` — risk classifier + deploy gates
- `references/loop-mechanics.md` — hands-off vs supervised, resume, cost/runaway rails
- `references/desktop-mcp-bridge.md` — run this loop from Claude Desktop via `codex mcp-server`
