---
name: orchestrate
description: "Run the dual-brain plan→execute→review→ship loop end-to-end: Claude plans and reviews the PR, OpenAI Codex CLI (gpt-5.5) critiques the plan, writes the code, opens the PR, and applies review edits. Use to take a well-spec'd change from idea to merged/deployed. Default hands-off; pass --supervised to gate each step. Not for trivial one-file edits (just do it) or plan-only work. Keywords: orchestrate, ship it, dual-brain, plan execute review loop, autonomous PR, hand to codex, relay."
allowed-tools: Read, Glob, Grep, Edit, Write, Bash
---

# Orchestrate — dual-brain shipping loop

## Purpose
Drive a change from plan to (optionally) deployed across two models:
**Claude** (a strong planning/reviewing model, e.g. Opus) plans the change and reviews the PR — the taste/judgment half; **OpenAI Codex CLI** (`gpt-5.5`) critiques the plan, writes the code, opens the PR, and applies review edits — the execution half. The idea: keep expensive judgment work on Claude, hand mechanical, well-spec'd execution to Codex (which runs on your ChatGPT/Codex subscription).

This skill is the conductor — it drives the loop with plain `codex` / `gh` / `git` commands, inlined below so it depends on nothing but those CLIs. If you *also* have review/handover/risk skills, use them at the matching steps (see "Optional enhancements").

## Requirements (check once)
1. In a git repo with a remote and a clean-enough tree (`git rev-parse --show-toplevel`).
2. `codex --version` OK and logged in (`codex login`) → provides `gpt-5.5`. If missing, tell the user to install/log in and stop.
3. `gh auth status` OK with `repo` + `workflow` scopes.
4. Optional per-repo config `.ai/orchestrate.toml` (deploy target, effort, caps) — see `references/auto-deploy-safety.md`. Absent → deploy is human-gated.

## Modes
- **Hands-off (default):** run steps 2–6 without stopping; step 7 auto-deploys only if the repo is explicitly authorized (below), else stops for the human.
- **`--supervised`:** pause for the user at each handoff. Use for ambiguous, security-sensitive, or first-run-in-a-repo work.
- **`--dry-run`:** print the `codex`/`gh`/`git` commands the loop would run; execute nothing.

## The loop

### 1 — Plan (Claude)
Produce a concrete spec at `PLAN-<topic>.md`. Track loop state (step, branch, PR#, iteration) however you track long tasks — at minimum, the `HANDOFF-*.md` files + branch + PR are the durable state.

### 2 — Critique the plan (Codex / gpt-5.5)
```bash
codex exec -s read-only -o /tmp/orch-critique.md \
  "You are an elite engineer. Critique this plan for a change in $(pwd): risks, wrong assumptions, missing edge cases, simpler approaches, and anything that would make a reviewer reject the PR. Be specific and terse. Plan:\n\n$(cat PLAN-<topic>.md)"
```
Read it. Hands-off: fold in valid points, revise the plan, proceed. Supervised: show critique + revisions, wait.

### 3 — Implement (Codex / gpt-5.5)
Create the task branch, write a handoff (format below), then implement:
```bash
git switch -c orch/<topic>
codex exec -s workspace-write -c approval_policy=never -c model_reasoning_effort=medium -o /tmp/orch-impl.md \
  "Read HANDOFF-CODEX-<topic>.md and PLAN-<topic>.md. Implement on the current branch (orch/<topic>). Run the project's tests/lint/build until green. Then git commit with a clear message. Do NOT push or open a PR (the sandbox has no network)."
```
Notes: `codex exec` has **no `-a` flag** — set approvals via `-c approval_policy=never`. `workspace-write` **blocks network**, so Codex commits locally and *you/the driver* push + PR. Execution is mechanical → `medium` effort; keep critique/review at the config default (`xhigh`). Reserve `--dangerously-bypass-approvals-and-sandbox` for throwaway worktrees only.

### 4 — Open the PR (Claude / driver)
```bash
git push -u origin orch/<topic>
gh pr create --base main --head orch/<topic> --fill   # or --title/--body
```

### 5 — Review the PR (Claude)
```bash
gh pr diff <n> > /tmp/orch-pr.diff
```
Review the diff for correctness, security, contract, and taste — this is Claude's judgment pass. Optional independent lens: `codex review --base main`. Categorize findings blocking / notable / nit. No blocking → step 7. Blocking → step 6.

### 6 — Apply review edits (Codex / gpt-5.5)
```bash
codex exec resume --last -c model_reasoning_effort=medium -o /tmp/orch-fix.md \
  "Address this PR review and git commit the fixes on this branch (do not push). Review:\n<blocking + notable findings>"
git push   # push the new commits to the PR
```
Increment the iteration count. **Cap at `max_iter` (default 3):** if still blocking after the cap, stop and escalate to the human. Otherwise loop back to step 5.

### 7 — Deploy (risk-gated)
See `references/auto-deploy-safety.md`. Auto-deploy ONLY if **all** hold: the repo is human-authorized (`deploy_authorized = true` in `.ai/orchestrate.toml`, set by a person — never self-authorize) **AND** risk = low **AND** CI green (`gh pr checks <n>`) **AND** PR mergeable **AND** a deploy mechanism is configured. Otherwise **stop, summarize, hand deploy to the user.**

## Handoff file format (carries state across tools/sessions)
`HANDOFF-CODEX-<topic>.md` (Claude → Codex, execution):
```md
# Handoff for Codex
## Mission
- Implement PLAN-<topic>.md on branch orch/<topic>; run checks; commit locally.
## Read First
- PLAN-<topic>.md, plus 3–8 high-signal files
## Constraints / Definition of Done
- Tests/lint/build green; scope limited to the plan; no unrelated changes.
```
`HANDOFF-CLAUDE-review-<topic>.md` (Codex → Claude, PR review):
```md
# Handoff for Claude — review PR #<n>
## Mission
- Review PR #<n> (<url>) on branch orch/<topic>. Lens: correctness, taste, security, contract.
## Read First
- `gh pr diff <n>`; 2–5 highest-signal changed files
## Definition of Done
- Post review (blocking/notable/nit). Blocking → hand back to Codex. Clean + low-risk + CI green → deploy gate.
```

## Guardrails
- Branch-per-task; PR always; never direct-push or force-push `main`.
- Default sandbox `workspace-write` (not `danger-full-access`) unless in a disposable worktree.
- Hard-gate deploy for any change touching auth, secrets, migrations, deletion/force-push, public API, prod/CI config, IaC, or diff > ~300 lines.
- Never put secrets in handoff/plan/critique files.
- Cap the review↔fix loop; `--dry-run` before trusting it on a new repo.

## Reasoning effort
Critique (step 2) and PR review (step 5) run at the config default (`xhigh`, judgment work). The mechanical implement (step 3) and fix (step 6) steps run at `medium` — faster and lighter. Override via `exec_effort` in `.ai/orchestrate.toml` or `ORCH_EXEC_EFFORT` for the driver.

## Optional enhancements
If you have your own skills, slot them in: a code-review skill at step 5, a risk-assessment skill at step 7, a handover skill for the batons, a continuity/memory system to checkpoint loop state. The loop works without them.

## References
- `references/auto-deploy-safety.md` — deploy gates, risk classifier, `.ai/orchestrate.toml` schema.
- `references/loop-mechanics.md` — Codex CLI flags, resume, effort, runaway/cost rails.
- `references/desktop-mcp-bridge.md` — drive the loop from Claude Desktop via `codex mcp-server`.
