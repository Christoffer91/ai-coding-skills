#!/usr/bin/env bash
# orchestrate.sh — headless "Codex execution leg" of the dual-brain loop.
#
# Automates steps 2–4 of the /orchestrate skill (skills/orchestrate/SKILL.md):
# plan-critique -> branch -> implement -> open PR. It then STOPS and hands the
# PR to Claude for review. It deliberately does NOT do PR review, apply-edits,
# or deploy:
#   - PR review is Claude's job (Codex reviewing its own work is worthless).
#   - Auto-deploy needs the risk classifier, a Claude-in-the-loop capability,
#     not a dumb bash loop.
# Resume the review/fix/ship leg from a Claude session:  /orchestrate <topic>
#
# Requirements: codex (logged in), gh (authed: repo+workflow), git, a remote.
#
# Usage:  scripts/orchestrate.sh <topic> [path/to/PLAN.md]
#   <topic>     kebab-case task name (branch = orch/<topic>)
#   PLAN.md     plan/spec file (default: PLAN-<topic>.md)
#
# Env:
#   ORCH_SANDBOX      codex exec sandbox for implement step (default workspace-write)
#   ORCH_EXEC_EFFORT  reasoning effort for the mechanical implement step
#                     (default medium; the critique step keeps the config's default)
#   ORCH_DRYRUN=1     print the codex/gh/git commands, execute nothing
set -euo pipefail

TOPIC="${1:?usage: orchestrate.sh <topic> [PLAN.md]}"
PLAN="${2:-PLAN-${TOPIC}.md}"
BRANCH="orch/${TOPIC}"
SANDBOX="${ORCH_SANDBOX:-workspace-write}"
EXEC_EFFORT="${ORCH_EXEC_EFFORT:-medium}"
DRY="${ORCH_DRYRUN:-0}"

run() { if [[ "$DRY" == "1" ]]; then echo "+ $*"; else eval "$@"; fi; }
die() { echo "orchestrate: $*" >&2; exit 1; }

# --- preconditions -----------------------------------------------------------
command -v codex >/dev/null || die "codex CLI not found"
command -v gh    >/dev/null || die "gh CLI not found"
git rev-parse --show-toplevel >/dev/null 2>&1 || die "not in a git repo"
gh auth status >/dev/null 2>&1 || die "gh not authenticated (gh auth login)"
[[ -f "$PLAN" ]] || die "plan file not found: $PLAN"
if ! git diff --quiet || ! git diff --cached --quiet; then
  die "working tree dirty — commit/stash first (loop needs a clean base)"
fi

echo "== orchestrate: $TOPIC =="
echo "   plan=$PLAN  branch=$BRANCH  sandbox=$SANDBOX  exec_effort=$EXEC_EFFORT  dry-run=$DRY"

# --- step 2: critique the plan (read-only, config default effort) -------------
# The critique is judgment work, so it keeps the config's default effort (no override).
echo "-- [2/4] Codex critiques the plan (read-only)"
CRIT="$(mktemp -t orch-critique-XXXX).md"
run "codex exec -s read-only -o '$CRIT' \
  \"You are an elite engineer. Critique this plan for a change in \$(pwd): risks, wrong assumptions, missing edge cases, simpler approaches, and anything that would make a reviewer reject the PR. Be specific and terse. Plan follows:\n\n\$(cat '$PLAN')\"" \
  || die "critique step failed"
[[ "$DRY" == "1" ]] || { echo "   critique -> $CRIT"; }

# --- step 3: branch + implement (sandboxed, NO network: commit only) ---------
# codex exec has -s/--sandbox and --dangerously-bypass-approvals-and-sandbox but
# NO -a flag; approvals are set via `-c approval_policy=never`. workspace-write
# also BLOCKS network, so Codex commits locally and the driver does push+PR.
# Executing a well-spec'd plan is mechanical, so we run at $EXEC_EFFORT (default
# medium) rather than the config's higher default — faster and lighter.
echo "-- [3/4] Codex implements on $BRANCH (sandbox=$SANDBOX, effort=$EXEC_EFFORT, no network)"
run "git switch -c '$BRANCH'"
IMPL="$(mktemp -t orch-impl-XXXX).md"
run "codex exec -s '$SANDBOX' -c approval_policy=never -c model_reasoning_effort=$EXEC_EFFORT -o '$IMPL' \
  \"Implement the plan in '$PLAN' on the current branch ($BRANCH). Consider the critique at '$CRIT'. Run the project's tests/lint/build until green. Then stage and 'git commit' with a clear message. Do NOT push and do NOT open a PR — the sandbox has no network; the driver handles that. Summarize what you changed on the last line.\"" \
  || die "implement step failed"

# --- step 4: push branch + open PR (driver, outside sandbox = has network) ----
echo "-- [4/4] push branch + open PR"
if [[ "$DRY" == "1" ]]; then
  echo "+ git push -u origin '$BRANCH'  &&  gh pr create --base main --head '$BRANCH' --fill"
  exit 0
fi
AHEAD="$(git rev-list --count "main..$BRANCH" 2>/dev/null || echo 0)"
[[ "$AHEAD" -ge 1 ]] || die "Codex committed nothing on $BRANCH (see $IMPL) — aborting."
run "git push -u origin '$BRANCH'" || die "git push failed"
gh pr view "$BRANCH" >/dev/null 2>&1 || gh pr create --base main --head "$BRANCH" --fill >/dev/null || die "gh pr create failed"
PR_NUM="$(gh pr view "$BRANCH" --json number -q .number)"
PR_URL="$(gh pr view "$BRANCH" --json url -q .url)"

# --- hand review back to Claude ---------------------------------------------
BATON="HANDOFF-CLAUDE-review-${TOPIC}.md"
cat > "$BATON" <<EOF
# Handoff for Claude — review PR #${PR_NUM}

## Mission
- Review PR #${PR_NUM} (${PR_URL}) on branch ${BRANCH}. Lens: correctness, taste, security, contract.

## Read First
- \`gh pr diff ${PR_NUM}\`
- Codex critique: ${CRIT}
- Codex implementation notes: ${IMPL}

## Definition of Done
- Post review (blocking/notable/nit). Blocking -> hand back to Codex to fix.
  Clean + low-risk + CI green -> deploy gate.
EOF

echo
echo "== Codex leg done. PR #${PR_NUM} ready for Claude review."
echo "   Baton: ${BATON}"
echo "   Resume the review/fix/ship leg in a Claude session:  /orchestrate ${TOPIC}"
