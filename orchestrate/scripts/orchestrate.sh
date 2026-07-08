#!/usr/bin/env bash
# orchestrate.sh — headless "Codex execution leg" of the dual-brain loop.
#
# Automates steps 2–4 of the /orchestrate loop (see
# skills/orchestrate/SKILL.md): plan-critique -> branch ->
# implement -> open PR. It then STOPS and hands the PR to Claude for
# review. It does NOT do PR review, apply-edits, or deploy.
#
# RELIABILITY — always EOF codex's stdin. `codex exec` reads stdin even when the
# prompt is a positional arg (to append a <stdin> block); in a backgrounded /
# piped launch stdin is an open pipe that never EOFs, so codex blocks FOREVER on
# "Reading additional input from stdin...". We therefore feed every prompt via
# `codex exec [flags] - < promptfile` (prompt read from stdin; file redirect
# EOFs it). Never use the bare `codex exec "<prompt>"` arg form here.
#
# Requirements: codex (logged in), gh (authed: repo+workflow), git, a remote.
#
# Usage:  scripts/orchestrate.sh <topic> [path/to/PLAN.md]
#
# Env:
#   ORCH_SANDBOX      codex exec sandbox for implement (default workspace-write)
#   ORCH_EXEC_EFFORT  reasoning effort for implement (default medium; critique keeps config default)
#   ORCH_WORKTREE=1   run in a fresh worktree off origin/<default-branch> (for dirty/behind repos)
#   ORCH_STALL_KILL   secs of NO Codex output before a step is treated as hung + killed (default 90)
#   ORCH_MAX_RETRY    auto-recovery retries of a hung step before escalating to a human (default 2)
#   ORCH_TITLE        dashboard card title — set to match your Claude chat name (default: <topic>)
#   ORCH_DRYRUN=1     print the codex/gh/git commands, execute nothing
set -euo pipefail

TOPIC="${1:?usage: orchestrate.sh <topic> [PLAN.md]}"
PLAN="${2:-PLAN-${TOPIC}.md}"
BRANCH="orch/${TOPIC}"
SANDBOX="${ORCH_SANDBOX:-workspace-write}"
EXEC_EFFORT="${ORCH_EXEC_EFFORT:-medium}"
WORKTREE="${ORCH_WORKTREE:-0}"
DRY="${ORCH_DRYRUN:-0}"

run() { if [[ "$DRY" == "1" ]]; then echo "+ $*"; else eval "$@"; fi; }
die() { echo "orchestrate: $*" >&2; exit 1; }

# --- preconditions -----------------------------------------------------------
command -v codex >/dev/null || die "codex CLI not found"
command -v gh    >/dev/null || die "gh CLI not found"
git rev-parse --show-toplevel >/dev/null 2>&1 || die "not in a git repo"
gh auth status >/dev/null 2>&1 || die "gh not authenticated (gh auth login)"
[[ -f "$PLAN" ]] || die "plan file not found: $PLAN"
PLAN_ABS="$(cd "$(dirname "$PLAN")" && pwd)/$(basename "$PLAN")"
ORIG_ROOT="$(git rev-parse --show-toplevel)"

# --- optional live status for the dashboard (no-ops if orchestrate-status absent) ---
RUN_ID="$(basename "$ORIG_ROOT")-$TOPIC"
STATUS_BIN="$(command -v orchestrate-status 2>/dev/null || true)"
if [[ -z "$STATUS_BIN" ]]; then
  for c in "$(dirname "$0")/../dashboard/orchestrate-status" \
           "$(dirname "$0")/../skills/claude/skills/orchestrate/dashboard/orchestrate-status" \
           "$HOME/.claude/skills/orchestrate/dashboard/orchestrate-status"; do
    [[ -x "$c" ]] && { STATUS_BIN="$c"; break; }
  done
fi
emit(){ [[ -n "${STATUS_BIN:-}" ]] && "$STATUS_BIN" "$@" >/dev/null 2>&1 || true; }
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
emit start --id "$RUN_ID" --repo "$(basename "$ORIG_ROOT")" --topic "$TOPIC" --title "${ORCH_TITLE:-$TOPIC}" --branch "$BRANCH" --pid $$ --cwd "$ORIG_ROOT" --driver "$SELF"
emit step --id "$RUN_ID" --n 1 --state done

# --- run a Codex step with auto-recovery: kill a hung Codex + retry (capped) ---
# Keeps runs on track without you: if Codex produces NO output for ORCH_STALL_KILL
# seconds (default 90) it's treated as hung -> killed precisely -> the step is
# retried, up to ORCH_MAX_RETRY (default 2), then escalated to a human. Never
# touches gates or deploy. Heartbeats the dashboard while output is flowing.
codex_run(){  # <prompt-file> <out-file> <sandbox> <effort|""> <step-n|"">
  local pf="$1" of="$2" sb="$3" eff="$4" sn="$5"
  local effflag=""; [[ -n "$eff" ]] && effflag="-c model_reasoning_effort=$eff"
  if [[ "$DRY" == "1" ]]; then echo "+ codex exec -s $sb -c approval_policy=never $effflag -o $of - < $pf   (+stall-kill/retry)"; return 0; fi
  local attempt=1 max="${ORCH_MAX_RETRY:-2}" kill_after="${ORCH_STALL_KILL:-90}"
  while :; do
    local log; log="$(mktemp -t orch-clog-XXXX).log"
    codex exec -s "$sb" -c approval_policy=never $effflag -o "$of" - < "$pf" >"$log" 2>&1 &
    local cpid=$! last_sz=-1 idle=0 hung=0
    while kill -0 "$cpid" 2>/dev/null; do
      sleep 10
      local sz; sz=$(wc -c <"$log" 2>/dev/null || echo 0)
      if [[ "$sz" != "$last_sz" ]]; then last_sz="$sz"; idle=0; emit heartbeat --id "$RUN_ID" --pid $$
      else idle=$((idle+10)); fi
      if (( idle >= kill_after )); then hung=1; kill -9 "$cpid" 2>/dev/null; pkill -9 -P "$cpid" 2>/dev/null; wait "$cpid" 2>/dev/null; break; fi
    done
    if [[ "$hung" == "0" ]]; then wait "$cpid"; return $?; fi
    if (( attempt > max )); then
      [[ -n "$sn" ]] && emit step --id "$RUN_ID" --n "$sn" --state fail --note "Codex hung ${kill_after}s; $max retries exhausted — escalating"
      echo "  Codex hung repeatedly (log: $log) — escalating to human" >&2; return 124
    fi
    [[ -n "$sn" ]] && emit step --id "$RUN_ID" --n "$sn" --state active --note "Codex hung — auto-recovered (retry $attempt/$max)"
    echo "  Codex: no output for ${kill_after}s — killed + retrying ($attempt/$max)" >&2
    attempt=$((attempt+1))
  done
}

# --- detect the repo's default branch (don't assume main) --------------------
git fetch origin -q 2>/dev/null || true
BASE="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@')"
[[ -z "$BASE" ]] && BASE="$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null || true)"
[[ -z "$BASE" ]] && BASE="main"

# --- isolate: worktree mode, or require a clean tree -------------------------
if [[ "$WORKTREE" == "1" ]]; then
  WT="$(mktemp -d -t orch-wt-XXXX)"
  run "git worktree add -q -b '$BRANCH' '$WT' 'origin/$BASE'" || die "worktree add failed"
  cp "$PLAN_ABS" "$WT/$(basename "$PLAN")" 2>/dev/null || true
  cd "$WT"
  PLAN="$(basename "$PLAN")"
  MADE_BRANCH=1
else
  if [[ "${ORCH_RESTART:-0}" != "1" ]] && { ! git diff --quiet || ! git diff --cached --quiet; }; then
    die "working tree dirty — commit/stash first, or set ORCH_WORKTREE=1 to run in a clean worktree off origin/$BASE"
  fi
  MADE_BRANCH=0
fi

echo "== orchestrate: $TOPIC =="
echo "   plan=$PLAN  branch=$BRANCH  base=$BASE  sandbox=$SANDBOX  effort=$EXEC_EFFORT  worktree=$WORKTREE  dry-run=$DRY"

# --- step 2: critique the plan (read-only, config default effort) -------------
echo "-- [2/4] Codex critiques the plan (read-only)"
emit step --id "$RUN_ID" --n 2 --state active
CRIT="$(mktemp -t orch-critique-XXXX).md"
CPROMPT="$(mktemp -t orch-cprompt-XXXX).md"
{ printf 'You are an elite engineer. Critique this plan for a change in %s: risks, wrong assumptions, missing edge cases, simpler approaches, and anything that would make a reviewer reject the PR. Be specific and terse. Plan follows:\n\n' "$(pwd)"
  cat "$PLAN"; } > "$CPROMPT"
codex_run "$CPROMPT" "$CRIT" "read-only" "" 2 || die "critique step failed (see log above)"
[[ "$DRY" == "1" ]] || echo "   critique -> $CRIT"

# --- step 3: branch + implement (sandboxed, NO network: commit only) ---------
emit step --id "$RUN_ID" --n 2 --state done
echo "-- [3/4] Codex implements on $BRANCH (sandbox=$SANDBOX, effort=$EXEC_EFFORT, no network)"
emit step --id "$RUN_ID" --n 3 --state active
if [[ "$MADE_BRANCH" != "1" ]]; then
  if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    run "git switch '$BRANCH'"; [[ "${ORCH_RESTART:-0}" == "1" ]] && run "git reset --hard -q"   # restart: reuse branch, discard partial work
  else run "git switch -c '$BRANCH'"; fi
fi
BEFORE="$(git rev-parse HEAD 2>/dev/null || echo '')"
IMPL="$(mktemp -t orch-impl-XXXX).md"
IPROMPT="$(mktemp -t orch-iprompt-XXXX).md"
printf 'Implement the plan in %s on the current branch (%s). Consider the critique at %s. Run the project'"'"'s tests/lint/build until green. Then stage and git commit with a clear message. Do NOT push and do NOT open a PR — the sandbox has no network; the driver handles that. Summarize what you changed on the last line.\n' "$PLAN" "$BRANCH" "$CRIT" > "$IPROMPT"
codex_run "$IPROMPT" "$IMPL" "$SANDBOX" "$EXEC_EFFORT" 3 || die "implement step failed"

# --- step 4: push branch + open PR (driver, outside sandbox = has network) ----
emit step --id "$RUN_ID" --n 3 --state done
echo "-- [4/4] push branch + open PR (base: $BASE)"
emit step --id "$RUN_ID" --n 4 --state active
if [[ "$DRY" == "1" ]]; then
  echo "+ git push -u origin '$BRANCH'  &&  gh pr create --base '$BASE' --head '$BRANCH' --fill"
  exit 0
fi
AHEAD="$(git rev-list --count "${BEFORE:+$BEFORE..}HEAD" 2>/dev/null || echo 0)"
[[ "$AHEAD" -ge 1 ]] || die "Codex committed nothing on $BRANCH (see $IMPL) — aborting."
run "git push -u origin '$BRANCH'" || die "git push failed"
gh pr view "$BRANCH" >/dev/null 2>&1 || gh pr create --base "$BASE" --head "$BRANCH" --fill >/dev/null || die "gh pr create failed"
PR_NUM="$(gh pr view "$BRANCH" --json number -q .number)"
PR_URL="$(gh pr view "$BRANCH" --json url -q .url)"
emit pr --id "$RUN_ID" --number "$PR_NUM" --url "$PR_URL"
emit step --id "$RUN_ID" --n 4 --state done
emit step --id "$RUN_ID" --n 5 --state active

# --- hand review back to Claude (baton written in the original repo) -----
BATON="$ORIG_ROOT/HANDOFF-CLAUDE-review-${TOPIC}.md"
cat > "$BATON" <<EOF
# Handoff for Claude — review PR #${PR_NUM}

## Mission
- Review PR #${PR_NUM} (${PR_URL}) on branch ${BRANCH} (base ${BASE}). Lens: correctness, taste, security, contract.

## Read First
- \`gh pr diff ${PR_NUM}\`
- Codex critique: ${CRIT}
- Codex implementation notes: ${IMPL}
$([[ "$WORKTREE" == "1" ]] && echo "- Worktree with the changes: $(pwd)  (git worktree remove it when done)")

## Definition of Done
- Post review (blocking/notable/nit). Blocking -> hand back to Codex to fix.
  Clean + low-risk + CI green -> deploy gate.
EOF

echo
echo "== Codex leg done. PR #${PR_NUM} ready for Claude review."
echo "   Baton: ${BATON}"
[[ "$WORKTREE" == "1" ]] && echo "   Worktree: $(pwd)  (remove with: git worktree remove '$(pwd)')"
echo "   Resume the review/fix/ship leg in a Claude session:  /orchestrate ${TOPIC}"
