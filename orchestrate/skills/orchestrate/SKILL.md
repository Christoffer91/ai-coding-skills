---
name: orchestrate
description: "Run the Claude-plan/review and Codex-execute loop from plan to PR and an optional risk-gated deploy. Use for autonomous or supervised multi-step delivery, resuming an orchestrate run, or reviewing its handoff."
allowed-tools: Read, Glob, Grep, Edit, Write, Bash
---

# Orchestrate — dual-brain shipping loop

Claude plans and reviews; Codex critiques, implements, and applies review edits. The shell driver automates steps 2–4 and stops at a durable review handoff. Claude owns steps 5–7.

## Modes and gates

- Hands-off (default): continue through local work and stop only at a real approval or the review handoff.
- `--supervised`: gate plan, execution, review edits, and deploy.
- `--dry-run`: print commands and make no changes.
- Installs, network/live-tenant calls, migrations, first push/PR, secrets, and deploy always require the applicable approval.

### Temporary model overrides

The dashboard's **model overrides** panel (or `orchestrate-status overrides set|get|clear`) stores temporary, machine-wide runtime state in `~/.orchestrate/overrides.json`; every override has a TTL (default four hours, maximum 72 hours) and applies only when a new critique or implementation step begins. Overrides replace the selected role's prior entry, take precedence over configured/environment effort while active, and are visibly recorded on the run. `critique` may use a provider-specific Claude model with tools disabled and no Codex fallback; `implement` remains Codex-only. The driver currently has no distinct `fix` model invocation, so fixes are intentionally not overrideable yet. Treat this localhost control as trusted-local-user state, never as repository configuration.

For an in-session gate, call `PushNotification` once with an actionable sentence, then use `AskUserQuestion` for Approve/Reject/Edit. Remote Control is the phone path. The driver instead uses `ORCH_NOTIFY_CMD` (an executable path) or repo-local `notify_cmd` (a string path or argv array) from `.ai/orchestrate.toml`; the message is appended as one argument. It never uses a shell. macOS Notification Center is only a desktop fallback.

## Preconditions

1. Confirm repo/branch/WIP with `git status`; never direct-push or force-push the default branch.
2. Confirm `codex --version` and `gh auth status`.
3. Locate and read repo memory when `.ai/memory-map.json` exists. Use memctl only for durable project facts, never loop checkpoints.
4. Read `.ai/orchestrate.toml` if present. Absence means deploy is human-gated.
5. The loop state is `~/.orchestrate/runs/<id>.json`; implementation artifacts are under `~/.orchestrate/artifacts/<id>/`.
6. **Dashboard emitter — bootstrap, don't skip silently.** If `command -v orchestrate-status` fails but
   `~/.claude/skills/orchestrate/dashboard/orchestrate-status` exists, symlink BOTH scripts onto PATH now
   (`ln -sf ~/.claude/skills/orchestrate/dashboard/orchestrate-{status,dashboard} ~/.local/bin/`) and use
   the absolute path for this session if `~/.local/bin` isn't on PATH. The emitter's no-op-when-missing
   design is for machines WITHOUT the dashboard — on a machine that has it, running without emitting is a
   bug (the user watches localhost:4600 and sees nothing). If the dashboard dir doesn't exist either,
   say so once in the first status output instead of failing.

## Steps 1–4 — plan and execute

1. Write or validate `PLAN-<topic>.md` — **always spec-driven**, per `references/spec-template.md` (context, files in scope, numbered fixes with file paths, runnable acceptance, out-of-scope, commit subject). Planner: Fable 5 (medium) when available; otherwise draft with gpt-5.6-sol at ultra (read-only) and validate in-session before proceeding. No implementation without a complete spec. For unfamiliar or multi-area scope, fan out read-only Explore subagents for repo reconnaissance before writing the spec — the spec quality ceiling is the recon quality.
2. Critique it with Codex in `read-only`; fold valid findings into execution.
3. Implement on `orch/<topic>` in `workspace-write`, run tests/lint/build, and capture the exact Codex session ID. In a linked worktree Codex does not stage or commit; the driver does so after implementation. In normal mode verification may therefore follow Codex's local commit, but it always precedes push.
4. Before push, the driver scans the implementation result for `⛔ APPROVAL-REQUEST: <action> — <why>`. This marker blocks push/PR; in a non-worktree run Codex may already have committed locally. After any approval, the driver independently runs configured `test_cmd`, `build_cmd`, and `eval_cmd` commands. One failure resumes the exact Codex session for a single repair, then the driver reruns the full verify gate. The gate offers `Approve and continue` or `Reject and stop`. Timeout preserves `awaiting_approval`; resume from the recorded cwd without rerunning Codex:

```bash
scripts/orchestrate.sh --resume --timeout 0 <topic> PLAN-<topic>.md
```

On approval, push `orch/<topic>`, open/locate the PR, write `HANDOFF-CLAUDE-review-<topic>.md`, record its absolute path plus PR/session metadata in run JSON, notify once, and stop.

## Review entry — steps 5–7

Invoke `/orchestrate review <topic>` in the repo. From another cwd use `/orchestrate review <topic> --repo /absolute/repo/path`.

1. Resolve the repo root, then select the single run JSON whose topic matches and whose recorded repo/worktree belongs to that git common directory. If zero or multiple match, stop and request the exact run ID; topic alone must never guess across repos.
2. Require `status=handoff`, a PR number/URL, implementation session ID, review metadata, and a readable absolute baton path. Verify the baton topic/PR/branch agrees with run JSON and `gh pr view`; reject stale or mismatched metadata.
3. Set step 5 active and review `gh pr diff <n>` for correctness, taste, security, tests, and contract. Categorize blocking/notable/nit. For large diffs (>~500 lines or ≥3 REQUIRED coverage lenses), fan the review into parallel subagent lenses (correctness / security / tests) and synthesize into the single verdict — never ship parallel verdicts. At the end of each review pass, record integer outcome counts with `orchestrate-status metric --id <id> --key review.blocking --value N` and `--key review.notable --value N`.
4. With no blocking findings, continue to step 7. Otherwise increment `review.iteration` in run JSON and resume the exact implementation session:

```bash
codex exec resume <session-id> -c model_reasoning_effort=medium \
  "Address these findings and run relevant checks; do not push. <findings>" \
  </dev/null > /tmp/orch-fix.md
```

5. Commit linked-worktree edits outside the sandbox, push to the same PR, and repeat review. Stop and escalate after `maxIterations` (default 3).
6. For deploy, apply `/risk-assess` plus `references/auto-deploy-safety.md`. Merge/deploy only when user-set `deploy_authorized=true`, risk is low, CI is green, the PR is mergeable, and a deploy mechanism is configured. Otherwise hand deploy to the user.

## Live status

The driver emits automatically. For in-session runs:

```bash
ID="$(basename "$PWD")-<topic>"
orchestrate-status start --id "$ID" --repo <repo> --topic <topic> --title "<title>" --branch orch/<topic>
orchestrate-status step --id "$ID" --n <1-7> --state active|done
orchestrate-status pr --id "$ID" --number <n> --url <url>
orchestrate-status gate --id "$ID" --question "Deploy?" --option "Merge & deploy:primary" --option "Leave PR open"
choice=$(orchestrate-status wait --id "$ID" --timeout 0)
orchestrate-status done --id "$ID"
```

Also call `PushNotification` and `AskUserQuestion` for in-session gates; the localhost dashboard is optional desktop status, not the phone transport.

## Guardrails and output

- Default to `workspace-write`; use bypass mode only in a disposable worktree.
- Resume the recorded session ID, never a most-recent-session shortcut.
- Never store secrets in plans, batons, run JSON, notifier configuration, or output.
- Report mode, step reached, branch/PR, critique changes, recorded blocking/notable review counts and iteration, risk/deploy state, and one concrete next action.

References: `references/auto-deploy-safety.md`, `references/loop-mechanics.md`, `references/desktop-mcp-bridge.md`, and `dashboard/README.md`.
