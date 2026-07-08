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
emit start --id "$RUN_ID" --repo "$(basename "$ORIG_ROOT")" --topic "$TOPIC" --title "$TOPIC" --branch "$BRANCH"
emit step --id "$RUN_ID" --n 1 --state done

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
  if ! git diff --quiet || ! git diff --cached --quiet; then
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
run "codex exec -s read-only -o '$CRIT' - < '$CPROMPT'" || die "critique step failed"
[[ "$DRY" == "1" ]] || echo "   critique -> $CRIT"

# --- step 3: branch + implement (sandboxed, NO network: commit only) ---------
emit step --id "$RUN_ID" --n 2 --state done
echo "-- [3/4] Codex implements on $BRANCH (sandbox=$SANDBOX, effort=$EXEC_EFFORT, no network)"
emit step --id "$RUN_ID" --n 3 --state active
[[ "$MADE_BRANCH" == "1" ]] || run "git switch -c '$BRANCH'"
BEFORE="$(git rev-parse HEAD 2>/dev/null || echo '')"
IMPL="$(mktemp -t orch-impl-XXXX).md"
IPROMPT="$(mktemp -t orch-iprompt-XXXX).md"
printf 'Implement the plan in %s on the current branch (%s). Consider the critique at %s. Run the project'"'"'s tests/lint/build until green. Then stage and git commit with a clear message. Do NOT push and do NOT open a PR — the sandbox has no network; the driver handles that. Summarize what you changed on the last line.\n' "$PLAN" "$BRANCH" "$CRIT" > "$IPROMPT"
run "codex exec -s '$SANDBOX' -c approval_policy=never -c model_reasoning_effort=$EXEC_EFFORT -o '$IMPL' - < '$IPROMPT'" || die "implement step failed"

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
